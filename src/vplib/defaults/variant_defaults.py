# services/vectoplan-library/src/vplib/defaults/variant_defaults.py
"""
Variant defaults for the VPLIB package engine.

Diese Datei erzeugt robuste Default-Daten für:

    variants/index.json
    variants/default.json
    variants/<variant_id>.json

Grundregel:
Eine Variante ist keine vollständige neue Family. Eine Variante enthält nur
Overrides gegenüber der Family- oder Default-Struktur.

Diese Datei schreibt keine Dateien. Sie erzeugt nur JSON-kompatible Payloads.

Technische Namen, JSON-Keys und Variablen bleiben Englisch.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from enum import Enum
from functools import lru_cache
from typing import Any, Final, Iterable, Mapping


VARIANT_DEFAULTS_SCHEMA_VERSION: Final[str] = "vplib.variant_defaults.v1"
VARIANT_INDEX_DOCUMENT_SCHEMA_VERSION: Final[str] = "vplib.variants.index.v1"
VARIANT_DOCUMENT_SCHEMA_VERSION: Final[str] = "vplib.variant.v1"

DEFAULT_VARIANT_ID: Final[str] = "default"
DEFAULT_VARIANT_LABEL: Final[str] = "Default"

SAFE_VARIANT_ID_RE: Final[re.Pattern[str]] = re.compile(
    r"^[a-z0-9][a-z0-9._-]*[a-z0-9]$|^[a-z0-9]$"
)


class VariantDefaultsError(ValueError):
    """Wird ausgelöst, wenn Variant-Defaults ungültig erzeugt werden."""


class VariantMode(str, Enum):
    """Variantenmodus einer Family."""

    SINGLE = "single"
    MULTIPLE = "multiple"

    @property
    def key(self) -> str:
        return str(self.value)


class VariantStatus(str, Enum):
    """Status einer Variante."""

    ACTIVE = "active"
    DRAFT = "draft"
    DEPRECATED = "deprecated"
    DISABLED = "disabled"

    @property
    def key(self) -> str:
        return str(self.value)


class VariantSourceKind(str, Enum):
    """Quelle der Variantenstruktur."""

    CREATE_REQUEST = "create_request"
    VARIANT_SET = "variant_set"
    VARIANT_PLANNING_RESULT = "variant_planning_result"
    PROFILE_DEFAULTS = "profile_defaults"
    SYSTEM = "system"

    @property
    def key(self) -> str:
        return str(self.value)


@dataclass(frozen=True, slots=True)
class VariantDocumentDefaults:
    """Defaults für eine einzelne variants/<variant_id>.json-Datei."""

    variant_id: str
    label: str | None = None
    description: str = ""
    inherits_from: str | None = DEFAULT_VARIANT_ID
    enabled: bool = True
    status: str = VariantStatus.ACTIVE.value
    sort_order: int = 100
    tags: tuple[str, ...] = field(default_factory=tuple)
    overrides: Mapping[str, Any] = field(default_factory=dict)
    metadata: Mapping[str, Any] = field(default_factory=dict)

    def normalized(self) -> "VariantDocumentDefaults":
        variant_id = normalize_variant_id(self.variant_id)
        label = clean_optional_string(self.label) or humanize_variant_id(variant_id)
        description = clean_optional_string(self.description) or ""
        inherits_from = clean_optional_string(self.inherits_from)
        enabled = bool(self.enabled)
        status = parse_variant_status_value(self.status)
        sort_order = normalize_int(self.sort_order, "sort_order")
        tags = normalize_string_tuple(self.tags)
        overrides = normalize_overrides_mapping_safe(self.overrides)
        metadata = normalize_metadata(self.metadata)

        if variant_id == DEFAULT_VARIANT_ID:
            inherits_from = None
            sort_order = 0
        elif not inherits_from:
            inherits_from = DEFAULT_VARIANT_ID
        else:
            inherits_from = normalize_variant_id(inherits_from)

        if inherits_from == variant_id:
            raise VariantDefaultsError(f"Variant {variant_id!r} cannot inherit from itself.")

        return VariantDocumentDefaults(
            variant_id=variant_id,
            label=label,
            description=description,
            inherits_from=inherits_from,
            enabled=enabled,
            status=status,
            sort_order=sort_order,
            tags=tags,
            overrides=overrides,
            metadata=metadata,
        )

    def to_document(self) -> dict[str, Any]:
        """Erzeugt variants/<variant_id>.json."""
        normalized = self.normalized()

        return {
            "schema_version": VARIANT_DOCUMENT_SCHEMA_VERSION,
            "variant_id": normalized.variant_id,
            "label": normalized.label,
            "description": normalized.description,
            "inherits_from": normalized.inherits_from,
            "enabled": normalized.enabled,
            "status": normalized.status,
            "sort_order": normalized.sort_order,
            "tags": list(normalized.tags),
            "overrides": dict(normalized.overrides),
            "metadata": dict(normalized.metadata),
        }

    def to_index_entry(self) -> dict[str, Any]:
        """Erzeugt den kompakten Indexeintrag für variants/index.json."""
        normalized = self.normalized()

        return {
            "variant_id": normalized.variant_id,
            "label": normalized.label,
            "description": normalized.description,
            "inherits_from": normalized.inherits_from,
            "enabled": normalized.enabled,
            "status": normalized.status,
            "sort_order": normalized.sort_order,
            "tags": list(normalized.tags),
        }

    def to_dict(self) -> dict[str, Any]:
        return self.to_document()


@dataclass(frozen=True, slots=True)
class VariantIndexDefaults:
    """Defaults für variants/index.json."""

    mode: str = VariantMode.SINGLE.value
    default_variant_id: str = DEFAULT_VARIANT_ID
    variants: tuple[VariantDocumentDefaults, ...] = field(default_factory=tuple)
    source_kind: str = VariantSourceKind.SYSTEM.value
    metadata: Mapping[str, Any] = field(default_factory=dict)

    def normalized(self) -> "VariantIndexDefaults":
        mode = parse_variant_mode_value(self.mode)
        default_variant_id = normalize_variant_id(self.default_variant_id or DEFAULT_VARIANT_ID)
        source_kind = parse_source_kind_value(self.source_kind)
        metadata = normalize_metadata(self.metadata)

        variants = tuple(variant.normalized() for variant in self.variants or ())
        if not variants:
            variants = (
                VariantDocumentDefaults(
                    variant_id=default_variant_id,
                    label=DEFAULT_VARIANT_LABEL,
                    description="Default variant.",
                    inherits_from=None,
                    sort_order=0,
                    overrides={},
                ).normalized(),
            )

        variants_by_id: dict[str, VariantDocumentDefaults] = {}
        for variant in variants:
            if variant.variant_id in variants_by_id:
                raise VariantDefaultsError(f"Duplicate variant_id {variant.variant_id!r}.")
            variants_by_id[variant.variant_id] = variant

        if default_variant_id not in variants_by_id:
            variants_by_id[default_variant_id] = VariantDocumentDefaults(
                variant_id=default_variant_id,
                label=DEFAULT_VARIANT_LABEL,
                description="Default variant.",
                inherits_from=None,
                sort_order=0,
                overrides={},
            ).normalized()

        for variant in variants_by_id.values():
            if variant.inherits_from and variant.inherits_from not in variants_by_id:
                raise VariantDefaultsError(
                    f"Variant {variant.variant_id!r} inherits from unknown variant "
                    f"{variant.inherits_from!r}."
                )

        sorted_variants = tuple(
            sorted(
                variants_by_id.values(),
                key=lambda item: (
                    0 if item.variant_id == default_variant_id else 1,
                    item.sort_order,
                    item.variant_id,
                ),
            )
        )

        active_variants = tuple(
            variant
            for variant in sorted_variants
            if variant.enabled and variant.status == VariantStatus.ACTIVE.value
        )

        if mode == VariantMode.SINGLE.value and len(active_variants) > 1:
            mode = VariantMode.MULTIPLE.value

        return VariantIndexDefaults(
            mode=mode,
            default_variant_id=default_variant_id,
            variants=sorted_variants,
            source_kind=source_kind,
            metadata=metadata,
        )

    @property
    def variant_ids(self) -> tuple[str, ...]:
        return tuple(variant.variant_id for variant in self.normalized().variants)

    @property
    def default_variant(self) -> VariantDocumentDefaults:
        normalized = self.normalized()

        for variant in normalized.variants:
            if variant.variant_id == normalized.default_variant_id:
                return variant

        raise VariantDefaultsError(
            f"Default variant {normalized.default_variant_id!r} does not exist."
        )

    def to_document(self) -> dict[str, Any]:
        """Erzeugt variants/index.json."""
        normalized = self.normalized()

        return {
            "schema_version": VARIANT_INDEX_DOCUMENT_SCHEMA_VERSION,
            "mode": normalized.mode,
            "default_variant_id": normalized.default_variant_id,
            "variant_ids": list(normalized.variant_ids),
            "variants": [variant.to_index_entry() for variant in normalized.variants],
            "source_kind": normalized.source_kind,
            "metadata": dict(normalized.metadata),
        }

    def to_dict(self) -> dict[str, Any]:
        return self.to_document()


@dataclass(frozen=True, slots=True)
class VariantDefaults:
    """Vollständige Defaults für alle variants/*.json-Dokumente."""

    index: VariantIndexDefaults

    def normalized(self) -> "VariantDefaults":
        return VariantDefaults(
            index=self.index.normalized(),
        )

    @property
    def variants(self) -> tuple[VariantDocumentDefaults, ...]:
        return self.normalized().index.variants

    @property
    def default_variant_id(self) -> str:
        return self.normalized().index.default_variant_id

    @property
    def mode(self) -> str:
        return self.normalized().index.mode

    def to_documents(self) -> dict[str, dict[str, Any]]:
        """Erzeugt alle Varianten-Dokumente als Pfad -> Payload."""
        normalized = self.normalized()

        documents: dict[str, dict[str, Any]] = {
            "variants/index.json": normalized.index.to_document(),
        }

        for variant in normalized.variants:
            documents[f"variants/{variant.variant_id}.json"] = variant.to_document()

        return documents

    def to_dict(self) -> dict[str, Any]:
        normalized = self.normalized()

        return {
            "schema_version": VARIANT_DEFAULTS_SCHEMA_VERSION,
            "index": normalized.index.to_dict(),
            "documents": normalized.to_documents(),
        }


def build_variant_defaults(
    *,
    mode: str = VariantMode.SINGLE.value,
    default_variant_id: str = DEFAULT_VARIANT_ID,
    variants: Iterable[VariantDocumentDefaults | Mapping[str, Any]] = (),
    source_kind: str = VariantSourceKind.SYSTEM.value,
    metadata: Mapping[str, Any] | None = None,
) -> VariantDefaults:
    """Baut VariantDefaults aus expliziten Werten."""
    try:
        parsed_variants = tuple(
            variant
            if isinstance(variant, VariantDocumentDefaults)
            else variant_document_defaults_from_mapping(variant)
            for variant in variants or ()
        )

        return VariantDefaults(
            index=VariantIndexDefaults(
                mode=mode,
                default_variant_id=default_variant_id,
                variants=parsed_variants,
                source_kind=source_kind,
                metadata=dict(metadata or {}),
            )
        ).normalized()
    except VariantDefaultsError:
        raise
    except Exception as exc:
        raise VariantDefaultsError(f"Could not build variant defaults: {exc}") from exc


def build_default_variant_document(
    *,
    variant_id: str = DEFAULT_VARIANT_ID,
    label: str = DEFAULT_VARIANT_LABEL,
    description: str = "Default variant.",
    overrides: Mapping[str, Any] | None = None,
    metadata: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    """Baut direkt ein Default-Variant-Dokument."""
    return VariantDocumentDefaults(
        variant_id=variant_id,
        label=label,
        description=description,
        inherits_from=None,
        sort_order=0,
        overrides=dict(overrides or {}),
        metadata=dict(metadata or {}),
    ).to_document()


def variant_document_defaults_from_mapping(data: Mapping[str, Any]) -> VariantDocumentDefaults:
    """Baut VariantDocumentDefaults aus einem Mapping."""
    try:
        if not isinstance(data, Mapping):
            raise VariantDefaultsError("Variant document data must be a mapping.")

        return VariantDocumentDefaults(
            variant_id=data.get("variant_id") or data.get("id"),
            label=data.get("label") or data.get("name"),
            description=data.get("description", ""),
            inherits_from=data.get("inherits_from", DEFAULT_VARIANT_ID),
            enabled=bool(data.get("enabled", True)),
            status=data.get("status", VariantStatus.ACTIVE.value),
            sort_order=data.get("sort_order", 100),
            tags=tuple(data.get("tags", ()) or ()),
            overrides=dict(data.get("overrides", {}) or {}),
            metadata=dict(data.get("metadata", {}) or {}),
        ).normalized()
    except VariantDefaultsError:
        raise
    except Exception as exc:
        raise VariantDefaultsError(f"Could not build VariantDocumentDefaults from mapping: {exc}") from exc


def variant_defaults_from_variant_set(
    variant_set: Any,
    *,
    source_kind: str = VariantSourceKind.VARIANT_SET.value,
    metadata: Mapping[str, Any] | None = None,
) -> VariantDefaults:
    """Baut VariantDefaults aus einem VariantSet-ähnlichen Objekt."""
    try:
        normalized_set = normalize_variant_set(variant_set)
        variants = tuple(
            VariantDocumentDefaults(
                variant_id=variant.variant_id,
                label=variant.label,
                description=variant.description,
                inherits_from=variant.inherits_from,
                enabled=variant.enabled,
                status=variant.status,
                sort_order=variant.sort_order,
                tags=variant.tags,
                overrides=variant.overrides,
                metadata=variant.metadata,
            ).normalized()
            for variant in normalized_set.variants
        )

        return build_variant_defaults(
            mode=normalized_set.mode,
            default_variant_id=normalized_set.default_variant_id,
            variants=variants,
            source_kind=source_kind,
            metadata={
                "source": "variant_set",
                **dict(metadata or {}),
            },
        )
    except VariantDefaultsError:
        raise
    except Exception as exc:
        raise VariantDefaultsError(f"Could not build variant defaults from VariantSet: {exc}") from exc


def variant_defaults_from_create_request(
    request: Any,
    *,
    metadata: Mapping[str, Any] | None = None,
) -> VariantDefaults:
    """Baut VariantDefaults aus einem CreateRequest-ähnlichen Objekt."""
    try:
        from ..models.variant_definition import variant_set_from_create_request

        normalized_request = normalize_create_request(request)
        variant_set = variant_set_from_create_request(normalized_request)

        return variant_defaults_from_variant_set(
            variant_set,
            source_kind=VariantSourceKind.CREATE_REQUEST.value,
            metadata={
                "source": "create_request",
                **dict(metadata or {}),
            },
        )
    except VariantDefaultsError:
        raise
    except Exception as exc:
        raise VariantDefaultsError(f"Could not build variant defaults from CreateRequest: {exc}") from exc


def variant_defaults_from_planning_result(
    planning_result: Any,
    *,
    metadata: Mapping[str, Any] | None = None,
) -> VariantDefaults:
    """Baut VariantDefaults aus einem VariantPlanningResult-ähnlichen Objekt."""
    try:
        normalized_result = planning_result.normalized() if hasattr(planning_result, "normalized") else planning_result

        return variant_defaults_from_variant_set(
            normalized_result.variant_set,
            source_kind=VariantSourceKind.VARIANT_PLANNING_RESULT.value,
            metadata={
                "source": "variant_planning_result",
                "object_kind": getattr(normalized_result, "object_kind", None),
                "profile_key": getattr(normalized_result, "profile_key", None),
                **dict(metadata or {}),
            },
        )
    except VariantDefaultsError:
        raise
    except Exception as exc:
        raise VariantDefaultsError(f"Could not build variant defaults from planning result: {exc}") from exc


def variants_index_document_from_create_request(
    request: Any,
    *,
    metadata: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    """Baut variants/index.json aus CreateRequest."""
    return variant_defaults_from_create_request(
        request,
        metadata=metadata,
    ).index.to_document()


def variant_documents_from_create_request(
    request: Any,
    *,
    metadata: Mapping[str, Any] | None = None,
) -> dict[str, dict[str, Any]]:
    """Baut alle variants/*.json-Dokumente aus CreateRequest."""
    return variant_defaults_from_create_request(
        request,
        metadata=metadata,
    ).to_documents()


def variant_documents_from_variant_set(
    variant_set: Any,
    *,
    metadata: Mapping[str, Any] | None = None,
) -> dict[str, dict[str, Any]]:
    """Baut alle variants/*.json-Dokumente aus VariantSet."""
    return variant_defaults_from_variant_set(
        variant_set,
        metadata=metadata,
    ).to_documents()


def validate_variant_index_document(document: Mapping[str, Any]) -> tuple[bool, tuple[str, ...]]:
    """Validiert grob variants/index.json."""
    messages: list[str] = []

    try:
        if not isinstance(document, Mapping):
            return False, ("variants/index.json must be a mapping.",)

        required_fields = (
            "schema_version",
            "mode",
            "default_variant_id",
            "variant_ids",
            "variants",
        )

        for field_name in required_fields:
            if field_name not in document:
                messages.append(f"Missing variant index field {field_name!r}.")

        if "mode" in document:
            try:
                parse_variant_mode_value(document["mode"])
            except Exception as exc:
                messages.append(str(exc))

        if "default_variant_id" in document:
            try:
                normalize_variant_id(document["default_variant_id"])
            except Exception as exc:
                messages.append(str(exc))

        variant_ids = document.get("variant_ids", ())
        if isinstance(variant_ids, list):
            normalized_ids = []
            for variant_id in variant_ids:
                try:
                    normalized_ids.append(normalize_variant_id(variant_id))
                except Exception as exc:
                    messages.append(str(exc))

            if len(normalized_ids) != len(set(normalized_ids)):
                messages.append("variants/index.json contains duplicate variant_ids.")
        else:
            messages.append("variants/index.json field 'variant_ids' must be a list.")

    except Exception as exc:
        messages.append(f"Could not validate variant index document: {exc}")

    return len(messages) == 0, tuple(messages)


def validate_variant_document(document: Mapping[str, Any]) -> tuple[bool, tuple[str, ...]]:
    """Validiert grob variants/<variant_id>.json."""
    messages: list[str] = []

    try:
        if not isinstance(document, Mapping):
            return False, ("Variant document must be a mapping.",)

        required_fields = (
            "schema_version",
            "variant_id",
            "label",
            "enabled",
            "status",
            "sort_order",
            "overrides",
        )

        for field_name in required_fields:
            if field_name not in document:
                messages.append(f"Missing variant document field {field_name!r}.")

        try:
            VariantDocumentDefaults(
                variant_id=document.get("variant_id"),
                label=document.get("label"),
                description=document.get("description", ""),
                inherits_from=document.get("inherits_from"),
                enabled=bool(document.get("enabled", True)),
                status=document.get("status", VariantStatus.ACTIVE.value),
                sort_order=document.get("sort_order", 100),
                tags=tuple(document.get("tags", ()) or ()),
                overrides=dict(document.get("overrides", {}) or {}),
                metadata=dict(document.get("metadata", {}) or {}),
            ).normalized()
        except Exception as exc:
            messages.append(str(exc))

    except Exception as exc:
        messages.append(f"Could not validate variant document: {exc}")

    return len(messages) == 0, tuple(messages)


def assert_valid_variant_index_document(document: Mapping[str, Any]) -> None:
    """Wirft VariantDefaultsError, wenn variants/index.json ungültig ist."""
    valid, messages = validate_variant_index_document(document)

    if not valid:
        joined = " ".join(messages) if messages else "Invalid variant index document."
        raise VariantDefaultsError(joined)


def assert_valid_variant_document(document: Mapping[str, Any]) -> None:
    """Wirft VariantDefaultsError, wenn ein Variant-Dokument ungültig ist."""
    valid, messages = validate_variant_document(document)

    if not valid:
        joined = " ".join(messages) if messages else "Invalid variant document."
        raise VariantDefaultsError(joined)


def normalize_create_request(value: Any) -> Any:
    """Normalisiert CreateRequest-ähnliche Werte."""
    try:
        from ..models.create_request import CreateRequest, create_request_from_mapping

        if isinstance(value, CreateRequest):
            return value.normalized()

        if isinstance(value, Mapping):
            return create_request_from_mapping(value).normalized()

        if hasattr(value, "normalized") and callable(value.normalized):
            return value.normalized()

        raise VariantDefaultsError("CreateRequest value is required.")
    except VariantDefaultsError:
        raise
    except Exception as exc:
        raise VariantDefaultsError(f"Invalid CreateRequest: {exc}") from exc


def normalize_variant_set(value: Any) -> Any:
    """Normalisiert VariantSet-ähnliche Werte."""
    try:
        from ..models.variant_definition import VariantSet, variant_set_from_mapping

        if isinstance(value, VariantSet):
            return value.normalized()

        if isinstance(value, Mapping):
            return variant_set_from_mapping(value).normalized()

        if hasattr(value, "normalized") and callable(value.normalized):
            return value.normalized()

        raise VariantDefaultsError("VariantSet value is required.")
    except VariantDefaultsError:
        raise
    except Exception as exc:
        raise VariantDefaultsError(f"Invalid VariantSet: {exc}") from exc


def normalize_variant_id(value: Any) -> str:
    """Normalisiert variant_id."""
    raw = clean_required_string(value, "variant_id")
    variant_id = (
        raw.lower()
        .replace(" ", "_")
        .replace("-", "_")
        .replace("/", "_")
        .replace("\\", "_")
    )

    if not SAFE_VARIANT_ID_RE.match(variant_id):
        raise VariantDefaultsError(f"Invalid variant_id {value!r}.")

    return variant_id


def humanize_variant_id(value: Any) -> str:
    """Erzeugt ein einfaches Label aus einer Variant-ID."""
    variant_id = normalize_variant_id(value)

    if variant_id == DEFAULT_VARIANT_ID:
        return DEFAULT_VARIANT_LABEL

    return variant_id.replace("_", " ").replace(".", " ").title()


def normalize_overrides_mapping_safe(value: Mapping[str, Any]) -> dict[str, Any]:
    """Normalisiert Variant-Overrides über das VariantDefinition-Modell."""
    try:
        from ..models.variant_definition import normalize_overrides_mapping

        return normalize_overrides_mapping(value or {})
    except Exception as exc:
        raise VariantDefaultsError(f"Invalid variant overrides: {exc}") from exc


@lru_cache(maxsize=128)
def parse_variant_mode_value(value: Any) -> str:
    """Parst VariantMode."""
    try:
        if isinstance(value, VariantMode):
            return value.value

        raw = normalize_enum_key(value)

        aliases = {
            "single": VariantMode.SINGLE.value,
            "standard": VariantMode.SINGLE.value,
            "default": VariantMode.SINGLE.value,
            "one": VariantMode.SINGLE.value,
            "multiple": VariantMode.MULTIPLE.value,
            "multi": VariantMode.MULTIPLE.value,
            "many": VariantMode.MULTIPLE.value,
            "variants": VariantMode.MULTIPLE.value,
        }

        if raw in aliases:
            return aliases[raw]

        return VariantMode(raw).value
    except Exception as exc:
        raise VariantDefaultsError(f"Invalid variant mode {value!r}.") from exc


@lru_cache(maxsize=128)
def parse_variant_status_value(value: Any) -> str:
    """Parst VariantStatus."""
    try:
        if isinstance(value, VariantStatus):
            return value.value

        raw = normalize_enum_key(value)

        aliases = {
            "active": VariantStatus.ACTIVE.value,
            "enabled": VariantStatus.ACTIVE.value,
            "draft": VariantStatus.DRAFT.value,
            "deprecated": VariantStatus.DEPRECATED.value,
            "disabled": VariantStatus.DISABLED.value,
            "inactive": VariantStatus.DISABLED.value,
        }

        if raw in aliases:
            return aliases[raw]

        return VariantStatus(raw).value
    except Exception as exc:
        raise VariantDefaultsError(f"Invalid variant status {value!r}.") from exc


@lru_cache(maxsize=128)
def parse_source_kind_value(value: Any) -> str:
    """Parst VariantSourceKind."""
    try:
        if isinstance(value, VariantSourceKind):
            return value.value

        raw = normalize_enum_key(value)

        aliases = {
            "request": VariantSourceKind.CREATE_REQUEST.value,
            "create_request": VariantSourceKind.CREATE_REQUEST.value,
            "variant_set": VariantSourceKind.VARIANT_SET.value,
            "planning_result": VariantSourceKind.VARIANT_PLANNING_RESULT.value,
            "variant_planning_result": VariantSourceKind.VARIANT_PLANNING_RESULT.value,
            "profile": VariantSourceKind.PROFILE_DEFAULTS.value,
            "profile_defaults": VariantSourceKind.PROFILE_DEFAULTS.value,
            "system": VariantSourceKind.SYSTEM.value,
        }

        if raw in aliases:
            return aliases[raw]

        return VariantSourceKind(raw).value
    except Exception as exc:
        raise VariantDefaultsError(f"Invalid variant source kind {value!r}.") from exc


def normalize_enum_key(value: Any) -> str:
    """Normalisiert Enum-ähnliche Werte."""
    try:
        raw = str(value).strip()

        if not raw:
            raise VariantDefaultsError("Enum value is required.")

        return (
            raw.lower()
            .replace(" ", "_")
            .replace("-", "_")
            .replace("/", "_")
            .replace("\\", "_")
        )
    except VariantDefaultsError:
        raise
    except Exception as exc:
        raise VariantDefaultsError(f"Invalid enum value {value!r}.") from exc


def normalize_int(value: Any, field_name: str) -> int:
    """Normalisiert einen Integer."""
    try:
        if isinstance(value, bool):
            raise VariantDefaultsError(f"{field_name} must be an integer.")

        return int(value)
    except VariantDefaultsError:
        raise
    except Exception as exc:
        raise VariantDefaultsError(f"{field_name} must be an integer.") from exc


def normalize_string_tuple(values: Iterable[Any]) -> tuple[str, ...]:
    """Normalisiert Stringlisten ohne Duplikate."""
    result: list[str] = []
    seen: set[str] = set()

    for value in values or ():
        cleaned = clean_optional_string(value)
        if not cleaned or cleaned in seen:
            continue
        result.append(cleaned)
        seen.add(cleaned)

    return tuple(result)


def normalize_metadata(value: Mapping[str, Any] | None) -> dict[str, Any]:
    """Normalisiert Metadata JSON-kompatibel."""
    if value is None:
        return {}

    if not isinstance(value, Mapping):
        raise VariantDefaultsError("metadata must be a mapping.")

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


def clean_required_string(value: Any, field_name: str) -> str:
    """Normalisiert einen Pflicht-String."""
    try:
        cleaned = str(value).strip()

        if not cleaned:
            raise VariantDefaultsError(f"{field_name} is required.")

        return cleaned
    except VariantDefaultsError:
        raise
    except Exception as exc:
        raise VariantDefaultsError(f"{field_name} must be string-like.") from exc


def clean_optional_string(value: Any) -> str | None:
    """Normalisiert einen optionalen String."""
    if value is None:
        return None

    try:
        cleaned = str(value).strip()
        return cleaned or None
    except Exception:
        return None


def clear_variant_defaults_caches() -> None:
    """Leert interne Parser-Caches."""
    parse_variant_mode_value.cache_clear()
    parse_variant_status_value.cache_clear()
    parse_source_kind_value.cache_clear()


__all__ = [
    "DEFAULT_VARIANT_ID",
    "DEFAULT_VARIANT_LABEL",
    "SAFE_VARIANT_ID_RE",
    "VARIANT_DEFAULTS_SCHEMA_VERSION",
    "VARIANT_DOCUMENT_SCHEMA_VERSION",
    "VARIANT_INDEX_DOCUMENT_SCHEMA_VERSION",
    "VariantDefaults",
    "VariantDefaultsError",
    "VariantDocumentDefaults",
    "VariantIndexDefaults",
    "VariantMode",
    "VariantSourceKind",
    "VariantStatus",
    "assert_valid_variant_document",
    "assert_valid_variant_index_document",
    "build_default_variant_document",
    "build_variant_defaults",
    "clean_optional_string",
    "clean_required_string",
    "clear_variant_defaults_caches",
    "humanize_variant_id",
    "normalize_create_request",
    "normalize_enum_key",
    "normalize_int",
    "normalize_metadata",
    "normalize_metadata_value",
    "normalize_overrides_mapping_safe",
    "normalize_string_tuple",
    "normalize_variant_id",
    "normalize_variant_set",
    "parse_source_kind_value",
    "parse_variant_mode_value",
    "parse_variant_status_value",
    "validate_variant_document",
    "validate_variant_index_document",
    "variant_defaults_from_create_request",
    "variant_defaults_from_planning_result",
    "variant_defaults_from_variant_set",
    "variant_document_defaults_from_mapping",
    "variant_documents_from_create_request",
    "variant_documents_from_variant_set",
    "variants_index_document_from_create_request",
]