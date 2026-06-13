# services/vectoplan-library/src/vplib/domain/__init__.py
"""
Public domain API for the VPLIB package engine.

Diese Datei bündelt die stabilen Domain-Bausteine für VPLIB:

- object kinds
- placement modes
- module names
- package paths
- units
- field names
- classification taxonomy

Sie ist bewusst robust aufgebaut:
- Imports laufen lazy über __getattr__.
- Einzelne beschädigte Domain-Module blockieren nicht sofort das ganze Package.
- Diagnosefunktionen zeigen Importstatus und Fehler.
- Cache-Clear-Funktionen können alle Domain-Caches gesammelt leeren.

Technische Namen bleiben Englisch. Kommentare und Hinweise dürfen Deutsch sein.
"""

from __future__ import annotations

import importlib
from dataclasses import dataclass
from functools import lru_cache
from types import ModuleType
from typing import Any, Final, Mapping


DOMAIN_PACKAGE_VERSION: Final[str] = "vplib.domain.v1"


class DomainImportError(ImportError):
    """Wird ausgelöst, wenn ein Domain-Symbol nicht geladen werden kann."""


@dataclass(frozen=True, slots=True)
class DomainModuleStatus:
    """Importstatus eines Domain-Moduls."""

    module_key: str
    module_path: str
    loaded: bool
    error: str | None
    exported_symbols: tuple[str, ...]


_DOMAIN_MODULES: Final[dict[str, str]] = {
    "object_kinds": "services.vectoplan_library.src.vplib.domain.object_kinds",
    "placement_modes": "services.vectoplan_library.src.vplib.domain.placement_modes",
    "module_names": "services.vectoplan_library.src.vplib.domain.module_names",
    "package_paths": "services.vectoplan_library.src.vplib.domain.package_paths",
    "units": "services.vectoplan_library.src.vplib.domain.units",
    "field_names": "services.vectoplan_library.src.vplib.domain.field_names",
    "classification": "services.vectoplan_library.src.vplib.domain.classification",
}

# Relative Importpfade sind für die echte Package-Nutzung maßgeblich.
_RELATIVE_DOMAIN_MODULES: Final[dict[str, str]] = {
    "object_kinds": ".object_kinds",
    "placement_modes": ".placement_modes",
    "module_names": ".module_names",
    "package_paths": ".package_paths",
    "units": ".units",
    "field_names": ".field_names",
    "classification": ".classification",
}

_SYMBOL_TO_MODULE: Final[dict[str, str]] = {
    # object_kinds.py
    "OBJECT_KIND_SCHEMA_VERSION": "object_kinds",
    "ObjectKindDefinition": "object_kinds",
    "ObjectKindError": "object_kinds",
    "VplibObjectKind": "object_kinds",
    "all_object_kinds_to_json": "object_kinds",
    "allows_manufacturer_overlay": "object_kinds",
    "assert_valid_grid_footprint_for_object_kind": "object_kinds",
    "clear_object_kind_caches": "object_kinds",
    "ensure_object_kind": "object_kinds",
    "ensure_object_kind_value": "object_kinds",
    "filter_valid_object_kinds": "object_kinds",
    "get_default_grid_footprint": "object_kinds",
    "get_min_grid_footprint": "object_kinds",
    "get_object_kind_aliases": "object_kinds",
    "get_object_kind_definition": "object_kinds",
    "get_object_kind_definitions": "object_kinds",
    "get_object_kind_values": "object_kinds",
    "get_optional_module_keys": "object_kinds",
    "get_recommended_module_keys": "object_kinds",
    "get_required_module_keys": "object_kinds",
    "is_valid_object_kind": "object_kinds",
    "object_kind_to_json": "object_kinds",
    "parse_object_kind": "object_kinds",
    "requires_bounds_check": "object_kinds",
    "requires_dynamic_modules": "object_kinds",
    "requires_grid_footprint": "object_kinds",
    "supports_fallback_color": "object_kinds",
    "supports_glb": "object_kinds",
    "supports_multi_cell_footprint": "object_kinds",
    "supports_texture": "object_kinds",
    "try_parse_object_kind": "object_kinds",
    "validate_grid_footprint_for_object_kind": "object_kinds",

    # placement_modes.py
    "PLACEMENT_MODE_SCHEMA_VERSION": "placement_modes",
    "PlacementModeDefinition": "placement_modes",
    "PlacementModeError": "placement_modes",
    "VplibPlacementMode": "placement_modes",
    "all_placement_modes_to_json": "placement_modes",
    "assert_valid_placement_mode_for_object_kind": "placement_modes",
    "build_editor_placement_defaults": "placement_modes",
    "clear_placement_mode_caches": "placement_modes",
    "ensure_placement_mode": "placement_modes",
    "ensure_placement_mode_value": "placement_modes",
    "filter_valid_placement_modes": "placement_modes",
    "get_allowed_placement_modes_for_object_kind": "placement_modes",
    "get_default_anchor": "placement_modes",
    "get_default_pivot": "placement_modes",
    "get_default_placement_mode_for_object_kind": "placement_modes",
    "get_placement_mode_aliases": "placement_modes",
    "get_placement_mode_definition": "placement_modes",
    "get_placement_mode_definitions": "placement_modes",
    "get_placement_mode_values": "placement_modes",
    "get_typical_placement_modes_for_object_kind": "placement_modes",
    "is_placement_mode_allowed_for_object_kind": "placement_modes",
    "is_placement_mode_typical_for_object_kind": "placement_modes",
    "is_valid_placement_mode": "placement_modes",
    "parse_placement_mode": "placement_modes",
    "placement_mode_allows_fallback_color": "placement_modes",
    "placement_mode_allows_glb": "placement_modes",
    "placement_mode_allows_texture": "placement_modes",
    "placement_mode_to_json": "placement_modes",
    "requires_grid_footprint": "placement_modes",
    "requires_support_surface": "placement_modes",
    "requires_surface_normal": "placement_modes",
    "try_parse_placement_mode": "placement_modes",
    "validate_placement_mode_for_object_kind": "placement_modes",

    # module_names.py
    "MODULE_NAME_SCHEMA_VERSION": "module_names",
    "ModuleDefinition": "module_names",
    "ModuleNameError": "module_names",
    "VplibModuleName": "module_names",
    "all_module_definitions_to_json": "module_names",
    "assert_valid_module_set": "module_names",
    "build_modules_manifest_payload": "module_names",
    "clear_module_name_caches": "module_names",
    "dedupe_module_names": "module_names",
    "directory_name": "module_names",
    "ensure_module_name": "module_names",
    "ensure_module_name_value": "module_names",
    "filter_valid_module_names": "module_names",
    "get_all_module_names": "module_names",
    "get_content_module_names": "module_names",
    "get_core_module_names": "module_names",
    "get_default_creation_module_names": "module_names",
    "get_module_definition": "module_names",
    "get_module_definitions": "module_names",
    "get_module_name_aliases": "module_names",
    "get_module_name_values": "module_names",
    "get_support_module_names": "module_names",
    "get_technical_module_names": "module_names",
    "is_valid_module_name": "module_names",
    "merge_module_names": "module_names",
    "module_allows_assets": "module_names",
    "module_allows_binary_assets": "module_names",
    "module_allows_json_documents": "module_names",
    "module_allows_markdown_documents": "module_names",
    "module_definition_to_json": "module_names",
    "module_dependencies": "module_names",
    "module_forbids_executable_files": "module_names",
    "module_mutual_exclusions": "module_names",
    "module_name_values": "module_names",
    "module_participates_in_archive": "module_names",
    "module_participates_in_checksum": "module_names",
    "optional_document_names": "module_names",
    "parse_module_name": "module_names",
    "required_document_names": "module_names",
    "sort_module_names": "module_names",
    "top_level_file_name": "module_names",
    "try_parse_module_name": "module_names",
    "validate_core_modules_present": "module_names",
    "validate_module_dependencies": "module_names",
    "validate_module_set": "module_names",

    # package_paths.py
    "ALLOWED_ASSET_EXTENSIONS": "package_paths",
    "ALLOWED_PACKAGE_EXTENSIONS": "package_paths",
    "ALLOWED_TEXT_EXTENSIONS": "package_paths",
    "FORBIDDEN_FILE_EXTENSIONS": "package_paths",
    "PACKAGE_PATH_SCHEMA_VERSION": "package_paths",
    "SAFE_PATH_RE": "package_paths",
    "SAFE_SLUG_RE": "package_paths",
    "VARIANT_FILE_PATTERN": "package_paths",
    "VPLIB_MANIFEST_FILE": "package_paths",
    "VPLIB_MODULES_FILE": "package_paths",
    "ModulePathDefinition": "package_paths",
    "PackagePathDefinition": "package_paths",
    "PackagePathError": "package_paths",
    "PackagePathKind": "package_paths",
    "all_module_paths_to_json": "package_paths",
    "all_package_paths_to_json": "package_paths",
    "assert_safe_package_file_path": "package_paths",
    "assert_valid_package_paths": "package_paths",
    "classify_package_path": "package_paths",
    "clear_package_path_caches": "package_paths",
    "get_allowed_subdirectories_for_module": "package_paths",
    "get_allowed_subdirectories_for_modules": "package_paths",
    "get_asset_files_for_module": "package_paths",
    "get_generated_files_for_module": "package_paths",
    "get_module_directories_for_modules": "package_paths",
    "get_module_directory": "package_paths",
    "get_module_path_definition": "package_paths",
    "get_module_path_definitions": "package_paths",
    "get_module_top_level_file": "package_paths",
    "get_optional_files_for_module": "package_paths",
    "get_optional_files_for_modules": "package_paths",
    "get_package_path_definition_by_path": "package_paths",
    "get_package_path_definitions": "package_paths",
    "get_required_files_for_module": "package_paths",
    "get_required_files_for_modules": "package_paths",
    "get_top_level_files": "package_paths",
    "has_forbidden_extension": "package_paths",
    "infer_module_from_path": "package_paths",
    "is_allowed_package_file_extension": "package_paths",
    "is_known_package_path": "package_paths",
    "is_path_under_module": "package_paths",
    "is_valid_package_path": "package_paths",
    "make_asset_path": "package_paths",
    "make_render_icon_path": "package_paths",
    "make_render_model_path": "package_paths",
    "make_render_preview_path": "package_paths",
    "make_render_texture_path": "package_paths",
    "make_variant_file_path": "package_paths",
    "module_path_definition_to_json": "package_paths",
    "normalize_package_path": "package_paths",
    "path_definition_to_json": "package_paths",
    "path_extension": "package_paths",
    "resolve_relative_package_path": "package_paths",
    "try_normalize_package_path": "package_paths",
    "validate_package_paths": "package_paths",
    "validate_required_paths_present": "package_paths",

    # units.py
    "UNIT_SCHEMA_VERSION": "units",
    "UnitCategory": "units",
    "UnitDefinition": "units",
    "UnitError": "units",
    "VplibUnit": "units",
    "all_units_to_json": "units",
    "are_compatible_units": "units",
    "assert_valid_numeric_value": "units",
    "build_unit_value_payload": "units",
    "clear_unit_caches": "units",
    "convert_value": "units",
    "ensure_unit": "units",
    "ensure_unit_value": "units",
    "filter_valid_units": "units",
    "get_base_unit": "units",
    "get_unit_aliases": "units",
    "get_unit_category": "units",
    "get_unit_definition": "units",
    "get_unit_definitions": "units",
    "get_unit_symbol": "units",
    "get_unit_values": "units",
    "get_units_by_category": "units",
    "is_valid_unit": "units",
    "normalize_numeric_value": "units",
    "parse_unit": "units",
    "try_parse_unit": "units",
    "unit_accepts_float": "units",
    "unit_accepts_integer": "units",
    "unit_accepts_negative": "units",
    "unit_definition_to_json": "units",
    "unit_supports_conversion": "units",
    "validate_numeric_value": "units",

    # field_names.py
    "FIELD_NAME_SCHEMA_VERSION": "field_names",
    "FieldDefinition": "field_names",
    "FieldGroup": "field_names",
    "FieldNameError": "field_names",
    "ValueKind": "field_names",
    "VplibFieldName": "field_names",
    "all_field_definitions_to_json": "field_names",
    "build_classification_payload": "field_names",
    "clear_field_name_caches": "field_names",
    "ensure_field_name": "field_names",
    "ensure_field_name_value": "field_names",
    "field_definition_to_json": "field_names",
    "filter_valid_field_names": "field_names",
    "get_all_field_names": "field_names",
    "get_classification_field_names": "field_names",
    "get_classification_id_field_names": "field_names",
    "get_classification_label_field_names": "field_names",
    "get_field_definition": "field_names",
    "get_field_definitions": "field_names",
    "get_field_group": "field_names",
    "get_field_name_aliases": "field_names",
    "get_field_name_values": "field_names",
    "get_field_value_kind": "field_names",
    "get_fields_by_group": "field_names",
    "is_valid_field_name": "field_names",
    "parse_field_name": "field_names",
    "try_parse_field_name": "field_names",

    # classification.py
    "CLASSIFICATION_SCHEMA_VERSION": "classification",
    "SAFE_CLASSIFICATION_KEY_RE": "classification",
    "CategoryDefinition": "classification",
    "ClassificationError": "classification",
    "ClassificationPath": "classification",
    "DomainDefinition": "classification",
    "SubcategoryDefinition": "classification",
    "VplibDomain": "classification",
    "all_categories_to_json": "classification",
    "all_domains_to_json": "classification",
    "all_subcategories_to_json": "classification",
    "assert_valid_classification": "classification",
    "build_classification_path": "classification",
    "category_definition_to_json": "classification",
    "clear_classification_caches": "classification",
    "domain_definition_to_json": "classification",
    "get_all_domains": "classification",
    "get_categories_for_domain": "classification",
    "get_category_definition": "classification",
    "get_domain_definition": "classification",
    "get_domain_definitions": "classification",
    "get_domain_values": "classification",
    "get_subcategories_for_category": "classification",
    "get_subcategory_definition": "classification",
    "is_valid_classification": "classification",
    "is_valid_domain": "classification",
    "normalize_classification_key": "classification",
    "parse_category": "classification",
    "parse_classification_path": "classification",
    "parse_domain": "classification",
    "parse_subcategory": "classification",
    "subcategory_definition_to_json": "classification",
    "taxonomy_to_json": "classification",
    "try_parse_category": "classification",
    "try_parse_classification_path": "classification",
    "try_parse_domain": "classification",
    "try_parse_subcategory": "classification",
    "validate_classification": "classification",
}


@lru_cache(maxsize=64)
def _load_domain_module(module_key: str) -> ModuleType:
    """
    Lädt ein Domain-Modul lazy.

    Relative Imports werden bevorzugt. Dadurch funktioniert das Package auch,
    wenn der absolute Service-Pfad im Python-Importkontext anders aussieht.
    """
    if module_key not in _RELATIVE_DOMAIN_MODULES:
        raise DomainImportError(f"Unknown VPLIB domain module {module_key!r}.")

    relative_path = _RELATIVE_DOMAIN_MODULES[module_key]

    try:
        return importlib.import_module(relative_path, package=__name__)
    except Exception as relative_error:
        absolute_path = _DOMAIN_MODULES.get(module_key)

        if absolute_path:
            try:
                return importlib.import_module(absolute_path)
            except Exception as absolute_error:
                raise DomainImportError(
                    f"Could not import VPLIB domain module {module_key!r}. "
                    f"Relative error: {relative_error}. Absolute error: {absolute_error}."
                ) from absolute_error

        raise DomainImportError(
            f"Could not import VPLIB domain module {module_key!r}: {relative_error}."
        ) from relative_error


def __getattr__(name: str) -> Any:
    """
    Lazy-Reexport für öffentliche Domain-Symbole.

    Dadurch kann z. B. importiert werden:

        from vplib.domain import VplibObjectKind

    ohne dass alle Domain-Module sofort geladen werden müssen.
    """
    module_key = _SYMBOL_TO_MODULE.get(name)

    if not module_key:
        raise AttributeError(f"module {__name__!r} has no attribute {name!r}")

    module = _load_domain_module(module_key)

    try:
        value = getattr(module, name)
    except AttributeError as exc:
        raise DomainImportError(
            f"Domain symbol {name!r} is mapped to module {module_key!r}, "
            f"but the module does not export it."
        ) from exc

    globals()[name] = value
    return value


def get_domain_module_keys() -> tuple[str, ...]:
    """Gibt alle bekannten Domain-Modulkeys zurück."""
    return tuple(_RELATIVE_DOMAIN_MODULES.keys())


def get_domain_symbol_names() -> tuple[str, ...]:
    """Gibt alle lazy exportierten öffentlichen Symbolnamen zurück."""
    return tuple(sorted(_SYMBOL_TO_MODULE.keys()))


def get_domain_symbol_module_map() -> Mapping[str, str]:
    """Gibt die Symbol-zu-Modul-Zuordnung zurück."""
    return dict(_SYMBOL_TO_MODULE)


def is_domain_symbol(name: str) -> bool:
    """Gibt zurück, ob ein Symbol über dieses Package exportiert wird."""
    return name in _SYMBOL_TO_MODULE


def load_all_domain_modules() -> tuple[ModuleType, ...]:
    """
    Lädt alle Domain-Module.

    Nützlich für Tests, Startup-Diagnose oder strikte Entwicklungsprüfungen.
    """
    modules: list[ModuleType] = []

    for module_key in get_domain_module_keys():
        modules.append(_load_domain_module(module_key))

    return tuple(modules)


def get_domain_module_statuses() -> tuple[DomainModuleStatus, ...]:
    """
    Gibt Importstatus für alle Domain-Module zurück.

    Diese Funktion wirft nicht, sondern sammelt Fehler in Statusobjekten.
    """
    statuses: list[DomainModuleStatus] = []

    for module_key, relative_path in _RELATIVE_DOMAIN_MODULES.items():
        exported_symbols = tuple(
            sorted(
                symbol
                for symbol, mapped_module_key in _SYMBOL_TO_MODULE.items()
                if mapped_module_key == module_key
            )
        )

        try:
            _load_domain_module(module_key)
            statuses.append(
                DomainModuleStatus(
                    module_key=module_key,
                    module_path=relative_path,
                    loaded=True,
                    error=None,
                    exported_symbols=exported_symbols,
                )
            )
        except Exception as exc:
            statuses.append(
                DomainModuleStatus(
                    module_key=module_key,
                    module_path=relative_path,
                    loaded=False,
                    error=str(exc),
                    exported_symbols=exported_symbols,
                )
            )

    return tuple(statuses)


def get_domain_health() -> dict[str, Any]:
    """
    Gibt einen JSON-kompatiblen Health-Snapshot der Domain-Schicht zurück.
    """
    statuses = get_domain_module_statuses()

    return {
        "schema_version": DOMAIN_PACKAGE_VERSION,
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


def assert_domain_ready() -> None:
    """
    Prüft, ob alle Domain-Module ladbar sind.

    Raises:
        DomainImportError: Wenn mindestens ein Modul nicht importiert werden kann.
    """
    statuses = get_domain_module_statuses()
    failed = [status for status in statuses if not status.loaded]

    if failed:
        details = "; ".join(
            f"{status.module_key}: {status.error}" for status in failed
        )
        raise DomainImportError(f"VPLIB domain package is not ready: {details}")


def clear_domain_caches() -> None:
    """
    Leert alle bekannten Domain-Caches.

    Diese Funktion ist bewusst defensiv. Wenn ein einzelnes Modul fehlt oder
    eine Clear-Funktion nicht existiert, wird weitergemacht.
    """
    _load_domain_module.cache_clear()

    clear_function_names = (
        "clear_object_kind_caches",
        "clear_placement_mode_caches",
        "clear_module_name_caches",
        "clear_package_path_caches",
        "clear_unit_caches",
        "clear_field_name_caches",
        "clear_classification_caches",
    )

    for module_key in get_domain_module_keys():
        try:
            module = _load_domain_module(module_key)
        except Exception:
            continue

        for function_name in clear_function_names:
            function = getattr(module, function_name, None)

            if callable(function):
                try:
                    function()
                except Exception:
                    continue


def domain_status_to_json(status: DomainModuleStatus) -> dict[str, Any]:
    """Serialisiert einen DomainModuleStatus JSON-kompatibel."""
    return {
        "schema_version": DOMAIN_PACKAGE_VERSION,
        "module_key": status.module_key,
        "module_path": status.module_path,
        "loaded": status.loaded,
        "error": status.error,
        "exported_symbols": list(status.exported_symbols),
    }


def domain_statuses_to_json() -> list[dict[str, Any]]:
    """Serialisiert alle Domain-Modulstatuswerte JSON-kompatibel."""
    return [domain_status_to_json(status) for status in get_domain_module_statuses()]


__all__ = [
    "DOMAIN_PACKAGE_VERSION",
    "DomainImportError",
    "DomainModuleStatus",
    "assert_domain_ready",
    "clear_domain_caches",
    "domain_status_to_json",
    "domain_statuses_to_json",
    "get_domain_health",
    "get_domain_module_keys",
    "get_domain_module_statuses",
    "get_domain_symbol_module_map",
    "get_domain_symbol_names",
    "is_domain_symbol",
    "load_all_domain_modules",
    *_SYMBOL_TO_MODULE.keys(),
]