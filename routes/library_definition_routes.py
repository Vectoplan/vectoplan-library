# services/vectoplan-library/src/routes/library_definition_routes.py
"""
Flask routes for VECTOPLAN Library Definitions.

Route prefix:
- /api/v1/vplib/definitions

This route layer is intentionally thin:
- parse Flask request args/json
- call src.services.library_definition_route_service
- jsonify the returned dictionaries

The actual logic lives in:
- services/library_definition_route_service.py

This API is isolated from /create at first. It exists to test the new
backend-owned definitions layer before wiring definitions into the Create wizard.
"""

from __future__ import annotations

import logging
from typing import Any, Dict, Mapping, Optional

from flask import Blueprint, jsonify, request

try:
    from src.services.library_definition_route_service import (
        LIBRARY_DEFINITION_ROUTE_SERVICE_COMPONENT,
        LIBRARY_DEFINITION_ROUTE_SERVICE_VERSION,
        build_empty_library_definition_variant_values_response,
        clear_library_definition_cache_response,
        get_library_definition_options_response,
        get_library_definition_payload_response,
        get_library_definition_route_map_response,
        get_library_definition_route_service_health,
        get_library_definition_summary_response,
        get_library_definition_variant_profile_response,
        resolve_library_definition_family_profile_response,
        resolve_library_definition_variant_profile_response,
        validate_library_definition_variant_response,
    )
except Exception:  # pragma: no cover - fallback for package-relative imports
    from ..services.library_definition_route_service import (
        LIBRARY_DEFINITION_ROUTE_SERVICE_COMPONENT,
        LIBRARY_DEFINITION_ROUTE_SERVICE_VERSION,
        build_empty_library_definition_variant_values_response,
        clear_library_definition_cache_response,
        get_library_definition_options_response,
        get_library_definition_payload_response,
        get_library_definition_route_map_response,
        get_library_definition_route_service_health,
        get_library_definition_summary_response,
        get_library_definition_variant_profile_response,
        resolve_library_definition_family_profile_response,
        resolve_library_definition_variant_profile_response,
        validate_library_definition_variant_response,
    )


LIBRARY_DEFINITION_ROUTES_COMPONENT = "routes.library_definition_routes"
LIBRARY_DEFINITION_ROUTES_VERSION = "0.1.0"
LIBRARY_DEFINITION_ROUTE_PREFIX = "/api/v1/vplib/definitions"

_LOGGER = logging.getLogger(__name__)

library_definition_bp = Blueprint(
    "library_definition_routes",
    __name__,
    url_prefix=LIBRARY_DEFINITION_ROUTE_PREFIX,
)


@library_definition_bp.get("/")
def library_definition_routes_index():
    return _json_response(get_library_definition_route_map_response(request.args))


@library_definition_bp.get("/routes")
def library_definition_routes_map():
    return _json_response(get_library_definition_route_map_response(request.args))


@library_definition_bp.get("/health")
def library_definition_health():
    return _json_response(get_library_definition_route_service_health(request.args))


@library_definition_bp.get("/summary")
def library_definition_summary():
    return _json_response(get_library_definition_summary_response(request.args))


@library_definition_bp.get("/options")
def library_definition_options():
    return _json_response(get_library_definition_options_response(request.args))


@library_definition_bp.get("/payload")
def library_definition_payload():
    return _json_response(get_library_definition_payload_response(request.args))


@library_definition_bp.get("/variant-profiles/<path:profile_id>")
def library_definition_variant_profile(profile_id: str):
    return _json_response(
        get_library_definition_variant_profile_response(
            profile_id,
            request.args,
        )
    )


@library_definition_bp.route(
    "/resolve-family-profile",
    methods=["GET", "POST"],
)
def library_definition_resolve_family_profile():
    payload = _json_payload() if request.method == "POST" else None
    return _json_response(
        resolve_library_definition_family_profile_response(
            request.args,
            payload,
        )
    )


@library_definition_bp.route(
    "/resolve-variant-profile",
    methods=["GET", "POST"],
)
def library_definition_resolve_variant_profile():
    payload = _json_payload() if request.method == "POST" else None
    return _json_response(
        resolve_library_definition_variant_profile_response(
            request.args,
            payload,
        )
    )


@library_definition_bp.route(
    "/empty-variant-values",
    methods=["GET", "POST"],
)
def library_definition_empty_variant_values_from_query_or_payload():
    payload = _json_payload() if request.method == "POST" else None
    return _json_response(
        build_empty_library_definition_variant_values_response(
            None,
            request.args,
            payload,
        )
    )


@library_definition_bp.route(
    "/empty-variant-values/<path:profile_id>",
    methods=["GET", "POST"],
)
def library_definition_empty_variant_values(profile_id: str):
    payload = _json_payload() if request.method == "POST" else None
    return _json_response(
        build_empty_library_definition_variant_values_response(
            profile_id,
            request.args,
            payload,
        )
    )


@library_definition_bp.post("/validate-variant")
def library_definition_validate_variant():
    return _json_response(
        validate_library_definition_variant_response(
            _json_payload(),
            request.args,
        )
    )


@library_definition_bp.post("/cache/clear")
def library_definition_cache_clear():
    return _json_response(clear_library_definition_cache_response(request.args))


@library_definition_bp.get("/selftest")
def library_definition_selftest():
    """
    Lightweight route-level smoke test.

    This is useful during development and can be removed later if desired.
    """
    try:
        from src.services.library_definition_route_service import (
            get_library_definition_route_service_selftest,
        )
    except Exception:  # pragma: no cover
        from ..services.library_definition_route_service import (
            get_library_definition_route_service_selftest,
        )

    return _json_response(get_library_definition_route_service_selftest())


def _json_payload() -> Dict[str, Any]:
    """
    Defensive JSON body reader.

    Flask's request.get_json() may raise depending on content type or invalid
    JSON. Route services should receive a dict, never None or an exception.
    """
    try:
        payload = request.get_json(silent=True)
    except Exception as exc:
        _LOGGER.warning("Could not parse definitions route JSON payload: %s", exc)
        return {}

    if isinstance(payload, Mapping):
        return dict(payload)

    return {}


def _json_response(payload: Mapping[str, Any]):
    status_code = _status_code_from_payload(payload)
    return jsonify(dict(payload)), status_code


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

    if status in {"not_found"} or code.endswith("not_found"):
        return 404

    if status in {"unavailable", "failed", "error"}:
        return 500

    if code.startswith("invalid_"):
        return 400

    return 500


def get_library_definition_routes_health() -> Dict[str, Any]:
    """
    Import-safe route health helper for routes/__init__.py or diagnostics.
    """
    return {
        "ok": True,
        "healthy": True,
        "status": "healthy",
        "component": LIBRARY_DEFINITION_ROUTES_COMPONENT,
        "version": LIBRARY_DEFINITION_ROUTES_VERSION,
        "route_prefix": LIBRARY_DEFINITION_ROUTE_PREFIX,
        "blueprint": library_definition_bp.name,
        "service_component": LIBRARY_DEFINITION_ROUTE_SERVICE_COMPONENT,
        "service_version": LIBRARY_DEFINITION_ROUTE_SERVICE_VERSION,
        "routes": [
            "GET /api/v1/vplib/definitions/",
            "GET /api/v1/vplib/definitions/routes",
            "GET /api/v1/vplib/definitions/health",
            "GET /api/v1/vplib/definitions/summary",
            "GET /api/v1/vplib/definitions/options",
            "GET /api/v1/vplib/definitions/payload",
            "GET /api/v1/vplib/definitions/variant-profiles/<profile_id>",
            "GET|POST /api/v1/vplib/definitions/resolve-family-profile",
            "GET|POST /api/v1/vplib/definitions/resolve-variant-profile",
            "GET|POST /api/v1/vplib/definitions/empty-variant-values",
            "GET|POST /api/v1/vplib/definitions/empty-variant-values/<profile_id>",
            "POST /api/v1/vplib/definitions/validate-variant",
            "POST /api/v1/vplib/definitions/cache/clear",
            "GET /api/v1/vplib/definitions/selftest",
        ],
    }


# Common aliases for route registration code that expects conventional names.
bp = library_definition_bp
blueprint = library_definition_bp