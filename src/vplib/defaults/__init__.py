# services/vectoplan-library/src/vplib/defaults/__init__.py
"""
Public defaults API for the VPLIB package engine.

Diese Datei bündelt die stabilen Defaults-Bausteine für VPLIB:

- manifest_defaults
- module_defaults
- family_defaults
- variant_defaults
- editor_defaults
- render_defaults
- physical_defaults
- material_defaults
- calculation_defaults
- manufacturer_defaults
- analysis_defaults
- dynamic_defaults
- document_bundle

Die Defaults-Schicht schreibt keine Dateien. Sie erzeugt nur JSON-kompatible
Dokument-Payloads und DocumentBundle-Strukturen, die später von creators/*
ausgeführt und gespeichert werden.

Wichtig für die neue VPLIB-ID-Architektur:
- manifest_defaults erzeugt und validiert jetzt `vplib_uid`.
- `vplib_uid` entsteht beim Erstellen des .vplib-Packages.
- Die Datenbank übernimmt diese ID später nur.
- Diese Datei exportiert die Manifest-ID-Helfer lazy, damit Create-, Scanner-,
  Validator- und Creator-Code sie stabil über `vplib.defaults` nutzen können.

Sie ist bewusst robust aufgebaut:
- Imports laufen lazy über __getattr__.
- Einzelne beschädigte Defaults-Module blockieren nicht sofort das ganze Package.
- Diagnosefunktionen zeigen Importstatus und Fehler.
- Cache-Clear-Funktionen können alle Defaults-Caches gesammelt leeren.
- Modul-Aliase wie `manifest` oder `bundle` sind nur Komfortzugriffe und
  ändern keine bestehende API.

Technische Namen, JSON-Keys und Variablen bleiben Englisch.
"""

from __future__ import annotations

import importlib
from dataclasses import dataclass
from functools import lru_cache
from types import ModuleType
from typing import Any, Final, Mapping


DEFAULTS_PACKAGE_VERSION: Final[str] = "vplib.defaults.v1"


class DefaultsImportError(ImportError):
    """Wird ausgelöst, wenn ein Defaults-Modul oder Defaults-Symbol nicht geladen werden kann."""


@dataclass(frozen=True, slots=True)
class DefaultsModuleStatus:
    """Importstatus eines Defaults-Moduls."""

    module_key: str
    module_path: str
    loaded: bool
    error: str | None
    exported_symbols: tuple[str, ...]

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema_version": DEFAULTS_PACKAGE_VERSION,
            "module_key": self.module_key,
            "module_path": self.module_path,
            "loaded": self.loaded,
            "error": self.error,
            "exported_symbols": list(self.exported_symbols),
            "exported_symbol_count": len(self.exported_symbols),
        }


_RELATIVE_DEFAULT_MODULES: Final[dict[str, str]] = {
    "manifest_defaults": ".manifest_defaults",
    "module_defaults": ".module_defaults",
    "family_defaults": ".family_defaults",
    "variant_defaults": ".variant_defaults",
    "editor_defaults": ".editor_defaults",
    "render_defaults": ".render_defaults",
    "physical_defaults": ".physical_defaults",
    "material_defaults": ".material_defaults",
    "calculation_defaults": ".calculation_defaults",
    "manufacturer_defaults": ".manufacturer_defaults",
    "analysis_defaults": ".analysis_defaults",
    "dynamic_defaults": ".dynamic_defaults",
    "document_bundle": ".document_bundle",
}


_RELATIVE_DEFAULT_MODULE_ALIASES: Final[dict[str, str]] = {
    "manifest": "manifest_defaults",
    "modules": "module_defaults",
    "family": "family_defaults",
    "variants": "variant_defaults",
    "editor": "editor_defaults",
    "render": "render_defaults",
    "physical": "physical_defaults",
    "material": "material_defaults",
    "calculation": "calculation_defaults",
    "manufacturer": "manufacturer_defaults",
    "analysis": "analysis_defaults",
    "dynamic": "dynamic_defaults",
    "bundle": "document_bundle",
}


_SYMBOL_TO_MODULE: Final[dict[str, str]] = {
    # ---------------------------------------------------------------------
    # manifest_defaults.py
    # ---------------------------------------------------------------------
    "DEFAULT_GENERATOR_NAME": "manifest_defaults",
    "DEFAULT_GENERATOR_VERSION": "manifest_defaults",
    "DEFAULT_PACKAGE_VERSION": "manifest_defaults",
    "DEFAULT_VPLIB_VERSION": "manifest_defaults",
    "MANIFEST_DEFAULTS_SCHEMA_VERSION": "manifest_defaults",
    "MANIFEST_DOCUMENT_SCHEMA_VERSION": "manifest_defaults",
    "MANIFEST_VPLIB_UID_FIELD": "manifest_defaults",
    "SAFE_MANIFEST_ID_RE": "manifest_defaults",
    "ManifestClassification": "manifest_defaults",
    "ManifestDefaults": "manifest_defaults",
    "ManifestDefaultsError": "manifest_defaults",
    "ManifestIdentity": "manifest_defaults",
    "ManifestLifecycleStatus": "manifest_defaults",
    "ManifestSource": "manifest_defaults",
    "ManifestSourceKind": "manifest_defaults",
    "ManifestTimestamps": "manifest_defaults",
    "assert_valid_manifest_document": "manifest_defaults",
    "build_manifest_defaults": "manifest_defaults",
    "build_manifest_document": "manifest_defaults",
    "clear_manifest_defaults_caches": "manifest_defaults",
    "clean_optional_string": "manifest_defaults",
    "clean_required_string": "manifest_defaults",
    "ensure_manifest_document_vplib_uid": "manifest_defaults",
    "extract_raw_vplib_uid_from_any": "manifest_defaults",
    "manifest_defaults_from_context": "manifest_defaults",
    "manifest_defaults_from_create_request": "manifest_defaults",
    "manifest_defaults_from_creation_plan": "manifest_defaults",
    "manifest_document_from_context": "manifest_defaults",
    "manifest_document_from_create_request": "manifest_defaults",
    "manifest_document_from_creation_plan": "manifest_defaults",
    "manifest_document_with_vplib_uid": "manifest_defaults",
    "normalize_create_request": "manifest_defaults",
    "normalize_enum_key": "manifest_defaults",
    "normalize_manifest_id": "manifest_defaults",
    "normalize_manifest_vplib_uid": "manifest_defaults",
    "normalize_metadata": "manifest_defaults",
    "normalize_metadata_value": "manifest_defaults",
    "normalize_object_kind_value": "manifest_defaults",
    "normalize_or_generate_manifest_vplib_uid": "manifest_defaults",
    "normalize_required_manifest_vplib_uid": "manifest_defaults",
    "normalize_slug": "manifest_defaults",
    "parse_lifecycle_status_value": "manifest_defaults",
    "parse_source_kind_value": "manifest_defaults",
    "utc_now_iso": "manifest_defaults",
    "validate_manifest_document": "manifest_defaults",

    # ---------------------------------------------------------------------
    # module_defaults.py
    # ---------------------------------------------------------------------
    "MODULE_DEFAULTS_SCHEMA_VERSION": "module_defaults",
    "MODULE_DOCUMENT_SCHEMA_VERSION": "module_defaults",
    "ModuleDefaults": "module_defaults",
    "ModuleDefaultsError": "module_defaults",
    "ModuleDocumentDefaults": "module_defaults",
    "ModuleSetKind": "module_defaults",
    "ModuleValidationMode": "module_defaults",
    "ModuleVersionDefaults": "module_defaults",
    "assert_valid_module_defaults": "module_defaults",
    "assert_valid_modules_document": "module_defaults",
    "build_module_defaults": "module_defaults",
    "build_modules_document": "module_defaults",
    "clear_module_defaults_caches": "module_defaults",
    "module_defaults_from_module_plan": "module_defaults",
    "module_defaults_from_profile": "module_defaults",
    "module_document_defaults_for_module": "module_defaults",
    "modules_document_from_module_plan": "module_defaults",
    "modules_document_from_profile": "module_defaults",
    "validate_module_defaults": "module_defaults",
    "validate_modules_document": "module_defaults",

    # ---------------------------------------------------------------------
    # family_defaults.py
    # ---------------------------------------------------------------------
    "FAMILY_DEFAULTS_SCHEMA_VERSION": "family_defaults",
    "FAMILY_IDENTITY_DOCUMENT_SCHEMA_VERSION": "family_defaults",
    "FAMILY_CLASSIFICATION_DOCUMENT_SCHEMA_VERSION": "family_defaults",
    "FamilyAliasesDefaults": "family_defaults",
    "FamilyClassificationDefaults": "family_defaults",
    "FamilyDefaults": "family_defaults",
    "FamilyDefaultsError": "family_defaults",
    "FamilyIdentityDefaults": "family_defaults",
    "FamilyLifecycleDefaults": "family_defaults",
    "FamilyLifecycleStatus": "family_defaults",
    "FamilyMetadataDefaults": "family_defaults",
    "FamilySourceKind": "family_defaults",
    "assert_valid_family_classification_document": "family_defaults",
    "assert_valid_family_identity_document": "family_defaults",
    "build_family_defaults": "family_defaults",
    "clear_family_defaults_caches": "family_defaults",
    "family_classification_document_from_create_request": "family_defaults",
    "family_defaults_from_context": "family_defaults",
    "family_defaults_from_create_request": "family_defaults",
    "family_defaults_from_creation_plan": "family_defaults",
    "family_documents_from_create_request": "family_defaults",
    "family_identity_document_from_create_request": "family_defaults",
    "validate_family_classification_document": "family_defaults",
    "validate_family_identity_document": "family_defaults",

    # ---------------------------------------------------------------------
    # variant_defaults.py
    # ---------------------------------------------------------------------
    "VARIANT_DEFAULTS_SCHEMA_VERSION": "variant_defaults",
    "VARIANT_DOCUMENT_SCHEMA_VERSION": "variant_defaults",
    "VARIANT_INDEX_DOCUMENT_SCHEMA_VERSION": "variant_defaults",
    "VariantDefaults": "variant_defaults",
    "VariantDefaultsError": "variant_defaults",
    "VariantDocumentDefaults": "variant_defaults",
    "VariantIndexDefaults": "variant_defaults",
    "VariantMode": "variant_defaults",
    "VariantSourceKind": "variant_defaults",
    "VariantStatus": "variant_defaults",
    "assert_valid_variant_document": "variant_defaults",
    "assert_valid_variant_index_document": "variant_defaults",
    "build_default_variant_document": "variant_defaults",
    "build_variant_defaults": "variant_defaults",
    "clear_variant_defaults_caches": "variant_defaults",
    "validate_variant_document": "variant_defaults",
    "validate_variant_index_document": "variant_defaults",
    "variant_defaults_from_create_request": "variant_defaults",
    "variant_defaults_from_planning_result": "variant_defaults",
    "variant_defaults_from_variant_set": "variant_defaults",
    "variant_document_defaults_from_mapping": "variant_defaults",
    "variant_documents_from_create_request": "variant_defaults",
    "variant_documents_from_variant_set": "variant_defaults",
    "variants_index_document_from_create_request": "variant_defaults",

    # ---------------------------------------------------------------------
    # editor_defaults.py
    # ---------------------------------------------------------------------
    "EDITOR_DEFAULTS_SCHEMA_VERSION": "editor_defaults",
    "EditorAnchorDefaults": "editor_defaults",
    "EditorAnchorsDefaults": "editor_defaults",
    "EditorDefaults": "editor_defaults",
    "EditorDefaultsError": "editor_defaults",
    "EditorHost": "editor_defaults",
    "EditorHotbarDefaults": "editor_defaults",
    "EditorInventoryDefaults": "editor_defaults",
    "EditorPlacementDefaults": "editor_defaults",
    "EditorPortDefaults": "editor_defaults",
    "EditorPortsDefaults": "editor_defaults",
    "EditorSocketDefaults": "editor_defaults",
    "EditorSocketsDefaults": "editor_defaults",
    "EditorSurface": "editor_defaults",
    "EditorTargetingDefaults": "editor_defaults",
    "EditorTool": "editor_defaults",
    "EditorToolsDefaults": "editor_defaults",
    "GridFootprintDefaults": "editor_defaults",
    "InventoryVisibility": "editor_defaults",
    "PortKind": "editor_defaults",
    "SnapMode": "editor_defaults",
    "SocketKind": "editor_defaults",
    "TargetingMode": "editor_defaults",
    "assert_valid_inventory_document": "editor_defaults",
    "assert_valid_placement_document": "editor_defaults",
    "build_editor_defaults": "editor_defaults",
    "clear_editor_defaults_caches": "editor_defaults",
    "editor_defaults_from_context": "editor_defaults",
    "editor_defaults_from_create_request": "editor_defaults",
    "editor_defaults_from_creation_plan": "editor_defaults",
    "editor_documents_from_context": "editor_defaults",
    "editor_documents_from_create_request": "editor_defaults",
    "editor_documents_from_creation_plan": "editor_defaults",
    "validate_inventory_document": "editor_defaults",
    "validate_placement_document": "editor_defaults",

    # ---------------------------------------------------------------------
    # render_defaults.py
    # ---------------------------------------------------------------------
    "RENDER_DEFAULTS_SCHEMA_VERSION": "render_defaults",
    "LodLevelDefaults": "render_defaults",
    "LodStrategy": "render_defaults",
    "RenderAlignment": "render_defaults",
    "RenderAssetRefDefaults": "render_defaults",
    "RenderAssetRole": "render_defaults",
    "RenderBoundsDefaults": "render_defaults",
    "RenderDefaults": "render_defaults",
    "RenderDefaultsError": "render_defaults",
    "RenderFitMode": "render_defaults",
    "RenderLodDefaults": "render_defaults",
    "RenderMaterialDefaults": "render_defaults",
    "RenderMaterialKind": "render_defaults",
    "RenderMaterialsDefaults": "render_defaults",
    "RenderShape": "render_defaults",
    "RenderVariantDefaults": "render_defaults",
    "RenderVariantsDefaults": "render_defaults",
    "TextureFilterMode": "render_defaults",
    "TextureWrapMode": "render_defaults",
    "Vector3Defaults": "render_defaults",
    "assert_valid_render_bounds_document": "render_defaults",
    "assert_valid_render_variants_document": "render_defaults",
    "build_render_defaults": "render_defaults",
    "clear_render_defaults_caches": "render_defaults",
    "render_defaults_from_context": "render_defaults",
    "render_defaults_from_create_request": "render_defaults",
    "render_defaults_from_creation_plan": "render_defaults",
    "render_documents_from_context": "render_defaults",
    "render_documents_from_create_request": "render_defaults",
    "render_documents_from_creation_plan": "render_defaults",
    "render_variant_defaults_from_mapping": "render_defaults",
    "validate_render_bounds_document": "render_defaults",
    "validate_render_variants_document": "render_defaults",

    # ---------------------------------------------------------------------
    # physical_defaults.py
    # ---------------------------------------------------------------------
    "PHYSICAL_DEFAULTS_SCHEMA_VERSION": "physical_defaults",
    "CollisionMode": "physical_defaults",
    "GridSizeDefaults": "physical_defaults",
    "LayerKind": "physical_defaults",
    "MassSource": "physical_defaults",
    "OccupancyCellDefaults": "physical_defaults",
    "OccupancyMode": "physical_defaults",
    "PhysicalBaseDefaults": "physical_defaults",
    "PhysicalBoundsDefaults": "physical_defaults",
    "PhysicalCollisionDefaults": "physical_defaults",
    "PhysicalDefaults": "physical_defaults",
    "PhysicalDefaultsError": "physical_defaults",
    "PhysicalDimensionsDefaults": "physical_defaults",
    "PhysicalFootprintDefaults": "physical_defaults",
    "PhysicalLayerDefaults": "physical_defaults",
    "PhysicalLayersDefaults": "physical_defaults",
    "PhysicalMassDefaults": "physical_defaults",
    "PhysicalOccupancyDefaults": "physical_defaults",
    "PhysicalRole": "physical_defaults",
    "PhysicalShape": "physical_defaults",
    "assert_valid_physical_base_document": "physical_defaults",
    "assert_valid_physical_collision_document": "physical_defaults",
    "assert_valid_physical_dimensions_document": "physical_defaults",
    "build_physical_defaults": "physical_defaults",
    "clear_physical_defaults_caches": "physical_defaults",
    "physical_bounds_from_grid": "physical_defaults",
    "physical_defaults_from_context": "physical_defaults",
    "physical_defaults_from_create_request": "physical_defaults",
    "physical_defaults_from_creation_plan": "physical_defaults",
    "physical_documents_from_context": "physical_defaults",
    "physical_documents_from_create_request": "physical_defaults",
    "physical_documents_from_creation_plan": "physical_defaults",
    "validate_physical_base_document": "physical_defaults",
    "validate_physical_collision_document": "physical_defaults",
    "validate_physical_dimensions_document": "physical_defaults",

    # ---------------------------------------------------------------------
    # material_defaults.py
    # ---------------------------------------------------------------------
    "MATERIAL_DEFAULTS_SCHEMA_VERSION": "material_defaults",
    "FireReactionClass": "material_defaults",
    "LayerFunction": "material_defaults",
    "MaterialBaseDefaults": "material_defaults",
    "MaterialClass": "material_defaults",
    "MaterialDefaults": "material_defaults",
    "MaterialDefaultsError": "material_defaults",
    "MaterialFinishDefaults": "material_defaults",
    "MaterialFinishesDefaults": "material_defaults",
    "MaterialLayerDefaults": "material_defaults",
    "MaterialLayersDefaults": "material_defaults",
    "MaterialPerformanceDefaults": "material_defaults",
    "MaterialRole": "material_defaults",
    "MaterialSurfaceDefaults": "material_defaults",
    "MaterialSurfacesDefaults": "material_defaults",
    "PerformanceValueSource": "material_defaults",
    "SurfaceFinish": "material_defaults",
    "SurfaceSide": "material_defaults",
    "assert_valid_material_base_document": "material_defaults",
    "assert_valid_material_performance_document": "material_defaults",
    "build_material_defaults": "material_defaults",
    "clear_material_defaults_caches": "material_defaults",
    "material_defaults_from_context": "material_defaults",
    "material_defaults_from_create_request": "material_defaults",
    "material_defaults_from_creation_plan": "material_defaults",
    "material_documents_from_context": "material_defaults",
    "material_documents_from_create_request": "material_defaults",
    "material_documents_from_creation_plan": "material_defaults",
    "validate_material_base_document": "material_defaults",
    "validate_material_performance_document": "material_defaults",

    # ---------------------------------------------------------------------
    # calculation_defaults.py
    # ---------------------------------------------------------------------
    "CALCULATION_DEFAULTS_SCHEMA_VERSION": "calculation_defaults",
    "CalculationConstraintDefaults": "calculation_defaults",
    "CalculationConstraintsDefaults": "calculation_defaults",
    "CalculationCostFactorDefaults": "calculation_defaults",
    "CalculationCostFactorsDefaults": "calculation_defaults",
    "CalculationDefaults": "calculation_defaults",
    "CalculationDefaultsError": "calculation_defaults",
    "CalculationFormulaDefaults": "calculation_defaults",
    "CalculationFormulasDefaults": "calculation_defaults",
    "CalculationMeasureLogicDefaults": "calculation_defaults",
    "CalculationQuantitiesDefaults": "calculation_defaults",
    "CalculationQuantityDefaults": "calculation_defaults",
    "CalculationUnitsDefaults": "calculation_defaults",
    "CalculationVariableDefaults": "calculation_defaults",
    "CalculationVariablesDefaults": "calculation_defaults",
    "ConstraintOperator": "calculation_defaults",
    "ConstraintSeverity": "calculation_defaults",
    "CostFactorKind": "calculation_defaults",
    "FormulaKind": "calculation_defaults",
    "MeasureMode": "calculation_defaults",
    "QuantityKind": "calculation_defaults",
    "VariableSource": "calculation_defaults",
    "VariableValueType": "calculation_defaults",
    "assert_valid_formulas_document": "calculation_defaults",
    "assert_valid_measure_logic_document": "calculation_defaults",
    "assert_valid_quantities_document": "calculation_defaults",
    "assert_valid_variables_document": "calculation_defaults",
    "build_calculation_defaults": "calculation_defaults",
    "calculation_defaults_from_context": "calculation_defaults",
    "calculation_defaults_from_create_request": "calculation_defaults",
    "calculation_defaults_from_creation_plan": "calculation_defaults",
    "calculation_documents_from_context": "calculation_defaults",
    "calculation_documents_from_create_request": "calculation_defaults",
    "calculation_documents_from_creation_plan": "calculation_defaults",
    "clear_calculation_defaults_caches": "calculation_defaults",
    "validate_formulas_document": "calculation_defaults",
    "validate_measure_logic_document": "calculation_defaults",
    "validate_quantities_document": "calculation_defaults",
    "validate_variables_document": "calculation_defaults",

    # ---------------------------------------------------------------------
    # manufacturer_defaults.py
    # ---------------------------------------------------------------------
    "MANUFACTURER_DEFAULTS_SCHEMA_VERSION": "manufacturer_defaults",
    "ManufacturerAssetDefaults": "manufacturer_defaults",
    "ManufacturerAssetRole": "manufacturer_defaults",
    "ManufacturerAssetsDefaults": "manufacturer_defaults",
    "ManufacturerBrandingDefaults": "manufacturer_defaults",
    "ManufacturerContractDefaults": "manufacturer_defaults",
    "ManufacturerContractMode": "manufacturer_defaults",
    "ManufacturerDefaults": "manufacturer_defaults",
    "ManufacturerDefaultsError": "manufacturer_defaults",
    "ManufacturerOverlayLevel": "manufacturer_defaults",
    "ManufacturerOverrideScope": "manufacturer_defaults",
    "ManufacturerOverrideSlotDefaults": "manufacturer_defaults",
    "ManufacturerOverrideSlotsDefaults": "manufacturer_defaults",
    "ManufacturerProductCategoriesDefaults": "manufacturer_defaults",
    "ManufacturerProductCategoryDefaults": "manufacturer_defaults",
    "ManufacturerProductFieldDefaults": "manufacturer_defaults",
    "ManufacturerProductFieldsDefaults": "manufacturer_defaults",
    "ManufacturerValidationPolicy": "manufacturer_defaults",
    "ManufacturerValueType": "manufacturer_defaults",
    "ProductCategoryKind": "manufacturer_defaults",
    "ProductFieldGroup": "manufacturer_defaults",
    "assert_valid_manufacturer_contract_document": "manufacturer_defaults",
    "assert_valid_override_slots_document": "manufacturer_defaults",
    "build_manufacturer_defaults": "manufacturer_defaults",
    "clear_manufacturer_defaults_caches": "manufacturer_defaults",
    "manufacturer_defaults_from_context": "manufacturer_defaults",
    "manufacturer_defaults_from_create_request": "manufacturer_defaults",
    "manufacturer_defaults_from_creation_plan": "manufacturer_defaults",
    "manufacturer_documents_from_context": "manufacturer_defaults",
    "manufacturer_documents_from_create_request": "manufacturer_defaults",
    "manufacturer_documents_from_creation_plan": "manufacturer_defaults",
    "override_slot_from_mapping": "manufacturer_defaults",
    "product_category_from_mapping": "manufacturer_defaults",
    "product_field_from_mapping": "manufacturer_defaults",
    "validate_manufacturer_contract_document": "manufacturer_defaults",
    "validate_override_slots_document": "manufacturer_defaults",

    # ---------------------------------------------------------------------
    # analysis_defaults.py
    # ---------------------------------------------------------------------
    "ANALYSIS_DEFAULTS_SCHEMA_VERSION": "analysis_defaults",
    "AnalysisAssumptionDefaults": "analysis_defaults",
    "AnalysisAssumptionsDefaults": "analysis_defaults",
    "AnalysisCheckDefaults": "analysis_defaults",
    "AnalysisCheckScope": "analysis_defaults",
    "AnalysisCheckSeverity": "analysis_defaults",
    "AnalysisChecksDefaults": "analysis_defaults",
    "AnalysisDefaults": "analysis_defaults",
    "AnalysisDefaultsError": "analysis_defaults",
    "AnalysisParameterDefaults": "analysis_defaults",
    "AnalysisParameterSource": "analysis_defaults",
    "AnalysisProfileStatus": "analysis_defaults",
    "AnalysisValidationPolicy": "analysis_defaults",
    "AnalysisValueType": "analysis_defaults",
    "LoadCaseKind": "analysis_defaults",
    "ReinforcementLayerDefaults": "analysis_defaults",
    "ReinforcementPlacementMode": "analysis_defaults",
    "ReinforcementProfileDefaults": "analysis_defaults",
    "ReinforcementSystemKind": "analysis_defaults",
    "RoutingConnectorDefaults": "analysis_defaults",
    "RoutingConnectorKind": "analysis_defaults",
    "RoutingProfileDefaults": "analysis_defaults",
    "RoutingSystemKind": "analysis_defaults",
    "StaticsLoadCaseDefaults": "analysis_defaults",
    "StaticsProfileDefaults": "analysis_defaults",
    "StaticsSystemKind": "analysis_defaults",
    "analysis_defaults_from_context": "analysis_defaults",
    "analysis_defaults_from_create_request": "analysis_defaults",
    "analysis_defaults_from_creation_plan": "analysis_defaults",
    "analysis_documents_from_context": "analysis_defaults",
    "analysis_documents_from_create_request": "analysis_defaults",
    "analysis_documents_from_creation_plan": "analysis_defaults",
    "assert_valid_reinforcement_profile_document": "analysis_defaults",
    "assert_valid_routing_profile_document": "analysis_defaults",
    "assert_valid_statics_profile_document": "analysis_defaults",
    "build_analysis_defaults": "analysis_defaults",
    "clear_analysis_defaults_caches": "analysis_defaults",
    "validate_reinforcement_profile_document": "analysis_defaults",
    "validate_routing_profile_document": "analysis_defaults",
    "validate_statics_profile_document": "analysis_defaults",

    # ---------------------------------------------------------------------
    # dynamic_defaults.py
    # ---------------------------------------------------------------------
    "DYNAMIC_DEFAULTS_SCHEMA_VERSION": "dynamic_defaults",
    "DynamicBindingDefaults": "dynamic_defaults",
    "DynamicBindingKind": "dynamic_defaults",
    "DynamicBindingsDefaults": "dynamic_defaults",
    "DynamicConstraintDefaults": "dynamic_defaults",
    "DynamicConstraintOperator": "dynamic_defaults",
    "DynamicConstraintSeverity": "dynamic_defaults",
    "DynamicConstraintsDefaults": "dynamic_defaults",
    "DynamicContextRuleDefaults": "dynamic_defaults",
    "DynamicContextRulesDefaults": "dynamic_defaults",
    "DynamicDefaults": "dynamic_defaults",
    "DynamicDefaultsError": "dynamic_defaults",
    "DynamicEvaluationMode": "dynamic_defaults",
    "DynamicGeneratorDefaults": "dynamic_defaults",
    "DynamicGeneratorKind": "dynamic_defaults",
    "DynamicHostContractDefaults": "dynamic_defaults",
    "DynamicHostKind": "dynamic_defaults",
    "DynamicParameterDefaults": "dynamic_defaults",
    "DynamicParameterSource": "dynamic_defaults",
    "DynamicParametersDefaults": "dynamic_defaults",
    "DynamicRuleGraphDefaults": "dynamic_defaults",
    "DynamicRuleGraphEdgeDefaults": "dynamic_defaults",
    "DynamicRuleGraphNodeDefaults": "dynamic_defaults",
    "DynamicRuleGraphNodeKind": "dynamic_defaults",
    "DynamicRuleKind": "dynamic_defaults",
    "DynamicSystemKind": "dynamic_defaults",
    "DynamicValueType": "dynamic_defaults",
    "assert_valid_bindings_document": "dynamic_defaults",
    "assert_valid_context_rules_document": "dynamic_defaults",
    "assert_valid_generator_document": "dynamic_defaults",
    "binding_from_mapping": "dynamic_defaults",
    "build_dynamic_defaults": "dynamic_defaults",
    "clear_dynamic_defaults_caches": "dynamic_defaults",
    "constraint_from_mapping": "dynamic_defaults",
    "context_rule_from_mapping": "dynamic_defaults",
    "dynamic_defaults_from_context": "dynamic_defaults",
    "dynamic_defaults_from_create_request": "dynamic_defaults",
    "dynamic_defaults_from_creation_plan": "dynamic_defaults",
    "dynamic_documents_from_context": "dynamic_defaults",
    "dynamic_documents_from_create_request": "dynamic_defaults",
    "dynamic_documents_from_creation_plan": "dynamic_defaults",
    "parameter_from_mapping": "dynamic_defaults",
    "validate_bindings_document": "dynamic_defaults",
    "validate_context_rules_document": "dynamic_defaults",
    "validate_dynamic_references": "dynamic_defaults",
    "validate_generator_document": "dynamic_defaults",

    # ---------------------------------------------------------------------
    # document_bundle.py
    # ---------------------------------------------------------------------
    "DOCUMENT_BUNDLE_SCHEMA_VERSION": "document_bundle",
    "DocumentBundle": "document_bundle",
    "DocumentBundleError": "document_bundle",
    "DocumentBundleItem": "document_bundle",
    "DocumentBundleOptions": "document_bundle",
    "DocumentBundleSource": "document_bundle",
    "DocumentKind": "document_bundle",
    "DocumentRequirement": "document_bundle",
    "build_document_bundle_from_components": "document_bundle",
    "build_document_bundle_from_context": "document_bundle",
    "build_document_bundle_from_create_request": "document_bundle",
    "build_document_bundle_from_creation_plan": "document_bundle",
    "bundle_items_from_documents": "document_bundle",
    "clear_document_bundle_caches": "document_bundle",
}


_CLEAR_FUNCTION_BY_MODULE: Final[dict[str, str]] = {
    "manifest_defaults": "clear_manifest_defaults_caches",
    "module_defaults": "clear_module_defaults_caches",
    "family_defaults": "clear_family_defaults_caches",
    "variant_defaults": "clear_variant_defaults_caches",
    "editor_defaults": "clear_editor_defaults_caches",
    "render_defaults": "clear_render_defaults_caches",
    "physical_defaults": "clear_physical_defaults_caches",
    "material_defaults": "clear_material_defaults_caches",
    "calculation_defaults": "clear_calculation_defaults_caches",
    "manufacturer_defaults": "clear_manufacturer_defaults_caches",
    "analysis_defaults": "clear_analysis_defaults_caches",
    "dynamic_defaults": "clear_dynamic_defaults_caches",
    "document_bundle": "clear_document_bundle_caches",
}


def _canonical_module_key(module_key: str) -> str:
    """Normalisiert Defaults-Modulkeys und Komfort-Aliase."""
    try:
        key = str(module_key).strip()
    except Exception as exc:
        raise DefaultsImportError("Invalid VPLIB defaults module key.") from exc

    if not key:
        raise DefaultsImportError("Empty VPLIB defaults module key.")

    return _RELATIVE_DEFAULT_MODULE_ALIASES.get(key, key)


@lru_cache(maxsize=64)
def _load_default_module(module_key: str) -> ModuleType:
    """Lädt ein Defaults-Modul lazy über relative Imports."""
    canonical_key = _canonical_module_key(module_key)

    if canonical_key not in _RELATIVE_DEFAULT_MODULES:
        raise DefaultsImportError(f"Unknown VPLIB defaults module {module_key!r}.")

    relative_path = _RELATIVE_DEFAULT_MODULES[canonical_key]

    try:
        return importlib.import_module(relative_path, package=__name__)
    except Exception as exc:
        raise DefaultsImportError(
            f"Could not import VPLIB defaults module "
            f"{canonical_key!r} from {relative_path!r}: {exc}"
        ) from exc


def __getattr__(name: str) -> Any:
    """
    Lazy-Reexport für öffentliche Defaults-Symbole.

    Beispiele:
        from vplib.defaults import build_document_bundle_from_creation_plan
        from vplib.defaults import manifest_document_from_context
        from vplib.defaults import ensure_manifest_document_vplib_uid
        from vplib.defaults import editor_documents_from_create_request
    """
    canonical_module_name = _RELATIVE_DEFAULT_MODULE_ALIASES.get(name, name)

    if canonical_module_name in _RELATIVE_DEFAULT_MODULES:
        module = _load_default_module(canonical_module_name)
        globals()[name] = module
        return module

    module_key = _SYMBOL_TO_MODULE.get(name)

    if not module_key:
        raise AttributeError(f"module {__name__!r} has no attribute {name!r}")

    module = _load_default_module(module_key)

    try:
        value = getattr(module, name)
    except AttributeError as exc:
        raise DefaultsImportError(
            f"Defaults symbol {name!r} is mapped to module {module_key!r}, "
            f"but the module does not export it."
        ) from exc

    globals()[name] = value
    return value


def get_default_module_keys(*, include_aliases: bool = False) -> tuple[str, ...]:
    """
    Gibt alle bekannten Defaults-Modulkeys zurück.

    Args:
        include_aliases:
            Wenn True, werden Komfort-Aliase wie "manifest" und "bundle" ergänzt.
    """
    keys = list(_RELATIVE_DEFAULT_MODULES.keys())

    if include_aliases:
        keys.extend(_RELATIVE_DEFAULT_MODULE_ALIASES.keys())

    return tuple(keys)


def get_default_module_alias_map() -> Mapping[str, str]:
    """Gibt die Alias-zu-Modul-Zuordnung zurück."""
    return dict(_RELATIVE_DEFAULT_MODULE_ALIASES)


def get_default_symbol_names() -> tuple[str, ...]:
    """Gibt alle lazy exportierten öffentlichen Symbolnamen zurück."""
    return tuple(sorted(_SYMBOL_TO_MODULE.keys()))


def get_default_symbol_module_map() -> Mapping[str, str]:
    """Gibt die Symbol-zu-Modul-Zuordnung zurück."""
    return dict(_SYMBOL_TO_MODULE)


def is_default_symbol(name: str) -> bool:
    """Gibt zurück, ob ein Symbol oder Modul-Alias über dieses Package exportiert wird."""
    try:
        key = str(name).strip()
    except Exception:
        return False

    if not key:
        return False

    return (
        key in _SYMBOL_TO_MODULE
        or key in _RELATIVE_DEFAULT_MODULES
        or key in _RELATIVE_DEFAULT_MODULE_ALIASES
    )


def load_all_default_modules() -> tuple[ModuleType, ...]:
    """
    Lädt alle kanonischen Defaults-Module.

    Nützlich für Tests, Startup-Diagnose oder strikte Entwicklungsprüfungen.
    Aliase werden nicht doppelt geladen.
    """
    modules: list[ModuleType] = []

    for module_key in get_default_module_keys(include_aliases=False):
        modules.append(_load_default_module(module_key))

    return tuple(modules)


def get_default_module_statuses() -> tuple[DefaultsModuleStatus, ...]:
    """
    Gibt Importstatus für alle Defaults-Module zurück.

    Diese Funktion wirft nicht, sondern sammelt Fehler in Statusobjekten.
    """
    statuses: list[DefaultsModuleStatus] = []

    for module_key, relative_path in _RELATIVE_DEFAULT_MODULES.items():
        exported_symbols = tuple(
            sorted(
                symbol
                for symbol, mapped_module_key in _SYMBOL_TO_MODULE.items()
                if mapped_module_key == module_key
            )
        )

        try:
            _load_default_module(module_key)
            statuses.append(
                DefaultsModuleStatus(
                    module_key=module_key,
                    module_path=relative_path,
                    loaded=True,
                    error=None,
                    exported_symbols=exported_symbols,
                )
            )
        except Exception as exc:
            statuses.append(
                DefaultsModuleStatus(
                    module_key=module_key,
                    module_path=relative_path,
                    loaded=False,
                    error=str(exc),
                    exported_symbols=exported_symbols,
                )
            )

    return tuple(statuses)


def get_defaults_health() -> dict[str, Any]:
    """Gibt einen JSON-kompatiblen Health-Snapshot der Defaults-Schicht zurück."""
    statuses = get_default_module_statuses()

    try:
        healthy = all(status.loaded for status in statuses)
    except Exception:
        healthy = False

    return {
        "schema_version": DEFAULTS_PACKAGE_VERSION,
        "healthy": healthy,
        "module_count": len(statuses),
        "loaded_module_count": sum(1 for status in statuses if status.loaded),
        "symbol_count": len(_SYMBOL_TO_MODULE),
        "alias_count": len(_RELATIVE_DEFAULT_MODULE_ALIASES),
        "aliases": get_default_module_alias_map(),
        "modules": [
            {
                "module_key": status.module_key,
                "module_path": status.module_path,
                "loaded": status.loaded,
                "error": status.error,
                "exported_symbol_count": len(status.exported_symbols),
            }
            for status in statuses
        ],
    }


def assert_defaults_ready() -> None:
    """
    Prüft, ob alle Defaults-Module ladbar sind.

    Raises:
        DefaultsImportError: Wenn mindestens ein Modul nicht importiert werden kann.
    """
    statuses = get_default_module_statuses()
    failed = [status for status in statuses if not status.loaded]

    if failed:
        details = "; ".join(
            f"{status.module_key}: {status.error}" for status in failed
        )
        raise DefaultsImportError(f"VPLIB defaults package is not ready: {details}")


def clear_defaults_caches() -> None:
    """
    Leert alle bekannten Defaults-Caches.

    Diese Funktion ist bewusst defensiv. Wenn ein einzelnes Modul fehlt oder
    eine Clear-Funktion nicht existiert, wird weitergemacht.
    """
    for module_key, function_name in _CLEAR_FUNCTION_BY_MODULE.items():
        try:
            module = _load_default_module(module_key)
            function = getattr(module, function_name, None)

            if callable(function):
                function()
        except Exception:
            continue

    try:
        _load_default_module.cache_clear()
    except Exception:
        pass


def default_status_to_json(status: DefaultsModuleStatus) -> dict[str, Any]:
    """Serialisiert einen DefaultsModuleStatus JSON-kompatibel."""
    try:
        return status.to_dict()
    except Exception:
        return {
            "schema_version": DEFAULTS_PACKAGE_VERSION,
            "module_key": str(getattr(status, "module_key", "<unknown>")),
            "module_path": str(getattr(status, "module_path", "<unknown>")),
            "loaded": bool(getattr(status, "loaded", False)),
            "error": str(getattr(status, "error", None)),
            "exported_symbols": list(getattr(status, "exported_symbols", ()) or ()),
        }


def default_statuses_to_json() -> list[dict[str, Any]]:
    """Serialisiert alle Defaults-Modulstatuswerte JSON-kompatibel."""
    return [default_status_to_json(status) for status in get_default_module_statuses()]


def build_full_document_bundle(
    creation_plan: Any,
    *,
    include_optional: bool = True,
    include_generated: bool = True,
    metadata: Mapping[str, Any] | None = None,
) -> Any:
    """
    Komfortfunktion für den späteren Package-Creator.

    Diese Funktion bleibt ein dünner Wrapper um document_bundle, damit externe
    Aufrufer einen stabilen Einstieg haben.
    """
    try:
        module = _load_default_module("document_bundle")
        options_cls = getattr(module, "DocumentBundleOptions")
        builder = getattr(module, "build_document_bundle_from_creation_plan")

        return builder(
            creation_plan,
            options=options_cls(
                include_optional=include_optional,
                include_generated=include_generated,
            ),
            metadata=metadata,
        )
    except DefaultsImportError:
        raise
    except Exception as exc:
        raise DefaultsImportError(f"Could not build full VPLIB DocumentBundle: {exc}") from exc


__version__ = DEFAULTS_PACKAGE_VERSION

__all__ = [
    "DEFAULTS_PACKAGE_VERSION",
    "DefaultsImportError",
    "DefaultsModuleStatus",
    "__version__",
    "assert_defaults_ready",
    "build_full_document_bundle",
    "clear_defaults_caches",
    "default_status_to_json",
    "default_statuses_to_json",
    "get_default_module_alias_map",
    "get_default_module_keys",
    "get_default_module_statuses",
    "get_default_symbol_module_map",
    "get_default_symbol_names",
    "get_defaults_health",
    "is_default_symbol",
    "load_all_default_modules",
    "manifest_defaults",
    "module_defaults",
    "family_defaults",
    "variant_defaults",
    "editor_defaults",
    "render_defaults",
    "physical_defaults",
    "material_defaults",
    "calculation_defaults",
    "manufacturer_defaults",
    "analysis_defaults",
    "dynamic_defaults",
    "document_bundle",
    "manifest",
    "modules",
    "family",
    "variants",
    "editor",
    "render",
    "physical",
    "material",
    "calculation",
    "manufacturer",
    "analysis",
    "dynamic",
    "bundle",
    *_SYMBOL_TO_MODULE.keys(),
]