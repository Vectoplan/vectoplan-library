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
import time
import uuid
from functools import lru_cache
from types import ModuleType
from typing import Any, Callable, Dict, Mapping

from flask import Blueprint, has_request_context, jsonify, request


LIBRARY_DEFINITION_ROUTES_COMPONENT = "routes.library_definition_routes"
LIBRARY_DEFINITION_ROUTES_VERSION = "1.1.0"
LIBRARY_DEFINITION_ROUTE_PREFIX = "/api/v1/vplib/definitions"

STARTER_VARIANT_PROFILE_ID = "simple_cell_block.v1"
STARTER_FAMILY_PROFILE_ID = "simple_cell_block"
STARTER_OBJECT_KIND = "cell_block"
DEFAULT_USER_ID = 1
MAX_IDENTIFIER_LENGTH = 200
DEFAULT_CACHE_CONTROL = "no-store, max-age=0"

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
    """
    Lightweight route-level smoke test.

    The selftest verifies the exact starter profile used by the first creator
    milestone. It remains read-only.
    """
    profile_id = _str_arg(
        "profile_id",
        default=STARTER_VARIANT_PROFILE_ID,
    )
    payload = {
        "profile_id": profile_id,
        "family_profile_id": _str_arg(
            "family_profile_id",
            default=STARTER_FAMILY_PROFILE_ID,
        ),
        "object_kind": _str_arg(
            "object_kind",
            default=STARTER_OBJECT_KIND,
        ),
        "user_id": _int_arg(
            "user_id",
            default=DEFAULT_USER_ID,
        ),
    }

    readiness = _safe_service_call(
        lambda service: _build_creator_readiness_payload(
            service,
            payload,
        ),
        operation="creator_selftest",
    )

    return _json_response(
        {
            "ok": bool(readiness.get("ok", False)),
            "healthy": bool(readiness.get("healthy", False)),
            "ready": bool(readiness.get("ready", False)),
            "status": readiness.get("status", "unavailable"),
            "component": LIBRARY_DEFINITION_ROUTES_COMPONENT,
            "version": LIBRARY_DEFINITION_ROUTES_VERSION,
            "route_prefix": LIBRARY_DEFINITION_ROUTE_PREFIX,
            "catalog_service": _safe_catalog_health(),
            "legacy_service": _safe_legacy_health(),
            "seed_service": _safe_seed_health(),
            "creator": readiness,
        }
    )


@library_definition_bp.get("/creator-readiness")
def library_definition_creator_readiness():
    """
    Read-only readiness check for the first downloadable cell block.

    GET /api/v1/vplib/definitions/creator-readiness
    """
    payload = {
        "profile_id": _str_arg(
            "profile_id",
            default=STARTER_VARIANT_PROFILE_ID,
        ),
        "variant_profile_id": _str_arg(
            "variant_profile_id",
            default=STARTER_VARIANT_PROFILE_ID,
        ),
        "family_profile_id": _str_arg(
            "family_profile_id",
            default=STARTER_FAMILY_PROFILE_ID,
        ),
        "object_kind": _str_arg(
            "object_kind",
            default=STARTER_OBJECT_KIND,
        ),
        "domain": _str_arg("domain"),
        "category": _str_arg("category"),
        "subcategory": _str_arg("subcategory"),
        "user_id": _int_arg(
            "user_id",
            default=DEFAULT_USER_ID,
        ),
    }

    return _json_response(
        _safe_service_call(
            lambda service: _build_creator_readiness_payload(
                service,
                payload,
            ),
            operation="creator_readiness",
        )
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
    normalized_dataset_key, validation_error = _route_identifier_or_response(
        dataset_key,
        field_name="dataset_key",
    )
    if validation_error is not None:
        return _json_response(validation_error)

    return _json_response(
        _safe_service_call(
            lambda service: service.get_dataset(
                normalized_dataset_key,
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
    normalized_profile_id, validation_error = _route_identifier_or_response(
        profile_id,
        field_name="family_profile_id",
    )
    if validation_error is not None:
        return _json_response(validation_error)

    return _json_response(
        _safe_service_call(
            lambda service: {
                "ok": True,
                "status": "ok",
                "component": LIBRARY_DEFINITION_ROUTES_COMPONENT,
                "profile_id": normalized_profile_id,
                "item": service.get_family_profile(
                    normalized_profile_id,
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
    normalized_profile_id, validation_error = _route_identifier_or_response(
        profile_id,
        field_name="variant_profile_id",
    )
    if validation_error is not None:
        return _json_response(validation_error)

    return _json_response(
        _safe_service_call(
            lambda service: {
                "ok": True,
                "status": "ok",
                "component": LIBRARY_DEFINITION_ROUTES_COMPONENT,
                "profile_id": normalized_profile_id,
                "variant_profile_id": normalized_profile_id,
                "item": service.get_variant_profile(
                    normalized_profile_id,
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
    normalized_profile_id, validation_error = _route_identifier_or_response(
        profile_id,
        field_name="variant_profile_id",
    )
    if validation_error is not None:
        return _json_response(validation_error)

    resolved = _bool_arg("resolved", default=False)

    response = _safe_service_call(
        lambda service: {
            "ok": True,
            "status": "ok",
            "component": LIBRARY_DEFINITION_ROUTES_COMPONENT,
            "profile_id": normalized_profile_id,
            "variant_profile_id": normalized_profile_id,
            "resolved": resolved,
            "item": service.get_variant_profile(
                normalized_profile_id,
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
            normalized_profile_id,
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
            lambda service: _get_create_context_from_payload(
                service,
                payload,
            ),
            operation="create_context",
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
# Compatibility endpoints, now catalog-first
# ---------------------------------------------------------------------------

@library_definition_bp.route(
    "/resolve-family-profile",
    methods=["GET", "POST"],
)
def library_definition_resolve_family_profile():
    payload = _merged_request_payload()

    response = _safe_service_call(
        lambda service: _resolve_family_profile_with_catalog(
            service,
            payload,
        ),
        operation="resolve_family_profile",
    )

    if response.get("status") != "unavailable":
        return _json_response(response)

    return _json_response(
        _legacy_call(
            "resolve_library_definition_family_profile_response",
            request.args,
            _json_payload() if request.method == "POST" else None,
        )
    )


@library_definition_bp.route(
    "/resolve-variant-profile",
    methods=["GET", "POST"],
)
def library_definition_resolve_variant_profile():
    payload = _merged_request_payload()

    response = _safe_service_call(
        lambda service: _resolve_variant_profile_with_catalog(
            service,
            payload,
        ),
        operation="resolve_variant_profile",
    )

    if response.get("status") != "unavailable":
        return _json_response(response)

    return _json_response(
        _legacy_call(
            "resolve_library_definition_variant_profile_response",
            request.args,
            _json_payload() if request.method == "POST" else None,
        )
    )


@library_definition_bp.route(
    "/empty-variant-values",
    methods=["GET", "POST"],
)
def library_definition_empty_variant_values_from_query_or_payload():
    payload = _merged_request_payload()

    response = _safe_service_call(
        lambda service: _build_empty_variant_values_payload(
            service,
            None,
            payload,
        ),
        operation="empty_variant_values",
    )

    if response.get("status") != "unavailable":
        return _json_response(response)

    return _json_response(
        _legacy_call(
            "build_empty_library_definition_variant_values_response",
            None,
            request.args,
            _json_payload() if request.method == "POST" else None,
        )
    )


@library_definition_bp.route(
    "/empty-variant-values/<path:profile_id>",
    methods=["GET", "POST"],
)
def library_definition_empty_variant_values(profile_id: str):
    normalized_profile_id, validation_error = _route_identifier_or_response(
        profile_id,
        field_name="variant_profile_id",
    )
    if validation_error is not None:
        return _json_response(validation_error)

    payload = _merged_request_payload()

    response = _safe_service_call(
        lambda service: _build_empty_variant_values_payload(
            service,
            normalized_profile_id,
            payload,
        ),
        operation="empty_variant_values",
    )

    if response.get("status") != "unavailable":
        return _json_response(response)

    return _json_response(
        _legacy_call(
            "build_empty_library_definition_variant_values_response",
            normalized_profile_id,
            request.args,
            _json_payload() if request.method == "POST" else None,
        )
    )


@library_definition_bp.post("/validate-variant")
def library_definition_validate_variant():
    """
    Variant validation remains on the legacy validator until the canonical
    create validator is connected. Errors are still mapped to API-safe JSON.
    """
    return _json_response(
        _legacy_call(
            "validate_library_definition_variant_response",
            _json_payload(),
            request.args,
        )
    )


@library_definition_bp.post("/cache/clear")
def library_definition_cache_clear():
    route_clear = clear_library_definition_routes_caches()

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
            "version": LIBRARY_DEFINITION_ROUTES_VERSION,
            "cleared": route_clear.get("cleared", []),
            "downstream": route_clear.get("downstream", {}),
            "legacy": (
                dict(legacy_response)
                if isinstance(legacy_response, Mapping)
                else None
            ),
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
# Catalog orchestration helpers
# ---------------------------------------------------------------------------

def _route_identifier_or_response(
    value: Any,
    *,
    field_name: str,
) -> tuple[str | None, Dict[str, Any] | None]:
    try:
        return (
            _require_identifier(
                value,
                field_name=field_name,
            ),
            None,
        )
    except Exception as exc:
        return (
            None,
            _exception_response(
                exc,
                code=f"invalid_{field_name}",
                operation="route_identifier_validation",
            ),
        )


def _require_identifier(
    value: Any,
    *,
    field_name: str,
    allow_empty: bool = False,
) -> str:
    """
    Validate a technical definition identifier.

    Dots, dashes, underscores and colons are intentionally accepted. Path
    separators and control characters are rejected.
    """
    text = str(value or "").replace("\x00", "").strip()

    if not text:
        if allow_empty:
            return ""
        raise ValueError(f"{field_name} is required.")

    if len(text) > MAX_IDENTIFIER_LENGTH:
        raise ValueError(
            f"{field_name} exceeds the maximum length of "
            f"{MAX_IDENTIFIER_LENGTH} characters."
        )

    if "/" in text or "\\" in text:
        raise ValueError(
            f"{field_name} must not contain path separators."
        )

    if any(ord(character) < 32 for character in text):
        raise ValueError(
            f"{field_name} contains control characters."
        )

    return text


def _payload_value(
    payload: Mapping[str, Any],
    *keys: str,
    default: Any = None,
) -> Any:
    for key in keys:
        if key not in payload:
            continue
        value = payload.get(key)
        if value is None:
            continue
        if isinstance(value, str) and not value.strip():
            continue
        return value
    return default


def _normalized_context_payload(
    payload: Mapping[str, Any] | None,
) -> Dict[str, Any]:
    data = dict(payload or {})

    return {
        "user_id": _safe_int(
            _payload_value(
                data,
                "user_id",
                "userId",
                default=DEFAULT_USER_ID,
            ),
            default=DEFAULT_USER_ID,
            minimum=1,
        ),
        "domain": _optional_text(
            _payload_value(data, "domain"),
        ),
        "category": _optional_text(
            _payload_value(data, "category"),
        ),
        "subcategory": _optional_text(
            _payload_value(data, "subcategory"),
        ),
        "object_kind": _optional_text(
            _payload_value(
                data,
                "object_kind",
                "objectKind",
            ),
        ),
        "family_profile_id": _optional_identifier(
            _payload_value(
                data,
                "family_profile_id",
                "familyProfileId",
            ),
            field_name="family_profile_id",
        ),
        "variant_profile_id": _optional_identifier(
            _payload_value(
                data,
                "variant_profile_id",
                "variantProfileId",
                "profile_id",
                "profileId",
            ),
            field_name="variant_profile_id",
        ),
        "include_catalog": _bool_value(
            _payload_value(
                data,
                "include_catalog",
                "includeCatalog",
            ),
            default=False,
        ),
    }


def _optional_identifier(
    value: Any,
    *,
    field_name: str,
) -> str | None:
    if value is None:
        return None
    text = str(value).strip()
    if not text:
        return None
    return _require_identifier(
        text,
        field_name=field_name,
    )


def _optional_text(value: Any) -> str | None:
    if value is None:
        return None
    try:
        text = str(value).replace("\x00", "").strip()
    except Exception:
        return None
    return text or None


def _safe_int(
    value: Any,
    *,
    default: int,
    minimum: int | None = None,
) -> int:
    try:
        result = int(value)
    except Exception:
        result = int(default)

    if minimum is not None:
        result = max(minimum, result)

    return result


def _get_create_context_from_payload(
    service: Any,
    payload: Mapping[str, Any] | None,
) -> Dict[str, Any]:
    context = _normalized_context_payload(payload)

    result = service.get_create_context(
        user_id=context["user_id"],
        domain=context["domain"],
        category=context["category"],
        subcategory=context["subcategory"],
        object_kind=context["object_kind"],
        family_profile_id=context["family_profile_id"],
        variant_profile_id=context["variant_profile_id"],
        include_catalog=context["include_catalog"],
    )

    if not isinstance(result, Mapping):
        raise RuntimeError(
            "Definition catalog service returned an invalid create-context payload."
        )

    response = dict(result)
    response.setdefault("ok", True)
    response.setdefault("healthy", True)
    response.setdefault("ready", True)
    response.setdefault("status", "resolved")
    return response


def _resolve_family_profile_with_catalog(
    service: Any,
    payload: Mapping[str, Any] | None,
) -> Dict[str, Any]:
    context = _normalized_context_payload(payload)

    explicit_id = context.get("family_profile_id")
    if explicit_id:
        profile = service.get_family_profile(
            explicit_id,
            user_id=context["user_id"],
            required=True,
        )
        canonical_id = _definition_identifier(
            profile,
            "family_profile_id",
            "definition_key",
            "id",
            fallback=explicit_id,
        )
        source = _definition_source(profile)
        return {
            "ok": True,
            "healthy": True,
            "ready": True,
            "status": "resolved",
            "component": LIBRARY_DEFINITION_ROUTES_COMPONENT,
            "source": source,
            "strategy": "explicit",
            "family_profile_id": canonical_id,
            "familyProfileId": canonical_id,
            "profile_id": canonical_id,
            "item": profile,
            "profile": profile,
            "family_profile": profile,
        }

    create_context = _get_create_context_from_payload(
        service,
        context,
    )
    profile = create_context.get("family_profile")
    canonical_id = _definition_identifier(
        profile,
        "family_profile_id",
        "definition_key",
        "id",
        fallback=create_context.get("family_profile_id"),
    )

    if not canonical_id or not isinstance(profile, Mapping):
        raise RuntimeError(
            "Create context did not contain a resolved family profile."
        )

    resolution = create_context.get("resolution")
    family_resolution = (
        resolution.get("family")
        if isinstance(resolution, Mapping)
        else None
    )
    strategy = (
        family_resolution.get("strategy")
        if isinstance(family_resolution, Mapping)
        else None
    ) or (
        "profile_binding"
        if create_context.get("profile_binding")
        else "create_context"
    )

    return {
        "ok": True,
        "healthy": True,
        "ready": True,
        "status": "resolved",
        "component": LIBRARY_DEFINITION_ROUTES_COMPONENT,
        "source": create_context.get("source"),
        "strategy": strategy,
        "family_profile_id": canonical_id,
        "familyProfileId": canonical_id,
        "profile_id": canonical_id,
        "item": dict(profile),
        "profile": dict(profile),
        "family_profile": dict(profile),
        "create_context": create_context,
    }


def _resolve_variant_profile_with_catalog(
    service: Any,
    payload: Mapping[str, Any] | None,
) -> Dict[str, Any]:
    context = _normalized_context_payload(payload)

    explicit_id = context.get("variant_profile_id")
    if explicit_id:
        profile = service.get_variant_profile(
            explicit_id,
            user_id=context["user_id"],
            resolved=_bool_value(
                _payload_value(
                    dict(payload or {}),
                    "resolved",
                ),
                default=True,
            ),
            required=True,
        )
        canonical_id = _definition_identifier(
            profile,
            "variant_profile_id",
            "profile_id",
            "definition_key",
            "id",
            fallback=explicit_id,
        )
        source = _definition_source(profile)
        return {
            "ok": True,
            "healthy": True,
            "ready": True,
            "status": "resolved",
            "component": LIBRARY_DEFINITION_ROUTES_COMPONENT,
            "source": source,
            "strategy": "explicit",
            "variant_profile_id": canonical_id,
            "variantProfileId": canonical_id,
            "profile_id": canonical_id,
            "item": profile,
            "profile": profile,
            "variant_profile": profile,
        }

    create_context = _get_create_context_from_payload(
        service,
        context,
    )
    profile = create_context.get("variant_profile")
    canonical_id = _definition_identifier(
        profile,
        "variant_profile_id",
        "profile_id",
        "definition_key",
        "id",
        fallback=create_context.get("variant_profile_id"),
    )

    if not canonical_id or not isinstance(profile, Mapping):
        raise RuntimeError(
            "Create context did not contain a resolved variant profile."
        )

    resolution = create_context.get("resolution")
    variant_resolution = (
        resolution.get("variant")
        if isinstance(resolution, Mapping)
        else None
    )
    strategy = (
        variant_resolution.get("strategy")
        if isinstance(variant_resolution, Mapping)
        else None
    ) or (
        "profile_binding"
        if create_context.get("profile_binding")
        else "create_context"
    )

    return {
        "ok": True,
        "healthy": True,
        "ready": True,
        "status": "resolved",
        "component": LIBRARY_DEFINITION_ROUTES_COMPONENT,
        "source": create_context.get("source"),
        "strategy": strategy,
        "family_profile_id": create_context.get("family_profile_id"),
        "variant_profile_id": canonical_id,
        "variantProfileId": canonical_id,
        "profile_id": canonical_id,
        "item": dict(profile),
        "profile": dict(profile),
        "variant_profile": dict(profile),
        "create_context": create_context,
    }


def _build_empty_variant_values_payload(
    service: Any,
    path_profile_id: str | None,
    payload: Mapping[str, Any] | None,
) -> Dict[str, Any]:
    data = dict(payload or {})
    context = _normalized_context_payload(data)

    profile_id = path_profile_id or context.get(
        "variant_profile_id"
    )

    create_context: Dict[str, Any] | None = None
    if not profile_id:
        create_context = _get_create_context_from_payload(
            service,
            context,
        )
        profile_id = _require_identifier(
            create_context.get("variant_profile_id"),
            field_name="variant_profile_id",
        )

    profile = service.get_variant_profile(
        profile_id,
        user_id=context["user_id"],
        resolved=True,
        required=True,
    )
    if not isinstance(profile, Mapping):
        raise RuntimeError(
            f"Variant profile {profile_id!r} returned no payload."
        )

    canonical_id = _definition_identifier(
        profile,
        "variant_profile_id",
        "profile_id",
        "definition_key",
        "id",
        fallback=profile_id,
    )

    default_values = _mapping_copy(
        profile.get("default_values")
        or profile.get("defaultValues")
    )
    field_keys = _extract_profile_field_keys(profile)

    flat_values: Dict[str, Any] = {}
    for field_key in field_keys:
        flat_values[field_key] = default_values.get(field_key)

    for field_key, value in default_values.items():
        flat_values.setdefault(str(field_key), value)

    return {
        "ok": True,
        "healthy": True,
        "ready": True,
        "status": "ok",
        "component": LIBRARY_DEFINITION_ROUTES_COMPONENT,
        "source": _definition_source(profile),
        "profile_id": canonical_id,
        "variant_profile_id": canonical_id,
        "variantProfileId": canonical_id,
        "values": flat_values,
        "flat_values": flat_values,
        "nested_values": _expand_dotted_mapping(flat_values),
        "default_values": default_values,
        "required_fields": list(
            profile.get("required_fields")
            or profile.get("requiredFields")
            or []
        ),
        "optional_fields": list(
            profile.get("optional_fields")
            or profile.get("optionalFields")
            or []
        ),
        "field_keys": field_keys,
        "profile": dict(profile),
        "create_context": create_context,
    }


def _build_creator_readiness_payload(
    service: Any,
    payload: Mapping[str, Any] | None,
) -> Dict[str, Any]:
    data = dict(payload or {})
    context = _normalized_context_payload(
        {
            **data,
            "object_kind": _payload_value(
                data,
                "object_kind",
                "objectKind",
                default=STARTER_OBJECT_KIND,
            ),
            "family_profile_id": _payload_value(
                data,
                "family_profile_id",
                "familyProfileId",
                default=STARTER_FAMILY_PROFILE_ID,
            ),
            "variant_profile_id": _payload_value(
                data,
                "variant_profile_id",
                "variantProfileId",
                "profile_id",
                default=STARTER_VARIANT_PROFILE_ID,
            ),
        }
    )

    profile_id = _require_identifier(
        context.get("variant_profile_id"),
        field_name="variant_profile_id",
    )
    family_profile_id = _require_identifier(
        context.get("family_profile_id"),
        field_name="family_profile_id",
    )
    object_kind = _require_identifier(
        context.get("object_kind"),
        field_name="object_kind",
    )

    health = (
        dict(service.get_health())
        if hasattr(service, "get_health")
        and callable(service.get_health)
        else {"ok": True, "ready": True}
    )

    raw_profile = service.get_variant_profile(
        profile_id,
        user_id=context["user_id"],
        resolved=False,
        required=True,
    )
    resolved_profile = service.get_variant_profile(
        profile_id,
        user_id=context["user_id"],
        resolved=True,
        required=True,
    )
    family_profile = service.get_family_profile(
        family_profile_id,
        user_id=context["user_id"],
        required=True,
    )
    create_context = service.get_create_context(
        user_id=context["user_id"],
        domain=context["domain"],
        category=context["category"],
        subcategory=context["subcategory"],
        object_kind=object_kind,
        family_profile_id=family_profile_id,
        variant_profile_id=profile_id,
        include_catalog=False,
    )

    defaults = _mapping_copy(
        resolved_profile.get("default_values")
        if isinstance(resolved_profile, Mapping)
        else None
    )
    required_fields = [
        str(value)
        for value in (
            resolved_profile.get("required_fields", [])
            if isinstance(resolved_profile, Mapping)
            else []
        )
        if str(value).strip()
    ]
    missing_defaults = [
        field_key
        for field_key in required_fields
        if field_key not in defaults
        or defaults.get(field_key) in (None, "")
    ]

    dimensions_valid = all(
        _is_positive_number(defaults.get(field_key))
        for field_key in (
            "dimensions.width_mm",
            "dimensions.height_mm",
            "dimensions.depth_mm",
        )
    )

    checks = {
        "catalog_health_ready": bool(
            health.get("ready", health.get("ok", False))
        ),
        "variant_profile_raw": isinstance(raw_profile, Mapping),
        "variant_profile_resolved": isinstance(
            resolved_profile,
            Mapping,
        ),
        "family_profile": isinstance(family_profile, Mapping),
        "create_context": bool(
            isinstance(create_context, Mapping)
            and create_context.get("ready", True)
        ),
        "required_defaults_complete": not missing_defaults,
        "dimensions_positive": dimensions_valid,
    }
    ready = all(checks.values())

    return {
        "ok": ready,
        "healthy": ready and bool(
            health.get("healthy", health.get("ok", False))
        ),
        "ready": ready,
        "status": "ready" if ready else "blocked",
        "component": LIBRARY_DEFINITION_ROUTES_COMPONENT,
        "source": (
            create_context.get("source")
            if isinstance(create_context, Mapping)
            else _definition_source(resolved_profile)
        ),
        "starter": {
            "object_kind": object_kind,
            "family_profile_id": family_profile_id,
            "variant_profile_id": profile_id,
        },
        "checks": checks,
        "missing_defaults": missing_defaults,
        "health": health,
        "family_profile": family_profile,
        "variant_profile": resolved_profile,
        "create_context": create_context,
    }


def _definition_identifier(
    payload: Any,
    *field_names: str,
    fallback: Any = None,
) -> str | None:
    if isinstance(payload, Mapping):
        for field_name in field_names:
            value = payload.get(field_name)
            if value is not None and str(value).strip():
                return str(value).strip()

    if fallback is not None and str(fallback).strip():
        return str(fallback).strip()

    return None


def _definition_source(payload: Any) -> str | None:
    if not isinstance(payload, Mapping):
        return None

    for field_name in (
        "catalog_source",
        "source",
        "definition_source",
    ):
        value = payload.get(field_name)
        if value is not None and str(value).strip():
            return str(value).strip()

    return None


def _mapping_copy(value: Any) -> Dict[str, Any]:
    if isinstance(value, Mapping):
        return {
            str(key): child_value
            for key, child_value in value.items()
        }
    return {}


def _extract_profile_field_keys(
    profile: Mapping[str, Any],
) -> list[str]:
    result: list[str] = []
    seen: set[str] = set()

    direct_values = (
        profile.get("field_keys")
        or profile.get("all_field_keys")
        or []
    )
    for value in direct_values:
        key = str(value or "").strip()
        if key and key not in seen:
            seen.add(key)
            result.append(key)

    sections = profile.get("sections") or []
    if isinstance(sections, (list, tuple)):
        for section in sections:
            if not isinstance(section, Mapping):
                continue
            fields = section.get("fields") or []
            if not isinstance(fields, (list, tuple)):
                continue
            for field in fields:
                if isinstance(field, Mapping):
                    value = (
                        field.get("field_key")
                        or field.get("key")
                        or field.get("id")
                    )
                else:
                    value = field
                key = str(value or "").strip()
                if key and key not in seen:
                    seen.add(key)
                    result.append(key)

    for field_name in (
        "required_fields",
        "optional_fields",
        "summary_fields",
    ):
        values = profile.get(field_name) or []
        if not isinstance(values, (list, tuple)):
            continue
        for value in values:
            key = str(value or "").strip()
            if key and key not in seen:
                seen.add(key)
                result.append(key)

    return result


def _expand_dotted_mapping(
    values: Mapping[str, Any],
) -> Dict[str, Any]:
    result: Dict[str, Any] = {}

    for raw_key, value in values.items():
        key = str(raw_key or "").strip()
        if not key:
            continue

        parts = [
            part
            for part in key.split(".")
            if part
        ]
        if not parts:
            continue

        cursor = result
        for part in parts[:-1]:
            existing = cursor.get(part)
            if not isinstance(existing, dict):
                existing = {}
                cursor[part] = existing
            cursor = existing
        cursor[parts[-1]] = value

    return result


def _is_positive_number(value: Any) -> bool:
    try:
        return float(value) > 0
    except Exception:
        return False


# ---------------------------------------------------------------------------
# Response helpers
# ---------------------------------------------------------------------------

def _json_response(payload: Mapping[str, Any] | Any):
    """
    Build a stable JSON response with request correlation and no-store headers.
    """
    if isinstance(payload, Mapping):
        response_payload = dict(payload)
    else:
        response_payload = {
            "ok": False,
            "healthy": False,
            "status": "error",
            "component": LIBRARY_DEFINITION_ROUTES_COMPONENT,
            "error": {
                "code": "invalid_route_payload",
                "message": "Route payload is not a mapping.",
            },
        }

    response_payload.setdefault(
        "component",
        LIBRARY_DEFINITION_ROUTES_COMPONENT,
    )
    response_payload.setdefault(
        "route_version",
        LIBRARY_DEFINITION_ROUTES_VERSION,
    )
    response_payload.setdefault(
        "request_id",
        _request_id(),
    )

    status_code = _status_code_from_payload(response_payload)
    response = jsonify(response_payload)
    response.status_code = status_code
    response.headers["Cache-Control"] = DEFAULT_CACHE_CONTROL
    response.headers["Pragma"] = "no-cache"
    response.headers["X-Content-Type-Options"] = "nosniff"
    response.headers["X-Request-ID"] = response_payload["request_id"]
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

    if status in {"validation_failed", "unprocessable"}:
        return 422

    if status == "not_found" or code.endswith("not_found"):
        return 404

    if status in {"unavailable", "service_unavailable"}:
        return 503

    if status == "not_implemented":
        return 501

    if status in {"timeout", "gateway_timeout"}:
        return 504

    if status in {"conflict"}:
        return 409

    if status == "blocked":
        return 503

    if status in {"failed", "error"}:
        return 500

    if code.startswith("invalid_"):
        return 400

    if code.endswith("_missing"):
        return 404

    return 500


def _safe_service_call(
    callback: Callable[[Any], Mapping[str, Any] | Any],
    *,
    operation: str = "catalog_service_call",
) -> Dict[str, Any]:
    """
    Create a catalog service and invoke a callback with typed error mapping.
    """
    started_at = time.monotonic()

    try:
        service = _create_catalog_service()
    except Exception as exc:
        return _unavailable_response(
            "catalog_service_unavailable",
            f"Definition catalog service is unavailable: {exc}",
            operation=operation,
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
        payload.setdefault(
            "component",
            LIBRARY_DEFINITION_ROUTES_COMPONENT,
        )
        payload.setdefault(
            "route_version",
            LIBRARY_DEFINITION_ROUTES_VERSION,
        )
        payload.setdefault("operation", operation)
        payload.setdefault(
            "duration_ms",
            round(
                (time.monotonic() - started_at) * 1000,
                3,
            ),
        )
        return payload

    except Exception as exc:
        _LOGGER.exception(
            "Definition catalog route service call failed. "
            "operation=%s request_id=%s",
            operation,
            _request_id(),
        )
        return _exception_response(
            exc,
            code=f"{operation}_error",
            operation=operation,
        )


def _safe_seed_call(
    callback: Callable[[Any], Mapping[str, Any] | Any],
    *,
    operation: str = "seed_service_call",
) -> Dict[str, Any]:
    started_at = time.monotonic()

    try:
        service = _create_seed_service()
    except Exception as exc:
        return _unavailable_response(
            "seed_service_unavailable",
            f"Definition seed service is unavailable: {exc}",
            operation=operation,
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
        payload.setdefault(
            "component",
            LIBRARY_DEFINITION_ROUTES_COMPONENT,
        )
        payload.setdefault(
            "route_version",
            LIBRARY_DEFINITION_ROUTES_VERSION,
        )
        payload.setdefault("operation", operation)
        payload.setdefault(
            "duration_ms",
            round(
                (time.monotonic() - started_at) * 1000,
                3,
            ),
        )
        return payload

    except Exception as exc:
        _LOGGER.exception(
            "Definition seed route service call failed. "
            "operation=%s request_id=%s",
            operation,
            _request_id(),
        )
        return _exception_response(
            exc,
            code=f"{operation}_error",
            operation=operation,
        )


@lru_cache(maxsize=1)
def _catalog_exception_types() -> Dict[str, type[BaseException]]:
    result: Dict[str, type[BaseException]] = {}

    try:
        module = _load_catalog_service_module()
    except Exception:
        return result

    for name in (
        "LibraryDefinitionCatalogNotFoundError",
        "LibraryDefinitionCreateContextError",
        "LibraryDefinitionCatalogImportError",
        "LibraryDefinitionCatalogServiceError",
    ):
        candidate = getattr(module, name, None)
        if isinstance(candidate, type) and issubclass(
            candidate,
            BaseException,
        ):
            result[name] = candidate

    return result


def _exception_response(
    exc: Exception,
    *,
    code: str = "route_error",
    operation: str | None = None,
) -> Dict[str, Any]:
    message = str(exc)
    exc_name = type(exc).__name__
    lowered = f"{exc_name} {message}".lower()
    exception_types = _catalog_exception_types()

    not_found_type = exception_types.get(
        "LibraryDefinitionCatalogNotFoundError"
    )
    context_type = exception_types.get(
        "LibraryDefinitionCreateContextError"
    )
    import_type = exception_types.get(
        "LibraryDefinitionCatalogImportError"
    )

    status = "error"
    error_code = code

    if (
        not_found_type is not None
        and isinstance(exc, not_found_type)
    ) or "notfound" in lowered or "not found" in lowered:
        status = "not_found"
        error_code = f"{code}_not_found"
    elif (
        context_type is not None
        and isinstance(exc, context_type)
    ):
        status = "validation_failed"
        error_code = f"{code}_create_context"
    elif isinstance(exc, (ValueError, TypeError)):
        status = "invalid_request"
        error_code = f"{code}_invalid_request"
    elif (
        import_type is not None
        and isinstance(exc, import_type)
    ):
        status = "unavailable"
        error_code = f"{code}_unavailable"
    elif isinstance(exc, TimeoutError):
        status = "timeout"
        error_code = f"{code}_timeout"
    elif "invalid" in lowered or "required" in lowered:
        status = "invalid_request"
        error_code = f"{code}_invalid_request"

    return {
        "ok": False,
        "healthy": False,
        "ready": False,
        "status": status,
        "component": LIBRARY_DEFINITION_ROUTES_COMPONENT,
        "version": LIBRARY_DEFINITION_ROUTES_VERSION,
        "operation": operation,
        "request_id": _request_id(),
        "error": {
            "code": error_code,
            "type": exc_name,
            "message": message,
        },
    }


def _unavailable_response(
    code: str,
    message: str,
    *,
    operation: str | None = None,
) -> Dict[str, Any]:
    return {
        "ok": False,
        "healthy": False,
        "ready": False,
        "status": "unavailable",
        "component": LIBRARY_DEFINITION_ROUTES_COMPONENT,
        "version": LIBRARY_DEFINITION_ROUTES_VERSION,
        "operation": operation,
        "request_id": _request_id(),
        "error": {
            "code": code,
            "message": message,
        },
    }


def _request_id() -> str:
    if has_request_context():
        try:
            incoming = (
                request.headers.get("X-Request-ID")
                or request.headers.get("X-Correlation-ID")
            )
        except Exception:
            incoming = None

        if incoming:
            value = str(incoming).replace("\x00", "").strip()
            if value:
                return value[:128]

    return uuid.uuid4().hex


# ---------------------------------------------------------------------------
# Health / route map
# ---------------------------------------------------------------------------

def _safe_catalog_health() -> Dict[str, Any]:
    try:
        service = _create_catalog_service()
        if hasattr(service, "get_health") and callable(service.get_health):
            result = service.get_health()
            return (
                dict(result)
                if isinstance(result, Mapping)
                else {
                    "ok": False,
                    "healthy": False,
                    "ready": False,
                    "status": "error",
                    "error": {
                        "code": "invalid_catalog_health",
                        "message": "Catalog health is not a mapping.",
                    },
                }
            )

        return {
            "ok": True,
            "healthy": True,
            "ready": True,
            "status": "ok",
        }
    except Exception as exc:
        return _unavailable_response(
            "catalog_service_unavailable",
            str(exc),
            operation="catalog_health",
        )


def _safe_seed_health() -> Dict[str, Any]:
    try:
        service = _create_seed_service()
        if hasattr(service, "get_health") and callable(service.get_health):
            result = service.get_health()
            return (
                dict(result)
                if isinstance(result, Mapping)
                else {
                    "ok": False,
                    "healthy": False,
                    "ready": False,
                    "status": "error",
                    "error": {
                        "code": "invalid_seed_health",
                        "message": "Seed health is not a mapping.",
                    },
                }
            )

        return {
            "ok": True,
            "healthy": True,
            "ready": True,
            "status": "ok",
        }
    except Exception as exc:
        return _unavailable_response(
            "seed_service_unavailable",
            str(exc),
            operation="seed_health",
        )


def _safe_legacy_health() -> Dict[str, Any]:
    try:
        module = _load_legacy_route_service_module()
        function = getattr(
            module,
            "get_library_definition_route_service_health",
            None,
        )

        if callable(function):
            args = request.args if has_request_context() else {}
            result = function(args)
            return (
                dict(result)
                if isinstance(result, Mapping)
                else {
                    "ok": True,
                    "healthy": True,
                    "status": "ok",
                    "result": result,
                }
            )

        return {
            "ok": False,
            "healthy": False,
            "ready": False,
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
            operation="legacy_health",
        )


def get_library_definition_route_map_response(
    args: Mapping[str, Any] | None = None,
) -> Dict[str, Any]:
    return {
        "ok": True,
        "healthy": True,
        "ready": True,
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
                "GET /creator-readiness",
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
                "GET|POST /resolve-family-profile",
                "GET|POST /resolve-variant-profile",
                "GET|POST /empty-variant-values",
                "GET|POST /empty-variant-values/<profile_id>",
            ],
            "seed": [
                "GET|POST /seed/preview",
                "GET|POST /seed/validate",
                "POST /seed/run",
            ],
            "legacy": [
                "POST /validate-variant",
            ],
        },
    }


@lru_cache(maxsize=1)
def _cached_library_definition_route_list() -> tuple[str, ...]:
    return (
        "GET /api/v1/vplib/definitions/",
        "GET /api/v1/vplib/definitions/routes",
        "GET /api/v1/vplib/definitions/health",
        "GET /api/v1/vplib/definitions/selftest",
        "GET /api/v1/vplib/definitions/creator-readiness",
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
    )


def get_library_definition_route_list() -> list[str]:
    return list(_cached_library_definition_route_list())


def get_library_definition_routes_health() -> Dict[str, Any]:
    catalog_health = _safe_catalog_health()
    seed_health = _safe_seed_health()
    legacy_health = _safe_legacy_health()

    catalog_ready = bool(
        catalog_health.get(
            "ready",
            catalog_health.get("ok", False),
        )
    )
    catalog_healthy = bool(
        catalog_health.get(
            "healthy",
            catalog_health.get("ok", False),
        )
    )

    ready = catalog_ready
    healthy = catalog_healthy

    if healthy:
        status = "healthy"
    elif ready:
        status = "degraded"
    else:
        status = "unavailable"

    return {
        "ok": ready,
        "healthy": healthy,
        "ready": ready,
        "status": status,
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
        "supports_creator_readiness": True,
        "supports_seed_preview": True,
        "supports_seed_run": True,
        "supports_legacy_validation": True,
        "starter_profile_id": STARTER_VARIANT_PROFILE_ID,
    }


def clear_library_definition_routes_caches() -> Dict[str, Any]:
    """
    Clear import, route metadata and downstream service caches.

    The cache clear is best effort. One failing downstream cache must not
    prevent the remaining caches from being cleared.
    """
    cleared: list[str] = []
    downstream: Dict[str, Any] = {}

    for cached_func in (
        _load_catalog_service_module,
        _load_seed_service_module,
        _load_legacy_route_service_module,
        _catalog_exception_types,
        _cached_library_definition_route_list,
    ):
        try:
            cached_func.cache_clear()
            cleared.append(
                getattr(
                    cached_func,
                    "__name__",
                    str(cached_func),
                )
            )
        except Exception as exc:
            downstream[
                getattr(cached_func, "__name__", str(cached_func))
            ] = {
                "ok": False,
                "error": f"{type(exc).__name__}: {exc}",
            }

    downstream_specs = (
        (
            "catalog",
            _load_catalog_service_module,
            "clear_library_definition_catalog_service_caches",
        ),
        (
            "seed",
            _load_seed_service_module,
            "clear_library_definition_seed_service_caches",
        ),
        (
            "legacy",
            _load_legacy_route_service_module,
            "clear_library_definition_cache_response",
        ),
    )

    for name, loader, clear_function_name in downstream_specs:
        try:
            module = loader()
            clear_function = getattr(
                module,
                clear_function_name,
                None,
            )
            if not callable(clear_function):
                downstream[name] = {
                    "ok": False,
                    "status": "missing",
                    "function": clear_function_name,
                }
                continue

            result = clear_function()
            downstream[name] = (
                dict(result)
                if isinstance(result, Mapping)
                else {
                    "ok": True,
                    "result": result,
                }
            )
            cleared.append(clear_function_name)
        except Exception as exc:
            downstream[name] = {
                "ok": False,
                "error": f"{type(exc).__name__}: {exc}",
            }

    return {
        "ok": True,
        "cleared": cleared,
        "downstream": downstream,
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