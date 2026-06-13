# services/vectoplan-library/src/routes/taxonomy.py
"""
VECTOPLAN Library Taxonomy Routes.

Thin Flask route layer for the backend-owned VPLIB taxonomy.

This module intentionally contains no taxonomy business logic. It only:
- reads Flask request args / JSON payloads
- delegates to TaxonomyRouteService
- converts RouteServiceResponse into Flask JSON responses

Route prefix:
    /api/v1/vplib/taxonomy

Registered endpoints:
    GET  /api/v1/vplib/taxonomy/health
    GET  /api/v1/vplib/taxonomy
    GET  /api/v1/vplib/taxonomy/options
    GET  /api/v1/vplib/taxonomy/create-options
    GET  /api/v1/vplib/taxonomy/tree
    GET  /api/v1/vplib/taxonomy/lookup
    POST /api/v1/vplib/taxonomy/validate
    POST /api/v1/vplib/taxonomy/resolve
    POST /api/v1/vplib/taxonomy/build-reference
    POST /api/v1/vplib/taxonomy/build-classification
    POST /api/v1/vplib/taxonomy/validate-source-path
    POST /api/v1/vplib/taxonomy/cache/clear
    POST /api/v1/vplib/taxonomy/reload

Design:
- Backend taxonomy is canonical.
- Frontend must consume taxonomy from these routes or from create/options.
- Domain/category/subcategory are required.
- No hard-coded taxonomy values belong in this route file.
"""

from __future__ import annotations

import logging
from typing import Any, Mapping, Optional, Tuple

from flask import Blueprint, Response, jsonify, request


try:
    from src.services.taxonomy_route_service import (
        RouteServiceResponse,
        TaxonomyRouteService,
        get_default_taxonomy_route_service,
    )
except ImportError:  # pragma: no cover - fallback for alternative PYTHONPATH layouts
    try:
        from services.taxonomy_route_service import (  # type: ignore
            RouteServiceResponse,
            TaxonomyRouteService,
            get_default_taxonomy_route_service,
        )
    except ImportError:  # pragma: no cover - package-relative fallback
        from ..services.taxonomy_route_service import (  # type: ignore
            RouteServiceResponse,
            TaxonomyRouteService,
            get_default_taxonomy_route_service,
        )


LOGGER = logging.getLogger(__name__)

TAXONOMY_ROUTES_COMPONENT = "taxonomy-routes"
TAXONOMY_ROUTES_VERSION = "0.1.0"

taxonomy_bp = Blueprint(
    "taxonomy",
    __name__,
    url_prefix="/api/v1/vplib/taxonomy",
)

# Alias for projects that prefer importing `bp`.
bp = taxonomy_bp


@taxonomy_bp.get("/health")
def taxonomy_health() -> Response:
    """
    Health endpoint for taxonomy registry/service/route stack.

    Optional query:
        ?force_reload=true
        ?include_registry_state=true
    """

    return _to_flask_response(
        _service().health(request.args),
    )


@taxonomy_bp.get("")
@taxonomy_bp.get("/")
def taxonomy_root() -> Response:
    """
    Canonical taxonomy payload.

    Optional query:
        ?include_inactive=true
        ?include_tree=true
        ?include_options=true
        ?include_lookup=true
        ?force_reload=true
    """

    return _to_flask_response(
        _service().taxonomy(request.args),
    )


@taxonomy_bp.get("/options")
def taxonomy_options() -> Response:
    """
    Direct select-option payload.

    Intended for generic clients that only need select data.

    Optional query:
        ?include_inactive=true
        ?force_reload=true
    """

    return _to_flask_response(
        _service().options(request.args),
    )


@taxonomy_bp.get("/create-options")
def taxonomy_create_options() -> Response:
    """
    Create-Wizard-friendly taxonomy options.

    This route exposes direct keys:
    - domains
    - categories_by_domain
    - subcategories_by_category
    - taxonomy

    Optional query:
        ?include_inactive=true
        ?force_reload=true
    """

    return _to_flask_response(
        _service().create_options(request.args),
    )


@taxonomy_bp.get("/tree")
def taxonomy_tree() -> Response:
    """
    Taxonomy tree payload.

    Optional query:
        ?include_inactive=true
        ?force_reload=true
    """

    return _to_flask_response(
        _service().tree(request.args),
    )


@taxonomy_bp.get("/lookup")
def taxonomy_lookup() -> Response:
    """
    Taxonomy lookup maps.

    Optional query:
        ?force_reload=true
    """

    return _to_flask_response(
        _service().lookup(request.args),
    )


@taxonomy_bp.post("/validate")
def taxonomy_validate() -> Response:
    """
    Validate a domain/category/subcategory selection.

    JSON payload:
        {
          "domain": "hochbau",
          "category": "waende",
          "subcategory": "aussenwaende",
          "object_kind": "cell_block"
        }

    Optional query:
        ?force_reload=true
    """

    payload = _read_json_payload()
    return _to_flask_response(
        _service().validate(payload, request.args),
    )


@taxonomy_bp.post("/resolve")
def taxonomy_resolve() -> Response:
    """
    Resolve a taxonomy selection into canonical IDs, labels and node metadata.

    JSON payload:
        {
          "domain": "hochbau",
          "category": "waende",
          "subcategory": "aussenwaende"
        }

    Optional query:
        ?force_reload=true
    """

    payload = _read_json_payload()
    return _to_flask_response(
        _service().resolve(payload, request.args),
    )


@taxonomy_bp.post("/build-reference")
def taxonomy_build_reference() -> Response:
    """
    Build source_path, family_id and package_id from taxonomy selection.

    JSON payload:
        {
          "domain": "hochbau",
          "category": "waende",
          "subcategory": "aussenwaende",
          "family_slug": "ziegelwand",
          "object_kind": "cell_block"
        }

    Optional query:
        ?force_reload=true
    """

    payload = _read_json_payload()
    return _to_flask_response(
        _service().build_reference(payload, request.args),
    )


@taxonomy_bp.post("/build-classification")
def taxonomy_build_classification() -> Response:
    """
    Build a classification.json-compatible taxonomy fragment.

    JSON payload:
        {
          "domain": "hochbau",
          "category": "waende",
          "subcategory": "aussenwaende",
          "object_kind": "cell_block",
          "include_node_metadata": true
        }

    Optional query:
        ?force_reload=true
    """

    payload = _read_json_payload()
    return _to_flask_response(
        _service().build_classification(payload, request.args),
    )


@taxonomy_bp.post("/validate-source-path")
def taxonomy_validate_source_path() -> Response:
    """
    Validate canonical or legacy taxonomy source paths.

    JSON payload:
        {
          "source_path": "hochbau/waende/aussenwaende/ziegelwand",
          "object_kind": "cell_block",
          "expect_family_slug": true
        }

    Optional query:
        ?force_reload=true
    """

    payload = _read_json_payload()
    return _to_flask_response(
        _service().validate_source_path(payload, request.args),
    )


@taxonomy_bp.post("/cache/clear")
def taxonomy_cache_clear() -> Response:
    """Clear taxonomy service and registry caches."""

    return _to_flask_response(
        _service().clear_cache(request.args),
    )


@taxonomy_bp.post("/reload")
def taxonomy_reload() -> Response:
    """
    Force reload taxonomy registry from JSON file.

    Optional query:
        ?allow_stale_on_error=true
    """

    return _to_flask_response(
        _service().reload(request.args),
    )


def register_taxonomy_routes(app: Any) -> None:
    """
    Register taxonomy routes on a Flask app.

    This helper is optional. Existing app/bootstrap code may also import
    taxonomy_bp directly and call app.register_blueprint(taxonomy_bp).
    """

    try:
        app.register_blueprint(taxonomy_bp)
    except Exception:
        LOGGER.exception("Failed to register taxonomy blueprint.")
        raise


def get_taxonomy_routes_info() -> Mapping[str, Any]:
    """Return static route metadata for diagnostics."""

    return {
        "component": TAXONOMY_ROUTES_COMPONENT,
        "version": TAXONOMY_ROUTES_VERSION,
        "blueprint": taxonomy_bp.name,
        "url_prefix": taxonomy_bp.url_prefix,
        "routes": [
            {
                "method": "GET",
                "path": "/api/v1/vplib/taxonomy/health",
                "action": "health",
            },
            {
                "method": "GET",
                "path": "/api/v1/vplib/taxonomy",
                "action": "taxonomy",
            },
            {
                "method": "GET",
                "path": "/api/v1/vplib/taxonomy/options",
                "action": "options",
            },
            {
                "method": "GET",
                "path": "/api/v1/vplib/taxonomy/create-options",
                "action": "create_options",
            },
            {
                "method": "GET",
                "path": "/api/v1/vplib/taxonomy/tree",
                "action": "tree",
            },
            {
                "method": "GET",
                "path": "/api/v1/vplib/taxonomy/lookup",
                "action": "lookup",
            },
            {
                "method": "POST",
                "path": "/api/v1/vplib/taxonomy/validate",
                "action": "validate",
            },
            {
                "method": "POST",
                "path": "/api/v1/vplib/taxonomy/resolve",
                "action": "resolve",
            },
            {
                "method": "POST",
                "path": "/api/v1/vplib/taxonomy/build-reference",
                "action": "build_reference",
            },
            {
                "method": "POST",
                "path": "/api/v1/vplib/taxonomy/build-classification",
                "action": "build_classification",
            },
            {
                "method": "POST",
                "path": "/api/v1/vplib/taxonomy/validate-source-path",
                "action": "validate_source_path",
            },
            {
                "method": "POST",
                "path": "/api/v1/vplib/taxonomy/cache/clear",
                "action": "clear_cache",
            },
            {
                "method": "POST",
                "path": "/api/v1/vplib/taxonomy/reload",
                "action": "reload",
            },
        ],
    }


def _service() -> TaxonomyRouteService:
    return get_default_taxonomy_route_service()


def _read_json_payload() -> Mapping[str, Any]:
    """
    Read JSON body defensively.

    Returns an empty dict if the request body is empty or invalid. Validation
    errors are handled by the route service so all taxonomy endpoints keep the
    same response envelope.
    """

    try:
        payload = request.get_json(silent=True)

        if isinstance(payload, Mapping):
            return payload

        return {}
    except Exception:
        LOGGER.debug("Could not parse taxonomy request JSON payload.", exc_info=True)
        return {}


def _to_flask_response(result: RouteServiceResponse) -> Response:
    """
    Convert RouteServiceResponse to Flask Response.

    Header handling:
    - route service headers are added after jsonify()
    - Content-Type remains managed by Flask/jsonify
    """

    payload, status_code, headers = result.to_tuple()
    response = jsonify(payload)
    response.status_code = status_code

    for key, value in headers.items():
        if key.lower() == "content-type":
            continue
        response.headers[key] = value

    return response


__all__ = [
    "TAXONOMY_ROUTES_COMPONENT",
    "TAXONOMY_ROUTES_VERSION",
    "bp",
    "get_taxonomy_routes_info",
    "register_taxonomy_routes",
    "taxonomy_bp",
]