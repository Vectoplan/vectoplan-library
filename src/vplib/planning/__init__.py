# services/vectoplan-library/src/vplib/planning/__init__.py
"""
Public planning API for the VPLIB package engine.

Diese Datei bündelt die stabilen Planning-Bausteine für die VPLIB-Erstellung:

- creation_planner
- module_planner
- path_planner
- variant_planner
- asset_planner

Die Planning-Schicht schreibt keine Dateien. Sie erzeugt nur robuste Pläne,
die später von creators/* ausgeführt werden.

Sie ist bewusst robust aufgebaut:
- Imports laufen lazy über __getattr__.
- Einzelne beschädigte Planning-Module blockieren nicht sofort das ganze Package.
- Diagnosefunktionen zeigen Importstatus und Fehler.
- Cache-Clear-Funktionen können alle Planning-Caches gesammelt leeren.

Technische Namen, JSON-Keys und Variablen bleiben Englisch.
"""

from __future__ import annotations

import importlib
from dataclasses import dataclass
from functools import lru_cache
from types import ModuleType
from typing import Any, Final, Mapping


PLANNING_PACKAGE_VERSION: Final[str] = "vplib.planning.v1"


class PlanningImportError(ImportError):
    """Wird ausgelöst, wenn ein Planning-Modul oder Planning-Symbol nicht geladen werden kann."""


@dataclass(frozen=True, slots=True)
class PlanningModuleStatus:
    """Importstatus eines Planning-Moduls."""

    module_key: str
    module_path: str
    loaded: bool
    error: str | None
    exported_symbols: tuple[str, ...]


_RELATIVE_PLANNING_MODULES: Final[dict[str, str]] = {
    "creation_planner": ".creation_planner",
    "module_planner": ".module_planner",
    "path_planner": ".path_planner",
    "variant_planner": ".variant_planner",
    "asset_planner": ".asset_planner",
}


_SYMBOL_TO_MODULE: Final[dict[str, str]] = {
    # creation_planner.py
    "CREATION_PLANNER_SCHEMA_VERSION": "creation_planner",
    "CreationPlan": "creation_planner",
    "CreationPlanStatus": "creation_planner",
    "CreationPlannerError": "creation_planner",
    "build_asset_copies_for_request": "creation_planner",
    "build_context_for_request": "creation_planner",
    "build_module_plan_for_request": "creation_planner",
    "build_package_plan_for_request": "creation_planner",
    "clear_creation_planner_caches": "creation_planner",
    "creation_plan_from_mapping": "creation_planner",
    "normalize_create_request": "creation_planner",
    "normalize_metadata": "creation_planner",
    "normalize_metadata_value": "creation_planner",
    "normalize_module_plan": "creation_planner",
    "normalize_package_context": "creation_planner",
    "normalize_package_plan": "creation_planner",
    "normalize_profile": "creation_planner",
    "normalize_validation_result": "creation_planner",
    "parse_creation_plan_status_value": "creation_planner",
    "plan_vplib_creation": "creation_planner",
    "resolve_profile_for_request": "creation_planner",
    "validate_creation_plan_parts": "creation_planner",

    # module_planner.py
    "MODULE_PLANNER_SCHEMA_VERSION": "module_planner",
    "ModuleDecisionAction": "module_planner",
    "ModuleDecisionSource": "module_planner",
    "ModulePlannerError": "module_planner",
    "ModulePlanningDecision": "module_planner",
    "ModulePlanningOptions": "module_planner",
    "ModulePlanningResult": "module_planner",
    "build_module_plan_from_decisions": "module_planner",
    "clear_module_planner_caches": "module_planner",
    "collect_dependency_decisions": "module_planner",
    "collect_module_decisions": "module_planner",
    "collect_option_decisions": "module_planner",
    "collect_profile_decisions": "module_planner",
    "collect_request_feature_decisions": "module_planner",
    "dedupe_decisions": "module_planner",
    "feature_decision": "module_planner",
    "get_module_dependencies_safe": "module_planner",
    "get_module_order_safe": "module_planner",
    "map_decision_source_to_module_source": "module_planner",
    "normalize_module_tuple": "module_planner",
    "normalize_options": "module_planner",
    "parse_decision_action_value": "module_planner",
    "parse_decision_source_value": "module_planner",
    "plan_modules_for_profile": "module_planner",
    "plan_modules_for_request": "module_planner",
    "profile_decision_priority": "module_planner",
    "request_has_asset_data": "module_planner",
    "request_has_calculation_data": "module_planner",
    "request_has_dynamic_data": "module_planner",
    "request_has_manufacturer_data": "module_planner",
    "request_has_material_data": "module_planner",
    "request_has_physical_data": "module_planner",
    "request_has_visual_data": "module_planner",
    "resolve_profile_for_object_kind": "module_planner",
    "sort_decisions": "module_planner",
    "stronger_decision": "module_planner",

    # path_planner.py
    "PATH_PLANNER_SCHEMA_VERSION": "path_planner",
    "PathCollisionPolicy": "path_planner",
    "PathPlanSource": "path_planner",
    "PathPlannerError": "path_planner",
    "PathPlanningOptions": "path_planner",
    "PathPlanningResult": "path_planner",
    "PlannedPathPurpose": "path_planner",
    "PlannedPathRecord": "path_planner",
    "PlannedPathType": "path_planner",
    "assert_safe_relative_path": "path_planner",
    "build_asset_target_records": "path_planner",
    "build_module_directory_records": "path_planner",
    "build_module_file_records": "path_planner",
    "build_package_root_records": "path_planner",
    "build_variant_file_records": "path_planner",
    "clear_path_planner_caches": "path_planner",
    "dedupe_path_records": "path_planner",
    "infer_module_from_path_safe": "path_planner",
    "is_child_path": "path_planner",
    "is_path_under_module_safe": "path_planner",
    "make_variant_file_path_safe": "path_planner",
    "merge_path_records": "path_planner",
    "normalize_absolute_path": "path_planner",
    "normalize_asset_collection": "path_planner",
    "normalize_package_context": "path_planner",
    "normalize_relative_path": "path_planner",
    "normalize_variant_set": "path_planner",
    "parse_collision_policy_value": "path_planner",
    "parse_path_plan_source_value": "path_planner",
    "parse_path_purpose_value": "path_planner",
    "parse_path_type_value": "path_planner",
    "path_planning_options_from_mapping": "path_planner",
    "path_planning_result_from_mapping": "path_planner",
    "path_type_order": "path_planner",
    "plan_paths_for_package": "path_planner",
    "planned_path_record_from_mapping": "path_planner",
    "purpose_order": "path_planner",
    "sort_path_records": "path_planner",
    "stronger_path_purpose": "path_planner",

    # variant_planner.py
    "VARIANT_PLANNER_SCHEMA_VERSION": "variant_planner",
    "VariantPlannerError": "variant_planner",
    "VariantPlanningAction": "variant_planner",
    "VariantPlanningDecision": "variant_planner",
    "VariantPlanningOptions": "variant_planner",
    "VariantPlanningResult": "variant_planner",
    "VariantPlanningSource": "variant_planner",
    "build_variant_set_from_decisions": "variant_planner",
    "clear_variant_planner_caches": "variant_planner",
    "collect_variant_decisions": "variant_planner",
    "get_profile_default_variant_id": "variant_planner",
    "get_profile_variant_mode": "variant_planner",
    "humanize_variant_id_safe": "variant_planner",
    "normalize_optional_object_kind": "variant_planner",
    "normalize_variant_id_safe": "variant_planner",
    "normalize_variant_mode_safe": "variant_planner",
    "parse_variant_planning_action_value": "variant_planner",
    "parse_variant_planning_source_value": "variant_planner",
    "plan_variants_for_profile": "variant_planner",
    "plan_variants_for_request": "variant_planner",

    # asset_planner.py
    "ASSET_PLANNER_SCHEMA_VERSION": "asset_planner",
    "DEFAULT_ASSET_TARGET_ROOT": "asset_planner",
    "DEFAULT_RENDER_MODULE_NAME": "asset_planner",
    "ROLE_DEFAULT_FILENAMES": "asset_planner",
    "ROLE_TARGET_DIRECTORIES": "asset_planner",
    "AssetPlannerError": "asset_planner",
    "AssetPlanningAction": "asset_planner",
    "AssetPlanningDecision": "asset_planner",
    "AssetPlanningOptions": "asset_planner",
    "AssetPlanningResult": "asset_planner",
    "AssetPlanningSource": "asset_planner",
    "AssetTargetStrategy": "asset_planner",
    "build_asset_collection": "asset_planner",
    "build_asset_copy_plans": "asset_planner",
    "build_asset_reference_from_request_asset": "asset_planner",
    "build_asset_reference_from_visual_ref": "asset_planner",
    "build_asset_source": "asset_planner",
    "build_asset_target": "asset_planner",
    "build_target_path_canonical": "asset_planner",
    "build_target_path_preserve_filename": "asset_planner",
    "canonical_filename_for_role": "asset_planner",
    "clear_asset_planner_caches": "asset_planner",
    "collect_explicit_assets_from_request": "asset_planner",
    "collect_profile_asset_decisions": "asset_planner",
    "collect_visual_assets_from_request": "asset_planner",
    "extension_from_reference": "asset_planner",
    "infer_asset_id_from_path_safe": "asset_planner",
    "infer_asset_type_for_role": "asset_planner",
    "infer_target_module_for_role": "asset_planner",
    "is_external_uri": "asset_planner",
    "is_package_internal_path": "asset_planner",
    "normalize_optional_asset_id": "asset_planner",
    "normalize_package_asset_path_safe": "asset_planner",
    "normalize_planned_asset_copy": "asset_planner",
    "parse_asset_planning_action_value": "asset_planner",
    "parse_asset_planning_source_value": "asset_planner",
    "parse_target_strategy_value": "asset_planner",
    "plan_assets_for_request": "asset_planner",
    "plan_assets_from_references": "asset_planner",
    "safe_filename_from_reference": "asset_planner",
    "validate_asset_planning_parts": "asset_planner",
}


@lru_cache(maxsize=64)
def _load_planning_module(module_key: str) -> ModuleType:
    """Lädt ein Planning-Modul lazy über relative Imports."""
    if module_key not in _RELATIVE_PLANNING_MODULES:
        raise PlanningImportError(f"Unknown VPLIB planning module {module_key!r}.")

    relative_path = _RELATIVE_PLANNING_MODULES[module_key]

    try:
        return importlib.import_module(relative_path, package=__name__)
    except Exception as exc:
        raise PlanningImportError(
            f"Could not import VPLIB planning module {module_key!r}: {exc}"
        ) from exc


def __getattr__(name: str) -> Any:
    """
    Lazy-Reexport für öffentliche Planning-Symbole.

    Beispiel:

        from vplib.planning import plan_vplib_creation
        from vplib.planning import plan_modules_for_request
        from vplib.planning import plan_paths_for_package
    """
    module_key = _SYMBOL_TO_MODULE.get(name)

    if not module_key:
        raise AttributeError(f"module {__name__!r} has no attribute {name!r}")

    module = _load_planning_module(module_key)

    try:
        value = getattr(module, name)
    except AttributeError as exc:
        raise PlanningImportError(
            f"Planning symbol {name!r} is mapped to module {module_key!r}, "
            f"but the module does not export it."
        ) from exc

    globals()[name] = value
    return value


def get_planning_module_keys() -> tuple[str, ...]:
    """Gibt alle bekannten Planning-Modulkeys zurück."""
    return tuple(_RELATIVE_PLANNING_MODULES.keys())


def get_planning_symbol_names() -> tuple[str, ...]:
    """Gibt alle lazy exportierten öffentlichen Symbolnamen zurück."""
    return tuple(sorted(_SYMBOL_TO_MODULE.keys()))


def get_planning_symbol_module_map() -> Mapping[str, str]:
    """Gibt die Symbol-zu-Modul-Zuordnung zurück."""
    return dict(_SYMBOL_TO_MODULE)


def is_planning_symbol(name: str) -> bool:
    """Gibt zurück, ob ein Symbol über dieses Package exportiert wird."""
    return name in _SYMBOL_TO_MODULE


def load_all_planning_modules() -> tuple[ModuleType, ...]:
    """
    Lädt alle Planning-Module.

    Nützlich für Tests, Startup-Diagnose oder strikte Entwicklungsprüfungen.
    """
    modules: list[ModuleType] = []

    for module_key in get_planning_module_keys():
        modules.append(_load_planning_module(module_key))

    return tuple(modules)


def get_planning_module_statuses() -> tuple[PlanningModuleStatus, ...]:
    """
    Gibt Importstatus für alle Planning-Module zurück.

    Diese Funktion wirft nicht, sondern sammelt Fehler in Statusobjekten.
    """
    statuses: list[PlanningModuleStatus] = []

    for module_key, relative_path in _RELATIVE_PLANNING_MODULES.items():
        exported_symbols = tuple(
            sorted(
                symbol
                for symbol, mapped_module_key in _SYMBOL_TO_MODULE.items()
                if mapped_module_key == module_key
            )
        )

        try:
            _load_planning_module(module_key)
            statuses.append(
                PlanningModuleStatus(
                    module_key=module_key,
                    module_path=relative_path,
                    loaded=True,
                    error=None,
                    exported_symbols=exported_symbols,
                )
            )
        except Exception as exc:
            statuses.append(
                PlanningModuleStatus(
                    module_key=module_key,
                    module_path=relative_path,
                    loaded=False,
                    error=str(exc),
                    exported_symbols=exported_symbols,
                )
            )

    return tuple(statuses)


def get_planning_health() -> dict[str, Any]:
    """Gibt einen JSON-kompatiblen Health-Snapshot der Planning-Schicht zurück."""
    statuses = get_planning_module_statuses()

    return {
        "schema_version": PLANNING_PACKAGE_VERSION,
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


def assert_planning_ready() -> None:
    """
    Prüft, ob alle Planning-Module ladbar sind.

    Raises:
        PlanningImportError: Wenn mindestens ein Modul nicht importiert werden kann.
    """
    statuses = get_planning_module_statuses()
    failed = [status for status in statuses if not status.loaded]

    if failed:
        details = "; ".join(
            f"{status.module_key}: {status.error}" for status in failed
        )
        raise PlanningImportError(f"VPLIB planning package is not ready: {details}")


def clear_planning_caches() -> None:
    """
    Leert alle bekannten Planning-Caches.

    Diese Funktion ist bewusst defensiv. Wenn ein einzelnes Modul fehlt oder
    eine Clear-Funktion nicht existiert, wird weitergemacht.
    """
    _load_planning_module.cache_clear()

    clear_function_names = (
        "clear_creation_planner_caches",
        "clear_module_planner_caches",
        "clear_path_planner_caches",
        "clear_variant_planner_caches",
        "clear_asset_planner_caches",
    )

    for module_key in get_planning_module_keys():
        try:
            module = _load_planning_module(module_key)
        except Exception:
            continue

        for function_name in clear_function_names:
            function = getattr(module, function_name, None)

            if callable(function):
                try:
                    function()
                except Exception:
                    continue


def planning_status_to_json(status: PlanningModuleStatus) -> dict[str, Any]:
    """Serialisiert einen PlanningModuleStatus JSON-kompatibel."""
    return {
        "schema_version": PLANNING_PACKAGE_VERSION,
        "module_key": status.module_key,
        "module_path": status.module_path,
        "loaded": status.loaded,
        "error": status.error,
        "exported_symbols": list(status.exported_symbols),
    }


def planning_statuses_to_json() -> list[dict[str, Any]]:
    """Serialisiert alle Planning-Modulstatuswerte JSON-kompatibel."""
    return [planning_status_to_json(status) for status in get_planning_module_statuses()]


__all__ = [
    "PLANNING_PACKAGE_VERSION",
    "PlanningImportError",
    "PlanningModuleStatus",
    "assert_planning_ready",
    "clear_planning_caches",
    "get_planning_health",
    "get_planning_module_keys",
    "get_planning_module_statuses",
    "get_planning_symbol_module_map",
    "get_planning_symbol_names",
    "is_planning_symbol",
    "load_all_planning_modules",
    "planning_status_to_json",
    "planning_statuses_to_json",
    *_SYMBOL_TO_MODULE.keys(),
]