# services/vectoplan-library/src/library/definitions/definition_models.py
"""
Data models for the VECTOPLAN Library Definitions layer.

This module contains only lightweight, import-safe model code:
- no filesystem access
- no JSON loading
- no service imports
- no Flask imports
- no scan execution during import

The registry will load JSON datasets and use these models to normalize and
validate:
- object kinds
- family profiles
- variant profiles
- variable definitions
- units
- materials
- document types
- profile bindings

The models are intentionally defensive:
- mappings are copied before use
- lists are normalized to tuples
- unknown extra fields are preserved in `extra`
- invalid data raises explicit Definition* errors
- to_dict() payloads are stable for APIs and frontend options
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any, Dict, Iterable, List, Mapping, Optional, Sequence, Tuple


DEFINITION_MODELS_VERSION = "0.1.0"
DEFINITION_SCHEMA_VERSION = "1.0"
DEFINITION_DEFAULT_VERSION = "v1"

DEFAULT_LANGUAGE = "de"

SUPPORTED_VALUE_TYPES: Tuple[str, ...] = (
    "string",
    "text",
    "number",
    "integer",
    "boolean",
    "enum",
    "multi_enum",
    "object",
    "array",
    "document_list",
    "money",
    "url",
    "date",
)

SUPPORTED_FIELD_WIDGETS: Tuple[str, ...] = (
    "input",
    "textarea",
    "number",
    "select",
    "multi_select",
    "checkbox",
    "document_list",
    "money",
    "url",
    "date",
    "readonly",
)

_ID_PATTERN = re.compile(r"^[a-z][a-z0-9]*(?:[._-][a-z0-9]+)*$")
_VARIABLE_KEY_PATTERN = re.compile(r"^[a-z][a-z0-9]*(?:[._][a-z0-9]+)*$")
_TAXONOMY_PART_PATTERN = re.compile(r"^[a-z][a-z0-9]*(?:[_-][a-z0-9]+)*$")


class DefinitionError(Exception):
    """Base exception for all definitions model errors."""


class DefinitionValidationError(DefinitionError):
    """Raised when a definition has invalid field values."""


class DefinitionDatasetError(DefinitionError):
    """Raised when a dataset structure is invalid."""


class DefinitionReferenceError(DefinitionError):
    """Raised when a definition references a missing or incompatible item."""


def _is_mapping(value: Any) -> bool:
    return isinstance(value, Mapping)


def _copy_mapping(value: Optional[Mapping[str, Any]]) -> Dict[str, Any]:
    if not value:
        return {}
    return dict(value)


def _as_clean_string(value: Any, *, default: str = "") -> str:
    if value is None:
        return default
    return str(value).strip()


def _as_optional_string(value: Any) -> Optional[str]:
    clean = _as_clean_string(value)
    return clean or None


def _as_bool(value: Any, *, default: bool = False) -> bool:
    if value is None:
        return default
    if isinstance(value, bool):
        return value
    if isinstance(value, (int, float)):
        return bool(value)
    if isinstance(value, str):
        clean = value.strip().lower()
        if clean in {"1", "true", "yes", "y", "on", "active", "enabled"}:
            return True
        if clean in {"0", "false", "no", "n", "off", "inactive", "disabled"}:
            return False
    return default


def _as_tuple(value: Any) -> Tuple[Any, ...]:
    if value is None:
        return tuple()
    if isinstance(value, tuple):
        return value
    if isinstance(value, list):
        return tuple(value)
    if isinstance(value, set):
        return tuple(value)
    return (value,)


def _as_string_tuple(value: Any, *, drop_empty: bool = True) -> Tuple[str, ...]:
    items: List[str] = []
    for item in _as_tuple(value):
        clean = _as_clean_string(item)
        if clean or not drop_empty:
            items.append(clean)
    return tuple(items)


def _as_mapping_tuple(value: Any) -> Tuple[Mapping[str, Any], ...]:
    items: List[Mapping[str, Any]] = []
    for item in _as_tuple(value):
        if _is_mapping(item):
            items.append(dict(item))
    return tuple(items)


def _merge_extra(data: Mapping[str, Any], known_keys: Iterable[str]) -> Dict[str, Any]:
    known = set(known_keys)
    return {key: value for key, value in data.items() if key not in known}


def _require_mapping(data: Any, *, context: str) -> Mapping[str, Any]:
    if not _is_mapping(data):
        raise DefinitionValidationError(f"{context} must be an object/mapping")
    return data


def _require_string_id(
    value: Any,
    *,
    field_name: str,
    context: str,
    pattern: re.Pattern[str] = _ID_PATTERN,
) -> str:
    clean = _as_clean_string(value)
    if not clean:
        raise DefinitionValidationError(f"{context}.{field_name} is required")
    if not pattern.match(clean):
        raise DefinitionValidationError(
            f"{context}.{field_name} has invalid format: {clean!r}"
        )
    return clean


def _validate_optional_id(
    value: Any,
    *,
    field_name: str,
    context: str,
    pattern: re.Pattern[str] = _ID_PATTERN,
) -> Optional[str]:
    clean = _as_optional_string(value)
    if clean is None:
        return None
    if not pattern.match(clean):
        raise DefinitionValidationError(
            f"{context}.{field_name} has invalid format: {clean!r}"
        )
    return clean


def _validate_id_tuple(
    values: Any,
    *,
    field_name: str,
    context: str,
    pattern: re.Pattern[str] = _ID_PATTERN,
) -> Tuple[str, ...]:
    result: List[str] = []
    seen = set()

    for raw_value in _as_tuple(values):
        clean = _as_clean_string(raw_value)
        if not clean:
            continue
        if not pattern.match(clean):
            raise DefinitionValidationError(
                f"{context}.{field_name} contains invalid id: {clean!r}"
            )
        if clean not in seen:
            result.append(clean)
            seen.add(clean)

    return tuple(result)


def _validate_taxonomy_path_parts(
    values: Any,
    *,
    field_name: str,
    context: str,
) -> Tuple[str, ...]:
    result: List[str] = []

    for raw_value in _as_tuple(values):
        clean = _as_clean_string(raw_value)
        if not clean:
            continue
        if not _TAXONOMY_PART_PATTERN.match(clean):
            raise DefinitionValidationError(
                f"{context}.{field_name} contains invalid taxonomy part: {clean!r}"
            )
        result.append(clean)

    return tuple(result)


def _normalize_label(value: Any, *, fallback: str) -> str:
    clean = _as_clean_string(value)
    return clean or fallback


def _normalize_i18n_mapping(value: Any) -> Dict[str, str]:
    if not _is_mapping(value):
        return {}

    result: Dict[str, str] = {}
    for lang, text in value.items():
        clean_lang = _as_clean_string(lang)
        clean_text = _as_clean_string(text)
        if clean_lang and clean_text:
            result[clean_lang] = clean_text

    return result


def _normalize_options(value: Any) -> Tuple[Dict[str, Any], ...]:
    """
    Normalize enum/select options.

    Accepted shorthand:
    - ["brick", "concrete"]
    - [{"id": "brick", "label": "Ziegel"}]
    """
    result: List[Dict[str, Any]] = []
    seen = set()

    for item in _as_tuple(value):
        if _is_mapping(item):
            raw = dict(item)
            option_id = _as_clean_string(raw.get("id") or raw.get("value") or raw.get("key"))
            if not option_id:
                continue
            label = _normalize_label(raw.get("label"), fallback=option_id)
            option = {
                **raw,
                "id": option_id,
                "value": raw.get("value", option_id),
                "label": label,
                "active": _as_bool(raw.get("active"), default=True),
            }
        else:
            option_id = _as_clean_string(item)
            if not option_id:
                continue
            option = {
                "id": option_id,
                "value": option_id,
                "label": option_id,
                "active": True,
            }

        if option["id"] in seen:
            continue

        seen.add(option["id"])
        result.append(option)

    return tuple(result)


def _normalize_validation(value: Any) -> Dict[str, Any]:
    if not _is_mapping(value):
        return {}
    return dict(value)


def _normalize_ui(value: Any) -> Dict[str, Any]:
    if not _is_mapping(value):
        return {}
    return dict(value)


def _normalize_metadata(value: Any) -> Dict[str, Any]:
    if not _is_mapping(value):
        return {}
    return dict(value)


def _dict_without_none(payload: Mapping[str, Any]) -> Dict[str, Any]:
    return {key: value for key, value in payload.items() if value is not None}


def _dict_without_empty(payload: Mapping[str, Any]) -> Dict[str, Any]:
    result: Dict[str, Any] = {}

    for key, value in payload.items():
        if value is None:
            continue
        if value == "":
            continue
        if value == []:
            continue
        if value == {}:
            continue
        if value == ():
            continue
        result[key] = value

    return result


def _tuple_to_list(value: Sequence[Any]) -> List[Any]:
    return list(value or [])


def _mapping_tuple_to_list(value: Sequence[Mapping[str, Any]]) -> List[Dict[str, Any]]:
    return [dict(item) for item in value or []]


@dataclass(frozen=True)
class BaseDefinition:
    """
    Shared base model for definition items.

    `extra` deliberately preserves unknown fields so that the definitions layer
    can evolve without breaking older code paths.
    """

    id: str
    label: str
    description: str = ""
    active: bool = True
    sort_order: int = 1000
    tags: Tuple[str, ...] = field(default_factory=tuple)
    aliases: Tuple[str, ...] = field(default_factory=tuple)
    i18n: Dict[str, str] = field(default_factory=dict)
    metadata: Dict[str, Any] = field(default_factory=dict)
    extra: Dict[str, Any] = field(default_factory=dict)

    def is_active(self) -> bool:
        return bool(self.active)

    def label_for(self, language: str = DEFAULT_LANGUAGE) -> str:
        clean_language = _as_clean_string(language, default=DEFAULT_LANGUAGE)
        return self.i18n.get(clean_language) or self.label

    def to_option(self, *, language: str = DEFAULT_LANGUAGE) -> Dict[str, Any]:
        return {
            "id": self.id,
            "label": self.label_for(language),
            "description": self.description,
            "active": self.active,
            "sort_order": self.sort_order,
        }

    def to_dict(
        self,
        *,
        include_extra: bool = True,
        include_inactive: bool = True,
        language: str = DEFAULT_LANGUAGE,
    ) -> Dict[str, Any]:
        if not include_inactive and not self.active:
            return {}

        payload: Dict[str, Any] = {
            "id": self.id,
            "label": self.label_for(language),
            "description": self.description,
            "active": self.active,
            "sort_order": self.sort_order,
            "tags": _tuple_to_list(self.tags),
            "aliases": _tuple_to_list(self.aliases),
            "i18n": dict(self.i18n),
            "metadata": dict(self.metadata),
        }

        if include_extra and self.extra:
            payload["extra"] = dict(self.extra)

        return _dict_without_empty(payload)


@dataclass(frozen=True)
class ObjectKindDefinition(BaseDefinition):
    """
    UI/profile metadata for a technical VPLIB object_kind.

    The hard technical object kind list should remain in VPLIB core. This model
    adds labels, profile compatibility and create-flow metadata.
    """

    allowed_family_profiles: Tuple[str, ...] = field(default_factory=tuple)
    default_family_profile_id: Optional[str] = None
    default_variant_profile_id: Optional[str] = None
    default_modules: Dict[str, Any] = field(default_factory=dict)
    geometry_rules: Dict[str, Any] = field(default_factory=dict)
    preview_behavior: Dict[str, Any] = field(default_factory=dict)
    ui: Dict[str, Any] = field(default_factory=dict)

    @classmethod
    def from_mapping(cls, data: Mapping[str, Any]) -> "ObjectKindDefinition":
        data = _require_mapping(data, context="ObjectKindDefinition")
        context = "ObjectKindDefinition"

        identifier = _require_string_id(
            data.get("id") or data.get("object_kind"),
            field_name="id",
            context=context,
        )

        known_keys = {
            "id",
            "object_kind",
            "label",
            "description",
            "active",
            "sort_order",
            "tags",
            "aliases",
            "i18n",
            "metadata",
            "allowed_family_profiles",
            "default_family_profile_id",
            "default_variant_profile_id",
            "default_modules",
            "geometry_rules",
            "preview_behavior",
            "ui",
        }

        return cls(
            id=identifier,
            label=_normalize_label(data.get("label"), fallback=identifier),
            description=_as_clean_string(data.get("description")),
            active=_as_bool(data.get("active"), default=True),
            sort_order=int(data.get("sort_order") or 1000),
            tags=_as_string_tuple(data.get("tags")),
            aliases=_as_string_tuple(data.get("aliases")),
            i18n=_normalize_i18n_mapping(data.get("i18n")),
            metadata=_normalize_metadata(data.get("metadata")),
            extra=_merge_extra(data, known_keys),
            allowed_family_profiles=_validate_id_tuple(
                data.get("allowed_family_profiles"),
                field_name="allowed_family_profiles",
                context=context,
            ),
            default_family_profile_id=_validate_optional_id(
                data.get("default_family_profile_id"),
                field_name="default_family_profile_id",
                context=context,
            ),
            default_variant_profile_id=_validate_optional_id(
                data.get("default_variant_profile_id"),
                field_name="default_variant_profile_id",
                context=context,
            ),
            default_modules=_copy_mapping(data.get("default_modules")),
            geometry_rules=_copy_mapping(data.get("geometry_rules")),
            preview_behavior=_copy_mapping(data.get("preview_behavior")),
            ui=_normalize_ui(data.get("ui")),
        )

    def to_dict(
        self,
        *,
        include_extra: bool = True,
        include_inactive: bool = True,
        language: str = DEFAULT_LANGUAGE,
    ) -> Dict[str, Any]:
        payload = super().to_dict(
            include_extra=include_extra,
            include_inactive=include_inactive,
            language=language,
        )
        if not payload:
            return payload

        payload.update(
            _dict_without_empty(
                {
                    "object_kind": self.id,
                    "allowed_family_profiles": _tuple_to_list(self.allowed_family_profiles),
                    "default_family_profile_id": self.default_family_profile_id,
                    "default_variant_profile_id": self.default_variant_profile_id,
                    "default_modules": dict(self.default_modules),
                    "geometry_rules": dict(self.geometry_rules),
                    "preview_behavior": dict(self.preview_behavior),
                    "ui": dict(self.ui),
                }
            )
        )
        return payload


@dataclass(frozen=True)
class FamilyProfileDefinition(BaseDefinition):
    """
    Fachliches Family-Profil.

    Examples:
    - wall_masonry
    - bridge_abutment_concrete
    - sanitary_faucet
    """

    object_kinds: Tuple[str, ...] = field(default_factory=tuple)
    taxonomy_domains: Tuple[str, ...] = field(default_factory=tuple)
    taxonomy_categories: Tuple[str, ...] = field(default_factory=tuple)
    taxonomy_subcategories: Tuple[str, ...] = field(default_factory=tuple)
    allowed_variant_profiles: Tuple[str, ...] = field(default_factory=tuple)
    default_variant_profile_id: Optional[str] = None
    required_modules: Tuple[str, ...] = field(default_factory=tuple)
    optional_modules: Tuple[str, ...] = field(default_factory=tuple)
    default_modules: Dict[str, Any] = field(default_factory=dict)
    ui: Dict[str, Any] = field(default_factory=dict)

    @classmethod
    def from_mapping(cls, data: Mapping[str, Any]) -> "FamilyProfileDefinition":
        data = _require_mapping(data, context="FamilyProfileDefinition")
        context = "FamilyProfileDefinition"

        identifier = _require_string_id(
            data.get("id") or data.get("profile_id") or data.get("family_profile_id"),
            field_name="id",
            context=context,
        )

        known_keys = {
            "id",
            "profile_id",
            "family_profile_id",
            "label",
            "description",
            "active",
            "sort_order",
            "tags",
            "aliases",
            "i18n",
            "metadata",
            "object_kinds",
            "taxonomy_domains",
            "taxonomy_categories",
            "taxonomy_subcategories",
            "allowed_variant_profiles",
            "default_variant_profile_id",
            "required_modules",
            "optional_modules",
            "default_modules",
            "ui",
        }

        return cls(
            id=identifier,
            label=_normalize_label(data.get("label"), fallback=identifier),
            description=_as_clean_string(data.get("description")),
            active=_as_bool(data.get("active"), default=True),
            sort_order=int(data.get("sort_order") or 1000),
            tags=_as_string_tuple(data.get("tags")),
            aliases=_as_string_tuple(data.get("aliases")),
            i18n=_normalize_i18n_mapping(data.get("i18n")),
            metadata=_normalize_metadata(data.get("metadata")),
            extra=_merge_extra(data, known_keys),
            object_kinds=_validate_id_tuple(
                data.get("object_kinds"),
                field_name="object_kinds",
                context=context,
            ),
            taxonomy_domains=_validate_taxonomy_path_parts(
                data.get("taxonomy_domains"),
                field_name="taxonomy_domains",
                context=context,
            ),
            taxonomy_categories=_validate_taxonomy_path_parts(
                data.get("taxonomy_categories"),
                field_name="taxonomy_categories",
                context=context,
            ),
            taxonomy_subcategories=_validate_taxonomy_path_parts(
                data.get("taxonomy_subcategories"),
                field_name="taxonomy_subcategories",
                context=context,
            ),
            allowed_variant_profiles=_validate_id_tuple(
                data.get("allowed_variant_profiles"),
                field_name="allowed_variant_profiles",
                context=context,
            ),
            default_variant_profile_id=_validate_optional_id(
                data.get("default_variant_profile_id"),
                field_name="default_variant_profile_id",
                context=context,
            ),
            required_modules=_as_string_tuple(data.get("required_modules")),
            optional_modules=_as_string_tuple(data.get("optional_modules")),
            default_modules=_copy_mapping(data.get("default_modules")),
            ui=_normalize_ui(data.get("ui")),
        )

    @property
    def profile_id(self) -> str:
        return self.id

    def supports_object_kind(self, object_kind: str) -> bool:
        clean = _as_clean_string(object_kind)
        return not self.object_kinds or clean in self.object_kinds

    def to_dict(
        self,
        *,
        include_extra: bool = True,
        include_inactive: bool = True,
        language: str = DEFAULT_LANGUAGE,
    ) -> Dict[str, Any]:
        payload = super().to_dict(
            include_extra=include_extra,
            include_inactive=include_inactive,
            language=language,
        )
        if not payload:
            return payload

        payload.update(
            _dict_without_empty(
                {
                    "profile_id": self.id,
                    "family_profile_id": self.id,
                    "object_kinds": _tuple_to_list(self.object_kinds),
                    "taxonomy_domains": _tuple_to_list(self.taxonomy_domains),
                    "taxonomy_categories": _tuple_to_list(self.taxonomy_categories),
                    "taxonomy_subcategories": _tuple_to_list(self.taxonomy_subcategories),
                    "allowed_variant_profiles": _tuple_to_list(self.allowed_variant_profiles),
                    "default_variant_profile_id": self.default_variant_profile_id,
                    "required_modules": _tuple_to_list(self.required_modules),
                    "optional_modules": _tuple_to_list(self.optional_modules),
                    "default_modules": dict(self.default_modules),
                    "ui": dict(self.ui),
                }
            )
        )
        return payload


@dataclass(frozen=True)
class VariantProfileSectionDefinition:
    """
    Section inside a VariantProfileDefinition.

    Example sections:
    - identity
    - dimensions
    - material
    - performance
    - commercial
    - documents
    - manufacturer_reference
    """

    id: str
    label: str
    description: str = ""
    fields: Tuple[str, ...] = field(default_factory=tuple)
    required: bool = False
    collapsed: bool = False
    sort_order: int = 1000
    ui: Dict[str, Any] = field(default_factory=dict)
    metadata: Dict[str, Any] = field(default_factory=dict)
    extra: Dict[str, Any] = field(default_factory=dict)

    @classmethod
    def from_mapping(cls, data: Mapping[str, Any]) -> "VariantProfileSectionDefinition":
        data = _require_mapping(data, context="VariantProfileSectionDefinition")
        context = "VariantProfileSectionDefinition"

        identifier = _require_string_id(
            data.get("id") or data.get("section_id"),
            field_name="id",
            context=context,
        )

        known_keys = {
            "id",
            "section_id",
            "label",
            "description",
            "fields",
            "required",
            "collapsed",
            "sort_order",
            "ui",
            "metadata",
        }

        fields = _validate_id_tuple(
            data.get("fields"),
            field_name="fields",
            context=context,
            pattern=_VARIABLE_KEY_PATTERN,
        )

        return cls(
            id=identifier,
            label=_normalize_label(data.get("label"), fallback=identifier),
            description=_as_clean_string(data.get("description")),
            fields=fields,
            required=_as_bool(data.get("required"), default=False),
            collapsed=_as_bool(data.get("collapsed"), default=False),
            sort_order=int(data.get("sort_order") or 1000),
            ui=_normalize_ui(data.get("ui")),
            metadata=_normalize_metadata(data.get("metadata")),
            extra=_merge_extra(data, known_keys),
        )

    def to_dict(
        self,
        *,
        include_extra: bool = True,
        language: str = DEFAULT_LANGUAGE,
    ) -> Dict[str, Any]:
        payload: Dict[str, Any] = {
            "id": self.id,
            "section_id": self.id,
            "label": self.label,
            "description": self.description,
            "fields": _tuple_to_list(self.fields),
            "required": self.required,
            "collapsed": self.collapsed,
            "sort_order": self.sort_order,
            "ui": dict(self.ui),
            "metadata": dict(self.metadata),
        }

        if include_extra and self.extra:
            payload["extra"] = dict(self.extra)

        return _dict_without_empty(payload)


@dataclass(frozen=True)
class VariantProfileDefinition(BaseDefinition):
    """
    Field schema for variants of a family profile.

    This is the backend truth for the future "Variante hinzufügen" drawer.
    The frontend should render sections and fields from this model.
    """

    family_profiles: Tuple[str, ...] = field(default_factory=tuple)
    object_kinds: Tuple[str, ...] = field(default_factory=tuple)
    sections: Tuple[VariantProfileSectionDefinition, ...] = field(default_factory=tuple)
    required_fields: Tuple[str, ...] = field(default_factory=tuple)
    optional_fields: Tuple[str, ...] = field(default_factory=tuple)
    summary_fields: Tuple[str, ...] = field(default_factory=tuple)
    default_values: Dict[str, Any] = field(default_factory=dict)
    document_types: Tuple[str, ...] = field(default_factory=tuple)
    manufacturer_mode: str = "none"
    ui: Dict[str, Any] = field(default_factory=dict)

    @classmethod
    def from_mapping(cls, data: Mapping[str, Any]) -> "VariantProfileDefinition":
        data = _require_mapping(data, context="VariantProfileDefinition")
        context = "VariantProfileDefinition"

        identifier = _require_string_id(
            data.get("id") or data.get("profile_id") or data.get("variant_profile_id"),
            field_name="id",
            context=context,
        )

        known_keys = {
            "id",
            "profile_id",
            "variant_profile_id",
            "label",
            "description",
            "active",
            "sort_order",
            "tags",
            "aliases",
            "i18n",
            "metadata",
            "family_profiles",
            "object_kinds",
            "sections",
            "required_fields",
            "optional_fields",
            "summary_fields",
            "default_values",
            "document_types",
            "manufacturer_mode",
            "ui",
        }

        sections = tuple(
            VariantProfileSectionDefinition.from_mapping(item)
            for item in _as_mapping_tuple(data.get("sections"))
        )

        required_fields = _validate_id_tuple(
            data.get("required_fields"),
            field_name="required_fields",
            context=context,
            pattern=_VARIABLE_KEY_PATTERN,
        )
        optional_fields = _validate_id_tuple(
            data.get("optional_fields"),
            field_name="optional_fields",
            context=context,
            pattern=_VARIABLE_KEY_PATTERN,
        )

        section_field_set = {
            field_key
            for section in sections
            for field_key in section.fields
        }

        for required_field in required_fields:
            if section_field_set and required_field not in section_field_set:
                raise DefinitionValidationError(
                    f"{context}.required_fields references field not present in sections: "
                    f"{required_field!r}"
                )

        return cls(
            id=identifier,
            label=_normalize_label(data.get("label"), fallback=identifier),
            description=_as_clean_string(data.get("description")),
            active=_as_bool(data.get("active"), default=True),
            sort_order=int(data.get("sort_order") or 1000),
            tags=_as_string_tuple(data.get("tags")),
            aliases=_as_string_tuple(data.get("aliases")),
            i18n=_normalize_i18n_mapping(data.get("i18n")),
            metadata=_normalize_metadata(data.get("metadata")),
            extra=_merge_extra(data, known_keys),
            family_profiles=_validate_id_tuple(
                data.get("family_profiles"),
                field_name="family_profiles",
                context=context,
            ),
            object_kinds=_validate_id_tuple(
                data.get("object_kinds"),
                field_name="object_kinds",
                context=context,
            ),
            sections=sections,
            required_fields=required_fields,
            optional_fields=optional_fields,
            summary_fields=_validate_id_tuple(
                data.get("summary_fields"),
                field_name="summary_fields",
                context=context,
                pattern=_VARIABLE_KEY_PATTERN,
            ),
            default_values=_copy_mapping(data.get("default_values")),
            document_types=_validate_id_tuple(
                data.get("document_types"),
                field_name="document_types",
                context=context,
            ),
            manufacturer_mode=_as_clean_string(data.get("manufacturer_mode"), default="none"),
            ui=_normalize_ui(data.get("ui")),
        )

    @property
    def profile_id(self) -> str:
        return self.id

    @property
    def all_field_keys(self) -> Tuple[str, ...]:
        fields: List[str] = []
        seen = set()

        for section in self.sections:
            for field_key in section.fields:
                if field_key not in seen:
                    fields.append(field_key)
                    seen.add(field_key)

        for field_key in self.required_fields + self.optional_fields:
            if field_key not in seen:
                fields.append(field_key)
                seen.add(field_key)

        return tuple(fields)

    def supports_family_profile(self, family_profile_id: str) -> bool:
        clean = _as_clean_string(family_profile_id)
        return not self.family_profiles or clean in self.family_profiles

    def supports_object_kind(self, object_kind: str) -> bool:
        clean = _as_clean_string(object_kind)
        return not self.object_kinds or clean in self.object_kinds

    def to_dict(
        self,
        *,
        include_extra: bool = True,
        include_inactive: bool = True,
        language: str = DEFAULT_LANGUAGE,
    ) -> Dict[str, Any]:
        payload = super().to_dict(
            include_extra=include_extra,
            include_inactive=include_inactive,
            language=language,
        )
        if not payload:
            return payload

        payload.update(
            _dict_without_empty(
                {
                    "profile_id": self.id,
                    "variant_profile_id": self.id,
                    "family_profiles": _tuple_to_list(self.family_profiles),
                    "object_kinds": _tuple_to_list(self.object_kinds),
                    "sections": [
                        section.to_dict(include_extra=include_extra, language=language)
                        for section in sorted(self.sections, key=lambda item: item.sort_order)
                    ],
                    "required_fields": _tuple_to_list(self.required_fields),
                    "optional_fields": _tuple_to_list(self.optional_fields),
                    "summary_fields": _tuple_to_list(self.summary_fields),
                    "all_fields": _tuple_to_list(self.all_field_keys),
                    "default_values": dict(self.default_values),
                    "document_types": _tuple_to_list(self.document_types),
                    "manufacturer_mode": self.manufacturer_mode,
                    "ui": dict(self.ui),
                }
            )
        )
        return payload


@dataclass(frozen=True)
class VariableDefinition(BaseDefinition):
    """
    Canonical variable definition.

    Examples:
    - dimensions.thickness_mm
    - thermal.u_value
    - structural.compressive_strength
    - commercial.price_per_m2
    """

    key: str = ""
    value_type: str = "string"
    unit: Optional[str] = None
    required_default: bool = False
    default_value: Any = None
    options: Tuple[Dict[str, Any], ...] = field(default_factory=tuple)
    validation: Dict[str, Any] = field(default_factory=dict)
    widget: str = "input"
    group: Optional[str] = None
    applies_to: Tuple[str, ...] = field(default_factory=tuple)
    readonly: bool = False
    system: bool = False

    @classmethod
    def from_mapping(cls, data: Mapping[str, Any]) -> "VariableDefinition":
        data = _require_mapping(data, context="VariableDefinition")
        context = "VariableDefinition"

        identifier = _require_string_id(
            data.get("key") or data.get("id"),
            field_name="key",
            context=context,
            pattern=_VARIABLE_KEY_PATTERN,
        )

        value_type = _as_clean_string(data.get("value_type"), default="string")
        if value_type not in SUPPORTED_VALUE_TYPES:
            raise DefinitionValidationError(
                f"{context}.value_type is unsupported for {identifier!r}: {value_type!r}"
            )

        widget = _as_clean_string(data.get("widget"), default="")
        if not widget:
            widget = _default_widget_for_value_type(value_type)
        if widget not in SUPPORTED_FIELD_WIDGETS:
            raise DefinitionValidationError(
                f"{context}.widget is unsupported for {identifier!r}: {widget!r}"
            )

        known_keys = {
            "id",
            "key",
            "label",
            "description",
            "active",
            "sort_order",
            "tags",
            "aliases",
            "i18n",
            "metadata",
            "value_type",
            "unit",
            "required_default",
            "default_value",
            "options",
            "validation",
            "widget",
            "group",
            "applies_to",
            "readonly",
            "system",
        }

        return cls(
            id=identifier,
            key=identifier,
            label=_normalize_label(data.get("label"), fallback=identifier),
            description=_as_clean_string(data.get("description")),
            active=_as_bool(data.get("active"), default=True),
            sort_order=int(data.get("sort_order") or 1000),
            tags=_as_string_tuple(data.get("tags")),
            aliases=_as_string_tuple(data.get("aliases")),
            i18n=_normalize_i18n_mapping(data.get("i18n")),
            metadata=_normalize_metadata(data.get("metadata")),
            extra=_merge_extra(data, known_keys),
            value_type=value_type,
            unit=_as_optional_string(data.get("unit")),
            required_default=_as_bool(data.get("required_default"), default=False),
            default_value=data.get("default_value"),
            options=_normalize_options(data.get("options")),
            validation=_normalize_validation(data.get("validation")),
            widget=widget,
            group=_as_optional_string(data.get("group")),
            applies_to=_validate_id_tuple(
                data.get("applies_to"),
                field_name="applies_to",
                context=context,
            ),
            readonly=_as_bool(data.get("readonly"), default=False),
            system=_as_bool(data.get("system"), default=False),
        )

    def to_dict(
        self,
        *,
        include_extra: bool = True,
        include_inactive: bool = True,
        language: str = DEFAULT_LANGUAGE,
    ) -> Dict[str, Any]:
        payload = super().to_dict(
            include_extra=include_extra,
            include_inactive=include_inactive,
            language=language,
        )
        if not payload:
            return payload

        payload.update(
            _dict_without_empty(
                {
                    "key": self.key,
                    "value_type": self.value_type,
                    "unit": self.unit,
                    "required_default": self.required_default,
                    "default_value": self.default_value,
                    "options": _mapping_tuple_to_list(self.options),
                    "validation": dict(self.validation),
                    "widget": self.widget,
                    "group": self.group,
                    "applies_to": _tuple_to_list(self.applies_to),
                    "readonly": self.readonly,
                    "system": self.system,
                }
            )
        )
        return payload


def _default_widget_for_value_type(value_type: str) -> str:
    if value_type in {"number", "integer"}:
        return "number"
    if value_type == "boolean":
        return "checkbox"
    if value_type == "enum":
        return "select"
    if value_type == "multi_enum":
        return "multi_select"
    if value_type == "text":
        return "textarea"
    if value_type == "document_list":
        return "document_list"
    if value_type == "money":
        return "money"
    if value_type == "url":
        return "url"
    if value_type == "date":
        return "date"
    return "input"


@dataclass(frozen=True)
class UnitDefinition(BaseDefinition):
    """
    Canonical unit definition.

    Examples:
    - mm
    - m²
    - W/m²K
    - N/mm²
    - EUR/m²
    """

    symbol: str = ""
    quantity_kind: Optional[str] = None
    base_unit: Optional[str] = None
    conversion_factor_to_base: Optional[float] = None
    precision: Optional[int] = None

    @classmethod
    def from_mapping(cls, data: Mapping[str, Any]) -> "UnitDefinition":
        data = _require_mapping(data, context="UnitDefinition")
        context = "UnitDefinition"

        identifier = _as_clean_string(data.get("id") or data.get("unit") or data.get("symbol"))
        if not identifier:
            raise DefinitionValidationError(f"{context}.id is required")

        known_keys = {
            "id",
            "unit",
            "symbol",
            "label",
            "description",
            "active",
            "sort_order",
            "tags",
            "aliases",
            "i18n",
            "metadata",
            "quantity_kind",
            "base_unit",
            "conversion_factor_to_base",
            "precision",
        }

        conversion_factor = data.get("conversion_factor_to_base")
        if conversion_factor is not None:
            try:
                conversion_factor = float(conversion_factor)
            except (TypeError, ValueError) as exc:
                raise DefinitionValidationError(
                    f"{context}.conversion_factor_to_base must be numeric for {identifier!r}"
                ) from exc

        precision = data.get("precision")
        if precision is not None:
            try:
                precision = int(precision)
            except (TypeError, ValueError) as exc:
                raise DefinitionValidationError(
                    f"{context}.precision must be integer for {identifier!r}"
                ) from exc

        symbol = _as_clean_string(data.get("symbol"), default=identifier)

        return cls(
            id=identifier,
            label=_normalize_label(data.get("label"), fallback=symbol),
            description=_as_clean_string(data.get("description")),
            active=_as_bool(data.get("active"), default=True),
            sort_order=int(data.get("sort_order") or 1000),
            tags=_as_string_tuple(data.get("tags")),
            aliases=_as_string_tuple(data.get("aliases")),
            i18n=_normalize_i18n_mapping(data.get("i18n")),
            metadata=_normalize_metadata(data.get("metadata")),
            extra=_merge_extra(data, known_keys),
            symbol=symbol,
            quantity_kind=_as_optional_string(data.get("quantity_kind")),
            base_unit=_as_optional_string(data.get("base_unit")),
            conversion_factor_to_base=conversion_factor,
            precision=precision,
        )

    def to_dict(
        self,
        *,
        include_extra: bool = True,
        include_inactive: bool = True,
        language: str = DEFAULT_LANGUAGE,
    ) -> Dict[str, Any]:
        payload = super().to_dict(
            include_extra=include_extra,
            include_inactive=include_inactive,
            language=language,
        )
        if not payload:
            return payload

        payload.update(
            _dict_without_empty(
                {
                    "unit": self.id,
                    "symbol": self.symbol,
                    "quantity_kind": self.quantity_kind,
                    "base_unit": self.base_unit,
                    "conversion_factor_to_base": self.conversion_factor_to_base,
                    "precision": self.precision,
                }
            )
        )
        return payload


@dataclass(frozen=True)
class MaterialDefinition(BaseDefinition):
    """
    Canonical material definition.

    Examples:
    - brick
    - concrete
    - steel
    - wood
    """

    material_type: str = ""
    parent_material_id: Optional[str] = None
    compatible_family_profiles: Tuple[str, ...] = field(default_factory=tuple)
    compatible_variant_profiles: Tuple[str, ...] = field(default_factory=tuple)
    default_values: Dict[str, Any] = field(default_factory=dict)
    properties: Dict[str, Any] = field(default_factory=dict)

    @classmethod
    def from_mapping(cls, data: Mapping[str, Any]) -> "MaterialDefinition":
        data = _require_mapping(data, context="MaterialDefinition")
        context = "MaterialDefinition"

        identifier = _require_string_id(
            data.get("id") or data.get("material_id") or data.get("material_type"),
            field_name="id",
            context=context,
        )

        known_keys = {
            "id",
            "material_id",
            "material_type",
            "label",
            "description",
            "active",
            "sort_order",
            "tags",
            "aliases",
            "i18n",
            "metadata",
            "parent_material_id",
            "compatible_family_profiles",
            "compatible_variant_profiles",
            "default_values",
            "properties",
        }

        return cls(
            id=identifier,
            material_type=identifier,
            label=_normalize_label(data.get("label"), fallback=identifier),
            description=_as_clean_string(data.get("description")),
            active=_as_bool(data.get("active"), default=True),
            sort_order=int(data.get("sort_order") or 1000),
            tags=_as_string_tuple(data.get("tags")),
            aliases=_as_string_tuple(data.get("aliases")),
            i18n=_normalize_i18n_mapping(data.get("i18n")),
            metadata=_normalize_metadata(data.get("metadata")),
            extra=_merge_extra(data, known_keys),
            parent_material_id=_validate_optional_id(
                data.get("parent_material_id"),
                field_name="parent_material_id",
                context=context,
            ),
            compatible_family_profiles=_validate_id_tuple(
                data.get("compatible_family_profiles"),
                field_name="compatible_family_profiles",
                context=context,
            ),
            compatible_variant_profiles=_validate_id_tuple(
                data.get("compatible_variant_profiles"),
                field_name="compatible_variant_profiles",
                context=context,
            ),
            default_values=_copy_mapping(data.get("default_values")),
            properties=_copy_mapping(data.get("properties")),
        )

    def to_dict(
        self,
        *,
        include_extra: bool = True,
        include_inactive: bool = True,
        language: str = DEFAULT_LANGUAGE,
    ) -> Dict[str, Any]:
        payload = super().to_dict(
            include_extra=include_extra,
            include_inactive=include_inactive,
            language=language,
        )
        if not payload:
            return payload

        payload.update(
            _dict_without_empty(
                {
                    "material_id": self.id,
                    "material_type": self.material_type,
                    "parent_material_id": self.parent_material_id,
                    "compatible_family_profiles": _tuple_to_list(
                        self.compatible_family_profiles
                    ),
                    "compatible_variant_profiles": _tuple_to_list(
                        self.compatible_variant_profiles
                    ),
                    "default_values": dict(self.default_values),
                    "properties": dict(self.properties),
                }
            )
        )
        return payload


@dataclass(frozen=True)
class DocumentTypeDefinition(BaseDefinition):
    """
    Canonical document type definition.

    Examples:
    - datasheet
    - test_report
    - approval
    - certificate
    """

    required_for_profiles: Tuple[str, ...] = field(default_factory=tuple)
    allowed_mime_types: Tuple[str, ...] = field(default_factory=tuple)
    allowed_extensions: Tuple[str, ...] = field(default_factory=tuple)
    max_size_mb: Optional[float] = None
    multiple: bool = True
    ui: Dict[str, Any] = field(default_factory=dict)

    @classmethod
    def from_mapping(cls, data: Mapping[str, Any]) -> "DocumentTypeDefinition":
        data = _require_mapping(data, context="DocumentTypeDefinition")
        context = "DocumentTypeDefinition"

        identifier = _require_string_id(
            data.get("id") or data.get("document_type_id") or data.get("type"),
            field_name="id",
            context=context,
        )

        max_size = data.get("max_size_mb")
        if max_size is not None:
            try:
                max_size = float(max_size)
            except (TypeError, ValueError) as exc:
                raise DefinitionValidationError(
                    f"{context}.max_size_mb must be numeric for {identifier!r}"
                ) from exc

        known_keys = {
            "id",
            "document_type_id",
            "type",
            "label",
            "description",
            "active",
            "sort_order",
            "tags",
            "aliases",
            "i18n",
            "metadata",
            "required_for_profiles",
            "allowed_mime_types",
            "allowed_extensions",
            "max_size_mb",
            "multiple",
            "ui",
        }

        return cls(
            id=identifier,
            label=_normalize_label(data.get("label"), fallback=identifier),
            description=_as_clean_string(data.get("description")),
            active=_as_bool(data.get("active"), default=True),
            sort_order=int(data.get("sort_order") or 1000),
            tags=_as_string_tuple(data.get("tags")),
            aliases=_as_string_tuple(data.get("aliases")),
            i18n=_normalize_i18n_mapping(data.get("i18n")),
            metadata=_normalize_metadata(data.get("metadata")),
            extra=_merge_extra(data, known_keys),
            required_for_profiles=_validate_id_tuple(
                data.get("required_for_profiles"),
                field_name="required_for_profiles",
                context=context,
            ),
            allowed_mime_types=_as_string_tuple(data.get("allowed_mime_types")),
            allowed_extensions=_as_string_tuple(data.get("allowed_extensions")),
            max_size_mb=max_size,
            multiple=_as_bool(data.get("multiple"), default=True),
            ui=_normalize_ui(data.get("ui")),
        )

    def to_dict(
        self,
        *,
        include_extra: bool = True,
        include_inactive: bool = True,
        language: str = DEFAULT_LANGUAGE,
    ) -> Dict[str, Any]:
        payload = super().to_dict(
            include_extra=include_extra,
            include_inactive=include_inactive,
            language=language,
        )
        if not payload:
            return payload

        payload.update(
            _dict_without_empty(
                {
                    "document_type_id": self.id,
                    "type": self.id,
                    "required_for_profiles": _tuple_to_list(self.required_for_profiles),
                    "allowed_mime_types": _tuple_to_list(self.allowed_mime_types),
                    "allowed_extensions": _tuple_to_list(self.allowed_extensions),
                    "max_size_mb": self.max_size_mb,
                    "multiple": self.multiple,
                    "ui": dict(self.ui),
                }
            )
        )
        return payload


@dataclass(frozen=True)
class ProfileBindingDefinition(BaseDefinition):
    """
    Binding between taxonomy context, object_kind, family_profile and
    variant_profile.

    This is the profile resolver's source of truth.
    """

    domain: Optional[str] = None
    category: Optional[str] = None
    subcategory: Optional[str] = None
    object_kind: Optional[str] = None
    family_profile_id: Optional[str] = None
    variant_profile_id: Optional[str] = None
    priority: int = 1000
    match: Dict[str, Any] = field(default_factory=dict)

    @classmethod
    def from_mapping(cls, data: Mapping[str, Any]) -> "ProfileBindingDefinition":
        data = _require_mapping(data, context="ProfileBindingDefinition")
        context = "ProfileBindingDefinition"

        raw_id = (
            data.get("id")
            or data.get("binding_id")
            or _derive_binding_id(data)
        )
        identifier = _require_string_id(raw_id, field_name="id", context=context)

        domain = _validate_optional_taxonomy_part(
            data.get("domain"),
            field_name="domain",
            context=context,
        )
        category = _validate_optional_taxonomy_part(
            data.get("category"),
            field_name="category",
            context=context,
        )
        subcategory = _validate_optional_taxonomy_part(
            data.get("subcategory"),
            field_name="subcategory",
            context=context,
        )

        object_kind = _validate_optional_id(
            data.get("object_kind"),
            field_name="object_kind",
            context=context,
        )
        family_profile_id = _validate_optional_id(
            data.get("family_profile_id") or data.get("family_profile"),
            field_name="family_profile_id",
            context=context,
        )
        variant_profile_id = _validate_optional_id(
            data.get("variant_profile_id") or data.get("variant_profile"),
            field_name="variant_profile_id",
            context=context,
        )

        if not family_profile_id and not variant_profile_id:
            raise DefinitionValidationError(
                f"{context} {identifier!r} must define at least family_profile_id "
                "or variant_profile_id"
            )

        known_keys = {
            "id",
            "binding_id",
            "label",
            "description",
            "active",
            "sort_order",
            "tags",
            "aliases",
            "i18n",
            "metadata",
            "domain",
            "category",
            "subcategory",
            "object_kind",
            "family_profile",
            "family_profile_id",
            "variant_profile",
            "variant_profile_id",
            "priority",
            "match",
        }

        return cls(
            id=identifier,
            label=_normalize_label(data.get("label"), fallback=identifier),
            description=_as_clean_string(data.get("description")),
            active=_as_bool(data.get("active"), default=True),
            sort_order=int(data.get("sort_order") or 1000),
            tags=_as_string_tuple(data.get("tags")),
            aliases=_as_string_tuple(data.get("aliases")),
            i18n=_normalize_i18n_mapping(data.get("i18n")),
            metadata=_normalize_metadata(data.get("metadata")),
            extra=_merge_extra(data, known_keys),
            domain=domain,
            category=category,
            subcategory=subcategory,
            object_kind=object_kind,
            family_profile_id=family_profile_id,
            variant_profile_id=variant_profile_id,
            priority=int(data.get("priority") or data.get("sort_order") or 1000),
            match=_copy_mapping(data.get("match")),
        )

    def matches_context(
        self,
        *,
        domain: Optional[str] = None,
        category: Optional[str] = None,
        subcategory: Optional[str] = None,
        object_kind: Optional[str] = None,
        family_profile_id: Optional[str] = None,
    ) -> bool:
        if not self.active:
            return False

        checks = (
            (self.domain, domain),
            (self.category, category),
            (self.subcategory, subcategory),
            (self.object_kind, object_kind),
            (self.family_profile_id, family_profile_id),
        )

        for expected, actual in checks:
            if expected and _as_clean_string(actual) != expected:
                return False

        return True

    def specificity_score(self) -> int:
        score = 0
        for value in (
            self.domain,
            self.category,
            self.subcategory,
            self.object_kind,
            self.family_profile_id,
            self.variant_profile_id,
        ):
            if value:
                score += 1
        return score

    def to_dict(
        self,
        *,
        include_extra: bool = True,
        include_inactive: bool = True,
        language: str = DEFAULT_LANGUAGE,
    ) -> Dict[str, Any]:
        payload = super().to_dict(
            include_extra=include_extra,
            include_inactive=include_inactive,
            language=language,
        )
        if not payload:
            return payload

        payload.update(
            _dict_without_empty(
                {
                    "binding_id": self.id,
                    "domain": self.domain,
                    "category": self.category,
                    "subcategory": self.subcategory,
                    "object_kind": self.object_kind,
                    "family_profile_id": self.family_profile_id,
                    "variant_profile_id": self.variant_profile_id,
                    "priority": self.priority,
                    "specificity_score": self.specificity_score(),
                    "match": dict(self.match),
                }
            )
        )
        return payload


def _validate_optional_taxonomy_part(
    value: Any,
    *,
    field_name: str,
    context: str,
) -> Optional[str]:
    clean = _as_optional_string(value)
    if clean is None:
        return None
    if not _TAXONOMY_PART_PATTERN.match(clean):
        raise DefinitionValidationError(
            f"{context}.{field_name} has invalid taxonomy value: {clean!r}"
        )
    return clean


def _derive_binding_id(data: Mapping[str, Any]) -> str:
    parts = [
        _as_clean_string(data.get("domain"), default="any"),
        _as_clean_string(data.get("category"), default="any"),
        _as_clean_string(data.get("subcategory"), default="any"),
        _as_clean_string(data.get("object_kind"), default="any"),
        _as_clean_string(
            data.get("family_profile_id") or data.get("family_profile"),
            default="any",
        ),
        _as_clean_string(
            data.get("variant_profile_id") or data.get("variant_profile"),
            default="any",
        ),
    ]
    clean_parts = [part if _ID_PATTERN.match(part) else "any" for part in parts]
    return "binding." + ".".join(clean_parts)


@dataclass(frozen=True)
class DefinitionsRegistrySnapshot:
    """
    Immutable normalized snapshot produced by definition_registry.py.

    The registry can expose this snapshot to services, route builders,
    validators and diagnostics without leaking mutable internal state.
    """

    definitions_version: str = DEFINITION_DEFAULT_VERSION
    schema_version: str = DEFINITION_SCHEMA_VERSION
    source: Optional[str] = None
    loaded_at: Optional[str] = None
    object_kinds: Tuple[ObjectKindDefinition, ...] = field(default_factory=tuple)
    family_profiles: Tuple[FamilyProfileDefinition, ...] = field(default_factory=tuple)
    variant_profiles: Tuple[VariantProfileDefinition, ...] = field(default_factory=tuple)
    variables: Tuple[VariableDefinition, ...] = field(default_factory=tuple)
    units: Tuple[UnitDefinition, ...] = field(default_factory=tuple)
    materials: Tuple[MaterialDefinition, ...] = field(default_factory=tuple)
    document_types: Tuple[DocumentTypeDefinition, ...] = field(default_factory=tuple)
    profile_bindings: Tuple[ProfileBindingDefinition, ...] = field(default_factory=tuple)
    warnings: Tuple[str, ...] = field(default_factory=tuple)
    errors: Tuple[str, ...] = field(default_factory=tuple)
    metadata: Dict[str, Any] = field(default_factory=dict)

    @property
    def ok(self) -> bool:
        return not self.errors

    @property
    def healthy(self) -> bool:
        return self.ok

    def counts(self, *, include_inactive: bool = True) -> Dict[str, int]:
        def count_items(items: Sequence[BaseDefinition]) -> int:
            if include_inactive:
                return len(items)
            return sum(1 for item in items if item.active)

        return {
            "object_kinds": count_items(self.object_kinds),
            "family_profiles": count_items(self.family_profiles),
            "variant_profiles": count_items(self.variant_profiles),
            "variables": count_items(self.variables),
            "units": count_items(self.units),
            "materials": count_items(self.materials),
            "document_types": count_items(self.document_types),
            "profile_bindings": count_items(self.profile_bindings),
            "warnings": len(self.warnings),
            "errors": len(self.errors),
        }

    def to_dict(
        self,
        *,
        include_inactive: bool = False,
        include_internal: bool = False,
        include_extra: bool = True,
        language: str = DEFAULT_LANGUAGE,
    ) -> Dict[str, Any]:
        payload: Dict[str, Any] = {
            "ok": self.ok,
            "healthy": self.healthy,
            "status": "healthy" if self.healthy else "invalid",
            "definitions_version": self.definitions_version,
            "schema_version": self.schema_version,
            "counts": self.counts(include_inactive=include_inactive),
            "object_kinds": [
                item.to_dict(
                    include_extra=include_extra,
                    include_inactive=include_inactive,
                    language=language,
                )
                for item in self.object_kinds
                if include_inactive or item.active
            ],
            "family_profiles": [
                item.to_dict(
                    include_extra=include_extra,
                    include_inactive=include_inactive,
                    language=language,
                )
                for item in self.family_profiles
                if include_inactive or item.active
            ],
            "variant_profiles": [
                item.to_dict(
                    include_extra=include_extra,
                    include_inactive=include_inactive,
                    language=language,
                )
                for item in self.variant_profiles
                if include_inactive or item.active
            ],
            "variables": [
                item.to_dict(
                    include_extra=include_extra,
                    include_inactive=include_inactive,
                    language=language,
                )
                for item in self.variables
                if include_inactive or item.active
            ],
            "units": [
                item.to_dict(
                    include_extra=include_extra,
                    include_inactive=include_inactive,
                    language=language,
                )
                for item in self.units
                if include_inactive or item.active
            ],
            "materials": [
                item.to_dict(
                    include_extra=include_extra,
                    include_inactive=include_inactive,
                    language=language,
                )
                for item in self.materials
                if include_inactive or item.active
            ],
            "document_types": [
                item.to_dict(
                    include_extra=include_extra,
                    include_inactive=include_inactive,
                    language=language,
                )
                for item in self.document_types
                if include_inactive or item.active
            ],
            "profile_bindings": [
                item.to_dict(
                    include_extra=include_extra,
                    include_inactive=include_inactive,
                    language=language,
                )
                for item in self.profile_bindings
                if include_inactive or item.active
            ],
            "warnings": _tuple_to_list(self.warnings),
            "errors": _tuple_to_list(self.errors),
        }

        if include_internal:
            payload.update(
                _dict_without_empty(
                    {
                        "source": self.source,
                        "loaded_at": self.loaded_at,
                        "metadata": dict(self.metadata),
                    }
                )
            )

        return payload

    def summary(self) -> Dict[str, Any]:
        return {
            "ok": self.ok,
            "healthy": self.healthy,
            "status": "healthy" if self.healthy else "invalid",
            "definitions_version": self.definitions_version,
            "schema_version": self.schema_version,
            "counts": self.counts(include_inactive=True),
            "source": self.source,
            "loaded_at": self.loaded_at,
            "warnings": _tuple_to_list(self.warnings),
            "errors": _tuple_to_list(self.errors),
        }


DATASET_MODEL_FACTORIES = {
    "object_kinds": ObjectKindDefinition.from_mapping,
    "family_profiles": FamilyProfileDefinition.from_mapping,
    "variant_profiles": VariantProfileDefinition.from_mapping,
    "variables": VariableDefinition.from_mapping,
    "units": UnitDefinition.from_mapping,
    "materials": MaterialDefinition.from_mapping,
    "document_types": DocumentTypeDefinition.from_mapping,
    "profile_bindings": ProfileBindingDefinition.from_mapping,
}


def parse_dataset_items(
    dataset_name: str,
    raw_data: Any,
    *,
    allow_empty: bool = True,
) -> Tuple[Any, ...]:
    """
    Parse one dataset into model objects.

    Supported dataset JSON shapes:
    - {"items": [...]}
    - {"object_kinds": [...]}
    - [...]
    """
    clean_dataset_name = _as_clean_string(dataset_name)
    if clean_dataset_name not in DATASET_MODEL_FACTORIES:
        raise DefinitionDatasetError(f"Unknown definitions dataset: {dataset_name!r}")

    factory = DATASET_MODEL_FACTORIES[clean_dataset_name]

    if _is_mapping(raw_data):
        if "items" in raw_data:
            items = raw_data.get("items")
        else:
            items = raw_data.get(clean_dataset_name)
    else:
        items = raw_data

    raw_items = _as_tuple(items)
    if not raw_items and not allow_empty:
        raise DefinitionDatasetError(f"Dataset {clean_dataset_name!r} must not be empty")

    parsed: List[Any] = []
    for index, item in enumerate(raw_items):
        try:
            parsed.append(factory(_require_mapping(item, context=f"{clean_dataset_name}[{index}]")))
        except DefinitionError:
            raise
        except Exception as exc:
            raise DefinitionDatasetError(
                f"Could not parse {clean_dataset_name}[{index}]: {exc}"
            ) from exc

    _assert_unique_ids(clean_dataset_name, parsed)

    return tuple(parsed)


def _assert_unique_ids(dataset_name: str, items: Sequence[Any]) -> None:
    seen: Dict[str, int] = {}

    for index, item in enumerate(items):
        identifier = getattr(item, "id", None)
        if not identifier:
            raise DefinitionDatasetError(
                f"Dataset {dataset_name!r} item at index {index} has no id"
            )
        if identifier in seen:
            raise DefinitionDatasetError(
                f"Dataset {dataset_name!r} contains duplicate id {identifier!r} "
                f"at indexes {seen[identifier]} and {index}"
            )
        seen[identifier] = index


def build_registry_snapshot(
    *,
    definitions_version: str = DEFINITION_DEFAULT_VERSION,
    schema_version: str = DEFINITION_SCHEMA_VERSION,
    source: Optional[str] = None,
    loaded_at: Optional[str] = None,
    object_kinds: Sequence[ObjectKindDefinition] = (),
    family_profiles: Sequence[FamilyProfileDefinition] = (),
    variant_profiles: Sequence[VariantProfileDefinition] = (),
    variables: Sequence[VariableDefinition] = (),
    units: Sequence[UnitDefinition] = (),
    materials: Sequence[MaterialDefinition] = (),
    document_types: Sequence[DocumentTypeDefinition] = (),
    profile_bindings: Sequence[ProfileBindingDefinition] = (),
    warnings: Sequence[str] = (),
    errors: Sequence[str] = (),
    metadata: Optional[Mapping[str, Any]] = None,
) -> DefinitionsRegistrySnapshot:
    """
    Build an immutable snapshot while validating duplicate IDs per dataset.
    """
    _assert_unique_ids("object_kinds", object_kinds)
    _assert_unique_ids("family_profiles", family_profiles)
    _assert_unique_ids("variant_profiles", variant_profiles)
    _assert_unique_ids("variables", variables)
    _assert_unique_ids("units", units)
    _assert_unique_ids("materials", materials)
    _assert_unique_ids("document_types", document_types)
    _assert_unique_ids("profile_bindings", profile_bindings)

    return DefinitionsRegistrySnapshot(
        definitions_version=_as_clean_string(
            definitions_version,
            default=DEFINITION_DEFAULT_VERSION,
        ),
        schema_version=_as_clean_string(
            schema_version,
            default=DEFINITION_SCHEMA_VERSION,
        ),
        source=_as_optional_string(source),
        loaded_at=_as_optional_string(loaded_at),
        object_kinds=tuple(object_kinds),
        family_profiles=tuple(family_profiles),
        variant_profiles=tuple(variant_profiles),
        variables=tuple(variables),
        units=tuple(units),
        materials=tuple(materials),
        document_types=tuple(document_types),
        profile_bindings=tuple(profile_bindings),
        warnings=tuple(_as_clean_string(item) for item in warnings if _as_clean_string(item)),
        errors=tuple(_as_clean_string(item) for item in errors if _as_clean_string(item)),
        metadata=_normalize_metadata(metadata),
    )


def get_definition_models_health() -> Dict[str, Any]:
    """
    Lightweight health endpoint for package diagnostics.
    """
    return {
        "ok": True,
        "healthy": True,
        "status": "healthy",
        "component": "library.definitions.models",
        "version": DEFINITION_MODELS_VERSION,
        "schema_version": DEFINITION_SCHEMA_VERSION,
        "supported_value_types": list(SUPPORTED_VALUE_TYPES),
        "supported_field_widgets": list(SUPPORTED_FIELD_WIDGETS),
        "datasets": sorted(DATASET_MODEL_FACTORIES.keys()),
    }