# services/vectoplan-library/src/vplib/defaults/manufacturer_defaults.py
"""
Manufacturer defaults for the VPLIB package engine.

Diese Datei erzeugt robuste Default-Daten für:

    manufacturer/contract.json
    optional: manufacturer/override_slots.json
    optional: manufacturer/product_fields.json
    optional: manufacturer/product_categories.json
    optional: manufacturer/branding.json
    optional: manufacturer/assets.json

Manufacturer-Daten definieren, ob und wie Hersteller später eine neutrale
Creative-Library-Family mit produktspezifischen Daten ergänzen dürfen.

Wichtig:
Herstellerdaten dürfen die semantische Family nicht zerstören. Sie ergänzen
oder überschreiben nur ausdrücklich erlaubte Felder über override_slots.

Diese Datei schreibt keine Dateien. Sie erzeugt nur JSON-kompatible Payloads.

Technische Namen, JSON-Keys und Variablen bleiben Englisch.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from enum import Enum
from functools import lru_cache
from typing import Any, Final, Iterable, Mapping


MANUFACTURER_DEFAULTS_SCHEMA_VERSION: Final[str] = "vplib.manufacturer_defaults.v1"
MANUFACTURER_CONTRACT_DOCUMENT_SCHEMA_VERSION: Final[str] = "vplib.manufacturer.contract.v1"
MANUFACTURER_OVERRIDE_SLOTS_DOCUMENT_SCHEMA_VERSION: Final[str] = "vplib.manufacturer.override_slots.v1"
MANUFACTURER_PRODUCT_FIELDS_DOCUMENT_SCHEMA_VERSION: Final[str] = "vplib.manufacturer.product_fields.v1"
MANUFACTURER_PRODUCT_CATEGORIES_DOCUMENT_SCHEMA_VERSION: Final[str] = "vplib.manufacturer.product_categories.v1"
MANUFACTURER_BRANDING_DOCUMENT_SCHEMA_VERSION: Final[str] = "vplib.manufacturer.branding.v1"
MANUFACTURER_ASSETS_DOCUMENT_SCHEMA_VERSION: Final[str] = "vplib.manufacturer.assets.v1"

DEFAULT_CONTRACT_ID: Final[str] = "default_contract"
DEFAULT_MANUFACTURER_ID: Final[str] = "generic_manufacturer"
DEFAULT_OVERLAY_LEVEL: Final[str] = "none"
DEFAULT_PRODUCT_CATEGORY_ID: Final[str] = "generic_product"
DEFAULT_BRAND_COLOR: Final[str] = "#64748B"

SAFE_MANUFACTURER_KEY_RE: Final[re.Pattern[str]] = re.compile(
    r"^[a-z0-9][a-z0-9._-]*[a-z0-9]$|^[a-z0-9]$"
)
SAFE_FIELD_PATH_RE: Final[re.Pattern[str]] = re.compile(
    r"^[a-zA-Z0-9_][a-zA-Z0-9_.-]*[a-zA-Z0-9_]$|^[a-zA-Z0-9_]$"
)
SAFE_HEX_COLOR_RE: Final[re.Pattern[str]] = re.compile(
    r"^#(?:[0-9a-fA-F]{3}|[0-9a-fA-F]{6}|[0-9a-fA-F]{8})$"
)

FORBIDDEN_MANUFACTURER_OVERRIDE_PREFIXES: Final[tuple[str, ...]] = (
    "schema_version",
    "vplib_version",
    "package_id",
    "family_id",
    "family_slug",
    "family_name",
    "object_kind",
    "classification",
    "classification_path",
    "domain",
    "tab",
    "category",
    "subcategory",
    "active_modules",
    "required_modules",
    "optional_modules",
    "module_versions",
)

DEFAULT_ALLOWED_OVERRIDE_PREFIXES: Final[tuple[str, ...]] = (
    "variant",
    "editor.inventory",
    "render",
    "physical",
    "material",
    "calculation",
    "manufacturer",
)


class ManufacturerDefaultsError(ValueError):
    """Wird ausgelöst, wenn Manufacturer-Defaults ungültig erzeugt werden."""


class ManufacturerContractMode(str, Enum):
    """Vertragsmodus für Herstellerdaten."""

    DISABLED = "disabled"
    ALLOWED = "allowed"
    REQUIRED = "required"

    @property
    def key(self) -> str:
        return str(self.value)


class ManufacturerOverlayLevel(str, Enum):
    """Erlaubter Overlay-Level."""

    NONE = "none"
    PRODUCT_METADATA = "product_metadata"
    BRANDING = "branding"
    RENDER = "render"
    MATERIAL = "material"
    PERFORMANCE = "performance"
    COMMERCIAL = "commercial"
    FULL_ALLOWED_SLOTS = "full_allowed_slots"

    @property
    def key(self) -> str:
        return str(self.value)


class ManufacturerOverrideScope(str, Enum):
    """Scope eines Override-Slots."""

    VARIANT = "variant"
    EDITOR = "editor"
    RENDER = "render"
    PHYSICAL = "physical"
    MATERIAL = "material"
    CALCULATION = "calculation"
    ANALYSIS = "analysis"
    MANUFACTURER = "manufacturer"

    @property
    def key(self) -> str:
        return str(self.value)


class ManufacturerValueType(str, Enum):
    """Datentyp eines Herstellerfeldes oder Override-Slots."""

    STRING = "string"
    INTEGER = "integer"
    NUMBER = "number"
    BOOLEAN = "boolean"
    ENUM = "enum"
    COLOR = "color"
    ASSET_REF = "asset_ref"
    UNIT_VALUE = "unit_value"
    OBJECT = "object"
    ARRAY = "array"

    @property
    def key(self) -> str:
        return str(self.value)


class ManufacturerAssetRole(str, Enum):
    """Rolle eines Herstellerassets."""

    LOGO = "logo"
    PRODUCT_IMAGE = "product_image"
    PRODUCT_PREVIEW = "product_preview"
    MATERIAL_TEXTURE = "material_texture"
    MODEL = "model"
    DOCUMENTATION = "documentation"
    DATASHEET = "datasheet"
    CERTIFICATE = "certificate"
    OTHER = "other"

    @property
    def key(self) -> str:
        return str(self.value)


class ProductFieldGroup(str, Enum):
    """Gruppe eines Produktfeldes."""

    IDENTITY = "identity"
    TECHNICAL = "technical"
    COMMERCIAL = "commercial"
    PERFORMANCE = "performance"
    DOCUMENTATION = "documentation"
    LOGISTICS = "logistics"
    CUSTOM = "custom"

    @property
    def key(self) -> str:
        return str(self.value)


class ProductCategoryKind(str, Enum):
    """Art einer Hersteller-Produktkategorie."""

    GENERIC = "generic"
    BUILDING_COMPONENT = "building_component"
    EQUIPMENT = "equipment"
    MATERIAL = "material"
    SYSTEM = "system"
    ACCESSORY = "accessory"
    SERVICE = "service"

    @property
    def key(self) -> str:
        return str(self.value)


class ManufacturerValidationPolicy(str, Enum):
    """Validierungspolitik für Herstellerdaten."""

    STRICT = "strict"
    NORMAL = "normal"
    PERMISSIVE = "permissive"

    @property
    def key(self) -> str:
        return str(self.value)


@dataclass(frozen=True, slots=True)
class ManufacturerContractDefaults:
    """Defaults für manufacturer/contract.json."""

    contract_id: str = DEFAULT_CONTRACT_ID
    manufacturer_allowed: bool = False
    contract_mode: str = ManufacturerContractMode.DISABLED.value
    overlay_level: str = ManufacturerOverlayLevel.NONE.value
    validation_policy: str = ManufacturerValidationPolicy.STRICT.value
    allow_branding: bool = False
    allow_product_mapping: bool = False
    allow_asset_overrides: bool = False
    allow_render_overrides: bool = False
    allow_material_overrides: bool = False
    allow_physical_overrides: bool = False
    allow_calculation_overrides: bool = False
    require_product_identity: bool = False
    require_datasheet: bool = False
    require_validation: bool = True
    allowed_override_prefixes: tuple[str, ...] = DEFAULT_ALLOWED_OVERRIDE_PREFIXES
    forbidden_override_prefixes: tuple[str, ...] = FORBIDDEN_MANUFACTURER_OVERRIDE_PREFIXES
    metadata: Mapping[str, Any] = field(default_factory=dict)

    def normalized(self) -> "ManufacturerContractDefaults":
        contract_id = normalize_manufacturer_key(self.contract_id, "contract_id")
        manufacturer_allowed = bool(self.manufacturer_allowed)
        contract_mode = parse_contract_mode_value(self.contract_mode)
        overlay_level = parse_overlay_level_value(self.overlay_level)
        validation_policy = parse_validation_policy_value(self.validation_policy)

        if not manufacturer_allowed:
            contract_mode = ManufacturerContractMode.DISABLED.value
            overlay_level = ManufacturerOverlayLevel.NONE.value

        allow_branding = bool(self.allow_branding)
        allow_product_mapping = bool(self.allow_product_mapping)
        allow_asset_overrides = bool(self.allow_asset_overrides)
        allow_render_overrides = bool(self.allow_render_overrides)
        allow_material_overrides = bool(self.allow_material_overrides)
        allow_physical_overrides = bool(self.allow_physical_overrides)
        allow_calculation_overrides = bool(self.allow_calculation_overrides)

        if overlay_level == ManufacturerOverlayLevel.BRANDING.value:
            allow_branding = True
        elif overlay_level == ManufacturerOverlayLevel.RENDER.value:
            allow_branding = True
            allow_asset_overrides = True
            allow_render_overrides = True
        elif overlay_level == ManufacturerOverlayLevel.MATERIAL.value:
            allow_branding = True
            allow_material_overrides = True
        elif overlay_level == ManufacturerOverlayLevel.PERFORMANCE.value:
            allow_material_overrides = True
            allow_physical_overrides = True
            allow_calculation_overrides = True
        elif overlay_level == ManufacturerOverlayLevel.COMMERCIAL.value:
            allow_product_mapping = True
        elif overlay_level == ManufacturerOverlayLevel.FULL_ALLOWED_SLOTS.value:
            allow_branding = True
            allow_product_mapping = True
            allow_asset_overrides = True
            allow_render_overrides = True
            allow_material_overrides = True
            allow_physical_overrides = True
            allow_calculation_overrides = True

        return ManufacturerContractDefaults(
            contract_id=contract_id,
            manufacturer_allowed=manufacturer_allowed,
            contract_mode=contract_mode,
            overlay_level=overlay_level,
            validation_policy=validation_policy,
            allow_branding=allow_branding,
            allow_product_mapping=allow_product_mapping,
            allow_asset_overrides=allow_asset_overrides,
            allow_render_overrides=allow_render_overrides,
            allow_material_overrides=allow_material_overrides,
            allow_physical_overrides=allow_physical_overrides,
            allow_calculation_overrides=allow_calculation_overrides,
            require_product_identity=bool(self.require_product_identity),
            require_datasheet=bool(self.require_datasheet),
            require_validation=bool(self.require_validation),
            allowed_override_prefixes=normalize_field_prefix_tuple(self.allowed_override_prefixes),
            forbidden_override_prefixes=normalize_field_prefix_tuple(self.forbidden_override_prefixes),
            metadata=normalize_metadata(self.metadata),
        )

    def to_document(self) -> dict[str, Any]:
        """Erzeugt manufacturer/contract.json."""
        normalized = self.normalized()

        return {
            "schema_version": MANUFACTURER_CONTRACT_DOCUMENT_SCHEMA_VERSION,
            "contract_id": normalized.contract_id,
            "manufacturer_allowed": normalized.manufacturer_allowed,
            "contract_mode": normalized.contract_mode,
            "overlay_level": normalized.overlay_level,
            "validation_policy": normalized.validation_policy,
            "allow_branding": normalized.allow_branding,
            "allow_product_mapping": normalized.allow_product_mapping,
            "allow_asset_overrides": normalized.allow_asset_overrides,
            "allow_render_overrides": normalized.allow_render_overrides,
            "allow_material_overrides": normalized.allow_material_overrides,
            "allow_physical_overrides": normalized.allow_physical_overrides,
            "allow_calculation_overrides": normalized.allow_calculation_overrides,
            "require_product_identity": normalized.require_product_identity,
            "require_datasheet": normalized.require_datasheet,
            "require_validation": normalized.require_validation,
            "allowed_override_prefixes": list(normalized.allowed_override_prefixes),
            "forbidden_override_prefixes": list(normalized.forbidden_override_prefixes),
            "metadata": dict(normalized.metadata),
        }

    def to_dict(self) -> dict[str, Any]:
        return self.to_document()


@dataclass(frozen=True, slots=True)
class ManufacturerOverrideSlotDefaults:
    """Ein erlaubter Hersteller-Override-Slot."""

    slot_id: str
    field_path: str
    scope: str
    value_type: str
    label: str | None = None
    description: str = ""
    unit: str | None = None
    required: bool = False
    editable: bool = True
    default_value: Any = None
    allowed_values: tuple[Any, ...] = field(default_factory=tuple)
    min_value: float | None = None
    max_value: float | None = None
    metadata: Mapping[str, Any] = field(default_factory=dict)

    def normalized(self) -> "ManufacturerOverrideSlotDefaults":
        slot_id = normalize_manufacturer_key(self.slot_id, "slot_id")
        field_path = normalize_field_path(self.field_path)
        assert_override_field_allowed(field_path)

        scope = parse_override_scope_value(self.scope)
        value_type = parse_value_type_value(self.value_type)
        label = clean_optional_string(self.label) or humanize_key(slot_id)
        description = clean_optional_string(self.description) or ""
        unit = normalize_optional_unit_value(self.unit)
        required = bool(self.required)
        editable = bool(self.editable)
        default_value = normalize_typed_value(self.default_value, value_type, allow_none=True)
        allowed_values = tuple(
            normalize_typed_value(value, value_type, allow_none=False)
            for value in self.allowed_values or ()
        )
        min_value = normalize_optional_float(self.min_value, "min_value")
        max_value = normalize_optional_float(self.max_value, "max_value")

        if min_value is not None and max_value is not None and min_value > max_value:
            raise ManufacturerDefaultsError(f"Override slot {slot_id!r} has min_value greater than max_value.")

        if default_value is not None and allowed_values and default_value not in allowed_values:
            raise ManufacturerDefaultsError(f"Override slot {slot_id!r} default_value is not in allowed_values.")

        return ManufacturerOverrideSlotDefaults(
            slot_id=slot_id,
            field_path=field_path,
            scope=scope,
            value_type=value_type,
            label=label,
            description=description,
            unit=unit,
            required=required,
            editable=editable,
            default_value=default_value,
            allowed_values=allowed_values,
            min_value=min_value,
            max_value=max_value,
            metadata=normalize_metadata(self.metadata),
        )

    def to_dict(self) -> dict[str, Any]:
        normalized = self.normalized()

        return {
            "slot_id": normalized.slot_id,
            "field_path": normalized.field_path,
            "scope": normalized.scope,
            "value_type": normalized.value_type,
            "label": normalized.label,
            "description": normalized.description,
            "unit": normalized.unit,
            "required": normalized.required,
            "editable": normalized.editable,
            "default_value": normalized.default_value,
            "allowed_values": list(normalized.allowed_values),
            "min_value": normalized.min_value,
            "max_value": normalized.max_value,
            "metadata": dict(normalized.metadata),
        }


@dataclass(frozen=True, slots=True)
class ManufacturerOverrideSlotsDefaults:
    """Defaults für manufacturer/override_slots.json."""

    override_slots: tuple[ManufacturerOverrideSlotDefaults, ...] = field(default_factory=tuple)
    metadata: Mapping[str, Any] = field(default_factory=dict)

    def normalized(self) -> "ManufacturerOverrideSlotsDefaults":
        override_slots = tuple(slot.normalized() for slot in self.override_slots or ())
        assert_unique_values([slot.slot_id for slot in override_slots], "slot_id")
        assert_unique_values([slot.field_path for slot in override_slots], "field_path")

        return ManufacturerOverrideSlotsDefaults(
            override_slots=tuple(sorted(override_slots, key=lambda item: item.slot_id)),
            metadata=normalize_metadata(self.metadata),
        )

    def to_document(self) -> dict[str, Any]:
        """Erzeugt manufacturer/override_slots.json."""
        normalized = self.normalized()

        return {
            "schema_version": MANUFACTURER_OVERRIDE_SLOTS_DOCUMENT_SCHEMA_VERSION,
            "slot_ids": [slot.slot_id for slot in normalized.override_slots],
            "override_slots": [slot.to_dict() for slot in normalized.override_slots],
            "metadata": dict(normalized.metadata),
        }

    def to_dict(self) -> dict[str, Any]:
        return self.to_document()


@dataclass(frozen=True, slots=True)
class ManufacturerProductFieldDefaults:
    """Ein Hersteller-Produktfeld."""

    field_id: str
    label: str | None = None
    value_type: str = ManufacturerValueType.STRING.value
    field_group: str = ProductFieldGroup.IDENTITY.value
    unit: str | None = None
    required: bool = False
    searchable: bool = True
    display_in_inventory: bool = False
    default_value: Any = None
    allowed_values: tuple[Any, ...] = field(default_factory=tuple)
    description: str = ""
    metadata: Mapping[str, Any] = field(default_factory=dict)

    def normalized(self) -> "ManufacturerProductFieldDefaults":
        field_id = normalize_manufacturer_key(self.field_id, "field_id")
        label = clean_optional_string(self.label) or humanize_key(field_id)
        value_type = parse_value_type_value(self.value_type)
        field_group = parse_product_field_group_value(self.field_group)
        unit = normalize_optional_unit_value(self.unit)
        required = bool(self.required)
        searchable = bool(self.searchable)
        display_in_inventory = bool(self.display_in_inventory)
        default_value = normalize_typed_value(self.default_value, value_type, allow_none=True)
        allowed_values = tuple(
            normalize_typed_value(value, value_type, allow_none=False)
            for value in self.allowed_values or ()
        )
        description = clean_optional_string(self.description) or ""

        if default_value is not None and allowed_values and default_value not in allowed_values:
            raise ManufacturerDefaultsError(f"Product field {field_id!r} default_value is not in allowed_values.")

        return ManufacturerProductFieldDefaults(
            field_id=field_id,
            label=label,
            value_type=value_type,
            field_group=field_group,
            unit=unit,
            required=required,
            searchable=searchable,
            display_in_inventory=display_in_inventory,
            default_value=default_value,
            allowed_values=allowed_values,
            description=description,
            metadata=normalize_metadata(self.metadata),
        )

    def to_dict(self) -> dict[str, Any]:
        normalized = self.normalized()

        return {
            "field_id": normalized.field_id,
            "label": normalized.label,
            "value_type": normalized.value_type,
            "field_group": normalized.field_group,
            "unit": normalized.unit,
            "required": normalized.required,
            "searchable": normalized.searchable,
            "display_in_inventory": normalized.display_in_inventory,
            "default_value": normalized.default_value,
            "allowed_values": list(normalized.allowed_values),
            "description": normalized.description,
            "metadata": dict(normalized.metadata),
        }


@dataclass(frozen=True, slots=True)
class ManufacturerProductFieldsDefaults:
    """Defaults für manufacturer/product_fields.json."""

    product_fields: tuple[ManufacturerProductFieldDefaults, ...] = field(default_factory=tuple)
    metadata: Mapping[str, Any] = field(default_factory=dict)

    def normalized(self) -> "ManufacturerProductFieldsDefaults":
        product_fields = tuple(field.normalized() for field in self.product_fields or ())

        if not product_fields:
            product_fields = default_product_fields()

        assert_unique_values([field.field_id for field in product_fields], "field_id")

        return ManufacturerProductFieldsDefaults(
            product_fields=tuple(sorted(product_fields, key=lambda item: (item.field_group, item.field_id))),
            metadata=normalize_metadata(self.metadata),
        )

    def to_document(self) -> dict[str, Any]:
        """Erzeugt manufacturer/product_fields.json."""
        normalized = self.normalized()

        return {
            "schema_version": MANUFACTURER_PRODUCT_FIELDS_DOCUMENT_SCHEMA_VERSION,
            "field_ids": [field.field_id for field in normalized.product_fields],
            "product_fields": [field.to_dict() for field in normalized.product_fields],
            "metadata": dict(normalized.metadata),
        }

    def to_dict(self) -> dict[str, Any]:
        return self.to_document()


@dataclass(frozen=True, slots=True)
class ManufacturerProductCategoryDefaults:
    """Eine Hersteller-Produktkategorie."""

    category_id: str = DEFAULT_PRODUCT_CATEGORY_ID
    label: str | None = None
    category_kind: str = ProductCategoryKind.GENERIC.value
    description: str = ""
    parent_category_id: str | None = None
    tags: tuple[str, ...] = field(default_factory=tuple)
    metadata: Mapping[str, Any] = field(default_factory=dict)

    def normalized(self) -> "ManufacturerProductCategoryDefaults":
        category_id = normalize_manufacturer_key(self.category_id, "category_id")
        label = clean_optional_string(self.label) or humanize_key(category_id)
        category_kind = parse_product_category_kind_value(self.category_kind)
        description = clean_optional_string(self.description) or ""
        parent_category_id = normalize_optional_manufacturer_key(self.parent_category_id, "parent_category_id")
        tags = normalize_string_tuple(self.tags)

        if parent_category_id == category_id:
            raise ManufacturerDefaultsError(f"Product category {category_id!r} cannot be its own parent.")

        return ManufacturerProductCategoryDefaults(
            category_id=category_id,
            label=label,
            category_kind=category_kind,
            description=description,
            parent_category_id=parent_category_id,
            tags=tags,
            metadata=normalize_metadata(self.metadata),
        )

    def to_dict(self) -> dict[str, Any]:
        normalized = self.normalized()

        return {
            "category_id": normalized.category_id,
            "label": normalized.label,
            "category_kind": normalized.category_kind,
            "description": normalized.description,
            "parent_category_id": normalized.parent_category_id,
            "tags": list(normalized.tags),
            "metadata": dict(normalized.metadata),
        }


@dataclass(frozen=True, slots=True)
class ManufacturerProductCategoriesDefaults:
    """Defaults für manufacturer/product_categories.json."""

    product_categories: tuple[ManufacturerProductCategoryDefaults, ...] = field(default_factory=tuple)
    default_category_id: str = DEFAULT_PRODUCT_CATEGORY_ID
    metadata: Mapping[str, Any] = field(default_factory=dict)

    def normalized(self) -> "ManufacturerProductCategoriesDefaults":
        default_category_id = normalize_manufacturer_key(self.default_category_id, "default_category_id")
        product_categories = tuple(category.normalized() for category in self.product_categories or ())

        if not product_categories:
            product_categories = (
                ManufacturerProductCategoryDefaults(
                    category_id=default_category_id,
                    label="Generic Product",
                    category_kind=ProductCategoryKind.GENERIC.value,
                ).normalized(),
            )

        category_ids = [category.category_id for category in product_categories]
        assert_unique_values(category_ids, "category_id")

        if default_category_id not in set(category_ids):
            product_categories = (
                ManufacturerProductCategoryDefaults(
                    category_id=default_category_id,
                    label="Generic Product",
                    category_kind=ProductCategoryKind.GENERIC.value,
                ).normalized(),
                *product_categories,
            )

        category_id_set = {category.category_id for category in product_categories}
        for category in product_categories:
            if category.parent_category_id and category.parent_category_id not in category_id_set:
                raise ManufacturerDefaultsError(
                    f"Product category {category.category_id!r} references unknown parent "
                    f"{category.parent_category_id!r}."
                )

        return ManufacturerProductCategoriesDefaults(
            product_categories=tuple(sorted(product_categories, key=lambda item: item.category_id)),
            default_category_id=default_category_id,
            metadata=normalize_metadata(self.metadata),
        )

    def to_document(self) -> dict[str, Any]:
        """Erzeugt manufacturer/product_categories.json."""
        normalized = self.normalized()

        return {
            "schema_version": MANUFACTURER_PRODUCT_CATEGORIES_DOCUMENT_SCHEMA_VERSION,
            "default_category_id": normalized.default_category_id,
            "category_ids": [category.category_id for category in normalized.product_categories],
            "product_categories": [category.to_dict() for category in normalized.product_categories],
            "metadata": dict(normalized.metadata),
        }

    def to_dict(self) -> dict[str, Any]:
        return self.to_document()


@dataclass(frozen=True, slots=True)
class ManufacturerBrandingDefaults:
    """Defaults für manufacturer/branding.json."""

    manufacturer_id: str = DEFAULT_MANUFACTURER_ID
    manufacturer_name: str | None = None
    brand_name: str | None = None
    brand_color: str = DEFAULT_BRAND_COLOR
    logo_ref: str | None = None
    website_url: str | None = None
    support_url: str | None = None
    metadata: Mapping[str, Any] = field(default_factory=dict)

    def normalized(self) -> "ManufacturerBrandingDefaults":
        manufacturer_id = normalize_manufacturer_key(self.manufacturer_id, "manufacturer_id")
        manufacturer_name = clean_optional_string(self.manufacturer_name) or humanize_key(manufacturer_id)
        brand_name = clean_optional_string(self.brand_name) or manufacturer_name
        brand_color = normalize_color(self.brand_color)
        logo_ref = clean_optional_string(self.logo_ref)
        website_url = clean_optional_string(self.website_url)
        support_url = clean_optional_string(self.support_url)

        return ManufacturerBrandingDefaults(
            manufacturer_id=manufacturer_id,
            manufacturer_name=manufacturer_name,
            brand_name=brand_name,
            brand_color=brand_color,
            logo_ref=logo_ref,
            website_url=website_url,
            support_url=support_url,
            metadata=normalize_metadata(self.metadata),
        )

    def to_document(self) -> dict[str, Any]:
        """Erzeugt manufacturer/branding.json."""
        normalized = self.normalized()

        return {
            "schema_version": MANUFACTURER_BRANDING_DOCUMENT_SCHEMA_VERSION,
            "manufacturer_id": normalized.manufacturer_id,
            "manufacturer_name": normalized.manufacturer_name,
            "brand_name": normalized.brand_name,
            "brand_color": normalized.brand_color,
            "logo_ref": normalized.logo_ref,
            "website_url": normalized.website_url,
            "support_url": normalized.support_url,
            "metadata": dict(normalized.metadata),
        }

    def to_dict(self) -> dict[str, Any]:
        return self.to_document()


@dataclass(frozen=True, slots=True)
class ManufacturerAssetDefaults:
    """Ein Herstellerasset für manufacturer/assets.json."""

    asset_id: str
    role: str
    ref: str
    label: str | None = None
    mime_type: str | None = None
    required: bool = False
    metadata: Mapping[str, Any] = field(default_factory=dict)

    def normalized(self) -> "ManufacturerAssetDefaults":
        asset_id = normalize_manufacturer_key(self.asset_id, "asset_id")
        role = parse_asset_role_value(self.role)
        ref = clean_required_string(self.ref, "ref")
        label = clean_optional_string(self.label) or humanize_key(asset_id)
        mime_type = clean_optional_string(self.mime_type)

        return ManufacturerAssetDefaults(
            asset_id=asset_id,
            role=role,
            ref=ref,
            label=label,
            mime_type=mime_type,
            required=bool(self.required),
            metadata=normalize_metadata(self.metadata),
        )

    def to_dict(self) -> dict[str, Any]:
        normalized = self.normalized()

        return {
            "asset_id": normalized.asset_id,
            "role": normalized.role,
            "ref": normalized.ref,
            "label": normalized.label,
            "mime_type": normalized.mime_type,
            "required": normalized.required,
            "metadata": dict(normalized.metadata),
        }


@dataclass(frozen=True, slots=True)
class ManufacturerAssetsDefaults:
    """Defaults für manufacturer/assets.json."""

    assets: tuple[ManufacturerAssetDefaults, ...] = field(default_factory=tuple)
    metadata: Mapping[str, Any] = field(default_factory=dict)

    def normalized(self) -> "ManufacturerAssetsDefaults":
        assets = tuple(asset.normalized() for asset in self.assets or ())
        assert_unique_values([asset.asset_id for asset in assets], "asset_id")

        return ManufacturerAssetsDefaults(
            assets=tuple(sorted(assets, key=lambda item: item.asset_id)),
            metadata=normalize_metadata(self.metadata),
        )

    def to_document(self) -> dict[str, Any]:
        """Erzeugt manufacturer/assets.json."""
        normalized = self.normalized()

        return {
            "schema_version": MANUFACTURER_ASSETS_DOCUMENT_SCHEMA_VERSION,
            "asset_ids": [asset.asset_id for asset in normalized.assets],
            "assets": [asset.to_dict() for asset in normalized.assets],
            "metadata": dict(normalized.metadata),
        }

    def to_dict(self) -> dict[str, Any]:
        return self.to_document()


@dataclass(frozen=True, slots=True)
class ManufacturerDefaults:
    """Vollständige Defaults für alle manufacturer/*.json-Dokumente."""

    contract: ManufacturerContractDefaults = field(default_factory=ManufacturerContractDefaults)
    override_slots: ManufacturerOverrideSlotsDefaults = field(default_factory=ManufacturerOverrideSlotsDefaults)
    product_fields: ManufacturerProductFieldsDefaults = field(default_factory=ManufacturerProductFieldsDefaults)
    product_categories: ManufacturerProductCategoriesDefaults = field(default_factory=ManufacturerProductCategoriesDefaults)
    branding: ManufacturerBrandingDefaults = field(default_factory=ManufacturerBrandingDefaults)
    assets: ManufacturerAssetsDefaults = field(default_factory=ManufacturerAssetsDefaults)

    def normalized(self) -> "ManufacturerDefaults":
        contract = self.contract.normalized()
        override_slots = self.override_slots.normalized()
        product_fields = self.product_fields.normalized()
        product_categories = self.product_categories.normalized()
        branding = self.branding.normalized()
        assets = self.assets.normalized()

        if not contract.manufacturer_allowed and override_slots.override_slots:
            raise ManufacturerDefaultsError("manufacturer_allowed is false, but override_slots are defined.")

        if contract.contract_mode == ManufacturerContractMode.REQUIRED.value:
            required_identity_fields = {"manufacturer_id", "product_id", "product_name"}
            existing_required_fields = {
                field.field_id
                for field in product_fields.product_fields
                if field.required
            }
            missing = required_identity_fields - existing_required_fields
            if missing:
                raise ManufacturerDefaultsError(
                    "Required manufacturer contract needs required product fields: "
                    + ", ".join(sorted(missing))
                )

        return ManufacturerDefaults(
            contract=contract,
            override_slots=override_slots,
            product_fields=product_fields,
            product_categories=product_categories,
            branding=branding,
            assets=assets,
        )

    def to_documents(self, *, include_optional: bool = True) -> dict[str, dict[str, Any]]:
        """Erzeugt alle Manufacturer-Dokumente als Pfad -> Payload."""
        normalized = self.normalized()

        documents: dict[str, dict[str, Any]] = {
            "manufacturer/contract.json": normalized.contract.to_document(),
        }

        if include_optional:
            documents["manufacturer/override_slots.json"] = normalized.override_slots.to_document()
            documents["manufacturer/product_fields.json"] = normalized.product_fields.to_document()
            documents["manufacturer/product_categories.json"] = normalized.product_categories.to_document()
            documents["manufacturer/branding.json"] = normalized.branding.to_document()
            documents["manufacturer/assets.json"] = normalized.assets.to_document()

        return documents

    def to_dict(self) -> dict[str, Any]:
        normalized = self.normalized()

        return {
            "schema_version": MANUFACTURER_DEFAULTS_SCHEMA_VERSION,
            "contract": normalized.contract.to_dict(),
            "override_slots": normalized.override_slots.to_dict(),
            "product_fields": normalized.product_fields.to_dict(),
            "product_categories": normalized.product_categories.to_dict(),
            "branding": normalized.branding.to_dict(),
            "assets": normalized.assets.to_dict(),
        }


def build_manufacturer_defaults(
    *,
    manufacturer_allowed: bool = False,
    contract_mode: str | None = None,
    overlay_level: str = DEFAULT_OVERLAY_LEVEL,
    override_slots: Iterable[ManufacturerOverrideSlotDefaults | Mapping[str, Any]] = (),
    required_product_fields: Iterable[Any] = (),
    product_categories: Iterable[ManufacturerProductCategoryDefaults | Mapping[str, Any] | str] = (),
    metadata: Mapping[str, Any] | None = None,
) -> ManufacturerDefaults:
    """Baut ManufacturerDefaults aus expliziten Werten."""
    try:
        normalized_contract_mode = (
            contract_mode
            if contract_mode is not None
            else ManufacturerContractMode.ALLOWED.value
            if manufacturer_allowed
            else ManufacturerContractMode.DISABLED.value
        )

        parsed_override_slots = tuple(
            slot if isinstance(slot, ManufacturerOverrideSlotDefaults) else override_slot_from_mapping(slot)
            for slot in override_slots or ()
        )

        parsed_product_fields = merge_product_fields(
            default_product_fields(),
            product_fields_from_required_names(required_product_fields),
        )

        parsed_product_categories = tuple(
            product_category_from_value(category)
            for category in product_categories or ()
        )

        return ManufacturerDefaults(
            contract=ManufacturerContractDefaults(
                manufacturer_allowed=manufacturer_allowed,
                contract_mode=normalized_contract_mode,
                overlay_level=overlay_level,
                metadata=dict(metadata or {}),
            ),
            override_slots=ManufacturerOverrideSlotsDefaults(
                override_slots=parsed_override_slots,
                metadata=dict(metadata or {}),
            ),
            product_fields=ManufacturerProductFieldsDefaults(
                product_fields=parsed_product_fields,
                metadata=dict(metadata or {}),
            ),
            product_categories=ManufacturerProductCategoriesDefaults(
                product_categories=parsed_product_categories,
                metadata=dict(metadata or {}),
            ),
            branding=ManufacturerBrandingDefaults(metadata=dict(metadata or {})),
            assets=ManufacturerAssetsDefaults(metadata=dict(metadata or {})),
        ).normalized()
    except ManufacturerDefaultsError:
        raise
    except Exception as exc:
        raise ManufacturerDefaultsError(f"Could not build manufacturer defaults: {exc}") from exc


def manufacturer_defaults_from_create_request(
    request: Any,
    *,
    metadata: Mapping[str, Any] | None = None,
) -> ManufacturerDefaults:
    """Baut ManufacturerDefaults aus einem CreateRequest-ähnlichen Objekt."""
    try:
        normalized_request = normalize_create_request(request)
        manufacturer = normalized_request.manufacturer.normalized()

        return build_manufacturer_defaults(
            manufacturer_allowed=manufacturer.manufacturer_allowed,
            overlay_level=manufacturer.overlay_level,
            override_slots=manufacturer.override_slots,
            required_product_fields=manufacturer.required_product_fields,
            product_categories=manufacturer.product_categories,
            metadata={
                "source": "create_request",
                "object_kind": normalized_request.object_kind,
                **dict(metadata or {}),
            },
        )
    except ManufacturerDefaultsError:
        raise
    except Exception as exc:
        raise ManufacturerDefaultsError(f"Could not build manufacturer defaults from CreateRequest: {exc}") from exc


def manufacturer_defaults_from_context(
    context: Any,
    *,
    manufacturer_allowed: bool = False,
    overlay_level: str = DEFAULT_OVERLAY_LEVEL,
    metadata: Mapping[str, Any] | None = None,
) -> ManufacturerDefaults:
    """Baut ManufacturerDefaults aus einem PackageContext-ähnlichen Objekt."""
    try:
        normalized_context = context.normalized() if hasattr(context, "normalized") else context

        return build_manufacturer_defaults(
            manufacturer_allowed=manufacturer_allowed,
            overlay_level=overlay_level,
            metadata={
                "source": "package_context",
                "object_kind": normalized_context.object_kind,
                "correlation_id": getattr(normalized_context, "correlation_id", None),
                **dict(metadata or {}),
            },
        )
    except ManufacturerDefaultsError:
        raise
    except Exception as exc:
        raise ManufacturerDefaultsError(f"Could not build manufacturer defaults from PackageContext: {exc}") from exc


def manufacturer_defaults_from_creation_plan(
    creation_plan: Any,
    *,
    metadata: Mapping[str, Any] | None = None,
) -> ManufacturerDefaults:
    """Baut ManufacturerDefaults aus einem CreationPlan-ähnlichen Objekt."""
    try:
        normalized_plan = creation_plan.normalized() if hasattr(creation_plan, "normalized") else creation_plan

        return manufacturer_defaults_from_create_request(
            normalized_plan.request,
            metadata={
                "source": "creation_plan",
                "profile_key": getattr(normalized_plan.profile, "profile_key", None),
                **dict(metadata or {}),
            },
        )
    except ManufacturerDefaultsError:
        raise
    except Exception as exc:
        raise ManufacturerDefaultsError(f"Could not build manufacturer defaults from CreationPlan: {exc}") from exc


def manufacturer_documents_from_create_request(
    request: Any,
    *,
    include_optional: bool = True,
    metadata: Mapping[str, Any] | None = None,
) -> dict[str, dict[str, Any]]:
    """Baut alle manufacturer/*.json-Dokumente aus CreateRequest."""
    return manufacturer_defaults_from_create_request(
        request,
        metadata=metadata,
    ).to_documents(include_optional=include_optional)


def manufacturer_documents_from_context(
    context: Any,
    *,
    include_optional: bool = True,
    metadata: Mapping[str, Any] | None = None,
) -> dict[str, dict[str, Any]]:
    """Baut alle manufacturer/*.json-Dokumente aus PackageContext."""
    return manufacturer_defaults_from_context(
        context,
        metadata=metadata,
    ).to_documents(include_optional=include_optional)


def manufacturer_documents_from_creation_plan(
    creation_plan: Any,
    *,
    include_optional: bool = True,
    metadata: Mapping[str, Any] | None = None,
) -> dict[str, dict[str, Any]]:
    """Baut alle manufacturer/*.json-Dokumente aus CreationPlan."""
    return manufacturer_defaults_from_creation_plan(
        creation_plan,
        metadata=metadata,
    ).to_documents(include_optional=include_optional)


def override_slot_from_mapping(data: Mapping[str, Any]) -> ManufacturerOverrideSlotDefaults:
    """Baut ManufacturerOverrideSlotDefaults aus Mapping."""
    if not isinstance(data, Mapping):
        raise ManufacturerDefaultsError("Override slot data must be a mapping.")

    return ManufacturerOverrideSlotDefaults(
        slot_id=data.get("slot_id") or data.get("id"),
        field_path=data.get("field_path") or data.get("field"),
        scope=data.get("scope") or infer_scope_from_field_path(data.get("field_path") or data.get("field")),
        value_type=data.get("value_type") or data.get("type") or ManufacturerValueType.STRING.value,
        label=data.get("label") or data.get("name"),
        description=data.get("description", ""),
        unit=data.get("unit"),
        required=bool(data.get("required", False)),
        editable=bool(data.get("editable", True)),
        default_value=data.get("default_value"),
        allowed_values=tuple(data.get("allowed_values", ()) or ()),
        min_value=data.get("min_value"),
        max_value=data.get("max_value"),
        metadata=dict(data.get("metadata", {}) or {}),
    ).normalized()


def product_field_from_mapping(data: Mapping[str, Any]) -> ManufacturerProductFieldDefaults:
    """Baut ManufacturerProductFieldDefaults aus Mapping."""
    if not isinstance(data, Mapping):
        raise ManufacturerDefaultsError("Product field data must be a mapping.")

    return ManufacturerProductFieldDefaults(
        field_id=data.get("field_id") or data.get("id"),
        label=data.get("label") or data.get("name"),
        value_type=data.get("value_type") or data.get("type") or ManufacturerValueType.STRING.value,
        field_group=data.get("field_group", ProductFieldGroup.IDENTITY.value),
        unit=data.get("unit"),
        required=bool(data.get("required", False)),
        searchable=bool(data.get("searchable", True)),
        display_in_inventory=bool(data.get("display_in_inventory", False)),
        default_value=data.get("default_value"),
        allowed_values=tuple(data.get("allowed_values", ()) or ()),
        description=data.get("description", ""),
        metadata=dict(data.get("metadata", {}) or {}),
    ).normalized()


def product_category_from_mapping(data: Mapping[str, Any]) -> ManufacturerProductCategoryDefaults:
    """Baut ManufacturerProductCategoryDefaults aus Mapping."""
    if not isinstance(data, Mapping):
        raise ManufacturerDefaultsError("Product category data must be a mapping.")

    return ManufacturerProductCategoryDefaults(
        category_id=data.get("category_id") or data.get("id"),
        label=data.get("label") or data.get("name"),
        category_kind=data.get("category_kind", ProductCategoryKind.GENERIC.value),
        description=data.get("description", ""),
        parent_category_id=data.get("parent_category_id"),
        tags=tuple(data.get("tags", ()) or ()),
        metadata=dict(data.get("metadata", {}) or {}),
    ).normalized()


def product_category_from_value(value: Any) -> ManufacturerProductCategoryDefaults:
    """Baut ProductCategory aus String oder Mapping."""
    if isinstance(value, ManufacturerProductCategoryDefaults):
        return value.normalized()

    if isinstance(value, Mapping):
        return product_category_from_mapping(value)

    category_id = normalize_manufacturer_key(value, "category_id")
    return ManufacturerProductCategoryDefaults(
        category_id=category_id,
        label=humanize_key(category_id),
        category_kind=ProductCategoryKind.GENERIC.value,
    ).normalized()


def default_product_fields() -> tuple[ManufacturerProductFieldDefaults, ...]:
    """Erzeugt Standard-Produktfelder."""
    return (
        ManufacturerProductFieldDefaults(
            field_id="manufacturer_id",
            label="Manufacturer ID",
            value_type=ManufacturerValueType.STRING.value,
            field_group=ProductFieldGroup.IDENTITY.value,
            required=False,
            searchable=True,
        ).normalized(),
        ManufacturerProductFieldDefaults(
            field_id="manufacturer_name",
            label="Manufacturer Name",
            value_type=ManufacturerValueType.STRING.value,
            field_group=ProductFieldGroup.IDENTITY.value,
            required=False,
            searchable=True,
            display_in_inventory=True,
        ).normalized(),
        ManufacturerProductFieldDefaults(
            field_id="product_id",
            label="Product ID",
            value_type=ManufacturerValueType.STRING.value,
            field_group=ProductFieldGroup.IDENTITY.value,
            required=False,
            searchable=True,
        ).normalized(),
        ManufacturerProductFieldDefaults(
            field_id="product_name",
            label="Product Name",
            value_type=ManufacturerValueType.STRING.value,
            field_group=ProductFieldGroup.IDENTITY.value,
            required=False,
            searchable=True,
            display_in_inventory=True,
        ).normalized(),
        ManufacturerProductFieldDefaults(
            field_id="article_number",
            label="Article Number",
            value_type=ManufacturerValueType.STRING.value,
            field_group=ProductFieldGroup.IDENTITY.value,
            required=False,
            searchable=True,
        ).normalized(),
        ManufacturerProductFieldDefaults(
            field_id="datasheet_ref",
            label="Datasheet Reference",
            value_type=ManufacturerValueType.ASSET_REF.value,
            field_group=ProductFieldGroup.DOCUMENTATION.value,
            required=False,
            searchable=False,
        ).normalized(),
    )


def product_fields_from_required_names(values: Iterable[Any]) -> tuple[ManufacturerProductFieldDefaults, ...]:
    """Erzeugt required product fields aus Namen."""
    result: list[ManufacturerProductFieldDefaults] = []

    for value in values or ():
        field_id = normalize_manufacturer_key(value, "field_id")
        result.append(
            ManufacturerProductFieldDefaults(
                field_id=field_id,
                label=humanize_key(field_id),
                value_type=ManufacturerValueType.STRING.value,
                field_group=ProductFieldGroup.CUSTOM.value,
                required=True,
                searchable=True,
            ).normalized()
        )

    return tuple(result)


def merge_product_fields(
    left: Iterable[ManufacturerProductFieldDefaults],
    right: Iterable[ManufacturerProductFieldDefaults],
) -> tuple[ManufacturerProductFieldDefaults, ...]:
    """Merged Produktfelder anhand field_id."""
    by_id: dict[str, ManufacturerProductFieldDefaults] = {}

    for field_value in (*tuple(left or ()), *tuple(right or ())):
        field_normalized = field_value.normalized()
        existing = by_id.get(field_normalized.field_id)

        if existing is None:
            by_id[field_normalized.field_id] = field_normalized
            continue

        by_id[field_normalized.field_id] = ManufacturerProductFieldDefaults(
            field_id=field_normalized.field_id,
            label=field_normalized.label or existing.label,
            value_type=field_normalized.value_type or existing.value_type,
            field_group=field_normalized.field_group or existing.field_group,
            unit=field_normalized.unit or existing.unit,
            required=existing.required or field_normalized.required,
            searchable=existing.searchable or field_normalized.searchable,
            display_in_inventory=existing.display_in_inventory or field_normalized.display_in_inventory,
            default_value=field_normalized.default_value if field_normalized.default_value is not None else existing.default_value,
            allowed_values=field_normalized.allowed_values or existing.allowed_values,
            description=field_normalized.description or existing.description,
            metadata={**dict(existing.metadata), **dict(field_normalized.metadata)},
        ).normalized()

    return tuple(sorted(by_id.values(), key=lambda item: (item.field_group, item.field_id)))


def validate_manufacturer_contract_document(document: Mapping[str, Any]) -> tuple[bool, tuple[str, ...]]:
    """Validiert grob manufacturer/contract.json."""
    messages: list[str] = []

    try:
        if not isinstance(document, Mapping):
            return False, ("manufacturer/contract.json must be a mapping.",)

        required_fields = (
            "schema_version",
            "contract_id",
            "manufacturer_allowed",
            "contract_mode",
            "overlay_level",
            "validation_policy",
            "allowed_override_prefixes",
            "forbidden_override_prefixes",
        )

        for field_name in required_fields:
            if field_name not in document:
                messages.append(f"Missing manufacturer contract field {field_name!r}.")

        if "contract_mode" in document:
            try:
                parse_contract_mode_value(document["contract_mode"])
            except Exception as exc:
                messages.append(str(exc))

        if "overlay_level" in document:
            try:
                parse_overlay_level_value(document["overlay_level"])
            except Exception as exc:
                messages.append(str(exc))

    except Exception as exc:
        messages.append(f"Could not validate manufacturer contract document: {exc}")

    return len(messages) == 0, tuple(messages)


def validate_override_slots_document(document: Mapping[str, Any]) -> tuple[bool, tuple[str, ...]]:
    """Validiert grob manufacturer/override_slots.json."""
    messages: list[str] = []

    try:
        if not isinstance(document, Mapping):
            return False, ("manufacturer/override_slots.json must be a mapping.",)

        if "override_slots" not in document:
            messages.append("Missing override_slots field.")
        elif not isinstance(document["override_slots"], list):
            messages.append("override_slots must be a list.")
        else:
            for item in document["override_slots"]:
                try:
                    override_slot_from_mapping(item)
                except Exception as exc:
                    messages.append(str(exc))

    except Exception as exc:
        messages.append(f"Could not validate manufacturer override slots document: {exc}")

    return len(messages) == 0, tuple(messages)


def assert_valid_manufacturer_contract_document(document: Mapping[str, Any]) -> None:
    """Wirft ManufacturerDefaultsError, wenn manufacturer/contract.json ungültig ist."""
    valid, messages = validate_manufacturer_contract_document(document)

    if not valid:
        raise ManufacturerDefaultsError(
            " ".join(messages) if messages else "Invalid manufacturer contract document."
        )


def assert_valid_override_slots_document(document: Mapping[str, Any]) -> None:
    """Wirft ManufacturerDefaultsError, wenn manufacturer/override_slots.json ungültig ist."""
    valid, messages = validate_override_slots_document(document)

    if not valid:
        raise ManufacturerDefaultsError(
            " ".join(messages) if messages else "Invalid manufacturer override slots document."
        )


def infer_scope_from_field_path(field_path: Any) -> str:
    """Leitet Override-Scope aus field_path ab."""
    path = normalize_field_path(field_path)
    first = path.split(".", 1)[0]

    mapping = {
        "variant": ManufacturerOverrideScope.VARIANT.value,
        "editor": ManufacturerOverrideScope.EDITOR.value,
        "render": ManufacturerOverrideScope.RENDER.value,
        "physical": ManufacturerOverrideScope.PHYSICAL.value,
        "material": ManufacturerOverrideScope.MATERIAL.value,
        "calculation": ManufacturerOverrideScope.CALCULATION.value,
        "analysis": ManufacturerOverrideScope.ANALYSIS.value,
        "manufacturer": ManufacturerOverrideScope.MANUFACTURER.value,
    }

    return mapping.get(first, ManufacturerOverrideScope.MANUFACTURER.value)


def assert_override_field_allowed(field_path: str) -> None:
    """Prüft, ob ein Hersteller-Override-Feld erlaubt ist."""
    normalized_path = normalize_field_path(field_path)

    for forbidden_prefix in FORBIDDEN_MANUFACTURER_OVERRIDE_PREFIXES:
        if normalized_path == forbidden_prefix or normalized_path.startswith(f"{forbidden_prefix}."):
            raise ManufacturerDefaultsError(
                f"Manufacturer override field {normalized_path!r} is forbidden."
            )

    if not any(
        normalized_path == prefix or normalized_path.startswith(f"{prefix}.")
        for prefix in DEFAULT_ALLOWED_OVERRIDE_PREFIXES
    ):
        raise ManufacturerDefaultsError(
            f"Manufacturer override field {normalized_path!r} must start with one of: "
            f"{', '.join(DEFAULT_ALLOWED_OVERRIDE_PREFIXES)}."
        )


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

        raise ManufacturerDefaultsError("CreateRequest value is required.")
    except ManufacturerDefaultsError:
        raise
    except Exception as exc:
        raise ManufacturerDefaultsError(f"Invalid CreateRequest: {exc}") from exc


def normalize_manufacturer_key(value: Any, field_name: str) -> str:
    """Normalisiert technische Manufacturer-Keys."""
    raw = clean_required_string(value, field_name)
    key = (
        raw.lower()
        .replace(" ", "_")
        .replace("-", "_")
        .replace("/", "_")
        .replace("\\", "_")
    )

    if not SAFE_MANUFACTURER_KEY_RE.match(key):
        raise ManufacturerDefaultsError(f"{field_name} contains unsafe characters: {value!r}.")

    return key


def normalize_optional_manufacturer_key(value: Any, field_name: str) -> str | None:
    """Normalisiert optionale Manufacturer-Keys."""
    if value is None:
        return None

    return normalize_manufacturer_key(value, field_name)


def normalize_field_path(value: Any) -> str:
    """Normalisiert Field-Path."""
    raw = clean_required_string(value, "field_path")
    field_path = (
        raw.strip()
        .replace(" ", "_")
        .replace("/", ".")
        .replace("\\", ".")
    )

    if not SAFE_FIELD_PATH_RE.match(field_path):
        raise ManufacturerDefaultsError(f"Unsafe field_path {value!r}.")

    return field_path


def normalize_field_prefix_tuple(values: Iterable[Any]) -> tuple[str, ...]:
    """Normalisiert Field-Prefix-Liste."""
    result: list[str] = []
    seen: set[str] = set()

    for value in values or ():
        prefix = normalize_field_path(value)
        if prefix in seen:
            continue
        result.append(prefix)
        seen.add(prefix)

    return tuple(result)


def normalize_color(value: Any) -> str:
    """Normalisiert Hex-Farbe."""
    color = clean_required_string(value or DEFAULT_BRAND_COLOR, "color")

    if not SAFE_HEX_COLOR_RE.match(color):
        raise ManufacturerDefaultsError(f"Invalid color {value!r}.")

    return color


def normalize_optional_unit_value(value: Any) -> str | None:
    """Normalisiert optionale Unit-Werte."""
    if value is None:
        return None

    try:
        from ..domain.units import ensure_unit_value

        return ensure_unit_value(value)
    except Exception as exc:
        raise ManufacturerDefaultsError(f"Invalid unit {value!r}: {exc}") from exc


def normalize_typed_value(value: Any, value_type: str, *, allow_none: bool) -> Any:
    """Normalisiert Werte anhand ManufacturerValueType."""
    if value is None:
        if allow_none:
            return None
        raise ManufacturerDefaultsError("Value must not be None.")

    type_value = parse_value_type_value(value_type)

    try:
        if type_value == ManufacturerValueType.STRING.value:
            return str(value).strip()

        if type_value == ManufacturerValueType.INTEGER.value:
            if isinstance(value, bool):
                raise ManufacturerDefaultsError("Integer value must not be boolean.")
            return int(value)

        if type_value == ManufacturerValueType.NUMBER.value:
            if isinstance(value, bool):
                raise ManufacturerDefaultsError("Number value must not be boolean.")
            number = float(value)
            return int(number) if number.is_integer() else number

        if type_value == ManufacturerValueType.BOOLEAN.value:
            if isinstance(value, bool):
                return value
            raw = str(value).strip().lower()
            if raw in {"true", "1", "yes", "on"}:
                return True
            if raw in {"false", "0", "no", "off"}:
                return False
            raise ManufacturerDefaultsError(f"Invalid boolean value {value!r}.")

        if type_value == ManufacturerValueType.COLOR.value:
            return normalize_color(value)

        if type_value in {ManufacturerValueType.ENUM.value, ManufacturerValueType.ASSET_REF.value}:
            return str(value).strip()

        if type_value == ManufacturerValueType.UNIT_VALUE.value:
            if not isinstance(value, Mapping):
                raise ManufacturerDefaultsError("unit_value must be an object with value and unit.")
            return {
                "value": normalize_json_value(value.get("value")),
                "unit": normalize_optional_unit_value(value.get("unit")) or "none",
            }

        if type_value == ManufacturerValueType.OBJECT.value:
            if not isinstance(value, Mapping):
                raise ManufacturerDefaultsError("object value must be a mapping.")
            return normalize_json_value(value)

        if type_value == ManufacturerValueType.ARRAY.value:
            if not isinstance(value, (list, tuple)):
                raise ManufacturerDefaultsError("array value must be a list.")
            return [normalize_json_value(item) for item in value]

        return normalize_json_value(value)
    except ManufacturerDefaultsError:
        raise
    except Exception as exc:
        raise ManufacturerDefaultsError(f"Invalid value {value!r} for type {value_type!r}.") from exc


def normalize_json_value(value: Any) -> Any:
    """Normalisiert JSON-kompatible Werte."""
    if value is None:
        return None

    if isinstance(value, (str, int, float, bool)):
        return value

    if isinstance(value, Mapping):
        return {
            str(key): normalize_json_value(child_value)
            for key, child_value in value.items()
        }

    if isinstance(value, (list, tuple, set)):
        return [normalize_json_value(item) for item in value]

    return str(value)


@lru_cache(maxsize=128)
def parse_contract_mode_value(value: Any) -> str:
    """Parst ManufacturerContractMode."""
    try:
        if isinstance(value, ManufacturerContractMode):
            return value.value

        raw = normalize_enum_key(value)

        aliases = {
            "disabled": ManufacturerContractMode.DISABLED.value,
            "off": ManufacturerContractMode.DISABLED.value,
            "none": ManufacturerContractMode.DISABLED.value,
            "allowed": ManufacturerContractMode.ALLOWED.value,
            "optional": ManufacturerContractMode.ALLOWED.value,
            "required": ManufacturerContractMode.REQUIRED.value,
            "mandatory": ManufacturerContractMode.REQUIRED.value,
        }

        if raw in aliases:
            return aliases[raw]

        return ManufacturerContractMode(raw).value
    except Exception as exc:
        raise ManufacturerDefaultsError(f"Invalid manufacturer contract mode {value!r}.") from exc


@lru_cache(maxsize=128)
def parse_overlay_level_value(value: Any) -> str:
    """Parst ManufacturerOverlayLevel."""
    try:
        if isinstance(value, ManufacturerOverlayLevel):
            return value.value

        raw = normalize_enum_key(value)

        aliases = {
            "none": ManufacturerOverlayLevel.NONE.value,
            "disabled": ManufacturerOverlayLevel.NONE.value,
            "product": ManufacturerOverlayLevel.PRODUCT_METADATA.value,
            "product_metadata": ManufacturerOverlayLevel.PRODUCT_METADATA.value,
            "branding": ManufacturerOverlayLevel.BRANDING.value,
            "render": ManufacturerOverlayLevel.RENDER.value,
            "material": ManufacturerOverlayLevel.MATERIAL.value,
            "performance": ManufacturerOverlayLevel.PERFORMANCE.value,
            "commercial": ManufacturerOverlayLevel.COMMERCIAL.value,
            "full": ManufacturerOverlayLevel.FULL_ALLOWED_SLOTS.value,
            "full_allowed_slots": ManufacturerOverlayLevel.FULL_ALLOWED_SLOTS.value,
        }

        if raw in aliases:
            return aliases[raw]

        return ManufacturerOverlayLevel(raw).value
    except Exception as exc:
        raise ManufacturerDefaultsError(f"Invalid manufacturer overlay level {value!r}.") from exc


@lru_cache(maxsize=128)
def parse_override_scope_value(value: Any) -> str:
    """Parst ManufacturerOverrideScope."""
    try:
        if isinstance(value, ManufacturerOverrideScope):
            return value.value

        raw = normalize_enum_key(value)
        return ManufacturerOverrideScope(raw).value
    except Exception as exc:
        raise ManufacturerDefaultsError(f"Invalid manufacturer override scope {value!r}.") from exc


@lru_cache(maxsize=128)
def parse_value_type_value(value: Any) -> str:
    """Parst ManufacturerValueType."""
    try:
        if isinstance(value, ManufacturerValueType):
            return value.value

        raw = normalize_enum_key(value)

        aliases = {
            "str": ManufacturerValueType.STRING.value,
            "string": ManufacturerValueType.STRING.value,
            "int": ManufacturerValueType.INTEGER.value,
            "integer": ManufacturerValueType.INTEGER.value,
            "float": ManufacturerValueType.NUMBER.value,
            "number": ManufacturerValueType.NUMBER.value,
            "bool": ManufacturerValueType.BOOLEAN.value,
            "boolean": ManufacturerValueType.BOOLEAN.value,
            "enum": ManufacturerValueType.ENUM.value,
            "color": ManufacturerValueType.COLOR.value,
            "asset": ManufacturerValueType.ASSET_REF.value,
            "asset_ref": ManufacturerValueType.ASSET_REF.value,
            "unit_value": ManufacturerValueType.UNIT_VALUE.value,
            "object": ManufacturerValueType.OBJECT.value,
            "array": ManufacturerValueType.ARRAY.value,
        }

        if raw in aliases:
            return aliases[raw]

        return ManufacturerValueType(raw).value
    except Exception as exc:
        raise ManufacturerDefaultsError(f"Invalid manufacturer value type {value!r}.") from exc


@lru_cache(maxsize=128)
def parse_product_field_group_value(value: Any) -> str:
    """Parst ProductFieldGroup."""
    try:
        if isinstance(value, ProductFieldGroup):
            return value.value

        raw = normalize_enum_key(value)
        return ProductFieldGroup(raw).value
    except Exception as exc:
        raise ManufacturerDefaultsError(f"Invalid product field group {value!r}.") from exc


@lru_cache(maxsize=128)
def parse_product_category_kind_value(value: Any) -> str:
    """Parst ProductCategoryKind."""
    try:
        if isinstance(value, ProductCategoryKind):
            return value.value

        raw = normalize_enum_key(value)
        return ProductCategoryKind(raw).value
    except Exception as exc:
        raise ManufacturerDefaultsError(f"Invalid product category kind {value!r}.") from exc


@lru_cache(maxsize=128)
def parse_validation_policy_value(value: Any) -> str:
    """Parst ManufacturerValidationPolicy."""
    try:
        if isinstance(value, ManufacturerValidationPolicy):
            return value.value

        raw = normalize_enum_key(value)
        return ManufacturerValidationPolicy(raw).value
    except Exception as exc:
        raise ManufacturerDefaultsError(f"Invalid manufacturer validation policy {value!r}.") from exc


@lru_cache(maxsize=128)
def parse_asset_role_value(value: Any) -> str:
    """Parst ManufacturerAssetRole."""
    try:
        if isinstance(value, ManufacturerAssetRole):
            return value.value

        raw = normalize_enum_key(value)
        return ManufacturerAssetRole(raw).value
    except Exception as exc:
        raise ManufacturerDefaultsError(f"Invalid manufacturer asset role {value!r}.") from exc


def assert_unique_values(values: Iterable[str], field_name: str) -> None:
    """Prüft eindeutige Werte."""
    seen: set[str] = set()

    for value in values or ():
        if value in seen:
            raise ManufacturerDefaultsError(f"Duplicate {field_name} {value!r}.")
        seen.add(value)


def normalize_enum_key(value: Any) -> str:
    """Normalisiert Enum-ähnliche Werte."""
    try:
        raw = str(value).strip()

        if not raw:
            raise ManufacturerDefaultsError("Enum value is required.")

        return (
            raw.lower()
            .replace(" ", "_")
            .replace("-", "_")
            .replace("/", "_")
            .replace("\\", "_")
        )
    except ManufacturerDefaultsError:
        raise
    except Exception as exc:
        raise ManufacturerDefaultsError(f"Invalid enum value {value!r}.") from exc


def normalize_float(value: Any, field_name: str) -> float:
    """Normalisiert Float."""
    try:
        if isinstance(value, bool):
            raise ManufacturerDefaultsError(f"{field_name} must be a number.")
        return float(value)
    except ManufacturerDefaultsError:
        raise
    except Exception as exc:
        raise ManufacturerDefaultsError(f"{field_name} must be a number.") from exc


def normalize_optional_float(value: Any, field_name: str) -> float | None:
    """Normalisiert optionalen Float."""
    if value is None:
        return None
    return normalize_float(value, field_name)


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
        raise ManufacturerDefaultsError("metadata must be a mapping.")

    return {
        str(key): normalize_json_value(child_value)
        for key, child_value in value.items()
    }


def humanize_key(value: Any) -> str:
    """Erzeugt einfaches Label aus technischem Key."""
    return str(value).replace("_", " ").replace(".", " ").title()


def clean_required_string(value: Any, field_name: str) -> str:
    """Normalisiert Pflicht-String."""
    try:
        cleaned = str(value).strip()

        if not cleaned:
            raise ManufacturerDefaultsError(f"{field_name} is required.")

        return cleaned
    except ManufacturerDefaultsError:
        raise
    except Exception as exc:
        raise ManufacturerDefaultsError(f"{field_name} must be string-like.") from exc


def clean_optional_string(value: Any) -> str | None:
    """Normalisiert optionalen String."""
    if value is None:
        return None

    try:
        cleaned = str(value).strip()
        return cleaned or None
    except Exception:
        return None


def clear_manufacturer_defaults_caches() -> None:
    """Leert interne Parser-Caches."""
    parse_contract_mode_value.cache_clear()
    parse_overlay_level_value.cache_clear()
    parse_override_scope_value.cache_clear()
    parse_value_type_value.cache_clear()
    parse_product_field_group_value.cache_clear()
    parse_product_category_kind_value.cache_clear()
    parse_validation_policy_value.cache_clear()
    parse_asset_role_value.cache_clear()


__all__ = [
    "DEFAULT_ALLOWED_OVERRIDE_PREFIXES",
    "DEFAULT_BRAND_COLOR",
    "DEFAULT_CONTRACT_ID",
    "DEFAULT_MANUFACTURER_ID",
    "DEFAULT_OVERLAY_LEVEL",
    "DEFAULT_PRODUCT_CATEGORY_ID",
    "FORBIDDEN_MANUFACTURER_OVERRIDE_PREFIXES",
    "MANUFACTURER_ASSETS_DOCUMENT_SCHEMA_VERSION",
    "MANUFACTURER_BRANDING_DOCUMENT_SCHEMA_VERSION",
    "MANUFACTURER_CONTRACT_DOCUMENT_SCHEMA_VERSION",
    "MANUFACTURER_DEFAULTS_SCHEMA_VERSION",
    "MANUFACTURER_OVERRIDE_SLOTS_DOCUMENT_SCHEMA_VERSION",
    "MANUFACTURER_PRODUCT_CATEGORIES_DOCUMENT_SCHEMA_VERSION",
    "MANUFACTURER_PRODUCT_FIELDS_DOCUMENT_SCHEMA_VERSION",
    "SAFE_FIELD_PATH_RE",
    "SAFE_HEX_COLOR_RE",
    "SAFE_MANUFACTURER_KEY_RE",
    "ManufacturerAssetDefaults",
    "ManufacturerAssetRole",
    "ManufacturerAssetsDefaults",
    "ManufacturerBrandingDefaults",
    "ManufacturerContractDefaults",
    "ManufacturerContractMode",
    "ManufacturerDefaults",
    "ManufacturerDefaultsError",
    "ManufacturerOverlayLevel",
    "ManufacturerOverrideScope",
    "ManufacturerOverrideSlotDefaults",
    "ManufacturerOverrideSlotsDefaults",
    "ManufacturerProductCategoriesDefaults",
    "ManufacturerProductCategoryDefaults",
    "ManufacturerProductFieldDefaults",
    "ManufacturerProductFieldsDefaults",
    "ManufacturerValidationPolicy",
    "ManufacturerValueType",
    "ProductCategoryKind",
    "ProductFieldGroup",
    "assert_override_field_allowed",
    "assert_unique_values",
    "assert_valid_manufacturer_contract_document",
    "assert_valid_override_slots_document",
    "build_manufacturer_defaults",
    "clean_optional_string",
    "clean_required_string",
    "clear_manufacturer_defaults_caches",
    "default_product_fields",
    "humanize_key",
    "infer_scope_from_field_path",
    "manufacturer_defaults_from_context",
    "manufacturer_defaults_from_create_request",
    "manufacturer_defaults_from_creation_plan",
    "manufacturer_documents_from_context",
    "manufacturer_documents_from_create_request",
    "manufacturer_documents_from_creation_plan",
    "merge_product_fields",
    "normalize_color",
    "normalize_create_request",
    "normalize_enum_key",
    "normalize_field_path",
    "normalize_field_prefix_tuple",
    "normalize_float",
    "normalize_json_value",
    "normalize_manufacturer_key",
    "normalize_metadata",
    "normalize_optional_float",
    "normalize_optional_manufacturer_key",
    "normalize_optional_unit_value",
    "normalize_string_tuple",
    "normalize_typed_value",
    "override_slot_from_mapping",
    "parse_asset_role_value",
    "parse_contract_mode_value",
    "parse_overlay_level_value",
    "parse_override_scope_value",
    "parse_product_category_kind_value",
    "parse_product_field_group_value",
    "parse_validation_policy_value",
    "parse_value_type_value",
    "product_category_from_mapping",
    "product_category_from_value",
    "product_field_from_mapping",
    "product_fields_from_required_names",
    "validate_manufacturer_contract_document",
    "validate_override_slots_document",
]