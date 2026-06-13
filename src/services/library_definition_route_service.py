# services/vectoplan-library/src/services/library_definition_route_service.py
"""
HTTP-near route service for VECTOPLAN Library Definitions.

This module is the route-service layer for the new backend-owned definitions
API. It intentionally contains no Flask imports so it can be tested directly.

Planned route layer:
- src/routes/library_definition_routes.py

Route prefix:
- /api/v1/vplib/definitions

Primary responsibilities:
- parse query parameters defensively
- normalize payloads defensively
- call src.library.definitions service facade
- return JSON-ready dictionaries
- keep actual Flask route functions thin
- provide health/options/summary/payload/profile/resolve/validate/cache actions

This service is intentionally isolated from /create at first. The definitions
API should be tested green before /api/v1/vplib/create/options is extended.

Robustness note:
The package facade src.library.definitions is intentionally tolerant and evolves
file by file. This route service therefore calls facade functions through
_signature-aware helpers so unknown keyword arguments do not break endpoints.
"""

from __future__ import annotations

import inspect
import logging
from dataclasses import dataclass, field
from typing import Any, Callable, Dict, Mapping, Optional, Sequence


LIBRARY_DEFINITION_ROUTE_SERVICE_COMPONENT = "services.library_definition_route_service"
LIBRARY_DEFINITION_ROUTE_SERVICE_VERSION = "0.1.1"

DEFAULT_LANGUAGE = "de"

_LOGGER = logging.getLogger(__name__)


@dataclass(frozen=True)
class LibraryDefinitionRouteRequestOptions:
    """
    Normalized options parsed from query params.

    The route layer may pass Flask request.args directly. This class keeps the
    service independent from Flask's concrete MultiDict implementation.
    """

    include_inactive: bool = False
    include_internal: bool = False
    include_extra: bool = True
    force_refresh: bool = False
    force_reload: bool = False
    strict_references: bool = True
    allow_missing_datasets: bool = True
    allow_empty_datasets: bool = True
    use_config_fallback: bool = True
    language: str = DEFAULT_LANGUAGE
    definitions_root: Optional[str] = None
    definitions_version: str = "v1"
    debug: bool = False
    raw_query: Dict[str, Any] = field(default_factory=dict)

    @classmethod
    def from_query(
        cls,
        query_params: Optional[Mapping[str, Any]] = None,
    ) -> "LibraryDefinitionRouteRequestOptions":
        query = _normalize_query_mapping(query_params)

        return cls(
            include_inactive=_get_bool(
                query,
                "include_inactive",
                "includeInactive",
                "inactive",
                default=False,
            ),
            include_internal=_get_bool(
                query,
                "include_internal",
                "includeInternal",
                "internal",
                default=False,
            ),
            include_extra=_get_bool(
                query,
                "include_extra",
                "includeExtra",
                "extra",
                default=True,
            ),
            force_refresh=_get_bool(
                query,
                "force_refresh",
                "forceRefresh",
                "refresh",
                default=False,
            ),
            force_reload=_get_bool(
                query,
                "force_reload",
                "forceReload",
                "reload",
                default=False,
            ),
            strict_references=_get_bool(
                query,
                "strict_references",
                "strictReferences",
                "strict",
                default=True,
            ),
            allow_missing_datasets=_get_bool(
                query,
                "allow_missing_datasets",
                "allowMissingDatasets",
                default=True,
            ),
            allow_empty_datasets=_get_bool(
                query,
                "allow_empty_datasets",
                "allowEmptyDatasets",
                default=True,
            ),
            use_config_fallback=_get_bool(
                query,
                "use_config_fallback",
                "useConfigFallback",
                default=True,
            ),
            language=_get_str(
                query,
                "language",
                "lang",
                default=DEFAULT_LANGUAGE,
            ),
            definitions_root=_get_optional_str(
                query,
                "definitions_root",
                "definitionsRoot",
                "root",
            ),
            definitions_version=_get_str(
                query,
                "definitions_version",
                "definitionsVersion",
                "version",
                default="v1",
            ),
            debug=_get_bool(
                query,
                "debug",
                default=False,
            ),
            raw_query=query,
        )

    def service_kwargs(self) -> Dict[str, Any]:
        """
        Keyword arguments that configure the definitions service.

        Do not include include_inactive/include_internal here. Those are
        endpoint payload flags and are passed explicitly where needed. Keeping
        them out prevents duplicate keyword errors.
        """
        return {
            "definitions_root": self.definitions_root,
            "definitions_version": self.definitions_version,
            "strict_references": self.strict_references,
            "allow_missing_datasets": self.allow_missing_datasets,
            "allow_empty_datasets": self.allow_empty_datasets,
            "use_config_fallback": self.use_config_fallback,
            "language": self.language,
        }

    def to_dict(self) -> Dict[str, Any]:
        return {
            "include_inactive": self.include_inactive,
            "include_internal": self.include_internal,
            "include_extra": self.include_extra,
            "force_refresh": self.force_refresh,
            "force_reload": self.force_reload,
            "strict_references": self.strict_references,
            "allow_missing_datasets": self.allow_missing_datasets,
            "allow_empty_datasets": self.allow_empty_datasets,
            "use_config_fallback": self.use_config_fallback,
            "language": self.language,
            "definitions_root": self.definitions_root,
            "definitions_version": self.definitions_version,
            "debug": self.debug,
        }


def get_library_definition_route_service_health(
    query_params: Optional[Mapping[str, Any]] = None,
) -> Dict[str, Any]:
    options = LibraryDefinitionRouteRequestOptions.from_query(query_params)
    definitions_api = _get_definitions_api()

    if not definitions_api.get("ok"):
        return _error_response(
            "definitions_import_failed",
            definitions_api.get("error") or "Could not import definitions API",
            options=options,
            status="unavailable",
        )

    try:
        call = _call_api_function(
            definitions_api["get_definitions_health"],
            force_refresh=options.force_refresh,
            force_reload=options.force_reload,
            **options.service_kwargs(),
        )

        if not call.get("ok"):
            return _error_response(
                "health_failed",
                call.get("error") or "Definitions health call failed",
                options=options,
                status="unavailable",
            )

        health = _as_mapping(call.get("value"))

        return _envelope(
            action="health",
            payload={
                "ok": bool(health.get("ok") or health.get("healthy")),
                "healthy": bool(health.get("healthy") or health.get("ok")),
                "status": health.get("status", "healthy" if health.get("ok") else "degraded"),
                "definitions": health,
            },
            options=options,
        )
    except Exception as exc:
        _LOGGER.exception("Definitions health route service failed")
        return _error_response(
            "health_failed",
            _format_exception(exc),
            options=options,
            status="unavailable",
        )


def get_library_definition_summary_response(
    query_params: Optional[Mapping[str, Any]] = None,
) -> Dict[str, Any]:
    options = LibraryDefinitionRouteRequestOptions.from_query(query_params)
    definitions_api = _get_definitions_api()

    if not definitions_api.get("ok"):
        return _error_response(
            "definitions_import_failed",
            definitions_api.get("error") or "Could not import definitions API",
            options=options,
            status="unavailable",
        )

    try:
        call = _call_api_function(
            definitions_api["get_definitions_summary"],
            force_refresh=options.force_refresh,
            force_reload=options.force_reload,
            **options.service_kwargs(),
        )

        if not call.get("ok"):
            return _error_response(
                "summary_failed",
                call.get("error") or "Definitions summary call failed",
                options=options,
                status="unavailable",
            )

        summary = _as_mapping(call.get("value"))

        return _envelope(
            action="summary",
            payload={
                "ok": bool(summary.get("ok", True)),
                "healthy": bool(summary.get("healthy", summary.get("ok", True))),
                "status": summary.get("status", "ok"),
                "summary": summary,
            },
            options=options,
        )
    except Exception as exc:
        _LOGGER.exception("Definitions summary route service failed")
        return _error_response(
            "summary_failed",
            _format_exception(exc),
            options=options,
            status="unavailable",
        )


def get_library_definition_options_response(
    query_params: Optional[Mapping[str, Any]] = None,
) -> Dict[str, Any]:
    """
    Return create-flow-ready definitions options.

    This is the safest first integration target for UI testing, but it should be
    exposed under /definitions/options before being merged into /create/options.
    """
    options = LibraryDefinitionRouteRequestOptions.from_query(query_params)
    definitions_api = _get_definitions_api()

    if not definitions_api.get("ok"):
        return _error_response(
            "definitions_import_failed",
            definitions_api.get("error") or "Could not import definitions API",
            options=options,
            status="unavailable",
        )

    try:
        call = _call_api_function(
            definitions_api["get_create_definition_options"],
            include_inactive=options.include_inactive,
            include_internal=options.include_internal,
            force_refresh=options.force_refresh,
            force_reload=options.force_reload,
            **options.service_kwargs(),
        )

        if not call.get("ok"):
            return _error_response(
                "options_failed",
                call.get("error") or "Definitions options call failed",
                options=options,
                status="unavailable",
            )

        payload = _as_mapping(call.get("value"))

        return _envelope(
            action="options",
            payload={
                "ok": bool(payload.get("ok", True)),
                "healthy": bool(payload.get("healthy", payload.get("ok", True))),
                "status": payload.get("status", "ok"),
                "data": payload,
            },
            options=options,
        )
    except Exception as exc:
        _LOGGER.exception("Definitions options route service failed")
        return _error_response(
            "options_failed",
            _format_exception(exc),
            options=options,
            status="unavailable",
        )


def get_library_definition_payload_response(
    query_params: Optional[Mapping[str, Any]] = None,
) -> Dict[str, Any]:
    """
    Return the full definitions payload.

    This endpoint is more verbose than /options and useful for debugging.
    """
    options = LibraryDefinitionRouteRequestOptions.from_query(query_params)
    definitions_api = _get_definitions_api()

    if not definitions_api.get("ok"):
        return _error_response(
            "definitions_import_failed",
            definitions_api.get("error") or "Could not import definitions API",
            options=options,
            status="unavailable",
        )

    try:
        call = _call_api_function(
            definitions_api["get_definitions_payload"],
            include_inactive=options.include_inactive,
            include_internal=options.include_internal,
            force_refresh=options.force_refresh,
            force_reload=options.force_reload,
            **options.service_kwargs(),
        )

        if not call.get("ok"):
            return _error_response(
                "payload_failed",
                call.get("error") or "Definitions payload call failed",
                options=options,
                status="unavailable",
            )

        payload = _as_mapping(call.get("value"))

        return _envelope(
            action="payload",
            payload={
                "ok": bool(payload.get("ok", True)),
                "healthy": bool(payload.get("healthy", payload.get("ok", True))),
                "status": payload.get("status", "ok"),
                "data": payload,
            },
            options=options,
        )
    except Exception as exc:
        _LOGGER.exception("Definitions payload route service failed")
        return _error_response(
            "payload_failed",
            _format_exception(exc),
            options=options,
            status="unavailable",
        )


def get_library_definition_variant_profile_response(
    profile_id: str,
    query_params: Optional[Mapping[str, Any]] = None,
) -> Dict[str, Any]:
    options = LibraryDefinitionRouteRequestOptions.from_query(query_params)
    definitions_api = _get_definitions_api()
    clean_profile_id = _clean_string(profile_id)

    if not clean_profile_id:
        return _error_response(
            "invalid_profile_id",
            "profile_id must not be empty",
            options=options,
            status="invalid_request",
        )

    if not definitions_api.get("ok"):
        return _error_response(
            "definitions_import_failed",
            definitions_api.get("error") or "Could not import definitions API",
            options=options,
            status="unavailable",
        )

    try:
        call = _call_api_function(
            definitions_api["get_variant_profile"],
            clean_profile_id,
            force_refresh=options.force_refresh,
            force_reload=options.force_reload,
            **options.service_kwargs(),
        )

        if not call.get("ok"):
            return _error_response(
                "variant_profile_failed",
                call.get("error") or "Definitions variant profile call failed",
                options=options,
                status="unavailable",
                extra={"profile_id": clean_profile_id},
            )

        payload = _as_mapping(call.get("value"))

        return _envelope(
            action="variant_profile",
            payload={
                "ok": bool(payload.get("ok", True)),
                "status": payload.get("status", "ok"),
                "profile_id": clean_profile_id,
                "data": payload,
            },
            options=options,
        )
    except Exception as exc:
        _LOGGER.exception("Definitions variant profile route service failed")
        return _error_response(
            "variant_profile_failed",
            _format_exception(exc),
            options=options,
            status="unavailable",
            extra={"profile_id": clean_profile_id},
        )


def resolve_library_definition_family_profile_response(
    query_params: Optional[Mapping[str, Any]] = None,
    payload: Optional[Mapping[str, Any]] = None,
) -> Dict[str, Any]:
    options = LibraryDefinitionRouteRequestOptions.from_query(query_params)
    context = _context_from_query_and_payload(options.raw_query, payload)
    definitions_api = _get_definitions_api()

    if not definitions_api.get("ok"):
        return _error_response(
            "definitions_import_failed",
            definitions_api.get("error") or "Could not import definitions API",
            options=options,
            status="unavailable",
            extra={"context": context},
        )

    try:
        call = _call_api_function(
            definitions_api["resolve_family_profile_for_context"],
            domain=context.get("domain"),
            category=context.get("category"),
            subcategory=context.get("subcategory"),
            object_kind=context.get("object_kind"),
            family_profile_id=context.get("family_profile_id"),
            force_refresh=options.force_refresh,
            force_reload=options.force_reload,
            **options.service_kwargs(),
        )

        if not call.get("ok"):
            return _error_response(
                "resolve_family_profile_failed",
                call.get("error") or "Definitions family profile resolution failed",
                options=options,
                status="unavailable",
                extra={"context": context},
            )

        result = _as_mapping(call.get("value"))

        return _envelope(
            action="resolve_family_profile",
            payload={
                "ok": bool(result.get("ok")),
                "status": result.get("status", "resolved" if result.get("ok") else "not_found"),
                "context": context,
                "data": result,
            },
            options=options,
        )
    except Exception as exc:
        _LOGGER.exception("Definitions family profile resolution failed")
        return _error_response(
            "resolve_family_profile_failed",
            _format_exception(exc),
            options=options,
            status="unavailable",
            extra={"context": context},
        )


def resolve_library_definition_variant_profile_response(
    query_params: Optional[Mapping[str, Any]] = None,
    payload: Optional[Mapping[str, Any]] = None,
) -> Dict[str, Any]:
    options = LibraryDefinitionRouteRequestOptions.from_query(query_params)
    context = _context_from_query_and_payload(options.raw_query, payload)
    definitions_api = _get_definitions_api()

    if not definitions_api.get("ok"):
        return _error_response(
            "definitions_import_failed",
            definitions_api.get("error") or "Could not import definitions API",
            options=options,
            status="unavailable",
            extra={"context": context},
        )

    try:
        call = _call_api_function(
            definitions_api["resolve_variant_profile_for_context"],
            domain=context.get("domain"),
            category=context.get("category"),
            subcategory=context.get("subcategory"),
            object_kind=context.get("object_kind"),
            family_profile_id=context.get("family_profile_id"),
            variant_profile_id=context.get("variant_profile_id"),
            force_refresh=options.force_refresh,
            force_reload=options.force_reload,
            **options.service_kwargs(),
        )

        if not call.get("ok"):
            return _error_response(
                "resolve_variant_profile_failed",
                call.get("error") or "Definitions variant profile resolution failed",
                options=options,
                status="unavailable",
                extra={"context": context},
            )

        result = _as_mapping(call.get("value"))

        return _envelope(
            action="resolve_variant_profile",
            payload={
                "ok": bool(result.get("ok")),
                "status": result.get("status", "resolved" if result.get("ok") else "not_found"),
                "context": context,
                "data": result,
            },
            options=options,
        )
    except Exception as exc:
        _LOGGER.exception("Definitions variant profile resolution failed")
        return _error_response(
            "resolve_variant_profile_failed",
            _format_exception(exc),
            options=options,
            status="unavailable",
            extra={"context": context},
        )


def build_empty_library_definition_variant_values_response(
    profile_id: Optional[str] = None,
    query_params: Optional[Mapping[str, Any]] = None,
    payload: Optional[Mapping[str, Any]] = None,
) -> Dict[str, Any]:
    options = LibraryDefinitionRouteRequestOptions.from_query(query_params)
    body = _copy_mapping(payload)
    clean_profile_id = (
        _clean_string(profile_id)
        or _get_str(options.raw_query, "variant_profile_id", "profile_id", default="")
        or _clean_string(body.get("variant_profile_id") or body.get("profile_id"))
    )

    if not clean_profile_id:
        return _error_response(
            "invalid_variant_profile_id",
            "variant_profile_id must not be empty",
            options=options,
            status="invalid_request",
        )

    definitions_api = _get_definitions_api()
    if not definitions_api.get("ok"):
        return _error_response(
            "definitions_import_failed",
            definitions_api.get("error") or "Could not import definitions API",
            options=options,
            status="unavailable",
            extra={"variant_profile_id": clean_profile_id},
        )

    try:
        call = _call_api_function(
            definitions_api["build_empty_variant_values"],
            variant_profile_id=clean_profile_id,
            force_refresh=options.force_refresh,
            force_reload=options.force_reload,
            **options.service_kwargs(),
        )

        if not call.get("ok"):
            return _error_response(
                "empty_variant_values_failed",
                call.get("error") or "Definitions empty variant values call failed",
                options=options,
                status="unavailable",
                extra={"variant_profile_id": clean_profile_id},
            )

        result = _as_mapping(call.get("value"))

        return _envelope(
            action="empty_variant_values",
            payload={
                "ok": bool(result.get("ok")),
                "status": result.get("status", "ok" if result.get("ok") else "not_found"),
                "variant_profile_id": clean_profile_id,
                "data": result,
            },
            options=options,
        )
    except Exception as exc:
        _LOGGER.exception("Definitions empty variant values failed")
        return _error_response(
            "empty_variant_values_failed",
            _format_exception(exc),
            options=options,
            status="unavailable",
            extra={"variant_profile_id": clean_profile_id},
        )


def validate_library_definition_variant_response(
    payload: Optional[Mapping[str, Any]] = None,
    query_params: Optional[Mapping[str, Any]] = None,
) -> Dict[str, Any]:
    """
    Validate a variant-drawer payload.

    Accepted payload shapes:
    {
      "variant_profile_id": "wall_masonry_product.v1",
      "values": {...},
      "documents": [...],
      "manufacturer_reference": {...}
    }

    or:

    {
      "variant": {
        "variant_profile_id": "...",
        "values": {...}
      }
    }
    """
    options = LibraryDefinitionRouteRequestOptions.from_query(query_params)
    body = _copy_mapping(payload)
    variant = _copy_mapping(body.get("variant")) if isinstance(body.get("variant"), Mapping) else {}

    variant_profile_id = (
        _clean_string(body.get("variant_profile_id"))
        or _clean_string(body.get("profile_id"))
        or _clean_string(variant.get("variant_profile_id"))
        or _clean_string(variant.get("profile_id"))
        or _get_str(options.raw_query, "variant_profile_id", "profile_id", default="")
    )

    if not variant_profile_id:
        return _error_response(
            "invalid_variant_profile_id",
            "variant_profile_id is required",
            options=options,
            status="invalid_request",
        )

    values = body.get("values")
    if not isinstance(values, Mapping):
        values = variant.get("values")

    documents = body.get("documents")
    if documents is None:
        documents = variant.get("documents")

    manufacturer_reference = (
        body.get("manufacturer_reference")
        or body.get("manufacturer")
        or variant.get("manufacturer_reference")
        or variant.get("manufacturer")
    )

    definitions_api = _get_definitions_api()
    if not definitions_api.get("ok"):
        return _error_response(
            "definitions_import_failed",
            definitions_api.get("error") or "Could not import definitions API",
            options=options,
            status="unavailable",
            extra={"variant_profile_id": variant_profile_id},
        )

    try:
        call = _call_api_function(
            definitions_api["validate_variant_values"],
            variant_profile_id=variant_profile_id,
            values=values if isinstance(values, Mapping) else {},
            documents=documents if isinstance(documents, list) else [],
            manufacturer_reference=manufacturer_reference
            if isinstance(manufacturer_reference, Mapping)
            else {},
            force_refresh=options.force_refresh,
            force_reload=options.force_reload,
            **options.service_kwargs(),
        )

        if not call.get("ok"):
            return _error_response(
                "validate_variant_failed",
                call.get("error") or "Definitions variant validation call failed",
                options=options,
                status="unavailable",
                extra={"variant_profile_id": variant_profile_id},
            )

        result = _as_mapping(call.get("value"))

        return _envelope(
            action="validate_variant",
            payload={
                "ok": bool(result.get("ok")),
                "valid": bool(result.get("valid")),
                "status": result.get("status", "valid" if result.get("valid") else "invalid"),
                "variant_profile_id": variant_profile_id,
                "data": result,
            },
            options=options,
        )
    except Exception as exc:
        _LOGGER.exception("Definitions variant validation failed")
        return _error_response(
            "validate_variant_failed",
            _format_exception(exc),
            options=options,
            status="unavailable",
            extra={"variant_profile_id": variant_profile_id},
        )


def clear_library_definition_cache_response(
    query_params: Optional[Mapping[str, Any]] = None,
) -> Dict[str, Any]:
    options = LibraryDefinitionRouteRequestOptions.from_query(query_params)
    definitions_api = _get_definitions_api()

    if not definitions_api.get("ok"):
        return _error_response(
            "definitions_import_failed",
            definitions_api.get("error") or "Could not import definitions API",
            options=options,
            status="unavailable",
        )

    try:
        call = _call_api_function(definitions_api["clear_definitions_caches"])

        if not call.get("ok"):
            return _error_response(
                "cache_clear_failed",
                call.get("error") or "Definitions cache clear call failed",
                options=options,
                status="unavailable",
            )

        result = _as_mapping(call.get("value"))

        return _envelope(
            action="cache_clear",
            payload={
                "ok": bool(result.get("ok", True)),
                "status": result.get("status", "cleared"),
                "data": result,
            },
            options=options,
        )
    except Exception as exc:
        _LOGGER.exception("Definitions cache clear failed")
        return _error_response(
            "cache_clear_failed",
            _format_exception(exc),
            options=options,
            status="unavailable",
        )


def get_library_definition_route_map_response(
    query_params: Optional[Mapping[str, Any]] = None,
) -> Dict[str, Any]:
    options = LibraryDefinitionRouteRequestOptions.from_query(query_params)
    routes = [
        {
            "method": "GET",
            "path": "/api/v1/vplib/definitions/health",
            "action": "health",
        },
        {
            "method": "GET",
            "path": "/api/v1/vplib/definitions/summary",
            "action": "summary",
        },
        {
            "method": "GET",
            "path": "/api/v1/vplib/definitions/options",
            "action": "options",
        },
        {
            "method": "GET",
            "path": "/api/v1/vplib/definitions/payload",
            "action": "payload",
        },
        {
            "method": "GET",
            "path": "/api/v1/vplib/definitions/variant-profiles/<profile_id>",
            "action": "variant_profile",
        },
        {
            "method": "GET|POST",
            "path": "/api/v1/vplib/definitions/resolve-family-profile",
            "action": "resolve_family_profile",
        },
        {
            "method": "GET|POST",
            "path": "/api/v1/vplib/definitions/resolve-variant-profile",
            "action": "resolve_variant_profile",
        },
        {
            "method": "GET|POST",
            "path": "/api/v1/vplib/definitions/empty-variant-values/<profile_id>",
            "action": "empty_variant_values",
        },
        {
            "method": "POST",
            "path": "/api/v1/vplib/definitions/validate-variant",
            "action": "validate_variant",
        },
        {
            "method": "POST",
            "path": "/api/v1/vplib/definitions/cache/clear",
            "action": "cache_clear",
        },
    ]

    return _envelope(
        action="routes",
        payload={
            "ok": True,
            "status": "ok",
            "route_prefix": "/api/v1/vplib/definitions",
            "routes": routes,
        },
        options=options,
    )


def _get_definitions_api() -> Dict[str, Any]:
    """
    Lazy import definitions facade.

    Supports both common import modes:
    - from src.library import definitions
    - from ..library import definitions
    """
    try:
        from src.library import definitions as definitions_api  # type: ignore
    except Exception as absolute_exc:
        try:
            from ..library import definitions as definitions_api  # type: ignore
        except Exception as relative_exc:
            return {
                "ok": False,
                "error": (
                    "Could not import src.library.definitions. "
                    f"absolute={_format_exception(absolute_exc)}; "
                    f"relative={_format_exception(relative_exc)}"
                ),
            }

    required_functions = (
        "get_definitions_health",
        "get_definitions_summary",
        "get_definitions_payload",
        "get_create_definition_options",
        "resolve_family_profile_for_context",
        "resolve_variant_profile_for_context",
        "get_variant_profile",
        "build_empty_variant_values",
        "validate_variant_values",
        "clear_definitions_caches",
    )

    missing = [
        name
        for name in required_functions
        if not callable(getattr(definitions_api, name, None))
    ]

    if missing:
        return {
            "ok": False,
            "error": f"Definitions API missing callables: {', '.join(missing)}",
        }

    return {
        "ok": True,
        **{
            name: getattr(definitions_api, name)
            for name in required_functions
        },
    }


def _call_api_function(
    func: Callable[..., Any],
    *args: Any,
    **kwargs: Any,
) -> Dict[str, Any]:
    """
    Call a definitions facade function while filtering unsupported kwargs.

    This keeps routes stable while the package facade evolves.
    """
    safe_kwargs = _filter_supported_kwargs(func, kwargs)

    try:
        return {
            "ok": True,
            "value": func(*args, **safe_kwargs),
            "error": None,
        }
    except TypeError as exc:
        if safe_kwargs:
            try:
                return {
                    "ok": True,
                    "value": func(*args),
                    "error": None,
                    "primary_error": _format_exception(exc),
                    "fallback": "called_without_kwargs",
                }
            except Exception as fallback_exc:
                return {
                    "ok": False,
                    "value": None,
                    "error": _format_exception(fallback_exc),
                    "primary_error": _format_exception(exc),
                }

        return {
            "ok": False,
            "value": None,
            "error": _format_exception(exc),
        }
    except Exception as exc:
        return {
            "ok": False,
            "value": None,
            "error": _format_exception(exc),
        }


def _filter_supported_kwargs(func: Callable[..., Any], kwargs: Mapping[str, Any]) -> Dict[str, Any]:
    if not kwargs:
        return {}

    try:
        signature = inspect.signature(func)
    except (TypeError, ValueError):
        return dict(kwargs)

    for parameter in signature.parameters.values():
        if parameter.kind == inspect.Parameter.VAR_KEYWORD:
            return dict(kwargs)

    supported_names = set(signature.parameters.keys())
    return {
        key: value
        for key, value in kwargs.items()
        if key in supported_names
    }


def _context_from_query_and_payload(
    query: Optional[Mapping[str, Any]],
    payload: Optional[Mapping[str, Any]],
) -> Dict[str, Optional[str]]:
    body = _copy_mapping(payload)
    context = _copy_mapping(body.get("context")) if isinstance(body.get("context"), Mapping) else {}

    return {
        "domain": (
            _get_optional_str(query, "domain")
            or _clean_optional_string(body.get("domain"))
            or _clean_optional_string(context.get("domain"))
        ),
        "category": (
            _get_optional_str(query, "category")
            or _clean_optional_string(body.get("category"))
            or _clean_optional_string(context.get("category"))
        ),
        "subcategory": (
            _get_optional_str(query, "subcategory", "sub_category", "subCategory")
            or _clean_optional_string(body.get("subcategory"))
            or _clean_optional_string(body.get("sub_category"))
            or _clean_optional_string(context.get("subcategory"))
            or _clean_optional_string(context.get("sub_category"))
        ),
        "object_kind": (
            _get_optional_str(query, "object_kind", "objectKind")
            or _clean_optional_string(body.get("object_kind"))
            or _clean_optional_string(body.get("objectKind"))
            or _clean_optional_string(context.get("object_kind"))
            or _clean_optional_string(context.get("objectKind"))
        ),
        "family_profile_id": (
            _get_optional_str(query, "family_profile_id", "familyProfileId", "family_profile")
            or _clean_optional_string(body.get("family_profile_id"))
            or _clean_optional_string(body.get("familyProfileId"))
            or _clean_optional_string(body.get("family_profile"))
            or _clean_optional_string(context.get("family_profile_id"))
            or _clean_optional_string(context.get("familyProfileId"))
            or _clean_optional_string(context.get("family_profile"))
        ),
        "variant_profile_id": (
            _get_optional_str(query, "variant_profile_id", "variantProfileId", "variant_profile")
            or _clean_optional_string(body.get("variant_profile_id"))
            or _clean_optional_string(body.get("variantProfileId"))
            or _clean_optional_string(body.get("variant_profile"))
            or _clean_optional_string(context.get("variant_profile_id"))
            or _clean_optional_string(context.get("variantProfileId"))
            or _clean_optional_string(context.get("variant_profile"))
        ),
    }


def _envelope(
    *,
    action: str,
    payload: Mapping[str, Any],
    options: LibraryDefinitionRouteRequestOptions,
) -> Dict[str, Any]:
    ok = bool(payload.get("ok", True))
    status = payload.get("status") or ("ok" if ok else "error")

    response = {
        "ok": ok,
        "status": status,
        "component": LIBRARY_DEFINITION_ROUTE_SERVICE_COMPONENT,
        "version": LIBRARY_DEFINITION_ROUTE_SERVICE_VERSION,
        "action": action,
        **dict(payload),
    }

    if options.debug:
        response["request_options"] = options.to_dict()
        response["raw_query"] = dict(options.raw_query)

    return response


def _error_response(
    code: str,
    message: str,
    *,
    options: LibraryDefinitionRouteRequestOptions,
    status: str = "error",
    extra: Optional[Mapping[str, Any]] = None,
) -> Dict[str, Any]:
    payload: Dict[str, Any] = {
        "ok": False,
        "healthy": False,
        "status": status,
        "component": LIBRARY_DEFINITION_ROUTE_SERVICE_COMPONENT,
        "version": LIBRARY_DEFINITION_ROUTE_SERVICE_VERSION,
        "error": {
            "code": code,
            "message": message,
        },
    }

    if extra:
        payload.update(dict(extra))

    if options.debug:
        payload["request_options"] = options.to_dict()
        payload["raw_query"] = dict(options.raw_query)

    return payload


def _normalize_query_mapping(query_params: Optional[Mapping[str, Any]]) -> Dict[str, Any]:
    if not query_params:
        return {}

    result: Dict[str, Any] = {}

    keys_getter = getattr(query_params, "keys", None)
    if callable(keys_getter):
        try:
            keys = list(keys_getter())
        except Exception:
            keys = []
    else:
        keys = list(query_params.keys()) if isinstance(query_params, Mapping) else []

    for key in keys:
        clean_key = _clean_string(key)
        if not clean_key:
            continue

        value = None

        getlist = getattr(query_params, "getlist", None)
        if callable(getlist):
            try:
                values = getlist(key)
            except Exception:
                values = []
            if values:
                value = values[-1] if len(values) == 1 else values
        else:
            try:
                value = query_params[key]  # type: ignore[index]
            except Exception:
                value = None

        result[clean_key] = value

    return result


def _get_first(query: Optional[Mapping[str, Any]], *names: str) -> Any:
    if not query:
        return None

    for name in names:
        if name in query:
            value = query.get(name)
            if isinstance(value, (list, tuple)):
                return value[-1] if value else None
            return value

    return None


def _get_str(
    query: Optional[Mapping[str, Any]],
    *names: str,
    default: str = "",
) -> str:
    value = _get_first(query, *names)
    clean = _clean_string(value)
    return clean or default


def _get_optional_str(
    query: Optional[Mapping[str, Any]],
    *names: str,
) -> Optional[str]:
    clean = _get_str(query, *names, default="")
    return clean or None


def _get_bool(
    query: Optional[Mapping[str, Any]],
    *names: str,
    default: bool = False,
) -> bool:
    value = _get_first(query, *names)
    return _as_bool(value, default=default)


def _as_mapping(value: Any) -> Dict[str, Any]:
    if isinstance(value, Mapping):
        return dict(value)
    return {
        "ok": value is not None,
        "value": value,
    }


def _as_bool(value: Any, *, default: bool = False) -> bool:
    if value is None:
        return default

    if isinstance(value, bool):
        return value

    if isinstance(value, (int, float)):
        return bool(value)

    if isinstance(value, str):
        clean = value.strip().lower()
        if clean in {"1", "true", "yes", "y", "on", "active", "enabled"}:
            return True
        if clean in {"0", "false", "no", "n", "off", "inactive", "disabled"}:
            return False

    return default


def _copy_mapping(value: Optional[Mapping[str, Any]]) -> Dict[str, Any]:
    if not isinstance(value, Mapping):
        return {}
    return dict(value)


def _clean_string(value: Any, *, default: str = "") -> str:
    if value is None:
        return default
    clean = str(value).strip()
    return clean or default


def _clean_optional_string(value: Any) -> Optional[str]:
    clean = _clean_string(value)
    return clean or None


def _format_exception(exc: BaseException) -> str:
    return f"{exc.__class__.__name__}: {exc}"


def get_library_definition_route_service_selftest() -> Dict[str, Any]:
    """
    Minimal direct self-test without Flask.

    Useful in Python shell:
    from src.services.library_definition_route_service import get_library_definition_route_service_selftest
    get_library_definition_route_service_selftest()
    """
    health = get_library_definition_route_service_health({"debug": "true"})
    options = get_library_definition_options_response({"debug": "true"})
    resolve = resolve_library_definition_variant_profile_response(
        {
            "domain": "hochbau",
            "category": "waende",
            "subcategory": "ziegel",
            "object_kind": "cell_block",
            "debug": "true",
        }
    )

    return {
        "ok": bool(health.get("ok")) and bool(options.get("ok")) and bool(resolve.get("ok")),
        "health": health,
        "options": options,
        "resolve": resolve,
    }