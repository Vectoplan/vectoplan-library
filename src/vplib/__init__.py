# services/vectoplan-library/src/vplib/__init__.py
"""
Top-level public API for the VPLIB package engine.

Diese Datei bündelt die stabile öffentliche API für:

- defaults
- validators
- creators
- sources
- vplib_id_service

Der VPLIB-Kern unter src/vplib ist damit als internes Package nutzbar.

Typische Einstiegspunkte:

    from vplib import create_vplib
    from vplib import validate_vplib_documents
    from vplib import scan_vplib_sources
    from vplib import load_vplib_sources
    from vplib import build_full_document_bundle

Neue ID-Einstiegspunkte:

    from vplib import generate_vplib_uid
    from vplib import ensure_vplib_uid
    from vplib import validate_vplib_uid
    from vplib import ensure_mapping_vplib_uid

Diese Datei arbeitet bewusst mit Lazy Imports:
- Subpackages/Module werden erst geladen, wenn ein Symbol gebraucht wird.
- Ein defektes optionales Subpackage blockiert nicht direkt den Import von vplib.
- Health- und Ready-Funktionen prüfen den aktuellen Zustand gesammelt.
- Der neue VPLIB-ID-Service wird wie die übrigen Kernmodule lazy exportiert.

Technische Namen, JSON-Keys und Variablen bleiben Englisch.
"""

from __future__ import annotations

import importlib
from dataclasses import dataclass
from functools import lru_cache
from types import ModuleType
from typing import Any, Final, Mapping


VPLIB_PACKAGE_VERSION: Final[str] = "vplib.core.v1"


class VplibImportError(ImportError):
    """Wird ausgelöst, wenn ein VPLIB-Subpackage oder Symbol nicht geladen werden kann."""


@dataclass(frozen=True, slots=True)
class VplibModuleStatus:
    """Importstatus eines VPLIB-Subpackages oder VPLIB-Kernmoduls."""

    module_key: str
    module_path: str
    loaded: bool
    error: str | None
    health: Mapping[str, Any] | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema_version": VPLIB_PACKAGE_VERSION,
            "module_key": self.module_key,
            "module_path": self.module_path,
            "loaded": self.loaded,
            "error": self.error,
            "health": dict(self.health or {}),
        }


# ---------------------------------------------------------------------------
# Lazy module registry
# ---------------------------------------------------------------------------

# Canonical module keys.
# Wichtig:
# - "id_service" zeigt auf eine einzelne Datei, nicht auf ein Package.
# - Für die Lazy-API ist das egal; importlib kann beides laden.
_RELATIVE_SUBPACKAGES: Final[dict[str, str]] = {
    "defaults": ".defaults",
    "validators": ".validators",
    "creators": ".creators",
    "sources": ".sources",
    "id_service": ".vplib_id_service",
}

# Komfort-Aliase für direkte Modulimporte:
#
#     from vplib import ids
#     from vplib import vplib_id_service
#
# Beide zeigen auf dasselbe Modul wie "id_service".
_RELATIVE_SUBPACKAGE_ALIASES: Final[dict[str, str]] = {
    "ids": "id_service",
    "vplib_id_service": "id_service",
}

_HEALTH_FUNCTION_NAMES: Final[dict[str, str]] = {
    "defaults": "get_defaults_health",
    "validators": "get_validators_health",
    "creators": "get_creators_health",
    "sources": "get_sources_health",
    # vplib_id_service hat aktuell keine eigene Health-Funktion.
    # get_subpackage_health() behandelt das defensiv als healthy.
    "id_service": "get_vplib_id_service_health",
}

_CLEAR_FUNCTION_NAMES: Final[dict[str, str]] = {
    "defaults": "clear_defaults_caches",
    "validators": "clear_validator_caches",
    "creators": "clear_creator_caches",
    "sources": "clear_source_caches",
    # vplib_id_service braucht aktuell keine Cache-Clear-Funktion.
    # Falls später intern gecached wird, kann die Funktion dort ergänzt werden.
    "id_service": "clear_vplib_id_service_caches",
}


_SYMBOL_TO_MODULE: Final[dict[str, str]] = {
    # ---------------------------------------------------------------------
    # defaults
    # ---------------------------------------------------------------------
    "build_full_document_bundle": "defaults",
    "build_document_bundle_from_components": "defaults",
    "build_document_bundle_from_context": "defaults",
    "build_document_bundle_from_create_request": "defaults",
    "build_document_bundle_from_creation_plan": "defaults",
    "DocumentBundle": "defaults",
    "DocumentBundleItem": "defaults",
    "DocumentBundleOptions": "defaults",
    "DocumentBundleError": "defaults",
    "get_defaults_health": "defaults",
    "assert_defaults_ready": "defaults",
    "clear_defaults_caches": "defaults",

    # ---------------------------------------------------------------------
    # validators
    # ---------------------------------------------------------------------
    "validate_vplib_creation_plan": "validators",
    "validate_vplib_documents": "validators",
    "validate_vplib_document_bundle": "validators",
    "validate_vplib_schema_only": "validators",
    "validate_vplib_semantics_only": "validators",
    "validate_vplib_assets_only": "validators",
    "validate_package_creation_plan": "validators",
    "validate_package_documents": "validators",
    "validate_package_document_bundle": "validators",
    "PackageValidationOptions": "validators",
    "PackageValidationResult": "validators",
    "PackageValidatorError": "validators",
    "get_validators_health": "validators",
    "assert_validators_ready": "validators",
    "clear_validator_caches": "validators",

    # ---------------------------------------------------------------------
    # creators
    # ---------------------------------------------------------------------
    "create_vplib": "creators",
    "create_vplib_from_plan": "creators",
    "create_vplib_archive": "creators",
    "write_vplib_documents": "creators",
    "create_vplib_package_from_request": "creators",
    "create_vplib_package_from_plan": "creators",
    "create_vplib_package_from_bundle": "creators",
    "PackageCreationOptions": "creators",
    "PackageCreationResult": "creators",
    "PackageCreatorError": "creators",
    "get_creators_health": "creators",
    "assert_creators_ready": "creators",
    "clear_creator_caches": "creators",

    # ---------------------------------------------------------------------
    # sources
    # ---------------------------------------------------------------------
    "scan_vplib_sources": "sources",
    "load_vplib_sources": "sources",
    "load_vplib_scan_result": "sources",
    "source_candidate_to_bundle": "sources",
    "source_scan_result_to_bundles": "sources",
    "scan_source_root": "sources",
    "scan_source_package": "sources",
    "load_source_root_to_library": "sources",
    "load_source_candidate_to_library": "sources",
    "SourceScanOptions": "sources",
    "SourceScanResult": "sources",
    "SourceLoadOptions": "sources",
    "SourceLoadResult": "sources",
    "SourceScannerError": "sources",
    "SourceLoaderError": "sources",
    "get_sources_health": "sources",
    "assert_sources_ready": "sources",
    "clear_source_caches": "sources",

    # ---------------------------------------------------------------------
    # vplib_id_service
    # ---------------------------------------------------------------------
    "DEFAULT_GENERATION_ATTEMPTS": "id_service",
    "DEFAULT_UNIQUE_GENERATION_ATTEMPTS": "id_service",
    "NIL_UUID": "id_service",
    "UUID_CANONICAL_RE": "id_service",
    "VPLIB_UID_ALIASES": "id_service",
    "VPLIB_UID_FIELD": "id_service",
    "VPLIB_UID_GENERATOR_VERSION": "id_service",
    "VplibIdError": "id_service",
    "VplibIdGenerationContext": "id_service",
    "VplibIdGenerationError": "id_service",
    "VplibIdValidationError": "id_service",
    "VplibIdValidationResult": "id_service",
    "assert_same_vplib_uid": "id_service",
    "build_vplib_uid_payload_fragment": "id_service",
    "compare_vplib_uids": "id_service",
    "ensure_mapping_vplib_uid": "id_service",
    "ensure_vplib_uid": "id_service",
    "generate_unique_vplib_uid": "id_service",
    "generate_vplib_uid": "id_service",
    "get_vplib_uid_from_mapping": "id_service",
    "is_valid_vplib_uid": "id_service",
    "normalize_vplib_uid": "id_service",
    "remove_mapping_vplib_uid": "id_service",
    "require_vplib_uid_from_mapping": "id_service",
    "set_mapping_vplib_uid": "id_service",
    "validate_vplib_uid": "id_service",
    "validate_vplib_uid_result": "id_service",
}


def _canonical_module_key(module_key: str) -> str:
    """
    Normalisiert einen Modul-Key auf seinen kanonischen Key.

    Beispiele:
        ids              -> id_service
        vplib_id_service -> id_service
        defaults         -> defaults
    """
    try:
        key = str(module_key).strip()
    except Exception as exc:
        raise VplibImportError("Invalid VPLIB module key.") from exc

    if not key:
        raise VplibImportError("Empty VPLIB module key.")

    return _RELATIVE_SUBPACKAGE_ALIASES.get(key, key)


@lru_cache(maxsize=64)
def _load_subpackage(module_key: str) -> ModuleType:
    """Lädt ein VPLIB-Subpackage/Kernmodul lazy über relative Imports."""
    canonical_key = _canonical_module_key(module_key)

    if canonical_key not in _RELATIVE_SUBPACKAGES:
        raise VplibImportError(f"Unknown VPLIB subpackage/module {module_key!r}.")

    relative_path = _RELATIVE_SUBPACKAGES[canonical_key]

    try:
        return importlib.import_module(relative_path, package=__name__)
    except Exception as exc:
        raise VplibImportError(
            f"Could not import VPLIB subpackage/module "
            f"{canonical_key!r} from {relative_path!r}: {exc}"
        ) from exc


def __getattr__(name: str) -> Any:
    """
    Lazy-Reexport für öffentliche VPLIB-Symbole.

    Beispiele:
        from vplib import create_vplib
        from vplib import validate_vplib_documents
        from vplib import scan_vplib_sources
        from vplib import generate_vplib_uid
    """
    canonical_module_name = _RELATIVE_SUBPACKAGE_ALIASES.get(name, name)

    if canonical_module_name in _RELATIVE_SUBPACKAGES:
        module = _load_subpackage(canonical_module_name)
        globals()[name] = module
        return module

    module_key = _SYMBOL_TO_MODULE.get(name)

    if not module_key:
        raise AttributeError(f"module {__name__!r} has no attribute {name!r}")

    module = _load_subpackage(module_key)

    try:
        value = getattr(module, name)
    except AttributeError as exc:
        raise VplibImportError(
            f"VPLIB symbol {name!r} is mapped to module {module_key!r}, "
            f"but the module does not export it."
        ) from exc

    globals()[name] = value
    return value


# ---------------------------------------------------------------------------
# Public registry helpers
# ---------------------------------------------------------------------------


def get_vplib_subpackage_keys(*, include_aliases: bool = False) -> tuple[str, ...]:
    """
    Gibt alle bekannten VPLIB-Subpackage-/Modul-Keys zurück.

    Args:
        include_aliases:
            Wenn True, werden auch Komfort-Aliase wie "ids" ausgegeben.
    """
    keys = list(_RELATIVE_SUBPACKAGES.keys())

    if include_aliases:
        keys.extend(_RELATIVE_SUBPACKAGE_ALIASES.keys())

    return tuple(keys)


def get_vplib_symbol_names() -> tuple[str, ...]:
    """Gibt alle top-level lazy exportierten Symbolnamen zurück."""
    return tuple(sorted(_SYMBOL_TO_MODULE.keys()))


def get_vplib_symbol_module_map() -> Mapping[str, str]:
    """Gibt die Symbol-zu-Subpackage-/Modul-Zuordnung zurück."""
    return dict(_SYMBOL_TO_MODULE)


def get_vplib_module_alias_map() -> Mapping[str, str]:
    """Gibt die Alias-zu-Modul-Zuordnung zurück."""
    return dict(_RELATIVE_SUBPACKAGE_ALIASES)


def is_vplib_symbol(name: str) -> bool:
    """Gibt zurück, ob ein Symbol oder Modul-Key top-level exportiert wird."""
    try:
        key = str(name).strip()
    except Exception:
        return False

    if not key:
        return False

    return (
        key in _SYMBOL_TO_MODULE
        or key in _RELATIVE_SUBPACKAGES
        or key in _RELATIVE_SUBPACKAGE_ALIASES
    )


def load_all_vplib_subpackages() -> tuple[ModuleType, ...]:
    """
    Lädt alle kanonischen VPLIB-Subpackages/Kernmodule.

    Nützlich für Tests, Startup-Diagnose oder strikte Entwicklungsprüfungen.
    Aliase werden nicht doppelt geladen.
    """
    modules: list[ModuleType] = []

    for module_key in get_vplib_subpackage_keys(include_aliases=False):
        modules.append(_load_subpackage(module_key))

    return tuple(modules)


# ---------------------------------------------------------------------------
# Health / readiness
# ---------------------------------------------------------------------------


def get_vplib_module_statuses() -> tuple[VplibModuleStatus, ...]:
    """
    Gibt Importstatus für alle kanonischen VPLIB-Subpackages/Kernmodule zurück.

    Diese Funktion wirft nicht, sondern sammelt Fehler in Statusobjekten.
    """
    statuses: list[VplibModuleStatus] = []

    for module_key, relative_path in _RELATIVE_SUBPACKAGES.items():
        try:
            module = _load_subpackage(module_key)
            health = get_subpackage_health(module_key, module)
            statuses.append(
                VplibModuleStatus(
                    module_key=module_key,
                    module_path=relative_path,
                    loaded=True,
                    error=None,
                    health=health,
                )
            )
        except Exception as exc:
            statuses.append(
                VplibModuleStatus(
                    module_key=module_key,
                    module_path=relative_path,
                    loaded=False,
                    error=str(exc),
                    health=None,
                )
            )

    return tuple(statuses)


def get_subpackage_health(module_key: str, module: ModuleType) -> dict[str, Any]:
    """
    Liest Health-Payload eines Subpackages/Kernmoduls, falls vorhanden.

    Wenn ein Modul keine Health-Funktion exportiert, gilt es als healthy,
    solange es importiert werden konnte.
    """
    canonical_key = _canonical_module_key(module_key)
    function_name = _HEALTH_FUNCTION_NAMES.get(canonical_key)

    if not function_name:
        return {
            "healthy": True,
            "note": f"No health function configured for module {canonical_key!r}.",
        }

    function = getattr(module, function_name, None)
    if not callable(function):
        return {
            "healthy": True,
            "note": f"No health function {function_name!r} exported.",
        }

    try:
        payload = function()
        return normalize_metadata(payload if isinstance(payload, Mapping) else {"payload": payload})
    except Exception as exc:
        return {
            "healthy": False,
            "error": str(exc),
        }


def get_vplib_health() -> dict[str, Any]:
    """Gibt einen JSON-kompatiblen Health-Snapshot des VPLIB-Kerns zurück."""
    statuses = get_vplib_module_statuses()

    try:
        healthy = all(
            status.loaded and bool((status.health or {}).get("healthy", True))
            for status in statuses
        )
    except Exception:
        healthy = False

    return {
        "schema_version": VPLIB_PACKAGE_VERSION,
        "healthy": healthy,
        "subpackage_count": len(statuses),
        "loaded_subpackage_count": sum(1 for status in statuses if status.loaded),
        "symbol_count": len(_SYMBOL_TO_MODULE),
        "alias_count": len(_RELATIVE_SUBPACKAGE_ALIASES),
        "subpackages": [status.to_dict() for status in statuses],
        "aliases": get_vplib_module_alias_map(),
    }


def assert_vplib_ready() -> None:
    """
    Prüft, ob alle VPLIB-Subpackages/Kernmodule bereit sind.

    Raises:
        VplibImportError: Wenn mindestens ein Subpackage/Modul nicht importiert
        werden kann oder ein Healthcheck fehlschlägt.
    """
    statuses = get_vplib_module_statuses()
    failed: list[str] = []

    for status in statuses:
        if not status.loaded:
            failed.append(f"{status.module_key}: {status.error}")
            continue

        health = status.health or {}
        if health and health.get("healthy") is False:
            failed.append(f"{status.module_key}: {health.get('error') or 'unhealthy'}")

    if failed:
        raise VplibImportError("VPLIB package is not ready: " + "; ".join(failed))


def clear_vplib_caches() -> None:
    """
    Leert alle bekannten VPLIB-Caches.

    Diese Funktion ist defensiv. Wenn ein einzelnes Subpackage fehlt oder seine
    Clear-Funktion fehlschlägt, wird weitergemacht.
    """
    for module_key, function_name in _CLEAR_FUNCTION_NAMES.items():
        try:
            module = _load_subpackage(module_key)
            function = getattr(module, function_name, None)
            if callable(function):
                function()
        except Exception:
            continue

    try:
        _load_subpackage.cache_clear()
    except Exception:
        pass


# ---------------------------------------------------------------------------
# Serialization helpers
# ---------------------------------------------------------------------------


def vplib_status_to_json(status: VplibModuleStatus) -> dict[str, Any]:
    """Serialisiert einen VplibModuleStatus JSON-kompatibel."""
    return status.to_dict()


def vplib_statuses_to_json() -> list[dict[str, Any]]:
    """Serialisiert alle VPLIB-Subpackage-/Modul-Statuswerte JSON-kompatibel."""
    return [vplib_status_to_json(status) for status in get_vplib_module_statuses()]


def normalize_metadata(value: Mapping[str, Any] | None) -> dict[str, Any]:
    """Normalisiert Metadata JSON-kompatibel."""
    if value is None:
        return {}

    if not isinstance(value, Mapping):
        return {"value": str(value)}

    normalized: dict[str, Any] = {}

    for key, child_value in value.items():
        try:
            normalized[str(key)] = normalize_metadata_value(child_value)
        except Exception as exc:
            normalized[str(key)] = f"<metadata-normalization-error: {exc}>"

    return normalized


def normalize_metadata_value(value: Any) -> Any:
    """Normalisiert Metadata-Werte JSON-kompatibel."""
    if value is None:
        return None

    if isinstance(value, (str, int, float, bool)):
        return value

    if isinstance(value, Mapping):
        return normalize_metadata(value)

    if isinstance(value, (list, tuple, set)):
        result: list[Any] = []
        for item in value:
            try:
                result.append(normalize_metadata_value(item))
            except Exception as exc:
                result.append(f"<metadata-normalization-error: {exc}>")
        return result

    return str(value)


__version__ = VPLIB_PACKAGE_VERSION

__all__ = [
    "VPLIB_PACKAGE_VERSION",
    "VplibImportError",
    "VplibModuleStatus",
    "__version__",
    "assert_vplib_ready",
    "clear_vplib_caches",
    "get_subpackage_health",
    "get_vplib_health",
    "get_vplib_module_alias_map",
    "get_vplib_module_statuses",
    "get_vplib_subpackage_keys",
    "get_vplib_symbol_module_map",
    "get_vplib_symbol_names",
    "is_vplib_symbol",
    "load_all_vplib_subpackages",
    "normalize_metadata",
    "normalize_metadata_value",
    "vplib_status_to_json",
    "vplib_statuses_to_json",
    "defaults",
    "validators",
    "creators",
    "sources",
    "id_service",
    "ids",
    "vplib_id_service",
    *_SYMBOL_TO_MODULE.keys(),
]