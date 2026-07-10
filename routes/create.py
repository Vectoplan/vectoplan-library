# services/vectoplan-library/routes/create.py
from __future__ import annotations

"""
VECTOPLAN Library – Create Blueprint

Flask adapter for the VPLIB create flow.

This route module intentionally stays thin:
- provides /create frontend route
- provides /api/v1/vplib/create/* API routes
- does not generate VPLIB documents directly
- does not validate package semantics directly
- does not write package files directly
- does not query SQLAlchemy directly
- does not call db.create_all()
- does not run migrations
- delegates HTTP-near work to:
    services.library_create_route_service
- that route service delegates generator workflow/context work to:
    library.services.library_generator_workflow_service
    library.services.library_generator_context_service
    library.services.library_generator_diagnostics_service

Primary routes:
    GET      /create
    GET      /api/v1/vplib/create
    GET      /api/v1/vplib/create/health
    GET      /api/v1/vplib/create/routes
    GET      /api/v1/vplib/create/selftest
    GET      /api/v1/vplib/create/readiness
    GET      /api/v1/vplib/create/creator-readiness
    GET      /api/v1/vplib/create/options
    GET|POST /api/v1/vplib/create/create-context
    GET|POST /api/v1/vplib/create/context
    GET      /api/v1/vplib/create/definitions/current
    POST     /api/v1/vplib/create/draft
    POST     /api/v1/vplib/create/drafts
    GET      /api/v1/vplib/create/drafts/<draft_ref>
    PATCH    /api/v1/vplib/create/drafts/<draft_ref>
    POST     /api/v1/vplib/create/drafts/<draft_ref>/validate
    POST     /api/v1/vplib/create/drafts/<draft_ref>/publish/prepare
    POST     /api/v1/vplib/create/validate
    POST     /api/v1/vplib/create/package-plan
    POST     /api/v1/vplib/create/publish-bundle
    POST     /api/v1/vplib/create/download
    POST     /api/v1/vplib/create/save
    POST     /api/v1/vplib/create/cache/clear

Important:
- /save delegates to lower services. Actual write permission remains controlled
  by lower service/env configuration.
- /draft remains backward-compatible. Persistent draft creation is opt-in via:
  persist=true, save_draft=true, db=true, persistent=true
- /drafts always means persistent draft intent.
- /download performs server-side validate + package-plan preflight by default.
- Generated downloads are accepted only when they are valid, bounded ZIP/VPLIB
  archives with safe member paths.
"""

import hashlib
import importlib
import io
import json
import os
import re
import traceback
import uuid
import zipfile
from dataclasses import asdict, is_dataclass
from enum import Enum
from functools import lru_cache
from types import ModuleType
from typing import Any, Callable, Iterable, Mapping

from flask import Blueprint, Response, current_app, jsonify, make_response, render_template, request, send_file


CREATE_BLUEPRINT_VERSION = "1.3.0"
CREATE_BLUEPRINT_COMPONENT = "create-blueprint"

CREATE_PAGE_ROUTE = "/create"
CREATE_API_PREFIX = "/api/v1/vplib/create"

CREATE_TEMPLATE = "vplib/create.html"
FALLBACK_TEMPLATE_TITLE = "VPLIB erstellen"

DEFAULT_JSON_MIMETYPE = "application/json"
DEFAULT_VPLIB_MIMETYPE = "application/octet-stream"

DEFAULT_MAX_REQUEST_BYTES = 64 * 1024 * 1024
DEFAULT_MAX_ARCHIVE_BYTES = 128 * 1024 * 1024
DEFAULT_MAX_ARCHIVE_ENTRIES = 4096
DEFAULT_MAX_ARCHIVE_UNCOMPRESSED_BYTES = 512 * 1024 * 1024
DEFAULT_MAX_COMPRESSION_RATIO = 250.0

STARTER_OBJECT_KIND = "cell_block"
STARTER_FAMILY_PROFILE_ID = "simple_cell_block"
STARTER_VARIANT_PROFILE_ID = "simple_cell_block.v1"
STARTER_DEFAULT_VARIANT_ID = "default"
STARTER_DEFAULT_LABEL = "Standard"
STARTER_DIMENSIONS_MM = {
    "dimensions.width_mm": 1000,
    "dimensions.height_mm": 1000,
    "dimensions.depth_mm": 1000,
}
STARTER_GEOMETRY_METRES = {
    "geometry_width": "1.00",
    "geometry_height": "1.00",
    "geometry_depth": "1.00",
    "geometry_unit": "m",
}
ZIP_SIGNATURES = (
    b"PK\x03\x04",
    b"PK\x05\x06",
    b"PK\x07\x08",
)
REQUEST_ID_PATTERN = re.compile(r"[^A-Za-z0-9._:-]+")

create_bp = Blueprint("vplib_create", __name__)

# Common aliases for central route registries.
bp = create_bp
blueprint = create_bp


class CreateRouteError(RuntimeError):
    """Base error for route-level create contract failures."""

    def __init__(
        self,
        message: str,
        *,
        code: str = "create_route_error",
        http_status: int = 500,
        details: Mapping[str, Any] | None = None,
    ) -> None:
        super().__init__(message)
        self.code = str(code or "create_route_error")
        self.http_status = _safe_http_status(http_status)
        self.details = dict(details or {})


class CreateRequestError(CreateRouteError):
    """Raised for malformed or unsafe create requests."""


class CreateArchiveError(CreateRouteError):
    """Raised when a generated VPLIB archive is invalid or unsafe."""


# ---------------------------------------------------------------------------
# Lazy service imports
# ---------------------------------------------------------------------------

def _import_first(module_names: Iterable[str]) -> ModuleType:
    errors: list[str] = []

    for module_name in module_names:
        try:
            return importlib.import_module(module_name)
        except Exception as exc:
            errors.append(f"{module_name}: {type(exc).__name__}: {exc}")

    raise ImportError("Could not import any module. " + " | ".join(errors))


@lru_cache(maxsize=1)
def _load_route_service_module() -> ModuleType:
    """Load services.library_create_route_service defensively."""
    return _import_first(
        (
            "services.library_create_route_service",
            "src.services.library_create_route_service",
            "vectoplan_library.services.library_create_route_service",
            "vectoplan_library.src.services.library_create_route_service",
        )
    )


@lru_cache(maxsize=1)
def _load_definition_catalog_service_module() -> ModuleType:
    """Load DB-backed Definition Catalog service defensively."""
    return _import_first(
        (
            "src.library.services.library_definition_catalog_service",
            "library.services.library_definition_catalog_service",
            "vectoplan_library.src.library.services.library_definition_catalog_service",
            "vectoplan_library.library.services.library_definition_catalog_service",
        )
    )


@lru_cache(maxsize=1)
def _load_creative_library_draft_service_module() -> ModuleType:
    """Load DB-backed Creative Library Draft service defensively."""
    return _import_first(
        (
            "src.library.services.creative_library_draft_service",
            "library.services.creative_library_draft_service",
            "vectoplan_library.src.library.services.creative_library_draft_service",
            "vectoplan_library.library.services.creative_library_draft_service",
        )
    )


@lru_cache(maxsize=1)
def _load_generator_diagnostics_service_module() -> ModuleType:
    """Load generator diagnostics service defensively."""
    return _import_first(
        (
            "src.library.services.library_generator_diagnostics_service",
            "library.services.library_generator_diagnostics_service",
            "vectoplan_library.src.library.services.library_generator_diagnostics_service",
            "vectoplan_library.library.services.library_generator_diagnostics_service",
        )
    )


@lru_cache(maxsize=1)
def _load_generator_context_service_module() -> ModuleType:
    """Load generator context service defensively."""
    return _import_first(
        (
            "src.library.services.library_generator_context_service",
            "library.services.library_generator_context_service",
            "vectoplan_library.src.library.services.library_generator_context_service",
            "vectoplan_library.library.services.library_generator_context_service",
        )
    )


def _route_service() -> ModuleType:
    """Return create route service module."""
    return _load_route_service_module()


def _create_definition_catalog_service() -> Any:
    """Create LibraryDefinitionCatalogService instance."""
    module = _load_definition_catalog_service_module()

    for factory_name in (
        "create_library_definition_catalog_service",
        "get_library_definition_catalog_service",
        "get_definition_catalog_service",
    ):
        factory = getattr(module, factory_name, None)
        if callable(factory):
            return factory()

    service_class = getattr(module, "LibraryDefinitionCatalogService", None)
    if service_class is None:
        raise RuntimeError("LibraryDefinitionCatalogService is not available.")

    return service_class()


def _create_draft_service() -> Any:
    """Create CreativeLibraryDraftService instance."""
    module = _load_creative_library_draft_service_module()

    for factory_name in (
        "create_creative_library_draft_service",
        "get_creative_library_draft_service",
        "get_library_draft_service",
    ):
        factory = getattr(module, factory_name, None)
        if callable(factory):
            return factory()

    service_class = getattr(module, "CreativeLibraryDraftService", None)
    if service_class is None:
        raise RuntimeError("CreativeLibraryDraftService is not available.")

    return service_class()


# ---------------------------------------------------------------------------
# Page
# ---------------------------------------------------------------------------

@create_bp.get(CREATE_PAGE_ROUTE)
def create_page() -> Response | str:
    """
    Render the VPLIB create frontend.

    The route stays small. The template receives generator-backed context,
    options, route map and health. If the final template is not present yet,
    a minimal fallback page is returned.
    """
    try:
        route_health = _json_safe(_safe_route_health_payload())
        options_payload = _json_safe(_safe_options_payload())
        context_payload = _json_safe(_safe_context_payload())
        definitions_payload = _json_safe(_safe_definitions_current_payload(user_id=1))

        context = _build_create_template_context(
            route_health=route_health,
            options_payload=options_payload,
            context_payload=context_payload,
            definitions_payload=definitions_payload,
        )

        try:
            return render_template(CREATE_TEMPLATE, **context)
        except Exception as template_error:
            return _render_fallback_page(
                template_error=template_error,
                health_payload=route_health,
                options_payload=options_payload,
                context_payload=context_payload,
                definitions_payload=definitions_payload,
            )
    except Exception as exc:
        payload = _failure_payload(
            route="page",
            code="create_page_failed",
            message="Die Create-Seite konnte nicht gerendert werden.",
            exc=exc,
            http_status=500,
        )
        return _json_response(payload, 500)


# ---------------------------------------------------------------------------
# Health / index / routes
# ---------------------------------------------------------------------------

@create_bp.get(f"{CREATE_API_PREFIX}/health")
def create_health() -> Response:
    """Health for create blueprint and delegated services."""
    payload = get_create_routes_health()
    return _json_response(payload, _status_code_from_payload(payload))


@create_bp.get(f"{CREATE_API_PREFIX}/routes")
def create_routes_map() -> Response:
    """Route map for manual checks."""
    payload = get_create_route_map_response()
    return _json_response(payload, 200)


@create_bp.get(f"{CREATE_API_PREFIX}/selftest")
def create_selftest() -> Response:
    """Route-level smoke test with optional generator diagnostics."""
    payload = {
        "ok": True,
        "status": "ok",
        "route": "selftest",
        "component": CREATE_BLUEPRINT_COMPONENT,
        "version": CREATE_BLUEPRINT_VERSION,
        "api_prefix": CREATE_API_PREFIX,
        "page_route": CREATE_PAGE_ROUTE,
        "route_service": _safe_route_service_health(),
        "creator_readiness": _starter_readiness_payload(request_id=_request_id()),
        "definition_catalog_service": _safe_definition_service_health(),
        "draft_service": _safe_draft_service_health(),
        "generator_diagnostics": _safe_generator_diagnostics_payload(
            {
                "checks": [
                    "imports",
                    "context_service_health",
                    "builder_health",
                    "minimal_context",
                    "route_contract",
                    "payload_contract",
                ],
                "include_optional": False,
                "include_payloads": False,
                "check_dependencies": False,
            }
        ),
        "_http_status": 200,
    }
    return _json_response(payload, 200)


@create_bp.get(f"{CREATE_API_PREFIX}/creator-readiness")
@create_bp.get(f"{CREATE_API_PREFIX}/readiness")
def create_creator_readiness() -> Response:
    """Report whether the minimal starter create flow can be resolved."""
    request_id = _request_id()
    payload = _starter_readiness_payload(request_id=request_id)
    return _json_response(
        payload,
        _status_code_from_payload(payload),
        request_id=request_id,
    )


@create_bp.get(f"{CREATE_API_PREFIX}/")
@create_bp.get(CREATE_API_PREFIX)
def create_index() -> Response:
    """Small API index for manual checks."""
    payload = {
        "ok": True,
        "status": "ok",
        "route": "index",
        "component": CREATE_BLUEPRINT_COMPONENT,
        "version": CREATE_BLUEPRINT_VERSION,
        "api_prefix": CREATE_API_PREFIX,
        "page_route": CREATE_PAGE_ROUTE,
        "routes": get_create_route_list(),
        "groups": get_create_route_groups(),
        "health": {
            "route_service_available": _is_route_service_available(),
            "definition_catalog_service_available": _is_definition_service_available(),
            "draft_service_available": _is_draft_service_available(),
            "generator_context_service_available": _is_generator_context_service_available(),
            "generator_diagnostics_service_available": _is_generator_diagnostics_service_available(),
        },
        "_http_status": 200,
    }
    return _json_response(payload, 200)


# ---------------------------------------------------------------------------
# Options / definitions / create context
# ---------------------------------------------------------------------------

@create_bp.get(f"{CREATE_API_PREFIX}/options")
def create_options() -> Response:
    """
    Return create options for the frontend.

    Default: generator-backed route service options.
    Optional compatibility:
    - ?source=definitions
    - ?definitions=true
    """
    use_definitions_only = (
        _request_bool("definitions", default=False)
        or _request_bool("resolved", default=False)
        or str(request.args.get("source", "")).strip().lower() in {"definitions", "definition", "db", "resolved"}
    )

    if use_definitions_only:
        payload = _safe_definitions_current_payload(user_id=_request_int("user_id", default=1))
        return _json_response(payload, _status_code_from_payload(payload))

    if not _is_route_service_available():
        payload = _route_service_unavailable_payload(route="options")
        return _json_response(payload, 503)

    try:
        response = _route_service().get_options_response(
            user_id=_request_int("user_id", default=1),
        )
        payload = _route_response_to_payload(response)
        return _json_response(payload, _status_code_from_payload(payload))
    except Exception as exc:
        payload = _failure_payload(
            route="options",
            code="options_failed",
            message="Create-Optionen konnten nicht geladen werden.",
            exc=exc,
            http_status=500,
        )
        return _json_response(payload, 500)


@create_bp.route(f"{CREATE_API_PREFIX}/create-context", methods=["GET", "POST"])
@create_bp.route(f"{CREATE_API_PREFIX}/context", methods=["GET", "POST"])
def create_context() -> Response:
    """Return generator-backed Create Context for UI/runtime."""
    if not _is_route_service_available():
        payload = _route_service_unavailable_payload(route="create-context")
        return _json_response(payload, 503)

    try:
        payload = _request_payload()
        response = _route_service().get_create_context_response(payload)
        return _json_route_response(response)
    except Exception as exc:
        payload = _failure_payload(
            route="create-context",
            code="create_context_failed",
            message="Create Context konnte nicht erzeugt werden.",
            exc=exc,
            http_status=500,
        )
        return _json_response(payload, 500)


@create_bp.get(f"{CREATE_API_PREFIX}/definitions/current")
def create_definitions_current() -> Response:
    """Return current resolved definition catalog through Create namespace."""
    if _is_route_service_available():
        try:
            response = _route_service().get_current_definitions_response(
                user_id=_request_int("user_id", default=1),
            )
            return _json_route_response(response)
        except Exception:
            pass

    payload = _safe_definition_call(
        lambda service: service.get_current_catalog(
            user_id=_request_int("user_id", default=1),
            resolved=_request_bool("resolved", default=True),
            include_inactive=_request_bool("include_inactive", default=False),
            include_deleted=_request_bool("include_deleted", default=False),
        ),
        route="definitions-current",
    )
    return _json_response(payload, _status_code_from_payload(payload))


# ---------------------------------------------------------------------------
# Create flow / drafts
# ---------------------------------------------------------------------------

@create_bp.post(f"{CREATE_API_PREFIX}/draft")
def create_draft() -> Response:
    """
    Normalize incoming form/JSON data into a stable draft.

    Default:
    - calls route_service.build_draft_response()

    Optional DB persistence:
    - persist=true
    - save_draft=true
    - db=true
    - persistent=true
    """
    if not _is_route_service_available():
        payload = _route_service_unavailable_payload(route="draft")
        return _json_response(payload, 503)

    try:
        payload = _request_payload()
        persist = _should_persist_draft(payload)

        if persist:
            response = _route_service().build_persistent_draft_payload_response(payload)
        else:
            response = _route_service().build_draft_response(payload)

        return _json_route_response(response)
    except Exception as exc:
        failure = _failure_payload(
            route="draft",
            code="draft_failed",
            message="Der Draft konnte nicht erzeugt werden.",
            exc=exc,
            http_status=422,
        )
        return _json_response(failure, 422)


@create_bp.post(f"{CREATE_API_PREFIX}/drafts")
def create_persistent_draft() -> Response:
    """
    Create persistent DB draft.

    Preferred:
    - route_service.build_persistent_draft_payload_response()
      which delegates to generator workflow.

    Fallback:
    - direct CreativeLibraryDraftService create_draft().
    """
    payload = _request_payload()

    if _is_route_service_available():
        try:
            response = _route_service().build_persistent_draft_payload_response(payload)
            response_payload = _route_response_to_payload(response)
            if bool(response_payload.get("ok", False)):
                return _json_response(response_payload, _status_code_from_payload(response_payload))
        except Exception:
            pass

    response_payload = _safe_draft_call(
        lambda service: _call_flexible(
            service.create_draft,
            _build_direct_draft_service_payload(payload),
            user_id=payload.get("user_id"),
            auto_validate=_safe_bool(payload.get("auto_validate"), default=False),
            commit=True,
        ),
        route="drafts",
    )
    return _json_response(response_payload, _status_code_from_payload(response_payload))


@create_bp.get(f"{CREATE_API_PREFIX}/drafts/<path:draft_ref>")
def create_persistent_draft_get(draft_ref: str) -> Response:
    """Read persistent DB draft through Create namespace."""
    response_payload = _safe_draft_call(
        lambda service: _call_flexible(
            service.get_draft,
            draft_ref,
            include_variants=_request_bool("include_variants", default=True),
            include_assets=_request_bool("include_assets", default=True),
            include_documents=_request_bool("include_documents", default=True),
            include_issues=_request_bool("include_issues", default=True),
            include_audit=_request_bool("include_audit", default=False),
            include_summary=_request_bool("include_summary", default=True),
        ),
        route="drafts-get",
    )
    return _json_response(response_payload, _status_code_from_payload(response_payload))


@create_bp.patch(f"{CREATE_API_PREFIX}/drafts/<path:draft_ref>")
def create_persistent_draft_patch(draft_ref: str) -> Response:
    """Update persistent DB draft through Create namespace."""
    payload = _request_payload()

    response_payload = _safe_draft_call(
        lambda service: _call_flexible(
            service.update_draft,
            draft_ref,
            _build_direct_draft_service_payload(payload),
            user_id=payload.get("user_id"),
            auto_validate=_safe_bool(payload.get("auto_validate"), default=False),
            commit=True,
        ),
        route="drafts-patch",
    )
    return _json_response(response_payload, _status_code_from_payload(response_payload))


@create_bp.post(f"{CREATE_API_PREFIX}/drafts/<path:draft_ref>/validate")
def create_persistent_draft_validate(draft_ref: str) -> Response:
    """Validate persistent DB draft through Create namespace."""
    payload = _request_payload()

    response_payload = _safe_draft_call(
        lambda service: _call_flexible(
            service.validate_draft,
            draft_ref,
            user_id=payload.get("user_id"),
            replace_existing=_safe_bool(payload.get("replace_existing"), default=True),
            commit=True,
        ),
        route="drafts-validate",
    )
    return _json_response(response_payload, _status_code_from_payload(response_payload))


@create_bp.post(f"{CREATE_API_PREFIX}/drafts/<path:draft_ref>/publish/prepare")
def create_persistent_draft_publish_prepare(draft_ref: str) -> Response:
    """Build publish payload for persistent DB draft through Create namespace."""
    payload = _request_payload()

    if _is_route_service_available():
        try:
            workflow_payload = dict(payload)
            workflow_payload["draft_ref"] = draft_ref
            response = _route_service().build_publish_bundle_response(workflow_payload)
            response_payload = _route_response_to_payload(response)
            if bool(response_payload.get("ok", False)):
                return _json_response(response_payload, _status_code_from_payload(response_payload))
        except Exception:
            pass

    response_payload = _safe_draft_call(
        lambda service: _call_flexible(
            service.prepare_publish_payload,
            draft_ref,
            user_id=payload.get("user_id"),
            validate_first=_safe_bool(payload.get("validate_first"), default=True),
            allow_invalid=_safe_bool(payload.get("allow_invalid"), default=False),
        ),
        route="drafts-publish-prepare",
    )
    return _json_response(response_payload, _status_code_from_payload(response_payload))


# ---------------------------------------------------------------------------
# Validation / package plan / publish-bundle / download / save
# ---------------------------------------------------------------------------

@create_bp.post(f"{CREATE_API_PREFIX}/validate")
def create_validate() -> Response:
    """Validate a normalized create payload through the route service."""
    request_id = _request_id()

    if not _is_route_service_available():
        payload = _route_service_unavailable_payload(route="validate")
        return _json_response(payload, 503, request_id=request_id)

    try:
        payload = _prepare_create_payload(
            _request_payload(),
            route="validate",
            request_id=request_id,
        )
        _validate_starter_payload(payload, route="validate")

        response = _route_service().validate_draft_response(payload)
        response_payload = _route_response_to_payload(response)
        _attach_route_metadata(
            response_payload,
            route="validate",
            request_id=request_id,
            request_payload=payload,
        )
        return _json_response(
            response_payload,
            _status_code_from_payload(response_payload),
            request_id=request_id,
        )
    except CreateRouteError as exc:
        failure = _create_route_error_payload(exc, route="validate", request_id=request_id)
        return _json_response(failure, exc.http_status, request_id=request_id)
    except Exception as exc:
        failure = _failure_payload(
            route="validate",
            code="validation_failed",
            message="Die Validierung konnte nicht ausgeführt werden.",
            exc=exc,
            http_status=422,
        )
        return _json_response(failure, 422, request_id=request_id)


@create_bp.post(f"{CREATE_API_PREFIX}/package-plan")
def create_package_plan() -> Response:
    """Build a package plan from the same normalized payload used by download."""
    request_id = _request_id()

    if not _is_route_service_available():
        payload = _route_service_unavailable_payload(route="package-plan")
        return _json_response(payload, 503, request_id=request_id)

    try:
        payload = _prepare_create_payload(
            _request_payload(),
            route="package-plan",
            request_id=request_id,
        )
        _validate_starter_payload(payload, route="package-plan")
        include_documents = _resolve_include_documents(payload)

        response = _route_service().build_package_plan_response(
            payload,
            include_documents=include_documents,
        )
        response_payload = _route_response_to_payload(response)
        _attach_route_metadata(
            response_payload,
            route="package-plan",
            request_id=request_id,
            request_payload=payload,
            extra={"include_documents": include_documents},
        )
        return _json_response(
            response_payload,
            _status_code_from_payload(response_payload),
            request_id=request_id,
        )
    except CreateRouteError as exc:
        failure = _create_route_error_payload(exc, route="package-plan", request_id=request_id)
        return _json_response(failure, exc.http_status, request_id=request_id)
    except Exception as exc:
        failure = _failure_payload(
            route="package-plan",
            code="package_plan_failed",
            message="Der Package-Plan konnte nicht erzeugt werden.",
            exc=exc,
            http_status=500,
        )
        return _json_response(failure, 500, request_id=request_id)


@create_bp.post(f"{CREATE_API_PREFIX}/publish-bundle")
def create_publish_bundle() -> Response:
    """Build publish-bundle / publish-prepare payload without direct publish."""
    if not _is_route_service_available():
        payload = _route_service_unavailable_payload(route="publish-bundle")
        return _json_response(payload, 503)

    try:
        payload = _request_payload()
        response = _route_service().build_publish_bundle_response(payload)
        return _json_route_response(response)
    except Exception as exc:
        payload = _failure_payload(
            route="publish-bundle",
            code="publish_bundle_failed",
            message="Publish-Bundle konnte nicht erzeugt werden.",
            exc=exc,
            http_status=500,
        )
        return _json_response(payload, 500)


@create_bp.post(f"{CREATE_API_PREFIX}/save")
def create_save() -> Response:
    """Save package into source root when lower service explicitly allows writing."""
    if not _is_route_service_available():
        payload = _route_service_unavailable_payload(route="save")
        return _json_response(payload, 503)

    try:
        payload = _request_payload()
        overwrite = _request_optional_bool("overwrite")
        response = _route_service().save_package_response(
            payload,
            overwrite=overwrite,
        )
        return _json_route_response(response)
    except Exception as exc:
        payload = _failure_payload(
            route="save",
            code="save_failed",
            message="Das Package konnte nicht gespeichert werden.",
            exc=exc,
            http_status=500,
        )
        return _json_response(payload, 500)


@create_bp.post(f"{CREATE_API_PREFIX}/download")
def create_download() -> Response:
    """Validate, plan and return a verified in-memory ``.vplib`` ZIP archive."""
    request_id = _request_id()

    if not _is_route_service_available():
        payload = _route_service_unavailable_payload(route="download")
        return _json_response(payload, 503, request_id=request_id)

    try:
        payload = _prepare_create_payload(
            _request_payload(),
            route="download",
            request_id=request_id,
        )
        _validate_starter_payload(payload, route="download")

        preflight = _run_download_preflight(payload, request_id=request_id)
        if not bool(preflight.get("ok", False)):
            return _json_response(
                preflight,
                _status_code_from_payload(preflight),
                request_id=request_id,
            )

        binary_response = _route_service().build_download_response(payload)

        if not bool(_extract_from_mapping_or_object(binary_response, "ok")):
            meta_payload = _binary_response_to_payload(binary_response)
            _attach_route_metadata(
                meta_payload,
                route="download",
                request_id=request_id,
                request_payload=payload,
                extra={"preflight": preflight.get("data", {})},
            )
            return _json_response(
                meta_payload,
                _safe_http_status(
                    _extract_from_mapping_or_object(binary_response, "http_status") or 500
                ),
                request_id=request_id,
            )

        filename = _safe_filename(
            _extract_from_mapping_or_object(binary_response, "filename") or "package.vplib"
        )
        content = _coerce_archive_bytes(
            _extract_from_mapping_or_object(binary_response, "content")
        )
        archive_info = _validate_vplib_archive(content)
        mimetype = (
            _extract_from_mapping_or_object(binary_response, "mimetype")
            or DEFAULT_VPLIB_MIMETYPE
        )
        status_code = _safe_http_status(
            _extract_from_mapping_or_object(binary_response, "http_status") or 200
        )

        file_response = send_file(
            io.BytesIO(content),
            mimetype=str(mimetype),
            as_attachment=True,
            download_name=filename,
            max_age=0,
            conditional=False,
        )
        file_response.status_code = status_code
        file_response.headers["X-VECTOPLAN-Create-Status"] = str(
            _extract_from_mapping_or_object(binary_response, "status") or "archive_ready"
        )
        file_response.headers["X-VECTOPLAN-Create-Route"] = "download"
        file_response.headers["X-VECTOPLAN-Create-Version"] = CREATE_BLUEPRINT_VERSION
        file_response.headers["X-VECTOPLAN-Request-ID"] = request_id
        file_response.headers["X-VECTOPLAN-Archive-SHA256"] = archive_info["sha256"]
        file_response.headers["X-VECTOPLAN-Archive-Entries"] = str(
            archive_info["entry_count"]
        )
        file_response.headers["X-Content-Type-Options"] = "nosniff"
        file_response.headers["Cache-Control"] = "no-store, no-cache, must-revalidate, max-age=0"
        file_response.headers["Pragma"] = "no-cache"
        file_response.headers["Expires"] = "0"

        vplib_uid = _extract_from_mapping_or_object(binary_response, "vplib_uid")
        if vplib_uid:
            file_response.headers["X-VECTOPLAN-VPLIB-UID"] = str(vplib_uid)

        return file_response
    except CreateRouteError as exc:
        failure = _create_route_error_payload(exc, route="download", request_id=request_id)
        return _json_response(failure, exc.http_status, request_id=request_id)
    except Exception as exc:
        payload = _failure_payload(
            route="download",
            code="download_failed",
            message="Das VPLIB-Archiv konnte nicht erzeugt werden.",
            exc=exc,
            http_status=500,
        )
        return _json_response(payload, 500, request_id=request_id)


@create_bp.post(f"{CREATE_API_PREFIX}/cache/clear")
def create_cache_clear() -> Response:
    """Clear create route/service caches."""
    cleared = clear_create_route_caches()

    route_payload = None
    if _is_route_service_available():
        try:
            response = _route_service().clear_cache_response()
            route_payload = _route_response_to_payload(response)
        except Exception as exc:
            route_payload = _failure_payload(
                route="cache-clear",
                code="route_service_cache_clear_failed",
                message="Create-Route-Service-Cache konnte nicht geleert werden.",
                exc=exc,
                http_status=500,
            )

    payload = {
        "ok": True,
        "status": "ok",
        "route": "cache-clear",
        "component": CREATE_BLUEPRINT_COMPONENT,
        "version": CREATE_BLUEPRINT_VERSION,
        "api_prefix": CREATE_API_PREFIX,
        "cleared": cleared.get("cleared", []),
        "route_service": route_payload,
        "_http_status": 200,
    }
    return _json_response(payload, 200)


# ---------------------------------------------------------------------------
# Starter contract / request and archive guards
# ---------------------------------------------------------------------------

def _request_id() -> str:
    """Return a bounded request/correlation identifier."""
    candidates = (
        request.headers.get("X-Request-ID"),
        request.headers.get("X-Correlation-ID"),
        request.headers.get("X-VECTOPLAN-Request-ID"),
    )

    for candidate in candidates:
        text = REQUEST_ID_PATTERN.sub("-", str(candidate or "").strip()).strip("-._:")
        if text:
            return text[:96]

    return uuid.uuid4().hex


def _configured_int(name: str, default: int, *, minimum: int = 1) -> int:
    value: Any = None

    try:
        value = current_app.config.get(name)
    except Exception:
        value = None

    if value is None:
        value = os.getenv(name)

    try:
        parsed = int(value)
    except Exception:
        parsed = int(default)

    return max(int(minimum), parsed)


def _ensure_request_size() -> None:
    limit = _configured_int(
        "VECTOPLAN_CREATE_MAX_REQUEST_BYTES",
        DEFAULT_MAX_REQUEST_BYTES,
        minimum=1024,
    )

    try:
        content_length = request.content_length
    except Exception:
        content_length = None

    if content_length is not None and int(content_length) > limit:
        raise CreateRequestError(
            f"Create request exceeds the configured limit of {limit} bytes.",
            code="request_too_large",
            http_status=413,
            details={
                "content_length": int(content_length),
                "max_request_bytes": limit,
            },
        )


def _normalize_identifier(value: Any, *, fallback: str = "") -> str:
    text = str(value or "").replace("\x00", "").strip()
    if not text:
        return fallback

    text = text.replace("-", "_").replace(" ", "_")
    text = re.sub(r"[^A-Za-z0-9_.:/]+", "", text)
    return text or fallback


def _normalize_embedded_json_fields(payload: dict[str, Any]) -> dict[str, Any]:
    field_types: dict[str, type] = {
        "definition_variants_json": list,
        "definitionVariantsJson": list,
        "geometry_model_uploads_json": dict,
        "geometryModelUploadsJson": dict,
        "technical_document_uploads_json": dict,
        "technicalDocumentUploadsJson": dict,
        "variant_document_uploads_json": dict,
        "variantDocumentUploadsJson": dict,
        "uploads_json": dict,
        "uploadsJson": dict,
    }

    for field_name, expected_type in field_types.items():
        value = payload.get(field_name)
        if not isinstance(value, str) or not value.strip():
            continue

        try:
            decoded = json.loads(value)
        except Exception as exc:
            raise CreateRequestError(
                f"Field {field_name!r} does not contain valid JSON.",
                code="invalid_embedded_json",
                http_status=400,
                details={"field": field_name},
            ) from exc

        if not isinstance(decoded, expected_type):
            raise CreateRequestError(
                f"Field {field_name!r} must contain a JSON {expected_type.__name__}.",
                code="invalid_embedded_json_type",
                http_status=400,
                details={
                    "field": field_name,
                    "expected": expected_type.__name__,
                    "actual": type(decoded).__name__,
                },
            )

        payload[field_name] = decoded

    return payload


def _first_payload_value(payload: Mapping[str, Any], *keys: str) -> Any:
    for key in keys:
        value = payload.get(key)
        if value is None:
            continue
        if isinstance(value, str) and not value.strip():
            continue
        return value
    return None


def _mirror_payload_alias(
    payload: dict[str, Any],
    snake_key: str,
    camel_key: str,
    *,
    default: Any = None,
) -> Any:
    value = _first_payload_value(payload, snake_key, camel_key)
    if value is None:
        value = default

    if value is not None:
        payload[snake_key] = value
        payload[camel_key] = value

    return value


def _json_mapping_from_any(value: Any) -> dict[str, Any]:
    if isinstance(value, Mapping):
        return _json_safe(dict(value))

    if isinstance(value, str) and value.strip():
        try:
            decoded = json.loads(value)
        except Exception:
            return {}
        if isinstance(decoded, Mapping):
            return _json_safe(dict(decoded))

    return {}


def _json_list_from_payload(value: Any) -> list[Any]:
    if isinstance(value, list):
        return _json_safe(value)

    if isinstance(value, tuple):
        return _json_safe(list(value))

    if isinstance(value, str) and value.strip():
        try:
            decoded = json.loads(value)
        except Exception:
            return []
        if isinstance(decoded, list):
            return _json_safe(decoded)

    return []


def _positive_number(value: Any, *, fallback: float | None = None) -> float | None:
    try:
        number = float(str(value).strip().replace(",", "."))
    except Exception:
        return fallback

    if number <= 0:
        return fallback

    return number


def _geometry_value_to_mm(value: Any, unit: Any) -> int | None:
    number = _positive_number(value)
    if number is None:
        return None

    unit_text = str(unit or "m").strip().lower()
    factors = {
        "mm": 1.0,
        "millimeter": 1.0,
        "millimetre": 1.0,
        "cm": 10.0,
        "m": 1000.0,
        "meter": 1000.0,
        "metre": 1000.0,
    }
    factor = factors.get(unit_text, 1000.0)
    return max(1, int(round(number * factor)))


def _empty_upload_contract(kind: str) -> dict[str, Any]:
    return {
        "kind": kind,
        "count": 0,
        "files": [],
        "errors": [],
        "ok": True,
        "required": False,
        "local_only": True,
        "localOnly": True,
        "backend_stored": False,
        "backendStored": False,
    }


def _prepare_create_payload(
    payload: Mapping[str, Any] | None,
    *,
    route: str,
    request_id: str,
) -> dict[str, Any]:
    """Normalize aliases and materialize the minimal starter contract."""
    data = _json_safe(dict(payload or {}))
    if not isinstance(data, dict):
        data = {}

    _normalize_embedded_json_fields(data)

    object_kind = _normalize_identifier(
        _first_payload_value(data, "object_kind", "objectKind", "object_class"),
        fallback=STARTER_OBJECT_KIND,
    ).lower()
    family_profile_id = _normalize_identifier(
        _first_payload_value(data, "family_profile_id", "familyProfileId"),
        fallback="",
    )
    variant_profile_id = _normalize_identifier(
        _first_payload_value(data, "variant_profile_id", "variantProfileId"),
        fallback="",
    )

    starter_requested = (
        object_kind == STARTER_OBJECT_KIND
        and family_profile_id in {"", STARTER_FAMILY_PROFILE_ID}
        and variant_profile_id in {"", STARTER_VARIANT_PROFILE_ID}
    )

    if starter_requested:
        family_profile_id = STARTER_FAMILY_PROFILE_ID
        variant_profile_id = STARTER_VARIANT_PROFILE_ID

    data["object_kind"] = object_kind
    data["objectKind"] = object_kind
    _mirror_payload_alias(
        data,
        "family_profile_id",
        "familyProfileId",
        default=family_profile_id,
    )
    _mirror_payload_alias(
        data,
        "variant_profile_id",
        "variantProfileId",
        default=variant_profile_id,
    )

    data["domain"] = _normalize_identifier(data.get("domain"), fallback="hochbau").lower()
    data["category"] = _normalize_identifier(data.get("category"), fallback="bloecke").lower()
    data["subcategory"] = _normalize_identifier(
        data.get("subcategory"),
        fallback="basis",
    ).lower()
    taxonomy_path = str(
        _first_payload_value(data, "taxonomy_path", "taxonomyPath")
        or f"{data['domain']}/{data['category']}/{data['subcategory']}"
    ).strip().replace("\\", "/")
    taxonomy_path = "/".join(
        _normalize_identifier(part, fallback="").lower()
        for part in taxonomy_path.split("/")
        if _normalize_identifier(part, fallback="")
    )
    data["taxonomy_path"] = taxonomy_path
    data["taxonomyPath"] = taxonomy_path

    if starter_requested:
        family_name_value = str(
            _first_payload_value(data, "family_name", "familyName")
            or "Simple Cell Block"
        ).strip()
        data["family_name"] = family_name_value
        data["familyName"] = family_name_value

        primitive_shape_value = str(
            _first_payload_value(data, "primitive_shape", "primitiveShape")
            or "block"
        ).strip()
        data["primitive_shape"] = primitive_shape_value
        data["primitiveShape"] = primitive_shape_value

        for snake_key, camel_key in (
            ("editor_cells_x", "editorCellsX"),
            ("editor_cells_y", "editorCellsY"),
            ("editor_cells_z", "editorCellsZ"),
        ):
            raw_value = _first_payload_value(data, snake_key, camel_key)
            normalized_value = _positive_number(raw_value, fallback=1.0) or 1.0
            text_value = str(int(normalized_value))
            data[snake_key] = text_value
            data[camel_key] = text_value

        for snake_key, camel_key, default_value in (
            ("geometry_width", "geometryWidth", "1.00"),
            ("geometry_height", "geometryHeight", "1.00"),
            ("geometry_depth", "geometryDepth", "1.00"),
            ("geometry_unit", "geometryUnit", "m"),
        ):
            value = str(
                _first_payload_value(data, snake_key, camel_key)
                or default_value
            ).strip()
            data[snake_key] = value
            data[camel_key] = value

        dimension_values = {
            "dimensions.width_mm": _geometry_value_to_mm(
                data.get("geometry_width"),
                data.get("geometry_unit"),
            )
            or STARTER_DIMENSIONS_MM["dimensions.width_mm"],
            "dimensions.height_mm": _geometry_value_to_mm(
                data.get("geometry_height"),
                data.get("geometry_unit"),
            )
            or STARTER_DIMENSIONS_MM["dimensions.height_mm"],
            "dimensions.depth_mm": _geometry_value_to_mm(
                data.get("geometry_depth"),
                data.get("geometry_unit"),
            )
            or STARTER_DIMENSIONS_MM["dimensions.depth_mm"],
        }

        dimensions = _json_mapping_from_any(data.get("dimensions"))
        dimensions.setdefault("width_mm", dimension_values["dimensions.width_mm"])
        dimensions.setdefault("height_mm", dimension_values["dimensions.height_mm"])
        dimensions.setdefault("depth_mm", dimension_values["dimensions.depth_mm"])
        data["dimensions"] = dimensions

        variants = _json_list_from_payload(
            _first_payload_value(
                data,
                "definition_variants",
                "definitionVariants",
                "definition_variants_json",
                "definitionVariantsJson",
            )
        )

        normalized_variants: list[dict[str, Any]] = []
        for index, raw_variant in enumerate(variants):
            variant = _json_mapping_from_any(raw_variant)
            if not variant:
                continue

            variant_id = _normalize_identifier(
                _first_payload_value(variant, "variant_id", "variantId", "id"),
                fallback=STARTER_DEFAULT_VARIANT_ID if index == 0 else f"variant_{index + 1}",
            )
            label = str(
                _first_payload_value(variant, "label", "name", "title")
                or (STARTER_DEFAULT_LABEL if index == 0 else f"Variante {index + 1}")
            ).strip()
            definition_values = _json_mapping_from_any(
                _first_payload_value(
                    variant,
                    "definition_values",
                    "definitionValues",
                    "values",
                    "definition_values_json",
                    "definitionValuesJson",
                )
            )

            definition_values.setdefault("variant.variant_id", variant_id)
            definition_values.setdefault("variant.label", label)
            for field_key, field_value in dimension_values.items():
                definition_values.setdefault(field_key, field_value)

            variant.update(
                {
                    "variant_id": variant_id,
                    "variantId": variant_id,
                    "label": label,
                    "name": label,
                    "family_profile_id": STARTER_FAMILY_PROFILE_ID,
                    "familyProfileId": STARTER_FAMILY_PROFILE_ID,
                    "variant_profile_id": STARTER_VARIANT_PROFILE_ID,
                    "variantProfileId": STARTER_VARIANT_PROFILE_ID,
                    "object_kind": STARTER_OBJECT_KIND,
                    "objectKind": STARTER_OBJECT_KIND,
                    "definition_values": definition_values,
                    "definitionValues": definition_values,
                    "definition_values_json": json.dumps(
                        definition_values,
                        ensure_ascii=False,
                        separators=(",", ":"),
                    ),
                    "definitionValuesJson": json.dumps(
                        definition_values,
                        ensure_ascii=False,
                        separators=(",", ":"),
                    ),
                }
            )
            normalized_variants.append(variant)

        if not normalized_variants:
            definition_values = {
                "variant.variant_id": STARTER_DEFAULT_VARIANT_ID,
                "variant.label": STARTER_DEFAULT_LABEL,
                **dimension_values,
            }
            normalized_variants = [
                {
                    "variant_id": STARTER_DEFAULT_VARIANT_ID,
                    "variantId": STARTER_DEFAULT_VARIANT_ID,
                    "label": STARTER_DEFAULT_LABEL,
                    "name": STARTER_DEFAULT_LABEL,
                    "description": "",
                    "is_default": True,
                    "isDefault": True,
                    "family_profile_id": STARTER_FAMILY_PROFILE_ID,
                    "familyProfileId": STARTER_FAMILY_PROFILE_ID,
                    "variant_profile_id": STARTER_VARIANT_PROFILE_ID,
                    "variantProfileId": STARTER_VARIANT_PROFILE_ID,
                    "object_kind": STARTER_OBJECT_KIND,
                    "objectKind": STARTER_OBJECT_KIND,
                    "definition_values": definition_values,
                    "definitionValues": definition_values,
                    "definition_values_json": json.dumps(
                        definition_values,
                        ensure_ascii=False,
                        separators=(",", ":"),
                    ),
                    "definitionValuesJson": json.dumps(
                        definition_values,
                        ensure_ascii=False,
                        separators=(",", ":"),
                    ),
                    "additional_field_keys": [],
                    "additionalFieldKeys": [],
                    "source": "routes.create.starter_default",
                }
            ]

        default_index = next(
            (
                index
                for index, variant in enumerate(normalized_variants)
                if _safe_bool(
                    _first_payload_value(variant, "is_default", "isDefault"),
                    default=False,
                )
                or variant.get("variant_id") == STARTER_DEFAULT_VARIANT_ID
            ),
            0,
        )
        for index, variant in enumerate(normalized_variants):
            is_default = index == default_index
            variant["is_default"] = is_default
            variant["isDefault"] = is_default

        default_variant_id = str(
            normalized_variants[default_index].get("variant_id")
            or STARTER_DEFAULT_VARIANT_ID
        )
        data["definition_variants"] = normalized_variants
        data["definitionVariants"] = normalized_variants
        variants_json = json.dumps(
            normalized_variants,
            ensure_ascii=False,
            separators=(",", ":"),
        )
        data["definition_variants_json"] = variants_json
        data["definitionVariantsJson"] = variants_json
        data["default_variant_id"] = default_variant_id
        data["defaultVariantId"] = default_variant_id

        geometry_upload = _json_mapping_from_any(
            _first_payload_value(
                data,
                "geometry_model_uploads",
                "geometryModelUploads",
                "geometry_model_uploads_json",
                "geometryModelUploadsJson",
            )
        ) or _empty_upload_contract("geometry_model")
        technical_upload = _json_mapping_from_any(
            _first_payload_value(
                data,
                "technical_document_uploads",
                "technicalDocumentUploads",
                "technical_document_uploads_json",
                "technicalDocumentUploadsJson",
            )
        ) or _empty_upload_contract("technical_documents")
        variant_upload = _json_mapping_from_any(
            _first_payload_value(
                data,
                "variant_document_uploads",
                "variantDocumentUploads",
                "variant_document_uploads_json",
                "variantDocumentUploadsJson",
            )
        ) or _empty_upload_contract("variant_documents")

        data["geometry_model_uploads"] = geometry_upload
        data["geometryModelUploads"] = geometry_upload
        data["technical_document_uploads"] = technical_upload
        data["technicalDocumentUploads"] = technical_upload
        data["variant_document_uploads"] = variant_upload
        data["variantDocumentUploads"] = variant_upload
        data["geometry_model_uploads_json"] = json.dumps(
            geometry_upload,
            ensure_ascii=False,
            separators=(",", ":"),
        )
        data["geometryModelUploadsJson"] = data["geometry_model_uploads_json"]
        data["technical_document_uploads_json"] = json.dumps(
            technical_upload,
            ensure_ascii=False,
            separators=(",", ":"),
        )
        data["technicalDocumentUploadsJson"] = data[
            "technical_document_uploads_json"
        ]
        data["variant_document_uploads_json"] = json.dumps(
            variant_upload,
            ensure_ascii=False,
            separators=(",", ":"),
        )
        data["variantDocumentUploadsJson"] = data[
            "variant_document_uploads_json"
        ]
        data.setdefault("documents", [])
        data.setdefault("assets", [])
        data.setdefault("include_documents", False)
        data.setdefault("includeDocuments", data["include_documents"])

    data["_request_id"] = request_id
    data["_create_route"] = route
    data["_create_blueprint_version"] = CREATE_BLUEPRINT_VERSION
    data["_starter_contract"] = {
        "requested": starter_requested,
        "object_kind": object_kind,
        "family_profile_id": family_profile_id,
        "variant_profile_id": variant_profile_id,
        "default_variant_id": data.get("default_variant_id"),
        "dimensions_mm": (
            {
                "width": data.get("dimensions", {}).get("width_mm"),
                "height": data.get("dimensions", {}).get("height_mm"),
                "depth": data.get("dimensions", {}).get("depth_mm"),
            }
            if starter_requested
            else {}
        ),
    }
    return data


def _validate_starter_payload(payload: Mapping[str, Any], *, route: str) -> None:
    starter = _safe_mapping(payload.get("_starter_contract"))
    if not _safe_bool(starter.get("requested"), default=False):
        return

    issues: list[dict[str, Any]] = []

    if payload.get("object_kind") != STARTER_OBJECT_KIND:
        issues.append(
            {
                "field": "object_kind",
                "code": "starter_object_kind_invalid",
                "expected": STARTER_OBJECT_KIND,
                "actual": payload.get("object_kind"),
            }
        )

    if payload.get("family_profile_id") != STARTER_FAMILY_PROFILE_ID:
        issues.append(
            {
                "field": "family_profile_id",
                "code": "starter_family_profile_invalid",
                "expected": STARTER_FAMILY_PROFILE_ID,
                "actual": payload.get("family_profile_id"),
            }
        )

    if payload.get("variant_profile_id") != STARTER_VARIANT_PROFILE_ID:
        issues.append(
            {
                "field": "variant_profile_id",
                "code": "starter_variant_profile_invalid",
                "expected": STARTER_VARIANT_PROFILE_ID,
                "actual": payload.get("variant_profile_id"),
            }
        )

    variants = _json_list_from_payload(
        _first_payload_value(
            payload,
            "definition_variants",
            "definitionVariants",
            "definition_variants_json",
            "definitionVariantsJson",
        )
    )
    if not variants:
        issues.append(
            {
                "field": "definition_variants",
                "code": "starter_variant_missing",
            }
        )
    else:
        default_variant = next(
            (
                _json_mapping_from_any(variant)
                for variant in variants
                if _safe_bool(
                    _first_payload_value(
                        _json_mapping_from_any(variant),
                        "is_default",
                        "isDefault",
                    ),
                    default=False,
                )
            ),
            _json_mapping_from_any(variants[0]),
        )
        values = _json_mapping_from_any(
            _first_payload_value(
                default_variant,
                "definition_values",
                "definitionValues",
                "definition_values_json",
                "definitionValuesJson",
            )
        )

        for field_key in (
            "variant.variant_id",
            "variant.label",
            *STARTER_DIMENSIONS_MM.keys(),
        ):
            if field_key not in values:
                issues.append(
                    {
                        "field": field_key,
                        "code": "starter_default_missing",
                    }
                )

        for field_key in STARTER_DIMENSIONS_MM:
            if _positive_number(values.get(field_key)) is None:
                issues.append(
                    {
                        "field": field_key,
                        "code": "starter_dimension_invalid",
                        "actual": values.get(field_key),
                    }
                )

    if issues:
        raise CreateRequestError(
            "The minimal cell_block starter payload is incomplete.",
            code="starter_payload_invalid",
            http_status=422,
            details={
                "route": route,
                "issues": issues,
            },
        )


def _resolve_include_documents(payload: Mapping[str, Any]) -> bool:
    for key in ("include_documents", "includeDocuments"):
        if key in payload:
            return _safe_bool(payload.get(key), default=False)

    starter = _safe_mapping(payload.get("_starter_contract"))
    if _safe_bool(starter.get("requested"), default=False):
        return False

    return _request_bool("include_documents", default=True)


def _payload_has_error_issues(payload: Mapping[str, Any]) -> bool:
    errors = payload.get("errors")
    if isinstance(errors, list):
        return any(
            not isinstance(issue, Mapping)
            or str(issue.get("severity") or "error").lower() == "error"
            for issue in errors
        )
    return bool(errors)


def _route_payload_succeeded(
    payload: Mapping[str, Any],
    *,
    require_valid: bool = False,
) -> bool:
    if not isinstance(payload, Mapping):
        return False

    if payload.get("ok") is False:
        return False

    status = str(payload.get("status") or "").strip().lower()
    if status in {
        "invalid",
        "draft_invalid",
        "validation_failed",
        "failed",
        "error",
        "not_found",
        "unavailable",
    }:
        return False

    if _payload_has_error_issues(payload):
        return False

    if require_valid:
        valid_candidates = (
            payload.get("valid"),
            payload.get("is_valid"),
            payload.get("isValid"),
            _nested_value(payload, "data.valid"),
            _nested_value(payload, "data.is_valid"),
            _nested_value(payload, "validation.valid"),
        )
        for candidate in valid_candidates:
            if candidate is False:
                return False

    return bool(payload.get("ok", True))


def _compact_service_payload(payload: Mapping[str, Any]) -> dict[str, Any]:
    data = dict(payload or {})
    compact = {
        "ok": bool(data.get("ok", False)),
        "status": data.get("status"),
        "route": data.get("route"),
        "_http_status": data.get("_http_status"),
        "errors": _json_safe(data.get("errors") or []),
        "warnings": _json_safe(data.get("warnings") or []),
    }

    for key in ("valid", "is_valid", "isValid", "summary"):
        if key in data:
            compact[key] = _json_safe(data[key])

    return compact


def _run_download_preflight(
    payload: Mapping[str, Any],
    *,
    request_id: str,
) -> dict[str, Any]:
    if not _safe_bool(payload.get("server_preflight"), default=True):
        return {
            "ok": True,
            "status": "preflight_skipped",
            "route": "download-preflight",
            "data": {"skipped": True},
            "_http_status": 200,
        }

    validation_response = _route_service().validate_draft_response(dict(payload))
    validation_payload = _route_response_to_payload(validation_response)
    if not _route_payload_succeeded(validation_payload, require_valid=True):
        failure = {
            "ok": False,
            "status": "download_preflight_validation_failed",
            "route": "download",
            "component": CREATE_BLUEPRINT_COMPONENT,
            "version": CREATE_BLUEPRINT_VERSION,
            "errors": validation_payload.get("errors")
            or [
                {
                    "severity": "error",
                    "code": "download_preflight_validation_failed",
                    "field": "validate",
                    "message": "Server-side validation failed before archive generation.",
                }
            ],
            "warnings": validation_payload.get("warnings") or [],
            "data": {
                "validation": _compact_service_payload(validation_payload),
            },
            "_http_status": _safe_http_status(
                validation_payload.get("_http_status") or 422
            ),
        }
        _attach_route_metadata(
            failure,
            route="download",
            request_id=request_id,
            request_payload=payload,
        )
        return failure

    include_documents = _resolve_include_documents(payload)
    package_response = _route_service().build_package_plan_response(
        dict(payload),
        include_documents=include_documents,
    )
    package_payload = _route_response_to_payload(package_response)
    if not _route_payload_succeeded(package_payload):
        failure = {
            "ok": False,
            "status": "download_preflight_package_plan_failed",
            "route": "download",
            "component": CREATE_BLUEPRINT_COMPONENT,
            "version": CREATE_BLUEPRINT_VERSION,
            "errors": package_payload.get("errors")
            or [
                {
                    "severity": "error",
                    "code": "download_preflight_package_plan_failed",
                    "field": "package-plan",
                    "message": "Package planning failed before archive generation.",
                }
            ],
            "warnings": package_payload.get("warnings") or [],
            "data": {
                "validation": _compact_service_payload(validation_payload),
                "package_plan": _compact_service_payload(package_payload),
                "include_documents": include_documents,
            },
            "_http_status": _safe_http_status(
                package_payload.get("_http_status") or 422
            ),
        }
        _attach_route_metadata(
            failure,
            route="download",
            request_id=request_id,
            request_payload=payload,
        )
        return failure

    return {
        "ok": True,
        "status": "preflight_ok",
        "route": "download-preflight",
        "component": CREATE_BLUEPRINT_COMPONENT,
        "version": CREATE_BLUEPRINT_VERSION,
        "data": {
            "validation": _compact_service_payload(validation_payload),
            "package_plan": _compact_service_payload(package_payload),
            "include_documents": include_documents,
        },
        "_http_status": 200,
    }


def _coerce_archive_bytes(value: Any) -> bytes:
    if value is None:
        raise CreateArchiveError(
            "Download service returned no archive content.",
            code="archive_content_missing",
            http_status=500,
        )

    if isinstance(value, bytes):
        content = value
    elif isinstance(value, bytearray):
        content = bytes(value)
    elif isinstance(value, memoryview):
        content = value.tobytes()
    elif hasattr(value, "read") and callable(value.read):
        try:
            content = value.read()
        except Exception as exc:
            raise CreateArchiveError(
                "Archive stream could not be read.",
                code="archive_stream_read_failed",
                http_status=500,
            ) from exc
        if isinstance(content, str):
            content = content.encode("utf-8")
        elif not isinstance(content, bytes):
            content = bytes(content or b"")
    else:
        raise CreateArchiveError(
            "Download service returned an unsupported archive content type.",
            code="archive_content_type_invalid",
            http_status=500,
            details={"type": type(value).__name__},
        )

    max_bytes = _configured_int(
        "VECTOPLAN_CREATE_MAX_ARCHIVE_BYTES",
        DEFAULT_MAX_ARCHIVE_BYTES,
        minimum=1024,
    )
    if not content:
        raise CreateArchiveError(
            "Generated VPLIB archive is empty.",
            code="archive_empty",
            http_status=500,
        )
    if len(content) > max_bytes:
        raise CreateArchiveError(
            "Generated VPLIB archive exceeds the configured size limit.",
            code="archive_too_large",
            http_status=500,
            details={
                "size_bytes": len(content),
                "max_archive_bytes": max_bytes,
            },
        )

    return content


def _safe_archive_member_name(name: Any) -> str:
    text = str(name or "").replace("\\", "/").replace("\x00", "")
    if not text:
        raise CreateArchiveError(
            "Generated archive contains an empty member name.",
            code="archive_member_name_invalid",
            http_status=500,
        )
    if text.startswith("/") or re.match(r"^[A-Za-z]:/", text):
        raise CreateArchiveError(
            "Generated archive contains an absolute member path.",
            code="archive_member_path_unsafe",
            http_status=500,
            details={"member": text},
        )

    parts = [part for part in text.split("/") if part not in {"", "."}]
    if any(part == ".." for part in parts):
        raise CreateArchiveError(
            "Generated archive contains a path traversal member.",
            code="archive_member_path_unsafe",
            http_status=500,
            details={"member": text},
        )

    return "/".join(parts)


def _validate_vplib_archive(content: bytes) -> dict[str, Any]:
    if not any(content.startswith(signature) for signature in ZIP_SIGNATURES):
        raise CreateArchiveError(
            "Generated VPLIB content does not have a ZIP signature.",
            code="archive_signature_invalid",
            http_status=500,
        )

    buffer = io.BytesIO(content)
    if not zipfile.is_zipfile(buffer):
        raise CreateArchiveError(
            "Generated VPLIB content is not a valid ZIP archive.",
            code="archive_zip_invalid",
            http_status=500,
        )

    max_entries = _configured_int(
        "VECTOPLAN_CREATE_MAX_ARCHIVE_ENTRIES",
        DEFAULT_MAX_ARCHIVE_ENTRIES,
        minimum=1,
    )
    max_uncompressed = _configured_int(
        "VECTOPLAN_CREATE_MAX_ARCHIVE_UNCOMPRESSED_BYTES",
        DEFAULT_MAX_ARCHIVE_UNCOMPRESSED_BYTES,
        minimum=1024,
    )

    try:
        max_ratio = float(
            current_app.config.get(
                "VECTOPLAN_CREATE_MAX_COMPRESSION_RATIO",
                os.getenv(
                    "VECTOPLAN_CREATE_MAX_COMPRESSION_RATIO",
                    DEFAULT_MAX_COMPRESSION_RATIO,
                ),
            )
        )
    except Exception:
        max_ratio = DEFAULT_MAX_COMPRESSION_RATIO

    try:
        with zipfile.ZipFile(io.BytesIO(content), "r") as archive:
            members = archive.infolist()
            if not members:
                raise CreateArchiveError(
                    "Generated VPLIB archive contains no files.",
                    code="archive_has_no_entries",
                    http_status=500,
                )
            if len(members) > max_entries:
                raise CreateArchiveError(
                    "Generated VPLIB archive contains too many entries.",
                    code="archive_entry_limit_exceeded",
                    http_status=500,
                    details={
                        "entry_count": len(members),
                        "max_entries": max_entries,
                    },
                )

            total_uncompressed = 0
            total_compressed = 0
            names: list[str] = []

            for member in members:
                safe_name = _safe_archive_member_name(member.filename)
                names.append(safe_name)
                if member.flag_bits & 0x1:
                    raise CreateArchiveError(
                        "Generated VPLIB archive contains encrypted entries.",
                        code="archive_encrypted_entry",
                        http_status=500,
                        details={"member": safe_name},
                    )

                total_uncompressed += int(member.file_size or 0)
                total_compressed += int(member.compress_size or 0)

                if total_uncompressed > max_uncompressed:
                    raise CreateArchiveError(
                        "Generated VPLIB archive exceeds the uncompressed size limit.",
                        code="archive_uncompressed_limit_exceeded",
                        http_status=500,
                        details={
                            "uncompressed_bytes": total_uncompressed,
                            "max_uncompressed_bytes": max_uncompressed,
                        },
                    )

                if member.file_size and member.compress_size == 0:
                    raise CreateArchiveError(
                        "Generated VPLIB archive contains an invalid compressed entry.",
                        code="archive_compression_invalid",
                        http_status=500,
                        details={"member": safe_name},
                    )

                if member.file_size and member.compress_size:
                    ratio = float(member.file_size) / float(member.compress_size)
                    if ratio > max_ratio:
                        raise CreateArchiveError(
                            "Generated VPLIB archive contains a suspicious compression ratio.",
                            code="archive_compression_ratio_exceeded",
                            http_status=500,
                            details={
                                "member": safe_name,
                                "ratio": ratio,
                                "max_ratio": max_ratio,
                            },
                        )

            corrupt_member = archive.testzip()
            if corrupt_member:
                raise CreateArchiveError(
                    "Generated VPLIB archive failed CRC validation.",
                    code="archive_crc_failed",
                    http_status=500,
                    details={"member": corrupt_member},
                )
    except CreateRouteError:
        raise
    except (OSError, zipfile.BadZipFile, zipfile.LargeZipFile) as exc:
        raise CreateArchiveError(
            "Generated VPLIB archive could not be inspected.",
            code="archive_inspection_failed",
            http_status=500,
            details={"exception_type": type(exc).__name__},
        ) from exc

    return {
        "ok": True,
        "sha256": hashlib.sha256(content).hexdigest(),
        "size_bytes": len(content),
        "entry_count": len(members),
        "uncompressed_bytes": total_uncompressed,
        "compressed_bytes": total_compressed,
        "members": names[:32],
    }


def _attach_route_metadata(
    payload: dict[str, Any],
    *,
    route: str,
    request_id: str,
    request_payload: Mapping[str, Any] | None = None,
    extra: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    payload.setdefault("route", route)
    payload.setdefault("component", CREATE_BLUEPRINT_COMPONENT)
    payload.setdefault("version", CREATE_BLUEPRINT_VERSION)
    payload["_request_id"] = request_id

    data = payload.get("data")
    if not isinstance(data, Mapping):
        data = {}
    data = dict(data)

    if request_payload:
        starter = _safe_mapping(request_payload.get("_starter_contract"))
        if starter:
            data.setdefault("starter_contract", starter)

    if extra:
        for key, value in extra.items():
            data[key] = _json_safe(value)

    payload["data"] = data
    return payload


def _create_route_error_payload(
    exc: CreateRouteError,
    *,
    route: str,
    request_id: str,
) -> dict[str, Any]:
    payload = _failure_payload(
        route=route,
        code=exc.code,
        message=str(exc),
        details=exc.details,
        http_status=exc.http_status,
    )
    payload["_request_id"] = request_id
    return payload


def _starter_readiness_payload(*, request_id: str) -> dict[str, Any]:
    route_service_available = _is_route_service_available()
    definition_service_available = _is_definition_service_available()
    profile_payload: dict[str, Any] = {}

    if definition_service_available:
        profile_payload = _safe_definition_call(
            lambda service: service.get_variant_profile(
                STARTER_VARIANT_PROFILE_ID,
                user_id=1,
                resolved=True,
                required=True,
            ),
            route="creator-readiness-profile",
        )

    profile_ok = _route_payload_succeeded(profile_payload)
    ready = route_service_available and definition_service_available and profile_ok
    payload = {
        "ok": ready,
        "ready": ready,
        "healthy": ready,
        "status": "ready" if ready else "degraded",
        "route": "creator-readiness",
        "component": CREATE_BLUEPRINT_COMPONENT,
        "version": CREATE_BLUEPRINT_VERSION,
        "_request_id": request_id,
        "data": {
            "route_service_available": route_service_available,
            "definition_service_available": definition_service_available,
            "starter": {
                "object_kind": STARTER_OBJECT_KIND,
                "family_profile_id": STARTER_FAMILY_PROFILE_ID,
                "variant_profile_id": STARTER_VARIANT_PROFILE_ID,
                "default_variant_id": STARTER_DEFAULT_VARIANT_ID,
                "dimensions_mm": {
                    "width": STARTER_DIMENSIONS_MM["dimensions.width_mm"],
                    "height": STARTER_DIMENSIONS_MM["dimensions.height_mm"],
                    "depth": STARTER_DIMENSIONS_MM["dimensions.depth_mm"],
                },
            },
            "profile": _compact_service_payload(profile_payload),
        },
        "errors": [],
        "warnings": [],
        "_http_status": 200 if ready else 503,
    }

    if not ready:
        payload["errors"] = [
            {
                "severity": "error",
                "code": "creator_not_ready",
                "field": "create",
                "message": "The minimal cell_block create flow is not ready.",
            }
        ]

    return payload


# ---------------------------------------------------------------------------
# Request helpers
# ---------------------------------------------------------------------------

def _request_payload() -> dict[str, Any]:
    """
    Collect query, JSON, form data and multipart metadata into one payload.

    Precedence:
        1. query args
        2. JSON body
        3. form body

    Form values override JSON values because browser forms are the primary
    frontend path.
    """
    _ensure_request_size()
    payload: dict[str, Any] = {}

    try:
        payload.update(_mapping_to_plain_dict(request.args))
    except Exception:
        pass

    raw_data = b""
    try:
        raw_data = request.get_data(cache=True) or b""
    except Exception:
        raw_data = b""

    max_request_bytes = _configured_int(
        "VECTOPLAN_CREATE_MAX_REQUEST_BYTES",
        DEFAULT_MAX_REQUEST_BYTES,
        minimum=1024,
    )
    if len(raw_data) > max_request_bytes:
        raise CreateRequestError(
            f"Create request exceeds the configured limit of {max_request_bytes} bytes.",
            code="request_too_large",
            http_status=413,
            details={
                "content_length": len(raw_data),
                "max_request_bytes": max_request_bytes,
            },
        )

    try:
        if request.is_json:
            json_body = request.get_json(silent=True)
            if json_body is None and raw_data.strip():
                raise CreateRequestError(
                    "Request body is not valid JSON.",
                    code="invalid_json_body",
                    http_status=400,
                )
            if isinstance(json_body, Mapping):
                payload.update(_mapping_to_plain_dict(json_body))
            elif json_body is not None:
                raise CreateRequestError(
                    "Create JSON body must be an object.",
                    code="invalid_json_body_type",
                    http_status=400,
                    details={"actual": type(json_body).__name__},
                )
    except CreateRouteError:
        raise
    except Exception as exc:
        raise CreateRequestError(
            "Request JSON body could not be parsed.",
            code="invalid_json_body",
            http_status=400,
        ) from exc

    try:
        if request.form:
            payload.update(_mapping_to_plain_dict(request.form))
    except Exception:
        pass

    if raw_data and not request.form and not request.is_json:
        raw_text = raw_data.decode("utf-8", errors="strict").strip()
        if raw_text:
            try:
                decoded = json.loads(raw_text)
            except Exception as exc:
                raise CreateRequestError(
                    "Request body must be valid JSON or form data.",
                    code="unsupported_request_body",
                    http_status=400,
                ) from exc
            if not isinstance(decoded, Mapping):
                raise CreateRequestError(
                    "Create request body must decode to an object.",
                    code="invalid_request_body_type",
                    http_status=400,
                    details={"actual": type(decoded).__name__},
                )
            payload.update(_mapping_to_plain_dict(decoded))

    try:
        if request.files:
            payload.update(_request_upload_metadata())
    except Exception:
        pass

    payload["_request_id"] = _request_id()
    return _normalize_embedded_json_fields(payload)


def _request_upload_metadata() -> dict[str, Any]:
    result: dict[str, Any] = {
        "uploaded_file_count": 0,
        "uploaded_file_fields": [],
        "uploads": {},
    }

    try:
        files = request.files
    except Exception:
        return result

    try:
        result["uploaded_file_count"] = len(files)
        result["uploaded_file_fields"] = list(files.keys())
    except Exception:
        pass

    uploads: dict[str, Any] = {}

    try:
        for field_name in files.keys():
            values = files.getlist(field_name) if callable(getattr(files, "getlist", None)) else [files.get(field_name)]
            normalized_values = []

            for item in values:
                if item is None:
                    continue

                normalized_values.append(
                    {
                        "field": str(field_name),
                        "filename": _safe_upload_filename(getattr(item, "filename", "")),
                        "mimetype": str(getattr(item, "mimetype", "") or getattr(item, "content_type", "") or ""),
                        "content_type": str(getattr(item, "content_type", "") or getattr(item, "mimetype", "") or ""),
                    }
                )

            if normalized_values:
                uploads[str(field_name)] = normalized_values[0] if len(normalized_values) == 1 else normalized_values
    except Exception:
        pass

    result["uploads"] = uploads
    return result


def _mapping_to_plain_dict(mapping: Mapping[str, Any]) -> dict[str, Any]:
    result: dict[str, Any] = {}

    for key, value in mapping.items():
        key_text = str(key)

        if isinstance(value, (list, tuple)):
            if len(value) == 1:
                result[key_text] = value[0]
            else:
                result[key_text] = list(value)
        else:
            getlist = getattr(mapping, "getlist", None)
            if callable(getlist):
                try:
                    values = getlist(key)
                    if len(values) == 1:
                        result[key_text] = values[0]
                    elif len(values) > 1:
                        result[key_text] = values
                    else:
                        result[key_text] = value
                    continue
                except Exception:
                    pass

            result[key_text] = value

    return result


def _request_bool(name: str, *, default: bool = False) -> bool:
    value = request.args.get(name, None)
    if value is None and request.form:
        value = request.form.get(name, None)
    return _safe_bool(value, default=default)


def _request_optional_bool(name: str) -> bool | None:
    value = request.args.get(name, None)
    if value is None and request.form:
        value = request.form.get(name, None)
    if value is None:
        return None
    return _safe_bool(value, default=False)


def _request_int(name: str, *, default: int | None = None) -> int | None:
    value = request.args.get(name, None)
    if value is None and request.form:
        value = request.form.get(name, None)
    if value is None:
        return default

    try:
        return int(value)
    except Exception:
        return default


# ---------------------------------------------------------------------------
# Response helpers
# ---------------------------------------------------------------------------

def _json_route_response(
    route_response: Any,
    *,
    request_id: str | None = None,
) -> Response:
    payload = _route_response_to_payload(route_response)
    status_code = _safe_http_status(
        payload.get("_http_status", _status_code_from_payload(payload))
    )
    return _json_response(payload, status_code, request_id=request_id)


def _json_response(
    payload: Mapping[str, Any],
    status_code: int = 200,
    *,
    request_id: str | None = None,
) -> Response:
    response_payload = _json_safe(dict(payload))
    if not isinstance(response_payload, dict):
        response_payload = {"result": response_payload}

    resolved_request_id = (
        str(request_id or response_payload.get("_request_id") or "").strip()
        or _request_id()
    )
    response_payload["_request_id"] = resolved_request_id

    response = jsonify(response_payload)
    response.status_code = _safe_http_status(status_code)
    response.headers[
        "Cache-Control"
    ] = "no-store, no-cache, must-revalidate, max-age=0"
    response.headers["Pragma"] = "no-cache"
    response.headers["Expires"] = "0"
    response.headers["X-Content-Type-Options"] = "nosniff"
    response.headers["X-VECTOPLAN-Create-Blueprint"] = CREATE_BLUEPRINT_VERSION
    response.headers["X-VECTOPLAN-Request-ID"] = resolved_request_id
    return response


def _route_response_to_payload(route_response: Any) -> dict[str, Any]:
    if route_response is None:
        return _failure_payload(
            route="unknown",
            code="empty_route_response",
            message="Route-Service hat keine Antwort geliefert.",
            http_status=500,
        )

    if hasattr(route_response, "to_dict") and callable(route_response.to_dict):
        try:
            payload = route_response.to_dict(include_http_status=True)
        except TypeError:
            payload = route_response.to_dict()

        if isinstance(payload, Mapping):
            return dict(payload)

    if isinstance(route_response, Mapping):
        return dict(route_response)

    return _failure_payload(
        route="unknown",
        code="invalid_route_response",
        message="Route-Service hat einen unerwarteten Antworttyp geliefert.",
        details={"type": type(route_response).__name__, "repr": repr(route_response)},
        http_status=500,
    )


def _binary_response_to_payload(binary_response: Any) -> dict[str, Any]:
    if binary_response is None:
        return _failure_payload(
            route="download",
            code="empty_binary_response",
            message="Route-Service hat keine Download-Antwort geliefert.",
            http_status=500,
        )

    if hasattr(binary_response, "to_dict") and callable(binary_response.to_dict):
        try:
            payload = binary_response.to_dict(include_http_status=True)
        except TypeError:
            payload = binary_response.to_dict()

        if isinstance(payload, Mapping):
            return dict(payload)

    if isinstance(binary_response, Mapping):
        return dict(binary_response)

    return _failure_payload(
        route="download",
        code="invalid_binary_response",
        message="Route-Service hat einen unerwarteten Download-Antworttyp geliefert.",
        details={"type": type(binary_response).__name__, "repr": repr(binary_response)},
        http_status=500,
    )


def _status_code_from_payload(payload: Mapping[str, Any]) -> int:
    if not isinstance(payload, Mapping):
        return 500

    explicit = payload.get("_http_status")
    if explicit is not None:
        return _safe_http_status(explicit)

    if bool(payload.get("ok", False)):
        return 200

    status = str(payload.get("status") or "").strip().lower()
    error = payload.get("error")

    codes: list[str] = []
    if isinstance(error, Mapping):
        codes.append(str(error.get("code") or "").strip().lower())

    errors = payload.get("errors")
    if isinstance(errors, list):
        for issue in errors:
            if isinstance(issue, Mapping):
                code = str(issue.get("code") or "").strip().lower()
                if code:
                    codes.append(code)

    if status in {"invalid_request", "bad_request"}:
        return 400

    if status in {
        "taxonomy_required_fields_missing",
        "invalid",
        "draft_invalid",
        "starter_payload_invalid",
        "download_preflight_validation_failed",
        "download_preflight_package_plan_failed",
    }:
        return 422

    if status == "not_found" or any(code.endswith("not_found") for code in codes):
        return 404

    if status in {
        "unavailable",
        "route_service_unavailable",
        "service_unavailable",
        "degraded",
    }:
        return 503

    if status in {"not_implemented"}:
        return 501

    if status in {"request_too_large"} or "request_too_large" in codes:
        return 413

    if status in {"failed", "error"}:
        return 500

    if any(code.startswith("invalid_") for code in codes):
        return 400

    if any(
        code in {
            "starter_payload_invalid",
            "download_preflight_validation_failed",
            "download_preflight_package_plan_failed",
        }
        for code in codes
    ):
        return 422

    return 500


def _safe_definition_call(callback: Callable[[Any], Mapping[str, Any] | Any], *, route: str) -> dict[str, Any]:
    try:
        service = _create_definition_catalog_service()
    except Exception as exc:
        return _service_unavailable_payload(
            route=route,
            dependency="src.library.services.library_definition_catalog_service",
            code="definition_catalog_service_unavailable",
            message="Definition-Catalog-Service konnte nicht geladen werden.",
            exc=exc,
        )

    try:
        result = callback(service)
        payload = _to_payload_dict(result)
        payload.setdefault("ok", True)
        payload.setdefault("status", "ok")
        payload.setdefault("route", route)
        payload.setdefault("component", CREATE_BLUEPRINT_COMPONENT)
        payload.setdefault("version", CREATE_BLUEPRINT_VERSION)
        payload.setdefault("_http_status", 200)
        return payload
    except Exception as exc:
        return _failure_payload(
            route=route,
            code=f"{route}_failed",
            message="Definition-backed Create-Anfrage konnte nicht verarbeitet werden.",
            exc=exc,
            http_status=500,
        )


def _safe_draft_call(callback: Callable[[Any], Mapping[str, Any] | Any], *, route: str) -> dict[str, Any]:
    try:
        service = _create_draft_service()
    except Exception as exc:
        return _service_unavailable_payload(
            route=route,
            dependency="src.library.services.creative_library_draft_service",
            code="creative_library_draft_service_unavailable",
            message="Creative-Library-Draft-Service konnte nicht geladen werden.",
            exc=exc,
        )

    try:
        result = callback(service)
        payload = _to_payload_dict(result)
        payload.setdefault("ok", True)
        payload.setdefault("status", "ok")
        payload.setdefault("route", route)
        payload.setdefault("component", CREATE_BLUEPRINT_COMPONENT)
        payload.setdefault("version", CREATE_BLUEPRINT_VERSION)
        payload.setdefault("_http_status", _status_code_from_payload(payload))
        return payload
    except Exception as exc:
        return _failure_payload(
            route=route,
            code=f"{route}_failed",
            message="Persistent Create-Draft-Anfrage konnte nicht verarbeitet werden.",
            exc=exc,
            http_status=500,
        )


def _call_flexible(function: Callable[..., Any], *args: Any, **kwargs: Any) -> Any:
    if not kwargs:
        return function(*args)

    try:
        signature = getattr(function, "__signature__", None)
        if signature is None:
            import inspect
            signature = inspect.signature(function)

        supports_kwargs = any(
            parameter.kind == parameter.VAR_KEYWORD
            for parameter in signature.parameters.values()
        )

        if supports_kwargs:
            return function(*args, **kwargs)

        supported = set(signature.parameters.keys())
        filtered = {key: value for key, value in kwargs.items() if key in supported}
        return function(*args, **filtered)
    except TypeError:
        try:
            return function(*args)
        except TypeError:
            return function()
    except Exception:
        raise


def _to_payload_dict(value: Any) -> dict[str, Any]:
    if value is None:
        return {}

    if isinstance(value, Mapping):
        return dict(value)

    if hasattr(value, "to_dict") and callable(value.to_dict):
        for kwargs in (
            {"include_http_status": True},
            {"include_payloads": True},
            {},
        ):
            try:
                payload = value.to_dict(**kwargs)
                if isinstance(payload, Mapping):
                    return dict(payload)
            except TypeError:
                continue
            except Exception:
                break

    if isinstance(value, (list, tuple)):
        return {"items": _json_safe(list(value))}

    return {"result": _json_safe(value)}


# ---------------------------------------------------------------------------
# Safe payload helpers
# ---------------------------------------------------------------------------

def _safe_route_health_payload() -> dict[str, Any]:
    if not _is_route_service_available():
        return _route_service_unavailable_payload(route="health")

    try:
        response = _route_service().get_route_service_health()
        return _route_response_to_payload(response)
    except Exception as exc:
        return _failure_payload(
            route="health",
            code="health_failed",
            message="Create-Health konnte für das Template nicht geladen werden.",
            exc=exc,
            http_status=500,
        )


def _safe_options_payload() -> dict[str, Any]:
    if not _is_route_service_available():
        return _route_service_unavailable_payload(route="options")

    try:
        response = _route_service().get_options_response()
        return _route_response_to_payload(response)
    except Exception as exc:
        return _failure_payload(
            route="options",
            code="options_failed",
            message="Create-Optionen konnten für das Template nicht geladen werden.",
            exc=exc,
            http_status=500,
        )


def _safe_context_payload() -> dict[str, Any]:
    if not _is_route_service_available():
        return _route_service_unavailable_payload(route="create-context")

    try:
        response = _route_service().get_create_context_response(
            {
                "user_id": 1,
                "include_catalog": False,
            }
        )
        return _route_response_to_payload(response)
    except Exception as exc:
        return _failure_payload(
            route="create-context",
            code="context_failed",
            message="Create Context konnte für das Template nicht geladen werden.",
            exc=exc,
            http_status=500,
        )


def _safe_definitions_current_payload(*, user_id: int | None = 1) -> dict[str, Any]:
    if _is_route_service_available():
        try:
            response = _route_service().get_current_definitions_response(user_id=user_id)
            return _route_response_to_payload(response)
        except Exception:
            pass

    return _safe_definition_call(
        lambda service: service.get_create_options(user_id=user_id),
        route="definition-options",
    )


def _safe_route_service_health() -> dict[str, Any]:
    if not _is_route_service_available():
        return _route_service_unavailable_payload(route="route-service-health")

    try:
        response = _route_service().get_route_service_health()
        return _route_response_to_payload(response)
    except Exception as exc:
        return _failure_payload(
            route="route-service-health",
            code="route_service_health_failed",
            message="Create-Route-Service-Health konnte nicht geladen werden.",
            exc=exc,
            http_status=500,
        )


def _safe_definition_service_health() -> dict[str, Any]:
    try:
        service = _create_definition_catalog_service()
        if hasattr(service, "get_health") and callable(service.get_health):
            payload = service.get_health()
            return _to_payload_dict(payload)

        return {"ok": True, "status": "ok"}
    except Exception as exc:
        return _service_unavailable_payload(
            route="definition-health",
            dependency="src.library.services.library_definition_catalog_service",
            code="definition_catalog_service_unavailable",
            message="Definition-Catalog-Service konnte nicht geladen werden.",
            exc=exc,
        )


def _safe_draft_service_health() -> dict[str, Any]:
    try:
        service = _create_draft_service()
        if hasattr(service, "get_health") and callable(service.get_health):
            payload = service.get_health()
            return _to_payload_dict(payload)

        return {"ok": True, "status": "ok"}
    except Exception as exc:
        return _service_unavailable_payload(
            route="draft-health",
            dependency="src.library.services.creative_library_draft_service",
            code="creative_library_draft_service_unavailable",
            message="Creative-Library-Draft-Service konnte nicht geladen werden.",
            exc=exc,
        )


def _safe_generator_diagnostics_payload(request_payload: Mapping[str, Any] | None = None) -> dict[str, Any]:
    try:
        module = _load_generator_diagnostics_service_module()

        for function_name in (
            "get_generator_diagnostics_payload",
            "run_generator_diagnostics",
        ):
            function = getattr(module, function_name, None)
            if not callable(function):
                continue

            result = function(dict(request_payload or {}))
            return _to_payload_dict(result)

        service_factory = getattr(module, "get_library_generator_diagnostics_service", None)
        if callable(service_factory):
            service = service_factory()
            if hasattr(service, "get_payload") and callable(service.get_payload):
                return _to_payload_dict(service.get_payload(dict(request_payload or {})))

        return {
            "ok": True,
            "status": "available",
            "component": "library_generator_diagnostics_service",
        }
    except Exception as exc:
        return _service_unavailable_payload(
            route="generator-diagnostics",
            dependency="src.library.services.library_generator_diagnostics_service",
            code="generator_diagnostics_service_unavailable",
            message="Generator-Diagnostics-Service konnte nicht geladen werden.",
            exc=exc,
        )


# ---------------------------------------------------------------------------
# Template context helpers
# ---------------------------------------------------------------------------

def _build_create_template_context(
    *,
    route_health: Mapping[str, Any],
    options_payload: Mapping[str, Any],
    context_payload: Mapping[str, Any],
    definitions_payload: Mapping[str, Any],
) -> dict[str, Any]:
    """
    Build the render context for ``templates/vplib/create.html``.

    The context is intentionally pre-sanitized before Jinja receives it. This
    prevents ``Undefined`` or service objects from reaching ``|tojson`` in
    ``_context_json.html`` while still keeping the generator-backed payloads
    available to the browser runtime.
    """

    safe_route_health = _json_safe(dict(route_health or {}))
    safe_options_payload = _json_safe(dict(options_payload or {}))
    safe_context_payload = _json_safe(dict(context_payload or {}))
    safe_definitions_payload = _json_safe(dict(definitions_payload or {}))

    options_data = _payload_data(safe_options_payload)
    context_data = _payload_data(safe_context_payload)
    definitions_data = _payload_data(safe_definitions_payload)

    generator_context = _first_mapping(
        context_data.get("generator_context"),
        context_data.get("generatorContext"),
        context_data.get("window_payload"),
        _nested_mapping(context_data, "data.generator_context"),
        _nested_mapping(context_data, "data.generatorContext"),
        _nested_mapping(options_data, "generator_context"),
        _nested_mapping(options_data, "generatorContext"),
        _nested_mapping(definitions_data, "generator_context"),
        _nested_mapping(safe_context_payload, "data.generator_context"),
    )

    generator_data = _first_mapping(
        generator_context.get("data"),
        generator_context.get("payload"),
        generator_context.get("generator_data"),
        generator_context.get("generatorData"),
        generator_context,
    )

    definition_context = _first_mapping(
        context_data.get("definition_context"),
        context_data.get("definitionContext"),
        context_data.get("definitions"),
        _nested_mapping(context_data, "generator_context.data.definition_context"),
        _nested_mapping(context_data, "generator_context.data.definitions"),
        _nested_mapping(generator_data, "definition_context"),
        _nested_mapping(generator_data, "definitions"),
        definitions_data.get("definition_context"),
        definitions_data.get("definitions"),
        definitions_data,
    )

    definition_records = _first_mapping(
        definition_context.get("records"),
        definition_context.get("definitions"),
        definition_context.get("catalogs"),
        definition_context.get("definition_catalogs"),
        definition_context.get("definitionCatalogs"),
        definitions_data.get("records"),
        definitions_data.get("catalogs"),
        definitions_data.get("definition_catalogs"),
        options_data.get("definition_catalogs"),
        options_data.get("definitions"),
    )

    definitions_options = _first_mapping(
        options_data.get("definitions_options"),
        options_data.get("definitionsOptions"),
        definition_context.get("options"),
        definitions_data.get("options"),
        _nested_mapping(definitions_data, "definitions.options"),
    )

    taxonomy_context = _first_mapping(
        context_data.get("taxonomy_context"),
        context_data.get("taxonomyContext"),
        context_data.get("taxonomy"),
        options_data.get("taxonomy"),
        generator_data.get("taxonomy_context"),
        generator_data.get("taxonomy"),
        definitions_data.get("taxonomy"),
    )

    upload_config = _first_mapping(
        context_data.get("upload_config"),
        context_data.get("uploadConfig"),
        context_data.get("uploads"),
        options_data.get("uploads"),
        generator_data.get("upload_config"),
        generator_data.get("uploadConfig"),
        generator_data.get("uploads"),
    )

    payload_contract = _first_mapping(
        context_data.get("payload_contract"),
        context_data.get("payloadContract"),
        options_data.get("payload_contract"),
        options_data.get("payloadContract"),
        generator_data.get("payload_contract"),
        generator_data.get("payloadContract"),
    )

    domains = _first_list(options_data.get("domains"), taxonomy_context.get("domains"))
    categories = _first_list(options_data.get("categories"), taxonomy_context.get("categories"))
    subcategories = _first_list(options_data.get("subcategories"), taxonomy_context.get("subcategories"))

    object_kinds = _first_list(
        options_data.get("object_kinds"),
        options_data.get("objectKinds"),
        definitions_options.get("object_kinds"),
        definitions_options.get("objectKinds"),
        definition_records.get("object_kinds"),
        definition_records.get("objectKinds"),
        definition_context.get("object_kinds"),
        definition_context.get("objectKinds"),
    )
    family_profiles = _first_list(
        options_data.get("family_profiles"),
        options_data.get("familyProfiles"),
        definitions_options.get("family_profiles"),
        definitions_options.get("familyProfiles"),
        definition_records.get("family_profiles"),
        definition_records.get("familyProfiles"),
        definition_context.get("family_profiles"),
        definition_context.get("familyProfiles"),
    )
    variant_profiles = _first_list(
        options_data.get("variant_profiles"),
        options_data.get("variantProfiles"),
        definitions_options.get("variant_profiles"),
        definitions_options.get("variantProfiles"),
        definition_records.get("variant_profiles"),
        definition_records.get("variantProfiles"),
        definition_context.get("variant_profiles"),
        definition_context.get("variantProfiles"),
    )
    variables = _first_list(
        options_data.get("variables"),
        definitions_options.get("variables"),
        definition_records.get("variables"),
        definition_context.get("variables"),
    )
    primitive_shapes = _first_list(
        options_data.get("primitive_shapes"),
        options_data.get("primitiveShapes"),
        definitions_options.get("primitive_shapes"),
        definitions_options.get("primitiveShapes"),
    )
    units = _first_list(
        options_data.get("units"),
        definitions_options.get("units"),
        definition_records.get("units"),
        definition_context.get("units"),
    )
    materials = _first_list(
        options_data.get("material_classes"),
        options_data.get("materialClasses"),
        options_data.get("materials"),
        definitions_options.get("materials"),
        definitions_options.get("material_classes"),
        definition_records.get("materials"),
        definition_records.get("material_classes"),
        definition_context.get("materials"),
        definition_context.get("material_classes"),
    )
    document_types = _first_list(
        options_data.get("document_types"),
        options_data.get("documentTypes"),
        definitions_options.get("document_types"),
        definitions_options.get("documentTypes"),
        definition_records.get("document_types"),
        definition_records.get("documentTypes"),
        definition_context.get("document_types"),
        definition_context.get("documentTypes"),
    )
    profile_bindings = _first_list(
        options_data.get("profile_bindings"),
        options_data.get("profileBindings"),
        definitions_options.get("profile_bindings"),
        definitions_options.get("profileBindings"),
        definition_records.get("profile_bindings"),
        definition_records.get("profileBindings"),
        definition_context.get("profile_bindings"),
        definition_context.get("profileBindings"),
    )

    route_data = _payload_data(safe_route_health)
    create_service_health = _first_mapping(
        route_data.get("create_service_health"),
        _nested_mapping(route_data, "data.create_service_health"),
        _nested_mapping(safe_route_health, "data.create_service_health"),
    )

    source_root = (
        options_data.get("source_root")
        or options_data.get("sourceRoot")
        or generator_data.get("source_root")
        or generator_data.get("sourceRoot")
        or ""
    )
    create_service_version = (
        create_service_health.get("version")
        or options_data.get("version")
        or route_data.get("version")
        or "unknown"
    )

    context = {
        # Jinja render guards. Several existing templates use JSON-style ``null``.
        # Defining it here prevents a Jinja Undefined object from reaching tojson.
        "null": None,
        "undefined": None,

        "create_blueprint": {
            "component": CREATE_BLUEPRINT_COMPONENT,
            "version": CREATE_BLUEPRINT_VERSION,
            "api_prefix": CREATE_API_PREFIX,
            "page_route": CREATE_PAGE_ROUTE,
        },
        "create_api_prefix": CREATE_API_PREFIX,
        "definitions_api_prefix": "/api/v1/vplib/definitions",
        "taxonomy_api_prefix": "/api/v1/vplib/taxonomy",
        "files_api_prefix": "/api/v1/vplib/files",
        "create_page_route": CREATE_PAGE_ROUTE,

        "create_options": options_data,
        "create_context": context_data,
        "create_definition_options": definitions_data,
        "create_health": safe_route_health,
        "create_routes": get_create_route_map_response(),

        "generator_context": generator_context,
        "definitions": definition_context,
        "definitions_options": definitions_options,
        "definition_catalogs": definition_records,

        "_api_prefix": CREATE_API_PREFIX,
        "_definitions_api_prefix": "/api/v1/vplib/definitions",
        "_taxonomy_api_prefix": "/api/v1/vplib/taxonomy",
        "_files_api_prefix": "/api/v1/vplib/files",
        "_options": options_data,
        "_health": safe_route_health,
        "_write_enabled": _safe_bool(options_data.get("write_enabled") or generator_data.get("write_enabled"), default=False),
        "_health_ok": _safe_bool(safe_route_health.get("ok") or safe_route_health.get("healthy"), default=False),
        "_source_root": source_root,
        "_blueprint_version": CREATE_BLUEPRINT_VERSION,
        "_create_service_version": create_service_version,

        "_domains": domains,
        "_categories": categories,
        "_subcategories": subcategories,
        "_object_kinds": object_kinds,
        "_primitive_shapes": primitive_shapes,
        "_units": units,
        "_material_classes": materials,

        "create_steps": _first_list(
            options_data.get("create_steps"),
            options_data.get("steps"),
            context_data.get("steps"),
            generator_data.get("steps"),
        ),
        "create_initial_step": 1,
        "create_default_theme": "dark",
        "create_theme_storage_key": "vectoplan.create.wizard.theme",
        "create_legacy_theme_storage_key": "vectoplan.create.theme",

        # Explicit payload blocks consumed by _context_json.html.
        "_context_generator_raw": generator_context,
        "_context_generator_data": generator_data,
        "_context_definition_block": definition_context,
        "_context_definition_records": definition_records,
        "_context_definitions_options": definitions_options,
        "_context_taxonomy": taxonomy_context,
        "_context_upload_config_raw": upload_config,
        "_context_payload_contract": payload_contract,

        "active_screen": "create",
        "_active_screen": "create",
    }

    return _json_safe(context)


def _payload_data(payload: Any) -> dict[str, Any]:
    safe_payload = _json_safe(payload)

    if isinstance(safe_payload, Mapping):
        data = safe_payload.get("data")
        if isinstance(data, Mapping):
            return _json_safe(dict(data))
        return _json_safe(dict(safe_payload))

    return {}


def _nested_value(payload: Any, path: str, default: Any = None) -> Any:
    current = payload

    for part in str(path or "").split("."):
        if not isinstance(current, Mapping):
            return default

        current = current.get(part)
        if current is None:
            return default

    return current


def _nested_mapping(payload: Any, path: str) -> dict[str, Any]:
    value = _nested_value(payload, path, default={})
    return _safe_mapping(value)


def _first_mapping(*values: Any) -> dict[str, Any]:
    for value in values:
        mapped = _safe_mapping(value)
        if mapped:
            return mapped
    return {}


def _as_list(value: Any) -> list[Any]:
    safe_value = _json_safe(value)

    if safe_value is None:
        return []

    if isinstance(safe_value, list):
        return safe_value

    if isinstance(safe_value, tuple):
        return list(safe_value)

    if isinstance(safe_value, set):
        return list(safe_value)

    if isinstance(safe_value, Mapping):
        return list(safe_value.values())

    if isinstance(safe_value, str) and not safe_value.strip():
        return []

    return [safe_value]


def _first_list(*values: Any) -> list[Any]:
    for value in values:
        items = _as_list(value)
        if items:
            return _json_safe(items)
    return []


def _is_jinja_undefined(value: Any) -> bool:
    try:
        value_type = type(value)
        module_name = str(getattr(value_type, "__module__", ""))
        class_name = str(getattr(value_type, "__name__", ""))
        return module_name.startswith("jinja2.") and "Undefined" in class_name
    except Exception:
        return False


def _is_route_service_available() -> bool:
    try:
        _route_service()
        return True
    except Exception:
        return False


def _is_definition_service_available() -> bool:
    try:
        _create_definition_catalog_service()
        return True
    except Exception:
        return False


def _is_draft_service_available() -> bool:
    try:
        _create_draft_service()
        return True
    except Exception:
        return False


def _is_generator_context_service_available() -> bool:
    try:
        _load_generator_context_service_module()
        return True
    except Exception:
        return False


def _is_generator_diagnostics_service_available() -> bool:
    try:
        _load_generator_diagnostics_service_module()
        return True
    except Exception:
        return False


# ---------------------------------------------------------------------------
# Draft persistence helpers
# ---------------------------------------------------------------------------

def _should_persist_draft(payload: Mapping[str, Any]) -> bool:
    return (
        _safe_bool(payload.get("persist"), default=False)
        or _safe_bool(payload.get("save_draft"), default=False)
        or _safe_bool(payload.get("db"), default=False)
        or _safe_bool(payload.get("persistent"), default=False)
    )


def _build_direct_draft_service_payload(payload: Mapping[str, Any]) -> dict[str, Any]:
    data = dict(payload)
    return {
        "user_id": data.get("user_id", 1),
        "mode": data.get("mode") or data.get("draft_mode") or "create",
        "source_scope": data.get("source_scope") or "user",
        "target_item_id": data.get("target_item_id"),
        "target_vplib_uid": data.get("target_vplib_uid") or data.get("vplib_uid"),
        "base_revision_id": data.get("base_revision_id"),
        "family_id": data.get("family_id"),
        "package_id": data.get("package_id"),
        "vplib_uid": data.get("vplib_uid") or data.get("target_vplib_uid"),
        "title": (
            data.get("title")
            or data.get("label")
            or data.get("name")
            or data.get("family_name")
            or data.get("family_id")
            or "VPLIB Draft"
        ),
        "label": data.get("label") or data.get("title") or data.get("family_name"),
        "name": data.get("name") or data.get("label") or data.get("title") or data.get("family_name"),
        "description": data.get("description"),
        "family_payload": _json_object_from_any(data.get("family_payload") or data.get("family")),
        "classification_payload": _json_object_from_any(data.get("classification_payload") or data.get("classification")),
        "manifest_payload": _json_object_from_any(data.get("manifest_payload") or data.get("manifest")),
        "modules_payload": _json_object_from_any(data.get("modules_payload") or data.get("modules")),
        "generator_payload": _json_object_from_any(data.get("generator_payload") or data.get("generator") or data),
        "validation_payload": _json_object_from_any(data.get("validation_payload") or data.get("validation")),
        "variants": _json_list_from_any(data.get("variants")),
        "assets": _json_list_from_any(data.get("assets")),
        "documents": _json_list_from_any(data.get("documents")),
        "validation_issues": _json_list_from_any(data.get("validation_issues") or data.get("issues")),
        "payload": {
            "request": _json_safe(dict(data)),
            "source": "routes.create",
        },
        "metadata": _metadata_from_payload(data),
    }


def _json_object_from_any(value: Any) -> dict[str, Any]:
    if value is None:
        return {}

    if isinstance(value, Mapping):
        return _json_safe(dict(value))

    if isinstance(value, str):
        text = value.strip()
        if text.startswith("{") and text.endswith("}"):
            try:
                decoded = json.loads(text)
                if isinstance(decoded, Mapping):
                    return _json_safe(dict(decoded))
            except Exception:
                pass
        return {"value": value}

    return {"value": _json_safe(value)}


def _json_list_from_any(value: Any) -> list[Any]:
    if value is None:
        return []

    if isinstance(value, list):
        return [_json_safe(item) for item in value]

    if isinstance(value, tuple):
        return [_json_safe(item) for item in value]

    if isinstance(value, str):
        text = value.strip()
        if text.startswith("[") and text.endswith("]"):
            try:
                decoded = json.loads(text)
                if isinstance(decoded, list):
                    return [_json_safe(item) for item in decoded]
            except Exception:
                pass
        if not text:
            return []
        return [text]

    return [_json_safe(value)]


def _metadata_from_payload(payload: Mapping[str, Any]) -> dict[str, Any]:
    metadata = payload.get("metadata")
    if isinstance(metadata, Mapping):
        return _json_safe(dict(metadata))

    result: dict[str, Any] = {}

    for key, value in payload.items():
        key_text = str(key)
        if key_text.startswith("metadata."):
            result[key_text.split(".", 1)[1]] = _json_safe(value)

    return result


# ---------------------------------------------------------------------------
# Page fallback
# ---------------------------------------------------------------------------

def _render_fallback_page(
    *,
    template_error: BaseException,
    health_payload: Mapping[str, Any],
    options_payload: Mapping[str, Any],
    context_payload: Mapping[str, Any] | None = None,
    definitions_payload: Mapping[str, Any] | None = None,
) -> Response:
    """Render a minimal fallback page until create.html is available."""
    health_json = json.dumps(_json_safe(dict(health_payload)), ensure_ascii=False, indent=2)
    options_json = json.dumps(_json_safe(dict(options_payload)), ensure_ascii=False, indent=2)
    context_json = json.dumps(_json_safe(dict(context_payload or {})), ensure_ascii=False, indent=2)
    definitions_json = json.dumps(_json_safe(dict(definitions_payload or {})), ensure_ascii=False, indent=2)
    template_error_text = _html_escape(str(template_error) or type(template_error).__name__)

    html = f"""<!doctype html>
<html lang="de">
<head>
  <meta charset="utf-8">
  <title>{FALLBACK_TEMPLATE_TITLE}</title>
  <style>
    body {{
      margin: 0;
      font-family: system-ui, -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif;
      background: #0f172a;
      color: #e5e7eb;
    }}
    main {{
      max-width: 1100px;
      margin: 0 auto;
      padding: 32px;
    }}
    .card {{
      background: rgba(15, 23, 42, 0.9);
      border: 1px solid rgba(148, 163, 184, 0.35);
      border-radius: 16px;
      padding: 20px;
      margin: 16px 0;
    }}
    h1, h2 {{
      margin-top: 0;
    }}
    code, pre {{
      font-family: ui-monospace, SFMono-Regular, Menlo, Consolas, monospace;
    }}
    pre {{
      overflow: auto;
      background: rgba(2, 6, 23, 0.8);
      border-radius: 12px;
      padding: 16px;
      max-height: 420px;
    }}
    a {{
      color: #93c5fd;
    }}
  </style>
</head>
<body>
  <main>
    <section class="card">
      <p>VECTOPLAN Library</p>
      <h1>VPLIB erstellen</h1>
      <p>
        Die Route <code>/create</code> funktioniert. Das finale Template
        <code>{_html_escape(CREATE_TEMPLATE)}</code> ist noch nicht verfügbar oder konnte nicht gerendert werden.
      </p>
      <p><strong>Template-Fehler:</strong> {template_error_text}</p>
      <p>Health: <a href="{CREATE_API_PREFIX}/health">{CREATE_API_PREFIX}/health</a></p>
      <p>Options: <a href="{CREATE_API_PREFIX}/options">{CREATE_API_PREFIX}/options</a></p>
      <p>Context: <a href="{CREATE_API_PREFIX}/context">{CREATE_API_PREFIX}/context</a></p>
      <p>Selftest: <a href="{CREATE_API_PREFIX}/selftest">{CREATE_API_PREFIX}/selftest</a></p>
    </section>

    <section class="card">
      <h2>Health</h2>
      <pre>{_html_escape(health_json)}</pre>
    </section>

    <section class="card">
      <h2>Options</h2>
      <pre>{_html_escape(options_json)}</pre>
    </section>

    <section class="card">
      <h2>Context</h2>
      <pre>{_html_escape(context_json)}</pre>
    </section>

    <section class="card">
      <h2>Definitions</h2>
      <pre>{_html_escape(definitions_json)}</pre>
    </section>
  </main>
</body>
</html>
"""

    response = make_response(html, 200)
    response.headers["Content-Type"] = "text/html; charset=utf-8"
    response.headers["Cache-Control"] = "no-store"
    response.headers["X-VECTOPLAN-Create-Fallback"] = "true"
    return response


# ---------------------------------------------------------------------------
# Failure / utility helpers
# ---------------------------------------------------------------------------

def _include_debug_details() -> bool:
    """Whether exception tracebacks may be exposed in API payloads."""
    env_value = os.getenv("VECTOPLAN_INCLUDE_ERROR_TRACEBACKS")
    if env_value is not None:
        return _safe_bool(env_value, default=False)

    try:
        return bool(current_app.debug or current_app.testing)
    except Exception:
        return False


def _route_service_unavailable_payload(*, route: str) -> dict[str, Any]:
    try:
        _route_service()
        import_error = None
    except Exception as exc:
        import_error = exc

    details: dict[str, Any] = {
        "dependency": "services.library_create_route_service",
        "available": False,
    }

    if import_error is not None:
        details["exception_type"] = type(import_error).__name__
        details["exception"] = str(import_error)
        if _include_debug_details():
            try:
                details["traceback"] = traceback.format_exception(
                    type(import_error),
                    import_error,
                    import_error.__traceback__,
                )
            except Exception:
                pass

    return {
        "ok": False,
        "status": "route_service_unavailable",
        "route": route,
        "component": CREATE_BLUEPRINT_COMPONENT,
        "version": CREATE_BLUEPRINT_VERSION,
        "api_prefix": CREATE_API_PREFIX,
        "data": {
            "dependency": details,
        },
        "errors": [
            {
                "severity": "error",
                "code": "route_service_unavailable",
                "field": "services.library_create_route_service",
                "message": "Der Create-Route-Service konnte nicht importiert werden.",
                "details": _json_safe(details),
            }
        ],
        "warnings": [],
        "info": [],
        "_http_status": 503,
    }


def _service_unavailable_payload(
    *,
    route: str,
    dependency: str,
    code: str,
    message: str,
    exc: BaseException,
) -> dict[str, Any]:
    details: dict[str, Any] = {
        "dependency": dependency,
        "available": False,
        "exception_type": type(exc).__name__,
        "exception": str(exc),
    }

    if _include_debug_details():
        try:
            details["traceback"] = traceback.format_exception(
                type(exc),
                exc,
                exc.__traceback__,
            )
        except Exception:
            pass

    return {
        "ok": False,
        "status": "unavailable",
        "route": route,
        "component": CREATE_BLUEPRINT_COMPONENT,
        "version": CREATE_BLUEPRINT_VERSION,
        "api_prefix": CREATE_API_PREFIX,
        "data": {
            "dependency": details,
        },
        "errors": [
            {
                "severity": "error",
                "code": code,
                "field": dependency,
                "message": message,
                "details": _json_safe(details),
            }
        ],
        "warnings": [],
        "info": [],
        "_http_status": 503,
    }


def _failure_payload(
    *,
    route: str,
    code: str,
    message: str,
    exc: BaseException | None = None,
    details: Mapping[str, Any] | None = None,
    http_status: int = 500,
) -> dict[str, Any]:
    issue_details: dict[str, Any] = dict(details or {})

    if exc is not None:
        issue_details["exception_type"] = type(exc).__name__
        issue_details["exception"] = str(exc)
        if _include_debug_details():
            try:
                issue_details["traceback"] = traceback.format_exc()
            except Exception:
                pass

    return {
        "ok": False,
        "status": code,
        "route": route,
        "component": CREATE_BLUEPRINT_COMPONENT,
        "version": CREATE_BLUEPRINT_VERSION,
        "api_prefix": CREATE_API_PREFIX,
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


def _safe_bool(value: Any, *, default: bool = False) -> bool:
    if value is None:
        return default

    if isinstance(value, bool):
        return value

    text = str(value).strip().lower()

    if text in {"1", "true", "yes", "ja", "on", "enabled", "active", "allow", "allowed", "persist", "save"}:
        return True

    if text in {"0", "false", "no", "nein", "off", "disabled", "inactive", "deny", "blocked"}:
        return False

    return default


def _safe_http_status(value: Any) -> int:
    try:
        status = int(value)
    except Exception:
        return 500

    if status < 100 or status > 599:
        return 500

    return status


def _safe_filename(value: Any) -> str:
    text = str(value or "package.vplib").strip()
    text = text.replace("\\", "/").split("/")[-1]
    text = text.replace("\x00", "")

    if not text:
        text = "package.vplib"

    cleaned = []
    for char in text:
        if char.isalnum() or char in {"-", "_", ".", " "}:
            cleaned.append(char)
        else:
            cleaned.append("_")

    filename = "".join(cleaned).strip(" ._")

    if not filename:
        filename = "package.vplib"

    if not filename.endswith(".vplib"):
        filename = f"{filename}.vplib"

    return filename[:180]


def _safe_upload_filename(value: Any) -> str:
    text = str(value or "").strip()
    text = text.replace("\\", "/").split("/")[-1]
    text = text.replace("\x00", "")
    return text[:180]


def _safe_mapping(value: Any) -> dict[str, Any]:
    safe_value = _json_safe(value)

    if isinstance(safe_value, Mapping):
        return dict(safe_value)

    return {}


def _json_safe(value: Any) -> Any:
    if value is None or isinstance(value, (str, int, float, bool)):
        return value

    if _is_jinja_undefined(value):
        return None

    if isinstance(value, bytes):
        return {
            "type": "bytes",
            "size_bytes": len(value),
        }

    if isinstance(value, Enum):
        return _json_safe(value.value)

    if is_dataclass(value) and not isinstance(value, type):
        try:
            return _json_safe(asdict(value))
        except Exception:
            pass

    if isinstance(value, ModuleType):
        return {
            "module": getattr(value, "__name__", ""),
        }

    if isinstance(value, Mapping):
        return {str(key): _json_safe(inner_value) for key, inner_value in value.items()}

    if isinstance(value, (list, tuple, set)):
        return [_json_safe(item) for item in value]

    if hasattr(value, "to_dict") and callable(value.to_dict):
        for kwargs in (
            {"include_http_status": True},
            {"include_payloads": True},
            {},
        ):
            try:
                return _json_safe(value.to_dict(**kwargs))
            except TypeError:
                continue
            except Exception:
                break

    if hasattr(value, "isoformat") and callable(value.isoformat):
        try:
            return value.isoformat()
        except Exception:
            pass

    if callable(value):
        return {
            "callable": getattr(value, "__name__", type(value).__name__),
        }

    try:
        json.dumps(value)
        return value
    except Exception:
        return str(value)


def _html_escape(value: Any) -> str:
    text = str(value)
    return (
        text.replace("&", "&amp;")
        .replace("<", "&lt;")
        .replace(">", "&gt;")
        .replace('"', "&quot;")
        .replace("'", "&#x27;")
    )


def _extract_from_mapping_or_object(value: Any, key: str) -> Any:
    if value is None:
        return None

    if isinstance(value, Mapping):
        return value.get(key)

    try:
        return getattr(value, key)
    except Exception:
        return None


# ---------------------------------------------------------------------------
# Public diagnostics
# ---------------------------------------------------------------------------

def get_create_route_list() -> list[str]:
    """Return public create route list."""
    return [
        "GET /create",
        "GET /api/v1/vplib/create",
        "GET /api/v1/vplib/create/health",
        "GET /api/v1/vplib/create/routes",
        "GET /api/v1/vplib/create/selftest",
        "GET /api/v1/vplib/create/readiness",
        "GET /api/v1/vplib/create/creator-readiness",
        "GET /api/v1/vplib/create/options",
        "GET|POST /api/v1/vplib/create/create-context",
        "GET|POST /api/v1/vplib/create/context",
        "GET /api/v1/vplib/create/definitions/current",
        "POST /api/v1/vplib/create/draft",
        "POST /api/v1/vplib/create/drafts",
        "GET /api/v1/vplib/create/drafts/<draft_ref>",
        "PATCH /api/v1/vplib/create/drafts/<draft_ref>",
        "POST /api/v1/vplib/create/drafts/<draft_ref>/validate",
        "POST /api/v1/vplib/create/drafts/<draft_ref>/publish/prepare",
        "POST /api/v1/vplib/create/validate",
        "POST /api/v1/vplib/create/package-plan",
        "POST /api/v1/vplib/create/publish-bundle",
        "POST /api/v1/vplib/create/save",
        "POST /api/v1/vplib/create/download",
        "POST /api/v1/vplib/create/cache/clear",
    ]


def get_create_route_groups() -> dict[str, list[str]]:
    """Return grouped route map."""
    return {
        "page": [
            "GET /create",
        ],
        "diagnostics": [
            "GET /api/v1/vplib/create",
            "GET /api/v1/vplib/create/health",
            "GET /api/v1/vplib/create/routes",
            "GET /api/v1/vplib/create/selftest",
            "GET /api/v1/vplib/create/readiness",
            "GET /api/v1/vplib/create/creator-readiness",
            "POST /api/v1/vplib/create/cache/clear",
        ],
        "context": [
            "GET /api/v1/vplib/create/options",
            "GET|POST /api/v1/vplib/create/create-context",
            "GET|POST /api/v1/vplib/create/context",
            "GET /api/v1/vplib/create/definitions/current",
        ],
        "drafts": [
            "POST /api/v1/vplib/create/draft",
            "POST /api/v1/vplib/create/drafts",
            "GET /api/v1/vplib/create/drafts/<draft_ref>",
            "PATCH /api/v1/vplib/create/drafts/<draft_ref>",
            "POST /api/v1/vplib/create/drafts/<draft_ref>/validate",
            "POST /api/v1/vplib/create/drafts/<draft_ref>/publish/prepare",
        ],
        "generator_package": [
            "POST /api/v1/vplib/create/validate",
            "POST /api/v1/vplib/create/package-plan",
            "POST /api/v1/vplib/create/publish-bundle",
            "POST /api/v1/vplib/create/save",
            "POST /api/v1/vplib/create/download",
        ],
    }


def get_create_route_map_response() -> dict[str, Any]:
    """Return route map response."""
    return {
        "ok": True,
        "status": "ok",
        "component": CREATE_BLUEPRINT_COMPONENT,
        "version": CREATE_BLUEPRINT_VERSION,
        "api_prefix": CREATE_API_PREFIX,
        "page_route": CREATE_PAGE_ROUTE,
        "routes": get_create_route_list(),
        "route_count": len(get_create_route_list()),
        "groups": get_create_route_groups(),
        "_http_status": 200,
    }


def get_create_routes_health() -> dict[str, Any]:
    """Route-registry compatible health helper."""
    route_health = _safe_route_service_health()
    definition_health = _safe_definition_service_health()
    draft_health = _safe_draft_service_health()
    diagnostics_payload = _safe_generator_diagnostics_payload(
        {
            "checks": ["imports", "minimal_context"],
            "include_optional": False,
            "include_payloads": False,
            "check_dependencies": False,
        }
    )

    starter_readiness = _starter_readiness_payload(request_id=uuid.uuid4().hex)
    route_service_ok = bool(route_health.get("ok", False))
    starter_ready = bool(starter_readiness.get("ready", False))
    healthy = route_service_ok and starter_ready

    return {
        "ok": healthy,
        "healthy": healthy,
        "ready": healthy,
        "status": "healthy" if healthy else "degraded",
        "component": CREATE_BLUEPRINT_COMPONENT,
        "version": CREATE_BLUEPRINT_VERSION,
        "api_prefix": CREATE_API_PREFIX,
        "page_route": CREATE_PAGE_ROUTE,
        "routes": get_create_route_list(),
        "route_count": len(get_create_route_list()),
        "route_service": route_health,
        "creator_readiness": starter_readiness,
        "definition_catalog_service": definition_health,
        "draft_service": draft_health,
        "generator_diagnostics": diagnostics_payload,
        "supports_route_service": _is_route_service_available(),
        "supports_definition_create_context": _is_definition_service_available(),
        "supports_persistent_drafts": _is_draft_service_available(),
        "supports_generator_context": _is_generator_context_service_available(),
        "supports_generator_diagnostics": _is_generator_diagnostics_service_available(),
        "supports_page": True,
        "supports_download": True,
        "supports_verified_archive_download": True,
        "supports_server_download_preflight": True,
        "starter_profile_id": STARTER_VARIANT_PROFILE_ID,
        "_http_status": 200 if healthy else 503,
    }


def clear_create_route_caches() -> dict[str, Any]:
    """Clear create route and downstream service caches."""
    cleared: list[str] = []

    for cached_func in (
        _load_route_service_module,
        _load_definition_catalog_service_module,
        _load_creative_library_draft_service_module,
        _load_generator_context_service_module,
        _load_generator_diagnostics_service_module,
    ):
        try:
            cached_func.cache_clear()
            cleared.append(getattr(cached_func, "__name__", str(cached_func)))
        except Exception:
            pass

    for loader, clear_function_names in (
        (
            _load_route_service_module,
            (
                "clear_library_create_route_service_caches",
                "clear_cache",
            ),
        ),
        (
            _load_definition_catalog_service_module,
            (
                "clear_library_definition_catalog_service_caches",
                "clear_cache",
            ),
        ),
        (
            _load_creative_library_draft_service_module,
            (
                "clear_creative_library_draft_service_caches",
                "clear_cache",
            ),
        ),
        (
            _load_generator_context_service_module,
            (
                "clear_library_generator_context_service_caches",
                "clear_cache",
            ),
        ),
        (
            _load_generator_diagnostics_service_module,
            (
                "clear_library_generator_diagnostics_service_caches",
                "clear_cache",
            ),
        ),
    ):
        try:
            module = loader()
            for clear_function_name in clear_function_names:
                clear_function = getattr(module, clear_function_name, None)
                if callable(clear_function):
                    clear_function()
                    cleared.append(clear_function_name)
                    break
        except Exception:
            continue

    return {
        "ok": True,
        "status": "ok",
        "component": CREATE_BLUEPRINT_COMPONENT,
        "version": CREATE_BLUEPRINT_VERSION,
        "cleared": cleared,
    }


__all__ = [
    "CREATE_BLUEPRINT_COMPONENT",
    "CREATE_BLUEPRINT_VERSION",
    "CREATE_PAGE_ROUTE",
    "CREATE_API_PREFIX",
    "CREATE_TEMPLATE",
    "FALLBACK_TEMPLATE_TITLE",
    "DEFAULT_JSON_MIMETYPE",
    "DEFAULT_VPLIB_MIMETYPE",
    "DEFAULT_MAX_REQUEST_BYTES",
    "DEFAULT_MAX_ARCHIVE_BYTES",
    "STARTER_OBJECT_KIND",
    "STARTER_FAMILY_PROFILE_ID",
    "STARTER_VARIANT_PROFILE_ID",
    "STARTER_DEFAULT_VARIANT_ID",
    "CreateRouteError",
    "CreateRequestError",
    "CreateArchiveError",
    "create_bp",
    "bp",
    "blueprint",
    "get_create_routes_health",
    "get_create_route_map_response",
    "get_create_route_list",
    "get_create_route_groups",
    "clear_create_route_caches",
]