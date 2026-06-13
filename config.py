# services/vectoplan-library/config.py
"""
Central configuration for the vectoplan-library microservice.

Diese Datei ist die Root-Service-Konfiguration für Flask, Gunicorn/WSGI,
SQLAlchemy, Flask-Migrate und die grundlegende Runtime des VPLIB-Library-Service.

Wichtig:
- keine Editor-Begriffe
- keine Route /editor
- keine Editor-Templates
- keine Hotbar-/Viewport-/Inspector-Konfiguration
- VPLIB-spezifische Pfade und Routen werden hier zentral bereitgestellt
- Detail-Settings für VPLIB liegen zusätzlich in src/config/vplib_settings.py
- Detail-Settings für Creative Library liegen zusätzlich in src/config/library_settings.py
- PostgreSQL/SQLAlchemy-Konfiguration wird hier zentral bereitgestellt
- Datenbankmodelle liegen unter services/vectoplan-library/models

Diese Datei enthält keine Business-Logik.
Sie enthält nur Konfiguration und kleine defensive Hilfsfunktionen.

Datenbank-Architektur:
- Die Datenbank erzeugt keine fachliche VPLIB-/Block-ID.
- `vplib_uid` entsteht beim Erstellen des .vplib-Packages.
- PostgreSQL speichert und indiziert `vplib_uid` nur.
- SQLAlchemy wird über extensions.py initialisiert.
- Flask-Migrate wird über extensions.py registriert.
- `flask db init/migrate/upgrade` wird zur Laufzeit über entrypoint.sh ausgeführt.
- Kein db.create_all() in config.py.
- Keine Migrationen in config.py.
"""

from __future__ import annotations

import os
from functools import lru_cache
from pathlib import Path
from typing import Any, Final
from urllib.parse import quote_plus, urlparse


# -----------------------------------------------------------------------------
# Interne Konstanten
# -----------------------------------------------------------------------------

CONFIG_SCHEMA_VERSION: Final[str] = "vplib.config.v3"

DEFAULT_APP_NAME: Final[str] = "vectoplan-library"
DEFAULT_APP_DISPLAY_NAME: Final[str] = "VECTOPLAN Library"
DEFAULT_SERVICE_NAME: Final[str] = DEFAULT_APP_NAME
DEFAULT_SERVICE_DISPLAY_NAME: Final[str] = DEFAULT_APP_DISPLAY_NAME
DEFAULT_APP_ENV: Final[str] = "development"

DEFAULT_HOST: Final[str] = "0.0.0.0"
DEFAULT_PORT: Final[int] = 5000

DEFAULT_ROUTE_PREFIX: Final[str] = "/api/v1/vplib"
DEFAULT_LIBRARY_ROUTE_PREFIX: Final[str] = "/api/v1/vplib/library"
DEFAULT_CREATE_API_PREFIX: Final[str] = "/api/v1/vplib/create"
DEFAULT_CREATE_PAGE_ROUTE: Final[str] = "/create"
DEFAULT_HEALTH_ROUTE: Final[str] = "/health"
DEFAULT_READY_ROUTE: Final[str] = "/health/ready"

DEFAULT_SOURCE_DIR_NAME: Final[str] = "sources"
DEFAULT_LIBRARY_CATALOG_DIR_NAME: Final[str] = "creative_library"
DEFAULT_GENERATED_DIR_NAME: Final[str] = "generated"
DEFAULT_VPLIB_GENERATED_DIR_NAME: Final[str] = "vplib"
DEFAULT_ARCHIVE_DIR_NAME: Final[str] = "archives"
DEFAULT_TEST_OUTPUT_DIR_NAME: Final[str] = "vplib_test"
DEFAULT_TEMPLATE_DIR_NAME: Final[str] = "templates"
DEFAULT_STATIC_DIR_NAME: Final[str] = "static"
DEFAULT_MIGRATIONS_DIR_NAME: Final[str] = "migrations"

DEFAULT_MAX_CONTENT_LENGTH: Final[int] = 64 * 1024 * 1024
DEFAULT_SECRET_KEY: Final[str] = "dev-secret-key-change-me"

DEFAULT_DATABASE_DRIVER: Final[str] = "postgresql+psycopg"
DEFAULT_DATABASE_HOST: Final[str] = "vectoplan-library-db"
DEFAULT_DATABASE_PORT: Final[int] = 5432
DEFAULT_DATABASE_NAME: Final[str] = "vectoplan_library"
DEFAULT_DATABASE_USER: Final[str] = "vectoplan"
DEFAULT_DATABASE_PASSWORD: Final[str] = "vectoplan"

DATABASE_ENV_KEYS: Final[tuple[str, ...]] = (
    "SQLALCHEMY_DATABASE_URI",
    "VECTOPLAN_LIBRARY_DATABASE_URI",
    "VECTOPLAN_LIBRARY_DATABASE_URL",
    "VPLIB_DATABASE_URL",
    "DATABASE_URL",
)

DATABASE_REQUIRED_ENV_KEYS: Final[tuple[str, ...]] = (
    "VECTOPLAN_LIBRARY_DATABASE_REQUIRED",
    "VPLIB_DATABASE_REQUIRED",
)

DATABASE_HEALTH_CHECK_ENV_KEYS: Final[tuple[str, ...]] = (
    "VECTOPLAN_LIBRARY_DB_HEALTH_CHECK",
    "VPLIB_DB_HEALTH_CHECK",
)

DATABASE_WAIT_ENV_KEYS: Final[tuple[str, ...]] = (
    "VECTOPLAN_LIBRARY_DB_WAIT_FOR_READY",
    "VPLIB_DB_WAIT_FOR_READY",
)

DATABASE_AUTO_INIT_ENV_KEYS: Final[tuple[str, ...]] = (
    "VECTOPLAN_LIBRARY_DB_AUTO_INIT",
    "VPLIB_DB_AUTO_INIT",
)

DATABASE_AUTO_MIGRATE_ENV_KEYS: Final[tuple[str, ...]] = (
    "VECTOPLAN_LIBRARY_DB_AUTO_MIGRATE",
    "VPLIB_DB_AUTO_MIGRATE",
)

DATABASE_AUTO_UPGRADE_ENV_KEYS: Final[tuple[str, ...]] = (
    "VECTOPLAN_LIBRARY_DB_AUTO_UPGRADE",
    "VPLIB_DB_AUTO_UPGRADE",
)

_TRUE_VALUES: Final[set[str]] = {"1", "true", "t", "yes", "y", "on", "enabled"}
_FALSE_VALUES: Final[set[str]] = {"0", "false", "f", "no", "n", "off", "disabled"}


# -----------------------------------------------------------------------------
# Defensive Environment-Helfer
# -----------------------------------------------------------------------------

def _safe_getenv(name: str) -> str | None:
    """Liest eine Umgebungsvariable defensiv aus."""
    try:
        return os.getenv(name)
    except Exception:
        return None


def _normalize_text(value: Any, default: str | None = None) -> str | None:
    """
    Normalisiert String-Eingaben defensiv:
    - None -> default
    - Whitespace wird entfernt
    - leere Strings -> default
    """
    if value is None:
        return default

    try:
        normalized = str(value).strip()
    except Exception:
        return default

    return normalized or default


def _read_str_env(*names: str, default: str) -> str:
    """Liest eine String-Umgebungsvariable aus mehreren Kandidaten."""
    for name in names:
        value = _normalize_text(_safe_getenv(name))
        if value is not None:
            return value

    return default


def _read_optional_str_env(*names: str, default: str | None = None) -> str | None:
    """Liest eine optionale String-Umgebungsvariable aus mehreren Kandidaten."""
    for name in names:
        value = _normalize_text(_safe_getenv(name))
        if value is not None:
            return value

    return default


def _read_bool_env(*names: str, default: bool = False) -> bool:
    """Liest eine Bool-Umgebungsvariable robust aus mehreren Kandidaten."""
    for name in names:
        raw_value = _normalize_text(_safe_getenv(name))
        if raw_value is None:
            continue

        normalized = raw_value.lower()

        if normalized in _TRUE_VALUES:
            return True

        if normalized in _FALSE_VALUES:
            return False

    return bool(default)


def _read_int_env(
    *names: str,
    default: int,
    minimum: int | None = None,
    maximum: int | None = None,
) -> int:
    """Liest eine Integer-Umgebungsvariable robust aus mehreren Kandidaten."""
    value = int(default)

    for name in names:
        raw_value = _normalize_text(_safe_getenv(name))
        if raw_value is None:
            continue

        try:
            value = int(raw_value)
            break
        except (TypeError, ValueError):
            value = int(default)
            break

    if minimum is not None:
        value = max(int(minimum), value)

    if maximum is not None:
        value = min(int(maximum), value)

    return value


def _normalize_route_prefix(value: Any, default: str = DEFAULT_ROUTE_PREFIX) -> str:
    """Normalisiert Route-Prefix."""
    route_prefix = _normalize_text(value, default) or default

    if not route_prefix.startswith("/"):
        route_prefix = f"/{route_prefix}"

    route_prefix = route_prefix.rstrip("/")

    return route_prefix or default


def _normalize_route_path(value: Any, default: str) -> str:
    """Normalisiert einen einzelnen Route-Pfad."""
    route_path = _normalize_text(value, default) or default

    if not route_path.startswith("/"):
        route_path = f"/{route_path}"

    return route_path.rstrip("/") or "/"


# -----------------------------------------------------------------------------
# Datenbank-Helfer
# -----------------------------------------------------------------------------

def _normalize_database_uri(value: Any) -> str | None:
    """
    Normalisiert Datenbank-URIs.

    Unterstützt:
    - postgresql://...
    - postgresql+psycopg://...
    - postgresql+psycopg2://...
    - legacy postgres://... -> postgresql://...
    - sqlite:///... für Tests/dev fallback, falls explizit gesetzt
    """
    uri = _normalize_text(value)
    if not uri:
        return None

    if uri.startswith("postgres://"):
        uri = "postgresql://" + uri[len("postgres://"):]

    return uri


def _read_database_uri(*names: str, default: str | None = None) -> str | None:
    """Liest und normalisiert die erste gesetzte Datenbank-URI."""
    for name in names:
        uri = _normalize_database_uri(_safe_getenv(name))
        if uri:
            return uri

    return _normalize_database_uri(default)


def _database_uri_backend(uri: Any) -> str:
    """Leitet den DB-Backend-Typ aus der URI ab."""
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


def _mask_database_uri(uri: Any) -> str | None:
    """Maskiert Credentials in Datenbank-URIs für Health-/Summary-Payloads."""
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


def _database_uri_public_parts(uri: Any) -> dict[str, Any]:
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
            "backend": _database_uri_backend(normalized),
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


def _is_postgresql_uri(uri: Any) -> bool:
    """Prüft, ob eine URI auf PostgreSQL zeigt."""
    return _database_uri_backend(uri) == "postgresql"


def _is_sqlite_uri(uri: Any) -> bool:
    """Prüft, ob eine URI auf SQLite zeigt."""
    return _database_uri_backend(uri) == "sqlite"


def _build_postgresql_uri_from_parts() -> str:
    """
    Baut eine PostgreSQL-URI aus Einzelvariablen.

    Diese Funktion wird nicht als erster Mechanismus genutzt. Sie ist ein
    Fallback, falls keine vollständige URI gesetzt wurde, aber Docker-/Compose-
    Einzelvariablen vorhanden sind.
    """
    driver = _read_str_env(
        "VECTOPLAN_LIBRARY_DATABASE_DRIVER",
        default=DEFAULT_DATABASE_DRIVER,
    )
    host = _read_str_env(
        "VECTOPLAN_LIBRARY_DB_HOST",
        default=DEFAULT_DATABASE_HOST,
    )
    port = _read_int_env(
        "VECTOPLAN_LIBRARY_DB_PORT",
        default=DEFAULT_DATABASE_PORT,
        minimum=1,
        maximum=65535,
    )
    database = _read_str_env(
        "VECTOPLAN_LIBRARY_DB_NAME",
        default=DEFAULT_DATABASE_NAME,
    )
    username = _read_str_env(
        "VECTOPLAN_LIBRARY_DB_USER",
        default=DEFAULT_DATABASE_USER,
    )
    password = _read_str_env(
        "VECTOPLAN_LIBRARY_DB_PASSWORD",
        default=DEFAULT_DATABASE_PASSWORD,
    )

    return (
        f"{driver}://"
        f"{quote_plus(username)}:{quote_plus(password)}"
        f"@{host}:{port}/{database}"
    )


def _build_sqlalchemy_engine_options(database_uri: str | None) -> dict[str, Any]:
    """
    Baut SQLAlchemy Engine Options.

    PostgreSQL:
    - pool_pre_ping
    - pool_size
    - max_overflow
    - pool_recycle
    - pool_timeout
    - connect_timeout über connect_args

    SQLite:
    - keine PostgreSQL-Pool-Optionen, damit lokale Tests nicht brechen.
    """
    if not database_uri:
        return {}

    if _is_sqlite_uri(database_uri):
        return {
            "pool_pre_ping": True,
        }

    if _is_postgresql_uri(database_uri):
        return {
            "pool_pre_ping": _read_bool_env(
                "VECTOPLAN_LIBRARY_DB_POOL_PRE_PING",
                "SQLALCHEMY_POOL_PRE_PING",
                default=True,
            ),
            "pool_size": _read_int_env(
                "VECTOPLAN_LIBRARY_DB_POOL_SIZE",
                "SQLALCHEMY_POOL_SIZE",
                default=5,
                minimum=1,
                maximum=100,
            ),
            "max_overflow": _read_int_env(
                "VECTOPLAN_LIBRARY_DB_MAX_OVERFLOW",
                "SQLALCHEMY_MAX_OVERFLOW",
                default=10,
                minimum=0,
                maximum=200,
            ),
            "pool_recycle": _read_int_env(
                "VECTOPLAN_LIBRARY_DB_POOL_RECYCLE_SECONDS",
                "SQLALCHEMY_POOL_RECYCLE",
                default=1800,
                minimum=30,
            ),
            "pool_timeout": _read_int_env(
                "VECTOPLAN_LIBRARY_DB_POOL_TIMEOUT_SECONDS",
                "SQLALCHEMY_POOL_TIMEOUT",
                default=30,
                minimum=1,
            ),
            "connect_args": {
                "connect_timeout": _read_int_env(
                    "VECTOPLAN_LIBRARY_DATABASE_CONNECT_TIMEOUT",
                    "VECTOPLAN_LIBRARY_DB_CONNECT_TIMEOUT",
                    default=15,
                    minimum=1,
                    maximum=300,
                ),
            },
        }

    return {
        "pool_pre_ping": True,
    }


def _build_testing_sqlite_uri() -> str:
    """Baut eine robuste SQLite-URI für Tests, falls keine DB-URI gesetzt ist."""
    try:
        return f"sqlite:///{(SERVICE_ROOT / 'generated' / 'test_library.sqlite3').as_posix()}"
    except Exception:
        return "sqlite:///:memory:"


def _read_effective_database_uri(*, testing: bool = False) -> str | None:
    """
    Liest die effektive Datenbank-URI.

    Reihenfolge:
    1. vollständige URI-Aliase
    2. Test-SQLite-Fallback, wenn testing=True
    3. optionaler Compose-Fallback aus Einzelvariablen, wenn aktiviert

    Der Compose-Fallback ist standardmäßig aktiv, damit Containerstarts mit
    Einzelvariablen stabil bleiben.
    """
    uri = _read_database_uri(*DATABASE_ENV_KEYS, default=None)
    if uri:
        return uri

    if testing:
        return _build_testing_sqlite_uri()

    if _read_bool_env("VECTOPLAN_LIBRARY_BUILD_DATABASE_URI_FROM_PARTS", default=True):
        return _build_postgresql_uri_from_parts()

    return None


# -----------------------------------------------------------------------------
# Pfad-Helfer
# -----------------------------------------------------------------------------

@lru_cache(maxsize=1)
def _resolve_service_root() -> Path:
    """
    Ermittelt das Root-Verzeichnis des Services robust.

    Normalfall:
    config.py liegt direkt im Service-Root.

    Fallback:
    aktuelles Arbeitsverzeichnis.
    """
    try:
        return Path(__file__).resolve().parent
    except Exception:
        return Path(".").resolve()


SERVICE_ROOT: Final[Path] = _resolve_service_root()
SRC_ROOT: Final[Path] = SERVICE_ROOT / "src"


def _build_path(*parts: str) -> Path:
    """Baut robust einen Pfad relativ zum Service-Root."""
    try:
        return SERVICE_ROOT.joinpath(*parts)
    except Exception:
        return SERVICE_ROOT


def _read_path_env(*names: str, default: Path) -> Path:
    """Liest einen Pfad aus Environment oder liefert Default."""
    for name in names:
        raw_value = _normalize_text(_safe_getenv(name))
        if raw_value is None:
            continue

        try:
            path = Path(raw_value).expanduser()
            return path if path.is_absolute() else SERVICE_ROOT / path
        except Exception:
            return default

    return default


# -----------------------------------------------------------------------------
# Basiskonfiguration
# -----------------------------------------------------------------------------

class BaseConfig:
    """
    Gemeinsame Basiskonfiguration für alle Umgebungen.

    Diese Klasse enthält:
    - Service-Metadaten
    - Flask-Grundeinstellungen
    - SQLAlchemy-/PostgreSQL-Konfiguration
    - Flask-Migrate-/Alembic-Konfiguration
    - Pfade innerhalb des Services
    - VPLIB-Routen- und Runtime-Defaults
    """

    # -------------------------------------------------------------------------
    # Service-Metadaten
    # -------------------------------------------------------------------------

    CONFIG_SCHEMA_VERSION = CONFIG_SCHEMA_VERSION

    APP_NAME = DEFAULT_APP_NAME
    APP_DISPLAY_NAME = DEFAULT_APP_DISPLAY_NAME
    APP_ENV = _read_str_env(
        "VECTOPLAN_LIBRARY_ENV",
        "VECTOPLAN_ENV",
        "FLASK_ENV",
        default=DEFAULT_APP_ENV,
    )

    SERVICE_NAME = DEFAULT_SERVICE_NAME
    SERVICE_DISPLAY_NAME = DEFAULT_SERVICE_DISPLAY_NAME

    # -------------------------------------------------------------------------
    # Flask-Grundkonfiguration
    # -------------------------------------------------------------------------

    SECRET_KEY = _read_str_env(
        "VECTOPLAN_LIBRARY_SECRET_KEY",
        "VECTOPLAN_SECRET_KEY",
        "SECRET_KEY",
        default=DEFAULT_SECRET_KEY,
    )

    DEBUG = _read_bool_env(
        "VECTOPLAN_LIBRARY_DEBUG",
        "VECTOPLAN_DEBUG",
        "FLASK_DEBUG",
        default=False,
    )

    TESTING = _read_bool_env(
        "VECTOPLAN_LIBRARY_TESTING",
        "VECTOPLAN_TESTING",
        default=False,
    )

    TEMPLATES_AUTO_RELOAD = _read_bool_env(
        "VECTOPLAN_LIBRARY_TEMPLATES_AUTO_RELOAD",
        default=False,
    )

    EXPLAIN_TEMPLATE_LOADING = _read_bool_env(
        "VECTOPLAN_LIBRARY_EXPLAIN_TEMPLATE_LOADING",
        default=False,
    )

    SEND_FILE_MAX_AGE_DEFAULT = _read_int_env(
        "VECTOPLAN_LIBRARY_SEND_FILE_MAX_AGE_DEFAULT",
        default=0,
        minimum=0,
    )

    PREFERRED_URL_SCHEME = _read_str_env(
        "VECTOPLAN_LIBRARY_PREFERRED_URL_SCHEME",
        default="http",
    )

    SERVER_NAME = _read_optional_str_env(
        "VECTOPLAN_LIBRARY_SERVER_NAME",
        default=None,
    )

    APPLICATION_ROOT = _read_str_env(
        "VECTOPLAN_LIBRARY_APPLICATION_ROOT",
        default="/",
    )

    MAX_CONTENT_LENGTH = _read_int_env(
        "VECTOPLAN_LIBRARY_MAX_CONTENT_LENGTH",
        "VPLIB_MAX_CONTENT_LENGTH",
        default=DEFAULT_MAX_CONTENT_LENGTH,
        minimum=1024,
    )

    JSON_SORT_KEYS = False

    SESSION_COOKIE_HTTPONLY = True
    SESSION_COOKIE_SAMESITE = "Lax"
    SESSION_COOKIE_SECURE = _read_bool_env(
        "VECTOPLAN_LIBRARY_SESSION_COOKIE_SECURE",
        default=False,
    )

    # -------------------------------------------------------------------------
    # Datenbank / SQLAlchemy / PostgreSQL
    # -------------------------------------------------------------------------

    SQLALCHEMY_DATABASE_URI = _read_effective_database_uri(testing=False)
    SQLALCHEMY_TRACK_MODIFICATIONS = False

    SQLALCHEMY_RECORD_QUERIES = _read_bool_env(
        "VECTOPLAN_LIBRARY_SQLALCHEMY_RECORD_QUERIES",
        "SQLALCHEMY_RECORD_QUERIES",
        default=False,
    )

    SQLALCHEMY_ECHO = _read_bool_env(
        "VECTOPLAN_LIBRARY_SQLALCHEMY_ECHO",
        "SQLALCHEMY_ECHO",
        default=False,
    )

    SQLALCHEMY_ENGINE_OPTIONS = _build_sqlalchemy_engine_options(SQLALCHEMY_DATABASE_URI)

    VECTOPLAN_LIBRARY_DATABASE_URI = SQLALCHEMY_DATABASE_URI
    VECTOPLAN_LIBRARY_DATABASE_URL = SQLALCHEMY_DATABASE_URI
    VPLIB_DATABASE_URL = SQLALCHEMY_DATABASE_URI
    DATABASE_URL = SQLALCHEMY_DATABASE_URI

    VECTOPLAN_LIBRARY_DATABASE_REQUIRED = _read_bool_env(
        *DATABASE_REQUIRED_ENV_KEYS,
        default=True,
    )
    VECTOPLAN_LIBRARY_DATABASE_BACKEND = _database_uri_backend(SQLALCHEMY_DATABASE_URI)
    VECTOPLAN_LIBRARY_DATABASE_URI_MASKED = _mask_database_uri(SQLALCHEMY_DATABASE_URI)
    VECTOPLAN_LIBRARY_DATABASE_PUBLIC_PARTS = _database_uri_public_parts(SQLALCHEMY_DATABASE_URI)

    VECTOPLAN_LIBRARY_DB_HEALTH_CHECK = _read_bool_env(
        *DATABASE_HEALTH_CHECK_ENV_KEYS,
        default=False,
    )

    VECTOPLAN_LIBRARY_DB_WAIT_FOR_READY = _read_bool_env(
        *DATABASE_WAIT_ENV_KEYS,
        default=True,
    )
    VECTOPLAN_LIBRARY_DB_WAIT_TIMEOUT = _read_int_env(
        "VECTOPLAN_LIBRARY_DB_WAIT_TIMEOUT",
        "VPLIB_DB_WAIT_TIMEOUT",
        default=60,
        minimum=1,
        maximum=3600,
    )
    VECTOPLAN_LIBRARY_DB_WAIT_INTERVAL = _read_int_env(
        "VECTOPLAN_LIBRARY_DB_WAIT_INTERVAL",
        "VPLIB_DB_WAIT_INTERVAL",
        default=2,
        minimum=1,
        maximum=300,
    )

    # -------------------------------------------------------------------------
    # Flask-Migrate / Alembic Runtime-Flags
    # -------------------------------------------------------------------------

    MIGRATIONS_DIRECTORY = _read_str_env(
        "VECTOPLAN_LIBRARY_MIGRATIONS_DIRECTORY",
        "ALEMBIC_MIGRATIONS_DIRECTORY",
        "MIGRATIONS_DIRECTORY",
        default=DEFAULT_MIGRATIONS_DIR_NAME,
    )

    VECTOPLAN_LIBRARY_MIGRATIONS_DIRECTORY = MIGRATIONS_DIRECTORY
    ALEMBIC_MIGRATIONS_DIRECTORY = MIGRATIONS_DIRECTORY

    VECTOPLAN_LIBRARY_DB_BOOTSTRAP_ENABLED = _read_bool_env(
        "VECTOPLAN_LIBRARY_DB_BOOTSTRAP_ENABLED",
        "VPLIB_DB_BOOTSTRAP_ENABLED",
        default=True,
    )
    VECTOPLAN_LIBRARY_DB_AUTO_INIT = _read_bool_env(
        *DATABASE_AUTO_INIT_ENV_KEYS,
        default=True,
    )
    VECTOPLAN_LIBRARY_DB_AUTO_MIGRATE = _read_bool_env(
        *DATABASE_AUTO_MIGRATE_ENV_KEYS,
        default=True,
    )
    VECTOPLAN_LIBRARY_DB_AUTO_UPGRADE = _read_bool_env(
        *DATABASE_AUTO_UPGRADE_ENV_KEYS,
        default=True,
    )
    VECTOPLAN_LIBRARY_DB_MIGRATION_STRICT = _read_bool_env(
        "VECTOPLAN_LIBRARY_DB_MIGRATION_STRICT",
        "VPLIB_DB_MIGRATION_STRICT",
        default=True,
    )
    VECTOPLAN_LIBRARY_DB_RECREATE_INCOMPLETE_MIGRATIONS = _read_bool_env(
        "VECTOPLAN_LIBRARY_DB_RECREATE_INCOMPLETE_MIGRATIONS",
        "VPLIB_DB_RECREATE_INCOMPLETE_MIGRATIONS",
        default=True,
    )
    VECTOPLAN_LIBRARY_DB_AUTO_MIGRATE_MESSAGE = _read_str_env(
        "VECTOPLAN_LIBRARY_DB_AUTO_MIGRATE_MESSAGE",
        "VPLIB_DB_AUTO_MIGRATE_MESSAGE",
        default="auto creative library migration",
    )

    # Legacy-/Startup-Schalter bleiben bewusst getrennt von Flask-Migrate.
    VECTOPLAN_LIBRARY_DB_AUTO_CREATE = _read_bool_env(
        "VECTOPLAN_LIBRARY_DB_AUTO_CREATE",
        default=False,
    )
    VECTOPLAN_LIBRARY_DB_AUTO_SEED = _read_bool_env(
        "VECTOPLAN_LIBRARY_DB_AUTO_SEED",
        default=False,
    )
    VECTOPLAN_LIBRARY_DB_DROP_ALL_ON_BOOT = _read_bool_env(
        "VECTOPLAN_LIBRARY_DB_DROP_ALL_ON_BOOT",
        default=False,
    )

    # -------------------------------------------------------------------------
    # Service-Pfade
    # -------------------------------------------------------------------------

    SERVICE_ROOT = SERVICE_ROOT
    SRC_ROOT = SRC_ROOT

    BOOTSTRAP_ROOT = _build_path("src", "bootstrap")
    ROUTES_ROOT = _build_path("src", "routes")
    SERVICES_ROOT = _build_path("src", "services")
    CONFIG_ROOT = _build_path("src", "config")
    VPLIB_ROOT = _build_path("src", "vplib")
    MODELS_ROOT = _build_path("models")
    MIGRATIONS_ROOT = _read_path_env(
        "VECTOPLAN_LIBRARY_MIGRATIONS_ROOT",
        default=_build_path(MIGRATIONS_DIRECTORY),
    )

    TEMPLATES_ROOT = _build_path(DEFAULT_TEMPLATE_DIR_NAME)
    STATIC_ROOT = _build_path(DEFAULT_STATIC_DIR_NAME)
    TESTS_ROOT = _build_path("tests")

    # -------------------------------------------------------------------------
    # VPLIB-Pfade
    # -------------------------------------------------------------------------

    VPLIB_SERVICE_ROOT = _read_path_env(
        "VPLIB_SERVICE_ROOT",
        default=SERVICE_ROOT,
    )

    VPLIB_SRC_ROOT = _read_path_env(
        "VPLIB_SRC_ROOT",
        default=SRC_ROOT,
    )

    VPLIB_SOURCE_ROOT = _read_path_env(
        "VPLIB_SOURCE_ROOT",
        default=_build_path(DEFAULT_SOURCE_DIR_NAME),
    )

    VPLIB_LIBRARY_CATALOG_ROOT = _read_path_env(
        "VPLIB_LIBRARY_CATALOG_ROOT",
        default=_build_path(DEFAULT_LIBRARY_CATALOG_DIR_NAME),
    )

    VPLIB_GENERATED_ROOT = _read_path_env(
        "VPLIB_GENERATED_ROOT",
        default=_build_path(DEFAULT_GENERATED_DIR_NAME, DEFAULT_VPLIB_GENERATED_DIR_NAME),
    )

    VPLIB_ARCHIVE_ROOT = _read_path_env(
        "VPLIB_ARCHIVE_ROOT",
        default=_build_path(DEFAULT_GENERATED_DIR_NAME, DEFAULT_ARCHIVE_DIR_NAME),
    )

    VPLIB_TEST_OUTPUT_ROOT = _read_path_env(
        "VPLIB_TEST_OUTPUT_ROOT",
        default=_build_path(DEFAULT_GENERATED_DIR_NAME, DEFAULT_TEST_OUTPUT_DIR_NAME),
    )

    # -------------------------------------------------------------------------
    # Creative Library Source Pfade
    # -------------------------------------------------------------------------

    VECTOPLAN_LIBRARY_SOURCE_ROOT = _read_path_env(
        "VECTOPLAN_LIBRARY_SOURCE_ROOT",
        "VPLIB_CREATE_SOURCE_ROOT",
        "LIBRARY_SOURCE_ROOT",
        default=_build_path("src", "library", "source"),
    )

    VPLIB_CREATE_SOURCE_ROOT = VECTOPLAN_LIBRARY_SOURCE_ROOT

    # -------------------------------------------------------------------------
    # VPLIB-Routen
    # -------------------------------------------------------------------------

    VPLIB_ROUTE_PREFIX = _normalize_route_prefix(
        _read_str_env(
            "VPLIB_ROUTE_PREFIX",
            "VECTOPLAN_LIBRARY_VPLIB_ROUTE_PREFIX",
            default=DEFAULT_ROUTE_PREFIX,
        )
    )

    VECTOPLAN_LIBRARY_ROUTE_PREFIX = _normalize_route_prefix(
        _read_str_env(
            "VECTOPLAN_LIBRARY_ROUTE_PREFIX",
            "VPLIB_LIBRARY_ROUTE_PREFIX",
            "LIBRARY_ROUTE_PREFIX",
            default=DEFAULT_LIBRARY_ROUTE_PREFIX,
        ),
        default=DEFAULT_LIBRARY_ROUTE_PREFIX,
    )

    HEALTH_ROUTE_PATH = _normalize_route_path(
        _read_str_env(
            "VECTOPLAN_LIBRARY_HEALTH_ROUTE",
            default=DEFAULT_HEALTH_ROUTE,
        ),
        DEFAULT_HEALTH_ROUTE,
    )

    READY_ROUTE_PATH = _normalize_route_path(
        _read_str_env(
            "VECTOPLAN_LIBRARY_READY_ROUTE",
            default=DEFAULT_READY_ROUTE,
        ),
        DEFAULT_READY_ROUTE,
    )

    CREATE_PAGE_ROUTE_PATH = _normalize_route_path(
        _read_str_env(
            "VECTOPLAN_LIBRARY_CREATE_PAGE_ROUTE",
            default=DEFAULT_CREATE_PAGE_ROUTE,
        ),
        DEFAULT_CREATE_PAGE_ROUTE,
    )

    CREATE_API_PREFIX = _normalize_route_prefix(
        _read_str_env(
            "VECTOPLAN_LIBRARY_CREATE_API_PREFIX",
            "VPLIB_CREATE_ROUTE_PREFIX",
            default=DEFAULT_CREATE_API_PREFIX,
        ),
        default=DEFAULT_CREATE_API_PREFIX,
    )

    VPLIB_HEALTH_ROUTE_PATH = f"{VPLIB_ROUTE_PREFIX}/health"
    VPLIB_TEST_ROUTE_PATH = f"{VPLIB_ROUTE_PREFIX}/test"
    VPLIB_CREATE_ROUTE_PATH = f"{VPLIB_ROUTE_PREFIX}/create"
    VPLIB_CREATE_DRY_RUN_ROUTE_PATH = f"{VPLIB_ROUTE_PREFIX}/create/dry-run"

    VPLIB_TEST_ROUTE_ENABLED = _read_bool_env(
        "VPLIB_TEST_ROUTE_ENABLED",
        default=True,
    )

    VPLIB_CREATE_ROUTE_ENABLED = _read_bool_env(
        "VPLIB_CREATE_ROUTE_ENABLED",
        default=True,
    )

    # -------------------------------------------------------------------------
    # VPLIB-Verhalten
    # -------------------------------------------------------------------------

    VPLIB_DRY_RUN_DEFAULT = _read_bool_env(
        "VPLIB_DRY_RUN_DEFAULT",
        default=True,
    )

    VPLIB_CREATE_ARCHIVE_DEFAULT = _read_bool_env(
        "VPLIB_CREATE_ARCHIVE_DEFAULT",
        default=False,
    )

    VPLIB_DEFAULT_WRITE_MODE = _read_str_env(
        "VPLIB_DEFAULT_WRITE_MODE",
        default="fail",
    )

    VPLIB_DEFAULT_VALIDATION_MODE = _read_str_env(
        "VPLIB_DEFAULT_VALIDATION_MODE",
        default="strict",
    )

    VPLIB_PACKAGE_DIR_PATTERN = _read_str_env(
        "VPLIB_PACKAGE_DIR_PATTERN",
        default="{family_slug}",
    )

    VPLIB_ALLOW_EXTERNAL_ASSET_URI = _read_bool_env(
        "VPLIB_ALLOW_EXTERNAL_ASSET_URI",
        default=False,
    )

    # -------------------------------------------------------------------------
    # Startup / Bootstrap
    # -------------------------------------------------------------------------

    VECTOPLAN_LIBRARY_RUN_STARTUP_HOOKS = _read_bool_env(
        "VECTOPLAN_LIBRARY_RUN_STARTUP_HOOKS",
        default=True,
    )

    VECTOPLAN_LIBRARY_STARTUP_STRICT = _read_bool_env(
        "VECTOPLAN_LIBRARY_STARTUP_STRICT",
        default=False,
    )

    VECTOPLAN_LIBRARY_FAIL_FAST_CONFIG = _read_bool_env(
        "VECTOPLAN_LIBRARY_FAIL_FAST_CONFIG",
        default=False,
    )

    VECTOPLAN_LIBRARY_FAIL_FAST_VPLIB_SETTINGS = _read_bool_env(
        "VECTOPLAN_LIBRARY_FAIL_FAST_VPLIB_SETTINGS",
        default=False,
    )

    VECTOPLAN_LIBRARY_FAIL_FAST_DATABASE = _read_bool_env(
        "VECTOPLAN_LIBRARY_FAIL_FAST_DATABASE",
        default=False,
    )

    VECTOPLAN_LIBRARY_FAIL_FAST_MODELS = _read_bool_env(
        "VECTOPLAN_LIBRARY_FAIL_FAST_MODELS",
        default=False,
    )

    # -------------------------------------------------------------------------
    # Runtime / Server Defaults
    # -------------------------------------------------------------------------

    HOST = _read_str_env(
        "VECTOPLAN_LIBRARY_HOST",
        default=DEFAULT_HOST,
    )

    PORT = _read_int_env(
        "VECTOPLAN_LIBRARY_PORT",
        default=DEFAULT_PORT,
        minimum=1,
        maximum=65535,
    )

    RUN_MODE = _read_str_env(
        "VECTOPLAN_LIBRARY_RUN_MODE",
        default="gunicorn",
    )

    # -------------------------------------------------------------------------
    # Hilfsmethoden
    # -------------------------------------------------------------------------

    @classmethod
    def get_database_config(cls) -> dict[str, Any]:
        """Liefert DB-Konfiguration ohne Secrets."""
        return {
            "configured": bool(cls.SQLALCHEMY_DATABASE_URI),
            "backend": cls.VECTOPLAN_LIBRARY_DATABASE_BACKEND,
            "database_uri": cls.VECTOPLAN_LIBRARY_DATABASE_URI_MASKED,
            "database_required": bool(cls.VECTOPLAN_LIBRARY_DATABASE_REQUIRED),
            "public_parts": dict(cls.VECTOPLAN_LIBRARY_DATABASE_PUBLIC_PARTS),
            "track_modifications": bool(cls.SQLALCHEMY_TRACK_MODIFICATIONS),
            "record_queries": bool(cls.SQLALCHEMY_RECORD_QUERIES),
            "echo": bool(cls.SQLALCHEMY_ECHO),
            "engine_options": dict(cls.SQLALCHEMY_ENGINE_OPTIONS or {}),
            "health_check_enabled": bool(cls.VECTOPLAN_LIBRARY_DB_HEALTH_CHECK),
            "wait_for_ready": bool(cls.VECTOPLAN_LIBRARY_DB_WAIT_FOR_READY),
            "wait_timeout": int(cls.VECTOPLAN_LIBRARY_DB_WAIT_TIMEOUT),
            "wait_interval": int(cls.VECTOPLAN_LIBRARY_DB_WAIT_INTERVAL),
            "migrations_directory": cls.MIGRATIONS_DIRECTORY,
            "migrations_root": str(cls.MIGRATIONS_ROOT),
            "bootstrap_enabled": bool(cls.VECTOPLAN_LIBRARY_DB_BOOTSTRAP_ENABLED),
            "auto_init": bool(cls.VECTOPLAN_LIBRARY_DB_AUTO_INIT),
            "auto_migrate": bool(cls.VECTOPLAN_LIBRARY_DB_AUTO_MIGRATE),
            "auto_upgrade": bool(cls.VECTOPLAN_LIBRARY_DB_AUTO_UPGRADE),
            "migration_strict": bool(cls.VECTOPLAN_LIBRARY_DB_MIGRATION_STRICT),
            "recreate_incomplete_migrations": bool(cls.VECTOPLAN_LIBRARY_DB_RECREATE_INCOMPLETE_MIGRATIONS),
            "auto_migrate_message": cls.VECTOPLAN_LIBRARY_DB_AUTO_MIGRATE_MESSAGE,
            "legacy_auto_create": bool(cls.VECTOPLAN_LIBRARY_DB_AUTO_CREATE),
            "legacy_auto_seed": bool(cls.VECTOPLAN_LIBRARY_DB_AUTO_SEED),
            "legacy_drop_all_on_boot": bool(cls.VECTOPLAN_LIBRARY_DB_DROP_ALL_ON_BOOT),
        }

    @classmethod
    def get_vplib_paths(cls) -> dict[str, str]:
        """Liefert zentrale VPLIB-Pfade als String-Dictionary."""
        return {
            "service_root": str(cls.SERVICE_ROOT),
            "src_root": str(cls.SRC_ROOT),
            "models_root": str(cls.MODELS_ROOT),
            "migrations_root": str(cls.MIGRATIONS_ROOT),
            "vplib_service_root": str(cls.VPLIB_SERVICE_ROOT),
            "vplib_src_root": str(cls.VPLIB_SRC_ROOT),
            "vplib_source_root": str(cls.VPLIB_SOURCE_ROOT),
            "vplib_library_catalog_root": str(cls.VPLIB_LIBRARY_CATALOG_ROOT),
            "vplib_generated_root": str(cls.VPLIB_GENERATED_ROOT),
            "vplib_archive_root": str(cls.VPLIB_ARCHIVE_ROOT),
            "vplib_test_output_root": str(cls.VPLIB_TEST_OUTPUT_ROOT),
            "vectoplan_library_source_root": str(cls.VECTOPLAN_LIBRARY_SOURCE_ROOT),
        }

    @classmethod
    def get_vplib_routes(cls) -> dict[str, str]:
        """Liefert zentrale Routenpfade als Dictionary."""
        return {
            "health": cls.HEALTH_ROUTE_PATH,
            "ready": cls.READY_ROUTE_PATH,
            "vplib_prefix": cls.VPLIB_ROUTE_PREFIX,
            "vplib_health": cls.VPLIB_HEALTH_ROUTE_PATH,
            "vplib_test": cls.VPLIB_TEST_ROUTE_PATH,
            "vplib_create": cls.VPLIB_CREATE_ROUTE_PATH,
            "vplib_create_dry_run": cls.VPLIB_CREATE_DRY_RUN_ROUTE_PATH,
            "library_prefix": cls.VECTOPLAN_LIBRARY_ROUTE_PREFIX,
            "create_page": cls.CREATE_PAGE_ROUTE_PATH,
            "create_api_prefix": cls.CREATE_API_PREFIX,
        }

    @classmethod
    def build_runtime_summary(cls) -> dict[str, Any]:
        """Baut eine JSON-kompatible Runtime-Zusammenfassung."""
        return {
            "schema_version": cls.CONFIG_SCHEMA_VERSION,
            "app_name": cls.APP_NAME,
            "app_display_name": cls.APP_DISPLAY_NAME,
            "app_env": cls.APP_ENV,
            "debug": bool(cls.DEBUG),
            "testing": bool(cls.TESTING),
            "host": cls.HOST,
            "port": int(cls.PORT),
            "run_mode": cls.RUN_MODE,
            "database": cls.get_database_config(),
            "paths": cls.get_vplib_paths(),
            "routes": cls.get_vplib_routes(),
            "vplib": {
                "dry_run_default": bool(cls.VPLIB_DRY_RUN_DEFAULT),
                "create_archive_default": bool(cls.VPLIB_CREATE_ARCHIVE_DEFAULT),
                "default_write_mode": cls.VPLIB_DEFAULT_WRITE_MODE,
                "default_validation_mode": cls.VPLIB_DEFAULT_VALIDATION_MODE,
                "package_dir_pattern": cls.VPLIB_PACKAGE_DIR_PATTERN,
                "allow_external_asset_uri": bool(cls.VPLIB_ALLOW_EXTERNAL_ASSET_URI),
                "test_route_enabled": bool(cls.VPLIB_TEST_ROUTE_ENABLED),
                "create_route_enabled": bool(cls.VPLIB_CREATE_ROUTE_ENABLED),
            },
        }

    @classmethod
    def validate(cls) -> list[str]:
        """
        Führt einfache Struktur- und Konfigurationsprüfungen aus.

        Diese Methode wirft absichtlich keine Exception, sondern liefert eine
        Liste von Fehlermeldungen zurück. Die App-Factory entscheidet, ob sie
        fail-fast oder nur mit Logging reagiert.
        """
        errors: list[str] = []

        if not isinstance(cls.APP_NAME, str) or not cls.APP_NAME:
            errors.append("APP_NAME must be a non-empty string.")

        if cls.APP_NAME == "vectoplan-editor":
            errors.append("APP_NAME must not be vectoplan-editor.")

        if not isinstance(cls.VPLIB_ROUTE_PREFIX, str) or not cls.VPLIB_ROUTE_PREFIX.startswith("/"):
            errors.append("VPLIB_ROUTE_PREFIX must be a string starting with '/'.")

        for route_name, route_path in cls.get_vplib_routes().items():
            if not isinstance(route_path, str) or not route_path.startswith("/"):
                errors.append(f"Route {route_name} must start with '/'.")

        for attribute_name in (
            "SERVICE_ROOT",
            "SRC_ROOT",
            "ROUTES_ROOT",
            "SERVICES_ROOT",
            "CONFIG_ROOT",
            "VPLIB_ROOT",
            "MODELS_ROOT",
            "MIGRATIONS_ROOT",
            "VPLIB_SOURCE_ROOT",
            "VPLIB_LIBRARY_CATALOG_ROOT",
            "VPLIB_GENERATED_ROOT",
            "VPLIB_ARCHIVE_ROOT",
            "VPLIB_TEST_OUTPUT_ROOT",
            "VECTOPLAN_LIBRARY_SOURCE_ROOT",
        ):
            value = getattr(cls, attribute_name, None)
            if not isinstance(value, Path):
                errors.append(f"{attribute_name} must be pathlib.Path.")

        if cls.VPLIB_DEFAULT_WRITE_MODE not in {"fail", "skip", "overwrite"}:
            errors.append("VPLIB_DEFAULT_WRITE_MODE must be one of: fail, skip, overwrite.")

        if cls.VPLIB_DEFAULT_VALIDATION_MODE not in {"strict", "normal", "permissive"}:
            errors.append("VPLIB_DEFAULT_VALIDATION_MODE must be one of: strict, normal, permissive.")

        if cls.VECTOPLAN_LIBRARY_DATABASE_REQUIRED and not cls.SQLALCHEMY_DATABASE_URI:
            errors.append(
                "SQLALCHEMY_DATABASE_URI is required. Set SQLALCHEMY_DATABASE_URI, "
                "VECTOPLAN_LIBRARY_DATABASE_URI, VECTOPLAN_LIBRARY_DATABASE_URL, "
                "VPLIB_DATABASE_URL or DATABASE_URL."
            )

        if cls.SQLALCHEMY_DATABASE_URI:
            backend = _database_uri_backend(cls.SQLALCHEMY_DATABASE_URI)
            if backend not in {"postgresql", "sqlite"}:
                errors.append(f"Unsupported SQLALCHEMY_DATABASE_URI backend: {backend}")

        if not cls.MIGRATIONS_DIRECTORY:
            errors.append("MIGRATIONS_DIRECTORY must be configured.")

        if "/" in cls.MIGRATIONS_DIRECTORY.strip("/"):
            # Flask-Migrate kann Unterpfade, aber für diese Service-Struktur
            # halten wir es bewusst einfach.
            errors.append("MIGRATIONS_DIRECTORY should be a simple directory name such as 'migrations'.")

        if cls.VECTOPLAN_LIBRARY_DB_AUTO_MIGRATE and not cls.VECTOPLAN_LIBRARY_DB_AUTO_INIT:
            errors.append("VECTOPLAN_LIBRARY_DB_AUTO_MIGRATE=true requires VECTOPLAN_LIBRARY_DB_AUTO_INIT=true for first startup.")

        return errors


# -----------------------------------------------------------------------------
# Umgebungsspezifische Konfigurationen
# -----------------------------------------------------------------------------

class Config(BaseConfig):
    """Default-Konfiguration."""

    APP_ENV = _read_str_env(
        "VECTOPLAN_LIBRARY_ENV",
        "VECTOPLAN_ENV",
        "FLASK_ENV",
        default="development",
    )
    DEBUG = _read_bool_env(
        "VECTOPLAN_LIBRARY_DEBUG",
        "FLASK_DEBUG",
        default=True,
    )
    TESTING = _read_bool_env(
        "VECTOPLAN_LIBRARY_TESTING",
        default=False,
    )
    TEMPLATES_AUTO_RELOAD = _read_bool_env(
        "VECTOPLAN_LIBRARY_TEMPLATES_AUTO_RELOAD",
        default=True,
    )


class DevelopmentConfig(BaseConfig):
    """Explizite Entwicklungs-Konfiguration."""

    APP_ENV = "development"
    DEBUG = True
    TESTING = False
    TEMPLATES_AUTO_RELOAD = True
    SEND_FILE_MAX_AGE_DEFAULT = _read_int_env(
        "VECTOPLAN_LIBRARY_SEND_FILE_MAX_AGE_DEFAULT",
        default=0,
        minimum=0,
    )
    VECTOPLAN_LIBRARY_STARTUP_STRICT = _read_bool_env(
        "VECTOPLAN_LIBRARY_STARTUP_STRICT",
        default=False,
    )

    VECTOPLAN_LIBRARY_DB_AUTO_INIT = _read_bool_env(
        *DATABASE_AUTO_INIT_ENV_KEYS,
        default=True,
    )
    VECTOPLAN_LIBRARY_DB_AUTO_MIGRATE = _read_bool_env(
        *DATABASE_AUTO_MIGRATE_ENV_KEYS,
        default=True,
    )
    VECTOPLAN_LIBRARY_DB_AUTO_UPGRADE = _read_bool_env(
        *DATABASE_AUTO_UPGRADE_ENV_KEYS,
        default=True,
    )


class TestingConfig(BaseConfig):
    """Konfiguration für Tests."""

    APP_ENV = "testing"
    DEBUG = True
    TESTING = True
    SECRET_KEY = _read_str_env(
        "VECTOPLAN_LIBRARY_TEST_SECRET_KEY",
        default="test-secret-key",
    )
    TEMPLATES_AUTO_RELOAD = True
    SEND_FILE_MAX_AGE_DEFAULT = 0
    VPLIB_DRY_RUN_DEFAULT = True
    VECTOPLAN_LIBRARY_STARTUP_STRICT = False
    VECTOPLAN_LIBRARY_DATABASE_REQUIRED = False

    SQLALCHEMY_DATABASE_URI = _read_effective_database_uri(testing=True)
    VECTOPLAN_LIBRARY_DATABASE_URI = SQLALCHEMY_DATABASE_URI
    VECTOPLAN_LIBRARY_DATABASE_URL = SQLALCHEMY_DATABASE_URI
    VPLIB_DATABASE_URL = SQLALCHEMY_DATABASE_URI
    DATABASE_URL = SQLALCHEMY_DATABASE_URI
    VECTOPLAN_LIBRARY_DATABASE_BACKEND = _database_uri_backend(SQLALCHEMY_DATABASE_URI)
    VECTOPLAN_LIBRARY_DATABASE_URI_MASKED = _mask_database_uri(SQLALCHEMY_DATABASE_URI)
    VECTOPLAN_LIBRARY_DATABASE_PUBLIC_PARTS = _database_uri_public_parts(SQLALCHEMY_DATABASE_URI)
    SQLALCHEMY_ENGINE_OPTIONS = _build_sqlalchemy_engine_options(SQLALCHEMY_DATABASE_URI)

    VECTOPLAN_LIBRARY_DB_BOOTSTRAP_ENABLED = _read_bool_env(
        "VECTOPLAN_LIBRARY_DB_BOOTSTRAP_ENABLED",
        default=False,
    )
    VECTOPLAN_LIBRARY_DB_AUTO_INIT = False
    VECTOPLAN_LIBRARY_DB_AUTO_MIGRATE = False
    VECTOPLAN_LIBRARY_DB_AUTO_UPGRADE = False


class ProductionConfig(BaseConfig):
    """Konfiguration für produktivere Umgebungen."""

    APP_ENV = "production"
    DEBUG = False
    TESTING = False
    TEMPLATES_AUTO_RELOAD = False
    SESSION_COOKIE_SECURE = _read_bool_env(
        "VECTOPLAN_LIBRARY_SESSION_COOKIE_SECURE",
        default=True,
    )
    SEND_FILE_MAX_AGE_DEFAULT = _read_int_env(
        "VECTOPLAN_LIBRARY_SEND_FILE_MAX_AGE_DEFAULT",
        default=3600,
        minimum=0,
    )
    VECTOPLAN_LIBRARY_STARTUP_STRICT = _read_bool_env(
        "VECTOPLAN_LIBRARY_STARTUP_STRICT",
        default=False,
    )
    VECTOPLAN_LIBRARY_DATABASE_REQUIRED = True

    # In echten Production-Deployments sollte AUTO_MIGRATE normalerweise false
    # gesetzt werden. Der Default bleibt für unser aktuelles Compose-Setup bewusst
    # steuerbar über ENV und nicht hart deaktiviert.
    VECTOPLAN_LIBRARY_DB_AUTO_INIT = _read_bool_env(
        *DATABASE_AUTO_INIT_ENV_KEYS,
        default=True,
    )
    VECTOPLAN_LIBRARY_DB_AUTO_MIGRATE = _read_bool_env(
        *DATABASE_AUTO_MIGRATE_ENV_KEYS,
        default=True,
    )
    VECTOPLAN_LIBRARY_DB_AUTO_UPGRADE = _read_bool_env(
        *DATABASE_AUTO_UPGRADE_ENV_KEYS,
        default=True,
    )


CONFIG_BY_NAME: Final[dict[str, type[BaseConfig]]] = {
    "default": Config,
    "config": Config,
    "development": DevelopmentConfig,
    "dev": DevelopmentConfig,
    "testing": TestingConfig,
    "test": TestingConfig,
    "production": ProductionConfig,
    "prod": ProductionConfig,
}


def get_config_class(name: str | None = None) -> type[BaseConfig]:
    """
    Liefert robust eine Konfigurationsklasse zurück.

    Priorität:
    1. explizit übergebener Name
    2. ENV VECTOPLAN_LIBRARY_CONFIG
    3. ENV VECTOPLAN_CONFIG
    4. ENV FLASK_CONFIG
    5. Default-Konfiguration

    Unbekannte Werte fallen sauber auf Config zurück.
    """
    requested_name = _normalize_text(name)

    if requested_name is None:
        requested_name = _read_str_env(
            "VECTOPLAN_LIBRARY_CONFIG",
            "VECTOPLAN_CONFIG",
            "FLASK_CONFIG",
            default="default",
        )

    key = requested_name.lower()
    return CONFIG_BY_NAME.get(key, Config)


def get_config_summary(name: str | None = None) -> dict[str, Any]:
    """Liefert eine JSON-kompatible Config-Zusammenfassung."""
    config_class = get_config_class(name)
    return config_class.build_runtime_summary()


def clear_config_caches() -> None:
    """Leert Config-Caches."""
    _resolve_service_root.cache_clear()


__all__ = [
    "BaseConfig",
    "CONFIG_BY_NAME",
    "CONFIG_SCHEMA_VERSION",
    "Config",
    "DATABASE_AUTO_INIT_ENV_KEYS",
    "DATABASE_AUTO_MIGRATE_ENV_KEYS",
    "DATABASE_AUTO_UPGRADE_ENV_KEYS",
    "DATABASE_ENV_KEYS",
    "DATABASE_HEALTH_CHECK_ENV_KEYS",
    "DATABASE_REQUIRED_ENV_KEYS",
    "DATABASE_WAIT_ENV_KEYS",
    "DEFAULT_APP_DISPLAY_NAME",
    "DEFAULT_APP_ENV",
    "DEFAULT_APP_NAME",
    "DEFAULT_ARCHIVE_DIR_NAME",
    "DEFAULT_CREATE_API_PREFIX",
    "DEFAULT_CREATE_PAGE_ROUTE",
    "DEFAULT_DATABASE_DRIVER",
    "DEFAULT_DATABASE_HOST",
    "DEFAULT_DATABASE_NAME",
    "DEFAULT_DATABASE_PASSWORD",
    "DEFAULT_DATABASE_PORT",
    "DEFAULT_DATABASE_USER",
    "DEFAULT_GENERATED_DIR_NAME",
    "DEFAULT_HEALTH_ROUTE",
    "DEFAULT_HOST",
    "DEFAULT_LIBRARY_CATALOG_DIR_NAME",
    "DEFAULT_LIBRARY_ROUTE_PREFIX",
    "DEFAULT_MAX_CONTENT_LENGTH",
    "DEFAULT_MIGRATIONS_DIR_NAME",
    "DEFAULT_PORT",
    "DEFAULT_READY_ROUTE",
    "DEFAULT_ROUTE_PREFIX",
    "DEFAULT_SECRET_KEY",
    "DEFAULT_SERVICE_DISPLAY_NAME",
    "DEFAULT_SERVICE_NAME",
    "DEFAULT_SOURCE_DIR_NAME",
    "DEFAULT_STATIC_DIR_NAME",
    "DEFAULT_TEMPLATE_DIR_NAME",
    "DEFAULT_TEST_OUTPUT_DIR_NAME",
    "DEFAULT_VPLIB_GENERATED_DIR_NAME",
    "DevelopmentConfig",
    "ProductionConfig",
    "SERVICE_ROOT",
    "SRC_ROOT",
    "TestingConfig",
    "clear_config_caches",
    "get_config_class",
    "get_config_summary",
]