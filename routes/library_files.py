# services/vectoplan-library/routes/library_files.py
"""
Flask routes for VECTOPLAN Library Files.

Route prefix:
- /api/v1/vplib/files

This route layer is intentionally thin:

- parse Flask request args/json/form/files
- call src.library.services.library_file_service.LibraryFileService
- jsonify returned dictionaries
- map exceptions to API-safe JSON responses

Business logic lives in:
- src/library/services/library_file_service.py
- src/library/repositories/library_file_repository.py

Supported workflows:

- upload file
- upload multiple files
- read file metadata
- list files
- replace file version
- link existing file to context
- list links
- delete file
- delete link
- mark link primary

Storage logic remains in the service.
DB logic remains in the repository.
"""

from __future__ import annotations

import importlib
import logging
from functools import lru_cache
from types import ModuleType
from typing import Any, Callable, Dict, Mapping

from flask import Blueprint, jsonify, request


LIBRARY_FILES_ROUTES_COMPONENT = "routes.library_files"
LIBRARY_FILES_ROUTES_VERSION = "1.0.0"
LIBRARY_FILES_ROUTE_PREFIX = "/api/v1/vplib/files"

_LOGGER = logging.getLogger(__name__)


file_bp = Blueprint(
    "library_files",
    __name__,
    url_prefix=LIBRARY_FILES_ROUTE_PREFIX,
)

library_files_bp = file_bp
library_file_bp = file_bp
files_bp = file_bp


# ---------------------------------------------------------------------------
# Lazy service imports
# ---------------------------------------------------------------------------

@lru_cache(maxsize=1)
def _load_file_service_module() -> ModuleType:
    """Loads library_file_service defensively."""
    errors: list[str] = []

    for module_name in (
        "src.library.services.library_file_service",
        "library.services.library_file_service",
        "vectoplan_library.src.library.services.library_file_service",
        "vectoplan_library.library.services.library_file_service",
    ):
        try:
            return importlib.import_module(module_name)
        except Exception as exc:
            errors.append(f"{module_name}: {type(exc).__name__}: {exc}")

    raise ImportError(
        "Could not import library_file_service. "
        + " | ".join(errors)
    )


def _create_file_service() -> Any:
    """Creates LibraryFileService per request."""
    module = _load_file_service_module()

    factory = getattr(module, "create_library_file_service", None)
    if callable(factory):
        return factory()

    service_class = getattr(module, "LibraryFileService", None)
    if service_class is None:
        raise RuntimeError("LibraryFileService is not available.")

    return service_class()


# ---------------------------------------------------------------------------
# Diagnostics
# ---------------------------------------------------------------------------

@file_bp.get("/")
def library_files_index():
    """
    List files.

    GET /api/v1/vplib/files?user_id=1&document_type=datasheet
    """
    return _json_response(
        _safe_service_call(
            lambda service: service.list_files(
                query=_query_payload(),
            )
        )
    )


@file_bp.get("/routes")
def library_files_routes_map():
    return _json_response(get_library_files_route_map_response())


@file_bp.get("/health")
def library_files_health():
    return _json_response(get_library_files_routes_health())


@file_bp.get("/selftest")
def library_files_selftest():
    return _json_response(
        {
            "ok": True,
            "healthy": True,
            "status": "ok",
            "component": LIBRARY_FILES_ROUTES_COMPONENT,
            "version": LIBRARY_FILES_ROUTES_VERSION,
            "route_prefix": LIBRARY_FILES_ROUTE_PREFIX,
            "service": _safe_file_service_health(),
        }
    )


@file_bp.post("/cache/clear")
def library_files_cache_clear():
    return _json_response(clear_library_files_routes_caches())


# ---------------------------------------------------------------------------
# Upload / file CRUD
# ---------------------------------------------------------------------------

@file_bp.post("")
@file_bp.post("/")
def library_files_upload():
    """
    Upload one or more files.

    Multipart form:
        file=<upload>
        user_id=1
        document_type=datasheet
        context_type=creative_variant
        context_db_id=123
        field_key=documents.datasheets

    JSON-only upload is intentionally not supported here for binary content.
    """
    files = _uploaded_files()
    payload = _merged_request_payload()

    if not files:
        return _json_response(
            _invalid_request_response(
                "file_missing",
                "Upload requires at least one multipart file field named file, upload, asset or files.",
            )
        )

    if len(files) == 1:
        return _json_response(
            _safe_service_call(
                lambda service: service.upload(
                    content=files[0],
                    original_filename=payload.get("original_filename") or payload.get("filename") or getattr(files[0], "filename", None),
                    mime_type=payload.get("mime_type") or payload.get("content_type") or getattr(files[0], "mimetype", None),
                    document_type=payload.get("document_type") or payload.get("documentType"),
                    asset_kind=payload.get("asset_kind") or payload.get("assetKind"),
                    field_key=payload.get("field_key") or payload.get("fieldKey"),
                    role=payload.get("role"),
                    is_primary=payload.get("is_primary") or payload.get("primary"),
                    context_type=payload.get("context_type") or payload.get("contextType"),
                    context_db_id=payload.get("context_db_id") or payload.get("contextDbId"),
                    context_id=payload.get("context_id") or payload.get("contextId"),
                    context_uid=payload.get("context_uid") or payload.get("contextUid"),
                    vplib_uid=payload.get("vplib_uid") or payload.get("vplibUid"),
                    family_id=payload.get("family_id") or payload.get("familyId"),
                    package_id=payload.get("package_id") or payload.get("packageId"),
                    variant_id=payload.get("variant_id") or payload.get("variantId"),
                    revision_hash=payload.get("revision_hash") or payload.get("revisionHash"),
                    user_id=payload.get("user_id"),
                    owner_user_id=payload.get("owner_user_id") or payload.get("user_id"),
                    source_scope=payload.get("source_scope"),
                    storage_backend=payload.get("storage_backend"),
                    metadata=_metadata_payload(payload),
                    payload=payload,
                    replace_single=_optional_bool(payload.get("replace_single")),
                    commit=True,
                )
            )
        )

    results: list[dict[str, Any]] = []

    for index, file_storage in enumerate(files):
        item_payload = dict(payload)
        item_payload["multi_upload_index"] = index

        result = _safe_service_call(
            lambda service, current_file=file_storage, current_payload=item_payload: service.upload(
                content=current_file,
                original_filename=current_payload.get("original_filename") or current_payload.get("filename") or getattr(current_file, "filename", None),
                mime_type=current_payload.get("mime_type") or current_payload.get("content_type") or getattr(current_file, "mimetype", None),
                document_type=current_payload.get("document_type") or current_payload.get("documentType"),
                asset_kind=current_payload.get("asset_kind") or current_payload.get("assetKind"),
                field_key=current_payload.get("field_key") or current_payload.get("fieldKey"),
                role=current_payload.get("role"),
                is_primary=current_payload.get("is_primary") or current_payload.get("primary"),
                context_type=current_payload.get("context_type") or current_payload.get("contextType"),
                context_db_id=current_payload.get("context_db_id") or current_payload.get("contextDbId"),
                context_id=current_payload.get("context_id") or current_payload.get("contextId"),
                context_uid=current_payload.get("context_uid") or current_payload.get("contextUid"),
                vplib_uid=current_payload.get("vplib_uid") or current_payload.get("vplibUid"),
                family_id=current_payload.get("family_id") or current_payload.get("familyId"),
                package_id=current_payload.get("package_id") or current_payload.get("packageId"),
                variant_id=current_payload.get("variant_id") or current_payload.get("variantId"),
                revision_hash=current_payload.get("revision_hash") or current_payload.get("revisionHash"),
                user_id=current_payload.get("user_id"),
                owner_user_id=current_payload.get("owner_user_id") or current_payload.get("user_id"),
                source_scope=current_payload.get("source_scope"),
                storage_backend=current_payload.get("storage_backend"),
                metadata=_metadata_payload(current_payload),
                payload=current_payload,
                replace_single=_optional_bool(current_payload.get("replace_single")),
                commit=True,
            )
        )
        results.append(result)

    ok = all(bool(item.get("ok")) for item in results)

    return _json_response(
        {
            "ok": ok,
            "healthy": ok,
            "status": "ok" if ok else "partial",
            "component": LIBRARY_FILES_ROUTES_COMPONENT,
            "version": LIBRARY_FILES_ROUTES_VERSION,
            "action": "multi_upload",
            "count": len(results),
            "items": results,
        }
    )


@file_bp.get("/<path:file_ref>")
def library_files_get(file_ref: str):
    """Get one file by file_uid or DB id."""
    return _json_response(
        _safe_service_call(
            lambda service: service.get_file(file_ref)
        )
    )


@file_bp.patch("/<path:file_ref>")
def library_files_patch(file_ref: str):
    """
    Patch file metadata or replace content.

    If multipart file is present, creates a new current version.
    Otherwise updates mutable file metadata through repository.
    """
    files = _uploaded_files()
    payload = _merged_request_payload()

    if files:
        file_storage = files[0]
        return _json_response(
            _safe_service_call(
                lambda service: service.replace_version(
                    file_ref,
                    content=file_storage,
                    original_filename=payload.get("original_filename") or payload.get("filename") or getattr(file_storage, "filename", None),
                    mime_type=payload.get("mime_type") or payload.get("content_type") or getattr(file_storage, "mimetype", None),
                    user_id=payload.get("user_id"),
                    metadata=_metadata_payload(payload),
                    payload=payload,
                    storage_backend=payload.get("storage_backend"),
                    commit=True,
                )
            )
        )

    return _json_response(
        _safe_service_call(
            lambda service: _repository_update_file_metadata(
                service,
                file_ref,
                payload,
            )
        )
    )


@file_bp.delete("/<path:file_ref>")
def library_files_delete(file_ref: str):
    """Soft-delete file metadata and links."""
    payload = _merged_request_payload()

    return _json_response(
        _safe_service_call(
            lambda service: service.delete_file(
                file_ref,
                user_id=payload.get("user_id"),
                commit=True,
            )
        )
    )


# ---------------------------------------------------------------------------
# Versions
# ---------------------------------------------------------------------------

@file_bp.get("/<path:file_ref>/versions")
def library_files_versions(file_ref: str):
    """List versions for one file."""
    return _json_response(
        _safe_service_call(
            lambda service: {
                "ok": True,
                "healthy": True,
                "status": "ok",
                "component": LIBRARY_FILES_ROUTES_COMPONENT,
                "version": LIBRARY_FILES_ROUTES_VERSION,
                "action": "list_versions",
                "file_ref": file_ref,
                "items": service.repository.list_versions(
                    file_ref,
                    active_only=_bool_arg("active_only", default=False),
                    include_deleted=_bool_arg("include_deleted", default=False),
                    as_dict=True,
                ),
            }
        )
    )


@file_bp.post("/<path:file_ref>/versions")
def library_files_replace_version(file_ref: str):
    """Create new current version for existing file."""
    files = _uploaded_files()
    payload = _merged_request_payload()

    if not files:
        return _json_response(
            _invalid_request_response(
                "file_missing",
                "Replacing a version requires a multipart file.",
            )
        )

    file_storage = files[0]

    return _json_response(
        _safe_service_call(
            lambda service: service.replace_version(
                file_ref,
                content=file_storage,
                original_filename=payload.get("original_filename") or payload.get("filename") or getattr(file_storage, "filename", None),
                mime_type=payload.get("mime_type") or payload.get("content_type") or getattr(file_storage, "mimetype", None),
                user_id=payload.get("user_id"),
                metadata=_metadata_payload(payload),
                payload=payload,
                storage_backend=payload.get("storage_backend"),
                commit=True,
            )
        )
    )


@file_bp.delete("/versions/<path:version_ref>")
def library_files_delete_version(version_ref: str):
    """Soft-delete one file version."""
    payload = _merged_request_payload()

    return _json_response(
        _safe_service_call(
            lambda service: {
                "ok": True,
                "healthy": True,
                "status": "ok",
                "component": LIBRARY_FILES_ROUTES_COMPONENT,
                "version": LIBRARY_FILES_ROUTES_VERSION,
                "action": "delete_version",
                "deleted": service.repository.mark_version_deleted(
                    version_ref,
                    user_id=payload.get("user_id"),
                    commit=True,
                    audit=True,
                ),
                "version_ref": version_ref,
            }
        )
    )


# ---------------------------------------------------------------------------
# Links
# ---------------------------------------------------------------------------

@file_bp.get("/links")
def library_files_links_list():
    """List file links."""
    return _json_response(
        _safe_service_call(
            lambda service: service.list_links(
                query=_query_payload(),
            )
        )
    )


@file_bp.post("/<path:file_ref>/links")
def library_files_link_existing(file_ref: str):
    """
    Link an existing file to a context.

    JSON body or form/query fields:
    - context_type
    - context_db_id/context_id/context_uid
    - field_key
    - document_type
    - role
    - is_primary
    """
    payload = _merged_request_payload()

    return _json_response(
        _safe_service_call(
            lambda service: service.link_existing_file(
                file_ref=file_ref,
                file_version_ref=payload.get("file_version_ref") or payload.get("file_version_id") or payload.get("version_uid"),
                user_id=payload.get("user_id"),
                context_type=payload.get("context_type") or payload.get("contextType"),
                context_db_id=payload.get("context_db_id") or payload.get("contextDbId"),
                context_id=payload.get("context_id") or payload.get("contextId"),
                context_uid=payload.get("context_uid") or payload.get("contextUid"),
                field_key=payload.get("field_key") or payload.get("fieldKey"),
                document_type=payload.get("document_type") or payload.get("documentType"),
                role=payload.get("role"),
                is_primary=payload.get("is_primary") or payload.get("primary"),
                vplib_uid=payload.get("vplib_uid") or payload.get("vplibUid"),
                family_id=payload.get("family_id") or payload.get("familyId"),
                package_id=payload.get("package_id") or payload.get("packageId"),
                variant_id=payload.get("variant_id") or payload.get("variantId"),
                revision_hash=payload.get("revision_hash") or payload.get("revisionHash"),
                replace_single=_optional_bool(payload.get("replace_single")),
                metadata=_metadata_payload(payload),
                payload=payload,
                commit=True,
            )
        )
    )


@file_bp.get("/links/<path:link_ref>")
def library_files_link_get(link_ref: str):
    """Get one link."""
    return _json_response(
        _safe_service_call(
            lambda service: {
                "ok": True,
                "healthy": True,
                "status": "ok",
                "component": LIBRARY_FILES_ROUTES_COMPONENT,
                "version": LIBRARY_FILES_ROUTES_VERSION,
                "action": "get_link",
                "link": service.repository.get_link_payload(
                    link_ref,
                    include_file=True,
                    include_version=True,
                ),
            }
        )
    )


@file_bp.delete("/links/<path:link_ref>")
def library_files_link_delete(link_ref: str):
    """Soft-delete one file link."""
    payload = _merged_request_payload()

    return _json_response(
        _safe_service_call(
            lambda service: service.delete_link(
                link_ref,
                user_id=payload.get("user_id"),
                commit=True,
            )
        )
    )


@file_bp.post("/links/<path:link_ref>/primary")
def library_files_link_primary(link_ref: str):
    """Mark a link as primary for its context/field/document_type."""
    payload = _merged_request_payload()

    return _json_response(
        _safe_service_call(
            lambda service: {
                "ok": True,
                "healthy": True,
                "status": "ok",
                "component": LIBRARY_FILES_ROUTES_COMPONENT,
                "version": LIBRARY_FILES_ROUTES_VERSION,
                "action": "set_link_primary",
                "link": service.repository.set_link_primary(
                    link_ref,
                    user_id=payload.get("user_id"),
                    commit=True,
                    audit=True,
                ).to_dict(include_file=True, include_version=True),
            }
        )
    )


@file_bp.get("/context")
def library_files_context_files():
    """List files for a context."""
    payload = _query_payload()

    return _json_response(
        _safe_service_call(
            lambda service: {
                "ok": True,
                "healthy": True,
                "status": "ok",
                "component": LIBRARY_FILES_ROUTES_COMPONENT,
                "version": LIBRARY_FILES_ROUTES_VERSION,
                "action": "list_context_files",
                "items": service.repository.list_context_files(
                    context_type=payload.get("context_type") or payload.get("contextType"),
                    context_id=payload.get("context_id") or payload.get("contextId"),
                    context_db_id=payload.get("context_db_id") or payload.get("contextDbId"),
                    context_uid=payload.get("context_uid") or payload.get("contextUid"),
                    user_id=payload.get("user_id"),
                    field_key=payload.get("field_key") or payload.get("fieldKey"),
                    document_type=payload.get("document_type") or payload.get("documentType"),
                    active_only=_bool_value(payload.get("active_only"), default=True),
                ),
            }
        )
    )


# ---------------------------------------------------------------------------
# Upload constraints / audit
# ---------------------------------------------------------------------------

@file_bp.route("/upload-constraints", methods=["GET", "POST"])
def library_files_upload_constraints():
    """Resolve upload constraints using Definition Catalog through file service."""
    payload = _merged_request_payload()

    return _json_response(
        _safe_service_call(
            lambda service: {
                "ok": True,
                "healthy": True,
                "status": "ok",
                "component": LIBRARY_FILES_ROUTES_COMPONENT,
                "version": LIBRARY_FILES_ROUTES_VERSION,
                "action": "upload_constraints",
                "constraints": service.resolve_upload_constraints(
                    user_id=payload.get("user_id"),
                    document_type=payload.get("document_type") or payload.get("documentType"),
                    field_key=payload.get("field_key") or payload.get("fieldKey"),
                ),
            }
        )
    )


@file_bp.get("/audit")
def library_files_audit_list():
    """List file audit events."""
    payload = _query_payload()

    return _json_response(
        _safe_service_call(
            lambda service: {
                "ok": True,
                "healthy": True,
                "status": "ok",
                "component": LIBRARY_FILES_ROUTES_COMPONENT,
                "version": LIBRARY_FILES_ROUTES_VERSION,
                "action": "list_audit",
                "items": service.repository.list_audit_events(
                    file_uid=payload.get("file_uid") or payload.get("fileUid"),
                    user_id=payload.get("user_id"),
                    event_type=payload.get("event_type") or payload.get("eventType"),
                    context_type=payload.get("context_type") or payload.get("contextType"),
                    context_id=payload.get("context_id") or payload.get("contextId"),
                    limit=_int_value(payload.get("limit"), default=100),
                    offset=_int_value(payload.get("offset"), default=0),
                    as_dict=True,
                ),
            }
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
        _LOGGER.warning("Could not parse library files route JSON payload: %s", exc)
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
    """Merge query, form and JSON body. Later sources win."""
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


def _metadata_payload(payload: Mapping[str, Any]) -> Dict[str, Any]:
    """Extract metadata payload from request fields."""
    metadata = payload.get("metadata")

    if isinstance(metadata, Mapping):
        return dict(metadata)

    result: Dict[str, Any] = {}

    for key, value in payload.items():
        if str(key).startswith("metadata."):
            result[str(key).split(".", 1)[1]] = value

    return result


def _int_value(value: Any, *, default: int | None = None) -> int | None:
    try:
        if value is None:
            return default
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

    if text in {"1", "true", "yes", "y", "ja", "on", "enabled", "active", "primary"}:
        return True

    if text in {"0", "false", "no", "n", "nein", "off", "disabled", "inactive"}:
        return False

    return default


def _optional_bool(value: Any) -> bool | None:
    if value is None:
        return None

    return _bool_value(value, default=False)


# ---------------------------------------------------------------------------
# Response helpers
# ---------------------------------------------------------------------------

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

    if status in {"unavailable", "not_implemented"}:
        return 501

    if status in {"partial"}:
        return 207

    if status in {"failed", "error"}:
        return 500

    if code.startswith("invalid_"):
        return 400

    if code.endswith("_missing"):
        return 404

    return 500


def _safe_service_call(callback: Callable[[Any], Mapping[str, Any] | Any]) -> Dict[str, Any]:
    """Creates file service and calls callback with exception mapping."""
    try:
        service = _create_file_service()
    except Exception as exc:
        return _unavailable_response(
            "file_service_unavailable",
            f"LibraryFileService is unavailable: {exc}",
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
        payload.setdefault("component", LIBRARY_FILES_ROUTES_COMPONENT)
        payload.setdefault("route_version", LIBRARY_FILES_ROUTES_VERSION)

        return payload

    except Exception as exc:
        _LOGGER.exception("Library files route service call failed.")
        return _exception_response(exc, code="file_service_error")


def _exception_response(exc: Exception, *, code: str = "route_error") -> Dict[str, Any]:
    message = str(exc)
    exc_name = type(exc).__name__
    lowered = f"{exc_name} {message}".lower()

    status = "error"
    error_code = code

    if "notfound" in lowered or "not found" in lowered:
        status = "not_found"
        error_code = f"{code}_not_found"

    if "invalid" in lowered or "required" in lowered or "validation" in lowered or "bad request" in lowered:
        status = "invalid_request"
        error_code = f"{code}_invalid_request"

    errors = getattr(exc, "errors", None)

    return {
        "ok": False,
        "healthy": False,
        "status": status,
        "component": LIBRARY_FILES_ROUTES_COMPONENT,
        "version": LIBRARY_FILES_ROUTES_VERSION,
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
        "component": LIBRARY_FILES_ROUTES_COMPONENT,
        "version": LIBRARY_FILES_ROUTES_VERSION,
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
        "component": LIBRARY_FILES_ROUTES_COMPONENT,
        "version": LIBRARY_FILES_ROUTES_VERSION,
        "error": {
            "code": code,
            "message": message,
        },
    }


# ---------------------------------------------------------------------------
# Internal service/repository bridge helpers
# ---------------------------------------------------------------------------

def _repository_update_file_metadata(service: Any, file_ref: Any, payload: Mapping[str, Any]) -> Mapping[str, Any]:
    """Updates file metadata through repository and returns API payload."""
    file = service.repository.update_file_metadata(
        file_ref,
        payload,
        user_id=payload.get("user_id"),
        commit=True,
        audit=True,
    )

    return {
        "ok": True,
        "healthy": True,
        "status": "ok",
        "component": LIBRARY_FILES_ROUTES_COMPONENT,
        "version": LIBRARY_FILES_ROUTES_VERSION,
        "action": "update_file_metadata",
        "file": service.repository.get_file_payload(
            getattr(file, "id", file_ref),
            include_current_version=True,
            include_versions=False,
            include_links=True,
        ),
    }


# ---------------------------------------------------------------------------
# Health / route map
# ---------------------------------------------------------------------------

def _safe_file_service_health() -> Dict[str, Any]:
    try:
        service = _create_file_service()
        if hasattr(service, "get_health") and callable(service.get_health):
            return dict(service.get_health())

        return {
            "ok": True,
            "healthy": True,
            "status": "ok",
        }
    except Exception as exc:
        return _unavailable_response(
            "file_service_unavailable",
            str(exc),
        )


def get_library_files_route_list() -> list[str]:
    """Returns all public routes."""
    return [
        "GET /api/v1/vplib/files",
        "POST /api/v1/vplib/files",
        "GET /api/v1/vplib/files/routes",
        "GET /api/v1/vplib/files/health",
        "GET /api/v1/vplib/files/selftest",
        "POST /api/v1/vplib/files/cache/clear",
        "GET /api/v1/vplib/files/<file_ref>",
        "PATCH /api/v1/vplib/files/<file_ref>",
        "DELETE /api/v1/vplib/files/<file_ref>",
        "GET /api/v1/vplib/files/<file_ref>/versions",
        "POST /api/v1/vplib/files/<file_ref>/versions",
        "DELETE /api/v1/vplib/files/versions/<version_ref>",
        "GET /api/v1/vplib/files/links",
        "GET /api/v1/vplib/files/links/<link_ref>",
        "POST /api/v1/vplib/files/<file_ref>/links",
        "DELETE /api/v1/vplib/files/links/<link_ref>",
        "POST /api/v1/vplib/files/links/<link_ref>/primary",
        "GET /api/v1/vplib/files/context",
        "GET|POST /api/v1/vplib/files/upload-constraints",
        "GET /api/v1/vplib/files/audit",
    ]


def get_library_files_route_map_response() -> Dict[str, Any]:
    """Returns route map response."""
    return {
        "ok": True,
        "healthy": True,
        "status": "ok",
        "component": LIBRARY_FILES_ROUTES_COMPONENT,
        "version": LIBRARY_FILES_ROUTES_VERSION,
        "route_prefix": LIBRARY_FILES_ROUTE_PREFIX,
        "blueprint": file_bp.name,
        "routes": get_library_files_route_list(),
        "groups": {
            "diagnostics": [
                "GET /routes",
                "GET /health",
                "GET /selftest",
                "POST /cache/clear",
            ],
            "files": [
                "GET /",
                "POST /",
                "GET /<file_ref>",
                "PATCH /<file_ref>",
                "DELETE /<file_ref>",
            ],
            "versions": [
                "GET /<file_ref>/versions",
                "POST /<file_ref>/versions",
                "DELETE /versions/<version_ref>",
            ],
            "links": [
                "GET /links",
                "POST /<file_ref>/links",
                "GET /links/<link_ref>",
                "DELETE /links/<link_ref>",
                "POST /links/<link_ref>/primary",
                "GET /context",
            ],
            "validation": [
                "GET|POST /upload-constraints",
            ],
            "audit": [
                "GET /audit",
            ],
        },
    }


def get_library_files_routes_health() -> Dict[str, Any]:
    """Import-safe route health helper for routes/__init__.py."""
    service_health = _safe_file_service_health()

    return {
        "ok": True,
        "healthy": True,
        "status": "healthy",
        "component": LIBRARY_FILES_ROUTES_COMPONENT,
        "version": LIBRARY_FILES_ROUTES_VERSION,
        "route_prefix": LIBRARY_FILES_ROUTE_PREFIX,
        "blueprint": file_bp.name,
        "routes": get_library_files_route_list(),
        "route_count": len(get_library_files_route_list()),
        "service": service_health,
        "supports_upload": True,
        "supports_multi_upload": True,
        "supports_file_read": True,
        "supports_file_patch": True,
        "supports_file_delete": True,
        "supports_versions": True,
        "supports_links": True,
        "supports_context_files": True,
        "supports_upload_constraints": True,
        "supports_audit": True,
    }


def clear_library_files_routes_caches() -> Dict[str, Any]:
    """Clears route and service caches."""
    cleared: list[str] = []

    try:
        _load_file_service_module.cache_clear()
        cleared.append("_load_file_service_module")
    except Exception:
        pass

    try:
        module = _load_file_service_module()
        clear_function = getattr(module, "clear_library_file_service_caches", None)
        if callable(clear_function):
            clear_function()
            cleared.append("clear_library_file_service_caches")
    except Exception:
        pass

    return {
        "ok": True,
        "healthy": True,
        "status": "ok",
        "component": LIBRARY_FILES_ROUTES_COMPONENT,
        "version": LIBRARY_FILES_ROUTES_VERSION,
        "cleared": cleared,
    }


# Common aliases for route registration code.
bp = file_bp
blueprint = file_bp


__all__ = [
    "LIBRARY_FILES_ROUTES_COMPONENT",
    "LIBRARY_FILES_ROUTES_VERSION",
    "LIBRARY_FILES_ROUTE_PREFIX",
    "file_bp",
    "library_files_bp",
    "library_file_bp",
    "files_bp",
    "bp",
    "blueprint",
    "get_library_files_routes_health",
    "get_library_files_route_map_response",
    "get_library_files_route_list",
    "clear_library_files_routes_caches",
]