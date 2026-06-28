# services/vectoplan-library/routes/vplib_routes.py
"""
Flask routes for VPLIB creation and diagnostics.

Diese Datei stellt die HTTP-Routen für den VPLIB-Kern bereit.

Blueprint:
    vplib_bp

Default Prefix:
    /api/v1/vplib

Routen:
    GET  /test
    GET  /health
    POST /create
    POST /create/dry-run

Wichtig:
Die fachliche Logik liegt in services/vplib_route_service.py.
Diese Datei bleibt bewusst dünn und übersetzt nur HTTP <-> Service-Result.

Robustheitsziele:
- keine Funktion wird vor ihrer Definition verwendet
- Settings werden robust über src.config.vplib_settings bevorzugt geladen
- config.py im Service-Root blockiert nicht mehr config/vplib_settings.py
- Routen liefern immer JSON
- Exceptions werden als JSON serialisiert
- keine Editor-Abhängigkeiten

Technische Namen, JSON-Keys und Variablen bleiben Englisch.
"""

from __future__ import annotations

import importlib
from dataclasses import dataclass, field
from functools import lru_cache
from typing import Any, Final, Mapping

from flask import Blueprint, Response, jsonify, request


VPLIB_ROUTES_SCHEMA_VERSION: Final[str] = "vplib.routes.v1"
DEFAULT_BLUEPRINT_NAME: Final[str] = "vplib"
DEFAULT_ROUTE_PREFIX: Final[str] = "/api/v1/vplib"

SETTINGS_MODULE_CANDIDATES: Final[tuple[str, ...]] = (
    "src.config.vplib_settings",
    "config.vplib_settings",
)

ROUTE_SERVICE_MODULE_CANDIDATES: Final[tuple[str, ...]] = (
    "services.vplib_route_service",
    "src.services.vplib_route_service",
)


class VplibRoutesError(RuntimeError):
    """Wird ausgelöst, wenn die VPLIB-Routenschicht fehlschlägt."""


@dataclass(frozen=True, slots=True)
class VplibHttpResponse:
    """Interne HTTP-Antwortstruktur."""

    payload: Mapping[str, Any]
    status_code: int = 200
    headers: Mapping[str, str] = field(default_factory=dict)

    def normalized(self) -> "VplibHttpResponse":
        status_code = normalize_status_code(self.status_code)

        return VplibHttpResponse(
            payload=normalize_json_mapping(self.payload),
            status_code=status_code,
            headers={
                str(key): str(value)
                for key, value in dict(self.headers or {}).items()
            },
        )

    def to_flask_response(self) -> tuple[Response, int, dict[str, str]]:
        normalized = self.normalized()
        return jsonify(normalized.payload), normalized.status_code, dict(normalized.headers)


def normalize_status_code(value: Any) -> int:
    """Normalisiert HTTP-Statuscode defensiv."""
    try:
        status_code = int(value)
    except Exception:
        return 500

    if status_code < 100 or status_code > 599:
        return 500

    return status_code


def normalize_route_prefix(value: Any) -> str:
    """Normalisiert Route-Prefix."""
    raw = str(value or DEFAULT_ROUTE_PREFIX).strip()

    if not raw:
        raw = DEFAULT_ROUTE_PREFIX

    if not raw.startswith("/"):
        raw = f"/{raw}"

    return raw.rstrip("/") or DEFAULT_ROUTE_PREFIX


def normalize_json_mapping(value: Mapping[str, Any]) -> dict[str, Any]:
    """Normalisiert Mapping JSON-kompatibel."""
    if not isinstance(value, Mapping):
        raise VplibRoutesError("value must be a mapping.")

    return {
        str(key): normalize_json_value(child_value)
        for key, child_value in value.items()
    }


def normalize_json_value(value: Any) -> Any:
    """Normalisiert Werte JSON-kompatibel."""
    if value is None:
        return None

    if isinstance(value, (str, int, float, bool)):
        return value

    if isinstance(value, Mapping):
        return normalize_json_mapping(value)

    if isinstance(value, (list, tuple, set)):
        return [normalize_json_value(item) for item in value]

    if hasattr(value, "to_dict"):
        try:
            return normalize_json_value(value.to_dict())
        except Exception:
            return str(value)

    return str(value)


def normalize_enum_key(value: Any) -> str:
    """Normalisiert Enum-ähnliche Werte."""
    raw = str(value).strip()

    if not raw:
        raise VplibRoutesError("Enum value is required.")

    return (
        raw.lower()
        .replace(" ", "_")
        .replace("-", "_")
        .replace("/", "_")
        .replace("\\", "_")
    )


@lru_cache(maxsize=128)
def parse_bool_value(value: Any) -> bool:
    """Parst boolesche Werte robust."""
    if isinstance(value, bool):
        return value

    raw = normalize_enum_key(value)

    if raw in {"1", "true", "yes", "y", "on", "enabled"}:
        return True

    if raw in {"0", "false", "no", "n", "off", "disabled"}:
        return False

    raise VplibRoutesError(f"Invalid boolean value {value!r}.")


def parse_query_bool(name: str, *, default: bool) -> bool:
    """Parst booleschen Query-Parameter."""
    value = request.args.get(name)

    if value is None:
        return bool(default)

    return parse_bool_value(value)


@lru_cache(maxsize=16)
def import_first_available_module(module_names: tuple[str, ...]) -> Any:
    """Importiert das erste verfügbare Modul aus Kandidaten."""
    errors: list[str] = []

    for module_name in module_names:
        try:
            return importlib.import_module(module_name)
        except Exception as exc:
            errors.append(f"{module_name}: {exc}")

    raise VplibRoutesError(
        "None of the candidate modules could be imported: " + " | ".join(errors)
    )


@lru_cache(maxsize=1)
def get_settings_module_safe() -> Any:
    """Lädt das VPLIB-Settings-Modul robust."""
    return import_first_available_module(SETTINGS_MODULE_CANDIDATES)


@lru_cache(maxsize=1)
def get_route_service_module_safe() -> Any:
    """Lädt das VPLIB-Route-Service-Modul robust."""
    return import_first_available_module(ROUTE_SERVICE_MODULE_CANDIDATES)


@lru_cache(maxsize=1)
def get_settings_safe() -> Any:
    """
    Lädt VPLIB-Settings defensiv und cached sie.

    Wichtig:
    src.config.vplib_settings wird bevorzugt, weil root config.py sonst
    config.vplib_settings blockieren kann.
    """
    try:
        module = get_settings_module_safe()
        getter = getattr(module, "get_vplib_settings", None)

        if not callable(getter):
            raise VplibRoutesError("Settings module does not export callable get_vplib_settings().")

        settings = getter()
        return settings.normalized() if hasattr(settings, "normalized") else settings
    except Exception as exc:
        raise VplibRoutesError(f"Could not load VPLIB route settings: {exc}") from exc


def reload_route_settings() -> Any:
    """Leert lokalen Settings-Cache und lädt Settings neu."""
    clear_vplib_route_caches()
    return get_settings_safe()


def get_route_prefix_safe() -> str:
    """Liest Route-Prefix defensiv."""
    try:
        settings = get_settings_safe()
        prefix = getattr(settings, "route_prefix", DEFAULT_ROUTE_PREFIX)
        return normalize_route_prefix(prefix)
    except Exception:
        return DEFAULT_ROUTE_PREFIX


def is_test_route_enabled() -> bool:
    """Prüft Settings für Test-Route."""
    try:
        return bool(get_settings_safe().test_route_enabled)
    except Exception:
        return True


def is_create_route_enabled() -> bool:
    """Prüft Settings für Create-Route."""
    try:
        return bool(get_settings_safe().create_route_enabled)
    except Exception:
        return True


def get_request_json_payload() -> dict[str, Any]:
    """Liest und validiert JSON-Payload aus Flask request."""
    if not request.is_json:
        raise VplibRoutesError("Request Content-Type must be application/json.")

    payload = request.get_json(silent=False)

    if payload is None:
        raise VplibRoutesError("JSON payload is required.")

    if not isinstance(payload, Mapping):
        raise VplibRoutesError("JSON payload must be an object.")

    return normalize_json_mapping(payload)


def error_payload_from_exception(
    exc: BaseException,
    *,
    source: str,
    include_traceback: bool = False,
    code: str = "VPLIB_ROUTE_EXCEPTION",
) -> dict[str, Any]:
    """Serialisiert Exception JSON-kompatibel."""
    payload: dict[str, Any] = {
        "code": code,
        "message": str(exc) or exc.__class__.__name__,
        "source": source,
        "details": {
            "exception_type": exc.__class__.__name__,
        },
    }

    if include_traceback:
        import traceback

        payload["traceback"] = traceback.format_exc()

    return payload


def exception_response(
    exc: BaseException,
    *,
    route: str,
    include_traceback: bool = False,
) -> VplibHttpResponse:
    """Wandelt unerwartete Route-Exceptions in JSON um."""
    return VplibHttpResponse(
        payload={
            "schema_version": VPLIB_ROUTES_SCHEMA_VERSION,
            "ok": False,
            "status": "failed",
            "route": route,
            "errors": [
                error_payload_from_exception(
                    exc,
                    source="vplib_routes",
                    include_traceback=include_traceback,
                )
            ],
        },
        status_code=500,
    ).normalized()


def response_from_service_result(
    result: Mapping[str, Any],
    *,
    success_status: int = 200,
    error_status: int = 500,
    route_name: str = "unknown",
) -> VplibHttpResponse:
    """Wandelt Service-Result in Flask-kompatible Antwort um."""
    payload = normalize_json_mapping(result)
    ok = bool(payload.get("ok", False))

    return VplibHttpResponse(
        payload=payload,
        status_code=success_status if ok else error_status,
        headers={
            "X-VPLIB-Route": str(payload.get("action") or route_name),
        },
    ).normalized()


def route_disabled_response(route_name: str) -> VplibHttpResponse:
    """Antwort für deaktivierte Routen."""
    return VplibHttpResponse(
        payload={
            "schema_version": VPLIB_ROUTES_SCHEMA_VERSION,
            "ok": False,
            "status": "disabled",
            "route": route_name,
            "errors": [
                {
                    "code": "VPLIB_ROUTE_DISABLED",
                    "message": f"VPLIB route {route_name!r} is disabled by settings.",
                    "source": "vplib_routes",
                    "details": {},
                }
            ],
        },
        status_code=404,
    ).normalized()


def create_vplib_blueprint() -> Blueprint:
    """
    Erstellt den VPLIB-Blueprint.

    Der Prefix wird aus src.config.vplib_settings gelesen.
    Wenn Settings fehlschlagen, wird /api/v1/vplib verwendet.
    """
    return Blueprint(
        DEFAULT_BLUEPRINT_NAME,
        __name__,
        url_prefix=get_route_prefix_safe(),
    )


# Wichtig:
# Der Blueprint wird erst nach Definition aller benötigten Helper erzeugt.
vplib_bp = create_vplib_blueprint()


@vplib_bp.get("/test")
def vplib_test_route() -> tuple[Response, int, dict[str, str]]:
    """
    Führt den VPLIB-Self-Test aus.

    Beispiel:
        GET /api/v1/vplib/test

    Query-Parameter:
        include_traceback=true|false
        dry_run=true|false
    """
    include_traceback = False

    try:
        include_traceback = parse_query_bool("include_traceback", default=False)

        if not is_test_route_enabled():
            return route_disabled_response("test").to_flask_response()

        dry_run = parse_query_bool("dry_run", default=True)
        service_module = get_route_service_module_safe()
        runner = getattr(service_module, "run_vplib_self_test", None)

        if not callable(runner):
            raise VplibRoutesError("Route service does not export callable run_vplib_self_test().")

        result = runner(
            settings=get_settings_safe(),
            include_traceback=include_traceback,
            dry_run=dry_run,
        )

        return response_from_service_result(
            result,
            success_status=200,
            error_status=500,
            route_name="test",
        ).to_flask_response()
    except Exception as exc:
        return exception_response(
            exc,
            route="/test",
            include_traceback=include_traceback,
        ).to_flask_response()


@vplib_bp.get("/health")
def vplib_health_route() -> tuple[Response, int, dict[str, str]]:
    """
    Gibt einen leichten VPLIB-Health-Snapshot zurück.

    Beispiel:
        GET /api/v1/vplib/health
    """
    include_traceback = False

    try:
        include_traceback = parse_query_bool("include_traceback", default=False)

        payload: dict[str, Any] = {
            "schema_version": VPLIB_ROUTES_SCHEMA_VERSION,
            "ok": True,
            "status": "ok",
            "route": "/health",
            "settings": None,
            "vplib": None,
            "errors": [],
            "warnings": [],
            "metadata": {
                "settings_module_candidates": list(SETTINGS_MODULE_CANDIDATES),
                "route_service_module_candidates": list(ROUTE_SERVICE_MODULE_CANDIDATES),
                "route_prefix": get_route_prefix_safe(),
            },
        }

        try:
            settings = get_settings_safe()
            payload["settings"] = settings.to_dict() if hasattr(settings, "to_dict") else str(settings)
        except Exception as exc:
            payload["ok"] = False
            payload["status"] = "failed"
            payload["errors"].append(
                error_payload_from_exception(
                    exc,
                    source="settings",
                    include_traceback=include_traceback,
                    code="VPLIB_ROUTE_SETTINGS_FAILED",
                )
            )

        try:
            import vplib

            health = vplib.get_vplib_health()
            payload["vplib"] = normalize_json_value(health)

            if isinstance(health, Mapping) and health.get("healthy") is False:
                payload["ok"] = False
                payload["status"] = "failed"
                payload["warnings"].append("VPLIB health reported unhealthy state.")
        except Exception as exc:
            payload["ok"] = False
            payload["status"] = "failed"
            payload["errors"].append(
                error_payload_from_exception(
                    exc,
                    source="vplib",
                    include_traceback=include_traceback,
                    code="VPLIB_ROUTE_VPLIB_HEALTH_FAILED",
                )
            )

        return response_from_service_result(
            payload,
            success_status=200,
            error_status=500,
            route_name="health",
        ).to_flask_response()
    except Exception as exc:
        return exception_response(
            exc,
            route="/health",
            include_traceback=include_traceback,
        ).to_flask_response()


@vplib_bp.post("/create")
def vplib_create_route() -> tuple[Response, int, dict[str, str]]:
    """
    Erstellt ein VPLIB-Package aus JSON-Payload.

    Beispiel:
        POST /api/v1/vplib/create

    Payload:
        {
          "request": {...},
          "options": {
            "dry_run": true,
            "write_mode": "fail",
            "create_archive": false
          }
        }
    """
    include_traceback = False

    try:
        include_traceback = parse_query_bool("include_traceback", default=False)

        if not is_create_route_enabled():
            return route_disabled_response("create").to_flask_response()

        payload = get_request_json_payload()
        service_module = get_route_service_module_safe()
        creator = getattr(service_module, "create_vplib_from_payload", None)

        if not callable(creator):
            raise VplibRoutesError("Route service does not export callable create_vplib_from_payload().")

        result = creator(
            payload,
            settings=get_settings_safe(),
            include_traceback=include_traceback,
        )

        result_ok = bool(result.get("ok")) if isinstance(result, Mapping) else False

        return response_from_service_result(
            result,
            success_status=201 if result_ok else 500,
            error_status=500,
            route_name="create",
        ).to_flask_response()
    except Exception as exc:
        return exception_response(
            exc,
            route="/create",
            include_traceback=include_traceback,
        ).to_flask_response()


@vplib_bp.post("/create/dry-run")
def vplib_create_dry_run_route() -> tuple[Response, int, dict[str, str]]:
    """
    Führt eine erzwungene Dry-Run-Erstellung aus.

    Beispiel:
        POST /api/v1/vplib/create/dry-run

    Diese Route überschreibt payload.options.dry_run immer auf true.
    """
    include_traceback = False

    try:
        include_traceback = parse_query_bool("include_traceback", default=False)

        if not is_create_route_enabled():
            return route_disabled_response("create").to_flask_response()

        payload = get_request_json_payload()
        service_module = get_route_service_module_safe()
        creator = getattr(service_module, "create_vplib_dry_run_from_payload", None)

        if not callable(creator):
            raise VplibRoutesError("Route service does not export callable create_vplib_dry_run_from_payload().")

        result = creator(
            payload,
            settings=get_settings_safe(),
            include_traceback=include_traceback,
        )

        return response_from_service_result(
            result,
            success_status=200,
            error_status=500,
            route_name="create_dry_run",
        ).to_flask_response()
    except Exception as exc:
        return exception_response(
            exc,
            route="/create/dry-run",
            include_traceback=include_traceback,
        ).to_flask_response()


def clear_vplib_route_caches() -> None:
    """Leert Route-Caches."""
    import_first_available_module.cache_clear()
    get_settings_module_safe.cache_clear()
    get_route_service_module_safe.cache_clear()
    get_settings_safe.cache_clear()
    parse_bool_value.cache_clear()


__all__ = [
    "DEFAULT_BLUEPRINT_NAME",
    "DEFAULT_ROUTE_PREFIX",
    "ROUTE_SERVICE_MODULE_CANDIDATES",
    "SETTINGS_MODULE_CANDIDATES",
    "VPLIB_ROUTES_SCHEMA_VERSION",
    "VplibHttpResponse",
    "VplibRoutesError",
    "clear_vplib_route_caches",
    "create_vplib_blueprint",
    "error_payload_from_exception",
    "exception_response",
    "get_request_json_payload",
    "get_route_prefix_safe",
    "get_route_service_module_safe",
    "get_settings_module_safe",
    "get_settings_safe",
    "import_first_available_module",
    "is_create_route_enabled",
    "is_test_route_enabled",
    "normalize_enum_key",
    "normalize_json_mapping",
    "normalize_json_value",
    "normalize_route_prefix",
    "normalize_status_code",
    "parse_bool_value",
    "parse_query_bool",
    "reload_route_settings",
    "response_from_service_result",
    "route_disabled_response",
    "vplib_bp",
    "vplib_create_dry_run_route",
    "vplib_create_route",
    "vplib_health_route",
    "vplib_test_route",
]