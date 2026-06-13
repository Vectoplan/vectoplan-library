# services/vectoplan-library/src/vplib/planning/variant_planner.py
"""
Variant planner for the VPLIB package engine.

Diese Datei plant die Variantenstruktur eines modularen VPLIB-Packages.

Rolle dieser Datei:

    CreateRequest
    + ObjectKindProfile
    -> VariantPlanningResult
    -> VariantSet
    -> variants/index.json
    -> variants/default.json
    -> variants/<variant_id>.json

Wichtig:
Eine Variante ist keine vollständige neue Family. Eine Variante enthält nur
Overrides gegenüber der Family-/Default-Struktur.

Diese Datei schreibt keine Dateien. Sie plant nur Varianten.

Technische Namen, JSON-Keys und Variablen bleiben Englisch.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from functools import lru_cache
from typing import Any, Final, Iterable, Mapping


VARIANT_PLANNER_SCHEMA_VERSION: Final[str] = "vplib.variant_planner.v1"


class VariantPlannerError(ValueError):
    """Wird ausgelöst, wenn Varianten nicht geplant werden können."""


class VariantPlanningSource(str, Enum):
    """Quelle einer Variantenentscheidung."""

    REQUEST = "request"
    PROFILE_DEFAULTS = "profile_defaults"
    SYSTEM_DEFAULT = "system_default"
    NORMALIZATION = "normalization"

    @property
    def key(self) -> str:
        return str(self.value)


class VariantPlanningAction(str, Enum):
    """Aktion einer Variantenentscheidung."""

    CREATE_DEFAULT = "create_default"
    CREATE_VARIANT = "create_variant"
    NORMALIZE_VARIANT = "normalize_variant"
    PROMOTE_TO_MULTIPLE = "promote_to_multiple"
    REJECT_VARIANT = "reject_variant"

    @property
    def key(self) -> str:
        return str(self.value)


@dataclass(frozen=True, slots=True)
class VariantPlanningOptions:
    """Optionen für die Variantenplanung."""

    default_variant_id: str | None = None
    mode: str | None = None
    allow_multiple_variants: bool = True
    enforce_overrides_only: bool = True
    strict: bool = True

    def normalized(self) -> "VariantPlanningOptions":
        default_variant_id = (
            normalize_variant_id_safe(self.default_variant_id)
            if self.default_variant_id
            else None
        )
        mode = normalize_variant_mode_safe(self.mode) if self.mode else None

        return VariantPlanningOptions(
            default_variant_id=default_variant_id,
            mode=mode,
            allow_multiple_variants=bool(self.allow_multiple_variants),
            enforce_overrides_only=bool(self.enforce_overrides_only),
            strict=bool(self.strict),
        )

    def to_dict(self) -> dict[str, Any]:
        normalized = self.normalized()

        return {
            "default_variant_id": normalized.default_variant_id,
            "mode": normalized.mode,
            "allow_multiple_variants": normalized.allow_multiple_variants,
            "enforce_overrides_only": normalized.enforce_overrides_only,
            "strict": normalized.strict,
        }


@dataclass(frozen=True, slots=True)
class VariantPlanningDecision:
    """Einzelne Variantenentscheidung."""

    action: str
    source: str
    variant_id: str | None = None
    message: str = ""
    metadata: Mapping[str, Any] = field(default_factory=dict)

    def normalized(self) -> "VariantPlanningDecision":
        action = parse_variant_planning_action_value(self.action)
        source = parse_variant_planning_source_value(self.source)
        variant_id = (
            normalize_variant_id_safe(self.variant_id)
            if self.variant_id is not None
            else None
        )
        message = clean_optional_string(self.message) or ""
        metadata = normalize_metadata(self.metadata)

        return VariantPlanningDecision(
            action=action,
            source=source,
            variant_id=variant_id,
            message=message,
            metadata=metadata,
        )

    def to_dict(self) -> dict[str, Any]:
        normalized = self.normalized()

        return {
            "action": normalized.action,
            "source": normalized.source,
            "variant_id": normalized.variant_id,
            "message": normalized.message,
            "metadata": dict(normalized.metadata),
        }


@dataclass(frozen=True, slots=True)
class VariantPlanningResult:
    """Ergebnis der Variantenplanung."""

    variant_set: Any
    decisions: tuple[VariantPlanningDecision, ...] = field(default_factory=tuple)
    options: VariantPlanningOptions = field(default_factory=VariantPlanningOptions)
    object_kind: str | None = None
    profile_key: str | None = None
    schema_version: str = VARIANT_PLANNER_SCHEMA_VERSION
    metadata: Mapping[str, Any] = field(default_factory=dict)

    def normalized(self) -> "VariantPlanningResult":
        variant_set = normalize_variant_set(self.variant_set)
        decisions = tuple(decision.normalized() for decision in self.decisions or ())
        options = self.options.normalized()
        object_kind = normalize_optional_object_kind(self.object_kind)
        profile_key = clean_optional_string(self.profile_key)
        metadata = normalize_metadata(self.metadata)

        return VariantPlanningResult(
            variant_set=variant_set,
            decisions=decisions,
            options=options,
            object_kind=object_kind,
            profile_key=profile_key,
            schema_version=self.schema_version or VARIANT_PLANNER_SCHEMA_VERSION,
            metadata=metadata,
        )

    @property
    def variant_ids(self) -> tuple[str, ...]:
        return tuple(self.normalized().variant_set.variant_ids)

    @property
    def default_variant_id(self) -> str:
        return str(self.normalized().variant_set.default_variant_id)

    @property
    def mode(self) -> str:
        return str(self.normalized().variant_set.mode)

    def to_dict(self) -> dict[str, Any]:
        normalized = self.normalized()

        return {
            "schema_version": normalized.schema_version,
            "object_kind": normalized.object_kind,
            "profile_key": normalized.profile_key,
            "mode": normalized.mode,
            "default_variant_id": normalized.default_variant_id,
            "variant_ids": list(normalized.variant_ids),
            "variant_set": normalized.variant_set.to_dict(),
            "decisions": [decision.to_dict() for decision in normalized.decisions],
            "options": normalized.options.to_dict(),
            "metadata": dict(normalized.metadata),
        }


def plan_variants_for_request(
    *,
    request: Any,
    profile: Any | None = None,
    options: VariantPlanningOptions | Mapping[str, Any] | None = None,
    metadata: Mapping[str, Any] | None = None,
) -> VariantPlanningResult:
    """
    Plant Varianten für einen CreateRequest.

    Dies ist der bevorzugte Einstieg für spätere Creator und Document-Builder.
    """
    try:
        normalized_request = normalize_create_request(request)
        normalized_profile = normalize_profile(profile) if profile is not None else None
        normalized_options = normalize_options(options, request=normalized_request, profile=normalized_profile)

        decisions = collect_variant_decisions(
            request=normalized_request,
            profile=normalized_profile,
            options=normalized_options,
        )

        variant_set = build_variant_set_from_decisions(
            request=normalized_request,
            profile=normalized_profile,
            decisions=decisions,
            options=normalized_options,
        )

        return VariantPlanningResult(
            variant_set=variant_set,
            decisions=decisions,
            options=normalized_options,
            object_kind=normalized_request.object_kind,
            profile_key=getattr(normalized_profile, "profile_key", None),
            metadata={
                "planned_by": "variant_planner",
                **dict(metadata or {}),
            },
        ).normalized()
    except VariantPlannerError:
        raise
    except Exception as exc:
        raise VariantPlannerError(f"Could not plan variants for request: {exc}") from exc


def plan_variants_for_profile(
    *,
    profile: Any,
    options: VariantPlanningOptions | Mapping[str, Any] | None = None,
    metadata: Mapping[str, Any] | None = None,
) -> VariantPlanningResult:
    """Plant eine Default-Variantenstruktur nur aus einem Profil."""
    try:
        normalized_profile = normalize_profile(profile)
        normalized_options = normalize_options(options, profile=normalized_profile)

        decisions = (
            VariantPlanningDecision(
                action=VariantPlanningAction.CREATE_DEFAULT.value,
                source=VariantPlanningSource.PROFILE_DEFAULTS.value,
                variant_id=normalized_options.default_variant_id
                or normalized_profile.defaults.default_variant_id,
                message="Default variant planned from profile defaults.",
                metadata={
                    "profile_key": normalized_profile.profile_key,
                },
            ).normalized(),
        )

        variant_set = build_variant_set_from_decisions(
            request=None,
            profile=normalized_profile,
            decisions=decisions,
            options=normalized_options,
        )

        return VariantPlanningResult(
            variant_set=variant_set,
            decisions=decisions,
            options=normalized_options,
            object_kind=normalized_profile.object_kind,
            profile_key=normalized_profile.profile_key,
            metadata={
                "planned_by": "variant_planner",
                "request_present": False,
                **dict(metadata or {}),
            },
        ).normalized()
    except VariantPlannerError:
        raise
    except Exception as exc:
        raise VariantPlannerError(f"Could not plan variants for profile: {exc}") from exc


def collect_variant_decisions(
    *,
    request: Any,
    profile: Any | None,
    options: VariantPlanningOptions,
) -> tuple[VariantPlanningDecision, ...]:
    """Sammelt Variantenentscheidungen aus Request, Profil und Optionen."""
    decisions: list[VariantPlanningDecision] = []
    normalized_request = normalize_create_request(request)
    normalized_options = options.normalized()

    request_variants = getattr(normalized_request.variants, "variants", ()) or ()
    default_variant_id = (
        normalized_options.default_variant_id
        or getattr(normalized_request.variants, "default_variant_id", None)
        or get_profile_default_variant_id(profile)
        or "default"
    )

    if not request_variants:
        decisions.append(
            VariantPlanningDecision(
                action=VariantPlanningAction.CREATE_DEFAULT.value,
                source=VariantPlanningSource.SYSTEM_DEFAULT.value,
                variant_id=default_variant_id,
                message="No request variants provided; default variant will be created.",
            ).normalized()
        )
        return tuple(decisions)

    for variant in request_variants:
        variant_id = getattr(variant, "variant_id", None) or "default"
        action = (
            VariantPlanningAction.CREATE_DEFAULT.value
            if normalize_variant_id_safe(variant_id) == normalize_variant_id_safe(default_variant_id)
            else VariantPlanningAction.CREATE_VARIANT.value
        )

        decisions.append(
            VariantPlanningDecision(
                action=action,
                source=VariantPlanningSource.REQUEST.value,
                variant_id=variant_id,
                message="Variant planned from request.",
                metadata={
                    "has_overrides": bool(getattr(variant, "overrides", None)),
                },
            ).normalized()
        )

    if len(request_variants) > 1:
        decisions.append(
            VariantPlanningDecision(
                action=VariantPlanningAction.PROMOTE_TO_MULTIPLE.value,
                source=VariantPlanningSource.NORMALIZATION.value,
                variant_id=None,
                message="More than one variant requires multiple variant mode.",
            ).normalized()
        )

    return tuple(decisions)


def build_variant_set_from_decisions(
    *,
    request: Any | None,
    profile: Any | None,
    decisions: Iterable[VariantPlanningDecision],
    options: VariantPlanningOptions,
) -> Any:
    """Baut ein VariantSet aus Entscheidungen und Request-Daten."""
    try:
        from ..models.variant_definition import VariantDefinition, VariantSet

        normalized_options = options.normalized()
        normalized_profile = normalize_profile(profile) if profile is not None else None

        request_variants_by_id = {}
        request_variant_mode = None
        request_default_variant_id = None

        if request is not None:
            normalized_request = normalize_create_request(request)
            request_variant_mode = getattr(normalized_request.variants, "mode", None)
            request_default_variant_id = getattr(normalized_request.variants, "default_variant_id", None)

            for request_variant in getattr(normalized_request.variants, "variants", ()) or ():
                variant_normalized = request_variant.normalized() if hasattr(request_variant, "normalized") else request_variant
                request_variants_by_id[normalize_variant_id_safe(getattr(variant_normalized, "variant_id", "default"))] = variant_normalized

        default_variant_id = (
            normalized_options.default_variant_id
            or request_default_variant_id
            or get_profile_default_variant_id(normalized_profile)
            or "default"
        )
        default_variant_id = normalize_variant_id_safe(default_variant_id)

        mode = (
            normalized_options.mode
            or request_variant_mode
            or get_profile_variant_mode(normalized_profile)
            or "single"
        )
        mode = normalize_variant_mode_safe(mode)

        variants: list[Any] = []
        seen: set[str] = set()

        for decision in decisions or ():
            normalized_decision = decision.normalized()

            if normalized_decision.action == VariantPlanningAction.REJECT_VARIANT.value:
                continue

            if not normalized_decision.variant_id:
                continue

            variant_id = normalized_decision.variant_id
            if variant_id in seen:
                continue

            request_variant = request_variants_by_id.get(variant_id)
            if request_variant is not None:
                overrides = dict(getattr(request_variant, "overrides", {}) or {})
                label = getattr(request_variant, "label", None)
                description = getattr(request_variant, "description", "")
            else:
                overrides = {}
                label = "Default" if variant_id == default_variant_id else humanize_variant_id_safe(variant_id)
                description = "Default variant." if variant_id == default_variant_id else ""

            variants.append(
                VariantDefinition(
                    variant_id=variant_id,
                    label=label,
                    description=description,
                    inherits_from=None if variant_id == default_variant_id else default_variant_id,
                    sort_order=0 if variant_id == default_variant_id else 100,
                    overrides=overrides,
                ).normalized(
                    policy="strict" if normalized_options.enforce_overrides_only else "permissive"
                )
            )
            seen.add(variant_id)

        if default_variant_id not in seen:
            variants.insert(
                0,
                VariantDefinition(
                    variant_id=default_variant_id,
                    label="Default",
                    description="Default variant.",
                    inherits_from=None,
                    sort_order=0,
                    overrides={},
                ).normalized(
                    policy="strict" if normalized_options.enforce_overrides_only else "permissive"
                ),
            )

        if len(variants) > 1 and normalized_options.allow_multiple_variants:
            mode = "multiple"

        if len(variants) > 1 and not normalized_options.allow_multiple_variants:
            raise VariantPlannerError("Multiple variants are not allowed by options.")

        return VariantSet(
            variants=tuple(variants),
            default_variant_id=default_variant_id,
            mode=mode,
            policy="strict" if normalized_options.enforce_overrides_only else "permissive",
            metadata={
                "planned_by": "variant_planner",
                "profile_key": getattr(normalized_profile, "profile_key", None),
            },
        ).normalized()
    except VariantPlannerError:
        raise
    except Exception as exc:
        raise VariantPlannerError(f"Could not build VariantSet from decisions: {exc}") from exc


def normalize_options(
    options: VariantPlanningOptions | Mapping[str, Any] | None,
    *,
    request: Any | None = None,
    profile: Any | None = None,
) -> VariantPlanningOptions:
    """Normalisiert VariantPlanningOptions."""
    try:
        if options is None:
            request_default_variant_id = None
            request_mode = None

            if request is not None:
                normalized_request = normalize_create_request(request)
                request_default_variant_id = getattr(normalized_request.variants, "default_variant_id", None)
                request_mode = getattr(normalized_request.variants, "mode", None)

            return VariantPlanningOptions(
                default_variant_id=request_default_variant_id or get_profile_default_variant_id(profile),
                mode=request_mode or get_profile_variant_mode(profile),
                strict=True,
            ).normalized()

        if isinstance(options, VariantPlanningOptions):
            return options.normalized()

        if isinstance(options, Mapping):
            return VariantPlanningOptions(
                default_variant_id=options.get("default_variant_id"),
                mode=options.get("mode"),
                allow_multiple_variants=bool(options.get("allow_multiple_variants", True)),
                enforce_overrides_only=bool(options.get("enforce_overrides_only", True)),
                strict=bool(options.get("strict", True)),
            ).normalized()

        raise VariantPlannerError("options must be VariantPlanningOptions, mapping or None.")
    except VariantPlannerError:
        raise
    except Exception as exc:
        raise VariantPlannerError(f"Invalid variant planning options: {exc}") from exc


def get_profile_default_variant_id(profile: Any | None) -> str | None:
    """Liest default_variant_id aus einem Profil."""
    if profile is None:
        return None

    try:
        normalized_profile = normalize_profile(profile)
        return normalize_variant_id_safe(normalized_profile.defaults.default_variant_id)
    except Exception:
        return None


def get_profile_variant_mode(profile: Any | None) -> str | None:
    """Liest variant_mode aus einem Profil."""
    if profile is None:
        return None

    try:
        normalized_profile = normalize_profile(profile)
        return normalize_variant_mode_safe(normalized_profile.defaults.variant_mode)
    except Exception:
        return None


def normalize_create_request(value: Any) -> Any:
    """Normalisiert einen CreateRequest."""
    try:
        from ..models.create_request import CreateRequest, create_request_from_mapping

        if isinstance(value, CreateRequest):
            return value.normalized()

        if isinstance(value, Mapping):
            return create_request_from_mapping(value).normalized()

        if hasattr(value, "normalized") and callable(value.normalized):
            return value.normalized()

        raise VariantPlannerError("CreateRequest value is required.")
    except VariantPlannerError:
        raise
    except Exception as exc:
        raise VariantPlannerError(f"Invalid CreateRequest: {exc}") from exc


def normalize_profile(value: Any) -> Any:
    """Normalisiert ein ObjectKindProfile."""
    try:
        from ..profiles.base_profiles import ObjectKindProfile

        if isinstance(value, ObjectKindProfile):
            return value.normalized()

        if hasattr(value, "normalized") and callable(value.normalized):
            return value.normalized()

        raise VariantPlannerError("ObjectKindProfile value is required.")
    except VariantPlannerError:
        raise
    except Exception as exc:
        raise VariantPlannerError(f"Invalid ObjectKindProfile: {exc}") from exc


def normalize_variant_set(value: Any) -> Any:
    """Normalisiert ein VariantSet."""
    try:
        from ..models.variant_definition import VariantSet, variant_set_from_mapping

        if isinstance(value, VariantSet):
            return value.normalized()

        if isinstance(value, Mapping):
            return variant_set_from_mapping(value).normalized()

        if hasattr(value, "normalized") and callable(value.normalized):
            return value.normalized()

        raise VariantPlannerError("VariantSet value is required.")
    except VariantPlannerError:
        raise
    except Exception as exc:
        raise VariantPlannerError(f"Invalid VariantSet: {exc}") from exc


def normalize_optional_object_kind(value: Any) -> str | None:
    """Normalisiert optionale Objektart."""
    if value is None:
        return None

    try:
        from ..domain.object_kinds import ensure_object_kind_value

        return ensure_object_kind_value(value)
    except Exception as exc:
        raise VariantPlannerError(f"Invalid object_kind {value!r}: {exc}") from exc


def normalize_variant_id_safe(value: Any) -> str:
    """Normalisiert Variant-ID."""
    try:
        from ..models.variant_definition import normalize_variant_id

        return normalize_variant_id(value)
    except Exception as exc:
        raise VariantPlannerError(f"Invalid variant_id {value!r}: {exc}") from exc


def normalize_variant_mode_safe(value: Any) -> str:
    """Normalisiert VariantMode."""
    try:
        from ..models.variant_definition import parse_variant_mode_value

        return parse_variant_mode_value(value)
    except Exception as exc:
        raise VariantPlannerError(f"Invalid variant mode {value!r}: {exc}") from exc


def humanize_variant_id_safe(value: Any) -> str:
    """Erzeugt ein Label aus Variant-ID."""
    try:
        from ..models.variant_definition import humanize_variant_id

        return humanize_variant_id(value)
    except Exception:
        return str(value).replace("_", " ").title()


@lru_cache(maxsize=128)
def parse_variant_planning_source_value(value: Any) -> str:
    """Parst VariantPlanningSource."""
    try:
        if isinstance(value, VariantPlanningSource):
            return value.value

        raw = normalize_enum_key(value)
        return VariantPlanningSource(raw).value
    except Exception as exc:
        raise VariantPlannerError(f"Invalid variant planning source {value!r}.") from exc


@lru_cache(maxsize=128)
def parse_variant_planning_action_value(value: Any) -> str:
    """Parst VariantPlanningAction."""
    try:
        if isinstance(value, VariantPlanningAction):
            return value.value

        raw = normalize_enum_key(value)
        return VariantPlanningAction(raw).value
    except Exception as exc:
        raise VariantPlannerError(f"Invalid variant planning action {value!r}.") from exc


def normalize_enum_key(value: Any) -> str:
    """Normalisiert Enum-ähnliche Werte."""
    try:
        raw = str(value).strip()

        if not raw:
            raise VariantPlannerError("Enum value is required.")

        return (
            raw.lower()
            .replace(" ", "_")
            .replace("-", "_")
            .replace("/", "_")
            .replace("\\", "_")
        )
    except VariantPlannerError:
        raise
    except Exception as exc:
        raise VariantPlannerError(f"Invalid enum value {value!r}.") from exc


def clean_optional_string(value: Any) -> str | None:
    """Normalisiert optionalen String."""
    if value is None:
        return None

    try:
        cleaned = str(value).strip()
        return cleaned or None
    except Exception:
        return None


def normalize_metadata(value: Mapping[str, Any] | None) -> dict[str, Any]:
    """Normalisiert Metadata JSON-kompatibel."""
    if value is None:
        return {}

    if not isinstance(value, Mapping):
        raise VariantPlannerError("metadata must be a mapping.")

    return {
        str(key): normalize_metadata_value(child_value)
        for key, child_value in value.items()
    }


def normalize_metadata_value(value: Any) -> Any:
    """Normalisiert Metadata-Werte JSON-kompatibel."""
    if value is None:
        return None

    if isinstance(value, (str, int, float, bool)):
        return value

    if isinstance(value, Mapping):
        return normalize_metadata(value)

    if isinstance(value, (list, tuple, set)):
        return [normalize_metadata_value(item) for item in value]

    return str(value)


def clear_variant_planner_caches() -> None:
    """Leert interne Parser-Caches."""
    parse_variant_planning_source_value.cache_clear()
    parse_variant_planning_action_value.cache_clear()


__all__ = [
    "VARIANT_PLANNER_SCHEMA_VERSION",
    "VariantPlannerError",
    "VariantPlanningAction",
    "VariantPlanningDecision",
    "VariantPlanningOptions",
    "VariantPlanningResult",
    "VariantPlanningSource",
    "build_variant_set_from_decisions",
    "clean_optional_string",
    "clear_variant_planner_caches",
    "collect_variant_decisions",
    "get_profile_default_variant_id",
    "get_profile_variant_mode",
    "humanize_variant_id_safe",
    "normalize_create_request",
    "normalize_enum_key",
    "normalize_metadata",
    "normalize_metadata_value",
    "normalize_optional_object_kind",
    "normalize_options",
    "normalize_profile",
    "normalize_variant_id_safe",
    "normalize_variant_mode_safe",
    "normalize_variant_set",
    "parse_variant_planning_action_value",
    "parse_variant_planning_source_value",
    "plan_variants_for_profile",
    "plan_variants_for_request",
]