# services/vectoplan-library/wsgi.py
"""
WSGI entrypoint for the vectoplan-library microservice.

Diese Datei hat eine klare Verantwortung:

- die Flask-App für WSGI-Server wie Gunicorn bereitstellen
- eine stabile, wiederverwendbare `app`-Referenz exportieren
- `FLASK_APP=wsgi:app` für Flask-Migrate bereitstellen
- optional einen lokalen Direktstart für Entwicklungszwecke ermöglichen
- WSGI-Diagnostik für VPLIB, Creative Library, Create, DB, Migrations und Models liefern

Wichtig:

- keine Editor-Begriffe
- keine VECTOPLAN_EDITOR_* Variablen
- Service-Root und src/ werden defensiv in sys.path aufgenommen
- create_app wird lazy importiert, damit Importpfade vorher stabil gesetzt sind
- Fehlertexte sind eindeutig auf vectoplan-library bezogen
- keine Scan-Ausführung beim Import
- keine Migration-Ausführung beim Import
- kein db.create_all() beim Import
- kein direktes Datenbank-Querying beim Import
- DB-/Model-Initialisierung erfolgt ausschließlich indirekt über app.create_app()
- wsgi.py selbst schreibt nicht ins Dateisystem

Gunicorn nutzt standardmäßig:

    wsgi:app

Flask-Migrate nutzt ebenfalls:

    FLASK_APP=wsgi:app
    flask db init
    flask db migrate
    flask db upgrade

Die Creative-Library-Schicht liegt unter:

    src/library
    src/library/source
    src/routes/library_routes.py
    src/services/library_route_service.py

Die Datenbankschicht liegt unter:

    extensions.py
    models/
    models/creative_library.py

Die fachliche `vplib_uid` entsteht weiterhin im .vplib/Manifest-Flow.
Die Datenbank übernimmt diese ID später nur.
"""

from __future__ import annotations

import os
import sys
import traceback
from functools import lru_cache
from pathlib import Path
from typing import Any, Final, Mapping
from urllib.parse import urlparse


# -----------------------------------------------------------------------------
# Konstanten
# -----------------------------------------------------------------------------

WSGI_SCHEMA_VERSION: Final[str] = "vplib.wsgi.v4"
SERVICE_NAME: Final[str] = "vectoplan-library"

_TRUE_VALUES: Final[set[str]] = {"1", "true", "t", "yes", "y", "on", "enabled"}
_FALSE_VALUES: Final[set[str]] = {"0", "false", "f", "no", "n", "off", "disabled"}

_DEFAULT_HOST: Final[str] = "127.0.0.1"
_DEFAULT_PORT: Final[int] = 5000
_DEFAULT_CONFIG: Final[str | None] = None

_DEFAULT_VPLIB_ROUTE_PREFIX: Final[str] = "/api/v1/vplib"
_DEFAULT_LIBRARY_ROUTE_PREFIX: Final[str] = "/api/v1/vplib/library"
_DEFAULT_CREATE_ROUTE_PREFIX: Final[str] = "/api/v1/vplib/create"
_DEFAULT_MIGRATIONS_DIRECTORY: Final[str] = "migrations"

_DATABASE_ENV_KEYS: Final[tuple[str, ...]] = (
    "SQLALCHEMY_DATABASE_URI",
    "VECTOPLAN_LIBRARY_DATABASE_URI",
    "VECTOPLAN_LIBRARY_DATABASE_URL",
    "VPLIB_DATABASE_URL",
    "DATABASE_URL",
)

_DATABASE_HEALTH_CHECK_ENV_KEYS: Final[tuple[str, ...]] = (
    "VECTOPLAN_LIBRARY_DB_HEALTH_CHECK",
    "VPLIB_DB_HEALTH_CHECK",
)

_MIGRATIONS_DIRECTORY_ENV_KEYS: Final[tuple[str, ...]] = (
    "VECTOPLAN_LIBRARY_MIGRATIONS_DIRECTORY",
    "ALEMBIC_MIGRATIONS_DIRECTORY",
    "MIGRATIONS_DIRECTORY",
)

_DB_BOOTSTRAP_FLAG_ENV_KEYS: Final[tuple[str, ...]] = (
    "VECTOPLAN_LIBRARY_DB_BOOTSTRAP_ENABLED",
    "VECTOPLAN_LIBRARY_DB_AUTO_INIT",
    "VECTOPLAN_LIBRARY_DB_AUTO_MIGRATE",
    "VECTOPLAN_LIBRARY_DB_AUTO_UPGRADE",
    "VECTOPLAN_LIBRARY_DB_MIGRATION_STRICT",
    "VECTOPLAN_LIBRARY_DB_RECREATE_INCOMPLETE_MIGRATIONS",
)


# -----------------------------------------------------------------------------
# Pfadauflösung
# -----------------------------------------------------------------------------

def _resolve_service_root() -> Path:
    """
    Liefert robust das Service-Root.

    Normalfall:
    wsgi.py liegt direkt im Service-Root.

    Fallback:
    aktuelles Arbeitsverzeichnis.
    """
    try:
        return Path(__file__).resolve().parent
    except Exception:
        return Path.cwd().resolve()


SERVICE_ROOT: Final[Path] = _resolve_service_root()
SRC_ROOT: Final[Path] = SERVICE_ROOT / "src"
MODELS_ROOT: Final[Path] = SERVICE_ROOT / "models"
MIGRATIONS_ROOT: Final[Path] = SERVICE_ROOT / _DEFAULT_MIGRATIONS_DIRECTORY
LIBRARY_ROOT: Final[Path] = SRC_ROOT / "library"
LIBRARY_SOURCE_ROOT: Final[Path] = LIBRARY_ROOT / "source"


@lru_cache(maxsize=1)
def _ensure_import_paths() -> tuple[str, ...]:
    """
    Stellt sicher, dass src/ und Service-Root im Python-Pfad vorhanden sind.

    Reihenfolge:

    1. src/
    2. Service-Root

    Dadurch können diese Imports funktionieren:

    - app
    - config
    - extensions
    - models
    - routes
    - services.*
    - vplib
    - library
    - src.*
    """
    desired_paths: list[str] = []

    for candidate in (SRC_ROOT, SERVICE_ROOT):
        try:
            candidate_str = str(candidate)
        except Exception:
            continue

        if candidate_str:
            desired_paths.append(candidate_str)

    for candidate_str in reversed(desired_paths):
        try:
            while candidate_str in sys.path:
                sys.path.remove(candidate_str)

            sys.path.insert(0, candidate_str)

        except Exception:
            continue

    return tuple(desired_paths)


# -----------------------------------------------------------------------------
# Defensive Environment-Helfer
# -----------------------------------------------------------------------------

def _safe_getenv(name: str, default: str | None = None) -> str | None:
    """Liest eine Umgebungsvariable defensiv aus."""
    try:
        return os.getenv(name, default)
    except Exception:
        return default


def _normalize_text(value: Any, default: str | None = None) -> str | None:
    """
    Normalisiert Texteingaben defensiv.

    Verhalten:
    - None -> default
    - strip()
    - leerer String -> default
    """
    if value is None:
        return default

    try:
        normalized = str(value).strip()
    except Exception:
        return default

    return normalized or default


def _read_bool_env(name: str, default: bool = False) -> bool:
    """Liest eine Bool-Umgebungsvariable robust aus."""
    raw_value = _normalize_text(_safe_getenv(name))

    if raw_value is None:
        return bool(default)

    lowered = raw_value.lower()

    if lowered in _TRUE_VALUES:
        return True

    if lowered in _FALSE_VALUES:
        return False

    return bool(default)


def _read_first_bool_env(*names: str, default: bool = False) -> bool:
    """Liest erstes gesetztes Bool-ENV aus mehreren Kandidaten."""
    for name in names:
        raw_value = _normalize_text(_safe_getenv(name))

        if raw_value is None:
            continue

        lowered = raw_value.lower()

        if lowered in _TRUE_VALUES:
            return True

        if lowered in _FALSE_VALUES:
            return False

    return bool(default)


def _read_int_env(
    name: str,
    default: int,
    minimum: int | None = None,
    maximum: int | None = None,
) -> int:
    """Liest eine Integer-Umgebungsvariable robust aus und begrenzt sie optional."""
    raw_value = _normalize_text(_safe_getenv(name))

    if raw_value is None:
        value = int(default)
    else:
        try:
            value = int(raw_value)
        except (TypeError, ValueError):
            value = int(default)

    if minimum is not None:
        value = max(int(minimum), value)

    if maximum is not None:
        value = min(int(maximum), value)

    return value


def _read_first_env(*names: str, default: str | None = None) -> str | None:
    """Liest die erste gesetzte ENV-Variable aus mehreren Kandidaten."""
    for name in names:
        value = _normalize_text(_safe_getenv(name))

        if value is not None:
            return value

    return default


def _safe_path(value: Any, fallback: Path | None = None) -> Path | None:
    """Wandelt Text defensiv in Path."""
    text = _normalize_text(value)

    if text is None:
        return fallback

    try:
        path = Path(text).expanduser()
        if path.is_absolute():
            return path
        return SERVICE_ROOT / path
    except Exception:
        return fallback


def _path_exists(path: Path | None) -> bool:
    """Prüft Pfadexistenz defensiv."""
    if path is None:
        return False

    try:
        return path.exists()
    except Exception:
        return False


def _path_is_dir(path: Path | None) -> bool:
    """Prüft Verzeichnis defensiv."""
    if path is None:
        return False

    try:
        return path.is_dir()
    except Exception:
        return False


def _path_is_file(path: Path | None) -> bool:
    """Prüft Datei defensiv."""
    if path is None:
        return False

    try:
        return path.is_file()
    except Exception:
        return False


# -----------------------------------------------------------------------------
# Datenbank-ENV-Helfer
# -----------------------------------------------------------------------------

def _normalize_database_uri(value: Any) -> str | None:
    """Normalisiert eine DB-URI defensiv."""
    uri = _normalize_text(value)

    if not uri:
        return None

    if uri.startswith("postgres://"):
        uri = "postgresql://" + uri[len("postgres://"):]

    return uri


def _resolve_database_uri() -> str | None:
    """Ermittelt die konfigurierte DB-URI aus ENV."""
    for name in _DATABASE_ENV_KEYS:
        uri = _normalize_database_uri(_safe_getenv(name))
        if uri:
            return uri
    return None


def _mask_database_uri(uri: Any) -> str | None:
    """Maskiert Credentials in DB-URIs für Diagnostik."""
    normalized = _normalize_database_uri(uri)
    if not normalized:
        return None

    try:
        parsed = urlparse(normalized)
        if not parsed.netloc:
            return normalized

        username = parsed.username
        hostname = parsed.hostname or ""
        port = f":{parsed.port}" if parsed.port else ""

        if username:
            auth = f"{username}:***@"
        elif "@" in parsed.netloc:
            auth = "***@"
        else:
            auth = ""

        return f"{parsed.scheme}://{auth}{hostname}{port}{parsed.path or ''}"
    except Exception:
        return "<masked-database-uri>"


def _database_backend(uri: Any) -> str:
    """Leitet DB-Backend aus URI ab."""
    normalized = _normalize_database_uri(uri)
    if not normalized:
        return "none"

    try:
        scheme = urlparse(normalized).scheme.lower()
    except Exception:
        return "unknown"

    if scheme.startswith("postgresql") or scheme == "postgres":
        return "postgresql"

    if scheme.startswith("sqlite"):
        return "sqlite"

    return scheme or "unknown"


def _database_public_parts(uri: Any) -> dict[str, Any]:
    """Extrahiert nicht-sensitive DB-URI-Bestandteile."""
    normalized = _normalize_database_uri(uri)

    if not normalized:
        return {
            "backend": "none",
            "driver": None,
            "host": None,
            "port": None,
            "database": None,
            "username": None,
        }

    try:
        parsed = urlparse(normalized)
        return {
            "backend": _database_backend(normalized),
            "driver": parsed.scheme or None,
            "host": parsed.hostname,
            "port": parsed.port,
            "database": (parsed.path or "").lstrip("/") or None,
            "username": parsed.username,
        }
    except Exception:
        return {
            "backend": "unknown",
            "driver": None,
            "host": None,
            "port": None,
            "database": None,
            "username": None,
        }


# -----------------------------------------------------------------------------
# Konfigurationsauflösung
# -----------------------------------------------------------------------------

def _resolve_config_name() -> str | None:
    """
    Ermittelt den gewünschten Konfigurationsnamen für create_app().

    Priorität:
    1. VECTOPLAN_LIBRARY_CONFIG
    2. VECTOPLAN_CONFIG
    3. FLASK_CONFIG
    4. None -> create_app() verwendet eigenen Default
    """
    return _read_first_env(
        "VECTOPLAN_LIBRARY_CONFIG",
        "VECTOPLAN_CONFIG",
        "FLASK_CONFIG",
        default=_DEFAULT_CONFIG,
    )


def _resolve_host() -> str:
    """Liest Host für lokalen Direktstart."""
    return (
        _read_first_env(
            "VECTOPLAN_LIBRARY_HOST",
            "VECTOPLAN_HOST",
            default=None,
        )
        or _DEFAULT_HOST
    )


def _resolve_port() -> int:
    """Liest Port für lokalen Direktstart."""
    if _normalize_text(_safe_getenv("VECTOPLAN_LIBRARY_PORT")) is not None:
        return _read_int_env(
            "VECTOPLAN_LIBRARY_PORT",
            default=_DEFAULT_PORT,
            minimum=1,
            maximum=65535,
        )

    if _normalize_text(_safe_getenv("VECTOPLAN_PORT")) is not None:
        return _read_int_env(
            "VECTOPLAN_PORT",
            default=_DEFAULT_PORT,
            minimum=1,
            maximum=65535,
        )

    return _DEFAULT_PORT


def _resolve_debug() -> bool:
    """Liest Debug-Flag für lokalen Direktstart."""
    if _normalize_text(_safe_getenv("VECTOPLAN_LIBRARY_DEBUG")) is not None:
        return _read_bool_env("VECTOPLAN_LIBRARY_DEBUG", default=False)

    if _normalize_text(_safe_getenv("VECTOPLAN_DEBUG")) is not None:
        return _read_bool_env("VECTOPLAN_DEBUG", default=False)

    return False


def _resolve_vplib_route_prefix() -> str:
    """Ermittelt VPLIB-Route-Prefix."""
    return (
        _read_first_env(
            "VPLIB_ROUTE_PREFIX",
            "VECTOPLAN_LIBRARY_VPLIB_ROUTE_PREFIX",
            default=None,
        )
        or _DEFAULT_VPLIB_ROUTE_PREFIX
    )


def _resolve_library_route_prefix() -> str:
    """Ermittelt Creative-Library-Route-Prefix."""
    return (
        _read_first_env(
            "VECTOPLAN_LIBRARY_ROUTE_PREFIX",
            "VPLIB_LIBRARY_ROUTE_PREFIX",
            "LIBRARY_ROUTE_PREFIX",
            default=None,
        )
        or _DEFAULT_LIBRARY_ROUTE_PREFIX
    )


def _resolve_create_route_prefix() -> str:
    """Ermittelt Create-API-Route-Prefix."""
    return (
        _read_first_env(
            "VECTOPLAN_LIBRARY_CREATE_ROUTE_PREFIX",
            "VPLIB_CREATE_ROUTE_PREFIX",
            default=None,
        )
        or _DEFAULT_CREATE_ROUTE_PREFIX
    )


def _resolve_library_source_root() -> Path:
    """
    Ermittelt Creative-Library-Source-Root.

    Standard:
        SERVICE_ROOT/src/library/source
    """
    raw = _read_first_env(
        "VECTOPLAN_LIBRARY_SOURCE_ROOT",
        "VPLIB_CREATE_SOURCE_ROOT",
        "LIBRARY_SOURCE_ROOT",
        default=None,
    )

    path = _safe_path(raw, fallback=LIBRARY_SOURCE_ROOT)

    if path is None:
        return LIBRARY_SOURCE_ROOT

    return path


def _resolve_migrations_directory_name() -> str:
    """Ermittelt das konfigurierte Flask-Migrate/Alembic-Verzeichnis."""
    return (
        _read_first_env(
            *_MIGRATIONS_DIRECTORY_ENV_KEYS,
            default=None,
        )
        or _DEFAULT_MIGRATIONS_DIRECTORY
    )


def _resolve_migrations_root() -> Path:
    """Ermittelt den effektiven Migrationspfad."""
    directory_name = _resolve_migrations_directory_name()
    path = _safe_path(directory_name, fallback=MIGRATIONS_ROOT)

    if path is None:
        return MIGRATIONS_ROOT

    return path


# -----------------------------------------------------------------------------
# App-Factory Import
# -----------------------------------------------------------------------------

def _import_create_app():
    """
    Importiert create_app defensiv nach Stabilisierung von sys.path.

    Der Import liegt bewusst nicht auf Top-Level, damit:
    - src/ vorher sicher in sys.path ist
    - Fehlermeldungen klarer bleiben
    - Tests den Importpfad leichter kontrollieren können
    """
    _ensure_import_paths()

    try:
        from app import create_app
    except Exception as exc:
        raise RuntimeError(
            f"create_app could not be imported for {SERVICE_NAME}. "
            f"service_root={SERVICE_ROOT}, src_root={SRC_ROOT}, sys_path={list(sys.path)[:8]}"
        ) from exc

    if not callable(create_app):
        raise RuntimeError("Imported create_app is not callable.")

    return create_app


# -----------------------------------------------------------------------------
# Gecachte App-Erzeugung
# -----------------------------------------------------------------------------

@lru_cache(maxsize=1)
def _build_wsgi_app():
    """
    Erzeugt die Flask-App genau einmal pro Prozess.

    Warum Cache:
    - vermeidet unnötige Mehrfachinitialisierung innerhalb desselben Prozesses
    - passt zum WSGI-Modell, bei dem die App pro Worker importiert wird
    - sorgt für konsistentes Verhalten bei wiederholtem Zugriff

    DB-Hinweis:
    - create_app() initialisiert SQLAlchemy/Flask-Migrate defensiv
    - create_app() importiert alle DB-Models für Alembic/db.metadata
    - wsgi.py selbst führt keine Migration und kein db.create_all() aus
    """
    _ensure_import_paths()
    config_name = _resolve_config_name()
    create_app = _import_create_app()

    try:
        if config_name is not None:
            return create_app(config_name)

        return create_app()

    except Exception as exc:
        raise RuntimeError(
            f"Die WSGI-Anwendung für `{SERVICE_NAME}` konnte nicht erstellt werden. "
            f"Konfigurationsname: {config_name!r}. "
            f"SERVICE_ROOT={SERVICE_ROOT}. SRC_ROOT={SRC_ROOT}. "
            f"MODELS_ROOT={MODELS_ROOT}. MIGRATIONS_ROOT={_resolve_migrations_root()}. "
            f"LIBRARY_ROOT={LIBRARY_ROOT}. LIBRARY_SOURCE_ROOT={_resolve_library_source_root()}. "
            f"DATABASE_BACKEND={_database_backend(_resolve_database_uri())}."
        ) from exc


def get_wsgi_app():
    """
    Öffentlicher Zugriffspunkt für die WSGI-Anwendung.

    Diese Funktion ist nützlich für:
    - Gunicorn
    - Flask-Migrate
    - Tests
    - Diagnose-Skripte
    """
    return _build_wsgi_app()


def reload_wsgi_app():
    """
    Leert den WSGI-App-Cache und erzeugt die App neu.

    Primär für Tests oder lokale Diagnose gedacht.
    """
    clear_wsgi_caches()
    return get_wsgi_app()


def clear_wsgi_caches() -> None:
    """Leert interne WSGI-Caches."""
    _ensure_import_paths.cache_clear()
    _build_wsgi_app.cache_clear()


# -----------------------------------------------------------------------------
# Diagnostik
# -----------------------------------------------------------------------------

def _module_available(module_name: str) -> dict[str, Any]:
    """Prüft Importfähigkeit eines Moduls ohne harte Abhängigkeit."""
    _ensure_import_paths()

    try:
        __import__(module_name)
        return {
            "ok": True,
            "module": module_name,
            "error": None,
        }
    except Exception as exc:
        return {
            "ok": False,
            "module": module_name,
            "error": {
                "type": exc.__class__.__name__,
                "message": str(exc),
            },
        }


def _safe_get_app_metadata() -> dict[str, Any] | None:
    """Liest get_app_metadata(app), falls die gecachte App erzeugbar ist."""
    try:
        flask_app = get_wsgi_app()
        from app import get_app_metadata

        if callable(get_app_metadata):
            metadata = get_app_metadata(flask_app)
            if isinstance(metadata, dict):
                return metadata
    except Exception:
        return None

    return None


def _safe_get_app_route_snapshot() -> dict[str, Any]:
    """Gibt Route-Snapshot der gecachten App zurück, falls erzeugbar."""
    try:
        flask_app = get_wsgi_app()
        route_rules = sorted(str(rule) for rule in flask_app.url_map.iter_rules())
        blueprints = sorted(str(name) for name in flask_app.blueprints.keys())
        library_prefix = _resolve_library_route_prefix()
        create_prefix = _resolve_create_route_prefix()

        return {
            "ok": True,
            "route_count": len(route_rules),
            "routes": route_rules,
            "blueprints": blueprints,
            "has_vplib_blueprint": "vplib_bp" in blueprints,
            "has_library_blueprint": "library_bp" in blueprints,
            "has_create_blueprint": "vplib_create" in blueprints,
            "has_library_blocks_route": f"{library_prefix}/blocks" in route_rules,
            "has_library_scan_route": f"{library_prefix}/scan" in route_rules,
            "has_library_tree_route": f"{library_prefix}/tree" in route_rules,
            "has_create_page_route": "/create" in route_rules,
            "has_create_health_route": f"{create_prefix}/health" in route_rules,
            "has_create_save_route": f"{create_prefix}/save" in route_rules,
        }

    except Exception as exc:
        return {
            "ok": False,
            "error": {
                "type": exc.__class__.__name__,
                "message": str(exc),
                "traceback": traceback.format_exception(
                    type(exc),
                    exc,
                    exc.__traceback__,
                ),
            },
        }


def _safe_get_database_snapshot() -> dict[str, Any]:
    """Gibt DB-Diagnostik ohne aktiven DB-Query zurück."""
    uri = _resolve_database_uri()

    snapshot: dict[str, Any] = {
        "configured": bool(uri),
        "backend": _database_backend(uri),
        "database_uri": _mask_database_uri(uri),
        "public_parts": _database_public_parts(uri),
        "health_check_requested": _read_first_bool_env(
            *_DATABASE_HEALTH_CHECK_ENV_KEYS,
            default=False,
        ),
        "env_keys_checked": list(_DATABASE_ENV_KEYS),
    }

    metadata = _safe_get_app_metadata()
    if isinstance(metadata, dict):
        snapshot["app_database_initialized"] = bool(metadata.get("database_initialized", False))
        snapshot["app_database_migrate_initialized"] = bool(metadata.get("database_migrate_initialized", False))
        snapshot["app_database_health"] = metadata.get("database_health")
        snapshot["app_database_error"] = metadata.get("database_error")
        snapshot["app_database_metadata"] = metadata.get("database_metadata")
        snapshot["app_models_imported"] = bool(metadata.get("models_imported", False))
        snapshot["app_models_class_names"] = metadata.get("models_class_names", [])
        snapshot["app_models_table_names"] = metadata.get("models_table_names", [])
        snapshot["app_models_error"] = metadata.get("models_error")

    return snapshot


def _safe_get_migration_snapshot() -> dict[str, Any]:
    """Gibt Migrations-Diagnostik zurück, ohne Migrationen auszuführen."""
    migrations_root = _resolve_migrations_root()
    versions_root = migrations_root / "versions"

    version_files: list[str] = []
    try:
        if versions_root.is_dir():
            version_files = sorted(
                path.name
                for path in versions_root.iterdir()
                if path.is_file() and path.suffix == ".py"
            )
    except Exception:
        version_files = []

    return {
        "configured_directory": _resolve_migrations_directory_name(),
        "root": str(migrations_root),
        "root_exists": _path_is_dir(migrations_root),
        "env_py_exists": _path_is_file(migrations_root / "env.py"),
        "script_mako_exists": _path_is_file(migrations_root / "script.py.mako"),
        "versions_root": str(versions_root),
        "versions_root_exists": _path_is_dir(versions_root),
        "version_file_count": len(version_files),
        "version_files": version_files,
        "auto_flags": {
            name: _safe_getenv(name)
            for name in _DB_BOOTSTRAP_FLAG_ENV_KEYS
        },
    }


def get_wsgi_diagnostics(*, include_app_routes: bool = False, include_app_metadata: bool = False) -> dict[str, Any]:
    """
    Gibt einen JSON-kompatiblen Diagnose-Snapshot zurück.

    Standardmäßig wird die App hierfür nicht aktiv erzeugt. Mit
    `include_app_routes=True` oder `include_app_metadata=True` kann App-Erzeugung
    erzwungen werden.
    """
    try:
        config_name = _resolve_config_name()
    except Exception as exc:
        config_name = f"<error: {exc}>"

    library_source_root = _resolve_library_source_root()
    database_uri = _resolve_database_uri()
    migrations_root = _resolve_migrations_root()

    diagnostics: dict[str, Any] = {
        "schema_version": WSGI_SCHEMA_VERSION,
        "service_name": SERVICE_NAME,
        "service_root": str(SERVICE_ROOT),
        "src_root": str(SRC_ROOT),
        "models_root": str(MODELS_ROOT),
        "migrations_root": str(migrations_root),
        "library_root": str(LIBRARY_ROOT),
        "library_source_root": str(library_source_root),
        "paths": {
            "service_root_exists": _path_is_dir(SERVICE_ROOT),
            "src_root_exists": _path_is_dir(SRC_ROOT),
            "models_root_exists": _path_is_dir(MODELS_ROOT),
            "creative_library_model_exists": _path_is_file(MODELS_ROOT / "creative_library.py"),
            "models_init_exists": _path_is_file(MODELS_ROOT / "__init__.py"),
            "migrations_root_exists": _path_is_dir(migrations_root),
            "migrations_env_exists": _path_is_file(migrations_root / "env.py"),
            "migrations_script_template_exists": _path_is_file(migrations_root / "script.py.mako"),
            "migrations_versions_exists": _path_is_dir(migrations_root / "versions"),
            "library_root_exists": _path_is_dir(LIBRARY_ROOT),
            "library_source_root_exists": _path_is_dir(library_source_root),
            "app_py_exists": _path_is_file(SERVICE_ROOT / "app.py"),
            "wsgi_py_exists": _path_is_file(SERVICE_ROOT / "wsgi.py"),
            "config_py_exists": _path_is_file(SERVICE_ROOT / "config.py"),
            "extensions_py_exists": _path_is_file(SERVICE_ROOT / "extensions.py"),
            "library_settings_exists": _path_is_file(SRC_ROOT / "config" / "library_settings.py"),
            "library_routes_exists": _path_is_file(SRC_ROOT / "routes" / "library_routes.py"),
            "create_routes_exists": _path_is_file(SRC_ROOT / "routes" / "create.py"),
        },
        "import_paths": list(_ensure_import_paths()),
        "config_name": config_name,
        "host": _resolve_host(),
        "port": _resolve_port(),
        "debug": _resolve_debug(),
        "route_prefixes": {
            "vplib": _resolve_vplib_route_prefix(),
            "library": _resolve_library_route_prefix(),
            "create": _resolve_create_route_prefix(),
        },
        "database": {
            "configured": bool(database_uri),
            "backend": _database_backend(database_uri),
            "database_uri": _mask_database_uri(database_uri),
            "public_parts": _database_public_parts(database_uri),
            "health_check_requested": _read_first_bool_env(
                *_DATABASE_HEALTH_CHECK_ENV_KEYS,
                default=False,
            ),
        },
        "migrations": _safe_get_migration_snapshot(),
        "environment": {
            "FLASK_APP": _safe_getenv("FLASK_APP"),
            "FLASK_ENV": _safe_getenv("FLASK_ENV"),
            "VECTOPLAN_LIBRARY_CONFIG": _safe_getenv("VECTOPLAN_LIBRARY_CONFIG"),
            "VECTOPLAN_LIBRARY_ROUTE_PREFIX": _safe_getenv("VECTOPLAN_LIBRARY_ROUTE_PREFIX"),
            "VECTOPLAN_LIBRARY_SOURCE_ROOT": _safe_getenv("VECTOPLAN_LIBRARY_SOURCE_ROOT"),
            "VPLIB_CREATE_SOURCE_ROOT": _safe_getenv("VPLIB_CREATE_SOURCE_ROOT"),
            "LIBRARY_SOURCE_ROOT": _safe_getenv("LIBRARY_SOURCE_ROOT"),
            "SQLALCHEMY_DATABASE_URI": _mask_database_uri(_safe_getenv("SQLALCHEMY_DATABASE_URI")),
            "VECTOPLAN_LIBRARY_DATABASE_URI": _mask_database_uri(_safe_getenv("VECTOPLAN_LIBRARY_DATABASE_URI")),
            "VECTOPLAN_LIBRARY_DATABASE_URL": _mask_database_uri(_safe_getenv("VECTOPLAN_LIBRARY_DATABASE_URL")),
            "VPLIB_DATABASE_URL": _mask_database_uri(_safe_getenv("VPLIB_DATABASE_URL")),
            "DATABASE_URL": _mask_database_uri(_safe_getenv("DATABASE_URL")),
            "VECTOPLAN_LIBRARY_DB_HEALTH_CHECK": _safe_getenv("VECTOPLAN_LIBRARY_DB_HEALTH_CHECK"),
            "VECTOPLAN_LIBRARY_DB_AUTO_INIT": _safe_getenv("VECTOPLAN_LIBRARY_DB_AUTO_INIT"),
            "VECTOPLAN_LIBRARY_DB_AUTO_MIGRATE": _safe_getenv("VECTOPLAN_LIBRARY_DB_AUTO_MIGRATE"),
            "VECTOPLAN_LIBRARY_DB_AUTO_UPGRADE": _safe_getenv("VECTOPLAN_LIBRARY_DB_AUTO_UPGRADE"),
            "VECTOPLAN_LIBRARY_MIGRATIONS_DIRECTORY": _safe_getenv("VECTOPLAN_LIBRARY_MIGRATIONS_DIRECTORY"),
            "ALEMBIC_MIGRATIONS_DIRECTORY": _safe_getenv("ALEMBIC_MIGRATIONS_DIRECTORY"),
            "MIGRATIONS_DIRECTORY": _safe_getenv("MIGRATIONS_DIRECTORY"),
            "PYTHONPATH": _safe_getenv("PYTHONPATH"),
        },
        "imports": {
            "app": _module_available("app"),
            "config": _module_available("config"),
            "extensions": _module_available("extensions"),
            "models": _module_available("models"),
            "models.creative_library": _module_available("models.creative_library"),
            "flask_sqlalchemy": _module_available("flask_sqlalchemy"),
            "flask_migrate": _module_available("flask_migrate"),
            "alembic": _module_available("alembic"),
            "sqlalchemy": _module_available("sqlalchemy"),
            "psycopg": _module_available("psycopg"),
            "psycopg2": _module_available("psycopg2"),
            "routes": _module_available("routes"),
            "routes.vplib_routes": _module_available("routes.vplib_routes"),
            "routes.library_routes": _module_available("routes.library_routes"),
            "routes.create": _module_available("routes.create"),
            "services.vplib_route_service": _module_available("services.vplib_route_service"),
            "services.library_route_service": _module_available("services.library_route_service"),
            "services.library_create_route_service": _module_available("services.library_create_route_service"),
            "config.vplib_settings": _module_available("config.vplib_settings"),
            "config.library_settings": _module_available("config.library_settings"),
            "vplib": _module_available("vplib"),
            "vplib.vplib_id_service": _module_available("vplib.vplib_id_service"),
            "library": _module_available("library"),
            "library.domain": _module_available("library.domain"),
            "library.scanner": _module_available("library.scanner"),
            "library.validation": _module_available("library.validation"),
            "library.read_models": _module_available("library.read_models"),
            "library.services": _module_available("library.services"),
            "library.services.library_create_service": _module_available("library.services.library_create_service"),
        },
    }

    if include_app_routes:
        diagnostics["app_routes"] = _safe_get_app_route_snapshot()

    if include_app_metadata:
        diagnostics["app_metadata"] = _safe_get_app_metadata()
        diagnostics["database_snapshot"] = _safe_get_database_snapshot()

    return diagnostics


# -----------------------------------------------------------------------------
# WSGI-Exports
# -----------------------------------------------------------------------------

# Standardname, den WSGI-Server und Flask-Migrate erwarten.
app = get_wsgi_app()

# Zusätzlicher Alias für maximale Kompatibilität.
application = app


# -----------------------------------------------------------------------------
# Optionaler Direktstart für lokale Entwicklung
# -----------------------------------------------------------------------------

if __name__ == "__main__":
    host = _resolve_host()
    port = _resolve_port()
    debug = _resolve_debug()

    try:
        app.run(host=host, port=port, debug=debug)
    except Exception as exc:
        raise RuntimeError(
            f"Der lokale Direktstart von `{SERVICE_NAME}` über wsgi.py ist fehlgeschlagen. "
            f"host={host!r}, port={port!r}, debug={debug!r}"
        ) from exc


__all__: Final[list[str]] = [
    "LIBRARY_ROOT",
    "LIBRARY_SOURCE_ROOT",
    "MIGRATIONS_ROOT",
    "MODELS_ROOT",
    "SERVICE_NAME",
    "SERVICE_ROOT",
    "SRC_ROOT",
    "WSGI_SCHEMA_VERSION",
    "app",
    "application",
    "clear_wsgi_caches",
    "get_wsgi_app",
    "get_wsgi_diagnostics",
    "reload_wsgi_app",
]