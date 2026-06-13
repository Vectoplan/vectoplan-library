# services/vectoplan-library/src/library/repositories/__init__.py
"""
Repository-Fassade für die fachliche Library-Schicht von VECTOPLAN.

Diese Datei ist bewusst robust, importarm und seiteneffektfrei aufgebaut.

Aufgaben dieser Fassade:

- zentrale Einstiegspunkte für Repository-Subpackages bereitstellen
- spätere SQL-/Storage-Repositories lazy importieren
- Importfehler zwischenspeichern und diagnostizierbar machen
- Health-/Ready-Funktionen für Startup, Tests und Admin bereitstellen
- Runtime- und Import-Caches kontrolliert leeren
- keine Datenbankverbindung beim Import öffnen
- keine Modelle beim Import erzwingen
- keine Schreiboperationen ausführen

Wichtig:

Diese Datei ist nur die Fassade. Die konkrete SQL-Implementierung folgt in:

    services/vectoplan-library/src/library/repositories/sql/__init__.py
    services/vectoplan-library/src/library/repositories/sql/creative_library_repository.py

Die Repository-Schicht liegt absichtlich zwischen:

    services / sync / read-services
        und
    models / SQLAlchemy / Datenbank

Scanner, Reader, Validatoren und Read-Models sollen nicht direkt in die
Datenbank schreiben.
"""

from __future__ import annotations

import importlib
import importlib.util
import os
import threading
import traceback as traceback_module
from dataclasses import dataclass
from pathlib import Path
from types import ModuleType
from typing import Any, Dict, Iterable, List, Mapping, Optional, Sequence, Tuple


# ---------------------------------------------------------------------------
# Metadata
# ---------------------------------------------------------------------------

REPOSITORIES_PACKAGE_NAME = "library.repositories"
REPOSITORIES_COMPONENT_NAME = "creative_library_repositories"
REPOSITORIES_API_VERSION = "v1"
REPOSITORIES_IMPLEMENTATION_STAGE = "repository-facade"

__version__ = "0.1.0"


# ---------------------------------------------------------------------------
# Backend / package configuration
# ---------------------------------------------------------------------------

DEFAULT_REPOSITORY_BACKEND = "sql"
REPOSITORY_BACKEND_ENV = "VPLIB_LIBRARY_REPOSITORY_BACKEND"

# In der aktuellen Zielarchitektur ist SQL/PostgreSQL der produktive Hauptpfad.
# Weitere Backends können später für Tests, In-Memory-Betrieb oder externe
# Storage-Adapter ergänzt werden.
SUPPORTED_REPOSITORY_BACKENDS: Tuple[str, ...] = (
    "sql",
)

# Core-Subpackages sind im strikten Modus erforderlich.
# Im nicht-strikten Modus werden fehlende Module nur als Warnung gemeldet,
# damit inkrementelle Entwicklung und Tests nicht sofort brechen.
CORE_REPOSITORY_SUBPACKAGES: Tuple[str, ...] = (
    "sql",
)

# Optional für spätere Erweiterungen, z. B. S3, Dateispeicher, externe Registry.
OPTIONAL_REPOSITORY_SUBPACKAGES: Tuple[str, ...] = (
    "storage",
)

REPOSITORY_SUBPACKAGE_MODULES: Mapping[str, str] = {
    "sql": f"{__name__}.sql",
    "storage": f"{__name__}.storage",
}

REPOSITORY_BACKEND_MODULES: Mapping[str, str] = {
    "sql": f"{__name__}.sql",
}


# ---------------------------------------------------------------------------
# Forward-looking lazy symbol registry
# ---------------------------------------------------------------------------

# Diese Symbole werden erst verfügbar, wenn die konkreten Dateien existieren.
# Die Fassade darf sie bereits kennen, aber nicht beim Import erzwingen.
SYMBOL_TO_MODULE: Mapping[str, str] = {
    # Repository class / config / errors
    "CreativeLibraryRepository": f"{__name__}.sql.creative_library_repository",
    "CreativeLibraryRepositoryConfig": f"{__name__}.sql.creative_library_repository",
    "CreativeLibraryRepositoryError": f"{__name__}.sql.creative_library_repository",
    "CreativeLibraryRepositoryUnavailable": f"{__name__}.sql.creative_library_repository",
    "CreativeLibraryRepositoryConflict": f"{__name__}.sql.creative_library_repository",
    "CreativeLibraryRepositoryNotFound": f"{__name__}.sql.creative_library_repository",

    # Factory / lifecycle helpers
    "create_creative_library_repository": f"{__name__}.sql.creative_library_repository",
    "get_creative_library_repository": f"{__name__}.sql.creative_library_repository",
    "get_default_creative_library_repository": f"{__name__}.sql.creative_library_repository",

    # Cache / health helpers from concrete repository implementation
    "clear_creative_library_repository_cache": f"{__name__}.sql.creative_library_repository",
    "get_creative_library_repository_health": f"{__name__}.sql.creative_library_repository",
    "assert_creative_library_repository_ready": f"{__name__}.sql.creative_library_repository",
}


CACHE_CLEAR_FUNCTION_NAMES: Tuple[str, ...] = (
    "clear_repository_cache",
    "clear_repositories_cache",
    "clear_repository_caches",
    "clear_repositories_caches",
    "clear_repository_runtime_cache",
    "clear_repository_runtime_caches",
    "clear_creative_library_repository_cache",
    "clear_creative_library_repository_caches",
)


# ---------------------------------------------------------------------------
# Internal caches
# ---------------------------------------------------------------------------

_CACHE_LOCK = threading.RLock()

_MODULE_CACHE: Dict[str, ModuleType] = {}
_IMPORT_ERROR_CACHE: Dict[str, BaseException] = {}
_IMPORT_TRACEBACK_CACHE: Dict[str, str] = {}


# ---------------------------------------------------------------------------
# Exceptions
# ---------------------------------------------------------------------------


class RepositoryError(RuntimeError):
    """Basisklasse für Repository-Fassadenfehler."""


class RepositoryConfigurationError(RepositoryError):
    """Fehlerhafte Repository-Konfiguration, z. B. unbekannter Backend-Name."""


class RepositoryUnavailableError(RepositoryError):
    """Repository-Modul oder Backend ist nicht verfügbar."""


# ---------------------------------------------------------------------------
# Status models
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class RepositoryModuleStatus:
    """
    Import-/Verfügbarkeitsstatus eines Repository-Subpackages.

    exists:
        Modul wurde über importlib.util.find_spec gefunden.

    imported:
        Modul liegt im lokalen Import-Cache dieser Fassade.

    available:
        Modul ist für die aktuelle Betriebsart verwendbar.
        Bei attempt_import=True bedeutet das: Import erfolgreich.
        Bei attempt_import=False bedeutet das: Modul wurde gefunden.
    """

    name: str
    module_path: str
    required: bool
    exists: bool
    imported: bool
    available: bool
    error_type: Optional[str] = None
    error: Optional[str] = None
    traceback: Optional[str] = None

    @property
    def ok(self) -> bool:
        return bool(self.available)

    def to_dict(self, *, include_traceback: bool = False) -> Dict[str, Any]:
        payload: Dict[str, Any] = {
            "name": self.name,
            "module_path": self.module_path,
            "required": self.required,
            "exists": self.exists,
            "imported": self.imported,
            "available": self.available,
            "ok": self.ok,
            "error_type": self.error_type,
            "error": self.error,
        }

        if include_traceback:
            payload["traceback"] = self.traceback

        return payload


# ---------------------------------------------------------------------------
# Basic helpers
# ---------------------------------------------------------------------------


def _normalize_key(value: Any) -> str:
    """
    Normalisiert technische Keys für Backend- und Subpackage-Namen.

    Beispiele:
        "SQL"        -> "sql"
        "sql-db"     -> "sql_db"
        " sql_db "   -> "sql_db"
    """

    return str(value or "").strip().lower().replace("-", "_")


def _exception_to_payload(exc: Optional[BaseException]) -> Tuple[Optional[str], Optional[str]]:
    if exc is None:
        return None, None

    return exc.__class__.__name__, str(exc)


def _module_exists(module_path: str) -> Tuple[bool, Optional[BaseException]]:
    """
    Prüft, ob ein Modul prinzipiell auffindbar ist.

    Diese Funktion importiert das Zielmodul nicht aktiv. Sie ist dadurch
    leichter als ein echter Import, kann aber bei beschädigten Parent-Packages
    trotzdem Exceptions werfen. Diese werden defensiv zurückgegeben.
    """

    try:
        return importlib.util.find_spec(module_path) is not None, None
    except Exception as exc:  # intentionally defensive for health endpoints
        return False, exc


def _store_import_error(module_path: str, exc: BaseException) -> None:
    with _CACHE_LOCK:
        _IMPORT_ERROR_CACHE[module_path] = exc
        _IMPORT_TRACEBACK_CACHE[module_path] = traceback_module.format_exc()
        _MODULE_CACHE.pop(module_path, None)


def _clear_import_error(module_path: str) -> None:
    with _CACHE_LOCK:
        _IMPORT_ERROR_CACHE.pop(module_path, None)
        _IMPORT_TRACEBACK_CACHE.pop(module_path, None)


def _get_cached_import_error(module_path: str) -> Optional[BaseException]:
    with _CACHE_LOCK:
        return _IMPORT_ERROR_CACHE.get(module_path)


def _get_cached_traceback(module_path: str) -> Optional[str]:
    with _CACHE_LOCK:
        return _IMPORT_TRACEBACK_CACHE.get(module_path)


def _build_unavailable_message(module_path: str, exc: Optional[BaseException] = None) -> str:
    if exc is None:
        exc = _get_cached_import_error(module_path)

    if exc is None:
        return f"Repository module is not available: {module_path}"

    return (
        f"Repository module is not available: {module_path} "
        f"({exc.__class__.__name__}: {exc})"
    )


def get_repositories_package_root() -> Path:
    """Gibt den absoluten Pfad zum Repository-Package zurück."""

    return Path(__file__).resolve().parent


def get_repositories_info() -> Dict[str, Any]:
    """Liefert statische Informationen über die Repository-Fassade."""

    return {
        "package": REPOSITORIES_PACKAGE_NAME,
        "python_package": __name__,
        "component": REPOSITORIES_COMPONENT_NAME,
        "api_version": REPOSITORIES_API_VERSION,
        "implementation_stage": REPOSITORIES_IMPLEMENTATION_STAGE,
        "version": __version__,
        "package_root": str(get_repositories_package_root()),
        "default_backend": DEFAULT_REPOSITORY_BACKEND,
        "backend_env": REPOSITORY_BACKEND_ENV,
        "supported_backends": list(SUPPORTED_REPOSITORY_BACKENDS),
        "core_subpackages": list(CORE_REPOSITORY_SUBPACKAGES),
        "optional_subpackages": list(OPTIONAL_REPOSITORY_SUBPACKAGES),
    }


# Backwards-compatible singular alias.
get_repository_info = get_repositories_info


# ---------------------------------------------------------------------------
# Safe imports
# ---------------------------------------------------------------------------


def safe_import_module(
    module_path: str,
    *,
    required: bool = False,
    force_reload: bool = False,
) -> Optional[ModuleType]:
    """
    Importiert ein Modul robust und cached das Ergebnis.

    required=False:
        Importfehler werden gecached und als None zurückgegeben.

    required=True:
        Importfehler werden als RepositoryUnavailableError geworfen.

    Diese Funktion soll von Health-Checks, Lazy-Exports und Services genutzt
    werden, damit Importfehler zentral sichtbar und cachebar bleiben.
    """

    normalized_path = str(module_path or "").strip()

    if not normalized_path:
        exc = RepositoryConfigurationError("Empty repository module path.")
        if required:
            raise exc
        return None

    with _CACHE_LOCK:
        if not force_reload and normalized_path in _MODULE_CACHE:
            return _MODULE_CACHE[normalized_path]

    try:
        with _CACHE_LOCK:
            if force_reload and normalized_path in _MODULE_CACHE:
                module = importlib.reload(_MODULE_CACHE[normalized_path])
            else:
                module = importlib.import_module(normalized_path)

            _MODULE_CACHE[normalized_path] = module
            _clear_import_error(normalized_path)
            return module

    except Exception as exc:  # intentionally defensive for lazy imports
        _store_import_error(normalized_path, exc)

        if required:
            raise RepositoryUnavailableError(
                _build_unavailable_message(normalized_path, exc)
            ) from exc

        return None


def safe_import_subpackage(
    name: str,
    *,
    required: bool = False,
    force_reload: bool = False,
) -> Optional[ModuleType]:
    """
    Importiert ein Repository-Subpackage anhand seines kurzen Namens.

    Beispiel:
        safe_import_subpackage("sql")
    """

    normalized_name = _normalize_key(name)
    module_path = REPOSITORY_SUBPACKAGE_MODULES.get(
        normalized_name,
        f"{__name__}.{normalized_name}",
    )

    return safe_import_module(
        module_path,
        required=required,
        force_reload=force_reload,
    )


def get_repository_backend_from_env(default: str = DEFAULT_REPOSITORY_BACKEND) -> str:
    """Liest den gewünschten Repository-Backendnamen aus der Umgebung."""

    env_value = os.getenv(REPOSITORY_BACKEND_ENV)
    return _normalize_key(env_value or default)


def resolve_repository_backend(backend: Optional[str] = None) -> str:
    """
    Normalisiert und validiert den gewünschten Repository-Backendnamen.

    Aktuell unterstützt:
        - sql
    """

    normalized_backend = _normalize_key(
        backend if backend is not None else get_repository_backend_from_env()
    )

    if not normalized_backend:
        normalized_backend = DEFAULT_REPOSITORY_BACKEND

    if normalized_backend not in SUPPORTED_REPOSITORY_BACKENDS:
        supported = ", ".join(SUPPORTED_REPOSITORY_BACKENDS)
        raise RepositoryConfigurationError(
            f"Unsupported repository backend '{normalized_backend}'. "
            f"Supported backends: {supported}"
        )

    return normalized_backend


def get_repository_backend_module(
    backend: Optional[str] = None,
    *,
    required: bool = True,
    force_reload: bool = False,
) -> Optional[ModuleType]:
    """
    Liefert das Modul des gewünschten Repository-Backends.

    Standardmäßig wird das Modul als erforderlich behandelt, weil diese
    Funktion in der Regel von produktiven Services genutzt wird.
    """

    resolved_backend = resolve_repository_backend(backend)
    module_path = REPOSITORY_BACKEND_MODULES[resolved_backend]

    return safe_import_module(
        module_path,
        required=required,
        force_reload=force_reload,
    )


def get_creative_library_repository_module(
    *,
    required: bool = True,
    force_reload: bool = False,
) -> Optional[ModuleType]:
    """
    Importiert das konkrete Creative-Library-Repository-Modul.

    Diese Datei wird erst in einem späteren Schritt erstellt. Bis dahin liefert
    required=False None und required=True eine RepositoryUnavailableError.
    """

    return safe_import_module(
        f"{__name__}.sql.creative_library_repository",
        required=required,
        force_reload=force_reload,
    )


def get_creative_library_repository_class(
    *,
    required: bool = True,
    force_reload: bool = False,
) -> Optional[type]:
    """
    Liefert die Klasse CreativeLibraryRepository aus der SQL-Implementierung.

    Diese Hilfsfunktion verhindert, dass Services selbst Lazy-Import-Logik
    duplizieren müssen.
    """

    module = get_creative_library_repository_module(
        required=required,
        force_reload=force_reload,
    )

    if module is None:
        return None

    repository_class = getattr(module, "CreativeLibraryRepository", None)

    if repository_class is None and required:
        raise RepositoryUnavailableError(
            "CreativeLibraryRepository class is missing in "
            f"{module.__name__}."
        )

    return repository_class


# ---------------------------------------------------------------------------
# Status / health
# ---------------------------------------------------------------------------


def get_repository_subpackage_status(
    name: str,
    *,
    required: Optional[bool] = None,
    attempt_import: bool = True,
    force_reload: bool = False,
    include_traceback: bool = False,
) -> RepositoryModuleStatus:
    """
    Liefert den Status eines Repository-Subpackages.

    attempt_import=True:
        Das Modul wird tatsächlich importiert. Importfehler werden gecached.

    attempt_import=False:
        Es wird nur geprüft, ob das Modul auffindbar ist.
    """

    normalized_name = _normalize_key(name)
    module_path = REPOSITORY_SUBPACKAGE_MODULES.get(
        normalized_name,
        f"{__name__}.{normalized_name}",
    )

    is_required = (
        bool(required)
        if required is not None
        else normalized_name in CORE_REPOSITORY_SUBPACKAGES
    )

    exists, spec_error = _module_exists(module_path)
    module: Optional[ModuleType] = None

    if exists and attempt_import:
        module = safe_import_module(
            module_path,
            required=False,
            force_reload=force_reload,
        )

    cached_error = _get_cached_import_error(module_path)
    effective_error = cached_error or spec_error

    imported = module_path in _MODULE_CACHE

    if attempt_import:
        available = module is not None
    else:
        available = exists and effective_error is None

    error_type, error_message = _exception_to_payload(effective_error)

    if not exists and effective_error is None:
        error_type = "ModuleNotFound"
        error_message = f"Repository subpackage not found: {module_path}"

    return RepositoryModuleStatus(
        name=normalized_name,
        module_path=module_path,
        required=is_required,
        exists=exists,
        imported=imported,
        available=available,
        error_type=error_type,
        error=error_message,
        traceback=_get_cached_traceback(module_path) if include_traceback else None,
    )


def get_repository_subpackage_statuses(
    *,
    strict: bool = False,
    attempt_import: bool = True,
    force_reload: bool = False,
    include_tracebacks: bool = False,
) -> Dict[str, RepositoryModuleStatus]:
    """
    Liefert Statusinformationen für alle bekannten Repository-Subpackages.

    strict beeinflusst hier nicht die Statusdaten selbst, sondern wird aus
    Konsistenzgründen akzeptiert. Die Auswertung erfolgt in get_repositories_health.
    """

    del strict  # Auswertung passiert in get_repositories_health.

    names: List[str] = []

    for name in CORE_REPOSITORY_SUBPACKAGES:
        if name not in names:
            names.append(name)

    for name in OPTIONAL_REPOSITORY_SUBPACKAGES:
        if name not in names:
            names.append(name)

    return {
        name: get_repository_subpackage_status(
            name,
            attempt_import=attempt_import,
            force_reload=force_reload,
            include_traceback=include_tracebacks,
        )
        for name in names
    }


def get_available_repository_backends(
    *,
    attempt_import: bool = False,
    force_reload: bool = False,
) -> List[str]:
    """
    Liefert alle aktuell verfügbaren Repository-Backends.

    Standardmäßig wird nur geprüft, ob das Modul auffindbar ist. Für produktive
    Readiness kann attempt_import=True genutzt werden.
    """

    available: List[str] = []

    for backend in SUPPORTED_REPOSITORY_BACKENDS:
        module_path = REPOSITORY_BACKEND_MODULES[backend]
        exists, spec_error = _module_exists(module_path)

        if not exists or spec_error is not None:
            continue

        if attempt_import:
            module = safe_import_module(
                module_path,
                required=False,
                force_reload=force_reload,
            )
            if module is None:
                continue

        available.append(backend)

    return available


def has_repository_backend(
    backend: str,
    *,
    attempt_import: bool = False,
    force_reload: bool = False,
) -> bool:
    """Prüft, ob ein Repository-Backend verfügbar ist."""

    try:
        resolved_backend = resolve_repository_backend(backend)
    except RepositoryConfigurationError:
        return False

    return resolved_backend in get_available_repository_backends(
        attempt_import=attempt_import,
        force_reload=force_reload,
    )


def get_repositories_health(
    *,
    strict: bool = False,
    attempt_import: bool = True,
    force_reload: bool = False,
    include_tracebacks: bool = False,
    require_backend: Optional[str] = None,
) -> Dict[str, Any]:
    """
    Liefert einen robusten Health-Report der Repository-Schicht.

    strict=False:
        Entwicklungsfreundlich. Fehlende Core-Subpackages werden als Warnung
        gemeldet, aber der Health-Report kann weiterhin ok=True sein.

    strict=True:
        Core-Subpackages und das gewünschte Backend müssen importierbar sein.

    require_backend:
        Zusätzlich zu den bekannten Subpackages kann ein konkretes Backend
        verlangt werden, z. B. "sql".
    """

    statuses = get_repository_subpackage_statuses(
        strict=strict,
        attempt_import=attempt_import,
        force_reload=force_reload,
        include_tracebacks=include_tracebacks,
    )

    errors: List[Dict[str, Any]] = []
    warnings: List[Dict[str, Any]] = []

    for status in statuses.values():
        payload = status.to_dict(include_traceback=include_tracebacks)

        if status.required and not status.available:
            if strict:
                errors.append(payload)
            else:
                warnings.append(payload)

        elif not status.required and not status.available:
            warnings.append(payload)

    backend_error: Optional[str] = None
    resolved_backend: Optional[str] = None

    try:
        resolved_backend = resolve_repository_backend(require_backend)
    except RepositoryConfigurationError as exc:
        backend_error = str(exc)
        errors.append(
            {
                "name": require_backend,
                "module_path": None,
                "required": True,
                "exists": False,
                "imported": False,
                "available": False,
                "ok": False,
                "error_type": exc.__class__.__name__,
                "error": str(exc),
            }
        )

    if resolved_backend is not None:
        backend_available = has_repository_backend(
            resolved_backend,
            attempt_import=attempt_import if strict else False,
            force_reload=force_reload,
        )

        if require_backend and not backend_available:
            payload = {
                "name": resolved_backend,
                "module_path": REPOSITORY_BACKEND_MODULES.get(resolved_backend),
                "required": True,
                "available": False,
                "ok": False,
                "error_type": "RepositoryBackendUnavailable",
                "error": f"Required repository backend is unavailable: {resolved_backend}",
            }

            if strict:
                errors.append(payload)
            else:
                warnings.append(payload)

    ok = not errors

    if not ok:
        status_text = "error"
    elif warnings:
        status_text = "partial"
    else:
        status_text = "ok"

    return {
        "ok": ok,
        "status": status_text,
        "strict": strict,
        "attempt_import": attempt_import,
        "component": REPOSITORIES_COMPONENT_NAME,
        "package": REPOSITORIES_PACKAGE_NAME,
        "python_package": __name__,
        "version": __version__,
        "implementation_stage": REPOSITORIES_IMPLEMENTATION_STAGE,
        "package_root": str(get_repositories_package_root()),
        "default_backend": DEFAULT_REPOSITORY_BACKEND,
        "configured_backend": resolved_backend,
        "backend_error": backend_error,
        "available_backends": get_available_repository_backends(
            attempt_import=False,
            force_reload=force_reload,
        ),
        "subpackages": {
            name: status.to_dict(include_traceback=include_tracebacks)
            for name, status in statuses.items()
        },
        "errors": errors,
        "warnings": warnings,
        "cache": {
            "module_cache_size": len(_MODULE_CACHE),
            "import_error_cache_size": len(_IMPORT_ERROR_CACHE),
            "cached_modules": sorted(_MODULE_CACHE.keys()),
            "cached_import_errors": sorted(_IMPORT_ERROR_CACHE.keys()),
        },
    }


# Backwards-compatible singular alias.
get_repository_health = get_repositories_health


def is_repositories_healthy(
    *,
    strict: bool = False,
    attempt_import: bool = True,
    require_backend: Optional[str] = None,
) -> bool:
    """Gibt True zurück, wenn die Repository-Schicht verwendbar ist."""

    return bool(
        get_repositories_health(
            strict=strict,
            attempt_import=attempt_import,
            require_backend=require_backend,
        ).get("ok")
    )


# Backwards-compatible singular alias.
is_repository_healthy = is_repositories_healthy


def assert_repositories_ready(
    *,
    strict: bool = False,
    attempt_import: bool = True,
    require_backend: Optional[str] = None,
) -> Dict[str, Any]:
    """
    Prüft die Repository-Schicht und wirft bei Fehlern eine klare Exception.

    Standardmäßig ist strict=False, damit die Fassade während inkrementeller
    Entwicklung importierbar bleibt. Produktive Startup-Checks sollten
    strict=True und require_backend="sql" verwenden.
    """

    health = get_repositories_health(
        strict=strict,
        attempt_import=attempt_import,
        require_backend=require_backend,
    )

    if not health.get("ok"):
        error_count = len(health.get("errors") or [])
        warning_count = len(health.get("warnings") or [])

        raise RepositoryUnavailableError(
            "Repository layer is not ready "
            f"(status={health.get('status')}, "
            f"errors={error_count}, warnings={warning_count})."
        )

    return health


# Backwards-compatible singular alias.
assert_repository_ready = assert_repositories_ready


# ---------------------------------------------------------------------------
# Cache handling
# ---------------------------------------------------------------------------


def clear_repository_import_cache() -> Dict[str, Any]:
    """
    Leert nur die Import-/Fehlercaches dieser Fassade.

    Diese Funktion entfernt keine Einträge aus sys.modules. Dadurch bleibt sie
    sicher für laufende Flask-/WSGI-Prozesse.
    """

    with _CACHE_LOCK:
        cleared_modules = sorted(_MODULE_CACHE.keys())
        cleared_errors = sorted(_IMPORT_ERROR_CACHE.keys())

        _MODULE_CACHE.clear()
        _IMPORT_ERROR_CACHE.clear()
        _IMPORT_TRACEBACK_CACHE.clear()

    return {
        "ok": True,
        "cleared_module_cache": cleared_modules,
        "cleared_import_error_cache": cleared_errors,
    }


def clear_repository_runtime_caches() -> Dict[str, Any]:
    """
    Ruft Cache-Clear-Funktionen bereits importierter Repository-Module auf.

    Es werden keine neuen Module importiert. Nur bereits gecachte Module werden
    berücksichtigt. Dadurch ist die Funktion für Admin- und Testbetrieb sicher.
    """

    cleared: List[Dict[str, str]] = []
    failed: List[Dict[str, str]] = []

    with _CACHE_LOCK:
        cached_modules = list(_MODULE_CACHE.items())

    for module_path, module in cached_modules:
        for function_name in CACHE_CLEAR_FUNCTION_NAMES:
            clearer = getattr(module, function_name, None)

            if not callable(clearer):
                continue

            try:
                clearer()
                cleared.append(
                    {
                        "module_path": module_path,
                        "function": function_name,
                    }
                )
                break

            except Exception as exc:  # defensive: cache clearing must be safe
                failed.append(
                    {
                        "module_path": module_path,
                        "function": function_name,
                        "error_type": exc.__class__.__name__,
                        "error": str(exc),
                    }
                )
                break

    return {
        "ok": not failed,
        "cleared": cleared,
        "failed": failed,
    }


def clear_repositories_caches() -> Dict[str, Any]:
    """
    Leert Runtime-Caches der importierten Module und danach den Import-Cache.

    Reihenfolge:
        1. Runtime-Caches konkreter Repositories leeren
        2. Import-/Fehlercache dieser Fassade leeren
    """

    runtime_result = clear_repository_runtime_caches()
    import_result = clear_repository_import_cache()

    return {
        "ok": bool(runtime_result.get("ok")) and bool(import_result.get("ok")),
        "runtime": runtime_result,
        "imports": import_result,
    }


# Backwards-compatible aliases.
clear_repository_caches = clear_repositories_caches
clear_repositories_cache = clear_repositories_caches
clear_repository_cache = clear_repositories_caches


# ---------------------------------------------------------------------------
# Lazy attribute exports
# ---------------------------------------------------------------------------


def __getattr__(name: str) -> Any:
    """
    Lazy-Exports für Subpackages und konkrete Repository-Symbole.

    Beispiele:
        from library.repositories import sql
        from library.repositories import CreativeLibraryRepository

    Wenn die konkrete SQL-Datei noch nicht existiert, wird erst beim Zugriff
    ein klarer AttributeError/RepositoryUnavailableError ausgelöst.
    """

    normalized_name = _normalize_key(name)

    if normalized_name in REPOSITORY_SUBPACKAGE_MODULES:
        module = safe_import_subpackage(normalized_name, required=True)

        if module is None:
            raise AttributeError(
                f"Repository subpackage '{name}' is not available."
            )

        return module

    module_path = SYMBOL_TO_MODULE.get(name)

    if module_path:
        module = safe_import_module(module_path, required=True)

        if module is None:
            raise AttributeError(
                f"Repository symbol '{name}' is not available."
            )

        try:
            return getattr(module, name)
        except AttributeError as exc:
            raise AttributeError(
                f"Repository symbol '{name}' is not defined in {module_path}."
            ) from exc

    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")


def __dir__() -> List[str]:
    """Verbessert Autocomplete für Lazy-Exports."""

    static_names = set(globals().keys())
    static_names.update(REPOSITORY_SUBPACKAGE_MODULES.keys())
    static_names.update(SYMBOL_TO_MODULE.keys())
    return sorted(static_names)


# ---------------------------------------------------------------------------
# Public exports
# ---------------------------------------------------------------------------

__all__ = [
    # Metadata
    "REPOSITORIES_PACKAGE_NAME",
    "REPOSITORIES_COMPONENT_NAME",
    "REPOSITORIES_API_VERSION",
    "REPOSITORIES_IMPLEMENTATION_STAGE",
    "DEFAULT_REPOSITORY_BACKEND",
    "REPOSITORY_BACKEND_ENV",
    "SUPPORTED_REPOSITORY_BACKENDS",
    "CORE_REPOSITORY_SUBPACKAGES",
    "OPTIONAL_REPOSITORY_SUBPACKAGES",

    # Exceptions
    "RepositoryError",
    "RepositoryConfigurationError",
    "RepositoryUnavailableError",

    # Status models
    "RepositoryModuleStatus",

    # Info
    "get_repositories_package_root",
    "get_repositories_info",
    "get_repository_info",

    # Imports
    "safe_import_module",
    "safe_import_subpackage",
    "get_repository_backend_from_env",
    "resolve_repository_backend",
    "get_repository_backend_module",
    "get_creative_library_repository_module",
    "get_creative_library_repository_class",

    # Health
    "get_repository_subpackage_status",
    "get_repository_subpackage_statuses",
    "get_available_repository_backends",
    "has_repository_backend",
    "get_repositories_health",
    "get_repository_health",
    "is_repositories_healthy",
    "is_repository_healthy",
    "assert_repositories_ready",
    "assert_repository_ready",

    # Cache
    "clear_repository_import_cache",
    "clear_repository_runtime_caches",
    "clear_repositories_caches",
    "clear_repository_caches",
    "clear_repositories_cache",
    "clear_repository_cache",

    # Future lazy symbols
    "CreativeLibraryRepository",
    "CreativeLibraryRepositoryConfig",
    "CreativeLibraryRepositoryError",
    "CreativeLibraryRepositoryUnavailable",
    "CreativeLibraryRepositoryConflict",
    "CreativeLibraryRepositoryNotFound",
    "create_creative_library_repository",
    "get_creative_library_repository",
    "get_default_creative_library_repository",
    "clear_creative_library_repository_cache",
    "get_creative_library_repository_health",
    "assert_creative_library_repository_ready",
]