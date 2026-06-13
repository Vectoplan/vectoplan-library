# services/vectoplan-library/src/vplib/profiles/adaptive_system_profile.py
"""
Adaptive-system object-kind profile for the VPLIB package engine.

Diese Datei definiert das feste Profil für:

    object_kind = adaptive_system

Ein adaptive_system ist kein statisches Einzelobjekt. Es beschreibt ein Element,
dessen endgültige Form, Parameter oder Platzierung später aus Kontextdaten
abgeleitet werden.

Typische Fälle:
- bridge cap
- railing system
- edge beam
- pipe or routing system
- host-bound adaptive technical system

Wichtig:
Adaptive Systeme bleiben deklarativ. Sie dürfen keinen frei ausführbaren Code
im Package enthalten.

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


ADAPTIVE_SYSTEM_PROFILE_SCHEMA_VERSION: Final[str] = "vplib.profile.adaptive_system.v1"
ADAPTIVE_SYSTEM_PROFILE_KEY: Final[str] = "adaptive_system_profile"
ADAPTIVE_SYSTEM_OBJECT_KIND: Final[str] = "adaptive_system"

ADAPTIVE_SYSTEM_REQUIRED_MODULES: Final[tuple[str, ...]] = (
    "manifest",
    "modules",
    "family",
    "variants",
    "editor",
    "dynamic",
    "manufacturer",
)

ADAPTIVE_SYSTEM_RECOMMENDED_MODULES: Final[tuple[str, ...]] = (
    "render",
    "physical",
    "material",
    "calculation",
)

ADAPTIVE_SYSTEM_OPTIONAL_MODULES: Final[tuple[str, ...]] = (
    "analysis",
    "docs",
    "tests",
)

ADAPTIVE_SYSTEM_EXCLUDED_MODULES: Final[tuple[str, ...]] = tuple()

ADAPTIVE_SYSTEM_REQUIRED_DOCUMENTS: Final[tuple[tuple[str, str], ...]] = (
    ("family", "family/identity.json"),
    ("family", "family/classification.json"),
    ("variants", "variants/index.json"),
    ("variants", "variants/default.json"),
    ("editor", "editor/inventory.json"),
    ("editor", "editor/placement.json"),
    ("dynamic", "dynamic/context_rules.json"),
    ("dynamic", "dynamic/bindings.json"),
    ("dynamic", "dynamic/generator.json"),
    ("manufacturer", "manufacturer/contract.json"),
)

ADAPTIVE_SYSTEM_OPTIONAL_DOCUMENTS: Final[tuple[tuple[str, str], ...]] = (
    ("editor", "editor/targeting.json"),
    ("editor", "editor/anchors.json"),
    ("editor", "editor/sockets.json"),
    ("editor", "editor/ports.json"),
    ("render", "render/render_variants.json"),
    ("render", "render/bounds.json"),
    ("render", "render/materials.json"),
    ("render", "render/lod.json"),
    ("physical", "physical/base.json"),
    ("physical", "physical/dimensions.json"),
    ("physical", "physical/collision.json"),
    ("physical", "physical/occupancy.json"),
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
    ("analysis", "analysis/reinforcement/profile.json"),
    ("dynamic", "dynamic/parameters.json"),
    ("dynamic", "dynamic/constraints.json"),
    ("manufacturer", "manufacturer/override_slots.json"),
)

ADAPTIVE_SYSTEM_ALLOWED_PLACEMENT_MODES: Final[tuple[str, ...]] = (
    "surface_aligned",
    "centered",
)

ADAPTIVE_SYSTEM_RECOMMENDED_PLACEMENT_MODE: Final[str] = "surface_aligned"

ADAPTIVE_SYSTEM_DEFAULT_GRID_SIZE_CELLS: Final[tuple[int, int, int]] = (1, 1, 1)

ADAPTIVE_SYSTEM_ALLOWED_ASSET_EXTENSIONS: Final[tuple[str, ...]] = (
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

ADAPTIVE_SYSTEM_DEFAULT_MAX_MODEL_SIZE_MB: Final[float] = 150.0
ADAPTIVE_SYSTEM_DEFAULT_MAX_TEXTURE_SIZE_MB: Final[float] = 50.0
ADAPTIVE_SYSTEM_DEFAULT_MAX_PREVIEW_SIZE_MB: Final[float] = 10.0


def build_adaptive_system_profile(
    *,
    metadata: Mapping[str, Any] | None = None,
) -> ObjectKindProfile:
    """
    Baut das kanonische adaptive_system-Profil.

    Dieses Profil unterscheidet sich bewusst von cell_block, multi_cell_module
    und catalog_object:
    - dynamic ist required
    - render ist recommended, aber ein Preview-Modell ist nicht die fachliche Wahrheit
    - physical ist recommended, kann aber kontextabhängig aufgelöst werden
    - calculation ist recommended, weil adaptive Systeme häufig Parameterlogik benötigen
    - keine ausführbaren Generatoren, nur deklarative Generator-Metadaten
    """
    try:
        extra_module_rules = (
            *adaptive_system_required_module_rules(),
            *adaptive_system_recommended_module_rules(),
            *adaptive_system_optional_module_rules(),
            *adaptive_system_excluded_module_rules(),
        )

        extra_document_rules = (
            *adaptive_system_required_document_rules(),
            *adaptive_system_optional_document_rules(),
        )

        extra_asset_rules = adaptive_system_asset_rules()
        extra_validation_rules = adaptive_system_validation_rules()

        profile = build_base_profile(
            profile_key=ADAPTIVE_SYSTEM_PROFILE_KEY,
            object_kind=ADAPTIVE_SYSTEM_OBJECT_KIND,
            title="Adaptive System Profile",
            description=(
                "Profile for VPLIB adaptive systems whose final geometry, placement "
                "or parameters are derived from declarative context rules, bindings "
                "and generator metadata."
            ),
            defaults=ProfileDefaults(
                schema_version=ADAPTIVE_SYSTEM_PROFILE_SCHEMA_VERSION,
                variant_mode="single",
                default_variant_id="default",
                placement_mode=ADAPTIVE_SYSTEM_RECOMMENDED_PLACEMENT_MODE,
                fit_mode="strict_inside",
                fallback_color="#64748B",
                cell_size_m=1.0,
                grid_size_cells=ADAPTIVE_SYSTEM_DEFAULT_GRID_SIZE_CELLS,
                manufacturer_allowed=False,
                manufacturer_overlay_level="none",
            ),
            extra_module_rules=extra_module_rules,
            extra_document_rules=extra_document_rules,
            extra_asset_rules=extra_asset_rules,
            extra_validation_rules=extra_validation_rules,
            validation_mode=ProfileValidationMode.STRICT.value,
            metadata={
                "profile_schema_version": ADAPTIVE_SYSTEM_PROFILE_SCHEMA_VERSION,
                "allowed_placement_modes": list(ADAPTIVE_SYSTEM_ALLOWED_PLACEMENT_MODES),
                "recommended_placement_mode": ADAPTIVE_SYSTEM_RECOMMENDED_PLACEMENT_MODE,
                "default_grid_size_cells": list(ADAPTIVE_SYSTEM_DEFAULT_GRID_SIZE_CELLS),
                "declarative_only": True,
                **dict(metadata or {}),
            },
        ).normalized()

        return profile
    except ProfileError:
        raise
    except Exception as exc:
        raise ProfileError(f"Could not build adaptive_system profile: {exc}") from exc


def adaptive_system_required_module_rules() -> tuple[ProfileModuleRule, ...]:
    """Erzeugt adaptive_system-required Modulregeln."""
    return tuple(
        ProfileModuleRule(
            module_name=module_name,
            requirement=ProfileModuleRequirement.REQUIRED.value,
            active_by_default=True,
            reason="Required for adaptive_system packages.",
        ).normalized()
        for module_name in ADAPTIVE_SYSTEM_REQUIRED_MODULES
    )


def adaptive_system_recommended_module_rules() -> tuple[ProfileModuleRule, ...]:
    """Erzeugt adaptive_system-recommended Modulregeln."""
    return tuple(
        ProfileModuleRule(
            module_name=module_name,
            requirement=ProfileModuleRequirement.RECOMMENDED.value,
            active_by_default=True,
            reason="Recommended for useful adaptive_system packages.",
        ).normalized()
        for module_name in ADAPTIVE_SYSTEM_RECOMMENDED_MODULES
    )


def adaptive_system_optional_module_rules() -> tuple[ProfileModuleRule, ...]:
    """Erzeugt adaptive_system-optionale Modulregeln."""
    return tuple(
        ProfileModuleRule(
            module_name=module_name,
            requirement=ProfileModuleRequirement.OPTIONAL.value,
            active_by_default=False,
            reason="Optional for adaptive_system packages.",
        ).normalized()
        for module_name in ADAPTIVE_SYSTEM_OPTIONAL_MODULES
    )


def adaptive_system_excluded_module_rules() -> tuple[ProfileModuleRule, ...]:
    """Erzeugt adaptive_system-ausgeschlossene Modulregeln."""
    return tuple(
        ProfileModuleRule(
            module_name=module_name,
            requirement=ProfileModuleRequirement.EXCLUDED.value,
            active_by_default=False,
            reason="Excluded for adaptive_system packages.",
        ).normalized()
        for module_name in ADAPTIVE_SYSTEM_EXCLUDED_MODULES
    )


def adaptive_system_required_document_rules() -> tuple[ProfileDocumentRule, ...]:
    """Erzeugt required document rules für adaptive_system."""
    return tuple(
        ProfileDocumentRule(
            module_name=module_name,
            path=path,
            required=True,
            generated=True,
            allow_empty_initially=False,
            reason="Required adaptive_system document.",
        ).normalized()
        for module_name, path in ADAPTIVE_SYSTEM_REQUIRED_DOCUMENTS
    )


def adaptive_system_optional_document_rules() -> tuple[ProfileDocumentRule, ...]:
    """Erzeugt optional document rules für adaptive_system."""
    return tuple(
        ProfileDocumentRule(
            module_name=module_name,
            path=path,
            required=False,
            generated=True,
            allow_empty_initially=True,
            reason="Optional adaptive_system document.",
        ).normalized()
        for module_name, path in ADAPTIVE_SYSTEM_OPTIONAL_DOCUMENTS
    )


def adaptive_system_asset_rules() -> tuple[ProfileAssetRule, ...]:
    """
    Erzeugt Assetregeln für adaptive_system.

    Ein statisches GLB ist hier nur Preview oder Prototyp, nicht die fachliche
    Wahrheit. Die adaptive Wahrheit liegt in dynamic/*.json.
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
            max_size_mb=ADAPTIVE_SYSTEM_DEFAULT_MAX_PREVIEW_SIZE_MB,
            requires_bounds=False,
            must_fit_grid_footprint=False,
            reason="Previews are recommended for adaptive system display.",
        ).normalized(),
        ProfileAssetRule(
            role="texture",
            policy=ProfileAssetPolicy.OPTIONAL.value,
            module_name="render",
            allowed_extensions=(".png", ".jpg", ".jpeg", ".webp", ".ktx2", ".basis"),
            max_size_mb=ADAPTIVE_SYSTEM_DEFAULT_MAX_TEXTURE_SIZE_MB,
            requires_bounds=False,
            must_fit_grid_footprint=False,
            reason="Textures are optional for adaptive systems.",
        ).normalized(),
        ProfileAssetRule(
            role="material_texture",
            policy=ProfileAssetPolicy.OPTIONAL.value,
            module_name="render",
            allowed_extensions=(".png", ".jpg", ".jpeg", ".webp", ".ktx2", ".basis"),
            max_size_mb=ADAPTIVE_SYSTEM_DEFAULT_MAX_TEXTURE_SIZE_MB,
            requires_bounds=False,
            must_fit_grid_footprint=False,
            reason="Material textures are optional for richer rendering.",
        ).normalized(),
        ProfileAssetRule(
            role="glb_model",
            policy=ProfileAssetPolicy.OPTIONAL.value,
            module_name="render",
            allowed_extensions=(".glb",),
            max_size_mb=ADAPTIVE_SYSTEM_DEFAULT_MAX_MODEL_SIZE_MB,
            requires_bounds=True,
            must_fit_grid_footprint=True,
            reason=(
                "GLB models are optional previews/prototypes for adaptive systems. "
                "They must not replace declarative dynamic rules."
            ),
        ).normalized(),
        ProfileAssetRule(
            role="gltf_model",
            policy=ProfileAssetPolicy.OPTIONAL.value,
            module_name="render",
            allowed_extensions=(".gltf",),
            max_size_mb=ADAPTIVE_SYSTEM_DEFAULT_MAX_MODEL_SIZE_MB,
            requires_bounds=True,
            must_fit_grid_footprint=True,
            reason=(
                "glTF models are optional previews/prototypes for adaptive systems. "
                "They must not replace declarative dynamic rules."
            ),
        ).normalized(),
    )


def adaptive_system_validation_rules() -> tuple[ProfileValidationRule, ...]:
    """Erzeugt adaptive_system-spezifische Validierungsregeln."""
    return (
        ProfileValidationRule(
            rule_key="adaptive_system_dynamic_module_required",
            scope=ProfileRuleScope.DYNAMIC.value,
            severity=ProfileRuleSeverity.FATAL.value,
            enabled=True,
            message="adaptive_system packages must enable the dynamic module.",
        ).normalized(),
        ProfileValidationRule(
            rule_key="adaptive_system_context_rules_required",
            scope=ProfileRuleScope.DYNAMIC.value,
            severity=ProfileRuleSeverity.ERROR.value,
            enabled=True,
            message="dynamic/context_rules.json is required for adaptive_system packages.",
        ).normalized(),
        ProfileValidationRule(
            rule_key="adaptive_system_bindings_required",
            scope=ProfileRuleScope.DYNAMIC.value,
            severity=ProfileRuleSeverity.ERROR.value,
            enabled=True,
            message="dynamic/bindings.json is required for adaptive_system packages.",
        ).normalized(),
        ProfileValidationRule(
            rule_key="adaptive_system_generator_required",
            scope=ProfileRuleScope.DYNAMIC.value,
            severity=ProfileRuleSeverity.ERROR.value,
            enabled=True,
            message="dynamic/generator.json is required for adaptive_system packages.",
        ).normalized(),
        ProfileValidationRule(
            rule_key="adaptive_system_generator_declarative_only",
            scope=ProfileRuleScope.DYNAMIC.value,
            severity=ProfileRuleSeverity.FATAL.value,
            enabled=True,
            message=(
                "Adaptive generator metadata must be declarative and must not "
                "reference executable code."
            ),
        ).normalized(),
        ProfileValidationRule(
            rule_key="adaptive_system_no_executable_files",
            scope=ProfileRuleScope.PROFILE.value,
            severity=ProfileRuleSeverity.FATAL.value,
            enabled=True,
            message="Executable files are forbidden inside adaptive_system packages.",
        ).normalized(),
        ProfileValidationRule(
            rule_key="adaptive_system_static_model_is_preview_only",
            scope=ProfileRuleScope.RENDER.value,
            severity=ProfileRuleSeverity.WARNING.value,
            enabled=True,
            message=(
                "Static render assets for adaptive_system packages are previews "
                "or prototypes, not the semantic source of truth."
            ),
        ).normalized(),
        ProfileValidationRule(
            rule_key="adaptive_system_placement_mode_allowed",
            scope=ProfileRuleScope.PLACEMENT.value,
            severity=ProfileRuleSeverity.ERROR.value,
            enabled=True,
            message="The placement mode must be allowed for adaptive_system.",
            details={
                "allowed_placement_modes": list(ADAPTIVE_SYSTEM_ALLOWED_PLACEMENT_MODES),
            },
        ).normalized(),
        ProfileValidationRule(
            rule_key="adaptive_system_surface_alignment_recommended",
            scope=ProfileRuleScope.PLACEMENT.value,
            severity=ProfileRuleSeverity.WARNING.value,
            enabled=True,
            message=(
                "surface_aligned placement is recommended for adaptive systems "
                "because they are usually host- or context-bound."
            ),
        ).normalized(),
        ProfileValidationRule(
            rule_key="adaptive_system_context_bindings_consistent",
            scope=ProfileRuleScope.DYNAMIC.value,
            severity=ProfileRuleSeverity.ERROR.value,
            enabled=True,
            message="Dynamic context rules, bindings and generator parameters must be consistent.",
        ).normalized(),
        ProfileValidationRule(
            rule_key="adaptive_system_variant_overrides_limited",
            scope=ProfileRuleScope.VARIANT.value,
            severity=ProfileRuleSeverity.ERROR.value,
            enabled=True,
            message="Variants must only define allowed overrides, not duplicate the full family.",
        ).normalized(),
    )


def get_adaptive_system_profile() -> ObjectKindProfile:
    """Gibt das kanonische adaptive_system-Profil zurück."""
    return build_adaptive_system_profile()


def adaptive_system_profile_to_dict() -> dict[str, Any]:
    """Serialisiert das adaptive_system-Profil JSON-kompatibel."""
    return get_adaptive_system_profile().to_dict()


def validate_adaptive_system_profile() -> tuple[bool, tuple[str, ...]]:
    """Validiert das adaptive_system-Profil selbst."""
    try:
        profile = get_adaptive_system_profile()
        return profile.validate()
    except Exception as exc:
        return False, (f"Invalid adaptive_system profile: {exc}",)


def assert_adaptive_system_profile_valid() -> None:
    """Wirft ProfileError, wenn das adaptive_system-Profil ungültig ist."""
    valid, messages = validate_adaptive_system_profile()

    if not valid:
        joined = " ".join(messages) if messages else "Invalid adaptive_system profile."
        raise ProfileError(joined)


__all__ = [
    "ADAPTIVE_SYSTEM_ALLOWED_ASSET_EXTENSIONS",
    "ADAPTIVE_SYSTEM_ALLOWED_PLACEMENT_MODES",
    "ADAPTIVE_SYSTEM_DEFAULT_GRID_SIZE_CELLS",
    "ADAPTIVE_SYSTEM_DEFAULT_MAX_MODEL_SIZE_MB",
    "ADAPTIVE_SYSTEM_DEFAULT_MAX_PREVIEW_SIZE_MB",
    "ADAPTIVE_SYSTEM_DEFAULT_MAX_TEXTURE_SIZE_MB",
    "ADAPTIVE_SYSTEM_EXCLUDED_MODULES",
    "ADAPTIVE_SYSTEM_OBJECT_KIND",
    "ADAPTIVE_SYSTEM_OPTIONAL_DOCUMENTS",
    "ADAPTIVE_SYSTEM_OPTIONAL_MODULES",
    "ADAPTIVE_SYSTEM_PROFILE_KEY",
    "ADAPTIVE_SYSTEM_PROFILE_SCHEMA_VERSION",
    "ADAPTIVE_SYSTEM_RECOMMENDED_MODULES",
    "ADAPTIVE_SYSTEM_RECOMMENDED_PLACEMENT_MODE",
    "ADAPTIVE_SYSTEM_REQUIRED_DOCUMENTS",
    "ADAPTIVE_SYSTEM_REQUIRED_MODULES",
    "adaptive_system_asset_rules",
    "adaptive_system_excluded_module_rules",
    "adaptive_system_optional_document_rules",
    "adaptive_system_optional_module_rules",
    "adaptive_system_profile_to_dict",
    "adaptive_system_recommended_module_rules",
    "adaptive_system_required_document_rules",
    "adaptive_system_required_module_rules",
    "adaptive_system_validation_rules",
    "assert_adaptive_system_profile_valid",
    "build_adaptive_system_profile",
    "get_adaptive_system_profile",
    "validate_adaptive_system_profile",
]