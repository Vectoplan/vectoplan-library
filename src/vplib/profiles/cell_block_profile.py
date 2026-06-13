# services/vectoplan-library/src/vplib/profiles/cell_block_profile.py
"""
Cell-block object-kind profile for the VPLIB package engine.

Diese Datei definiert das feste Profil für:

    object_kind = cell_block

Ein cell_block ist ein Raster-Bauteil. Es ist für Elemente gedacht, die im
Editor als einzelner Block oder einfacher Rasterbaustein funktionieren, aber
trotzdem semantische Daten, Varianten, Materialwerte und Berechnungslogik tragen
können.

Typische Fälle:
- wall block
- slab block
- road block
- floor block
- simple building component

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


CELL_BLOCK_PROFILE_SCHEMA_VERSION: Final[str] = "vplib.profile.cell_block.v1"
CELL_BLOCK_PROFILE_KEY: Final[str] = "cell_block_profile"
CELL_BLOCK_OBJECT_KIND: Final[str] = "cell_block"

CELL_BLOCK_REQUIRED_MODULES: Final[tuple[str, ...]] = (
    "manifest",
    "modules",
    "family",
    "variants",
    "editor",
    "render",
    "physical",
    "manufacturer",
)

CELL_BLOCK_RECOMMENDED_MODULES: Final[tuple[str, ...]] = (
    "material",
    "calculation",
)

CELL_BLOCK_OPTIONAL_MODULES: Final[tuple[str, ...]] = (
    "analysis",
    "docs",
    "tests",
)

CELL_BLOCK_EXCLUDED_MODULES: Final[tuple[str, ...]] = (
    "dynamic",
)

CELL_BLOCK_REQUIRED_DOCUMENTS: Final[tuple[tuple[str, str], ...]] = (
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
    ("manufacturer", "manufacturer/contract.json"),
)

CELL_BLOCK_OPTIONAL_DOCUMENTS: Final[tuple[tuple[str, str], ...]] = (
    ("editor", "editor/targeting.json"),
    ("editor", "editor/anchors.json"),
    ("render", "render/bounds.json"),
    ("render", "render/materials.json"),
    ("physical", "physical/layers.json"),
    ("physical", "physical/occupancy.json"),
    ("physical", "physical/mass.json"),
    ("physical", "physical/footprint.json"),
    ("material", "material/base.json"),
    ("material", "material/performance.json"),
    ("calculation", "calculation/variables.json"),
    ("calculation", "calculation/formulas.json"),
    ("calculation", "calculation/quantities.json"),
    ("calculation", "calculation/measure_logic.json"),
    ("calculation", "calculation/constraints.json"),
    ("manufacturer", "manufacturer/override_slots.json"),
)

CELL_BLOCK_ALLOWED_PLACEMENT_MODES: Final[tuple[str, ...]] = (
    "fill_block",
    "centered",
    "bottom_aligned",
    "top_aligned",
)

CELL_BLOCK_RECOMMENDED_PLACEMENT_MODE: Final[str] = "fill_block"

CELL_BLOCK_DEFAULT_GRID_SIZE_CELLS: Final[tuple[int, int, int]] = (1, 1, 1)

CELL_BLOCK_ALLOWED_ASSET_EXTENSIONS: Final[tuple[str, ...]] = (
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

CELL_BLOCK_DEFAULT_MAX_MODEL_SIZE_MB: Final[float] = 25.0
CELL_BLOCK_DEFAULT_MAX_TEXTURE_SIZE_MB: Final[float] = 15.0
CELL_BLOCK_DEFAULT_MAX_PREVIEW_SIZE_MB: Final[float] = 5.0


def build_cell_block_profile(
    *,
    metadata: Mapping[str, Any] | None = None,
) -> ObjectKindProfile:
    """
    Baut das kanonische cell_block-Profil.

    Dieses Profil ist bewusst strenger als das generische Basisprofil:
    - render ist required
    - physical ist required
    - dynamic ist ausgeschlossen
    - calculation/material sind empfohlen
    - GLB/Textur/Farbe sind erlaubt
    - sichtbare Bounds müssen in den Grid-Footprint passen
    """
    try:
        extra_module_rules = (
            *cell_block_required_module_rules(),
            *cell_block_recommended_module_rules(),
            *cell_block_optional_module_rules(),
            *cell_block_excluded_module_rules(),
        )

        extra_document_rules = (
            *cell_block_required_document_rules(),
            *cell_block_optional_document_rules(),
        )

        extra_asset_rules = cell_block_asset_rules()
        extra_validation_rules = cell_block_validation_rules()

        profile = build_base_profile(
            profile_key=CELL_BLOCK_PROFILE_KEY,
            object_kind=CELL_BLOCK_OBJECT_KIND,
            title="Cell Block Profile",
            description=(
                "Profile for raster-based VPLIB components that usually occupy "
                "one grid cell and can represent walls, slabs, floors, road blocks "
                "or similar block-like building elements."
            ),
            defaults=ProfileDefaults(
                schema_version=CELL_BLOCK_PROFILE_SCHEMA_VERSION,
                variant_mode="single",
                default_variant_id="default",
                placement_mode=CELL_BLOCK_RECOMMENDED_PLACEMENT_MODE,
                fit_mode="fill_footprint",
                fallback_color="#9CA3AF",
                cell_size_m=1.0,
                grid_size_cells=CELL_BLOCK_DEFAULT_GRID_SIZE_CELLS,
                manufacturer_allowed=False,
                manufacturer_overlay_level="none",
            ),
            extra_module_rules=extra_module_rules,
            extra_document_rules=extra_document_rules,
            extra_asset_rules=extra_asset_rules,
            extra_validation_rules=extra_validation_rules,
            validation_mode=ProfileValidationMode.STRICT.value,
            metadata={
                "profile_schema_version": CELL_BLOCK_PROFILE_SCHEMA_VERSION,
                "allowed_placement_modes": list(CELL_BLOCK_ALLOWED_PLACEMENT_MODES),
                "recommended_placement_mode": CELL_BLOCK_RECOMMENDED_PLACEMENT_MODE,
                "default_grid_size_cells": list(CELL_BLOCK_DEFAULT_GRID_SIZE_CELLS),
                **dict(metadata or {}),
            },
        ).normalized()

        return profile
    except ProfileError:
        raise
    except Exception as exc:
        raise ProfileError(f"Could not build cell_block profile: {exc}") from exc


def cell_block_required_module_rules() -> tuple[ProfileModuleRule, ...]:
    """Erzeugt cell_block-required Modulregeln."""
    return tuple(
        ProfileModuleRule(
            module_name=module_name,
            requirement=ProfileModuleRequirement.REQUIRED.value,
            active_by_default=True,
            reason="Required for cell_block packages.",
        ).normalized()
        for module_name in CELL_BLOCK_REQUIRED_MODULES
    )


def cell_block_recommended_module_rules() -> tuple[ProfileModuleRule, ...]:
    """Erzeugt cell_block-recommended Modulregeln."""
    return tuple(
        ProfileModuleRule(
            module_name=module_name,
            requirement=ProfileModuleRequirement.RECOMMENDED.value,
            active_by_default=True,
            reason="Recommended for technically useful cell_block packages.",
        ).normalized()
        for module_name in CELL_BLOCK_RECOMMENDED_MODULES
    )


def cell_block_optional_module_rules() -> tuple[ProfileModuleRule, ...]:
    """Erzeugt cell_block-optionale Modulregeln."""
    return tuple(
        ProfileModuleRule(
            module_name=module_name,
            requirement=ProfileModuleRequirement.OPTIONAL.value,
            active_by_default=False,
            reason="Optional for cell_block packages.",
        ).normalized()
        for module_name in CELL_BLOCK_OPTIONAL_MODULES
    )


def cell_block_excluded_module_rules() -> tuple[ProfileModuleRule, ...]:
    """Erzeugt cell_block-ausgeschlossene Modulregeln."""
    return tuple(
        ProfileModuleRule(
            module_name=module_name,
            requirement=ProfileModuleRequirement.EXCLUDED.value,
            active_by_default=False,
            reason="cell_block packages must not use adaptive dynamic modules.",
        ).normalized()
        for module_name in CELL_BLOCK_EXCLUDED_MODULES
    )


def cell_block_required_document_rules() -> tuple[ProfileDocumentRule, ...]:
    """Erzeugt required document rules für cell_block."""
    return tuple(
        ProfileDocumentRule(
            module_name=module_name,
            path=path,
            required=True,
            generated=True,
            allow_empty_initially=False,
            reason="Required cell_block document.",
        ).normalized()
        for module_name, path in CELL_BLOCK_REQUIRED_DOCUMENTS
    )


def cell_block_optional_document_rules() -> tuple[ProfileDocumentRule, ...]:
    """Erzeugt optional document rules für cell_block."""
    return tuple(
        ProfileDocumentRule(
            module_name=module_name,
            path=path,
            required=False,
            generated=True,
            allow_empty_initially=True,
            reason="Optional cell_block document.",
        ).normalized()
        for module_name, path in CELL_BLOCK_OPTIONAL_DOCUMENTS
    )


def cell_block_asset_rules() -> tuple[ProfileAssetRule, ...]:
    """
    Erzeugt Assetregeln für cell_block.

    Ein cell_block darf ohne Textur arbeiten, wenn fallback_color gesetzt ist.
    GLB ist erlaubt, aber nicht required. Wenn ein GLB verwendet wird, müssen
    Bounds vorhanden sein und innerhalb des Grid-Footprints liegen.
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
            max_size_mb=CELL_BLOCK_DEFAULT_MAX_PREVIEW_SIZE_MB,
            requires_bounds=False,
            must_fit_grid_footprint=False,
            reason="Previews are recommended for creative-library display.",
        ).normalized(),
        ProfileAssetRule(
            role="texture",
            policy=ProfileAssetPolicy.OPTIONAL.value,
            module_name="render",
            allowed_extensions=(".png", ".jpg", ".jpeg", ".webp", ".ktx2", ".basis"),
            max_size_mb=CELL_BLOCK_DEFAULT_MAX_TEXTURE_SIZE_MB,
            requires_bounds=False,
            must_fit_grid_footprint=False,
            reason="Textures are optional because fallback_color is allowed.",
        ).normalized(),
        ProfileAssetRule(
            role="material_texture",
            policy=ProfileAssetPolicy.OPTIONAL.value,
            module_name="render",
            allowed_extensions=(".png", ".jpg", ".jpeg", ".webp", ".ktx2", ".basis"),
            max_size_mb=CELL_BLOCK_DEFAULT_MAX_TEXTURE_SIZE_MB,
            requires_bounds=False,
            must_fit_grid_footprint=False,
            reason="Material textures are optional for richer rendering.",
        ).normalized(),
        ProfileAssetRule(
            role="glb_model",
            policy=ProfileAssetPolicy.OPTIONAL.value,
            module_name="render",
            allowed_extensions=(".glb",),
            max_size_mb=CELL_BLOCK_DEFAULT_MAX_MODEL_SIZE_MB,
            requires_bounds=True,
            must_fit_grid_footprint=True,
            reason="GLB models are optional, but must fit inside the occupied grid footprint.",
        ).normalized(),
        ProfileAssetRule(
            role="gltf_model",
            policy=ProfileAssetPolicy.OPTIONAL.value,
            module_name="render",
            allowed_extensions=(".gltf",),
            max_size_mb=CELL_BLOCK_DEFAULT_MAX_MODEL_SIZE_MB,
            requires_bounds=True,
            must_fit_grid_footprint=True,
            reason="glTF models are optional, but must fit inside the occupied grid footprint.",
        ).normalized(),
    )


def cell_block_validation_rules() -> tuple[ProfileValidationRule, ...]:
    """Erzeugt cell_block-spezifische Validierungsregeln."""
    return (
        ProfileValidationRule(
            rule_key="cell_block_grid_footprint_is_single_cell",
            scope=ProfileRuleScope.PHYSICAL.value,
            severity=ProfileRuleSeverity.WARNING.value,
            enabled=True,
            message=(
                "cell_block packages should use a 1x1x1 grid footprint. "
                "Use multi_cell_module for larger footprints."
            ),
            details={
                "recommended_grid_size_cells": list(CELL_BLOCK_DEFAULT_GRID_SIZE_CELLS),
            },
        ).normalized(),
        ProfileValidationRule(
            rule_key="cell_block_no_dynamic_module",
            scope=ProfileRuleScope.DYNAMIC.value,
            severity=ProfileRuleSeverity.ERROR.value,
            enabled=True,
            message="cell_block packages must not enable the dynamic module.",
        ).normalized(),
        ProfileValidationRule(
            rule_key="cell_block_visual_fits_grid_footprint",
            scope=ProfileRuleScope.RENDER.value,
            severity=ProfileRuleSeverity.ERROR.value,
            enabled=True,
            message="The visible model must not exceed the occupied grid footprint.",
        ).normalized(),
        ProfileValidationRule(
            rule_key="cell_block_visual_has_texture_or_color_or_model",
            scope=ProfileRuleScope.RENDER.value,
            severity=ProfileRuleSeverity.ERROR.value,
            enabled=True,
            message="A cell_block must define a texture, a model or a fallback_color.",
        ).normalized(),
        ProfileValidationRule(
            rule_key="cell_block_placement_mode_allowed",
            scope=ProfileRuleScope.PLACEMENT.value,
            severity=ProfileRuleSeverity.ERROR.value,
            enabled=True,
            message="The placement mode must be allowed for cell_block.",
            details={
                "allowed_placement_modes": list(CELL_BLOCK_ALLOWED_PLACEMENT_MODES),
            },
        ).normalized(),
        ProfileValidationRule(
            rule_key="cell_block_physical_dimensions_present",
            scope=ProfileRuleScope.PHYSICAL.value,
            severity=ProfileRuleSeverity.WARNING.value,
            enabled=True,
            message=(
                "Physical dimensions are recommended for cell_block packages, "
                "especially for walls, slabs and technical building components."
            ),
        ).normalized(),
        ProfileValidationRule(
            rule_key="cell_block_variant_overrides_limited",
            scope=ProfileRuleScope.VARIANT.value,
            severity=ProfileRuleSeverity.ERROR.value,
            enabled=True,
            message="Variants must only define allowed overrides, not duplicate the full family.",
        ).normalized(),
        ProfileValidationRule(
            rule_key="cell_block_calculation_declarative_only",
            scope=ProfileRuleScope.CALCULATION.value,
            severity=ProfileRuleSeverity.ERROR.value,
            enabled=True,
            message="Calculation data must be declarative and must not reference executable code.",
        ).normalized(),
    )


def get_cell_block_profile() -> ObjectKindProfile:
    """Gibt das kanonische cell_block-Profil zurück."""
    return build_cell_block_profile()


def cell_block_profile_to_dict() -> dict[str, Any]:
    """Serialisiert das cell_block-Profil JSON-kompatibel."""
    return get_cell_block_profile().to_dict()


def validate_cell_block_profile() -> tuple[bool, tuple[str, ...]]:
    """Validiert das cell_block-Profil selbst."""
    try:
        profile = get_cell_block_profile()
        return profile.validate()
    except Exception as exc:
        return False, (f"Invalid cell_block profile: {exc}",)


def assert_cell_block_profile_valid() -> None:
    """Wirft ProfileError, wenn das cell_block-Profil ungültig ist."""
    valid, messages = validate_cell_block_profile()

    if not valid:
        joined = " ".join(messages) if messages else "Invalid cell_block profile."
        raise ProfileError(joined)


__all__ = [
    "CELL_BLOCK_ALLOWED_ASSET_EXTENSIONS",
    "CELL_BLOCK_ALLOWED_PLACEMENT_MODES",
    "CELL_BLOCK_DEFAULT_GRID_SIZE_CELLS",
    "CELL_BLOCK_DEFAULT_MAX_MODEL_SIZE_MB",
    "CELL_BLOCK_DEFAULT_MAX_PREVIEW_SIZE_MB",
    "CELL_BLOCK_DEFAULT_MAX_TEXTURE_SIZE_MB",
    "CELL_BLOCK_EXCLUDED_MODULES",
    "CELL_BLOCK_OBJECT_KIND",
    "CELL_BLOCK_OPTIONAL_DOCUMENTS",
    "CELL_BLOCK_OPTIONAL_MODULES",
    "CELL_BLOCK_PROFILE_KEY",
    "CELL_BLOCK_PROFILE_SCHEMA_VERSION",
    "CELL_BLOCK_RECOMMENDED_MODULES",
    "CELL_BLOCK_RECOMMENDED_PLACEMENT_MODE",
    "CELL_BLOCK_REQUIRED_DOCUMENTS",
    "CELL_BLOCK_REQUIRED_MODULES",
    "assert_cell_block_profile_valid",
    "build_cell_block_profile",
    "cell_block_asset_rules",
    "cell_block_excluded_module_rules",
    "cell_block_optional_document_rules",
    "cell_block_optional_module_rules",
    "cell_block_profile_to_dict",
    "cell_block_recommended_module_rules",
    "cell_block_required_document_rules",
    "cell_block_required_module_rules",
    "cell_block_validation_rules",
    "get_cell_block_profile",
    "validate_cell_block_profile",
]