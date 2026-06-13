# services/vectoplan-library/app.py
"""
Flask app factory for the vectoplan-library microservice.

Diese Datei ist der robuste Startpunkt des VPLIB-Library-Service.

Verantwortung:

- .env-Datei defensiv laden
- Importpfade für Service-Root und src-Root stabil setzen
- Root-config.py gezielt laden, ohne von src/config blockiert zu werden
- VPLIB-Settings aus src/config/vplib_settings.py laden
- Library-Settings aus src/config/library_settings.py laden
- Library-Package-Health defensiv erfassen
- Flask-App erzeugen
- Konfiguration anwenden
- SQLAlchemy/Flask-Migrate defensiv initialisieren
- Datenbankmodelle defensiv importieren
- db.metadata sichtbar machen, damit `flask db migrate` Tabellen erkennt
- Basis-Health-Routen bereitstellen
- Blueprints zentral registrieren
- Create-Blueprint für /create defensiv registrieren
- optionale Startup-Hooks defensiv ausführen
- interne Extension-Registry initialisieren
- Service-, VPLIB-, Library-, Create-, Database- und Model-Metadaten am App-Objekt hinterlegen

Wichtig:

- keine Editor-Begriffe
- keine Editor-Routen
- keine Prüfung auf routes/editor.py
- keine Creative-Library-Scanlogik in app.py
- keine Create-Fachlogik in app.py
- keine automatischen DB-Migrationen in app.py
- keine automatischen db.create_all()-Aufrufe in app.py
- kein produktiver Datenbank-Read/Write beim Import
- DB-Initialisierung bedeutet nur: SQLAlchemy/Migrate an Flask-App binden
- Model-Import bedeutet nur: Modelklassen in db.metadata registrieren
- `flask db init/migrate/upgrade` läuft ausschließlich über entrypoint.sh
- VPLIB-Settings werden bevorzugt aus src/config/vplib_settings.py geladen
- Library-Settings werden bevorzugt aus src/config/library_settings.py geladen
- Startup-Hooks dürfen im nicht-strikten Modus nicht den Containerstart blockieren
- Der Create-Blueprint wird zusätzlich zur zentralen routes-Registry defensiv registriert.
  Wenn routes.register_blueprints(app) ihn später ebenfalls registriert, wird doppelte
  Registrierung verhindert.

Die eigentliche Creative-Library-Logik liegt unter:

    src/library/
    src/services/library_route_service.py
    src/routes/library_routes.py

Die einfache Create-Logik liegt unter:

    src/library/services/library_create_service.py
    src/services/library_create_route_service.py
    src/routes/create.py

Die Datenbankmodelle liegen unter:

    models/
    models/creative_library.py

Diese Datei verdrahtet nur App-Start, Settings, DB-Extension, Model-Import,
Health und Blueprint-Registrierung.
"""

from __future__ import annotations

import importlib
import importlib.util as importlib_util
import logging
import os
import sys
import traceback
from dataclasses import asdict, is_dataclass
from functools import lru_cache
from pathlib import Path
from types import ModuleType
from typing import Any, Final, Mapping

from dotenv import load_dotenv
from flask import Flask, jsonify


# -----------------------------------------------------------------------------
# Konstanten
# -----------------------------------------------------------------------------

SERVICE_SCHEMA_VERSION: Final[str] = "vplib.flask_app.v4"
SERVICE_EXTENSION_KEY: Final[str] = "vectoplan_library"

_TRUE_VALUES: Final[set[str]] = {"1", "true", "t", "yes", "y", "on", "enabled"}
_FALSE_VALUES: Final[set[str]] = {"0", "false", "f", "no", "n", "off", "disabled"}

_ENV_CONFIG_MODULE: Final[str] = "VECTOPLAN_LIBRARY_CONFIG_MODULE"
_ENV_ROUTE_MODULE: Final[str] = "VECTOPLAN_LIBRARY_ROUTE_MODULE"
_ENV_CREATE_ROUTE_MODULE: Final[str] = "VECTOPLAN_LIBRARY_CREATE_ROUTE_MODULE"
_ENV_STARTUP_MODULE: Final[str] = "VECTOPLAN_LIBRARY_STARTUP_MODULE"
_ENV_EXTENSIONS_MODULE: Final[str] = "VECTOPLAN_LIBRARY_EXTENSIONS_MODULE"
_ENV_MODELS_MODULE: Final[str] = "VECTOPLAN_LIBRARY_MODELS_MODULE"

_ENV_FAIL_FAST_CONFIG: Final[str] = "VECTOPLAN_LIBRARY_FAIL_FAST_CONFIG"
_ENV_FAIL_FAST_VPLIB_SETTINGS: Final[str] = "VECTOPLAN_LIBRARY_FAIL_FAST_VPLIB_SETTINGS"
_ENV_FAIL_FAST_LIBRARY_SETTINGS: Final[str] = "VECTOPLAN_LIBRARY_FAIL_FAST_LIBRARY_SETTINGS"
_ENV_FAIL_FAST_LIBRARY_HEALTH: Final[str] = "VECTOPLAN_LIBRARY_FAIL_FAST_LIBRARY_HEALTH"
_ENV_FAIL_FAST_CREATE_BLUEPRINT: Final[str] = "VECTOPLAN_LIBRARY_FAIL_FAST_CREATE_BLUEPRINT"
_ENV_FAIL_FAST_DATABASE: Final[str] = "VECTOPLAN_LIBRARY_FAIL_FAST_DATABASE"
_ENV_FAIL_FAST_MODELS: Final[str] = "VECTOPLAN_LIBRARY_FAIL_FAST_MODELS"
_ENV_FAIL_FAST_EXTENSIONS: Final[str] = "VECTOPLAN_LIBRARY_FAIL_FAST_EXTENSIONS"

_ENV_RUN_STARTUP_HOOKS: Final[str] = "VECTOPLAN_LIBRARY_RUN_STARTUP_HOOKS"
_ENV_STARTUP_STRICT: Final[str] = "VECTOPLAN_LIBRARY_STARTUP_STRICT"

_DEFAULT_APP_NAME: Final[str] = "vectoplan-library"
_DEFAULT_APP_DISPLAY_NAME: Final[str] = "VECTOPLAN Library"

_DEFAULT_TEMPLATE_DIR_NAME: Final[str] = "templates"
_DEFAULT_STATIC_DIR_NAME: Final[str] = "static"

_DEFAULT_CONFIG_MODULE_CANDIDATES: Final[tuple[str, ...]] = (
    "config",
    "src.config",
)

_DEFAULT_EXTENSIONS_MODULE_CANDIDATES: Final[tuple[str, ...]] = (
    "extensions",
    "src.extensions",
)

_DEFAULT_MODELS_MODULE_CANDIDATES: Final[tuple[str, ...]] = (
    "models",
    "src.models",
)

_DEFAULT_ROUTE_MODULE_CANDIDATES: Final[tuple[str, ...]] = (
    "routes",
    "src.routes",
)

_DEFAULT_CREATE_ROUTE_MODULE_CANDIDATES: Final[tuple[str, ...]] = (
    "routes.create",
    "src.routes.create",
)

_DEFAULT_STARTUP_MODULE_CANDIDATES: Final[tuple[str, ...]] = (
    "src.bootstrap.startup",
    "bootstrap.startup",
)

_DEFAULT_VPLIB_SETTINGS_MODULE_CANDIDATES: Final[tuple[str, ...]] = (
    "src.config.vplib_settings",
    "config.vplib_settings",
)

_DEFAULT_LIBRARY_SETTINGS_MODULE_CANDIDATES: Final[tuple[str, ...]] = (
    "src.config.library_settings",
    "config.library_settings",
)

_DEFAULT_LIBRARY_PACKAGE_MODULE_CANDIDATES: Final[tuple[str, ...]] = (
    "library",
    "src.library",
)


# -----------------------------------------------------------------------------
# Text, ENV, Logging
# -----------------------------------------------------------------------------

def _normalize_text(value: Any, default: str | None = None) -> str | None:
    """Normalisiert Texteingaben defensiv."""
    if value is None:
        return default

    try:
        normalized = str(value).strip()
    except Exception:
        return default

    return normalized or default


def _env_flag(name: str, default: bool = False) -> bool:
    """Liest eine Bool-Umgebungsvariable defensiv aus."""
    value = _normalize_text(os.getenv(name))

    if value is None:
        return bool(default)

    lowered = value.lower()

    if lowered in _TRUE_VALUES:
        return True

    if lowered in _FALSE_VALUES:
        return False

    return bool(default)


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


def _safe_log_error(app: Flask, message: str, *args: Any) -> None:
    try:
        app.logger.error(message, *args)
    except Exception:
        pass


# -----------------------------------------------------------------------------
# Pfade und Importpfade
# -----------------------------------------------------------------------------

def _resolve_service_root() -> Path:
    """Liefert robust das Root-Verzeichnis des Services."""
    try:
        return Path(__file__).resolve().parent
    except Exception:
        return Path(".").resolve()


SERVICE_ROOT: Final[Path] = _resolve_service_root()
SRC_ROOT: Final[Path] = SERVICE_ROOT / "src"


@lru_cache(maxsize=1)
def _ensure_import_paths() -> tuple[str, ...]:
    """
    Stellt sicher, dass src/ und Service-Root im Python-Pfad vorhanden sind.

    Reihenfolge:
    1. src/
    2. Service-Root

    Dadurch sind diese Imports möglich:
    - import routes
    - import services.library_route_service
    - import services.library_create_route_service
    - import vplib
    - import library
    - import config.library_settings
    - import extensions
    - import models
    """

    ordered_paths: list[str] = []

    for candidate in (SRC_ROOT, SERVICE_ROOT):
        try:
            candidate_str = str(candidate)
        except Exception:
            continue

        if candidate_str:
            ordered_paths.append(candidate_str)

    for candidate_str in reversed(ordered_paths):
        try:
            while candidate_str in sys.path:
                sys.path.remove(candidate_str)

            sys.path.insert(0, candidate_str)

        except Exception:
            continue

    return tuple(ordered_paths)


def _safe_path_from_config(value: Any, fallback_name: str) -> str:
    """Wandelt einen konfigurierten Pfad robust in einen String um."""
    try:
        if isinstance(value, Path):
            return str(value)

        if isinstance(value, str) and value.strip():
            return value.strip()

    except Exception:
        pass

    try:
        return str(SERVICE_ROOT / fallback_name)
    except Exception:
        return fallback_name


@lru_cache(maxsize=1)
def _load_environment_file() -> bool:
    """Lädt eine .env-Datei defensiv und nur einmal pro Prozess."""
    _ensure_import_paths()

    candidate_paths: list[Path] = []

    try:
        candidate_paths.append(SERVICE_ROOT / ".env")
    except Exception:
        pass

    try:
        candidate_paths.append(Path.cwd() / ".env")
    except Exception:
        pass

    for candidate in candidate_paths:
        try:
            if candidate.is_file():
                load_dotenv(dotenv_path=candidate, override=False)
                return True
        except Exception:
            continue

    try:
        load_dotenv(override=False)
        return True
    except Exception:
        return False


# -----------------------------------------------------------------------------
# Import-Helfer
# -----------------------------------------------------------------------------

@lru_cache(maxsize=128)
def _import_module(module_name: str) -> ModuleType:
    """Importiert ein Modul gecacht."""
    _ensure_import_paths()
    return importlib.import_module(module_name)


@lru_cache(maxsize=64)
def _load_module_from_file(module_name: str, file_path: str) -> ModuleType:
    """Lädt ein Modul direkt aus einem Dateipfad."""
    path = Path(file_path)

    if not path.is_file():
        raise ModuleNotFoundError(f"Module file does not exist: {path}")

    spec = importlib_util.spec_from_file_location(module_name, path)

    if spec is None or spec.loader is None:
        raise RuntimeError(f"Could not create import spec for {path}")

    module = importlib_util.module_from_spec(spec)
    sys.modules[module_name] = module
    spec.loader.exec_module(module)
    return module


@lru_cache(maxsize=128)
def _candidate_missing_names(module_name: str) -> tuple[str, ...]:
    """Liefert zulässige ModuleNotFoundError.name-Werte für einen Modulpfad."""
    parts = module_name.split(".")
    return tuple(".".join(parts[:index]) for index in range(1, len(parts) + 1))


def _is_missing_candidate_module(exc: ModuleNotFoundError, module_name: str) -> bool:
    """Prüft, ob ein Kandidatenmodul selbst fehlt."""
    missing_name = _normalize_text(getattr(exc, "name", None))

    if missing_name is None:
        return False

    return missing_name in _candidate_missing_names(module_name)


def _env_candidate(name: str) -> str | None:
    """Liest optionalen Modulpfad aus Environment."""
    return _normalize_text(os.getenv(name))


def _dedupe_module_candidates(values: list[str]) -> tuple[str, ...]:
    """Dedupliziert Modulpfade stabil."""
    result: list[str] = []
    seen: set[str] = set()

    for value in values:
        normalized = _normalize_text(value)

        if not normalized or normalized in seen:
            continue

        result.append(normalized)
        seen.add(normalized)

    return tuple(result)


@lru_cache(maxsize=1)
def _get_config_module_candidates() -> tuple[str, ...]:
    candidates: list[str] = []

    env_candidate = _env_candidate(_ENV_CONFIG_MODULE)
    if env_candidate:
        candidates.append(env_candidate)

    candidates.extend(_DEFAULT_CONFIG_MODULE_CANDIDATES)
    return _dedupe_module_candidates(candidates)


@lru_cache(maxsize=1)
def _get_extensions_module_candidates() -> tuple[str, ...]:
    candidates: list[str] = []

    env_candidate = _env_candidate(_ENV_EXTENSIONS_MODULE)
    if env_candidate:
        candidates.append(env_candidate)

    candidates.extend(_DEFAULT_EXTENSIONS_MODULE_CANDIDATES)
    return _dedupe_module_candidates(candidates)


@lru_cache(maxsize=1)
def _get_models_module_candidates() -> tuple[str, ...]:
    candidates: list[str] = []

    env_candidate = _env_candidate(_ENV_MODELS_MODULE)
    if env_candidate:
        candidates.append(env_candidate)

    candidates.extend(_DEFAULT_MODELS_MODULE_CANDIDATES)
    return _dedupe_module_candidates(candidates)


@lru_cache(maxsize=1)
def _get_route_module_candidates() -> tuple[str, ...]:
    candidates: list[str] = []

    env_candidate = _env_candidate(_ENV_ROUTE_MODULE)
    if env_candidate:
        candidates.append(env_candidate)

    candidates.extend(_DEFAULT_ROUTE_MODULE_CANDIDATES)
    return _dedupe_module_candidates(candidates)


@lru_cache(maxsize=1)
def _get_create_route_module_candidates() -> tuple[str, ...]:
    candidates: list[str] = []

    env_candidate = _env_candidate(_ENV_CREATE_ROUTE_MODULE)
    if env_candidate:
        candidates.append(env_candidate)

    candidates.extend(_DEFAULT_CREATE_ROUTE_MODULE_CANDIDATES)
    return _dedupe_module_candidates(candidates)


@lru_cache(maxsize=1)
def _get_startup_module_candidates() -> tuple[str, ...]:
    candidates: list[str] = []

    env_candidate = _env_candidate(_ENV_STARTUP_MODULE)
    if env_candidate:
        candidates.append(env_candidate)

    candidates.extend(_DEFAULT_STARTUP_MODULE_CANDIDATES)
    return _dedupe_module_candidates(candidates)


@lru_cache(maxsize=1)
def _get_vplib_settings_module_candidates() -> tuple[str, ...]:
    return _DEFAULT_VPLIB_SETTINGS_MODULE_CANDIDATES


@lru_cache(maxsize=1)
def _get_library_settings_module_candidates() -> tuple[str, ...]:
    return _DEFAULT_LIBRARY_SETTINGS_MODULE_CANDIDATES


@lru_cache(maxsize=1)
def _get_library_package_module_candidates() -> tuple[str, ...]:
    return _DEFAULT_LIBRARY_PACKAGE_MODULE_CANDIDATES


def _resolve_first_existing_module(
    candidates: tuple[str, ...],
    *,
    purpose: str,
    app: Flask | None = None,
    optional: bool = False,
) -> tuple[ModuleType | None, str | None]:
    """
    Löst das erste importierbare Modul aus Kandidaten auf.

    Verhalten:
    - fehlt ein Kandidat selbst, wird der nächste probiert
    - fehlt eine innere Abhängigkeit, wird hart abgebrochen
    - wenn optional=True und kein Kandidat existiert, wird (None, None) geliefert
    """

    _ensure_import_paths()
    errors: list[str] = []

    for module_name in candidates:
        try:
            module = _import_module(module_name)
            return module, module_name

        except ModuleNotFoundError as exc:
            errors.append(f"{module_name}: {exc}")

            if _is_missing_candidate_module(exc, module_name):
                if app is not None:
                    _safe_log_debug(
                        app,
                        "%s module `%s` not found; checking next candidate.",
                        purpose,
                        module_name,
                    )

                continue

            raise RuntimeError(
                f"The {purpose} module {module_name!r} could not be loaded "
                f"because an inner dependency is missing: {getattr(exc, 'name', None)!r}."
            ) from exc

        except Exception as exc:
            errors.append(f"{module_name}: {exc}")
            raise RuntimeError(f"The {purpose} module {module_name!r} could not be loaded: {exc}") from exc

    if optional:
        return None, None

    raise RuntimeError(
        f"No {purpose} module could be imported. "
        f"Checked candidates: {', '.join(candidates)}. Errors: {' | '.join(errors)}"
    )


def _exception_to_dict(exc: BaseException, *, include_traceback: bool = False) -> dict[str, Any]:
    """Serialisiert Exceptions JSON-kompatibel."""
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


# -----------------------------------------------------------------------------
# Konfiguration
# -----------------------------------------------------------------------------

@lru_cache(maxsize=1)
def _resolve_config_module() -> tuple[ModuleType, str]:
    """
    Löst das Konfigurationsmodul auf.

    Wichtig:
    Root config.py wird direkt aus SERVICE_ROOT/config.py geladen. Dadurch wird
    es nicht von src/config als Package überschattet.
    """

    root_config_path = SERVICE_ROOT / "config.py"

    if root_config_path.is_file():
        try:
            module = _load_module_from_file("_vectoplan_library_root_config", str(root_config_path))
            return module, str(root_config_path)
        except Exception:
            pass

    module, module_name = _resolve_first_existing_module(
        _get_config_module_candidates(),
        purpose="config",
        optional=False,
    )

    if module is None or module_name is None:
        raise RuntimeError("No config module could be resolved.")

    return module, module_name


def _resolve_config_class(config_object: Any = None) -> Any:
    """Löst robust die zu verwendende Konfigurationsklasse auf."""
    config_module, _module_name = _resolve_config_module()

    config_class_default = getattr(config_module, "Config", None)
    get_config_class = getattr(config_module, "get_config_class", None)

    if config_object is None:
        if callable(get_config_class):
            try:
                return get_config_class()
            except Exception:
                pass

        if config_class_default is not None:
            return config_class_default

        raise RuntimeError("Config module does not provide Config or get_config_class().")

    if isinstance(config_object, str):
        if callable(get_config_class):
            try:
                return get_config_class(config_object)
            except Exception:
                pass

        if config_class_default is not None:
            return config_class_default

        raise RuntimeError(f"Could not resolve config class for {config_object!r}.")

    return config_object


def _validate_config(config_class: Any, logger: logging.Logger) -> None:
    """Führt optionale Konfigurationsvalidierung aus."""
    validator = getattr(config_class, "validate", None)

    if not callable(validator):
        return

    try:
        errors = validator()
    except Exception as exc:
        errors = [f"Configuration validation failed with an exception: {exc!r}"]

    if not errors:
        return

    message = " | ".join(str(error) for error in errors if error)

    if _env_flag(_ENV_FAIL_FAST_CONFIG, default=False):
        raise RuntimeError(f"Invalid configuration for vectoplan-library: {message}")

    try:
        logger.warning("Configuration warning for vectoplan-library: %s", message)
    except Exception:
        pass


# -----------------------------------------------------------------------------
# Flask-App
# -----------------------------------------------------------------------------

def _create_flask_app(config_class: Any) -> Flask:
    """Erzeugt die Flask-Anwendung mit robust aufgelösten Pfaden."""
    template_folder = _safe_path_from_config(
        getattr(config_class, "TEMPLATES_ROOT", None),
        _DEFAULT_TEMPLATE_DIR_NAME,
    )
    static_folder = _safe_path_from_config(
        getattr(config_class, "STATIC_ROOT", None),
        _DEFAULT_STATIC_DIR_NAME,
    )

    try:
        app = Flask(
            __name__,
            template_folder=template_folder,
            static_folder=static_folder,
            static_url_path="/static",
        )
    except Exception as exc:
        raise RuntimeError(
            "Flask app could not be created. "
            f"template_folder={template_folder!r}, static_folder={static_folder!r}"
        ) from exc

    return app


def _ensure_service_registry(app: Flask) -> dict[str, Any]:
    """Stellt app.extensions[SERVICE_EXTENSION_KEY] bereit."""
    try:
        app.extensions.setdefault(SERVICE_EXTENSION_KEY, {})
        registry = app.extensions[SERVICE_EXTENSION_KEY]

        if not isinstance(registry, dict):
            raise TypeError(f"app.extensions[{SERVICE_EXTENSION_KEY!r}] is not a dict.")

        return registry

    except Exception as exc:
        raise RuntimeError(f"Could not initialize extension registry {SERVICE_EXTENSION_KEY!r}.") from exc


def _apply_config(app: Flask, config_class: Any) -> None:
    """Wendet die Konfiguration auf die Flask-App an."""
    try:
        app.config.from_object(config_class)
    except Exception as exc:
        raise RuntimeError(
            f"Configuration object {getattr(config_class, '__name__', config_class)!r} could not be loaded."
        ) from exc

    registry = _ensure_service_registry(app)

    registry["schema_version"] = SERVICE_SCHEMA_VERSION
    registry["service_name"] = app.config.get("APP_NAME", _DEFAULT_APP_NAME)
    registry["service_display_name"] = app.config.get("APP_DISPLAY_NAME", _DEFAULT_APP_DISPLAY_NAME)
    registry["config_class_name"] = getattr(config_class, "__name__", str(config_class))
    registry["service_root"] = str(SERVICE_ROOT)
    registry["src_root"] = str(SRC_ROOT)
    registry["import_paths"] = list(_ensure_import_paths())
    registry["dotenv_loaded"] = _load_environment_file()

    registry["database_initialized"] = False
    registry["database_migrate_initialized"] = False
    registry["database_init"] = None
    registry["database_health"] = None
    registry["database_error"] = None
    registry["database_metadata"] = None

    registry["models_imported"] = False
    registry["models_module_name"] = None
    registry["models_health"] = None
    registry["models_class_names"] = []
    registry["models_table_names"] = []
    registry["models_error"] = None

    registry["extensions_initialized"] = False
    registry["extensions_module_name"] = None
    registry["extensions_health"] = None
    registry["extensions_error"] = None

    registry["startup_completed"] = False
    registry["startup_attempted"] = False
    registry["startup_module_name"] = None
    registry["startup_hook_name"] = None
    registry["startup_skipped"] = False
    registry["startup_error"] = None

    registry["blueprints_registered"] = False
    registry["blueprint_registry"] = None
    registry["blueprint_registry_error"] = None

    registry["create_blueprint_registered"] = False
    registry["create_blueprint_module_name"] = None
    registry["create_blueprint_name"] = None
    registry["create_blueprint_error"] = None
    registry["create_blueprint_skipped"] = False

    registry["vplib_settings"] = None
    registry["vplib_settings_module"] = None
    registry["vplib_settings_error"] = None

    registry["library_settings"] = None
    registry["library_settings_module"] = None
    registry["library_settings_error"] = None

    registry["library_package_info"] = None
    registry["library_package_health"] = None
    registry["library_package_health_error"] = None


def _configure_app_defaults(app: Flask) -> None:
    """Setzt kleine, sinnvolle App-Defaults."""
    try:
        app.json.sort_keys = False
    except Exception:
        pass

    try:
        app.url_map.strict_slashes = False
    except Exception:
        pass


def _configure_logger(app: Flask) -> None:
    """Stellt sicher, dass die App einen brauchbaren Logger-Zustand hat."""
    try:
        if app.debug:
            app.logger.setLevel(logging.DEBUG)
        else:
            app.logger.setLevel(logging.INFO)
    except Exception:
        pass


# -----------------------------------------------------------------------------
# Database / Models / Extensions
# -----------------------------------------------------------------------------

def _resolve_extensions_module(app: Flask | None = None) -> tuple[ModuleType | None, str | None]:
    """Löst das extensions-Modul optional auf."""
    return _resolve_first_existing_module(
        _get_extensions_module_candidates(),
        purpose="extensions",
        app=app,
        optional=True,
    )


def _resolve_models_module(app: Flask | None = None) -> tuple[ModuleType | None, str | None]:
    """Löst das models-Modul optional auf."""
    return _resolve_first_existing_module(
        _get_models_module_candidates(),
        purpose="models",
        app=app,
        optional=True,
    )


def _get_db_metadata_snapshot(extensions_module: ModuleType | None) -> dict[str, Any]:
    """Liefert eine kompakte db.metadata-Diagnose."""
    if extensions_module is None:
        return {
            "available": False,
            "table_count": 0,
            "table_names": [],
            "error": "extensions module missing",
        }

    try:
        db_object = getattr(extensions_module, "db", None)
        metadata = getattr(db_object, "metadata", None)
        tables = getattr(metadata, "tables", None)

        if tables is None:
            return {
                "available": False,
                "table_count": 0,
                "table_names": [],
                "error": "db.metadata.tables missing",
            }

        table_names = sorted(str(name) for name in tables.keys())

        return {
            "available": True,
            "table_count": len(table_names),
            "table_names": table_names,
        }
    except Exception as exc:
        return {
            "available": False,
            "table_count": 0,
            "table_names": [],
            "error": str(exc),
        }


def _initialize_database_and_models(app: Flask) -> None:
    """
    Initialisiert DB-Extension und importiert Models defensiv.

    Diese Funktion:
    - erzeugt keine Tabellen
    - führt keine Migrationen aus
    - führt standardmäßig keinen SELECT aus
    - bindet SQLAlchemy/Flask-Migrate an die App
    - importiert danach Modelklassen, damit SQLAlchemy/Alembic sie kennt

    Wichtig für `flask db migrate`:
    Wenn Flask-Migrate die App über FLASK_APP=wsgi:app lädt, muss create_app()
    am Ende alle Models importiert haben. Erst danach sieht Alembic die Tabellen
    in db.metadata.
    """
    registry = _ensure_service_registry(app)
    extensions_module: ModuleType | None = None

    try:
        extensions_module, extensions_module_name = _resolve_extensions_module(app)

        if extensions_module is None:
            raise RuntimeError("extensions module could not be resolved.")

        registry["extensions_module_name"] = extensions_module_name

        init_database = getattr(extensions_module, "init_database", None)
        get_database_health = getattr(extensions_module, "get_database_health", None)

        if callable(init_database):
            database_init = init_database(app)
        else:
            raise RuntimeError(f"{extensions_module_name} does not export init_database(app).")

        registry["database_init"] = _json_safe(database_init)
        registry["database_initialized"] = bool(
            isinstance(database_init, Mapping)
            and database_init.get("db_initialized")
        )
        registry["database_migrate_initialized"] = bool(
            isinstance(database_init, Mapping)
            and database_init.get("migrate_initialized")
        )
        registry["database_error"] = None

        if callable(get_database_health):
            registry["database_health"] = _json_safe(
                get_database_health(
                    app,
                    test_connection=bool(app.config.get("VECTOPLAN_LIBRARY_DB_HEALTH_CHECK", False)),
                )
            )

    except Exception as exc:
        registry["database_initialized"] = False
        registry["database_migrate_initialized"] = False
        registry["database_error"] = _exception_to_dict(exc, include_traceback=True)

        if _env_flag(_ENV_FAIL_FAST_DATABASE, default=False):
            raise RuntimeError(f"Database initialization failed: {exc}") from exc

        _safe_log_warning(app, "Database initialization failed: %s", exc)

    try:
        models_module, models_module_name = _resolve_models_module(app)

        if models_module is None:
            raise RuntimeError("models module could not be resolved.")

        registry["models_module_name"] = models_module_name

        import_all_models = getattr(models_module, "import_all_models", None)
        get_models_health = getattr(models_module, "get_models_health", None)

        model_classes = tuple()
        if callable(import_all_models):
            model_classes = tuple(import_all_models())

        metadata_snapshot = _get_db_metadata_snapshot(extensions_module)

        registry["models_imported"] = True
        registry["models_class_names"] = [
            getattr(model_class, "__name__", str(model_class))
            for model_class in model_classes
        ]
        registry["models_table_names"] = metadata_snapshot.get("table_names", [])
        registry["database_metadata"] = metadata_snapshot
        registry["models_error"] = None

        if callable(get_models_health):
            registry["models_health"] = _json_safe(get_models_health())

        if not metadata_snapshot.get("table_count"):
            _safe_log_warning(
                app,
                "Models were imported, but db.metadata contains no tables. "
                "flask db migrate may not detect schema changes.",
            )

    except Exception as exc:
        registry["models_imported"] = False
        registry["models_error"] = _exception_to_dict(exc, include_traceback=True)
        registry["database_metadata"] = _get_db_metadata_snapshot(extensions_module)

        if _env_flag(_ENV_FAIL_FAST_MODELS, default=False):
            raise RuntimeError(f"Model import failed: {exc}") from exc

        _safe_log_warning(app, "Model import failed: %s", exc)


def _initialize_extensions_registry(app: Flask) -> None:
    """
    Initialisiert die interne Extension-Registry.

    Wird nach Blueprint-Registrierung und Startup-Hooks ausgeführt, damit die
    Registry den finalen Zustand der App besser abbildet.
    """
    registry = _ensure_service_registry(app)

    try:
        extensions_module, extensions_module_name = _resolve_extensions_module(app)

        if extensions_module is None:
            raise RuntimeError("extensions module could not be resolved.")

        init_extensions = getattr(extensions_module, "init_extensions", None)
        get_extensions_health = getattr(extensions_module, "get_extensions_health", None)

        if not callable(init_extensions):
            raise RuntimeError(f"{extensions_module_name} does not export init_extensions(app).")

        init_extensions(app)

        registry["extensions_initialized"] = True
        registry["extensions_module_name"] = extensions_module_name
        registry["extensions_error"] = None

        if callable(get_extensions_health):
            registry["extensions_health"] = _json_safe(get_extensions_health(app))

    except Exception as exc:
        registry["extensions_initialized"] = False
        registry["extensions_error"] = _exception_to_dict(exc, include_traceback=True)

        if _env_flag(_ENV_FAIL_FAST_EXTENSIONS, default=False):
            raise RuntimeError(f"Extension registry initialization failed: {exc}") from exc

        _safe_log_warning(app, "Extension registry initialization failed: %s", exc)


# -----------------------------------------------------------------------------
# JSON-Helfer und Built-in Health
# -----------------------------------------------------------------------------

def _json_safe(value: Any) -> Any:
    """Serialisiert einfache Werte JSON-kompatibel."""
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
        return {str(key): _json_safe(child) for key, child in value.items()}

    if isinstance(value, (list, tuple, set)):
        return [_json_safe(item) for item in value]

    if hasattr(value, "to_dict"):
        try:
            return _json_safe(value.to_dict())
        except Exception:
            return str(value)

    return str(value)


def _register_builtin_health_routes(app: Flask) -> None:
    """
    Registriert minimale Health-Routen direkt an der App.

    Diese Routen sind bewusst unabhängig von VPLIB-, Library- und Create-Blueprints,
    damit der Container auch dann Diagnose liefern kann, wenn ein Fach-Blueprint
    fehlschlägt.
    """

    if "library_root" not in app.view_functions:
        @app.get("/", endpoint="library_root")
        def library_root():
            return jsonify(
                {
                    "ok": True,
                    "service": _DEFAULT_APP_NAME,
                    "message": "vectoplan-library is running",
                    "health": "/health",
                    "ready": "/health/ready",
                    "vplib_health": "/api/v1/vplib/health",
                    "vplib_test": "/api/v1/vplib/test",
                    "library_health": "/api/v1/vplib/library/health",
                    "library_scan": "/api/v1/vplib/library/scan",
                    "library_blocks": "/api/v1/vplib/library/blocks",
                    "library_tree": "/api/v1/vplib/library/tree",
                    "create_page": "/create",
                    "create_health": "/api/v1/vplib/create/health",
                    "create_options": "/api/v1/vplib/create/options",
                    "create_validate": "/api/v1/vplib/create/validate",
                    "create_package_plan": "/api/v1/vplib/create/package-plan",
                    "create_download": "/api/v1/vplib/create/download",
                    "create_save": "/api/v1/vplib/create/save",
                    "database_health": "/health",
                }
            ), 200

    if "library_health" not in app.view_functions:
        @app.get("/health", endpoint="library_health")
        def library_health():
            return jsonify(
                {
                    "ok": True,
                    "status": "ok",
                    "service": _DEFAULT_APP_NAME,
                    "metadata": get_app_metadata(app),
                }
            ), 200

    if "library_health_live" not in app.view_functions:
        @app.get("/health/live", endpoint="library_health_live")
        def library_health_live():
            return jsonify(
                {
                    "ok": True,
                    "status": "live",
                    "service": _DEFAULT_APP_NAME,
                }
            ), 200

    if "library_health_ready" not in app.view_functions:
        @app.get("/health/ready", endpoint="library_health_ready")
        def library_health_ready():
            metadata = get_app_metadata(app)

            blueprints_registered = bool(metadata.get("blueprints_registered", False))
            create_route_known = _metadata_contains_create_routes(metadata)
            vplib_settings_loaded = metadata.get("vplib_settings_error") in (None, "")
            library_settings_loaded = metadata.get("library_settings_error") in (None, "")
            library_routes_known = _metadata_contains_library_routes(metadata)

            database_required = bool(app.config.get("VECTOPLAN_LIBRARY_DATABASE_REQUIRED", True))
            database_ready = bool(metadata.get("database_initialized", False)) if database_required else True
            migrate_ready = bool(metadata.get("database_migrate_initialized", False)) if database_required else True
            models_ready = bool(metadata.get("models_imported", False)) if database_required else True
            metadata_ready = bool(
                (metadata.get("database_metadata") or {}).get("table_count", 0)
            ) if database_required else True

            ready = bool(
                blueprints_registered
                and create_route_known
                and vplib_settings_loaded
                and library_settings_loaded
                and library_routes_known
                and database_ready
                and migrate_ready
                and models_ready
                and metadata_ready
            )

            return jsonify(
                {
                    "ok": ready,
                    "status": "ready" if ready else "not_ready",
                    "service": _DEFAULT_APP_NAME,
                    "checks": {
                        "blueprints_registered": blueprints_registered,
                        "create_route_known": create_route_known,
                        "vplib_settings_loaded": vplib_settings_loaded,
                        "library_settings_loaded": library_settings_loaded,
                        "library_routes_known": library_routes_known,
                        "database_required": database_required,
                        "database_ready": database_ready,
                        "migrate_ready": migrate_ready,
                        "models_ready": models_ready,
                        "metadata_ready": metadata_ready,
                    },
                    "metadata": metadata,
                }
            ), 200 if ready else 503


def _metadata_contains_library_routes(metadata: Mapping[str, Any]) -> bool:
    """Prüft, ob die neue Library-Route-Registry sichtbar ist."""
    try:
        blueprint_registry = metadata.get("blueprint_registry")

        if not isinstance(blueprint_registry, Mapping):
            return False

        registered_names = blueprint_registry.get("registered_blueprint_names") or []

        if "library_bp" in registered_names:
            return True

        app_blueprint_names = blueprint_registry.get("app_blueprint_names") or []

        if "library_bp" in app_blueprint_names:
            return True

        specs = blueprint_registry.get("specs") or []

        for spec in specs:
            if not isinstance(spec, Mapping):
                continue

            if spec.get("module_name") == "routes.library_routes":
                return True

    except Exception:
        return False

    return False


def _metadata_contains_create_routes(metadata: Mapping[str, Any]) -> bool:
    """Prüft, ob der Create-Blueprint sichtbar ist."""
    try:
        if metadata.get("create_blueprint_registered") is True:
            return True

        blueprint_registry = metadata.get("blueprint_registry")

        if isinstance(blueprint_registry, Mapping):
            registered_names = blueprint_registry.get("registered_blueprint_names") or []
            app_blueprint_names = blueprint_registry.get("app_blueprint_names") or []

            if "vplib_create" in registered_names or "vplib_create" in app_blueprint_names:
                return True

            specs = blueprint_registry.get("specs") or []

            for spec in specs:
                if not isinstance(spec, Mapping):
                    continue

                if spec.get("module_name") in {"routes.create", "src.routes.create"}:
                    return True

        app_url_rules = metadata.get("app_url_rules") or []

        if isinstance(app_url_rules, list):
            for rule in app_url_rules:
                if isinstance(rule, Mapping) and rule.get("rule") == "/create":
                    return True

    except Exception:
        return False

    return False


def _get_app_url_rules(app: Flask) -> list[dict[str, Any]]:
    """Liefert eine kompakte, JSON-kompatible Liste registrierter URL-Rules."""
    rules: list[dict[str, Any]] = []

    try:
        for rule in app.url_map.iter_rules():
            try:
                methods = sorted(method for method in rule.methods if method not in {"HEAD", "OPTIONS"})
            except Exception:
                methods = []

            rules.append(
                {
                    "endpoint": str(rule.endpoint),
                    "rule": str(rule.rule),
                    "methods": methods,
                }
            )
    except Exception:
        return []

    return rules


# -----------------------------------------------------------------------------
# VPLIB Settings
# -----------------------------------------------------------------------------

@lru_cache(maxsize=1)
def _resolve_vplib_settings_module() -> tuple[ModuleType, str]:
    """
    Lädt das VPLIB-Settings-Modul robust.

    src/config/vplib_settings.py wird bevorzugt direkt vom Dateipfad geladen.
    """

    settings_file = SRC_ROOT / "config" / "vplib_settings.py"

    if settings_file.is_file():
        module = _load_module_from_file("_vectoplan_library_vplib_settings", str(settings_file))
        return module, str(settings_file)

    module, module_name = _resolve_first_existing_module(
        _get_vplib_settings_module_candidates(),
        purpose="vplib_settings",
        optional=False,
    )

    if module is None or module_name is None:
        raise RuntimeError("No VPLIB settings module could be resolved.")

    return module, module_name


def _load_vplib_settings(app: Flask) -> Any | None:
    """Lädt optionale VPLIB-Settings und hinterlegt sie in app.extensions."""
    registry = _ensure_service_registry(app)

    try:
        settings_module, settings_module_name = _resolve_vplib_settings_module()
        get_settings = getattr(settings_module, "get_vplib_settings", None)

        if not callable(get_settings):
            raise RuntimeError(f"{settings_module_name} does not export get_vplib_settings().")

        settings = get_settings()
        settings = settings.normalized() if hasattr(settings, "normalized") else settings

        registry["vplib_settings_module"] = settings_module_name
        registry["vplib_settings"] = settings.to_dict() if hasattr(settings, "to_dict") else str(settings)
        registry["vplib_settings_error"] = None

        return settings

    except Exception as exc:
        registry["vplib_settings_error"] = str(exc)

        if _env_flag(_ENV_FAIL_FAST_VPLIB_SETTINGS, default=False):
            raise RuntimeError(f"VPLIB settings could not be loaded: {exc}") from exc

        _safe_log_warning(app, "VPLIB settings could not be loaded: %s", exc)
        return None


# -----------------------------------------------------------------------------
# Library Settings / Library Package Health
# -----------------------------------------------------------------------------

@lru_cache(maxsize=1)
def _resolve_library_settings_module() -> tuple[ModuleType, str]:
    """Lädt das Library-Settings-Modul robust."""
    settings_file = SRC_ROOT / "config" / "library_settings.py"

    if settings_file.is_file():
        module = _load_module_from_file("_vectoplan_library_library_settings", str(settings_file))
        return module, str(settings_file)

    module, module_name = _resolve_first_existing_module(
        _get_library_settings_module_candidates(),
        purpose="library_settings",
        optional=False,
    )

    if module is None or module_name is None:
        raise RuntimeError("No Library settings module could be resolved.")

    return module, module_name


def _load_library_settings(app: Flask) -> Any | None:
    """Lädt Library-Settings und hinterlegt sie in app.extensions."""
    registry = _ensure_service_registry(app)

    try:
        settings_module, settings_module_name = _resolve_library_settings_module()
        get_settings = getattr(settings_module, "get_library_settings", None)

        if not callable(get_settings):
            raise RuntimeError(f"{settings_module_name} does not export get_library_settings().")

        settings = get_settings()
        registry["library_settings_module"] = settings_module_name
        registry["library_settings"] = settings.to_dict() if hasattr(settings, "to_dict") else str(settings)
        registry["library_settings_error"] = None

        health_function = getattr(settings_module, "get_library_settings_health", None)

        if callable(health_function):
            try:
                registry["library_settings_health"] = _json_safe(health_function())
            except Exception as health_exc:
                registry["library_settings_health_error"] = str(health_exc)

        return settings

    except Exception as exc:
        registry["library_settings_error"] = str(exc)

        if _env_flag(_ENV_FAIL_FAST_LIBRARY_SETTINGS, default=False):
            raise RuntimeError(f"Library settings could not be loaded: {exc}") from exc

        _safe_log_warning(app, "Library settings could not be loaded: %s", exc)
        return None


def _resolve_library_package_module(app: Flask | None = None) -> tuple[ModuleType | None, str | None]:
    """Löst das Python-Package `library` optional auf."""
    return _resolve_first_existing_module(
        _get_library_package_module_candidates(),
        purpose="library_package",
        app=app,
        optional=True,
    )


def _load_library_package_health(app: Flask) -> dict[str, Any] | None:
    """
    Lädt optionale Metadaten und Health aus dem neuen `library` Package.

    Diese Funktion führt keinen Scan aus.
    """
    registry = _ensure_service_registry(app)

    try:
        library_module, module_name = _resolve_library_package_module(app)

        if library_module is None:
            registry["library_package_health_error"] = "library package could not be resolved"
            return None

        registry["library_package_module"] = module_name

        info_function = getattr(library_module, "get_library_info", None)

        if callable(info_function):
            try:
                registry["library_package_info"] = _json_safe(info_function())
            except Exception as info_exc:
                registry["library_package_info_error"] = str(info_exc)

        health_function = getattr(library_module, "get_library_health", None)

        if not callable(health_function):
            raise RuntimeError(f"{module_name} does not export get_library_health().")

        health = health_function(strict=False)
        registry["library_package_health"] = _json_safe(health)
        registry["library_package_health_error"] = None

        return health if isinstance(health, dict) else {"value": str(health)}

    except Exception as exc:
        registry["library_package_health_error"] = str(exc)

        if _env_flag(_ENV_FAIL_FAST_LIBRARY_HEALTH, default=False):
            raise RuntimeError(f"Library package health could not be loaded: {exc}") from exc

        _safe_log_warning(app, "Library package health could not be loaded: %s", exc)
        return None


# -----------------------------------------------------------------------------
# Blueprint-Registrierung
# -----------------------------------------------------------------------------

def _resolve_routes_module(app: Flask) -> tuple[ModuleType, str]:
    """Löst das Route-Modul robust auf."""
    module, module_name = _resolve_first_existing_module(
        _get_route_module_candidates(),
        purpose="routes",
        app=app,
        optional=False,
    )

    if module is None or module_name is None:
        raise RuntimeError("No routes module could be resolved.")

    return module, module_name


def _resolve_create_route_module(app: Flask) -> tuple[ModuleType | None, str | None]:
    """Löst das Create-Route-Modul optional auf."""
    return _resolve_first_existing_module(
        _get_create_route_module_candidates(),
        purpose="create_route",
        app=app,
        optional=True,
    )


def _register_blueprints(app: Flask) -> None:
    """Importiert die zentralen Routen defensiv und registriert sie."""
    _ensure_import_paths()

    try:
        routes_module, route_module_name = _resolve_routes_module(app)
    except Exception as exc:
        raise RuntimeError(
            "The routes module could not be imported. "
            "Expected one of: "
            + ", ".join(_get_route_module_candidates())
        ) from exc

    register_function = getattr(routes_module, "register_blueprints", None)

    if not callable(register_function):
        raise RuntimeError(
            f"The routes module {route_module_name!r} does not export callable register_blueprints(app)."
        )

    try:
        register_function(app)
    except Exception as exc:
        raise RuntimeError("Blueprint registration failed.") from exc

    registry = _ensure_service_registry(app)
    registry["blueprints_registered"] = True
    registry["route_module_name"] = route_module_name

    try:
        snapshot_function = getattr(routes_module, "get_blueprint_registry_snapshot", None)

        if callable(snapshot_function):
            registry["blueprint_registry"] = _json_safe(snapshot_function(app))
            registry["blueprint_registry_error"] = None

    except Exception as exc:
        registry["blueprint_registry_error"] = str(exc)


def _register_create_blueprint(app: Flask) -> None:
    """Registriert den einfachen Create-Blueprint für /create defensiv."""
    registry = _ensure_service_registry(app)

    if "vplib_create" in app.blueprints:
        registry["create_blueprint_registered"] = True
        registry["create_blueprint_name"] = "vplib_create"
        registry["create_blueprint_skipped"] = True
        registry["create_blueprint_skip_reason"] = "already_registered"
        registry["create_blueprint_error"] = None
        return

    try:
        create_module, module_name = _resolve_create_route_module(app)

        if create_module is None or module_name is None:
            registry["create_blueprint_registered"] = False
            registry["create_blueprint_module_name"] = None
            registry["create_blueprint_error"] = "create route module could not be resolved"

            if _env_flag(_ENV_FAIL_FAST_CREATE_BLUEPRINT, default=False):
                raise RuntimeError("Create route module could not be resolved.")

            _safe_log_warning(app, "Create route module could not be resolved; /create will not be available.")
            return

        create_blueprint = getattr(create_module, "create_bp", None)

        if create_blueprint is None:
            raise RuntimeError(f"{module_name} does not export create_bp.")

        blueprint_name = getattr(create_blueprint, "name", None) or "vplib_create"

        if blueprint_name in app.blueprints:
            registry["create_blueprint_registered"] = True
            registry["create_blueprint_module_name"] = module_name
            registry["create_blueprint_name"] = blueprint_name
            registry["create_blueprint_skipped"] = True
            registry["create_blueprint_skip_reason"] = "already_registered_by_name"
            registry["create_blueprint_error"] = None
            return

        app.register_blueprint(create_blueprint)

        registry["create_blueprint_registered"] = True
        registry["create_blueprint_module_name"] = module_name
        registry["create_blueprint_name"] = blueprint_name
        registry["create_blueprint_error"] = None
        registry["create_blueprint_skipped"] = False

        _safe_log_info(app, "Create blueprint registered successfully from %s.", module_name)

    except Exception as exc:
        registry["create_blueprint_registered"] = False
        registry["create_blueprint_error"] = str(exc)

        if _env_flag(_ENV_FAIL_FAST_CREATE_BLUEPRINT, default=False):
            raise RuntimeError(f"Create blueprint registration failed: {exc}") from exc

        _safe_log_warning(app, "Create blueprint registration failed: %s", exc)


def _refresh_blueprint_registry_snapshot(app: Flask) -> None:
    """Aktualisiert die Blueprint-/URL-Registry nach Zusatzregistrierungen."""
    registry = _ensure_service_registry(app)

    existing = registry.get("blueprint_registry")
    if not isinstance(existing, Mapping):
        existing = {}

    snapshot: dict[str, Any] = dict(existing)
    snapshot["app_blueprint_names"] = sorted(str(name) for name in app.blueprints.keys())
    snapshot["registered_blueprint_names"] = sorted(str(name) for name in app.blueprints.keys())
    snapshot["app_url_rules"] = _get_app_url_rules(app)

    registry["blueprint_registry"] = _json_safe(snapshot)
    registry["blueprint_registry_error"] = None


# -----------------------------------------------------------------------------
# Optionale Startup-Hooks
# -----------------------------------------------------------------------------

def _resolve_startup_module(app: Flask) -> tuple[ModuleType | None, str | None]:
    """Löst das bevorzugte Startup-Modul robust auf."""
    return _resolve_first_existing_module(
        _get_startup_module_candidates(),
        purpose="startup",
        app=app,
        optional=True,
    )


def _run_optional_startup_hooks(app: Flask) -> None:
    """Führt optional vorhandene Startup-Hooks aus."""
    registry = _ensure_service_registry(app)
    registry["startup_attempted"] = True
    registry["startup_module_candidates"] = list(_get_startup_module_candidates())

    if not _env_flag(_ENV_RUN_STARTUP_HOOKS, default=True):
        registry["startup_skipped"] = True
        registry["startup_skip_reason"] = "disabled_by_env"
        return

    startup_module, module_name = _resolve_startup_module(app)

    if startup_module is None or module_name is None:
        registry["startup_skipped"] = True
        _safe_log_debug(
            app,
            "No startup module found; checked candidates: %s",
            ", ".join(_get_startup_module_candidates()),
        )
        return

    registry["startup_module_name"] = module_name

    startup_function = None
    startup_function_name = None

    for function_name in ("run_startup", "bootstrap_app", "initialize_app"):
        candidate = getattr(startup_module, function_name, None)

        if callable(candidate):
            startup_function = candidate
            startup_function_name = function_name
            break

    if startup_function is None:
        registry["startup_skipped"] = True
        _safe_log_debug(
            app,
            "Startup module `%s` found, but no known startup function is defined.",
            module_name,
        )
        return

    registry["startup_hook_name"] = startup_function_name

    try:
        startup_function(app)

    except Exception as exc:
        registry["startup_error"] = str(exc)

        if _env_flag(_ENV_STARTUP_STRICT, default=False):
            raise RuntimeError(
                f"Startup hooks failed (module={module_name}, hook={startup_function_name})."
            ) from exc

        registry["startup_completed"] = False
        registry["startup_skipped"] = False
        _safe_log_warning(
            app,
            "Startup hook failed but strict mode is disabled: module=%s hook=%s error=%s",
            module_name,
            startup_function_name,
            exc,
        )
        return

    registry["startup_completed"] = True
    registry["startup_skipped"] = False


# -----------------------------------------------------------------------------
# App-Metadaten
# -----------------------------------------------------------------------------

def get_app_metadata(app: Flask) -> dict[str, Any]:
    """Gibt JSON-kompatible App-Metadaten zurück."""
    try:
        registry = _ensure_service_registry(app)
    except Exception:
        registry = {}

    metadata = {
        "schema_version": SERVICE_SCHEMA_VERSION,
        "service_name": registry.get("service_name", app.config.get("APP_NAME", _DEFAULT_APP_NAME)),
        "service_display_name": registry.get("service_display_name", app.config.get("APP_DISPLAY_NAME", _DEFAULT_APP_DISPLAY_NAME)),
        "config_class_name": registry.get("config_class_name"),
        "service_root": registry.get("service_root", str(SERVICE_ROOT)),
        "src_root": registry.get("src_root", str(SRC_ROOT)),
        "import_paths": registry.get("import_paths", list(_ensure_import_paths())),
        "dotenv_loaded": registry.get("dotenv_loaded"),

        "database_initialized": registry.get("database_initialized", False),
        "database_migrate_initialized": registry.get("database_migrate_initialized", False),
        "database_init": registry.get("database_init"),
        "database_health": registry.get("database_health"),
        "database_error": registry.get("database_error"),
        "database_metadata": registry.get("database_metadata"),

        "models_imported": registry.get("models_imported", False),
        "models_module_name": registry.get("models_module_name"),
        "models_health": registry.get("models_health"),
        "models_class_names": registry.get("models_class_names", []),
        "models_table_names": registry.get("models_table_names", []),
        "models_error": registry.get("models_error"),

        "extensions_initialized": registry.get("extensions_initialized", False),
        "extensions_module_name": registry.get("extensions_module_name"),
        "extensions_health": registry.get("extensions_health"),
        "extensions_error": registry.get("extensions_error"),

        "blueprints_registered": registry.get("blueprints_registered", False),
        "route_module_name": registry.get("route_module_name"),
        "blueprint_registry": registry.get("blueprint_registry"),
        "blueprint_registry_error": registry.get("blueprint_registry_error"),
        "app_url_rules": _get_app_url_rules(app),

        "create_blueprint_registered": registry.get("create_blueprint_registered", False),
        "create_blueprint_module_name": registry.get("create_blueprint_module_name"),
        "create_blueprint_name": registry.get("create_blueprint_name"),
        "create_blueprint_error": registry.get("create_blueprint_error"),
        "create_blueprint_skipped": registry.get("create_blueprint_skipped", False),
        "create_route_module_candidates": list(_get_create_route_module_candidates()),

        "startup_attempted": registry.get("startup_attempted", False),
        "startup_completed": registry.get("startup_completed", False),
        "startup_skipped": registry.get("startup_skipped", False),
        "startup_module_name": registry.get("startup_module_name"),
        "startup_hook_name": registry.get("startup_hook_name"),
        "startup_error": registry.get("startup_error"),

        "vplib_settings_module": registry.get("vplib_settings_module"),
        "vplib_settings": registry.get("vplib_settings"),
        "vplib_settings_error": registry.get("vplib_settings_error"),

        "library_settings_module": registry.get("library_settings_module"),
        "library_settings": registry.get("library_settings"),
        "library_settings_error": registry.get("library_settings_error"),
        "library_settings_health": registry.get("library_settings_health"),
        "library_settings_health_error": registry.get("library_settings_health_error"),

        "library_package_module": registry.get("library_package_module"),
        "library_package_info": registry.get("library_package_info"),
        "library_package_health": registry.get("library_package_health"),
        "library_package_health_error": registry.get("library_package_health_error"),
    }

    return _json_safe(metadata)


# -----------------------------------------------------------------------------
# Öffentliche App-Factory
# -----------------------------------------------------------------------------

def create_app(config_object: Any = None) -> Flask:
    """
    Öffentliche Flask-App-Factory.

    Ablauf:

    1. SERVICE_ROOT und SRC_ROOT in sys.path sicherstellen
    2. .env laden
    3. Root-config.py oder Config-Modul auflösen
    4. Flask-App erzeugen
    5. Konfiguration anwenden
    6. Logger/App-Defaults setzen
    7. Built-in Health-Routen registrieren
    8. Konfiguration validieren
    9. SQLAlchemy/Migrate initialisieren
    10. Datenbankmodelle importieren
    11. VPLIB-Settings optional laden
    12. Library-Settings optional laden
    13. Library-Package-Health optional laden
    14. zentrale Blueprints registrieren
    15. Create-Blueprint defensiv zusätzlich registrieren
    16. Blueprint-Snapshot aktualisieren
    17. optionale Startup-Hooks ausführen
    18. interne Extension-Registry initialisieren

    Für `flask db migrate` ist Schritt 9 + 10 entscheidend.
    """

    _ensure_import_paths()
    _load_environment_file()

    config_class = _resolve_config_class(config_object)
    app = _create_flask_app(config_class)

    _apply_config(app, config_class)
    _configure_app_defaults(app)
    _configure_logger(app)
    _register_builtin_health_routes(app)

    _validate_config(config_class, app.logger)

    _initialize_database_and_models(app)

    _load_vplib_settings(app)
    _load_library_settings(app)
    _load_library_package_health(app)

    _register_blueprints(app)
    _register_create_blueprint(app)
    _refresh_blueprint_registry_snapshot(app)

    with app.app_context():
        _run_optional_startup_hooks(app)

    _initialize_extensions_registry(app)

    _safe_log_info(
        app,
        "Flask app `%s` initialized successfully "
        "(config=%s, db=%s, migrate=%s, models=%s, tables=%s, route_module=%s, create_blueprint=%s, startup_module=%s).",
        app.config.get("APP_NAME", _DEFAULT_APP_NAME),
        getattr(config_class, "__name__", str(config_class)),
        _ensure_service_registry(app).get("database_initialized"),
        _ensure_service_registry(app).get("database_migrate_initialized"),
        _ensure_service_registry(app).get("models_imported"),
        len(_ensure_service_registry(app).get("models_table_names", []) or []),
        _ensure_service_registry(app).get("route_module_name"),
        _ensure_service_registry(app).get("create_blueprint_name"),
        _ensure_service_registry(app).get("startup_module_name"),
    )

    return app


def clear_app_factory_caches() -> None:
    """Leert App-Factory-Caches für Tests oder Reload-Szenarien."""
    _ensure_import_paths.cache_clear()
    _load_environment_file.cache_clear()
    _import_module.cache_clear()
    _load_module_from_file.cache_clear()
    _candidate_missing_names.cache_clear()
    _get_config_module_candidates.cache_clear()
    _get_extensions_module_candidates.cache_clear()
    _get_models_module_candidates.cache_clear()
    _get_route_module_candidates.cache_clear()
    _get_create_route_module_candidates.cache_clear()
    _get_startup_module_candidates.cache_clear()
    _get_vplib_settings_module_candidates.cache_clear()
    _get_library_settings_module_candidates.cache_clear()
    _get_library_package_module_candidates.cache_clear()
    _resolve_config_module.cache_clear()
    _resolve_vplib_settings_module.cache_clear()
    _resolve_library_settings_module.cache_clear()


__all__: Final[list[str]] = [
    "SERVICE_EXTENSION_KEY",
    "SERVICE_ROOT",
    "SERVICE_SCHEMA_VERSION",
    "SRC_ROOT",
    "clear_app_factory_caches",
    "create_app",
    "get_app_metadata",
]