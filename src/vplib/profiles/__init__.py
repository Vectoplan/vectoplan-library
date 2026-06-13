# services/vectoplan-library/src/vplib/profiles/__init__.py
"""
Public profile API for the VPLIB package engine.

Diese Datei bündelt die stabilen Profile-Bausteine für VPLIB:

- base profile structures
- cell_block profile
- multi_cell_module profile
- catalog_object profile
- adaptive_system profile
- profile resolver

Sie ist bewusst robust aufgebaut:
- Imports laufen lazy über __getattr__.
- Einzelne beschädigte Profile-Module blockieren nicht sofort das ganze Package.
- Diagnosefunktionen zeigen Importstatus und Fehler.
- Cache-Clear-Funktionen können alle Profile-Caches gesammelt leeren.

Technische Namen, JSON-Keys und Variablen bleiben Englisch.
"""

from __future__ import annotations

import importlib
from dataclasses import dataclass
from functools import lru_cache
from types import ModuleType
from typing import Any, Final, Mapping


PROFILES_PACKAGE_VERSION: Final[str] = "vplib.profiles.v1"


class ProfileImportError(ImportError):
    """Wird ausgelöst, wenn ein Profile-Modul oder Profile-Symbol nicht geladen werden kann."""


@dataclass(frozen=True, slots=True)
class ProfileModuleStatus:
    """Importstatus eines Profile-Moduls."""

    module_key: str
    module_path: str
    loaded: bool
    error: str | None
    exported_symbols: tuple[str, ...]


_RELATIVE_PROFILE_MODULES: Final[dict[str, str]] = {
    "base_profiles": ".base_profiles",
    "cell_block_profile": ".cell_block_profile",
    "multi_cell_module_profile": ".multi_cell_module_profile",
    "catalog_object_profile": ".catalog_object_profile",
    "adaptive_system_profile": ".adaptive_system_profile",
    "profile_resolver": ".profile_resolver",
}


_SYMBOL_TO_MODULE: Final[dict[str, str]] = {
    # base_profiles.py
    "BASE_FORBIDDEN_MODULES": "base_profiles",
    "BASE_OPTIONAL_MODULES": "base_profiles",
    "BASE_PROFILE_KEY": "base_profiles",
    "BASE_PROFILE_SCHEMA_VERSION": "base_profiles",
    "BASE_RECOMMENDED_MODULES": "base_profiles",
    "CORE_REQUIRED_MODULES": "base_profiles",
    "DEFAULT_MANUFACTURER_OVERLAY_LEVEL": "base_profiles",
    "DEFAULT_SCHEMA_VERSION": "base_profiles",
    "ObjectKindProfile": "base_profiles",
    "ProfileAssetPolicy": "base_profiles",
    "ProfileAssetRule": "base_profiles",
    "ProfileDefaults": "base_profiles",
    "ProfileDocumentRule": "base_profiles",
    "ProfileError": "base_profiles",
    "ProfileModuleRequirement": "base_profiles",
    "ProfileModuleRule": "base_profiles",
    "ProfileRuleScope": "base_profiles",
    "ProfileRuleSeverity": "base_profiles",
    "ProfileValidationMode": "base_profiles",
    "ProfileValidationRule": "base_profiles",
    "base_optional_module_rules": "base_profiles",
    "base_recommended_module_rules": "base_profiles",
    "base_required_module_rules": "base_profiles",
    "base_validation_rules": "base_profiles",
    "build_base_profile": "base_profiles",
    "clear_base_profile_caches": "base_profiles",
    "ensure_core_module_rules": "base_profiles",
    "find_duplicates": "base_profiles",
    "get_allowed_subdirectories_for_module_safe": "base_profiles",
    "get_generated_files_for_module_safe": "base_profiles",
    "get_module_order_safe": "base_profiles",
    "get_optional_files_for_module_safe": "base_profiles",
    "get_required_files_for_module_safe": "base_profiles",
    "is_path_under_module_safe": "base_profiles",
    "merge_profile_module_rules": "base_profiles",
    "merge_string_tuples": "base_profiles",
    "normalize_asset_role_value": "base_profiles",
    "normalize_color": "base_profiles",
    "normalize_document_rules": "base_profiles",
    "normalize_enum_key": "base_profiles",
    "normalize_extension_tuple": "base_profiles",
    "normalize_grid_size_cells": "base_profiles",
    "normalize_metadata": "base_profiles",
    "normalize_metadata_value": "base_profiles",
    "normalize_module_name": "base_profiles",
    "normalize_module_rules": "base_profiles",
    "normalize_object_kind_value": "base_profiles",
    "normalize_package_path": "base_profiles",
    "normalize_package_path_tuple": "base_profiles",
    "normalize_placement_mode_value": "base_profiles",
    "normalize_positive_float": "base_profiles",
    "normalize_positive_int": "base_profiles",
    "normalize_profile_key": "base_profiles",
    "normalize_rule_key": "base_profiles",
    "normalize_slug_like": "base_profiles",
    "normalize_validation_rules": "base_profiles",
    "normalize_variant_mode_value": "base_profiles",
    "parse_profile_asset_policy_value": "base_profiles",
    "parse_profile_module_requirement_value": "base_profiles",
    "parse_profile_rule_scope_value": "base_profiles",
    "parse_profile_rule_severity_value": "base_profiles",
    "parse_profile_validation_mode_value": "base_profiles",
    "strongest_asset_policy": "base_profiles",
    "strongest_module_requirement": "base_profiles",

    # cell_block_profile.py
    "CELL_BLOCK_ALLOWED_ASSET_EXTENSIONS": "cell_block_profile",
    "CELL_BLOCK_ALLOWED_PLACEMENT_MODES": "cell_block_profile",
    "CELL_BLOCK_DEFAULT_GRID_SIZE_CELLS": "cell_block_profile",
    "CELL_BLOCK_DEFAULT_MAX_MODEL_SIZE_MB": "cell_block_profile",
    "CELL_BLOCK_DEFAULT_MAX_PREVIEW_SIZE_MB": "cell_block_profile",
    "CELL_BLOCK_DEFAULT_MAX_TEXTURE_SIZE_MB": "cell_block_profile",
    "CELL_BLOCK_EXCLUDED_MODULES": "cell_block_profile",
    "CELL_BLOCK_OBJECT_KIND": "cell_block_profile",
    "CELL_BLOCK_OPTIONAL_DOCUMENTS": "cell_block_profile",
    "CELL_BLOCK_OPTIONAL_MODULES": "cell_block_profile",
    "CELL_BLOCK_PROFILE_KEY": "cell_block_profile",
    "CELL_BLOCK_PROFILE_SCHEMA_VERSION": "cell_block_profile",
    "CELL_BLOCK_RECOMMENDED_MODULES": "cell_block_profile",
    "CELL_BLOCK_RECOMMENDED_PLACEMENT_MODE": "cell_block_profile",
    "CELL_BLOCK_REQUIRED_DOCUMENTS": "cell_block_profile",
    "CELL_BLOCK_REQUIRED_MODULES": "cell_block_profile",
    "assert_cell_block_profile_valid": "cell_block_profile",
    "build_cell_block_profile": "cell_block_profile",
    "cell_block_asset_rules": "cell_block_profile",
    "cell_block_excluded_module_rules": "cell_block_profile",
    "cell_block_optional_document_rules": "cell_block_profile",
    "cell_block_optional_module_rules": "cell_block_profile",
    "cell_block_profile_to_dict": "cell_block_profile",
    "cell_block_recommended_module_rules": "cell_block_profile",
    "cell_block_required_document_rules": "cell_block_profile",
    "cell_block_required_module_rules": "cell_block_profile",
    "cell_block_validation_rules": "cell_block_profile",
    "get_cell_block_profile": "cell_block_profile",
    "validate_cell_block_profile": "cell_block_profile",

    # multi_cell_module_profile.py
    "MULTI_CELL_MODULE_ALLOWED_ASSET_EXTENSIONS": "multi_cell_module_profile",
    "MULTI_CELL_MODULE_ALLOWED_PLACEMENT_MODES": "multi_cell_module_profile",
    "MULTI_CELL_MODULE_DEFAULT_GRID_SIZE_CELLS": "multi_cell_module_profile",
    "MULTI_CELL_MODULE_DEFAULT_MAX_MODEL_SIZE_MB": "multi_cell_module_profile",
    "MULTI_CELL_MODULE_DEFAULT_MAX_PREVIEW_SIZE_MB": "multi_cell_module_profile",
    "MULTI_CELL_MODULE_DEFAULT_MAX_TEXTURE_SIZE_MB": "multi_cell_module_profile",
    "MULTI_CELL_MODULE_EXCLUDED_MODULES": "multi_cell_module_profile",
    "MULTI_CELL_MODULE_OBJECT_KIND": "multi_cell_module_profile",
    "MULTI_CELL_MODULE_OPTIONAL_DOCUMENTS": "multi_cell_module_profile",
    "MULTI_CELL_MODULE_OPTIONAL_MODULES": "multi_cell_module_profile",
    "MULTI_CELL_MODULE_PROFILE_KEY": "multi_cell_module_profile",
    "MULTI_CELL_MODULE_PROFILE_SCHEMA_VERSION": "multi_cell_module_profile",
    "MULTI_CELL_MODULE_RECOMMENDED_MODULES": "multi_cell_module_profile",
    "MULTI_CELL_MODULE_RECOMMENDED_PLACEMENT_MODE": "multi_cell_module_profile",
    "MULTI_CELL_MODULE_REQUIRED_DOCUMENTS": "multi_cell_module_profile",
    "MULTI_CELL_MODULE_REQUIRED_MODULES": "multi_cell_module_profile",
    "assert_multi_cell_module_profile_valid": "multi_cell_module_profile",
    "build_multi_cell_module_profile": "multi_cell_module_profile",
    "get_multi_cell_module_profile": "multi_cell_module_profile",
    "multi_cell_module_asset_rules": "multi_cell_module_profile",
    "multi_cell_module_excluded_module_rules": "multi_cell_module_profile",
    "multi_cell_module_optional_document_rules": "multi_cell_module_profile",
    "multi_cell_module_optional_module_rules": "multi_cell_module_profile",
    "multi_cell_module_profile_to_dict": "multi_cell_module_profile",
    "multi_cell_module_recommended_module_rules": "multi_cell_module_profile",
    "multi_cell_module_required_document_rules": "multi_cell_module_profile",
    "multi_cell_module_required_module_rules": "multi_cell_module_profile",
    "multi_cell_module_validation_rules": "multi_cell_module_profile",
    "validate_multi_cell_module_profile": "multi_cell_module_profile",

    # catalog_object_profile.py
    "CATALOG_OBJECT_ALLOWED_ASSET_EXTENSIONS": "catalog_object_profile",
    "CATALOG_OBJECT_ALLOWED_PLACEMENT_MODES": "catalog_object_profile",
    "CATALOG_OBJECT_DEFAULT_GRID_SIZE_CELLS": "catalog_object_profile",
    "CATALOG_OBJECT_DEFAULT_MAX_MODEL_SIZE_MB": "catalog_object_profile",
    "CATALOG_OBJECT_DEFAULT_MAX_PREVIEW_SIZE_MB": "catalog_object_profile",
    "CATALOG_OBJECT_DEFAULT_MAX_TEXTURE_SIZE_MB": "catalog_object_profile",
    "CATALOG_OBJECT_EXCLUDED_MODULES": "catalog_object_profile",
    "CATALOG_OBJECT_OBJECT_KIND": "catalog_object_profile",
    "CATALOG_OBJECT_OPTIONAL_DOCUMENTS": "catalog_object_profile",
    "CATALOG_OBJECT_OPTIONAL_MODULES": "catalog_object_profile",
    "CATALOG_OBJECT_PROFILE_KEY": "catalog_object_profile",
    "CATALOG_OBJECT_PROFILE_SCHEMA_VERSION": "catalog_object_profile",
    "CATALOG_OBJECT_RECOMMENDED_MODULES": "catalog_object_profile",
    "CATALOG_OBJECT_RECOMMENDED_PLACEMENT_MODE": "catalog_object_profile",
    "CATALOG_OBJECT_REQUIRED_DOCUMENTS": "catalog_object_profile",
    "CATALOG_OBJECT_REQUIRED_MODULES": "catalog_object_profile",
    "assert_catalog_object_profile_valid": "catalog_object_profile",
    "build_catalog_object_profile": "catalog_object_profile",
    "catalog_object_asset_rules": "catalog_object_profile",
    "catalog_object_excluded_module_rules": "catalog_object_profile",
    "catalog_object_optional_document_rules": "catalog_object_profile",
    "catalog_object_optional_module_rules": "catalog_object_profile",
    "catalog_object_profile_to_dict": "catalog_object_profile",
    "catalog_object_recommended_module_rules": "catalog_object_profile",
    "catalog_object_required_document_rules": "catalog_object_profile",
    "catalog_object_required_module_rules": "catalog_object_profile",
    "catalog_object_validation_rules": "catalog_object_profile",
    "get_catalog_object_profile": "catalog_object_profile",
    "validate_catalog_object_profile": "catalog_object_profile",

    # adaptive_system_profile.py
    "ADAPTIVE_SYSTEM_ALLOWED_ASSET_EXTENSIONS": "adaptive_system_profile",
    "ADAPTIVE_SYSTEM_ALLOWED_PLACEMENT_MODES": "adaptive_system_profile",
    "ADAPTIVE_SYSTEM_DEFAULT_GRID_SIZE_CELLS": "adaptive_system_profile",
    "ADAPTIVE_SYSTEM_DEFAULT_MAX_MODEL_SIZE_MB": "adaptive_system_profile",
    "ADAPTIVE_SYSTEM_DEFAULT_MAX_PREVIEW_SIZE_MB": "adaptive_system_profile",
    "ADAPTIVE_SYSTEM_DEFAULT_MAX_TEXTURE_SIZE_MB": "adaptive_system_profile",
    "ADAPTIVE_SYSTEM_EXCLUDED_MODULES": "adaptive_system_profile",
    "ADAPTIVE_SYSTEM_OBJECT_KIND": "adaptive_system_profile",
    "ADAPTIVE_SYSTEM_OPTIONAL_DOCUMENTS": "adaptive_system_profile",
    "ADAPTIVE_SYSTEM_OPTIONAL_MODULES": "adaptive_system_profile",
    "ADAPTIVE_SYSTEM_PROFILE_KEY": "adaptive_system_profile",
    "ADAPTIVE_SYSTEM_PROFILE_SCHEMA_VERSION": "adaptive_system_profile",
    "ADAPTIVE_SYSTEM_RECOMMENDED_MODULES": "adaptive_system_profile",
    "ADAPTIVE_SYSTEM_RECOMMENDED_PLACEMENT_MODE": "adaptive_system_profile",
    "ADAPTIVE_SYSTEM_REQUIRED_DOCUMENTS": "adaptive_system_profile",
    "ADAPTIVE_SYSTEM_REQUIRED_MODULES": "adaptive_system_profile",
    "adaptive_system_asset_rules": "adaptive_system_profile",
    "adaptive_system_excluded_module_rules": "adaptive_system_profile",
    "adaptive_system_optional_document_rules": "adaptive_system_profile",
    "adaptive_system_optional_module_rules": "adaptive_system_profile",
    "adaptive_system_profile_to_dict": "adaptive_system_profile",
    "adaptive_system_recommended_module_rules": "adaptive_system_profile",
    "adaptive_system_required_document_rules": "adaptive_system_profile",
    "adaptive_system_required_module_rules": "adaptive_system_profile",
    "adaptive_system_validation_rules": "adaptive_system_profile",
    "assert_adaptive_system_profile_valid": "adaptive_system_profile",
    "build_adaptive_system_profile": "adaptive_system_profile",
    "get_adaptive_system_profile": "adaptive_system_profile",
    "validate_adaptive_system_profile": "adaptive_system_profile",

    # profile_resolver.py
    "PROFILE_RESOLVER_SCHEMA_VERSION": "profile_resolver",
    "ProfileRegistration": "profile_resolver",
    "ProfileResolverError": "profile_resolver",
    "ProfileResolverStatus": "profile_resolver",
    "all_profile_summaries": "profile_resolver",
    "all_profiles": "profile_resolver",
    "all_profiles_to_dict": "profile_resolver",
    "all_registrations_to_dict": "profile_resolver",
    "assert_profiles_ready": "profile_resolver",
    "clear_profile_resolver_caches": "profile_resolver",
    "get_profile_module_status": "profile_resolver",
    "get_profile_registration": "profile_resolver",
    "get_profile_registrations": "profile_resolver",
    "get_profile_resolver_health": "profile_resolver",
    "get_profile_resolver_statuses": "profile_resolver",
    "get_registered_object_kinds": "profile_resolver",
    "get_registered_profile_keys": "profile_resolver",
    "is_profile_registered": "profile_resolver",
    "profile_summary": "profile_resolver",
    "registration_to_dict": "profile_resolver",
    "resolve_profile": "profile_resolver",
    "resolve_profile_by_key": "profile_resolver",
    "try_resolve_profile": "profile_resolver",
    "try_resolve_profile_by_key": "profile_resolver",
}


@lru_cache(maxsize=64)
def _load_profile_module(module_key: str) -> ModuleType:
    """Lädt ein Profile-Modul lazy über relative Imports."""
    if module_key not in _RELATIVE_PROFILE_MODULES:
        raise ProfileImportError(f"Unknown VPLIB profile module {module_key!r}.")

    relative_path = _RELATIVE_PROFILE_MODULES[module_key]

    try:
        return importlib.import_module(relative_path, package=__name__)
    except Exception as exc:
        raise ProfileImportError(
            f"Could not import VPLIB profile module {module_key!r}: {exc}"
        ) from exc


def __getattr__(name: str) -> Any:
    """
    Lazy-Reexport für öffentliche Profile-Symbole.

    Beispiel:

        from vplib.profiles import resolve_profile
        from vplib.profiles import get_cell_block_profile
    """
    module_key = _SYMBOL_TO_MODULE.get(name)

    if not module_key:
        raise AttributeError(f"module {__name__!r} has no attribute {name!r}")

    module = _load_profile_module(module_key)

    try:
        value = getattr(module, name)
    except AttributeError as exc:
        raise ProfileImportError(
            f"Profile symbol {name!r} is mapped to module {module_key!r}, "
            f"but the module does not export it."
        ) from exc

    globals()[name] = value
    return value


def get_profile_module_keys() -> tuple[str, ...]:
    """Gibt alle bekannten Profile-Modulkeys zurück."""
    return tuple(_RELATIVE_PROFILE_MODULES.keys())


def get_profile_symbol_names() -> tuple[str, ...]:
    """Gibt alle lazy exportierten öffentlichen Symbolnamen zurück."""
    return tuple(sorted(_SYMBOL_TO_MODULE.keys()))


def get_profile_symbol_module_map() -> Mapping[str, str]:
    """Gibt die Symbol-zu-Modul-Zuordnung zurück."""
    return dict(_SYMBOL_TO_MODULE)


def is_profile_symbol(name: str) -> bool:
    """Gibt zurück, ob ein Symbol über dieses Package exportiert wird."""
    return name in _SYMBOL_TO_MODULE


def load_all_profile_modules() -> tuple[ModuleType, ...]:
    """
    Lädt alle Profile-Module.

    Nützlich für Tests, Startup-Diagnose oder strikte Entwicklungsprüfungen.
    """
    modules: list[ModuleType] = []

    for module_key in get_profile_module_keys():
        modules.append(_load_profile_module(module_key))

    return tuple(modules)


def get_profile_module_statuses() -> tuple[ProfileModuleStatus, ...]:
    """
    Gibt Importstatus für alle Profile-Module zurück.

    Diese Funktion wirft nicht, sondern sammelt Fehler in Statusobjekten.
    """
    statuses: list[ProfileModuleStatus] = []

    for module_key, relative_path in _RELATIVE_PROFILE_MODULES.items():
        exported_symbols = tuple(
            sorted(
                symbol
                for symbol, mapped_module_key in _SYMBOL_TO_MODULE.items()
                if mapped_module_key == module_key
            )
        )

        try:
            _load_profile_module(module_key)
            statuses.append(
                ProfileModuleStatus(
                    module_key=module_key,
                    module_path=relative_path,
                    loaded=True,
                    error=None,
                    exported_symbols=exported_symbols,
                )
            )
        except Exception as exc:
            statuses.append(
                ProfileModuleStatus(
                    module_key=module_key,
                    module_path=relative_path,
                    loaded=False,
                    error=str(exc),
                    exported_symbols=exported_symbols,
                )
            )

    return tuple(statuses)


def get_profiles_health() -> dict[str, Any]:
    """Gibt einen JSON-kompatiblen Health-Snapshot der Profile-Schicht zurück."""
    statuses = get_profile_module_statuses()

    resolver_health: dict[str, Any] | None = None
    try:
        resolver = _load_profile_module("profile_resolver")
        resolver_health_function = getattr(resolver, "get_profile_resolver_health", None)
        if callable(resolver_health_function):
            resolver_health = resolver_health_function()
    except Exception as exc:
        resolver_health = {
            "healthy": False,
            "error": str(exc),
        }

    return {
        "schema_version": PROFILES_PACKAGE_VERSION,
        "healthy": all(status.loaded for status in statuses)
        and bool(resolver_health and resolver_health.get("healthy", False)),
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
        "resolver": resolver_health,
    }


def assert_profiles_package_ready() -> None:
    """
    Prüft, ob alle Profile-Module und registrierten Profile ladbar sind.

    Raises:
        ProfileImportError: Wenn mindestens ein Modul oder Profil nicht ladbar ist.
    """
    statuses = get_profile_module_statuses()
    failed = [status for status in statuses if not status.loaded]

    if failed:
        details = "; ".join(
            f"{status.module_key}: {status.error}" for status in failed
        )
        raise ProfileImportError(f"VPLIB profile package is not ready: {details}")

    try:
        resolver = _load_profile_module("profile_resolver")
        assert_ready = getattr(resolver, "assert_profiles_ready")
        assert_ready()
    except Exception as exc:
        raise ProfileImportError(f"VPLIB registered profiles are not ready: {exc}") from exc


def clear_profile_caches() -> None:
    """
    Leert alle bekannten Profile-Caches.

    Diese Funktion ist bewusst defensiv. Wenn ein einzelnes Modul fehlt oder
    eine Clear-Funktion nicht existiert, wird weitergemacht.
    """
    _load_profile_module.cache_clear()

    clear_function_names = (
        "clear_base_profile_caches",
        "clear_cell_block_profile_caches",
        "clear_multi_cell_module_profile_caches",
        "clear_catalog_object_profile_caches",
        "clear_adaptive_system_profile_caches",
        "clear_profile_resolver_caches",
    )

    for module_key in get_profile_module_keys():
        try:
            module = _load_profile_module(module_key)
        except Exception:
            continue

        for function_name in clear_function_names:
            function = getattr(module, function_name, None)

            if callable(function):
                try:
                    function()
                except Exception:
                    continue


def profile_status_to_json(status: ProfileModuleStatus) -> dict[str, Any]:
    """Serialisiert einen ProfileModuleStatus JSON-kompatibel."""
    return {
        "schema_version": PROFILES_PACKAGE_VERSION,
        "module_key": status.module_key,
        "module_path": status.module_path,
        "loaded": status.loaded,
        "error": status.error,
        "exported_symbols": list(status.exported_symbols),
    }


def profile_statuses_to_json() -> list[dict[str, Any]]:
    """Serialisiert alle Profile-Modulstatuswerte JSON-kompatibel."""
    return [profile_status_to_json(status) for status in get_profile_module_statuses()]


__all__ = [
    "PROFILES_PACKAGE_VERSION",
    "ProfileImportError",
    "ProfileModuleStatus",
    "assert_profiles_package_ready",
    "clear_profile_caches",
    "get_profile_module_keys",
    "get_profile_module_statuses",
    "get_profile_symbol_module_map",
    "get_profile_symbol_names",
    "get_profiles_health",
    "is_profile_symbol",
    "load_all_profile_modules",
    "profile_status_to_json",
    "profile_statuses_to_json",
    *_SYMBOL_TO_MODULE.keys(),
]