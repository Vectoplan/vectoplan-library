# services/vectoplan-library/src/vplib/profiles/multi_cell_module_profile.py
"""
Multi-cell-module object-kind profile for the VPLIB package engine.

Diese Datei definiert das feste Profil für:

    object_kind = multi_cell_module

Ein multi_cell_module ist ein zusammenhängendes Bauteil oder Objekt, das mehrere
Rasterzellen belegt, aber fachlich weiterhin eine einzige Family/Instance bleibt.

Typische Fälle:
- stair core
- shaft
- foundation module
- technical block
- multi-cell prefabricated component

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


MULTI_CELL_MODULE_PROFILE_SCHEMA_VERSION: Final[str] = "vplib.profile.multi_cell_module.v1"
MULTI_CELL_MODULE_PROFILE_KEY: Final[str] = "multi_cell_module_profile"
MULTI_CELL_MODULE_OBJECT_KIND: Final[str] = "multi_cell_module"

MULTI_CELL_MODULE_REQUIRED_MODULES: Final[tuple[str, ...]] = (
    "manifest",
    "modules",
    "family",
    "variants",
    "editor",
    "render",
    "physical",
    "manufacturer",
)

MULTI_CELL_MODULE_RECOMMENDED_MODULES: Final[tuple[str, ...]] = (
    "material",
    "calculation",
)

MULTI_CELL_MODULE_OPTIONAL_MODULES: Final[tuple[str, ...]] = (
    "analysis",
    "docs",
    "tests",
)

MULTI_CELL_MODULE_EXCLUDED_MODULES: Final[tuple[str, ...]] = (
    "dynamic",
)

MULTI_CELL_MODULE_REQUIRED_DOCUMENTS: Final[tuple[tuple[str, str], ...]] = (
    ("family", "family/identity.json"),
    ("family", "family/classification.json"),
    ("variants", "variants/index.json"),
    ("variants", "variants/default.json"),
    ("editor", "editor/inventory.json"),
    ("editor", "editor/placement.json"),
    ("render", "render/render_variants.json"),
    ("physical", "physical/base.json"),
    ("physical", "physical/dimensions.json"),
    ("physical", "physical/collision.json"),
    ("physical", "physical/occupancy.json"),
    ("manufacturer", "manufacturer/contract.json"),
)

MULTI_CELL_MODULE_OPTIONAL_DOCUMENTS: Final[tuple[tuple[str, str], ...]] = (
    ("editor", "editor/targeting.json"),
    ("editor", "editor/anchors.json"),
    ("editor", "editor/sockets.json"),
    ("editor", "editor/ports.json"),
    ("render", "render/bounds.json"),
    ("render", "render/materials.json"),
    ("render", "render/lod.json"),
    ("physical", "physical/layers.json"),
    ("physical", "physical/mass.json"),
    ("physical", "physical/footprint.json"),
    ("material", "material/base.json"),
    ("material", "material/performance.json"),
    ("calculation", "calculation/variables.json"),
    ("calculation", "calculation/formulas.json"),
    ("calculation", "calculation/quantities.json"),
    ("calculation", "calculation/measure_logic.json"),
    ("calculation", "calculation/constraints.json"),
    ("analysis", "analysis/statics/profile.json"),
    ("analysis", "analysis/routing/profile.json"),
    ("manufacturer", "manufacturer/override_slots.json"),
)

MULTI_CELL_MODULE_ALLOWED_PLACEMENT_MODES: Final[tuple[str, ...]] = (
    "centered",
    "bottom_aligned",
    "fill_block",
    "surface_aligned",
)

MULTI_CELL_MODULE_RECOMMENDED_PLACEMENT_MODE: Final[str] = "bottom_aligned"

MULTI_CELL_MODULE_DEFAULT_GRID_SIZE_CELLS: Final[tuple[int, int, int]] = (2, 1, 2)

MULTI_CELL_MODULE_ALLOWED_ASSET_EXTENSIONS: Final[tuple[str, ...]] = (
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

MULTI_CELL_MODULE_DEFAULT_MAX_MODEL_SIZE_MB: Final[float] = 75.0
MULTI_CELL_MODULE_DEFAULT_MAX_TEXTURE_SIZE_MB: Final[float] = 25.0
MULTI_CELL_MODULE_DEFAULT_MAX_PREVIEW_SIZE_MB: Final[float] = 8.0


def build_multi_cell_module_profile(
    *,
    metadata: Mapping[str, Any] | None = None,
) -> ObjectKindProfile:
    """
    Baut das kanonische multi_cell_module-Profil.

    Dieses Profil ist strenger als cell_block bei Occupancy:
    - physical/occupancy.json ist required
    - render ist required
    - physical ist required
    - dynamic ist ausgeschlossen
    - GLB ist erlaubt und für größere Module oft sinnvoll
    - sichtbare Bounds müssen in den mehrzelligen Grid-Footprint passen
    """
    try:
        extra_module_rules = (
            *multi_cell_module_required_module_rules(),
            *multi_cell_module_recommended_module_rules(),
            *multi_cell_module_optional_module_rules(),
            *multi_cell_module_excluded_module_rules(),
        )

        extra_document_rules = (
            *multi_cell_module_required_document_rules(),
            *multi_cell_module_optional_document_rules(),
        )

        extra_asset_rules = multi_cell_module_asset_rules()
        extra_validation_rules = multi_cell_module_validation_rules()

        profile = build_base_profile(
            profile_key=MULTI_CELL_MODULE_PROFILE_KEY,
            object_kind=MULTI_CELL_MODULE_OBJECT_KIND,
            title="Multi Cell Module Profile",
            description=(
                "Profile for VPLIB elements that occupy multiple grid cells but "
                "remain a single semantic family and project instance."
            ),
            defaults=ProfileDefaults(
                schema_version=MULTI_CELL_MODULE_PROFILE_SCHEMA_VERSION,
                variant_mode="single",
                default_variant_id="default",
                placement_mode=MULTI_CELL_MODULE_RECOMMENDED_PLACEMENT_MODE,
                fit_mode="strict_inside",
                fallback_color="#6B7280",
                cell_size_m=1.0,
                grid_size_cells=MULTI_CELL_MODULE_DEFAULT_GRID_SIZE_CELLS,
                manufacturer_allowed=False,
                manufacturer_overlay_level="none",
            ),
            extra_module_rules=extra_module_rules,
            extra_document_rules=extra_document_rules,
            extra_asset_rules=extra_asset_rules,
            extra_validation_rules=extra_validation_rules,
            validation_mode=ProfileValidationMode.STRICT.value,
            metadata={
                "profile_schema_version": MULTI_CELL_MODULE_PROFILE_SCHEMA_VERSION,
                "allowed_placement_modes": list(MULTI_CELL_MODULE_ALLOWED_PLACEMENT_MODES),
                "recommended_placement_mode": MULTI_CELL_MODULE_RECOMMENDED_PLACEMENT_MODE,
                "default_grid_size_cells": list(MULTI_CELL_MODULE_DEFAULT_GRID_SIZE_CELLS),
                **dict(metadata or {}),
            },
        ).normalized()

        return profile
    except ProfileError:
        raise
    except Exception as exc:
        raise ProfileError(f"Could not build multi_cell_module profile: {exc}") from exc


def multi_cell_module_required_module_rules() -> tuple[ProfileModuleRule, ...]:
    """Erzeugt multi_cell_module-required Modulregeln."""
    return tuple(
        ProfileModuleRule(
            module_name=module_name,
            requirement=ProfileModuleRequirement.REQUIRED.value,
            active_by_default=True,
            reason="Required for multi_cell_module packages.",
        ).normalized()
        for module_name in MULTI_CELL_MODULE_REQUIRED_MODULES
    )


def multi_cell_module_recommended_module_rules() -> tuple[ProfileModuleRule, ...]:
    """Erzeugt multi_cell_module-recommended Modulregeln."""
    return tuple(
        ProfileModuleRule(
            module_name=module_name,
            requirement=ProfileModuleRequirement.RECOMMENDED.value,
            active_by_default=True,
            reason="Recommended for technically useful multi_cell_module packages.",
        ).normalized()
        for module_name in MULTI_CELL_MODULE_RECOMMENDED_MODULES
    )


def multi_cell_module_optional_module_rules() -> tuple[ProfileModuleRule, ...]:
    """Erzeugt multi_cell_module-optionale Modulregeln."""
    return tuple(
        ProfileModuleRule(
            module_name=module_name,
            requirement=ProfileModuleRequirement.OPTIONAL.value,
            active_by_default=False,
            reason="Optional for multi_cell_module packages.",
        ).normalized()
        for module_name in MULTI_CELL_MODULE_OPTIONAL_MODULES
    )


def multi_cell_module_excluded_module_rules() -> tuple[ProfileModuleRule, ...]:
    """Erzeugt multi_cell_module-ausgeschlossene Modulregeln."""
    return tuple(
        ProfileModuleRule(
            module_name=module_name,
            requirement=ProfileModuleRequirement.EXCLUDED.value,
            active_by_default=False,
            reason="multi_cell_module packages use fixed multi-cell occupancy, not adaptive dynamic modules.",
        ).normalized()
        for module_name in MULTI_CELL_MODULE_EXCLUDED_MODULES
    )


def multi_cell_module_required_document_rules() -> tuple[ProfileDocumentRule, ...]:
    """Erzeugt required document rules für multi_cell_module."""
    return tuple(
        ProfileDocumentRule(
            module_name=module_name,
            path=path,
            required=True,
            generated=True,
            allow_empty_initially=False,
            reason="Required multi_cell_module document.",
        ).normalized()
        for module_name, path in MULTI_CELL_MODULE_REQUIRED_DOCUMENTS
    )


def multi_cell_module_optional_document_rules() -> tuple[ProfileDocumentRule, ...]:
    """Erzeugt optional document rules für multi_cell_module."""
    return tuple(
        ProfileDocumentRule(
            module_name=module_name,
            path=path,
            required=False,
            generated=True,
            allow_empty_initially=True,
            reason="Optional multi_cell_module document.",
        ).normalized()
        for module_name, path in MULTI_CELL_MODULE_OPTIONAL_DOCUMENTS
    )


def multi_cell_module_asset_rules() -> tuple[ProfileAssetRule, ...]:
    """
    Erzeugt Assetregeln für multi_cell_module.

    Multi-cell modules dürfen einfache Renderformen nutzen, aber GLB-Modelle sind
    häufig sinnvoll. Wenn ein GLB verwendet wird, müssen Bounds vorhanden sein und
    vollständig im belegten Grid-Footprint liegen.
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
            max_size_mb=MULTI_CELL_MODULE_DEFAULT_MAX_PREVIEW_SIZE_MB,
            requires_bounds=False,
            must_fit_grid_footprint=False,
            reason="Previews are recommended for creative-library display.",
        ).normalized(),
        ProfileAssetRule(
            role="texture",
            policy=ProfileAssetPolicy.OPTIONAL.value,
            module_name="render",
            allowed_extensions=(".png", ".jpg", ".jpeg", ".webp", ".ktx2", ".basis"),
            max_size_mb=MULTI_CELL_MODULE_DEFAULT_MAX_TEXTURE_SIZE_MB,
            requires_bounds=False,
            must_fit_grid_footprint=False,
            reason="Textures are optional because fallback_color is allowed.",
        ).normalized(),
        ProfileAssetRule(
            role="material_texture",
            policy=ProfileAssetPolicy.OPTIONAL.value,
            module_name="render",
            allowed_extensions=(".png", ".jpg", ".jpeg", ".webp", ".ktx2", ".basis"),
            max_size_mb=MULTI_CELL_MODULE_DEFAULT_MAX_TEXTURE_SIZE_MB,
            requires_bounds=False,
            must_fit_grid_footprint=False,
            reason="Material textures are optional for richer rendering.",
        ).normalized(),
        ProfileAssetRule(
            role="glb_model",
            policy=ProfileAssetPolicy.RECOMMENDED.value,
            module_name="render",
            allowed_extensions=(".glb",),
            max_size_mb=MULTI_CELL_MODULE_DEFAULT_MAX_MODEL_SIZE_MB,
            requires_bounds=True,
            must_fit_grid_footprint=True,
            reason="GLB models are recommended for multi-cell modules and must fit inside the occupied grid footprint.",
        ).normalized(),
        ProfileAssetRule(
            role="gltf_model",
            policy=ProfileAssetPolicy.OPTIONAL.value,
            module_name="render",
            allowed_extensions=(".gltf",),
            max_size_mb=MULTI_CELL_MODULE_DEFAULT_MAX_MODEL_SIZE_MB,
            requires_bounds=True,
            must_fit_grid_footprint=True,
            reason="glTF models are allowed and must fit inside the occupied grid footprint.",
        ).normalized(),
    )


def multi_cell_module_validation_rules() -> tuple[ProfileValidationRule, ...]:
    """Erzeugt multi_cell_module-spezifische Validierungsregeln."""
    return (
        ProfileValidationRule(
            rule_key="multi_cell_module_grid_footprint_has_multiple_cells",
            scope=ProfileRuleScope.PHYSICAL.value,
            severity=ProfileRuleSeverity.ERROR.value,
            enabled=True,
            message=(
                "multi_cell_module packages must occupy more than one grid cell "
                "in at least one dimension."
            ),
            details={
                "minimum_rule": "max(size_cells_x, size_cells_y, size_cells_z) > 1",
            },
        ).normalized(),
        ProfileValidationRule(
            rule_key="multi_cell_module_occupancy_required",
            scope=ProfileRuleScope.PHYSICAL.value,
            severity=ProfileRuleSeverity.ERROR.value,
            enabled=True,
            message="physical/occupancy.json is required for multi_cell_module packages.",
        ).normalized(),
        ProfileValidationRule(
            rule_key="multi_cell_module_collision_required",
            scope=ProfileRuleScope.PHYSICAL.value,
            severity=ProfileRuleSeverity.ERROR.value,
            enabled=True,
            message="physical/collision.json is required for multi_cell_module packages.",
        ).normalized(),
        ProfileValidationRule(
            rule_key="multi_cell_module_no_dynamic_module",
            scope=ProfileRuleScope.DYNAMIC.value,
            severity=ProfileRuleSeverity.ERROR.value,
            enabled=True,
            message="multi_cell_module packages must not enable the dynamic module.",
        ).normalized(),
        ProfileValidationRule(
            rule_key="multi_cell_module_visual_fits_grid_footprint",
            scope=ProfileRuleScope.RENDER.value,
            severity=ProfileRuleSeverity.ERROR.value,
            enabled=True,
            message="The visible model must not exceed the occupied multi-cell grid footprint.",
        ).normalized(),
        ProfileValidationRule(
            rule_key="multi_cell_module_placement_mode_allowed",
            scope=ProfileRuleScope.PLACEMENT.value,
            severity=ProfileRuleSeverity.ERROR.value,
            enabled=True,
            message="The placement mode must be allowed for multi_cell_module.",
            details={
                "allowed_placement_modes": list(MULTI_CELL_MODULE_ALLOWED_PLACEMENT_MODES),
            },
        ).normalized(),
        ProfileValidationRule(
            rule_key="multi_cell_module_single_semantic_instance",
            scope=ProfileRuleScope.PROFILE.value,
            severity=ProfileRuleSeverity.WARNING.value,
            enabled=True,
            message=(
                "A multi_cell_module occupies multiple cells but must remain one "
                "semantic family and later one project instance."
            ),
        ).normalized(),
        ProfileValidationRule(
            rule_key="multi_cell_module_variant_overrides_limited",
            scope=ProfileRuleScope.VARIANT.value,
            severity=ProfileRuleSeverity.ERROR.value,
            enabled=True,
            message="Variants must only define allowed overrides, not duplicate the full family.",
        ).normalized(),
        ProfileValidationRule(
            rule_key="multi_cell_module_calculation_declarative_only",
            scope=ProfileRuleScope.CALCULATION.value,
            severity=ProfileRuleSeverity.ERROR.value,
            enabled=True,
            message="Calculation data must be declarative and must not reference executable code.",
        ).normalized(),
    )


def get_multi_cell_module_profile() -> ObjectKindProfile:
    """Gibt das kanonische multi_cell_module-Profil zurück."""
    return build_multi_cell_module_profile()


def multi_cell_module_profile_to_dict() -> dict[str, Any]:
    """Serialisiert das multi_cell_module-Profil JSON-kompatibel."""
    return get_multi_cell_module_profile().to_dict()


def validate_multi_cell_module_profile() -> tuple[bool, tuple[str, ...]]:
    """Validiert das multi_cell_module-Profil selbst."""
    try:
        profile = get_multi_cell_module_profile()
        return profile.validate()
    except Exception as exc:
        return False, (f"Invalid multi_cell_module profile: {exc}",)


def assert_multi_cell_module_profile_valid() -> None:
    """Wirft ProfileError, wenn das multi_cell_module-Profil ungültig ist."""
    valid, messages = validate_multi_cell_module_profile()

    if not valid:
        joined = " ".join(messages) if messages else "Invalid multi_cell_module profile."
        raise ProfileError(joined)


__all__ = [
    "MULTI_CELL_MODULE_ALLOWED_ASSET_EXTENSIONS",
    "MULTI_CELL_MODULE_ALLOWED_PLACEMENT_MODES",
    "MULTI_CELL_MODULE_DEFAULT_GRID_SIZE_CELLS",
    "MULTI_CELL_MODULE_DEFAULT_MAX_MODEL_SIZE_MB",
    "MULTI_CELL_MODULE_DEFAULT_MAX_PREVIEW_SIZE_MB",
    "MULTI_CELL_MODULE_DEFAULT_MAX_TEXTURE_SIZE_MB",
    "MULTI_CELL_MODULE_EXCLUDED_MODULES",
    "MULTI_CELL_MODULE_OBJECT_KIND",
    "MULTI_CELL_MODULE_OPTIONAL_DOCUMENTS",
    "MULTI_CELL_MODULE_OPTIONAL_MODULES",
    "MULTI_CELL_MODULE_PROFILE_KEY",
    "MULTI_CELL_MODULE_PROFILE_SCHEMA_VERSION",
    "MULTI_CELL_MODULE_RECOMMENDED_MODULES",
    "MULTI_CELL_MODULE_RECOMMENDED_PLACEMENT_MODE",
    "MULTI_CELL_MODULE_REQUIRED_DOCUMENTS",
    "MULTI_CELL_MODULE_REQUIRED_MODULES",
    "assert_multi_cell_module_profile_valid",
    "build_multi_cell_module_profile",
    "get_multi_cell_module_profile",
    "multi_cell_module_asset_rules",
    "multi_cell_module_excluded_module_rules",
    "multi_cell_module_optional_document_rules",
    "multi_cell_module_optional_module_rules",
    "multi_cell_module_profile_to_dict",
    "multi_cell_module_recommended_module_rules",
    "multi_cell_module_required_document_rules",
    "multi_cell_module_required_module_rules",
    "multi_cell_module_validation_rules",
    "validate_multi_cell_module_profile",
]