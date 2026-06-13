# services/vectoplan-library/src/vplib/profiles/catalog_object_profile.py
"""
Catalog-object object-kind profile for the VPLIB package engine.

Diese Datei definiert das feste Profil für:

    object_kind = catalog_object

Ein catalog_object ist ein eher freies Objekt oder Ausstattungsobjekt innerhalb
eines Raster-Footprints. Es kann ein GLB-Modell, einfache Renderdaten, Bounding-
Daten und optionale technische Profile besitzen.

Typische Fälle:
- faucet
- furniture
- fixture
- heat pump
- cabinet
- equipment object

Technische Namen, JSON-Keys und Variablen bleiben Englisch.
"""

from __future__ import annotations

from typing import Any, Final, Mapping

from .base_profiles import (
    ObjectKindProfile,
    ProfileAssetPolicy,
    ProfileAssetRule,
    ProfileDefaults,
    ProfileDocumentRule,
    ProfileError,
    ProfileModuleRequirement,
    ProfileModuleRule,
    ProfileRuleScope,
    ProfileRuleSeverity,
    ProfileValidationMode,
    ProfileValidationRule,
    build_base_profile,
)


CATALOG_OBJECT_PROFILE_SCHEMA_VERSION: Final[str] = "vplib.profile.catalog_object.v1"
CATALOG_OBJECT_PROFILE_KEY: Final[str] = "catalog_object_profile"
CATALOG_OBJECT_OBJECT_KIND: Final[str] = "catalog_object"

CATALOG_OBJECT_REQUIRED_MODULES: Final[tuple[str, ...]] = (
    "manifest",
    "modules",
    "family",
    "variants",
    "editor",
    "render",
    "physical",
    "manufacturer",
)

CATALOG_OBJECT_RECOMMENDED_MODULES: Final[tuple[str, ...]] = (
    "material",
)

CATALOG_OBJECT_OPTIONAL_MODULES: Final[tuple[str, ...]] = (
    "calculation",
    "analysis",
    "docs",
    "tests",
)

CATALOG_OBJECT_EXCLUDED_MODULES: Final[tuple[str, ...]] = (
    "dynamic",
)

CATALOG_OBJECT_REQUIRED_DOCUMENTS: Final[tuple[tuple[str, str], ...]] = (
    ("family", "family/identity.json"),
    ("family", "family/classification.json"),
    ("variants", "variants/index.json"),
    ("variants", "variants/default.json"),
    ("editor", "editor/inventory.json"),
    ("editor", "editor/placement.json"),
    ("render", "render/render_variants.json"),
    ("render", "render/bounds.json"),
    ("physical", "physical/base.json"),
    ("physical", "physical/dimensions.json"),
    ("physical", "physical/collision.json"),
    ("manufacturer", "manufacturer/contract.json"),
)

CATALOG_OBJECT_OPTIONAL_DOCUMENTS: Final[tuple[tuple[str, str], ...]] = (
    ("editor", "editor/targeting.json"),
    ("editor", "editor/anchors.json"),
    ("editor", "editor/sockets.json"),
    ("editor", "editor/ports.json"),
    ("render", "render/materials.json"),
    ("render", "render/lod.json"),
    ("physical", "physical/occupancy.json"),
    ("physical", "physical/mass.json"),
    ("physical", "physical/footprint.json"),
    ("material", "material/base.json"),
    ("material", "material/performance.json"),
    ("material", "material/surfaces.json"),
    ("calculation", "calculation/variables.json"),
    ("calculation", "calculation/formulas.json"),
    ("calculation", "calculation/quantities.json"),
    ("calculation", "calculation/measure_logic.json"),
    ("calculation", "calculation/constraints.json"),
    ("analysis", "analysis/routing/profile.json"),
    ("manufacturer", "manufacturer/override_slots.json"),
)

CATALOG_OBJECT_ALLOWED_PLACEMENT_MODES: Final[tuple[str, ...]] = (
    "centered",
    "bottom_aligned",
    "top_aligned",
    "surface_aligned",
)

CATALOG_OBJECT_RECOMMENDED_PLACEMENT_MODE: Final[str] = "centered"

CATALOG_OBJECT_DEFAULT_GRID_SIZE_CELLS: Final[tuple[int, int, int]] = (1, 1, 1)

CATALOG_OBJECT_ALLOWED_ASSET_EXTENSIONS: Final[tuple[str, ...]] = (
    ".svg",
    ".png",
    ".jpg",
    ".jpeg",
    ".webp",
    ".ktx2",
    ".basis",
    ".glb",
    ".gltf",
)

CATALOG_OBJECT_DEFAULT_MAX_MODEL_SIZE_MB: Final[float] = 100.0
CATALOG_OBJECT_DEFAULT_MAX_TEXTURE_SIZE_MB: Final[float] = 35.0
CATALOG_OBJECT_DEFAULT_MAX_PREVIEW_SIZE_MB: Final[float] = 8.0


def build_catalog_object_profile(
    *,
    metadata: Mapping[str, Any] | None = None,
) -> ObjectKindProfile:
    """
    Baut das kanonische catalog_object-Profil.

    Dieses Profil ist auf freie Objekte und Ausstattung ausgerichtet:
    - render ist required
    - render/bounds.json ist required
    - physical ist required, aber weniger fachlich tief als bei Bauteilen
    - material ist recommended
    - calculation ist optional
    - dynamic ist ausgeschlossen
    - GLB ist recommended, aber fallback rendering bleibt erlaubt
    """
    try:
        extra_module_rules = (
            *catalog_object_required_module_rules(),
            *catalog_object_recommended_module_rules(),
            *catalog_object_optional_module_rules(),
            *catalog_object_excluded_module_rules(),
        )

        extra_document_rules = (
            *catalog_object_required_document_rules(),
            *catalog_object_optional_document_rules(),
        )

        extra_asset_rules = catalog_object_asset_rules()
        extra_validation_rules = catalog_object_validation_rules()

        profile = build_base_profile(
            profile_key=CATALOG_OBJECT_PROFILE_KEY,
            object_kind=CATALOG_OBJECT_OBJECT_KIND,
            title="Catalog Object Profile",
            description=(
                "Profile for VPLIB catalog objects such as furniture, fixtures, "
                "equipment, faucets, heat pumps or similar object-like elements "
                "that are placed inside a grid footprint."
            ),
            defaults=ProfileDefaults(
                schema_version=CATALOG_OBJECT_PROFILE_SCHEMA_VERSION,
                variant_mode="single",
                default_variant_id="default",
                placement_mode=CATALOG_OBJECT_RECOMMENDED_PLACEMENT_MODE,
                fit_mode="strict_inside",
                fallback_color="#94A3B8",
                cell_size_m=1.0,
                grid_size_cells=CATALOG_OBJECT_DEFAULT_GRID_SIZE_CELLS,
                manufacturer_allowed=False,
                manufacturer_overlay_level="none",
            ),
            extra_module_rules=extra_module_rules,
            extra_document_rules=extra_document_rules,
            extra_asset_rules=extra_asset_rules,
            extra_validation_rules=extra_validation_rules,
            validation_mode=ProfileValidationMode.STRICT.value,
            metadata={
                "profile_schema_version": CATALOG_OBJECT_PROFILE_SCHEMA_VERSION,
                "allowed_placement_modes": list(CATALOG_OBJECT_ALLOWED_PLACEMENT_MODES),
                "recommended_placement_mode": CATALOG_OBJECT_RECOMMENDED_PLACEMENT_MODE,
                "default_grid_size_cells": list(CATALOG_OBJECT_DEFAULT_GRID_SIZE_CELLS),
                **dict(metadata or {}),
            },
        ).normalized()

        return profile
    except ProfileError:
        raise
    except Exception as exc:
        raise ProfileError(f"Could not build catalog_object profile: {exc}") from exc


def catalog_object_required_module_rules() -> tuple[ProfileModuleRule, ...]:
    """Erzeugt catalog_object-required Modulregeln."""
    return tuple(
        ProfileModuleRule(
            module_name=module_name,
            requirement=ProfileModuleRequirement.REQUIRED.value,
            active_by_default=True,
            reason="Required for catalog_object packages.",
        ).normalized()
        for module_name in CATALOG_OBJECT_REQUIRED_MODULES
    )


def catalog_object_recommended_module_rules() -> tuple[ProfileModuleRule, ...]:
    """Erzeugt catalog_object-recommended Modulregeln."""
    return tuple(
        ProfileModuleRule(
            module_name=module_name,
            requirement=ProfileModuleRequirement.RECOMMENDED.value,
            active_by_default=True,
            reason="Recommended for richer catalog_object packages.",
        ).normalized()
        for module_name in CATALOG_OBJECT_RECOMMENDED_MODULES
    )


def catalog_object_optional_module_rules() -> tuple[ProfileModuleRule, ...]:
    """Erzeugt catalog_object-optionale Modulregeln."""
    return tuple(
        ProfileModuleRule(
            module_name=module_name,
            requirement=ProfileModuleRequirement.OPTIONAL.value,
            active_by_default=False,
            reason="Optional for catalog_object packages.",
        ).normalized()
        for module_name in CATALOG_OBJECT_OPTIONAL_MODULES
    )


def catalog_object_excluded_module_rules() -> tuple[ProfileModuleRule, ...]:
    """Erzeugt catalog_object-ausgeschlossene Modulregeln."""
    return tuple(
        ProfileModuleRule(
            module_name=module_name,
            requirement=ProfileModuleRequirement.EXCLUDED.value,
            active_by_default=False,
            reason="catalog_object packages are fixed catalog objects, not adaptive dynamic systems.",
        ).normalized()
        for module_name in CATALOG_OBJECT_EXCLUDED_MODULES
    )


def catalog_object_required_document_rules() -> tuple[ProfileDocumentRule, ...]:
    """Erzeugt required document rules für catalog_object."""
    return tuple(
        ProfileDocumentRule(
            module_name=module_name,
            path=path,
            required=True,
            generated=True,
            allow_empty_initially=False,
            reason="Required catalog_object document.",
        ).normalized()
        for module_name, path in CATALOG_OBJECT_REQUIRED_DOCUMENTS
    )


def catalog_object_optional_document_rules() -> tuple[ProfileDocumentRule, ...]:
    """Erzeugt optional document rules für catalog_object."""
    return tuple(
        ProfileDocumentRule(
            module_name=module_name,
            path=path,
            required=False,
            generated=True,
            allow_empty_initially=True,
            reason="Optional catalog_object document.",
        ).normalized()
        for module_name, path in CATALOG_OBJECT_OPTIONAL_DOCUMENTS
    )


def catalog_object_asset_rules() -> tuple[ProfileAssetRule, ...]:
    """
    Erzeugt Assetregeln für catalog_object.

    Für Katalogobjekte ist ein GLB-Modell empfohlen, aber nicht zwingend Pflicht,
    damit auch einfache frühe Objekte mit Fallback-Shape/Fallback-Color möglich
    bleiben. Bounds sind für Modelle Pflicht.
    """
    return (
        ProfileAssetRule(
            role="icon",
            policy=ProfileAssetPolicy.RECOMMENDED.value,
            module_name="render",
            allowed_extensions=(".svg", ".png", ".webp"),
            max_size_mb=1.0,
            requires_bounds=False,
            must_fit_grid_footprint=False,
            reason="Icons are recommended for library and inventory display.",
        ).normalized(),
        ProfileAssetRule(
            role="preview",
            policy=ProfileAssetPolicy.RECOMMENDED.value,
            module_name="render",
            allowed_extensions=(".png", ".jpg", ".jpeg", ".webp"),
            max_size_mb=CATALOG_OBJECT_DEFAULT_MAX_PREVIEW_SIZE_MB,
            requires_bounds=False,
            must_fit_grid_footprint=False,
            reason="Previews are recommended for catalog object display.",
        ).normalized(),
        ProfileAssetRule(
            role="texture",
            policy=ProfileAssetPolicy.OPTIONAL.value,
            module_name="render",
            allowed_extensions=(".png", ".jpg", ".jpeg", ".webp", ".ktx2", ".basis"),
            max_size_mb=CATALOG_OBJECT_DEFAULT_MAX_TEXTURE_SIZE_MB,
            requires_bounds=False,
            must_fit_grid_footprint=False,
            reason="Textures are optional for catalog objects.",
        ).normalized(),
        ProfileAssetRule(
            role="material_texture",
            policy=ProfileAssetPolicy.OPTIONAL.value,
            module_name="render",
            allowed_extensions=(".png", ".jpg", ".jpeg", ".webp", ".ktx2", ".basis"),
            max_size_mb=CATALOG_OBJECT_DEFAULT_MAX_TEXTURE_SIZE_MB,
            requires_bounds=False,
            must_fit_grid_footprint=False,
            reason="Material textures are optional for richer object rendering.",
        ).normalized(),
        ProfileAssetRule(
            role="glb_model",
            policy=ProfileAssetPolicy.RECOMMENDED.value,
            module_name="render",
            allowed_extensions=(".glb",),
            max_size_mb=CATALOG_OBJECT_DEFAULT_MAX_MODEL_SIZE_MB,
            requires_bounds=True,
            must_fit_grid_footprint=True,
            reason="GLB models are recommended for catalog objects and must fit inside the occupied grid footprint.",
        ).normalized(),
        ProfileAssetRule(
            role="gltf_model",
            policy=ProfileAssetPolicy.OPTIONAL.value,
            module_name="render",
            allowed_extensions=(".gltf",),
            max_size_mb=CATALOG_OBJECT_DEFAULT_MAX_MODEL_SIZE_MB,
            requires_bounds=True,
            must_fit_grid_footprint=True,
            reason="glTF models are allowed and must fit inside the occupied grid footprint.",
        ).normalized(),
    )


def catalog_object_validation_rules() -> tuple[ProfileValidationRule, ...]:
    """Erzeugt catalog_object-spezifische Validierungsregeln."""
    return (
        ProfileValidationRule(
            rule_key="catalog_object_render_bounds_required",
            scope=ProfileRuleScope.RENDER.value,
            severity=ProfileRuleSeverity.ERROR.value,
            enabled=True,
            message="render/bounds.json is required for catalog_object packages.",
        ).normalized(),
        ProfileValidationRule(
            rule_key="catalog_object_visual_fits_grid_footprint",
            scope=ProfileRuleScope.RENDER.value,
            severity=ProfileRuleSeverity.ERROR.value,
            enabled=True,
            message="The visible model must not exceed the occupied grid footprint.",
        ).normalized(),
        ProfileValidationRule(
            rule_key="catalog_object_visual_has_texture_color_or_model",
            scope=ProfileRuleScope.RENDER.value,
            severity=ProfileRuleSeverity.ERROR.value,
            enabled=True,
            message="A catalog_object must define a texture, a model or a fallback_color.",
        ).normalized(),
        ProfileValidationRule(
            rule_key="catalog_object_placement_mode_allowed",
            scope=ProfileRuleScope.PLACEMENT.value,
            severity=ProfileRuleSeverity.ERROR.value,
            enabled=True,
            message="The placement mode must be allowed for catalog_object.",
            details={
                "allowed_placement_modes": list(CATALOG_OBJECT_ALLOWED_PLACEMENT_MODES),
            },
        ).normalized(),
        ProfileValidationRule(
            rule_key="catalog_object_no_dynamic_module",
            scope=ProfileRuleScope.DYNAMIC.value,
            severity=ProfileRuleSeverity.ERROR.value,
            enabled=True,
            message="catalog_object packages must not enable the dynamic module.",
        ).normalized(),
        ProfileValidationRule(
            rule_key="catalog_object_collision_required",
            scope=ProfileRuleScope.PHYSICAL.value,
            severity=ProfileRuleSeverity.ERROR.value,
            enabled=True,
            message="physical/collision.json is required for catalog_object packages.",
        ).normalized(),
        ProfileValidationRule(
            rule_key="catalog_object_grid_footprint_positive",
            scope=ProfileRuleScope.PHYSICAL.value,
            severity=ProfileRuleSeverity.ERROR.value,
            enabled=True,
            message="catalog_object grid footprint must contain positive dimensions.",
        ).normalized(),
        ProfileValidationRule(
            rule_key="catalog_object_surface_alignment_requires_targeting",
            scope=ProfileRuleScope.PLACEMENT.value,
            severity=ProfileRuleSeverity.WARNING.value,
            enabled=True,
            message=(
                "surface_aligned catalog objects should define targeting or anchor "
                "metadata for predictable placement."
            ),
        ).normalized(),
        ProfileValidationRule(
            rule_key="catalog_object_variant_overrides_limited",
            scope=ProfileRuleScope.VARIANT.value,
            severity=ProfileRuleSeverity.ERROR.value,
            enabled=True,
            message="Variants must only define allowed overrides, not duplicate the full family.",
        ).normalized(),
    )


def get_catalog_object_profile() -> ObjectKindProfile:
    """Gibt das kanonische catalog_object-Profil zurück."""
    return build_catalog_object_profile()


def catalog_object_profile_to_dict() -> dict[str, Any]:
    """Serialisiert das catalog_object-Profil JSON-kompatibel."""
    return get_catalog_object_profile().to_dict()


def validate_catalog_object_profile() -> tuple[bool, tuple[str, ...]]:
    """Validiert das catalog_object-Profil selbst."""
    try:
        profile = get_catalog_object_profile()
        return profile.validate()
    except Exception as exc:
        return False, (f"Invalid catalog_object profile: {exc}",)


def assert_catalog_object_profile_valid() -> None:
    """Wirft ProfileError, wenn das catalog_object-Profil ungültig ist."""
    valid, messages = validate_catalog_object_profile()

    if not valid:
        joined = " ".join(messages) if messages else "Invalid catalog_object profile."
        raise ProfileError(joined)


__all__ = [
    "CATALOG_OBJECT_ALLOWED_ASSET_EXTENSIONS",
    "CATALOG_OBJECT_ALLOWED_PLACEMENT_MODES",
    "CATALOG_OBJECT_DEFAULT_GRID_SIZE_CELLS",
    "CATALOG_OBJECT_DEFAULT_MAX_MODEL_SIZE_MB",
    "CATALOG_OBJECT_DEFAULT_MAX_PREVIEW_SIZE_MB",
    "CATALOG_OBJECT_DEFAULT_MAX_TEXTURE_SIZE_MB",
    "CATALOG_OBJECT_EXCLUDED_MODULES",
    "CATALOG_OBJECT_OBJECT_KIND",
    "CATALOG_OBJECT_OPTIONAL_DOCUMENTS",
    "CATALOG_OBJECT_OPTIONAL_MODULES",
    "CATALOG_OBJECT_PROFILE_KEY",
    "CATALOG_OBJECT_PROFILE_SCHEMA_VERSION",
    "CATALOG_OBJECT_RECOMMENDED_MODULES",
    "CATALOG_OBJECT_RECOMMENDED_PLACEMENT_MODE",
    "CATALOG_OBJECT_REQUIRED_DOCUMENTS",
    "CATALOG_OBJECT_REQUIRED_MODULES",
    "assert_catalog_object_profile_valid",
    "build_catalog_object_profile",
    "catalog_object_asset_rules",
    "catalog_object_excluded_module_rules",
    "catalog_object_optional_document_rules",
    "catalog_object_optional_module_rules",
    "catalog_object_profile_to_dict",
    "catalog_object_recommended_module_rules",
    "catalog_object_required_document_rules",
    "catalog_object_required_module_rules",
    "catalog_object_validation_rules",
    "get_catalog_object_profile",
    "validate_catalog_object_profile",
]