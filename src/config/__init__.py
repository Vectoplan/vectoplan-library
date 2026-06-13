# services/vectoplan-library/src/config/__init__.py
"""
Config Package für den VECTOPLAN Library Microservice.

Dieses Package bündelt die zentralen Konfigurationsmodule:

- `vplib_settings.py`
  Bestehende VPLIB-Core-Konfiguration für:
    - VPLIB-Routen
    - Creator
    - Teststrecken
    - generierte Pakete
    - Archive
    - Runtime-Verzeichnisse

- `library_settings.py`
  Neue Creative-Library-Konfiguration für:
    - src/library/source
    - Creative-Library-Scanner
    - Taxonomie-Reiter/Kategorie/Subkategorie
    - Library-Routen
    - Library-Read-Models
    - Library-Scan-Cache

Diese Datei ist bewusst defensiv:

- keine Flask-Abhängigkeit
- kein Scan beim Import
- keine Directory-Erzeugung beim Import
- kein Dateisystem-Schreiben beim Import
- kein Taxonomie-JSON-Load beim Import
- Lazy-Imports
- robuste Health-Funktion
- zentrale Cache-Reset-Funktionen

Version 0.2.0:

- `library_settings.py` wird als eigenes Konfigurationsmodul registriert.
- `vplib_settings.py` bleibt vollständig kompatibel.
- Zentrale Health-Funktion für beide Config-Welten.
- Zentrale Cache-Clear-Funktion für Settings-Caches.
- Lazy-Reexports für häufig genutzte Settings-Funktionen.
"""

from __future__ import annotations

import importlib
import traceback
from dataclasses import asdict, dataclass, field, is_dataclass
from datetime import datetime, timezone
from threading import RLock
from types import ModuleType
from typing import Any, Final, Iterable, Mapping


# ---------------------------------------------------------------------------
# Package metadata
# ---------------------------------------------------------------------------

CONFIG_PACKAGE_VERSION: Final[str] = "0.2.0"
CONFIG_PACKAGE_NAME: Final[str] = "config"
CONFIG_COMPONENT_NAME: Final[str] = "vectoplan-config"

CONFIG_MODULES: Final[tuple[str, ...]] = (
    "vplib_settings",
    "library_settings",
)

REQUIRED_CONFIG_MODULES: Final[tuple[str, ...]] = (
    "vplib_settings",
    "library_settings",
)

OPTIONAL_CONFIG_MODULES: Final[tuple[str, ...]] = ()


# ---------------------------------------------------------------------------
# Symbol registry
# ---------------------------------------------------------------------------

SYMBOL_TO_MODULE: Final[dict[str, str]] = {
    # -----------------------------------------------------------------------
    # vplib_settings.py - primary constants/classes/functions
    # -----------------------------------------------------------------------
    "VPLIB_SETTINGS_SCHEMA_VERSION": "vplib_settings",
    "ENV_PREFIX": "vplib_settings",
    "DEFAULT_SERVICE_NAME": "vplib_settings",
    "DEFAULT_RUNTIME_MODE": "vplib_settings",
    "DEFAULT_ROUTE_PREFIX": "vplib_settings",
    "DEFAULT_WRITE_MODE": "vplib_settings",
    "DEFAULT_VALIDATION_MODE": "vplib_settings",
    "DEFAULT_PACKAGE_DIR_PATTERN": "vplib_settings",
    "VplibSettingsError": "vplib_settings",
    "VplibRuntimeMode": "vplib_settings",
    "VplibWriteMode": "vplib_settings",
    "VplibValidationMode": "vplib_settings",
    "VplibDirectoryRole": "vplib_settings",
    "VplibDirectoryEnsureStatus": "vplib_settings",
    "VplibDirectoryPlanItem": "vplib_settings",
    "VplibDirectoryEnsureResult": "vplib_settings",
    "VplibDirectoryEnsureBatchResult": "vplib_settings",
    "VplibSettings": "vplib_settings",
    "build_vplib_settings_from_env": "vplib_settings",
    "get_vplib_settings": "vplib_settings",
    "reload_vplib_settings": "vplib_settings",
    "get_vplib_settings_health": "vplib_settings",
    "ensure_vplib_runtime_directories": "vplib_settings",
    "ensure_directory_item": "vplib_settings",
    "clear_vplib_settings_cache": "vplib_settings",

    # -----------------------------------------------------------------------
    # library_settings.py - primary constants/classes/functions
    # -----------------------------------------------------------------------
    "LIBRARY_SETTINGS_VERSION": "library_settings",
    "LIBRARY_SETTINGS_COMPONENT": "library_settings",
    "DEFAULT_LIBRARY_ROUTE_PREFIX": "library_settings",
    "DEFAULT_HEALTH_ROUTE_PATH": "library_settings",
    "DEFAULT_SCAN_ROUTE_PATH": "library_settings",
    "DEFAULT_BLOCKS_ROUTE_PATH": "library_settings",
    "DEFAULT_TREE_ROUTE_PATH": "library_settings",
    "DEFAULT_CACHE_CLEAR_ROUTE_PATH": "library_settings",
    "DEFAULT_BLOCK_DETAIL_ROUTE_TEMPLATE": "library_settings",
    "DEFAULT_BLOCK_VARIANTS_ROUTE_TEMPLATE": "library_settings",
    "DEFAULT_SOURCE_DIRECTORY_RELATIVE": "library_settings",
    "DEFAULT_LIBRARY_PACKAGE_DIRECTORY_RELATIVE": "library_settings",
    "DEFAULT_CREATIVE_LIBRARY_DIRECTORY_RELATIVE": "library_settings",
    "DEFAULT_GENERATED_LIBRARY_DIRECTORY_RELATIVE": "library_settings",
    "DEFAULT_LIBRARY_CACHE_DIRECTORY_RELATIVE": "library_settings",
    "CANONICAL_SOURCE_DEPTH": "library_settings",
    "LEGACY_SOURCE_DEPTH": "library_settings",
    "CANONICAL_SOURCE_PATH_PATTERN": "library_settings",
    "LEGACY_SOURCE_PATH_PATTERN": "library_settings",
    "DEFAULT_ALLOWED_MANIFEST_FILENAMES": "library_settings",
    "DEFAULT_REQUIRED_PACKAGE_FILES": "library_settings",
    "DEFAULT_OPTIONAL_SUMMARY_FILES": "library_settings",
    "DEFAULT_IGNORED_DIRECTORY_NAMES": "library_settings",
    "DEFAULT_IGNORED_FILE_SUFFIXES": "library_settings",
    "LibraryDirectoryPlan": "library_settings",
    "LibraryRoutePlan": "library_settings",
    "LibraryTaxonomyOptions": "library_settings",
    "LibraryScanOptions": "library_settings",
    "LibraryReadOptions": "library_settings",
    "LibraryCacheOptions": "library_settings",
    "LibrarySettings": "library_settings",
    "DirectoryStatus": "library_settings",
    "build_library_settings": "library_settings",
    "get_library_settings": "library_settings",
    "reset_library_settings_cache": "library_settings",
    "get_library_directory_plan": "library_settings",
    "get_library_route_plan": "library_settings",
    "get_library_taxonomy_options": "library_settings",
    "get_library_scan_options": "library_settings",
    "get_library_read_options": "library_settings",
    "get_library_cache_options": "library_settings",
    "get_source_root": "library_settings",
    "get_creative_library_root": "library_settings",
    "get_taxonomy_root": "library_settings",
    "get_library_route_prefix": "library_settings",
    "get_library_route_prefix_safe": "library_settings",
    "get_settings_summary": "library_settings",
    "check_library_directories": "library_settings",
    "ensure_library_directories": "library_settings",
    "get_library_settings_health": "library_settings",
    "assert_library_settings_ready": "library_settings",
}


# ---------------------------------------------------------------------------
# Internal import cache
# ---------------------------------------------------------------------------

_IMPORT_CACHE_LOCK = RLock()
_MODULE_CACHE: dict[str, ModuleType] = {}


# ---------------------------------------------------------------------------
# Dataclasses
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class ConfigModuleStatus:
    """Importstatus eines Config-Submoduls."""

    name: str
    import_path: str
    loaded: bool
    status: str
    required: bool = False
    optional: bool = False
    symbol_count: int = 0
    exported_symbols: tuple[str, ...] = field(default_factory=tuple)
    error: dict[str, Any] | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "import_path": self.import_path,
            "loaded": self.loaded,
            "status": self.status,
            "required": self.required,
            "optional": self.optional,
            "symbol_count": self.symbol_count,
            "exported_symbols": list(self.exported_symbols),
            "error": json_safe(self.error),
        }


@dataclass(frozen=True)
class ConfigHealth:
    """Health-Modell für das Config-Package."""

    ok: bool
    healthy: bool
    package: str
    component: str
    version: str
    generated_at: str
    module_count: int
    loaded_module_count: int
    failed_module_count: int
    required_module_count: int
    loaded_required_module_count: int
    optional_module_count: int
    loaded_optional_module_count: int
    symbol_count: int
    modules: dict[str, dict[str, Any]]
    subhealth: dict[str, dict[str, Any]] = field(default_factory=dict)
    settings_summary: dict[str, Any] = field(default_factory=dict)
    warnings: tuple[str, ...] = field(default_factory=tuple)
    errors: tuple[str, ...] = field(default_factory=tuple)

    def to_dict(self) -> dict[str, Any]:
        return {
            "ok": self.ok,
            "healthy": self.healthy,
            "package": self.package,
            "component": self.component,
            "version": self.version,
            "generated_at": self.generated_at,
            "module_count": self.module_count,
            "loaded_module_count": self.loaded_module_count,
            "failed_module_count": self.failed_module_count,
            "required_module_count": self.required_module_count,
            "loaded_required_module_count": self.loaded_required_module_count,
            "optional_module_count": self.optional_module_count,
            "loaded_optional_module_count": self.loaded_optional_module_count,
            "symbol_count": self.symbol_count,
            "modules": json_safe(self.modules),
            "subhealth": json_safe(self.subhealth),
            "settings_summary": json_safe(self.settings_summary),
            "warnings": list(self.warnings),
            "errors": list(self.errors),
        }


# ---------------------------------------------------------------------------
# Generic helpers
# ---------------------------------------------------------------------------

def utc_now_iso() -> str:
    """UTC-Zeit im ISO-Format."""
    try:
        return datetime.now(timezone.utc).isoformat()
    except Exception:
        return datetime.utcnow().replace(tzinfo=timezone.utc).isoformat()


def exception_to_dict(
    exc: BaseException | None,
    *,
    include_traceback: bool = False,
) -> dict[str, Any] | None:
    """Serialisiert Exceptions JSON-kompatibel."""
    if exc is None:
        return None

    try:
        data: dict[str, Any] = {
            "type": exc.__class__.__name__,
            "message": str(exc),
        }

        if include_traceback:
            data["traceback"] = traceback.format_exception(
                type(exc),
                exc,
                exc.__traceback__,
            )

        return data

    except Exception as serialization_exc:
        return {
            "type": "ExceptionSerializationError",
            "message": str(serialization_exc),
            "original_type": str(type(exc)),
        }


def json_safe(value: Any) -> Any:
    """Defensiver JSON-Safe-Konverter."""
    try:
        if value is None:
            return None

        if isinstance(value, (str, int, float, bool)):
            return value

        if is_dataclass(value):
            return json_safe(asdict(value))

        if isinstance(value, Mapping):
            return {
                str(key): json_safe(item)
                for key, item in value.items()
            }

        if isinstance(value, (list, tuple, set)):
            return [json_safe(item) for item in value]

        if isinstance(value, ModuleType):
            return {
                "module": value.__name__,
                "file": getattr(value, "__file__", None),
            }

        to_dict = getattr(value, "to_dict", None)
        if callable(to_dict):
            try:
                return json_safe(to_dict())
            except TypeError:
                return json_safe(to_dict(flat=True))

        return str(value)

    except Exception as exc:
        return {
            "serialization_error": exception_to_dict(exc),
            "fallback_type": str(type(value)),
        }


def dataclass_to_dict_safe(value: Any) -> dict[str, Any]:
    """Defensive Dataclass-/Mapping-Serialisierung."""
    try:
        if hasattr(value, "to_dict") and callable(value.to_dict):
            raw = value.to_dict()
            return dict(raw) if isinstance(raw, Mapping) else {"value": json_safe(raw)}
    except Exception:
        pass

    try:
        if is_dataclass(value):
            return json_safe(asdict(value))
    except Exception:
        pass

    if isinstance(value, Mapping):
        return dict(json_safe(value))

    return {"value": str(value)}


def safe_tuple(value: Any) -> tuple[Any, ...]:
    """Normalisiert Werte defensiv zu tuple."""
    if value is None:
        return ()

    if isinstance(value, tuple):
        return value

    if isinstance(value, str):
        return (value,)

    if isinstance(value, Iterable):
        try:
            return tuple(value)
        except Exception:
            return ()

    return (value,)


def build_module_import_path(module_name: str) -> str:
    """Baut den vollständigen Importpfad eines Config-Submoduls."""
    return f"{__name__}.{module_name}"


def _status_is_healthy(payload: Mapping[str, Any]) -> bool:
    """Defensiver Health-Flag-Leser."""
    try:
        if "healthy" in payload:
            return bool(payload.get("healthy"))

        if "ok" in payload:
            return bool(payload.get("ok"))

        return False
    except Exception:
        return False


# ---------------------------------------------------------------------------
# Import cache / module loading
# ---------------------------------------------------------------------------

def clear_config_import_cache() -> None:
    """Leert den lokalen Lazy-Import-Cache dieses Packages."""
    with _IMPORT_CACHE_LOCK:
        _MODULE_CACHE.clear()

    for symbol_name in tuple(SYMBOL_TO_MODULE.keys()):
        globals().pop(symbol_name, None)


def safe_import_module(
    module_name: str,
    *,
    include_traceback: bool = False,
    force_reload: bool = False,
) -> tuple[ModuleType | None, ConfigModuleStatus]:
    """
    Importiert ein Config-Submodul defensiv.

    Rückgabe:
      (module, status)
    """
    import_path = build_module_import_path(module_name)
    required = module_name in REQUIRED_CONFIG_MODULES
    optional = module_name in OPTIONAL_CONFIG_MODULES

    try:
        with _IMPORT_CACHE_LOCK:
            if not force_reload and module_name in _MODULE_CACHE:
                module = _MODULE_CACHE[module_name]
            else:
                module = importlib.import_module(import_path)
                _MODULE_CACHE[module_name] = module

        exported_symbols = tuple(
            str(symbol)
            for symbol in safe_tuple(getattr(module, "__all__", ()))
        )

        return module, ConfigModuleStatus(
            name=module_name,
            import_path=import_path,
            loaded=True,
            status="loaded",
            required=required,
            optional=optional,
            symbol_count=len(exported_symbols),
            exported_symbols=exported_symbols,
            error=None,
        )

    except Exception as exc:
        return None, ConfigModuleStatus(
            name=module_name,
            import_path=import_path,
            loaded=False,
            status="error",
            required=required,
            optional=optional,
            symbol_count=0,
            exported_symbols=(),
            error=exception_to_dict(exc, include_traceback=include_traceback),
        )


def get_config_module(module_name: str) -> ModuleType | None:
    """Gibt ein Config-Submodul zurück, falls es importierbar ist."""
    if module_name not in CONFIG_MODULES:
        return None

    module, _ = safe_import_module(module_name)
    return module


def get_vplib_settings_module() -> ModuleType | None:
    return get_config_module("vplib_settings")


def get_library_settings_module() -> ModuleType | None:
    return get_config_module("library_settings")


# ---------------------------------------------------------------------------
# Runtime cache clearing
# ---------------------------------------------------------------------------

def clear_config_runtime_caches() -> dict[str, Any]:
    """
    Leert bekannte Settings-Laufzeit-Caches.

    Diese Funktion führt keine Directory-Erzeugung aus.
    """
    cleared: dict[str, Any] = {
        "vplib_settings": False,
        "library_settings": False,
        "errors": [],
    }

    try:
        module, status = safe_import_module("vplib_settings")
        if module is not None:
            clear_fn = getattr(module, "clear_vplib_settings_cache", None)
            if callable(clear_fn):
                clear_fn()
                cleared["vplib_settings"] = True
        else:
            cleared["errors"].append(status.error)
    except Exception as exc:
        cleared["errors"].append(exception_to_dict(exc))

    try:
        module, status = safe_import_module("library_settings")
        if module is not None:
            clear_fn = getattr(module, "reset_library_settings_cache", None)
            if callable(clear_fn):
                clear_fn()
                cleared["library_settings"] = True
        else:
            cleared["errors"].append(status.error)
    except Exception as exc:
        cleared["errors"].append(exception_to_dict(exc))

    return cleared


def clear_config_caches() -> dict[str, Any]:
    """
    Leert Import- und Runtime-Caches der Config-Schicht.
    """
    runtime = clear_config_runtime_caches()
    clear_config_import_cache()

    return {
        "ok": not runtime.get("errors"),
        "runtime": runtime,
        "import_cache_cleared": True,
    }


# ---------------------------------------------------------------------------
# Health
# ---------------------------------------------------------------------------

def get_config_module_status(
    *,
    include_traceback: bool = False,
    force_reload: bool = False,
) -> dict[str, dict[str, Any]]:
    """Liefert den Importstatus aller Config-Submodule."""
    statuses: dict[str, dict[str, Any]] = {}

    for module_name in CONFIG_MODULES:
        _, status = safe_import_module(
            module_name,
            include_traceback=include_traceback,
            force_reload=force_reload,
        )
        statuses[module_name] = status.to_dict()

    return statuses


def get_config_subhealth(
    *,
    include_traceback: bool = False,
    force_reload: bool = False,
) -> dict[str, dict[str, Any]]:
    """Ruft Health-Funktionen der Config-Submodule auf."""
    subhealth: dict[str, dict[str, Any]] = {}

    health_functions = {
        "vplib_settings": "get_vplib_settings_health",
        "library_settings": "get_library_settings_health",
    }

    for module_name, function_name in health_functions.items():
        try:
            module, status = safe_import_module(
                module_name,
                include_traceback=include_traceback,
                force_reload=force_reload,
            )

            if module is None:
                subhealth[module_name] = {
                    "ok": False,
                    "healthy": False,
                    "status": "import_error",
                    "required": module_name in REQUIRED_CONFIG_MODULES,
                    "optional": module_name in OPTIONAL_CONFIG_MODULES,
                    "error": status.error,
                }
                continue

            health_function = getattr(module, function_name, None)

            if not callable(health_function):
                subhealth[module_name] = {
                    "ok": False,
                    "healthy": False,
                    "status": "missing_health_function",
                    "required": module_name in REQUIRED_CONFIG_MODULES,
                    "optional": module_name in OPTIONAL_CONFIG_MODULES,
                    "function": function_name,
                }
                continue

            try:
                health = health_function()
            except TypeError:
                health = health_function(refresh=force_reload)

            health_payload = dataclass_to_dict_safe(health)
            health_payload.setdefault("required", module_name in REQUIRED_CONFIG_MODULES)
            health_payload.setdefault("optional", module_name in OPTIONAL_CONFIG_MODULES)
            subhealth[module_name] = health_payload

        except Exception as exc:
            subhealth[module_name] = {
                "ok": False,
                "healthy": False,
                "status": "health_error",
                "required": module_name in REQUIRED_CONFIG_MODULES,
                "optional": module_name in OPTIONAL_CONFIG_MODULES,
                "error": exception_to_dict(exc, include_traceback=include_traceback),
            }

    return subhealth


def get_combined_settings_summary(*, refresh: bool = False) -> dict[str, Any]:
    """
    Liefert eine kompakte Zusammenfassung beider Settings-Welten.

    Keine Directory-Erzeugung, kein Scan.
    """
    result: dict[str, Any] = {
        "ok": True,
        "generated_at": utc_now_iso(),
        "vplib": None,
        "library": None,
        "errors": [],
    }

    try:
        module, status = safe_import_module("vplib_settings", force_reload=refresh)
        if module is None:
            result["ok"] = False
            result["errors"].append(status.error)
        else:
            get_settings = getattr(module, "get_vplib_settings", None)
            if callable(get_settings):
                result["vplib"] = json_safe(get_settings().to_dict())
            else:
                result["ok"] = False
                result["errors"].append({"message": "get_vplib_settings is unavailable"})
    except Exception as exc:
        result["ok"] = False
        result["errors"].append(exception_to_dict(exc))

    try:
        module, status = safe_import_module("library_settings", force_reload=refresh)
        if module is None:
            result["ok"] = False
            result["errors"].append(status.error)
        else:
            get_summary = getattr(module, "get_settings_summary", None)
            if callable(get_summary):
                result["library"] = json_safe(get_summary(refresh=refresh))
            else:
                result["ok"] = False
                result["errors"].append({"message": "get_settings_summary is unavailable"})
    except Exception as exc:
        result["ok"] = False
        result["errors"].append(exception_to_dict(exc))

    return result


def get_config_health(
    *,
    include_traceback: bool = False,
    include_subhealth: bool = True,
    force_reload: bool = False,
) -> dict[str, Any]:
    """
    Liefert einen robusten Health-Status der Config-Schicht.

    Diese Funktion führt keinen Scan aus und legt keine Verzeichnisse an.
    """
    module_statuses = get_config_module_status(
        include_traceback=include_traceback,
        force_reload=force_reload,
    )

    loaded_modules = [
        name
        for name, status in module_statuses.items()
        if status.get("loaded") is True
    ]

    failed_modules = [
        name
        for name, status in module_statuses.items()
        if status.get("loaded") is not True
    ]

    loaded_required_modules = [
        name
        for name in REQUIRED_CONFIG_MODULES
        if name in loaded_modules
    ]

    loaded_optional_modules = [
        name
        for name in OPTIONAL_CONFIG_MODULES
        if name in loaded_modules
    ]

    warnings: list[str] = []
    errors: list[str] = []

    for module_name in failed_modules:
        if module_name in REQUIRED_CONFIG_MODULES:
            errors.append(f"required config module failed to import: {module_name}")
        else:
            warnings.append(f"optional config module failed to import: {module_name}")

    missing_required = [
        name
        for name in REQUIRED_CONFIG_MODULES
        if name not in loaded_required_modules
    ]

    for module_name in missing_required:
        errors.append(f"required config module is not loaded: {module_name}")

    symbol_count = 0
    for status in module_statuses.values():
        try:
            symbol_count += int(status.get("symbol_count", 0))
        except Exception:
            continue

    subhealth: dict[str, dict[str, Any]] = {}

    if include_subhealth:
        subhealth = get_config_subhealth(
            include_traceback=include_traceback,
            force_reload=force_reload,
        )

        for name, health in subhealth.items():
            healthy = _status_is_healthy(health)

            if not healthy:
                if name in REQUIRED_CONFIG_MODULES:
                    errors.append(f"required config subhealth failed: {name}")
                else:
                    warnings.append(f"optional config subhealth failed: {name}")

    settings_summary = get_combined_settings_summary(refresh=force_reload)

    if not settings_summary.get("ok"):
        errors.append("combined settings summary failed")

    healthy = len(errors) == 0

    health = ConfigHealth(
        ok=healthy,
        healthy=healthy,
        package=CONFIG_PACKAGE_NAME,
        component=CONFIG_COMPONENT_NAME,
        version=CONFIG_PACKAGE_VERSION,
        generated_at=utc_now_iso(),
        module_count=len(CONFIG_MODULES),
        loaded_module_count=len(loaded_modules),
        failed_module_count=len(failed_modules),
        required_module_count=len(REQUIRED_CONFIG_MODULES),
        loaded_required_module_count=len(loaded_required_modules),
        optional_module_count=len(OPTIONAL_CONFIG_MODULES),
        loaded_optional_module_count=len(loaded_optional_modules),
        symbol_count=symbol_count,
        modules=module_statuses,
        subhealth=subhealth,
        settings_summary=settings_summary,
        warnings=tuple(warnings),
        errors=tuple(errors),
    )

    return health.to_dict()


def is_config_healthy() -> bool:
    """Boolescher Health-Check."""
    try:
        return bool(get_config_health().get("healthy"))
    except Exception:
        return False


def assert_config_ready() -> None:
    """Wirft RuntimeError, wenn die Config-Schicht nicht bereit ist."""
    health = get_config_health()

    if health.get("healthy"):
        return

    raise RuntimeError(
        f"config package is not ready: errors={health.get('errors')}"
    )


# ---------------------------------------------------------------------------
# Lazy re-export API
# ---------------------------------------------------------------------------

def load_config_symbol(symbol_name: str) -> Any:
    """Lädt ein bekanntes Config-Symbol aus seinem Zielmodul."""
    module_name = SYMBOL_TO_MODULE.get(symbol_name)

    if not module_name:
        raise AttributeError(f"module {__name__!r} has no attribute {symbol_name!r}")

    module, status = safe_import_module(module_name)

    if module is None:
        raise ImportError(
            f"could not import config module {module_name!r}: {status.error}"
        )

    try:
        value = getattr(module, symbol_name)
    except AttributeError as exc:
        raise AttributeError(
            f"config symbol {symbol_name!r} not found in module {module.__name__!r}"
        ) from exc

    globals()[symbol_name] = value

    return value


def preload_config_symbols(
    *,
    fail_fast: bool = False,
) -> dict[str, Any]:
    """
    Lädt alle bekannten Reexport-Symbole vor.

    Standard:
      fail_fast=False
    """
    loaded: dict[str, str] = {}
    errors: dict[str, dict[str, Any] | None] = {}

    for symbol_name in SYMBOL_TO_MODULE:
        try:
            value = load_config_symbol(symbol_name)
            loaded[symbol_name] = f"{getattr(value, '__module__', '')}.{getattr(value, '__name__', symbol_name)}"
        except Exception as exc:
            errors[symbol_name] = exception_to_dict(exc)

            if fail_fast:
                raise

    return {
        "ok": not errors,
        "loaded": loaded,
        "errors": errors,
        "loaded_count": len(loaded),
        "error_count": len(errors),
    }


def __getattr__(name: str) -> Any:
    """Lazy-Reexport bekannter Config-Symbole und Submodule."""
    if name in SYMBOL_TO_MODULE:
        return load_config_symbol(name)

    if name in CONFIG_MODULES:
        module, status = safe_import_module(name)
        if module is None:
            raise ImportError(
                f"could not import config module {name!r}: {status.error}"
            )
        globals()[name] = module
        return module

    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")


def __dir__() -> list[str]:
    """Ergänzt Lazy-Reexport-Symbole in `dir(config)`."""
    names = set(globals().keys())
    names.update(SYMBOL_TO_MODULE.keys())
    names.update(CONFIG_MODULES)
    return sorted(names)


# ---------------------------------------------------------------------------
# Convenience wrappers
# ---------------------------------------------------------------------------

def library_settings_summary(*, refresh: bool = False) -> dict[str, Any]:
    """Direkter Wrapper für `library_settings.get_settings_summary`."""
    module, status = safe_import_module("library_settings", force_reload=refresh)

    if module is None:
        return {
            "ok": False,
            "status": "error",
            "error": status.error,
        }

    fn = getattr(module, "get_settings_summary", None)

    if not callable(fn):
        return {
            "ok": False,
            "status": "error",
            "error": {"message": "get_settings_summary is unavailable"},
        }

    return fn(refresh=refresh)


def vplib_settings_summary(*, refresh: bool = False) -> dict[str, Any]:
    """Direkter Wrapper für `vplib_settings.get_vplib_settings`."""
    module, status = safe_import_module("vplib_settings", force_reload=refresh)

    if module is None:
        return {
            "ok": False,
            "status": "error",
            "error": status.error,
        }

    if refresh:
        reload_fn = getattr(module, "reload_vplib_settings", None)
        if callable(reload_fn):
            settings = reload_fn()
        else:
            settings = getattr(module, "get_vplib_settings")()
    else:
        settings = getattr(module, "get_vplib_settings")()

    return {
        "ok": True,
        "settings": json_safe(settings.to_dict() if hasattr(settings, "to_dict") else settings),
    }


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

__all__: Final[tuple[str, ...]] = (
    "CONFIG_PACKAGE_VERSION",
    "CONFIG_PACKAGE_NAME",
    "CONFIG_COMPONENT_NAME",
    "CONFIG_MODULES",
    "REQUIRED_CONFIG_MODULES",
    "OPTIONAL_CONFIG_MODULES",
    "SYMBOL_TO_MODULE",
    "ConfigModuleStatus",
    "ConfigHealth",
    "utc_now_iso",
    "exception_to_dict",
    "json_safe",
    "dataclass_to_dict_safe",
    "safe_tuple",
    "build_module_import_path",
    "clear_config_import_cache",
    "clear_config_runtime_caches",
    "clear_config_caches",
    "safe_import_module",
    "get_config_module",
    "get_vplib_settings_module",
    "get_library_settings_module",
    "get_config_module_status",
    "get_config_subhealth",
    "get_combined_settings_summary",
    "get_config_health",
    "is_config_healthy",
    "assert_config_ready",
    "load_config_symbol",
    "preload_config_symbols",
    "library_settings_summary",
    "vplib_settings_summary",
    # Reexported config symbols
    *tuple(SYMBOL_TO_MODULE.keys()),
)