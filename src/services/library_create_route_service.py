# services/vectoplan-library/src/services/library_create_route_service.py
from __future__ import annotations

"""
VECTOPLAN Library – Create Route Service

HTTP-near service layer for the VPLIB create flow.

This module is deliberately route-adjacent, not a Flask route:
- no Flask dependency
- no direct database dependency
- no direct repository calls
- no migration logic
- no database schema creation
- no direct file-writing logic
- no package-generation logic in this file

Main role:
- normalize route payloads
- keep stable API response envelopes
- expose health/routes/cache helpers
- delegate generator/create work to the new generator workflow facade
- preserve backward-compatible function names for existing routes/create.py

Preferred delegation path:

    routes/create.py
      -> src/services/library_create_route_service.py
      -> src/library/services/library_generator_workflow_service.py
      -> src/library/services/library_generator_context_service.py
      -> existing services:
           library_create_service.py
           creative_library_draft_service.py
           library_file_service.py
           creative_library_service.py
           library_definition_catalog_service.py
           library_taxonomy_user_service.py
      -> src/vplib/*

Fallback path:
- if generator workflow is unavailable, selected read-only or legacy calls can
  still delegate to library_create_service.py / definition catalog / taxonomy
  where safe.

Important:
- Source save is still delegated and must be explicitly enabled downstream.
- Published writes are not performed here.
- Persistent draft writes are delegated to workflow/draft service.
- Binary download may use the existing in-memory archive builder as fallback.
"""

import base64
import binascii
import hashlib
import importlib
import inspect
import io
import json
import os
import posixpath
import traceback
import uuid
import zipfile
from dataclasses import dataclass, field as dataclass_field
from datetime import datetime, timezone
from functools import lru_cache
from enum import Enum
from types import ModuleType
from typing import Any, Callable, Iterable, Mapping


# ---------------------------------------------------------------------------
# Metadata / constants
# ---------------------------------------------------------------------------

LIBRARY_CREATE_ROUTE_SERVICE_VERSION = "0.7.0"
LIBRARY_CREATE_ROUTE_SERVICE_COMPONENT = "library-create-route-service"

CREATE_API_PREFIX = "/api/v1/vplib/create"
CREATE_PAGE_ROUTE = "/create"

DEFAULT_JSON_MIMETYPE = "application/json"
DEFAULT_VPLIB_MIMETYPE = "application/octet-stream"

TAXONOMY_REQUIRED_FIELDS = ("domain", "category", "subcategory")

VPLIB_UID_FIELD = "vplib_uid"
VPLIB_UID_KEYS = (
    "vplib_uid",
    "vplibUid",
    "vplib_uid_v1",
)


STARTER_OBJECT_KIND = "cell_block"
STARTER_FAMILY_PROFILE_ID = "simple_cell_block"
STARTER_VARIANT_PROFILE_ID = "simple_cell_block.v1"
STARTER_DEFAULT_VARIANT_ID = "default"
STARTER_DEFAULT_LABEL = "Standard"
STARTER_TAXONOMY = {
    "domain": "hochbau",
    "category": "waende",
    "subcategory": "aussenwaende",
}
STARTER_DIMENSIONS_MM = {
    "dimensions.width_mm": 1000,
    "dimensions.height_mm": 1000,
    "dimensions.depth_mm": 1000,
}
STARTER_REQUIRED_VALUE_KEYS = (
    "variant.variant_id",
    "variant.label",
    "dimensions.width_mm",
    "dimensions.height_mm",
    "dimensions.depth_mm",
)
STARTER_UID_NAMESPACE = uuid.UUID("85c825f8-4c1c-4ad6-923f-4cf389854d42")

VPLIB_ZIP_SIGNATURES = (
    b"PK\x03\x04",
    b"PK\x05\x06",
    b"PK\x07\x08",
)
DEFAULT_MAX_ARCHIVE_BYTES = 128 * 1024 * 1024
DEFAULT_MAX_ARCHIVE_ENTRIES = 4096
DEFAULT_MAX_ARCHIVE_UNCOMPRESSED_BYTES = 512 * 1024 * 1024
DEFAULT_MAX_COMPRESSION_RATIO = 500.0
DEFAULT_MAX_BINARY_NESTING = 10

WORKFLOW_SUCCESS_STATUSES = {
    "ok",
    "ready",
    "healthy",
    "partial",
    "success",
    "valid",
    "created",
    "prepared",
    "saved",
    "persisted",
    "draft_ready",
    "package_plan_ready",
    "archive_ready",
    "download_ready",
}
WORKFLOW_INVALID_STATUSES = {
    "invalid",
    "validation_failed",
    "draft_invalid",
    "taxonomy_required_fields_missing",
    "payload_normalization_failed",
}

GENERATOR_ROUTE_SERVICE_FEATURES = {
    "generator_context": True,
    "generator_workflow": True,
    "generator_diagnostics": True,
    "legacy_create_fallback": True,
    "legacy_non_ok_fallback": True,
    "legacy_binary_download_fallback": True,
    "stable_vplib_uid": True,
    "deterministic_starter_uid_fallback": True,
    "starter_contract_normalization": True,
    "starter_documents_optional": True,
    "download_preflight": True,
    "verified_zip_download": True,
    "safe_archive_member_validation": True,
    "direct_db_dependency": False,
    "direct_file_write": False,
    "direct_package_generation": False,
}


# ---------------------------------------------------------------------------
# Service contract errors
# ---------------------------------------------------------------------------

class LibraryCreateRouteServiceError(RuntimeError):
    """Base error for route-service contract failures."""

    def __init__(
        self,
        message: str,
        *,
        code: str = "create_route_service_error",
        http_status: int = 500,
        details: Mapping[str, Any] | None = None,
    ) -> None:
        super().__init__(message)
        self.code = str(code or "create_route_service_error")
        self.http_status = _safe_http_status(http_status)
        self.details = dict(details or {})


class CreatePayloadContractError(LibraryCreateRouteServiceError):
    """Raised when the normalized create payload violates the starter contract."""


class CreateArchiveContractError(LibraryCreateRouteServiceError):
    """Raised when generated VPLIB bytes are missing, malformed or unsafe."""


# ---------------------------------------------------------------------------
# Lazy imports
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
def _load_generator_context_service_module() -> ModuleType:
    return _import_first(
        (
            "library.services.library_generator_context_service",
            "src.library.services.library_generator_context_service",
            "vectoplan_library.library.services.library_generator_context_service",
            "vectoplan_library.src.library.services.library_generator_context_service",
        )
    )


@lru_cache(maxsize=1)
def _load_generator_workflow_service_module() -> ModuleType:
    return _import_first(
        (
            "library.services.library_generator_workflow_service",
            "src.library.services.library_generator_workflow_service",
            "vectoplan_library.library.services.library_generator_workflow_service",
            "vectoplan_library.src.library.services.library_generator_workflow_service",
        )
    )


@lru_cache(maxsize=1)
def _load_generator_diagnostics_service_module() -> ModuleType:
    return _import_first(
        (
            "library.services.library_generator_diagnostics_service",
            "src.library.services.library_generator_diagnostics_service",
            "vectoplan_library.library.services.library_generator_diagnostics_service",
            "vectoplan_library.src.library.services.library_generator_diagnostics_service",
        )
    )


@lru_cache(maxsize=1)
def _load_create_service_module() -> ModuleType:
    return _import_first(
        (
            "library.services.library_create_service",
            "src.library.services.library_create_service",
            "vectoplan_library.library.services.library_create_service",
            "vectoplan_library.src.library.services.library_create_service",
        )
    )


@lru_cache(maxsize=1)
def _load_variant_payload_service_module() -> ModuleType:
    return _import_first(
        (
            "services.library_create_variant_payload_service",
            "src.services.library_create_variant_payload_service",
            "library.services.library_create_variant_payload_service",
            "src.library.services.library_create_variant_payload_service",
            "vectoplan_library.services.library_create_variant_payload_service",
            "vectoplan_library.src.services.library_create_variant_payload_service",
            "vectoplan_library.library.services.library_create_variant_payload_service",
            "library_create_variant_payload_service",
        )
    )


@lru_cache(maxsize=1)
def _load_taxonomy_module() -> ModuleType:
    return _import_first(
        (
            "library.taxonomy",
            "src.library.taxonomy",
            "vectoplan_library.library.taxonomy",
            "vectoplan_library.src.library.taxonomy",
        )
    )


@lru_cache(maxsize=1)
def _load_definition_catalog_service_module() -> ModuleType:
    return _import_first(
        (
            "library.services.library_definition_catalog_service",
            "src.library.services.library_definition_catalog_service",
            "vectoplan_library.library.services.library_definition_catalog_service",
            "vectoplan_library.src.library.services.library_definition_catalog_service",
        )
    )


@lru_cache(maxsize=1)
def _load_legacy_definitions_module() -> ModuleType:
    return _import_first(
        (
            "library.definitions",
            "src.library.definitions",
            "vectoplan_library.library.definitions",
            "vectoplan_library.src.library.definitions",
        )
    )


def _generator_context_module() -> ModuleType:
    return _load_generator_context_service_module()


def _generator_workflow_module() -> ModuleType:
    return _load_generator_workflow_service_module()


def _generator_diagnostics_module() -> ModuleType:
    return _load_generator_diagnostics_service_module()


def _create_service() -> ModuleType:
    return _load_create_service_module()


def _variant_payload_service() -> ModuleType:
    return _load_variant_payload_service_module()


def _taxonomy_module() -> ModuleType:
    return _load_taxonomy_module()


def _definition_catalog_service() -> Any:
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
    if service_class is not None:
        return service_class()

    raise RuntimeError("LibraryDefinitionCatalogService is not available.")


def _generator_context_service() -> Any:
    module = _generator_context_module()

    factory = getattr(module, "get_library_generator_context_service", None)
    if callable(factory):
        return factory()

    service_class = getattr(module, "LibraryGeneratorContextService", None)
    if service_class is not None:
        return service_class()

    return module


def _generator_workflow_service() -> Any:
    module = _generator_workflow_module()

    factory = getattr(module, "get_library_generator_workflow_service", None)
    if callable(factory):
        return factory()

    service_class = getattr(module, "LibraryGeneratorWorkflowService", None)
    if service_class is not None:
        return service_class()

    return module


def _generator_diagnostics_service() -> Any:
    module = _generator_diagnostics_module()

    factory = getattr(module, "get_library_generator_diagnostics_service", None)
    if callable(factory):
        return factory()

    service_class = getattr(module, "LibraryGeneratorDiagnosticsService", None)
    if service_class is not None:
        return service_class()

    return module


# ---------------------------------------------------------------------------
# Response dataclasses
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class RouteIssue:
    """Serializable route-level issue."""

    code: str
    message: str
    field: str = ""
    severity: str = "error"
    details: dict[str, Any] = dataclass_field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        payload: dict[str, Any] = {
            "severity": str(self.severity),
            "code": str(self.code),
            "message": str(self.message),
        }

        if self.field:
            payload["field"] = str(self.field)

        if self.details:
            payload["details"] = _json_safe(self.details)

        return payload


@dataclass(frozen=True)
class RouteResponse:
    """JSON-oriented response envelope for route handlers."""

    ok: bool
    status: str
    route: str
    data: dict[str, Any] = dataclass_field(default_factory=dict)
    errors: list[RouteIssue | dict[str, Any]] = dataclass_field(default_factory=list)
    warnings: list[RouteIssue | dict[str, Any]] = dataclass_field(default_factory=list)
    info: list[RouteIssue | dict[str, Any]] = dataclass_field(default_factory=list)
    http_status: int = 200

    def __post_init__(self) -> None:
        object.__setattr__(self, "data", _json_safe_dict(self.data))
        object.__setattr__(self, "errors", _json_safe_issue_list(self.errors))
        object.__setattr__(self, "warnings", _json_safe_issue_list(self.warnings))
        object.__setattr__(self, "info", _json_safe_issue_list(self.info))

    def to_dict(self, *, include_http_status: bool = True) -> dict[str, Any]:
        payload: dict[str, Any] = {
            "ok": bool(self.ok),
            "status": str(self.status),
            "route": str(self.route),
            "version": LIBRARY_CREATE_ROUTE_SERVICE_VERSION,
            "component": LIBRARY_CREATE_ROUTE_SERVICE_COMPONENT,
            "api_prefix": CREATE_API_PREFIX,
            "vplib_uid": _extract_vplib_uid_from_any(self.data),
            "data": _json_safe(self.data),
            "errors": [_issue_to_dict(issue) for issue in self.errors],
            "warnings": [_issue_to_dict(issue) for issue in self.warnings],
            "info": [_issue_to_dict(issue) for issue in self.info],
        }

        if include_http_status:
            payload["_http_status"] = _safe_http_status(self.http_status)

        return payload

    def to_tuple(self) -> tuple[dict[str, Any], int, dict[str, str]]:
        return (
            self.to_dict(include_http_status=True),
            _safe_http_status(self.http_status),
            {"Cache-Control": "no-store"},
        )


@dataclass(frozen=True)
class RouteBinaryResponse:
    """
    Binary response envelope for route handlers.

    The Flask blueprint should use:
    - filename
    - content
    - mimetype
    - http_status
    """

    ok: bool
    status: str
    route: str
    filename: str = "package.vplib"
    content: bytes = b""
    mimetype: str = DEFAULT_VPLIB_MIMETYPE
    data: dict[str, Any] = dataclass_field(default_factory=dict)
    errors: list[RouteIssue | dict[str, Any]] = dataclass_field(default_factory=list)
    warnings: list[RouteIssue | dict[str, Any]] = dataclass_field(default_factory=list)
    info: list[RouteIssue | dict[str, Any]] = dataclass_field(default_factory=list)
    http_status: int = 200

    def __post_init__(self) -> None:
        object.__setattr__(self, "data", _json_safe_dict(self.data))
        object.__setattr__(self, "errors", _json_safe_issue_list(self.errors))
        object.__setattr__(self, "warnings", _json_safe_issue_list(self.warnings))
        object.__setattr__(self, "info", _json_safe_issue_list(self.info))

    def to_dict(self, *, include_http_status: bool = True) -> dict[str, Any]:
        payload: dict[str, Any] = {
            "ok": bool(self.ok),
            "status": str(self.status),
            "route": str(self.route),
            "version": LIBRARY_CREATE_ROUTE_SERVICE_VERSION,
            "component": LIBRARY_CREATE_ROUTE_SERVICE_COMPONENT,
            "api_prefix": CREATE_API_PREFIX,
            "vplib_uid": _extract_vplib_uid_from_any(self.data),
            "filename": self.filename,
            "mimetype": self.mimetype,
            "size_bytes": len(self.content),
            "data": _json_safe(self.data),
            "errors": [_issue_to_dict(issue) for issue in self.errors],
            "warnings": [_issue_to_dict(issue) for issue in self.warnings],
            "info": [_issue_to_dict(issue) for issue in self.info],
        }

        if include_http_status:
            payload["_http_status"] = _safe_http_status(self.http_status)

        return payload


# ---------------------------------------------------------------------------
# Public route contract
# ---------------------------------------------------------------------------

def get_route_plan() -> dict[str, Any]:
    """Return the expected create-route contract."""
    return {
        "page": {
            "method": "GET",
            "path": CREATE_PAGE_ROUTE,
            "description": "Renders the VPLIB Create UI.",
        },
        "health": {
            "method": "GET",
            "path": f"{CREATE_API_PREFIX}/health",
            "description": "Health for create route service and delegated services.",
        },
        "routes": {
            "method": "GET",
            "path": f"{CREATE_API_PREFIX}/routes",
            "description": "Returns create route metadata.",
        },
        "selftest": {
            "method": "GET",
            "path": f"{CREATE_API_PREFIX}/selftest",
            "description": "Runs create/generator route selftest.",
        },
        "options": {
            "method": "GET",
            "path": f"{CREATE_API_PREFIX}/options",
            "description": "Returns generator-backed create options.",
        },
        "context": {
            "method": "GET|POST",
            "path": f"{CREATE_API_PREFIX}/context",
            "description": "Returns generator frontend context.",
        },
        "create_context": {
            "method": "GET|POST",
            "path": f"{CREATE_API_PREFIX}/create-context",
            "description": "Backward-compatible alias for generator frontend context.",
        },
        "template_context": {
            "method": "INTERNAL",
            "path": CREATE_PAGE_ROUTE,
            "description": "Builds JSON-safe Jinja context for the VPLIB Create UI.",
        },
        "definitions_current": {
            "method": "GET",
            "path": f"{CREATE_API_PREFIX}/definitions/current",
            "description": "Returns current definition context in create namespace.",
        },
        "draft": {
            "method": "POST",
            "path": f"{CREATE_API_PREFIX}/draft",
            "description": "Builds generator/create draft payload.",
        },
        "persistent_draft": {
            "method": "POST",
            "path": f"{CREATE_API_PREFIX}/drafts",
            "description": "Creates a persistent generator draft through workflow service.",
        },
        "persistent_draft_payload": {
            "method": "POST",
            "path": f"{CREATE_API_PREFIX}/draft/persistent-payload",
            "description": "Builds or delegates persistent draft payload.",
        },
        "validate": {
            "method": "POST",
            "path": f"{CREATE_API_PREFIX}/validate",
            "description": "Validates create/generator payload.",
        },
        "package_plan": {
            "method": "POST",
            "path": f"{CREATE_API_PREFIX}/package-plan",
            "description": "Builds package plan without route-level write.",
        },
        "publish_bundle": {
            "method": "POST",
            "path": f"{CREATE_API_PREFIX}/publish-bundle",
            "description": "Builds publish-prepare payload without direct route publish.",
        },
        "download": {
            "method": "POST",
            "path": f"{CREATE_API_PREFIX}/download",
            "description": "Prepares or builds in-memory .vplib download.",
        },
        "save": {
            "method": "POST",
            "path": f"{CREATE_API_PREFIX}/save",
            "description": "Delegates source package save. Write policy remains downstream.",
        },
        "cache_clear": {
            "method": "POST",
            "path": f"{CREATE_API_PREFIX}/cache/clear",
            "description": "Clears route, generator and delegated service caches.",
        },
    }


def get_route_service_health() -> RouteResponse:
    """Return health for route service and delegated services."""
    route = "health"

    errors: list[RouteIssue | dict[str, Any]] = []
    warnings: list[RouteIssue | dict[str, Any]] = []
    info: list[RouteIssue | dict[str, Any]] = []

    generator_context_health = _safe_generator_context_health()
    generator_workflow_health = _safe_generator_workflow_health()
    generator_diagnostics_health = _safe_generator_diagnostics_health()
    create_health = _safe_create_service_health()
    normalizer_health = _safe_variant_payload_service_health()
    taxonomy_health = _safe_taxonomy_service_health()
    definitions_health = _safe_definitions_health()

    workflow_available = bool(generator_workflow_health.get("available"))
    create_available = bool(create_health.get("available"))

    if not workflow_available and not create_available:
        errors.append(
            _error(
                "generator_and_create_services_unavailable",
                "Neither generator workflow service nor legacy create service is available.",
                field="generator_workflow",
                details={
                    "generator_workflow": generator_workflow_health,
                    "create_service": create_health,
                },
            )
        )

    if not workflow_available:
        warnings.append(
            _warning(
                "generator_workflow_unavailable",
                "Generator workflow service is unavailable. Legacy fallback may be used where possible.",
                field="library_generator_workflow_service",
                details=generator_workflow_health,
            )
        )

    if not bool(generator_context_health.get("available")):
        warnings.append(
            _warning(
                "generator_context_unavailable",
                "Generator context service is unavailable. Create context/options may degrade.",
                field="library_generator_context_service",
                details=generator_context_health,
            )
        )

    if not bool(generator_diagnostics_health.get("available")):
        warnings.append(
            _warning(
                "generator_diagnostics_unavailable",
                "Generator diagnostics service is unavailable.",
                field="library_generator_diagnostics_service",
                details=generator_diagnostics_health,
            )
        )

    if not bool(normalizer_health.get("available")):
        warnings.append(
            _warning(
                "payload_normalizer_unavailable",
                "Create payload normalizer is unavailable. Route service will use fallback UID handling.",
                field="library_create_variant_payload_service",
                details=normalizer_health,
            )
        )

    if not bool(taxonomy_health.get("available")):
        warnings.append(
            _warning(
                "taxonomy_service_unavailable",
                "Taxonomy service is unavailable. Generator context may report partial status.",
                field="library.taxonomy",
                details=taxonomy_health,
            )
        )

    if not bool(definitions_health.get("available")):
        warnings.append(
            _warning(
                "definitions_unavailable",
                "Definitions service is unavailable. Generator context may report partial status.",
                field="definitions",
                details=definitions_health,
            )
        )

    if workflow_available:
        info.append(
            _info(
                "generator_workflow_available",
                "Generator workflow service is available.",
                details=generator_workflow_health,
            )
        )

    ok = len(errors) == 0

    return RouteResponse(
        ok=ok,
        status="healthy" if ok and not warnings else "partial" if ok else "unhealthy",
        route=route,
        data={
            "service": LIBRARY_CREATE_ROUTE_SERVICE_COMPONENT,
            "version": LIBRARY_CREATE_ROUTE_SERVICE_VERSION,
            "api_prefix": CREATE_API_PREFIX,
            "page_route": CREATE_PAGE_ROUTE,
            "route_plan": get_route_plan(),
            "features": dict(GENERATOR_ROUTE_SERVICE_FEATURES),
            "dependency": {
                "generator_context_available": bool(generator_context_health.get("available")),
                "generator_workflow_available": bool(generator_workflow_health.get("available")),
                "generator_diagnostics_available": bool(generator_diagnostics_health.get("available")),
                "create_service_available": bool(create_health.get("available")),
                "payload_normalizer_available": bool(normalizer_health.get("available")),
                "taxonomy_service_available": bool(taxonomy_health.get("available")),
                "definitions_available": bool(definitions_health.get("available")),
                "taxonomy_required_fields": list(TAXONOMY_REQUIRED_FIELDS),
                "vplib_uid_field": VPLIB_UID_FIELD,
                "starter_object_kind": STARTER_OBJECT_KIND,
                "starter_family_profile_id": STARTER_FAMILY_PROFILE_ID,
                "starter_variant_profile_id": STARTER_VARIANT_PROFILE_ID,
                "verified_zip_download": True,
            },
            "generator_context_health": generator_context_health,
            "generator_workflow_health": generator_workflow_health,
            "generator_diagnostics_health": generator_diagnostics_health,
            "create_service_health": create_health,
            "payload_normalizer_health": normalizer_health,
            "taxonomy_service_health": taxonomy_health,
            "definitions_service_health": definitions_health,
            "timestamp": _utc_now(),
        },
        errors=errors,
        warnings=warnings,
        info=info,
        http_status=200 if ok else 503,
    )


# ---------------------------------------------------------------------------
# Public response functions
# ---------------------------------------------------------------------------

def get_options_response(*, user_id: Any = 1) -> RouteResponse:
    """Return generator-backed create options in a route envelope."""
    route = "options"

    payload = {
        "user_id": user_id,
        "include_definitions": True,
        "include_taxonomy": True,
        "include_uploads": True,
    }

    if _is_generator_context_available():
        try:
            module = _generator_context_module()
            function = getattr(module, "get_generator_create_options", None)

            if callable(function):
                result_payload = _service_result_payload(
                    function(
                        payload,
                        build_options={
                            "include_diagnostics": True,
                            "include_raw_payloads": False,
                            "compact": True,
                        },
                    )
                )
                response = _route_response_from_payload(
                    result_payload,
                    route=route,
                    default_status="ok",
                    success_statuses={"ok", "ready", "partial"},
                )
                response = _enrich_options_response_with_taxonomy(response)
                response = _enrich_options_response_with_definitions(response, user_id=user_id)
                response = _enrich_options_response_with_create_runtime(response)
                return _attach_vplib_uid_to_response(response, payload=result_payload)

            service = _generator_context_service()
            method = getattr(service, "get_create_options", None)
            if callable(method):
                result_payload = _service_result_payload(
                    method(
                        request=payload,
                        build_options={
                            "include_diagnostics": True,
                            "include_raw_payloads": False,
                            "compact": True,
                        },
                    )
                )
                response = _route_response_from_payload(
                    result_payload,
                    route=route,
                    default_status="ok",
                    success_statuses={"ok", "ready", "partial"},
                )
                response = _enrich_options_response_with_taxonomy(response)
                response = _enrich_options_response_with_definitions(response, user_id=user_id)
                response = _enrich_options_response_with_create_runtime(response)
                return _attach_vplib_uid_to_response(response, payload=result_payload)

        except Exception as exc:
            fallback_warning = _exception_warning(
                "generator_options_failed",
                exc,
                field="generator_context",
                fallback_message="Generator-backed create options failed. Falling back to legacy create options.",
            )
        else:
            fallback_warning = None
    else:
        fallback_warning = _warning(
            "generator_context_unavailable",
            "Generator context service is unavailable. Falling back to legacy create options.",
            field="generator_context",
            details=_safe_generator_context_health(),
        )

    legacy_response = _legacy_options_response(user_id=user_id)
    warnings = list(legacy_response.warnings)
    if fallback_warning is not None:
        warnings.insert(0, fallback_warning)

    return RouteResponse(
        ok=legacy_response.ok,
        status=legacy_response.status,
        route=legacy_response.route,
        data=legacy_response.data,
        errors=legacy_response.errors,
        warnings=warnings,
        info=legacy_response.info,
        http_status=legacy_response.http_status,
    )


def get_create_context_response(payload: Any = None) -> RouteResponse:
    """Return generator/create frontend context."""
    route = "create-context"
    normalized_payload = _safe_normalize_payload_for_response(payload, route=route)
    if isinstance(normalized_payload, RouteResponse):
        return normalized_payload

    if _is_generator_context_available():
        try:
            module = _generator_context_module()

            for function_name in (
                "get_generator_frontend_context",
                "get_generator_context_payload",
            ):
                function = getattr(module, function_name, None)
                if not callable(function):
                    continue

                if function_name == "get_generator_context_payload":
                    result = function(
                        normalized_payload,
                        mode="frontend",
                        build_options={
                            "include_diagnostics": True,
                            "include_raw_payloads": False,
                            "compact": True,
                        },
                    )
                else:
                    result = function(
                        normalized_payload,
                        build_options={
                            "include_diagnostics": True,
                            "include_raw_payloads": False,
                            "compact": True,
                        },
                    )

                result_payload = _service_result_payload(result)

                return _route_response_from_payload(
                    {
                        "ok": bool(result_payload.get("ok", True)),
                        "status": result_payload.get("status", "ok"),
                        "data": {
                            "route_service": _route_service_metadata(route, normalized_payload),
                            "generator_context": result_payload,
                            "definition_context": _extract_nested(result_payload, "data.definition_context", default={}),
                            "taxonomy_context": _extract_nested(result_payload, "data.taxonomy_context", default={}),
                            "upload_config": _extract_nested(result_payload, "data.upload_config", default={}),
                            "window_payload": result_payload.get("window_payload") or _extract_nested(result_payload, "data.window_payload", default={}),
                        },
                        "warnings": result_payload.get("warnings", []),
                        "errors": result_payload.get("errors", []),
                        "info": result_payload.get("info", []),
                    },
                    route=route,
                    default_status="ok",
                    success_statuses={"ok", "ready", "partial"},
                )

        except Exception as exc:
            fallback_warning = _exception_warning(
                "generator_context_failed",
                exc,
                field="generator_context",
                fallback_message="Generator context could not be built. Falling back to definition create-context.",
            )
        else:
            fallback_warning = None
    else:
        fallback_warning = _warning(
            "generator_context_unavailable",
            "Generator context service is unavailable. Falling back to definition create-context.",
            field="generator_context",
            details=_safe_generator_context_health(),
        )

    legacy_response = _legacy_create_context_response(normalized_payload)
    warnings = list(legacy_response.warnings)
    if fallback_warning is not None:
        warnings.insert(0, fallback_warning)

    return RouteResponse(
        ok=legacy_response.ok,
        status=legacy_response.status,
        route=legacy_response.route,
        data=legacy_response.data,
        errors=legacy_response.errors,
        warnings=warnings,
        info=legacy_response.info,
        http_status=legacy_response.http_status,
    )


def get_current_definitions_response(*, user_id: Any = 1) -> RouteResponse:
    """Return current definition catalog through generator context when possible."""
    route = "definitions-current"

    if _is_generator_context_available():
        try:
            module = _generator_context_module()
            function = getattr(module, "get_generator_context_payload", None)

            if callable(function):
                result_payload = _service_result_payload(
                    function(
                        {
                            "user_id": user_id,
                            "include_definitions": True,
                            "include_taxonomy": False,
                            "include_uploads": False,
                        },
                        mode="public",
                        build_options={
                            "include_diagnostics": True,
                            "include_raw_payloads": False,
                            "include_records": True,
                            "compact": False,
                        },
                    )
                )

                definitions = (
                    _extract_nested(result_payload, "definitions", default={})
                    or _extract_nested(result_payload, "data.definitions", default={})
                    or _extract_nested(result_payload, "payload.definitions", default={})
                )

                return RouteResponse(
                    ok=bool(result_payload.get("ok", True)),
                    status=str(result_payload.get("status") or "ok"),
                    route=route,
                    data={
                        "route_service": _route_service_metadata(route),
                        "source": "generator_context",
                        "definitions": definitions,
                        "generator_context": result_payload,
                    },
                    errors=_coerce_issue_list(result_payload.get("errors", [])),
                    warnings=_coerce_issue_list(result_payload.get("warnings", [])),
                    info=_coerce_issue_list(result_payload.get("info", [])),
                    http_status=200 if bool(result_payload.get("ok", True)) else 422,
                )
        except Exception:
            pass

    if not _is_definition_catalog_available():
        health = _safe_definitions_health()
        return RouteResponse(
            ok=False,
            status="definitions_unavailable",
            route=route,
            data={
                "route_service": _route_service_metadata(route),
                "definitions": health,
            },
            errors=[
                _error(
                    "definitions_unavailable",
                    "Definition-Catalog-Service is unavailable.",
                    field="definitions",
                    details=health,
                )
            ],
            http_status=503,
        )

    try:
        service = _definition_catalog_service()

        for method_name in ("get_current_catalog", "get_create_options", "get_summary"):
            method = getattr(service, method_name, None)
            if not callable(method):
                continue

            result = _call_function_flex(method, {"user_id": user_id, "resolved": True})
            result_payload = _service_result_payload(result)

            return RouteResponse(
                ok=bool(result_payload.get("ok", True)),
                status=str(result_payload.get("status") or "ok"),
                route=route,
                data={
                    "route_service": _route_service_metadata(route),
                    "source": "definition_catalog_service",
                    "method": method_name,
                    "definitions": result_payload,
                },
                errors=_coerce_issue_list(result_payload.get("errors", [])),
                warnings=_coerce_issue_list(result_payload.get("warnings", [])),
                info=_coerce_issue_list(result_payload.get("info", [])),
                http_status=200,
            )

        raise RuntimeError("Definition catalog service exposes no readable catalog method.")

    except Exception as exc:
        return _failure(
            route=route,
            code="definitions_current_failed",
            message="Current Definition Catalog could not be loaded.",
            exc=exc,
            http_status=500,
        )


def build_draft_response(payload: Any) -> RouteResponse:
    """Normalize incoming user input to a generator draft response."""
    normalized_or_error = _normalize_create_action_payload(payload, route="draft")
    if isinstance(normalized_or_error, RouteResponse):
        return normalized_or_error

    return _workflow_route_response(
        action="draft",
        route="draft",
        payload=normalized_or_error,
        success_status="draft_ready",
        fallback_legacy_function="build_draft",
        fallback_http_status=422,
    )



def validate_draft_response(payload: Any) -> RouteResponse:
    """Validate the canonical create payload used by plan and download."""
    route = "validate"
    normalized_or_error = _normalize_create_action_payload(payload, route=route)
    if isinstance(normalized_or_error, RouteResponse):
        return normalized_or_error

    normalized_payload = dict(normalized_or_error)
    starter_error = _validate_starter_contract_response(
        normalized_payload,
        route=route,
    )
    if starter_error is not None:
        return starter_error

    normalized_payload["validate_before_write"] = True
    normalized_payload["include_documents"] = _resolve_include_documents(
        normalized_payload,
        requested=normalized_payload.get("include_documents"),
    )
    normalized_payload["includeDocuments"] = normalized_payload["include_documents"]

    response = _workflow_route_response(
        action="validate",
        route=route,
        payload=normalized_payload,
        success_status="valid",
        fallback_legacy_function="validate_draft",
        fallback_http_status=422,
    )
    return _attach_action_contract_to_response(
        response,
        normalized_payload,
        action=route,
    )


def build_package_plan_response(payload: Any, *, include_documents: bool = True) -> RouteResponse:
    """Build a package plan from the same canonical payload used by download."""
    route = "package-plan"
    normalized_or_error = _normalize_create_action_payload(payload, route=route)
    if isinstance(normalized_or_error, RouteResponse):
        return normalized_or_error

    normalized_payload = dict(normalized_or_error)
    starter_error = _validate_starter_contract_response(
        normalized_payload,
        route=route,
    )
    if starter_error is not None:
        return starter_error

    resolved_include_documents = _resolve_include_documents(
        normalized_payload,
        requested=include_documents,
    )
    normalized_payload["include_documents"] = resolved_include_documents
    normalized_payload["includeDocuments"] = resolved_include_documents
    normalized_payload["validate_before_write"] = True

    response = _workflow_route_response(
        action="package_plan",
        route=route,
        payload=normalized_payload,
        success_status="ok",
        fallback_legacy_function="build_package_plan",
        fallback_kwargs={"include_documents": resolved_include_documents},
        fallback_http_status=422,
    )
    return _attach_action_contract_to_response(
        response,
        normalized_payload,
        action=route,
        extra={"include_documents": resolved_include_documents},
    )

def build_persistent_draft_payload_response(payload: Any) -> RouteResponse:
    """Build or persist CreativeLibraryDraftService-compatible payload."""
    normalized_or_error = _normalize_create_action_payload(payload, route="persistent-draft-payload")
    if isinstance(normalized_or_error, RouteResponse):
        return normalized_or_error

    normalized_payload = dict(normalized_or_error)
    normalized_payload.setdefault("persist", True)
    normalized_payload.setdefault("allow_draft_write", True)

    return _workflow_route_response(
        action="persist_draft",
        route="persistent-draft-payload",
        payload=normalized_payload,
        success_status="persisted",
        fallback_legacy_function="build_persistent_draft_payload",
        fallback_http_status=500,
    )


def build_publish_bundle_response(payload: Any) -> RouteResponse:
    """Build publish-prepare payload without publishing."""
    normalized_or_error = _normalize_create_action_payload(payload, route="publish-bundle")
    if isinstance(normalized_or_error, RouteResponse):
        return normalized_or_error

    return _workflow_route_response(
        action="publish_prepare",
        route="publish-bundle",
        payload=normalized_or_error,
        success_status="prepared",
        fallback_legacy_function="build_publish_bundle_from_create_payload",
        fallback_http_status=500,
    )


def save_package_response(
    payload: Any,
    *,
    overwrite: bool | None = None,
    allow_source_write: bool | None = None,
    save_source: bool | None = None,
    dry_run: bool | None = None,
) -> RouteResponse:
    """Delegate source package save through generator workflow or legacy create service."""
    route = "save"

    normalized_or_error = _normalize_create_action_payload(payload, route=route)
    if isinstance(normalized_or_error, RouteResponse):
        return normalized_or_error

    normalized_payload = dict(normalized_or_error)

    for key, value in (
        ("allow_source_write", allow_source_write),
        ("save_source", save_source),
        ("dry_run", dry_run),
    ):
        if value is not None:
            normalized_payload[key] = bool(value)
    if overwrite is None:
        overwrite = _extract_overwrite(normalized_payload)

    normalized_payload["overwrite"] = bool(overwrite) if overwrite is not None else False
    normalized_payload.setdefault(
        "allow_source_write",
        _safe_bool(
            normalized_payload.get("allow_source_write")
            or normalized_payload.get("write_enabled")
            or normalized_payload.get("save_source"),
            default=False,
        ),
    )
    normalized_payload.setdefault("save_source", True)

    response = _workflow_route_response(
        action="save",
        route=route,
        payload=normalized_payload,
        success_status="saved",
        fallback_legacy_function="save_package",
        fallback_kwargs={"overwrite": overwrite},
        fallback_http_status=500,
    )

    if response.status in {"skipped", "workflow_skipped"}:
        return RouteResponse(
            ok=False,
            status=response.status,
            route=response.route,
            data=response.data,
            errors=response.errors,
            warnings=response.warnings,
            info=response.info,
            http_status=403,
        )

    return response



def build_download_response(payload: Any) -> RouteBinaryResponse:
    """Build a verified in-memory ``.vplib`` ZIP archive."""
    route = "download"

    normalized_or_error = _normalize_create_action_payload(payload, route=route)
    if isinstance(normalized_or_error, RouteResponse):
        return _binary_from_route_response(normalized_or_error)

    normalized_payload = dict(normalized_or_error)
    starter_error = _validate_starter_contract_response(
        normalized_payload,
        route=route,
    )
    if starter_error is not None:
        return _binary_from_route_response(starter_error)

    include_documents = _resolve_include_documents(
        normalized_payload,
        requested=normalized_payload.get("include_documents"),
    )
    normalized_payload["include_documents"] = include_documents
    normalized_payload["includeDocuments"] = include_documents
    normalized_payload["validate_before_write"] = True
    normalized_payload["prefer_cache"] = False

    preflight_payload: dict[str, Any] = {
        "ok": True,
        "status": "preflight_delegated_to_blueprint",
        "external": True,
    }
    preflight_warnings: list[RouteIssue | dict[str, Any]] = []

    # Direct service callers do not have the Flask blueprint's preflight. The
    # blueprint marks its normalized payload with these internal fields.
    blueprint_preflight = bool(
        normalized_payload.get("_create_blueprint_version")
        and normalized_payload.get("_create_route") == "download"
    )
    if not blueprint_preflight and _safe_bool(
        normalized_payload.get("route_service_preflight"),
        default=True,
    ):
        validation = validate_draft_response(dict(normalized_payload))
        if not validation.ok:
            return _binary_from_route_response(
                _download_preflight_failure(
                    validation,
                    normalized_payload,
                    stage="validation",
                )
            )

        plan = build_package_plan_response(
            dict(normalized_payload),
            include_documents=include_documents,
        )
        if not plan.ok:
            return _binary_from_route_response(
                _download_preflight_failure(
                    plan,
                    normalized_payload,
                    stage="package_plan",
                )
            )

        preflight_payload = {
            "ok": True,
            "status": "preflight_ok",
            "external": False,
            "validation": _compact_route_response(validation),
            "package_plan": _compact_route_response(plan),
            "include_documents": include_documents,
        }

    workflow_warning: RouteIssue | dict[str, Any] | None = None

    # Prefer direct workflow bytes when they are present and valid.
    if _is_generator_workflow_available():
        try:
            workflow_payload = _run_workflow_payload(
                action="download",
                payload=normalized_payload,
                extra_request={
                    "validate_before_write": True,
                    "prefer_cache": False,
                    "include_documents": include_documents,
                    "require_binary": True,
                },
            )
            workflow_response = _route_response_from_workflow_payload(
                workflow_payload,
                route=route,
                success_status="download_ready",
            )

            if workflow_response.ok:
                binary = _extract_binary_download_payload(workflow_payload)
                if binary is not None:
                    filename, content, meta_payload = binary
                    archive_metadata = validate_vplib_archive(content)
                    workflow_response = _attach_vplib_uid_to_response(
                        workflow_response,
                        payload=normalized_payload,
                        result=workflow_payload,
                    )

                    return RouteBinaryResponse(
                        ok=True,
                        status="download_ready",
                        route=route,
                        filename=_safe_download_filename(filename),
                        content=content,
                        mimetype=DEFAULT_VPLIB_MIMETYPE,
                        data={
                            **workflow_response.data,
                            "download": meta_payload,
                            "download_source": "generator_workflow",
                            "archive": archive_metadata,
                            "preflight": preflight_payload,
                            "payload_contract": _payload_contract_metadata(
                                normalized_payload
                            ),
                        },
                        errors=workflow_response.errors,
                        warnings=workflow_response.warnings,
                        info=workflow_response.info,
                        http_status=200,
                    )

                workflow_warning = _warning(
                    "generator_workflow_binary_missing",
                    "Generator workflow completed without direct archive bytes. "
                    "The create-service archive fallback will be used.",
                    field="generator_workflow.download",
                    details={
                        "status": workflow_response.status,
                        "workflow_status": workflow_payload.get("status"),
                    },
                )
            else:
                workflow_warning = _warning(
                    "generator_workflow_download_not_ok",
                    "Generator workflow did not produce a successful download. "
                    "The create-service archive fallback will be used.",
                    field="generator_workflow.download",
                    details=_compact_route_response(workflow_response),
                )
        except Exception as exc:
            workflow_warning = _exception_warning(
                "generator_workflow_download_failed",
                exc,
                field="generator_workflow.download",
                fallback_message=(
                    "Generator workflow download failed. "
                    "The create-service archive fallback will be used."
                ),
            )

    if not _is_create_service_available():
        unavailable = _service_unavailable(route)
        if workflow_warning is not None:
            unavailable = RouteResponse(
                ok=unavailable.ok,
                status=unavailable.status,
                route=unavailable.route,
                data={
                    **unavailable.data,
                    "preflight": preflight_payload,
                },
                errors=unavailable.errors,
                warnings=[workflow_warning, *unavailable.warnings],
                info=unavailable.info,
                http_status=unavailable.http_status,
            )
        return _binary_from_route_response(unavailable)

    try:
        create_service = _create_service()
        build_archive = getattr(create_service, "build_vplib_archive", None)
        if not callable(build_archive):
            raise RuntimeError(
                "Create service does not expose build_vplib_archive."
            )

        archive_result = _call_function_with_supported_kwargs(
            build_archive,
            normalized_payload,
            validate_before_write=True,
            include_documents=include_documents,
            prefer_cache=False,
        )
        filename, content, result = _normalize_archive_builder_result(
            archive_result
        )
        wrapped = _wrap_create_result(result, route=route)
        wrapped = _attach_vplib_uid_to_response(
            wrapped,
            payload=normalized_payload,
            result=result,
        )

        if not wrapped.ok:
            return RouteBinaryResponse(
                ok=False,
                status=wrapped.status,
                route=route,
                filename="invalid.vplib",
                content=b"",
                mimetype=DEFAULT_VPLIB_MIMETYPE,
                data={
                    **wrapped.data,
                    "download_source": "legacy_create_service",
                    "preflight": preflight_payload,
                    "payload_contract": _payload_contract_metadata(
                        normalized_payload
                    ),
                },
                errors=wrapped.errors,
                warnings=(
                    [workflow_warning, *wrapped.warnings]
                    if workflow_warning is not None
                    else wrapped.warnings
                ),
                info=wrapped.info,
                http_status=wrapped.http_status,
            )

        archive_metadata = validate_vplib_archive(content)
        warnings = list(wrapped.warnings)
        if workflow_warning is not None:
            warnings.insert(0, workflow_warning)

        return RouteBinaryResponse(
            ok=True,
            status="download_ready",
            route=route,
            filename=_safe_download_filename(filename),
            content=content,
            mimetype=DEFAULT_VPLIB_MIMETYPE,
            data={
                **wrapped.data,
                "download_source": "legacy_create_service",
                "archive": archive_metadata,
                "preflight": preflight_payload,
                "payload_contract": _payload_contract_metadata(
                    normalized_payload
                ),
            },
            errors=wrapped.errors,
            warnings=warnings,
            info=wrapped.info,
            http_status=200,
        )

    except CreateArchiveContractError as exc:
        issue = _error(
            exc.code,
            str(exc),
            field="download",
            details=exc.details,
        )
        return RouteBinaryResponse(
            ok=False,
            status=exc.code,
            route=route,
            filename="invalid.vplib",
            content=b"",
            data={
                "vplib_uid": _extract_vplib_uid_from_any(normalized_payload),
                "route_service": _route_service_metadata(
                    route,
                    normalized_payload,
                ),
                "preflight": preflight_payload,
                "payload_contract": _payload_contract_metadata(
                    normalized_payload
                ),
            },
            errors=[issue],
            warnings=(
                [workflow_warning]
                if workflow_warning is not None
                else preflight_warnings
            ),
            http_status=exc.http_status,
        )
    except Exception as exc:
        issue = _exception_issue(
            "download_failed",
            exc,
            field="download",
        )
        return RouteBinaryResponse(
            ok=False,
            status="download_failed",
            route=route,
            filename="invalid.vplib",
            content=b"",
            data={
                "vplib_uid": _extract_vplib_uid_from_any(normalized_payload),
                "route_service": _route_service_metadata(
                    route,
                    normalized_payload,
                ),
                "preflight": preflight_payload,
                "payload_contract": _payload_contract_metadata(
                    normalized_payload
                ),
            },
            errors=[issue],
            warnings=(
                [workflow_warning]
                if workflow_warning is not None
                else preflight_warnings
            ),
            http_status=500,
        )

def clear_cache_response() -> RouteResponse:
    """Clear create-route related caches."""
    warnings: list[RouteIssue | dict[str, Any]] = []
    info: list[RouteIssue | dict[str, Any]] = []
    cleared: dict[str, Any] = {
        "route_service": False,
        "generator_context_service": False,
        "generator_diagnostics_service": False,
        "generator_workflow_service": False,
        "create_service": False,
        "payload_normalizer": False,
        "taxonomy_service": False,
        "definition_catalog_service": False,
        "legacy_definitions": False,
    }

    try:
        clear_library_create_route_service_caches()
        cleared["route_service"] = True
    except Exception as exc:
        warnings.append(
            _exception_warning(
                "route_cache_clear_failed",
                exc,
                field="route_service.cache",
            )
        )

    cache_clear_specs = (
        (
            "generator_context_service",
            _is_generator_context_available,
            _generator_context_module,
            (
                "clear_library_generator_context_service_caches",
                "clear_generator_context_domain_caches",
                "clear_cache",
            ),
        ),
        (
            "generator_diagnostics_service",
            _is_generator_diagnostics_available,
            _generator_diagnostics_module,
            (
                "clear_library_generator_diagnostics_service_caches",
                "clear_cache",
            ),
        ),
        (
            "generator_workflow_service",
            _is_generator_workflow_available,
            _generator_workflow_module,
            (
                "clear_library_generator_workflow_service_caches",
                "clear_cache",
            ),
        ),
        (
            "create_service",
            _is_create_service_available,
            _create_service,
            (
                "clear_library_create_service_caches",
                "clear_cache",
            ),
        ),
        (
            "payload_normalizer",
            _is_variant_payload_service_available,
            _variant_payload_service,
            (
                "clear_library_create_variant_payload_service_caches",
                "clear_create_variant_payload_service_caches",
                "clear_cache",
            ),
        ),
        (
            "definition_catalog_service",
            _is_definition_catalog_available,
            _load_definition_catalog_service_module,
            (
                "clear_library_definition_catalog_service_caches",
                "clear_cache",
            ),
        ),
        (
            "legacy_definitions",
            _is_legacy_definitions_available,
            _load_legacy_definitions_module,
            (
                "clear_definitions_caches",
                "clear_cache",
            ),
        ),
    )

    for key, available_func, module_func, function_names in cache_clear_specs:
        if not available_func():
            continue

        try:
            module = module_func()
            called = False
            for function_name in function_names:
                function = getattr(module, function_name, None)
                if callable(function):
                    function()
                    called = True
                    break
            cleared[key] = True if called else cleared[key]
        except Exception as exc:
            warnings.append(
                _exception_warning(
                    f"{key}_cache_clear_failed",
                    exc,
                    field=f"{key}.cache",
                )
            )

    if _is_taxonomy_service_available():
        try:
            service = _get_taxonomy_service()
            for function_name in ("clear_cache", "clear_caches"):
                function = getattr(service, function_name, None)
                if callable(function):
                    function()
                    break
            cleared["taxonomy_service"] = True
        except Exception as exc:
            warnings.append(
                _exception_warning(
                    "taxonomy_cache_clear_failed",
                    exc,
                    field="library.taxonomy.cache",
                )
            )

    if warnings:
        status = "partial"
        ok = False
        http_status = 207
    else:
        status = "ok"
        ok = True
        http_status = 200

    info.append(
        _info(
            "cache_clear_completed",
            "Create route service cache clear completed.",
            details=cleared,
        )
    )

    return RouteResponse(
        ok=ok,
        status=status,
        route="cache-clear",
        data={
            "cleared": cleared,
            "message": "Create route service cache clear completed.",
        },
        warnings=warnings,
        info=info,
        http_status=http_status,
    )



def get_template_context_response(payload: Any = None, *, user_id: Any = 1) -> RouteResponse:
    """
    Build the Jinja context for ``templates/vplib/create.html``.

    This function is still route-adjacent and Flask-free. It prepares a
    generator-backed, JSON-safe template context so the Flask route can simply
    pass ``response.data`` into ``render_template`` without leaking Jinja
    Undefined objects, dataclasses, enums, bytes or arbitrary service objects
    into ``|tojson``.

    It intentionally includes ``null`` and ``undefined`` as ``None`` values so
    older JSON-like Jinja snippets that use ``null`` do not create a Jinja
    Undefined object.
    """
    route = "template-context"
    warnings: list[RouteIssue | dict[str, Any]] = []
    errors: list[RouteIssue | dict[str, Any]] = []
    info: list[RouteIssue | dict[str, Any]] = []

    normalized_payload = _safe_normalize_payload_for_response(payload or {"user_id": user_id}, route=route)
    if isinstance(normalized_payload, RouteResponse):
        return normalized_payload

    options_response = get_options_response(user_id=user_id)
    context_response = get_create_context_response(normalized_payload)
    health_response = get_route_service_health()

    warnings.extend(options_response.warnings)
    warnings.extend(context_response.warnings)
    warnings.extend(health_response.warnings)

    errors.extend(options_response.errors)
    errors.extend(context_response.errors)
    errors.extend(health_response.errors)

    info.extend(options_response.info)
    info.extend(context_response.info)
    info.extend(health_response.info)

    options_data = _json_safe_dict(options_response.data)
    context_data = _json_safe_dict(context_response.data)
    health_data = _json_safe_dict(health_response.data)

    generator_context = _first_mapping(
        context_data.get("generator_context"),
        context_data.get("window_payload"),
        _extract_nested(context_data, "data.generator_context", default={}),
        _extract_nested(options_data, "generator_context", default={}),
    )

    generator_context_data = _first_mapping(
        generator_context.get("data") if isinstance(generator_context, Mapping) else {},
        generator_context.get("payload") if isinstance(generator_context, Mapping) else {},
        generator_context,
    )

    definition_context = _first_mapping(
        context_data.get("definition_context"),
        generator_context_data.get("definition_context") if isinstance(generator_context_data, Mapping) else {},
        generator_context_data.get("definitions") if isinstance(generator_context_data, Mapping) else {},
        options_data.get("definitions"),
        {
            "options": options_data.get("definitions_options", {}),
            "records": options_data.get("definition_catalogs", {}),
            "counts": _extract_counts(options_data),
        },
    )

    taxonomy_context = _first_mapping(
        context_data.get("taxonomy_context"),
        generator_context_data.get("taxonomy_context") if isinstance(generator_context_data, Mapping) else {},
        generator_context_data.get("taxonomy") if isinstance(generator_context_data, Mapping) else {},
        options_data.get("taxonomy"),
    )

    upload_config = _first_mapping(
        context_data.get("upload_config"),
        generator_context_data.get("upload_config") if isinstance(generator_context_data, Mapping) else {},
        generator_context_data.get("uploads") if isinstance(generator_context_data, Mapping) else {},
        options_data.get("uploads"),
    )

    payload_contract = _first_mapping(
        context_data.get("payload_contract"),
        context_data.get("payloadContract"),
        generator_context_data.get("payload_contract") if isinstance(generator_context_data, Mapping) else {},
        generator_context_data.get("payloadContract") if isinstance(generator_context_data, Mapping) else {},
        options_data.get("payload_contract"),
        options_data.get("payloadContract"),
        {
            "schema_version": "create_payload.v1",
            "required_fields": ["family_name", "domain", "category", "subcategory", "object_kind"],
            "duplicate_formdata_guards": [
                "object_kind",
                "family_profile_id",
                "variant_profile_id",
                "definition_variants_json",
                "default_variant_id",
            ],
        },
    )

    definitions_options = _first_mapping(
        options_data.get("definitions_options"),
        definition_context.get("options") if isinstance(definition_context, Mapping) else {},
        _extract_definition_options(definition_context),
    )

    definition_catalogs = _first_mapping(
        options_data.get("definition_catalogs"),
        definition_context.get("records") if isinstance(definition_context, Mapping) else {},
        definition_context.get("catalogs") if isinstance(definition_context, Mapping) else {},
        definition_context.get("definitions") if isinstance(definition_context, Mapping) else {},
        _extract_definition_catalogs(definition_context),
    )

    template_context = {
        "null": None,
        "undefined": None,
        "_api_prefix": CREATE_API_PREFIX,
        "create_api_prefix": CREATE_API_PREFIX,
        "_definitions_api_prefix": "/api/v1/vplib/definitions",
        "definitions_api_prefix": "/api/v1/vplib/definitions",
        "_taxonomy_api_prefix": "/api/v1/vplib/taxonomy",
        "taxonomy_api_prefix": "/api/v1/vplib/taxonomy",
        "_files_api_prefix": "/api/v1/vplib/files",
        "files_api_prefix": "/api/v1/vplib/files",
        "_write_enabled": _safe_bool(options_data.get("write_enabled") or options_data.get("writeEnabled"), default=False),
        "_health_ok": bool(health_response.ok),
        "_source_root": options_data.get("source_root") or options_data.get("sourceRoot") or "",
        "_blueprint_version": LIBRARY_CREATE_ROUTE_SERVICE_VERSION,
        "_create_service_version": options_data.get("version") or LIBRARY_CREATE_ROUTE_SERVICE_VERSION,
        "_options": options_data,
        "create_options": options_data,
        "_health": health_data,
        "create_health": health_data,
        "create_context": context_data,
        "generator_context": generator_context,
        "definitions": definition_context,
        "definition_catalogs": definition_catalogs,
        "definitions_options": definitions_options,
        "taxonomy": taxonomy_context,
        "upload_config": upload_config,
        "payload_contract": payload_contract,
        "_domains": _coerce_list(options_data.get("domains")),
        "_categories": _coerce_list(options_data.get("categories")),
        "_subcategories": _coerce_list(options_data.get("subcategories")),
        "_object_kinds": _coerce_list(options_data.get("object_kinds") or definitions_options.get("object_kinds") if isinstance(definitions_options, Mapping) else []),
        "_primitive_shapes": _coerce_list(options_data.get("primitive_shapes")),
        "_units": _coerce_list(options_data.get("units") or definitions_options.get("units") if isinstance(definitions_options, Mapping) else []),
        "_material_classes": _coerce_list(options_data.get("material_classes") or options_data.get("materials") or definitions_options.get("materials") if isinstance(definitions_options, Mapping) else []),
        "create_steps": options_data.get("create_steps") or context_data.get("create_steps") or None,
        "create_initial_step": 1,
        "create_default_theme": "light",
        "create_theme_storage_key": "vectoplan.create.wizard.theme",
        "create_legacy_theme_storage_key": "vectoplan.create.theme",
        "route_service": _route_service_metadata(route, normalized_payload),
        "template_context_source": "library_create_route_service",
        "template_context_safe_json": True,
    }

    safe_context = sanitize_template_context(template_context)

    ok = options_response.ok and context_response.ok and len(errors) == 0
    status = "ok" if ok and not warnings else "partial" if ok else "template_context_partial"

    return RouteResponse(
        ok=ok or context_response.ok or options_response.ok,
        status=status,
        route=route,
        data=safe_context,
        errors=errors,
        warnings=warnings,
        info=info + [
            _info(
                "template_context_prepared",
                "JSON-safe generator-backed template context was prepared.",
                details={
                    "generator_context_available": bool(generator_context),
                    "definition_context_available": bool(definition_context),
                    "taxonomy_context_available": bool(taxonomy_context),
                    "upload_config_available": bool(upload_config),
                },
            )
        ],
        http_status=200 if (ok or context_response.ok or options_response.ok) else 500,
    )


# ---------------------------------------------------------------------------
# Public utility API
# ---------------------------------------------------------------------------

def normalize_payload(payload: Any) -> dict[str, Any]:
    """
    Normalize route payloads before passing them to workflow/create services.

    This function does not require Flask and accepts:
    - None
    - dict-like mappings
    - JSON strings
    - bytes containing JSON
    - MultiDict-like objects
    - dataclasses / objects with to_dict()
    """
    try:
        if payload is None:
            return {}

        if isinstance(payload, bytes):
            text = payload.decode("utf-8", errors="replace")
            return normalize_payload(text)

        if isinstance(payload, str):
            text = payload.strip()
            if not text:
                return {}
            decoded = json.loads(text)
            if not isinstance(decoded, Mapping):
                raise ValueError("JSON payload must be an object")
            return normalize_payload(decoded)

        if isinstance(payload, Mapping):
            return _normalize_mapping_payload(payload)

        if is_dataclass_like(payload):
            return _normalize_mapping_payload(_dataclass_like_to_dict(payload))

        if hasattr(payload, "to_dict") and callable(payload.to_dict):
            try:
                return normalize_payload(payload.to_dict(flat=False))
            except TypeError:
                return normalize_payload(payload.to_dict())

        if hasattr(payload, "items") and callable(payload.items):
            return _normalize_mapping_payload(dict(payload.items()))

        raise TypeError(f"Unsupported payload type: {type(payload).__name__}")
    except Exception as exc:
        raise ValueError(f"Could not normalize route payload: {exc}") from exc


def merge_payloads(*payloads: Any) -> dict[str, Any]:
    """Merge multiple payload sources. Later payloads override earlier payloads."""
    merged: dict[str, Any] = {}

    for payload in payloads:
        if payload is None:
            continue
        normalized = normalize_payload(payload)
        merged.update(normalized)

    return merged


def response_to_tuple(response: RouteResponse) -> tuple[dict[str, Any], int]:
    """Convenience helper for Flask adapters."""
    return response.to_dict(include_http_status=True), _safe_http_status(response.http_status)


def binary_response_to_meta_tuple(response: RouteBinaryResponse) -> tuple[dict[str, Any], int]:
    """Return metadata for a binary response as JSON."""
    return response.to_dict(include_http_status=True), _safe_http_status(response.http_status)


def sanitize_template_context(value: Any) -> dict[str, Any]:
    """Return a JSON-/Jinja-safe mapping for render_template(**context)."""
    return _json_safe_dict(value)


# Backward-compatible aliases.
health = get_route_service_health
options = get_options_response
create_context = get_create_context_response
template_context = get_template_context_response
definitions_current = get_current_definitions_response
draft = build_draft_response
validate = validate_draft_response
package_plan = build_package_plan_response
persistent_draft_payload = build_persistent_draft_payload_response
publish_bundle = build_publish_bundle_response
download = build_download_response
save = save_package_response
cache_clear = clear_cache_response


# ---------------------------------------------------------------------------
# Workflow integration helpers
# ---------------------------------------------------------------------------


def _workflow_route_response(
    *,
    action: str,
    route: str,
    payload: Mapping[str, Any],
    success_status: str,
    fallback_legacy_function: str | None = None,
    fallback_kwargs: Mapping[str, Any] | None = None,
    fallback_http_status: int = 500,
) -> RouteResponse:
    workflow_response: RouteResponse | None = None
    workflow_warning: RouteIssue | dict[str, Any] | None = None

    if _is_generator_workflow_available():
        try:
            workflow_payload = _run_workflow_payload(
                action=action,
                payload=payload,
                extra_request={
                    "prefer_cache": False,
                    "include_context": True,
                    "include_options": True,
                    "include_files": bool(
                        payload.get("files") or payload.get("uploads")
                    ),
                    "include_draft": bool(
                        payload.get("draft_ref") or payload.get("draft_uid")
                    ),
                    "include_published": bool(
                        payload.get("item_ref") or payload.get("vplib_uid")
                    ),
                    "include_documents": _resolve_include_documents(
                        payload,
                        requested=payload.get("include_documents"),
                    ),
                    "validate_before_write": True,
                },
            )

            workflow_response = _route_response_from_workflow_payload(
                workflow_payload,
                route=route,
                success_status=success_status,
            )
            workflow_response = _attach_vplib_uid_to_response(
                workflow_response,
                payload=payload,
                result=workflow_payload,
            )

            if workflow_response.ok:
                return workflow_response

            workflow_warning = _warning(
                "generator_workflow_not_ok",
                "Generator workflow returned a non-successful response. "
                "A compatible create-service fallback will be attempted.",
                field="generator_workflow",
                details=_compact_route_response(workflow_response),
            )
        except Exception as exc:
            workflow_warning = _exception_warning(
                "generator_workflow_failed",
                exc,
                field="generator_workflow",
                fallback_message=(
                    "Generator workflow failed. "
                    "A compatible create-service fallback will be attempted."
                ),
            )
    else:
        workflow_warning = _warning(
            "generator_workflow_unavailable",
            "Generator workflow service is unavailable. "
            "A compatible create-service fallback will be attempted.",
            field="generator_workflow",
            details=_safe_generator_workflow_health(),
        )

    if fallback_legacy_function:
        legacy_response = _legacy_create_action_response(
            route=route,
            function_name=fallback_legacy_function,
            payload=payload,
            kwargs=dict(fallback_kwargs or {}),
            fallback_http_status=fallback_http_status,
        )
        warnings = list(legacy_response.warnings)
        if workflow_warning is not None:
            warnings.insert(0, workflow_warning)

        data = {
            **legacy_response.data,
            "generator_workflow_fallback": True,
        }
        if workflow_response is not None:
            data["generator_workflow_response"] = _compact_route_response(
                workflow_response
            )

        return RouteResponse(
            ok=legacy_response.ok,
            status=legacy_response.status,
            route=legacy_response.route,
            data=data,
            errors=legacy_response.errors,
            warnings=warnings,
            info=legacy_response.info,
            http_status=legacy_response.http_status,
        )

    if workflow_response is not None:
        warnings = list(workflow_response.warnings)
        if workflow_warning is not None:
            warnings.insert(0, workflow_warning)
        return RouteResponse(
            ok=workflow_response.ok,
            status=workflow_response.status,
            route=workflow_response.route,
            data=workflow_response.data,
            errors=workflow_response.errors,
            warnings=warnings,
            info=workflow_response.info,
            http_status=workflow_response.http_status,
        )

    return RouteResponse(
        ok=False,
        status="generator_workflow_unavailable",
        route=route,
        data={
            "route_service": _route_service_metadata(route, payload),
            "generator_workflow": _safe_generator_workflow_health(),
        },
        errors=[
            _error(
                "generator_workflow_unavailable",
                "Generator workflow service is unavailable.",
                field="generator_workflow",
                details=_safe_generator_workflow_health(),
            )
        ],
        warnings=[workflow_warning] if workflow_warning is not None else [],
        http_status=503,
    )


def _run_workflow_payload(
    *,
    action: str,
    payload: Mapping[str, Any],
    extra_request: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    module = _generator_workflow_module()
    normalized_action = str(action or "").strip()
    payload_dict = dict(payload)
    correlation_id = str(
        payload_dict.get("correlation_id")
        or payload_dict.get("correlationId")
        or payload_dict.get("client_request_id")
        or payload_dict.get("clientRequestId")
        or payload_dict.get("_request_id")
        or uuid.uuid4()
    )

    request_payload = {
        "action": normalized_action,
        "payload": payload_dict,
        "save_source": _safe_bool(
            payload_dict.get("save_source"),
            default=normalized_action == "save",
        ),
        "sync_after_save": _safe_bool(
            payload_dict.get("sync_after_save"),
            default=normalized_action == "save",
        ),
        "user_id": payload_dict.get("user_id", 1),
        "inventory_key": payload_dict.get("inventory_key", "default"),
        "domain": payload_dict.get("domain"),
        "category": payload_dict.get("category"),
        "subcategory": payload_dict.get("subcategory"),
        "taxonomy_path": payload_dict.get("taxonomy_path"),
        "object_kind": payload_dict.get("object_kind"),
        "family_profile_id": payload_dict.get("family_profile_id"),
        "variant_profile_id": payload_dict.get("variant_profile_id"),
        "default_variant_id": payload_dict.get("default_variant_id"),
        "draft_ref": payload_dict.get("draft_ref") or payload_dict.get("draft_uid"),
        "item_ref": payload_dict.get("item_ref") or payload_dict.get("item_id"),
        "vplib_uid": _extract_vplib_uid_from_any(payload_dict),
        "correlation_id": correlation_id,
        "allow_source_write": _safe_bool(
            payload_dict.get("allow_source_write"),
            default=False,
        ),
        "allow_publish_write": _safe_bool(
            payload_dict.get("allow_publish_write"),
            default=False,
        ),
        "allow_draft_write": _safe_bool(
            payload_dict.get("allow_draft_write"),
            default=True,
        ),
        "dry_run": _safe_bool(payload_dict.get("dry_run"), default=False),
        "validate_before_write": _safe_bool(
            payload_dict.get("validate_before_write"),
            default=True,
        ),
        "include_documents": _resolve_include_documents(
            payload_dict,
            requested=payload_dict.get("include_documents"),
        ),
        "payload_fingerprint": _payload_fingerprint(payload_dict),
        **dict(extra_request or {}),
    }

    last_type_error: TypeError | None = None

    for function_name in (
        "run_generator_workflow_payload",
        "run_generator_workflow",
    ):
        function = getattr(module, function_name, None)
        if not callable(function):
            continue

        try:
            result = _call_function_with_supported_kwargs(
                function,
                request_payload,
            )
        except TypeError as exc:
            last_type_error = exc
            try:
                result = _call_function_with_supported_kwargs(
                    function,
                    **request_payload,
                )
            except TypeError:
                continue

        if hasattr(result, "to_dict") and callable(result.to_dict):
            for kwargs in (
                {"include_context": False, "include_payloads": True},
                {"include_payloads": True},
                {},
            ):
                try:
                    converted = result.to_dict(**kwargs)
                    if isinstance(converted, Mapping):
                        return dict(converted)
                except TypeError:
                    continue

        return _service_result_payload(result)

    service = _generator_workflow_service()
    for method_name in ("run_payload", "run"):
        method = getattr(service, method_name, None)
        if not callable(method):
            continue

        try:
            result = _call_function_with_supported_kwargs(
                method,
                request_payload,
            )
        except TypeError:
            result = _call_function_with_supported_kwargs(
                method,
                **request_payload,
            )

        if hasattr(result, "to_dict") and callable(result.to_dict):
            for kwargs in (
                {"include_context": False, "include_payloads": True},
                {"include_payloads": True},
                {},
            ):
                try:
                    converted = result.to_dict(**kwargs)
                    if isinstance(converted, Mapping):
                        return dict(converted)
                except TypeError:
                    continue
        return _service_result_payload(result)

    if last_type_error is not None:
        raise RuntimeError(
            "Generator workflow service exposes methods with an unsupported "
            f"signature: {last_type_error}"
        ) from last_type_error

    raise RuntimeError(
        "Generator workflow service exposes no known run method."
    )


def _route_response_from_workflow_payload(
    workflow_payload: Mapping[str, Any],
    *,
    route: str,
    success_status: str,
) -> RouteResponse:
    payload = dict(workflow_payload or {})
    workflow_status = str(
        payload.get("status")
        or payload.get("workflow_status")
        or ""
    ).strip()
    ok = _workflow_payload_ok(payload)

    data: dict[str, Any] = {
        "route_service": _route_service_metadata(route, payload),
        "workflow": payload,
        "workflow_status": workflow_status or ("ok" if ok else "error"),
        "workflow_action": payload.get("action"),
        "correlation_id": payload.get("correlation_id"),
    }

    for key in (
        "payload",
        "draft_payload",
        "validation_payload",
        "package_plan_payload",
        "download_payload",
        "save_payload",
        "persistent_draft_payload",
        "publish_prepare_payload",
        "publish_payload",
        "sync_payload",
    ):
        value = payload.get(key)
        if value not in (None, {}, []):
            data[key] = value

    primary = _first_non_empty(
        payload.get("payload"),
        payload.get("draft_payload"),
        payload.get("validation_payload"),
        payload.get("package_plan_payload"),
        payload.get("download_payload"),
        payload.get("save_payload"),
        payload.get("persistent_draft_payload"),
        payload.get("publish_prepare_payload"),
        payload.get("publish_payload"),
        payload.get("sync_payload"),
    )
    if isinstance(primary, Mapping):
        data.update(
            {
                key: value
                for key, value in primary.items()
                if key not in data
            }
        )

    uid = (
        _extract_vplib_uid_from_any(data)
        or _extract_vplib_uid_from_any(payload)
    )
    if uid:
        data[VPLIB_UID_FIELD] = uid

    errors, warnings, info = _issues_from_workflow_payload(payload)

    if not ok and not errors:
        errors.append(
            _error(
                "workflow_not_ok",
                "Generator workflow returned a non-OK response.",
                field=route,
                details={
                    "status": workflow_status,
                    "action": payload.get("action"),
                },
            ).to_dict()
        )

    http_status = _http_status_from_workflow_payload(payload, ok=ok)
    final_status = success_status if ok else (
        workflow_status or "workflow_not_ok"
    )

    return RouteResponse(
        ok=ok,
        status=final_status,
        route=route,
        data=data,
        errors=errors,
        warnings=warnings,
        info=info,
        http_status=http_status,
    )


def _http_status_from_workflow_payload(payload: Mapping[str, Any], *, ok: bool) -> int:
    explicit = payload.get("_http_status") or payload.get("http_status")
    if explicit is not None:
        return _safe_http_status(explicit)

    status = str(payload.get("status") or "").strip().lower()
    if status in WORKFLOW_INVALID_STATUSES:
        return 422
    if status in {"bad_request", "invalid_request"}:
        return 400
    if status in {"not_found"}:
        return 404
    if status in {"unavailable", "service_unavailable"}:
        return 503
    if status in {"skipped", "write_disabled", "forbidden"}:
        return 403

    return 200 if ok else 500

def _issues_from_workflow_payload(
    payload: Mapping[str, Any],
) -> tuple[list[dict[str, Any]], list[dict[str, Any]], list[dict[str, Any]]]:
    errors: list[dict[str, Any]] = []
    warnings: list[dict[str, Any]] = []
    info: list[dict[str, Any]] = []

    def add_issue(issue: Any) -> None:
        issue_payload = _issue_to_dict(issue)
        severity = str(issue_payload.get("severity") or "error").lower()

        if severity in {"fatal", "error", "blocking"}:
            errors.append(issue_payload)
        elif severity in {"warning", "warn"}:
            warnings.append(issue_payload)
        else:
            info.append(issue_payload)

    for issue in _coerce_list(payload.get("errors")):
        issue_payload = _issue_to_dict(issue)
        issue_payload["severity"] = "error"
        errors.append(issue_payload)

    for issue in _coerce_list(payload.get("warnings")):
        issue_payload = _issue_to_dict(issue)
        issue_payload["severity"] = "warning"
        warnings.append(issue_payload)

    for issue in _coerce_list(payload.get("info")):
        issue_payload = _issue_to_dict(issue)
        issue_payload["severity"] = "info"
        info.append(issue_payload)

    diagnostics = payload.get("diagnostics")
    if isinstance(diagnostics, Mapping):
        for issue in _coerce_list(diagnostics.get("issues")):
            add_issue(issue)

    for step in _coerce_list(payload.get("steps")):
        if not isinstance(step, Mapping):
            continue
        for issue in _coerce_list(step.get("issues")):
            add_issue(issue)

    return errors, warnings, info


# ---------------------------------------------------------------------------
# Legacy fallback helpers
# ---------------------------------------------------------------------------

def _legacy_options_response(*, user_id: Any = 1) -> RouteResponse:
    route = "options"

    if not _is_create_service_available():
        return _service_unavailable(route)

    try:
        result = _call_create_service_function(
            "get_create_options",
            include_definitions=True,
            user_id=user_id,
        )
        response = _wrap_create_result(result, route=route)
        response = _enrich_options_response_with_taxonomy(response)
        response = _enrich_options_response_with_definitions(response, user_id=user_id)

        data = dict(response.data)
        data.setdefault("vplib_uid", "")
        data.setdefault("vplib_uid_field", VPLIB_UID_FIELD)
        data.setdefault("create_payload_normalization", {})
        if isinstance(data["create_payload_normalization"], Mapping):
            data["create_payload_normalization"] = {
                **dict(data["create_payload_normalization"]),
                "enabled": _is_variant_payload_service_available(),
                "vplib_uid_field": VPLIB_UID_FIELD,
                "uid_created_by": "library_create_variant_payload_service_or_route_fallback",
                "uid_persisted_in": "vplib.manifest.json",
                "existing_valid_uid_is_preserved": True,
                "invalid_uid_is_rejected": True,
            }

        return RouteResponse(
            ok=response.ok,
            status=response.status,
            route=response.route,
            data=data,
            errors=response.errors,
            warnings=response.warnings,
            info=response.info,
            http_status=response.http_status,
        )

    except Exception as exc:
        return _failure(
            route=route,
            code="options_failed",
            message="Create options could not be loaded.",
            exc=exc,
            http_status=500,
        )


def _legacy_create_context_response(payload: Any = None) -> RouteResponse:
    route = "create-context"

    try:
        normalized_payload = normalize_payload(payload)

        if _is_create_service_available():
            create_method = getattr(_create_service(), "get_create_context", None)
            if callable(create_method):
                result = _call_function_flex(create_method, normalized_payload)
                response = _wrap_create_result(result, route=route)
                return _attach_vplib_uid_to_response(response, payload=normalized_payload, result=result)

        if not _is_definition_catalog_available():
            return RouteResponse(
                ok=False,
                status="definitions_unavailable",
                route=route,
                data={
                    "route_service": _route_service_metadata(route, normalized_payload),
                    "definitions": _safe_definitions_health(),
                },
                errors=[
                    _error(
                        "definitions_unavailable",
                        "Definition Catalog service is unavailable for Create Context.",
                        field="definitions",
                        details=_safe_definitions_health(),
                    )
                ],
                http_status=503,
            )

        service = _definition_catalog_service()
        method = getattr(service, "get_create_context", None)
        if not callable(method):
            raise RuntimeError("Definition Catalog service exposes no get_create_context method.")

        result = _call_function_flex(method, normalized_payload)
        result_payload = _service_result_payload(result)

        ok = bool(result_payload.get("ok", True))
        status = str(result_payload.get("status") or ("ok" if ok else "invalid_request"))

        return RouteResponse(
            ok=ok,
            status=status,
            route=route,
            data={
                "route_service": _route_service_metadata(route, normalized_payload),
                "definition_context": result_payload,
            },
            errors=_coerce_issue_list(result_payload.get("errors", [])),
            warnings=_coerce_issue_list(result_payload.get("warnings", [])),
            info=_coerce_issue_list(result_payload.get("info", [])),
            http_status=200 if ok else 422,
        )
    except Exception as exc:
        return _failure(
            route=route,
            code="create_context_failed",
            message="Create Context could not be built.",
            exc=exc,
            http_status=500,
        )


def _legacy_create_action_response(
    *,
    route: str,
    function_name: str,
    payload: Mapping[str, Any],
    kwargs: Mapping[str, Any] | None = None,
    fallback_http_status: int = 500,
) -> RouteResponse:
    if not _is_create_service_available():
        return _service_unavailable(route)

    try:
        result = _call_create_service_function(
            function_name,
            payload,
            **dict(kwargs or {}),
        )
        response = _wrap_create_result(result, route=route)
        return _attach_vplib_uid_to_response(response, payload=payload, result=result)
    except Exception as exc:
        return _failure(
            route=route,
            code=f"{route.replace('-', '_')}_failed",
            message=f"Create action failed: {route}",
            exc=exc,
            http_status=fallback_http_status,
        )


# ---------------------------------------------------------------------------
# Canonical create/starter contract
# ---------------------------------------------------------------------------

def _unwrap_normalizer_result(value: Any) -> tuple[Mapping[str, Any], dict[str, Any]]:
    payload = _service_result_payload(value)
    if not isinstance(payload, Mapping):
        raise TypeError("Normalizer result is not a mapping.")

    data = dict(payload)
    report: dict[str, Any] = {}

    for report_key in (
        "report",
        "normalization_report",
        "normalizationReport",
        "diagnostics",
    ):
        if isinstance(data.get(report_key), Mapping):
            report[report_key] = _json_safe(dict(data[report_key]))

    for payload_key in (
        "normalized_payload",
        "normalizedPayload",
        "payload",
        "data",
        "result",
    ):
        candidate = data.get(payload_key)
        if not isinstance(candidate, Mapping):
            continue

        candidate_dict = dict(candidate)
        if payload_key == "data":
            nested = (
                candidate_dict.get("normalized_payload")
                or candidate_dict.get("normalizedPayload")
                or candidate_dict.get("payload")
            )
            if isinstance(nested, Mapping):
                return dict(nested), report

        if _looks_like_create_payload(candidate_dict):
            return candidate_dict, report

    return data, report


def _looks_like_create_payload(value: Mapping[str, Any]) -> bool:
    keys = {
        "object_kind",
        "objectKind",
        "family_name",
        "familyName",
        "family_profile_id",
        "familyProfileId",
        "variant_profile_id",
        "variantProfileId",
        "definition_variants",
        "definitionVariants",
        "definition_variants_json",
        "definitionVariantsJson",
        "domain",
        "category",
        "subcategory",
    }
    return any(key in value for key in keys)


def _normalize_create_contract_payload(
    payload: Mapping[str, Any],
    *,
    route: str,
) -> dict[str, Any]:
    data = _json_safe_dict(payload)
    _decode_create_json_fields(data)
    _normalize_scalar_aliases(data)

    object_kind = _normalize_slug_fallback(
        _first_non_empty(
            data.get("object_kind"),
            data.get("objectKind"),
            data.get("object_class"),
        ),
        default=STARTER_OBJECT_KIND,
    )
    family_profile_id = _clean_identifier(
        _first_non_empty(
            data.get("family_profile_id"),
            data.get("familyProfileId"),
        )
    )
    variant_profile_id = _clean_identifier(
        _first_non_empty(
            data.get("variant_profile_id"),
            data.get("variantProfileId"),
        )
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
    data["family_profile_id"] = family_profile_id
    data["familyProfileId"] = family_profile_id
    data["variant_profile_id"] = variant_profile_id
    data["variantProfileId"] = variant_profile_id

    for key, default_value in STARTER_TAXONOMY.items():
        data[key] = _normalize_slug_fallback(
            data.get(key),
            default=default_value,
        )

    taxonomy_path = _normalize_taxonomy_path(
        _first_non_empty(
            data.get("taxonomy_path"),
            data.get("taxonomyPath"),
            "/".join(data[key] for key in ("domain", "category", "subcategory")),
        )
    )
    data["taxonomy_path"] = taxonomy_path
    data["taxonomyPath"] = taxonomy_path

    if starter_requested:
        _materialize_starter_payload(data)

    data["_create_route_service_route"] = route
    data["_create_route_service_version"] = LIBRARY_CREATE_ROUTE_SERVICE_VERSION
    data["_starter_contract"] = {
        "requested": starter_requested,
        "object_kind": object_kind,
        "family_profile_id": family_profile_id,
        "variant_profile_id": variant_profile_id,
        "default_variant_id": data.get("default_variant_id"),
        "documents_required": False if starter_requested else None,
        "dimensions_mm": (
            {
                "width": _extract_dimension_value(data, "width"),
                "height": _extract_dimension_value(data, "height"),
                "depth": _extract_dimension_value(data, "depth"),
            }
            if starter_requested
            else {}
        ),
    }
    return data


def _materialize_starter_payload(data: dict[str, Any]) -> None:
    data["object_kind"] = STARTER_OBJECT_KIND
    data["objectKind"] = STARTER_OBJECT_KIND
    data["family_profile_id"] = STARTER_FAMILY_PROFILE_ID
    data["familyProfileId"] = STARTER_FAMILY_PROFILE_ID
    data["variant_profile_id"] = STARTER_VARIANT_PROFILE_ID
    data["variantProfileId"] = STARTER_VARIANT_PROFILE_ID

    family_name = str(
        _first_non_empty(
            data.get("family_name"),
            data.get("familyName"),
            "Simple Cell Block",
        )
    ).strip()
    data["family_name"] = family_name
    data["familyName"] = family_name

    primitive_shape = str(
        _first_non_empty(
            data.get("primitive_shape"),
            data.get("primitiveShape"),
            "block",
        )
    ).strip()
    data["primitive_shape"] = primitive_shape
    data["primitiveShape"] = primitive_shape

    geometry_unit = str(
        _first_non_empty(
            data.get("geometry_unit"),
            data.get("geometryUnit"),
            "m",
        )
    ).strip().lower()
    if geometry_unit not in {"m", "mm", "cm"}:
        geometry_unit = "m"

    geometry_values: dict[str, str] = {}
    dimension_values: dict[str, int] = {}
    for axis in ("width", "height", "depth"):
        snake = f"geometry_{axis}"
        camel = f"geometry{axis.title()}"
        raw_value = _first_non_empty(data.get(snake), data.get(camel), "1.00")
        numeric = _positive_float(raw_value, default=1.0)
        geometry_values[snake] = _format_decimal(numeric)
        dimension_values[f"dimensions.{axis}_mm"] = _geometry_to_mm(
            numeric,
            geometry_unit,
        )

    data.update(geometry_values)
    data["geometryWidth"] = data["geometry_width"]
    data["geometryHeight"] = data["geometry_height"]
    data["geometryDepth"] = data["geometry_depth"]
    data["geometry_unit"] = geometry_unit
    data["geometryUnit"] = geometry_unit

    dimensions = _json_object(data.get("dimensions"))
    dimensions["width_mm"] = dimension_values["dimensions.width_mm"]
    dimensions["height_mm"] = dimension_values["dimensions.height_mm"]
    dimensions["depth_mm"] = dimension_values["dimensions.depth_mm"]
    data["dimensions"] = dimensions

    for axis in ("x", "y", "z"):
        snake = f"editor_cells_{axis}"
        camel = f"editorCells{axis.upper()}"
        value = max(1, _safe_int(_first_non_empty(data.get(snake), data.get(camel), 1), default=1))
        data[snake] = str(value)
        data[camel] = str(value)

    variants = _json_list(
        _first_non_empty(
            data.get("definition_variants"),
            data.get("definitionVariants"),
            data.get("definition_variants_json"),
            data.get("definitionVariantsJson"),
        )
    )
    normalized_variants: list[dict[str, Any]] = []
    for index, raw_variant in enumerate(variants):
        variant = _json_object(raw_variant)
        if not variant:
            continue

        variant_id = _normalize_slug_fallback(
            _first_non_empty(
                variant.get("variant_id"),
                variant.get("variantId"),
                variant.get("id"),
            ),
            default=(
                STARTER_DEFAULT_VARIANT_ID
                if index == 0
                else f"variant_{index + 1}"
            ),
        )
        label = str(
            _first_non_empty(
                variant.get("label"),
                variant.get("name"),
                variant.get("title"),
                (
                    STARTER_DEFAULT_LABEL
                    if index == 0
                    else f"Variante {index + 1}"
                ),
            )
        ).strip()

        definition_values = _json_object(
            _first_non_empty(
                variant.get("definition_values"),
                variant.get("definitionValues"),
                variant.get("values"),
                variant.get("definition_values_json"),
                variant.get("definitionValuesJson"),
            )
        )
        definition_values.setdefault("variant.variant_id", variant_id)
        definition_values.setdefault("variant.label", label)
        for key, value in dimension_values.items():
            definition_values.setdefault(key, value)

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
                "definition_values_json": _compact_json(definition_values),
                "definitionValuesJson": _compact_json(definition_values),
                "additional_field_keys": _coerce_list(
                    variant.get("additional_field_keys")
                    or variant.get("additionalFieldKeys")
                ),
                "additionalFieldKeys": _coerce_list(
                    variant.get("additional_field_keys")
                    or variant.get("additionalFieldKeys")
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
                "definition_values_json": _compact_json(definition_values),
                "definitionValuesJson": _compact_json(definition_values),
                "additional_field_keys": [],
                "additionalFieldKeys": [],
                "source": "library_create_route_service.starter_default",
            }
        ]

    default_index = next(
        (
            index
            for index, variant in enumerate(normalized_variants)
            if _safe_bool(
                _first_non_empty(
                    variant.get("is_default"),
                    variant.get("isDefault"),
                ),
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
    variants_json = _compact_json(normalized_variants)
    data["definition_variants_json"] = variants_json
    data["definitionVariantsJson"] = variants_json
    data["default_variant_id"] = default_variant_id
    data["defaultVariantId"] = default_variant_id

    for kind, snake, camel in (
        ("geometry_model", "geometry_model_uploads", "geometryModelUploads"),
        (
            "technical_documents",
            "technical_document_uploads",
            "technicalDocumentUploads",
        ),
        (
            "variant_documents",
            "variant_document_uploads",
            "variantDocumentUploads",
        ),
    ):
        value = _json_object(
            _first_non_empty(
                data.get(snake),
                data.get(camel),
                data.get(f"{snake}_json"),
                data.get(f"{camel}Json"),
            )
        )
        if not value:
            value = _empty_upload_contract(kind)
        value.setdefault("required", False)
        value.setdefault("minimum_count", 0)
        data[snake] = value
        data[camel] = value
        data[f"{snake}_json"] = _compact_json(value)
        data[f"{camel}Json"] = data[f"{snake}_json"]

    data.setdefault("uploads", {
        "geometry_model": data["geometry_model_uploads"],
        "technical_documents": data["technical_document_uploads"],
        "variant_documents": data["variant_document_uploads"],
    })
    data.setdefault("assets", [])
    data.setdefault("documents", [])
    data["include_documents"] = _safe_bool(
        data.get("include_documents"),
        default=False,
    )
    data["includeDocuments"] = data["include_documents"]
    data["documents_required"] = False
    data["documentsRequired"] = False
    data["allow_empty_documents"] = True
    data["allowEmptyDocuments"] = True
    data["validate_before_write"] = True


def _decode_create_json_fields(data: dict[str, Any]) -> None:
    json_fields = (
        "definition_variants_json",
        "definitionVariantsJson",
        "geometry_model_uploads_json",
        "geometryModelUploadsJson",
        "spatial_contract_json",
        "spatialContractJson",
        "connection_points_json",
        "connectionPointsJson",
        "manufacturer_profile_json",
        "manufacturerProfileJson",
        "manufacturer_locations_json",
        "manufacturerLocationsJson",
        "manufacturer_territories_json",
        "manufacturerTerritoriesJson",
        "technical_document_uploads_json",
        "technicalDocumentUploadsJson",
        "variant_document_uploads_json",
        "variantDocumentUploadsJson",
        "uploads_json",
        "uploadsJson",
    )
    for key in json_fields:
        value = data.get(key)
        if not isinstance(value, str) or not value.strip():
            continue
        try:
            decoded = json.loads(value)
        except (TypeError, ValueError, json.JSONDecodeError):
            continue

        if key in {"definition_variants_json", "definitionVariantsJson"}:
            if isinstance(decoded, list):
                data.setdefault("definition_variants", decoded)
                data.setdefault("definitionVariants", decoded)
        elif key in {"connection_points_json", "connectionPointsJson"}:
            if isinstance(decoded, list):
                data.setdefault("connection_points", decoded)
                data.setdefault("connectionPoints", decoded)
        elif key in {"manufacturer_locations_json", "manufacturerLocationsJson"}:
            if isinstance(decoded, list):
                data.setdefault("manufacturer_locations", decoded)
                data.setdefault("manufacturerLocations", decoded)
        elif key in {"manufacturer_territories_json", "manufacturerTerritoriesJson"}:
            if isinstance(decoded, list):
                data.setdefault("manufacturer_territories", decoded)
                data.setdefault("manufacturerTerritories", decoded)
        elif isinstance(decoded, Mapping):
            if key.startswith("geometry_"):
                data.setdefault("geometry_model_uploads", dict(decoded))
            elif key.startswith("spatial"):
                data.setdefault("spatial_contract", dict(decoded))
                data.setdefault("spatialContract", dict(decoded))
            elif key.startswith("manufacturer_profile") or key.startswith("manufacturerProfile"):
                data.setdefault("manufacturer_profile", dict(decoded))
                data.setdefault("manufacturerProfile", dict(decoded))
            elif key.startswith("technical_"):
                data.setdefault("technical_document_uploads", dict(decoded))
            elif key.startswith("variant_"):
                data.setdefault("variant_document_uploads", dict(decoded))
            elif key.startswith("uploads"):
                data.setdefault("uploads", dict(decoded))


def _normalize_scalar_aliases(data: dict[str, Any]) -> None:
    aliases = (
        ("family_name", "familyName"),
        ("family_description", "familyDescription"),
        ("manufacturer_scope", "manufacturerScope"),
        ("manufacturer_coverage_mode", "manufacturerCoverageMode"),
        ("manufacturer_name", "manufacturerName"),
        ("manufacturer_brand", "manufacturerBrand"),
        ("manufacturer_org_id", "manufacturerOrgId"),
        ("manufacturer_website", "manufacturerWebsite"),
        ("manufacturer_country_code", "manufacturerCountryCode"),
        ("object_kind", "objectKind"),
        ("family_profile_id", "familyProfileId"),
        ("variant_profile_id", "variantProfileId"),
        ("default_variant_id", "defaultVariantId"),
        ("taxonomy_path", "taxonomyPath"),
        ("geometry_width", "geometryWidth"),
        ("geometry_height", "geometryHeight"),
        ("geometry_depth", "geometryDepth"),
        ("geometry_unit", "geometryUnit"),
        ("primitive_shape", "primitiveShape"),
    )
    for snake, camel in aliases:
        value = _first_non_empty(data.get(snake), data.get(camel))
        if value is None:
            continue
        if isinstance(value, (list, tuple)):
            value = next(
                (
                    item
                    for item in reversed(value)
                    if item not in (None, "")
                ),
                "",
            )
        data[snake] = value
        data[camel] = value


def _validate_starter_contract_response(
    payload: Mapping[str, Any],
    *,
    route: str,
) -> RouteResponse | None:
    starter = payload.get("_starter_contract")
    if not isinstance(starter, Mapping) or not _safe_bool(
        starter.get("requested"),
        default=False,
    ):
        return None

    issues: list[RouteIssue] = []
    expected_scalars = {
        "object_kind": STARTER_OBJECT_KIND,
        "family_profile_id": STARTER_FAMILY_PROFILE_ID,
        "variant_profile_id": STARTER_VARIANT_PROFILE_ID,
        "default_variant_id": STARTER_DEFAULT_VARIANT_ID,
    }
    for field_name, expected in expected_scalars.items():
        actual = payload.get(field_name)
        if actual != expected:
            issues.append(
                _error(
                    "starter_contract_mismatch",
                    f"Starter field {field_name!r} must equal {expected!r}.",
                    field=field_name,
                    details={"expected": expected, "actual": actual},
                )
            )

    variants = _json_list(
        _first_non_empty(
            payload.get("definition_variants"),
            payload.get("definitionVariants"),
            payload.get("definition_variants_json"),
            payload.get("definitionVariantsJson"),
        )
    )
    if not variants:
        issues.append(
            _error(
                "starter_variant_missing",
                "The starter payload must contain one default variant.",
                field="definition_variants",
            )
        )
    else:
        default_variant = next(
            (
                _json_object(variant)
                for variant in variants
                if _safe_bool(
                    _first_non_empty(
                        _json_object(variant).get("is_default"),
                        _json_object(variant).get("isDefault"),
                    ),
                    default=False,
                )
            ),
            _json_object(variants[0]),
        )
        values = _json_object(
            _first_non_empty(
                default_variant.get("definition_values"),
                default_variant.get("definitionValues"),
                default_variant.get("definition_values_json"),
                default_variant.get("definitionValuesJson"),
            )
        )
        for key in STARTER_REQUIRED_VALUE_KEYS:
            if key not in values:
                issues.append(
                    _error(
                        "starter_default_missing",
                        f"Starter default value is missing: {key}",
                        field=key,
                    )
                )

        for key in STARTER_DIMENSIONS_MM:
            if _positive_float(values.get(key), default=None) is None:
                issues.append(
                    _error(
                        "starter_dimension_invalid",
                        f"Starter dimension must be greater than zero: {key}",
                        field=key,
                        details={"actual": values.get(key)},
                    )
                )

    if not issues:
        return None

    return RouteResponse(
        ok=False,
        status="starter_payload_invalid",
        route=route,
        data={
            "route_service": _route_service_metadata(route, payload),
            "starter_contract": _json_safe(starter),
            "payload_contract": _payload_contract_metadata(payload),
        },
        errors=issues,
        http_status=422,
    )


def _resolve_include_documents(
    payload: Mapping[str, Any],
    *,
    requested: Any = None,
) -> bool:
    starter = payload.get("_starter_contract")
    if isinstance(starter, Mapping) and _safe_bool(
        starter.get("requested"),
        default=False,
    ):
        if requested is not None and _safe_bool(requested, default=False):
            documents = _coerce_list(payload.get("documents"))
            document_uploads = _json_object(
                payload.get("technical_document_uploads")
            )
            variant_uploads = _json_object(
                payload.get("variant_document_uploads")
            )
            has_documents = bool(
                documents
                or document_uploads.get("files")
                or variant_uploads.get("files")
            )
            return has_documents
        return False

    if requested is not None:
        return _safe_bool(requested, default=True)
    return _safe_bool(payload.get("include_documents"), default=True)


def _download_preflight_failure(
    response: RouteResponse,
    payload: Mapping[str, Any],
    *,
    stage: str,
) -> RouteResponse:
    return RouteResponse(
        ok=False,
        status=f"download_preflight_{stage}_failed",
        route="download",
        data={
            "route_service": _route_service_metadata("download", payload),
            "preflight_stage": stage,
            "preflight_response": _compact_route_response(response),
            "payload_contract": _payload_contract_metadata(payload),
        },
        errors=response.errors
        or [
            _error(
                f"download_preflight_{stage}_failed",
                f"Download preflight failed during {stage}.",
                field=stage,
            )
        ],
        warnings=response.warnings,
        info=response.info,
        http_status=response.http_status if response.http_status >= 400 else 422,
    )


def _attach_action_contract_to_response(
    response: RouteResponse,
    payload: Mapping[str, Any],
    *,
    action: str,
    extra: Mapping[str, Any] | None = None,
) -> RouteResponse:
    data = dict(response.data)
    data["payload_contract"] = _payload_contract_metadata(payload)
    data["normalized_payload_fingerprint"] = _payload_fingerprint(payload)
    data["action"] = action
    if extra:
        data.update(_json_safe_dict(extra))

    return RouteResponse(
        ok=response.ok,
        status=response.status,
        route=response.route,
        data=data,
        errors=response.errors,
        warnings=response.warnings,
        info=response.info,
        http_status=response.http_status,
    )


def _payload_contract_metadata(payload: Mapping[str, Any]) -> dict[str, Any]:
    starter = payload.get("_starter_contract")
    return {
        "schema_version": "create_route_payload.v2",
        "service_version": LIBRARY_CREATE_ROUTE_SERVICE_VERSION,
        "vplib_uid": _extract_vplib_uid_from_any(payload),
        "payload_fingerprint": _payload_fingerprint(payload),
        "object_kind": payload.get("object_kind"),
        "family_profile_id": payload.get("family_profile_id"),
        "variant_profile_id": payload.get("variant_profile_id"),
        "default_variant_id": payload.get("default_variant_id"),
        "starter": _json_safe(starter) if isinstance(starter, Mapping) else {},
        "include_documents": _resolve_include_documents(
            payload,
            requested=payload.get("include_documents"),
        ),
    }


def _compact_route_response(response: RouteResponse) -> dict[str, Any]:
    return {
        "ok": response.ok,
        "status": response.status,
        "route": response.route,
        "http_status": response.http_status,
        "errors": [_issue_to_dict(issue) for issue in response.errors],
        "warnings": [_issue_to_dict(issue) for issue in response.warnings],
        "vplib_uid": _extract_vplib_uid_from_any(response.data),
    }


def _workflow_payload_ok(payload: Mapping[str, Any]) -> bool:
    if "ok" in payload:
        return _safe_bool(payload.get("ok"), default=False)
    if "success" in payload:
        return _safe_bool(payload.get("success"), default=False)
    if "valid" in payload and str(payload.get("status") or "").lower() in {
        "",
        "valid",
        "ok",
        "ready",
    }:
        return _safe_bool(payload.get("valid"), default=False)

    status = str(
        payload.get("status")
        or payload.get("workflow_status")
        or ""
    ).strip().lower()
    if status in WORKFLOW_SUCCESS_STATUSES:
        return True
    if status in WORKFLOW_INVALID_STATUSES:
        return False

    for key in (
        "payload",
        "result",
        "data",
        "validation_payload",
        "package_plan_payload",
        "download_payload",
    ):
        nested = payload.get(key)
        if isinstance(nested, Mapping):
            if "ok" in nested:
                return _safe_bool(nested.get("ok"), default=False)
            nested_status = str(nested.get("status") or "").strip().lower()
            if nested_status in WORKFLOW_SUCCESS_STATUSES:
                return True

    return False


def _normalize_archive_builder_result(
    result: Any,
) -> tuple[str, bytes, Any]:
    if isinstance(result, tuple):
        if len(result) >= 3:
            filename, content, metadata = result[0], result[1], result[2]
        elif len(result) == 2:
            filename, content = result
            metadata = {
                "ok": True,
                "status": "archive_ready",
                "data": {},
            }
        else:
            raise CreateArchiveContractError(
                "Archive builder returned an empty tuple.",
                code="archive_builder_result_invalid",
                http_status=500,
            )
    elif isinstance(result, Mapping):
        filename = (
            result.get("filename")
            or result.get("download_filename")
            or "package.vplib"
        )
        content = (
            result.get("content")
            or result.get("bytes")
            or result.get("archive_bytes")
            or result.get("binary")
        )
        metadata = result.get("result") or result
    else:
        filename = getattr(result, "filename", "package.vplib")
        content = (
            getattr(result, "content", None)
            or getattr(result, "bytes", None)
            or getattr(result, "archive_bytes", None)
        )
        metadata = getattr(result, "result", result)

    binary = _coerce_binary_content(content)
    if binary is None:
        raise CreateArchiveContractError(
            "Archive builder returned no binary content.",
            code="archive_content_missing",
            http_status=500,
            details={"result_type": type(result).__name__},
        )
    return str(filename), binary, metadata


def _coerce_binary_content(value: Any, *, key_hint: str = "") -> bytes | None:
    if value is None:
        return None
    if isinstance(value, bytes):
        content = value
    elif isinstance(value, bytearray):
        content = bytes(value)
    elif isinstance(value, memoryview):
        content = value.tobytes()
    elif isinstance(value, io.BytesIO):
        content = value.getvalue()
    elif hasattr(value, "read") and callable(value.read):
        position = None
        try:
            if hasattr(value, "tell") and callable(value.tell):
                position = value.tell()
            content = value.read()
            if position is not None and hasattr(value, "seek") and callable(value.seek):
                value.seek(position)
        except Exception as exc:
            raise CreateArchiveContractError(
                "Binary archive stream could not be read.",
                code="archive_stream_read_failed",
                http_status=500,
                details={"exception_type": type(exc).__name__},
            ) from exc
        return _coerce_binary_content(content)
    elif isinstance(value, str):
        text = value.strip()
        if text.startswith("data:") and "," in text:
            text = text.split(",", 1)[1]
        is_base64_hint = "base64" in key_hint.lower()
        if not is_base64_hint and not text.startswith("UEs"):
            return None
        try:
            content = base64.b64decode(text, validate=True)
        except (ValueError, binascii.Error) as exc:
            raise CreateArchiveContractError(
                "Base64 archive content is invalid.",
                code="archive_base64_invalid",
                http_status=500,
            ) from exc
    else:
        return None

    if len(content) > _configured_int(
        "VECTOPLAN_CREATE_MAX_ARCHIVE_BYTES",
        DEFAULT_MAX_ARCHIVE_BYTES,
        minimum=1024,
    ):
        raise CreateArchiveContractError(
            "Generated archive exceeds the configured size limit.",
            code="archive_size_limit_exceeded",
            http_status=500,
            details={"size_bytes": len(content)},
        )
    return content


def validate_vplib_archive(content: Any) -> dict[str, Any]:
    binary = _coerce_binary_content(content)
    if binary is None:
        raise CreateArchiveContractError(
            "Generated VPLIB archive has no binary content.",
            code="archive_content_missing",
            http_status=500,
        )
    if not binary:
        raise CreateArchiveContractError(
            "Generated VPLIB archive is empty.",
            code="archive_empty",
            http_status=500,
        )
    if not binary.startswith(VPLIB_ZIP_SIGNATURES):
        raise CreateArchiveContractError(
            "Generated VPLIB content does not have a ZIP signature.",
            code="archive_signature_invalid",
            http_status=500,
        )
    if not zipfile.is_zipfile(io.BytesIO(binary)):
        raise CreateArchiveContractError(
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
            os.getenv(
                "VECTOPLAN_CREATE_MAX_COMPRESSION_RATIO",
                str(DEFAULT_MAX_COMPRESSION_RATIO),
            )
        )
    except Exception:
        max_ratio = DEFAULT_MAX_COMPRESSION_RATIO

    try:
        with zipfile.ZipFile(io.BytesIO(binary), "r") as archive:
            members = archive.infolist()
            if not members:
                raise CreateArchiveContractError(
                    "Generated VPLIB archive contains no files.",
                    code="archive_has_no_entries",
                    http_status=500,
                )
            if len(members) > max_entries:
                raise CreateArchiveContractError(
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
                name = _safe_archive_member_name(member.filename)
                names.append(name)

                if member.flag_bits & 0x1:
                    raise CreateArchiveContractError(
                        "Generated VPLIB archive contains encrypted entries.",
                        code="archive_encrypted_entry",
                        http_status=500,
                        details={"member": name},
                    )

                total_uncompressed += int(member.file_size or 0)
                total_compressed += int(member.compress_size or 0)
                if total_uncompressed > max_uncompressed:
                    raise CreateArchiveContractError(
                        "Generated VPLIB archive exceeds the uncompressed size limit.",
                        code="archive_uncompressed_limit_exceeded",
                        http_status=500,
                        details={
                            "uncompressed_bytes": total_uncompressed,
                            "max_uncompressed_bytes": max_uncompressed,
                        },
                    )

                if member.file_size and member.compress_size == 0:
                    raise CreateArchiveContractError(
                        "Generated VPLIB archive contains an invalid compressed entry.",
                        code="archive_compression_invalid",
                        http_status=500,
                        details={"member": name},
                    )
                if member.file_size and member.compress_size:
                    ratio = float(member.file_size) / float(member.compress_size)
                    if ratio > max_ratio:
                        raise CreateArchiveContractError(
                            "Generated VPLIB archive contains a suspicious compression ratio.",
                            code="archive_compression_ratio_exceeded",
                            http_status=500,
                            details={
                                "member": name,
                                "ratio": ratio,
                                "max_ratio": max_ratio,
                            },
                        )

            corrupt_member = archive.testzip()
            if corrupt_member:
                raise CreateArchiveContractError(
                    "Generated VPLIB archive failed CRC validation.",
                    code="archive_crc_failed",
                    http_status=500,
                    details={"member": corrupt_member},
                )
    except CreateArchiveContractError:
        raise
    except (OSError, zipfile.BadZipFile, zipfile.LargeZipFile) as exc:
        raise CreateArchiveContractError(
            "Generated VPLIB archive could not be inspected.",
            code="archive_inspection_failed",
            http_status=500,
            details={"exception_type": type(exc).__name__},
        ) from exc

    return {
        "ok": True,
        "sha256": hashlib.sha256(binary).hexdigest(),
        "size_bytes": len(binary),
        "entry_count": len(members),
        "uncompressed_bytes": total_uncompressed,
        "compressed_bytes": total_compressed,
        "members": names[:64],
        "has_manifest": any(
            posixpath.basename(name).lower()
            in {"vplib.manifest.json", "manifest.json"}
            for name in names
        ),
    }


def _safe_archive_member_name(value: Any) -> str:
    raw = str(value or "").replace("\\", "/").replace("\x00", "").strip()
    if not raw:
        raise CreateArchiveContractError(
            "Generated VPLIB archive contains an empty member name.",
            code="archive_member_name_empty",
            http_status=500,
        )
    if raw.startswith("/") or re_drive_prefix(raw):
        raise CreateArchiveContractError(
            "Generated VPLIB archive contains an absolute member path.",
            code="archive_member_path_absolute",
            http_status=500,
            details={"member": raw[:200]},
        )
    normalized = posixpath.normpath(raw)
    if normalized in {"", ".", ".."} or normalized.startswith("../"):
        raise CreateArchiveContractError(
            "Generated VPLIB archive contains an unsafe member path.",
            code="archive_member_path_unsafe",
            http_status=500,
            details={"member": raw[:200]},
        )
    return normalized


def re_drive_prefix(value: str) -> bool:
    return len(value) >= 2 and value[0].isalpha() and value[1] == ":"


def _configured_int(name: str, default: int, *, minimum: int) -> int:
    try:
        value = int(os.getenv(name, str(default)))
    except Exception:
        value = default
    return max(minimum, value)


def _empty_upload_contract(kind: str) -> dict[str, Any]:
    return {
        "version": LIBRARY_CREATE_ROUTE_SERVICE_VERSION,
        "kind": kind,
        "count": 0,
        "valid_count": 0,
        "validCount": 0,
        "invalid_count": 0,
        "invalidCount": 0,
        "files": [],
        "errors": [],
        "ok": True,
        "required": False,
        "minimum_count": 0,
        "backend_enabled": True,
        "backendEnabled": True,
        "local_only": True,
        "localOnly": True,
        "source": "library_create_route_service.empty",
    }


def _json_object(value: Any) -> dict[str, Any]:
    if isinstance(value, Mapping):
        return _json_safe_dict(value)
    if isinstance(value, str):
        text = value.strip()
        if text.startswith("{") and text.endswith("}"):
            try:
                decoded = json.loads(text)
                if isinstance(decoded, Mapping):
                    return _json_safe_dict(decoded)
            except Exception:
                return {}
    return {}


def _json_list(value: Any) -> list[Any]:
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
                return []
    if isinstance(value, Mapping):
        for key in ("items", "variants", "definition_variants", "definitionVariants"):
            nested = value.get(key)
            if isinstance(nested, list):
                return [_json_safe(item) for item in nested]
    return []


def _clean_identifier(value: Any) -> str:
    if value is None:
        return ""
    text = str(value).replace("\x00", "").strip()
    if not text:
        return ""
    return text.replace(" ", "").replace("-", "_")


def _normalize_taxonomy_path(value: Any) -> str:
    parts = []
    for part in str(value or "").replace("\\", "/").split("/"):
        normalized = _normalize_slug_fallback(part, default="")
        if normalized:
            parts.append(normalized)
    return "/".join(parts)


def _positive_float(value: Any, *, default: float | None = None) -> float | None:
    try:
        number = float(str(value).replace(",", "."))
    except Exception:
        return default
    if number <= 0:
        return default
    return number


def _format_decimal(value: float) -> str:
    return f"{value:.6f}".rstrip("0").rstrip(".") or "1"


def _geometry_to_mm(value: float, unit: str) -> int:
    factor = {"mm": 1.0, "cm": 10.0, "m": 1000.0}.get(unit, 1000.0)
    result = int(round(value * factor))
    return max(1, result)


def _extract_dimension_value(payload: Mapping[str, Any], axis: str) -> Any:
    dimensions = payload.get("dimensions")
    if isinstance(dimensions, Mapping):
        return dimensions.get(f"{axis}_mm")
    return None


def _compact_json(value: Any) -> str:
    return json.dumps(
        _json_safe(value),
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    )



def _payload_fingerprint(payload: Mapping[str, Any]) -> str:
    data = _json_safe_dict(payload)
    variants = _json_list(
        _first_non_empty(
            data.get("definition_variants"),
            data.get("definitionVariants"),
            data.get("definition_variants_json"),
            data.get("definitionVariantsJson"),
        )
    )
    canonical_variants: list[dict[str, Any]] = []
    for raw_variant in variants:
        variant = _json_object(raw_variant)
        if not variant:
            continue
        canonical_variants.append(
            {
                "variant_id": _first_non_empty(
                    variant.get("variant_id"),
                    variant.get("variantId"),
                    variant.get("id"),
                ),
                "label": _first_non_empty(
                    variant.get("label"),
                    variant.get("name"),
                ),
                "is_default": _safe_bool(
                    _first_non_empty(
                        variant.get("is_default"),
                        variant.get("isDefault"),
                    ),
                    default=False,
                ),
                "definition_values": _json_object(
                    _first_non_empty(
                        variant.get("definition_values"),
                        variant.get("definitionValues"),
                        variant.get("definition_values_json"),
                        variant.get("definitionValuesJson"),
                    )
                ),
            }
        )

    canonical = {
        "family_name": _first_non_empty(
            data.get("family_name"),
            data.get("familyName"),
        ),
        "family_description": _first_non_empty(
            data.get("family_description"),
            data.get("familyDescription"),
        ),
        "domain": data.get("domain"),
        "category": data.get("category"),
        "subcategory": data.get("subcategory"),
        "taxonomy_path": _first_non_empty(
            data.get("taxonomy_path"),
            data.get("taxonomyPath"),
        ),
        "object_kind": _first_non_empty(
            data.get("object_kind"),
            data.get("objectKind"),
        ),
        "family_profile_id": _first_non_empty(
            data.get("family_profile_id"),
            data.get("familyProfileId"),
        ),
        "variant_profile_id": _first_non_empty(
            data.get("variant_profile_id"),
            data.get("variantProfileId"),
        ),
        "default_variant_id": _first_non_empty(
            data.get("default_variant_id"),
            data.get("defaultVariantId"),
        ),
        "primitive_shape": _first_non_empty(
            data.get("primitive_shape"),
            data.get("primitiveShape"),
        ),
        "geometry_width": _first_non_empty(
            data.get("geometry_width"),
            data.get("geometryWidth"),
        ),
        "geometry_height": _first_non_empty(
            data.get("geometry_height"),
            data.get("geometryHeight"),
        ),
        "geometry_depth": _first_non_empty(
            data.get("geometry_depth"),
            data.get("geometryDepth"),
        ),
        "geometry_unit": _first_non_empty(
            data.get("geometry_unit"),
            data.get("geometryUnit"),
        ),
        "dimensions": _json_object(data.get("dimensions")),
        "material_class": _first_non_empty(
            data.get("material_class"),
            data.get("materialClass"),
        ),
        "definition_variants": canonical_variants,
    }
    return hashlib.sha256(_compact_json(canonical).encode("utf-8")).hexdigest()

def _stable_starter_uid_from_fingerprint(fingerprint: str) -> str:
    return str(uuid.uuid5(STARTER_UID_NAMESPACE, fingerprint)).lower()


def _stable_starter_vplib_uid(payload: Mapping[str, Any]) -> str:
    return _stable_starter_uid_from_fingerprint(_payload_fingerprint(payload))


# ---------------------------------------------------------------------------
# Payload normalization
# ---------------------------------------------------------------------------


def _normalize_create_action_payload(payload: Any, *, route: str) -> dict[str, Any] | RouteResponse:
    """
    Normalize a create action payload, materialize the starter contract and
    ensure a stable ``vplib_uid``.
    """
    try:
        raw_payload = dict(payload) if isinstance(payload, Mapping) else {}
        binary_assets = raw_payload.pop("_binary_assets", None)
        base_payload = normalize_payload(raw_payload if raw_payload else payload)
        if isinstance(binary_assets, list):
            base_payload["_binary_assets"] = binary_assets
    except Exception as exc:
        return _failure(
            route=route,
            code="payload_normalization_failed",
            message="Payload could not be normalized.",
            exc=exc,
            http_status=400,
        )

    normalization_metadata: dict[str, Any] = {
        "external_normalizer_available": _is_variant_payload_service_available(),
        "external_normalizer_used": False,
        "external_normalizer": None,
    }

    try:
        normalizer_payload = {key: value for key, value in base_payload.items() if key != "_binary_assets"}
        normalized_payload: Mapping[str, Any] = base_payload

        if _is_variant_payload_service_available():
            module = _variant_payload_service()
            normalizer = None

            for function_name in (
                "normalize_create_variant_payload",
                "normalize_create_payload",
                "normalize_payload",
            ):
                candidate = getattr(module, function_name, None)
                if callable(candidate):
                    normalizer = candidate
                    normalization_metadata["external_normalizer"] = function_name
                    break

            if normalizer is not None:
                normalized_result = _call_normalizer_flex(
                    normalizer,
                    normalizer_payload,
                )
                unwrapped, report = _unwrap_normalizer_result(
                    normalized_result
                )
                if not isinstance(unwrapped, Mapping):
                    raise TypeError(
                        "Create payload normalizer returned non-mapping payload."
                    )

                normalized_payload = unwrapped
                normalization_metadata["external_normalizer_used"] = True
                if report:
                    normalization_metadata["report"] = report

        result = _normalize_create_contract_payload(
            normalized_payload,
            route=route,
        )
        if isinstance(binary_assets, list):
            result["_binary_assets"] = binary_assets
        result["_payload_normalization"] = {
            **normalization_metadata,
            "route": route,
            "payload_fingerprint": _payload_fingerprint(result),
            "starter_contract": _json_safe(
                result.get("_starter_contract", {})
            ),
        }

        uid = _extract_vplib_uid_from_any(result)
        if uid:
            result[VPLIB_UID_FIELD] = uid
        else:
            result[VPLIB_UID_FIELD] = _ensure_payload_vplib_uid(result)

        result["vplibUid"] = result[VPLIB_UID_FIELD]
        return result

    except LibraryCreateRouteServiceError as exc:
        return RouteResponse(
            ok=False,
            status=exc.code,
            route=route,
            data={
                "route_service": _route_service_metadata(route, base_payload),
                "vplib_uid": _extract_vplib_uid_from_any(base_payload),
                "payload_normalizer_available": _is_variant_payload_service_available(),
                "details": _json_safe(exc.details),
            },
            errors=[
                _error(
                    exc.code,
                    str(exc),
                    field=route,
                    details=exc.details,
                )
            ],
            http_status=exc.http_status,
        )
    except Exception as exc:
        return RouteResponse(
            ok=False,
            status="payload_normalization_failed",
            route=route,
            data={
                "route_service": _route_service_metadata(route, base_payload),
                "vplib_uid": _extract_vplib_uid_from_any(base_payload),
                "payload_normalizer_available": _is_variant_payload_service_available(),
            },
            errors=[
                _exception_issue(
                    "create_payload_normalization_failed",
                    exc,
                    field=VPLIB_UID_FIELD,
                    fallback_message=(
                        "Create payload could not be normalized for "
                        "VPLIB generation."
                    ),
                )
            ],
            http_status=422,
        )


def _ensure_payload_vplib_uid(payload: Mapping[str, Any]) -> str:
    existing_raw = None
    for key in VPLIB_UID_KEYS:
        if payload.get(key):
            existing_raw = payload.get(key)
            break

    if existing_raw:
        normalized = _normalize_vplib_uid_safe(existing_raw)
        if normalized:
            return normalized

        raise CreatePayloadContractError(
            "Existing vplib_uid is invalid and will not be silently replaced.",
            code="vplib_uid_invalid",
            http_status=422,
            details={"value": str(existing_raw)[:120]},
        )

    starter = payload.get("_starter_contract")
    if isinstance(starter, Mapping) and _safe_bool(
        starter.get("requested"),
        default=False,
    ):
        return _stable_starter_vplib_uid(payload)

    generated = _generate_vplib_uid_safe()
    if generated:
        normalized = _normalize_vplib_uid_safe(generated)
        if normalized:
            return normalized

    return str(uuid.uuid4()).lower()

def _generate_vplib_uid_safe() -> str | None:
    for import_path in (
        "vplib.vplib_id_service",
        "src.vplib.vplib_id_service",
        "vectoplan_library.vplib.vplib_id_service",
        "vectoplan_library.src.vplib.vplib_id_service",
    ):
        try:
            module = importlib.import_module(import_path)
            for function_name in ("generate_vplib_uid", "new_vplib_uid", "create_vplib_uid"):
                function = getattr(module, function_name, None)
                if callable(function):
                    value = function()
                    normalized = _normalize_vplib_uid_safe(value)
                    if normalized:
                        return normalized
                    if value:
                        return str(value)
        except Exception:
            continue

    return None


def _call_normalizer_flex(normalizer: Callable[..., Any], payload: Mapping[str, Any]) -> Any:
    for kwargs in (
        {
            "ensure_uid": True,
            "overwrite_invalid_uid": False,
            "include_report": True,
            "strict": True,
        },
        {
            "ensure_uid": True,
            "overwrite_invalid_uid": False,
        },
        {
            "ensure_uid": True,
        },
        {},
    ):
        try:
            return normalizer(payload, **kwargs)
        except TypeError:
            continue

    return normalizer(payload)


# ---------------------------------------------------------------------------
# Create-result / route-result wrapping
# ---------------------------------------------------------------------------

def _wrap_create_result(result: Any, *, route: str) -> RouteResponse:
    """Convert create-service result into route-service result."""
    payload = _create_result_to_payload(result)

    ok = bool(payload.get("ok", False))
    status = str(payload.get("status") or ("ok" if ok else "error"))
    http_status = _safe_http_status(
        payload.get("_http_status")
        or payload.get("http_status")
        or getattr(result, "http_status", 200)
    )

    data = payload.get("data", {})
    if not isinstance(data, Mapping):
        data = {"value": data}

    route_data = dict(data)
    uid = (
        _extract_vplib_uid_from_any(payload)
        or _extract_vplib_uid_from_any(route_data)
        or _extract_vplib_uid_from_any(result)
    )
    if uid:
        route_data[VPLIB_UID_FIELD] = uid

    route_data.setdefault("route_service", {})
    if isinstance(route_data["route_service"], Mapping):
        route_data["route_service"] = dict(route_data["route_service"])
        route_data["route_service"].update(_route_service_metadata(route, route_data))

    return RouteResponse(
        ok=ok,
        status=status,
        route=route,
        data=route_data,
        errors=_coerce_issue_list(payload.get("errors", [])),
        warnings=_coerce_issue_list(payload.get("warnings", [])),
        info=_coerce_issue_list(payload.get("info", [])),
        http_status=http_status,
    )


def _route_response_from_payload(
    payload: Mapping[str, Any],
    *,
    route: str,
    default_status: str = "ok",
    success_statuses: set[str] | None = None,
) -> RouteResponse:
    success_statuses = success_statuses or {"ok", "ready", "healthy", "partial"}
    data = dict(payload.get("data")) if isinstance(payload.get("data"), Mapping) else dict(payload)

    ok = bool(payload.get("ok", str(payload.get("status", default_status)) in success_statuses))
    status = str(payload.get("status") or default_status)

    if ok and status in {"ready"}:
        status = default_status

    return RouteResponse(
        ok=ok,
        status=status,
        route=route,
        data={
            "route_service": _route_service_metadata(route, payload),
            **data,
        },
        errors=_coerce_issue_list(payload.get("errors", [])),
        warnings=_coerce_issue_list(payload.get("warnings", [])),
        info=_coerce_issue_list(payload.get("info", [])),
        http_status=_safe_http_status(payload.get("_http_status") or payload.get("http_status") or (200 if ok else 500)),
    )


def _attach_vplib_uid_to_response(
    response: RouteResponse,
    *,
    payload: Any | None = None,
    result: Any | None = None,
) -> RouteResponse:
    """Attach `vplib_uid` to response.data and route_service metadata."""
    uid = (
        _extract_vplib_uid_from_any(response.data)
        or _extract_vplib_uid_from_any(result)
        or _extract_vplib_uid_from_any(payload)
    )

    if not uid:
        return response

    data = dict(response.data)
    data[VPLIB_UID_FIELD] = uid

    route_service = data.get("route_service")
    if isinstance(route_service, Mapping):
        route_service_payload = dict(route_service)
    else:
        route_service_payload = {}

    route_service_payload.update(_route_service_metadata(response.route, data))
    route_service_payload[VPLIB_UID_FIELD] = uid
    data["route_service"] = route_service_payload

    return RouteResponse(
        ok=response.ok,
        status=response.status,
        route=response.route,
        data=data,
        errors=response.errors,
        warnings=response.warnings,
        info=response.info,
        http_status=response.http_status,
    )


def _route_service_metadata(route: str, payload: Any | None = None) -> dict[str, Any]:
    """Build route-service metadata with optional vplib_uid."""
    uid = _extract_vplib_uid_from_any(payload)

    return {
        "component": LIBRARY_CREATE_ROUTE_SERVICE_COMPONENT,
        "version": LIBRARY_CREATE_ROUTE_SERVICE_VERSION,
        "route": route,
        "api_prefix": CREATE_API_PREFIX,
        "taxonomy_required_fields": list(TAXONOMY_REQUIRED_FIELDS),
        "definitions_source": "generator_context_or_backend_definition_catalog_service",
        "payload_normalizer": "library_create_variant_payload_service_or_route_fallback",
        "generator_workflow": "library_generator_workflow_service",
        "generator_context": "library_generator_context_service",
        "vplib_uid_field": VPLIB_UID_FIELD,
        "vplib_uid": uid,
        "starter_object_kind": STARTER_OBJECT_KIND,
        "starter_family_profile_id": STARTER_FAMILY_PROFILE_ID,
        "starter_variant_profile_id": STARTER_VARIANT_PROFILE_ID,
        "verified_zip_download": True,
    }


def _create_result_to_payload(result: Any) -> dict[str, Any]:
    """Defensively convert a create-service result to a dict."""
    if result is None:
        return {
            "ok": False,
            "status": "empty_result",
            "data": {},
            "errors": [
                _error(
                    "empty_result",
                    "Create service returned no result.",
                ).to_dict()
            ],
            "warnings": [],
            "info": [],
            "_http_status": 500,
        }

    if hasattr(result, "to_dict") and callable(result.to_dict):
        try:
            payload = result.to_dict(include_http_status=True)
        except TypeError:
            payload = result.to_dict()
        if isinstance(payload, Mapping):
            return dict(payload)

    if isinstance(result, Mapping):
        return dict(result)

    return {
        "ok": False,
        "status": "invalid_result_type",
        "data": {"repr": repr(result)},
        "errors": [
            _error(
                "invalid_result_type",
                "Create service returned an unexpected result type.",
                details={"type": type(result).__name__},
            ).to_dict()
        ],
        "warnings": [],
        "info": [],
        "_http_status": 500,
    }


def _service_result_payload(result: Any) -> dict[str, Any]:
    if result is None:
        return {}

    if hasattr(result, "to_dict") and callable(result.to_dict):
        for kwargs in (
            {"include_http_status": True},
            {"include_payloads": True},
            {},
        ):
            try:
                payload = result.to_dict(**kwargs)
                if isinstance(payload, Mapping):
                    return dict(payload)
            except TypeError:
                continue
            except Exception:
                break

    if isinstance(result, Mapping):
        return dict(result)

    if isinstance(result, (list, tuple)):
        return {"items": _json_safe(list(result))}

    return {"value": _json_safe(result)}



def _first_mapping(*values: Any) -> dict[str, Any]:
    for value in values:
        if isinstance(value, Mapping) and value:
            return _json_safe_dict(value)
    return {}


# ---------------------------------------------------------------------------
# Options enrichment
# ---------------------------------------------------------------------------

def _enrich_options_response_with_create_runtime(response: RouteResponse) -> RouteResponse:
    """Attach write-mode flags owned by the legacy create service."""
    data = dict(response.data)
    create_health = _safe_create_service_health()
    health_payload = _first_mapping(create_health.get("payload"))
    runtime_data = _first_mapping(
        health_payload.get("data"),
        health_payload.get("payload"),
        health_payload,
    )

    for key in ("write_enabled", "overwrite_enabled", "source_root"):
        if key not in data and key in runtime_data:
            data[key] = runtime_data[key]

    capabilities = data.get("capabilities")
    if isinstance(capabilities, Mapping) and "write_enabled" in data:
        capabilities = dict(capabilities)
        capabilities["save_to_source_root"] = _safe_bool(
            data.get("write_enabled"),
            default=False,
        )
        data["capabilities"] = capabilities

    return RouteResponse(
        ok=response.ok,
        status=response.status,
        route=response.route,
        data=data,
        errors=list(response.errors),
        warnings=list(response.warnings),
        info=list(response.info),
        http_status=response.http_status,
    )


def _enrich_options_response_with_taxonomy(response: RouteResponse) -> RouteResponse:
    """Merge canonical backend taxonomy into create/options response."""
    data = dict(response.data)
    warnings = list(response.warnings)
    errors = list(response.errors)
    info = list(response.info)

    if not _is_taxonomy_service_available():
        warnings.append(
            _warning(
                "taxonomy_service_unavailable",
                "Taxonomy service is unavailable.",
                field="library.taxonomy",
                details=_safe_taxonomy_service_health(),
            )
        )
        return RouteResponse(
            ok=response.ok,
            status=response.status,
            route=response.route,
            data=data,
            errors=errors,
            warnings=warnings,
            info=info,
            http_status=response.http_status,
        )

    try:
        taxonomy_payload = _get_taxonomy_create_options_payload()

        data["taxonomy"] = taxonomy_payload.get("taxonomy", {})
        data["taxonomy_version"] = taxonomy_payload.get("taxonomy_version", data.get("taxonomy_version", ""))
        data["taxonomy_schema_version"] = taxonomy_payload.get("taxonomy_schema_version", data.get("taxonomy_schema_version", ""))
        data["taxonomy_source"] = "backend_taxonomy_service"
        data["required_taxonomy_fields"] = list(TAXONOMY_REQUIRED_FIELDS)

        data["domains"] = taxonomy_payload.get("domains", data.get("domains", []))
        data["categories_by_domain"] = taxonomy_payload.get("categories_by_domain", data.get("categories_by_domain", {}))
        data["subcategories_by_category"] = taxonomy_payload.get("subcategories_by_category", data.get("subcategories_by_category", {}))
        data["subcategories_by_category_path"] = taxonomy_payload.get(
            "subcategories_by_category_path",
            taxonomy_payload.get("subcategories_by_category", data.get("subcategories_by_category", {})),
        )
        data["categories"] = _flatten_taxonomy_categories(
            taxonomy_payload.get("categories", data.get("categories", [])),
            data["categories_by_domain"],
        )
        data["subcategories"] = _flatten_taxonomy_subcategories(
            taxonomy_payload.get("subcategories", data.get("subcategories", [])),
            data["subcategories_by_category_path"],
        )

        data.setdefault("constraints", {})
        if isinstance(data["constraints"], Mapping):
            constraints = dict(data["constraints"])
            constraints["taxonomy"] = taxonomy_payload.get("constraints", {})
            data["constraints"] = constraints

        data.setdefault("defaults", {})
        if isinstance(data["defaults"], Mapping):
            defaults = dict(data["defaults"])
            defaults["taxonomy"] = taxonomy_payload.get("defaults", {})
            data["defaults"] = defaults

        info.append(
            _info(
                "taxonomy_options_attached",
                "Canonical backend taxonomy was attached to create options.",
                details={
                    "taxonomy_version": data.get("taxonomy_version"),
                    "required_fields": list(TAXONOMY_REQUIRED_FIELDS),
                },
            )
        )

        return RouteResponse(
            ok=response.ok,
            status=response.status,
            route=response.route,
            data=data,
            errors=errors,
            warnings=warnings,
            info=info,
            http_status=response.http_status,
        )

    except Exception as exc:
        warnings.append(
            _exception_warning(
                "taxonomy_options_failed",
                exc,
                field="library.taxonomy.options",
                fallback_message="Taxonomy options could not be loaded.",
            )
        )
        return RouteResponse(
            ok=response.ok,
            status=response.status,
            route=response.route,
            data=data,
            errors=errors,
            warnings=warnings,
            info=info,
            http_status=response.http_status,
        )


def _enrich_options_response_with_definitions(response: RouteResponse, *, user_id: Any = 1) -> RouteResponse:
    """Merge backend-owned definitions into create/options response."""
    data = dict(response.data)
    warnings = list(response.warnings)
    errors = list(response.errors)
    info = list(response.info)

    definitions_payload = _get_definitions_options_payload(user_id=user_id)

    if not bool(definitions_payload.get("available")):
        data = _attach_unavailable_definitions_payload(data, definitions_payload)
        warnings.append(
            _warning(
                "definitions_unavailable",
                "Definitions service is unavailable. Create options were returned without full definitions data.",
                field="definitions",
                details=definitions_payload,
            )
        )
        return RouteResponse(
            ok=response.ok,
            status=response.status,
            route=response.route,
            data=data,
            errors=errors,
            warnings=warnings,
            info=info,
            http_status=response.http_status,
        )

    data = _attach_definitions_payload(data, definitions_payload)

    info.append(
        _info(
            "definitions_options_attached",
            "Backend definitions data was attached to create options.",
            details={
                "source": definitions_payload.get("source"),
                "method": definitions_payload.get("method"),
                "counts": definitions_payload.get("counts", {}),
            },
        )
    )

    return RouteResponse(
        ok=response.ok,
        status=response.status,
        route=response.route,
        data=data,
        errors=errors,
        warnings=warnings,
        info=info,
        http_status=response.http_status,
    )


def _flatten_taxonomy_categories(
    categories: Any,
    categories_by_domain: Any,
) -> list[dict[str, Any]]:
    """Return category options with the parent domain required by the UI."""
    flattened: list[dict[str, Any]] = []
    seen: set[tuple[str, str]] = set()

    direct_items = _coerce_list(categories)
    grouped = categories_by_domain if isinstance(categories_by_domain, Mapping) else {}
    groups: list[tuple[str, list[Any]]] = [("", direct_items)] if direct_items else []
    groups.extend((str(domain), _coerce_list(items)) for domain, items in grouped.items())

    for domain, items in groups:
        for item in items:
            option = dict(item) if isinstance(item, Mapping) else {"id": str(item), "label": str(item)}
            option_id = str(
                option.get("id")
                or option.get("value")
                or option.get("slug")
                or option.get("key")
                or ""
            ).strip()
            parent_domain = str(
                option.get("domain")
                or option.get("domain_id")
                or option.get("domain_slug")
                or option.get("parent_domain")
                or domain
            ).strip()
            if not option_id or (parent_domain, option_id) in seen:
                continue
            option.setdefault("domain", parent_domain)
            option.setdefault("domain_id", parent_domain)
            option.setdefault("parent_domain", parent_domain)
            flattened.append(option)
            seen.add((parent_domain, option_id))

    return flattened


def _flatten_taxonomy_subcategories(
    subcategories: Any,
    subcategories_by_category: Any,
) -> list[dict[str, Any]]:
    """Return subcategory options with parent domain and category metadata."""
    flattened: list[dict[str, Any]] = []
    seen: set[tuple[str, str, str]] = set()

    direct_items = _coerce_list(subcategories)
    grouped = subcategories_by_category if isinstance(subcategories_by_category, Mapping) else {}
    groups: list[tuple[str, list[Any]]] = [("", direct_items)] if direct_items else []
    groups.extend((str(path), _coerce_list(items)) for path, items in grouped.items())

    for parent_path, items in groups:
        path_parts = [part for part in parent_path.replace("\\", "/").split("/") if part]
        grouped_domain = path_parts[-2] if len(path_parts) >= 2 else ""
        grouped_category = path_parts[-1] if path_parts else ""

        for item in items:
            option = dict(item) if isinstance(item, Mapping) else {"id": str(item), "label": str(item)}
            option_id = str(
                option.get("id")
                or option.get("value")
                or option.get("slug")
                or option.get("key")
                or ""
            ).strip()
            parent_domain = str(
                option.get("domain")
                or option.get("domain_id")
                or option.get("domain_slug")
                or option.get("parent_domain")
                or grouped_domain
            ).strip()
            parent_category = str(
                option.get("category")
                or option.get("category_id")
                or option.get("category_slug")
                or option.get("parent_category")
                or grouped_category
            ).strip()
            identity = (parent_domain, parent_category, option_id)
            if not option_id or identity in seen:
                continue
            option.setdefault("domain", parent_domain)
            option.setdefault("domain_id", parent_domain)
            option.setdefault("parent_domain", parent_domain)
            option.setdefault("category", parent_category)
            option.setdefault("category_id", parent_category)
            option.setdefault("parent_category", parent_category)
            flattened.append(option)
            seen.add(identity)

    return flattened


def _get_taxonomy_create_options_payload() -> dict[str, Any]:
    service = _get_taxonomy_service()

    for method_name in (
        "get_create_options_payload",
        "get_create_options",
        "create_options",
    ):
        method = getattr(service, method_name, None)
        if not callable(method):
            continue

        result = method()
        payload = _service_result_payload(result)

        if isinstance(payload.get("data"), Mapping):
            return dict(payload["data"])

        if isinstance(payload.get("payload"), Mapping):
            return dict(payload["payload"])

        return payload

    raise RuntimeError("Taxonomy service exposes no create-options method.")


def _get_definitions_options_payload(*, user_id: Any = 1) -> dict[str, Any]:
    definition_catalog_error: Exception | None = None

    if _is_definition_catalog_available():
        try:
            service = _definition_catalog_service()

            for method_name in (
                "get_create_options",
                "get_current_catalog",
                "get_summary",
            ):
                method = getattr(service, method_name, None)
                if not callable(method):
                    continue

                result = _call_function_flex(method, {"user_id": user_id, "resolved": True})
                payload = _service_result_payload(result)
                inner_payload = payload.get("payload") if isinstance(payload.get("payload"), Mapping) else payload

                resolved = {
                    "available": True,
                    "source": "definition_catalog_service",
                    "method": method_name,
                    "payload": payload,
                    "options": _extract_definition_options(inner_payload),
                    "definitions": _extract_definition_catalogs(inner_payload),
                    "counts": _extract_counts(inner_payload),
                    "ok": bool(payload.get("ok", True)),
                    "status": payload.get("status", "ok"),
                }
                return _with_legacy_definition_dataset_fallbacks(resolved)
        except Exception as exc:
            definition_catalog_error = exc

    if _is_legacy_definitions_available():
        try:
            module = _load_legacy_definitions_module()

            for function_name in (
                "get_create_definition_options",
                "get_definition_options",
                "get_definitions_payload",
                "get_current_definitions",
            ):
                function = getattr(module, function_name, None)
                if not callable(function):
                    continue

                result = _call_function_flex(function, {"force_refresh": False, "force_reload": False})
                payload = _service_result_payload(result)

                return {
                    "available": True,
                    "source": "legacy_library_definitions",
                    "method": function_name,
                    "payload": payload,
                    "options": _extract_definition_options(payload),
                    "definitions": _extract_definition_catalogs(payload),
                    "counts": _extract_counts(payload),
                    "ok": bool(payload.get("ok", True)),
                    "status": payload.get("status", "ok"),
                }
        except Exception as exc:
            return _definitions_unavailable_payload(
                reason="legacy_definitions_failed",
                exc=exc,
            )

    if definition_catalog_error is not None:
        return _definitions_unavailable_payload(
            reason="definition_catalog_failed",
            exc=definition_catalog_error,
        )

    return _definitions_unavailable_payload(
        reason="import_failed",
        exc=None,
    )


def _with_legacy_definition_dataset_fallbacks(
    definitions_payload: Mapping[str, Any],
) -> dict[str, Any]:
    """Fill incomplete database catalogs from the bundled canonical definitions."""
    resolved = dict(definitions_payload)
    definitions = (
        dict(resolved.get("definitions", {}))
        if isinstance(resolved.get("definitions"), Mapping)
        else {}
    )
    options = (
        dict(resolved.get("options", {}))
        if isinstance(resolved.get("options"), Mapping)
        else {}
    )
    datasets = (
        "object_kinds",
        "family_profiles",
        "variant_profiles",
        "variables",
        "units",
        "materials",
        "document_types",
        "profile_bindings",
    )

    missing = [
        dataset
        for dataset in datasets
        if not _coerce_list(definitions.get(dataset))
        or not _coerce_list(options.get(dataset))
    ]
    if not missing or not _is_legacy_definitions_available():
        return resolved

    try:
        module = _load_legacy_definitions_module()
        legacy_payload: dict[str, Any] | None = None
        legacy_method = ""
        for function_name in (
            "get_create_definition_options",
            "get_definition_options",
            "get_definitions_payload",
            "get_current_definitions",
        ):
            function = getattr(module, function_name, None)
            if not callable(function):
                continue
            result = _call_function_flex(
                function,
                {"force_refresh": False, "force_reload": False},
            )
            legacy_payload = _service_result_payload(result)
            legacy_method = function_name
            break

        if legacy_payload is None:
            return resolved

        legacy_definitions = _extract_definition_catalogs(legacy_payload)
        legacy_options = _extract_definition_options(legacy_payload)
        fallback_datasets: list[str] = []

        for dataset in datasets:
            definition_items = _coerce_list(definitions.get(dataset))
            option_items = _coerce_list(options.get(dataset))
            fallback_items = _coerce_list(
                legacy_definitions.get(dataset) or legacy_options.get(dataset)
            )

            if not definition_items:
                definition_items = option_items or fallback_items
                if fallback_items:
                    fallback_datasets.append(dataset)
            if not option_items:
                option_items = definition_items or fallback_items

            definitions[dataset] = definition_items
            options[dataset] = option_items

        resolved["definitions"] = definitions
        resolved["options"] = options
        resolved["counts"] = {
            dataset: len(_coerce_list(definitions.get(dataset)))
            for dataset in datasets
        }
        if fallback_datasets:
            resolved["fallback_source"] = "legacy_library_definitions"
            resolved["fallback_method"] = legacy_method
            resolved["fallback_datasets"] = sorted(set(fallback_datasets))
        return resolved
    except Exception as exc:
        resolved["fallback_error"] = {
            "type": exc.__class__.__name__,
            "message": str(exc),
        }
        return resolved


def _extract_definition_options(payload: Any) -> dict[str, Any]:
    data = payload if isinstance(payload, Mapping) else {}

    options = data.get("options")
    if isinstance(options, Mapping):
        return dict(options)

    records = data.get("records")
    if isinstance(records, Mapping):
        return {
            "object_kinds": _coerce_list(records.get("object_kinds")),
            "family_profiles": _coerce_list(records.get("family_profiles")),
            "variant_profiles": _coerce_list(records.get("variant_profiles")),
            "variables": _coerce_list(records.get("variables")),
            "materials": _coerce_list(records.get("materials")),
            "units": _coerce_list(records.get("units")),
            "document_types": _coerce_list(records.get("document_types")),
            "profile_bindings": _coerce_list(records.get("profile_bindings")),
        }

    return {
        "object_kinds": _coerce_list(data.get("object_kinds")),
        "family_profiles": _coerce_list(data.get("family_profiles")),
        "variant_profiles": _coerce_list(data.get("variant_profiles")),
        "variables": _coerce_list(data.get("variables")),
        "materials": _coerce_list(data.get("materials") or data.get("material_classes")),
        "units": _coerce_list(data.get("units")),
        "document_types": _coerce_list(data.get("document_types")),
        "profile_bindings": _coerce_list(data.get("profile_bindings")),
    }


def _extract_definition_catalogs(payload: Any) -> dict[str, Any]:
    data = payload if isinstance(payload, Mapping) else {}

    definitions = data.get("definitions")
    if isinstance(definitions, Mapping):
        return dict(definitions)

    catalog = data.get("catalog")
    if isinstance(catalog, Mapping):
        return dict(catalog)

    records = data.get("records")
    if isinstance(records, Mapping):
        return dict(records)

    return {
        "variables": _coerce_list(data.get("variables")),
        "units": _coerce_list(data.get("units")),
        "materials": _coerce_list(data.get("materials") or data.get("material_classes")),
        "document_types": _coerce_list(data.get("document_types")),
        "object_kinds": _coerce_list(data.get("object_kinds")),
        "family_profiles": _coerce_list(data.get("family_profiles")),
        "variant_profiles": _coerce_list(data.get("variant_profiles")),
        "profile_bindings": _coerce_list(data.get("profile_bindings")),
    }


def _extract_counts(payload: Any) -> dict[str, int]:
    data = payload if isinstance(payload, Mapping) else {}

    counts = data.get("counts")
    if isinstance(counts, Mapping):
        return {str(key): _safe_int(value, default=0) for key, value in counts.items()}

    catalogs = _extract_definition_catalogs(data)
    return {
        key: len(value) if isinstance(value, list) else 0
        for key, value in catalogs.items()
    }


def _attach_definitions_payload(data: dict[str, Any], definitions_payload: Mapping[str, Any]) -> dict[str, Any]:
    enriched = dict(data)

    definition_options = definitions_payload.get("options", {})
    if not isinstance(definition_options, Mapping):
        definition_options = {}

    definition_catalogs = definitions_payload.get("definitions", {})
    if not isinstance(definition_catalogs, Mapping):
        definition_catalogs = {}

    enriched["definitions"] = dict(definitions_payload)
    enriched["definitions_health"] = {
        "ok": bool(definitions_payload.get("ok", True)),
        "healthy": bool(definitions_payload.get("healthy", definitions_payload.get("ok", True))),
        "status": definitions_payload.get("status", "ok"),
        "source": definitions_payload.get("source"),
        "method": definitions_payload.get("method"),
        "counts": definitions_payload.get("counts", {}),
    }
    enriched["definitions_source"] = definitions_payload.get("source", "definition_catalog_service")
    enriched["definitions_options"] = dict(definition_options)
    enriched["definition_catalogs"] = dict(definition_catalogs)

    for target_key, source_key in (
        ("object_kinds", "object_kinds"),
        ("family_profiles", "family_profiles"),
        ("variant_profiles", "variant_profiles"),
        ("materials", "materials"),
        ("document_types", "document_types"),
        ("units", "units"),
        ("profile_bindings", "profile_bindings"),
    ):
        value = definition_options.get(source_key)
        if isinstance(value, list) and value:
            enriched[target_key] = value

    enriched["object_kind_definitions"] = _coerce_list(definition_catalogs.get("object_kinds"))
    enriched["family_profile_definitions"] = _coerce_list(definition_catalogs.get("family_profiles"))
    enriched["variant_profile_definitions"] = _coerce_list(definition_catalogs.get("variant_profiles"))
    enriched["variables"] = _coerce_list(definition_catalogs.get("variables"))
    enriched["unit_definitions"] = _coerce_list(definition_catalogs.get("units"))
    enriched["material_definitions"] = _coerce_list(definition_catalogs.get("materials"))
    enriched["document_type_definitions"] = _coerce_list(definition_catalogs.get("document_types"))
    enriched["profile_bindings"] = _coerce_list(definition_catalogs.get("profile_bindings"))

    enriched.setdefault("constraints", {})
    if isinstance(enriched["constraints"], Mapping):
        constraints = dict(enriched["constraints"])
        constraints["definitions"] = {
            "source": definitions_payload.get("source"),
            "counts": definitions_payload.get("counts", {}),
            "variant_profile_required": True,
            "frontend_must_render_profiles_from_backend": True,
        }
        enriched["constraints"] = constraints

    enriched.setdefault("defaults", {})
    if isinstance(enriched["defaults"], Mapping):
        defaults = dict(enriched["defaults"])
        defaults["definitions"] = {
            "default_object_kind": _first_option_id(definition_options.get("object_kinds")),
            "default_family_profile": _first_option_id(definition_options.get("family_profiles")),
            "default_variant_profile": _first_option_id(definition_options.get("variant_profiles")),
        }
        enriched["defaults"] = defaults

    return enriched


def _attach_unavailable_definitions_payload(data: dict[str, Any], unavailable_payload: Mapping[str, Any]) -> dict[str, Any]:
    enriched = dict(data)

    enriched["definitions"] = dict(unavailable_payload)
    enriched["definitions_health"] = dict(unavailable_payload)
    enriched["definitions_source"] = "backend_definitions_unavailable"
    enriched["definitions_options"] = {}
    enriched["definition_catalogs"] = {}

    enriched.setdefault("object_kinds", [])
    enriched.setdefault("family_profiles", [])
    enriched.setdefault("variant_profiles", [])
    enriched.setdefault("variables", [])
    enriched.setdefault("units", [])
    enriched.setdefault("materials", [])
    enriched.setdefault("document_types", [])
    enriched.setdefault("profile_bindings", [])

    return enriched


# ---------------------------------------------------------------------------
# Taxonomy validation
# ---------------------------------------------------------------------------

def _prevalidate_taxonomy_payload(payload: Mapping[str, Any], *, route: str) -> RouteResponse | None:
    """
    Route-level taxonomy validation.

    The generator workflow also validates context. This precheck only catches
    missing required fields early for clear HTTP responses.
    """
    selection_payload = _extract_taxonomy_selection_dict(payload)
    missing_fields = [field for field in TAXONOMY_REQUIRED_FIELDS if not selection_payload.get(field)]

    if missing_fields:
        return RouteResponse(
            ok=False,
            status="taxonomy_required_fields_missing",
            route=route,
            data={
                "route_service": _route_service_metadata(route, payload),
                "required_taxonomy_fields": list(TAXONOMY_REQUIRED_FIELDS),
                "missing_fields": missing_fields,
                "payload_taxonomy": selection_payload,
                "vplib_uid": _extract_vplib_uid_from_any(payload),
            },
            errors=[
                _error(
                    "required",
                    f"Taxonomy field is required: {field}",
                    field=field,
                )
                for field in missing_fields
            ],
            http_status=422,
        )

    return None


def _extract_taxonomy_selection_dict(payload: Mapping[str, Any]) -> dict[str, str]:
    """Extract domain/category/subcategory from flat or nested payload."""
    source = payload
    nested = payload.get("classification") or payload.get("taxonomy")

    if isinstance(nested, Mapping):
        source = nested

    return {
        "domain": _taxonomy_normalize_slug(
            source.get("domain")
            or source.get("domain_id")
            or source.get("reiter"),
            default="",
        ),
        "category": _taxonomy_normalize_slug(
            source.get("category")
            or source.get("category_id")
            or source.get("kategorie"),
            default="",
        ),
        "subcategory": _taxonomy_normalize_slug(
            source.get("subcategory")
            or source.get("subcategory_id")
            or source.get("sub_category")
            or source.get("unterkategorie"),
            default="",
        ),
    }


def _taxonomy_normalize_slug(value: Any, *, default: str = "") -> str:
    try:
        module = _taxonomy_module()
        normalizer = getattr(module, "normalize_slug", None)
        if callable(normalizer):
            return str(normalizer(value, default=default))
    except Exception:
        pass

    return _normalize_slug_fallback(value, default=default)


# ---------------------------------------------------------------------------
# Import availability / service calls
# ---------------------------------------------------------------------------

def _is_generator_context_available() -> bool:
    try:
        _generator_context_module()
        return True
    except Exception:
        return False


def _is_generator_workflow_available() -> bool:
    try:
        _generator_workflow_module()
        return True
    except Exception:
        return False


def _is_generator_diagnostics_available() -> bool:
    try:
        _generator_diagnostics_module()
        return True
    except Exception:
        return False


def _is_create_service_available() -> bool:
    try:
        _create_service()
        return True
    except Exception:
        return False


def _is_variant_payload_service_available() -> bool:
    try:
        _variant_payload_service()
        return True
    except Exception:
        return False


def _is_taxonomy_service_available() -> bool:
    try:
        module = _taxonomy_module()
        return getattr(module, "get_default_taxonomy_service", None) is not None
    except Exception:
        return False


def _is_definition_catalog_available() -> bool:
    try:
        _definition_catalog_service()
        return True
    except Exception:
        return False


def _is_legacy_definitions_available() -> bool:
    try:
        _load_legacy_definitions_module()
        return True
    except Exception:
        return False


def _get_taxonomy_service() -> Any:
    if not _is_taxonomy_service_available():
        raise RuntimeError("Taxonomy service is unavailable.")

    module = _taxonomy_module()
    factory = getattr(module, "get_default_taxonomy_service", None)
    if not callable(factory):
        raise RuntimeError("Taxonomy service factory is unavailable.")

    return factory()


def _call_create_service_function(function_name: str, *args: Any, **kwargs: Any) -> Any:
    module = _create_service()
    function = getattr(module, function_name, None)

    if not callable(function):
        raise AttributeError(f"Create service does not export {function_name!r}.")

    return _call_function_with_supported_kwargs(function, *args, **kwargs)


def _call_function_flex(function: Callable[..., Any], payload_or_kwargs: Mapping[str, Any] | None = None) -> Any:
    payload = dict(payload_or_kwargs or {})

    try:
        return _call_function_with_supported_kwargs(function, **payload)
    except TypeError:
        pass

    try:
        return function(payload)
    except TypeError:
        return function()


def _call_function_with_supported_kwargs(function: Callable[..., Any], *args: Any, **kwargs: Any) -> Any:
    if not kwargs:
        return function(*args)

    supported_kwargs = _filter_supported_kwargs(function, kwargs)
    return function(*args, **supported_kwargs)


def _filter_supported_kwargs(func: Callable[..., Any], kwargs: Mapping[str, Any]) -> dict[str, Any]:
    if not kwargs:
        return {}

    try:
        signature = inspect.signature(func)
    except (TypeError, ValueError):
        return dict(kwargs)

    for parameter in signature.parameters.values():
        if parameter.kind == inspect.Parameter.VAR_KEYWORD:
            return dict(kwargs)

    supported = set(signature.parameters.keys())
    return {key: value for key, value in kwargs.items() if key in supported}


# ---------------------------------------------------------------------------
# Health helpers
# ---------------------------------------------------------------------------

def _safe_generator_context_health() -> dict[str, Any]:
    try:
        module = _generator_context_module()

        for function_name in (
            "get_library_generator_context_service_health",
            "get_generator_context_service_health",
            "get_health",
            "health",
        ):
            function = getattr(module, function_name, None)
            if not callable(function):
                continue

            payload = _service_result_payload(function())
            return {
                "available": True,
                "ok": bool(payload.get("ok", payload.get("healthy", True))),
                "healthy": bool(payload.get("healthy", payload.get("ok", True))),
                "status": payload.get("status", "available"),
                "payload": payload,
                "component": getattr(module, "LIBRARY_GENERATOR_CONTEXT_SERVICE_COMPONENT", "library_generator_context_service"),
                "schema_version": getattr(module, "LIBRARY_GENERATOR_CONTEXT_SERVICE_SCHEMA_VERSION", "unknown"),
            }

        return {
            "available": True,
            "ok": True,
            "healthy": True,
            "status": "available_no_health_method",
            "component": getattr(module, "LIBRARY_GENERATOR_CONTEXT_SERVICE_COMPONENT", "library_generator_context_service"),
        }
    except Exception as exc:
        return {
            "available": False,
            "ok": False,
            "healthy": False,
            "status": "unavailable",
            "error": _exception_payload(exc),
        }


def _safe_generator_workflow_health() -> dict[str, Any]:
    try:
        module = _generator_workflow_module()

        for function_name in (
            "get_library_generator_workflow_service_health",
            "get_generator_workflow_service_health",
            "get_health",
            "health",
        ):
            function = getattr(module, function_name, None)
            if not callable(function):
                continue

            payload = _service_result_payload(function())
            return {
                "available": True,
                "ok": bool(payload.get("ok", payload.get("healthy", True))),
                "healthy": bool(payload.get("healthy", payload.get("ok", True))),
                "status": payload.get("status", "available"),
                "payload": payload,
                "component": getattr(module, "LIBRARY_GENERATOR_WORKFLOW_SERVICE_COMPONENT", "library_generator_workflow_service"),
                "schema_version": getattr(module, "LIBRARY_GENERATOR_WORKFLOW_SERVICE_SCHEMA_VERSION", "unknown"),
            }

        return {
            "available": True,
            "ok": True,
            "healthy": True,
            "status": "available_no_health_method",
            "component": getattr(module, "LIBRARY_GENERATOR_WORKFLOW_SERVICE_COMPONENT", "library_generator_workflow_service"),
        }
    except Exception as exc:
        return {
            "available": False,
            "ok": False,
            "healthy": False,
            "status": "unavailable",
            "error": _exception_payload(exc),
        }


def _safe_generator_diagnostics_health() -> dict[str, Any]:
    try:
        module = _generator_diagnostics_module()

        for function_name in (
            "get_library_generator_diagnostics_service_health",
            "get_generator_diagnostics_service_health",
            "get_health",
            "health",
        ):
            function = getattr(module, function_name, None)
            if not callable(function):
                continue

            payload = _service_result_payload(function())
            return {
                "available": True,
                "ok": bool(payload.get("ok", payload.get("healthy", True))),
                "healthy": bool(payload.get("healthy", payload.get("ok", True))),
                "status": payload.get("status", "available"),
                "payload": payload,
                "component": getattr(module, "LIBRARY_GENERATOR_DIAGNOSTICS_SERVICE_COMPONENT", "library_generator_diagnostics_service"),
                "schema_version": getattr(module, "LIBRARY_GENERATOR_DIAGNOSTICS_SERVICE_SCHEMA_VERSION", "unknown"),
            }

        return {
            "available": True,
            "ok": True,
            "healthy": True,
            "status": "available_no_health_method",
            "component": getattr(module, "LIBRARY_GENERATOR_DIAGNOSTICS_SERVICE_COMPONENT", "library_generator_diagnostics_service"),
        }
    except Exception as exc:
        return {
            "available": False,
            "ok": False,
            "healthy": False,
            "status": "unavailable",
            "error": _exception_payload(exc),
        }


def _safe_create_service_health() -> dict[str, Any]:
    try:
        module = _create_service()
        health_func = getattr(module, "get_service_health", None) or getattr(module, "health", None)
        payload = _create_result_to_payload(health_func()) if callable(health_func) else {"ok": True}

        return {
            "available": True,
            "ok": bool(payload.get("ok", False)),
            "status": payload.get("status", "unknown"),
            "payload": payload,
            "component": getattr(module, "LIBRARY_CREATE_SERVICE_COMPONENT", "library-create-service"),
            "version": getattr(module, "LIBRARY_CREATE_SERVICE_VERSION", "unknown"),
        }
    except Exception as exc:
        return {
            "available": False,
            "ok": False,
            "status": "unavailable",
            "error": _exception_payload(exc),
        }


def _safe_variant_payload_service_health() -> dict[str, Any]:
    try:
        module = _variant_payload_service()

        health_payload = {}
        for function_name in (
            "get_service_health",
            "get_health",
            "health",
        ):
            candidate = getattr(module, function_name, None)
            if callable(candidate):
                health_payload = _service_result_payload(candidate())
                break

        return {
            "available": True,
            "ok": bool(health_payload.get("ok", True)),
            "healthy": bool(health_payload.get("healthy", health_payload.get("ok", True))),
            "status": health_payload.get("status", "available"),
            "payload": health_payload,
            "component": getattr(module, "CREATE_VARIANT_PAYLOAD_SERVICE_COMPONENT", "library_create_variant_payload_service"),
            "schema_version": getattr(module, "CREATE_VARIANT_PAYLOAD_SERVICE_SCHEMA_VERSION", "unknown"),
            "vplib_uid_field": VPLIB_UID_FIELD,
        }
    except Exception as exc:
        return {
            "available": False,
            "ok": False,
            "healthy": False,
            "status": "unavailable",
            "error": _exception_payload(exc),
        }


def _safe_taxonomy_service_health() -> dict[str, Any]:
    try:
        service = _get_taxonomy_service()

        for call in (
            lambda: service.health(force_reload=False, include_registry_state=False),
            lambda: service.health(),
            lambda: service.get_health(),
        ):
            try:
                result = call()
                payload = _service_result_payload(result)
                return {
                    "available": True,
                    "ok": bool(payload.get("ok", payload.get("healthy", True))),
                    "healthy": bool(payload.get("healthy", payload.get("ok", True))),
                    "status": payload.get("status", "available"),
                    "payload": payload,
                }
            except Exception:
                continue

        return {
            "available": True,
            "ok": True,
            "healthy": True,
            "status": "available",
        }
    except Exception as exc:
        return {
            "available": False,
            "ok": False,
            "healthy": False,
            "status": "unavailable",
            "error": _exception_payload(exc),
        }


def _safe_definitions_health() -> dict[str, Any]:
    if _is_definition_catalog_available():
        try:
            service = _definition_catalog_service()
            health_func = getattr(service, "get_health", None)
            payload = _service_result_payload(health_func()) if callable(health_func) else {"ok": True}

            return {
                "available": True,
                "source": "definition_catalog_service",
                "ok": bool(payload.get("ok", True)),
                "healthy": bool(payload.get("healthy", payload.get("ok", True))),
                "status": payload.get("status", "available"),
                "payload": payload,
            }
        except Exception as exc:
            return {
                "available": False,
                "source": "definition_catalog_service",
                "status": "unavailable",
                "error": _exception_payload(exc),
            }

    if _is_legacy_definitions_available():
        try:
            module = _load_legacy_definitions_module()
            for function_name in ("get_definitions_health", "get_health", "health"):
                function = getattr(module, function_name, None)
                if callable(function):
                    payload = _service_result_payload(_call_function_flex(function, {"force_refresh": False}))
                    return {
                        "available": True,
                        "source": "legacy_library_definitions",
                        "ok": bool(payload.get("ok", True)),
                        "healthy": bool(payload.get("healthy", payload.get("ok", True))),
                        "status": payload.get("status", "available"),
                        "payload": payload,
                    }

            return {
                "available": True,
                "source": "legacy_library_definitions",
                "ok": True,
                "healthy": True,
                "status": "available",
            }
        except Exception as exc:
            return {
                "available": False,
                "source": "legacy_library_definitions",
                "status": "unavailable",
                "error": _exception_payload(exc),
            }

    return {
        "available": False,
        "source": "none",
        "ok": False,
        "healthy": False,
        "status": "unavailable",
    }


# ---------------------------------------------------------------------------
# Error and payload helpers
# ---------------------------------------------------------------------------

def _service_unavailable(route: str) -> RouteResponse:
    return RouteResponse(
        ok=False,
        status="service_unavailable",
        route=route,
        data={
            "dependency": "library.services.library_generator_workflow_service or library.services.library_create_service",
            "available": False,
            "route_plan": get_route_plan(),
            "generator_workflow_health": _safe_generator_workflow_health(),
            "create_service_health": _safe_create_service_health(),
        },
        errors=[
            _error(
                "service_unavailable",
                "Generator workflow service and legacy create service are unavailable.",
                field="generator_workflow",
                details={
                    "generator_workflow": _safe_generator_workflow_health(),
                    "create_service": _safe_create_service_health(),
                },
            )
        ],
        http_status=503,
    )


def _failure(
    *,
    route: str,
    code: str,
    message: str,
    exc: BaseException | None = None,
    http_status: int = 500,
) -> RouteResponse:
    if exc is not None:
        errors = [
            _exception_issue(
                code,
                exc,
                field=route,
                fallback_message=message,
            )
        ]
    else:
        errors = [_error(code, message, field=route)]

    return RouteResponse(
        ok=False,
        status=code,
        route=route,
        data={
            "route_service": _route_service_metadata(route),
        },
        errors=errors,
        http_status=http_status,
    )


def _definitions_unavailable_payload(
    *,
    reason: str,
    exc: BaseException | None = None,
) -> dict[str, Any]:
    return {
        "available": False,
        "ok": False,
        "healthy": False,
        "status": "unavailable",
        "component": "definitions",
        "reason": reason,
        "error": _exception_payload(exc) if exc is not None else None,
    }


def _exception_payload(exc: BaseException | None) -> dict[str, Any]:
    if exc is None:
        return {}

    payload: dict[str, Any] = {
        "type": type(exc).__name__,
        "message": str(exc),
    }

    try:
        payload["traceback"] = traceback.format_exception(type(exc), exc, exc.__traceback__)
    except Exception:
        pass

    return payload


def _binary_from_route_response(response: RouteResponse) -> RouteBinaryResponse:
    return RouteBinaryResponse(
        ok=False,
        status=response.status,
        route=response.route,
        filename="invalid.vplib",
        content=b"",
        data=response.data,
        errors=response.errors,
        warnings=response.warnings,
        info=response.info,
        http_status=response.http_status,
    )


def _issue_to_dict(issue: RouteIssue | Mapping[str, Any] | Any) -> dict[str, Any]:
    if isinstance(issue, RouteIssue):
        return issue.to_dict()

    if isinstance(issue, Mapping):
        severity = str(issue.get("severity") or "error")
        code = str(issue.get("code") or issue.get("type") or "issue")
        message = str(issue.get("message") or issue.get("text") or issue.get("detail") or "")
        field = str(issue.get("field") or issue.get("field_key") or "")
        details_raw = issue.get("details", {})
        details = dict(details_raw) if isinstance(details_raw, Mapping) else {}

        payload = {
            "severity": severity,
            "code": code,
            "message": message,
        }
        if field:
            payload["field"] = field
        if details:
            payload["details"] = _json_safe(details)
        return payload

    return {
        "severity": "error",
        "code": "issue",
        "message": str(issue),
    }


def _coerce_issue_list(value: Any) -> list[dict[str, Any]]:
    if value is None:
        return []

    if isinstance(value, Mapping):
        return [_issue_to_dict(value)]

    if isinstance(value, (list, tuple, set)):
        return [_issue_to_dict(item) for item in value]

    return [_issue_to_dict(value)]


def _error(
    code: str,
    message: str,
    *,
    field: str = "",
    details: dict[str, Any] | None = None,
) -> RouteIssue:
    return RouteIssue(
        severity="error",
        code=code,
        message=message,
        field=field,
        details=details or {},
    )


def _warning(
    code: str,
    message: str,
    *,
    field: str = "",
    details: dict[str, Any] | None = None,
) -> RouteIssue:
    return RouteIssue(
        severity="warning",
        code=code,
        message=message,
        field=field,
        details=details or {},
    )


def _info(
    code: str,
    message: str,
    *,
    field: str = "",
    details: dict[str, Any] | None = None,
) -> RouteIssue:
    return RouteIssue(
        severity="info",
        code=code,
        message=message,
        field=field,
        details=details or {},
    )


def _exception_issue(
    code: str,
    exc: BaseException | None,
    *,
    field: str = "",
    fallback_message: str = "",
) -> RouteIssue:
    if exc is None:
        return _error(
            code,
            fallback_message or "Unknown error.",
            field=field,
            details={"exception": None},
        )

    return _error(
        code,
        fallback_message or str(exc) or type(exc).__name__,
        field=field,
        details=_exception_payload(exc),
    )


def _exception_warning(
    code: str,
    exc: BaseException | None,
    *,
    field: str = "",
    fallback_message: str = "",
) -> RouteIssue:
    if exc is None:
        return _warning(
            code,
            fallback_message or "Unknown warning.",
            field=field,
            details={"exception": None},
        )

    return _warning(
        code,
        fallback_message or str(exc) or type(exc).__name__,
        field=field,
        details=_exception_payload(exc),
    )


# ---------------------------------------------------------------------------
# VPLIB UID helpers
# ---------------------------------------------------------------------------

def _extract_vplib_uid_from_any(value: Any, *, _depth: int = 0) -> str | None:
    """Extract a valid `vplib_uid` from mappings, results or nested payloads."""
    if value is None or _depth > 7:
        return None

    direct = _normalize_vplib_uid_safe(value)
    if direct:
        return direct

    if isinstance(value, Mapping):
        for key in VPLIB_UID_KEYS:
            if key in value:
                uid = _normalize_vplib_uid_safe(value.get(key))
                if uid:
                    return uid

        for nested_key in (
            "data",
            "metadata",
            "payload",
            "request",
            "result",
            "workflow",
            "draft",
            "draft_payload",
            "validation_payload",
            "package_plan_payload",
            "download_payload",
            "save_payload",
            "persistent_draft_payload",
            "publish_prepare_payload",
            "publish_payload",
            "sync_payload",
            "manifest",
            "vplib_manifest",
            "document_bundle",
            "creation_result",
            "package_result",
            "route_service",
            "publish",
        ):
            nested = value.get(nested_key)
            uid = _extract_vplib_uid_from_any(nested, _depth=_depth + 1)
            if uid:
                return uid

        if "vplib.manifest.json" in value:
            uid = _extract_vplib_uid_from_any(value.get("vplib.manifest.json"), _depth=_depth + 1)
            if uid:
                return uid

        return None

    for attr_name in VPLIB_UID_KEYS:
        try:
            attr_value = _safe_getattr(value, attr_name)
            if attr_value is not None:
                uid = _normalize_vplib_uid_safe(attr_value)
                if uid:
                    return uid
        except Exception:
            continue

    for nested_attr in (
        "data",
        "metadata",
        "payload",
        "result",
        "workflow",
        "draft",
        "manifest",
        "vplib_manifest",
        "document_bundle",
        "creation_result",
        "package_result",
        "route_service",
        "publish",
    ):
        try:
            nested = getattr(value, nested_attr, None)
            uid = _extract_vplib_uid_from_any(nested, _depth=_depth + 1)
            if uid:
                return uid
        except Exception:
            continue

    to_dict = _safe_getattr(value, "to_dict")
    if callable(to_dict):
        try:
            payload = to_dict()
            uid = _extract_vplib_uid_from_any(payload, _depth=_depth + 1)
            if uid:
                return uid
        except Exception:
            pass

    return None


def _normalize_vplib_uid_safe(value: Any) -> str | None:
    """Normalize VPLIB UID defensively."""
    if value is None:
        return None

    if isinstance(value, Mapping):
        return None

    if isinstance(value, (list, tuple, set)):
        return None

    text = str(value).strip()
    if not text:
        return None

    try:
        if _is_variant_payload_service_available():
            normalizer = getattr(_variant_payload_service(), "normalize_vplib_uid_safe", None)
            if callable(normalizer):
                uid = normalizer(value)
                if uid:
                    return str(uid)
    except Exception:
        pass

    for import_path in (
        "vplib.vplib_id_service",
        "src.vplib.vplib_id_service",
        "vectoplan_library.vplib.vplib_id_service",
        "vectoplan_library.src.vplib.vplib_id_service",
    ):
        try:
            module = importlib.import_module(import_path)
            normalizer = getattr(module, "normalize_vplib_uid", None)
            if callable(normalizer):
                uid = normalizer(value)
                if uid:
                    return str(uid)
        except Exception:
            continue

    try:
        parsed = uuid.UUID(text)
        return str(parsed).lower()
    except Exception:
        return None


# ---------------------------------------------------------------------------
# Primitive helpers
# ---------------------------------------------------------------------------

def _normalize_mapping_payload(payload: Mapping[str, Any]) -> dict[str, Any]:
    """Normalize mappings without destroying intentional one-item arrays.

    Only MultiDict-like request objects need scalar collapsing through
    ``getlist``. Plain dictionaries already express the caller's intended
    shape, so lists such as ``_binary_assets`` and ``definition_variants`` must
    stay lists even when they contain exactly one item.
    """

    normalized: dict[str, Any] = {}
    getlist = getattr(payload, "getlist", None)
    is_multidict = callable(getlist)

    for key, value in payload.items():
        key_text = str(key)

        if is_multidict:
            try:
                values = getlist(key)
                if len(values) == 1:
                    normalized[key_text] = values[0]
                elif len(values) > 1:
                    normalized[key_text] = list(values)
                else:
                    normalized[key_text] = value
                continue
            except Exception:
                pass

        if isinstance(value, (list, tuple)):
            normalized[key_text] = list(value)
        else:
            normalized[key_text] = value

    return normalized


def _extract_overwrite(payload: Mapping[str, Any]) -> bool | None:
    for key in ("overwrite", "allow_overwrite", "replace_existing"):
        if key in payload:
            return _safe_bool(payload.get(key), default=False)
    return None


def _coerce_list(value: Any) -> list[Any]:
    if value is None:
        return []

    if isinstance(value, list):
        return value

    if isinstance(value, tuple):
        return list(value)

    if isinstance(value, set):
        return list(value)

    if isinstance(value, Mapping):
        return [dict(value)]

    return [value]


def _first_option_id(value: Any) -> str:
    items = _coerce_list(value)
    if not items:
        return ""

    first = items[0]
    if isinstance(first, Mapping):
        return str(first.get("id") or first.get("value") or first.get("key") or "").strip()

    return str(first or "").strip()


def _first_non_empty(*values: Any) -> Any:
    for value in values:
        if value is None:
            continue
        if isinstance(value, str) and not value.strip():
            continue
        if isinstance(value, (dict, list, tuple, set)) and not value:
            continue
        return value
    return None


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


def _safe_int(value: Any, *, default: int = 0) -> int:
    try:
        return int(value)
    except Exception:
        return default


def _safe_http_status(value: Any) -> int:
    try:
        status = int(value)
    except Exception:
        status = 500

    if status < 100:
        return 500

    if status > 599:
        return 500

    return status


def _safe_download_filename(filename: Any) -> str:
    raw = str(filename or "package.vplib").strip()
    raw = raw.replace("\\", "/").split("/")[-1]
    raw = raw.replace("\x00", "")

    if not raw:
        raw = "package.vplib"

    if not raw.endswith(".vplib"):
        raw = f"{raw}.vplib"

    cleaned = []
    for char in raw:
        if char.isalnum() or char in {"-", "_", ".", " "}:
            cleaned.append(char)
        else:
            cleaned.append("_")

    result = "".join(cleaned).strip(" ._")
    if not result:
        result = "package.vplib"

    if not result.endswith(".vplib"):
        result = f"{result}.vplib"

    return result[:180]


def _normalize_slug_fallback(value: Any, *, default: str = "") -> str:
    raw = str(value or "").strip().lower()
    if not raw:
        return default

    replacements = {
        "ä": "ae",
        "ö": "oe",
        "ü": "ue",
        "ß": "ss",
    }

    for source, target in replacements.items():
        raw = raw.replace(source, target)

    cleaned = []
    previous_separator = False

    for char in raw:
        if char.isalnum():
            cleaned.append(char)
            previous_separator = False
        else:
            if not previous_separator:
                cleaned.append("_")
                previous_separator = True

    result = "".join(cleaned).strip("_-")
    return result or default


def _json_safe(value: Any, *, _depth: int = 0) -> Any:
    if _depth > 40:
        return str(value)

    if _is_undefined_like(value):
        return None

    if value is None or isinstance(value, (str, int, float, bool)):
        return value

    if isinstance(value, bytes):
        return {
            "type": "bytes",
            "size_bytes": len(value),
        }

    if isinstance(value, Enum):
        return _json_safe(value.value, _depth=_depth + 1)

    if isinstance(value, RouteIssue):
        return value.to_dict()

    if isinstance(value, Mapping):
        safe_mapping: dict[str, Any] = {}
        for key, inner_value in value.items():
            if _is_undefined_like(key):
                continue
            key_text = str(key)
            safe_mapping[key_text] = _json_safe(inner_value, _depth=_depth + 1)
        return safe_mapping

    if isinstance(value, (list, tuple, set)):
        return [_json_safe(item, _depth=_depth + 1) for item in value]

    if is_dataclass_like(value):
        return _json_safe(_dataclass_like_to_dict(value), _depth=_depth + 1)

    to_dict = _safe_getattr(value, "to_dict")
    if callable(to_dict):
        for kwargs in (
            {"include_http_status": True},
            {"include_payloads": True},
            {"include_context": True},
            {},
        ):
            try:
                return _json_safe(to_dict(**kwargs), _depth=_depth + 1)
            except TypeError:
                continue
            except Exception:
                break

    as_dict = _safe_getattr(value, "as_dict")
    if callable(as_dict):
        try:
            return _json_safe(as_dict(), _depth=_depth + 1)
        except Exception:
            pass

    isoformat = _safe_getattr(value, "isoformat")
    if callable(isoformat):
        try:
            return isoformat()
        except Exception:
            pass

    try:
        json.dumps(value)
        return value
    except Exception:
        return str(value)


def _json_safe_dict(value: Any) -> dict[str, Any]:
    payload = _json_safe(value)
    if isinstance(payload, Mapping):
        return dict(payload)
    if payload is None:
        return {}
    return {"value": payload}


def _json_safe_issue_list(value: Any) -> list[dict[str, Any]]:
    if value is None:
        return []

    if isinstance(value, Mapping) or isinstance(value, RouteIssue):
        return [_issue_to_dict(_json_safe(value))]

    if isinstance(value, (list, tuple, set)):
        return [_issue_to_dict(_json_safe(item)) for item in value]

    return [_issue_to_dict(_json_safe(value))]


def _safe_getattr(value: Any, name: str, default: Any = None) -> Any:
    try:
        return getattr(value, name)
    except Exception:
        return default


def _is_undefined_like(value: Any) -> bool:
    if value is None:
        return False

    try:
        value_type = type(value)
        type_name = value_type.__name__.lower()
        module_name = getattr(value_type, "__module__", "").lower()
    except Exception:
        return False

    if "undefined" in type_name and "jinja" in module_name:
        return True

    if type_name in {"undefined", "strictundefined", "chainableundefined", "debugundefined"}:
        return True

    return False

def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z")


def _extract_nested(payload: Mapping[str, Any], path: str, *, default: Any = None) -> Any:
    current: Any = payload
    for part in path.split("."):
        if not isinstance(current, Mapping):
            return default
        current = current.get(part)
        if current is None:
            return default
    return current


def is_dataclass_like(value: Any) -> bool:
    try:
        return hasattr(value, "__dataclass_fields__")
    except Exception:
        return False


def _dataclass_like_to_dict(value: Any) -> dict[str, Any]:
    result: dict[str, Any] = {}
    try:
        for field_name in getattr(value, "__dataclass_fields__", {}).keys():
            result[field_name] = getattr(value, field_name)
    except Exception:
        return {}
    return result


def _safe_normalize_payload_for_response(payload: Any, *, route: str) -> dict[str, Any] | RouteResponse:
    try:
        return normalize_payload(payload)
    except Exception as exc:
        return _failure(
            route=route,
            code="payload_normalization_failed",
            message="Payload could not be normalized.",
            exc=exc,
            http_status=400,
        )



def _extract_binary_download_payload(
    payload: Mapping[str, Any],
) -> tuple[str, bytes, dict[str, Any]] | None:
    """Recursively extract direct binary archive content from workflow output."""
    seen: set[int] = set()

    def walk(value: Any, depth: int) -> tuple[str, bytes, dict[str, Any]] | None:
        if value is None or depth > DEFAULT_MAX_BINARY_NESTING:
            return None

        identity = id(value)
        if identity in seen:
            return None
        seen.add(identity)

        if isinstance(value, Mapping):
            candidate = dict(value)
            content_keys = (
                "content",
                "bytes",
                "archive_bytes",
                "archiveBytes",
                "binary",
                "body",
                "content_base64",
                "contentBase64",
                "archive_base64",
                "archiveBase64",
            )
            for key in content_keys:
                if key not in candidate:
                    continue
                content = _coerce_binary_content(
                    candidate.get(key),
                    key_hint=key,
                )
                if content is None:
                    continue
                filename = (
                    candidate.get("filename")
                    or candidate.get("download_filename")
                    or candidate.get("downloadFilename")
                    or candidate.get("archive_filename")
                    or candidate.get("archiveFilename")
                    or "package.vplib"
                )
                return str(filename), content, candidate

            for key in (
                "download_payload",
                "downloadPayload",
                "payload",
                "result",
                "data",
                "archive",
                "binary_response",
                "binaryResponse",
                "response",
            ):
                nested = candidate.get(key)
                result = walk(nested, depth + 1)
                if result is not None:
                    return result

            return None

        if isinstance(value, (list, tuple)):
            for item in value:
                result = walk(item, depth + 1)
                if result is not None:
                    return result
            return None

        content = _coerce_binary_content(value)
        if content is not None:
            return "package.vplib", content, {"source": type(value).__name__}

        return None

    return walk(payload, 0)

# ---------------------------------------------------------------------------
# Cache helpers
# ---------------------------------------------------------------------------

def clear_library_create_route_service_caches() -> dict[str, Any]:
    """Clear lazy import caches held by this module."""
    cleared: list[str] = []

    for cached_func in (
        _load_generator_context_service_module,
        _load_generator_workflow_service_module,
        _load_generator_diagnostics_service_module,
        _load_create_service_module,
        _load_variant_payload_service_module,
        _load_taxonomy_module,
        _load_definition_catalog_service_module,
        _load_legacy_definitions_module,
        _stable_starter_uid_from_fingerprint,
    ):
        try:
            cached_func.cache_clear()
            cleared.append(getattr(cached_func, "__name__", str(cached_func)))
        except Exception:
            continue

    return {
        "ok": True,
        "cleared": cleared,
    }


# ---------------------------------------------------------------------------
# Public exports
# ---------------------------------------------------------------------------

__all__ = [
    "CREATE_API_PREFIX",
    "CREATE_PAGE_ROUTE",
    "DEFAULT_JSON_MIMETYPE",
    "DEFAULT_VPLIB_MIMETYPE",
    "GENERATOR_ROUTE_SERVICE_FEATURES",
    "LIBRARY_CREATE_ROUTE_SERVICE_COMPONENT",
    "LIBRARY_CREATE_ROUTE_SERVICE_VERSION",
    "TAXONOMY_REQUIRED_FIELDS",
    "VPLIB_UID_FIELD",
    "VPLIB_UID_KEYS",
    "STARTER_OBJECT_KIND",
    "STARTER_FAMILY_PROFILE_ID",
    "STARTER_VARIANT_PROFILE_ID",
    "STARTER_DEFAULT_VARIANT_ID",
    "STARTER_DEFAULT_LABEL",
    "STARTER_DIMENSIONS_MM",
    "DEFAULT_MAX_ARCHIVE_BYTES",
    "DEFAULT_MAX_ARCHIVE_ENTRIES",
    "DEFAULT_MAX_ARCHIVE_UNCOMPRESSED_BYTES",

    # Errors
    "LibraryCreateRouteServiceError",
    "CreatePayloadContractError",
    "CreateArchiveContractError",

    # Dataclasses
    "RouteBinaryResponse",
    "RouteIssue",
    "RouteResponse",

    # Public responses
    "get_route_plan",
    "get_route_service_health",
    "get_options_response",
    "get_create_context_response",
    "get_template_context_response",
    "get_current_definitions_response",
    "build_draft_response",
    "validate_draft_response",
    "build_package_plan_response",
    "build_persistent_draft_payload_response",
    "build_publish_bundle_response",
    "save_package_response",
    "build_download_response",
    "clear_cache_response",

    # Utilities
    "normalize_payload",
    "merge_payloads",
    "sanitize_template_context",
    "response_to_tuple",
    "binary_response_to_meta_tuple",
    "validate_vplib_archive",
    "clear_library_create_route_service_caches",

    # Aliases
    "health",
    "options",
    "create_context",
    "template_context",
    "definitions_current",
    "draft",
    "validate",
    "package_plan",
    "persistent_draft_payload",
    "publish_bundle",
    "download",
    "save",
    "cache_clear",
]
