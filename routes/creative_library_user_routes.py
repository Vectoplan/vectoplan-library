# services/vectoplan-library/routes/creative_library_user_routes.py
"""
Flask routes for VECTOPLAN Creative Library User Overlay.

Route prefix:
- /api/v1/vplib/creative-library

This route layer is intentionally thin:

- parse Flask request args/json
- call src.library.services.creative_library_user_service.CreativeLibraryUserService
- jsonify returned dictionaries
- map exceptions to API-safe JSON responses

Business logic lives in:
- src/library/services/creative_library_user_service.py
- src/library/repositories/creative_library_user_repository.py

Supported workflows:

- resolved Creative Library for user_id
- Creative Inventory for user_id
- user collections
- collection items
- add/remove item
- hide/restore published item via user override
- favorite/unfavorite item
- pin/unpin item
- rename/reorder item
- user overrides
- user audit
"""

from __future__ import annotations

import importlib
import logging
from functools import lru_cache
from types import ModuleType
from typing import Any, Callable, Dict, Mapping

from flask import Blueprint, Response, jsonify, request


CREATIVE_LIBRARY_USER_ROUTES_COMPONENT = "routes.creative_library_user_routes"
CREATIVE_LIBRARY_USER_ROUTES_VERSION = "1.0.0"
CREATIVE_LIBRARY_USER_ROUTE_PREFIX = "/api/v1/vplib/creative-library"

_LOGGER = logging.getLogger(__name__)


creative_library_user_bp = Blueprint(
    "creative_library_user",
    __name__,
    url_prefix=CREATIVE_LIBRARY_USER_ROUTE_PREFIX,
)

creative_library_user_routes_bp = creative_library_user_bp
creative_user_bp = creative_library_user_bp
user_library_bp = creative_library_user_bp

bp = creative_library_user_bp
blueprint = creative_library_user_bp


# ---------------------------------------------------------------------------
# Lazy service imports
# ---------------------------------------------------------------------------

@lru_cache(maxsize=1)
def _load_user_service_module() -> ModuleType:
    """Loads creative_library_user_service defensively."""
    errors: list[str] = []

    for module_name in (
        "src.library.services.creative_library_user_service",
        "library.services.creative_library_user_service",
        "vectoplan_library.src.library.services.creative_library_user_service",
        "vectoplan_library.library.services.creative_library_user_service",
    ):
        try:
            return importlib.import_module(module_name)
        except Exception as exc:
            errors.append(f"{module_name}: {type(exc).__name__}: {exc}")

    raise ImportError(
        "Could not import creative_library_user_service. "
        + " | ".join(errors)
    )


def _create_user_service() -> Any:
    """Creates CreativeLibraryUserService per request."""
    module = _load_user_service_module()

    factory = getattr(module, "create_creative_library_user_service", None)
    if callable(factory):
        return factory()

    service_class = getattr(module, "CreativeLibraryUserService", None)
    if service_class is None:
        raise RuntimeError("CreativeLibraryUserService is not available.")

    return service_class()


# ---------------------------------------------------------------------------
# Diagnostics
# ---------------------------------------------------------------------------

@creative_library_user_bp.get("/health")
def creative_library_user_health() -> Response:
    return _json_response(get_creative_library_user_routes_health())


@creative_library_user_bp.get("/routes")
def creative_library_user_routes_map() -> Response:
    return _json_response(get_creative_library_user_route_map_response())


@creative_library_user_bp.get("/selftest")
def creative_library_user_selftest() -> Response:
    return _json_response(
        {
            "ok": True,
            "healthy": True,
            "status": "ok",
            "component": CREATIVE_LIBRARY_USER_ROUTES_COMPONENT,
            "version": CREATIVE_LIBRARY_USER_ROUTES_VERSION,
            "route_prefix": CREATIVE_LIBRARY_USER_ROUTE_PREFIX,
            "blueprint": creative_library_user_bp.name,
            "service": _safe_user_service_health(),
        }
    )


@creative_library_user_bp.post("/cache/clear")
def creative_library_user_cache_clear() -> Response:
    return _json_response(clear_creative_library_user_routes_caches())


# ---------------------------------------------------------------------------
# Resolved library / inventory
# ---------------------------------------------------------------------------

@creative_library_user_bp.get("")
@creative_library_user_bp.get("/")
def creative_library_user_root() -> Response:
    """
    Resolved Creative Library for a user.

    GET /api/v1/vplib/creative-library?user_id=1
    """
    return _json_response(
        _safe_service_call(
            lambda service: service.get_resolved_library(
                user_id=_int_arg("user_id", default=1),
                include_hidden=_bool_arg("include_hidden", default=False),
                include_deleted=_bool_arg("include_deleted", default=False),
                include_collections=_bool_arg("include_collections", default=True),
                include_items=_bool_arg("include_items", default=True),
                include_overrides=_bool_arg("include_overrides", default=True),
                include_audit=_bool_arg("include_audit", default=False),
                ensure_defaults=_bool_arg("ensure_defaults", default=True),
            )
        )
    )


@creative_library_user_bp.get("/resolved")
def creative_library_user_resolved() -> Response:
    """Explicit alias for resolved Creative Library."""
    return creative_library_user_root()


@creative_library_user_bp.get("/inventory")
def creative_library_user_inventory() -> Response:
    """
    Creative Inventory payload for user.

    This is the UI-friendly alias for resolved Creative Library.
    """
    return _json_response(
        _safe_service_call(
            lambda service: service.get_creative_inventory(
                user_id=_int_arg("user_id", default=1),
                include_hidden=_bool_arg("include_hidden", default=False),
                include_deleted=_bool_arg("include_deleted", default=False),
            )
        )
    )


@creative_library_user_bp.post("/ensure-defaults")
def creative_library_user_ensure_defaults() -> Response:
    """Ensure default user collections exist."""
    payload = _merged_request_payload()

    return _json_response(
        _safe_service_call(
            lambda service: service.ensure_default_user_collections(
                user_id=payload.get("user_id"),
                commit=True,
            )
        )
    )


# ---------------------------------------------------------------------------
# Collections
# ---------------------------------------------------------------------------

@creative_library_user_bp.get("/collections")
def creative_library_user_collections_list() -> Response:
    """List system/user collections."""
    return _json_response(
        _safe_service_call(
            lambda service: service.list_collections(
                user_id=_int_arg("user_id", default=1),
                include_system=_bool_arg("include_system", default=True),
                include_user=_bool_arg("include_user", default=True),
                include_deleted=_bool_arg("include_deleted", default=False),
                visible_only=_bool_arg("visible_only", default=False),
            )
        )
    )


@creative_library_user_bp.post("/collections")
def creative_library_user_collections_create() -> Response:
    """Create user-owned collection."""
    payload = _merged_request_payload()

    return _json_response(
        _safe_service_call(
            lambda service: service.create_collection(
                payload,
                user_id=payload.get("user_id"),
                commit=True,
            )
        )
    )


@creative_library_user_bp.get("/collections/<path:collection_ref>")
def creative_library_user_collections_get(collection_ref: str) -> Response:
    """Read one resolved collection."""
    return _json_response(
        _safe_service_call(
            lambda service: service.get_collection(
                collection_ref,
                user_id=_int_arg("user_id", default=1),
                include_hidden=_bool_arg("include_hidden", default=False),
                include_deleted=_bool_arg("include_deleted", default=False),
            )
        )
    )


@creative_library_user_bp.patch("/collections/<path:collection_ref>")
def creative_library_user_collections_patch(collection_ref: str) -> Response:
    """Update user-owned collection."""
    payload = _merged_request_payload()

    return _json_response(
        _safe_service_call(
            lambda service: service.update_collection(
                collection_ref,
                payload,
                user_id=payload.get("user_id"),
                commit=True,
            )
        )
    )


@creative_library_user_bp.delete("/collections/<path:collection_ref>")
def creative_library_user_collections_delete(collection_ref: str) -> Response:
    """Soft-delete user-owned collection."""
    payload = _merged_request_payload()

    return _json_response(
        _safe_service_call(
            lambda service: service.delete_collection(
                collection_ref,
                user_id=payload.get("user_id"),
                commit=True,
            )
        )
    )


@creative_library_user_bp.post("/collections/<path:collection_ref>/restore")
def creative_library_user_collections_restore(collection_ref: str) -> Response:
    """Restore user-owned collection."""
    payload = _merged_request_payload()

    return _json_response(
        _safe_service_call(
            lambda service: service.restore_collection(
                collection_ref,
                user_id=payload.get("user_id"),
                commit=True,
            )
        )
    )


@creative_library_user_bp.get("/collections/<path:collection_ref>/items")
def creative_library_user_collection_items_list(collection_ref: str) -> Response:
    """List items for one collection."""
    return _json_response(
        _safe_service_call(
            lambda service: service.get_collection(
                collection_ref,
                user_id=_int_arg("user_id", default=1),
                include_hidden=_bool_arg("include_hidden", default=False),
                include_deleted=_bool_arg("include_deleted", default=False),
            )
        )
    )


@creative_library_user_bp.post("/collections/<path:collection_ref>/items")
def creative_library_user_collection_items_add(collection_ref: str) -> Response:
    """Add item to a specific collection."""
    payload = _merged_request_payload()

    return _json_response(
        _safe_service_call(
            lambda service: service.add_item(
                payload,
                user_id=payload.get("user_id"),
                collection_ref=collection_ref,
                commit=True,
            )
        )
    )


# ---------------------------------------------------------------------------
# Collection items
# ---------------------------------------------------------------------------

@creative_library_user_bp.get("/items")
def creative_library_user_items_list() -> Response:
    """
    List resolved items for current user.

    This route returns the same resolved source as /inventory but item-focused.
    """
    return _json_response(
        _safe_service_call(
            lambda service: service.get_resolved_library(
                user_id=_int_arg("user_id", default=1),
                include_hidden=_bool_arg("include_hidden", default=False),
                include_deleted=_bool_arg("include_deleted", default=False),
                include_collections=False,
                include_items=True,
                include_overrides=_bool_arg("include_overrides", default=True),
                include_audit=False,
                ensure_defaults=_bool_arg("ensure_defaults", default=True),
            )
        )
    )


@creative_library_user_bp.post("/items")
def creative_library_user_items_add() -> Response:
    """Add item to default or given user collection."""
    payload = _merged_request_payload()

    return _json_response(
        _safe_service_call(
            lambda service: service.add_item(
                payload,
                user_id=payload.get("user_id"),
                collection_ref=payload.get("collection_ref") or payload.get("collection_uid") or payload.get("collection_id") or payload.get("collection_key"),
                commit=True,
            )
        )
    )


@creative_library_user_bp.delete("/items")
def creative_library_user_items_remove_by_payload() -> Response:
    """Remove item by identity from given/default collection."""
    payload = _merged_request_payload()

    return _json_response(
        _safe_service_call(
            lambda service: service.remove_item(
                payload,
                user_id=payload.get("user_id"),
                collection_ref=payload.get("collection_ref") or payload.get("collection_uid") or payload.get("collection_id") or payload.get("collection_key"),
                commit=True,
            )
        )
    )


@creative_library_user_bp.post("/items/hide")
def creative_library_user_items_hide_by_identity() -> Response:
    """Hide published/system item for user via override."""
    payload = _merged_request_payload()

    return _json_response(
        _safe_service_call(
            lambda service: service.hide_item(
                payload,
                user_id=payload.get("user_id"),
                commit=True,
            )
        )
    )


@creative_library_user_bp.post("/items/restore")
def creative_library_user_items_restore_by_identity() -> Response:
    """Restore hidden item for user via override."""
    payload = _merged_request_payload()

    return _json_response(
        _safe_service_call(
            lambda service: service.restore_item(
                payload,
                user_id=payload.get("user_id"),
                commit=True,
            )
        )
    )


@creative_library_user_bp.post("/items/favorite")
def creative_library_user_items_favorite_by_identity() -> Response:
    """Favorite item by identity."""
    payload = _merged_request_payload()

    return _json_response(
        _safe_service_call(
            lambda service: service.favorite_item(
                payload,
                user_id=payload.get("user_id"),
                favorite=True,
                commit=True,
            )
        )
    )


@creative_library_user_bp.post("/items/unfavorite")
def creative_library_user_items_unfavorite_by_identity() -> Response:
    """Unfavorite item by identity."""
    payload = _merged_request_payload()

    return _json_response(
        _safe_service_call(
            lambda service: service.favorite_item(
                payload,
                user_id=payload.get("user_id"),
                favorite=False,
                commit=True,
            )
        )
    )


@creative_library_user_bp.post("/items/pin")
def creative_library_user_items_pin_by_identity() -> Response:
    """Pin item by identity via override."""
    payload = _merged_request_payload()

    return _json_response(
        _safe_service_call(
            lambda service: service.pin_item(
                payload,
                user_id=payload.get("user_id"),
                pinned=True,
                commit=True,
            )
        )
    )


@creative_library_user_bp.post("/items/unpin")
def creative_library_user_items_unpin_by_identity() -> Response:
    """Unpin item by identity via override."""
    payload = _merged_request_payload()

    return _json_response(
        _safe_service_call(
            lambda service: service.pin_item(
                payload,
                user_id=payload.get("user_id"),
                pinned=False,
                commit=True,
            )
        )
    )


@creative_library_user_bp.post("/items/rename")
def creative_library_user_items_rename_by_identity() -> Response:
    """Rename item by identity via override."""
    payload = _merged_request_payload()
    label = payload.get("label") or payload.get("custom_label") or payload.get("label_override")

    return _json_response(
        _safe_service_call(
            lambda service: service.rename_item(
                payload,
                user_id=payload.get("user_id"),
                label=label,
                commit=True,
            )
        )
    )


@creative_library_user_bp.post("/items/reorder")
def creative_library_user_items_reorder_by_identity() -> Response:
    """Reorder item by identity via override."""
    payload = _merged_request_payload()

    return _json_response(
        _safe_service_call(
            lambda service: service.reorder_item(
                payload,
                user_id=payload.get("user_id"),
                sort_order=payload.get("sort_order") or payload.get("sortOrder"),
                commit=True,
            )
        )
    )


@creative_library_user_bp.patch("/items/<path:collection_item_ref>")
def creative_library_user_items_patch(collection_item_ref: str) -> Response:
    """Update direct collection item fields."""
    payload = _merged_request_payload()

    return _json_response(
        _safe_service_call(
            lambda service: service.update_collection_item(
                collection_item_ref,
                payload,
                user_id=payload.get("user_id"),
                commit=True,
            )
        )
    )


@creative_library_user_bp.delete("/items/<path:collection_item_ref>")
def creative_library_user_items_delete(collection_item_ref: str) -> Response:
    """Remove direct collection item."""
    payload = _merged_request_payload()

    return _json_response(
        _safe_service_call(
            lambda service: service.remove_item(
                payload,
                user_id=payload.get("user_id"),
                collection_item_ref=collection_item_ref,
                commit=True,
            )
        )
    )


@creative_library_user_bp.post("/items/<path:collection_item_ref>/pin")
def creative_library_user_items_pin(collection_item_ref: str) -> Response:
    """Pin direct collection item."""
    payload = _merged_request_payload()

    return _json_response(
        _safe_service_call(
            lambda service: service.pin_collection_item(
                collection_item_ref,
                pinned=True,
                user_id=payload.get("user_id"),
                commit=True,
            )
        )
    )


@creative_library_user_bp.post("/items/<path:collection_item_ref>/unpin")
def creative_library_user_items_unpin(collection_item_ref: str) -> Response:
    """Unpin direct collection item."""
    payload = _merged_request_payload()

    return _json_response(
        _safe_service_call(
            lambda service: service.pin_collection_item(
                collection_item_ref,
                pinned=False,
                user_id=payload.get("user_id"),
                commit=True,
            )
        )
    )


@creative_library_user_bp.post("/items/<path:collection_item_ref>/favorite")
def creative_library_user_items_favorite(collection_item_ref: str) -> Response:
    """Favorite direct collection item."""
    payload = _merged_request_payload()

    return _json_response(
        _safe_service_call(
            lambda service: service.favorite_collection_item(
                collection_item_ref,
                favorite=True,
                user_id=payload.get("user_id"),
                commit=True,
            )
        )
    )


@creative_library_user_bp.post("/items/<path:collection_item_ref>/unfavorite")
def creative_library_user_items_unfavorite(collection_item_ref: str) -> Response:
    """Unfavorite direct collection item."""
    payload = _merged_request_payload()

    return _json_response(
        _safe_service_call(
            lambda service: service.favorite_collection_item(
                collection_item_ref,
                favorite=False,
                user_id=payload.get("user_id"),
                commit=True,
            )
        )
    )


@creative_library_user_bp.post("/items/<path:collection_item_ref>/reorder")
def creative_library_user_items_reorder(collection_item_ref: str) -> Response:
    """Reorder direct collection item."""
    payload = _merged_request_payload()

    return _json_response(
        _safe_service_call(
            lambda service: service.reorder_collection_item(
                collection_item_ref,
                sort_order=payload.get("sort_order") or payload.get("sortOrder"),
                user_id=payload.get("user_id"),
                commit=True,
            )
        )
    )


# ---------------------------------------------------------------------------
# Overrides
# ---------------------------------------------------------------------------

@creative_library_user_bp.get("/overrides")
def creative_library_user_overrides_list() -> Response:
    """List user overrides."""
    return _json_response(
        _safe_service_call(
            lambda service: service.list_overrides(
                user_id=_int_arg("user_id", default=1),
                target_type=_str_arg("target_type"),
                target_uid=_str_arg("target_uid"),
                target_id=_int_arg("target_id", default=None),
                active_only=_bool_arg("active_only", default=True),
            )
        )
    )


@creative_library_user_bp.post("/overrides")
def creative_library_user_overrides_create() -> Response:
    """Create/update user override explicitly."""
    payload = _merged_request_payload()

    return _json_response(
        _safe_service_call(
            lambda service: service.create_override(
                payload,
                user_id=payload.get("user_id"),
                commit=True,
            )
        )
    )


@creative_library_user_bp.delete("/overrides/<path:override_ref>")
def creative_library_user_overrides_delete(override_ref: str) -> Response:
    """Soft-delete override by reference."""
    payload = _merged_request_payload()

    return _json_response(
        _safe_service_call(
            lambda service: service.delete_override(
                override_ref=override_ref,
                payload=payload,
                user_id=payload.get("user_id"),
                commit=True,
            )
        )
    )


@creative_library_user_bp.delete("/overrides")
def creative_library_user_overrides_delete_by_target() -> Response:
    """Soft-delete override by target identity."""
    payload = _merged_request_payload()

    return _json_response(
        _safe_service_call(
            lambda service: service.delete_override(
                payload=payload,
                user_id=payload.get("user_id"),
                commit=True,
            )
        )
    )


# ---------------------------------------------------------------------------
# Audit
# ---------------------------------------------------------------------------

@creative_library_user_bp.get("/audit")
def creative_library_user_audit_list() -> Response:
    """List Creative Library user audit events."""
    return _json_response(
        _safe_service_call(
            lambda service: service.list_audit_events(
                user_id=_int_arg("user_id", default=1),
                event_type=_str_arg("event_type"),
                target_type=_str_arg("target_type"),
                target_uid=_str_arg("target_uid"),
                collection_uid=_str_arg("collection_uid"),
                vplib_uid=_str_arg("vplib_uid"),
                limit=_int_arg("limit", default=100) or 100,
                offset=_int_arg("offset", default=0) or 0,
            )
        )
    )


# ---------------------------------------------------------------------------
# Request helpers
# ---------------------------------------------------------------------------

def _json_payload() -> Dict[str, Any]:
    """Defensive JSON body reader."""
    try:
        payload = request.get_json(silent=True)
    except Exception as exc:
        _LOGGER.warning("Could not parse creative library user route JSON payload: %s", exc)
        return {}

    if isinstance(payload, Mapping):
        return dict(payload)

    return {}


def _query_payload() -> Dict[str, Any]:
    """Returns query args as dict."""
    try:
        return dict(request.args.items())
    except Exception:
        return {}


def _merged_request_payload() -> Dict[str, Any]:
    """Merge query args and JSON body. JSON body wins."""
    result: Dict[str, Any] = {}
    result.update(_query_payload())

    if request.method in {"POST", "PATCH", "PUT", "DELETE"}:
        result.update(_json_payload())

    return result


def _str_arg(name: str, *, default: str | None = None) -> str | None:
    try:
        value = request.args.get(name)
    except Exception:
        return default

    if value is None:
        return default

    text = str(value).strip()
    return text if text else default


def _int_arg(name: str, *, default: int | None = None) -> int | None:
    try:
        value = request.args.get(name)
    except Exception:
        return default

    if value is None:
        return default

    try:
        return int(value)
    except Exception:
        return default


def _bool_arg(name: str, *, default: bool = False) -> bool:
    try:
        value = request.args.get(name)
    except Exception:
        return default

    return _bool_value(value, default=default)


def _bool_value(value: Any, *, default: bool = False) -> bool:
    if isinstance(value, bool):
        return value

    if value is None:
        return default

    text = str(value).strip().lower()

    if text in {"1", "true", "yes", "y", "ja", "on", "enabled", "active", "visible", "favorite", "pinned"}:
        return True

    if text in {"0", "false", "no", "n", "nein", "off", "disabled", "inactive", "hidden", "deleted"}:
        return False

    return default


# ---------------------------------------------------------------------------
# Response helpers
# ---------------------------------------------------------------------------

def _json_response(payload: Mapping[str, Any]) -> Response:
    status_code = _status_code_from_payload(payload)
    response = jsonify(dict(payload))
    response.status_code = status_code
    return response


def _status_code_from_payload(payload: Mapping[str, Any]) -> int:
    if not isinstance(payload, Mapping):
        return 500

    if bool(payload.get("ok", False)):
        return 200

    status = str(payload.get("status") or "").strip().lower()
    error = payload.get("error")

    code = ""
    if isinstance(error, Mapping):
        code = str(error.get("code") or "").strip().lower()

    if status in {"invalid_request", "bad_request"}:
        return 400

    if status == "not_found" or code.endswith("not_found"):
        return 404

    if status in {"unavailable", "not_implemented"}:
        return 501

    if status in {"failed", "error"}:
        return 500

    if code.startswith("invalid_"):
        return 400

    if code.endswith("_missing"):
        return 404

    return 500


def _safe_service_call(callback: Callable[[Any], Mapping[str, Any] | Any]) -> Dict[str, Any]:
    """Creates service and calls callback safely."""
    try:
        service = _create_user_service()
    except Exception as exc:
        return _unavailable_response(
            "creative_library_user_service_unavailable",
            f"CreativeLibraryUserService is unavailable: {exc}",
        )

    try:
        result = callback(service)

        if isinstance(result, Mapping):
            payload = dict(result)
        else:
            payload = {"result": result}

        payload.setdefault("ok", True)
        payload.setdefault("healthy", True)
        payload.setdefault("status", "ok")
        payload.setdefault("component", CREATIVE_LIBRARY_USER_ROUTES_COMPONENT)
        payload.setdefault("route_version", CREATIVE_LIBRARY_USER_ROUTES_VERSION)

        return payload

    except Exception as exc:
        _LOGGER.exception("Creative Library user route service call failed.")
        return _exception_response(exc, code="creative_library_user_service_error")


def _exception_response(exc: Exception, *, code: str = "route_error") -> Dict[str, Any]:
    message = str(exc)
    exc_name = type(exc).__name__
    lowered = f"{exc_name} {message}".lower()

    status = "error"
    error_code = code

    if "notfound" in lowered or "not found" in lowered:
        status = "not_found"
        error_code = f"{code}_not_found"

    if "invalid" in lowered or "required" in lowered or "validation" in lowered:
        status = "invalid_request"
        error_code = f"{code}_invalid_request"

    errors = getattr(exc, "errors", None)

    return {
        "ok": False,
        "healthy": False,
        "status": status,
        "component": CREATIVE_LIBRARY_USER_ROUTES_COMPONENT,
        "version": CREATIVE_LIBRARY_USER_ROUTES_VERSION,
        "error": {
            "code": error_code,
            "type": exc_name,
            "message": message,
            "errors": [str(item) for item in errors] if errors else None,
        },
    }


def _unavailable_response(code: str, message: str) -> Dict[str, Any]:
    return {
        "ok": False,
        "healthy": False,
        "status": "unavailable",
        "component": CREATIVE_LIBRARY_USER_ROUTES_COMPONENT,
        "version": CREATIVE_LIBRARY_USER_ROUTES_VERSION,
        "error": {
            "code": code,
            "message": message,
        },
    }


# ---------------------------------------------------------------------------
# Health / route map
# ---------------------------------------------------------------------------

def _safe_user_service_health() -> Dict[str, Any]:
    try:
        service = _create_user_service()
        if hasattr(service, "get_health") and callable(service.get_health):
            return dict(service.get_health())

        return {
            "ok": True,
            "healthy": True,
            "status": "ok",
        }
    except Exception as exc:
        return _unavailable_response(
            "creative_library_user_service_unavailable",
            str(exc),
        )


def get_creative_library_user_route_list() -> list[str]:
    """Returns public route list."""
    return [
        "GET /api/v1/vplib/creative-library",
        "GET /api/v1/vplib/creative-library/resolved",
        "GET /api/v1/vplib/creative-library/inventory",
        "POST /api/v1/vplib/creative-library/ensure-defaults",
        "GET /api/v1/vplib/creative-library/health",
        "GET /api/v1/vplib/creative-library/routes",
        "GET /api/v1/vplib/creative-library/selftest",
        "POST /api/v1/vplib/creative-library/cache/clear",
        "GET /api/v1/vplib/creative-library/collections",
        "POST /api/v1/vplib/creative-library/collections",
        "GET /api/v1/vplib/creative-library/collections/<collection_ref>",
        "PATCH /api/v1/vplib/creative-library/collections/<collection_ref>",
        "DELETE /api/v1/vplib/creative-library/collections/<collection_ref>",
        "POST /api/v1/vplib/creative-library/collections/<collection_ref>/restore",
        "GET /api/v1/vplib/creative-library/collections/<collection_ref>/items",
        "POST /api/v1/vplib/creative-library/collections/<collection_ref>/items",
        "GET /api/v1/vplib/creative-library/items",
        "POST /api/v1/vplib/creative-library/items",
        "DELETE /api/v1/vplib/creative-library/items",
        "PATCH /api/v1/vplib/creative-library/items/<collection_item_ref>",
        "DELETE /api/v1/vplib/creative-library/items/<collection_item_ref>",
        "POST /api/v1/vplib/creative-library/items/hide",
        "POST /api/v1/vplib/creative-library/items/restore",
        "POST /api/v1/vplib/creative-library/items/favorite",
        "POST /api/v1/vplib/creative-library/items/unfavorite",
        "POST /api/v1/vplib/creative-library/items/pin",
        "POST /api/v1/vplib/creative-library/items/unpin",
        "POST /api/v1/vplib/creative-library/items/rename",
        "POST /api/v1/vplib/creative-library/items/reorder",
        "POST /api/v1/vplib/creative-library/items/<collection_item_ref>/pin",
        "POST /api/v1/vplib/creative-library/items/<collection_item_ref>/unpin",
        "POST /api/v1/vplib/creative-library/items/<collection_item_ref>/favorite",
        "POST /api/v1/vplib/creative-library/items/<collection_item_ref>/unfavorite",
        "POST /api/v1/vplib/creative-library/items/<collection_item_ref>/reorder",
        "GET /api/v1/vplib/creative-library/overrides",
        "POST /api/v1/vplib/creative-library/overrides",
        "DELETE /api/v1/vplib/creative-library/overrides",
        "DELETE /api/v1/vplib/creative-library/overrides/<override_ref>",
        "GET /api/v1/vplib/creative-library/audit",
    ]


def get_creative_library_user_route_map_response() -> Dict[str, Any]:
    """Returns route map payload."""
    return {
        "ok": True,
        "healthy": True,
        "status": "ok",
        "component": CREATIVE_LIBRARY_USER_ROUTES_COMPONENT,
        "version": CREATIVE_LIBRARY_USER_ROUTES_VERSION,
        "route_prefix": CREATIVE_LIBRARY_USER_ROUTE_PREFIX,
        "blueprint": creative_library_user_bp.name,
        "routes": get_creative_library_user_route_list(),
        "route_count": len(get_creative_library_user_route_list()),
        "groups": {
            "diagnostics": [
                "GET /health",
                "GET /routes",
                "GET /selftest",
                "POST /cache/clear",
            ],
            "resolved": [
                "GET /",
                "GET /resolved",
                "GET /inventory",
                "POST /ensure-defaults",
            ],
            "collections": [
                "GET /collections",
                "POST /collections",
                "GET /collections/<collection_ref>",
                "PATCH /collections/<collection_ref>",
                "DELETE /collections/<collection_ref>",
                "POST /collections/<collection_ref>/restore",
                "GET /collections/<collection_ref>/items",
                "POST /collections/<collection_ref>/items",
            ],
            "items": [
                "GET /items",
                "POST /items",
                "DELETE /items",
                "PATCH /items/<collection_item_ref>",
                "DELETE /items/<collection_item_ref>",
                "POST /items/hide",
                "POST /items/restore",
                "POST /items/favorite",
                "POST /items/unfavorite",
                "POST /items/pin",
                "POST /items/unpin",
                "POST /items/rename",
                "POST /items/reorder",
            ],
            "overrides": [
                "GET /overrides",
                "POST /overrides",
                "DELETE /overrides",
                "DELETE /overrides/<override_ref>",
            ],
            "audit": [
                "GET /audit",
            ],
        },
    }


def get_creative_library_user_routes_health() -> Dict[str, Any]:
    """Import-safe route health helper for routes/__init__.py."""
    service_health = _safe_user_service_health()

    return {
        "ok": True,
        "healthy": True,
        "status": "healthy",
        "component": CREATIVE_LIBRARY_USER_ROUTES_COMPONENT,
        "version": CREATIVE_LIBRARY_USER_ROUTES_VERSION,
        "route_prefix": CREATIVE_LIBRARY_USER_ROUTE_PREFIX,
        "blueprint": creative_library_user_bp.name,
        "routes": get_creative_library_user_route_list(),
        "route_count": len(get_creative_library_user_route_list()),
        "service": service_health,
        "supports_resolved_library": True,
        "supports_creative_inventory": True,
        "supports_default_collections": True,
        "supports_collection_crud": True,
        "supports_collection_items": True,
        "supports_user_overrides": True,
        "supports_item_hide_restore": True,
        "supports_item_favorite": True,
        "supports_item_pin": True,
        "supports_item_rename": True,
        "supports_item_reorder": True,
        "supports_audit": True,
    }


def clear_creative_library_user_routes_caches() -> Dict[str, Any]:
    """Clears route and service caches."""
    cleared: list[str] = []

    try:
        _load_user_service_module.cache_clear()
        cleared.append("_load_user_service_module")
    except Exception:
        pass

    try:
        module = _load_user_service_module()
        clear_function = getattr(module, "clear_creative_library_user_service_caches", None)
        if callable(clear_function):
            clear_function()
            cleared.append("clear_creative_library_user_service_caches")
    except Exception:
        pass

    return {
        "ok": True,
        "healthy": True,
        "status": "ok",
        "component": CREATIVE_LIBRARY_USER_ROUTES_COMPONENT,
        "version": CREATIVE_LIBRARY_USER_ROUTES_VERSION,
        "cleared": cleared,
    }


__all__ = [
    "CREATIVE_LIBRARY_USER_ROUTES_COMPONENT",
    "CREATIVE_LIBRARY_USER_ROUTES_VERSION",
    "CREATIVE_LIBRARY_USER_ROUTE_PREFIX",
    "creative_library_user_bp",
    "creative_library_user_routes_bp",
    "creative_user_bp",
    "user_library_bp",
    "bp",
    "blueprint",
    "get_creative_library_user_routes_health",
    "get_creative_library_user_route_map_response",
    "get_creative_library_user_route_list",
    "clear_creative_library_user_routes_caches",
]