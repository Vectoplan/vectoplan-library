# services/vectoplan-library/routes/taxonomy.py
"""
VECTOPLAN Library Taxonomy Routes.

Thin Flask route layer for the backend-owned VPLIB taxonomy.

This module intentionally contains no taxonomy business logic. It only:
- reads Flask request args / JSON payloads
- delegates to the legacy TaxonomyRouteService or new LibraryTaxonomyUserService
- converts service responses into Flask JSON responses

Route prefix:
    /api/v1/vplib/taxonomy

Legacy endpoints:
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

New DB-backed user taxonomy endpoints:
    GET    /api/v1/vplib/taxonomy/resolved
    GET    /api/v1/vplib/taxonomy/nodes
    POST   /api/v1/vplib/taxonomy/nodes
    GET    /api/v1/vplib/taxonomy/nodes/<node_ref>
    PATCH  /api/v1/vplib/taxonomy/nodes/<node_ref>
    DELETE /api/v1/vplib/taxonomy/nodes/<node_ref>
    POST   /api/v1/vplib/taxonomy/nodes/<node_ref>/restore
    POST   /api/v1/vplib/taxonomy/nodes/<node_ref>/hide
    POST   /api/v1/vplib/taxonomy/nodes/<node_ref>/rename
    POST   /api/v1/vplib/taxonomy/nodes/<node_ref>/reorder
    POST   /api/v1/vplib/taxonomy/nodes/<node_ref>/move
    GET    /api/v1/vplib/taxonomy/overrides
    POST   /api/v1/vplib/taxonomy/overrides
    DELETE /api/v1/vplib/taxonomy/overrides/<override_ref>
    GET    /api/v1/vplib/taxonomy/audit

Design:
- Backend taxonomy remains canonical.
- Frontend must consume taxonomy from these routes or from create/options.
- System taxonomy is not copied per user.
- User taxonomy additions are user-owned nodes.
- User changes to system taxonomy are stored as overrides.
- No hard-coded taxonomy values belong in this route file.
"""

from __future__ import annotations

import importlib
import logging
from functools import lru_cache
from types import ModuleType
from typing import Any, Callable, Dict, Mapping

from flask import Blueprint, Response, jsonify, request


LOGGER = logging.getLogger(__name__)

TAXONOMY_ROUTES_COMPONENT = "taxonomy-routes"
TAXONOMY_ROUTES_VERSION = "1.0.0"
TAXONOMY_ROUTE_PREFIX = "/api/v1/vplib/taxonomy"

taxonomy_bp = Blueprint(
    "taxonomy",
    __name__,
    url_prefix=TAXONOMY_ROUTE_PREFIX,
)

# Aliases for projects that prefer conventional names.
bp = taxonomy_bp
blueprint = taxonomy_bp


# ---------------------------------------------------------------------------
# Lazy service imports
# ---------------------------------------------------------------------------

@lru_cache(maxsize=1)
def _load_legacy_taxonomy_route_service_module() -> ModuleType:
    """Loads the existing static/canonical taxonomy route service defensively."""
    errors: list[str] = []

    for module_name in (
        "src.services.taxonomy_route_service",
        "services.taxonomy_route_service",
        "vectoplan_library.src.services.taxonomy_route_service",
        "vectoplan_library.services.taxonomy_route_service",
    ):
        try:
            return importlib.import_module(module_name)
        except Exception as exc:
            errors.append(f"{module_name}: {type(exc).__name__}: {exc}")

    raise ImportError(
        "Could not import taxonomy_route_service. "
        + " | ".join(errors)
    )


@lru_cache(maxsize=1)
def _load_user_taxonomy_service_module() -> ModuleType:
    """Loads the new DB-backed user taxonomy service defensively."""
    errors: list[str] = []

    for module_name in (
        "src.library.services.library_taxonomy_user_service",
        "library.services.library_taxonomy_user_service",
        "vectoplan_library.src.library.services.library_taxonomy_user_service",
        "vectoplan_library.library.services.library_taxonomy_user_service",
    ):
        try:
            return importlib.import_module(module_name)
        except Exception as exc:
            errors.append(f"{module_name}: {type(exc).__name__}: {exc}")

    raise ImportError(
        "Could not import library_taxonomy_user_service. "
        + " | ".join(errors)
    )


def _legacy_service() -> Any:
    """Returns legacy TaxonomyRouteService."""
    module = _load_legacy_taxonomy_route_service_module()
    factory = getattr(module, "get_default_taxonomy_route_service", None)

    if callable(factory):
        return factory()

    raise RuntimeError("get_default_taxonomy_route_service is not available.")


def _user_service() -> Any:
    """Creates LibraryTaxonomyUserService."""
    module = _load_user_taxonomy_service_module()

    factory = getattr(module, "create_library_taxonomy_user_service", None)
    if callable(factory):
        return factory()

    service_class = getattr(module, "LibraryTaxonomyUserService", None)
    if service_class is None:
        raise RuntimeError("LibraryTaxonomyUserService is not available.")

    return service_class()


# ---------------------------------------------------------------------------
# Diagnostics
# ---------------------------------------------------------------------------

@taxonomy_bp.get("/health")
def taxonomy_health() -> Response:
    """
    Health endpoint for taxonomy route stack.

    Optional query:
        ?include_legacy=true
        ?include_user=true
    """
    include_legacy = _bool_arg("include_legacy", default=True)
    include_user = _bool_arg("include_user", default=True)

    payload: Dict[str, Any] = {
        "ok": True,
        "healthy": True,
        "status": "healthy",
        "component": TAXONOMY_ROUTES_COMPONENT,
        "version": TAXONOMY_ROUTES_VERSION,
        "route_prefix": TAXONOMY_ROUTE_PREFIX,
        "blueprint": taxonomy_bp.name,
        "routes": get_taxonomy_route_list(),
        "route_count": len(get_taxonomy_route_list()),
        "supports_legacy_taxonomy": True,
        "supports_user_taxonomy": True,
        "supports_resolved_taxonomy": True,
        "supports_nodes": True,
        "supports_overrides": True,
        "supports_audit": True,
    }

    if include_legacy:
        payload["legacy_service"] = _safe_legacy_health()

    if include_user:
        payload["user_taxonomy_service"] = _safe_user_taxonomy_health()

    return _json_response(payload)


@taxonomy_bp.get("/routes")
def taxonomy_routes_map() -> Response:
    """Return route metadata."""
    return _json_response(get_taxonomy_routes_info())


@taxonomy_bp.get("/selftest")
def taxonomy_selftest() -> Response:
    """Lightweight route smoke test."""
    return _json_response(
        {
            "ok": True,
            "healthy": True,
            "status": "ok",
            "component": TAXONOMY_ROUTES_COMPONENT,
            "version": TAXONOMY_ROUTES_VERSION,
            "route_prefix": TAXONOMY_ROUTE_PREFIX,
            "legacy_service": _safe_legacy_health(),
            "user_taxonomy_service": _safe_user_taxonomy_health(),
        }
    )


# ---------------------------------------------------------------------------
# Root / resolved taxonomy
# ---------------------------------------------------------------------------

@taxonomy_bp.get("")
@taxonomy_bp.get("/")
def taxonomy_root() -> Response:
    """
    Canonical taxonomy payload.

    Backward compatibility:
    - Without user-specific query args, this delegates to legacy TaxonomyRouteService.
    - With scope=resolved or user_id/include_user, this uses DB-backed user taxonomy.

    Examples:
        GET /api/v1/vplib/taxonomy
        GET /api/v1/vplib/taxonomy?user_id=1&scope=resolved
    """
    if _should_use_user_taxonomy(request.args):
        return _json_response(
            _safe_user_call(
                lambda service: service.get_resolved_taxonomy(
                    user_id=_int_arg("user_id", default=1),
                    include_hidden=_bool_arg("include_hidden", default=False),
                    include_deleted=_bool_arg("include_deleted", default=False),
                    include_tree=_bool_arg("include_tree", default=True),
                    include_nodes=_bool_arg("include_nodes", default=True),
                    include_create_options=_bool_arg("include_create_options", default=False),
                )
            )
        )

    return _to_flask_response(_legacy_service().taxonomy(request.args))


@taxonomy_bp.get("/resolved")
def taxonomy_resolved() -> Response:
    """
    DB-backed resolved taxonomy for a user.

    GET /api/v1/vplib/taxonomy/resolved?user_id=1
    """
    return _json_response(
        _safe_user_call(
            lambda service: service.get_resolved_taxonomy(
                user_id=_int_arg("user_id", default=1),
                include_hidden=_bool_arg("include_hidden", default=False),
                include_deleted=_bool_arg("include_deleted", default=False),
                include_tree=_bool_arg("include_tree", default=True),
                include_nodes=_bool_arg("include_nodes", default=True),
                include_create_options=_bool_arg("include_create_options", default=False),
            )
        )
    )


@taxonomy_bp.get("/options")
def taxonomy_options() -> Response:
    """
    Direct select-option payload.

    If user_id/scope=resolved is present, returns user-resolved create options.
    Otherwise legacy taxonomy options are used.
    """
    if _should_use_user_taxonomy(request.args):
        return _json_response(
            _safe_user_call(
                lambda service: service.get_create_options(
                    user_id=_int_arg("user_id", default=1),
                    include_hidden=_bool_arg("include_hidden", default=False),
                    include_deleted=_bool_arg("include_deleted", default=False),
                )
            )
        )

    return _to_flask_response(_legacy_service().options(request.args))


@taxonomy_bp.get("/create-options")
def taxonomy_create_options() -> Response:
    """
    Create-Wizard-friendly taxonomy options.

    For user-aware options:
        GET /api/v1/vplib/taxonomy/create-options?user_id=1&include_user=true
    """
    include_user = _bool_arg("include_user", default=False) or _should_use_user_taxonomy(request.args)

    if include_user:
        return _json_response(
            _safe_user_call(
                lambda service: service.get_create_options(
                    user_id=_int_arg("user_id", default=1),
                    include_hidden=_bool_arg("include_hidden", default=False),
                    include_deleted=_bool_arg("include_deleted", default=False),
                )
            )
        )

    return _to_flask_response(_legacy_service().create_options(request.args))


@taxonomy_bp.get("/tree")
def taxonomy_tree() -> Response:
    """
    Taxonomy tree payload.

    If user-specific query args are present, returns resolved user tree.
    """
    if _should_use_user_taxonomy(request.args):
        return _json_response(
            _safe_user_call(
                lambda service: service.get_resolved_taxonomy(
                    user_id=_int_arg("user_id", default=1),
                    include_hidden=_bool_arg("include_hidden", default=False),
                    include_deleted=_bool_arg("include_deleted", default=False),
                    include_tree=True,
                    include_nodes=False,
                    include_create_options=False,
                )
            )
        )

    return _to_flask_response(_legacy_service().tree(request.args))


@taxonomy_bp.get("/lookup")
def taxonomy_lookup() -> Response:
    """
    Taxonomy lookup maps.

    If user-specific query args are present, returns lookup maps from resolved DB taxonomy.
    """
    if _should_use_user_taxonomy(request.args):
        return _json_response(
            _safe_user_call(
                lambda service: _build_user_lookup_response(service)
            )
        )

    return _to_flask_response(_legacy_service().lookup(request.args))


# ---------------------------------------------------------------------------
# New DB-backed node endpoints
# ---------------------------------------------------------------------------

@taxonomy_bp.get("/nodes")
def taxonomy_nodes_list() -> Response:
    """List taxonomy nodes."""
    return _json_response(
        _safe_user_call(
            lambda service: service.list_nodes(
                user_id=_int_arg("user_id", default=1),
                source_scope=_str_arg("source_scope"),
                node_type=_str_arg("node_type"),
                domain=_str_arg("domain"),
                category=_str_arg("category"),
                subcategory=_str_arg("subcategory"),
                taxonomy_path=_str_arg("taxonomy_path"),
                include_system=_bool_arg("include_system", default=True),
                include_user=_bool_arg("include_user", default=True),
                active_only=_bool_arg("active_only", default=True),
                visible_only=_bool_arg("visible_only", default=False),
                include_deleted=_bool_arg("include_deleted", default=False),
            )
        )
    )


@taxonomy_bp.post("/nodes")
def taxonomy_nodes_create() -> Response:
    """
    Create user-owned taxonomy node.

    JSON payload examples:
        {"user_id": 1, "node_type": "domain", "domain": "custom", "label": "Custom"}
        {"user_id": 1, "domain": "hochbau", "category": "custom", "label": "Custom"}
    """
    payload = _merged_request_payload()

    return _json_response(
        _safe_user_call(
            lambda service: service.create_node(
                payload,
                user_id=payload.get("user_id"),
                commit=True,
            )
        )
    )


@taxonomy_bp.get("/nodes/<path:node_ref>")
def taxonomy_nodes_get(node_ref: str) -> Response:
    """Read one taxonomy node."""
    return _json_response(
        _safe_user_call(
            lambda service: service.get_node(node_ref)
        )
    )


@taxonomy_bp.patch("/nodes/<path:node_ref>")
def taxonomy_nodes_patch(node_ref: str) -> Response:
    """
    Update node.

    - User node: direct update
    - System node: creates user override
    """
    payload = _merged_request_payload()

    return _json_response(
        _safe_user_call(
            lambda service: service.update_node(
                node_ref,
                payload,
                user_id=payload.get("user_id"),
                commit=True,
            )
        )
    )


@taxonomy_bp.delete("/nodes/<path:node_ref>")
def taxonomy_nodes_delete(node_ref: str) -> Response:
    """
    Delete/hide node.

    - User node: soft delete
    - System node: hide override
    """
    payload = _merged_request_payload()

    return _json_response(
        _safe_user_call(
            lambda service: service.delete_node(
                node_ref,
                user_id=payload.get("user_id"),
                commit=True,
            )
        )
    )


@taxonomy_bp.post("/nodes/<path:node_ref>/restore")
def taxonomy_nodes_restore(node_ref: str) -> Response:
    """Restore user node or create restore override for system node."""
    payload = _merged_request_payload()

    return _json_response(
        _safe_user_call(
            lambda service: service.restore_node(
                node_ref,
                user_id=payload.get("user_id"),
                commit=True,
            )
        )
    )


@taxonomy_bp.post("/nodes/<path:node_ref>/hide")
def taxonomy_nodes_hide(node_ref: str) -> Response:
    """Hide a node for the current user."""
    payload = _merged_request_payload()

    return _json_response(
        _safe_user_call(
            lambda service: service.hide_node(
                node_ref,
                user_id=payload.get("user_id"),
                commit=True,
            )
        )
    )


@taxonomy_bp.post("/nodes/<path:node_ref>/rename")
def taxonomy_nodes_rename(node_ref: str) -> Response:
    """Rename a node for the current user."""
    payload = _merged_request_payload()
    label = payload.get("label") or payload.get("name") or payload.get("label_override")

    return _json_response(
        _safe_user_call(
            lambda service: service.rename_node(
                node_ref,
                label=label,
                user_id=payload.get("user_id"),
                commit=True,
            )
        )
    )


@taxonomy_bp.post("/nodes/<path:node_ref>/reorder")
def taxonomy_nodes_reorder(node_ref: str) -> Response:
    """Reorder a node for the current user."""
    payload = _merged_request_payload()

    return _json_response(
        _safe_user_call(
            lambda service: service.reorder_node(
                node_ref,
                sort_order=payload.get("sort_order") or payload.get("sortOrder"),
                user_id=payload.get("user_id"),
                commit=True,
            )
        )
    )


@taxonomy_bp.post("/nodes/<path:node_ref>/move")
def taxonomy_nodes_move(node_ref: str) -> Response:
    """Move a node under another parent."""
    payload = _merged_request_payload()
    parent_ref = (
        payload.get("parent_node_ref")
        or payload.get("parent_node_uid")
        or payload.get("parent_node_id")
        or payload.get("parent")
    )

    if not parent_ref:
        return _json_response(
            _invalid_request_response(
                "parent_node_ref_missing",
                "parent_node_ref, parent_node_uid or parent_node_id is required.",
            )
        )

    return _json_response(
        _safe_user_call(
            lambda service: service.move_node(
                node_ref,
                parent_node_ref=parent_ref,
                user_id=payload.get("user_id"),
                commit=True,
            )
        )
    )


# ---------------------------------------------------------------------------
# New DB-backed override endpoints
# ---------------------------------------------------------------------------

@taxonomy_bp.get("/overrides")
def taxonomy_overrides_list() -> Response:
    """List user taxonomy overrides."""
    return _json_response(
        _safe_user_call(
            lambda service: service.list_overrides(
                user_id=_int_arg("user_id", default=1),
                target_node_uid=_str_arg("target_node_uid"),
                active_only=_bool_arg("active_only", default=True),
            )
        )
    )


@taxonomy_bp.post("/overrides")
def taxonomy_overrides_create() -> Response:
    """Create/update user taxonomy override."""
    payload = _merged_request_payload()

    return _json_response(
        _safe_user_call(
            lambda service: service.create_override(
                payload,
                user_id=payload.get("user_id"),
                commit=True,
            )
        )
    )


@taxonomy_bp.delete("/overrides/<path:override_ref>")
def taxonomy_overrides_delete(override_ref: str) -> Response:
    """Soft-delete user taxonomy override."""
    payload = _merged_request_payload()

    return _json_response(
        _safe_user_call(
            lambda service: service.delete_override(
                override_ref=override_ref,
                user_id=payload.get("user_id"),
                commit=True,
            )
        )
    )


@taxonomy_bp.delete("/overrides")
def taxonomy_overrides_delete_by_node() -> Response:
    """Soft-delete override by target node ref/uid."""
    payload = _merged_request_payload()
    node_ref = payload.get("node_ref") or payload.get("node_uid") or payload.get("target_node_uid")

    if not node_ref:
        return _json_response(
            _invalid_request_response(
                "node_ref_missing",
                "node_ref, node_uid or target_node_uid is required.",
            )
        )

    return _json_response(
        _safe_user_call(
            lambda service: service.delete_override(
                node_ref=node_ref,
                user_id=payload.get("user_id"),
                commit=True,
            )
        )
    )


# ---------------------------------------------------------------------------
# New DB-backed audit endpoint
# ---------------------------------------------------------------------------

@taxonomy_bp.get("/audit")
def taxonomy_audit_list() -> Response:
    """List taxonomy audit events."""
    return _json_response(
        _safe_user_call(
            lambda service: service.list_audit_events(
                user_id=_int_arg("user_id", default=1),
                event_type=_str_arg("event_type"),
                node_uid=_str_arg("node_uid"),
                target_node_uid=_str_arg("target_node_uid"),
                limit=_int_arg("limit", default=100) or 100,
                offset=_int_arg("offset", default=0) or 0,
            )
        )
    )


# ---------------------------------------------------------------------------
# Convenience create endpoints
# ---------------------------------------------------------------------------

@taxonomy_bp.post("/domains")
def taxonomy_create_domain() -> Response:
    """Create user-owned domain/tab."""
    payload = _merged_request_payload()

    return _json_response(
        _safe_user_call(
            lambda service: service.create_domain(
                domain=payload.get("domain"),
                label=payload.get("label") or payload.get("name"),
                user_id=payload.get("user_id"),
                sort_order=payload.get("sort_order"),
                payload=payload,
                commit=True,
            )
        )
    )


@taxonomy_bp.post("/categories")
def taxonomy_create_category() -> Response:
    """Create user-owned category."""
    payload = _merged_request_payload()

    return _json_response(
        _safe_user_call(
            lambda service: service.create_category(
                domain=payload.get("domain"),
                category=payload.get("category"),
                label=payload.get("label") or payload.get("name"),
                user_id=payload.get("user_id"),
                sort_order=payload.get("sort_order"),
                payload=payload,
                commit=True,
            )
        )
    )


@taxonomy_bp.post("/subcategories")
def taxonomy_create_subcategory() -> Response:
    """Create user-owned subcategory."""
    payload = _merged_request_payload()

    return _json_response(
        _safe_user_call(
            lambda service: service.create_subcategory(
                domain=payload.get("domain"),
                category=payload.get("category"),
                subcategory=payload.get("subcategory"),
                label=payload.get("label") or payload.get("name"),
                user_id=payload.get("user_id"),
                sort_order=payload.get("sort_order"),
                payload=payload,
                commit=True,
            )
        )
    )


# ---------------------------------------------------------------------------
# Legacy validation/build endpoints
# ---------------------------------------------------------------------------

@taxonomy_bp.post("/validate")
def taxonomy_validate() -> Response:
    """
    Validate a domain/category/subcategory selection.

    Still delegated to the legacy canonical taxonomy route service.
    """
    payload = _read_json_payload()
    return _to_flask_response(
        _legacy_service().validate(payload, request.args),
    )


@taxonomy_bp.post("/resolve")
def taxonomy_resolve() -> Response:
    """
    Resolve a taxonomy selection into canonical IDs, labels and node metadata.

    Still delegated to the legacy canonical taxonomy route service.
    """
    payload = _read_json_payload()
    return _to_flask_response(
        _legacy_service().resolve(payload, request.args),
    )


@taxonomy_bp.post("/build-reference")
def taxonomy_build_reference() -> Response:
    """
    Build source_path, family_id and package_id from taxonomy selection.

    Still delegated to the legacy canonical taxonomy route service.
    """
    payload = _read_json_payload()
    return _to_flask_response(
        _legacy_service().build_reference(payload, request.args),
    )


@taxonomy_bp.post("/build-classification")
def taxonomy_build_classification() -> Response:
    """
    Build a classification.json-compatible taxonomy fragment.

    Still delegated to the legacy canonical taxonomy route service.
    """
    payload = _read_json_payload()
    return _to_flask_response(
        _legacy_service().build_classification(payload, request.args),
    )


@taxonomy_bp.post("/validate-source-path")
def taxonomy_validate_source_path() -> Response:
    """
    Validate canonical or legacy taxonomy source paths.

    Still delegated to the legacy canonical taxonomy route service.
    """
    payload = _read_json_payload()
    return _to_flask_response(
        _legacy_service().validate_source_path(payload, request.args),
    )


@taxonomy_bp.post("/cache/clear")
def taxonomy_cache_clear() -> Response:
    """Clear route, legacy service and user taxonomy service caches."""
    cleared = clear_taxonomy_route_caches()

    legacy_result = None
    try:
        legacy_result = _legacy_service().clear_cache(request.args)
    except Exception:
        LOGGER.debug("Legacy taxonomy cache clear failed.", exc_info=True)

    payload = {
        "ok": True,
        "healthy": True,
        "status": "ok",
        "component": TAXONOMY_ROUTES_COMPONENT,
        "version": TAXONOMY_ROUTES_VERSION,
        "cleared": cleared.get("cleared", []),
        "legacy": _route_response_to_payload(legacy_result) if legacy_result is not None else None,
    }

    return _json_response(payload)


@taxonomy_bp.post("/reload")
def taxonomy_reload() -> Response:
    """
    Force reload taxonomy registry from JSON file.

    Still delegated to the legacy canonical taxonomy route service.
    """
    return _to_flask_response(
        _legacy_service().reload(request.args),
    )


# ---------------------------------------------------------------------------
# Registration helper
# ---------------------------------------------------------------------------

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


# ---------------------------------------------------------------------------
# Route metadata / health helpers
# ---------------------------------------------------------------------------

def get_taxonomy_route_list() -> list[str]:
    """Return public taxonomy route list."""
    return [
        "GET /api/v1/vplib/taxonomy/health",
        "GET /api/v1/vplib/taxonomy/routes",
        "GET /api/v1/vplib/taxonomy/selftest",
        "GET /api/v1/vplib/taxonomy",
        "GET /api/v1/vplib/taxonomy/resolved",
        "GET /api/v1/vplib/taxonomy/options",
        "GET /api/v1/vplib/taxonomy/create-options",
        "GET /api/v1/vplib/taxonomy/tree",
        "GET /api/v1/vplib/taxonomy/lookup",
        "GET /api/v1/vplib/taxonomy/nodes",
        "POST /api/v1/vplib/taxonomy/nodes",
        "GET /api/v1/vplib/taxonomy/nodes/<node_ref>",
        "PATCH /api/v1/vplib/taxonomy/nodes/<node_ref>",
        "DELETE /api/v1/vplib/taxonomy/nodes/<node_ref>",
        "POST /api/v1/vplib/taxonomy/nodes/<node_ref>/restore",
        "POST /api/v1/vplib/taxonomy/nodes/<node_ref>/hide",
        "POST /api/v1/vplib/taxonomy/nodes/<node_ref>/rename",
        "POST /api/v1/vplib/taxonomy/nodes/<node_ref>/reorder",
        "POST /api/v1/vplib/taxonomy/nodes/<node_ref>/move",
        "GET /api/v1/vplib/taxonomy/overrides",
        "POST /api/v1/vplib/taxonomy/overrides",
        "DELETE /api/v1/vplib/taxonomy/overrides/<override_ref>",
        "DELETE /api/v1/vplib/taxonomy/overrides",
        "GET /api/v1/vplib/taxonomy/audit",
        "POST /api/v1/vplib/taxonomy/domains",
        "POST /api/v1/vplib/taxonomy/categories",
        "POST /api/v1/vplib/taxonomy/subcategories",
        "POST /api/v1/vplib/taxonomy/validate",
        "POST /api/v1/vplib/taxonomy/resolve",
        "POST /api/v1/vplib/taxonomy/build-reference",
        "POST /api/v1/vplib/taxonomy/build-classification",
        "POST /api/v1/vplib/taxonomy/validate-source-path",
        "POST /api/v1/vplib/taxonomy/cache/clear",
        "POST /api/v1/vplib/taxonomy/reload",
    ]


def get_taxonomy_routes_info() -> Mapping[str, Any]:
    """Return static route metadata for diagnostics."""
    return {
        "ok": True,
        "healthy": True,
        "status": "ok",
        "component": TAXONOMY_ROUTES_COMPONENT,
        "version": TAXONOMY_ROUTES_VERSION,
        "blueprint": taxonomy_bp.name,
        "url_prefix": taxonomy_bp.url_prefix,
        "routes": get_taxonomy_route_list(),
        "route_count": len(get_taxonomy_route_list()),
        "groups": {
            "diagnostics": [
                "GET /health",
                "GET /routes",
                "GET /selftest",
                "POST /cache/clear",
                "POST /reload",
            ],
            "legacy_read": [
                "GET /",
                "GET /options",
                "GET /create-options",
                "GET /tree",
                "GET /lookup",
            ],
            "user_resolved": [
                "GET /?user_id=1&scope=resolved",
                "GET /resolved",
                "GET /nodes",
                "GET /audit",
            ],
            "user_nodes": [
                "POST /nodes",
                "GET /nodes/<node_ref>",
                "PATCH /nodes/<node_ref>",
                "DELETE /nodes/<node_ref>",
                "POST /nodes/<node_ref>/restore",
                "POST /nodes/<node_ref>/hide",
                "POST /nodes/<node_ref>/rename",
                "POST /nodes/<node_ref>/reorder",
                "POST /nodes/<node_ref>/move",
                "POST /domains",
                "POST /categories",
                "POST /subcategories",
            ],
            "user_overrides": [
                "GET /overrides",
                "POST /overrides",
                "DELETE /overrides/<override_ref>",
                "DELETE /overrides",
            ],
            "legacy_validation": [
                "POST /validate",
                "POST /resolve",
                "POST /build-reference",
                "POST /build-classification",
                "POST /validate-source-path",
            ],
        },
    }


def get_taxonomy_routes_health() -> Mapping[str, Any]:
    """Route-registry compatible health helper."""
    return {
        "ok": True,
        "healthy": True,
        "status": "healthy",
        "component": TAXONOMY_ROUTES_COMPONENT,
        "version": TAXONOMY_ROUTES_VERSION,
        "blueprint": taxonomy_bp.name,
        "url_prefix": taxonomy_bp.url_prefix,
        "routes": get_taxonomy_route_list(),
        "route_count": len(get_taxonomy_route_list()),
        "legacy_service": _safe_legacy_health(),
        "user_taxonomy_service": _safe_user_taxonomy_health(),
        "supports_legacy_taxonomy": True,
        "supports_user_taxonomy": True,
        "supports_resolved_taxonomy": True,
        "supports_user_nodes": True,
        "supports_user_overrides": True,
        "supports_audit": True,
    }


# ---------------------------------------------------------------------------
# Request helpers
# ---------------------------------------------------------------------------

def _read_json_payload() -> Mapping[str, Any]:
    """
    Read JSON body defensively.

    Returns an empty dict if the request body is empty or invalid.
    """
    try:
        payload = request.get_json(silent=True)

        if isinstance(payload, Mapping):
            return payload

        return {}
    except Exception:
        LOGGER.debug("Could not parse taxonomy request JSON payload.", exc_info=True)
        return {}


def _query_payload() -> Dict[str, Any]:
    """Return query args as dict."""
    try:
        return dict(request.args.items())
    except Exception:
        return {}


def _merged_request_payload() -> Dict[str, Any]:
    """Merge query args and JSON body. JSON wins."""
    payload: Dict[str, Any] = {}
    payload.update(_query_payload())

    if request.method in {"POST", "PATCH", "PUT", "DELETE"}:
        payload.update(dict(_read_json_payload()))

    return payload


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

    if text in {"1", "true", "yes", "y", "ja", "on", "enabled", "active", "visible", "resolved"}:
        return True

    if text in {"0", "false", "no", "n", "nein", "off", "disabled", "inactive", "hidden"}:
        return False

    return default


def _should_use_user_taxonomy(args: Mapping[str, Any]) -> bool:
    """Determines whether the request should use DB-backed user taxonomy."""
    try:
        scope = str(args.get("scope") or "").strip().lower()
    except Exception:
        scope = ""

    if scope in {"resolved", "user", "db", "runtime"}:
        return True

    if args.get("user_id") is not None:
        return True

    if _bool_value(args.get("include_user"), default=False):
        return True

    if _bool_value(args.get("resolved"), default=False):
        return True

    return False


# ---------------------------------------------------------------------------
# Response helpers
# ---------------------------------------------------------------------------

def _to_flask_response(result: Any) -> Response:
    """
    Convert legacy RouteServiceResponse or mapping to Flask Response.

    Header handling:
    - route service headers are added after jsonify()
    - Content-Type remains managed by Flask/jsonify
    """
    if hasattr(result, "to_tuple") and callable(result.to_tuple):
        payload, status_code, headers = result.to_tuple()
        response = jsonify(payload)
        response.status_code = status_code

        for key, value in headers.items():
            if key.lower() == "content-type":
                continue
            response.headers[key] = value

        return response

    if isinstance(result, Mapping):
        return _json_response(result)

    return _json_response(
        {
            "ok": False,
            "healthy": False,
            "status": "error",
            "component": TAXONOMY_ROUTES_COMPONENT,
            "error": {
                "code": "invalid_service_response",
                "message": "Taxonomy service did not return a RouteServiceResponse or mapping.",
            },
        }
    )


def _json_response(payload: Mapping[str, Any]) -> Response:
    """Convert mapping to Flask JSON response."""
    status_code = _status_code_from_payload(payload)
    response = jsonify(dict(payload))
    response.status_code = status_code
    return response


def _status_code_from_payload(payload: Mapping[str, Any]) -> int:
    """Map response envelope to HTTP status."""
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


def _safe_user_call(callback: Callable[[Any], Mapping[str, Any] | Any]) -> Dict[str, Any]:
    """Creates user taxonomy service and calls callback safely."""
    try:
        service = _user_service()
    except Exception as exc:
        return _unavailable_response(
            "user_taxonomy_service_unavailable",
            f"LibraryTaxonomyUserService is unavailable: {exc}",
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
        payload.setdefault("component", TAXONOMY_ROUTES_COMPONENT)
        payload.setdefault("route_version", TAXONOMY_ROUTES_VERSION)

        return payload

    except Exception as exc:
        LOGGER.exception("User taxonomy route service call failed.")
        return _exception_response(exc, code="user_taxonomy_service_error")


def _exception_response(exc: Exception, *, code: str = "route_error") -> Dict[str, Any]:
    """Map exception to JSON response."""
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
        "component": TAXONOMY_ROUTES_COMPONENT,
        "version": TAXONOMY_ROUTES_VERSION,
        "error": {
            "code": error_code,
            "type": exc_name,
            "message": message,
            "errors": [str(item) for item in errors] if errors else None,
        },
    }


def _invalid_request_response(code: str, message: str) -> Dict[str, Any]:
    """Build invalid request response."""
    return {
        "ok": False,
        "healthy": False,
        "status": "invalid_request",
        "component": TAXONOMY_ROUTES_COMPONENT,
        "version": TAXONOMY_ROUTES_VERSION,
        "error": {
            "code": code,
            "message": message,
        },
    }


def _unavailable_response(code: str, message: str) -> Dict[str, Any]:
    """Build unavailable response."""
    return {
        "ok": False,
        "healthy": False,
        "status": "unavailable",
        "component": TAXONOMY_ROUTES_COMPONENT,
        "version": TAXONOMY_ROUTES_VERSION,
        "error": {
            "code": code,
            "message": message,
        },
    }


def _route_response_to_payload(result: Any) -> Dict[str, Any]:
    """Extract payload from legacy RouteServiceResponse."""
    if result is None:
        return {}

    if hasattr(result, "to_tuple") and callable(result.to_tuple):
        try:
            payload, status_code, headers = result.to_tuple()
            return {
                "payload": payload,
                "status_code": status_code,
                "headers": dict(headers),
            }
        except Exception:
            return {"value": str(result)}

    if isinstance(result, Mapping):
        return dict(result)

    return {"value": str(result)}


# ---------------------------------------------------------------------------
# Service helper payload builders
# ---------------------------------------------------------------------------

def _build_user_lookup_response(service: Any) -> Dict[str, Any]:
    """Build lookup maps from resolved user taxonomy."""
    response = service.get_resolved_taxonomy(
        user_id=_int_arg("user_id", default=1),
        include_hidden=_bool_arg("include_hidden", default=False),
        include_deleted=_bool_arg("include_deleted", default=False),
        include_tree=False,
        include_nodes=True,
        include_create_options=False,
    )

    payload = response.get("payload", {}) if isinstance(response, Mapping) else {}
    nodes = payload.get("nodes", []) if isinstance(payload, Mapping) else []

    by_uid: dict[str, Any] = {}
    by_path: dict[str, Any] = {}
    by_key: dict[str, Any] = {}

    if isinstance(nodes, list):
        for node in nodes:
            if not isinstance(node, Mapping):
                continue

            node_uid = node.get("node_uid")
            taxonomy_path = node.get("taxonomy_path")
            node_key = node.get("node_key") or node.get("slug")

            if node_uid:
                by_uid[str(node_uid)] = dict(node)

            if taxonomy_path:
                by_path[str(taxonomy_path)] = dict(node)

            if node_key:
                by_key[str(node_key)] = dict(node)

    return {
        "ok": True,
        "healthy": True,
        "status": "ok",
        "component": TAXONOMY_ROUTES_COMPONENT,
        "version": TAXONOMY_ROUTES_VERSION,
        "action": "lookup",
        "payload": {
            "user_id": _int_arg("user_id", default=1),
            "node_count": len(nodes) if isinstance(nodes, list) else 0,
            "by_uid": by_uid,
            "by_path": by_path,
            "by_key": by_key,
        },
    }


def _safe_legacy_health() -> Dict[str, Any]:
    """Return legacy service health safely."""
    try:
        service = _legacy_service()
        result = service.health(request.args)
        extracted = _route_response_to_payload(result)
        payload = extracted.get("payload") if isinstance(extracted, Mapping) else None

        if isinstance(payload, Mapping):
            return dict(payload)

        return {
            "ok": True,
            "healthy": True,
            "status": "ok",
            "payload": extracted,
        }
    except Exception as exc:
        return _unavailable_response(
            "legacy_taxonomy_service_unavailable",
            str(exc),
        )


def _safe_user_taxonomy_health() -> Dict[str, Any]:
    """Return user taxonomy service health safely."""
    try:
        service = _user_service()
        if hasattr(service, "get_health") and callable(service.get_health):
            return dict(service.get_health())

        return {
            "ok": True,
            "healthy": True,
            "status": "ok",
        }
    except Exception as exc:
        return _unavailable_response(
            "user_taxonomy_service_unavailable",
            str(exc),
        )


def clear_taxonomy_route_caches() -> Dict[str, Any]:
    """Clear route and downstream service caches."""
    cleared: list[str] = []

    for cached_func in (
        _load_legacy_taxonomy_route_service_module,
        _load_user_taxonomy_service_module,
    ):
        try:
            cached_func.cache_clear()
            cleared.append(getattr(cached_func, "__name__", str(cached_func)))
        except Exception:
            continue

    for loader, clear_function_name in (
        (_load_user_taxonomy_service_module, "clear_library_taxonomy_user_service_caches"),
    ):
        try:
            module = loader()
            clear_function = getattr(module, clear_function_name, None)
            if callable(clear_function):
                clear_function()
                cleared.append(clear_function_name)
        except Exception:
            continue

    return {
        "ok": True,
        "cleared": cleared,
    }


# Backward-compatible helper name used by existing code.
def _service() -> Any:
    return _legacy_service()


__all__ = [
    "TAXONOMY_ROUTES_COMPONENT",
    "TAXONOMY_ROUTES_VERSION",
    "TAXONOMY_ROUTE_PREFIX",
    "bp",
    "blueprint",
    "taxonomy_bp",
    "get_taxonomy_routes_info",
    "get_taxonomy_routes_health",
    "get_taxonomy_route_list",
    "clear_taxonomy_route_caches",
    "register_taxonomy_routes",
]