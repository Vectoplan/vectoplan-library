# services/vectoplan-library/src/bootstrap/startup.py
"""
Startup hooks for the vectoplan-library microservice.

Diese Datei enthält robuste Startup-Prüfungen für den VPLIB-Library-Service.

Verantwortung:

- Startup-Metadaten im App-Namespace erfassen
- optionale Extension-Registry integrieren
- grundlegende Struktur- und Dateiprüfungen durchführen
- VPLIB-Routen prüfen
- Creative-Library-Routen prüfen
- VPLIB-Core-Imports prüfen
- Creative-Library-Imports prüfen
- VPLIB-Settings prüfen
- Library-Settings prüfen
- Warnungen und Fehler sauber protokollieren
- idempotent und fail-safe arbeiten

Wichtig:

- keine Editor-Begriffe
- keine Route /editor
- keine Pflichtdatei routes/editor.py
- keine Pflicht-Templates oder Static-Dateien
- API-/JSON-Service, kein UI-Service
- kein Scan von src/library/source beim Startup
- kein Schreiben ins Dateisystem
- keine Datenbanklogik

Diese Datei enthält bewusst:

- defensive try/except-Blöcke
- Caching für Check-Spezifikationen
- keine Business-Logik
- keine Package-Erstellung
- keine Datenbanklogik
- keine automatische Creative-Library-Persistenz
"""

from __future__ import annotations

import copy
import importlib
import importlib.util as importlib_util
import os
import traceback
from dataclasses import asdict, dataclass, field, is_dataclass
from datetime import datetime, timezone
from functools import lru_cache
from pathlib import Path
from types import ModuleType
from typing import Any, Final, Iterable, Mapping

from flask import Flask


# -----------------------------------------------------------------------------
# Konstanten
# -----------------------------------------------------------------------------

STARTUP_SCHEMA_VERSION: Final[str] = "vplib.startup.v2"
SERVICE_NAMESPACE: Final[str] = "vectoplan_library"
STARTUP_STATE_KEY: Final[str] = "startup"

DEFAULT_SERVICE_NAME: Final[str] = "vectoplan-library"
DEFAULT_SERVICE_DISPLAY_NAME: Final[str] = "VECTOPLAN Library"

DEFAULT_HEALTH_ROUTE: Final[str] = "/health"
DEFAULT_READY_ROUTE: Final[str] = "/health/ready"

DEFAULT_VPLIB_ROUTE_PREFIX: Final[str] = "/api/v1/vplib"
DEFAULT_VPLIB_HEALTH_ROUTE: Final[str] = "/api/v1/vplib/health"
DEFAULT_VPLIB_TEST_ROUTE: Final[str] = "/api/v1/vplib/test"
DEFAULT_VPLIB_CREATE_ROUTE: Final[str] = "/api/v1/vplib/create"

DEFAULT_LIBRARY_ROUTE_PREFIX: Final[str] = "/api/v1/vplib/library"
DEFAULT_LIBRARY_HEALTH_ROUTE: Final[str] = "/api/v1/vplib/library/health"
DEFAULT_LIBRARY_SCAN_ROUTE: Final[str] = "/api/v1/vplib/library/scan"
DEFAULT_LIBRARY_BLOCKS_ROUTE: Final[str] = "/api/v1/vplib/library/blocks"
DEFAULT_LIBRARY_TREE_ROUTE: Final[str] = "/api/v1/vplib/library/tree"

TRUE_VALUES: Final[set[str]] = {"1", "true", "t", "yes", "y", "on", "enabled"}
FALSE_VALUES: Final[set[str]] = {"0", "false", "f", "no", "n", "off", "disabled"}

ENV_STARTUP_STRICT: Final[str] = "VECTOPLAN_LIBRARY_STARTUP_STRICT"
ENV_VPLIB_ROUTE_PREFIX: Final[str] = "VPLIB_ROUTE_PREFIX"
ENV_LIBRARY_ROUTE_PREFIX: Final[str] = "LIBRARY_ROUTE_PREFIX"


# -----------------------------------------------------------------------------
# Datenstrukturen
# -----------------------------------------------------------------------------

@dataclass(frozen=True, slots=True)
class PathCheckSpec:
    """Beschreibt eine Verzeichnisprüfung im Startup."""

    name: str
    config_key: str | None
    fallback_relative_paths: tuple[str, ...]
    required: bool
    description: str

    def normalized(self) -> "PathCheckSpec":
        return PathCheckSpec(
            name=_required_text(self.name, "name"),
            config_key=_optional_text(self.config_key),
            fallback_relative_paths=_normalize_text_tuple(self.fallback_relative_paths),
            required=bool(self.required),
            description=_optional_text(self.description) or "",
        )

    def to_dict(self) -> dict[str, Any]:
        return asdict(self.normalized())


@dataclass(frozen=True, slots=True)
class FileCheckSpec:
    """Beschreibt eine Dateiprüfung im Startup."""

    name: str
    fallback_relative_paths: tuple[str, ...]
    required: bool
    description: str

    def normalized(self) -> "FileCheckSpec":
        return FileCheckSpec(
            name=_required_text(self.name, "name"),
            fallback_relative_paths=_normalize_text_tuple(self.fallback_relative_paths),
            required=bool(self.required),
            description=_optional_text(self.description) or "",
        )

    def to_dict(self) -> dict[str, Any]:
        return asdict(self.normalized())


@dataclass(frozen=True, slots=True)
class ModuleCheckSpec:
    """Beschreibt eine Modulimportprüfung."""

    name: str
    module_candidates: tuple[str, ...]
    required: bool
    description: str

    def normalized(self) -> "ModuleCheckSpec":
        return ModuleCheckSpec(
            name=_required_text(self.name, "name"),
            module_candidates=_normalize_text_tuple(self.module_candidates),
            required=bool(self.required),
            description=_optional_text(self.description) or "",
        )

    def to_dict(self) -> dict[str, Any]:
        return asdict(self.normalized())


@dataclass(frozen=True, slots=True)
class RouteCheckSpec:
    """Beschreibt eine Route-Prüfung."""

    name: str
    route_path: str
    required: bool
    description: str

    def normalized(self) -> "RouteCheckSpec":
        return RouteCheckSpec(
            name=_required_text(self.name, "name"),
            route_path=_normalize_route_path(self.route_path),
            required=bool(self.required),
            description=_optional_text(self.description) or "",
        )

    def to_dict(self) -> dict[str, Any]:
        return asdict(self.normalized())


@dataclass(frozen=True, slots=True)
class StartupCheckResult:
    """Ein einzelnes Startup-Check-Ergebnis."""

    name: str
    check_type: str
    status: str
    required: bool
    ok: bool
    message: str = ""
    details: Mapping[str, Any] = field(default_factory=dict)

    def normalized(self) -> "StartupCheckResult":
        return StartupCheckResult(
            name=_required_text(self.name, "name"),
            check_type=_required_text(self.check_type, "check_type"),
            status=_required_text(self.status, "status"),
            required=bool(self.required),
            ok=bool(self.ok),
            message=_optional_text(self.message) or "",
            details=_json_safe_mapping(self.details),
        )

    def to_dict(self) -> dict[str, Any]:
        normalized = self.normalized()

        return {
            "name": normalized.name,
            "check_type": normalized.check_type,
            "status": normalized.status,
            "required": normalized.required,
            "ok": normalized.ok,
            "message": normalized.message,
            "details": dict(normalized.details),
        }


# -----------------------------------------------------------------------------
# Zeit / Logging / Primitive Hilfen
# -----------------------------------------------------------------------------

def _utc_now_iso() -> str:
    """Liefert einen UTC-Zeitstempel als ISO-String."""
    try:
        return datetime.now(timezone.utc).isoformat()
    except Exception:
        return "1970-01-01T00:00:00+00:00"


def _exception_to_dict(
    exc: BaseException | None,
    *,
    include_traceback: bool = False,
) -> dict[str, Any] | None:
    """Serialisiert eine Exception JSON-kompatibel."""
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
    """Liest einen Konfigurationswert defensiv aus der Flask-App."""
    try:
        return app.config.get(key, default)
    except Exception:
        return default


def _required_text(value: Any, field_name: str) -> str:
    """Normalisiert einen Pflichttext."""
    text = _optional_text(value)

    if not text:
        raise ValueError(f"{field_name} is required.")

    return text


def _optional_text(value: Any, default: str | None = None) -> str | None:
    """Normalisiert einen optionalen Text."""
    if value is None:
        return default

    try:
        text = str(value).strip()
    except Exception:
        return default

    return text or default


def _normalize_text_tuple(values: Iterable[Any] | Any) -> tuple[str, ...]:
    """Normalisiert Iterable zu dedupliziertem String-Tuple."""
    if values is None:
        return tuple()

    if isinstance(values, str):
        values = (values,)

    result: list[str] = []
    seen: set[str] = set()

    for value in values:
        text = _optional_text(value)

        if not text or text in seen:
            continue

        result.append(text)
        seen.add(text)

    return tuple(result)


def _safe_bool(value: Any, default: bool = False) -> bool:
    """Normalisiert booleans robust."""
    if isinstance(value, bool):
        return value

    text = _optional_text(value)

    if not text:
        return default

    lowered = text.lower()

    if lowered in TRUE_VALUES:
        return True

    if lowered in FALSE_VALUES:
        return False

    return default


def _safe_int(value: Any, default: int = 0, minimum: int | None = None, maximum: int | None = None) -> int:
    """Normalisiert Integer-Werte robust."""
    try:
        result = int(value)
    except (TypeError, ValueError):
        result = default

    if minimum is not None:
        result = max(minimum, result)

    if maximum is not None:
        result = min(maximum, result)

    return result


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
        return _json_safe_mapping(value)

    if isinstance(value, (list, tuple, set)):
        return [_json_safe(item) for item in value]

    if hasattr(value, "to_dict"):
        try:
            return _json_safe(value.to_dict())
        except Exception:
            return str(value)

    return str(value)


def _json_safe_mapping(value: Mapping[str, Any] | None) -> dict[str, Any]:
    """Normalisiert Mapping JSON-kompatibel."""
    if value is None:
        return {}

    if not isinstance(value, Mapping):
        return {"value": str(value)}

    return {
        str(key): _json_safe(child_value)
        for key, child_value in value.items()
    }


def _is_flask_app(app: object) -> bool:
    """Prüft defensiv, ob das Objekt wie eine Flask-App verwendbar ist."""
    if isinstance(app, Flask):
        return True

    required_attributes = ("extensions", "config", "logger", "url_map")

    try:
        return all(hasattr(app, attr_name) for attr_name in required_attributes)
    except Exception:
        return False


def _resolve_service_root_from_file() -> Path:
    """
    Ermittelt das Service-Root relativ zu dieser Datei.

    Erwarteter Pfad:
    services/vectoplan-library/src/bootstrap/startup.py

    parents[0] -> bootstrap
    parents[1] -> src
    parents[2] -> vectoplan-library
    """
    try:
        return Path(__file__).resolve().parents[2]
    except Exception:
        try:
            return Path(".").resolve()
        except Exception:
            return Path(".")


def _resolve_src_root_from_file() -> Path:
    """Ermittelt src-Root relativ zu dieser Datei."""
    try:
        return Path(__file__).resolve().parents[1]
    except Exception:
        return _resolve_service_root_from_file() / "src"


def _safe_path_exists(path: Path) -> bool:
    try:
        return path.exists()
    except Exception:
        return False


def _safe_is_dir(path: Path) -> bool:
    try:
        return path.is_dir()
    except Exception:
        return False


def _safe_is_file(path: Path) -> bool:
    try:
        return path.is_file()
    except Exception:
        return False


def _safe_path_to_string(path: Path | None) -> str:
    if path is None:
        return ""

    try:
        return str(path)
    except Exception:
        return ""


def _get_mapping_path(mapping: Mapping[str, Any], path: str, default: Any = None) -> Any:
    """Liest verschachtelte Mapping-Pfade defensiv."""
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
# Startup-Registry / Namespace
# -----------------------------------------------------------------------------

def _ensure_service_namespace(app: Flask) -> dict[str, Any]:
    """Stellt den Namespace app.extensions['vectoplan_library'] sicher."""
    if not _is_flask_app(app):
        raise TypeError("Startup hooks expect a Flask app or compatible object.")

    try:
        if not isinstance(app.extensions, dict):
            raise TypeError("app.extensions is not a dictionary.")
    except Exception as exc:
        raise RuntimeError("The Flask app does not provide a usable extensions container.") from exc

    try:
        namespace = app.extensions.setdefault(SERVICE_NAMESPACE, {})
    except Exception as exc:
        raise RuntimeError("The service namespace could not be created in app.extensions.") from exc

    if not isinstance(namespace, dict):
        raise RuntimeError(f"app.extensions[{SERVICE_NAMESPACE!r}] is not a dictionary.")

    return namespace


def _new_startup_state() -> dict[str, Any]:
    """Erzeugt frischen Startup-State."""
    return {
        "schema_version": STARTUP_SCHEMA_VERSION,
        "service_name": DEFAULT_SERVICE_NAME,
        "status": "idle",
        "started_at": None,
        "completed_at": None,
        "run_count": 0,
        "strict_mode": False,
        "warnings": [],
        "errors": [],
        "checks": {
            "paths": [],
            "files": [],
            "modules": [],
            "routes": [],
            "vplib_settings": [],
            "library_settings": [],
            "library_health": [],
        },
        "metadata": {},
        "route_summary": {
            "count": 0,
            "required_route_count": 0,
            "missing_required_routes": [],
            "vplib_route_prefix": DEFAULT_VPLIB_ROUTE_PREFIX,
            "library_route_prefix": DEFAULT_LIBRARY_ROUTE_PREFIX,
        },
    }


def _ensure_startup_state(app: Flask) -> dict[str, Any]:
    """Stellt den Startup-Zustandscontainer sicher."""
    namespace = _ensure_service_namespace(app)

    startup_state = namespace.get(STARTUP_STATE_KEY)

    if not isinstance(startup_state, dict):
        startup_state = _new_startup_state()
        namespace[STARTUP_STATE_KEY] = startup_state

    startup_state.setdefault("schema_version", STARTUP_SCHEMA_VERSION)
    startup_state.setdefault("service_name", DEFAULT_SERVICE_NAME)
    startup_state.setdefault("status", "idle")
    startup_state.setdefault("started_at", None)
    startup_state.setdefault("completed_at", None)
    startup_state.setdefault("run_count", 0)
    startup_state.setdefault("strict_mode", False)
    startup_state.setdefault("warnings", [])
    startup_state.setdefault("errors", [])
    startup_state.setdefault("checks", {})
    startup_state.setdefault("metadata", {})
    startup_state.setdefault("route_summary", {})

    if not isinstance(startup_state["warnings"], list):
        startup_state["warnings"] = []

    if not isinstance(startup_state["errors"], list):
        startup_state["errors"] = []

    if not isinstance(startup_state["checks"], dict):
        startup_state["checks"] = {}

    for key in ("paths", "files", "modules", "routes", "vplib_settings", "library_settings", "library_health"):
        startup_state["checks"].setdefault(key, [])

        if not isinstance(startup_state["checks"][key], list):
            startup_state["checks"][key] = []

    if not isinstance(startup_state["metadata"], dict):
        startup_state["metadata"] = {}

    if not isinstance(startup_state["route_summary"], dict):
        startup_state["route_summary"] = {}

    startup_state["route_summary"].setdefault("count", 0)
    startup_state["route_summary"].setdefault("required_route_count", 0)
    startup_state["route_summary"].setdefault("missing_required_routes", [])
    startup_state["route_summary"].setdefault("vplib_route_prefix", DEFAULT_VPLIB_ROUTE_PREFIX)
    startup_state["route_summary"].setdefault("library_route_prefix", DEFAULT_LIBRARY_ROUTE_PREFIX)

    return startup_state


def _append_warning(app: Flask, message: str, *, details: Mapping[str, Any] | None = None) -> None:
    """Hängt eine Startup-Warnung an."""
    state = _ensure_startup_state(app)

    try:
        state["warnings"].append(
            {
                "message": message,
                "details": _json_safe_mapping(details),
                "timestamp": _utc_now_iso(),
            }
        )
    except Exception:
        pass

    _safe_log_warning(app, message)


def _append_error(app: Flask, message: str, *, details: Mapping[str, Any] | None = None) -> None:
    """Hängt einen Startup-Fehler an."""
    state = _ensure_startup_state(app)

    try:
        state["errors"].append(
            {
                "message": message,
                "details": _json_safe_mapping(details),
                "timestamp": _utc_now_iso(),
            }
        )
    except Exception:
        pass

    _safe_log_warning(app, message)


def _append_check_result(app: Flask, category: str, result: StartupCheckResult) -> None:
    """Hängt ein Check-Ergebnis an den Startup-State an."""
    state = _ensure_startup_state(app)
    state["checks"].setdefault(category, [])

    try:
        state["checks"][category].append(result.normalized().to_dict())
    except Exception:
        pass


# -----------------------------------------------------------------------------
# Strict Mode
# -----------------------------------------------------------------------------

def _is_strict_startup_enabled(app: Flask) -> bool:
    """Ermittelt, ob Startup-Prüfungen streng behandelt werden sollen."""
    for config_key in (
        "VECTOPLAN_LIBRARY_STARTUP_STRICT",
        "LIBRARY_STARTUP_STRICT",
        "STARTUP_STRICT",
    ):
        config_value = _safe_get_config(app, config_key, None)

        if config_value is not None:
            return _safe_bool(config_value, default=False)

    try:
        env_value = os.getenv(ENV_STARTUP_STRICT)
    except Exception:
        env_value = None

    return _safe_bool(env_value, default=False)


def _maybe_raise_in_strict_mode(
    app: Flask,
    message: str,
    *,
    details: Mapping[str, Any] | None = None,
) -> None:
    """Hebt in Strict Mode harte Fehler an, ansonsten nur Warnung."""
    if _is_strict_startup_enabled(app):
        raise RuntimeError(message)

    _append_warning(app, message, details=details)


# -----------------------------------------------------------------------------
# Check-Spezifikationen
# -----------------------------------------------------------------------------

@lru_cache(maxsize=1)
def get_default_path_check_specs() -> tuple[PathCheckSpec, ...]:
    """Liefert die Standard-Verzeichnisprüfungen gecacht zurück."""
    return (
        PathCheckSpec(
            name="service_root",
            config_key="SERVICE_ROOT",
            fallback_relative_paths=(".",),
            required=True,
            description="Service root directory.",
        ).normalized(),
        PathCheckSpec(
            name="src_root",
            config_key="SRC_ROOT",
            fallback_relative_paths=("src",),
            required=True,
            description="Python src root directory.",
        ).normalized(),
        PathCheckSpec(
            name="routes_root",
            config_key="ROUTES_ROOT",
            fallback_relative_paths=("src/routes", "routes"),
            required=True,
            description="HTTP route modules.",
        ).normalized(),
        PathCheckSpec(
            name="services_root",
            config_key="SERVICES_ROOT",
            fallback_relative_paths=("src/services", "services"),
            required=True,
            description="Route service and application services.",
        ).normalized(),
        PathCheckSpec(
            name="config_root",
            config_key="CONFIG_ROOT",
            fallback_relative_paths=("src/config",),
            required=True,
            description="Settings package.",
        ).normalized(),
        PathCheckSpec(
            name="vplib_root",
            config_key="VPLIB_ROOT",
            fallback_relative_paths=("src/vplib",),
            required=True,
            description="VPLIB core package.",
        ).normalized(),
        PathCheckSpec(
            name="library_root",
            config_key="LIBRARY_ROOT",
            fallback_relative_paths=("src/library",),
            required=True,
            description="Creative Library backend package.",
        ).normalized(),
        PathCheckSpec(
            name="library_source_root",
            config_key="LIBRARY_SOURCE_ROOT",
            fallback_relative_paths=("src/library/source",),
            required=False,
            description="Creative Library source package input root. May be empty or missing in early development.",
        ).normalized(),
        PathCheckSpec(
            name="library_domain_root",
            config_key=None,
            fallback_relative_paths=("src/library/domain",),
            required=True,
            description="Creative Library domain models.",
        ).normalized(),
        PathCheckSpec(
            name="library_scanner_root",
            config_key=None,
            fallback_relative_paths=("src/library/scanner",),
            required=True,
            description="Creative Library scanner modules.",
        ).normalized(),
        PathCheckSpec(
            name="library_validation_root",
            config_key=None,
            fallback_relative_paths=("src/library/validation",),
            required=True,
            description="Creative Library validation modules.",
        ).normalized(),
        PathCheckSpec(
            name="library_read_models_root",
            config_key=None,
            fallback_relative_paths=("src/library/read_models",),
            required=True,
            description="Creative Library read-model builders.",
        ).normalized(),
        PathCheckSpec(
            name="library_services_root",
            config_key=None,
            fallback_relative_paths=("src/library/services",),
            required=True,
            description="Creative Library backend services.",
        ).normalized(),
        PathCheckSpec(
            name="legacy_vplib_source_root",
            config_key="VPLIB_SOURCE_ROOT",
            fallback_relative_paths=("sources",),
            required=False,
            description="Legacy/prepared VPLIB source packages.",
        ).normalized(),
        PathCheckSpec(
            name="creative_library_root",
            config_key="LIBRARY_CREATIVE_ROOT",
            fallback_relative_paths=("creative_library",),
            required=False,
            description="Future checked Creative Library catalog root.",
        ).normalized(),
        PathCheckSpec(
            name="generated_root",
            config_key="VPLIB_GENERATED_ROOT",
            fallback_relative_paths=("generated/vplib",),
            required=False,
            description="Generated VPLIB package output root.",
        ).normalized(),
    )


@lru_cache(maxsize=1)
def get_default_file_check_specs() -> tuple[FileCheckSpec, ...]:
    """Liefert die Standard-Dateiprüfungen gecacht zurück."""
    return (
        FileCheckSpec(
            name="app_factory",
            fallback_relative_paths=("app.py",),
            required=True,
            description="Flask app factory.",
        ).normalized(),
        FileCheckSpec(
            name="wsgi_entrypoint",
            fallback_relative_paths=("wsgi.py",),
            required=True,
            description="WSGI entrypoint.",
        ).normalized(),
        FileCheckSpec(
            name="service_config",
            fallback_relative_paths=("config.py",),
            required=True,
            description="Root service configuration.",
        ).normalized(),
        FileCheckSpec(
            name="route_registry",
            fallback_relative_paths=("src/routes/__init__.py", "routes/__init__.py"),
            required=True,
            description="Central Blueprint registration.",
        ).normalized(),
        FileCheckSpec(
            name="vplib_routes",
            fallback_relative_paths=("src/routes/vplib_routes.py", "routes/vplib_routes.py"),
            required=True,
            description="VPLIB HTTP routes.",
        ).normalized(),
        FileCheckSpec(
            name="library_routes",
            fallback_relative_paths=("src/routes/library_routes.py", "routes/library_routes.py"),
            required=True,
            description="Creative Library HTTP routes.",
        ).normalized(),
        FileCheckSpec(
            name="vplib_route_service",
            fallback_relative_paths=("src/services/vplib_route_service.py", "services/vplib_route_service.py"),
            required=True,
            description="VPLIB route service logic.",
        ).normalized(),
        FileCheckSpec(
            name="library_route_service",
            fallback_relative_paths=("src/services/library_route_service.py", "services/library_route_service.py"),
            required=True,
            description="Creative Library route service logic.",
        ).normalized(),
        FileCheckSpec(
            name="vplib_settings",
            fallback_relative_paths=("src/config/vplib_settings.py", "config/vplib_settings.py"),
            required=True,
            description="VPLIB route and runtime settings.",
        ).normalized(),
        FileCheckSpec(
            name="library_settings",
            fallback_relative_paths=("src/config/library_settings.py", "config/library_settings.py"),
            required=True,
            description="Creative Library route, source, scan and read settings.",
        ).normalized(),
        FileCheckSpec(
            name="vplib_core",
            fallback_relative_paths=("src/vplib/__init__.py",),
            required=True,
            description="VPLIB core package API.",
        ).normalized(),
        FileCheckSpec(
            name="library_package",
            fallback_relative_paths=("src/library/__init__.py",),
            required=True,
            description="Creative Library package API.",
        ).normalized(),
        FileCheckSpec(
            name="library_domain",
            fallback_relative_paths=("src/library/domain/__init__.py",),
            required=True,
            description="Creative Library domain package.",
        ).normalized(),
        FileCheckSpec(
            name="library_scanner",
            fallback_relative_paths=("src/library/scanner/__init__.py",),
            required=True,
            description="Creative Library scanner package.",
        ).normalized(),
        FileCheckSpec(
            name="library_validation",
            fallback_relative_paths=("src/library/validation/__init__.py",),
            required=True,
            description="Creative Library validation package.",
        ).normalized(),
        FileCheckSpec(
            name="library_read_models",
            fallback_relative_paths=("src/library/read_models/__init__.py",),
            required=True,
            description="Creative Library read-model package.",
        ).normalized(),
        FileCheckSpec(
            name="library_services",
            fallback_relative_paths=("src/library/services/__init__.py",),
            required=True,
            description="Creative Library services package.",
        ).normalized(),
        FileCheckSpec(
            name="dockerfile",
            fallback_relative_paths=("Dockerfile",),
            required=False,
            description="Container build file.",
        ).normalized(),
        FileCheckSpec(
            name="entrypoint",
            fallback_relative_paths=("entrypoint.sh",),
            required=False,
            description="Container entrypoint script.",
        ).normalized(),
    )


@lru_cache(maxsize=1)
def get_default_module_check_specs() -> tuple[ModuleCheckSpec, ...]:
    """Liefert die Standard-Modulprüfungen gecacht zurück."""
    return (
        ModuleCheckSpec(
            name="app",
            module_candidates=("app",),
            required=True,
            description="Root app module.",
        ).normalized(),
        ModuleCheckSpec(
            name="routes",
            module_candidates=("routes", "src.routes"),
            required=True,
            description="Routes package.",
        ).normalized(),
        ModuleCheckSpec(
            name="vplib_routes",
            module_candidates=("routes.vplib_routes", "src.routes.vplib_routes"),
            required=True,
            description="VPLIB route module.",
        ).normalized(),
        ModuleCheckSpec(
            name="library_routes",
            module_candidates=("routes.library_routes", "src.routes.library_routes"),
            required=True,
            description="Creative Library route module.",
        ).normalized(),
        ModuleCheckSpec(
            name="vplib_route_service",
            module_candidates=("services.vplib_route_service", "src.services.vplib_route_service"),
            required=True,
            description="VPLIB route service module.",
        ).normalized(),
        ModuleCheckSpec(
            name="library_route_service",
            module_candidates=("services.library_route_service", "src.services.library_route_service"),
            required=True,
            description="Creative Library route service module.",
        ).normalized(),
        ModuleCheckSpec(
            name="vplib",
            module_candidates=("vplib", "src.vplib"),
            required=True,
            description="VPLIB core package.",
        ).normalized(),
        ModuleCheckSpec(
            name="vplib_validators",
            module_candidates=("vplib.validators", "src.vplib.validators"),
            required=True,
            description="VPLIB validators package.",
        ).normalized(),
        ModuleCheckSpec(
            name="vplib_creators",
            module_candidates=("vplib.creators", "src.vplib.creators"),
            required=True,
            description="VPLIB creators package.",
        ).normalized(),
        ModuleCheckSpec(
            name="vplib_sources",
            module_candidates=("vplib.sources", "src.vplib.sources"),
            required=True,
            description="VPLIB sources package.",
        ).normalized(),
        ModuleCheckSpec(
            name="library",
            module_candidates=("library", "src.library"),
            required=True,
            description="Creative Library package.",
        ).normalized(),
        ModuleCheckSpec(
            name="library_domain",
            module_candidates=("library.domain", "src.library.domain"),
            required=True,
            description="Creative Library domain models.",
        ).normalized(),
        ModuleCheckSpec(
            name="library_scanner",
            module_candidates=("library.scanner", "src.library.scanner"),
            required=True,
            description="Creative Library scanner package.",
        ).normalized(),
        ModuleCheckSpec(
            name="library_validation",
            module_candidates=("library.validation", "src.library.validation"),
            required=True,
            description="Creative Library validation package.",
        ).normalized(),
        ModuleCheckSpec(
            name="library_read_models",
            module_candidates=("library.read_models", "src.library.read_models"),
            required=True,
            description="Creative Library read-model package.",
        ).normalized(),
        ModuleCheckSpec(
            name="library_services",
            module_candidates=("library.services", "src.library.services"),
            required=True,
            description="Creative Library service package.",
        ).normalized(),
        ModuleCheckSpec(
            name="library_scan_service",
            module_candidates=("library.services.library_scan_service", "src.library.services.library_scan_service"),
            required=True,
            description="Creative Library scan service.",
        ).normalized(),
        ModuleCheckSpec(
            name="library_block_service",
            module_candidates=("library.services.library_block_service", "src.library.services.library_block_service"),
            required=True,
            description="Creative Library block service.",
        ).normalized(),
    )


def get_default_route_check_specs(app: Flask | None = None) -> tuple[RouteCheckSpec, ...]:
    """Liefert die Standard-Routeprüfungen zurück."""
    vplib_route_prefix = DEFAULT_VPLIB_ROUTE_PREFIX
    library_route_prefix = DEFAULT_LIBRARY_ROUTE_PREFIX

    if app is not None:
        vplib_route_prefix = _resolve_vplib_route_prefix(app)
        library_route_prefix = _resolve_library_route_prefix(app)

    return (
        RouteCheckSpec(
            name="health",
            route_path=DEFAULT_HEALTH_ROUTE,
            required=True,
            description="Built-in service health route.",
        ).normalized(),
        RouteCheckSpec(
            name="ready",
            route_path=DEFAULT_READY_ROUTE,
            required=True,
            description="Built-in service readiness route.",
        ).normalized(),
        RouteCheckSpec(
            name="vplib_health",
            route_path=f"{vplib_route_prefix}/health",
            required=True,
            description="VPLIB health route.",
        ).normalized(),
        RouteCheckSpec(
            name="vplib_test",
            route_path=f"{vplib_route_prefix}/test",
            required=True,
            description="VPLIB self-test route.",
        ).normalized(),
        RouteCheckSpec(
            name="vplib_create",
            route_path=f"{vplib_route_prefix}/create",
            required=True,
            description="VPLIB create route.",
        ).normalized(),
        RouteCheckSpec(
            name="vplib_create_dry_run",
            route_path=f"{vplib_route_prefix}/create/dry-run",
            required=True,
            description="VPLIB create dry-run route.",
        ).normalized(),
        RouteCheckSpec(
            name="library_health",
            route_path=f"{library_route_prefix}/health",
            required=True,
            description="Creative Library health route.",
        ).normalized(),
        RouteCheckSpec(
            name="library_scan",
            route_path=f"{library_route_prefix}/scan",
            required=True,
            description="Creative Library source scan route.",
        ).normalized(),
        RouteCheckSpec(
            name="library_blocks",
            route_path=f"{library_route_prefix}/blocks",
            required=True,
            description="Creative Library block list route.",
        ).normalized(),
        RouteCheckSpec(
            name="library_tree",
            route_path=f"{library_route_prefix}/tree",
            required=True,
            description="Creative Library tree route.",
        ).normalized(),
    )


def get_default_path_check_spec_data() -> list[dict[str, Any]]:
    """Serialisierbare Darstellung der PathCheck-Spezifikationen."""
    return [spec.to_dict() for spec in get_default_path_check_specs()]


def get_default_file_check_spec_data() -> list[dict[str, Any]]:
    """Serialisierbare Darstellung der FileCheck-Spezifikationen."""
    return [spec.to_dict() for spec in get_default_file_check_specs()]


def get_default_module_check_spec_data() -> list[dict[str, Any]]:
    """Serialisierbare Darstellung der ModuleCheck-Spezifikationen."""
    return [spec.to_dict() for spec in get_default_module_check_specs()]


def get_default_route_check_spec_data(app: Flask | None = None) -> list[dict[str, Any]]:
    """Serialisierbare Darstellung der RouteCheck-Spezifikationen."""
    return [spec.to_dict() for spec in get_default_route_check_specs(app)]


# -----------------------------------------------------------------------------
# Pfad- und Datei-Checks
# -----------------------------------------------------------------------------

def _resolve_configured_path(app: Flask, config_key: str | None, fallback_relative_paths: Iterable[str]) -> Path:
    """Löst einen Pfad aus der Konfiguration oder aus Fallbacks auf."""
    service_root = _resolve_service_root(app)

    if config_key:
        configured_value = _safe_get_config(app, config_key, None)
        configured_text = _optional_text(configured_value)

        if configured_text:
            try:
                path = Path(configured_text)
                return path if path.is_absolute() else service_root / path
            except Exception:
                pass

    for relative_path in fallback_relative_paths:
        try:
            candidate = service_root / relative_path

            if candidate.exists():
                return candidate
        except Exception:
            continue

    fallback = next(iter(fallback_relative_paths), ".")
    return service_root / fallback


def _resolve_service_root(app: Flask) -> Path:
    """Löst Service-Root aus Config oder Datei ab."""
    configured = _safe_get_config(app, "SERVICE_ROOT", None)
    text = _optional_text(configured)

    if text:
        try:
            return Path(text)
        except Exception:
            pass

    return _resolve_service_root_from_file()


def _run_path_checks(app: Flask) -> None:
    """Führt Verzeichnisprüfungen aus."""
    for spec in get_default_path_check_specs():
        resolved_path = _resolve_configured_path(app, spec.config_key, spec.fallback_relative_paths)
        exists = _safe_path_exists(resolved_path)
        is_dir = _safe_is_dir(resolved_path)
        ok = bool(exists and is_dir)

        result = StartupCheckResult(
            name=spec.name,
            check_type="path",
            status="ok" if ok else ("missing" if not exists else "invalid_type"),
            required=spec.required,
            ok=ok or not spec.required,
            message="" if ok else f"Directory check failed for {spec.name}.",
            details={
                "config_key": spec.config_key,
                "description": spec.description,
                "path": _safe_path_to_string(resolved_path),
                "exists": exists,
                "is_dir": is_dir,
                "fallback_relative_paths": list(spec.fallback_relative_paths),
            },
        ).normalized()

        _append_check_result(app, "paths", result)

        if spec.required and not ok:
            _maybe_raise_in_strict_mode(app, result.message, details=result.details)
        elif not spec.required and not ok:
            _append_warning(app, result.message, details=result.details)


def _run_file_checks(app: Flask) -> None:
    """Führt Dateiprüfungen aus."""
    service_root = _resolve_service_root(app)

    for spec in get_default_file_check_specs():
        found_path = None

        for relative_path in spec.fallback_relative_paths:
            candidate = service_root / relative_path

            if _safe_is_file(candidate):
                found_path = candidate
                break

        checked_paths = [str(service_root / item) for item in spec.fallback_relative_paths]
        ok = found_path is not None

        result = StartupCheckResult(
            name=spec.name,
            check_type="file",
            status="ok" if ok else "missing",
            required=spec.required,
            ok=ok or not spec.required,
            message="" if ok else f"File check failed for {spec.name}.",
            details={
                "description": spec.description,
                "found_path": _safe_path_to_string(found_path),
                "checked_paths": checked_paths,
            },
        ).normalized()

        _append_check_result(app, "files", result)

        if spec.required and not ok:
            _maybe_raise_in_strict_mode(app, result.message, details=result.details)
        elif not spec.required and not ok:
            _append_warning(app, result.message, details=result.details)


# -----------------------------------------------------------------------------
# Modul-Checks
# -----------------------------------------------------------------------------

def _try_import_first(module_candidates: Iterable[str]) -> tuple[ModuleType | None, str | None, tuple[str, ...]]:
    """Importiert erstes verfügbares Modul aus Kandidaten."""
    errors: list[str] = []

    for module_name in module_candidates:
        try:
            return importlib.import_module(module_name), module_name, tuple(errors)
        except Exception as exc:
            errors.append(f"{module_name}: {exc}")

    return None, None, tuple(errors)


def _run_module_checks(app: Flask) -> None:
    """Führt Importprüfungen aus."""
    for spec in get_default_module_check_specs():
        module, module_name, errors = _try_import_first(spec.module_candidates)
        ok = module is not None

        health_payload = None

        if module is not None:
            health_payload = _try_get_module_health(module)

        result = StartupCheckResult(
            name=spec.name,
            check_type="module",
            status="ok" if ok else "missing",
            required=spec.required,
            ok=ok or not spec.required,
            message="" if ok else f"Module check failed for {spec.name}.",
            details={
                "description": spec.description,
                "resolved_module": module_name,
                "module_candidates": list(spec.module_candidates),
                "errors": list(errors),
                "health": _json_safe(health_payload),
            },
        ).normalized()

        _append_check_result(app, "modules", result)

        if spec.required and not ok:
            _maybe_raise_in_strict_mode(app, result.message, details=result.details)
        elif not spec.required and not ok:
            _append_warning(app, result.message, details=result.details)


def _try_get_module_health(module: ModuleType) -> dict[str, Any] | None:
    """Ruft eine bekannte Health-Funktion eines Moduls defensiv auf."""
    health_function_names = (
        "get_library_health",
        "get_domain_health",
        "get_scanner_health",
        "get_validation_health",
        "get_read_models_health",
        "get_services_health",
        "get_library_scan_service_health",
        "get_library_block_service_health",
        "get_library_routes_health",
        "get_vplib_health",
        "get_defaults_health",
        "get_validators_health",
        "get_creators_health",
        "get_sources_health",
    )

    for function_name in health_function_names:
        try:
            function = getattr(module, function_name, None)

            if not callable(function):
                continue

            return _json_safe(function())
        except TypeError:
            try:
                return _json_safe(function(include_subhealth=True))
            except Exception as exc:
                return {
                    "ok": False,
                    "healthy": False,
                    "function": function_name,
                    "error": _exception_to_dict(exc),
                }
        except Exception as exc:
            return {
                "ok": False,
                "healthy": False,
                "function": function_name,
                "error": _exception_to_dict(exc),
            }

    return None


# -----------------------------------------------------------------------------
# Route-Checks
# -----------------------------------------------------------------------------

def _collect_route_rules(app: Flask) -> list[str]:
    """Sammelt alle Route-Regeln der App defensiv."""
    try:
        return sorted(str(rule) for rule in app.url_map.iter_rules())
    except Exception:
        return []


def _normalize_route_path(path: Any) -> str:
    """Normalisiert Route-Pfad."""
    text = _optional_text(path, DEFAULT_VPLIB_ROUTE_PREFIX) or DEFAULT_VPLIB_ROUTE_PREFIX

    if not text.startswith("/"):
        text = f"/{text}"

    return text.rstrip("/") or "/"


def _resolve_vplib_route_prefix(app: Flask) -> str:
    """Löst VPLIB-Route-Prefix aus ENV, Config oder Default."""
    env_value = _optional_text(os.getenv(ENV_VPLIB_ROUTE_PREFIX))

    if env_value:
        return _normalize_route_path(env_value)

    for config_key in ("VPLIB_ROUTE_PREFIX", "VECTOPLAN_LIBRARY_VPLIB_ROUTE_PREFIX"):
        config_value = _optional_text(_safe_get_config(app, config_key, None))

        if config_value:
            return _normalize_route_path(config_value)

    return DEFAULT_VPLIB_ROUTE_PREFIX


def _resolve_library_route_prefix(app: Flask) -> str:
    """Löst Creative-Library-Route-Prefix aus ENV, Config, app.extensions oder Default."""
    env_value = _optional_text(os.getenv(ENV_LIBRARY_ROUTE_PREFIX))

    if env_value:
        return _normalize_route_path(env_value)

    for config_key in (
        "LIBRARY_ROUTE_PREFIX",
        "VPLIB_LIBRARY_ROUTE_PREFIX",
        "VECTOPLAN_LIBRARY_ROUTE_PREFIX",
    ):
        config_value = _optional_text(_safe_get_config(app, config_key, None))

        if config_value:
            return _normalize_route_path(config_value)

    try:
        namespace = _ensure_service_namespace(app)
        library_settings = namespace.get("library_settings")

        if isinstance(library_settings, Mapping):
            route_prefix = _get_mapping_path(library_settings, "route_plan.route_prefix")

            if route_prefix:
                return _normalize_route_path(route_prefix)

    except Exception:
        pass

    return DEFAULT_LIBRARY_ROUTE_PREFIX


def _run_route_checks(app: Flask) -> None:
    """Prüft vorhandene Routen."""
    state = _ensure_startup_state(app)
    route_rules = set(_collect_route_rules(app))
    specs = get_default_route_check_specs(app)

    missing_required_routes: list[str] = []

    for spec in specs:
        exists = spec.route_path in route_rules
        ok = bool(exists)

        result = StartupCheckResult(
            name=spec.name,
            check_type="route",
            status="ok" if ok else "missing",
            required=spec.required,
            ok=ok or not spec.required,
            message="" if ok else f"Route check failed for {spec.name}: {spec.route_path}",
            details={
                "description": spec.description,
                "route_path": spec.route_path,
                "exists": exists,
            },
        ).normalized()

        _append_check_result(app, "routes", result)

        if spec.required and not ok:
            missing_required_routes.append(spec.route_path)
            _maybe_raise_in_strict_mode(app, result.message, details=result.details)
        elif not spec.required and not ok:
            _append_warning(app, result.message, details=result.details)

    state["route_summary"] = {
        "count": len(route_rules),
        "required_route_count": sum(1 for item in specs if item.required),
        "missing_required_routes": missing_required_routes,
        "vplib_route_prefix": _resolve_vplib_route_prefix(app),
        "library_route_prefix": _resolve_library_route_prefix(app),
        "routes": sorted(route_rules),
    }


# -----------------------------------------------------------------------------
# VPLIB Settings Check
# -----------------------------------------------------------------------------

@lru_cache(maxsize=1)
def _load_vplib_settings_module() -> ModuleType:
    """Lädt VPLIB-Settings robust."""
    settings_path = _resolve_src_root_from_file() / "config" / "vplib_settings.py"

    if settings_path.is_file():
        spec = importlib_util.spec_from_file_location("_vectoplan_library_startup_vplib_settings", settings_path)

        if spec is not None and spec.loader is not None:
            module = importlib_util.module_from_spec(spec)
            spec.loader.exec_module(module)
            return module

    for module_name in ("src.config.vplib_settings", "config.vplib_settings"):
        try:
            return importlib.import_module(module_name)
        except Exception:
            continue

    raise RuntimeError("Could not load VPLIB settings module.")


def _run_vplib_settings_check(app: Flask) -> None:
    """Prüft VPLIB-Settings-Ladefähigkeit."""
    try:
        module = _load_vplib_settings_module()
        getter = getattr(module, "get_vplib_settings")
        settings = getter()
        settings = settings.normalized() if hasattr(settings, "normalized") else settings
        payload = settings.to_dict() if hasattr(settings, "to_dict") else {"settings": str(settings)}

        result = StartupCheckResult(
            name="vplib_settings",
            check_type="vplib_settings",
            status="ok",
            required=True,
            ok=True,
            message="",
            details={
                "settings": payload,
                "module": getattr(module, "__name__", "unknown"),
            },
        ).normalized()

    except Exception as exc:
        result = StartupCheckResult(
            name="vplib_settings",
            check_type="vplib_settings",
            status="failed",
            required=True,
            ok=False,
            message=f"VPLIB settings check failed: {exc}",
            details={
                "error": str(exc),
                "exception": _exception_to_dict(exc),
            },
        ).normalized()

    _append_check_result(app, "vplib_settings", result)

    if result.required and not result.ok:
        _maybe_raise_in_strict_mode(app, result.message, details=result.details)


# -----------------------------------------------------------------------------
# Library Settings / Health Checks
# -----------------------------------------------------------------------------

@lru_cache(maxsize=1)
def _load_library_settings_module() -> ModuleType:
    """Lädt Creative-Library-Settings robust."""
    settings_path = _resolve_src_root_from_file() / "config" / "library_settings.py"

    if settings_path.is_file():
        spec = importlib_util.spec_from_file_location("_vectoplan_library_startup_library_settings", settings_path)

        if spec is not None and spec.loader is not None:
            module = importlib_util.module_from_spec(spec)
            spec.loader.exec_module(module)
            return module

    for module_name in ("src.config.library_settings", "config.library_settings"):
        try:
            return importlib.import_module(module_name)
        except Exception:
            continue

    raise RuntimeError("Could not load Library settings module.")


def _run_library_settings_check(app: Flask) -> None:
    """Prüft Creative-Library-Settings-Ladefähigkeit."""
    try:
        module = _load_library_settings_module()
        getter = getattr(module, "get_library_settings")

        if not callable(getter):
            raise RuntimeError("library_settings does not export get_library_settings().")

        settings = getter()
        payload = settings.to_dict() if hasattr(settings, "to_dict") else {"settings": str(settings)}

        health_payload = None
        health_function = getattr(module, "get_library_settings_health", None)

        if callable(health_function):
            health_payload = health_function()

        result = StartupCheckResult(
            name="library_settings",
            check_type="library_settings",
            status="ok",
            required=True,
            ok=True,
            message="",
            details={
                "settings": payload,
                "health": _json_safe(health_payload),
                "module": getattr(module, "__name__", "unknown"),
            },
        ).normalized()

    except Exception as exc:
        result = StartupCheckResult(
            name="library_settings",
            check_type="library_settings",
            status="failed",
            required=True,
            ok=False,
            message=f"Library settings check failed: {exc}",
            details={
                "error": str(exc),
                "exception": _exception_to_dict(exc),
            },
        ).normalized()

    _append_check_result(app, "library_settings", result)

    if result.required and not result.ok:
        _maybe_raise_in_strict_mode(app, result.message, details=result.details)


def _run_library_health_check(app: Flask) -> None:
    """Prüft Creative-Library-Package-Health ohne Scan."""
    try:
        module, module_name, errors = _try_import_first(("library", "src.library"))

        if module is None:
            raise RuntimeError(f"Could not import library package: {errors}")

        health_function = getattr(module, "get_library_health", None)

        if not callable(health_function):
            raise RuntimeError(f"{module_name} does not export get_library_health().")

        health = health_function(strict=False)
        healthy = _safe_bool(health.get("healthy") if isinstance(health, Mapping) else True, default=True)

        result = StartupCheckResult(
            name="library_health",
            check_type="library_health",
            status="ok" if healthy else "warning",
            required=True,
            ok=True,
            message="" if healthy else "Library package health returned warnings.",
            details={
                "health": _json_safe(health),
                "module": module_name,
            },
        ).normalized()

    except Exception as exc:
        result = StartupCheckResult(
            name="library_health",
            check_type="library_health",
            status="failed",
            required=True,
            ok=False,
            message=f"Library health check failed: {exc}",
            details={
                "error": str(exc),
                "exception": _exception_to_dict(exc),
            },
        ).normalized()

    _append_check_result(app, "library_health", result)

    if result.required and not result.ok:
        _maybe_raise_in_strict_mode(app, result.message, details=result.details)


# -----------------------------------------------------------------------------
# Metadaten-Erfassung
# -----------------------------------------------------------------------------

def _collect_startup_metadata(app: Flask) -> None:
    """Erfasst zentrale App- und Startup-Metadaten."""
    state = _ensure_startup_state(app)
    metadata = state["metadata"]

    template_folder = None
    static_folder = None
    static_url_path = None
    instance_path = None

    try:
        template_folder = app.template_folder
    except Exception:
        pass

    try:
        static_folder = app.static_folder
    except Exception:
        pass

    try:
        static_url_path = app.static_url_path
    except Exception:
        pass

    try:
        instance_path = app.instance_path
    except Exception:
        pass

    metadata.update(
        {
            "schema_version": STARTUP_SCHEMA_VERSION,
            "app_name": _optional_text(_safe_get_config(app, "APP_NAME", DEFAULT_SERVICE_NAME), DEFAULT_SERVICE_NAME),
            "app_display_name": _optional_text(
                _safe_get_config(app, "APP_DISPLAY_NAME", DEFAULT_SERVICE_DISPLAY_NAME),
                DEFAULT_SERVICE_DISPLAY_NAME,
            ),
            "debug": _safe_bool(_safe_get_config(app, "DEBUG", False), False),
            "testing": _safe_bool(_safe_get_config(app, "TESTING", False), False),
            "strict_mode": _is_strict_startup_enabled(app),
            "service_root": _safe_path_to_string(_resolve_service_root(app)),
            "src_root": _safe_path_to_string(_resolve_src_root_from_file()),
            "template_folder": _optional_text(template_folder, ""),
            "static_folder": _optional_text(static_folder, ""),
            "static_url_path": _optional_text(static_url_path, ""),
            "instance_path": _optional_text(instance_path, ""),
            "vplib_route_prefix": _resolve_vplib_route_prefix(app),
            "library_route_prefix": _resolve_library_route_prefix(app),
            "collected_at": _utc_now_iso(),
        }
    )


# -----------------------------------------------------------------------------
# Extension-Integration
# -----------------------------------------------------------------------------

def _import_extensions_module() -> ModuleType | None:
    """Importiert optionales extensions-Modul defensiv."""
    for module_name in ("extensions", "src.extensions"):
        try:
            return importlib.import_module(module_name)
        except Exception:
            continue

    return None


def _call_optional_extension_function(module: ModuleType | None, function_name: str, *args: Any, **kwargs: Any) -> Any:
    """Ruft optionale Extension-Funktion defensiv auf."""
    if module is None:
        return None

    function = getattr(module, function_name, None)

    if not callable(function):
        return None

    try:
        return function(*args, **kwargs)
    except Exception:
        return None


def _initialize_extension_registry(app: Flask) -> ModuleType | None:
    """
    Initialisiert optionale Extension-Struktur und registriert Startup-Hook.

    Diese Integration ist absichtlich optional.
    """
    module = _import_extensions_module()

    _call_optional_extension_function(module, "init_extensions", app)
    _call_optional_extension_function(
        module,
        "register_extension",
        app,
        "startup",
        category="internal",
        description="Startup hooks, structure checks and VPLIB/Library diagnostics.",
        required=True,
    )

    return module


def _mark_startup_initialized(app: Flask, extensions_module: ModuleType | None) -> None:
    """Markiert Startup optional in Extension-Registry als initialisiert."""
    state = _ensure_startup_state(app)

    _call_optional_extension_function(
        extensions_module,
        "mark_extension_initialized",
        app,
        "startup",
        metadata={
            "status": state.get("status"),
            "run_count": state.get("run_count"),
            "strict_mode": state.get("strict_mode"),
            "route_count": state.get("route_summary", {}).get("count", 0),
            "missing_required_routes": state.get("route_summary", {}).get("missing_required_routes", []),
            "warning_count": len(state.get("warnings", []) or []),
            "error_count": len(state.get("errors", []) or []),
            "completed_at": state.get("completed_at"),
        },
    )


def _mark_startup_failed(app: Flask, extensions_module: ModuleType | None, error_message: str) -> None:
    """Markiert Startup optional in Extension-Registry als fehlgeschlagen."""
    state = _ensure_startup_state(app)

    _call_optional_extension_function(
        extensions_module,
        "mark_extension_failed",
        app,
        "startup",
        error_message,
        metadata={
            "status": state.get("status"),
            "run_count": state.get("run_count"),
            "strict_mode": state.get("strict_mode"),
            "completed_at": state.get("completed_at"),
        },
    )


def _collect_extension_summary(app: Flask, extensions_module: ModuleType | None) -> Any:
    """Liest optionale Extension-Summary."""
    return _call_optional_extension_function(extensions_module, "get_extension_summary", app)


# -----------------------------------------------------------------------------
# Öffentliche Startup-Funktionen
# -----------------------------------------------------------------------------

def run_startup(app: Flask) -> Flask:
    """
    Führt den Startup-Ablauf für vectoplan-library aus.

    Der Ablauf ist idempotent:

    - Mehrfaches Aufrufen zerstört keinen Zustand
    - run_count wird mitgeführt
    - bestehende Metadaten werden ergänzt

    Im nicht-strikten Modus werden fehlende optionale oder noch unfertige Teile
    als Warnungen dokumentiert, blockieren aber den Containerstart nicht.
    """

    if not _is_flask_app(app):
        raise TypeError("run_startup(app) expects a Flask app or compatible object.")

    state = _ensure_startup_state(app)
    state["status"] = "running"
    state["started_at"] = _utc_now_iso()
    state["completed_at"] = None
    state["run_count"] = _safe_int(state.get("run_count"), default=0, minimum=0) + 1
    state["strict_mode"] = _is_strict_startup_enabled(app)

    # Checklisten pro Run zurücksetzen.
    state["warnings"] = []
    state["errors"] = []
    state["checks"] = {
        "paths": [],
        "files": [],
        "modules": [],
        "routes": [],
        "vplib_settings": [],
        "library_settings": [],
        "library_health": [],
    }

    _safe_log_info(app, "Startup hooks for vectoplan-library are running.")

    extensions_module = None

    try:
        extensions_module = _initialize_extension_registry(app)

        _collect_startup_metadata(app)
        _run_path_checks(app)
        _run_file_checks(app)
        _run_module_checks(app)
        _run_vplib_settings_check(app)
        _run_library_settings_check(app)
        _run_library_health_check(app)
        _run_route_checks(app)

        extension_summary = _collect_extension_summary(app, extensions_module)

        if extension_summary is not None:
            state["metadata"]["extension_summary"] = _json_safe(extension_summary)

        state["completed_at"] = _utc_now_iso()
        state["status"] = "completed"

        _mark_startup_initialized(app, extensions_module)

        _safe_log_info(app, "Startup hooks for vectoplan-library completed.")
        return app

    except Exception as exc:
        state["status"] = "failed"
        state["completed_at"] = _utc_now_iso()

        error_message = f"Startup of vectoplan-library failed: {exc!r}"
        _append_error(app, error_message)
        _safe_log_exception(app, error_message)

        _mark_startup_failed(app, extensions_module, error_message)

        raise


def bootstrap_app(app: Flask) -> Flask:
    """Alias für kompatible App-Bootstrap-Aufrufe."""
    return run_startup(app)


def initialize_app(app: Flask) -> Flask:
    """Alias für kompatible Initialisierungsaufrufe."""
    return run_startup(app)


# -----------------------------------------------------------------------------
# Lesefunktionen / Debugging
# -----------------------------------------------------------------------------

def get_startup_state(app: Flask) -> dict[str, Any]:
    """Liefert den aktuellen Startup-Zustand als defensive Kopie zurück."""
    state = _ensure_startup_state(app)

    try:
        return copy.deepcopy(state)
    except Exception:
        return dict(state)


def get_startup_summary(app: Flask) -> dict[str, Any]:
    """Liefert eine kompakte Startup-Zusammenfassung zurück."""
    state = _ensure_startup_state(app)
    route_summary = state.get("route_summary", {}) if isinstance(state.get("route_summary"), Mapping) else {}

    checks = state.get("checks", {}) if isinstance(state.get("checks"), Mapping) else {}

    def _count_failed(category: str) -> int:
        result = 0

        for item in checks.get(category, []) or []:
            if isinstance(item, Mapping) and not bool(item.get("ok")):
                result += 1

        return result

    return {
        "schema_version": STARTUP_SCHEMA_VERSION,
        "service_name": DEFAULT_SERVICE_NAME,
        "status": _optional_text(state.get("status"), "unknown"),
        "started_at": state.get("started_at"),
        "completed_at": state.get("completed_at"),
        "run_count": _safe_int(state.get("run_count"), default=0, minimum=0),
        "strict_mode": _safe_bool(state.get("strict_mode"), False),
        "warning_count": len(state.get("warnings", []) or []),
        "error_count": len(state.get("errors", []) or []),
        "path_check_count": len(checks.get("paths", []) or []),
        "file_check_count": len(checks.get("files", []) or []),
        "module_check_count": len(checks.get("modules", []) or []),
        "route_check_count": len(checks.get("routes", []) or []),
        "failed_path_checks": _count_failed("paths"),
        "failed_file_checks": _count_failed("files"),
        "failed_module_checks": _count_failed("modules"),
        "failed_route_checks": _count_failed("routes"),
        "route_count": _safe_int(route_summary.get("count", 0), default=0, minimum=0),
        "required_route_count": _safe_int(route_summary.get("required_route_count", 0), default=0, minimum=0),
        "missing_required_routes": list(route_summary.get("missing_required_routes", []) or []),
        "vplib_route_prefix": _optional_text(route_summary.get("vplib_route_prefix"), DEFAULT_VPLIB_ROUTE_PREFIX),
        "library_route_prefix": _optional_text(route_summary.get("library_route_prefix"), DEFAULT_LIBRARY_ROUTE_PREFIX),
    }


def clear_startup_caches() -> None:
    """Leert Startup-Caches."""
    get_default_path_check_specs.cache_clear()
    get_default_file_check_specs.cache_clear()
    get_default_module_check_specs.cache_clear()
    _load_vplib_settings_module.cache_clear()
    _load_library_settings_module.cache_clear()


__all__: Final[list[str]] = [
    "DEFAULT_HEALTH_ROUTE",
    "DEFAULT_LIBRARY_BLOCKS_ROUTE",
    "DEFAULT_LIBRARY_HEALTH_ROUTE",
    "DEFAULT_LIBRARY_ROUTE_PREFIX",
    "DEFAULT_LIBRARY_SCAN_ROUTE",
    "DEFAULT_LIBRARY_TREE_ROUTE",
    "DEFAULT_READY_ROUTE",
    "DEFAULT_SERVICE_DISPLAY_NAME",
    "DEFAULT_SERVICE_NAME",
    "DEFAULT_VPLIB_CREATE_ROUTE",
    "DEFAULT_VPLIB_HEALTH_ROUTE",
    "DEFAULT_VPLIB_ROUTE_PREFIX",
    "DEFAULT_VPLIB_TEST_ROUTE",
    "ENV_LIBRARY_ROUTE_PREFIX",
    "ENV_STARTUP_STRICT",
    "ENV_VPLIB_ROUTE_PREFIX",
    "FileCheckSpec",
    "ModuleCheckSpec",
    "PathCheckSpec",
    "RouteCheckSpec",
    "SERVICE_NAMESPACE",
    "STARTUP_SCHEMA_VERSION",
    "STARTUP_STATE_KEY",
    "StartupCheckResult",
    "bootstrap_app",
    "clear_startup_caches",
    "get_default_file_check_spec_data",
    "get_default_file_check_specs",
    "get_default_module_check_spec_data",
    "get_default_module_check_specs",
    "get_default_path_check_spec_data",
    "get_default_path_check_specs",
    "get_default_route_check_spec_data",
    "get_default_route_check_specs",
    "get_startup_state",
    "get_startup_summary",
    "initialize_app",
    "run_startup",
]