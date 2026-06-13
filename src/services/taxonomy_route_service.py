# services/vectoplan-library/src/services/taxonomy_route_service.py
"""
VECTOPLAN Library Taxonomy Route Service.

HTTP-near service layer for taxonomy routes.

This module intentionally keeps Flask out of the core implementation. Flask
Blueprints should call this service and then convert the returned
RouteServiceResponse into jsonify(...) / Response objects.

Responsibilities:
- expose taxonomy health payloads
- expose canonical taxonomy payloads
- expose Create-Wizard taxonomy options
- expose tree / lookup / options payloads
- validate domain/category/subcategory selections
- resolve taxonomy selections
- build canonical source paths, family_id and package_id values
- reload / clear taxonomy caches
- return consistent route envelopes and status codes

Intended route mapping:

GET  /api/v1/vplib/taxonomy/health
GET  /api/v1/vplib/taxonomy
GET  /api/v1/vplib/taxonomy/options
GET  /api/v1/vplib/taxonomy/create-options
GET  /api/v1/vplib/taxonomy/tree
GET  /api/v1/vplib/taxonomy/lookup
POST /api/v1/vplib/taxonomy/validate
POST /api/v1/vplib/taxonomy/resolve
POST /api/v1/vplib/taxonomy/build-reference
POST /api/v1/vplib/taxonomy/cache/clear
POST /api/v1/vplib/taxonomy/reload

The existing Create route can also call:
    TaxonomyRouteService().create_options(...)
or use TaxonomyService directly.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field as dataclass_field
from datetime import datetime, timezone
from typing import Any, Dict, Iterable, Mapping, Optional, Sequence, Tuple


try:
    from src.library.taxonomy import (
        TAXONOMY_REQUIRED_FIELDS,
        TaxonomyIssue,
        TaxonomySelection,
        TaxonomySelectionError,
        TaxonomyService,
        TaxonomyServiceError,
        TaxonomyServiceUnavailableError,
        TaxonomyValidationResult,
        get_default_taxonomy_service,
        make_json_safe,
        normalize_slug,
        safe_bool,
        safe_int,
        safe_str,
    )
except ImportError:  # pragma: no cover - fallback for alternative PYTHONPATH layouts
    try:
        from library.taxonomy import (  # type: ignore
            TAXONOMY_REQUIRED_FIELDS,
            TaxonomyIssue,
            TaxonomySelection,
            TaxonomySelectionError,
            TaxonomyService,
            TaxonomyServiceError,
            TaxonomyServiceUnavailableError,
            TaxonomyValidationResult,
            get_default_taxonomy_service,
            make_json_safe,
            normalize_slug,
            safe_bool,
            safe_int,
            safe_str,
        )
    except ImportError:  # pragma: no cover - fallback when imported as src.services.*
        from ..library.taxonomy import (  # type: ignore
            TAXONOMY_REQUIRED_FIELDS,
            TaxonomyIssue,
            TaxonomySelection,
            TaxonomySelectionError,
            TaxonomyService,
            TaxonomyServiceError,
            TaxonomyServiceUnavailableError,
            TaxonomyValidationResult,
            get_default_taxonomy_service,
            make_json_safe,
            normalize_slug,
            safe_bool,
            safe_int,
            safe_str,
        )


LOGGER = logging.getLogger(__name__)

TAXONOMY_ROUTE_SERVICE_COMPONENT = "taxonomy-route-service"
TAXONOMY_ROUTE_SERVICE_VERSION = "0.1.0"

DEFAULT_OK_STATUS = 200
DEFAULT_CREATED_STATUS = 201
DEFAULT_BAD_REQUEST_STATUS = 400
DEFAULT_NOT_FOUND_STATUS = 404
DEFAULT_CONFLICT_STATUS = 409
DEFAULT_ERROR_STATUS = 500
DEFAULT_UNAVAILABLE_STATUS = 503

DEFAULT_JSON_HEADERS: Mapping[str, str] = {
    "X-Vectoplan-Component": TAXONOMY_ROUTE_SERVICE_COMPONENT,
    "X-Vectoplan-Component-Version": TAXONOMY_ROUTE_SERVICE_VERSION,
}


@dataclass(frozen=True)
class RouteServiceResponse:
    """
    Framework-neutral route response.

    Flask route usage example:

        result = taxonomy_route_service.taxonomy(request.args)
        return jsonify(result.payload), result.status_code, result.headers
    """

    payload: Mapping[str, Any]
    status_code: int = DEFAULT_OK_STATUS
    headers: Mapping[str, str] = dataclass_field(default_factory=lambda: dict(DEFAULT_JSON_HEADERS))

    @property
    def ok(self) -> bool:
        return 200 <= self.status_code < 300 and bool(self.payload.get("ok", False))

    def to_tuple(self) -> Tuple[Mapping[str, Any], int, Mapping[str, str]]:
        return self.payload, self.status_code, self.headers

    def to_dict(self) -> Dict[str, Any]:
        return {
            "payload": make_json_safe(self.payload),
            "status_code": self.status_code,
            "headers": dict(self.headers),
            "ok": self.ok,
        }


class TaxonomyRouteService:
    """
    HTTP-near wrapper around TaxonomyService.

    It catches service exceptions and returns route-ready envelopes instead of
    raising framework-specific errors.
    """

    def __init__(
        self,
        taxonomy_service: Optional[TaxonomyService] = None,
        *,
        logger: Optional[logging.Logger] = None,
    ) -> None:
        self.taxonomy_service = taxonomy_service or get_default_taxonomy_service()
        self.logger = logger or LOGGER

    def health(self, query: Any = None) -> RouteServiceResponse:
        """
        Return taxonomy route/service health.

        Query parameters:
        - force_reload=true|false
        - include_registry_state=true|false
        """

        try:
            params = RouteParams(query)
            force_reload = params.get_bool("force_reload", default=False)
            include_registry_state = params.get_bool("include_registry_state", default=False)

            health_payload = self.taxonomy_service.health(
                force_reload=force_reload,
                include_registry_state=include_registry_state,
            )

            status_code = DEFAULT_OK_STATUS if health_payload.get("healthy") else DEFAULT_UNAVAILABLE_STATUS

            return self._success(
                data=health_payload,
                status_code=status_code,
                action="health",
                message="Taxonomy health loaded.",
            )

        except Exception as exc:
            return self._exception_response(
                exc,
                action="health",
                message="Taxonomy health failed.",
                status_code=DEFAULT_UNAVAILABLE_STATUS,
            )

    def taxonomy(self, query: Any = None) -> RouteServiceResponse:
        """
        Return the canonical taxonomy payload.

        Query parameters:
        - include_inactive=true|false
        - include_tree=true|false
        - include_options=true|false
        - include_lookup=true|false
        - force_reload=true|false
        """

        try:
            params = RouteParams(query)

            payload = self.taxonomy_service.get_taxonomy_payload(
                include_inactive=params.get_optional_bool("include_inactive"),
                include_tree=params.get_optional_bool("include_tree"),
                include_options=params.get_optional_bool("include_options"),
                include_lookup=params.get_optional_bool("include_lookup"),
                force_reload=params.get_bool("force_reload", default=False),
            )

            return self._success(
                data=payload,
                action="taxonomy",
                message="Taxonomy payload loaded.",
            )

        except Exception as exc:
            return self._exception_response(
                exc,
                action="taxonomy",
                message="Taxonomy payload failed.",
            )

    def options(self, query: Any = None) -> RouteServiceResponse:
        """
        Return direct taxonomy select options.

        Query parameters:
        - include_inactive=true|false
        - force_reload=true|false
        """

        try:
            params = RouteParams(query)

            payload = self.taxonomy_service.get_options_payload(
                include_inactive=params.get_optional_bool("include_inactive"),
                force_reload=params.get_bool("force_reload", default=False),
            )

            return self._success(
                data=payload,
                action="options",
                message="Taxonomy options loaded.",
            )

        except Exception as exc:
            return self._exception_response(
                exc,
                action="options",
                message="Taxonomy options failed.",
            )

    def create_options(self, query: Any = None) -> RouteServiceResponse:
        """
        Return Create-Wizard-friendly taxonomy options.

        This can be used directly by:
            GET /api/v1/vplib/create/options

        Query parameters:
        - include_inactive=true|false
        - force_reload=true|false
        """

        try:
            params = RouteParams(query)

            payload = self.taxonomy_service.get_create_options_payload(
                include_inactive=params.get_optional_bool("include_inactive"),
                force_reload=params.get_bool("force_reload", default=False),
            )

            return self._success(
                data=payload,
                action="create_options",
                message="Create taxonomy options loaded.",
            )

        except Exception as exc:
            return self._exception_response(
                exc,
                action="create_options",
                message="Create taxonomy options failed.",
            )

    def tree(self, query: Any = None) -> RouteServiceResponse:
        """
        Return taxonomy tree.

        Query parameters:
        - include_inactive=true|false
        - force_reload=true|false
        """

        try:
            params = RouteParams(query)

            payload = self.taxonomy_service.get_tree_payload(
                include_inactive=params.get_optional_bool("include_inactive"),
                force_reload=params.get_bool("force_reload", default=False),
            )

            return self._success(
                data=payload,
                action="tree",
                message="Taxonomy tree loaded.",
            )

        except Exception as exc:
            return self._exception_response(
                exc,
                action="tree",
                message="Taxonomy tree failed.",
            )

    def lookup(self, query: Any = None) -> RouteServiceResponse:
        """
        Return taxonomy lookup maps.

        Query parameters:
        - force_reload=true|false
        """

        try:
            params = RouteParams(query)

            payload = self.taxonomy_service.get_lookup_payload(
                force_reload=params.get_bool("force_reload", default=False),
            )

            return self._success(
                data=payload,
                action="lookup",
                message="Taxonomy lookup loaded.",
            )

        except Exception as exc:
            return self._exception_response(
                exc,
                action="lookup",
                message="Taxonomy lookup failed.",
            )

    def validate(self, payload: Any = None, query: Any = None) -> RouteServiceResponse:
        """
        Validate a taxonomy selection.

        Payload:
        {
          "domain": "hochbau",
          "category": "waende",
          "subcategory": "aussenwaende",
          "object_kind": "cell_block"
        }

        Query parameters:
        - force_reload=true|false
        """

        try:
            params = RouteParams(query)
            source = as_mapping(payload)
            selection = TaxonomySelection.from_payload(source)
            object_kind = normalize_slug(source.get("object_kind"), default="")

            result = self.taxonomy_service.validate_selection(
                selection.domain,
                selection.category,
                selection.subcategory,
                object_kind=object_kind,
                force_reload=params.get_bool("force_reload", default=False),
            )

            status_code = DEFAULT_OK_STATUS if result.valid else DEFAULT_BAD_REQUEST_STATUS

            return self._success(
                data={
                    "valid": result.valid,
                    "selection": selection.to_dict(),
                    "object_kind": object_kind,
                    "validation": result.to_dict(),
                },
                status_code=status_code,
                action="validate",
                message="Taxonomy selection validated.",
            )

        except Exception as exc:
            return self._exception_response(
                exc,
                action="validate",
                message="Taxonomy validation failed.",
                status_code=DEFAULT_BAD_REQUEST_STATUS,
            )

    def resolve(self, payload: Any = None, query: Any = None) -> RouteServiceResponse:
        """
        Resolve a taxonomy selection into labels and node metadata.

        Payload:
        {
          "domain": "hochbau",
          "category": "waende",
          "subcategory": "aussenwaende"
        }

        Query parameters:
        - force_reload=true|false
        """

        try:
            params = RouteParams(query)
            selection = TaxonomySelection.from_payload(payload)

            resolved = self.taxonomy_service.resolve_selection(
                selection.domain,
                selection.category,
                selection.subcategory,
                force_reload=params.get_bool("force_reload", default=False),
            )

            return self._success(
                data={
                    "resolved": resolved.to_dict(),
                    "selection": resolved.selection.to_dict(),
                    "classification_path": resolved.classification_path,
                    "path_labels": list(resolved.path_labels),
                },
                action="resolve",
                message="Taxonomy selection resolved.",
            )

        except Exception as exc:
            return self._exception_response(
                exc,
                action="resolve",
                message="Taxonomy resolve failed.",
                status_code=DEFAULT_BAD_REQUEST_STATUS,
            )

    def build_reference(self, payload: Any = None, query: Any = None) -> RouteServiceResponse:
        """
        Build canonical source_path, family_id and package_id.

        Payload:
        {
          "domain": "hochbau",
          "category": "waende",
          "subcategory": "aussenwaende",
          "family_slug": "ziegelwand",
          "object_kind": "cell_block"
        }

        Query parameters:
        - force_reload=true|false
        """

        try:
            params = RouteParams(query)
            source = as_mapping(payload)

            result = self.taxonomy_service.build_family_reference_from_payload(
                source,
                force_reload=params.get_bool("force_reload", default=False),
            )

            status_code = DEFAULT_OK_STATUS if result.valid else DEFAULT_BAD_REQUEST_STATUS

            return self._success(
                data=result.to_dict(),
                status_code=status_code,
                action="build_reference",
                message="Taxonomy family reference built.",
            )

        except Exception as exc:
            return self._exception_response(
                exc,
                action="build_reference",
                message="Taxonomy family reference failed.",
                status_code=DEFAULT_BAD_REQUEST_STATUS,
            )

    def build_classification(self, payload: Any = None, query: Any = None) -> RouteServiceResponse:
        """
        Build a classification.json-compatible taxonomy fragment.

        Payload:
        {
          "domain": "hochbau",
          "category": "waende",
          "subcategory": "aussenwaende",
          "object_kind": "cell_block",
          "include_node_metadata": true
        }
        """

        try:
            params = RouteParams(query)
            source = as_mapping(payload)
            selection = TaxonomySelection.from_payload(source)

            document = self.taxonomy_service.build_classification_document(
                domain=selection.domain,
                category=selection.category,
                subcategory=selection.subcategory,
                object_kind=source.get("object_kind", ""),
                include_node_metadata=safe_bool(source.get("include_node_metadata"), True),
                force_reload=params.get_bool("force_reload", default=False),
            )

            return self._success(
                data={
                    "classification": document,
                    "selection": selection.to_dict(),
                },
                action="build_classification",
                message="Taxonomy classification document built.",
            )

        except Exception as exc:
            return self._exception_response(
                exc,
                action="build_classification",
                message="Taxonomy classification build failed.",
                status_code=DEFAULT_BAD_REQUEST_STATUS,
            )

    def validate_source_path(self, payload: Any = None, query: Any = None) -> RouteServiceResponse:
        """
        Validate a canonical or legacy taxonomy source path.

        Payload:
        {
          "source_path": "hochbau/waende/aussenwaende/ziegelwand",
          "object_kind": "cell_block",
          "expect_family_slug": true
        }
        """

        try:
            params = RouteParams(query)
            source = as_mapping(payload)

            source_path = source.get("source_path") or source.get("path") or ""
            object_kind = source.get("object_kind", "")
            expect_family_slug = safe_bool(source.get("expect_family_slug"), True)

            result = self.taxonomy_service.validate_source_path(
                source_path,
                object_kind=object_kind,
                expect_family_slug=expect_family_slug,
                force_reload=params.get_bool("force_reload", default=False),
            )

            status_code = DEFAULT_OK_STATUS if result.valid else DEFAULT_BAD_REQUEST_STATUS

            return self._success(
                data=result.to_dict(),
                status_code=status_code,
                action="validate_source_path",
                message="Taxonomy source path validated.",
            )

        except Exception as exc:
            return self._exception_response(
                exc,
                action="validate_source_path",
                message="Taxonomy source path validation failed.",
                status_code=DEFAULT_BAD_REQUEST_STATUS,
            )

    def reload(self, query: Any = None) -> RouteServiceResponse:
        """
        Force reload taxonomy registry.

        Query parameters:
        - allow_stale_on_error=true|false
        """

        try:
            params = RouteParams(query)
            allow_stale_on_error = params.get_bool("allow_stale_on_error", default=False)

            load_result = self.taxonomy_service.load_registry_result(
                force_reload=True,
                allow_stale_on_error=allow_stale_on_error,
            )

            self.taxonomy_service.clear_cache()

            payload = {
                "reloaded": True,
                "load_result": load_result.to_dict(include_registry=False) if load_result else None,
                "health": self.taxonomy_service.health(
                    force_reload=False,
                    include_registry_state=True,
                ),
            }

            status_code = (
                DEFAULT_OK_STATUS
                if payload["health"].get("healthy")
                else DEFAULT_UNAVAILABLE_STATUS
            )

            return self._success(
                data=payload,
                status_code=status_code,
                action="reload",
                message="Taxonomy registry reloaded.",
            )

        except Exception as exc:
            return self._exception_response(
                exc,
                action="reload",
                message="Taxonomy reload failed.",
                status_code=DEFAULT_UNAVAILABLE_STATUS,
            )

    def clear_cache(self, query: Any = None) -> RouteServiceResponse:
        """Clear taxonomy service and registry caches."""

        try:
            self.taxonomy_service.clear_cache()

            return self._success(
                data={
                    "cleared": True,
                    "component": TAXONOMY_ROUTE_SERVICE_COMPONENT,
                },
                action="clear_cache",
                message="Taxonomy cache cleared.",
            )

        except Exception as exc:
            return self._exception_response(
                exc,
                action="clear_cache",
                message="Taxonomy cache clear failed.",
            )

    def _success(
        self,
        *,
        data: Mapping[str, Any],
        action: str,
        message: str,
        status_code: int = DEFAULT_OK_STATUS,
        meta: Optional[Mapping[str, Any]] = None,
    ) -> RouteServiceResponse:
        envelope = self._envelope(
            ok=True,
            action=action,
            message=message,
            data=data,
            error=None,
            meta=meta,
        )

        return RouteServiceResponse(
            payload=envelope,
            status_code=status_code,
            headers=dict(DEFAULT_JSON_HEADERS),
        )

    def _exception_response(
        self,
        exc: Exception,
        *,
        action: str,
        message: str,
        status_code: int = DEFAULT_ERROR_STATUS,
    ) -> RouteServiceResponse:
        self.logger.exception("%s: %s", message, exc)

        resolved_status = self._status_code_for_exception(exc, default=status_code)

        envelope = self._envelope(
            ok=False,
            action=action,
            message=message,
            data={},
            error={
                "type": exc.__class__.__name__,
                "message": safe_str(exc, message),
            },
            meta=None,
        )

        return RouteServiceResponse(
            payload=envelope,
            status_code=resolved_status,
            headers=dict(DEFAULT_JSON_HEADERS),
        )

    def _envelope(
        self,
        *,
        ok: bool,
        action: str,
        message: str,
        data: Mapping[str, Any],
        error: Optional[Mapping[str, Any]],
        meta: Optional[Mapping[str, Any]],
    ) -> Dict[str, Any]:
        payload = {
            "ok": bool(ok),
            "component": TAXONOMY_ROUTE_SERVICE_COMPONENT,
            "component_version": TAXONOMY_ROUTE_SERVICE_VERSION,
            "action": safe_str(action, ""),
            "message": safe_str(message, ""),
            "timestamp": utc_now_iso(),
            "required_fields": list(TAXONOMY_REQUIRED_FIELDS),
            "data": make_json_safe(data),
            "error": make_json_safe(error) if error else None,
            "meta": make_json_safe(meta or {}),
        }

        return make_json_safe(payload)

    def _status_code_for_exception(self, exc: Exception, *, default: int) -> int:
        if isinstance(exc, TaxonomyServiceUnavailableError):
            return DEFAULT_UNAVAILABLE_STATUS

        if isinstance(exc, TaxonomySelectionError):
            return DEFAULT_BAD_REQUEST_STATUS

        if isinstance(exc, TaxonomyServiceError):
            return DEFAULT_ERROR_STATUS

        return default


class RouteParams:
    """
    Small adapter for Flask request.args, plain dicts or similar objects.

    Supported inputs:
    - None
    - dict
    - werkzeug MultiDict / request.args
    - any object with get(key, default)
    """

    def __init__(self, query: Any = None) -> None:
        self.query = query

    def get(self, key: str, default: Any = None) -> Any:
        if self.query is None:
            return default

        try:
            if isinstance(self.query, Mapping):
                value = self.query.get(key, default)
            elif hasattr(self.query, "get"):
                value = self.query.get(key, default)
            else:
                return default

            if isinstance(value, (list, tuple)) and value:
                return value[0]

            return value
        except Exception:
            return default

    def get_str(self, key: str, default: str = "") -> str:
        return safe_str(self.get(key, default), default)

    def get_bool(self, key: str, default: bool = False) -> bool:
        return safe_bool(self.get(key, default), default)

    def get_optional_bool(self, key: str) -> Optional[bool]:
        value = self.get(key, None)

        if value is None or value == "":
            return None

        return safe_bool(value, False)

    def get_int(
        self,
        key: str,
        default: int = 0,
        *,
        minimum: Optional[int] = None,
        maximum: Optional[int] = None,
    ) -> int:
        return safe_int(
            self.get(key, default),
            default,
            minimum=minimum,
            maximum=maximum,
        )

    def to_dict(self) -> Dict[str, Any]:
        if self.query is None:
            return {}

        if isinstance(self.query, Mapping):
            return {safe_str(key, ""): value for key, value in self.query.items()}

        if hasattr(self.query, "items"):
            try:
                return {safe_str(key, ""): value for key, value in self.query.items()}
            except Exception:
                return {}

        return {}


_DEFAULT_TAXONOMY_ROUTE_SERVICE: Optional[TaxonomyRouteService] = None


def get_default_taxonomy_route_service(
    *,
    force_new: bool = False,
    taxonomy_service: Optional[TaxonomyService] = None,
) -> TaxonomyRouteService:
    global _DEFAULT_TAXONOMY_ROUTE_SERVICE

    if (
        force_new
        or _DEFAULT_TAXONOMY_ROUTE_SERVICE is None
        or taxonomy_service is not None
    ):
        _DEFAULT_TAXONOMY_ROUTE_SERVICE = TaxonomyRouteService(
            taxonomy_service=taxonomy_service,
        )

    return _DEFAULT_TAXONOMY_ROUTE_SERVICE


def reset_default_taxonomy_route_service() -> None:
    global _DEFAULT_TAXONOMY_ROUTE_SERVICE
    _DEFAULT_TAXONOMY_ROUTE_SERVICE = None


def as_mapping(value: Any) -> Mapping[str, Any]:
    if isinstance(value, Mapping):
        return value

    return {}


def utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


__all__ = [
    "DEFAULT_BAD_REQUEST_STATUS",
    "DEFAULT_CONFLICT_STATUS",
    "DEFAULT_CREATED_STATUS",
    "DEFAULT_ERROR_STATUS",
    "DEFAULT_JSON_HEADERS",
    "DEFAULT_NOT_FOUND_STATUS",
    "DEFAULT_OK_STATUS",
    "DEFAULT_UNAVAILABLE_STATUS",
    "RouteParams",
    "RouteServiceResponse",
    "TAXONOMY_ROUTE_SERVICE_COMPONENT",
    "TAXONOMY_ROUTE_SERVICE_VERSION",
    "TaxonomyRouteService",
    "as_mapping",
    "get_default_taxonomy_route_service",
    "reset_default_taxonomy_route_service",
    "utc_now_iso",
]