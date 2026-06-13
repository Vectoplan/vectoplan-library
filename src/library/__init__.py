# services/vectoplan-library/src/library/__init__.py
"""
VECTOPLAN Library Package.

Diese Package-Schicht bildet die fachliche Creative-Library-Ebene über dem
bestehenden VPLIB-Kern.

Wichtige Trennung:

- `src/vplib`
  Technischer VPLIB-Kern:
  Defaults, Validatoren, Creator, Source-Scanner, Loader, Archive.

- `src/library`
  Fachliche Library-Schicht:
  Taxonomie, Block-/Objekt-Katalog, Source-Scan-Orchestrierung,
  Validierung, Read-Modelle, API-taugliche Creative-Library-Ansichten,
  Create-Flow, DB-Sync-Vorbereitung und produktive Published-DB-Lesepfade.

Diese Datei ist bewusst robust und side-effect-arm gehalten:

- kein automatisches Erzeugen von Ordnern
- kein automatischer Scan beim Import
- kein Dateilesen beim Import
- kein Taxonomie-JSON-Load beim Import
- keine Datenbankverbindung beim Import
- keine harte Abhängigkeit auf optionale Subpackages
- sichere Health-/Status-Funktionen für Startup, Routes und Tests
- Lazy-Imports für Subpackages
- zentrale Cache-Clear-Helfer

Taxonomie-Regel:

    Backend-Taxonomie ist kanonisch für:
    - Domain/Reiter
    - Kategorie
    - Subkategorie
    - Source-Pfad
    - Navigation
    - Labels
    - Sortierung

DB-/Publication-Regel:

    vplib_uid ist die stabile technische Package-ID.
    family_id und package_id bleiben semantische IDs.
    revision_hash beschreibt die Inhaltsrevision.
    Die DB erzeugt keine vplib_uid, sondern übernimmt sie aus dem Manifest.

Version 0.3.0:

- `repositories` ist als optionales DB-Subpackage registriert.
- Health enthält DB-/Repository-/Published-Capabilities.
- Runtime-Caches können auch DB-Sync-, Published- und Repository-Caches leeren.
- Strict-Health unterscheidet Core-, optionale und DB-Subpackages.
- Package-Import bleibt weiterhin ohne Scan, ohne DB-Zugriff und ohne Schreiboperation.
"""

from __future__ import annotations

import importlib
import traceback
from dataclasses import asdict, dataclass, field, is_dataclass
from datetime import datetime, timezone
from pathlib import Path
from threading import RLock
from types import ModuleType
from typing import Any, Final, Iterable, Mapping


# ---------------------------------------------------------------------------
# Public package metadata
# ---------------------------------------------------------------------------

__version__: Final[str] = "0.3.0"

LIBRARY_SERVICE_NAME: Final[str] = "vectoplan-library"
LIBRARY_PACKAGE_NAME: Final[str] = "library"
LIBRARY_COMPONENT_NAME: Final[str] = "creative-library-backend"
LIBRARY_API_VERSION: Final[str] = "v1"
LIBRARY_IMPLEMENTATION_STAGE: Final[str] = "filesystem-taxonomy-db-sync-read-model"

DEFAULT_LIBRARY_ROUTE_PREFIX: Final[str] = "/api/v1/vplib/library"
DEFAULT_SOURCE_DIRECTORY_NAME: Final[str] = "source"

CANONICAL_SOURCE_DEPTH: Final[int] = 4
LEGACY_SOURCE_DEPTH: Final[int] = 3
CANONICAL_SOURCE_PATH_PATTERN: Final[str] = "{domain}/{category}/{subcategory}/{family_slug}"
LEGACY_SOURCE_PATH_PATTERN: Final[str] = "{domain}/{category}/{family_slug}"

CORE_SUBPACKAGES: Final[tuple[str, ...]] = (
    "taxonomy",
    "domain",
    "scanner",
    "validation",
    "read_models",
    "services",
)

DB_SUBPACKAGES: Final[tuple[str, ...]] = (
    "repositories",
)

EXTRA_OPTIONAL_SUBPACKAGES: Final[tuple[str, ...]] = (
    "utils",
)

# Backwards-compatible:
# In früheren Versionen enthielt OPTIONAL_SUBPACKAGES auch Core-Subpackages.
# Dieses Verhalten bleibt erhalten, damit bestehende Iterationen über
# OPTIONAL_SUBPACKAGES weiter funktionieren.
OPTIONAL_SUBPACKAGES: Final[tuple[str, ...]] = (
    *CORE_SUBPACKAGES,
    *DB_SUBPACKAGES,
    *EXTRA_OPTIONAL_SUBPACKAGES,
)

KNOWN_SUBPACKAGES: Final[tuple[str, ...]] = OPTIONAL_SUBPACKAGES

# Content-Verzeichnisse sind keine Pflicht-Python-Subpackages.
# `source` enthält echte Block-/Objektordner.
CONTENT_DIRECTORIES: Final[tuple[str, ...]] = (
    DEFAULT_SOURCE_DIRECTORY_NAME,
)

SUBPACKAGE_HEALTH_FUNCTIONS: Final[dict[str, tuple[str, ...]]] = {
    "taxonomy": (
        "get_taxonomy_package_health",
        "get_taxonomy_health",
    ),
    "domain": (
        "get_domain_health",
    ),
    "scanner": (
        "get_scanner_health",
    ),
    "validation": (
        "get_validation_health",
    ),
    "read_models": (
        "get_read_models_health",
    ),
    "services": (
        "get_services_health",
    ),
    "repositories": (
        "get_repositories_health",
        "get_repository_health",
    ),
    "utils": (
        "get_utils_health",
    ),
}


# ---------------------------------------------------------------------------
# Internal paths / cache
# ---------------------------------------------------------------------------

_PACKAGE_ROOT: Final[Path] = Path(__file__).resolve().parent
_IMPORT_CACHE_LOCK = RLock()
_SUBPACKAGE_CACHE: dict[str, ModuleType] = {}
_IMPORT_ERRORS: dict[str, dict[str, Any] | None] = {}


# ---------------------------------------------------------------------------
# Data structures
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class LibrarySubpackageStatus:
    """
    Status eines Library-Subpackages.

    `available=False` ist bei optionalen Subpackages nicht automatisch ein
    Fehler. `strict=True` in `get_library_health()` macht fehlende Core-
    Subpackages aber zu Fehlern.
    """

    name: str
    import_path: str
    expected_path: str
    available: bool
    loaded: bool
    status: str
    core: bool = False
    optional: bool = True
    db_subpackage: bool = False
    error: dict[str, Any] | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "import_path": self.import_path,
            "expected_path": self.expected_path,
            "available": self.available,
            "loaded": self.loaded,
            "status": self.status,
            "core": self.core,
            "optional": self.optional,
            "db_subpackage": self.db_subpackage,
            "error": json_safe(self.error),
        }


@dataclass(frozen=True)
class LibraryContentDirectoryStatus:
    """
    Status eines fachlichen Content-Verzeichnisses.

    Beispiel:
      src/library/source

    Dieses Verzeichnis darf leer sein. Leer bedeutet nicht fehlerhaft.
    """

    name: str
    path: str
    exists: bool
    is_directory: bool
    status: str

    def to_dict(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "path": self.path,
            "exists": self.exists,
            "is_directory": self.is_directory,
            "status": self.status,
        }


@dataclass(frozen=True)
class LibraryHealth:
    """JSON-kompatibles Health-Modell der Library-Schicht."""

    ok: bool
    healthy: bool
    strict: bool
    service: str
    package: str
    component: str
    version: str
    api_version: str
    implementation_stage: str
    generated_at: str
    package_root: str
    default_source_root: str
    default_route_prefix: str

    expected_subpackage_count: int
    core_subpackage_count: int
    db_subpackage_count: int
    available_subpackage_count: int
    loaded_subpackage_count: int
    missing_subpackage_count: int
    error_subpackage_count: int

    subpackages: dict[str, dict[str, Any]] = field(default_factory=dict)
    subhealth: dict[str, dict[str, Any]] = field(default_factory=dict)
    content_directories: dict[str, dict[str, Any]] = field(default_factory=dict)
    taxonomy: dict[str, Any] = field(default_factory=dict)
    db: dict[str, Any] = field(default_factory=dict)
    capabilities: dict[str, Any] = field(default_factory=dict)
    warnings: list[str] = field(default_factory=list)
    errors: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "ok": self.ok,
            "healthy": self.healthy,
            "strict": self.strict,
            "service": self.service,
            "package": self.package,
            "component": self.component,
            "version": self.version,
            "api_version": self.api_version,
            "implementation_stage": self.implementation_stage,
            "generated_at": self.generated_at,
            "package_root": self.package_root,
            "default_source_root": self.default_source_root,
            "default_route_prefix": self.default_route_prefix,
            "expected_subpackage_count": self.expected_subpackage_count,
            "core_subpackage_count": self.core_subpackage_count,
            "db_subpackage_count": self.db_subpackage_count,
            "available_subpackage_count": self.available_subpackage_count,
            "loaded_subpackage_count": self.loaded_subpackage_count,
            "missing_subpackage_count": self.missing_subpackage_count,
            "error_subpackage_count": self.error_subpackage_count,
            "subpackages": json_safe(self.subpackages),
            "subhealth": json_safe(self.subhealth),
            "content_directories": json_safe(self.content_directories),
            "taxonomy": json_safe(self.taxonomy),
            "db": json_safe(self.db),
            "capabilities": json_safe(self.capabilities),
            "warnings": list(self.warnings),
            "errors": list(self.errors),
        }


# ---------------------------------------------------------------------------
# Time / serialization helpers
# ---------------------------------------------------------------------------

def utc_now_iso() -> str:
    """Liefert eine stabile UTC-Zeit im ISO-Format."""
    try:
        return datetime.now(timezone.utc).isoformat()
    except Exception:
        return datetime.utcnow().replace(tzinfo=timezone.utc).isoformat()


def exception_to_dict(
    exc: BaseException | None,
    *,
    include_traceback: bool = False,
) -> dict[str, Any] | None:
    """
    Serialisiert Exceptions JSON-kompatibel.

    Tracebacks werden standardmäßig nicht ausgegeben, damit Health-Routen keine
    internen Details leaken. Für lokale Debug-Ausgaben kann `include_traceback`
    aktiviert werden.
    """

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

        if isinstance(value, Path):
            return str(value)

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
    """Defensive Dataclass- oder Mapping-Serialisierung."""
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
# Path helpers
# ---------------------------------------------------------------------------

def get_library_package_root() -> Path:
    """Gibt den Root-Pfad des Python-Packages `src/library` zurück."""
    return _PACKAGE_ROOT


def get_default_source_root() -> Path:
    """
    Gibt den Standard-Source-Ordner für manuell abgelegte Block-/Objektpakete
    zurück.

    Erwarteter Pfad:
      services/vectoplan-library/src/library/source

    Diese Funktion erzeugt den Ordner bewusst nicht.
    """
    return _PACKAGE_ROOT / DEFAULT_SOURCE_DIRECTORY_NAME


def get_default_route_prefix() -> str:
    """Gibt den Standard-Route-Prefix der Library-API zurück."""
    return DEFAULT_LIBRARY_ROUTE_PREFIX


def get_library_info() -> dict[str, Any]:
    """
    Liefert eine kompakte, JSON-kompatible Beschreibung der Library-Schicht.
    """
    return {
        "service": LIBRARY_SERVICE_NAME,
        "package": LIBRARY_PACKAGE_NAME,
        "component": LIBRARY_COMPONENT_NAME,
        "version": __version__,
        "api_version": LIBRARY_API_VERSION,
        "implementation_stage": LIBRARY_IMPLEMENTATION_STAGE,
        "package_root": str(get_library_package_root()),
        "default_source_root": str(get_default_source_root()),
        "default_route_prefix": get_default_route_prefix(),
        "core_subpackages": list(CORE_SUBPACKAGES),
        "db_subpackages": list(DB_SUBPACKAGES),
        "optional_subpackages": list(OPTIONAL_SUBPACKAGES),
        "known_subpackages": list(KNOWN_SUBPACKAGES),
        "content_directories": list(CONTENT_DIRECTORIES),
        "taxonomy": {
            "canonical_source_depth": CANONICAL_SOURCE_DEPTH,
            "legacy_source_depth": LEGACY_SOURCE_DEPTH,
            "canonical_source_path_pattern": CANONICAL_SOURCE_PATH_PATTERN,
            "legacy_source_path_pattern": LEGACY_SOURCE_PATH_PATTERN,
        },
        "db": {
            "vplib_uid_is_primary_business_key": True,
            "revision_hash_tracks_content_revision": True,
            "database_creates_vplib_uid": False,
        },
    }


# ---------------------------------------------------------------------------
# Import helpers
# ---------------------------------------------------------------------------

def build_subpackage_import_path(name: str) -> str:
    """Baut den vollständigen Importpfad für ein Library-Subpackage."""
    return f"{__name__}.{name}"


def subpackage_expected_path(name: str) -> Path:
    """Erwarteter Dateisystempfad eines optionalen Subpackages."""
    return _PACKAGE_ROOT / name


def clear_library_import_cache() -> dict[str, Any]:
    """
    Leert den lokalen Subpackage-Import-Cache.

    Entfernt keine Module aus sys.modules.
    """
    with _IMPORT_CACHE_LOCK:
        cached = sorted(_SUBPACKAGE_CACHE.keys())
        errors = sorted(_IMPORT_ERRORS.keys())
        _SUBPACKAGE_CACHE.clear()
        _IMPORT_ERRORS.clear()

    for name in KNOWN_SUBPACKAGES:
        globals().pop(name, None)

    return {
        "ok": True,
        "cleared_subpackage_cache": cached,
        "cleared_import_errors": errors,
    }


def safe_import_subpackage(
    name: str,
    *,
    include_traceback: bool = False,
    force_reload: bool = False,
) -> tuple[ModuleType | None, LibrarySubpackageStatus]:
    """
    Importiert ein Subpackage defensiv.

    Rückgabe:
      (module, status)

    - Fehlende Subpackages werden als `missing` gemeldet.
    - Fehlerhafte Subpackages werden als `error` gemeldet.
    - Erfolgreiche Importe werden als `available` gemeldet.
    """

    import_path = build_subpackage_import_path(name)
    expected_path = subpackage_expected_path(name)
    core = name in CORE_SUBPACKAGES
    db_subpackage = name in DB_SUBPACKAGES

    try:
        with _IMPORT_CACHE_LOCK:
            if force_reload and name in _SUBPACKAGE_CACHE:
                module = importlib.reload(_SUBPACKAGE_CACHE[name])
                _SUBPACKAGE_CACHE[name] = module
            elif not force_reload and name in _SUBPACKAGE_CACHE:
                module = _SUBPACKAGE_CACHE[name]
            else:
                module = importlib.import_module(import_path)
                _SUBPACKAGE_CACHE[name] = module

            _IMPORT_ERRORS.pop(name, None)

        return module, LibrarySubpackageStatus(
            name=name,
            import_path=import_path,
            expected_path=str(expected_path),
            available=True,
            loaded=True,
            status="available",
            core=core,
            optional=not core,
            db_subpackage=db_subpackage,
            error=None,
        )

    except ModuleNotFoundError as exc:
        missing_requested_subpackage = exc.name == import_path

        status = "missing" if missing_requested_subpackage else "error"
        error_payload = exception_to_dict(exc, include_traceback=include_traceback)

        with _IMPORT_CACHE_LOCK:
            _IMPORT_ERRORS[name] = error_payload
            _SUBPACKAGE_CACHE.pop(name, None)

        return None, LibrarySubpackageStatus(
            name=name,
            import_path=import_path,
            expected_path=str(expected_path),
            available=False,
            loaded=False,
            status=status,
            core=core,
            optional=not core,
            db_subpackage=db_subpackage,
            error=error_payload,
        )

    except Exception as exc:
        error_payload = exception_to_dict(exc, include_traceback=include_traceback)

        with _IMPORT_CACHE_LOCK:
            _IMPORT_ERRORS[name] = error_payload
            _SUBPACKAGE_CACHE.pop(name, None)

        return None, LibrarySubpackageStatus(
            name=name,
            import_path=import_path,
            expected_path=str(expected_path),
            available=False,
            loaded=False,
            status="error",
            core=core,
            optional=not core,
            db_subpackage=db_subpackage,
            error=error_payload,
        )


def get_subpackage_status(
    *,
    include_traceback: bool = False,
    force_reload: bool = False,
) -> dict[str, dict[str, Any]]:
    """Liefert den Status aller bekannten Library-Subpackages."""
    statuses: dict[str, dict[str, Any]] = {}

    for name in KNOWN_SUBPACKAGES:
        _, status = safe_import_subpackage(
            name,
            include_traceback=include_traceback,
            force_reload=force_reload,
        )
        statuses[name] = status.to_dict()

    return statuses


def get_subpackage_subhealth(
    *,
    include_traceback: bool = False,
    force_reload: bool = False,
) -> dict[str, dict[str, Any]]:
    """
    Ruft optionale Health-Funktionen der Subpackages auf.

    Health-Funktionen werden defensiv gesucht. Fehlende Health-Funktion ist für
    optionale Subpackages kein harter Fehler.
    """

    subhealth: dict[str, dict[str, Any]] = {}

    for name in KNOWN_SUBPACKAGES:
        try:
            module, status = safe_import_subpackage(
                name,
                include_traceback=include_traceback,
                force_reload=force_reload,
            )

            if module is None:
                subhealth[name] = {
                    "ok": False,
                    "healthy": False,
                    "status": status.status,
                    "core": name in CORE_SUBPACKAGES,
                    "optional": name not in CORE_SUBPACKAGES,
                    "db_subpackage": name in DB_SUBPACKAGES,
                    "error": status.error,
                }
                continue

            health_function = None
            for function_name in SUBPACKAGE_HEALTH_FUNCTIONS.get(name, ()):
                candidate = getattr(module, function_name, None)
                if callable(candidate):
                    health_function = candidate
                    break

            if health_function is None:
                subhealth[name] = {
                    "ok": True,
                    "healthy": True,
                    "status": "loaded_no_health_function",
                    "core": name in CORE_SUBPACKAGES,
                    "optional": name not in CORE_SUBPACKAGES,
                    "db_subpackage": name in DB_SUBPACKAGES,
                }
                continue

            try:
                health = health_function(
                    include_traceback=include_traceback,
                    include_subhealth=True,
                    force_reload=force_reload,
                )
            except TypeError:
                try:
                    health = health_function(
                        include_traceback=include_traceback,
                    )
                except TypeError:
                    health = health_function()

            payload = dataclass_to_dict_safe(health)
            payload.setdefault("core", name in CORE_SUBPACKAGES)
            payload.setdefault("optional", name not in CORE_SUBPACKAGES)
            payload.setdefault("db_subpackage", name in DB_SUBPACKAGES)
            subhealth[name] = payload

        except Exception as exc:
            subhealth[name] = {
                "ok": False,
                "healthy": False,
                "status": "health_error",
                "core": name in CORE_SUBPACKAGES,
                "optional": name not in CORE_SUBPACKAGES,
                "db_subpackage": name in DB_SUBPACKAGES,
                "error": exception_to_dict(exc, include_traceback=include_traceback),
            }

    return subhealth


def get_content_directory_status() -> dict[str, dict[str, Any]]:
    """
    Liefert den Status fachlicher Content-Verzeichnisse.

    Aktuell relevant:
      src/library/source

    Ein nicht vorhandener Source-Ordner wird hier nur als Status gemeldet.
    """
    statuses: dict[str, dict[str, Any]] = {}

    for name in CONTENT_DIRECTORIES:
        path = _PACKAGE_ROOT / name
        exists = path.exists()
        is_directory = path.is_dir()

        if exists and is_directory:
            status = "available"
        elif exists and not is_directory:
            status = "invalid"
        else:
            status = "missing"

        directory_status = LibraryContentDirectoryStatus(
            name=name,
            path=str(path),
            exists=exists,
            is_directory=is_directory,
            status=status,
        )
        statuses[name] = directory_status.to_dict()

    return statuses


# ---------------------------------------------------------------------------
# Runtime cache helpers
# ---------------------------------------------------------------------------

def clear_library_runtime_caches() -> dict[str, Any]:
    """
    Leert bekannte Runtime-Caches der Library-Schicht.

    Führt keine Scans, keine DB-Syncs und keine Schreiboperationen aus.
    """
    cleared: dict[str, Any] = {
        "services": False,
        "read_models": False,
        "taxonomy": False,
        "repositories": False,
        "errors": [],
    }

    try:
        module, status = safe_import_subpackage("services")
        if module is not None:
            clear_fn = (
                getattr(module, "clear_services_caches", None)
                or getattr(module, "clear_scan_cache", None)
            )
            if callable(clear_fn):
                clear_fn()
                cleared["services"] = True
        else:
            cleared["errors"].append(status.error)
    except Exception as exc:
        cleared["errors"].append(exception_to_dict(exc))

    try:
        module, status = safe_import_subpackage("read_models")
        if module is not None:
            clear_fn = getattr(module, "clear_read_models_caches", None)
            if callable(clear_fn):
                clear_fn()
                cleared["read_models"] = True
        else:
            cleared["errors"].append(status.error)
    except Exception as exc:
        cleared["errors"].append(exception_to_dict(exc))

    try:
        module, status = safe_import_subpackage("taxonomy")
        if module is not None:
            clear_fn = (
                getattr(module, "clear_taxonomy_cache", None)
                or getattr(module, "clear_taxonomy_caches", None)
            )
            if callable(clear_fn):
                clear_fn()
                cleared["taxonomy"] = True
        else:
            cleared["errors"].append(status.error)
    except Exception as exc:
        cleared["errors"].append(exception_to_dict(exc))

    try:
        module, status = safe_import_subpackage("repositories")
        if module is not None:
            clear_fn = (
                getattr(module, "clear_repositories_caches", None)
                or getattr(module, "clear_repository_caches", None)
                or getattr(module, "clear_repository_cache", None)
            )
            if callable(clear_fn):
                clear_fn()
                cleared["repositories"] = True
        else:
            cleared["errors"].append(status.error)
    except Exception as exc:
        cleared["errors"].append(exception_to_dict(exc))

    return cleared


def clear_library_caches() -> dict[str, Any]:
    """Leert Import- und Runtime-Caches der Library-Schicht."""
    runtime = clear_library_runtime_caches()
    imports = clear_library_import_cache()

    return {
        "ok": not runtime.get("errors") and bool(imports.get("ok", True)),
        "runtime": runtime,
        "imports": imports,
    }


clear_library_cache = clear_library_caches


# ---------------------------------------------------------------------------
# Health / readiness
# ---------------------------------------------------------------------------

def _extract_taxonomy_health(subhealth: Mapping[str, Any]) -> dict[str, Any]:
    """Extrahiert Taxonomie-Capabilities aus Subhealth."""
    taxonomy_health = subhealth.get("taxonomy")

    result: dict[str, Any] = {
        "registered": "taxonomy" in KNOWN_SUBPACKAGES,
        "core": "taxonomy" in CORE_SUBPACKAGES,
        "canonical_source_depth": CANONICAL_SOURCE_DEPTH,
        "legacy_source_depth": LEGACY_SOURCE_DEPTH,
        "canonical_source_path_pattern": CANONICAL_SOURCE_PATH_PATTERN,
        "legacy_source_path_pattern": LEGACY_SOURCE_PATH_PATTERN,
        "healthy": None,
        "version": None,
    }

    if isinstance(taxonomy_health, Mapping):
        result["healthy"] = taxonomy_health.get("healthy", taxonomy_health.get("ok"))
        result["version"] = (
            taxonomy_health.get("version")
            or taxonomy_health.get("taxonomy_version")
            or taxonomy_health.get("package_version")
        )
        result["details"] = dict(json_safe(taxonomy_health))

    return result


def _extract_db_health(subhealth: Mapping[str, Any]) -> dict[str, Any]:
    """Extrahiert DB-/Repository-/Published-Capabilities aus Subhealth."""
    repositories = subhealth.get("repositories")
    services = subhealth.get("services")
    read_models = subhealth.get("read_models")
    domain = subhealth.get("domain")

    services_db = services.get("db_services") if isinstance(services, Mapping) else None
    read_models_db = read_models.get("db_read_models") if isinstance(read_models, Mapping) else None
    domain_db = domain.get("db_domain") if isinstance(domain, Mapping) else None

    return {
        "registered": "repositories" in KNOWN_SUBPACKAGES,
        "repository_available": isinstance(repositories, Mapping) and _status_is_healthy(repositories),
        "repository_status": repositories.get("status") if isinstance(repositories, Mapping) else None,
        "sync_service_available": bool(
            isinstance(services_db, Mapping)
            and services_db.get("sync", {}).get("available")
        ),
        "published_service_available": bool(
            isinstance(services_db, Mapping)
            and services_db.get("published", {}).get("available")
        ),
        "db_summary_builder_available": bool(
            isinstance(read_models_db, Mapping)
            and read_models_db.get("summary_ready")
        ),
        "db_detail_builder_available": bool(
            isinstance(read_models_db, Mapping)
            and read_models_db.get("detail_ready")
        ),
        "db_tree_builder_available": bool(
            isinstance(read_models_db, Mapping)
            and read_models_db.get("tree_ready")
        ),
        "db_inventory_builder_available": bool(
            isinstance(read_models_db, Mapping)
            and read_models_db.get("inventory_ready")
        ),
        "sync_domain_available": bool(
            isinstance(domain_db, Mapping)
            and domain_db.get("sync_result", {}).get("available")
        ),
        "publication_domain_available": bool(
            isinstance(domain_db, Mapping)
            and domain_db.get("publication", {}).get("available")
        ),
        "inventory_domain_available": bool(
            isinstance(domain_db, Mapping)
            and domain_db.get("inventory", {}).get("available")
        ),
        "details": {
            "repositories": json_safe(repositories) if isinstance(repositories, Mapping) else None,
            "services_db": json_safe(services_db) if isinstance(services_db, Mapping) else None,
            "read_models_db": json_safe(read_models_db) if isinstance(read_models_db, Mapping) else None,
            "domain_db": json_safe(domain_db) if isinstance(domain_db, Mapping) else None,
        },
    }


def _build_library_capabilities(
    *,
    taxonomy: Mapping[str, Any],
    db: Mapping[str, Any],
    content_directories: Mapping[str, Any],
) -> dict[str, Any]:
    """Baut kompakte Capability-Map für Admin-/Health-Routen."""
    source_status = content_directories.get(DEFAULT_SOURCE_DIRECTORY_NAME, {})
    source_available = isinstance(source_status, Mapping) and source_status.get("status") == "available"

    return {
        "filesystem_source_available": bool(source_available),
        "taxonomy_available": taxonomy.get("healthy") is not False,
        "filesystem_scan_path": True,
        "filesystem_block_read_path": True,
        "create_source_package_path": True,
        "repository_layer": bool(db.get("repository_available")),
        "db_sync_path": bool(db.get("sync_service_available") and db.get("repository_available")),
        "published_db_read_path": bool(db.get("published_service_available") and db.get("repository_available")),
        "published_blocks_route_ready": bool(
            db.get("published_service_available")
            and db.get("db_summary_builder_available")
        ),
        "published_detail_route_ready": bool(
            db.get("published_service_available")
            and db.get("db_detail_builder_available")
        ),
        "published_tree_route_ready": bool(
            db.get("published_service_available")
            and db.get("db_tree_builder_available")
        ),
        "published_inventory_route_ready": bool(
            db.get("published_service_available")
            and db.get("db_inventory_builder_available")
        ),
        "vplib_uid_ready": True,
        "database_creates_vplib_uid": False,
    }


def get_library_health(
    *,
    strict: bool = False,
    include_traceback: bool = False,
    include_subhealth: bool = True,
    force_reload: bool = False,
    strict_db: bool = False,
) -> dict[str, Any]:
    """
    Liefert einen robusten Health-Status der Library-Schicht.

    Parameter:
      strict=False
        Geeignet für Entwicklung. Fehlende optionale Subpackages werden als
        Warnung gemeldet, machen den Health-Status aber nicht rot.

      strict=True
        Core-Subpackages und Source-Verzeichnis müssen vorhanden sein.
        Fehlerhafte Core-Subpackages machen den Health-Status rot.

      strict_db=False
        DB-Subpackages sind während der Migration optional.

      strict_db=True
        DB-Subpackages und DB-Capabilities werden hart geprüft.

    Diese Funktion führt keinen Scan aus, öffnet keine DB-Verbindung und erzeugt
    keine Dateien.
    """

    warnings: list[str] = []
    errors: list[str] = []

    subpackages = get_subpackage_status(
        include_traceback=include_traceback,
        force_reload=force_reload,
    )
    content_directories = get_content_directory_status()

    subhealth: dict[str, dict[str, Any]] = {}
    if include_subhealth:
        subhealth = get_subpackage_subhealth(
            include_traceback=include_traceback,
            force_reload=force_reload,
        )

    available_subpackages = [
        name
        for name, status in subpackages.items()
        if status.get("status") == "available"
    ]
    missing_subpackages = [
        name
        for name, status in subpackages.items()
        if status.get("status") == "missing"
    ]
    error_subpackages = [
        name
        for name, status in subpackages.items()
        if status.get("status") == "error"
    ]

    invalid_content_directories = [
        name
        for name, status in content_directories.items()
        if status.get("status") == "invalid"
    ]
    missing_content_directories = [
        name
        for name, status in content_directories.items()
        if status.get("status") == "missing"
    ]

    for name in missing_subpackages:
        if name in CORE_SUBPACKAGES:
            warnings.append(f"core library subpackage is not available: {name}")
        elif name in DB_SUBPACKAGES:
            warnings.append(f"db library subpackage is not available: {name}")
        else:
            warnings.append(f"optional library subpackage is not available: {name}")

    for name in missing_content_directories:
        warnings.append(f"library content directory is missing: {name}")

    for name in error_subpackages:
        if name in CORE_SUBPACKAGES:
            errors.append(f"core library subpackage import failed: {name}")
        elif strict_db and name in DB_SUBPACKAGES:
            errors.append(f"db library subpackage import failed in strict_db mode: {name}")
        else:
            warnings.append(f"optional/db library subpackage import failed: {name}")

    for name in invalid_content_directories:
        errors.append(f"library content path exists but is not a directory: {name}")

    if include_subhealth:
        for name, health in subhealth.items():
            healthy = _status_is_healthy(health)
            if healthy:
                continue

            if name in CORE_SUBPACKAGES:
                errors.append(f"core library subhealth failed: {name}")
            elif strict_db and name in DB_SUBPACKAGES:
                errors.append(f"db library subhealth failed in strict_db mode: {name}")
            else:
                warnings.append(f"optional/db library subhealth failed: {name}")

    if strict:
        for name in missing_subpackages:
            if name in CORE_SUBPACKAGES:
                errors.append(f"required library subpackage is missing in strict mode: {name}")

        for name in missing_content_directories:
            errors.append(f"required library content directory is missing in strict mode: {name}")

    taxonomy = _extract_taxonomy_health(subhealth)
    db = _extract_db_health(subhealth)
    capabilities = _build_library_capabilities(
        taxonomy=taxonomy,
        db=db,
        content_directories=content_directories,
    )

    if strict and taxonomy.get("healthy") is False:
        errors.append("taxonomy subpackage is not healthy in strict mode")

    if strict_db:
        required_db_capabilities = (
            "repository_layer",
            "db_sync_path",
            "published_db_read_path",
            "published_blocks_route_ready",
            "published_detail_route_ready",
            "published_tree_route_ready",
            "published_inventory_route_ready",
        )

        for capability in required_db_capabilities:
            if not capabilities.get(capability):
                errors.append(f"required DB capability is unavailable in strict_db mode: {capability}")

    healthy = len(errors) == 0

    health = LibraryHealth(
        ok=healthy,
        healthy=healthy,
        strict=strict,
        service=LIBRARY_SERVICE_NAME,
        package=LIBRARY_PACKAGE_NAME,
        component=LIBRARY_COMPONENT_NAME,
        version=__version__,
        api_version=LIBRARY_API_VERSION,
        implementation_stage=LIBRARY_IMPLEMENTATION_STAGE,
        generated_at=utc_now_iso(),
        package_root=str(get_library_package_root()),
        default_source_root=str(get_default_source_root()),
        default_route_prefix=get_default_route_prefix(),
        expected_subpackage_count=len(KNOWN_SUBPACKAGES),
        core_subpackage_count=len(CORE_SUBPACKAGES),
        db_subpackage_count=len(DB_SUBPACKAGES),
        available_subpackage_count=len(available_subpackages),
        loaded_subpackage_count=len(available_subpackages),
        missing_subpackage_count=len(missing_subpackages),
        error_subpackage_count=len(error_subpackages),
        subpackages=subpackages,
        subhealth=subhealth,
        content_directories=content_directories,
        taxonomy=taxonomy,
        db=db,
        capabilities=capabilities,
        warnings=warnings,
        errors=errors,
    )

    return health.to_dict()


def is_library_healthy(*, strict: bool = False, strict_db: bool = False) -> bool:
    """Convenience-Funktion für einfache boolesche Prüfungen."""
    try:
        health = get_library_health(strict=strict, strict_db=strict_db)
        return bool(health.get("healthy"))
    except Exception:
        return False


def assert_library_ready(*, strict: bool = False, strict_db: bool = False) -> None:
    """
    Wirft RuntimeError, wenn die Library-Schicht nicht bereit ist.

    Diese Funktion eignet sich für spätere Startup-Prüfungen oder Tests.
    """

    health = get_library_health(strict=strict, strict_db=strict_db)

    if health.get("healthy"):
        return

    errors = health.get("errors") or []
    warnings = health.get("warnings") or []

    details = {
        "strict": strict,
        "strict_db": strict_db,
        "errors": errors,
        "warnings": warnings,
        "package_root": health.get("package_root"),
        "default_source_root": health.get("default_source_root"),
        "capabilities": health.get("capabilities"),
    }

    raise RuntimeError(f"library package is not ready: {details}")


# ---------------------------------------------------------------------------
# Lazy attribute access
# ---------------------------------------------------------------------------

def __getattr__(name: str) -> ModuleType:
    """
    Lazy Import für Library-Subpackages.

    Beispiel:
      import library
      library.scanner

    Fehlende optionale Subpackages erzeugen AttributeError.
    Interne Importfehler vorhandener Subpackages werden nicht verschluckt.
    """

    if name not in KNOWN_SUBPACKAGES:
        raise AttributeError(f"module {__name__!r} has no attribute {name!r}")

    module, status = safe_import_subpackage(name)

    if module is None:
        if status.status == "missing":
            raise AttributeError(
                f"optional library subpackage {status.import_path!r} is not available"
            )

        raise ImportError(
            f"could not import library subpackage {name!r}: {status.error}"
        )

    globals()[name] = module
    return module


def __dir__() -> list[str]:
    """Ergänzt die optionale Lazy-Import-API in dir(library)."""
    public_names = set(globals().keys())
    public_names.update(KNOWN_SUBPACKAGES)
    return sorted(public_names)


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

__all__: Final[tuple[str, ...]] = (
    "__version__",
    "LIBRARY_SERVICE_NAME",
    "LIBRARY_PACKAGE_NAME",
    "LIBRARY_COMPONENT_NAME",
    "LIBRARY_API_VERSION",
    "LIBRARY_IMPLEMENTATION_STAGE",
    "DEFAULT_LIBRARY_ROUTE_PREFIX",
    "DEFAULT_SOURCE_DIRECTORY_NAME",
    "CANONICAL_SOURCE_DEPTH",
    "LEGACY_SOURCE_DEPTH",
    "CANONICAL_SOURCE_PATH_PATTERN",
    "LEGACY_SOURCE_PATH_PATTERN",
    "CORE_SUBPACKAGES",
    "DB_SUBPACKAGES",
    "EXTRA_OPTIONAL_SUBPACKAGES",
    "OPTIONAL_SUBPACKAGES",
    "KNOWN_SUBPACKAGES",
    "CONTENT_DIRECTORIES",
    "SUBPACKAGE_HEALTH_FUNCTIONS",
    "LibrarySubpackageStatus",
    "LibraryContentDirectoryStatus",
    "LibraryHealth",
    "utc_now_iso",
    "exception_to_dict",
    "json_safe",
    "dataclass_to_dict_safe",
    "safe_tuple",
    "get_library_package_root",
    "get_default_source_root",
    "get_default_route_prefix",
    "get_library_info",
    "build_subpackage_import_path",
    "subpackage_expected_path",
    "clear_library_import_cache",
    "safe_import_subpackage",
    "get_subpackage_status",
    "get_subpackage_subhealth",
    "get_content_directory_status",
    "clear_library_runtime_caches",
    "clear_library_caches",
    "clear_library_cache",
    "get_library_health",
    "is_library_healthy",
    "assert_library_ready",
)