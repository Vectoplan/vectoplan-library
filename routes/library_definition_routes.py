# services/vectoplan-library/routes/library_definition_routes.py
"""
Flask routes for VECTOPLAN Library Definitions.

Route prefix:
- /api/v1/vplib/definitions

This route layer is intentionally thin:

- parse Flask request args/json
- call catalog/legacy services
- jsonify returned dictionaries
- map exceptions to API-safe JSON responses

Primary new logic lives in:
- src/library/services/library_definition_catalog_service.py
- src/library/repositories/library_definition_repository.py

Legacy compatibility remains for existing endpoints that currently use:
- src.services.library_definition_route_service

This route is the public API layer for the backend-owned Definition Catalog.
It is used by Create UI, Variant Drawer, Upload Fields and Generator context
resolution.
"""

from __future__ import annotations

import importlib
import logging
from functools import lru_cache
from types import ModuleType
from typing import Any, Callable, Dict, Mapping

from flask import Blueprint, jsonify, request


LIBRARY_DEFINITION_ROUTES_COMPONENT = "routes.library_definition_routes"
LIBRARY_DEFINITION_ROUTES_VERSION = "1.0.0"
LIBRARY_DEFINITION_ROUTE_PREFIX = "/api/v1/vplib/definitions"

_LOGGER = logging.getLogger(__name__)


library_definition_bp = Blueprint(
    "library_definition_routes",
    __name__,
    url_prefix=LIBRARY_DEFINITION_ROUTE_PREFIX,
)


# ---------------------------------------------------------------------------
# Lazy service imports
# ---------------------------------------------------------------------------

@lru_cache(maxsize=1)
def _load_catalog_service_module() -> ModuleType:
    """
    Loads the new DB-backed catalog service.

    Expected primary path:
        src.library.services.library_definition_catalog_service
    """

    errors: list[str] = []

    for module_name in (
        "src.library.services.library_definition_catalog_service",
        "library.services.library_definition_catalog_service",
        "vectoplan_library.src.library.services.library_definition_catalog_service",
        "vectoplan_library.library.services.library_definition_catalog_service",
    ):
        try:
            return importlib.import_module(module_name)
        except Exception as exc:
            errors.append(f"{module_name}: {type(exc).__name__}: {exc}")

    raise ImportError(
        "Could not import library_definition_catalog_service. "
        + " | ".join(errors)
    )


@lru_cache(maxsize=1)
def _load_seed_service_module() -> ModuleType:
    """
    Loads the optional seed service.

    Seed routes are intentionally diagnostic/admin-like. If the module is not
    present yet, the route returns an unavailable response instead of breaking
    the whole blueprint import.
    """

    errors: list[str] = []

    for module_name in (
        "src.library.services.library_definition_seed_service",
        "library.services.library_definition_seed_service",
        "vectoplan_library.src.library.services.library_definition_seed_service",
        "vectoplan_library.library.services.library_definition_seed_service",
    ):
        try:
            return importlib.import_module(module_name)
        except Exception as exc:
            errors.append(f"{module_name}: {type(exc).__name__}: {exc}")

    raise ImportError(
        "Could not import library_definition_seed_service. "
        + " | ".join(errors)
    )


@lru_cache(maxsize=1)
def _load_legacy_route_service_module() -> ModuleType:
    """
    Loads the legacy route service for backward-compatible endpoints.

    Expected current path:
        src.services.library_definition_route_service
    """

    errors: list[str] = []

    for module_name in (
        "src.services.library_definition_route_service",
        "services.library_definition_route_service",
        "vectoplan_library.src.services.library_definition_route_service",
        "vectoplan_library.services.library_definition_route_service",
    ):
        try:
            return importlib.import_module(module_name)
        except Exception as exc:
            errors.append(f"{module_name}: {type(exc).__name__}: {exc}")

    raise ImportError(
        "Could not import legacy library_definition_route_service. "
        + " | ".join(errors)
    )


def _create_catalog_service() -> Any:
    """Creates a catalog service instance per request."""
    module = _load_catalog_service_module()

    factory = getattr(module, "create_library_definition_catalog_service", None)
    if callable(factory):
        return factory()

    service_class = getattr(module, "LibraryDefinitionCatalogService", None)
    if service_class is None:
        raise RuntimeError("LibraryDefinitionCatalogService is not available.")

    return service_class()


def _create_seed_service() -> Any:
    """Creates a seed service instance per request."""
    module = _load_seed_service_module()

    factory = getattr(module, "create_library_definition_seed_service", None)
    if callable(factory):
        return factory()

    service_class = getattr(module, "LibraryDefinitionSeedService", None)
    if service_class is None:
        raise RuntimeError("LibraryDefinitionSeedService is not available.")

    return service_class()


def _legacy_call(function_name: str, *args: Any, **kwargs: Any) -> Mapping[str, Any]:
    """Calls a legacy route-service function defensively."""
    try:
        module = _load_legacy_route_service_module()
    except Exception as exc:
        return _unavailable_response(
            "legacy_route_service_unavailable",
            f"Legacy definition route service is unavailable: {exc}",
        )

    function = getattr(module, function_name, None)
    if not callable(function):
        return _unavailable_response(
            "legacy_function_missing",
            f"Legacy definition route function {function_name!r} is not available.",
        )

    try:
        result = function(*args, **kwargs)
        if isinstance(result, Mapping):
            return result

        return {
            "ok": False,
            "healthy": False,
            "status": "error",
            "component": LIBRARY_DEFINITION_ROUTES_COMPONENT,
            "error": {
                "code": "invalid_legacy_response",
                "message": f"Legacy function {function_name!r} did not return a mapping.",
            },
        }
    except Exception as exc:
        _LOGGER.exception("Legacy definition route service call failed: %s", function_name)
        return _exception_response(exc, code="legacy_route_service_error")


# ---------------------------------------------------------------------------
# Route map / basic diagnostics
# ---------------------------------------------------------------------------

@library_definition_bp.get("/")
def library_definition_routes_index():
    return _json_response(get_library_definition_route_map_response(request.args))


@library_definition_bp.get("/routes")
def library_definition_routes_map():
    return _json_response(get_library_definition_route_map_response(request.args))


@library_definition_bp.get("/health")
def library_definition_health():
    return _json_response(get_library_definition_routes_health())


@library_definition_bp.get("/selftest")
def library_definition_selftest():
    """Lightweight route-level smoke test."""
    return _json_response(
        {
            "ok": True,
            "healthy": True,
            "status": "ok",
            "component": LIBRARY_DEFINITION_ROUTES_COMPONENT,
            "version": LIBRARY_DEFINITION_ROUTES_VERSION,
            "route_prefix": LIBRARY_DEFINITION_ROUTE_PREFIX,
            "catalog_service": _safe_catalog_health(),
            "legacy_service": _safe_legacy_health(),
            "seed_service": _safe_seed_health(),
        }
    )


# ---------------------------------------------------------------------------
# New DB-backed catalog endpoints
# ---------------------------------------------------------------------------

@library_definition_bp.get("/current")
def library_definition_current():
    """
    Current resolved definition catalog.

    GET /api/v1/vplib/definitions/current?user_id=1
    """
    return _json_response(
        _safe_service_call(
            lambda service: service.get_current_catalog(
                user_id=_int_arg("user_id", default=1),
                scope=_str_arg("scope", default="resolved"),
                include_overrides=_bool_arg("include_overrides", default=True),
                include_inactive=_bool_arg("include_inactive", default=False),
                include_deleted=_bool_arg("include_deleted", default=False),
                resolved=_bool_arg("resolved", default=True),
            )
        )
    )


@library_definition_bp.get("/summary")
def library_definition_summary():
    """
    Compact summary.

    New catalog service is preferred. Legacy service remains fallback.
    """
    response = _safe_service_call(
        lambda service: service.get_summary(
            user_id=_int_arg("user_id", default=1),
        )
    )

    if bool(response.get("ok", True)) or response.get("status") != "unavailable":
        return _json_response(response)

    return _json_response(
        _legacy_call("get_library_definition_summary_response", request.args)
    )


@library_definition_bp.get("/options")
def library_definition_options():
    """
    Compact create options.

    GET /api/v1/vplib/definitions/options?user_id=1
    """
    response = _safe_service_call(
        lambda service: service.get_create_options(
            user_id=_int_arg("user_id", default=1),
        )
    )

    if bool(response.get("ok", True)) or response.get("status") != "unavailable":
        return _json_response(response)

    return _json_response(
        _legacy_call("get_library_definition_options_response", request.args)
    )


@library_definition_bp.get("/payload")
def library_definition_payload():
    """
    Backward-compatible payload endpoint.

    If dataset is provided, returns one dataset. Otherwise returns current catalog.
    """
    dataset_key = _str_arg("dataset") or _str_arg("dataset_key")

    if dataset_key:
        return _json_response(
            _safe_service_call(
                lambda service: service.get_dataset(
                    dataset_key,
                    user_id=_int_arg("user_id", default=1),
                    resolved=_bool_arg("resolved", default=True),
                    include_inactive=_bool_arg("include_inactive", default=False),
                )
            )
        )

    response = _safe_service_call(
        lambda service: service.get_current_catalog(
            user_id=_int_arg("user_id", default=1),
            resolved=_bool_arg("resolved", default=True),
            include_inactive=_bool_arg("include_inactive", default=False),
        )
    )

    if bool(response.get("ok", True)) or response.get("status") != "unavailable":
        return _json_response(response)

    return _json_response(
        _legacy_call("get_library_definition_payload_response", request.args)
    )


@library_definition_bp.get("/datasets")
def library_definition_datasets():
    """
    Lists all known datasets as current catalog summary.

    Full dataset contents are available through:
    GET /api/v1/vplib/definitions/datasets/<dataset_key>
    """
    return _json_response(
        _safe_service_call(
            lambda service: service.get_current_catalog(
                user_id=_int_arg("user_id", default=1),
                resolved=_bool_arg("resolved", default=True),
                include_inactive=_bool_arg("include_inactive", default=False),
            )
        )
    )


@library_definition_bp.get("/datasets/<path:dataset_key>")
def library_definition_dataset(dataset_key: str):
    """
    One dataset.

    Example:
    GET /api/v1/vplib/definitions/datasets/variables?user_id=1
    """
    return _json_response(
        _safe_service_call(
            lambda service: service.get_dataset(
                dataset_key,
                user_id=_int_arg("user_id", default=1),
                resolved=_bool_arg("resolved", default=True),
                include_inactive=_bool_arg("include_inactive", default=False),
            )
        )
    )


@library_definition_bp.get("/variables")
def library_definition_variables():
    return _json_response(
        _safe_service_call(
            lambda service: service.get_variables(
                user_id=_int_arg("user_id", default=1),
                profile_id=_str_arg("profile_id") or _str_arg("variant_profile_id"),
                resolved=_bool_arg("resolved", default=True),
                include_inactive=_bool_arg("include_inactive", default=False),
            )
        )
    )


@library_definition_bp.get("/units")
def library_definition_units():
    return _json_response(
        _safe_service_call(
            lambda service: service.get_units(
                user_id=_int_arg("user_id", default=1),
            )
        )
    )


@library_definition_bp.get("/materials")
def library_definition_materials():
    return _json_response(
        _safe_service_call(
            lambda service: service.get_materials(
                user_id=_int_arg("user_id", default=1),
            )
        )
    )


@library_definition_bp.get("/document-types")
def library_definition_document_types():
    return _json_response(
        _safe_service_call(
            lambda service: service.get_document_types(
                user_id=_int_arg("user_id", default=1),
            )
        )
    )


@library_definition_bp.get("/object-kinds")
def library_definition_object_kinds():
    return _json_response(
        _safe_service_call(
            lambda service: service.get_object_kinds(
                user_id=_int_arg("user_id", default=1),
            )
        )
    )


@library_definition_bp.get("/family-profiles")
def library_definition_family_profiles():
    return _json_response(
        _safe_service_call(
            lambda service: service.get_family_profiles(
                user_id=_int_arg("user_id", default=1),
            )
        )
    )


@library_definition_bp.get("/family-profiles/<path:profile_id>")
def library_definition_family_profile(profile_id: str):
    return _json_response(
        _safe_service_call(
            lambda service: {
                "ok": True,
                "status": "ok",
                "component": LIBRARY_DEFINITION_ROUTES_COMPONENT,
                "item": service.get_family_profile(
                    profile_id,
                    user_id=_int_arg("user_id", default=1),
                    required=True,
                ),
            }
        )
    )


@library_definition_bp.get("/variant-profiles")
def library_definition_variant_profiles():
    return _json_response(
        _safe_service_call(
            lambda service: service.get_variant_profiles(
                user_id=_int_arg("user_id", default=1),
            )
        )
    )


@library_definition_bp.get("/variant-profiles/<path:profile_id>/resolved")
def library_definition_variant_profile_resolved(profile_id: str):
    """
    Resolved variant profile.

    GET /api/v1/vplib/definitions/variant-profiles/<id>/resolved?user_id=1
    """
    return _json_response(
        _safe_service_call(
            lambda service: {
                "ok": True,
                "status": "ok",
                "component": LIBRARY_DEFINITION_ROUTES_COMPONENT,
                "profile_id": profile_id,
                "item": service.get_variant_profile(
                    profile_id,
                    user_id=_int_arg("user_id", default=1),
                    resolved=True,
                    required=True,
                ),
            }
        )
    )


@library_definition_bp.get("/variant-profiles/<path:profile_id>")
def library_definition_variant_profile(profile_id: str):
    """
    Variant profile.

    Query:
    - resolved=1 to include variables, sections and upload constraints.
    """
    resolved = _bool_arg("resolved", default=False)

    response = _safe_service_call(
        lambda service: {
            "ok": True,
            "status": "ok",
            "component": LIBRARY_DEFINITION_ROUTES_COMPONENT,
            "profile_id": profile_id,
            "resolved": resolved,
            "item": service.get_variant_profile(
                profile_id,
                user_id=_int_arg("user_id", default=1),
                resolved=resolved,
                required=True,
            ),
        }
    )

    if bool(response.get("ok", True)) or response.get("status") != "unavailable":
        return _json_response(response)

    return _json_response(
        _legacy_call(
            "get_library_definition_variant_profile_response",
            profile_id,
            request.args,
        )
    )


@library_definition_bp.get("/profile-bindings")
def library_definition_profile_bindings():
    return _json_response(
        _safe_service_call(
            lambda service: service.get_profile_bindings(
                user_id=_int_arg("user_id", default=1),
            )
        )
    )


@library_definition_bp.route("/create-context", methods=["GET", "POST"])
def library_definition_create_context():
    """
    Resolve create context.

    GET /api/v1/vplib/definitions/create-context
      ?user_id=1
      &domain=hochbau
      &category=waende
      &subcategory=ziegel
      &object_kind=cell_block

    POST accepts the same keys as JSON.
    """
    payload = _merged_request_payload()

    return _json_response(
        _safe_service_call(
            lambda service: service.get_create_context(
                user_id=payload.get("user_id"),
                domain=payload.get("domain"),
                category=payload.get("category"),
                subcategory=payload.get("subcategory"),
                object_kind=payload.get("object_kind") or payload.get("objectKind"),
                family_profile_id=payload.get("family_profile_id") or payload.get("familyProfileId"),
                variant_profile_id=payload.get("variant_profile_id") or payload.get("variantProfileId"),
                include_catalog=_bool_value(payload.get("include_catalog"), default=False),
            )
        )
    )


@library_definition_bp.route("/upload-constraints", methods=["GET", "POST"])
def library_definition_upload_constraints():
    """
    Resolve upload constraints by document_type or field_key.

    Examples:
    GET /api/v1/vplib/definitions/upload-constraints?field_key=documents.datasheets
    GET /api/v1/vplib/definitions/upload-constraints?document_type=model_3d
    """
    payload = _merged_request_payload()

    return _json_response(
        _safe_service_call(
            lambda service: service.get_upload_constraints(
                user_id=payload.get("user_id"),
                document_type=payload.get("document_type") or payload.get("documentType"),
                field_key=payload.get("field_key") or payload.get("fieldKey"),
                variable_key=payload.get("variable_key") or payload.get("variableKey"),
            )
        )
    )


# ---------------------------------------------------------------------------
# Seed utility endpoints
# ---------------------------------------------------------------------------

@library_definition_bp.route("/seed/preview", methods=["GET", "POST"])
def library_definition_seed_preview():
    """
    Preview seed import without DB writes.

    This is useful during development before running actual seed.
    """
    payload = _merged_request_payload()

    return _json_response(
        _safe_seed_call(
            lambda service: service.preview_seed_all(
                data_dir=payload.get("data_dir"),
                dataset_keys=payload.get("dataset_keys") or payload.get("datasets"),
                definitions_version=payload.get("definitions_version"),
            )
        )
    )


@library_definition_bp.route("/seed/validate", methods=["GET", "POST"])
def library_definition_seed_validate():
    """Validate definition JSON files without DB writes."""
    payload = _merged_request_payload()

    return _json_response(
        _safe_seed_call(
            lambda service: service.validate_dataset_files(
                data_dir=payload.get("data_dir"),
                dataset_keys=payload.get("dataset_keys") or payload.get("datasets"),
                definitions_version=payload.get("definitions_version"),
            )
        )
    )


@library_definition_bp.post("/seed/run")
def library_definition_seed_run():
    """
    Run seed import.

    Intended for development/admin usage. In production, protect this route
    before exposing it publicly.
    """
    payload = _json_payload()

    return _json_response(
        _safe_seed_call(
            lambda service: service.seed_all(
                options=payload,
            )
        )
    )


# ---------------------------------------------------------------------------
# Legacy compatibility endpoints
# ---------------------------------------------------------------------------

@library_definition_bp.route(
    "/resolve-family-profile",
    methods=["GET", "POST"],
)
def library_definition_resolve_family_profile():
    payload = _json_payload() if request.method == "POST" else None
    return _json_response(
        _legacy_call(
            "resolve_library_definition_family_profile_response",
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
        _legacy_call(
            "resolve_library_definition_variant_profile_response",
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
        _legacy_call(
            "build_empty_library_definition_variant_values_response",
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
        _legacy_call(
            "build_empty_library_definition_variant_values_response",
            profile_id,
            request.args,
            payload,
        )
    )


@library_definition_bp.post("/validate-variant")
def library_definition_validate_variant():
    return _json_response(
        _legacy_call(
            "validate_library_definition_variant_response",
            _json_payload(),
            request.args,
        )
    )


@library_definition_bp.post("/cache/clear")
def library_definition_cache_clear():
    clear_library_definition_routes_caches()

    legacy_response = _legacy_call(
        "clear_library_definition_cache_response",
        request.args,
    )

    return _json_response(
        {
            "ok": True,
            "healthy": True,
            "status": "ok",
            "component": LIBRARY_DEFINITION_ROUTES_COMPONENT,
            "cleared": [
                "_load_catalog_service_module",
                "_load_seed_service_module",
                "_load_legacy_route_service_module",
            ],
            "legacy": dict(legacy_response) if isinstance(legacy_response, Mapping) else None,
        }
    )


# ---------------------------------------------------------------------------
# Request helpers
# ---------------------------------------------------------------------------

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


def _merged_request_payload() -> Dict[str, Any]:
    """
    Merge query args and JSON body.

    JSON body wins over query args.
    """
    result: Dict[str, Any] = {}

    try:
        result.update(dict(request.args.items()))
    except Exception:
        pass

    if request.method in {"POST", "PATCH", "PUT", "DELETE"}:
        result.update(_json_payload())

    return result


def _str_arg(name: str, *, default: str | None = None) -> str | None:
    try:
        value = request.args.get(name)
    except Exception:
        value = None

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

    if text in {"1", "true", "yes", "y", "ja", "on", "enabled", "active", "resolved"}:
        return True

    if text in {"0", "false", "no", "n", "nein", "off", "disabled", "inactive"}:
        return False

    return default


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

    if status in {"failed", "error"}:
        return 500

    if code.startswith("invalid_"):
        return 400

    if code.endswith("_missing"):
        return 404

    return 500


def _safe_service_call(callback: Callable[[Any], Mapping[str, Any] | Any]) -> Dict[str, Any]:
    """Creates catalog service and calls callback with exception mapping."""
    try:
        service = _create_catalog_service()
    except Exception as exc:
        return _unavailable_response(
            "catalog_service_unavailable",
            f"Definition catalog service is unavailable: {exc}",
        )

    try:
        result = callback(service)

        if isinstance(result, Mapping):
            payload = dict(result)
        else:
            payload = {
                "result": result,
            }

        payload.setdefault("ok", True)
        payload.setdefault("healthy", True)
        payload.setdefault("status", "ok")
        payload.setdefault("component", LIBRARY_DEFINITION_ROUTES_COMPONENT)
        payload.setdefault("route_version", LIBRARY_DEFINITION_ROUTES_VERSION)

        return payload

    except Exception as exc:
        _LOGGER.exception("Definition catalog route service call failed.")
        return _exception_response(exc, code="catalog_service_error")


def _safe_seed_call(callback: Callable[[Any], Mapping[str, Any] | Any]) -> Dict[str, Any]:
    """Creates seed service and calls callback with exception mapping."""
    try:
        service = _create_seed_service()
    except Exception as exc:
        return _unavailable_response(
            "seed_service_unavailable",
            f"Definition seed service is unavailable: {exc}",
        )

    try:
        result = callback(service)

        if isinstance(result, Mapping):
            payload = dict(result)
        else:
            payload = {
                "result": result,
            }

        payload.setdefault("ok", True)
        payload.setdefault("healthy", True)
        payload.setdefault("status", "ok")
        payload.setdefault("component", LIBRARY_DEFINITION_ROUTES_COMPONENT)
        payload.setdefault("route_version", LIBRARY_DEFINITION_ROUTES_VERSION)

        return payload

    except Exception as exc:
        _LOGGER.exception("Definition seed route service call failed.")
        return _exception_response(exc, code="seed_service_error")


def _exception_response(exc: Exception, *, code: str = "route_error") -> Dict[str, Any]:
    message = str(exc)
    exc_name = type(exc).__name__
    lowered = f"{exc_name} {message}".lower()

    status = "error"
    error_code = code

    if "notfound" in lowered or "not found" in lowered:
        status = "not_found"
        error_code = f"{code}_not_found"

    if "invalid" in lowered or "required" in lowered or "bad request" in lowered:
        status = "invalid_request"
        error_code = f"{code}_invalid_request"

    return {
        "ok": False,
        "healthy": False,
        "status": status,
        "component": LIBRARY_DEFINITION_ROUTES_COMPONENT,
        "version": LIBRARY_DEFINITION_ROUTES_VERSION,
        "error": {
            "code": error_code,
            "type": exc_name,
            "message": message,
        },
    }


def _unavailable_response(code: str, message: str) -> Dict[str, Any]:
    return {
        "ok": False,
        "healthy": False,
        "status": "unavailable",
        "component": LIBRARY_DEFINITION_ROUTES_COMPONENT,
        "version": LIBRARY_DEFINITION_ROUTES_VERSION,
        "error": {
            "code": code,
            "message": message,
        },
    }


# ---------------------------------------------------------------------------
# Health / route map
# ---------------------------------------------------------------------------

def _safe_catalog_health() -> Dict[str, Any]:
    try:
        service = _create_catalog_service()
        if hasattr(service, "get_health") and callable(service.get_health):
            return dict(service.get_health())

        return {
            "ok": True,
            "healthy": True,
            "status": "ok",
        }
    except Exception as exc:
        return _unavailable_response(
            "catalog_service_unavailable",
            str(exc),
        )


def _safe_seed_health() -> Dict[str, Any]:
    try:
        service = _create_seed_service()
        if hasattr(service, "get_health") and callable(service.get_health):
            return dict(service.get_health())

        return {
            "ok": True,
            "healthy": True,
            "status": "ok",
        }
    except Exception as exc:
        return _unavailable_response(
            "seed_service_unavailable",
            str(exc),
        )


def _safe_legacy_health() -> Dict[str, Any]:
    try:
        module = _load_legacy_route_service_module()
        function = getattr(module, "get_library_definition_route_service_health", None)

        if callable(function):
            result = function(request.args)
            return dict(result) if isinstance(result, Mapping) else {"ok": True, "result": result}

        return {
            "ok": False,
            "healthy": False,
            "status": "unavailable",
            "error": {
                "code": "legacy_health_missing",
                "message": "Legacy health function is not available.",
            },
        }
    except Exception as exc:
        return _unavailable_response(
            "legacy_service_unavailable",
            str(exc),
        )


def get_library_definition_route_map_response(args: Mapping[str, Any] | None = None) -> Dict[str, Any]:
    """Returns route map response."""
    return {
        "ok": True,
        "healthy": True,
        "status": "ok",
        "component": LIBRARY_DEFINITION_ROUTES_COMPONENT,
        "version": LIBRARY_DEFINITION_ROUTES_VERSION,
        "route_prefix": LIBRARY_DEFINITION_ROUTE_PREFIX,
        "blueprint": library_definition_bp.name,
        "routes": get_library_definition_route_list(),
        "groups": {
            "diagnostics": [
                "GET /",
                "GET /routes",
                "GET /health",
                "GET /selftest",
                "POST /cache/clear",
            ],
            "catalog": [
                "GET /current",
                "GET /summary",
                "GET /options",
                "GET /payload",
                "GET /datasets",
                "GET /datasets/<dataset_key>",
            ],
            "datasets": [
                "GET /variables",
                "GET /units",
                "GET /materials",
                "GET /document-types",
                "GET /object-kinds",
                "GET /family-profiles",
                "GET /family-profiles/<profile_id>",
                "GET /variant-profiles",
                "GET /variant-profiles/<profile_id>",
                "GET /variant-profiles/<profile_id>/resolved",
                "GET /profile-bindings",
            ],
            "context": [
                "GET|POST /create-context",
                "GET|POST /upload-constraints",
            ],
            "seed": [
                "GET|POST /seed/preview",
                "GET|POST /seed/validate",
                "POST /seed/run",
            ],
            "legacy": [
                "GET|POST /resolve-family-profile",
                "GET|POST /resolve-variant-profile",
                "GET|POST /empty-variant-values",
                "GET|POST /empty-variant-values/<profile_id>",
                "POST /validate-variant",
            ],
        },
    }


def get_library_definition_route_list() -> list[str]:
    """Returns all public routes."""
    return [
        "GET /api/v1/vplib/definitions/",
        "GET /api/v1/vplib/definitions/routes",
        "GET /api/v1/vplib/definitions/health",
        "GET /api/v1/vplib/definitions/selftest",
        "GET /api/v1/vplib/definitions/current",
        "GET /api/v1/vplib/definitions/summary",
        "GET /api/v1/vplib/definitions/options",
        "GET /api/v1/vplib/definitions/payload",
        "GET /api/v1/vplib/definitions/datasets",
        "GET /api/v1/vplib/definitions/datasets/<dataset_key>",
        "GET /api/v1/vplib/definitions/variables",
        "GET /api/v1/vplib/definitions/units",
        "GET /api/v1/vplib/definitions/materials",
        "GET /api/v1/vplib/definitions/document-types",
        "GET /api/v1/vplib/definitions/object-kinds",
        "GET /api/v1/vplib/definitions/family-profiles",
        "GET /api/v1/vplib/definitions/family-profiles/<profile_id>",
        "GET /api/v1/vplib/definitions/variant-profiles",
        "GET /api/v1/vplib/definitions/variant-profiles/<profile_id>",
        "GET /api/v1/vplib/definitions/variant-profiles/<profile_id>/resolved",
        "GET /api/v1/vplib/definitions/profile-bindings",
        "GET|POST /api/v1/vplib/definitions/create-context",
        "GET|POST /api/v1/vplib/definitions/upload-constraints",
        "GET|POST /api/v1/vplib/definitions/seed/preview",
        "GET|POST /api/v1/vplib/definitions/seed/validate",
        "POST /api/v1/vplib/definitions/seed/run",
        "GET|POST /api/v1/vplib/definitions/resolve-family-profile",
        "GET|POST /api/v1/vplib/definitions/resolve-variant-profile",
        "GET|POST /api/v1/vplib/definitions/empty-variant-values",
        "GET|POST /api/v1/vplib/definitions/empty-variant-values/<profile_id>",
        "POST /api/v1/vplib/definitions/validate-variant",
        "POST /api/v1/vplib/definitions/cache/clear",
    ]


def get_library_definition_routes_health() -> Dict[str, Any]:
    """Import-safe route health helper for routes/__init__.py or diagnostics."""
    catalog_health = _safe_catalog_health()
    seed_health = _safe_seed_health()
    legacy_health = _safe_legacy_health()

    return {
        "ok": True,
        "healthy": True,
        "status": "healthy",
        "component": LIBRARY_DEFINITION_ROUTES_COMPONENT,
        "version": LIBRARY_DEFINITION_ROUTES_VERSION,
        "route_prefix": LIBRARY_DEFINITION_ROUTE_PREFIX,
        "blueprint": library_definition_bp.name,
        "routes": get_library_definition_route_list(),
        "route_count": len(get_library_definition_route_list()),
        "catalog_service": catalog_health,
        "seed_service": seed_health,
        "legacy_service": legacy_health,
        "supports_current_catalog": True,
        "supports_dataset_routes": True,
        "supports_create_context": True,
        "supports_upload_constraints": True,
        "supports_seed_preview": True,
        "supports_seed_run": True,
        "supports_legacy_routes": True,
    }


def clear_library_definition_routes_caches() -> Dict[str, Any]:
    """Clears route import caches and downstream service caches when available."""
    cleared: list[str] = []

    for cached_func in (
        _load_catalog_service_module,
        _load_seed_service_module,
        _load_legacy_route_service_module,
    ):
        try:
            cached_func.cache_clear()
            cleared.append(getattr(cached_func, "__name__", str(cached_func)))
        except Exception:
            continue

    for loader_name, clear_function_name in (
        ("catalog", "clear_library_definition_catalog_service_caches"),
        ("seed", "clear_library_definition_seed_service_caches"),
        ("legacy", "clear_library_definition_cache_response"),
    ):
        try:
            if loader_name == "catalog":
                module = _load_catalog_service_module()
            elif loader_name == "seed":
                module = _load_seed_service_module()
            else:
                module = _load_legacy_route_service_module()

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


# Common aliases for route registration code that expects conventional names.
bp = library_definition_bp
blueprint = library_definition_bp


__all__ = [
    "LIBRARY_DEFINITION_ROUTES_COMPONENT",
    "LIBRARY_DEFINITION_ROUTES_VERSION",
    "LIBRARY_DEFINITION_ROUTE_PREFIX",
    "library_definition_bp",
    "bp",
    "blueprint",
    "get_library_definition_routes_health",
    "get_library_definition_route_map_response",
    "get_library_definition_route_list",
    "clear_library_definition_routes_caches",
]