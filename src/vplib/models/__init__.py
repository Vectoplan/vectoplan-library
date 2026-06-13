# services/vectoplan-library/src/vplib/models/__init__.py
"""
Public model API for the VPLIB package engine.

Diese Datei bündelt die stabilen Model-Bausteine für die VPLIB-Erstellung:

- CreateRequest
- PackageContext
- ModulePlan
- PackagePlan
- AssetReference
- VariantDefinition
- ValidationResult
- PackageResult

Sie ist bewusst robust aufgebaut:
- Imports laufen lazy über __getattr__.
- Einzelne beschädigte Model-Module blockieren nicht sofort das ganze Package.
- Diagnosefunktionen zeigen Importstatus und Fehler.
- Cache-Clear-Funktionen können alle Model-Caches gesammelt leeren.

Technische Namen, JSON-Keys und Variablen bleiben Englisch.
"""

from __future__ import annotations

import importlib
from dataclasses import dataclass
from functools import lru_cache
from types import ModuleType
from typing import Any, Final, Mapping


MODELS_PACKAGE_VERSION: Final[str] = "vplib.models.v1"


class ModelImportError(ImportError):
    """Wird ausgelöst, wenn ein Model-Modul oder Model-Symbol nicht geladen werden kann."""


@dataclass(frozen=True, slots=True)
class ModelModuleStatus:
    """Importstatus eines Model-Moduls."""

    module_key: str
    module_path: str
    loaded: bool
    error: str | None
    exported_symbols: tuple[str, ...]


_RELATIVE_MODEL_MODULES: Final[dict[str, str]] = {
    "create_request": ".create_request",
    "package_context": ".package_context",
    "module_plan": ".module_plan",
    "package_plan": ".package_plan",
    "asset_reference": ".asset_reference",
    "variant_definition": ".variant_definition",
    "validation_result": ".validation_result",
    "package_result": ".package_result",
}


_SYMBOL_TO_MODULE: Final[dict[str, str]] = {
    # create_request.py
    "CREATE_REQUEST_SCHEMA_VERSION": "create_request",
    "DEFAULT_CELL_SIZE_M": "create_request",
    "DEFAULT_FALLBACK_COLOR": "create_request",
    "DEFAULT_PACKAGE_VERSION": "create_request",
    "DEFAULT_VARIANT_ID": "create_request",
    "SAFE_COLOR_RE": "create_request",
    "SAFE_ID_RE": "create_request",
    "AssetRequest": "create_request",
    "AssetRole": "create_request",
    "CalculationRequest": "create_request",
    "ClassificationRequest": "create_request",
    "CreateOptions": "create_request",
    "CreateRequest": "create_request",
    "CreateRequestError": "create_request",
    "DynamicRequest": "create_request",
    "FitMode": "create_request",
    "GridFootprintRequest": "create_request",
    "IdentityRequest": "create_request",
    "ManufacturerRequest": "create_request",
    "MaterialRequest": "create_request",
    "ModelBoundsRequest": "create_request",
    "PhysicalRequest": "create_request",
    "PlacementRequest": "create_request",
    "RenderShape": "create_request",
    "SnapMode": "create_request",
    "VariantMode": "create_request",
    "VariantRequest": "create_request",
    "VariantsRequest": "create_request",
    "asset_request_from_mapping": "create_request",
    "calculation_request_from_mapping": "create_request",
    "classification_request_from_mapping": "create_request",
    "clear_create_request_caches": "create_request",
    "clean_optional_string": "create_request",
    "clean_required_string": "create_request",
    "create_options_from_mapping": "create_request",
    "create_request_from_mapping": "create_request",
    "default_placement_for_object_kind": "create_request",
    "dynamic_request_from_mapping": "create_request",
    "grid_request_from_mapping": "create_request",
    "identity_request_from_mapping": "create_request",
    "manufacturer_request_from_mapping": "create_request",
    "material_request_from_mapping": "create_request",
    "normalize_color": "create_request",
    "normalize_identifier": "create_request",
    "normalize_optional_positive_float": "create_request",
    "normalize_positive_float": "create_request",
    "normalize_positive_int": "create_request",
    "normalize_rotation_steps": "create_request",
    "normalize_slug": "create_request",
    "normalize_string_tuple": "create_request",
    "optional_mapping": "create_request",
    "optional_mapping_or_none": "create_request",
    "parse_asset_role_value": "create_request",
    "parse_fit_mode_value": "create_request",
    "parse_object_kind_value": "create_request",
    "parse_placement_mode_value": "create_request",
    "parse_render_shape_value": "create_request",
    "parse_snap_mode_value": "create_request",
    "parse_variant_mode_value": "create_request",
    "physical_request_from_mapping": "create_request",
    "placement_request_from_mapping": "create_request",
    "require_mapping": "create_request",
    "variants_request_from_mapping": "create_request",
    "visual_request_from_mapping": "create_request",

    # package_context.py
    "DEFAULT_ARCHIVE_ROOT_NAME": "package_context",
    "DEFAULT_GENERATED_ROOT_NAME": "package_context",
    "DEFAULT_PACKAGE_ROOT_NAME": "package_context",
    "DEFAULT_SOURCE_ROOT_NAME": "package_context",
    "PACKAGE_CONTEXT_SCHEMA_VERSION": "package_context",
    "PackageClassificationContext": "package_context",
    "PackageContext": "package_context",
    "PackageContextError": "package_context",
    "PackageContextStatus": "package_context",
    "PackageExecutionContext": "package_context",
    "PackageIdentityContext": "package_context",
    "PackageLocationContext": "package_context",
    "PackageRootPaths": "package_context",
    "PackageWriteMode": "package_context",
    "build_package_relative_dir": "package_context",
    "clear_package_context_caches": "package_context",
    "context_from_dict": "package_context",
    "create_package_context": "package_context",
    "ensure_location_matches_classification": "package_context",
    "normalize_create_request": "package_context",
    "normalize_object_kind_value": "package_context",
    "normalize_path": "package_context",
    "normalize_relative_package_dir": "package_context",
    "normalize_required_string": "package_context",
    "normalize_slug_like": "package_context",
    "parse_context_status_value": "package_context",
    "parse_write_mode_value": "package_context",
    "resolve_write_mode": "package_context",
    "utc_now_iso": "package_context",

    # module_plan.py
    "MODULE_PLAN_SCHEMA_VERSION": "module_plan",
    "ModuleActivationSource": "module_plan",
    "ModulePlan": "module_plan",
    "ModulePlanEntry": "module_plan",
    "ModulePlanError": "module_plan",
    "ModuleRequirementLevel": "module_plan",
    "activate_dependencies": "module_plan",
    "build_module_plan": "module_plan",
    "clear_module_plan_caches": "module_plan",
    "get_allowed_subdirectories_for_module_safe": "module_plan",
    "get_core_module_names_safe": "module_plan",
    "get_generated_files_for_module_safe": "module_plan",
    "get_module_dependencies_safe": "module_plan",
    "get_module_directory_safe": "module_plan",
    "get_optional_files_for_module_safe": "module_plan",
    "get_optional_module_keys_for_object_kind_safe": "module_plan",
    "get_recommended_module_keys_for_object_kind_safe": "module_plan",
    "get_required_files_for_module_safe": "module_plan",
    "get_required_module_keys_for_object_kind_safe": "module_plan",
    "is_valid_package_path_safe": "module_plan",
    "merge_module_plan_entries": "module_plan",
    "merge_tuples": "module_plan",
    "module_plan_entry_from_mapping": "module_plan",
    "module_plan_from_mapping": "module_plan",
    "normalize_module_name_value": "module_plan",
    "normalize_package_path_safe": "module_plan",
    "normalize_path_tuple": "module_plan",
    "parse_activation_source_value": "module_plan",
    "parse_requirement_level_value": "module_plan",
    "sort_module_names_safe": "module_plan",
    "strongest_requirement": "module_plan",
    "validate_core_modules_present_safe": "module_plan",
    "validate_module_dependencies_safe": "module_plan",

    # package_plan.py
    "PACKAGE_PLAN_SCHEMA_VERSION": "package_plan",
    "PackagePlan": "package_plan",
    "PackagePlanError": "package_plan",
    "PlannedAssetCopy": "package_plan",
    "PlannedDirectory": "package_plan",
    "PlannedFile": "package_plan",
    "PlannedFileStatus": "package_plan",
    "PlannedPath": "package_plan",
    "PlannedPathKind": "package_plan",
    "build_directories_from_context_and_module_plan": "package_plan",
    "build_files_from_context_and_module_plan": "package_plan",
    "build_package_plan": "package_plan",
    "clear_package_plan_caches": "package_plan",
    "infer_content_kind": "package_plan",
    "infer_module_from_path_safe": "package_plan",
    "merge_planned_directories": "package_plan",
    "merge_planned_files": "package_plan",
    "normalize_absolute_path": "package_plan",
    "normalize_module_name": "package_plan",
    "normalize_module_plan": "package_plan",
    "normalize_optional_module_name": "package_plan",
    "normalize_package_context": "package_plan",
    "normalize_package_relative_path": "package_plan",
    "package_plan_from_mapping": "package_plan",
    "parse_planned_file_status_value": "package_plan",
    "parse_planned_path_kind_value": "package_plan",
    "planned_asset_copy_from_mapping": "package_plan",
    "planned_directory_from_mapping": "package_plan",
    "planned_file_from_mapping": "package_plan",
    "strongest_file_status": "package_plan",

    # asset_reference.py
    "ASSET_REFERENCE_SCHEMA_VERSION": "asset_reference",
    "DEFAULT_RENDER_MODULE_NAME": "asset_reference",
    "SAFE_ASSET_ID_RE": "asset_reference",
    "SAFE_HEX_COLOR_RE": "asset_reference",
    "URL_SCHEMES": "asset_reference",
    "AssetBounds3D": "asset_reference",
    "AssetOrigin": "asset_reference",
    "AssetReference": "asset_reference",
    "AssetReferenceCollection": "asset_reference",
    "AssetReferenceError": "asset_reference",
    "AssetReferenceStatus": "asset_reference",
    "AssetSource": "asset_reference",
    "AssetTarget": "asset_reference",
    "AssetType": "asset_reference",
    "asset_bounds_from_mapping": "asset_reference",
    "asset_reference_from_create_asset_request": "asset_reference",
    "asset_reference_from_mapping": "asset_reference",
    "asset_references_from_iterable": "asset_reference",
    "asset_source_from_mapping": "asset_reference",
    "asset_target_from_mapping": "asset_reference",
    "get_allowed_extensions_safe": "asset_reference",
    "get_forbidden_extensions_safe": "asset_reference",
    "infer_asset_id_from_mapping": "asset_reference",
    "infer_asset_id_from_path": "asset_reference",
    "infer_asset_type_from_extension": "asset_reference",
    "infer_asset_type_from_mapping": "asset_reference",
    "infer_extension_from_reference": "asset_reference",
    "infer_mime_type": "asset_reference",
    "infer_role_from_mapping": "asset_reference",
    "infer_target_module_from_role": "asset_reference",
    "is_path_under_module_safe": "asset_reference",
    "is_safe_external_uri": "asset_reference",
    "normalize_asset_id": "asset_reference",
    "normalize_enum_key": "asset_reference",
    "normalize_file_extension": "asset_reference",
    "normalize_module_name": "asset_reference",
    "normalize_optional_color": "asset_reference",
    "normalize_optional_non_negative_int": "asset_reference",
    "normalize_package_asset_path": "asset_reference",
    "normalize_positive_float": "asset_reference",
    "parse_asset_origin_value": "asset_reference",
    "parse_asset_reference_status_value": "asset_reference",
    "parse_asset_role_value": "asset_reference",
    "parse_asset_type_value": "asset_reference",
    "validate_asset_extension_for_type": "asset_reference",
    "validate_not_external_uri": "asset_reference",
    "validate_role_type_compatibility": "asset_reference",

    # variant_definition.py
    "ALLOWED_OVERRIDE_PREFIXES": "variant_definition",
    "FORBIDDEN_OVERRIDE_PREFIXES": "variant_definition",
    "SAFE_FIELD_PATH_RE": "variant_definition",
    "SAFE_VARIANT_ID_RE": "variant_definition",
    "TECHNICAL_VARIANT_FIELDS": "variant_definition",
    "VARIANT_DEFINITION_SCHEMA_VERSION": "variant_definition",
    "VARIANT_DOCUMENT_SCHEMA_VERSION": "variant_definition",
    "VARIANT_INDEX_SCHEMA_VERSION": "variant_definition",
    "VariantDefinition": "variant_definition",
    "VariantDefinitionError": "variant_definition",
    "VariantOverride": "variant_definition",
    "VariantOverridePolicy": "variant_definition",
    "VariantSet": "variant_definition",
    "VariantStatus": "variant_definition",
    "assert_override_field_allowed": "variant_definition",
    "clear_variant_definition_caches": "variant_definition",
    "flatten_overrides": "variant_definition",
    "humanize_variant_id": "variant_definition",
    "normalize_field_key": "variant_definition",
    "normalize_field_path": "variant_definition",
    "normalize_int": "variant_definition",
    "normalize_nested_mapping": "variant_definition",
    "normalize_override_value": "variant_definition",
    "normalize_overrides_mapping": "variant_definition",
    "normalize_variant_id": "variant_definition",
    "parse_override_policy_value": "variant_definition",
    "parse_variant_status_value": "variant_definition",
    "set_nested_override": "variant_definition",
    "variant_definition_from_mapping": "variant_definition",
    "variant_set_from_create_request": "variant_definition",
    "variant_set_from_mapping": "variant_definition",

    # validation_result.py
    "VALIDATION_RESULT_SCHEMA_VERSION": "validation_result",
    "ValidationIssue": "validation_result",
    "ValidationIssueCode": "validation_result",
    "ValidationResult": "validation_result",
    "ValidationResultError": "validation_result",
    "ValidationScope": "validation_result",
    "ValidationSeverity": "validation_result",
    "clear_validation_result_caches": "validation_result",
    "dedupe_issues": "validation_result",
    "invalid_result": "validation_result",
    "merge_validation_results": "validation_result",
    "normalize_detail_value": "validation_result",
    "normalize_details_mapping": "validation_result",
    "normalize_optional_field_path": "validation_result",
    "normalize_optional_module_name": "validation_result",
    "parse_issue_code_value": "validation_result",
    "parse_scope_value": "validation_result",
    "parse_severity_value": "validation_result",
    "result_from_exception": "validation_result",
    "sort_issues": "validation_result",
    "valid_result": "validation_result",
    "validation_error": "validation_result",
    "validation_fatal": "validation_result",
    "validation_info": "validation_result",
    "validation_issue": "validation_result",
    "validation_issue_from_mapping": "validation_result",
    "validation_result_from_mapping": "validation_result",
    "validation_warning": "validation_result",

    # package_result.py
    "PACKAGE_RESULT_SCHEMA_VERSION": "package_result",
    "PackageResult": "package_result",
    "PackageResultError": "package_result",
    "PackageResultItem": "package_result",
    "PackageResultStatus": "package_result",
    "ResultItemKind": "package_result",
    "ResultItemStatus": "package_result",
    "clear_package_result_caches": "package_result",
    "compute_success": "package_result",
    "copied_asset_item": "package_result",
    "created_directory_item": "package_result",
    "created_file_item": "package_result",
    "failed_item": "package_result",
    "get_validation_result_valid": "package_result",
    "normalize_metadata": "package_result",
    "normalize_metadata_value": "package_result",
    "normalize_validation_result": "package_result",
    "package_result_from_context": "package_result",
    "package_result_from_mapping": "package_result",
    "package_result_from_plan": "package_result",
    "package_result_item_from_mapping": "package_result",
    "parse_package_result_status_value": "package_result",
    "parse_result_item_kind_value": "package_result",
    "parse_result_item_status_value": "package_result",
    "skipped_item": "package_result",
    "validation_result_from_mapping_safe": "package_result",
}


@lru_cache(maxsize=64)
def _load_model_module(module_key: str) -> ModuleType:
    """Lädt ein Model-Modul lazy über relative Imports."""
    if module_key not in _RELATIVE_MODEL_MODULES:
        raise ModelImportError(f"Unknown VPLIB model module {module_key!r}.")

    relative_path = _RELATIVE_MODEL_MODULES[module_key]

    try:
        return importlib.import_module(relative_path, package=__name__)
    except Exception as exc:
        raise ModelImportError(
            f"Could not import VPLIB model module {module_key!r}: {exc}"
        ) from exc


def __getattr__(name: str) -> Any:
    """
    Lazy-Reexport für öffentliche Model-Symbole.

    Beispiel:

        from vplib.models import CreateRequest
        from vplib.models import PackagePlan
    """
    module_key = _SYMBOL_TO_MODULE.get(name)

    if not module_key:
        raise AttributeError(f"module {__name__!r} has no attribute {name!r}")

    module = _load_model_module(module_key)

    try:
        value = getattr(module, name)
    except AttributeError as exc:
        raise ModelImportError(
            f"Model symbol {name!r} is mapped to module {module_key!r}, "
            f"but the module does not export it."
        ) from exc

    globals()[name] = value
    return value


def get_model_module_keys() -> tuple[str, ...]:
    """Gibt alle bekannten Model-Modulkeys zurück."""
    return tuple(_RELATIVE_MODEL_MODULES.keys())


def get_model_symbol_names() -> tuple[str, ...]:
    """Gibt alle lazy exportierten öffentlichen Symbolnamen zurück."""
    return tuple(sorted(_SYMBOL_TO_MODULE.keys()))


def get_model_symbol_module_map() -> Mapping[str, str]:
    """Gibt die Symbol-zu-Modul-Zuordnung zurück."""
    return dict(_SYMBOL_TO_MODULE)


def is_model_symbol(name: str) -> bool:
    """Gibt zurück, ob ein Symbol über dieses Package exportiert wird."""
    return name in _SYMBOL_TO_MODULE


def load_all_model_modules() -> tuple[ModuleType, ...]:
    """
    Lädt alle Model-Module.

    Nützlich für Tests, Startup-Diagnose oder strikte Entwicklungsprüfungen.
    """
    modules: list[ModuleType] = []

    for module_key in get_model_module_keys():
        modules.append(_load_model_module(module_key))

    return tuple(modules)


def get_model_module_statuses() -> tuple[ModelModuleStatus, ...]:
    """
    Gibt Importstatus für alle Model-Module zurück.

    Diese Funktion wirft nicht, sondern sammelt Fehler in Statusobjekten.
    """
    statuses: list[ModelModuleStatus] = []

    for module_key, relative_path in _RELATIVE_MODEL_MODULES.items():
        exported_symbols = tuple(
            sorted(
                symbol
                for symbol, mapped_module_key in _SYMBOL_TO_MODULE.items()
                if mapped_module_key == module_key
            )
        )

        try:
            _load_model_module(module_key)
            statuses.append(
                ModelModuleStatus(
                    module_key=module_key,
                    module_path=relative_path,
                    loaded=True,
                    error=None,
                    exported_symbols=exported_symbols,
                )
            )
        except Exception as exc:
            statuses.append(
                ModelModuleStatus(
                    module_key=module_key,
                    module_path=relative_path,
                    loaded=False,
                    error=str(exc),
                    exported_symbols=exported_symbols,
                )
            )

    return tuple(statuses)


def get_models_health() -> dict[str, Any]:
    """Gibt einen JSON-kompatiblen Health-Snapshot der Model-Schicht zurück."""
    statuses = get_model_module_statuses()

    return {
        "schema_version": MODELS_PACKAGE_VERSION,
        "healthy": all(status.loaded for status in statuses),
        "module_count": len(statuses),
        "loaded_module_count": sum(1 for status in statuses if status.loaded),
        "symbol_count": len(_SYMBOL_TO_MODULE),
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


def assert_models_ready() -> None:
    """
    Prüft, ob alle Model-Module ladbar sind.

    Raises:
        ModelImportError: Wenn mindestens ein Modul nicht importiert werden kann.
    """
    statuses = get_model_module_statuses()
    failed = [status for status in statuses if not status.loaded]

    if failed:
        details = "; ".join(
            f"{status.module_key}: {status.error}" for status in failed
        )
        raise ModelImportError(f"VPLIB model package is not ready: {details}")


def clear_model_caches() -> None:
    """
    Leert alle bekannten Model-Caches.

    Diese Funktion ist bewusst defensiv. Wenn ein einzelnes Modul fehlt oder
    eine Clear-Funktion nicht existiert, wird weitergemacht.
    """
    _load_model_module.cache_clear()

    clear_function_names = (
        "clear_create_request_caches",
        "clear_package_context_caches",
        "clear_module_plan_caches",
        "clear_package_plan_caches",
        "clear_asset_reference_caches",
        "clear_variant_definition_caches",
        "clear_validation_result_caches",
        "clear_package_result_caches",
    )

    for module_key in get_model_module_keys():
        try:
            module = _load_model_module(module_key)
        except Exception:
            continue

        for function_name in clear_function_names:
            function = getattr(module, function_name, None)

            if callable(function):
                try:
                    function()
                except Exception:
                    continue


def model_status_to_json(status: ModelModuleStatus) -> dict[str, Any]:
    """Serialisiert einen ModelModuleStatus JSON-kompatibel."""
    return {
        "schema_version": MODELS_PACKAGE_VERSION,
        "module_key": status.module_key,
        "module_path": status.module_path,
        "loaded": status.loaded,
        "error": status.error,
        "exported_symbols": list(status.exported_symbols),
    }


def model_statuses_to_json() -> list[dict[str, Any]]:
    """Serialisiert alle Model-Modulstatuswerte JSON-kompatibel."""
    return [model_status_to_json(status) for status in get_model_module_statuses()]


__all__ = [
    "MODELS_PACKAGE_VERSION",
    "ModelImportError",
    "ModelModuleStatus",
    "assert_models_ready",
    "clear_model_caches",
    "get_model_module_keys",
    "get_model_module_statuses",
    "get_model_symbol_module_map",
    "get_model_symbol_names",
    "get_models_health",
    "is_model_symbol",
    "load_all_model_modules",
    "model_status_to_json",
    "model_statuses_to_json",
    *_SYMBOL_TO_MODULE.keys(),
]