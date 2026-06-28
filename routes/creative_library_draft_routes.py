# services/vectoplan-library/routes/creative_library_draft_routes.py
"""
Flask routes for VECTOPLAN Creative Library Drafts.

Route prefix:
- /api/v1/vplib/library/drafts

This route layer is intentionally thin:

- parse Flask request args/json/form/files
- call src.library.services.creative_library_draft_service.CreativeLibraryDraftService
- jsonify returned dictionaries
- map exceptions to API-safe JSON responses

Business logic lives in:
- src/library/services/creative_library_draft_service.py
- src/library/repositories/creative_library_draft_repository.py

Supported workflows:

- create draft
- list drafts
- read draft
- update draft
- discard draft
- delete draft
- add/update/delete variants
- add/update/delete assets
- add/update/delete documents
- upload file as draft document
- validate draft
- set validation issues
- prepare publish payload
- publish draft through optional publish adapter
- list audit events
"""

from __future__ import annotations

import importlib
import logging
from functools import lru_cache
from types import ModuleType
from typing import Any, Callable, Dict, Mapping

from flask import Blueprint, Response, jsonify, request


CREATIVE_LIBRARY_DRAFT_ROUTES_COMPONENT = "routes.creative_library_draft_routes"
CREATIVE_LIBRARY_DRAFT_ROUTES_VERSION = "1.0.0"
CREATIVE_LIBRARY_DRAFT_ROUTE_PREFIX = "/api/v1/vplib/library/drafts"

_LOGGER = logging.getLogger(__name__)


creative_library_drafts_bp = Blueprint(
    "creative_library_drafts",
    __name__,
    url_prefix=CREATIVE_LIBRARY_DRAFT_ROUTE_PREFIX,
)

creative_library_draft_bp = creative_library_drafts_bp
creative_library_draft_routes_bp = creative_library_drafts_bp
creative_drafts_bp = creative_library_drafts_bp
drafts_bp = creative_library_drafts_bp

bp = creative_library_drafts_bp
blueprint = creative_library_drafts_bp


# ---------------------------------------------------------------------------
# Lazy service imports
# ---------------------------------------------------------------------------

@lru_cache(maxsize=1)
def _load_draft_service_module() -> ModuleType:
    """Loads creative_library_draft_service defensively."""
    errors: list[str] = []

    for module_name in (
        "src.library.services.creative_library_draft_service",
        "library.services.creative_library_draft_service",
        "vectoplan_library.src.library.services.creative_library_draft_service",
        "vectoplan_library.library.services.creative_library_draft_service",
    ):
        try:
            return importlib.import_module(module_name)
        except Exception as exc:
            errors.append(f"{module_name}: {type(exc).__name__}: {exc}")

    raise ImportError(
        "Could not import creative_library_draft_service. "
        + " | ".join(errors)
    )


def _create_draft_service() -> Any:
    """Creates CreativeLibraryDraftService per request."""
    module = _load_draft_service_module()

    factory = getattr(module, "create_creative_library_draft_service", None)
    if callable(factory):
        return factory()

    service_class = getattr(module, "CreativeLibraryDraftService", None)
    if service_class is None:
        raise RuntimeError("CreativeLibraryDraftService is not available.")

    return service_class()


# ---------------------------------------------------------------------------
# Diagnostics
# ---------------------------------------------------------------------------

@creative_library_drafts_bp.get("/health")
def creative_library_drafts_health() -> Response:
    return _json_response(get_creative_library_draft_routes_health())


@creative_library_drafts_bp.get("/routes")
def creative_library_drafts_routes_map() -> Response:
    return _json_response(get_creative_library_draft_route_map_response())


@creative_library_drafts_bp.get("/selftest")
def creative_library_drafts_selftest() -> Response:
    return _json_response(
        {
            "ok": True,
            "healthy": True,
            "status": "ok",
            "component": CREATIVE_LIBRARY_DRAFT_ROUTES_COMPONENT,
            "version": CREATIVE_LIBRARY_DRAFT_ROUTES_VERSION,
            "route_prefix": CREATIVE_LIBRARY_DRAFT_ROUTE_PREFIX,
            "blueprint": creative_library_drafts_bp.name,
            "service": _safe_draft_service_health(),
        }
    )


@creative_library_drafts_bp.post("/cache/clear")
def creative_library_drafts_cache_clear() -> Response:
    return _json_response(clear_creative_library_draft_routes_caches())


# ---------------------------------------------------------------------------
# Draft CRUD
# ---------------------------------------------------------------------------

@creative_library_drafts_bp.get("")
@creative_library_drafts_bp.get("/")
def creative_library_drafts_list() -> Response:
    """
    List drafts.

    GET /api/v1/vplib/library/drafts?user_id=1&status=draft
    """
    return _json_response(
        _safe_service_call(
            lambda service: service.list_drafts(
                user_id=_int_arg("user_id", default=1),
                status=_str_arg("status"),
                mode=_str_arg("mode"),
                target_vplib_uid=_str_arg("target_vplib_uid") or _str_arg("vplib_uid"),
                include_deleted=_bool_arg("include_deleted", default=False),
                include_published=_bool_arg("include_published", default=True),
                include_discarded=_bool_arg("include_discarded", default=False),
                limit=_int_arg("limit", default=100) or 100,
                offset=_int_arg("offset", default=0) or 0,
            )
        )
    )


@creative_library_drafts_bp.post("")
@creative_library_drafts_bp.post("/")
def creative_library_drafts_create() -> Response:
    """
    Create draft.

    JSON payload may include:
    - family_payload
    - classification_payload
    - manifest_payload
    - modules_payload
    - generator_payload
    - variants[]
    - assets[]
    - documents[]
    """
    payload = _merged_request_payload()

    return _json_response(
        _safe_service_call(
            lambda service: service.create_draft(
                payload,
                user_id=payload.get("user_id"),
                auto_validate=_bool_value(payload.get("auto_validate"), default=False),
                commit=True,
            )
        )
    )


@creative_library_drafts_bp.get("/<string:draft_ref>")
def creative_library_drafts_get(draft_ref: str) -> Response:
    """Read one draft."""
    return _json_response(
        _safe_service_call(
            lambda service: service.get_draft(
                draft_ref,
                include_variants=_bool_arg("include_variants", default=True),
                include_assets=_bool_arg("include_assets", default=True),
                include_documents=_bool_arg("include_documents", default=True),
                include_issues=_bool_arg("include_issues", default=True),
                include_audit=_bool_arg("include_audit", default=False),
                include_summary=_bool_arg("include_summary", default=True),
            )
        )
    )


@creative_library_drafts_bp.patch("/<string:draft_ref>")
def creative_library_drafts_patch(draft_ref: str) -> Response:
    """Update draft."""
    payload = _merged_request_payload()

    return _json_response(
        _safe_service_call(
            lambda service: service.update_draft(
                draft_ref,
                payload,
                user_id=payload.get("user_id"),
                auto_validate=_bool_value(payload.get("auto_validate"), default=False),
                commit=True,
            )
        )
    )


@creative_library_drafts_bp.delete("/<string:draft_ref>")
def creative_library_drafts_delete(draft_ref: str) -> Response:
    """Soft-delete draft."""
    payload = _merged_request_payload()

    return _json_response(
        _safe_service_call(
            lambda service: service.delete_draft(
                draft_ref,
                user_id=payload.get("user_id"),
                commit=True,
            )
        )
    )


@creative_library_drafts_bp.post("/<string:draft_ref>/discard")
def creative_library_drafts_discard(draft_ref: str) -> Response:
    """Discard draft."""
    payload = _merged_request_payload()

    return _json_response(
        _safe_service_call(
            lambda service: service.discard_draft(
                draft_ref,
                user_id=payload.get("user_id"),
                commit=True,
            )
        )
    )


# ---------------------------------------------------------------------------
# Validation
# ---------------------------------------------------------------------------

@creative_library_drafts_bp.post("/<string:draft_ref>/validate")
def creative_library_drafts_validate(draft_ref: str) -> Response:
    """Validate draft and store validation issues."""
    payload = _merged_request_payload()

    return _json_response(
        _safe_service_call(
            lambda service: service.validate_draft(
                draft_ref,
                user_id=payload.get("user_id"),
                replace_existing=_bool_value(payload.get("replace_existing"), default=True),
                commit=True,
            )
        )
    )


@creative_library_drafts_bp.get("/<string:draft_ref>/validation-issues")
def creative_library_drafts_validation_issues_list(draft_ref: str) -> Response:
    """List validation issues for one draft."""
    return _json_response(
        _safe_service_call(
            lambda service: {
                "ok": True,
                "healthy": True,
                "status": "ok",
                "component": CREATIVE_LIBRARY_DRAFT_ROUTES_COMPONENT,
                "version": CREATIVE_LIBRARY_DRAFT_ROUTES_VERSION,
                "action": "list_validation_issues",
                "payload": {
                    "draft_ref": draft_ref,
                    "items": service.repository.list_validation_issues(
                        draft_ref,
                        severity=_str_arg("severity"),
                        unresolved_only=_bool_arg("unresolved_only", default=False),
                        blocking_only=_bool_arg("blocking_only", default=False),
                        as_dict=True,
                    ),
                },
            }
        )
    )


@creative_library_drafts_bp.post("/<string:draft_ref>/validation-issues")
def creative_library_drafts_validation_issues_set(draft_ref: str) -> Response:
    """
    Set externally computed validation issues.

    JSON:
        {"issues": [...], "replace_existing": true}
    """
    payload = _merged_request_payload()
    issues = payload.get("issues") or payload.get("validation_issues") or []

    return _json_response(
        _safe_service_call(
            lambda service: service.set_validation_issues(
                draft_ref,
                issues,
                user_id=payload.get("user_id"),
                replace_existing=_bool_value(payload.get("replace_existing"), default=True),
                commit=True,
            )
        )
    )


# ---------------------------------------------------------------------------
# Publish
# ---------------------------------------------------------------------------

@creative_library_drafts_bp.post("/<string:draft_ref>/publish/prepare")
def creative_library_drafts_publish_prepare(draft_ref: str) -> Response:
    """Build publish payload without writing published library tables."""
    payload = _merged_request_payload()

    return _json_response(
        _safe_service_call(
            lambda service: service.prepare_publish_payload(
                draft_ref,
                user_id=payload.get("user_id"),
                validate_first=_bool_value(payload.get("validate_first"), default=True),
                allow_invalid=_bool_value(payload.get("allow_invalid"), default=False),
            )
        )
    )


@creative_library_drafts_bp.post("/<string:draft_ref>/publish")
def creative_library_drafts_publish(draft_ref: str) -> Response:
    """Publish draft through optional publish adapter."""
    payload = _merged_request_payload()

    return _json_response(
        _safe_service_call(
            lambda service: service.publish_draft(
                draft_ref,
                user_id=payload.get("user_id"),
                validate_first=_bool_value(payload.get("validate_first"), default=True),
                allow_invalid=_bool_value(payload.get("allow_invalid"), default=False),
                commit=True,
            )
        )
    )


# ---------------------------------------------------------------------------
# Variants
# ---------------------------------------------------------------------------

@creative_library_drafts_bp.get("/<string:draft_ref>/variants")
def creative_library_drafts_variants_list(draft_ref: str) -> Response:
    """List draft variants."""
    return _json_response(
        _safe_service_call(
            lambda service: {
                "ok": True,
                "healthy": True,
                "status": "ok",
                "component": CREATIVE_LIBRARY_DRAFT_ROUTES_COMPONENT,
                "version": CREATIVE_LIBRARY_DRAFT_ROUTES_VERSION,
                "action": "list_variants",
                "payload": {
                    "draft_ref": draft_ref,
                    "items": service.repository.list_variants(
                        draft_ref,
                        query={
                            "active_only": _bool_arg("active_only", default=False),
                            "include_deleted": _bool_arg("include_deleted", default=False),
                        },
                        as_dict=True,
                    ),
                },
            }
        )
    )


@creative_library_drafts_bp.post("/<string:draft_ref>/variants")
def creative_library_drafts_variants_add(draft_ref: str) -> Response:
    """Add draft variant."""
    payload = _merged_request_payload()

    return _json_response(
        _safe_service_call(
            lambda service: service.add_variant(
                draft_ref,
                payload,
                user_id=payload.get("user_id"),
                commit=True,
            )
        )
    )


@creative_library_drafts_bp.patch("/variants/<string:variant_ref>")
def creative_library_drafts_variants_patch(variant_ref: str) -> Response:
    """Update draft variant."""
    payload = _merged_request_payload()

    return _json_response(
        _safe_service_call(
            lambda service: service.update_variant(
                variant_ref,
                payload,
                user_id=payload.get("user_id"),
                commit=True,
            )
        )
    )


@creative_library_drafts_bp.delete("/variants/<string:variant_ref>")
def creative_library_drafts_variants_delete(variant_ref: str) -> Response:
    """Soft-delete draft variant."""
    payload = _merged_request_payload()

    return _json_response(
        _safe_service_call(
            lambda service: service.delete_variant(
                variant_ref,
                user_id=payload.get("user_id"),
                commit=True,
            )
        )
    )


# ---------------------------------------------------------------------------
# Assets
# ---------------------------------------------------------------------------

@creative_library_drafts_bp.get("/<string:draft_ref>/assets")
def creative_library_drafts_assets_list(draft_ref: str) -> Response:
    """List draft assets."""
    return _json_response(
        _safe_service_call(
            lambda service: {
                "ok": True,
                "healthy": True,
                "status": "ok",
                "component": CREATIVE_LIBRARY_DRAFT_ROUTES_COMPONENT,
                "version": CREATIVE_LIBRARY_DRAFT_ROUTES_VERSION,
                "action": "list_assets",
                "payload": {
                    "draft_ref": draft_ref,
                    "items": service.repository.list_assets(
                        draft_ref,
                        query={
                            "active_only": _bool_arg("active_only", default=False),
                            "include_deleted": _bool_arg("include_deleted", default=False),
                            "draft_variant_id": _int_arg("draft_variant_id", default=None),
                            "draft_variant_uid": _str_arg("draft_variant_uid"),
                        },
                        as_dict=True,
                    ),
                },
            }
        )
    )


@creative_library_drafts_bp.post("/<string:draft_ref>/assets")
def creative_library_drafts_assets_add(draft_ref: str) -> Response:
    """Add draft asset."""
    payload = _merged_request_payload()

    return _json_response(
        _safe_service_call(
            lambda service: service.add_asset(
                draft_ref,
                payload,
                draft_variant_ref=payload.get("draft_variant_ref") or payload.get("draft_variant_uid") or payload.get("draft_variant_id"),
                user_id=payload.get("user_id"),
                commit=True,
            )
        )
    )


@creative_library_drafts_bp.patch("/assets/<string:asset_ref>")
def creative_library_drafts_assets_patch(asset_ref: str) -> Response:
    """Update draft asset."""
    payload = _merged_request_payload()

    return _json_response(
        _safe_service_call(
            lambda service: service.update_asset(
                asset_ref,
                payload,
                user_id=payload.get("user_id"),
                commit=True,
            )
        )
    )


@creative_library_drafts_bp.delete("/assets/<string:asset_ref>")
def creative_library_drafts_assets_delete(asset_ref: str) -> Response:
    """Soft-delete draft asset."""
    payload = _merged_request_payload()

    return _json_response(
        _safe_service_call(
            lambda service: service.delete_asset(
                asset_ref,
                user_id=payload.get("user_id"),
                commit=True,
            )
        )
    )


# ---------------------------------------------------------------------------
# Documents
# ---------------------------------------------------------------------------

@creative_library_drafts_bp.get("/<string:draft_ref>/documents")
def creative_library_drafts_documents_list(draft_ref: str) -> Response:
    """List draft documents."""
    return _json_response(
        _safe_service_call(
            lambda service: {
                "ok": True,
                "healthy": True,
                "status": "ok",
                "component": CREATIVE_LIBRARY_DRAFT_ROUTES_COMPONENT,
                "version": CREATIVE_LIBRARY_DRAFT_ROUTES_VERSION,
                "action": "list_documents",
                "payload": {
                    "draft_ref": draft_ref,
                    "items": service.repository.list_documents(
                        draft_ref,
                        query={
                            "active_only": _bool_arg("active_only", default=False),
                            "include_deleted": _bool_arg("include_deleted", default=False),
                            "draft_variant_id": _int_arg("draft_variant_id", default=None),
                            "draft_variant_uid": _str_arg("draft_variant_uid"),
                        },
                        as_dict=True,
                    ),
                },
            }
        )
    )


@creative_library_drafts_bp.post("/<string:draft_ref>/documents")
def creative_library_drafts_documents_add(draft_ref: str) -> Response:
    """Add draft document metadata."""
    payload = _merged_request_payload()

    return _json_response(
        _safe_service_call(
            lambda service: service.add_document(
                draft_ref,
                payload,
                draft_variant_ref=payload.get("draft_variant_ref") or payload.get("draft_variant_uid") or payload.get("draft_variant_id"),
                user_id=payload.get("user_id"),
                commit=True,
            )
        )
    )


@creative_library_drafts_bp.post("/<string:draft_ref>/documents/upload")
def creative_library_drafts_documents_upload(draft_ref: str) -> Response:
    """
    Upload file and attach it as draft document.

    Multipart:
        file=<upload>
        document_type=datasheet|model_3d|technical_drawing
        field_key=documents.datasheets
    """
    payload = _merged_request_payload()
    files = _uploaded_files()

    if not files:
        return _json_response(
            _invalid_request_response(
                "file_missing",
                "Upload requires a multipart file field named file, upload, asset, document or model.",
            )
        )

    document_type = payload.get("document_type") or payload.get("documentType")
    if not document_type:
        return _json_response(
            _invalid_request_response(
                "document_type_missing",
                "document_type is required.",
            )
        )

    file_storage = files[0]

    return _json_response(
        _safe_service_call(
            lambda service: service.attach_uploaded_file_as_document(
                draft_ref,
                content=file_storage,
                document_type=document_type,
                field_key=payload.get("field_key") or payload.get("fieldKey"),
                draft_variant_ref=payload.get("draft_variant_ref") or payload.get("draft_variant_uid") or payload.get("draft_variant_id"),
                user_id=payload.get("user_id"),
                original_filename=payload.get("original_filename") or payload.get("filename") or getattr(file_storage, "filename", None),
                mime_type=payload.get("mime_type") or payload.get("content_type") or getattr(file_storage, "mimetype", None),
                commit=True,
            )
        )
    )


@creative_library_drafts_bp.patch("/documents/<string:document_ref>")
def creative_library_drafts_documents_patch(document_ref: str) -> Response:
    """Update draft document."""
    payload = _merged_request_payload()

    return _json_response(
        _safe_service_call(
            lambda service: service.update_document(
                document_ref,
                payload,
                user_id=payload.get("user_id"),
                commit=True,
            )
        )
    )


@creative_library_drafts_bp.delete("/documents/<string:document_ref>")
def creative_library_drafts_documents_delete(document_ref: str) -> Response:
    """Soft-delete draft document."""
    payload = _merged_request_payload()

    return _json_response(
        _safe_service_call(
            lambda service: service.delete_document(
                document_ref,
                user_id=payload.get("user_id"),
                commit=True,
            )
        )
    )


# ---------------------------------------------------------------------------
# Audit
# ---------------------------------------------------------------------------

@creative_library_drafts_bp.get("/<string:draft_ref>/audit")
def creative_library_drafts_audit_for_draft(draft_ref: str) -> Response:
    """List audit events for one draft."""
    return _json_response(
        _safe_service_call(
            lambda service: service.list_audit_events(
                draft_ref=draft_ref,
                user_id=_int_arg("user_id", default=None),
                event_type=_str_arg("event_type"),
                limit=_int_arg("limit", default=100) or 100,
                offset=_int_arg("offset", default=0) or 0,
            )
        )
    )


@creative_library_drafts_bp.get("/audit")
def creative_library_drafts_audit_list() -> Response:
    """List draft audit events."""
    return _json_response(
        _safe_service_call(
            lambda service: service.list_audit_events(
                draft_ref=_str_arg("draft_ref") or _str_arg("draft_uid") or _str_arg("draft_id"),
                user_id=_int_arg("user_id", default=1),
                event_type=_str_arg("event_type"),
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
        _LOGGER.warning("Could not parse creative library draft route JSON payload: %s", exc)
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


def _form_payload() -> Dict[str, Any]:
    """Returns multipart/form fields as dict."""
    try:
        return dict(request.form.items())
    except Exception:
        return {}


def _merged_request_payload() -> Dict[str, Any]:
    """Merge query args, form fields and JSON body. Later sources win."""
    result: Dict[str, Any] = {}
    result.update(_query_payload())
    result.update(_form_payload())

    if request.method in {"POST", "PATCH", "PUT", "DELETE"}:
        result.update(_json_payload())

    return result


def _uploaded_files() -> list[Any]:
    """Returns uploaded files from common field names."""
    result: list[Any] = []

    try:
        for field_name in ("file", "files", "upload", "asset", "document", "model"):
            values = request.files.getlist(field_name)
            for value in values:
                if value is not None and getattr(value, "filename", None):
                    result.append(value)
    except Exception:
        return []

    seen: set[int] = set()
    deduped: list[Any] = []

    for item in result:
        identity = id(item)
        if identity in seen:
            continue
        seen.add(identity)
        deduped.append(item)

    return deduped


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

    if text in {"1", "true", "yes", "y", "ja", "on", "enabled", "active", "visible", "valid", "publish"}:
        return True

    if text in {"0", "false", "no", "n", "nein", "off", "disabled", "inactive", "hidden", "invalid"}:
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
        service = _create_draft_service()
    except Exception as exc:
        return _unavailable_response(
            "creative_library_draft_service_unavailable",
            f"CreativeLibraryDraftService is unavailable: {exc}",
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
        payload.setdefault("component", CREATIVE_LIBRARY_DRAFT_ROUTES_COMPONENT)
        payload.setdefault("route_version", CREATIVE_LIBRARY_DRAFT_ROUTES_VERSION)

        return payload

    except Exception as exc:
        _LOGGER.exception("Creative Library draft route service call failed.")
        return _exception_response(exc, code="creative_library_draft_service_error")


def _exception_response(exc: Exception, *, code: str = "route_error") -> Dict[str, Any]:
    message = str(exc)
    exc_name = type(exc).__name__
    lowered = f"{exc_name} {message}".lower()

    status = "error"
    error_code = code

    if "notfound" in lowered or "not found" in lowered:
        status = "not_found"
        error_code = f"{code}_not_found"

    if "not implemented" in lowered or "not available" in lowered:
        status = "not_implemented"
        error_code = f"{code}_not_implemented"

    if "invalid" in lowered or "required" in lowered or "validation" in lowered:
        status = "invalid_request"
        error_code = f"{code}_invalid_request"

    errors = getattr(exc, "errors", None)

    return {
        "ok": False,
        "healthy": False,
        "status": status,
        "component": CREATIVE_LIBRARY_DRAFT_ROUTES_COMPONENT,
        "version": CREATIVE_LIBRARY_DRAFT_ROUTES_VERSION,
        "error": {
            "code": error_code,
            "type": exc_name,
            "message": message,
            "errors": [str(item) for item in errors] if errors else None,
        },
    }


def _invalid_request_response(code: str, message: str) -> Dict[str, Any]:
    return {
        "ok": False,
        "healthy": False,
        "status": "invalid_request",
        "component": CREATIVE_LIBRARY_DRAFT_ROUTES_COMPONENT,
        "version": CREATIVE_LIBRARY_DRAFT_ROUTES_VERSION,
        "error": {
            "code": code,
            "message": message,
        },
    }


def _unavailable_response(code: str, message: str) -> Dict[str, Any]:
    return {
        "ok": False,
        "healthy": False,
        "status": "unavailable",
        "component": CREATIVE_LIBRARY_DRAFT_ROUTES_COMPONENT,
        "version": CREATIVE_LIBRARY_DRAFT_ROUTES_VERSION,
        "error": {
            "code": code,
            "message": message,
        },
    }


# ---------------------------------------------------------------------------
# Health / route map
# ---------------------------------------------------------------------------

def _safe_draft_service_health() -> Dict[str, Any]:
    try:
        service = _create_draft_service()
        if hasattr(service, "get_health") and callable(service.get_health):
            return dict(service.get_health())

        return {
            "ok": True,
            "healthy": True,
            "status": "ok",
        }
    except Exception as exc:
        return _unavailable_response(
            "creative_library_draft_service_unavailable",
            str(exc),
        )


def get_creative_library_draft_route_list() -> list[str]:
    """Returns public route list."""
    return [
        "GET /api/v1/vplib/library/drafts",
        "POST /api/v1/vplib/library/drafts",
        "GET /api/v1/vplib/library/drafts/health",
        "GET /api/v1/vplib/library/drafts/routes",
        "GET /api/v1/vplib/library/drafts/selftest",
        "POST /api/v1/vplib/library/drafts/cache/clear",
        "GET /api/v1/vplib/library/drafts/<draft_ref>",
        "PATCH /api/v1/vplib/library/drafts/<draft_ref>",
        "DELETE /api/v1/vplib/library/drafts/<draft_ref>",
        "POST /api/v1/vplib/library/drafts/<draft_ref>/discard",
        "POST /api/v1/vplib/library/drafts/<draft_ref>/validate",
        "GET /api/v1/vplib/library/drafts/<draft_ref>/validation-issues",
        "POST /api/v1/vplib/library/drafts/<draft_ref>/validation-issues",
        "POST /api/v1/vplib/library/drafts/<draft_ref>/publish/prepare",
        "POST /api/v1/vplib/library/drafts/<draft_ref>/publish",
        "GET /api/v1/vplib/library/drafts/<draft_ref>/variants",
        "POST /api/v1/vplib/library/drafts/<draft_ref>/variants",
        "PATCH /api/v1/vplib/library/drafts/variants/<variant_ref>",
        "DELETE /api/v1/vplib/library/drafts/variants/<variant_ref>",
        "GET /api/v1/vplib/library/drafts/<draft_ref>/assets",
        "POST /api/v1/vplib/library/drafts/<draft_ref>/assets",
        "PATCH /api/v1/vplib/library/drafts/assets/<asset_ref>",
        "DELETE /api/v1/vplib/library/drafts/assets/<asset_ref>",
        "GET /api/v1/vplib/library/drafts/<draft_ref>/documents",
        "POST /api/v1/vplib/library/drafts/<draft_ref>/documents",
        "POST /api/v1/vplib/library/drafts/<draft_ref>/documents/upload",
        "PATCH /api/v1/vplib/library/drafts/documents/<document_ref>",
        "DELETE /api/v1/vplib/library/drafts/documents/<document_ref>",
        "GET /api/v1/vplib/library/drafts/<draft_ref>/audit",
        "GET /api/v1/vplib/library/drafts/audit",
    ]


def get_creative_library_draft_route_map_response() -> Dict[str, Any]:
    """Returns route map payload."""
    return {
        "ok": True,
        "healthy": True,
        "status": "ok",
        "component": CREATIVE_LIBRARY_DRAFT_ROUTES_COMPONENT,
        "version": CREATIVE_LIBRARY_DRAFT_ROUTES_VERSION,
        "route_prefix": CREATIVE_LIBRARY_DRAFT_ROUTE_PREFIX,
        "blueprint": creative_library_drafts_bp.name,
        "routes": get_creative_library_draft_route_list(),
        "route_count": len(get_creative_library_draft_route_list()),
        "groups": {
            "diagnostics": [
                "GET /health",
                "GET /routes",
                "GET /selftest",
                "POST /cache/clear",
            ],
            "drafts": [
                "GET /",
                "POST /",
                "GET /<draft_ref>",
                "PATCH /<draft_ref>",
                "DELETE /<draft_ref>",
                "POST /<draft_ref>/discard",
            ],
            "validation": [
                "POST /<draft_ref>/validate",
                "GET /<draft_ref>/validation-issues",
                "POST /<draft_ref>/validation-issues",
            ],
            "publish": [
                "POST /<draft_ref>/publish/prepare",
                "POST /<draft_ref>/publish",
            ],
            "variants": [
                "GET /<draft_ref>/variants",
                "POST /<draft_ref>/variants",
                "PATCH /variants/<variant_ref>",
                "DELETE /variants/<variant_ref>",
            ],
            "assets": [
                "GET /<draft_ref>/assets",
                "POST /<draft_ref>/assets",
                "PATCH /assets/<asset_ref>",
                "DELETE /assets/<asset_ref>",
            ],
            "documents": [
                "GET /<draft_ref>/documents",
                "POST /<draft_ref>/documents",
                "POST /<draft_ref>/documents/upload",
                "PATCH /documents/<document_ref>",
                "DELETE /documents/<document_ref>",
            ],
            "audit": [
                "GET /<draft_ref>/audit",
                "GET /audit",
            ],
        },
    }


def get_creative_library_draft_routes_health() -> Dict[str, Any]:
    """Import-safe route health helper for routes/__init__.py."""
    service_health = _safe_draft_service_health()

    return {
        "ok": True,
        "healthy": True,
        "status": "healthy",
        "component": CREATIVE_LIBRARY_DRAFT_ROUTES_COMPONENT,
        "version": CREATIVE_LIBRARY_DRAFT_ROUTES_VERSION,
        "route_prefix": CREATIVE_LIBRARY_DRAFT_ROUTE_PREFIX,
        "blueprint": creative_library_drafts_bp.name,
        "routes": get_creative_library_draft_route_list(),
        "route_count": len(get_creative_library_draft_route_list()),
        "service": service_health,
        "supports_draft_crud": True,
        "supports_variants": True,
        "supports_assets": True,
        "supports_documents": True,
        "supports_document_upload": True,
        "supports_validation": True,
        "supports_publish_prepare": True,
        "supports_publish": True,
        "supports_audit": True,
    }


def clear_creative_library_draft_routes_caches() -> Dict[str, Any]:
    """Clears route and service caches."""
    cleared: list[str] = []

    try:
        _load_draft_service_module.cache_clear()
        cleared.append("_load_draft_service_module")
    except Exception:
        pass

    try:
        module = _load_draft_service_module()
        clear_function = getattr(module, "clear_creative_library_draft_service_caches", None)
        if callable(clear_function):
            clear_function()
            cleared.append("clear_creative_library_draft_service_caches")
    except Exception:
        pass

    return {
        "ok": True,
        "healthy": True,
        "status": "ok",
        "component": CREATIVE_LIBRARY_DRAFT_ROUTES_COMPONENT,
        "version": CREATIVE_LIBRARY_DRAFT_ROUTES_VERSION,
        "cleared": cleared,
    }


__all__ = [
    "CREATIVE_LIBRARY_DRAFT_ROUTES_COMPONENT",
    "CREATIVE_LIBRARY_DRAFT_ROUTES_VERSION",
    "CREATIVE_LIBRARY_DRAFT_ROUTE_PREFIX",
    "creative_library_drafts_bp",
    "creative_library_draft_bp",
    "creative_library_draft_routes_bp",
    "creative_drafts_bp",
    "drafts_bp",
    "bp",
    "blueprint",
    "get_creative_library_draft_routes_health",
    "get_creative_library_draft_route_map_response",
    "get_creative_library_draft_route_list",
    "clear_creative_library_draft_routes_caches",
]