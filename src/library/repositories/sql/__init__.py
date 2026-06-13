# services/vectoplan-library/src/library/repositories/sql/__init__.py
"""
SQL-Repository-Fassade für die fachliche Creative-Library-Schicht.

Diese Datei bündelt alle SQL-/DB-nahen Repository-Einstiegspunkte für:

- Creative-Library-Families
- Family-Revisions
- Varianten
- Assets
- Dokumente
- ScanRuns
- ScanIssues
- Inventar-Slots
- spätere Publication-/Overlay-Zustände

Wichtig:

Diese Datei ist absichtlich import-sicher und seiteneffektfrei.

Sie darf beim Import:

- keine Datenbankverbindung öffnen
- keine Queries ausführen
- keine Tabellen erzeugen
- keine Migrationen starten
- keine Models hart erzwingen
- keine Flask-App benötigen

Die konkrete Repository-Implementierung folgt in:

    services/vectoplan-library/src/library/repositories/sql/creative_library_repository.py

Diese Fassade bereitet Lazy Imports, Health Checks, Cache Clearing und robuste
Fehlerdiagnose vor.
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

SQL_REPOSITORIES_PACKAGE_NAME = "library.repositories.sql"
SQL_REPOSITORIES_COMPONENT_NAME = "creative_library_sql_repositories"
SQL_REPOSITORIES_API_VERSION = "v1"
SQL_REPOSITORIES_IMPLEMENTATION_STAGE = "sql-repository-facade"

__version__ = "0.1.0"


# ---------------------------------------------------------------------------
# Module configuration
# ---------------------------------------------------------------------------

CREATIVE_LIBRARY_REPOSITORY_MODULE_ENV = "VPLIB_CREATIVE_LIBRARY_REPOSITORY_MODULE"
CREATIVE_LIBRARY_MODEL_MODULE_ENV = "VPLIB_CREATIVE_LIBRARY_MODEL_MODULE"
SQLALCHEMY_EXTENSION_MODULE_ENV = "VPLIB_SQLALCHEMY_EXTENSION_MODULE"

DEFAULT_CREATIVE_LIBRARY_REPOSITORY_MODULE = f"{__name__}.creative_library_repository"

# In der üblichen Service-Struktur liegt models/creative_library.py im
# Service-Root und ist als "models.creative_library" importierbar.
DEFAULT_CREATIVE_LIBRARY_MODEL_MODULE = "models.creative_library"

# In vielen Flask-Services liegt das SQLAlchemy-Objekt in extensions.py.
DEFAULT_SQLALCHEMY_EXTENSION_MODULE = "extensions"

SQL_REPOSITORY_MODULES: Mapping[str, str] = {
    "creative_library_repository": DEFAULT_CREATIVE_LIBRARY_REPOSITORY_MODULE,
}

CORE_SQL_REPOSITORY_MODULES: Tuple[str, ...] = (
    "creative_library_repository",
)

OPTIONAL_SQL_REPOSITORY_MODULES: Tuple[str, ...] = ()

# Diese Symbolnamen werden später aus creative_library_repository.py lazy
# exportiert. Die Datei darf noch fehlen; erst beim Zugriff wird importiert.
SYMBOL_TO_MODULE: Mapping[str, str] = {
    # Config / repository / errors
    "CreativeLibraryRepository": DEFAULT_CREATIVE_LIBRARY_REPOSITORY_MODULE,
    "CreativeLibraryRepositoryConfig": DEFAULT_CREATIVE_LIBRARY_REPOSITORY_MODULE,
    "CreativeLibraryRepositoryError": DEFAULT_CREATIVE_LIBRARY_REPOSITORY_MODULE,
    "CreativeLibraryRepositoryUnavailable": DEFAULT_CREATIVE_LIBRARY_REPOSITORY_MODULE,
    "CreativeLibraryRepositoryConflict": DEFAULT_CREATIVE_LIBRARY_REPOSITORY_MODULE,
    "CreativeLibraryRepositoryNotFound": DEFAULT_CREATIVE_LIBRARY_REPOSITORY_MODULE,
    "CreativeLibraryRepositoryValidationError": DEFAULT_CREATIVE_LIBRARY_REPOSITORY_MODULE,

    # Scan runs
    "CreativeLibraryScanRunPayload": DEFAULT_CREATIVE_LIBRARY_REPOSITORY_MODULE,
    "CreativeLibraryScanRunSummary": DEFAULT_CREATIVE_LIBRARY_REPOSITORY_MODULE,

    # Sync / upsert payloads
    "CreativeLibraryFamilyUpsertPayload": DEFAULT_CREATIVE_LIBRARY_REPOSITORY_MODULE,
    "CreativeLibraryRevisionUpsertPayload": DEFAULT_CREATIVE_LIBRARY_REPOSITORY_MODULE,
    "CreativeLibraryVariantPayload": DEFAULT_CREATIVE_LIBRARY_REPOSITORY_MODULE,
    "CreativeLibraryAssetPayload": DEFAULT_CREATIVE_LIBRARY_REPOSITORY_MODULE,
    "CreativeLibraryDocumentPayload": DEFAULT_CREATIVE_LIBRARY_REPOSITORY_MODULE,
    "CreativeLibraryIssuePayload": DEFAULT_CREATIVE_LIBRARY_REPOSITORY_MODULE,

    # Factory / lifecycle
    "create_creative_library_repository": DEFAULT_CREATIVE_LIBRARY_REPOSITORY_MODULE,
    "get_creative_library_repository": DEFAULT_CREATIVE_LIBRARY_REPOSITORY_MODULE,
    "get_default_creative_library_repository": DEFAULT_CREATIVE_LIBRARY_REPOSITORY_MODULE,

    # Health / cache
    "get_creative_library_repository_health": DEFAULT_CREATIVE_LIBRARY_REPOSITORY_MODULE,
    "assert_creative_library_repository_ready": DEFAULT_CREATIVE_LIBRARY_REPOSITORY_MODULE,
    "clear_creative_library_repository_cache": DEFAULT_CREATIVE_LIBRARY_REPOSITORY_MODULE,
    "clear_creative_library_repository_caches": DEFAULT_CREATIVE_LIBRARY_REPOSITORY_MODULE,
}

CACHE_CLEAR_FUNCTION_NAMES: Tuple[str, ...] = (
    "clear_cache",
    "clear_caches",
    "clear_repository_cache",
    "clear_repository_caches",
    "clear_sql_repository_cache",
    "clear_sql_repository_caches",
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


class SqlRepositoryError(RuntimeError):
    """Basisklasse für SQL-Repository-Fassadenfehler."""


class SqlRepositoryConfigurationError(SqlRepositoryError):
    """Fehlerhafte SQL-Repository-Konfiguration."""


class SqlRepositoryUnavailableError(SqlRepositoryError):
    """SQL-Repository-Modul oder SQL-Abhängigkeit ist nicht verfügbar."""


# ---------------------------------------------------------------------------
# Status models
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class SqlRepositoryModuleStatus:
    """
    Status eines SQL-Repository-Moduls.

    exists:
        Das Modul ist über importlib auffindbar.

    imported:
        Das Modul liegt im lokalen Import-Cache dieser Fassade.

    available:
        Das Modul ist nutzbar.
        Bei attempt_import=True bedeutet das: Import erfolgreich.
        Bei attempt_import=False bedeutet das: Spec gefunden und kein Spec-Fehler.
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


@dataclass(frozen=True)
class SqlDependencyStatus:
    """
    Status einer externen SQL-Abhängigkeit.

    Beispiele:
        - models.creative_library
        - extensions
    """

    name: str
    candidates: Tuple[str, ...]
    selected_module_path: Optional[str]
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
            "candidates": list(self.candidates),
            "selected_module_path": self.selected_module_path,
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
# Internal helpers
# ---------------------------------------------------------------------------


def _normalize_key(value: Any) -> str:
    """Normalisiert technische Keys für Modul- und Dependency-Namen."""

    return str(value or "").strip().lower().replace("-", "_")


def _split_env_candidates(value: Optional[str]) -> Tuple[str, ...]:
    """
    Zerlegt eine Environment-Variable mit Modulpfad-Kandidaten.

    Erlaubt:
        "a.b.c"
        "a.b.c,d.e.f"
        "a.b.c;d.e.f"
        "a.b.c d.e.f"
    """

    if not value:
        return ()

    raw = str(value).replace(";", ",").replace(" ", ",")
    parts = [part.strip() for part in raw.split(",")]
    return tuple(part for part in parts if part)


def _dedupe(values: Iterable[str]) -> Tuple[str, ...]:
    seen: set[str] = set()
    result: List[str] = []

    for value in values:
        normalized = str(value or "").strip()

        if not normalized or normalized in seen:
            continue

        seen.add(normalized)
        result.append(normalized)

    return tuple(result)


def _module_exists(module_path: str) -> Tuple[bool, Optional[BaseException]]:
    """
    Prüft, ob ein Modul auffindbar ist, ohne es aktiv zu importieren.

    importlib.util.find_spec kann bei beschädigten Parent-Packages trotzdem
    Exceptions werfen. Diese werden defensiv zurückgegeben.
    """

    try:
        return importlib.util.find_spec(module_path) is not None, None
    except Exception as exc:
        return False, exc


def _exception_to_payload(exc: Optional[BaseException]) -> Tuple[Optional[str], Optional[str]]:
    if exc is None:
        return None, None

    return exc.__class__.__name__, str(exc)


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
        return f"SQL repository module is not available: {module_path}"

    return (
        f"SQL repository module is not available: {module_path} "
        f"({exc.__class__.__name__}: {exc})"
    )


# ---------------------------------------------------------------------------
# Basic package helpers
# ---------------------------------------------------------------------------


def get_sql_repositories_package_root() -> Path:
    """Gibt den absoluten Pfad dieses SQL-Repository-Packages zurück."""

    return Path(__file__).resolve().parent


def get_sql_repositories_info() -> Dict[str, Any]:
    """Liefert statische Informationen über die SQL-Repository-Fassade."""

    return {
        "package": SQL_REPOSITORIES_PACKAGE_NAME,
        "python_package": __name__,
        "component": SQL_REPOSITORIES_COMPONENT_NAME,
        "api_version": SQL_REPOSITORIES_API_VERSION,
        "implementation_stage": SQL_REPOSITORIES_IMPLEMENTATION_STAGE,
        "version": __version__,
        "package_root": str(get_sql_repositories_package_root()),
        "repository_module_env": CREATIVE_LIBRARY_REPOSITORY_MODULE_ENV,
        "model_module_env": CREATIVE_LIBRARY_MODEL_MODULE_ENV,
        "sqlalchemy_extension_module_env": SQLALCHEMY_EXTENSION_MODULE_ENV,
        "default_repository_module": DEFAULT_CREATIVE_LIBRARY_REPOSITORY_MODULE,
        "default_model_module": DEFAULT_CREATIVE_LIBRARY_MODEL_MODULE,
        "default_sqlalchemy_extension_module": DEFAULT_SQLALCHEMY_EXTENSION_MODULE,
        "core_modules": list(CORE_SQL_REPOSITORY_MODULES),
        "optional_modules": list(OPTIONAL_SQL_REPOSITORY_MODULES),
    }


# Backwards-compatible alias.
get_sql_repository_info = get_sql_repositories_info


# ---------------------------------------------------------------------------
# Module path resolution
# ---------------------------------------------------------------------------


def get_creative_library_repository_module_path() -> str:
    """
    Liefert den Modulpfad der konkreten Creative-Library-Repository-Implementierung.

    Standard:
        library.repositories.sql.creative_library_repository

    Überschreibbar über:
        VPLIB_CREATIVE_LIBRARY_REPOSITORY_MODULE
    """

    configured = os.getenv(CREATIVE_LIBRARY_REPOSITORY_MODULE_ENV)
    return str(configured or DEFAULT_CREATIVE_LIBRARY_REPOSITORY_MODULE).strip()


def get_creative_library_model_module_candidates() -> Tuple[str, ...]:
    """
    Liefert mögliche Modulpfade für models/creative_library.py.

    Standard:
        models.creative_library

    Erweiterbar über:
        VPLIB_CREATIVE_LIBRARY_MODEL_MODULE

    Die Environment-Variable darf mehrere Kandidaten enthalten.
    """

    env_candidates = _split_env_candidates(os.getenv(CREATIVE_LIBRARY_MODEL_MODULE_ENV))
    return _dedupe(
        (
            *env_candidates,
            DEFAULT_CREATIVE_LIBRARY_MODEL_MODULE,
        )
    )


def get_sqlalchemy_extension_module_candidates() -> Tuple[str, ...]:
    """
    Liefert mögliche Modulpfade für das Flask-/SQLAlchemy-Extension-Modul.

    Standard:
        extensions

    Erweiterbar über:
        VPLIB_SQLALCHEMY_EXTENSION_MODULE
    """

    env_candidates = _split_env_candidates(os.getenv(SQLALCHEMY_EXTENSION_MODULE_ENV))
    return _dedupe(
        (
            *env_candidates,
            DEFAULT_SQLALCHEMY_EXTENSION_MODULE,
        )
    )


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
    Importiert ein Modul robust und cached Ergebnis oder Fehler.

    required=False:
        Importfehler werden gecached und als None zurückgegeben.

    required=True:
        Importfehler werden als SqlRepositoryUnavailableError geworfen.
    """

    normalized_path = str(module_path or "").strip()

    if not normalized_path:
        exc = SqlRepositoryConfigurationError("Empty SQL repository module path.")
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

    except Exception as exc:
        _store_import_error(normalized_path, exc)

        if required:
            raise SqlRepositoryUnavailableError(
                _build_unavailable_message(normalized_path, exc)
            ) from exc

        return None


def safe_import_first_available(
    candidates: Sequence[str],
    *,
    required: bool = False,
    force_reload: bool = False,
) -> Optional[ModuleType]:
    """
    Importiert den ersten verfügbaren Modulpfad aus einer Kandidatenliste.

    Diese Funktion ist für Umgebungen gedacht, in denen App-/Service-Root oder
    PYTHONPATH je nach Startmodus leicht unterschiedlich sind.
    """

    last_error: Optional[BaseException] = None

    for module_path in candidates:
        normalized_path = str(module_path or "").strip()

        if not normalized_path:
            continue

        module = safe_import_module(
            normalized_path,
            required=False,
            force_reload=force_reload,
        )

        if module is not None:
            return module

        last_error = _get_cached_import_error(normalized_path)

    if required:
        joined = ", ".join(str(candidate) for candidate in candidates)

        if last_error is not None:
            raise SqlRepositoryUnavailableError(
                f"No candidate module could be imported: {joined} "
                f"({last_error.__class__.__name__}: {last_error})"
            ) from last_error

        raise SqlRepositoryUnavailableError(
            f"No candidate module could be imported: {joined}"
        )

    return None


def safe_import_sql_module(
    name: str,
    *,
    required: bool = False,
    force_reload: bool = False,
) -> Optional[ModuleType]:
    """Importiert ein bekanntes SQL-Repository-Modul anhand seines Kurznamens."""

    normalized_name = _normalize_key(name)
    module_path = SQL_REPOSITORY_MODULES.get(
        normalized_name,
        f"{__name__}.{normalized_name}",
    )

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
    """Importiert die konkrete Creative-Library-Repository-Implementierung."""

    return safe_import_module(
        get_creative_library_repository_module_path(),
        required=required,
        force_reload=force_reload,
    )


def get_creative_library_model_module(
    *,
    required: bool = False,
    force_reload: bool = False,
) -> Optional[ModuleType]:
    """
    Importiert das Model-Modul für creative_library-Tabellen.

    Standardmäßig nicht required, damit diese Fassade auch während der
    inkrementellen Implementierung stabil importierbar bleibt.
    """

    return safe_import_first_available(
        get_creative_library_model_module_candidates(),
        required=required,
        force_reload=force_reload,
    )


def get_sqlalchemy_extension_module(
    *,
    required: bool = False,
    force_reload: bool = False,
) -> Optional[ModuleType]:
    """
    Importiert das Extension-Modul, typischerweise extensions.py.

    Standardmäßig nicht required, weil Tests und CLI-Kontexte nicht immer eine
    Flask-App oder SQLAlchemy-Extension initialisieren.
    """

    return safe_import_first_available(
        get_sqlalchemy_extension_module_candidates(),
        required=required,
        force_reload=force_reload,
    )


def get_sqlalchemy_db_object(
    *,
    required: bool = False,
    force_reload: bool = False,
) -> Any:
    """
    Liefert das SQLAlchemy-db-Objekt aus dem Extension-Modul.

    Erwartete Namen:
        db
        database
        sqlalchemy_db

    Gibt None zurück, wenn kein Objekt gefunden wurde und required=False ist.
    """

    module = get_sqlalchemy_extension_module(
        required=required,
        force_reload=force_reload,
    )

    if module is None:
        return None

    for attr_name in ("db", "database", "sqlalchemy_db"):
        value = getattr(module, attr_name, None)
        if value is not None:
            return value

    if required:
        raise SqlRepositoryUnavailableError(
            "SQLAlchemy db object was not found in extension module. "
            "Expected one of: db, database, sqlalchemy_db."
        )

    return None


def get_creative_library_repository_class(
    *,
    required: bool = True,
    force_reload: bool = False,
) -> Optional[type]:
    """Liefert die Klasse CreativeLibraryRepository aus der Implementierungsdatei."""

    module = get_creative_library_repository_module(
        required=required,
        force_reload=force_reload,
    )

    if module is None:
        return None

    repository_class = getattr(module, "CreativeLibraryRepository", None)

    if repository_class is None and required:
        raise SqlRepositoryUnavailableError(
            "CreativeLibraryRepository class is missing in "
            f"{module.__name__}."
        )

    return repository_class


# ---------------------------------------------------------------------------
# Repository factory wrappers
# ---------------------------------------------------------------------------


def create_creative_library_repository(*args: Any, **kwargs: Any) -> Any:
    """
    Erstellt eine CreativeLibraryRepository-Instanz.

    Delegationsreihenfolge:
        1. create_creative_library_repository(...) im konkreten Modul
        2. CreativeLibraryRepository(...) Klasse im konkreten Modul
    """

    module = get_creative_library_repository_module(required=True)
    assert module is not None

    factory = getattr(module, "create_creative_library_repository", None)
    if callable(factory):
        return factory(*args, **kwargs)

    repository_class = getattr(module, "CreativeLibraryRepository", None)
    if repository_class is None:
        raise SqlRepositoryUnavailableError(
            "Neither create_creative_library_repository nor "
            "CreativeLibraryRepository is available."
        )

    return repository_class(*args, **kwargs)


def get_creative_library_repository(*args: Any, **kwargs: Any) -> Any:
    """
    Liefert eine CreativeLibraryRepository-Instanz.

    Falls die konkrete Implementierung eine eigene get-Funktion anbietet, wird
    sie verwendet. Andernfalls wird eine neue Instanz erzeugt.
    """

    module = get_creative_library_repository_module(required=True)
    assert module is not None

    getter = getattr(module, "get_creative_library_repository", None)
    if callable(getter):
        return getter(*args, **kwargs)

    return create_creative_library_repository(*args, **kwargs)


def get_default_creative_library_repository(*args: Any, **kwargs: Any) -> Any:
    """
    Liefert das Default-Repository.

    Diese Funktion ist für Services gedacht, die keine eigene Repository-Instanz
    injizieren. Die konkrete Implementierung kann intern cachen.
    """

    module = get_creative_library_repository_module(required=True)
    assert module is not None

    getter = getattr(module, "get_default_creative_library_repository", None)
    if callable(getter):
        return getter(*args, **kwargs)

    getter = getattr(module, "get_creative_library_repository", None)
    if callable(getter):
        return getter(*args, **kwargs)

    return create_creative_library_repository(*args, **kwargs)


# ---------------------------------------------------------------------------
# Status / health
# ---------------------------------------------------------------------------


def get_sql_repository_module_status(
    name: str,
    *,
    required: Optional[bool] = None,
    attempt_import: bool = True,
    force_reload: bool = False,
    include_traceback: bool = False,
) -> SqlRepositoryModuleStatus:
    """Liefert Statusinformationen für ein SQL-Repository-Modul."""

    normalized_name = _normalize_key(name)

    if normalized_name == "creative_library_repository":
        module_path = get_creative_library_repository_module_path()
    else:
        module_path = SQL_REPOSITORY_MODULES.get(
            normalized_name,
            f"{__name__}.{normalized_name}",
        )

    is_required = (
        bool(required)
        if required is not None
        else normalized_name in CORE_SQL_REPOSITORY_MODULES
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
        error_message = f"SQL repository module not found: {module_path}"

    return SqlRepositoryModuleStatus(
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


def get_sql_repository_module_statuses(
    *,
    strict: bool = False,
    attempt_import: bool = True,
    force_reload: bool = False,
    include_tracebacks: bool = False,
) -> Dict[str, SqlRepositoryModuleStatus]:
    """
    Liefert Statusinformationen für alle bekannten SQL-Repository-Module.

    strict wird aus Konsistenzgründen akzeptiert; die harte Bewertung passiert
    in get_sql_repositories_health.
    """

    del strict

    names: List[str] = []

    for name in CORE_SQL_REPOSITORY_MODULES:
        if name not in names:
            names.append(name)

    for name in OPTIONAL_SQL_REPOSITORY_MODULES:
        if name not in names:
            names.append(name)

    return {
        name: get_sql_repository_module_status(
            name,
            attempt_import=attempt_import,
            force_reload=force_reload,
            include_traceback=include_tracebacks,
        )
        for name in names
    }


def get_dependency_status(
    name: str,
    candidates: Sequence[str],
    *,
    required: bool = False,
    attempt_import: bool = False,
    force_reload: bool = False,
    include_traceback: bool = False,
) -> SqlDependencyStatus:
    """
    Liefert Statusinformationen für eine externe SQL-Abhängigkeit.

    Für Kandidaten wird der erste vorhandene/importierbare Modulpfad verwendet.
    """

    normalized_candidates = _dedupe(candidates)

    selected_module_path: Optional[str] = None
    selected_error: Optional[BaseException] = None
    selected_traceback: Optional[str] = None

    exists = False
    imported = False
    available = False

    for module_path in normalized_candidates:
        module_exists, spec_error = _module_exists(module_path)

        if not module_exists:
            selected_error = selected_error or spec_error
            continue

        exists = True
        selected_module_path = module_path

        if attempt_import:
            module = safe_import_module(
                module_path,
                required=False,
                force_reload=force_reload,
            )

            if module is not None:
                imported = True
                available = True
                selected_error = None
                selected_traceback = None
                break

            selected_error = _get_cached_import_error(module_path)
            selected_traceback = _get_cached_traceback(module_path)

        else:
            if spec_error is None:
                available = True
                selected_error = None
                selected_traceback = None
                break

            selected_error = spec_error

    error_type, error_message = _exception_to_payload(selected_error)

    if not exists and error_message is None:
        error_type = "ModuleNotFound"
        error_message = (
            f"No dependency module found for {name}. "
            f"Candidates: {', '.join(normalized_candidates)}"
        )

    return SqlDependencyStatus(
        name=name,
        candidates=normalized_candidates,
        selected_module_path=selected_module_path,
        required=required,
        exists=exists,
        imported=imported,
        available=available,
        error_type=error_type,
        error=error_message,
        traceback=selected_traceback if include_traceback else None,
    )


def get_creative_library_model_status(
    *,
    required: bool = False,
    attempt_import: bool = False,
    force_reload: bool = False,
    include_traceback: bool = False,
) -> SqlDependencyStatus:
    """Liefert Health-Status für models/creative_library.py."""

    return get_dependency_status(
        "creative_library_models",
        get_creative_library_model_module_candidates(),
        required=required,
        attempt_import=attempt_import,
        force_reload=force_reload,
        include_traceback=include_traceback,
    )


def get_sqlalchemy_extension_status(
    *,
    required: bool = False,
    attempt_import: bool = False,
    force_reload: bool = False,
    include_traceback: bool = False,
) -> SqlDependencyStatus:
    """Liefert Health-Status für das SQLAlchemy-/extensions-Modul."""

    return get_dependency_status(
        "sqlalchemy_extension",
        get_sqlalchemy_extension_module_candidates(),
        required=required,
        attempt_import=attempt_import,
        force_reload=force_reload,
        include_traceback=include_traceback,
    )


def get_sql_repositories_health(
    *,
    strict: bool = False,
    attempt_import: bool = True,
    force_reload: bool = False,
    include_tracebacks: bool = False,
    require_models: bool = False,
    require_sqlalchemy_extension: bool = False,
) -> Dict[str, Any]:
    """
    Liefert einen robusten Health-Report der SQL-Repository-Schicht.

    strict=False:
        Entwicklungsfreundlich. Fehlende Repository-Implementierung wird als
        Warnung gemeldet.

    strict=True:
        Core-SQL-Repository-Module müssen importierbar sein.

    require_models=True:
        models.creative_library muss verfügbar sein.

    require_sqlalchemy_extension=True:
        extensions.py beziehungsweise das konfigurierte Extension-Modul muss
        verfügbar sein.
    """

    module_statuses = get_sql_repository_module_statuses(
        strict=strict,
        attempt_import=attempt_import,
        force_reload=force_reload,
        include_tracebacks=include_tracebacks,
    )

    model_status = get_creative_library_model_status(
        required=require_models,
        attempt_import=attempt_import if require_models else False,
        force_reload=force_reload,
        include_traceback=include_tracebacks,
    )

    extension_status = get_sqlalchemy_extension_status(
        required=require_sqlalchemy_extension,
        attempt_import=attempt_import if require_sqlalchemy_extension else False,
        force_reload=force_reload,
        include_traceback=include_tracebacks,
    )

    errors: List[Dict[str, Any]] = []
    warnings: List[Dict[str, Any]] = []

    for status in module_statuses.values():
        payload = status.to_dict(include_traceback=include_tracebacks)

        if status.required and not status.available:
            if strict:
                errors.append(payload)
            else:
                warnings.append(payload)

        elif not status.required and not status.available:
            warnings.append(payload)

    for dependency_status in (model_status, extension_status):
        payload = dependency_status.to_dict(include_traceback=include_tracebacks)

        if dependency_status.required and not dependency_status.available:
            errors.append(payload)

        elif not dependency_status.available:
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
        "component": SQL_REPOSITORIES_COMPONENT_NAME,
        "package": SQL_REPOSITORIES_PACKAGE_NAME,
        "python_package": __name__,
        "version": __version__,
        "implementation_stage": SQL_REPOSITORIES_IMPLEMENTATION_STAGE,
        "package_root": str(get_sql_repositories_package_root()),
        "repository_module": get_creative_library_repository_module_path(),
        "model_module_candidates": list(get_creative_library_model_module_candidates()),
        "sqlalchemy_extension_candidates": list(get_sqlalchemy_extension_module_candidates()),
        "modules": {
            name: status.to_dict(include_traceback=include_tracebacks)
            for name, status in module_statuses.items()
        },
        "dependencies": {
            "creative_library_models": model_status.to_dict(
                include_traceback=include_tracebacks
            ),
            "sqlalchemy_extension": extension_status.to_dict(
                include_traceback=include_tracebacks
            ),
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


# Backwards-compatible aliases.
get_sql_repository_health = get_sql_repositories_health
get_repositories_health = get_sql_repositories_health


def is_sql_repositories_healthy(
    *,
    strict: bool = False,
    attempt_import: bool = True,
    require_models: bool = False,
    require_sqlalchemy_extension: bool = False,
) -> bool:
    """Gibt True zurück, wenn die SQL-Repository-Schicht verwendbar ist."""

    return bool(
        get_sql_repositories_health(
            strict=strict,
            attempt_import=attempt_import,
            require_models=require_models,
            require_sqlalchemy_extension=require_sqlalchemy_extension,
        ).get("ok")
    )


# Backwards-compatible aliases.
is_sql_repository_healthy = is_sql_repositories_healthy
is_repositories_healthy = is_sql_repositories_healthy


def assert_sql_repositories_ready(
    *,
    strict: bool = True,
    attempt_import: bool = True,
    require_models: bool = False,
    require_sqlalchemy_extension: bool = False,
) -> Dict[str, Any]:
    """
    Prüft die SQL-Repository-Schicht und wirft bei Fehlern eine klare Exception.

    Für produktive Startup-Checks sinnvoll:

        assert_sql_repositories_ready(
            strict=True,
            require_models=True,
            require_sqlalchemy_extension=True,
        )
    """

    health = get_sql_repositories_health(
        strict=strict,
        attempt_import=attempt_import,
        require_models=require_models,
        require_sqlalchemy_extension=require_sqlalchemy_extension,
    )

    if not health.get("ok"):
        error_count = len(health.get("errors") or [])
        warning_count = len(health.get("warnings") or [])

        raise SqlRepositoryUnavailableError(
            "SQL repository layer is not ready "
            f"(status={health.get('status')}, "
            f"errors={error_count}, warnings={warning_count})."
        )

    return health


# Backwards-compatible aliases.
assert_sql_repository_ready = assert_sql_repositories_ready
assert_repositories_ready = assert_sql_repositories_ready


# ---------------------------------------------------------------------------
# Cache handling
# ---------------------------------------------------------------------------


def clear_sql_repository_import_cache() -> Dict[str, Any]:
    """
    Leert nur die Import-/Fehlercaches dieser SQL-Fassade.

    Es werden keine Einträge aus sys.modules entfernt.
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


def clear_sql_repository_runtime_caches() -> Dict[str, Any]:
    """
    Ruft Cache-Clear-Funktionen bereits importierter SQL-Repository-Module auf.

    Es werden keine neuen Module importiert.
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

            except Exception as exc:
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


def clear_sql_repository_caches() -> Dict[str, Any]:
    """
    Leert Runtime-Caches importierter Module und danach den lokalen Importcache.
    """

    runtime_result = clear_sql_repository_runtime_caches()
    import_result = clear_sql_repository_import_cache()

    return {
        "ok": bool(runtime_result.get("ok")) and bool(import_result.get("ok")),
        "runtime": runtime_result,
        "imports": import_result,
    }


# Backwards-compatible aliases.
clear_sql_repositories_cache = clear_sql_repository_caches
clear_sql_repositories_caches = clear_sql_repository_caches
clear_repository_cache = clear_sql_repository_caches
clear_repository_caches = clear_sql_repository_caches
clear_repositories_cache = clear_sql_repository_caches
clear_repositories_caches = clear_sql_repository_caches


# ---------------------------------------------------------------------------
# Lazy attribute exports
# ---------------------------------------------------------------------------


def __getattr__(name: str) -> Any:
    """
    Lazy-Exports für SQL-Repository-Module und konkrete Symbole.

    Beispiele:
        from library.repositories.sql import creative_library_repository
        from library.repositories.sql import CreativeLibraryRepository
    """

    normalized_name = _normalize_key(name)

    if normalized_name in SQL_REPOSITORY_MODULES:
        module = safe_import_sql_module(normalized_name, required=True)

        if module is None:
            raise AttributeError(
                f"SQL repository module '{name}' is not available."
            )

        return module

    module_path = SYMBOL_TO_MODULE.get(name)

    if module_path:
        # Falls der Modulpfad per Environment überschrieben wurde, gilt das
        # für alle CreativeLibraryRepository-Symbole.
        if module_path == DEFAULT_CREATIVE_LIBRARY_REPOSITORY_MODULE:
            module_path = get_creative_library_repository_module_path()

        module = safe_import_module(module_path, required=True)

        if module is None:
            raise AttributeError(
                f"SQL repository symbol '{name}' is not available."
            )

        try:
            return getattr(module, name)
        except AttributeError as exc:
            raise AttributeError(
                f"SQL repository symbol '{name}' is not defined in {module_path}."
            ) from exc

    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")


def __dir__() -> List[str]:
    """Verbessert Autocomplete für Lazy-Exports."""

    names = set(globals().keys())
    names.update(SQL_REPOSITORY_MODULES.keys())
    names.update(SYMBOL_TO_MODULE.keys())
    return sorted(names)


# ---------------------------------------------------------------------------
# Public exports
# ---------------------------------------------------------------------------

__all__ = [
    # Metadata
    "SQL_REPOSITORIES_PACKAGE_NAME",
    "SQL_REPOSITORIES_COMPONENT_NAME",
    "SQL_REPOSITORIES_API_VERSION",
    "SQL_REPOSITORIES_IMPLEMENTATION_STAGE",
    "CREATIVE_LIBRARY_REPOSITORY_MODULE_ENV",
    "CREATIVE_LIBRARY_MODEL_MODULE_ENV",
    "SQLALCHEMY_EXTENSION_MODULE_ENV",
    "DEFAULT_CREATIVE_LIBRARY_REPOSITORY_MODULE",
    "DEFAULT_CREATIVE_LIBRARY_MODEL_MODULE",
    "DEFAULT_SQLALCHEMY_EXTENSION_MODULE",
    "CORE_SQL_REPOSITORY_MODULES",
    "OPTIONAL_SQL_REPOSITORY_MODULES",

    # Exceptions
    "SqlRepositoryError",
    "SqlRepositoryConfigurationError",
    "SqlRepositoryUnavailableError",

    # Status models
    "SqlRepositoryModuleStatus",
    "SqlDependencyStatus",

    # Info
    "get_sql_repositories_package_root",
    "get_sql_repositories_info",
    "get_sql_repository_info",

    # Module path resolution
    "get_creative_library_repository_module_path",
    "get_creative_library_model_module_candidates",
    "get_sqlalchemy_extension_module_candidates",

    # Imports
    "safe_import_module",
    "safe_import_first_available",
    "safe_import_sql_module",
    "get_creative_library_repository_module",
    "get_creative_library_model_module",
    "get_sqlalchemy_extension_module",
    "get_sqlalchemy_db_object",
    "get_creative_library_repository_class",

    # Factories
    "create_creative_library_repository",
    "get_creative_library_repository",
    "get_default_creative_library_repository",

    # Health
    "get_sql_repository_module_status",
    "get_sql_repository_module_statuses",
    "get_dependency_status",
    "get_creative_library_model_status",
    "get_sqlalchemy_extension_status",
    "get_sql_repositories_health",
    "get_sql_repository_health",
    "get_repositories_health",
    "is_sql_repositories_healthy",
    "is_sql_repository_healthy",
    "is_repositories_healthy",
    "assert_sql_repositories_ready",
    "assert_sql_repository_ready",
    "assert_repositories_ready",

    # Cache
    "clear_sql_repository_import_cache",
    "clear_sql_repository_runtime_caches",
    "clear_sql_repository_caches",
    "clear_sql_repositories_cache",
    "clear_sql_repositories_caches",
    "clear_repository_cache",
    "clear_repository_caches",
    "clear_repositories_cache",
    "clear_repositories_caches",

    # Future lazy repository symbols
    "CreativeLibraryRepository",
    "CreativeLibraryRepositoryConfig",
    "CreativeLibraryRepositoryError",
    "CreativeLibraryRepositoryUnavailable",
    "CreativeLibraryRepositoryConflict",
    "CreativeLibraryRepositoryNotFound",
    "CreativeLibraryRepositoryValidationError",
    "CreativeLibraryScanRunPayload",
    "CreativeLibraryScanRunSummary",
    "CreativeLibraryFamilyUpsertPayload",
    "CreativeLibraryRevisionUpsertPayload",
    "CreativeLibraryVariantPayload",
    "CreativeLibraryAssetPayload",
    "CreativeLibraryDocumentPayload",
    "CreativeLibraryIssuePayload",
    "get_creative_library_repository_health",
    "assert_creative_library_repository_ready",
    "clear_creative_library_repository_cache",
    "clear_creative_library_repository_caches",
]