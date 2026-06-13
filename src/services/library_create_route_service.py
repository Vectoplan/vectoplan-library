# services/vectoplan-library/src/services/library_create_route_service.py
"""
VECTOPLAN Library – Create Route Service

Purpose:
    HTTP-near service layer for the simple VPLIB create flow.

Scope:
    - No Flask dependency.
    - No database dependency.
    - No file writing logic here.
    - No package generation logic here.
    - Delegates create/domain work to:
        library.services.library_create_service
    - Delegates taxonomy work to:
        library.taxonomy.TaxonomyService
    - Delegates definitions work to:
        library.definitions
    - Delegates create payload normalization to:
        library_create_variant_payload_service

Responsibilities:
    - Build stable API response envelopes.
    - Normalize route-level status codes.
    - Expose route/service health.
    - Wrap validate/package-plan/save responses.
    - Prepare binary download responses for the Flask blueprint.
    - Merge canonical backend taxonomy into create/options.
    - Merge backend-owned definitions into create/options.
    - Normalize create payloads before all create actions.
    - Ensure `vplib_uid` is present and stable across draft/validate/package-plan/download/save.
    - Enforce domain/category/subcategory as required route-level fields.
    - Keep API behavior predictable even when imports fail.

Expected Flask blueprint:
    services/vectoplan-library/src/routes/create.py

Expected routes:
    GET  /create
    GET  /api/v1/vplib/create/health
    GET  /api/v1/vplib/create/options
    POST /api/v1/vplib/create/draft
    POST /api/v1/vplib/create/validate
    POST /api/v1/vplib/create/package-plan
    POST /api/v1/vplib/create/download
    POST /api/v1/vplib/create/save

Taxonomy decision:
    The Create-Wizard must not own or hard-code domain/category/subcategory data.
    The backend taxonomy registry is canonical.

Definitions decision:
    The Create-Wizard must not own or hard-code object kinds, family profiles,
    variant profiles, variables, units, materials, document types or profile
    bindings. The backend definitions registry is canonical.

VPLIB ID decision:
    The Create-Wizard must keep one stable `vplib_uid` across the entire flow.
    The route service normalizes incoming payloads and ensures a missing
    `vplib_uid` is created before delegating to the create service.
    Existing valid IDs are preserved.
    Existing invalid IDs are not silently replaced.

Failure policy:
    - create service unavailable: hard error
    - taxonomy unavailable: hard error, because taxonomy is required
    - create payload normalizer unavailable: hard error for create actions
    - definitions unavailable: soft warning for /options, returned as
      definitions.ok=false so the UI can still show a controlled state
"""

from __future__ import annotations

import inspect
import json
import traceback
import uuid
from dataclasses import dataclass, field as dataclass_field
from datetime import datetime, timezone
from typing import Any, Callable, Mapping


LIBRARY_CREATE_ROUTE_SERVICE_VERSION = "0.4.0"
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


try:
    from library.services import library_create_service as _create_service

    _CREATE_SERVICE_IMPORT_ERROR: BaseException | None = None
except Exception as import_error:  # pragma: no cover - defensive runtime guard
    _create_service = None  # type: ignore[assignment]
    _CREATE_SERVICE_IMPORT_ERROR = import_error


try:
    from services import library_create_variant_payload_service as _variant_payload_service

    _VARIANT_PAYLOAD_SERVICE_IMPORT_ERROR: BaseException | None = None
except Exception as first_import_error:  # pragma: no cover - defensive runtime guard
    try:
        from library.services import library_create_variant_payload_service as _variant_payload_service  # type: ignore[no-redef]

        _VARIANT_PAYLOAD_SERVICE_IMPORT_ERROR = None
    except Exception as second_import_error:  # pragma: no cover - defensive runtime guard
        try:
            import library_create_variant_payload_service as _variant_payload_service  # type: ignore[no-redef]

            _VARIANT_PAYLOAD_SERVICE_IMPORT_ERROR = None
        except Exception as third_import_error:  # pragma: no cover - defensive runtime guard
            _variant_payload_service = None  # type: ignore[assignment]
            _VARIANT_PAYLOAD_SERVICE_IMPORT_ERROR = RuntimeError(
                "Create-Variant-Payload-Service konnte nicht importiert werden. "
                f"services import error={first_import_error}; "
                f"library.services import error={second_import_error}; "
                f"direct import error={third_import_error}"
            )


try:
    from library.taxonomy import (
        TaxonomySelection,
        get_default_taxonomy_service,
        normalize_slug as _taxonomy_normalize_slug,
    )

    _TAXONOMY_SERVICE_IMPORT_ERROR: BaseException | None = None
except Exception as import_error:  # pragma: no cover - defensive runtime guard
    TaxonomySelection = None  # type: ignore[assignment]
    get_default_taxonomy_service = None  # type: ignore[assignment]

    def _taxonomy_normalize_slug(value: Any, *, default: str = "") -> str:  # type: ignore[no-redef]
        return _normalize_slug_fallback(value, default=default)

    _TAXONOMY_SERVICE_IMPORT_ERROR = import_error


try:
    from library import definitions as _definitions_service

    _DEFINITIONS_SERVICE_IMPORT_ERROR: BaseException | None = None
except Exception as first_import_error:  # pragma: no cover - defensive runtime guard
    try:
        from src.library import definitions as _definitions_service  # type: ignore[no-redef]

        _DEFINITIONS_SERVICE_IMPORT_ERROR = None
    except Exception as second_import_error:  # pragma: no cover - defensive runtime guard
        _definitions_service = None  # type: ignore[assignment]
        _DEFINITIONS_SERVICE_IMPORT_ERROR = RuntimeError(
            "Definitions-Service konnte nicht importiert werden. "
            f"library import error={first_import_error}; "
            f"src.library import error={second_import_error}"
        )


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
            "severity": self.severity,
            "code": self.code,
            "message": self.message,
        }

        if self.field:
            payload["field"] = self.field

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


@dataclass(frozen=True)
class RouteBinaryResponse:
    """
    Binary response envelope for route handlers.

    The Flask blueprint should use:
        - filename
        - content
        - mimetype
        - http_status

    and may expose meta with:
        to_dict()
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


def get_route_plan() -> dict[str, Any]:
    """Return the expected create-route contract."""
    return {
        "page": {
            "method": "GET",
            "path": CREATE_PAGE_ROUTE,
            "description": "Rendert die VPLIB-Create-Oberfläche.",
        },
        "health": {
            "method": "GET",
            "path": f"{CREATE_API_PREFIX}/health",
            "description": (
                "Health für Create-Route-Service, Create-Service, "
                "Payload-Normalizer, Taxonomie-Service und Definitions-Service."
            ),
        },
        "options": {
            "method": "GET",
            "path": f"{CREATE_API_PREFIX}/options",
            "description": (
                "Liefert Create-Optionen plus kanonische Backend-Taxonomie "
                "und backendgesteuerte Definitionsdaten für Objektarten, "
                "Family Profiles, Variant Profiles, Variablen, Einheiten, "
                "Materialien, Dokumenttypen und Profile Bindings."
            ),
        },
        "draft": {
            "method": "POST",
            "path": f"{CREATE_API_PREFIX}/draft",
            "description": "Normalisiert Nutzereingaben zu einem stabilen Create-Draft inklusive vplib_uid.",
        },
        "validate": {
            "method": "POST",
            "path": f"{CREATE_API_PREFIX}/validate",
            "description": "Validiert Draft und generierte Package-Dokumente inklusive vplib_uid.",
        },
        "package_plan": {
            "method": "POST",
            "path": f"{CREATE_API_PREFIX}/package-plan",
            "description": "Erzeugt einen Package-Plan ohne Schreibzugriff und hält die vplib_uid stabil.",
        },
        "download": {
            "method": "POST",
            "path": f"{CREATE_API_PREFIX}/download",
            "description": "Erzeugt ein .vplib-Archiv im Speicher mit stabiler vplib_uid.",
        },
        "save": {
            "method": "POST",
            "path": f"{CREATE_API_PREFIX}/save",
            "description": "Speichert ein Package in src/library/source mit stabiler vplib_uid, nur wenn Write-Modus aktiv ist.",
        },
    }


def get_route_service_health() -> RouteResponse:
    """Return health for route service, delegated create service, payload normalizer, taxonomy service and definitions service."""
    route = "health"

    errors: list[RouteIssue | dict[str, Any]] = []
    warnings: list[RouteIssue | dict[str, Any]] = []
    info: list[RouteIssue | dict[str, Any]] = []

    service_health_payload: dict[str, Any] = {}
    payload_normalizer_health_payload: dict[str, Any] = {}
    taxonomy_health_payload: dict[str, Any] = {}
    definitions_health_payload: dict[str, Any] = {}

    service_available = _is_create_service_available()
    payload_normalizer_available = _is_variant_payload_service_available()
    taxonomy_available = _is_taxonomy_service_available()
    definitions_available = _is_definitions_service_available()

    if not service_available:
        errors.append(
            _exception_issue(
                "create_service_import_failed",
                _CREATE_SERVICE_IMPORT_ERROR,
                field="library.services.library_create_service",
            )
        )
    else:
        try:
            service_result = _create_service.get_service_health()  # type: ignore[union-attr]
            service_response = _create_result_to_payload(service_result)
            service_health_payload = service_response

            if not bool(service_response.get("ok")):
                errors.extend(_coerce_issue_list(service_response.get("errors", [])))
                warnings.extend(_coerce_issue_list(service_response.get("warnings", [])))
            else:
                warnings.extend(_coerce_issue_list(service_response.get("warnings", [])))
                info.append(
                    _info(
                        "create_service_available",
                        "Create-Service ist importierbar und antwortet auf Health.",
                    )
                )
        except Exception as exc:
            errors.append(
                _exception_issue(
                    "create_service_health_failed",
                    exc,
                    field="library_create_service.health",
                )
            )

    if not payload_normalizer_available:
        errors.append(
            _exception_issue(
                "create_payload_normalizer_import_failed",
                _VARIANT_PAYLOAD_SERVICE_IMPORT_ERROR,
                field="library_create_variant_payload_service",
                fallback_message="Create-Payload-Normalizer konnte nicht importiert werden.",
            )
        )
        payload_normalizer_health_payload = {
            "ok": False,
            "healthy": False,
            "status": "unavailable",
            "component": "library_create_variant_payload_service",
            "error": str(_VARIANT_PAYLOAD_SERVICE_IMPORT_ERROR),
        }
    else:
        payload_normalizer_health_payload = {
            "ok": True,
            "healthy": True,
            "status": "available",
            "component": "library_create_variant_payload_service",
            "schema_version": _get_variant_payload_service_attr(
                "CREATE_VARIANT_PAYLOAD_SERVICE_SCHEMA_VERSION",
                default="unknown",
            ),
            "vplib_uid_field": VPLIB_UID_FIELD,
        }
        info.append(
            _info(
                "create_payload_normalizer_available",
                "Create-Payload-Normalizer ist importierbar.",
                details=payload_normalizer_health_payload,
            )
        )

    if not taxonomy_available:
        errors.append(
            _exception_issue(
                "taxonomy_service_import_failed",
                _TAXONOMY_SERVICE_IMPORT_ERROR,
                field="library.taxonomy",
                fallback_message="Taxonomie-Service konnte nicht importiert werden.",
            )
        )
    else:
        try:
            taxonomy_service = _get_taxonomy_service()
            taxonomy_health_payload = taxonomy_service.health(
                force_reload=False,
                include_registry_state=False,
            )

            if not bool(taxonomy_health_payload.get("healthy")):
                errors.append(
                    _error(
                        "taxonomy_service_unhealthy",
                        "Taxonomie-Service ist verfügbar, aber nicht healthy.",
                        field="library.taxonomy",
                        details=taxonomy_health_payload,
                    )
                )
            else:
                info.append(
                    _info(
                        "taxonomy_service_available",
                        "Taxonomie-Service ist importierbar und healthy.",
                    )
                )
        except Exception as exc:
            errors.append(
                _exception_issue(
                    "taxonomy_service_health_failed",
                    exc,
                    field="library.taxonomy.health",
                )
            )

    if not definitions_available:
        warnings.append(
            _exception_warning(
                "definitions_service_import_failed",
                _DEFINITIONS_SERVICE_IMPORT_ERROR,
                field="library.definitions",
                fallback_message=(
                    "Definitions-Service konnte nicht importiert werden. "
                    "Create-Options bleiben verfügbar, aber Definitionsdaten fehlen."
                ),
            )
        )
        definitions_health_payload = _definitions_unavailable_payload(
            reason="import_failed",
            exc=_DEFINITIONS_SERVICE_IMPORT_ERROR,
        )
    else:
        try:
            definitions_health_payload = _call_definitions_payload_function(
                "get_definitions_health",
                force_refresh=False,
            )

            if not bool(
                definitions_health_payload.get("healthy")
                or definitions_health_payload.get("ok")
            ):
                warnings.append(
                    _warning(
                        "definitions_service_unhealthy",
                        "Definitions-Service ist verfügbar, aber nicht healthy.",
                        field="library.definitions",
                        details=definitions_health_payload,
                    )
                )
            else:
                info.append(
                    _info(
                        "definitions_service_available",
                        "Definitions-Service ist importierbar und healthy.",
                    )
                )
        except Exception as exc:
            warnings.append(
                _exception_warning(
                    "definitions_service_health_failed",
                    exc,
                    field="library.definitions.health",
                    fallback_message="Definitions-Health konnte nicht ausgeführt werden.",
                )
            )
            definitions_health_payload = _definitions_unavailable_payload(
                reason="health_failed",
                exc=exc,
            )

    ok = len(errors) == 0

    return RouteResponse(
        ok=ok,
        status="healthy" if ok else "unhealthy",
        route=route,
        data={
            "service": LIBRARY_CREATE_ROUTE_SERVICE_COMPONENT,
            "version": LIBRARY_CREATE_ROUTE_SERVICE_VERSION,
            "api_prefix": CREATE_API_PREFIX,
            "page_route": CREATE_PAGE_ROUTE,
            "route_plan": get_route_plan(),
            "dependency": {
                "create_service_available": service_available,
                "create_service_component": _get_create_service_attr(
                    "LIBRARY_CREATE_SERVICE_COMPONENT",
                    default="library-create-service",
                ),
                "create_service_version": _get_create_service_attr(
                    "LIBRARY_CREATE_SERVICE_VERSION",
                    default="unknown",
                ),
                "payload_normalizer_available": payload_normalizer_available,
                "payload_normalizer_component": "library_create_variant_payload_service",
                "taxonomy_service_available": taxonomy_available,
                "taxonomy_required_fields": list(TAXONOMY_REQUIRED_FIELDS),
                "definitions_service_available": definitions_available,
            },
            "create_service_health": service_health_payload,
            "payload_normalizer_health": payload_normalizer_health_payload,
            "taxonomy_service_health": taxonomy_health_payload,
            "definitions_service_health": definitions_health_payload,
            "timestamp": _utc_now(),
        },
        errors=errors,
        warnings=warnings,
        info=info,
        http_status=200 if ok else 503,
    )


def get_options_response() -> RouteResponse:
    """
    Return create options in a route envelope.

    This endpoint merges:
    - delegated create-service options
    - canonical backend taxonomy
    - backend-owned definitions

    Taxonomy failure is hard because taxonomy fields are required.
    Definitions failure is soft: definitions.ok=false is attached and the
    response remains usable.
    """
    route = "options"

    if not _is_create_service_available():
        return _service_unavailable(route)

    try:
        result = _create_service.get_create_options()  # type: ignore[union-attr]
        response = _wrap_create_result(result, route=route)
        response = _enrich_options_response_with_taxonomy(response)

        if not response.ok:
            return response

        response = _enrich_options_response_with_definitions(response)

        data = dict(response.data)
        data.setdefault("vplib_uid", "")
        data.setdefault("vplib_uid_field", VPLIB_UID_FIELD)
        data.setdefault("create_payload_normalization", {})
        if isinstance(data["create_payload_normalization"], Mapping):
            data["create_payload_normalization"] = {
                **dict(data["create_payload_normalization"]),
                "enabled": _is_variant_payload_service_available(),
                "vplib_uid_field": VPLIB_UID_FIELD,
                "uid_created_by": "library_create_variant_payload_service",
                "uid_persisted_in": "vplib.manifest.json",
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
            message="Create-Optionen konnten nicht geladen werden.",
            exc=exc,
            http_status=500,
        )


def build_draft_response(payload: Any) -> RouteResponse:
    """Normalize incoming user input to a draft response."""
    route = "draft"

    if not _is_create_service_available():
        return _service_unavailable(route)

    normalized_or_error = _normalize_create_action_payload(payload, route=route)
    if isinstance(normalized_or_error, RouteResponse):
        return normalized_or_error
    normalized_payload = normalized_or_error

    taxonomy_precheck = _prevalidate_taxonomy_payload(normalized_payload, route=route)
    if taxonomy_precheck is not None:
        return _attach_vplib_uid_to_response(taxonomy_precheck, payload=normalized_payload)

    try:
        result = _create_service.build_draft(normalized_payload)  # type: ignore[union-attr]
        response = _wrap_create_result(result, route=route)
        return _attach_vplib_uid_to_response(response, payload=normalized_payload, result=result)
    except Exception as exc:
        return _failure(
            route=route,
            code="draft_failed",
            message="Der Create-Draft konnte nicht erzeugt werden.",
            exc=exc,
            http_status=422,
        )


def validate_draft_response(payload: Any) -> RouteResponse:
    """Validate incoming user input."""
    route = "validate"

    if not _is_create_service_available():
        return _service_unavailable(route)

    normalized_or_error = _normalize_create_action_payload(payload, route=route)
    if isinstance(normalized_or_error, RouteResponse):
        return normalized_or_error
    normalized_payload = normalized_or_error

    taxonomy_precheck = _prevalidate_taxonomy_payload(normalized_payload, route=route)
    if taxonomy_precheck is not None:
        return _attach_vplib_uid_to_response(taxonomy_precheck, payload=normalized_payload)

    try:
        result = _create_service.validate_draft(normalized_payload)  # type: ignore[union-attr]
        response = _wrap_create_result(result, route=route)
        return _attach_vplib_uid_to_response(response, payload=normalized_payload, result=result)
    except Exception as exc:
        return _failure(
            route=route,
            code="validation_failed",
            message="Die Create-Validierung konnte nicht ausgeführt werden.",
            exc=exc,
            http_status=422,
        )


def build_package_plan_response(payload: Any, *, include_documents: bool = True) -> RouteResponse:
    """Build a package plan without writing files."""
    route = "package-plan"

    if not _is_create_service_available():
        return _service_unavailable(route)

    normalized_or_error = _normalize_create_action_payload(payload, route=route)
    if isinstance(normalized_or_error, RouteResponse):
        return normalized_or_error
    normalized_payload = normalized_or_error

    taxonomy_precheck = _prevalidate_taxonomy_payload(normalized_payload, route=route)
    if taxonomy_precheck is not None:
        return _attach_vplib_uid_to_response(taxonomy_precheck, payload=normalized_payload)

    try:
        result = _create_service.build_package_plan(  # type: ignore[union-attr]
            normalized_payload,
            include_documents=include_documents,
        )
        response = _wrap_create_result(result, route=route)
        return _attach_vplib_uid_to_response(response, payload=normalized_payload, result=result)
    except Exception as exc:
        return _failure(
            route=route,
            code="package_plan_failed",
            message="Der Package-Plan konnte nicht erzeugt werden.",
            exc=exc,
            http_status=500,
        )


def save_package_response(payload: Any, *, overwrite: bool | None = None) -> RouteResponse:
    """Save a package through the create service."""
    route = "save"

    if not _is_create_service_available():
        return _service_unavailable(route)

    normalized_or_error = _normalize_create_action_payload(payload, route=route)
    if isinstance(normalized_or_error, RouteResponse):
        return normalized_or_error
    normalized_payload = normalized_or_error

    taxonomy_precheck = _prevalidate_taxonomy_payload(normalized_payload, route=route)
    if taxonomy_precheck is not None:
        return _attach_vplib_uid_to_response(taxonomy_precheck, payload=normalized_payload)

    try:
        if overwrite is None:
            overwrite = _extract_overwrite(normalized_payload)

        result = _create_service.save_package(  # type: ignore[union-attr]
            normalized_payload,
            overwrite=overwrite,
        )
        response = _wrap_create_result(result, route=route)
        return _attach_vplib_uid_to_response(response, payload=normalized_payload, result=result)
    except Exception as exc:
        return _failure(
            route=route,
            code="save_failed",
            message="Das VPLIB-Package konnte nicht gespeichert werden.",
            exc=exc,
            http_status=500,
        )


def build_download_response(payload: Any) -> RouteBinaryResponse:
    """Build an in-memory .vplib archive for route handlers."""
    route = "download"

    if not _is_create_service_available():
        unavailable = _service_unavailable(route)
        return RouteBinaryResponse(
            ok=False,
            status=unavailable.status,
            route=route,
            filename="invalid.vplib",
            content=b"",
            data=unavailable.data,
            errors=unavailable.errors,
            warnings=unavailable.warnings,
            info=unavailable.info,
            http_status=unavailable.http_status,
        )

    normalized_or_error = _normalize_create_action_payload(payload, route=route)
    if isinstance(normalized_or_error, RouteResponse):
        error_response = normalized_or_error
        return RouteBinaryResponse(
            ok=False,
            status=error_response.status,
            route=route,
            filename="invalid.vplib",
            content=b"",
            data=error_response.data,
            errors=error_response.errors,
            warnings=error_response.warnings,
            info=error_response.info,
            http_status=error_response.http_status,
        )

    normalized_payload = normalized_or_error

    taxonomy_precheck = _prevalidate_taxonomy_payload(normalized_payload, route=route)
    if taxonomy_precheck is not None:
        taxonomy_precheck = _attach_vplib_uid_to_response(taxonomy_precheck, payload=normalized_payload)
        return RouteBinaryResponse(
            ok=False,
            status=taxonomy_precheck.status,
            route=route,
            filename="invalid.vplib",
            content=b"",
            data=taxonomy_precheck.data,
            errors=taxonomy_precheck.errors,
            warnings=taxonomy_precheck.warnings,
            info=taxonomy_precheck.info,
            http_status=taxonomy_precheck.http_status,
        )

    try:
        filename, content, result = _create_service.build_vplib_archive(normalized_payload)  # type: ignore[union-attr]
        wrapped = _wrap_create_result(result, route=route)
        wrapped = _attach_vplib_uid_to_response(wrapped, payload=normalized_payload, result=result)

        return RouteBinaryResponse(
            ok=wrapped.ok,
            status=wrapped.status,
            route=route,
            filename=_safe_download_filename(filename),
            content=content if wrapped.ok else b"",
            mimetype=DEFAULT_VPLIB_MIMETYPE,
            data=wrapped.data,
            errors=wrapped.errors,
            warnings=wrapped.warnings,
            info=wrapped.info,
            http_status=wrapped.http_status,
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
                "route_service": _route_service_metadata(route, normalized_payload),
            },
            errors=[issue],
            http_status=500,
        )


def clear_cache_response() -> RouteResponse:
    """
    Clear create-route related caches.

    The create route service currently has no own package cache, but the
    taxonomy service and definitions service cache registry/payload data.
    Clearing them here makes the Create-Wizard reload changed taxonomy and
    definitions data during development and tests.
    """

    warnings: list[RouteIssue | dict[str, Any]] = []
    info: list[RouteIssue | dict[str, Any]] = []

    taxonomy_cleared = False
    definitions_cleared = False

    if _is_taxonomy_service_available():
        try:
            _get_taxonomy_service().clear_cache()
            taxonomy_cleared = True
            info.append(
                _info(
                    "taxonomy_cache_cleared",
                    "Taxonomie-Service-Cache wurde geleert.",
                )
            )
        except Exception as exc:
            warnings.append(
                _exception_warning(
                    "taxonomy_cache_clear_failed",
                    exc,
                    field="library.taxonomy.cache",
                    fallback_message="Taxonomie-Cache konnte nicht geleert werden.",
                )
            )
    else:
        warnings.append(
            _exception_warning(
                "taxonomy_service_unavailable",
                _TAXONOMY_SERVICE_IMPORT_ERROR,
                field="library.taxonomy",
                fallback_message="Taxonomie-Service ist nicht verfügbar.",
            )
        )

    if _is_definitions_service_available():
        try:
            _call_definitions_payload_function("clear_definitions_caches")
            definitions_cleared = True
            info.append(
                _info(
                    "definitions_cache_cleared",
                    "Definitions-Service-Cache wurde geleert.",
                )
            )
        except Exception as exc:
            warnings.append(
                _exception_warning(
                    "definitions_cache_clear_failed",
                    exc,
                    field="library.definitions.cache",
                    fallback_message="Definitions-Cache konnte nicht geleert werden.",
                )
            )
    else:
        warnings.append(
            _exception_warning(
                "definitions_service_unavailable",
                _DEFINITIONS_SERVICE_IMPORT_ERROR,
                field="library.definitions",
                fallback_message="Definitions-Service ist nicht verfügbar.",
            )
        )

    return RouteResponse(
        ok=len(warnings) == 0,
        status="ok" if len(warnings) == 0 else "partial",
        route="cache-clear",
        data={
            "cleared": taxonomy_cleared and definitions_cleared,
            "cache": {
                "route_service": "none",
                "taxonomy_service": taxonomy_cleared,
                "definitions_service": definitions_cleared,
            },
            "message": "Create-Route-Service-Cache-Clear wurde ausgeführt.",
        },
        warnings=warnings,
        info=info,
        http_status=200 if len(warnings) == 0 else 207,
    )


def normalize_payload(payload: Any) -> dict[str, Any]:
    """
    Normalize route payloads before passing them to the create service.

    Accepts:
        - dict / Mapping
        - JSON string
        - bytes JSON
        - objects exposing to_dict()
        - objects exposing items()

    This function does not create `vplib_uid`.
    Create actions use _normalize_create_action_payload(...), which calls this
    function first and then delegates to library_create_variant_payload_service.
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
    """
    Merge multiple payload sources.

    Later payloads override earlier payloads.
    Useful for route adapters combining:
        - JSON body
        - form body
        - query args
    """
    merged: dict[str, Any] = {}

    for payload in payloads:
        if payload is None:
            continue
        normalized = normalize_payload(payload)
        merged.update(normalized)

    return merged


def response_to_tuple(response: RouteResponse) -> tuple[dict[str, Any], int]:
    """
    Convenience helper for Flask adapters.

    Example:
        payload, status = response_to_tuple(get_options_response())
        return jsonify(payload), status
    """
    return response.to_dict(include_http_status=True), _safe_http_status(response.http_status)


def binary_response_to_meta_tuple(response: RouteBinaryResponse) -> tuple[dict[str, Any], int]:
    """
    Return metadata for a binary response as JSON.

    Used when the binary generation failed or when a route wants to expose
    metadata instead of bytes.
    """
    return response.to_dict(include_http_status=True), _safe_http_status(response.http_status)


health = get_route_service_health
options = get_options_response
draft = build_draft_response
validate = validate_draft_response
package_plan = build_package_plan_response
download = build_download_response
save = save_package_response
cache_clear = clear_cache_response


def _normalize_create_action_payload(payload: Any, *, route: str) -> dict[str, Any] | RouteResponse:
    """
    Normalize a create action payload and ensure stable `vplib_uid`.

    Returns:
        dict on success
        RouteResponse on failure
    """
    try:
        base_payload = normalize_payload(payload)
    except Exception as exc:
        return _failure(
            route=route,
            code="payload_normalization_failed",
            message="Payload konnte nicht normalisiert werden.",
            exc=exc,
            http_status=400,
        )

    if not _is_variant_payload_service_available():
        return RouteResponse(
            ok=False,
            status="payload_normalizer_unavailable",
            route=route,
            data={
                "route_service": _route_service_metadata(route, base_payload),
                "payload_normalizer_available": False,
                "vplib_uid": _extract_vplib_uid_from_any(base_payload),
            },
            errors=[
                _exception_issue(
                    "create_payload_normalizer_unavailable",
                    _VARIANT_PAYLOAD_SERVICE_IMPORT_ERROR,
                    field="library_create_variant_payload_service",
                    fallback_message="Create-Payload-Normalizer ist nicht verfügbar.",
                )
            ],
            http_status=500,
        )

    try:
        normalizer = getattr(_variant_payload_service, "normalize_create_variant_payload")
        normalized_payload = normalizer(
            base_payload,
            ensure_uid=True,
            overwrite_invalid_uid=False,
            include_report=True,
            strict=True,
        )

        if not isinstance(normalized_payload, Mapping):
            raise TypeError("Create-Payload-Normalizer returned non-mapping payload.")

        result = dict(normalized_payload)
        uid = _extract_vplib_uid_from_any(result)
        if uid:
            result[VPLIB_UID_FIELD] = uid

        return result
    except Exception as exc:
        return RouteResponse(
            ok=False,
            status="payload_normalization_failed",
            route=route,
            data={
                "route_service": _route_service_metadata(route, base_payload),
                "vplib_uid": _extract_vplib_uid_from_any(base_payload),
                "payload_normalizer_available": True,
            },
            errors=[
                _exception_issue(
                    "create_payload_normalization_failed",
                    exc,
                    field=VPLIB_UID_FIELD,
                    fallback_message="Create-Payload konnte nicht für VPLIB-Erzeugung normalisiert werden.",
                )
            ],
            http_status=422,
        )


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
        route_data["route_service"].update(
            {
                "component": LIBRARY_CREATE_ROUTE_SERVICE_COMPONENT,
                "version": LIBRARY_CREATE_ROUTE_SERVICE_VERSION,
                "route": route,
                "api_prefix": CREATE_API_PREFIX,
                "taxonomy_required_fields": list(TAXONOMY_REQUIRED_FIELDS),
                "definitions_source": "backend_definitions_service",
                "payload_normalizer": "library_create_variant_payload_service",
                "vplib_uid_field": VPLIB_UID_FIELD,
                "vplib_uid": uid,
            }
        )

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
    data.setdefault("route_service", {})
    if isinstance(data["route_service"], Mapping):
        route_service = dict(data["route_service"])
    else:
        route_service = {}

    route_service.update(
        {
            "component": LIBRARY_CREATE_ROUTE_SERVICE_COMPONENT,
            "version": LIBRARY_CREATE_ROUTE_SERVICE_VERSION,
            "route": response.route,
            "api_prefix": CREATE_API_PREFIX,
            "payload_normalizer": "library_create_variant_payload_service",
            "vplib_uid_field": VPLIB_UID_FIELD,
            "vplib_uid": uid,
        }
    )
    data["route_service"] = route_service

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
        "definitions_source": "backend_definitions_service",
        "payload_normalizer": "library_create_variant_payload_service",
        "vplib_uid_field": VPLIB_UID_FIELD,
        "vplib_uid": uid,
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
                    "Create-Service hat kein Ergebnis geliefert.",
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
                "Create-Service hat einen unerwarteten Ergebnistyp geliefert.",
                details={"type": type(result).__name__},
            ).to_dict()
        ],
        "warnings": [],
        "info": [],
        "_http_status": 500,
    }


def _enrich_options_response_with_taxonomy(response: RouteResponse) -> RouteResponse:
    """
    Merge canonical backend taxonomy into the create/options response.

    This function intentionally overwrites any previous route-level taxonomy
    option fields from the older create service, because backend taxonomy is now
    the single source of truth for domain/category/subcategory.
    """

    data = dict(response.data)
    warnings = list(response.warnings)
    errors = list(response.errors)
    info = list(response.info)

    if not _is_taxonomy_service_available():
        errors.append(
            _exception_issue(
                "taxonomy_service_unavailable",
                _TAXONOMY_SERVICE_IMPORT_ERROR,
                field="library.taxonomy",
                fallback_message="Taxonomie-Service ist nicht verfügbar.",
            )
        )
        return RouteResponse(
            ok=False,
            status="taxonomy_unavailable",
            route=response.route,
            data=data,
            errors=errors,
            warnings=warnings,
            info=info,
            http_status=503,
        )

    try:
        taxonomy_payload = _get_taxonomy_service().get_create_options_payload()

        data["taxonomy"] = taxonomy_payload.get("taxonomy", {})
        data["taxonomy_version"] = taxonomy_payload.get("taxonomy_version", "")
        data["taxonomy_schema_version"] = taxonomy_payload.get("taxonomy_schema_version", "")
        data["taxonomy_source"] = "backend_taxonomy_service"
        data["required_taxonomy_fields"] = list(TAXONOMY_REQUIRED_FIELDS)

        data["domains"] = taxonomy_payload.get("domains", [])
        data["categories_by_domain"] = taxonomy_payload.get("categories_by_domain", {})
        data["subcategories_by_category"] = taxonomy_payload.get("subcategories_by_category", {})

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
                "Kanonische Backend-Taxonomie wurde an Create-Optionen angehängt.",
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
        errors.append(
            _exception_issue(
                "taxonomy_options_failed",
                exc,
                field="library.taxonomy.options",
                fallback_message="Taxonomie-Optionen konnten nicht geladen werden.",
            )
        )
        return RouteResponse(
            ok=False,
            status="taxonomy_options_failed",
            route=response.route,
            data=data,
            errors=errors,
            warnings=warnings,
            info=info,
            http_status=503,
        )


def _enrich_options_response_with_definitions(response: RouteResponse) -> RouteResponse:
    """
    Merge backend-owned definitions into the create/options response.

    Definitions are intentionally a soft dependency for this endpoint:
    - if available: attach full definitions payload and flattened convenience lists
    - if unavailable: attach definitions.ok=false and add warning
    """

    data = dict(response.data)
    warnings = list(response.warnings)
    errors = list(response.errors)
    info = list(response.info)

    if not _is_definitions_service_available():
        unavailable = _definitions_unavailable_payload(
            reason="import_failed",
            exc=_DEFINITIONS_SERVICE_IMPORT_ERROR,
        )
        data = _attach_unavailable_definitions_payload(data, unavailable)
        warnings.append(
            _exception_warning(
                "definitions_service_unavailable",
                _DEFINITIONS_SERVICE_IMPORT_ERROR,
                field="library.definitions",
                fallback_message=(
                    "Definitions-Service ist nicht verfügbar. "
                    "Create-Optionen wurden ohne Definitionsdaten geliefert."
                ),
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
        definitions_payload = _call_definitions_payload_function(
            "get_create_definition_options",
            include_inactive=False,
            include_internal=False,
            force_refresh=False,
            force_reload=False,
        )

        if not isinstance(definitions_payload, Mapping):
            raise TypeError(
                "Definitions-Service returned non-mapping payload for create options."
            )

        data = _attach_definitions_payload(data, dict(definitions_payload))

        if not bool(definitions_payload.get("ok", True)):
            warnings.append(
                _warning(
                    "definitions_options_not_ok",
                    "Definitions-Service hat Optionen geliefert, meldet aber ok=false.",
                    field="library.definitions.options",
                    details=dict(definitions_payload),
                )
            )
        else:
            info.append(
                _info(
                    "definitions_options_attached",
                    "Backend-Definitionsdaten wurden an Create-Optionen angehängt.",
                    details={
                        "definitions_version": definitions_payload.get("definitions_version"),
                        "schema_version": definitions_payload.get("schema_version"),
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

    except Exception as exc:
        unavailable = _definitions_unavailable_payload(
            reason="options_failed",
            exc=exc,
        )
        data = _attach_unavailable_definitions_payload(data, unavailable)
        warnings.append(
            _exception_warning(
                "definitions_options_failed",
                exc,
                field="library.definitions.options",
                fallback_message=(
                    "Definitions-Optionen konnten nicht geladen werden. "
                    "Create-Optionen wurden ohne Definitionsdaten geliefert."
                ),
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


def _attach_definitions_payload(
    data: dict[str, Any],
    definitions_payload: Mapping[str, Any],
) -> dict[str, Any]:
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
        "definitions_version": definitions_payload.get("definitions_version"),
        "schema_version": definitions_payload.get("schema_version"),
        "counts": definitions_payload.get("counts", {}),
    }
    enriched["definitions_source"] = "backend_definitions_service"
    enriched["definitions_options"] = dict(definition_options)
    enriched["definition_catalogs"] = dict(definition_catalogs)

    enriched["object_kinds"] = list(definition_options.get("object_kinds", []))
    enriched["family_profiles"] = list(definition_options.get("family_profiles", []))
    enriched["variant_profiles"] = list(definition_options.get("variant_profiles", []))
    enriched["materials"] = list(definition_options.get("materials", []))
    enriched["document_types"] = list(definition_options.get("document_types", []))
    enriched["units"] = list(definition_options.get("units", []))

    enriched["object_kind_definitions"] = list(definition_catalogs.get("object_kinds", []))
    enriched["family_profile_definitions"] = list(definition_catalogs.get("family_profiles", []))
    enriched["variant_profile_definitions"] = list(definition_catalogs.get("variant_profiles", []))
    enriched["variables"] = list(definition_catalogs.get("variables", []))
    enriched["unit_definitions"] = list(definition_catalogs.get("units", []))
    enriched["material_definitions"] = list(definition_catalogs.get("materials", []))
    enriched["document_type_definitions"] = list(definition_catalogs.get("document_types", []))
    enriched["profile_bindings"] = list(definition_catalogs.get("profile_bindings", []))

    enriched.setdefault("constraints", {})
    if isinstance(enriched["constraints"], Mapping):
        constraints = dict(enriched["constraints"])
        constraints["definitions"] = {
            "definitions_version": definitions_payload.get("definitions_version"),
            "schema_version": definitions_payload.get("schema_version"),
            "counts": definitions_payload.get("counts", {}),
            "variant_profile_required": True,
            "frontend_must_render_profiles_from_backend": True,
        }
        enriched["constraints"] = constraints

    enriched.setdefault("defaults", {})
    if isinstance(enriched["defaults"], Mapping):
        defaults = dict(enriched["defaults"])
        defaults["definitions"] = {
            "definitions_version": definitions_payload.get("definitions_version"),
            "default_object_kind": _first_option_id(definition_options.get("object_kinds")),
            "default_family_profile": _first_option_id(definition_options.get("family_profiles")),
            "default_variant_profile": _first_option_id(definition_options.get("variant_profiles")),
        }
        enriched["defaults"] = defaults

    return enriched


def _attach_unavailable_definitions_payload(
    data: dict[str, Any],
    unavailable_payload: Mapping[str, Any],
) -> dict[str, Any]:
    enriched = dict(data)

    enriched["definitions"] = dict(unavailable_payload)
    enriched["definitions_health"] = dict(unavailable_payload)
    enriched["definitions_source"] = "backend_definitions_service_unavailable"
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


def _prevalidate_taxonomy_payload(payload: Mapping[str, Any], *, route: str) -> RouteResponse | None:
    """
    Route-level taxonomy validation before delegating to create service.

    This keeps the new required fields visible and consistent even if the older
    create service still contains fallback defaults such as subcategory=basis.
    """

    if not _is_taxonomy_service_available():
        return RouteResponse(
            ok=False,
            status="taxonomy_unavailable",
            route=route,
            data={
                "route_service": _route_service_metadata(route, payload),
                "required_taxonomy_fields": list(TAXONOMY_REQUIRED_FIELDS),
                "payload_taxonomy": _extract_taxonomy_selection_dict(payload),
                "vplib_uid": _extract_vplib_uid_from_any(payload),
            },
            errors=[
                _exception_issue(
                    "taxonomy_service_unavailable",
                    _TAXONOMY_SERVICE_IMPORT_ERROR,
                    field="library.taxonomy",
                    fallback_message="Taxonomie-Service ist nicht verfügbar.",
                )
            ],
            http_status=503,
        )

    try:
        selection_payload = _extract_taxonomy_selection_dict(payload)
        object_kind = _taxonomy_normalize_slug(payload.get("object_kind"), default="")

        taxonomy_service = _get_taxonomy_service()
        validation = taxonomy_service.validate_selection(
            selection_payload.get("domain", ""),
            selection_payload.get("category", ""),
            selection_payload.get("subcategory", ""),
            object_kind=object_kind,
        )

        if validation.valid:
            return None

        return RouteResponse(
            ok=False,
            status="taxonomy_invalid",
            route=route,
            data={
                "route_service": _route_service_metadata(route, payload),
                "required_taxonomy_fields": list(TAXONOMY_REQUIRED_FIELDS),
                "payload_taxonomy": selection_payload,
                "object_kind": object_kind,
                "taxonomy_validation": validation.to_dict(),
                "vplib_uid": _extract_vplib_uid_from_any(payload),
            },
            errors=[
                _issue_from_taxonomy_issue(issue)
                for issue in validation.errors
            ],
            warnings=[
                _issue_from_taxonomy_issue(issue)
                for issue in validation.warnings
            ],
            info=[
                _issue_from_taxonomy_issue(issue)
                for issue in getattr(validation, "infos", ())
            ],
            http_status=422,
        )

    except Exception as exc:
        return RouteResponse(
            ok=False,
            status="taxonomy_validation_failed",
            route=route,
            data={
                "route_service": _route_service_metadata(route, payload),
                "required_taxonomy_fields": list(TAXONOMY_REQUIRED_FIELDS),
                "payload_taxonomy": _extract_taxonomy_selection_dict(payload),
                "vplib_uid": _extract_vplib_uid_from_any(payload),
            },
            errors=[
                _exception_issue(
                    "taxonomy_validation_failed",
                    exc,
                    field="taxonomy",
                    fallback_message="Taxonomie-Validierung konnte nicht ausgeführt werden.",
                )
            ],
            http_status=422,
        )


def _extract_taxonomy_selection_dict(payload: Mapping[str, Any]) -> dict[str, str]:
    """
    Extract domain/category/subcategory from flat or nested payload.

    Supported:
        {"domain": "...", "category": "...", "subcategory": "..."}
        {"classification": {"domain": "...", "category": "...", "subcategory": "..."}}
    """

    source = payload
    nested = payload.get("classification")

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


def _issue_from_taxonomy_issue(issue: Any) -> dict[str, Any]:
    if hasattr(issue, "to_dict") and callable(issue.to_dict):
        try:
            payload = issue.to_dict()
            if isinstance(payload, Mapping):
                return _issue_to_dict(payload)
        except Exception:
            pass

    return _issue_to_dict(issue)


def _normalize_mapping_payload(payload: Mapping[str, Any]) -> dict[str, Any]:
    normalized: dict[str, Any] = {}

    for key, value in payload.items():
        key_text = str(key)

        if isinstance(value, (list, tuple)):
            if len(value) == 1:
                normalized[key_text] = value[0]
            else:
                normalized[key_text] = list(value)
        else:
            normalized[key_text] = value

    return normalized


def _extract_overwrite(payload: Mapping[str, Any]) -> bool | None:
    for key in ["overwrite", "allow_overwrite", "replace_existing"]:
        if key in payload:
            return _safe_bool(payload.get(key), default=False)
    return None


def _is_create_service_available() -> bool:
    return _create_service is not None and _CREATE_SERVICE_IMPORT_ERROR is None


def _is_variant_payload_service_available() -> bool:
    return _variant_payload_service is not None and _VARIANT_PAYLOAD_SERVICE_IMPORT_ERROR is None


def _is_taxonomy_service_available() -> bool:
    return get_default_taxonomy_service is not None and _TAXONOMY_SERVICE_IMPORT_ERROR is None


def _is_definitions_service_available() -> bool:
    return _definitions_service is not None and _DEFINITIONS_SERVICE_IMPORT_ERROR is None


def _get_taxonomy_service() -> Any:
    if not _is_taxonomy_service_available():
        raise RuntimeError("Taxonomie-Service ist nicht verfügbar.")
    return get_default_taxonomy_service()  # type: ignore[misc]


def _call_definitions_payload_function(
    function_name: str,
    *args: Any,
    **kwargs: Any,
) -> dict[str, Any]:
    if not _is_definitions_service_available():
        raise RuntimeError("Definitions-Service ist nicht verfügbar.")

    function = getattr(_definitions_service, function_name, None)
    if not callable(function):
        raise AttributeError(f"Definitions-Service exportiert {function_name!r} nicht.")

    safe_kwargs = _filter_supported_kwargs(function, kwargs)
    result = function(*args, **safe_kwargs)

    if isinstance(result, Mapping):
        return dict(result)

    return {
        "ok": result is not None,
        "status": "ok" if result is not None else "empty",
        "value": result,
    }


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


def _definitions_unavailable_payload(
    *,
    reason: str,
    exc: BaseException | None = None,
) -> dict[str, Any]:
    payload = {
        "ok": False,
        "healthy": False,
        "status": "unavailable",
        "component": "library.definitions",
        "reason": reason,
        "error": {
            "type": type(exc).__name__ if exc is not None else None,
            "message": str(exc) if exc is not None else "Definitions-Service ist nicht verfügbar.",
        },
    }
    return payload


def _get_create_service_attr(name: str, *, default: Any = None) -> Any:
    try:
        if _create_service is None:
            return default
        return getattr(_create_service, name, default)
    except Exception:
        return default


def _get_variant_payload_service_attr(name: str, *, default: Any = None) -> Any:
    try:
        if _variant_payload_service is None:
            return default
        return getattr(_variant_payload_service, name, default)
    except Exception:
        return default


def _service_unavailable(route: str) -> RouteResponse:
    return RouteResponse(
        ok=False,
        status="service_unavailable",
        route=route,
        data={
            "dependency": "library.services.library_create_service",
            "available": False,
            "route_plan": get_route_plan(),
        },
        errors=[
            _exception_issue(
                "create_service_unavailable",
                _CREATE_SERVICE_IMPORT_ERROR,
                field="library.services.library_create_service",
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
            "route_service": {
                "component": LIBRARY_CREATE_ROUTE_SERVICE_COMPONENT,
                "version": LIBRARY_CREATE_ROUTE_SERVICE_VERSION,
                "route": route,
                "api_prefix": CREATE_API_PREFIX,
                "taxonomy_required_fields": list(TAXONOMY_REQUIRED_FIELDS),
                "definitions_source": "backend_definitions_service",
                "payload_normalizer": "library_create_variant_payload_service",
                "vplib_uid_field": VPLIB_UID_FIELD,
            }
        },
        errors=errors,
        http_status=http_status,
    )


def _issue_to_dict(issue: RouteIssue | Mapping[str, Any] | Any) -> dict[str, Any]:
    if isinstance(issue, RouteIssue):
        return issue.to_dict()

    if isinstance(issue, Mapping):
        severity = str(issue.get("severity") or "error")
        code = str(issue.get("code") or issue.get("type") or "issue")
        message = str(issue.get("message") or issue.get("text") or issue.get("detail") or "")
        field = str(issue.get("field") or "")
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
            fallback_message or "Unbekannter Fehler.",
            field=field,
            details={"exception": None},
        )

    details: dict[str, Any] = {
        "exception_type": type(exc).__name__,
        "exception": str(exc),
    }

    try:
        details["traceback"] = traceback.format_exc()
    except Exception:
        pass

    return _error(
        code,
        fallback_message or str(exc) or type(exc).__name__,
        field=field,
        details=details,
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
            fallback_message or "Unbekannter Fehler.",
            field=field,
            details={"exception": None},
        )

    details: dict[str, Any] = {
        "exception_type": type(exc).__name__,
        "exception": str(exc),
    }

    try:
        details["traceback"] = traceback.format_exc()
    except Exception:
        pass

    return _warning(
        code,
        fallback_message or str(exc) or type(exc).__name__,
        field=field,
        details=details,
    )


def _extract_vplib_uid_from_any(value: Any, *, _depth: int = 0) -> str | None:
    """Extract a valid `vplib_uid` from mappings, results or nested payloads."""
    if value is None or _depth > 5:
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
            "manifest",
            "vplib_manifest",
            "document_bundle",
            "creation_result",
            "package_result",
            "result",
            "route_service",
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
            if hasattr(value, attr_name):
                uid = _normalize_vplib_uid_safe(getattr(value, attr_name))
                if uid:
                    return uid
        except Exception:
            continue

    for nested_attr in (
        "data",
        "metadata",
        "payload",
        "manifest",
        "vplib_manifest",
        "document_bundle",
        "creation_result",
        "package_result",
        "result",
        "route_service",
    ):
        try:
            nested = getattr(value, nested_attr, None)
            uid = _extract_vplib_uid_from_any(nested, _depth=_depth + 1)
            if uid:
                return uid
        except Exception:
            continue

    if hasattr(value, "to_dict") and callable(value.to_dict):
        try:
            payload = value.to_dict()
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

    try:
        if _is_variant_payload_service_available():
            normalizer = getattr(_variant_payload_service, "normalize_vplib_uid_safe", None)
            if callable(normalizer):
                uid = normalizer(value)
                if uid:
                    return str(uid)
    except Exception:
        pass

    try:
        from vplib.vplib_id_service import normalize_vplib_uid

        uid = normalize_vplib_uid(value)
        if uid:
            return str(uid)
    except Exception:
        pass

    try:
        from src.vplib.vplib_id_service import normalize_vplib_uid  # type: ignore

        uid = normalize_vplib_uid(value)
        if uid:
            return str(uid)
    except Exception:
        pass

    try:
        parsed = uuid.UUID(str(value).strip())
        return str(parsed).lower()
    except Exception:
        return None


def _json_safe(value: Any) -> Any:
    if value is None or isinstance(value, (str, int, float, bool)):
        return value

    if isinstance(value, bytes):
        return {
            "type": "bytes",
            "size_bytes": len(value),
        }

    if isinstance(value, RouteIssue):
        return value.to_dict()

    if isinstance(value, Mapping):
        return {str(key): _json_safe(inner_value) for key, inner_value in value.items()}

    if isinstance(value, (list, tuple, set)):
        return [_json_safe(item) for item in value]

    try:
        json.dumps(value)
        return value
    except Exception:
        return str(value)


def _safe_bool(value: Any, *, default: bool = False) -> bool:
    if value is None:
        return default

    if isinstance(value, bool):
        return value

    text = str(value).strip().lower()

    if text in {"1", "true", "yes", "ja", "on", "enabled", "active", "allow", "allowed"}:
        return True

    if text in {"0", "false", "no", "nein", "off", "disabled", "inactive", "deny", "blocked"}:
        return False

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


def _first_option_id(value: Any) -> str:
    if not isinstance(value, (list, tuple)) or not value:
        return ""

    first = value[0]
    if isinstance(first, Mapping):
        return str(first.get("id") or first.get("value") or "").strip()

    return str(first or "").strip()


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z")


__all__ = [
    "CREATE_API_PREFIX",
    "CREATE_PAGE_ROUTE",
    "DEFAULT_JSON_MIMETYPE",
    "DEFAULT_VPLIB_MIMETYPE",
    "LIBRARY_CREATE_ROUTE_SERVICE_COMPONENT",
    "LIBRARY_CREATE_ROUTE_SERVICE_VERSION",
    "TAXONOMY_REQUIRED_FIELDS",
    "VPLIB_UID_FIELD",
    "RouteBinaryResponse",
    "RouteIssue",
    "RouteResponse",
    "binary_response_to_meta_tuple",
    "build_download_response",
    "build_draft_response",
    "build_package_plan_response",
    "cache_clear",
    "clear_cache_response",
    "download",
    "draft",
    "get_options_response",
    "get_route_plan",
    "get_route_service_health",
    "health",
    "merge_payloads",
    "normalize_payload",
    "options",
    "package_plan",
    "response_to_tuple",
    "save",
    "save_package_response",
    "validate",
    "validate_draft_response",
]