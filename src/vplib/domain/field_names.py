# services/vectoplan-library/src/vplib/domain/field_names.py
"""
Canonical VPLIB field-name definitions.

This module defines stable JSON field names used across modular VPLIB packages.
It does not validate full document content. It provides a strict vocabulary for
document builders, planners, validators, serializers and later API projections.

Important invariants:
- Field names are canonical JSON-facing strings.
- Aliases are accepted only for parsing and migration convenience.
- Serialization should always use canonical field names.
- Classification is explicitly modeled as:
  domain/tab -> category -> subcategory.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from functools import lru_cache
from typing import Any, Final, Iterable, Mapping


FIELD_NAME_SCHEMA_VERSION: Final[str] = "vplib.field_names.v1"


class FieldNameError(ValueError):
    """Raised when a VPLIB field-name value cannot be normalized or validated."""


class FieldGroup(str, Enum):
    """Canonical field groups."""

    SYSTEM = "system"
    IDENTITY = "identity"
    CLASSIFICATION = "classification"
    OBJECT_KIND = "object_kind"
    GRID = "grid"
    VARIANT = "variant"
    EDITOR = "editor"
    PLACEMENT = "placement"
    RENDER = "render"
    ASSET = "asset"
    PHYSICAL = "physical"
    MATERIAL = "material"
    CALCULATION = "calculation"
    ANALYSIS = "analysis"
    DYNAMIC = "dynamic"
    MANUFACTURER = "manufacturer"
    VALIDATION = "validation"
    REPORT = "report"


class ValueKind(str, Enum):
    """Simple JSON value-kind hints for field metadata."""

    STRING = "string"
    INTEGER = "integer"
    FLOAT = "float"
    BOOLEAN = "boolean"
    OBJECT = "object"
    ARRAY = "array"
    NUMBER = "number"
    ANY = "any"
    NULLABLE_STRING = "nullable_string"
    NULLABLE_OBJECT = "nullable_object"
    NULLABLE_ARRAY = "nullable_array"


class VplibFieldName(str, Enum):
    """
    Canonical field names used in VPLIB JSON documents.

    Keep these values stable. They may appear in package files, generated read
    models, scanner reports, future database rows and API responses.
    """

    # System / schema
    SCHEMA_VERSION = "schema_version"
    VPLIB_VERSION = "vplib_version"
    CREATED_AT = "created_at"
    UPDATED_AT = "updated_at"
    CREATED_BY = "created_by"
    UPDATED_BY = "updated_by"
    SOURCE = "source"
    STATUS = "status"
    CHECKSUM = "checksum"
    CHECKSUMS = "checksums"
    METADATA = "metadata"

    # Identity
    PACKAGE_ID = "package_id"
    FAMILY_ID = "family_id"
    FAMILY_SLUG = "family_slug"
    FAMILY_NAME = "family_name"
    DISPLAY_NAME = "display_name"
    SHORT_NAME = "short_name"
    DESCRIPTION = "description"
    VERSION = "version"
    AUTHOR = "author"
    LABEL = "label"
    TAGS = "tags"
    ALIASES = "aliases"

    # Classification: domain/tab -> category -> subcategory
    DOMAIN = "domain"
    DOMAIN_ID = "domain_id"
    DOMAIN_LABEL = "domain_label"
    TAB = "tab"
    TAB_ID = "tab_id"
    TAB_LABEL = "tab_label"
    CATEGORY = "category"
    CATEGORY_ID = "category_id"
    CATEGORY_LABEL = "category_label"
    SUBCATEGORY = "subcategory"
    SUBCATEGORY_ID = "subcategory_id"
    SUBCATEGORY_LABEL = "subcategory_label"
    CLASSIFICATION_PATH = "classification_path"

    # Object kind
    OBJECT_KIND = "object_kind"
    OBJECT_KIND_LABEL = "object_kind_label"
    OBJECT_CLASS = "object_class"

    # Modules
    ACTIVE_MODULES = "active_modules"
    REQUIRED_MODULES = "required_modules"
    OPTIONAL_MODULES = "optional_modules"
    MODULE_VERSIONS = "module_versions"
    PROFILE_KEY = "profile_key"

    # Grid / footprint
    GRID = "grid"
    GRID_FOOTPRINT = "grid_footprint"
    SIZE_CELLS = "size_cells"
    SIZE_CELLS_X = "size_cells_x"
    SIZE_CELLS_Y = "size_cells_y"
    SIZE_CELLS_Z = "size_cells_z"
    CELL_SIZE_M = "cell_size_m"
    FOOTPRINT = "footprint"
    OCCUPIED_CELLS = "occupied_cells"
    ANCHOR_CELL = "anchor_cell"

    # Variants
    VARIANT_ID = "variant_id"
    VARIANT_IDS = "variant_ids"
    VARIANT_LABEL = "variant_label"
    VARIANT_LABELS = "variant_labels"
    DEFAULT_VARIANT_ID = "default_variant_id"
    VARIANT_MODE = "variant_mode"
    VARIANTS = "variants"
    OVERRIDES = "overrides"
    RESOLVED_VARIANTS = "resolved_variants"

    # Editor / inventory
    INVENTORY = "inventory"
    INVENTORY_VISIBLE = "inventory_visible"
    INVENTORY_LABEL = "inventory_label"
    INVENTORY_SHORT_LABEL = "inventory_short_label"
    CREATIVE_LIBRARY_VISIBLE = "creative_library_visible"
    HOTBAR_ELIGIBLE = "hotbar_eligible"
    SORT_KEY = "sort_key"
    SEARCH_TEXT = "search_text"

    # Placement
    PLACEMENT = "placement"
    PLACEMENT_MODE = "placement_mode"
    ALLOWED_SURFACES = "allowed_surfaces"
    ALLOWED_HOSTS = "allowed_hosts"
    ROTATION_ALLOWED = "rotation_allowed"
    ROTATION_STEPS = "rotation_steps"
    SNAP_MODE = "snap_mode"
    REQUIRES_SUPPORT = "requires_support"
    REQUIRES_SURFACE_NORMAL = "requires_surface_normal"
    REQUIRES_SUPPORT_SURFACE = "requires_support_surface"
    GRID_FOOTPRINT_IS_PLACEMENT_TRUTH = "grid_footprint_is_placement_truth"
    VISUAL_MODEL_MUST_REMAIN_INSIDE_FOOTPRINT = "visual_model_must_remain_inside_footprint"

    # Targeting / anchors / sockets / ports
    TARGETING = "targeting"
    ANCHORS = "anchors"
    SOCKETS = "sockets"
    PORTS = "ports"
    CAN_ATTACH = "can_attach"
    CAN_STACK = "can_stack"
    CAN_ROTATE = "can_rotate"

    # Render / visual
    RENDER = "render"
    RENDER_VARIANTS = "render_variants"
    SHAPE = "shape"
    FIT_MODE = "fit_mode"
    FALLBACK_COLOR = "fallback_color"
    TEXTURE_REF = "texture_ref"
    GLB_REF = "glb_ref"
    MODEL_REF = "model_ref"
    ICON_REF = "icon_ref"
    PREVIEW_REF = "preview_ref"
    MODEL_BOUNDS_M = "model_bounds_m"
    VISUAL_ALIGNMENT = "visual_alignment"
    LOD = "lod"

    # Assets
    ASSETS = "assets"
    ASSET_ID = "asset_id"
    ASSET_TYPE = "asset_type"
    ASSET_PATH = "asset_path"
    ASSET_ROLE = "asset_role"
    MIME_TYPE = "mime_type"
    FILE_SIZE_BYTES = "file_size_bytes"
    WIDTH = "width"
    HEIGHT = "height"
    DEPTH = "depth"

    # Physical
    PHYSICAL = "physical"
    DIMENSIONS = "dimensions"
    REAL_DIMENSIONS = "real_dimensions"
    REAL_WIDTH_M = "real_width_m"
    REAL_HEIGHT_M = "real_height_m"
    REAL_DEPTH_M = "real_depth_m"
    WALL_THICKNESS_M = "wall_thickness_m"
    VOLUME_M3 = "volume_m3"
    MASS_KG = "mass_kg"
    DENSITY_KG_M3 = "density_kg_m3"
    RAW_DENSITY_KG_M3 = "raw_density_kg_m3"
    COLLISION = "collision"
    OCCUPANCY = "occupancy"
    LOAD_BEARING = "load_bearing"
    FIRE_CLASS = "fire_class"

    # Material
    MATERIAL = "material"
    MATERIAL_ID = "material_id"
    MATERIAL_CLASS = "material_class"
    MATERIAL_NAME = "material_name"
    SURFACE_FINISH = "surface_finish"
    THERMAL_CONDUCTIVITY = "thermal_conductivity"
    U_VALUE = "u_value"
    COMPRESSIVE_STRENGTH = "compressive_strength"

    # Calculation
    CALCULATION = "calculation"
    VARIABLES = "variables"
    FORMULAS = "formulas"
    QUANTITIES = "quantities"
    CONSTRAINTS = "constraints"
    MEASURE_LOGIC = "measure_logic"
    UNIT = "unit"
    VALUE = "value"
    MIN_VALUE = "min_value"
    MAX_VALUE = "max_value"
    EXPRESSION = "expression"
    INPUTS = "inputs"
    OUTPUTS = "outputs"

    # Analysis
    ANALYSIS = "analysis"
    STATICS = "statics"
    ENERGY = "energy"
    ACOUSTICS = "acoustics"
    ROUTING = "routing"
    REINFORCEMENT = "reinforcement"

    # Dynamic / adaptive
    DYNAMIC = "dynamic"
    CONTEXT_RULES = "context_rules"
    BINDINGS = "bindings"
    GENERATOR = "generator"
    PARAMETERS = "parameters"
    HOST_CONTEXT = "host_context"

    # Manufacturer
    MANUFACTURER = "manufacturer"
    MANUFACTURER_ALLOWED = "manufacturer_allowed"
    CONTRACT = "contract"
    OVERLAY_LEVEL = "overlay_level"
    OVERRIDE_SLOTS = "override_slots"
    REQUIRED_PRODUCT_FIELDS = "required_product_fields"
    PRODUCT_CATEGORIES = "product_categories"

    # Validation / reports
    VALID = "valid"
    ERRORS = "errors"
    WARNINGS = "warnings"
    MESSAGE = "message"
    CODE = "code"
    PATH = "path"
    FIELD = "field"
    SEVERITY = "severity"
    CREATED_FILES = "created_files"
    CREATED_DIRECTORIES = "created_directories"
    COPIED_ASSETS = "copied_assets"
    PACKAGE_PATH = "package_path"
    ARCHIVE_PATH = "archive_path"

    @property
    def key(self) -> str:
        """Return the canonical field-name key."""
        return str(self.value)


@dataclass(frozen=True, slots=True)
class FieldDefinition:
    """Metadata for one canonical field name."""

    name: VplibFieldName
    group: FieldGroup
    value_kind: ValueKind
    description: str
    required_in_core_documents: bool
    stable_order: int


_FIELD_DEFINITIONS: Final[dict[VplibFieldName, FieldDefinition]] = {
    # System
    VplibFieldName.SCHEMA_VERSION: FieldDefinition(
        VplibFieldName.SCHEMA_VERSION,
        FieldGroup.SYSTEM,
        ValueKind.STRING,
        "Schema version of a VPLIB document.",
        True,
        10,
    ),
    VplibFieldName.VPLIB_VERSION: FieldDefinition(
        VplibFieldName.VPLIB_VERSION,
        FieldGroup.SYSTEM,
        ValueKind.STRING,
        "VPLIB format version.",
        False,
        20,
    ),
    VplibFieldName.CREATED_AT: FieldDefinition(
        VplibFieldName.CREATED_AT,
        FieldGroup.SYSTEM,
        ValueKind.STRING,
        "Creation timestamp.",
        False,
        30,
    ),
    VplibFieldName.UPDATED_AT: FieldDefinition(
        VplibFieldName.UPDATED_AT,
        FieldGroup.SYSTEM,
        ValueKind.STRING,
        "Update timestamp.",
        False,
        40,
    ),
    VplibFieldName.CREATED_BY: FieldDefinition(
        VplibFieldName.CREATED_BY,
        FieldGroup.SYSTEM,
        ValueKind.NULLABLE_STRING,
        "Creator identifier.",
        False,
        50,
    ),
    VplibFieldName.UPDATED_BY: FieldDefinition(
        VplibFieldName.UPDATED_BY,
        FieldGroup.SYSTEM,
        ValueKind.NULLABLE_STRING,
        "Updater identifier.",
        False,
        60,
    ),
    VplibFieldName.SOURCE: FieldDefinition(
        VplibFieldName.SOURCE,
        FieldGroup.SYSTEM,
        ValueKind.STRING,
        "Source descriptor.",
        False,
        70,
    ),
    VplibFieldName.STATUS: FieldDefinition(
        VplibFieldName.STATUS,
        FieldGroup.SYSTEM,
        ValueKind.STRING,
        "Lifecycle or validation status.",
        False,
        80,
    ),
    VplibFieldName.CHECKSUM: FieldDefinition(
        VplibFieldName.CHECKSUM,
        FieldGroup.SYSTEM,
        ValueKind.STRING,
        "Single checksum value.",
        False,
        90,
    ),
    VplibFieldName.CHECKSUMS: FieldDefinition(
        VplibFieldName.CHECKSUMS,
        FieldGroup.SYSTEM,
        ValueKind.OBJECT,
        "Checksum map.",
        False,
        100,
    ),
    VplibFieldName.METADATA: FieldDefinition(
        VplibFieldName.METADATA,
        FieldGroup.SYSTEM,
        ValueKind.OBJECT,
        "Additional metadata.",
        False,
        110,
    ),

    # Identity
    VplibFieldName.PACKAGE_ID: FieldDefinition(
        VplibFieldName.PACKAGE_ID,
        FieldGroup.IDENTITY,
        ValueKind.STRING,
        "Stable VPLIB package identifier.",
        True,
        200,
    ),
    VplibFieldName.FAMILY_ID: FieldDefinition(
        VplibFieldName.FAMILY_ID,
        FieldGroup.IDENTITY,
        ValueKind.STRING,
        "Stable semantic family identifier.",
        True,
        210,
    ),
    VplibFieldName.FAMILY_SLUG: FieldDefinition(
        VplibFieldName.FAMILY_SLUG,
        FieldGroup.IDENTITY,
        ValueKind.STRING,
        "Filesystem-safe family slug.",
        False,
        220,
    ),
    VplibFieldName.FAMILY_NAME: FieldDefinition(
        VplibFieldName.FAMILY_NAME,
        FieldGroup.IDENTITY,
        ValueKind.STRING,
        "Human-readable family name.",
        True,
        230,
    ),
    VplibFieldName.DISPLAY_NAME: FieldDefinition(
        VplibFieldName.DISPLAY_NAME,
        FieldGroup.IDENTITY,
        ValueKind.STRING,
        "Display name for UI and read models.",
        False,
        240,
    ),
    VplibFieldName.SHORT_NAME: FieldDefinition(
        VplibFieldName.SHORT_NAME,
        FieldGroup.IDENTITY,
        ValueKind.STRING,
        "Short display name.",
        False,
        250,
    ),
    VplibFieldName.DESCRIPTION: FieldDefinition(
        VplibFieldName.DESCRIPTION,
        FieldGroup.IDENTITY,
        ValueKind.STRING,
        "Description text.",
        False,
        260,
    ),
    VplibFieldName.VERSION: FieldDefinition(
        VplibFieldName.VERSION,
        FieldGroup.IDENTITY,
        ValueKind.STRING,
        "Package or family version.",
        True,
        270,
    ),
    VplibFieldName.AUTHOR: FieldDefinition(
        VplibFieldName.AUTHOR,
        FieldGroup.IDENTITY,
        ValueKind.NULLABLE_STRING,
        "Author or owner name.",
        False,
        280,
    ),
    VplibFieldName.LABEL: FieldDefinition(
        VplibFieldName.LABEL,
        FieldGroup.IDENTITY,
        ValueKind.STRING,
        "Generic label.",
        False,
        290,
    ),
    VplibFieldName.TAGS: FieldDefinition(
        VplibFieldName.TAGS,
        FieldGroup.IDENTITY,
        ValueKind.ARRAY,
        "Search and classification tags.",
        False,
        300,
    ),
    VplibFieldName.ALIASES: FieldDefinition(
        VplibFieldName.ALIASES,
        FieldGroup.IDENTITY,
        ValueKind.ARRAY,
        "Alternative identifiers or names.",
        False,
        310,
    ),

    # Classification
    VplibFieldName.DOMAIN: FieldDefinition(
        VplibFieldName.DOMAIN,
        FieldGroup.CLASSIFICATION,
        ValueKind.STRING,
        "Top-level classification domain/tab.",
        True,
        400,
    ),
    VplibFieldName.DOMAIN_ID: FieldDefinition(
        VplibFieldName.DOMAIN_ID,
        FieldGroup.CLASSIFICATION,
        ValueKind.STRING,
        "Stable domain identifier.",
        False,
        410,
    ),
    VplibFieldName.DOMAIN_LABEL: FieldDefinition(
        VplibFieldName.DOMAIN_LABEL,
        FieldGroup.CLASSIFICATION,
        ValueKind.STRING,
        "Display label for domain.",
        False,
        420,
    ),
    VplibFieldName.TAB: FieldDefinition(
        VplibFieldName.TAB,
        FieldGroup.CLASSIFICATION,
        ValueKind.STRING,
        "UI-facing alias for top-level domain.",
        False,
        430,
    ),
    VplibFieldName.TAB_ID: FieldDefinition(
        VplibFieldName.TAB_ID,
        FieldGroup.CLASSIFICATION,
        ValueKind.STRING,
        "UI-facing alias for domain id.",
        False,
        440,
    ),
    VplibFieldName.TAB_LABEL: FieldDefinition(
        VplibFieldName.TAB_LABEL,
        FieldGroup.CLASSIFICATION,
        ValueKind.STRING,
        "UI-facing alias for domain label.",
        False,
        450,
    ),
    VplibFieldName.CATEGORY: FieldDefinition(
        VplibFieldName.CATEGORY,
        FieldGroup.CLASSIFICATION,
        ValueKind.STRING,
        "Second-level category inside a domain.",
        True,
        460,
    ),
    VplibFieldName.CATEGORY_ID: FieldDefinition(
        VplibFieldName.CATEGORY_ID,
        FieldGroup.CLASSIFICATION,
        ValueKind.STRING,
        "Stable category identifier.",
        False,
        470,
    ),
    VplibFieldName.CATEGORY_LABEL: FieldDefinition(
        VplibFieldName.CATEGORY_LABEL,
        FieldGroup.CLASSIFICATION,
        ValueKind.STRING,
        "Display label for category.",
        False,
        480,
    ),
    VplibFieldName.SUBCATEGORY: FieldDefinition(
        VplibFieldName.SUBCATEGORY,
        FieldGroup.CLASSIFICATION,
        ValueKind.STRING,
        "Third-level subcategory inside a category.",
        True,
        490,
    ),
    VplibFieldName.SUBCATEGORY_ID: FieldDefinition(
        VplibFieldName.SUBCATEGORY_ID,
        FieldGroup.CLASSIFICATION,
        ValueKind.STRING,
        "Stable subcategory identifier.",
        False,
        500,
    ),
    VplibFieldName.SUBCATEGORY_LABEL: FieldDefinition(
        VplibFieldName.SUBCATEGORY_LABEL,
        FieldGroup.CLASSIFICATION,
        ValueKind.STRING,
        "Display label for subcategory.",
        False,
        510,
    ),
    VplibFieldName.CLASSIFICATION_PATH: FieldDefinition(
        VplibFieldName.CLASSIFICATION_PATH,
        FieldGroup.CLASSIFICATION,
        ValueKind.STRING,
        "Canonical domain/category/subcategory path.",
        False,
        520,
    ),

    # The remaining fields use compact generated metadata below.
}


_GENERATED_FIELD_GROUPS: Final[dict[VplibFieldName, tuple[FieldGroup, ValueKind, str, int]]] = {
    # Object kind
    VplibFieldName.OBJECT_KIND: (FieldGroup.OBJECT_KIND, ValueKind.STRING, "Canonical object kind.", 600),
    VplibFieldName.OBJECT_KIND_LABEL: (FieldGroup.OBJECT_KIND, ValueKind.STRING, "Object kind display label.", 610),
    VplibFieldName.OBJECT_CLASS: (FieldGroup.OBJECT_KIND, ValueKind.STRING, "Object class alias.", 620),

    # Modules
    VplibFieldName.ACTIVE_MODULES: (FieldGroup.SYSTEM, ValueKind.ARRAY, "Active VPLIB modules.", 700),
    VplibFieldName.REQUIRED_MODULES: (FieldGroup.SYSTEM, ValueKind.ARRAY, "Required VPLIB modules.", 710),
    VplibFieldName.OPTIONAL_MODULES: (FieldGroup.SYSTEM, ValueKind.ARRAY, "Optional VPLIB modules.", 720),
    VplibFieldName.MODULE_VERSIONS: (FieldGroup.SYSTEM, ValueKind.OBJECT, "Module version map.", 730),
    VplibFieldName.PROFILE_KEY: (FieldGroup.SYSTEM, ValueKind.STRING, "Creation or object-kind profile key.", 740),

    # Grid
    VplibFieldName.GRID: (FieldGroup.GRID, ValueKind.OBJECT, "Grid data.", 800),
    VplibFieldName.GRID_FOOTPRINT: (FieldGroup.GRID, ValueKind.OBJECT, "Grid footprint.", 810),
    VplibFieldName.SIZE_CELLS: (FieldGroup.GRID, ValueKind.OBJECT, "Size in cells.", 820),
    VplibFieldName.SIZE_CELLS_X: (FieldGroup.GRID, ValueKind.INTEGER, "Size in cells on X axis.", 830),
    VplibFieldName.SIZE_CELLS_Y: (FieldGroup.GRID, ValueKind.INTEGER, "Size in cells on Y axis.", 840),
    VplibFieldName.SIZE_CELLS_Z: (FieldGroup.GRID, ValueKind.INTEGER, "Size in cells on Z axis.", 850),
    VplibFieldName.CELL_SIZE_M: (FieldGroup.GRID, ValueKind.FLOAT, "Cell size in meters.", 860),
    VplibFieldName.FOOTPRINT: (FieldGroup.GRID, ValueKind.OBJECT, "Footprint data.", 870),
    VplibFieldName.OCCUPIED_CELLS: (FieldGroup.GRID, ValueKind.ARRAY, "Occupied grid cells.", 880),
    VplibFieldName.ANCHOR_CELL: (FieldGroup.GRID, ValueKind.OBJECT, "Anchor cell.", 890),

    # Variant
    VplibFieldName.VARIANT_ID: (FieldGroup.VARIANT, ValueKind.STRING, "Variant identifier.", 900),
    VplibFieldName.VARIANT_IDS: (FieldGroup.VARIANT, ValueKind.ARRAY, "Variant identifiers.", 910),
    VplibFieldName.VARIANT_LABEL: (FieldGroup.VARIANT, ValueKind.STRING, "Variant label.", 920),
    VplibFieldName.VARIANT_LABELS: (FieldGroup.VARIANT, ValueKind.OBJECT, "Variant label map.", 930),
    VplibFieldName.DEFAULT_VARIANT_ID: (FieldGroup.VARIANT, ValueKind.STRING, "Default variant identifier.", 940),
    VplibFieldName.VARIANT_MODE: (FieldGroup.VARIANT, ValueKind.STRING, "Variant mode.", 950),
    VplibFieldName.VARIANTS: (FieldGroup.VARIANT, ValueKind.ARRAY, "Variant list.", 960),
    VplibFieldName.OVERRIDES: (FieldGroup.VARIANT, ValueKind.OBJECT, "Variant override values.", 970),
    VplibFieldName.RESOLVED_VARIANTS: (FieldGroup.VARIANT, ValueKind.OBJECT, "Resolved variant data.", 980),

    # Editor / placement / render / assets
    VplibFieldName.INVENTORY: (FieldGroup.EDITOR, ValueKind.OBJECT, "Inventory metadata.", 1000),
    VplibFieldName.INVENTORY_VISIBLE: (FieldGroup.EDITOR, ValueKind.BOOLEAN, "Inventory visibility flag.", 1010),
    VplibFieldName.INVENTORY_LABEL: (FieldGroup.EDITOR, ValueKind.STRING, "Inventory label.", 1020),
    VplibFieldName.INVENTORY_SHORT_LABEL: (FieldGroup.EDITOR, ValueKind.STRING, "Inventory short label.", 1030),
    VplibFieldName.CREATIVE_LIBRARY_VISIBLE: (FieldGroup.EDITOR, ValueKind.BOOLEAN, "Creative-library visibility flag.", 1040),
    VplibFieldName.HOTBAR_ELIGIBLE: (FieldGroup.EDITOR, ValueKind.BOOLEAN, "Hotbar eligibility flag.", 1050),
    VplibFieldName.SORT_KEY: (FieldGroup.EDITOR, ValueKind.STRING, "Sort key.", 1060),
    VplibFieldName.SEARCH_TEXT: (FieldGroup.EDITOR, ValueKind.STRING, "Search text.", 1070),

    VplibFieldName.PLACEMENT: (FieldGroup.PLACEMENT, ValueKind.OBJECT, "Placement metadata.", 1100),
    VplibFieldName.PLACEMENT_MODE: (FieldGroup.PLACEMENT, ValueKind.STRING, "Placement mode.", 1110),
    VplibFieldName.ALLOWED_SURFACES: (FieldGroup.PLACEMENT, ValueKind.ARRAY, "Allowed placement surfaces.", 1120),
    VplibFieldName.ALLOWED_HOSTS: (FieldGroup.PLACEMENT, ValueKind.ARRAY, "Allowed hosts.", 1130),
    VplibFieldName.ROTATION_ALLOWED: (FieldGroup.PLACEMENT, ValueKind.BOOLEAN, "Rotation allowed flag.", 1140),
    VplibFieldName.ROTATION_STEPS: (FieldGroup.PLACEMENT, ValueKind.ARRAY, "Rotation steps.", 1150),
    VplibFieldName.SNAP_MODE: (FieldGroup.PLACEMENT, ValueKind.STRING, "Snap mode.", 1160),
    VplibFieldName.REQUIRES_SUPPORT: (FieldGroup.PLACEMENT, ValueKind.BOOLEAN, "Requires support flag.", 1170),
    VplibFieldName.REQUIRES_SURFACE_NORMAL: (FieldGroup.PLACEMENT, ValueKind.BOOLEAN, "Requires surface normal flag.", 1180),
    VplibFieldName.REQUIRES_SUPPORT_SURFACE: (FieldGroup.PLACEMENT, ValueKind.BOOLEAN, "Requires support surface flag.", 1190),
    VplibFieldName.GRID_FOOTPRINT_IS_PLACEMENT_TRUTH: (FieldGroup.PLACEMENT, ValueKind.BOOLEAN, "Grid footprint is placement truth flag.", 1200),
    VplibFieldName.VISUAL_MODEL_MUST_REMAIN_INSIDE_FOOTPRINT: (FieldGroup.PLACEMENT, ValueKind.BOOLEAN, "Visual bounds constraint flag.", 1210),

    VplibFieldName.TARGETING: (FieldGroup.PLACEMENT, ValueKind.OBJECT, "Targeting metadata.", 1220),
    VplibFieldName.ANCHORS: (FieldGroup.PLACEMENT, ValueKind.ARRAY, "Anchor definitions.", 1230),
    VplibFieldName.SOCKETS: (FieldGroup.PLACEMENT, ValueKind.ARRAY, "Socket definitions.", 1240),
    VplibFieldName.PORTS: (FieldGroup.PLACEMENT, ValueKind.ARRAY, "Port definitions.", 1250),
    VplibFieldName.CAN_ATTACH: (FieldGroup.PLACEMENT, ValueKind.BOOLEAN, "Attach capability flag.", 1260),
    VplibFieldName.CAN_STACK: (FieldGroup.PLACEMENT, ValueKind.BOOLEAN, "Stack capability flag.", 1270),
    VplibFieldName.CAN_ROTATE: (FieldGroup.PLACEMENT, ValueKind.BOOLEAN, "Rotate capability flag.", 1280),

    VplibFieldName.RENDER: (FieldGroup.RENDER, ValueKind.OBJECT, "Render metadata.", 1300),
    VplibFieldName.RENDER_VARIANTS: (FieldGroup.RENDER, ValueKind.OBJECT, "Render variant metadata.", 1310),
    VplibFieldName.SHAPE: (FieldGroup.RENDER, ValueKind.STRING, "Render shape.", 1320),
    VplibFieldName.FIT_MODE: (FieldGroup.RENDER, ValueKind.STRING, "Render fit mode.", 1330),
    VplibFieldName.FALLBACK_COLOR: (FieldGroup.RENDER, ValueKind.STRING, "Fallback color.", 1340),
    VplibFieldName.TEXTURE_REF: (FieldGroup.RENDER, ValueKind.NULLABLE_STRING, "Texture reference.", 1350),
    VplibFieldName.GLB_REF: (FieldGroup.RENDER, ValueKind.NULLABLE_STRING, "GLB reference.", 1360),
    VplibFieldName.MODEL_REF: (FieldGroup.RENDER, ValueKind.NULLABLE_STRING, "Model reference.", 1370),
    VplibFieldName.ICON_REF: (FieldGroup.RENDER, ValueKind.NULLABLE_STRING, "Icon reference.", 1380),
    VplibFieldName.PREVIEW_REF: (FieldGroup.RENDER, ValueKind.NULLABLE_STRING, "Preview reference.", 1390),
    VplibFieldName.MODEL_BOUNDS_M: (FieldGroup.RENDER, ValueKind.OBJECT, "Model bounds in meters.", 1400),
    VplibFieldName.VISUAL_ALIGNMENT: (FieldGroup.RENDER, ValueKind.STRING, "Visual alignment.", 1410),
    VplibFieldName.LOD: (FieldGroup.RENDER, ValueKind.OBJECT, "Level-of-detail metadata.", 1420),

    VplibFieldName.ASSETS: (FieldGroup.ASSET, ValueKind.ARRAY, "Asset list.", 1500),
    VplibFieldName.ASSET_ID: (FieldGroup.ASSET, ValueKind.STRING, "Asset identifier.", 1510),
    VplibFieldName.ASSET_TYPE: (FieldGroup.ASSET, ValueKind.STRING, "Asset type.", 1520),
    VplibFieldName.ASSET_PATH: (FieldGroup.ASSET, ValueKind.STRING, "Asset path.", 1530),
    VplibFieldName.ASSET_ROLE: (FieldGroup.ASSET, ValueKind.STRING, "Asset role.", 1540),
    VplibFieldName.MIME_TYPE: (FieldGroup.ASSET, ValueKind.STRING, "MIME type.", 1550),
    VplibFieldName.FILE_SIZE_BYTES: (FieldGroup.ASSET, ValueKind.INTEGER, "File size in bytes.", 1560),
    VplibFieldName.WIDTH: (FieldGroup.ASSET, ValueKind.NUMBER, "Width.", 1570),
    VplibFieldName.HEIGHT: (FieldGroup.ASSET, ValueKind.NUMBER, "Height.", 1580),
    VplibFieldName.DEPTH: (FieldGroup.ASSET, ValueKind.NUMBER, "Depth.", 1590),

    # Remaining domain fields
    VplibFieldName.PHYSICAL: (FieldGroup.PHYSICAL, ValueKind.OBJECT, "Physical metadata.", 2000),
    VplibFieldName.DIMENSIONS: (FieldGroup.PHYSICAL, ValueKind.OBJECT, "Dimensions.", 2010),
    VplibFieldName.REAL_DIMENSIONS: (FieldGroup.PHYSICAL, ValueKind.OBJECT, "Real dimensions.", 2020),
    VplibFieldName.REAL_WIDTH_M: (FieldGroup.PHYSICAL, ValueKind.FLOAT, "Real width in meters.", 2030),
    VplibFieldName.REAL_HEIGHT_M: (FieldGroup.PHYSICAL, ValueKind.FLOAT, "Real height in meters.", 2040),
    VplibFieldName.REAL_DEPTH_M: (FieldGroup.PHYSICAL, ValueKind.FLOAT, "Real depth in meters.", 2050),
    VplibFieldName.WALL_THICKNESS_M: (FieldGroup.PHYSICAL, ValueKind.FLOAT, "Wall thickness in meters.", 2060),
    VplibFieldName.VOLUME_M3: (FieldGroup.PHYSICAL, ValueKind.FLOAT, "Volume in cubic meters.", 2070),
    VplibFieldName.MASS_KG: (FieldGroup.PHYSICAL, ValueKind.FLOAT, "Mass in kilograms.", 2080),
    VplibFieldName.DENSITY_KG_M3: (FieldGroup.PHYSICAL, ValueKind.FLOAT, "Density in kilograms per cubic meter.", 2090),
    VplibFieldName.RAW_DENSITY_KG_M3: (FieldGroup.PHYSICAL, ValueKind.FLOAT, "Raw density in kilograms per cubic meter.", 2100),
    VplibFieldName.COLLISION: (FieldGroup.PHYSICAL, ValueKind.OBJECT, "Collision metadata.", 2110),
    VplibFieldName.OCCUPANCY: (FieldGroup.PHYSICAL, ValueKind.OBJECT, "Occupancy metadata.", 2120),
    VplibFieldName.LOAD_BEARING: (FieldGroup.PHYSICAL, ValueKind.BOOLEAN, "Load-bearing flag.", 2130),
    VplibFieldName.FIRE_CLASS: (FieldGroup.PHYSICAL, ValueKind.STRING, "Fire class.", 2140),

    VplibFieldName.MATERIAL: (FieldGroup.MATERIAL, ValueKind.OBJECT, "Material metadata.", 2200),
    VplibFieldName.MATERIAL_ID: (FieldGroup.MATERIAL, ValueKind.STRING, "Material identifier.", 2210),
    VplibFieldName.MATERIAL_CLASS: (FieldGroup.MATERIAL, ValueKind.STRING, "Material class.", 2220),
    VplibFieldName.MATERIAL_NAME: (FieldGroup.MATERIAL, ValueKind.STRING, "Material name.", 2230),
    VplibFieldName.SURFACE_FINISH: (FieldGroup.MATERIAL, ValueKind.STRING, "Surface finish.", 2240),
    VplibFieldName.THERMAL_CONDUCTIVITY: (FieldGroup.MATERIAL, ValueKind.NUMBER, "Thermal conductivity.", 2250),
    VplibFieldName.U_VALUE: (FieldGroup.MATERIAL, ValueKind.NUMBER, "Thermal transmittance.", 2260),
    VplibFieldName.COMPRESSIVE_STRENGTH: (FieldGroup.MATERIAL, ValueKind.NUMBER, "Compressive strength.", 2270),

    VplibFieldName.CALCULATION: (FieldGroup.CALCULATION, ValueKind.OBJECT, "Calculation metadata.", 2300),
    VplibFieldName.VARIABLES: (FieldGroup.CALCULATION, ValueKind.ARRAY, "Calculation variables.", 2310),
    VplibFieldName.FORMULAS: (FieldGroup.CALCULATION, ValueKind.ARRAY, "Calculation formulas.", 2320),
    VplibFieldName.QUANTITIES: (FieldGroup.CALCULATION, ValueKind.ARRAY, "Quantity definitions.", 2330),
    VplibFieldName.CONSTRAINTS: (FieldGroup.CALCULATION, ValueKind.ARRAY, "Calculation constraints.", 2340),
    VplibFieldName.MEASURE_LOGIC: (FieldGroup.CALCULATION, ValueKind.OBJECT, "Measurement logic.", 2350),
    VplibFieldName.UNIT: (FieldGroup.CALCULATION, ValueKind.STRING, "Unit.", 2360),
    VplibFieldName.VALUE: (FieldGroup.CALCULATION, ValueKind.ANY, "Value.", 2370),
    VplibFieldName.MIN_VALUE: (FieldGroup.CALCULATION, ValueKind.NUMBER, "Minimum value.", 2380),
    VplibFieldName.MAX_VALUE: (FieldGroup.CALCULATION, ValueKind.NUMBER, "Maximum value.", 2390),
    VplibFieldName.EXPRESSION: (FieldGroup.CALCULATION, ValueKind.STRING, "Declarative expression.", 2400),
    VplibFieldName.INPUTS: (FieldGroup.CALCULATION, ValueKind.ARRAY, "Formula inputs.", 2410),
    VplibFieldName.OUTPUTS: (FieldGroup.CALCULATION, ValueKind.ARRAY, "Formula outputs.", 2420),

    VplibFieldName.ANALYSIS: (FieldGroup.ANALYSIS, ValueKind.OBJECT, "Analysis metadata.", 2500),
    VplibFieldName.STATICS: (FieldGroup.ANALYSIS, ValueKind.OBJECT, "Statics profile.", 2510),
    VplibFieldName.ENERGY: (FieldGroup.ANALYSIS, ValueKind.OBJECT, "Energy profile.", 2520),
    VplibFieldName.ACOUSTICS: (FieldGroup.ANALYSIS, ValueKind.OBJECT, "Acoustics profile.", 2530),
    VplibFieldName.ROUTING: (FieldGroup.ANALYSIS, ValueKind.OBJECT, "Routing profile.", 2540),
    VplibFieldName.REINFORCEMENT: (FieldGroup.ANALYSIS, ValueKind.OBJECT, "Reinforcement profile.", 2550),

    VplibFieldName.DYNAMIC: (FieldGroup.DYNAMIC, ValueKind.OBJECT, "Dynamic metadata.", 2600),
    VplibFieldName.CONTEXT_RULES: (FieldGroup.DYNAMIC, ValueKind.ARRAY, "Context rules.", 2610),
    VplibFieldName.BINDINGS: (FieldGroup.DYNAMIC, ValueKind.ARRAY, "Dynamic bindings.", 2620),
    VplibFieldName.GENERATOR: (FieldGroup.DYNAMIC, ValueKind.OBJECT, "Declarative generator metadata.", 2630),
    VplibFieldName.PARAMETERS: (FieldGroup.DYNAMIC, ValueKind.ARRAY, "Parameters.", 2640),
    VplibFieldName.HOST_CONTEXT: (FieldGroup.DYNAMIC, ValueKind.OBJECT, "Host context metadata.", 2650),

    VplibFieldName.MANUFACTURER: (FieldGroup.MANUFACTURER, ValueKind.OBJECT, "Manufacturer metadata.", 2700),
    VplibFieldName.MANUFACTURER_ALLOWED: (FieldGroup.MANUFACTURER, ValueKind.BOOLEAN, "Manufacturer overlay allowed flag.", 2710),
    VplibFieldName.CONTRACT: (FieldGroup.MANUFACTURER, ValueKind.OBJECT, "Manufacturer contract.", 2720),
    VplibFieldName.OVERLAY_LEVEL: (FieldGroup.MANUFACTURER, ValueKind.STRING, "Overlay level.", 2730),
    VplibFieldName.OVERRIDE_SLOTS: (FieldGroup.MANUFACTURER, ValueKind.ARRAY, "Allowed override slots.", 2740),
    VplibFieldName.REQUIRED_PRODUCT_FIELDS: (FieldGroup.MANUFACTURER, ValueKind.ARRAY, "Required product fields.", 2750),
    VplibFieldName.PRODUCT_CATEGORIES: (FieldGroup.MANUFACTURER, ValueKind.ARRAY, "Product categories.", 2760),

    VplibFieldName.VALID: (FieldGroup.VALIDATION, ValueKind.BOOLEAN, "Validation result flag.", 3000),
    VplibFieldName.ERRORS: (FieldGroup.VALIDATION, ValueKind.ARRAY, "Validation errors.", 3010),
    VplibFieldName.WARNINGS: (FieldGroup.VALIDATION, ValueKind.ARRAY, "Validation warnings.", 3020),
    VplibFieldName.MESSAGE: (FieldGroup.VALIDATION, ValueKind.STRING, "Validation message.", 3030),
    VplibFieldName.CODE: (FieldGroup.VALIDATION, ValueKind.STRING, "Error or warning code.", 3040),
    VplibFieldName.PATH: (FieldGroup.VALIDATION, ValueKind.STRING, "Package path.", 3050),
    VplibFieldName.FIELD: (FieldGroup.VALIDATION, ValueKind.STRING, "Field name.", 3060),
    VplibFieldName.SEVERITY: (FieldGroup.VALIDATION, ValueKind.STRING, "Message severity.", 3070),

    VplibFieldName.CREATED_FILES: (FieldGroup.REPORT, ValueKind.ARRAY, "Created files.", 3100),
    VplibFieldName.CREATED_DIRECTORIES: (FieldGroup.REPORT, ValueKind.ARRAY, "Created directories.", 3110),
    VplibFieldName.COPIED_ASSETS: (FieldGroup.REPORT, ValueKind.ARRAY, "Copied assets.", 3120),
    VplibFieldName.PACKAGE_PATH: (FieldGroup.REPORT, ValueKind.STRING, "Package path.", 3130),
    VplibFieldName.ARCHIVE_PATH: (FieldGroup.REPORT, ValueKind.NULLABLE_STRING, "Archive path.", 3140),
}


def _build_field_definitions() -> dict[VplibFieldName, FieldDefinition]:
    definitions = dict(_FIELD_DEFINITIONS)

    for field_name, (group, value_kind, description, order) in _GENERATED_FIELD_GROUPS.items():
        if field_name in definitions:
            continue
        definitions[field_name] = FieldDefinition(
            name=field_name,
            group=group,
            value_kind=value_kind,
            description=description,
            required_in_core_documents=False,
            stable_order=order,
        )

    return definitions


_ALL_FIELD_DEFINITIONS: Final[dict[VplibFieldName, FieldDefinition]] = _build_field_definitions()


_ALIAS_MAP: Final[dict[str, VplibFieldName]] = {
    # Classification aliases
    "reiter": VplibFieldName.DOMAIN,
    "tab": VplibFieldName.TAB,
    "tabs": VplibFieldName.TAB,
    "domain": VplibFieldName.DOMAIN,
    "domain_key": VplibFieldName.DOMAIN,
    "domain_id": VplibFieldName.DOMAIN_ID,
    "domain_label": VplibFieldName.DOMAIN_LABEL,
    "category": VplibFieldName.CATEGORY,
    "category_key": VplibFieldName.CATEGORY,
    "category_id": VplibFieldName.CATEGORY_ID,
    "category_label": VplibFieldName.CATEGORY_LABEL,
    "subcategory": VplibFieldName.SUBCATEGORY,
    "sub_category": VplibFieldName.SUBCATEGORY,
    "subcategory_key": VplibFieldName.SUBCATEGORY,
    "subcategory_id": VplibFieldName.SUBCATEGORY_ID,
    "subcategory_label": VplibFieldName.SUBCATEGORY_LABEL,
    "classification": VplibFieldName.CLASSIFICATION_PATH,
    "classification_path": VplibFieldName.CLASSIFICATION_PATH,

    # Common aliases
    "id": VplibFieldName.FAMILY_ID,
    "name": VplibFieldName.FAMILY_NAME,
    "slug": VplibFieldName.FAMILY_SLUG,
    "title": VplibFieldName.DISPLAY_NAME,
    "object_type": VplibFieldName.OBJECT_KIND,
    "kind": VplibFieldName.OBJECT_KIND,
    "type": VplibFieldName.OBJECT_KIND,
    "modules": VplibFieldName.ACTIVE_MODULES,
    "footprint": VplibFieldName.GRID_FOOTPRINT,
    "grid_size": VplibFieldName.SIZE_CELLS,
    "x": VplibFieldName.SIZE_CELLS_X,
    "y": VplibFieldName.SIZE_CELLS_Y,
    "z": VplibFieldName.SIZE_CELLS_Z,
    "cell_size": VplibFieldName.CELL_SIZE_M,
    "default_variant": VplibFieldName.DEFAULT_VARIANT_ID,
    "variant": VplibFieldName.VARIANT_ID,
    "variant_name": VplibFieldName.VARIANT_LABEL,
    "placement_type": VplibFieldName.PLACEMENT_MODE,
    "color": VplibFieldName.FALLBACK_COLOR,
    "texture": VplibFieldName.TEXTURE_REF,
    "glb": VplibFieldName.GLB_REF,
    "mesh": VplibFieldName.GLB_REF,
    "model": VplibFieldName.MODEL_REF,
    "icon": VplibFieldName.ICON_REF,
    "preview": VplibFieldName.PREVIEW_REF,
    "bounds": VplibFieldName.MODEL_BOUNDS_M,
    "wall_thickness": VplibFieldName.WALL_THICKNESS_M,
    "density": VplibFieldName.DENSITY_KG_M3,
    "raw_density": VplibFieldName.RAW_DENSITY_KG_M3,
    "volume": VplibFieldName.VOLUME_M3,
    "mass": VplibFieldName.MASS_KG,
    "u_value": VplibFieldName.U_VALUE,
    "lambda": VplibFieldName.THERMAL_CONDUCTIVITY,
}


def _normalize_key(value: Any) -> str:
    """
    Normalize arbitrary input into a comparable field-name key.

    Raises:
        FieldNameError: If the value cannot be converted into a usable key.
    """
    try:
        if isinstance(value, VplibFieldName):
            return value.value

        if value is None:
            raise FieldNameError("Field name is required, got None.")

        raw = str(value).strip()
        if not raw:
            raise FieldNameError("Field name is required, got an empty value.")

        return (
            raw.lower()
            .replace(" ", "_")
            .replace("-", "_")
            .replace(".", "_")
            .replace("/", "_")
            .replace("\\", "_")
        )
    except FieldNameError:
        raise
    except Exception as exc:
        raise FieldNameError(f"Could not normalize field name {value!r}.") from exc


@lru_cache(maxsize=1024)
def parse_field_name(value: Any) -> VplibFieldName:
    """
    Parse a field-name input into a canonical VplibFieldName.

    Accepts canonical values and controlled aliases.

    Raises:
        FieldNameError: If the field name is unknown.
    """
    key = _normalize_key(value)

    try:
        return VplibFieldName(key)
    except ValueError:
        pass

    try:
        return _ALIAS_MAP[key]
    except KeyError as exc:
        allowed = ", ".join(get_field_name_values())
        raise FieldNameError(
            f"Unknown VPLIB field name {value!r}. Allowed values: {allowed}."
        ) from exc


def try_parse_field_name(
    value: Any,
    default: VplibFieldName | None = None,
) -> VplibFieldName | None:
    """
    Safe field-name parser.

    Returns default instead of raising FieldNameError.
    """
    try:
        return parse_field_name(value)
    except FieldNameError:
        return default
    except Exception:
        return default


def is_valid_field_name(value: Any) -> bool:
    """Return True if value can be parsed as a canonical VPLIB field name."""
    try:
        parse_field_name(value)
        return True
    except Exception:
        return False


@lru_cache(maxsize=1)
def get_field_name_values() -> tuple[str, ...]:
    """Return all canonical field-name string values in stable order."""
    return tuple(field.value for field in get_all_field_names())


@lru_cache(maxsize=1)
def get_field_name_aliases() -> Mapping[str, str]:
    """Return a read-only-style mapping of supported aliases to canonical values."""
    return {alias: field.value for alias, field in _ALIAS_MAP.items()}


@lru_cache(maxsize=1)
def get_field_definitions() -> Mapping[VplibFieldName, FieldDefinition]:
    """Return all canonical field definitions."""
    return dict(_ALL_FIELD_DEFINITIONS)


@lru_cache(maxsize=1)
def get_all_field_names() -> tuple[VplibFieldName, ...]:
    """Return all canonical field names in stable order."""
    return tuple(
        definition.name
        for definition in sorted(
            _ALL_FIELD_DEFINITIONS.values(),
            key=lambda definition: definition.stable_order,
        )
    )


@lru_cache(maxsize=256)
def get_field_definition(value: Any) -> FieldDefinition:
    """
    Return the field definition for a field-name value.

    Raises:
        FieldNameError: If the value is unknown or the definition is missing.
    """
    field_name = parse_field_name(value)

    try:
        return _ALL_FIELD_DEFINITIONS[field_name]
    except KeyError as exc:
        raise FieldNameError(f"Missing field definition for {field_name.value!r}.") from exc


def ensure_field_name(value: Any) -> VplibFieldName:
    """Strict parser for call sites that require a valid field name."""
    return parse_field_name(value)


def ensure_field_name_value(value: Any) -> str:
    """Return the canonical string value for a field-name input."""
    return ensure_field_name(value).value


def get_field_group(value: Any) -> FieldGroup:
    """Return the group for a field name."""
    return get_field_definition(value).group


def get_field_value_kind(value: Any) -> ValueKind:
    """Return the value-kind hint for a field name."""
    return get_field_definition(value).value_kind


def get_fields_by_group(group: Any) -> tuple[VplibFieldName, ...]:
    """
    Return all field names for a group.

    Raises:
        FieldNameError: If the group is unknown.
    """
    try:
        group_value = (
            group
            if isinstance(group, FieldGroup)
            else FieldGroup(str(group).strip().lower())
        )

        return tuple(
            definition.name
            for definition in sorted(
                _ALL_FIELD_DEFINITIONS.values(),
                key=lambda definition: definition.stable_order,
            )
            if definition.group == group_value
        )
    except ValueError as exc:
        raise FieldNameError(f"Unknown field group {group!r}.") from exc
    except Exception as exc:
        raise FieldNameError(f"Could not get fields for group {group!r}.") from exc


def get_classification_field_names() -> tuple[VplibFieldName, ...]:
    """
    Return canonical classification fields.

    Classification is the VPLIB hierarchy:
    domain/tab -> category -> subcategory.
    """
    return (
        VplibFieldName.DOMAIN,
        VplibFieldName.CATEGORY,
        VplibFieldName.SUBCATEGORY,
    )


def get_classification_id_field_names() -> tuple[VplibFieldName, ...]:
    """Return stable id fields for classification hierarchy."""
    return (
        VplibFieldName.DOMAIN_ID,
        VplibFieldName.CATEGORY_ID,
        VplibFieldName.SUBCATEGORY_ID,
    )


def get_classification_label_field_names() -> tuple[VplibFieldName, ...]:
    """Return display label fields for classification hierarchy."""
    return (
        VplibFieldName.DOMAIN_LABEL,
        VplibFieldName.CATEGORY_LABEL,
        VplibFieldName.SUBCATEGORY_LABEL,
    )


def build_classification_payload(
    *,
    domain: str,
    category: str,
    subcategory: str,
    domain_label: str | None = None,
    category_label: str | None = None,
    subcategory_label: str | None = None,
) -> dict[str, Any]:
    """
    Build a canonical classification payload.

    This does not validate allowed domain/category/subcategory values. That
    belongs to the classification domain file. This function only shapes fields.
    """
    normalized_domain = _clean_required_string(domain, "domain")
    normalized_category = _clean_required_string(category, "category")
    normalized_subcategory = _clean_required_string(subcategory, "subcategory")

    payload: dict[str, Any] = {
        VplibFieldName.DOMAIN.value: normalized_domain,
        VplibFieldName.TAB.value: normalized_domain,
        VplibFieldName.CATEGORY.value: normalized_category,
        VplibFieldName.SUBCATEGORY.value: normalized_subcategory,
        VplibFieldName.CLASSIFICATION_PATH.value: (
            f"{normalized_domain}/{normalized_category}/{normalized_subcategory}"
        ),
    }

    if domain_label is not None:
        payload[VplibFieldName.DOMAIN_LABEL.value] = str(domain_label).strip()

    if category_label is not None:
        payload[VplibFieldName.CATEGORY_LABEL.value] = str(category_label).strip()

    if subcategory_label is not None:
        payload[VplibFieldName.SUBCATEGORY_LABEL.value] = str(subcategory_label).strip()

    return payload


def _clean_required_string(value: Any, field_name: str) -> str:
    """Return a stripped non-empty string or raise FieldNameError."""
    try:
        cleaned = str(value).strip()
        if not cleaned:
            raise FieldNameError(f"{field_name} is required.")
        return cleaned
    except FieldNameError:
        raise
    except Exception as exc:
        raise FieldNameError(f"Invalid value for {field_name!r}.") from exc


def filter_valid_field_names(values: Iterable[Any]) -> tuple[VplibFieldName, ...]:
    """
    Parse many values and return only valid field names.

    Invalid entries are ignored. Duplicates are removed while preserving order.
    """
    result: list[VplibFieldName] = []
    seen: set[VplibFieldName] = set()

    for value in values:
        field_name = try_parse_field_name(value)
        if field_name is None or field_name in seen:
            continue
        result.append(field_name)
        seen.add(field_name)

    return tuple(result)


def field_definition_to_json(value: Any) -> dict[str, Any]:
    """
    Serialize one field definition into a JSON-compatible dictionary.
    """
    definition = get_field_definition(value)

    return {
        "schema_version": FIELD_NAME_SCHEMA_VERSION,
        "name": definition.name.value,
        "group": definition.group.value,
        "value_kind": definition.value_kind.value,
        "description": definition.description,
        "required_in_core_documents": definition.required_in_core_documents,
        "stable_order": definition.stable_order,
    }


def all_field_definitions_to_json() -> list[dict[str, Any]]:
    """Serialize all field definitions into JSON-compatible dictionaries."""
    return [field_definition_to_json(field) for field in get_all_field_names()]


def clear_field_name_caches() -> None:
    """
    Clear internal lru_cache state.

    Useful for tests and long-running developer sessions.
    """
    parse_field_name.cache_clear()
    get_field_name_values.cache_clear()
    get_field_name_aliases.cache_clear()
    get_field_definitions.cache_clear()
    get_all_field_names.cache_clear()
    get_field_definition.cache_clear()


__all__ = [
    "FIELD_NAME_SCHEMA_VERSION",
    "FieldDefinition",
    "FieldGroup",
    "FieldNameError",
    "ValueKind",
    "VplibFieldName",
    "all_field_definitions_to_json",
    "build_classification_payload",
    "clear_field_name_caches",
    "ensure_field_name",
    "ensure_field_name_value",
    "field_definition_to_json",
    "filter_valid_field_names",
    "get_all_field_names",
    "get_classification_field_names",
    "get_classification_id_field_names",
    "get_classification_label_field_names",
    "get_field_definition",
    "get_field_definitions",
    "get_field_group",
    "get_field_name_aliases",
    "get_field_name_values",
    "get_field_value_kind",
    "get_fields_by_group",
    "is_valid_field_name",
    "parse_field_name",
    "try_parse_field_name",
]