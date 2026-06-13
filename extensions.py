# services/vectoplan-library/extensions.py
"""
Internal extension registry for the vectoplan-library microservice.

Diese Datei verwaltet:

1. Die echte Flask-Erweiterungsschicht:
    - db = SQLAlchemy()
    - migrate = Migrate()

2. Eine interne, robuste Extension-/Subsystem-Registry unter:
    app.extensions["vectoplan_library"]

Wichtig:
- keine Editor-Begriffe
- keine Editor-Templates
- keine Editor-Static-Assets
- keine Route /editor
- keine Creative-Library-Scans beim Import
- keine Dateisystem-Schreiboperationen
- keine Tabellen-Erzeugung beim Import
- keine automatische Migration beim Import
- kein db.create_all()
- Datenbank-Initialisierung nur über init_database(app)
- Migration-Ausführung ausschließlich über entrypoint.sh:
    flask db init
    flask db migrate
    flask db upgrade

Ziele:
- PostgreSQL/SQLAlchemy zentral anschließen
- Flask-Migrate/Alembic vorbereiten
- `flask db ...` verfügbar machen
- konsistente Initialisierung eines Library-spezifischen Extension-Registries
- defensive, idempotente Initialisierung
- klare Status- und Metadatenstruktur pro Extension/Subsystem
- Sichtbarkeit des bestehenden VPLIB-Kerns
- Sichtbarkeit der Creative-Library-Schicht unter src/library
- Sichtbarkeit der DB-Modelle unter services/vectoplan-library/models
- kompatibel mit app.py, wsgi.py und entrypoint.sh

Datenbank-Architektur:
- Die Datenbank erzeugt keine fachliche VPLIB-/Block-ID.
- `vplib_uid` entsteht beim Erstellen des .vplib-Packages.
- PostgreSQL speichert und indiziert `vplib_uid` nur.
- Diese Datei initialisiert nur Extensions, nicht fachliche Daten.

Technische Namen, JSON-Keys und Variablen bleiben Englisch.
"""


from __future__ import annotations

import importlib
import os
import traceback
from copy import deepcopy
from dataclasses import asdict, dataclass, is_dataclass
from datetime import datetime, timezone
from functools import lru_cache
from pathlib import Path
from types import ModuleType
from typing import Any, Final, Iterable, Mapping
from urllib.parse import urlparse

from flask import Flask


# -----------------------------------------------------------------------------
# Optionale Flask-Erweiterungen
# -----------------------------------------------------------------------------

try:
    from flask_sqlalchemy import SQLAlchemy

    _SQLALCHEMY_IMPORT_ERROR: BaseException | None = None
except Exception as import_error:  # pragma: no cover - defensive runtime guard
    SQLAlchemy = None  # type: ignore[assignment]
    _SQLALCHEMY_IMPORT_ERROR = import_error


try:
    from flask_migrate import Migrate

    _MIGRATE_IMPORT_ERROR: BaseException | None = None
except Exception as import_error:  # pragma: no cover - defensive runtime guard
    Migrate = None  # type: ignore[assignment]
    _MIGRATE_IMPORT_ERROR = import_error


class _UnavailableExtension:
    """
    Fallback für fehlende optionale Flask-Erweiterungen.

    Der Service bleibt importierbar, aber jede echte Nutzung wirft einen
    klaren Fehler. Das hilft bei Health-Ausgaben und macht fehlende Dependencies
    sichtbar, ohne schon beim Import von extensions.py hart zu crashen.
    """

    def __init__(self, name: str, import_error: BaseException | None) -> None:
        self.name = name
        self.import_error = import_error

    def init_app(self, *_args: Any, **_kwargs: Any) -> None:
        raise RuntimeError(
            f"{self.name} is unavailable. Import error: {self.import_error}"
        )

    def __getattr__(self, attribute_name: str) -> Any:
        raise RuntimeError(
            f"{self.name} is unavailable; cannot access {attribute_name!r}. "
            f"Import error: {self.import_error}"
        )


db = SQLAlchemy() if SQLAlchemy is not None else _UnavailableExtension("SQLAlchemy", _SQLALCHEMY_IMPORT_ERROR)
migrate = Migrate() if Migrate is not None else _UnavailableExtension("Flask-Migrate", _MIGRATE_IMPORT_ERROR)


# -----------------------------------------------------------------------------
# Konstanten
# -----------------------------------------------------------------------------

EXTENSIONS_SCHEMA_VERSION: Final[str] = "vplib.extensions.v4"

SERVICE_EXTENSION_NAMESPACE: Final[str] = "vectoplan_library"
SERVICE_EXTENSION_REGISTRY_KEY: Final[str] = "extensions"
SERVICE_EXTENSION_REGISTRY_VERSION: Final[int] = 4

DEFAULT_SERVICE_NAME: Final[str] = "vectoplan-library"
DEFAULT_SERVICE_DISPLAY_NAME: Final[str] = "VECTOPLAN Library"

DEFAULT_VPLIB_ROUTE_PREFIX: Final[str] = "/api/v1/vplib"
DEFAULT_LIBRARY_ROUTE_PREFIX: Final[str] = "/api/v1/vplib/library"
DEFAULT_MIGRATIONS_DIRECTORY: Final[str] = "migrations"

DB_SQLALCHEMY_ENV: Final[str] = "SQLALCHEMY_DATABASE_URI"
DB_LIBRARY_URI_ENV: Final[str] = "VECTOPLAN_LIBRARY_DATABASE_URI"
DB_LIBRARY_URL_ENV: Final[str] = "VECTOPLAN_LIBRARY_DATABASE_URL"
DB_VPLIB_URL_ENV: Final[str] = "VPLIB_DATABASE_URL"
DB_DATABASE_URL_ENV: Final[str] = "DATABASE_URL"
DB_HEALTH_CHECK_ENV: Final[str] = "VECTOPLAN_LIBRARY_DB_HEALTH_CHECK"

DB_CONFIG_KEYS: Final[tuple[str, ...]] = (
    "SQLALCHEMY_DATABASE_URI",
    "VECTOPLAN_LIBRARY_DATABASE_URI",
    "VECTOPLAN_LIBRARY_DATABASE_URL",
    "VPLIB_DATABASE_URL",
    "DATABASE_URL",
)

DB_ENV_KEYS: Final[tuple[str, ...]] = (
    DB_SQLALCHEMY_ENV,
    DB_LIBRARY_URI_ENV,
    DB_LIBRARY_URL_ENV,
    DB_VPLIB_URL_ENV,
    DB_DATABASE_URL_ENV,
)

MIGRATIONS_DIRECTORY_CONFIG_KEYS: Final[tuple[str, ...]] = (
    "VECTOPLAN_LIBRARY_MIGRATIONS_DIRECTORY",
    "ALEMBIC_MIGRATIONS_DIRECTORY",
    "MIGRATIONS_DIRECTORY",
)

MIGRATIONS_DIRECTORY_ENV_KEYS: Final[tuple[str, ...]] = MIGRATIONS_DIRECTORY_CONFIG_KEYS

_TRUE_VALUES: Final[set[str]] = {"1", "true", "t", "yes", "y", "on", "enabled"}
_FALSE_VALUES: Final[set[str]] = {"0", "false", "f", "no", "n", "off", "disabled"}


# -----------------------------------------------------------------------------
# Datenstrukturen
# -----------------------------------------------------------------------------

@dataclass(frozen=True, slots=True)
class ExtensionSpec:
    """Beschreibt eine interne oder externe Library-Erweiterung/Subkomponente."""

    name: str
    category: str
    description: str
    required: bool = False

    def normalized(self) -> "ExtensionSpec":
        return ExtensionSpec(
            name=_normalize_required_text(self.name, "name"),
            category=_normalize_optional_text(self.category) or "custom",
            description=_normalize_optional_text(self.description) or "",
            required=bool(self.required),
        )

    @property
    def key(self) -> str:
        return _normalize_extension_name(self.name)

    def to_dict(self) -> dict[str, Any]:
        normalized = self.normalized()

        return {
            "name": normalized.name,
            "key": normalized.key,
            "category": normalized.category,
            "description": normalized.description,
            "required": normalized.required,
        }


@dataclass(frozen=True, slots=True)
class ModuleProbeResult:
    """Ergebnis einer defensiven Modulprüfung."""

    ok: bool
    module: str | None = None
    module_name: str | None = None
    candidates: tuple[str, ...] = tuple()
    errors: tuple[str, ...] = tuple()
    health: dict[str, Any] | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "ok": bool(self.ok),
            "module": self.module,
            "module_name": self.module_name,
            "candidates": list(self.candidates),
            "errors": list(self.errors),
            "health": _json_safe(self.health),
        }


# -----------------------------------------------------------------------------
# Kleine Hilfsfunktionen
# -----------------------------------------------------------------------------

def _utc_now_iso() -> str:
    """Liefert einen UTC-Zeitstempel im ISO-Format."""
    try:
        return datetime.now(timezone.utc).isoformat()
    except Exception:
        return "1970-01-01T00:00:00+00:00"


def _exception_to_dict(
    exc: BaseException | None,
    *,
    include_traceback: bool = False,
) -> dict[str, Any] | None:
    """Serialisiert Exceptions JSON-kompatibel."""
    if exc is None:
        return None

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


def _is_flask_app(app: object) -> bool:
    """Prüft defensiv, ob das Objekt wie eine Flask-App verwendet werden kann."""
    if isinstance(app, Flask):
        return True

    required_attributes = ("extensions", "config", "logger")

    try:
        return all(hasattr(app, attribute_name) for attribute_name in required_attributes)
    except Exception:
        return False


def _safe_log_debug(app: Flask, message: str, *args: Any) -> None:
    try:
        app.logger.debug(message, *args)
    except Exception:
        pass


def _safe_log_info(app: Flask, message: str, *args: Any) -> None:
    try:
        app.logger.info(message, *args)
    except Exception:
        pass


def _safe_log_warning(app: Flask, message: str, *args: Any) -> None:
    try:
        app.logger.warning(message, *args)
    except Exception:
        pass


def _safe_log_exception(app: Flask, message: str, *args: Any) -> None:
    try:
        app.logger.exception(message, *args)
    except Exception:
        pass


def _safe_get_config(app: Flask, key: str, default: Any = None) -> Any:
    try:
        return app.config.get(key, default)
    except Exception:
        return default


def _safe_set_config_default(app: Flask, key: str, value: Any) -> None:
    try:
        app.config.setdefault(key, value)
    except Exception:
        pass


def _safe_set_config_value(app: Flask, key: str, value: Any) -> None:
    try:
        app.config[key] = value
    except Exception:
        pass


def _safe_int(value: Any, default: int = 0, minimum: int | None = None) -> int:
    try:
        result = int(value)
    except (TypeError, ValueError):
        result = default

    if minimum is not None:
        result = max(minimum, result)

    return result


def _safe_bool(value: Any, default: bool = False) -> bool:
    if isinstance(value, bool):
        return value

    if value is None:
        return bool(default)

    text = _normalize_optional_text(value, "") or ""
    lowered = text.lower()

    if lowered in _TRUE_VALUES:
        return True

    if lowered in _FALSE_VALUES:
        return False

    return bool(default)


def _normalize_optional_text(value: Any, default: str | None = None) -> str | None:
    if value is None:
        return default

    try:
        normalized = str(value).strip()
    except Exception:
        return default

    return normalized or default


def _normalize_required_text(value: Any, field_name: str) -> str:
    normalized = _normalize_optional_text(value)

    if not normalized:
        raise ValueError(f"{field_name} is required.")

    return normalized


def _normalize_extension_name(name: Any) -> str:
    raw = _normalize_optional_text(name, "")

    if not raw:
        return ""

    return (
        raw.strip()
        .lower()
        .replace(" ", "_")
        .replace("-", "_")
        .replace("/", "_")
        .replace("\\", "_")
    )


def _deepcopy_safe(value: Any) -> Any:
    try:
        return deepcopy(value)
    except Exception:
        return value


def _json_safe(value: Any) -> Any:
    if value is None:
        return None

    if isinstance(value, (str, int, float, bool)):
        return value

    if isinstance(value, Path):
        return str(value)

    if is_dataclass(value):
        try:
            return _json_safe(asdict(value))
        except Exception:
            return str(value)

    if isinstance(value, Mapping):
        return {
            str(key): _json_safe(child_value)
            for key, child_value in value.items()
        }

    if isinstance(value, (list, tuple, set)):
        return [_json_safe(item) for item in value]

    if hasattr(value, "to_dict"):
        try:
            return _json_safe(value.to_dict())
        except Exception:
            return str(value)

    return str(value)


def _normalize_metadata(value: Mapping[str, Any] | None) -> dict[str, Any]:
    if value is None:
        return {}

    if not isinstance(value, Mapping):
        return {"value": str(value)}

    return {
        str(key): _json_safe(child_value)
        for key, child_value in value.items()
    }


def _normalize_string_tuple(values: Iterable[Any] | Any) -> tuple[str, ...]:
    if values is None:
        return tuple()

    if isinstance(values, str):
        values = (values,)

    result: list[str] = []
    seen: set[str] = set()

    for value in values:
        text = _normalize_optional_text(value)

        if not text or text in seen:
            continue

        result.append(text)
        seen.add(text)

    return tuple(result)


def _get_nested_mapping_value(mapping: Mapping[str, Any], path: str, default: Any = None) -> Any:
    current: Any = mapping

    try:
        for part in path.split("."):
            if not isinstance(current, Mapping):
                return default

            current = current.get(part, default)

        return current
    except Exception:
        return default


# -----------------------------------------------------------------------------
# Datenbank-Helfer
# -----------------------------------------------------------------------------

def is_sqlalchemy_available() -> bool:
    """Gibt zurück, ob Flask-SQLAlchemy importiert werden konnte."""
    return SQLAlchemy is not None and _SQLALCHEMY_IMPORT_ERROR is None


def is_migrate_available() -> bool:
    """Gibt zurück, ob Flask-Migrate importiert werden konnte."""
    return Migrate is not None and _MIGRATE_IMPORT_ERROR is None


def normalize_database_uri(uri: Any) -> str | None:
    """Normalisiert eine Datenbank-URI defensiv."""
    text = _normalize_optional_text(uri)

    if not text:
        return None

    if text.startswith("postgres://"):
        text = "postgresql://" + text[len("postgres://"):]

    return text


def database_backend(uri: Any) -> str:
    """Leitet DB-Backend aus einer URI ab."""
    text = normalize_database_uri(uri)

    if not text:
        return "none"

    try:
        scheme = urlparse(text).scheme.lower()
    except Exception:
        return "unknown"

    if scheme.startswith("postgresql") or scheme == "postgres":
        return "postgresql"

    if scheme.startswith("sqlite"):
        return "sqlite"

    return scheme or "unknown"


def mask_database_uri(uri: Any) -> str | None:
    """Maskiert Credentials in einer Datenbank-URI für Health-Ausgaben."""
    text = normalize_database_uri(uri)

    if not text:
        return None

    try:
        if "://" not in text or "@" not in text:
            return text

        scheme, rest = text.split("://", 1)
        credentials, host_part = rest.split("@", 1)

        if ":" in credentials:
            user = credentials.split(":", 1)[0]
            return f"{scheme}://{user}:***@{host_part}"

        return f"{scheme}://***@{host_part}"
    except Exception:
        return "<masked-database-uri>"


def get_database_uri_public_parts(uri: Any) -> dict[str, Any]:
    """Extrahiert nicht-sensitive DB-URI-Bestandteile."""
    text = normalize_database_uri(uri)

    if not text:
        return {
            "backend": "none",
            "driver": None,
            "host": None,
            "port": None,
            "database": None,
            "username": None,
        }

    try:
        parsed = urlparse(text)
        return {
            "backend": database_backend(text),
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


def get_configured_database_uri(app: Flask) -> str | None:
    """Liest die konfigurierte Datenbank-URI aus Flask-Config oder ENV."""
    for key in DB_CONFIG_KEYS:
        value = _safe_get_config(app, key)
        uri = normalize_database_uri(value)
        if uri:
            return uri

    for env_key in DB_ENV_KEYS:
        uri = normalize_database_uri(os.getenv(env_key))
        if uri:
            return uri

    return None


def configure_database_from_environment(app: Flask) -> dict[str, Any]:
    """
    Stellt SQLAlchemy-Konfiguration aus Flask-Config oder ENV sicher.

    Diese Funktion initialisiert die DB nicht. Sie setzt nur fehlende oder
    kanonische Config-Werte.
    """
    uri = get_configured_database_uri(app)

    if uri:
        _safe_set_config_value(app, "SQLALCHEMY_DATABASE_URI", uri)
        _safe_set_config_value(app, "VECTOPLAN_LIBRARY_DATABASE_URI", uri)
        _safe_set_config_value(app, "VECTOPLAN_LIBRARY_DATABASE_URL", uri)
        _safe_set_config_value(app, "VPLIB_DATABASE_URL", uri)
        _safe_set_config_value(app, "DATABASE_URL", uri)

    _safe_set_config_default(app, "SQLALCHEMY_TRACK_MODIFICATIONS", False)

    engine_options = _safe_get_config(app, "SQLALCHEMY_ENGINE_OPTIONS")
    if not isinstance(engine_options, Mapping):
        engine_options = {}

    next_engine_options = {
        "pool_pre_ping": True,
        **dict(engine_options),
    }

    _safe_set_config_value(app, "SQLALCHEMY_ENGINE_OPTIONS", next_engine_options)

    migrations_directory = get_migrations_directory(app)
    if migrations_directory:
        _safe_set_config_value(app, "MIGRATIONS_DIRECTORY", migrations_directory)
        _safe_set_config_value(app, "ALEMBIC_MIGRATIONS_DIRECTORY", migrations_directory)
        _safe_set_config_value(app, "VECTOPLAN_LIBRARY_MIGRATIONS_DIRECTORY", migrations_directory)

    return {
        "configured": bool(uri),
        "database_uri": mask_database_uri(uri),
        "database_backend": database_backend(uri),
        "database_public_parts": get_database_uri_public_parts(uri),
        "track_modifications": bool(_safe_get_config(app, "SQLALCHEMY_TRACK_MODIFICATIONS", False)),
        "engine_options": _json_safe(next_engine_options),
        "migrations_directory": migrations_directory,
    }


def get_migrations_directory(app: Flask) -> str:
    """Liest das Migrationsverzeichnis aus Config oder ENV."""
    for key in MIGRATIONS_DIRECTORY_CONFIG_KEYS:
        value = _normalize_optional_text(_safe_get_config(app, key))
        if value:
            return value

    for key in MIGRATIONS_DIRECTORY_ENV_KEYS:
        value = _normalize_optional_text(os.getenv(key))
        if value:
            return value

    return DEFAULT_MIGRATIONS_DIRECTORY


def is_database_initialized(app: Flask) -> bool:
    """Prüft, ob SQLAlchemy an der Flask-App registriert ist."""
    try:
        return "sqlalchemy" in getattr(app, "extensions", {})
    except Exception:
        return False


def is_migrate_initialized(app: Flask) -> bool:
    """Prüft, ob Flask-Migrate an der Flask-App registriert ist."""
    try:
        return "migrate" in getattr(app, "extensions", {})
    except Exception:
        return False


def init_database(app: Flask) -> dict[str, Any]:
    """
    Initialisiert SQLAlchemy und Flask-Migrate idempotent.

    Diese Funktion:
    - setzt fehlende DB-Config aus ENV
    - ruft db.init_app(app)
    - ruft migrate.init_app(app, db)
    - registriert dadurch `flask db ...`
    - erzeugt keine Tabellen
    - führt keine Migrationen aus
    - baut standardmäßig keine Testverbindung auf
    """
    config_payload = configure_database_from_environment(app)
    uri = get_configured_database_uri(app)
    migrations_directory = get_migrations_directory(app)

    result: dict[str, Any] = {
        "schema_version": EXTENSIONS_SCHEMA_VERSION,
        "configured": bool(uri),
        "database_uri": mask_database_uri(uri),
        "database_backend": database_backend(uri),
        "database_public_parts": get_database_uri_public_parts(uri),
        "migrations_directory": migrations_directory,
        "sqlalchemy_available": is_sqlalchemy_available(),
        "migrate_available": is_migrate_available(),
        "db_initialized": False,
        "migrate_initialized": False,
        "status": "unknown",
        "errors": [],
        "warnings": [],
        "config": config_payload,
    }

    if not is_sqlalchemy_available():
        result["status"] = "sqlalchemy_unavailable"
        result["errors"].append(_exception_to_dict(_SQLALCHEMY_IMPORT_ERROR))
        return result

    if not uri:
        result["status"] = "database_uri_missing"
        result["errors"].append(
            {
                "type": "ConfigurationError",
                "message": (
                    "Database URI is missing. Set SQLALCHEMY_DATABASE_URI, "
                    "VECTOPLAN_LIBRARY_DATABASE_URI, VECTOPLAN_LIBRARY_DATABASE_URL, "
                    "VPLIB_DATABASE_URL or DATABASE_URL."
                ),
            }
        )
        return result

    if is_database_initialized(app):
        result["db_initialized"] = True
        result["status"] = "already_initialized"
    else:
        try:
            db.init_app(app)
            result["db_initialized"] = True
            result["status"] = "initialized"
        except Exception as exc:
            message = str(exc).lower()
            if "already" in message and ("registered" in message or "initialized" in message):
                result["db_initialized"] = True
                result["status"] = "already_initialized"
            else:
                result["status"] = "db_init_failed"
                result["errors"].append(_exception_to_dict(exc, include_traceback=True))
                return result

    if not is_migrate_available():
        result["warnings"].append(_exception_to_dict(_MIGRATE_IMPORT_ERROR))
        return result

    if is_migrate_initialized(app):
        result["migrate_initialized"] = True
        return result

    try:
        if migrations_directory:
            try:
                migrate.init_app(app, db, directory=migrations_directory)
            except TypeError:
                migrate.init_app(app, db)
        else:
            migrate.init_app(app, db)

        result["migrate_initialized"] = True
    except Exception as exc:
        message = str(exc).lower()
        if "already" in message and ("registered" in message or "initialized" in message):
            result["migrate_initialized"] = True
        else:
            result["warnings"].append(_exception_to_dict(exc, include_traceback=True))

    return result


def check_database_connection(app: Flask) -> dict[str, Any]:
    """
    Führt optional einen `SELECT 1` gegen die konfigurierte Datenbank aus.

    Diese Funktion wird nicht automatisch bei jedem Import ausgeführt.
    """
    if not is_sqlalchemy_available():
        return {
            "ok": False,
            "status": "sqlalchemy_unavailable",
            "error": _exception_to_dict(_SQLALCHEMY_IMPORT_ERROR),
        }

    try:
        from sqlalchemy import text

        with app.app_context():
            db.session.execute(text("SELECT 1"))
            db.session.commit()

        return {
            "ok": True,
            "status": "connected",
        }
    except Exception as exc:
        try:
            db.session.rollback()
        except Exception:
            pass

        return {
            "ok": False,
            "status": "connection_failed",
            "error": _exception_to_dict(exc, include_traceback=True),
        }


def get_database_health(app: Flask, *, test_connection: bool | None = None) -> dict[str, Any]:
    """
    Liefert DB-Health.

    Args:
        test_connection:
            Wenn True, wird zusätzlich `SELECT 1` ausgeführt.
            Wenn None, steuert ENV/Config VECTOPLAN_LIBRARY_DB_HEALTH_CHECK.
    """
    uri = get_configured_database_uri(app)

    if test_connection is None:
        test_connection = _safe_bool(
            _safe_get_config(app, "VECTOPLAN_LIBRARY_DB_HEALTH_CHECK", os.getenv(DB_HEALTH_CHECK_ENV)),
            default=False,
        )

    payload = {
        "schema_version": EXTENSIONS_SCHEMA_VERSION,
        "healthy": False,
        "configured": bool(uri),
        "database_uri": mask_database_uri(uri),
        "database_backend": database_backend(uri),
        "database_public_parts": get_database_uri_public_parts(uri),
        "migrations_directory": get_migrations_directory(app),
        "sqlalchemy_available": is_sqlalchemy_available(),
        "migrate_available": is_migrate_available(),
        "sqlalchemy_import_error": _exception_to_dict(_SQLALCHEMY_IMPORT_ERROR),
        "migrate_import_error": _exception_to_dict(_MIGRATE_IMPORT_ERROR),
        "app_extensions": {
            "sqlalchemy": is_database_initialized(app),
            "migrate": is_migrate_initialized(app),
        },
        "test_connection": bool(test_connection),
        "connection": None,
    }

    payload["healthy"] = bool(
        payload["configured"]
        and payload["sqlalchemy_available"]
        and payload["app_extensions"]["sqlalchemy"]
        and payload["migrate_available"]
        and payload["app_extensions"]["migrate"]
    )

    if test_connection:
        connection = check_database_connection(app)
        payload["connection"] = connection
        payload["healthy"] = bool(payload["healthy"] and connection.get("ok"))

    return payload


# -----------------------------------------------------------------------------
# Default-Extension-Spezifikation
# -----------------------------------------------------------------------------

@lru_cache(maxsize=1)
def get_default_extension_specs() -> tuple[ExtensionSpec, ...]:
    """
    Liefert die Standard-Extension-Spezifikation für vectoplan-library.

    Diese Spezifikationen beschreiben interne Subsysteme und echte Flask-
    Erweiterungen.
    """

    return (
        ExtensionSpec(
            name="registry",
            category="internal",
            description="Internal registry area under app.extensions['vectoplan_library'].",
            required=True,
        ).normalized(),
        ExtensionSpec(
            name="configuration",
            category="internal",
            description="Loaded Flask configuration and service metadata.",
            required=True,
        ).normalized(),

        # Database
        ExtensionSpec(
            name="database",
            category="database",
            description="SQLAlchemy database integration for Creative Library persistence.",
            required=True,
        ).normalized(),
        ExtensionSpec(
            name="database_migrations",
            category="database",
            description="Flask-Migrate/Alembic integration for database schema migrations and flask db commands.",
            required=True,
        ).normalized(),
        ExtensionSpec(
            name="database_models",
            category="database",
            description="SQLAlchemy model package for Creative Library tables.",
            required=True,
        ).normalized(),
        ExtensionSpec(
            name="creative_library_models",
            category="database",
            description="Creative Library item/revision/variant/asset/scan/inventory models.",
            required=True,
        ).normalized(),

        # Settings
        ExtensionSpec(
            name="vplib_settings",
            category="configuration",
            description="VPLIB route, source, generated and catalog settings.",
            required=True,
        ).normalized(),
        ExtensionSpec(
            name="library_settings",
            category="configuration",
            description="Creative Library source, route, scan, read and cache settings.",
            required=True,
        ).normalized(),

        # HTTP / Routing
        ExtensionSpec(
            name="routes",
            category="http",
            description="Registered Flask routes and API endpoints.",
            required=True,
        ).normalized(),
        ExtensionSpec(
            name="library_routes",
            category="http",
            description="Creative Library Flask route adapter.",
            required=True,
        ).normalized(),

        # Startup
        ExtensionSpec(
            name="startup",
            category="internal",
            description="Startup hooks, structure checks and diagnostics.",
            required=True,
        ).normalized(),

        # Existing VPLIB core
        ExtensionSpec(
            name="vplib_core",
            category="vplib",
            description="Top-level VPLIB core package.",
            required=True,
        ).normalized(),
        ExtensionSpec(
            name="vplib_defaults",
            category="vplib",
            description="VPLIB defaults and document bundle builders.",
            required=True,
        ).normalized(),
        ExtensionSpec(
            name="vplib_validators",
            category="vplib",
            description="VPLIB schema, semantic, asset and package validators.",
            required=True,
        ).normalized(),
        ExtensionSpec(
            name="vplib_creators",
            category="vplib",
            description="VPLIB package, file and archive creators.",
            required=True,
        ).normalized(),
        ExtensionSpec(
            name="vplib_sources",
            category="vplib",
            description="VPLIB source scanner and source loader.",
            required=True,
        ).normalized(),

        # Creative Library backend
        ExtensionSpec(
            name="library_package",
            category="library",
            description="Top-level Creative Library package.",
            required=True,
        ).normalized(),
        ExtensionSpec(
            name="library_domain",
            category="library",
            description="Creative Library domain models for items, details and scan results.",
            required=True,
        ).normalized(),
        ExtensionSpec(
            name="library_scanner",
            category="library",
            description="Creative Library package discovery, reader and fingerprint scanner modules.",
            required=True,
        ).normalized(),
        ExtensionSpec(
            name="library_validation",
            category="library",
            description="Creative Library package validation layer above VPLIB validators.",
            required=True,
        ).normalized(),
        ExtensionSpec(
            name="library_read_models",
            category="library",
            description="Creative Library summary, detail and index read-model builders.",
            required=True,
        ).normalized(),
        ExtensionSpec(
            name="library_services",
            category="library",
            description="Creative Library scan and block service orchestration.",
            required=True,
        ).normalized(),
        ExtensionSpec(
            name="library_scan_service",
            category="library",
            description="Creative Library source scan pipeline service.",
            required=True,
        ).normalized(),
        ExtensionSpec(
            name="library_block_service",
            category="library",
            description="Creative Library block list, detail, variant and tree service.",
            required=True,
        ).normalized(),

        # Future integrations
        ExtensionSpec(
            name="cache",
            category="future",
            description="Reserved state for a future cache integration.",
            required=False,
        ).normalized(),
        ExtensionSpec(
            name="external_clients",
            category="future",
            description="Reserved state for future service clients and integrations.",
            required=False,
        ).normalized(),
    )


def get_default_extension_spec_data() -> list[dict[str, Any]]:
    return [spec.to_dict() for spec in get_default_extension_specs()]


# -----------------------------------------------------------------------------
# Registry-Aufbau
# -----------------------------------------------------------------------------

def _ensure_extensions_container(app: Flask) -> dict[str, Any]:
    if not _is_flask_app(app):
        raise TypeError("extensions.py expects a Flask app or a compatible object.")

    try:
        container = app.extensions
    except Exception as exc:
        raise RuntimeError("The Flask app does not provide a usable extensions container.") from exc

    if not isinstance(container, dict):
        raise RuntimeError("app.extensions is not a dictionary and cannot be used.")

    return container


def _ensure_service_namespace(app: Flask) -> dict[str, Any]:
    extensions_container = _ensure_extensions_container(app)

    try:
        namespace = extensions_container.setdefault(SERVICE_EXTENSION_NAMESPACE, {})
    except Exception as exc:
        raise RuntimeError("The service namespace in app.extensions could not be initialized.") from exc

    if not isinstance(namespace, dict):
        raise RuntimeError(f"app.extensions[{SERVICE_EXTENSION_NAMESPACE!r}] is not a dictionary.")

    namespace.setdefault("schema_version", EXTENSIONS_SCHEMA_VERSION)
    namespace.setdefault("namespace", SERVICE_EXTENSION_NAMESPACE)
    namespace.setdefault("extension_registry_version", SERVICE_EXTENSION_REGISTRY_VERSION)
    namespace.setdefault("extensions_initialized", False)
    namespace.setdefault("extensions_initialized_at", None)
    namespace.setdefault("extensions_init_count", 0)
    namespace.setdefault("service_name", _safe_get_config(app, "APP_NAME", DEFAULT_SERVICE_NAME))
    namespace.setdefault("service_display_name", _safe_get_config(app, "APP_DISPLAY_NAME", DEFAULT_SERVICE_DISPLAY_NAME))
    namespace.setdefault("extension_errors", [])
    namespace.setdefault("extension_warnings", [])
    namespace.setdefault("database_state", {})
    namespace.setdefault("database_health", {})
    namespace.setdefault(SERVICE_EXTENSION_REGISTRY_KEY, {})

    if not isinstance(namespace[SERVICE_EXTENSION_REGISTRY_KEY], dict):
        namespace[SERVICE_EXTENSION_REGISTRY_KEY] = {}

    if not isinstance(namespace["extension_errors"], list):
        namespace["extension_errors"] = []

    if not isinstance(namespace["extension_warnings"], list):
        namespace["extension_warnings"] = []

    if not isinstance(namespace["database_state"], dict):
        namespace["database_state"] = {}

    if not isinstance(namespace["database_health"], dict):
        namespace["database_health"] = {}

    return namespace


def _new_extension_state(spec: ExtensionSpec) -> dict[str, Any]:
    normalized = spec.normalized()
    timestamp = _utc_now_iso()

    return {
        "name": normalized.name,
        "key": normalized.key,
        "category": normalized.category,
        "description": normalized.description,
        "required": bool(normalized.required),
        "registered": True,
        "initialized": False,
        "status": "registered",
        "created_at": timestamp,
        "last_initialized_at": None,
        "last_updated_at": timestamp,
        "init_count": 0,
        "error_count": 0,
        "warning_count": 0,
        "metadata": {},
        "last_error": None,
        "last_warning": None,
    }


def _ensure_extension_registry(app: Flask) -> dict[str, dict[str, Any]]:
    namespace = _ensure_service_namespace(app)
    registry = namespace.get(SERVICE_EXTENSION_REGISTRY_KEY)

    if not isinstance(registry, dict):
        registry = {}
        namespace[SERVICE_EXTENSION_REGISTRY_KEY] = registry

    return registry


def _register_spec_if_missing(app: Flask, spec: ExtensionSpec) -> dict[str, Any]:
    normalized_spec = spec.normalized()
    registry = _ensure_extension_registry(app)
    key = _normalize_extension_name(normalized_spec.name)

    if not key:
        raise ValueError("An ExtensionSpec without a valid name cannot be registered.")

    entry = registry.get(key)

    if isinstance(entry, dict):
        entry.setdefault("name", normalized_spec.name)
        entry.setdefault("key", key)
        entry.setdefault("category", normalized_spec.category)
        entry.setdefault("description", normalized_spec.description)
        entry.setdefault("required", bool(normalized_spec.required))
        entry.setdefault("registered", True)
        entry.setdefault("initialized", False)
        entry.setdefault("status", "registered")
        entry.setdefault("created_at", _utc_now_iso())
        entry.setdefault("last_initialized_at", None)
        entry.setdefault("last_updated_at", _utc_now_iso())
        entry.setdefault("init_count", 0)
        entry.setdefault("error_count", 0)
        entry.setdefault("warning_count", 0)
        entry.setdefault("metadata", {})
        entry.setdefault("last_error", None)
        entry.setdefault("last_warning", None)

        entry["name"] = normalized_spec.name
        entry["key"] = key
        entry["category"] = normalized_spec.category
        entry["description"] = normalized_spec.description
        entry["required"] = bool(normalized_spec.required)

        if not isinstance(entry.get("metadata"), dict):
            entry["metadata"] = {}

        return entry

    entry = _new_extension_state(normalized_spec)
    registry[key] = entry
    return entry


def _append_warning(app: Flask, message: str, *, details: Mapping[str, Any] | None = None) -> None:
    namespace = _ensure_service_namespace(app)

    try:
        namespace["extension_warnings"].append(
            {
                "message": message,
                "details": _normalize_metadata(details),
                "timestamp": _utc_now_iso(),
            }
        )
    except Exception:
        pass

    _safe_log_warning(app, message)


def _append_error(app: Flask, message: str, *, details: Mapping[str, Any] | None = None) -> None:
    namespace = _ensure_service_namespace(app)

    try:
        namespace["extension_errors"].append(
            {
                "message": message,
                "details": _normalize_metadata(details),
                "timestamp": _utc_now_iso(),
            }
        )
    except Exception:
        pass

    _safe_log_warning(app, message)


# -----------------------------------------------------------------------------
# Status-Updates pro Extension
# -----------------------------------------------------------------------------

def register_extension(
    app: Flask,
    name: str,
    *,
    category: str = "custom",
    description: str = "",
    required: bool = False,
) -> dict[str, Any]:
    spec = ExtensionSpec(
        name=_normalize_extension_name(name),
        category=_normalize_optional_text(category, "custom") or "custom",
        description=_normalize_optional_text(description, "") or "",
        required=bool(required),
    ).normalized()

    if not spec.name:
        raise ValueError("register_extension() requires a valid extension name.")

    entry = _register_spec_if_missing(app, spec)
    entry["last_updated_at"] = _utc_now_iso()
    return entry


def mark_extension_initialized(
    app: Flask,
    name: str,
    metadata: dict[str, Any] | None = None,
) -> dict[str, Any]:
    normalized_name = _normalize_extension_name(name)

    if not normalized_name:
        raise ValueError("mark_extension_initialized() requires a valid extension name.")

    entry = register_extension(app, normalized_name)

    entry["initialized"] = True
    entry["status"] = "initialized"
    entry["init_count"] = _safe_int(entry.get("init_count"), default=0, minimum=0) + 1
    entry["last_initialized_at"] = _utc_now_iso()
    entry["last_updated_at"] = entry["last_initialized_at"]
    entry["last_error"] = None

    if isinstance(metadata, dict) and metadata:
        current_metadata = entry.get("metadata")

        if not isinstance(current_metadata, dict):
            current_metadata = {}
            entry["metadata"] = current_metadata

        try:
            current_metadata.update(_normalize_metadata(metadata))
        except Exception:
            entry["metadata"] = _deepcopy_safe(_normalize_metadata(metadata))

    return entry


def mark_extension_warning(
    app: Flask,
    name: str,
    warning_message: str,
    metadata: dict[str, Any] | None = None,
) -> dict[str, Any]:
    normalized_name = _normalize_extension_name(name)

    if not normalized_name:
        raise ValueError("mark_extension_warning() requires a valid extension name.")

    entry = register_extension(app, normalized_name)
    timestamp = _utc_now_iso()

    entry["status"] = "warning"
    entry["warning_count"] = _safe_int(entry.get("warning_count"), default=0, minimum=0) + 1
    entry["last_warning"] = {
        "message": str(warning_message),
        "timestamp": timestamp,
    }
    entry["last_updated_at"] = timestamp

    if isinstance(metadata, dict) and metadata:
        current_metadata = entry.get("metadata")

        if not isinstance(current_metadata, dict):
            current_metadata = {}
            entry["metadata"] = current_metadata

        try:
            current_metadata.update(_normalize_metadata(metadata))
        except Exception:
            entry["metadata"] = _deepcopy_safe(_normalize_metadata(metadata))

    _append_warning(app, f"Extension warning [{normalized_name}]: {warning_message}", details=metadata)
    return entry


def mark_extension_failed(
    app: Flask,
    name: str,
    error_message: str,
    metadata: dict[str, Any] | None = None,
) -> dict[str, Any]:
    normalized_name = _normalize_extension_name(name)

    if not normalized_name:
        raise ValueError("mark_extension_failed() requires a valid extension name.")

    entry = register_extension(app, normalized_name)
    timestamp = _utc_now_iso()

    entry["initialized"] = False
    entry["status"] = "failed"
    entry["error_count"] = _safe_int(entry.get("error_count"), default=0, minimum=0) + 1
    entry["last_error"] = {
        "message": str(error_message),
        "timestamp": timestamp,
    }
    entry["last_updated_at"] = timestamp

    if isinstance(metadata, dict) and metadata:
        current_metadata = entry.get("metadata")

        if not isinstance(current_metadata, dict):
            current_metadata = {}
            entry["metadata"] = current_metadata

        try:
            current_metadata.update(_normalize_metadata(metadata))
        except Exception:
            entry["metadata"] = _deepcopy_safe(_normalize_metadata(metadata))

    _append_error(app, f"Extension error [{normalized_name}]: {error_message}", details=metadata)
    return entry


# -----------------------------------------------------------------------------
# Modulprüfung / Health-Adapter
# -----------------------------------------------------------------------------

def _try_import_first(candidates: Iterable[str]) -> tuple[ModuleType | None, str | None, tuple[str, ...]]:
    errors: list[str] = []

    for module_name in candidates:
        try:
            return importlib.import_module(module_name), module_name, tuple(errors)
        except Exception as exc:
            errors.append(f"{module_name}: {exc}")

    return None, None, tuple(errors)


def _call_first_health_function(module: ModuleType, function_names: Iterable[str]) -> dict[str, Any] | None:
    for function_name in function_names:
        try:
            candidate = getattr(module, function_name, None)

            if not callable(candidate):
                continue

            return _json_safe(candidate())

        except TypeError:
            try:
                return _json_safe(candidate(include_subhealth=True))
            except Exception as exc:
                return {
                    "ok": False,
                    "healthy": False,
                    "status": "health_error",
                    "function": function_name,
                    "error": _exception_to_dict(exc),
                }

        except Exception as exc:
            return {
                "ok": False,
                "healthy": False,
                "status": "health_error",
                "function": function_name,
                "error": _exception_to_dict(exc),
            }

    return None


def _probe_module(
    *,
    candidates: Iterable[str],
    health_functions: Iterable[str] = tuple(),
) -> ModuleProbeResult:
    candidate_tuple = _normalize_string_tuple(candidates)
    module, module_name, errors = _try_import_first(candidate_tuple)

    if module is None or module_name is None:
        return ModuleProbeResult(
            ok=False,
            module=None,
            module_name=None,
            candidates=candidate_tuple,
            errors=errors,
            health=None,
        )

    health = None

    if health_functions:
        health = _call_first_health_function(module, health_functions)

    return ModuleProbeResult(
        ok=True,
        module=module_name,
        module_name=getattr(module, "__name__", module_name),
        candidates=candidate_tuple,
        errors=errors,
        health=health,
    )


def _mark_module_state(
    app: Flask,
    *,
    extension_name: str,
    candidates: Iterable[str],
    required: bool,
    health_functions: Iterable[str] = tuple(),
) -> None:
    probe = _probe_module(
        candidates=candidates,
        health_functions=health_functions,
    )

    metadata = probe.to_dict()

    if probe.ok:
        health = probe.health if isinstance(probe.health, Mapping) else None
        health_healthy = True

        if isinstance(health, Mapping) and "healthy" in health:
            health_healthy = _safe_bool(health.get("healthy"), default=True)
        elif isinstance(health, Mapping) and "ok" in health:
            health_healthy = _safe_bool(health.get("ok"), default=True)

        if health_healthy:
            mark_extension_initialized(
                app,
                extension_name,
                metadata=metadata,
            )
        else:
            mark_extension_warning(
                app,
                extension_name,
                f"Module {probe.module!r} was imported but health is not clean.",
                metadata=metadata,
            )
        return

    message = f"Could not import module for {extension_name}."

    if required:
        mark_extension_failed(
            app,
            extension_name,
            message,
            metadata=metadata,
        )
    else:
        mark_extension_warning(
            app,
            extension_name,
            message,
            metadata=metadata,
        )


# -----------------------------------------------------------------------------
# Built-in Initialisierung
# -----------------------------------------------------------------------------

def _seed_default_specs(app: Flask) -> None:
    for spec in get_default_extension_specs():
        _register_spec_if_missing(app, spec)


def _get_route_rules(app: Flask) -> list[str]:
    try:
        return sorted(str(rule) for rule in app.url_map.iter_rules())
    except Exception:
        return []


def _get_registered_blueprints(app: Flask) -> list[str]:
    try:
        return sorted(str(name) for name in app.blueprints.keys())
    except Exception:
        return []


def _initialize_configuration_state(app: Flask) -> None:
    config_class_name = None

    try:
        config_class_name = app.extensions.get(SERVICE_EXTENSION_NAMESPACE, {}).get("config_class_name")
    except Exception:
        pass

    mark_extension_initialized(
        app,
        "configuration",
        metadata={
            "app_name": _safe_get_config(app, "APP_NAME", DEFAULT_SERVICE_NAME),
            "app_display_name": _safe_get_config(app, "APP_DISPLAY_NAME", DEFAULT_SERVICE_DISPLAY_NAME),
            "debug": bool(_safe_get_config(app, "DEBUG", False)),
            "testing": bool(_safe_get_config(app, "TESTING", False)),
            "config_class_name": config_class_name,
        },
    )


def _initialize_database_state(app: Flask) -> None:
    namespace = _ensure_service_namespace(app)

    init_payload = init_database(app)
    health_payload = get_database_health(app, test_connection=False)

    namespace["database_state"] = _json_safe(init_payload)
    namespace["database_health"] = _json_safe(health_payload)

    if init_payload.get("db_initialized"):
        mark_extension_initialized(
            app,
            "database",
            metadata={
                "init": init_payload,
                "health": health_payload,
            },
        )
    else:
        mark_extension_failed(
            app,
            "database",
            "Database extension was not initialized.",
            metadata={
                "init": init_payload,
                "health": health_payload,
            },
        )

    if init_payload.get("migrate_initialized"):
        mark_extension_initialized(
            app,
            "database_migrations",
            metadata={
                "migrations_directory": get_migrations_directory(app),
                "init": init_payload,
            },
        )
    elif is_migrate_available():
        mark_extension_failed(
            app,
            "database_migrations",
            "Flask-Migrate is available but was not initialized.",
            metadata={"init": init_payload},
        )
    else:
        mark_extension_failed(
            app,
            "database_migrations",
            "Flask-Migrate is unavailable.",
            metadata={
                "error": _exception_to_dict(_MIGRATE_IMPORT_ERROR),
            },
        )


def _initialize_database_model_states(app: Flask) -> None:
    _mark_module_state(
        app,
        extension_name="database_models",
        candidates=("models", "src.models"),
        required=True,
        health_functions=("get_models_health",),
    )
    _mark_module_state(
        app,
        extension_name="creative_library_models",
        candidates=("models.creative_library", "src.models.creative_library"),
        required=True,
        health_functions=("get_creative_library_models_health",),
    )


def _initialize_vplib_settings_state(app: Flask) -> None:
    namespace = _ensure_service_namespace(app)

    settings_payload = namespace.get("vplib_settings")
    settings_error = namespace.get("vplib_settings_error")
    settings_module = namespace.get("vplib_settings_module")

    if settings_payload:
        mark_extension_initialized(
            app,
            "vplib_settings",
            metadata={
                "settings_module": settings_module,
                "settings": _json_safe(settings_payload),
            },
        )
        return

    if settings_error:
        mark_extension_failed(
            app,
            "vplib_settings",
            "VPLIB settings were not loaded.",
            metadata={
                "settings_module": settings_module,
                "error": settings_error,
            },
        )
        return

    mark_extension_warning(
        app,
        "vplib_settings",
        "VPLIB settings state is not available in app.extensions yet.",
    )


def _initialize_library_settings_state(app: Flask) -> None:
    namespace = _ensure_service_namespace(app)

    settings_payload = namespace.get("library_settings")
    settings_error = namespace.get("library_settings_error")
    settings_module = namespace.get("library_settings_module")
    settings_health = namespace.get("library_settings_health")
    settings_health_error = namespace.get("library_settings_health_error")

    if settings_payload:
        mark_extension_initialized(
            app,
            "library_settings",
            metadata={
                "settings_module": settings_module,
                "settings": _json_safe(settings_payload),
                "health": _json_safe(settings_health),
                "health_error": settings_health_error,
            },
        )
        return

    if settings_error:
        mark_extension_failed(
            app,
            "library_settings",
            "Library settings were not loaded.",
            metadata={
                "settings_module": settings_module,
                "error": settings_error,
            },
        )
        return

    _mark_module_state(
        app,
        extension_name="library_settings",
        candidates=("config.library_settings", "src.config.library_settings"),
        required=True,
        health_functions=("get_library_settings_health",),
    )


def _initialize_routes_state(app: Flask) -> None:
    route_rules = _get_route_rules(app)
    registered_blueprints = _get_registered_blueprints(app)

    vplib_route_prefix = _normalize_optional_text(_safe_get_config(app, "VPLIB_ROUTE_PREFIX"), DEFAULT_VPLIB_ROUTE_PREFIX)
    if not vplib_route_prefix:
        vplib_route_prefix = DEFAULT_VPLIB_ROUTE_PREFIX

    library_route_prefix = _normalize_optional_text(
        _safe_get_config(app, "VECTOPLAN_LIBRARY_ROUTE_PREFIX"),
        DEFAULT_LIBRARY_ROUTE_PREFIX,
    ) or DEFAULT_LIBRARY_ROUTE_PREFIX

    try:
        namespace = _ensure_service_namespace(app)
        library_settings = namespace.get("library_settings")

        if isinstance(library_settings, Mapping):
            route_prefix = _get_nested_mapping_value(library_settings, "route_plan.route_prefix")
            if route_prefix:
                library_route_prefix = str(route_prefix)

    except Exception:
        pass

    expected_routes = (
        "/health",
        "/health/ready",
        f"{vplib_route_prefix}/health",
        f"{vplib_route_prefix}/test",
        f"{vplib_route_prefix}/create",
        f"{vplib_route_prefix}/create/dry-run",
        f"{library_route_prefix}/health",
        f"{library_route_prefix}/scan",
        f"{library_route_prefix}/blocks",
        f"{library_route_prefix}/tree",
    )

    missing_routes = [
        route
        for route in expected_routes
        if route not in route_rules
    ]

    expected_blueprints = ("vplib_bp", "library_bp")
    missing_blueprints = [
        name
        for name in expected_blueprints
        if name not in registered_blueprints
    ]

    metadata = {
        "route_count": len(route_rules),
        "routes": route_rules,
        "registered_blueprints": registered_blueprints,
        "expected_blueprints": list(expected_blueprints),
        "missing_blueprints": missing_blueprints,
        "expected_routes": list(expected_routes),
        "missing_routes": missing_routes,
        "vplib_route_prefix": vplib_route_prefix,
        "library_route_prefix": library_route_prefix,
    }

    if missing_blueprints:
        mark_extension_failed(
            app,
            "routes",
            "One or more required blueprints are missing.",
            metadata=metadata,
        )
        return

    if missing_routes:
        mark_extension_warning(
            app,
            "routes",
            "One or more expected routes are missing.",
            metadata=metadata,
        )
        return

    mark_extension_initialized(app, "routes", metadata=metadata)


def _initialize_library_routes_state(app: Flask) -> None:
    route_rules = _get_route_rules(app)
    registered_blueprints = _get_registered_blueprints(app)

    library_route_prefix = _normalize_optional_text(
        _safe_get_config(app, "VECTOPLAN_LIBRARY_ROUTE_PREFIX"),
        DEFAULT_LIBRARY_ROUTE_PREFIX,
    ) or DEFAULT_LIBRARY_ROUTE_PREFIX

    library_routes = [
        route
        for route in route_rules
        if route.startswith(library_route_prefix)
    ]

    metadata = {
        "registered_blueprints": registered_blueprints,
        "library_routes": library_routes,
        "library_route_count": len(library_routes),
        "expected_blueprint": "library_bp",
        "library_route_prefix": library_route_prefix,
    }

    if "library_bp" not in registered_blueprints:
        mark_extension_failed(
            app,
            "library_routes",
            "Creative Library blueprint is not registered.",
            metadata=metadata,
        )
        return

    if not library_routes:
        mark_extension_warning(
            app,
            "library_routes",
            "Creative Library blueprint is registered but no library routes were detected.",
            metadata=metadata,
        )
        return

    _mark_module_state(
        app,
        extension_name="library_routes",
        candidates=("routes.library_routes", "src.routes.library_routes"),
        required=True,
        health_functions=("get_library_routes_health",),
    )

    entry = get_extension_state(app, "library_routes")
    if isinstance(entry, dict):
        current = entry.get("metadata")
        if isinstance(current, dict):
            current.update(_normalize_metadata(metadata))


def _initialize_vplib_module_states(app: Flask) -> None:
    module_specs: tuple[tuple[str, tuple[str, ...], bool, tuple[str, ...]], ...] = (
        ("vplib_core", ("vplib", "src.vplib"), True, ("get_vplib_health",)),
        ("vplib_defaults", ("vplib.defaults", "src.vplib.defaults"), True, ("get_defaults_health",)),
        ("vplib_validators", ("vplib.validators", "src.vplib.validators"), True, ("get_validators_health",)),
        ("vplib_creators", ("vplib.creators", "src.vplib.creators"), True, ("get_creators_health",)),
        ("vplib_sources", ("vplib.sources", "src.vplib.sources"), True, ("get_sources_health",)),
    )

    for extension_name, candidates, required, health_functions in module_specs:
        _mark_module_state(
            app,
            extension_name=extension_name,
            candidates=candidates,
            required=required,
            health_functions=health_functions,
        )


def _initialize_library_module_states(app: Flask) -> None:
    module_specs: tuple[tuple[str, tuple[str, ...], bool, tuple[str, ...]], ...] = (
        ("library_package", ("library", "src.library"), True, ("get_library_health",)),
        ("library_domain", ("library.domain", "src.library.domain"), True, ("get_domain_health",)),
        ("library_scanner", ("library.scanner", "src.library.scanner"), True, ("get_scanner_health",)),
        ("library_validation", ("library.validation", "src.library.validation"), True, ("get_validation_health",)),
        ("library_read_models", ("library.read_models", "src.library.read_models"), True, ("get_read_models_health",)),
        ("library_services", ("library.services", "src.library.services"), True, ("get_services_health",)),
        (
            "library_scan_service",
            ("library.services.library_scan_service", "src.library.services.library_scan_service"),
            True,
            ("get_library_scan_service_health",),
        ),
        (
            "library_block_service",
            ("library.services.library_block_service", "src.library.services.library_block_service"),
            True,
            ("get_library_block_service_health",),
        ),
    )

    for extension_name, candidates, required, health_functions in module_specs:
        _mark_module_state(
            app,
            extension_name=extension_name,
            candidates=candidates,
            required=required,
            health_functions=health_functions,
        )


def _initialize_startup_state(app: Flask) -> None:
    namespace = _ensure_service_namespace(app)

    metadata = {
        "startup_attempted": namespace.get("startup_attempted"),
        "startup_completed": namespace.get("startup_completed"),
        "startup_skipped": namespace.get("startup_skipped"),
        "startup_module_name": namespace.get("startup_module_name"),
        "startup_hook_name": namespace.get("startup_hook_name"),
        "startup_error": namespace.get("startup_error"),
    }

    if namespace.get("startup_error"):
        mark_extension_warning(
            app,
            "startup",
            "Startup hook reported an error.",
            metadata=metadata,
        )
        return

    if namespace.get("startup_completed"):
        mark_extension_initialized(
            app,
            "startup",
            metadata=metadata,
        )
        return

    if namespace.get("startup_skipped"):
        mark_extension_warning(
            app,
            "startup",
            "Startup hook was skipped.",
            metadata=metadata,
        )
        return

    mark_extension_initialized(
        app,
        "startup",
        metadata=metadata,
    )


def _initialize_future_states(app: Flask) -> None:
    for name in ("cache", "external_clients"):
        entry = register_extension(
            app,
            name,
            category="future",
            description=f"Reserved state for future {name} integration.",
            required=False,
        )
        entry["status"] = "reserved"
        entry["last_updated_at"] = _utc_now_iso()


def _initialize_builtin_states(app: Flask) -> None:
    mark_extension_initialized(
        app,
        "registry",
        metadata={
            "namespace": SERVICE_EXTENSION_NAMESPACE,
            "registry_version": SERVICE_EXTENSION_REGISTRY_VERSION,
            "schema_version": EXTENSIONS_SCHEMA_VERSION,
        },
    )

    _initialize_configuration_state(app)
    _initialize_database_state(app)
    _initialize_vplib_settings_state(app)
    _initialize_library_settings_state(app)
    _initialize_routes_state(app)
    _initialize_library_routes_state(app)
    _initialize_startup_state(app)
    _initialize_vplib_module_states(app)
    _initialize_library_module_states(app)
    _initialize_database_model_states(app)
    _initialize_future_states(app)


# -----------------------------------------------------------------------------
# Initialisierung
# -----------------------------------------------------------------------------

def init_extensions(app: Flask) -> Flask:
    """
    Initialisiert die interne Extension-Struktur von vectoplan-library idempotent.

    Diese Funktion kann mehrfach aufgerufen werden:
    - sie zerstört keine bestehenden Einträge
    - sie ergänzt nur fehlende Standardstrukturen
    - sie initialisiert SQLAlchemy/Flask-Migrate, falls konfiguriert
    - sie führt keine Migrationen aus
    - sie erzeugt keine Tabellen
    - sie aktualisiert den Initialisierungszeitpunkt und Zähler kontrolliert
    """

    namespace = _ensure_service_namespace(app)
    _seed_default_specs(app)

    try:
        _initialize_builtin_states(app)
    except Exception as exc:
        _safe_log_exception(app, "Failed to initialize built-in library extension states.")
        _append_error(app, f"Failed to initialize built-in library extension states: {exc!r}")
        raise

    namespace["schema_version"] = EXTENSIONS_SCHEMA_VERSION
    namespace["extensions_initialized"] = True
    namespace["extensions_initialized_at"] = _utc_now_iso()
    namespace["extensions_init_count"] = _safe_int(
        namespace.get("extensions_init_count"),
        default=0,
        minimum=0,
    ) + 1

    _safe_log_info(app, "Internal extension structure for vectoplan-library was initialized.")
    return app


# -----------------------------------------------------------------------------
# Lesezugriffe / Debug-Helfer
# -----------------------------------------------------------------------------

def get_extension_registry(app: Flask) -> dict[str, dict[str, Any]]:
    registry = _ensure_extension_registry(app)
    return _deepcopy_safe(registry)


def get_extension_state(app: Flask, name: str) -> dict[str, Any] | None:
    normalized_name = _normalize_extension_name(name)

    if not normalized_name:
        return None

    registry = _ensure_extension_registry(app)
    entry = registry.get(normalized_name)

    if not isinstance(entry, dict):
        return None

    return _deepcopy_safe(entry)


def list_extension_states(app: Flask) -> list[dict[str, Any]]:
    registry = _ensure_extension_registry(app)
    result: list[dict[str, Any]] = []

    for name in sorted(registry.keys()):
        entry = registry.get(name)

        if isinstance(entry, dict):
            result.append(_deepcopy_safe(entry))

    return result


def get_extension_summary(app: Flask) -> dict[str, Any]:
    namespace = _ensure_service_namespace(app)
    registry = _ensure_extension_registry(app)

    total_count = 0
    initialized_count = 0
    warning_count = 0
    failed_count = 0
    reserved_count = 0
    required_count = 0
    required_failed_count = 0
    library_count = 0
    library_initialized_count = 0
    vplib_count = 0
    vplib_initialized_count = 0
    database_count = 0
    database_initialized_count = 0

    by_category: dict[str, dict[str, int]] = {}

    for entry in registry.values():
        if not isinstance(entry, dict):
            continue

        total_count += 1

        category = str(entry.get("category") or "custom")
        by_category.setdefault(
            category,
            {
                "total": 0,
                "initialized": 0,
                "warning": 0,
                "failed": 0,
                "reserved": 0,
            },
        )
        by_category[category]["total"] += 1

        if bool(entry.get("required")):
            required_count += 1

        if bool(entry.get("initialized")):
            initialized_count += 1
            by_category[category]["initialized"] += 1

        status = entry.get("status")

        if status == "warning":
            warning_count += 1
            by_category[category]["warning"] += 1

        elif status == "failed":
            failed_count += 1
            by_category[category]["failed"] += 1

            if bool(entry.get("required")):
                required_failed_count += 1

        elif status == "reserved":
            reserved_count += 1
            by_category[category]["reserved"] += 1

        if category == "library":
            library_count += 1
            if bool(entry.get("initialized")):
                library_initialized_count += 1

        if category == "vplib":
            vplib_count += 1
            if bool(entry.get("initialized")):
                vplib_initialized_count += 1

        if category == "database":
            database_count += 1
            if bool(entry.get("initialized")):
                database_initialized_count += 1

    return {
        "schema_version": EXTENSIONS_SCHEMA_VERSION,
        "namespace": namespace.get("namespace", SERVICE_EXTENSION_NAMESPACE),
        "registry_version": namespace.get(
            "extension_registry_version",
            SERVICE_EXTENSION_REGISTRY_VERSION,
        ),
        "service_name": namespace.get("service_name", DEFAULT_SERVICE_NAME),
        "service_display_name": namespace.get("service_display_name", DEFAULT_SERVICE_DISPLAY_NAME),
        "extensions_initialized": bool(namespace.get("extensions_initialized")),
        "extensions_initialized_at": namespace.get("extensions_initialized_at"),
        "extensions_init_count": _safe_int(namespace.get("extensions_init_count"), default=0, minimum=0),
        "total_extensions": total_count,
        "required_extensions": required_count,
        "initialized_extensions": initialized_count,
        "warning_extensions": warning_count,
        "failed_extensions": failed_count,
        "reserved_extensions": reserved_count,
        "required_failed_extensions": required_failed_count,
        "vplib_extensions": vplib_count,
        "vplib_initialized_extensions": vplib_initialized_count,
        "library_extensions": library_count,
        "library_initialized_extensions": library_initialized_count,
        "database_extensions": database_count,
        "database_initialized_extensions": database_initialized_count,
        "warning_log_count": len(namespace.get("extension_warnings", []) or []),
        "error_log_count": len(namespace.get("extension_errors", []) or []),
        "by_category": by_category,
        "healthy": required_failed_count == 0,
    }


def get_extensions_health(app: Flask) -> dict[str, Any]:
    summary = get_extension_summary(app)
    registry = get_extension_registry(app)

    return {
        "schema_version": EXTENSIONS_SCHEMA_VERSION,
        "healthy": bool(summary.get("healthy", False)),
        "summary": summary,
        "database": get_database_health(app, test_connection=False),
        "registry": registry,
    }


def get_library_extensions_health(app: Flask) -> dict[str, Any]:
    registry = get_extension_registry(app)
    library_entries = {
        name: entry
        for name, entry in registry.items()
        if isinstance(entry, dict) and entry.get("category") == "library"
    }

    required_failed = [
        name
        for name, entry in library_entries.items()
        if entry.get("required") and entry.get("status") == "failed"
    ]

    warnings = [
        name
        for name, entry in library_entries.items()
        if entry.get("status") == "warning"
    ]

    initialized = [
        name
        for name, entry in library_entries.items()
        if entry.get("initialized")
    ]

    return {
        "schema_version": EXTENSIONS_SCHEMA_VERSION,
        "healthy": not required_failed,
        "total": len(library_entries),
        "initialized": len(initialized),
        "warning": len(warnings),
        "failed_required": len(required_failed),
        "initialized_names": sorted(initialized),
        "warning_names": sorted(warnings),
        "failed_required_names": sorted(required_failed),
        "registry": library_entries,
    }


def get_database_extensions_health(app: Flask, *, test_connection: bool = False) -> dict[str, Any]:
    registry = get_extension_registry(app)
    database_entries = {
        name: entry
        for name, entry in registry.items()
        if isinstance(entry, dict) and entry.get("category") == "database"
    }

    required_failed = [
        name
        for name, entry in database_entries.items()
        if entry.get("required") and entry.get("status") == "failed"
    ]

    return {
        "schema_version": EXTENSIONS_SCHEMA_VERSION,
        "healthy": not required_failed,
        "database": get_database_health(app, test_connection=test_connection),
        "total": len(database_entries),
        "failed_required": len(required_failed),
        "failed_required_names": sorted(required_failed),
        "registry": database_entries,
    }


def clear_extension_caches() -> None:
    get_default_extension_specs.cache_clear()


# -----------------------------------------------------------------------------
# Public API
# -----------------------------------------------------------------------------

__all__: Final[list[str]] = [
    "DB_CONFIG_KEYS",
    "DB_DATABASE_URL_ENV",
    "DB_ENV_KEYS",
    "DB_HEALTH_CHECK_ENV",
    "DB_LIBRARY_URI_ENV",
    "DB_LIBRARY_URL_ENV",
    "DB_SQLALCHEMY_ENV",
    "DB_VPLIB_URL_ENV",
    "DEFAULT_LIBRARY_ROUTE_PREFIX",
    "DEFAULT_MIGRATIONS_DIRECTORY",
    "DEFAULT_SERVICE_DISPLAY_NAME",
    "DEFAULT_SERVICE_NAME",
    "DEFAULT_VPLIB_ROUTE_PREFIX",
    "EXTENSIONS_SCHEMA_VERSION",
    "ExtensionSpec",
    "MIGRATIONS_DIRECTORY_CONFIG_KEYS",
    "MIGRATIONS_DIRECTORY_ENV_KEYS",
    "ModuleProbeResult",
    "SERVICE_EXTENSION_NAMESPACE",
    "SERVICE_EXTENSION_REGISTRY_KEY",
    "SERVICE_EXTENSION_REGISTRY_VERSION",
    "check_database_connection",
    "clear_extension_caches",
    "configure_database_from_environment",
    "database_backend",
    "db",
    "get_configured_database_uri",
    "get_database_extensions_health",
    "get_database_health",
    "get_database_uri_public_parts",
    "get_default_extension_spec_data",
    "get_default_extension_specs",
    "get_extension_registry",
    "get_extension_state",
    "get_extension_summary",
    "get_extensions_health",
    "get_library_extensions_health",
    "get_migrations_directory",
    "init_database",
    "init_extensions",
    "is_database_initialized",
    "is_migrate_available",
    "is_migrate_initialized",
    "is_sqlalchemy_available",
    "list_extension_states",
    "mark_extension_failed",
    "mark_extension_initialized",
    "mark_extension_warning",
    "mask_database_uri",
    "migrate",
    "normalize_database_uri",
    "register_extension",
]