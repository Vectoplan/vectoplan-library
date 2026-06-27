# services/vectoplan-library/src/routes/inventar_user.py
"""
User-Inventar API routes for vectoplan-library.

Diese Route ist der HTTP-Adapter für das persistierte User-Inventar.

Ziel:

    /user-inventar
        -> static/js/inventar/user-inventory.js
        -> /api/v1/vplib/inventar_user/*
        -> library.services.user_inventory_service
        -> library.repositories.user_inventory_repository
        -> models.user_inventory
        -> PostgreSQL

Phase 1:
- user_id standardmäßig 1.
- inventory_key standardmäßig "default".
- exakt 9 Hotbar-Slots.
- Mausrad-/Frontend-Auswahl wird über select-slot persistiert.

Wichtig:
- Keine SQLAlchemy-Queries in dieser Route.
- Keine DB-Session in dieser Route.
- Keine Model-Logik in dieser Route.
- Keine Fallback-HTML-Seite.
- Keine Mock-Daten.
- Route bleibt HTTP-nah und delegiert an den Service.
"""

from __future__ import annotations

from functools import lru_cache
from typing import Any, Mapping

from flask import Blueprint, Response, jsonify, request


INVENTAR_USER_ROUTE_VERSION = "vectoplan_library.routes.inventar_user.v1"
INVENTAR_USER_COMPONENT = "inventar-user-route"

INVENTAR_USER_API_PREFIX = "/api/v1/vplib/inventar_user"
DEFAULT_USER_ID = 1
DEFAULT_INVENTORY_KEY = "default"


inventar_user_bp = Blueprint(
    "inventar_user",
    __name__,
    url_prefix=INVENTAR_USER_API_PREFIX,
)


# ---------------------------------------------------------------------------
# Service loading
# ---------------------------------------------------------------------------

@lru_cache(maxsize=1)
def _load_service() -> Any:
    """
    Lädt den User-Inventar-Service defensiv.

    Unterstützte Startkontexte:
    - Flask-App aus services/vectoplan-library/src
    - Docker/Werkzeug
    - Tests
    - mögliche spätere Package-Imports
    """

    errors: list[str] = []

    for import_path in (
        "library.services.user_inventory_service",
        "src.library.services.user_inventory_service",
        "vectoplan_library.library.services.user_inventory_service",
    ):
        try:
            module = __import__(
                import_path,
                fromlist=[
                    "get_inventory_response",
                    "select_slot_response",
                    "set_slot_response",
                    "clear_slot_response",
                    "clear_cache_response",
                    "get_service_health_response",
                ],
            )

            required = (
                "get_inventory_response",
                "select_slot_response",
                "set_slot_response",
                "clear_slot_response",
                "clear_cache_response",
                "get_service_health_response",
            )

            missing = [name for name in required if not hasattr(module, name)]
            if missing:
                errors.append(f"{import_path}: missing {', '.join(missing)}")
                continue

            return module

        except Exception as exc:
            errors.append(f"{import_path}: {type(exc).__name__}: {exc}")

    raise RuntimeError(
        "Could not import user inventory service. "
        f"Import attempts: {'; '.join(errors)}"
    )


def _service_available() -> bool:
    try:
        _load_service()
        return True
    except Exception:
        return False


# ---------------------------------------------------------------------------
# Routes
# ---------------------------------------------------------------------------

@inventar_user_bp.get("/health")
def inventar_user_health() -> Response:
    """
    Health für Route, Service, Repository und Model-Anbindung.
    """

    try:
        service = _load_service()
        payload = service.get_service_health_response()
        return _json_route_response(payload)

    except Exception as exc:
        payload = _failure_payload(
            route="health",
            code="inventar_user_health_failed",
            message="User-Inventar-Health konnte nicht erzeugt werden.",
            exc=exc,
            http_status=500,
        )
        return _json_response(payload, 500)


@inventar_user_bp.get("/")
@inventar_user_bp.get("")
def inventar_user_index() -> Response:
    """
    Kleiner API-Index und zugleich aktueller Inventar-Zustand.

    Query:
        ?user_id=1
        ?inventory_key=default
    """

    if not _service_available():
        return _service_unavailable_response(route="index")

    try:
        service = _load_service()
        payload = service.get_inventory_response(_request_payload())
        return _json_route_response(payload)

    except Exception as exc:
        payload = _failure_payload(
            route="index",
            code="inventar_user_index_failed",
            message="User-Inventar konnte nicht geladen werden.",
            exc=exc,
            http_status=500,
        )
        return _json_response(payload, 500)


@inventar_user_bp.get("/state")
def inventar_user_state() -> Response:
    """
    Aktueller User-Inventar-State inklusive 9 Slots.

    Query:
        ?user_id=1
        ?inventory_key=default
    """

    if not _service_available():
        return _service_unavailable_response(route="state")

    try:
        service = _load_service()
        payload = service.get_inventory_response(_request_payload())
        return _json_route_response(payload)

    except Exception as exc:
        payload = _failure_payload(
            route="state",
            code="inventar_user_state_failed",
            message="User-Inventar-State konnte nicht geladen werden.",
            exc=exc,
            http_status=500,
        )
        return _json_response(payload, 500)


@inventar_user_bp.get("/slots")
def inventar_user_slots() -> Response:
    """
    Aktuelle 9 Slots.

    Die Response bleibt identisch zum State-Endpunkt, damit das Frontend nur ein
    Datenformat verarbeiten muss.
    """

    if not _service_available():
        return _service_unavailable_response(route="slots")

    try:
        service = _load_service()
        payload = service.get_inventory_response(_request_payload())
        return _json_route_response(payload)

    except Exception as exc:
        payload = _failure_payload(
            route="slots",
            code="inventar_user_slots_failed",
            message="User-Inventar-Slots konnten nicht geladen werden.",
            exc=exc,
            http_status=500,
        )
        return _json_response(payload, 500)


@inventar_user_bp.post("/select-slot")
@inventar_user_bp.patch("/select-slot")
def inventar_user_select_slot() -> Response:
    """
    Persistiert den aktuell ausgewählten Slot.

    Body:
        {
            "user_id": 1,
            "inventory_key": "default",
            "slot_index": 3
        }

    Query-Fallback:
        ?user_id=1&inventory_key=default&slot_index=3
    """

    if not _service_available():
        return _service_unavailable_response(route="select-slot")

    try:
        service = _load_service()
        payload = service.select_slot_response(_request_payload())
        return _json_route_response(payload)

    except Exception as exc:
        payload = _failure_payload(
            route="select-slot",
            code="inventar_user_select_slot_failed",
            message="Inventar-Slot konnte nicht ausgewählt werden.",
            exc=exc,
            http_status=422,
        )
        return _json_response(payload, 422)


@inventar_user_bp.put("/slots/<int:slot_index>")
@inventar_user_bp.patch("/slots/<int:slot_index>")
def inventar_user_set_slot(slot_index: int) -> Response:
    """
    Setzt oder ersetzt den Inhalt eines Slots.

    Body:
        {
            "user_id": 1,
            "inventory_key": "default",
            "item": {
                "vplib_uid": "...",
                "family_id": "...",
                "variant_id": "default",
                "label": "..."
            },
            "select": true
        }
    """

    if not _service_available():
        return _service_unavailable_response(route="set-slot")

    try:
        service = _load_service()
        payload = service.set_slot_response(slot_index, _request_payload())
        return _json_route_response(payload)

    except Exception as exc:
        payload = _failure_payload(
            route="set-slot",
            code="inventar_user_set_slot_failed",
            message="Inventar-Slot konnte nicht gesetzt werden.",
            exc=exc,
            http_status=422,
        )
        return _json_response(payload, 422)


@inventar_user_bp.delete("/slots/<int:slot_index>")
def inventar_user_clear_slot(slot_index: int) -> Response:
    """
    Leert einen Slot.

    Body optional:
        {
            "user_id": 1,
            "inventory_key": "default",
            "select": true
        }
    """

    if not _service_available():
        return _service_unavailable_response(route="clear-slot")

    try:
        service = _load_service()
        payload = service.clear_slot_response(slot_index, _request_payload())
        return _json_route_response(payload)

    except Exception as exc:
        payload = _failure_payload(
            route="clear-slot",
            code="inventar_user_clear_slot_failed",
            message="Inventar-Slot konnte nicht geleert werden.",
            exc=exc,
            http_status=422,
        )
        return _json_response(payload, 422)


@inventar_user_bp.post("/cache/clear")
def inventar_user_cache_clear() -> Response:
    """
    Leert Service-/Repository-Caches.

    Nützlich für lokale Entwicklung und Hot-Reload-Szenarien.
    """

    if not _service_available():
        return _service_unavailable_response(route="cache-clear")

    try:
        service = _load_service()
        payload = service.clear_cache_response()
        _clear_route_caches()
        return _json_route_response(payload)

    except Exception as exc:
        payload = _failure_payload(
            route="cache-clear",
            code="inventar_user_cache_clear_failed",
            message="User-Inventar-Caches konnten nicht geleert werden.",
            exc=exc,
            http_status=500,
        )
        return _json_response(payload, 500)


# ---------------------------------------------------------------------------
# Request / response helpers
# ---------------------------------------------------------------------------

def _request_payload() -> dict[str, Any]:
    """
    Sammelt Query-, JSON- und Form-Daten in einem Payload.

    Reihenfolge:
    1. Defaults
    2. Query
    3. JSON
    4. Form

    Form überschreibt JSON, Query überschreibt Defaults.
    """

    payload: dict[str, Any] = {
        "user_id": DEFAULT_USER_ID,
        "inventory_key": DEFAULT_INVENTORY_KEY,
    }

    try:
        payload.update(_mapping_to_plain_dict(request.args))
    except Exception:
        pass

    try:
        if request.is_json:
            body = request.get_json(silent=True)
            if isinstance(body, Mapping):
                payload.update(_mapping_to_plain_dict(body))
    except Exception:
        pass

    try:
        if request.form:
            payload.update(_mapping_to_plain_dict(request.form))
    except Exception:
        pass

    return payload


def _mapping_to_plain_dict(mapping: Mapping[str, Any]) -> dict[str, Any]:
    """
    Wandelt MultiDict/Mapping defensiv in dict.
    """

    result: dict[str, Any] = {}

    for key, value in mapping.items():
        key_text = str(key)

        getlist = getattr(mapping, "getlist", None)

        if callable(getlist):
            try:
                values = getlist(key)

                if len(values) == 1:
                    result[key_text] = values[0]
                elif len(values) > 1:
                    result[key_text] = list(values)
                else:
                    result[key_text] = value

                continue

            except Exception:
                pass

        if isinstance(value, tuple):
            result[key_text] = list(value)
        else:
            result[key_text] = value

    return result


def _json_route_response(payload: Any) -> Response:
    """
    Baut eine Flask-JSON-Response aus Service-Payload.
    """

    safe_payload = _payload_to_dict(payload)
    status_code = _safe_http_status(safe_payload.get("_http_status", 200))
    return _json_response(safe_payload, status_code)


def _json_response(payload: Mapping[str, Any], status_code: int = 200) -> Response:
    """
    Einheitliche JSON-Response.
    """

    response = jsonify(_json_safe(dict(payload)))
    response.status_code = _safe_http_status(status_code)
    response.headers["Cache-Control"] = "no-store"
    response.headers["X-VECTOPLAN-Inventar-User-Route"] = INVENTAR_USER_ROUTE_VERSION
    response.headers["X-VECTOPLAN-Inventar-User-Component"] = INVENTAR_USER_COMPONENT
    return response


def _payload_to_dict(payload: Any) -> dict[str, Any]:
    """
    Normalisiert Service-Payload zu dict.
    """

    if isinstance(payload, Mapping):
        return dict(payload)

    if hasattr(payload, "to_dict") and callable(payload.to_dict):
        try:
            value = payload.to_dict()
            if isinstance(value, Mapping):
                return dict(value)
        except Exception:
            pass

    return _failure_payload(
        route="unknown",
        code="invalid_service_payload",
        message="User-Inventar-Service hat einen unerwarteten Payload geliefert.",
        details={
            "payload_type": type(payload).__name__,
            "payload_repr": repr(payload),
        },
        http_status=500,
    )


def _service_unavailable_response(*, route: str) -> Response:
    """
    Response, wenn der Service nicht importierbar ist.
    """

    try:
        _load_service()
        details: dict[str, Any] = {"available": True}
    except Exception as exc:
        details = {
            "available": False,
            "exception_type": type(exc).__name__,
            "exception": str(exc),
        }

    payload = _failure_payload(
        route=route,
        code="user_inventory_service_unavailable",
        message="User-Inventar-Service konnte nicht geladen werden.",
        details={
            "dependency": "library.services.user_inventory_service",
            **details,
        },
        http_status=503,
    )
    return _json_response(payload, 503)


def _failure_payload(
    *,
    route: str,
    code: str,
    message: str,
    exc: BaseException | None = None,
    details: Mapping[str, Any] | None = None,
    http_status: int = 500,
) -> dict[str, Any]:
    """
    Einheitlicher Fehler-Payload.
    """

    issue_details: dict[str, Any] = dict(details or {})

    if exc is not None:
        issue_details["exception_type"] = type(exc).__name__
        issue_details["exception"] = str(exc)

    return {
        "ok": False,
        "healthy": False,
        "status": "error",
        "route": route,
        "component": INVENTAR_USER_COMPONENT,
        "version": INVENTAR_USER_ROUTE_VERSION,
        "data": {},
        "errors": [
            {
                "severity": "error",
                "code": code,
                "field": route,
                "message": message,
                "details": _json_safe(issue_details),
            }
        ],
        "warnings": [],
        "info": [],
        "_http_status": _safe_http_status(http_status),
    }


def _safe_http_status(value: Any) -> int:
    """
    Normalisiert HTTP-Status.
    """

    try:
        status = int(value)
    except Exception:
        return 500

    if status < 100 or status > 599:
        return 500

    return status


def _json_safe(value: Any) -> Any:
    """
    Macht Werte JSON-kompatibel.
    """

    if value is None or isinstance(value, (str, int, float, bool)):
        return value

    if isinstance(value, Mapping):
        return {str(key): _json_safe(child_value) for key, child_value in value.items()}

    if isinstance(value, tuple):
        return [_json_safe(item) for item in value]

    if isinstance(value, list):
        return [_json_safe(item) for item in value]

    if isinstance(value, set):
        return [_json_safe(item) for item in sorted(value, key=str)]

    if hasattr(value, "to_dict") and callable(value.to_dict):
        try:
            return _json_safe(value.to_dict())
        except Exception:
            return str(value)

    return str(value)


def _clear_route_caches() -> None:
    """
    Leert Route-interne Caches.
    """

    try:
        _load_service.cache_clear()
    except Exception:
        pass


__all__ = [
    "DEFAULT_INVENTORY_KEY",
    "DEFAULT_USER_ID",
    "INVENTAR_USER_API_PREFIX",
    "INVENTAR_USER_COMPONENT",
    "INVENTAR_USER_ROUTE_VERSION",
    "inventar_user_bp",
    "inventar_user_cache_clear",
    "inventar_user_clear_slot",
    "inventar_user_health",
    "inventar_user_index",
    "inventar_user_select_slot",
    "inventar_user_set_slot",
    "inventar_user_slots",
    "inventar_user_state",
]