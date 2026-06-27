# services/vectoplan-library/src/routes/__init__.py
"""
Central Blueprint registration for the vectoplan-library microservice.

Diese Datei bildet die HTTP-Außenkante auf Strukturebene ab.

Aufgaben:
- vorhandene Route-Module kennen
- Blueprints defensiv laden
- Blueprints genau einmal an der Flask-App registrieren
- Routing-Metadaten in app.extensions["vectoplan_library"] speichern
- keine Business-Logik
- keine HTML-Erzeugung direkt in dieser Registry
- keine Inventar-Mockdaten
- keine DB-Sync-Fachlogik

Registriert:

Required:
- routes.vplib_routes:vplib_bp
- routes.library_routes:library_bp
- routes.taxonomy:taxonomy_bp

Optional:
- routes.api:api_bp
- routes.library_definition_routes:library_definition_bp
- routes.create:create_bp
- routes.inventar:inventar_bp
- routes.inventar_user:inventar_user_bp

Inventar-UI:
- GET /user-inventar
- GET /creative-inventar

User-Inventar-API:
- GET    /api/v1/vplib/inventar_user
- GET    /api/v1/vplib/inventar_user/state
- GET    /api/v1/vplib/inventar_user/slots
- PATCH  /api/v1/vplib/inventar_user/select-slot
- PUT    /api/v1/vplib/inventar_user/slots/<slot_index>
- PATCH  /api/v1/vplib/inventar_user/slots/<slot_index>
- DELETE /api/v1/vplib/inventar_user/slots/<slot_index>
"""

from __future__ import annotations

import importlib
import traceback
from dataclasses import asdict, dataclass, field, is_dataclass
from datetime import datetime, timezone
from functools import lru_cache
from pathlib import Path
from types import ModuleType
from typing import Any, Final, Iterable, Mapping

from flask import Blueprint, Flask


# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

ROUTES_PACKAGE_SCHEMA_VERSION: Final[str] = "vplib.routes.registry.v9"
ROUTES_PACKAGE_VERSION: Final[str] = "0.9.1"
ROUTES_COMPONENT_NAME: Final[str] = "vectoplan-library-routes"

EXTENSION_REGISTRY_KEY: Final[str] = "vectoplan_library"

DEFAULT_VPLIB_ROUTE_MODULE: Final[str] = "routes.vplib_routes"
DEFAULT_VPLIB_BLUEPRINT_ATTRIBUTE: Final[str] = "vplib_bp"

DEFAULT_API_ROUTE_MODULE: Final[str] = "routes.api"
DEFAULT_API_BLUEPRINT_ATTRIBUTE: Final[str] = "api_bp"

DEFAULT_LIBRARY_ROUTE_MODULE: Final[str] = "routes.library_routes"
DEFAULT_LIBRARY_BLUEPRINT_ATTRIBUTE: Final[str] = "library_bp"

DEFAULT_TAXONOMY_ROUTE_MODULE: Final[str] = "routes.taxonomy"
DEFAULT_TAXONOMY_BLUEPRINT_ATTRIBUTE: Final[str] = "taxonomy_bp"

DEFAULT_DEFINITION_ROUTE_MODULE: Final[str] = "routes.library_definition_routes"
DEFAULT_DEFINITION_BLUEPRINT_ATTRIBUTE: Final[str] = "library_definition_bp"

DEFAULT_CREATE_ROUTE_MODULE: Final[str] = "routes.create"
DEFAULT_CREATE_BLUEPRINT_ATTRIBUTE: Final[str] = "create_bp"

DEFAULT_INVENTAR_ROUTE_MODULE: Final[str] = "routes.inventar"
DEFAULT_INVENTAR_BLUEPRINT_ATTRIBUTE: Final[str] = "inventar_bp"

DEFAULT_INVENTAR_USER_ROUTE_MODULE: Final[str] = "routes.inventar_user"
DEFAULT_INVENTAR_USER_BLUEPRINT_ATTRIBUTE: Final[str] = "inventar_user_bp"

DEFAULT_REQUIRED_BLUEPRINTS: Final[tuple[str, ...]] = (
    f"{DEFAULT_VPLIB_ROUTE_MODULE}:{DEFAULT_VPLIB_BLUEPRINT_ATTRIBUTE}",
    f"{DEFAULT_LIBRARY_ROUTE_MODULE}:{DEFAULT_LIBRARY_BLUEPRINT_ATTRIBUTE}",
    f"{DEFAULT_TAXONOMY_ROUTE_MODULE}:{DEFAULT_TAXONOMY_BLUEPRINT_ATTRIBUTE}",
)

DEFAULT_OPTIONAL_BLUEPRINTS: Final[tuple[str, ...]] = (
    f"{DEFAULT_API_ROUTE_MODULE}:{DEFAULT_API_BLUEPRINT_ATTRIBUTE}",
    f"{DEFAULT_DEFINITION_ROUTE_MODULE}:{DEFAULT_DEFINITION_BLUEPRINT_ATTRIBUTE}",
    f"{DEFAULT_CREATE_ROUTE_MODULE}:{DEFAULT_CREATE_BLUEPRINT_ATTRIBUTE}",
    f"{DEFAULT_INVENTAR_ROUTE_MODULE}:{DEFAULT_INVENTAR_BLUEPRINT_ATTRIBUTE}",
    f"{DEFAULT_INVENTAR_USER_ROUTE_MODULE}:{DEFAULT_INVENTAR_USER_BLUEPRINT_ATTRIBUTE}",
)


# ---------------------------------------------------------------------------
# Exceptions
# ---------------------------------------------------------------------------

class RouteRegistryError(RuntimeError):
    """Wird ausgelöst, wenn Blueprint-Registrierung oder Route-Registry fehlschlägt."""


# ---------------------------------------------------------------------------
# Dataclasses
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class BlueprintSpec:
    """Beschreibt, wie ein Blueprint geladen und registriert wird."""

    module_name: str
    attribute_name: str
    url_prefix: str | None = None
    required: bool = True
    description: str = ""

    @property
    def key(self) -> str:
        return f"{self.module_name}:{self.attribute_name}"

    def normalized(self) -> "BlueprintSpec":
        return BlueprintSpec(
            module_name=clean_required_string(self.module_name, "module_name"),
            attribute_name=clean_required_string(self.attribute_name, "attribute_name"),
            url_prefix=clean_optional_string(self.url_prefix),
            required=bool(self.required),
            description=clean_optional_string(self.description) or "",
        )

    def to_dict(self) -> dict[str, Any]:
        normalized = self.normalized()
        return {
            "module_name": normalized.module_name,
            "attribute_name": normalized.attribute_name,
            "url_prefix": normalized.url_prefix,
            "required": normalized.required,
            "description": normalized.description,
            "key": normalized.key,
        }


@dataclass(frozen=True)
class BlueprintResolutionResult:
    """Ergebnis einer Blueprint-Auflösung ohne Registrierung."""

    spec: BlueprintSpec
    resolved: bool
    blueprint_name: str | None = None
    error: str | None = None
    health: dict[str, Any] = field(default_factory=dict)

    @property
    def ok(self) -> bool:
        return bool(self.resolved)

    def to_dict(self) -> dict[str, Any]:
        return {
            "spec": self.spec.normalized().to_dict(),
            "resolved": self.resolved,
            "ok": self.ok,
            "blueprint_name": self.blueprint_name,
            "error": self.error,
            "health": normalize_metadata(self.health),
        }


@dataclass(frozen=True)
class BlueprintRegistrationResult:
    """Ergebnis einer einzelnen Blueprint-Registrierung."""

    blueprint_name: str
    module_name: str
    attribute_name: str
    registered: bool
    skipped: bool = False
    url_prefix: str | None = None
    error: str | None = None
    required: bool = True
    description: str = ""

    @property
    def key(self) -> str:
        return f"{self.module_name}:{self.attribute_name}"

    @property
    def ok(self) -> bool:
        if self.registered or self.skipped:
            return True

        return not self.required

    def to_dict(self) -> dict[str, Any]:
        return {
            "blueprint_name": self.blueprint_name,
            "module_name": self.module_name,
            "attribute_name": self.attribute_name,
            "key": self.key,
            "registered": self.registered,
            "skipped": self.skipped,
            "ok": self.ok,
            "url_prefix": self.url_prefix,
            "error": self.error,
            "required": self.required,
            "description": self.description,
        }


# ---------------------------------------------------------------------------
# Generic helpers
# ---------------------------------------------------------------------------

def utc_now_iso() -> str:
    """Liefert eine UTC-Zeit im ISO-Format."""
    return datetime.now(timezone.utc).isoformat()


def exception_to_dict(
    exc: BaseException,
    *,
    include_traceback: bool = False,
) -> dict[str, Any]:
    """Serialisiert Exceptions JSON-kompatibel."""
    payload: dict[str, Any] = {
        "type": exc.__class__.__name__,
        "message": str(exc),
    }

    if include_traceback:
        payload["traceback"] = traceback.format_exception(
            type(exc),
            exc,
            exc.__traceback__,
        )

    return payload


def clean_required_string(value: Any, field_name: str) -> str:
    """Normalisiert Pflicht-String."""
    try:
        cleaned = str(value).strip()
    except Exception as exc:
        raise RouteRegistryError(f"{field_name} must be string-like.") from exc

    if not cleaned:
        raise RouteRegistryError(f"{field_name} is required.")

    return cleaned


def clean_optional_string(value: Any) -> str | None:
    """Normalisiert optionalen String."""
    if value is None:
        return None

    try:
        cleaned = str(value).strip()
    except Exception:
        return None

    return cleaned or None


def normalize_metadata(value: Mapping[str, Any] | None) -> dict[str, Any]:
    """Normalisiert Metadata JSON-kompatibel."""
    if value is None:
        return {}

    if not isinstance(value, Mapping):
        return {"value": str(value)}

    return {
        str(key): normalize_metadata_value(child_value)
        for key, child_value in value.items()
    }


def normalize_metadata_value(value: Any) -> Any:
    """Normalisiert Metadata-Werte JSON-kompatibel."""
    if value is None:
        return None

    if isinstance(value, (str, int, float, bool)):
        return value

    if isinstance(value, Mapping):
        return normalize_metadata(value)

    if isinstance(value, Path):
        return str(value)

    if is_dataclass(value):
        try:
            return normalize_metadata(asdict(value))
        except Exception:
            return str(value)

    if isinstance(value, (list, tuple, set)):
        return [normalize_metadata_value(item) for item in value]

    if hasattr(value, "to_dict") and callable(value.to_dict):
        try:
            return normalize_metadata_value(value.to_dict())
        except Exception:
            return str(value)

    return str(value)


def safe_tuple(value: Any) -> tuple[Any, ...]:
    """Normalisiert defensiv zu tuple."""
    if value is None:
        return tuple()

    if isinstance(value, tuple):
        return value

    if isinstance(value, str):
        return (value,)

    if isinstance(value, Iterable):
        try:
            return tuple(value)
        except Exception:
            return tuple()

    return (value,)


def dataclass_to_dict_safe(value: Any) -> dict[str, Any]:
    """Defensive Dataclass-Serialisierung."""
    try:
        if is_dataclass(value):
            raw = asdict(value)
            if isinstance(raw, Mapping):
                return normalize_metadata(raw)
    except Exception:
        pass

    if isinstance(value, Mapping):
        return normalize_metadata(value)

    return {"value": str(value)}


# ---------------------------------------------------------------------------
# Flask app / registry helpers
# ---------------------------------------------------------------------------

def _is_flask_app(app: object) -> bool:
    """Prüft defensiv, ob das übergebene Objekt wie eine Flask-App verwendbar ist."""
    if isinstance(app, Flask):
        return True

    required_attributes = ("register_blueprint", "blueprints", "extensions")

    return all(hasattr(app, attribute_name) for attribute_name in required_attributes)


def _safe_get_logger(app: Flask):
    try:
        return app.logger
    except Exception:
        return None


def _safe_log_debug(app: Flask, message: str) -> None:
    logger = _safe_get_logger(app)
    if logger is None:
        return

    try:
        logger.debug(message)
    except Exception:
        pass


def _safe_log_info(app: Flask, message: str) -> None:
    logger = _safe_get_logger(app)
    if logger is None:
        return

    try:
        logger.info(message)
    except Exception:
        pass


def _safe_log_warning(app: Flask, message: str) -> None:
    logger = _safe_get_logger(app)
    if logger is None:
        return

    try:
        logger.warning(message)
    except Exception:
        pass


def _safe_log_error(app: Flask, message: str) -> None:
    logger = _safe_get_logger(app)
    if logger is None:
        return

    try:
        logger.error(message)
    except Exception:
        pass


def _ensure_extension_registry(app: Flask) -> dict[str, Any]:
    """Stellt sicher, dass der gemeinsame Extension-Bereich existiert."""
    try:
        app.extensions.setdefault(EXTENSION_REGISTRY_KEY, {})
        registry = app.extensions[EXTENSION_REGISTRY_KEY]

        if not isinstance(registry, dict):
            raise TypeError(
                f"app.extensions[{EXTENSION_REGISTRY_KEY!r}] is not a dictionary."
            )

        return registry
    except Exception as exc:
        raise RouteRegistryError(
            f"The Flask extension registry area {EXTENSION_REGISTRY_KEY!r} could not be initialized."
        ) from exc


def _ensure_blueprint_tracking(app: Flask) -> set[str]:
    """Erstellt robust ein Tracking-Set für bereits registrierte Blueprints."""
    registry = _ensure_extension_registry(app)
    existing = registry.get("registered_blueprint_names")

    if isinstance(existing, set):
        return existing

    if isinstance(existing, (list, tuple)):
        restored = {str(item) for item in existing}
        registry["registered_blueprint_names"] = restored
        return restored

    tracking: set[str] = set()
    registry["registered_blueprint_names"] = tracking
    return tracking


def _ensure_registration_results(app: Flask) -> list[dict[str, Any]]:
    """Erstellt robust eine Ergebnisliste im Registry-Bereich."""
    registry = _ensure_extension_registry(app)
    existing = registry.get("blueprint_registration_results")

    if isinstance(existing, list):
        return existing

    results: list[dict[str, Any]] = []
    registry["blueprint_registration_results"] = results
    return results


def _get_app_blueprint_names(app: Flask) -> tuple[str, ...]:
    """Liefert Namen aller bereits registrierten App-Blueprints."""
    try:
        return tuple(sorted(str(name) for name in app.blueprints.keys()))
    except Exception:
        return tuple()


def _get_app_route_count(app: Flask) -> int:
    """Liefert Anzahl registrierter URL-Rules."""
    try:
        return len(list(app.url_map.iter_rules()))
    except Exception:
        return 0


# ---------------------------------------------------------------------------
# Blueprint specs
# ---------------------------------------------------------------------------

@lru_cache(maxsize=1)
def get_blueprint_specs() -> tuple[BlueprintSpec, ...]:
    """Liefert die aktuell vorgesehenen Blueprint-Spezifikationen."""
    return (
        BlueprintSpec(
            module_name=DEFAULT_VPLIB_ROUTE_MODULE,
            attribute_name=DEFAULT_VPLIB_BLUEPRINT_ATTRIBUTE,
            required=True,
            description="VPLIB creation, dry-run, health and self-test routes.",
        ).normalized(),
        BlueprintSpec(
            module_name=DEFAULT_API_ROUTE_MODULE,
            attribute_name=DEFAULT_API_BLUEPRINT_ATTRIBUTE,
            required=False,
            description="Creative Library API routes for DB sync, DB health, published reads, inventory and filesystem debug access.",
        ).normalized(),
        BlueprintSpec(
            module_name=DEFAULT_LIBRARY_ROUTE_MODULE,
            attribute_name=DEFAULT_LIBRARY_BLUEPRINT_ATTRIBUTE,
            required=True,
            description="Creative Library scan, blocks, block detail, variants and tree routes.",
        ).normalized(),
        BlueprintSpec(
            module_name=DEFAULT_TAXONOMY_ROUTE_MODULE,
            attribute_name=DEFAULT_TAXONOMY_BLUEPRINT_ATTRIBUTE,
            required=True,
            description="Canonical taxonomy routes.",
        ).normalized(),
        BlueprintSpec(
            module_name=DEFAULT_DEFINITION_ROUTE_MODULE,
            attribute_name=DEFAULT_DEFINITION_BLUEPRINT_ATTRIBUTE,
            required=False,
            description="Definitions routes.",
        ).normalized(),
        BlueprintSpec(
            module_name=DEFAULT_CREATE_ROUTE_MODULE,
            attribute_name=DEFAULT_CREATE_BLUEPRINT_ATTRIBUTE,
            required=False,
            description="Create frontend and create API routes.",
        ).normalized(),
        BlueprintSpec(
            module_name=DEFAULT_INVENTAR_ROUTE_MODULE,
            attribute_name=DEFAULT_INVENTAR_BLUEPRINT_ATTRIBUTE,
            required=False,
            description="HTML routes for /user-inventar and /creative-inventar.",
        ).normalized(),
        BlueprintSpec(
            module_name=DEFAULT_INVENTAR_USER_ROUTE_MODULE,
            attribute_name=DEFAULT_INVENTAR_USER_BLUEPRINT_ATTRIBUTE,
            required=False,
            description="Persisted User-Inventar API routes.",
        ).normalized(),
    )


def iter_blueprint_specs() -> tuple[BlueprintSpec, ...]:
    """Öffentliche read-only Zugriffsfunktion auf die Blueprint-Spezifikation."""
    return get_blueprint_specs()


def get_required_blueprint_keys() -> tuple[str, ...]:
    """Liefert alle required Blueprint-Keys."""
    return tuple(spec.key for spec in get_blueprint_specs() if spec.required)


def get_optional_blueprint_keys() -> tuple[str, ...]:
    """Liefert alle optionalen Blueprint-Keys."""
    return tuple(spec.key for spec in get_blueprint_specs() if not spec.required)


# ---------------------------------------------------------------------------
# Module / blueprint resolution
# ---------------------------------------------------------------------------

@lru_cache(maxsize=64)
def _import_module(module_name: str) -> ModuleType:
    """Importiert ein Route-Modul gecacht und defensiv."""
    normalized_module_name = clean_required_string(module_name, "module_name")

    try:
        return importlib.import_module(normalized_module_name)
    except Exception as exc:
        raise RouteRegistryError(
            f"Route module {normalized_module_name!r} could not be imported."
        ) from exc


def _get_module_health(module: ModuleType) -> dict[str, Any]:
    """Ruft eine optionale Health-/Info-Funktion eines Route-Moduls auf."""
    health_function_names = (
        "get_api_routes_health",
        "get_library_routes_health",
        "get_vplib_routes_health",
        "get_create_routes_health",
        "get_taxonomy_routes_health",
        "get_taxonomy_routes_info",
        "get_library_definition_routes_health",
        "get_inventar_routes_health",
        "get_inventar_route_health",
        "get_inventar_user_routes_health",
        "get_inventar_user_route_health",
        "get_user_inventory_routes_health",
        "get_user_inventory_route_health",
        "get_routes_health",
        "get_route_health",
        "get_routes_info",
        "get_route_info",
    )

    for function_name in health_function_names:
        try:
            function = getattr(module, function_name, None)

            if not callable(function):
                continue

            health = function()
            normalized = normalize_metadata_value(health)

            if isinstance(normalized, Mapping):
                return dict(normalized)

            return {"value": str(normalized)}
        except Exception as exc:
            return {
                "ok": False,
                "healthy": False,
                "status": "health_error",
                "function": function_name,
                "error": exception_to_dict(exc),
            }

    return {
        "ok": True,
        "healthy": True,
        "status": "no_route_health_function",
    }


def _resolve_blueprint(spec: BlueprintSpec) -> Blueprint:
    """Löst anhand einer BlueprintSpec das tatsächliche Blueprint-Objekt auf."""
    normalized_spec = spec.normalized()
    module = _import_module(normalized_spec.module_name)

    try:
        candidate = getattr(module, normalized_spec.attribute_name)
    except AttributeError as exc:
        raise RouteRegistryError(
            f"Route module {normalized_spec.module_name!r} does not export "
            f"{normalized_spec.attribute_name!r}."
        ) from exc

    if candidate is None:
        raise RouteRegistryError(
            f"Attribute {normalized_spec.attribute_name!r} from "
            f"{normalized_spec.module_name!r} is None."
        )

    if not isinstance(candidate, Blueprint):
        raise RouteRegistryError(
            f"Attribute {normalized_spec.attribute_name!r} from "
            f"{normalized_spec.module_name!r} is not a Flask Blueprint."
        )

    return candidate


def resolve_blueprint_spec(spec: BlueprintSpec) -> BlueprintResolutionResult:
    """Öffentliche, JSON-kompatible Blueprint-Auflösung ohne Registrierung."""
    normalized_spec = spec.normalized()

    try:
        module = _import_module(normalized_spec.module_name)
        blueprint = _resolve_blueprint(normalized_spec)
        blueprint_name = getattr(blueprint, "name", None)
        module_health = _get_module_health(module)

        return BlueprintResolutionResult(
            spec=normalized_spec,
            resolved=True,
            blueprint_name=str(blueprint_name) if blueprint_name else None,
            error=None,
            health=module_health,
        )
    except Exception as exc:
        return BlueprintResolutionResult(
            spec=normalized_spec,
            resolved=False,
            blueprint_name=None,
            error=str(exc),
            health={
                "ok": False,
                "healthy": False,
                "error": exception_to_dict(exc),
            },
        )


def resolve_all_blueprint_specs() -> tuple[BlueprintResolutionResult, ...]:
    """Löst alle Blueprint-Spezifikationen ohne Registrierung auf."""
    return tuple(resolve_blueprint_spec(spec) for spec in get_blueprint_specs())


# ---------------------------------------------------------------------------
# Blueprint registration
# ---------------------------------------------------------------------------

def _register_single_blueprint(
    app: Flask,
    spec: BlueprintSpec,
) -> BlueprintRegistrationResult:
    """Registriert genau einen Blueprint defensiv an der App."""
    normalized_spec = spec.normalized()
    blueprint = _resolve_blueprint(normalized_spec)
    blueprint_name = getattr(blueprint, "name", None)

    if not blueprint_name or not isinstance(blueprint_name, str):
        raise RouteRegistryError("A Blueprint without a valid name cannot be registered.")

    tracked_names = _ensure_blueprint_tracking(app)

    if blueprint_name in tracked_names:
        _safe_log_debug(app, f"Blueprint {blueprint_name!r} is already tracked and will be skipped.")
        return BlueprintRegistrationResult(
            blueprint_name=blueprint_name,
            module_name=normalized_spec.module_name,
            attribute_name=normalized_spec.attribute_name,
            registered=False,
            skipped=True,
            url_prefix=normalized_spec.url_prefix,
            required=normalized_spec.required,
            description=normalized_spec.description,
        )

    if blueprint_name in getattr(app, "blueprints", {}):
        tracked_names.add(blueprint_name)
        _safe_log_debug(app, f"Blueprint {blueprint_name!r} already exists on app and was added to tracking.")
        return BlueprintRegistrationResult(
            blueprint_name=blueprint_name,
            module_name=normalized_spec.module_name,
            attribute_name=normalized_spec.attribute_name,
            registered=False,
            skipped=True,
            url_prefix=normalized_spec.url_prefix,
            required=normalized_spec.required,
            description=normalized_spec.description,
        )

    try:
        if normalized_spec.url_prefix:
            app.register_blueprint(blueprint, url_prefix=normalized_spec.url_prefix)
        else:
            app.register_blueprint(blueprint)
    except Exception as exc:
        raise RouteRegistryError(
            f"Blueprint {blueprint_name!r} could not be registered."
        ) from exc

    tracked_names.add(blueprint_name)
    _safe_log_info(app, f"Blueprint {blueprint_name!r} was registered successfully.")

    return BlueprintRegistrationResult(
        blueprint_name=blueprint_name,
        module_name=normalized_spec.module_name,
        attribute_name=normalized_spec.attribute_name,
        registered=True,
        skipped=False,
        url_prefix=normalized_spec.url_prefix,
        required=normalized_spec.required,
        description=normalized_spec.description,
    )


def _store_registration_metadata(
    app: Flask,
    *,
    results: Iterable[BlueprintRegistrationResult],
) -> None:
    """Speichert Routing-Metadaten im Extension-Bereich."""
    registry = _ensure_extension_registry(app)
    normalized_results = tuple(results or ())
    specs = get_blueprint_specs()
    resolution_results = resolve_all_blueprint_specs()

    registry["route_module"] = "routes"
    registry["routes_component"] = ROUTES_COMPONENT_NAME
    registry["routes_version"] = ROUTES_PACKAGE_VERSION
    registry["schema_version"] = ROUTES_PACKAGE_SCHEMA_VERSION
    registry["blueprint_specs"] = [spec.to_dict() for spec in specs]
    registry["blueprint_resolution_results"] = [
        result.to_dict()
        for result in resolution_results
    ]
    registry["blueprint_registration_results"] = [
        result.to_dict()
        for result in normalized_results
    ]
    registry["registered_blueprint_names_list"] = get_registered_blueprint_names(app)
    registry["app_blueprint_names"] = list(_get_app_blueprint_names(app))
    registry["route_count"] = _get_app_route_count(app)
    registry["routing_initialized"] = True
    registry["routing_initialized_at"] = utc_now_iso()


def register_blueprints(app: Flask) -> Flask:
    """
    Registriert alle vorgesehenen Blueprints an der Flask-App.

    Diese Funktion muss top-level exportiert bleiben.
    app.py erwartet exakt:
        routes.register_blueprints(app)
    """

    if not _is_flask_app(app):
        raise TypeError(
            "register_blueprints(app) expects a Flask app or a compatible object."
        )

    specs = get_blueprint_specs()
    results: list[BlueprintRegistrationResult] = []

    for spec in specs:
        normalized_spec = spec.normalized()

        try:
            result = _register_single_blueprint(app, normalized_spec)
            results.append(result)
            _ensure_registration_results(app).append(result.to_dict())

        except Exception as exc:
            if normalized_spec.required:
                _safe_log_error(
                    app,
                    f"Required Blueprint {normalized_spec.key!r} could not be registered: {exc}",
                )
                raise

            _safe_log_warning(
                app,
                f"Optional Blueprint {normalized_spec.key!r} could not be registered: {exc}",
            )

            result = BlueprintRegistrationResult(
                blueprint_name=normalized_spec.attribute_name,
                module_name=normalized_spec.module_name,
                attribute_name=normalized_spec.attribute_name,
                registered=False,
                skipped=False,
                url_prefix=normalized_spec.url_prefix,
                error=str(exc),
                required=normalized_spec.required,
                description=normalized_spec.description,
            )

            results.append(result)
            _ensure_registration_results(app).append(result.to_dict())

    _store_registration_metadata(app, results=tuple(results))
    return app


# ---------------------------------------------------------------------------
# Snapshot / public registry access
# ---------------------------------------------------------------------------

def get_registered_blueprint_names(app: Flask) -> list[str]:
    """Liefert die durch dieses Modul getrackten Blueprint-Namen sortiert zurück."""
    tracked_names = _ensure_blueprint_tracking(app)

    try:
        return sorted(tracked_names)
    except Exception:
        return list(tracked_names)


def get_blueprint_registry_snapshot(app: Flask) -> dict[str, Any]:
    """Gibt einen JSON-kompatiblen Snapshot der Blueprint-Registry zurück."""
    try:
        registry = _ensure_extension_registry(app)
        tracked_names = _ensure_blueprint_tracking(app)

        raw_results = registry.get("blueprint_registration_results", [])
        result_payloads = raw_results if isinstance(raw_results, list) else []

        return {
            "schema_version": ROUTES_PACKAGE_SCHEMA_VERSION,
            "version": ROUTES_PACKAGE_VERSION,
            "component": ROUTES_COMPONENT_NAME,
            "initialized": bool(registry.get("routing_initialized", False)),
            "ok": True,
            "registered_count": len(tracked_names),
            "registered_blueprint_names": sorted(tracked_names),
            "app_blueprint_names": list(_get_app_blueprint_names(app)),
            "route_count": _get_app_route_count(app),
            "specs": [spec.to_dict() for spec in get_blueprint_specs()],
            "results": result_payloads,
            "warnings": [],
            "errors": [],
        }
    except Exception as exc:
        return {
            "schema_version": ROUTES_PACKAGE_SCHEMA_VERSION,
            "version": ROUTES_PACKAGE_VERSION,
            "component": ROUTES_COMPONENT_NAME,
            "initialized": False,
            "ok": False,
            "registered_count": 0,
            "registered_blueprint_names": [],
            "app_blueprint_names": [],
            "route_count": 0,
            "specs": [spec.to_dict() for spec in get_blueprint_specs()],
            "results": [],
            "warnings": [],
            "errors": [str(exc)],
        }


def get_routes_health(app: Flask | None = None) -> dict[str, Any]:
    """Liefert einen Health-Status der Route-Registry."""
    errors: list[str] = []
    warnings: list[str] = []

    resolution_results = resolve_all_blueprint_specs()

    for result in resolution_results:
        if result.ok:
            continue

        if result.spec.required:
            errors.append(f"required blueprint could not be resolved: {result.spec.key}")
        else:
            warnings.append(f"optional blueprint could not be resolved: {result.spec.key}")

    app_snapshot: dict[str, Any] | None = None

    if app is not None:
        try:
            app_snapshot = get_blueprint_registry_snapshot(app)
            if not app_snapshot.get("ok", False):
                warnings.append("app blueprint registry snapshot is not ok")
        except Exception as exc:
            errors.append(f"could not build app route snapshot: {exc}")

    healthy = len(errors) == 0

    return {
        "ok": healthy,
        "healthy": healthy,
        "component": ROUTES_COMPONENT_NAME,
        "version": ROUTES_PACKAGE_VERSION,
        "schema_version": ROUTES_PACKAGE_SCHEMA_VERSION,
        "generated_at": utc_now_iso(),
        "spec_count": len(get_blueprint_specs()),
        "required_blueprint_keys": list(get_required_blueprint_keys()),
        "optional_blueprint_keys": list(get_optional_blueprint_keys()),
        "resolution_results": [result.to_dict() for result in resolution_results],
        "app_snapshot": app_snapshot,
        "warnings": warnings,
        "errors": errors,
    }


# ---------------------------------------------------------------------------
# Cache / reset helpers
# ---------------------------------------------------------------------------

def clear_route_registry_caches() -> None:
    """Leert interne Route-Registry-Caches."""
    get_blueprint_specs.cache_clear()
    _import_module.cache_clear()


def reset_route_registry_state(app: Flask) -> None:
    """Entfernt nur dieses Modul betreffende Registry-Metadaten aus app.extensions."""
    registry = _ensure_extension_registry(app)

    for key in (
        "registered_blueprint_names",
        "registered_blueprint_names_list",
        "blueprint_registration_results",
        "blueprint_resolution_results",
        "blueprint_specs",
        "app_blueprint_names",
        "route_count",
        "routing_initialized",
        "routing_initialized_at",
    ):
        registry.pop(key, None)


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

__all__: Final[list[str]] = [
    "DEFAULT_API_BLUEPRINT_ATTRIBUTE",
    "DEFAULT_API_ROUTE_MODULE",
    "DEFAULT_CREATE_BLUEPRINT_ATTRIBUTE",
    "DEFAULT_CREATE_ROUTE_MODULE",
    "DEFAULT_DEFINITION_BLUEPRINT_ATTRIBUTE",
    "DEFAULT_DEFINITION_ROUTE_MODULE",
    "DEFAULT_INVENTAR_BLUEPRINT_ATTRIBUTE",
    "DEFAULT_INVENTAR_ROUTE_MODULE",
    "DEFAULT_INVENTAR_USER_BLUEPRINT_ATTRIBUTE",
    "DEFAULT_INVENTAR_USER_ROUTE_MODULE",
    "DEFAULT_LIBRARY_BLUEPRINT_ATTRIBUTE",
    "DEFAULT_LIBRARY_ROUTE_MODULE",
    "DEFAULT_OPTIONAL_BLUEPRINTS",
    "DEFAULT_REQUIRED_BLUEPRINTS",
    "DEFAULT_TAXONOMY_BLUEPRINT_ATTRIBUTE",
    "DEFAULT_TAXONOMY_ROUTE_MODULE",
    "DEFAULT_VPLIB_BLUEPRINT_ATTRIBUTE",
    "DEFAULT_VPLIB_ROUTE_MODULE",
    "EXTENSION_REGISTRY_KEY",
    "ROUTES_COMPONENT_NAME",
    "ROUTES_PACKAGE_SCHEMA_VERSION",
    "ROUTES_PACKAGE_VERSION",
    "BlueprintRegistrationResult",
    "BlueprintResolutionResult",
    "BlueprintSpec",
    "RouteRegistryError",
    "clean_optional_string",
    "clean_required_string",
    "clear_route_registry_caches",
    "dataclass_to_dict_safe",
    "exception_to_dict",
    "get_blueprint_registry_snapshot",
    "get_blueprint_specs",
    "get_optional_blueprint_keys",
    "get_registered_blueprint_names",
    "get_required_blueprint_keys",
    "get_routes_health",
    "iter_blueprint_specs",
    "normalize_metadata",
    "normalize_metadata_value",
    "register_blueprints",
    "reset_route_registry_state",
    "resolve_all_blueprint_specs",
    "resolve_blueprint_spec",
    "safe_tuple",
    "utc_now_iso",
]