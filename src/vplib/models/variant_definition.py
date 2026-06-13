# services/vectoplan-library/src/vplib/models/variant_definition.py
"""
VariantDefinition model for the VPLIB package engine.

Diese Datei beschreibt Varianten innerhalb einer VPLIB-Family.

Grundregel:
Eine Variante beschreibt keine komplette neue Family. Eine Variante enthält nur
Overrides gegenüber der Family- oder Default-Definition.

Rolle dieser Datei:

    CreateRequest.variants
    -> VariantDefinition / VariantSet
    -> variants/index.json
    -> variants/default.json
    -> variants/<variant_id>.json
    -> later: resolver / package builder / validator

Technische Namen, JSON-Keys und Variablen bleiben Englisch.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from enum import Enum
from functools import lru_cache
from typing import Any, Final, Iterable, Mapping, Sequence


VARIANT_DEFINITION_SCHEMA_VERSION: Final[str] = "vplib.variant_definition.v1"
VARIANT_INDEX_SCHEMA_VERSION: Final[str] = "vplib.variants.index.v1"
VARIANT_DOCUMENT_SCHEMA_VERSION: Final[str] = "vplib.variant.v1"

DEFAULT_VARIANT_ID: Final[str] = "default"

SAFE_VARIANT_ID_RE: Final[re.Pattern[str]] = re.compile(
    r"^[a-z0-9][a-z0-9._-]*[a-z0-9]$|^[a-z0-9]$"
)

SAFE_FIELD_PATH_RE: Final[re.Pattern[str]] = re.compile(
    r"^[a-zA-Z0-9_][a-zA-Z0-9_.-]*[a-zA-Z0-9_]$|^[a-zA-Z0-9_]$"
)

FORBIDDEN_OVERRIDE_PREFIXES: Final[tuple[str, ...]] = (
    "schema_version",
    "vplib_version",
    "package_id",
    "family_id",
    "family_slug",
    "family_name",
    "classification",
    "classification_path",
    "domain",
    "domain_id",
    "domain_label",
    "tab",
    "tab_id",
    "tab_label",
    "category",
    "category_id",
    "category_label",
    "subcategory",
    "subcategory_id",
    "subcategory_label",
    "object_kind",
    "active_modules",
    "required_modules",
    "optional_modules",
    "module_versions",
)

ALLOWED_OVERRIDE_PREFIXES: Final[tuple[str, ...]] = (
    "variant",
    "editor",
    "placement",
    "targeting",
    "anchors",
    "sockets",
    "ports",
    "render",
    "physical",
    "material",
    "calculation",
    "analysis",
    "dynamic",
    "manufacturer",
)

TECHNICAL_VARIANT_FIELDS: Final[tuple[str, ...]] = (
    "schema_version",
    "variant_id",
    "label",
    "description",
    "inherits_from",
    "enabled",
    "sort_order",
    "tags",
    "overrides",
    "metadata",
)


class VariantDefinitionError(ValueError):
    """Wird ausgelöst, wenn Varianten ungültig sind."""


class VariantMode(str, Enum):
    """Variantenmodus einer Family."""

    SINGLE = "single"
    MULTIPLE = "multiple"

    @property
    def key(self) -> str:
        return str(self.value)


class VariantOverridePolicy(str, Enum):
    """Regel, wie streng Overrides geprüft werden."""

    STRICT = "strict"
    PERMISSIVE = "permissive"

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


@dataclass(frozen=True, slots=True)
class VariantOverride:
    """
    Einzelner Override-Wert.

    field_path ist ein dotted path, z. B.:
    - physical.wall_thickness_m
    - material.density_kg_m3
    - render.fallback_color
    - calculation.variables.wall_thickness
    """

    field_path: str
    value: Any
    reason: str = ""

    def normalized(self, *, policy: str = VariantOverridePolicy.STRICT.value) -> "VariantOverride":
        field_path = normalize_field_path(self.field_path)
        policy_value = parse_override_policy_value(policy)

        if policy_value == VariantOverridePolicy.STRICT.value:
            assert_override_field_allowed(field_path)

        return VariantOverride(
            field_path=field_path,
            value=normalize_override_value(self.value),
            reason=clean_optional_string(self.reason) or "",
        )

    def to_dict(self) -> dict[str, Any]:
        normalized = self.normalized()

        return {
            "field_path": normalized.field_path,
            "value": normalized.value,
            "reason": normalized.reason,
        }


@dataclass(frozen=True, slots=True)
class VariantDefinition:
    """
    Eine konkrete auswählbare Variante einer VPLIB-Family.

    Default-Variante:
    - variant_id == "default"
    - darf vollständiger befüllt sein als reine Varianten
    - bleibt trotzdem im Variantensystem

    Nicht-default-Varianten:
    - enthalten nur Overrides
    - sollen keine Family-Identität oder Klassifikation überschreiben
    """

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

    def normalized(
        self,
        *,
        policy: str = VariantOverridePolicy.STRICT.value,
        allow_default_without_inherits: bool = True,
    ) -> "VariantDefinition":
        variant_id = normalize_variant_id(self.variant_id)
        label = clean_optional_string(self.label) or humanize_variant_id(variant_id)
        description = clean_optional_string(self.description) or ""
        inherits_from = clean_optional_string(self.inherits_from)
        enabled = bool(self.enabled)
        status = parse_variant_status_value(self.status)
        sort_order = normalize_int(self.sort_order, "sort_order")
        tags = normalize_string_tuple(self.tags)
        metadata = dict(self.metadata or {})

        if variant_id == DEFAULT_VARIANT_ID and allow_default_without_inherits:
            inherits_from = None
        elif not inherits_from:
            inherits_from = DEFAULT_VARIANT_ID

        if inherits_from is not None:
            inherits_from = normalize_variant_id(inherits_from)
            if inherits_from == variant_id:
                raise VariantDefinitionError(
                    f"Variant {variant_id!r} cannot inherit from itself."
                )

        normalized_overrides = normalize_overrides_mapping(
            self.overrides,
            policy=policy,
        )

        return VariantDefinition(
            variant_id=variant_id,
            label=label,
            description=description,
            inherits_from=inherits_from,
            enabled=enabled,
            status=status,
            sort_order=sort_order,
            tags=tags,
            overrides=normalized_overrides,
            metadata=metadata,
        )

    @property
    def is_default(self) -> bool:
        return self.normalized().variant_id == DEFAULT_VARIANT_ID

    @property
    def is_active(self) -> bool:
        normalized = self.normalized()
        return normalized.enabled and normalized.status == VariantStatus.ACTIVE.value

    def with_override(self, field_path: str, value: Any, *, reason: str = "") -> "VariantDefinition":
        normalized = self.normalized()
        overrides = dict(normalized.overrides)
        override = VariantOverride(field_path=field_path, value=value, reason=reason).normalized()
        set_nested_override(overrides, override.field_path, override.value)

        return VariantDefinition(
            variant_id=normalized.variant_id,
            label=normalized.label,
            description=normalized.description,
            inherits_from=normalized.inherits_from,
            enabled=normalized.enabled,
            status=normalized.status,
            sort_order=normalized.sort_order,
            tags=normalized.tags,
            overrides=overrides,
            metadata=dict(normalized.metadata),
        ).normalized()

    def to_index_entry(self) -> dict[str, Any]:
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

    def to_document(self) -> dict[str, Any]:
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

    def to_dict(self) -> dict[str, Any]:
        return self.to_document()


@dataclass(frozen=True, slots=True)
class VariantSet:
    """
    Vollständige Variantenmenge einer Family.

    Garantien nach normalized():
    - default_variant_id existiert
    - variant_ids sind eindeutig
    - bei SINGLE gibt es genau eine aktive Variante
    - alle inherits_from-Ziele existieren oder sind None
    """

    variants: tuple[VariantDefinition, ...]
    default_variant_id: str = DEFAULT_VARIANT_ID
    mode: str = VariantMode.SINGLE.value
    policy: str = VariantOverridePolicy.STRICT.value
    metadata: Mapping[str, Any] = field(default_factory=dict)

    def normalized(self) -> "VariantSet":
        mode = parse_variant_mode_value(self.mode)
        policy = parse_override_policy_value(self.policy)
        default_variant_id = normalize_variant_id(self.default_variant_id or DEFAULT_VARIANT_ID)
        metadata = dict(self.metadata or {})

        normalized_variants = tuple(
            variant.normalized(policy=policy)
            for variant in self.variants or ()
        )

        if not normalized_variants:
            normalized_variants = (
                VariantDefinition(
                    variant_id=default_variant_id,
                    label="Default",
                    description="Default variant.",
                    inherits_from=None,
                    sort_order=0,
                    overrides={},
                ).normalized(policy=policy),
            )

        variants_by_id: dict[str, VariantDefinition] = {}

        for variant in normalized_variants:
            if variant.variant_id in variants_by_id:
                raise VariantDefinitionError(f"Duplicate variant_id {variant.variant_id!r}.")
            variants_by_id[variant.variant_id] = variant

        if default_variant_id not in variants_by_id:
            default_variant = VariantDefinition(
                variant_id=default_variant_id,
                label="Default",
                description="Default variant.",
                inherits_from=None,
                sort_order=0,
                overrides={},
            ).normalized(policy=policy)
            variants_by_id[default_variant_id] = default_variant

        for variant in tuple(variants_by_id.values()):
            if variant.inherits_from and variant.inherits_from not in variants_by_id:
                raise VariantDefinitionError(
                    f"Variant {variant.variant_id!r} inherits from unknown variant "
                    f"{variant.inherits_from!r}."
                )

        sorted_variants = tuple(
            sorted(
                variants_by_id.values(),
                key=lambda variant: (
                    0 if variant.variant_id == default_variant_id else 1,
                    variant.sort_order,
                    variant.variant_id,
                ),
            )
        )

        active_variants = tuple(variant for variant in sorted_variants if variant.is_active)
        if mode == VariantMode.SINGLE.value and len(active_variants) > 1:
            mode = VariantMode.MULTIPLE.value

        return VariantSet(
            variants=sorted_variants,
            default_variant_id=default_variant_id,
            mode=mode,
            policy=policy,
            metadata=metadata,
        )

    @property
    def variant_ids(self) -> tuple[str, ...]:
        return tuple(variant.variant_id for variant in self.normalized().variants)

    @property
    def active_variants(self) -> tuple[VariantDefinition, ...]:
        return tuple(variant for variant in self.normalized().variants if variant.is_active)

    @property
    def default_variant(self) -> VariantDefinition:
        normalized = self.normalized()

        for variant in normalized.variants:
            if variant.variant_id == normalized.default_variant_id:
                return variant

        raise VariantDefinitionError(
            f"Default variant {normalized.default_variant_id!r} does not exist."
        )

    def get_variant(self, variant_id: Any) -> VariantDefinition | None:
        normalized_id = normalize_variant_id(variant_id)

        for variant in self.normalized().variants:
            if variant.variant_id == normalized_id:
                return variant

        return None

    def require_variant(self, variant_id: Any) -> VariantDefinition:
        variant = self.get_variant(variant_id)

        if variant is None:
            raise VariantDefinitionError(f"Unknown variant_id {variant_id!r}.")

        return variant

    def with_variant(self, variant: VariantDefinition) -> "VariantSet":
        normalized = self.normalized()
        new_variant = variant.normalized(policy=normalized.policy)

        variants_by_id = {
            current.variant_id: current
            for current in normalized.variants
        }
        variants_by_id[new_variant.variant_id] = new_variant

        return VariantSet(
            variants=tuple(variants_by_id.values()),
            default_variant_id=normalized.default_variant_id,
            mode=normalized.mode,
            policy=normalized.policy,
            metadata=dict(normalized.metadata),
        ).normalized()

    def to_index_document(self) -> dict[str, Any]:
        normalized = self.normalized()

        return {
            "schema_version": VARIANT_INDEX_SCHEMA_VERSION,
            "mode": normalized.mode,
            "default_variant_id": normalized.default_variant_id,
            "variant_ids": list(normalized.variant_ids),
            "variants": [variant.to_index_entry() for variant in normalized.variants],
            "metadata": dict(normalized.metadata),
        }

    def to_variant_documents(self) -> dict[str, dict[str, Any]]:
        normalized = self.normalized()

        return {
            f"{variant.variant_id}.json": variant.to_document()
            for variant in normalized.variants
        }

    def to_dict(self) -> dict[str, Any]:
        normalized = self.normalized()

        return {
            "schema_version": VARIANT_DEFINITION_SCHEMA_VERSION,
            "mode": normalized.mode,
            "policy": normalized.policy,
            "default_variant_id": normalized.default_variant_id,
            "variant_ids": list(normalized.variant_ids),
            "variants": [variant.to_document() for variant in normalized.variants],
            "metadata": dict(normalized.metadata),
        }


def variant_definition_from_mapping(data: Mapping[str, Any]) -> VariantDefinition:
    """Baut eine VariantDefinition aus einem Mapping."""
    try:
        if not isinstance(data, Mapping):
            raise VariantDefinitionError("VariantDefinition data must be a mapping.")

        return VariantDefinition(
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
    except VariantDefinitionError:
        raise
    except Exception as exc:
        raise VariantDefinitionError(f"Could not build VariantDefinition: {exc}") from exc


def variant_set_from_mapping(data: Mapping[str, Any]) -> VariantSet:
    """Baut ein VariantSet aus einem Mapping."""
    try:
        if not isinstance(data, Mapping):
            raise VariantDefinitionError("VariantSet data must be a mapping.")

        variants_data = data.get("variants", ()) or ()
        variants = tuple(
            variant_definition_from_mapping(item)
            for item in variants_data
            if isinstance(item, Mapping)
        )

        return VariantSet(
            variants=variants,
            default_variant_id=data.get("default_variant_id", DEFAULT_VARIANT_ID),
            mode=data.get("mode", VariantMode.SINGLE.value),
            policy=data.get("policy", VariantOverridePolicy.STRICT.value),
            metadata=dict(data.get("metadata", {}) or {}),
        ).normalized()
    except VariantDefinitionError:
        raise
    except Exception as exc:
        raise VariantDefinitionError(f"Could not build VariantSet: {exc}") from exc


def variant_set_from_create_request(value: Any) -> VariantSet:
    """
    Baut ein VariantSet aus einem CreateRequest-ähnlichen Objekt.

    Diese Funktion nutzt Duck-Typing, damit kein harter Importzyklus entsteht.
    """
    try:
        normalized = value.normalized() if hasattr(value, "normalized") else value

        variants_request = getattr(normalized, "variants", None)
        if variants_request is None:
            return VariantSet(variants=tuple()).normalized()

        mode = getattr(variants_request, "mode", VariantMode.SINGLE.value)
        default_variant_id = getattr(
            variants_request,
            "default_variant_id",
            DEFAULT_VARIANT_ID,
        )

        variants: list[VariantDefinition] = []
        for variant in getattr(variants_request, "variants", ()) or ():
            variant_normalized = variant.normalized() if hasattr(variant, "normalized") else variant

            if isinstance(variant_normalized, Mapping):
                variants.append(variant_definition_from_mapping(variant_normalized))
                continue

            variants.append(
                VariantDefinition(
                    variant_id=getattr(variant_normalized, "variant_id", DEFAULT_VARIANT_ID),
                    label=getattr(variant_normalized, "label", None),
                    description=getattr(variant_normalized, "description", ""),
                    inherits_from=getattr(variant_normalized, "inherits_from", DEFAULT_VARIANT_ID),
                    overrides=dict(getattr(variant_normalized, "overrides", {}) or {}),
                ).normalized()
            )

        return VariantSet(
            variants=tuple(variants),
            default_variant_id=default_variant_id,
            mode=mode,
        ).normalized()
    except VariantDefinitionError:
        raise
    except Exception as exc:
        raise VariantDefinitionError(f"Could not build VariantSet from create request: {exc}") from exc


def normalize_overrides_mapping(
    overrides: Mapping[str, Any],
    *,
    policy: str = VariantOverridePolicy.STRICT.value,
) -> dict[str, Any]:
    """
    Normalisiert ein Overrides-Mapping.

    Akzeptiert zwei Formen:
    1. nested:
       {"physical": {"wall_thickness_m": 0.24}}
    2. dotted:
       {"physical.wall_thickness_m": 0.24}
    """
    policy_value = parse_override_policy_value(policy)

    if not isinstance(overrides, Mapping):
        raise VariantDefinitionError("Variant overrides must be an object.")

    result: dict[str, Any] = {}

    for key, value in overrides.items():
        key_value = clean_required_string(key, "override key")

        if "." in key_value:
            field_path = normalize_field_path(key_value)
            if policy_value == VariantOverridePolicy.STRICT.value:
                assert_override_field_allowed(field_path)
            set_nested_override(result, field_path, normalize_override_value(value))
            continue

        top_level_key = normalize_field_path(key_value)
        if policy_value == VariantOverridePolicy.STRICT.value:
            assert_override_field_allowed(top_level_key)

        if isinstance(value, Mapping):
            result[top_level_key] = normalize_nested_mapping(
                value,
                prefix=top_level_key,
                policy=policy_value,
            )
        else:
            result[top_level_key] = normalize_override_value(value)

    return result


def normalize_nested_mapping(
    value: Mapping[str, Any],
    *,
    prefix: str,
    policy: str,
) -> dict[str, Any]:
    """Normalisiert verschachtelte Override-Mappings."""
    result: dict[str, Any] = {}

    for key, child_value in value.items():
        key_value = normalize_field_key(key)
        field_path = f"{prefix}.{key_value}"

        if policy == VariantOverridePolicy.STRICT.value:
            assert_override_field_allowed(field_path)

        if isinstance(child_value, Mapping):
            result[key_value] = normalize_nested_mapping(
                child_value,
                prefix=field_path,
                policy=policy,
            )
        else:
            result[key_value] = normalize_override_value(child_value)

    return result


def normalize_override_value(value: Any) -> Any:
    """
    Normalisiert einzelne Override-Werte.

    Erlaubt JSON-kompatible Grundtypen, Listen und Dicts.
    """
    if value is None:
        return None

    if isinstance(value, (str, int, float, bool)):
        return value

    if isinstance(value, Sequence) and not isinstance(value, (str, bytes, bytearray)):
        return [normalize_override_value(item) for item in value]

    if isinstance(value, Mapping):
        return {
            normalize_field_key(key): normalize_override_value(child_value)
            for key, child_value in value.items()
        }

    raise VariantDefinitionError(
        f"Unsupported override value type {type(value).__name__!r}."
    )


def set_nested_override(target: dict[str, Any], field_path: str, value: Any) -> None:
    """Setzt einen dotted field_path in ein verschachteltes Dict."""
    parts = field_path.split(".")
    current: dict[str, Any] = target

    for part in parts[:-1]:
        child = current.get(part)

        if child is None:
            child = {}
            current[part] = child

        if not isinstance(child, dict):
            raise VariantDefinitionError(
                f"Cannot set nested override for {field_path!r}; "
                f"{part!r} already contains a non-object value."
            )

        current = child

    current[parts[-1]] = normalize_override_value(value)


def flatten_overrides(overrides: Mapping[str, Any], *, prefix: str = "") -> dict[str, Any]:
    """Flacht verschachtelte Overrides zu dotted field paths ab."""
    result: dict[str, Any] = {}

    for key, value in overrides.items():
        key_value = normalize_field_key(key)
        path = f"{prefix}.{key_value}" if prefix else key_value

        if isinstance(value, Mapping):
            result.update(flatten_overrides(value, prefix=path))
        else:
            result[path] = value

    return result


def assert_override_field_allowed(field_path: str) -> None:
    """Prüft, ob ein Override-Feld erlaubt ist."""
    normalized_path = normalize_field_path(field_path)

    if normalized_path in TECHNICAL_VARIANT_FIELDS:
        return

    for forbidden_prefix in FORBIDDEN_OVERRIDE_PREFIXES:
        if normalized_path == forbidden_prefix or normalized_path.startswith(f"{forbidden_prefix}."):
            raise VariantDefinitionError(
                f"Variant override field {normalized_path!r} is forbidden."
            )

    top_level = normalized_path.split(".", 1)[0]
    if top_level not in ALLOWED_OVERRIDE_PREFIXES:
        raise VariantDefinitionError(
            f"Variant override field {normalized_path!r} must start with one of: "
            f"{', '.join(ALLOWED_OVERRIDE_PREFIXES)}."
        )


def normalize_field_path(value: Any) -> str:
    """Normalisiert einen dotted field path."""
    raw = clean_required_string(value, "field_path")
    parts = [normalize_field_key(part) for part in raw.split(".") if part.strip()]

    if not parts:
        raise VariantDefinitionError("field_path is empty.")

    field_path = ".".join(parts)

    if not SAFE_FIELD_PATH_RE.match(field_path):
        raise VariantDefinitionError(f"Unsafe field_path {value!r}.")

    return field_path


def normalize_field_key(value: Any) -> str:
    """Normalisiert einen einzelnen Field-Key."""
    raw = clean_required_string(value, "field key")
    key = (
        raw.strip()
        .lower()
        .replace(" ", "_")
        .replace("-", "_")
        .replace("/", "_")
        .replace("\\", "_")
    )

    if not key:
        raise VariantDefinitionError("Field key is empty.")

    if not re.match(r"^[a-zA-Z0-9_][a-zA-Z0-9_]*$", key):
        raise VariantDefinitionError(f"Unsafe field key {value!r}.")

    return key


def normalize_variant_id(value: Any) -> str:
    """Normalisiert eine Variant-ID."""
    raw = clean_required_string(value, "variant_id")
    variant_id = (
        raw.lower()
        .replace(" ", "_")
        .replace("-", "_")
        .replace("/", "_")
        .replace("\\", "_")
    )

    if not SAFE_VARIANT_ID_RE.match(variant_id):
        raise VariantDefinitionError(f"Invalid variant_id {value!r}.")

    return variant_id


def humanize_variant_id(value: Any) -> str:
    """Erzeugt ein einfaches Label aus einer Variant-ID."""
    variant_id = normalize_variant_id(value)

    if variant_id == DEFAULT_VARIANT_ID:
        return "Default"

    return variant_id.replace("_", " ").replace(".", " ").title()


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
            "variants": VariantMode.MULTIPLE.value,
            "many": VariantMode.MULTIPLE.value,
        }

        if raw in aliases:
            return aliases[raw]

        return VariantMode(raw).value
    except Exception as exc:
        raise VariantDefinitionError(f"Invalid variant mode {value!r}.") from exc


@lru_cache(maxsize=128)
def parse_override_policy_value(value: Any) -> str:
    """Parst VariantOverridePolicy."""
    try:
        if isinstance(value, VariantOverridePolicy):
            return value.value

        raw = normalize_enum_key(value)
        return VariantOverridePolicy(raw).value
    except Exception as exc:
        raise VariantDefinitionError(f"Invalid variant override policy {value!r}.") from exc


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
        raise VariantDefinitionError(f"Invalid variant status {value!r}.") from exc


def normalize_enum_key(value: Any) -> str:
    """Normalisiert Enum-ähnliche Werte."""
    try:
        raw = str(value).strip()
        if not raw:
            raise VariantDefinitionError("Enum value is required.")

        return (
            raw.lower()
            .replace(" ", "_")
            .replace("-", "_")
            .replace("/", "_")
            .replace("\\", "_")
        )
    except VariantDefinitionError:
        raise
    except Exception as exc:
        raise VariantDefinitionError(f"Invalid enum value {value!r}.") from exc


def normalize_string_tuple(values: Iterable[Any]) -> tuple[str, ...]:
    """Normalisiert eine Stringliste ohne Duplikate."""
    result: list[str] = []
    seen: set[str] = set()

    for value in values or ():
        cleaned = clean_optional_string(value)
        if not cleaned or cleaned in seen:
            continue
        result.append(cleaned)
        seen.add(cleaned)

    return tuple(result)


def normalize_int(value: Any, field_name: str) -> int:
    """Normalisiert einen Integer."""
    try:
        if isinstance(value, bool):
            raise VariantDefinitionError(f"{field_name} must be an integer.")

        return int(value)
    except VariantDefinitionError:
        raise
    except Exception as exc:
        raise VariantDefinitionError(f"{field_name} must be an integer.") from exc


def clean_required_string(value: Any, field_name: str) -> str:
    """Normalisiert einen Pflicht-String."""
    try:
        cleaned = str(value).strip()

        if not cleaned:
            raise VariantDefinitionError(f"{field_name} is required.")

        return cleaned
    except VariantDefinitionError:
        raise
    except Exception as exc:
        raise VariantDefinitionError(f"{field_name} must be string-like.") from exc


def clean_optional_string(value: Any) -> str | None:
    """Normalisiert einen optionalen String."""
    if value is None:
        return None

    try:
        cleaned = str(value).strip()
        return cleaned or None
    except Exception:
        return None


def clear_variant_definition_caches() -> None:
    """Leert interne Parser-Caches."""
    parse_variant_mode_value.cache_clear()
    parse_override_policy_value.cache_clear()
    parse_variant_status_value.cache_clear()


__all__ = [
    "ALLOWED_OVERRIDE_PREFIXES",
    "DEFAULT_VARIANT_ID",
    "FORBIDDEN_OVERRIDE_PREFIXES",
    "SAFE_FIELD_PATH_RE",
    "SAFE_VARIANT_ID_RE",
    "TECHNICAL_VARIANT_FIELDS",
    "VARIANT_DEFINITION_SCHEMA_VERSION",
    "VARIANT_DOCUMENT_SCHEMA_VERSION",
    "VARIANT_INDEX_SCHEMA_VERSION",
    "VariantDefinition",
    "VariantDefinitionError",
    "VariantMode",
    "VariantOverride",
    "VariantOverridePolicy",
    "VariantSet",
    "VariantStatus",
    "assert_override_field_allowed",
    "clean_optional_string",
    "clean_required_string",
    "clear_variant_definition_caches",
    "flatten_overrides",
    "humanize_variant_id",
    "normalize_enum_key",
    "normalize_field_key",
    "normalize_field_path",
    "normalize_int",
    "normalize_nested_mapping",
    "normalize_override_value",
    "normalize_overrides_mapping",
    "normalize_string_tuple",
    "normalize_variant_id",
    "parse_override_policy_value",
    "parse_variant_mode_value",
    "parse_variant_status_value",
    "set_nested_override",
    "variant_definition_from_mapping",
    "variant_set_from_create_request",
    "variant_set_from_mapping",
]