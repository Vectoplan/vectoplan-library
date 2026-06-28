# services/vectoplan-library/routes/library_routes.py
"""
Flask-Routen für die VECTOPLAN Creative-Library-API.

Diese Datei ist der HTTP-Adapter für die Library-Schicht.

Sie ist bewusst dünn gehalten:

    HTTP / Flask
      -> routes/library_routes.py
      -> services/library_route_service.py              # legacy/dateibasierte Scan-Reads
      -> library.services.library_db_sync_service       # Source/ScanResult -> DB Sync
      -> library.services.creative_library_service      # DB-backed published Library Reads
      -> scanner / validation / read_models / taxonomy
      -> PostgreSQL published state

Diese Datei enthält keine Business-Logik.

Wesentliche Regeln:

- GET /scan liest Source-/Scan-Zustand und schreibt nicht in die DB.
- POST /sync schreibt synchronisierte/publizierte Daten in die DB.
- DB-Reads laufen über CreativeLibraryService.
- DB-Sync läuft über LibraryDbSyncService.
- Dateibasierte Legacy-Reads bleiben für Scan/Debug kompatibel.
- Published Library ist getrennt von Drafts und User-Overlays.
"""

from __future__ import annotations

import importlib
import traceback
from dataclasses import asdict, is_dataclass
from datetime import datetime, timezone
from functools import lru_cache
from pathlib import Path
from types import ModuleType
from typing import Any, Callable, Final, Mapping


# ---------------------------------------------------------------------------
# Optional Flask import
# ---------------------------------------------------------------------------

_FLASK_IMPORT_ERROR: BaseException | None = None

try:
    from flask import Blueprint, Response, jsonify, request
except Exception as import_exc:  # pragma: no cover - defensive fallback
    _FLASK_IMPORT_ERROR = import_exc
    Blueprint = None  # type: ignore[assignment]
    Response = Any  # type: ignore[assignment]
    jsonify = None  # type: ignore[assignment]
    request = None  # type: ignore[assignment]


# ---------------------------------------------------------------------------
# Settings fallback
# ---------------------------------------------------------------------------

_SETTINGS_IMPORT_ERROR: BaseException | None = None

try:
    from config.library_settings import (
        DEFAULT_LIBRARY_ROUTE_PREFIX,
        get_library_route_prefix_safe,
        get_library_route_plan,
    )
except Exception as import_exc:  # pragma: no cover - defensive fallback
    _SETTINGS_IMPORT_ERROR = import_exc

    DEFAULT_LIBRARY_ROUTE_PREFIX = "/api/v1/vplib/library"

    def get_library_route_prefix_safe() -> str:
        return DEFAULT_LIBRARY_ROUTE_PREFIX

    def get_library_route_plan(*args: Any, **kwargs: Any) -> dict[str, Any]:
        return {
            "route_prefix": DEFAULT_LIBRARY_ROUTE_PREFIX,
        }


# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

LIBRARY_ROUTES_VERSION: Final[str] = "1.0.1"
LIBRARY_ROUTES_COMPONENT: Final[str] = "library-routes"

DEFAULT_BLUEPRINT_NAME: Final[str] = "library_bp"

HEALTH_ROUTE: Final[str] = "/health"
ROUTES_ROUTE: Final[str] = "/routes"
SELFTEST_ROUTE: Final[str] = "/selftest"

SCAN_ROUTE: Final[str] = "/scan"
SYNC_ROUTE: Final[str] = "/sync"

BLOCKS_ROUTE: Final[str] = "/blocks"
TREE_ROUTE: Final[str] = "/tree"
CACHE_CLEAR_ROUTE: Final[str] = "/cache/clear"

BLOCK_VARIANTS_ROUTE: Final[str] = "/blocks/<path:block_id>/variants"
BLOCK_DETAIL_ROUTE: Final[str] = "/blocks/<path:block_id>"

PUBLISHED_ROUTE: Final[str] = "/published"
ITEMS_ROUTE: Final[str] = "/items"
ITEM_VARIANTS_ROUTE: Final[str] = "/items/<path:item_ref>/variants"
ITEM_REVISIONS_ROUTE: Final[str] = "/items/<path:item_ref>/revisions"
ITEM_ASSETS_ROUTE: Final[str] = "/items/<path:item_ref>/assets"
ITEM_DOCUMENTS_ROUTE: Final[str] = "/items/<path:item_ref>/documents"
ITEM_DETAIL_ROUTE: Final[str] = "/items/<path:item_ref>"

VPLIB_ITEM_ROUTE: Final[str] = "/vplib/<path:vplib_uid>"

SCAN_RUNS_ROUTE: Final[str] = "/scan-runs"
SCAN_RUN_FINISH_ROUTE: Final[str] = "/scan-runs/<path:scan_run_ref>/finish"
SCAN_RUN_ISSUES_ROUTE: Final[str] = "/scan-runs/<path:scan_run_ref>/issues"

INVENTORY_SLOTS_ROUTE: Final[str] = "/inventory/slots"
INVENTORY_SLOT_ROUTE: Final[str] = "/inventory/slots/<int:slot_index>"

ERROR_HTTP_STATUS: Final[int] = 500
DEFAULT_RESPONSE_HTTP_STATUS: Final[int] = 200

GENERAL_QUERY_KEYS: Final[tuple[str, ...]] = (
    "source",
    "force_refresh",
    "use_cache",
    "include_invalid",
    "enabled_only",
    "active_only",
    "visible_only",
    "include_raw_pipeline",
    "include_deleted",
    "include_current_revision",
    "include_revisions",
    "include_variants",
    "include_assets",
    "include_documents",
    "limit",
    "offset",
    "user_id",
)

TAXONOMY_QUERY_KEYS: Final[tuple[str, ...]] = (
    "domain",
    "category",
    "subcategory",
    "object_kind",
    "q",
    "include_empty_taxonomy_nodes",
    "include_inactive_taxonomy_nodes",
    "include_taxonomy_payload",
    "force_taxonomy_reload",
)

SYNC_QUERY_KEYS: Final[tuple[str, ...]] = (
    "source_root",
    "sourceRoot",
    "scan",
    "allow_scan",
    "publish_valid_only",
    "mark_missing_deleted",
    "include_raw_documents",
    "triggered_by",
    "triggeredBy",
)

SUPPORTED_QUERY_KEYS: Final[tuple[str, ...]] = (
    *GENERAL_QUERY_KEYS,
    *TAXONOMY_QUERY_KEYS,
    *SYNC_QUERY_KEYS,
)


# ---------------------------------------------------------------------------
# Lazy imports
# ---------------------------------------------------------------------------

@lru_cache(maxsize=1)
def _load_legacy_route_service_module() -> ModuleType:
    errors: list[str] = []

    for module_name in (
        "services.library_route_service",
        "src.services.library_route_service",
        "vectoplan_library.services.library_route_service",
        "vectoplan_library.src.services.library_route_service",
    ):
        try:
            return importlib.import_module(module_name)
        except Exception as exc:
            errors.append(f"{module_name}: {type(exc).__name__}: {exc}")

    raise ImportError(
        "library route service is unavailable. "
        + " | ".join(errors)
    )


@lru_cache(maxsize=1)
def _load_creative_library_service_module() -> ModuleType:
    errors: list[str] = []

    for module_name in (
        "library.services.creative_library_service",
        "src.library.services.creative_library_service",
        "vectoplan_library.library.services.creative_library_service",
        "vectoplan_library.src.library.services.creative_library_service",
    ):
        try:
            return importlib.import_module(module_name)
        except Exception as exc:
            errors.append(f"{module_name}: {type(exc).__name__}: {exc}")

    raise ImportError(
        "creative library service is unavailable. "
        + " | ".join(errors)
    )


@lru_cache(maxsize=1)
def _load_db_sync_service_module() -> ModuleType:
    errors: list[str] = []

    for module_name in (
        "library.services.library_db_sync_service",
        "src.library.services.library_db_sync_service",
        "vectoplan_library.library.services.library_db_sync_service",
        "vectoplan_library.src.library.services.library_db_sync_service",
    ):
        try:
            return importlib.import_module(module_name)
        except Exception as exc:
            errors.append(f"{module_name}: {type(exc).__name__}: {exc}")

    raise ImportError(
        "library db sync service is unavailable. "
        + " | ".join(errors)
    )


def _legacy_route_service() -> ModuleType:
    return _load_legacy_route_service_module()


def _create_published_service() -> Any:
    module = _load_creative_library_service_module()

    for factory_name in (
        "create_creative_library_service",
        "create_library_service",
        "create_published_library_service",
    ):
        factory = getattr(module, factory_name, None)
        if callable(factory):
            return factory()

    for class_name in (
        "CreativeLibraryService",
        "LibraryService",
        "PublishedLibraryService",
    ):
        service_class = getattr(module, class_name, None)
        if service_class is not None:
            return service_class()

    raise RuntimeError("CreativeLibraryService is not available.")


def _create_db_sync_service() -> Any:
    module = _load_db_sync_service_module()

    for factory_name in (
        "get_library_db_sync_service",
        "create_library_db_sync_service",
    ):
        factory = getattr(module, factory_name, None)
        if callable(factory):
            return factory()

    service_class = getattr(module, "LibraryDbSyncService", None)
    if service_class is not None:
        return service_class()

    raise RuntimeError("LibraryDbSyncService is not available.")


# ---------------------------------------------------------------------------
# Generic helpers
# ---------------------------------------------------------------------------

def utc_now_iso() -> str:
    """UTC-Zeit im ISO-Format."""
    return datetime.now(timezone.utc).isoformat()


def exception_to_dict(
    exc: BaseException | None,
    *,
    include_traceback: bool = False,
) -> dict[str, Any] | None:
    """Serialisiert Exceptions JSON-kompatibel."""
    if exc is None:
        return None

    data: dict[str, Any] = {
        "type": exc.__class__.__name__,
        "message": str(exc),
    }

    if include_traceback:
        data["traceback"] = traceback.format_exception(
            type(exc),
            exc,
            exc.__traceback__,
        )

    return data


def json_safe(value: Any) -> Any:
    """Defensiver JSON-Safe-Konverter."""
    try:
        if value is None:
            return None

        if isinstance(value, (str, int, float, bool)):
            return value

        if isinstance(value, Path):
            return str(value)

        if is_dataclass(value):
            return json_safe(asdict(value))

        if isinstance(value, Mapping):
            return {
                str(key): json_safe(item)
                for key, item in value.items()
            }

        if isinstance(value, (list, tuple, set)):
            return [json_safe(item) for item in value]

        if hasattr(value, "to_dict") and callable(value.to_dict):
            return json_safe(value.to_dict())

        if hasattr(value, "to_summary_dict") and callable(value.to_summary_dict):
            return json_safe(value.to_summary_dict())

        return str(value)

    except Exception as exc:
        return {
            "serialization_error": exception_to_dict(exc),
            "fallback_type": str(type(value)),
        }


def safe_str(value: Any, *, default: str = "") -> str:
    """Robuste String-Konvertierung."""
    try:
        if value is None:
            return default

        text = str(value).replace("\x00", "").strip()
        return text if text else default

    except Exception:
        return default


def safe_bool(value: Any, *, default: bool = False) -> bool:
    """Robuste Bool-Konvertierung."""
    if isinstance(value, bool):
        return value

    if value is None:
        return default

    try:
        text = str(value).strip().lower()
    except Exception:
        return default

    if text in {"1", "true", "yes", "y", "ja", "on", "enabled", "active", "visible", "scan", "sync"}:
        return True

    if text in {"0", "false", "no", "n", "nein", "off", "disabled", "inactive", "hidden"}:
        return False

    return default


def safe_int(
    value: Any,
    *,
    default: int | None = None,
    minimum: int | None = None,
    maximum: int | None = None,
) -> int | None:
    try:
        if value is None or value == "":
            result = default
        else:
            result = int(value)
    except Exception:
        result = default

    if result is None:
        return None

    if minimum is not None:
        result = max(minimum, result)

    if maximum is not None:
        result = min(maximum, result)

    return result


def safe_mapping(value: Any) -> dict[str, Any]:
    """
    Wandelt Mapping-/MultiDict-artige Werte robust in Dict um.

    Multi-value Query-Parameter bleiben als Liste erhalten, wenn mehr als ein
    Wert vorhanden ist. Ein einzelner Wert wird als Skalar zurückgegeben.
    """
    if value is None:
        return {}

    if isinstance(value, Mapping):
        try:
            getlist = getattr(value, "getlist", None)
            if callable(getlist):
                result: dict[str, Any] = {}
                for key in value.keys():
                    values = getlist(key)
                    if len(values) == 1:
                        result[str(key)] = values[0]
                    elif len(values) > 1:
                        result[str(key)] = values
                    else:
                        result[str(key)] = value.get(key)
                return result
            return dict(value)
        except Exception:
            return {}

    to_dict = getattr(value, "to_dict", None)
    if callable(to_dict):
        try:
            raw = to_dict(flat=False)
            if isinstance(raw, Mapping):
                result = {}
                for key, item in raw.items():
                    if isinstance(item, list):
                        result[str(key)] = item[0] if len(item) == 1 else item
                    else:
                        result[str(key)] = item
                return result
        except TypeError:
            try:
                raw = to_dict()
                return dict(raw) if isinstance(raw, Mapping) else {}
            except Exception:
                return {}
        except Exception:
            return {}

    items = getattr(value, "items", None)
    if callable(items):
        try:
            return {str(key): item for key, item in items()}
        except Exception:
            return {}

    try:
        return dict(value)
    except Exception:
        return {}


def normalize_query_args(query_args: Mapping[str, Any] | None) -> dict[str, Any]:
    """
    Normalisiert Query-Parameter minimal.

    Diese Funktion interpretiert keine Fachlogik. Sie macht nur Bool-/Int-nahe
    technische Flags stabiler und lässt Filterwerte unverändert.
    """
    source = dict(query_args or {})
    result: dict[str, Any] = {}

    bool_keys = {
        "force_refresh",
        "use_cache",
        "include_invalid",
        "enabled_only",
        "active_only",
        "visible_only",
        "include_raw_pipeline",
        "include_empty_taxonomy_nodes",
        "include_inactive_taxonomy_nodes",
        "include_taxonomy_payload",
        "force_taxonomy_reload",
        "include_deleted",
        "include_current_revision",
        "include_revisions",
        "include_variants",
        "include_assets",
        "include_documents",
        "mark_current",
        "replace_children",
        "validate",
        "commit",
        "allow_scan",
        "scan",
        "publish_valid_only",
        "mark_missing_deleted",
        "include_raw_documents",
    }

    int_keys = {
        "limit",
        "offset",
        "user_id",
        "slot_index",
    }

    for key, value in source.items():
        key_text = safe_str(key, default="")
        if not key_text:
            continue

        if key_text in bool_keys:
            result[key_text] = safe_bool(value, default=False)
        elif key_text in int_keys:
            result[key_text] = safe_int(value, default=None)
        else:
            result[key_text] = value

    return result


def get_query_args() -> dict[str, Any]:
    """Liest Flask Query Args defensiv."""
    try:
        if request is None:
            return {}
        return normalize_query_args(safe_mapping(request.args))
    except Exception:
        return {}


def get_json_payload() -> dict[str, Any]:
    """Liest JSON-Body defensiv."""
    try:
        if request is None:
            return {}

        if not request.is_json:
            return {}

        payload = request.get_json(silent=True)

        if isinstance(payload, Mapping):
            return dict(payload)

        return {}
    except Exception:
        return {}


def get_form_payload() -> dict[str, Any]:
    """Liest Form-Body defensiv."""
    try:
        if request is None or not request.form:
            return {}
        return safe_mapping(request.form)
    except Exception:
        return {}


def get_request_payload() -> dict[str, Any]:
    """Merged Query, JSON und Form. JSON/Form überschreiben Query."""
    payload: dict[str, Any] = {}
    payload.update(get_query_args())
    payload.update(get_json_payload())
    payload.update(get_form_payload())
    return payload


def get_request_context_payload() -> dict[str, Any]:
    """Liefert kleine Request-Metadaten für Debug-/Health-Antworten."""
    try:
        if request is None:
            return {}

        return {
            "method": safe_str(getattr(request, "method", None), default=""),
            "path": safe_str(getattr(request, "path", None), default=""),
            "endpoint": safe_str(getattr(request, "endpoint", None), default=""),
            "query_args": get_query_args(),
        }
    except Exception:
        return {}


def response_http_status(payload: Mapping[str, Any]) -> int:
    """Mappt Payload-Status auf HTTP-Status."""
    status = str(payload.get("status", "ok")).lower()

    if bool(payload.get("ok", False)):
        return 200

    if status == "not_found":
        return 404

    if status in {"bad_request", "invalid", "invalid_request"}:
        return 400

    if status == "unauthorized":
        return 401

    if status == "forbidden":
        return 403

    if status == "conflict":
        return 409

    if status in {"not_implemented"}:
        return 501

    if status in {"unavailable", "service_unavailable"}:
        return 503

    if status in {"error", "unhealthy", "failed"}:
        return 500

    return 200


def strip_internal_http_status(payload: Mapping[str, Any]) -> tuple[dict[str, Any], int]:
    """Entfernt `_http_status` aus Payload und gibt HTTP-Status separat zurück."""
    data = dict(payload)
    explicit_status = data.pop("_http_status", None)

    try:
        status_code = int(explicit_status) if explicit_status is not None else response_http_status(data)
    except Exception:
        status_code = DEFAULT_RESPONSE_HTTP_STATUS

    return data, status_code


def make_json_response(payload: Mapping[str, Any] | None, *, fallback_status: int = DEFAULT_RESPONSE_HTTP_STATUS) -> Any:
    """Baut eine Flask-JSON-Response."""
    try:
        raw_payload = dict(payload or {})
        raw_payload.setdefault("generated_at", utc_now_iso())
        raw_payload.setdefault("component", LIBRARY_ROUTES_COMPONENT)
        raw_payload.setdefault("route_component_version", LIBRARY_ROUTES_VERSION)

        data, status_code = strip_internal_http_status(raw_payload)

        if not isinstance(status_code, int) or status_code < 100 or status_code > 599:
            status_code = fallback_status

        if jsonify is None:
            return data

        response = jsonify(json_safe(data))
        response.status_code = status_code
        response.headers["X-Vectoplan-Component"] = LIBRARY_ROUTES_COMPONENT
        response.headers["X-Vectoplan-Route-Version"] = LIBRARY_ROUTES_VERSION
        response.headers["Cache-Control"] = "no-store"

        return response

    except Exception as exc:
        error_payload = {
            "ok": False,
            "status": "error",
            "message": "could not serialize library route response",
            "errors": ["could not serialize library route response"],
            "error": exception_to_dict(exc),
            "generated_at": utc_now_iso(),
            "component": LIBRARY_ROUTES_COMPONENT,
            "route_component_version": LIBRARY_ROUTES_VERSION,
        }

        if jsonify is None:
            return error_payload

        response = jsonify(error_payload)
        response.status_code = ERROR_HTTP_STATUS
        response.headers["X-Vectoplan-Component"] = LIBRARY_ROUTES_COMPONENT
        response.headers["X-Vectoplan-Route-Version"] = LIBRARY_ROUTES_VERSION
        response.headers["Cache-Control"] = "no-store"

        return response


def make_exception_response(
    exc: BaseException,
    *,
    message: str,
    include_traceback: bool = False,
) -> Any:
    """Baut standardisierte Exception-Response."""
    payload = {
        "ok": False,
        "status": "error",
        "message": message,
        "errors": [message],
        "error": exception_to_dict(exc, include_traceback=include_traceback),
        "generated_at": utc_now_iso(),
        "component": LIBRARY_ROUTES_COMPONENT,
        "route_component_version": LIBRARY_ROUTES_VERSION,
    }

    return make_json_response(payload, fallback_status=ERROR_HTTP_STATUS)


def service_result_to_route_payload(result: Any, *, route: str, default_payload_key: str = "payload") -> dict[str, Any]:
    """Konvertiert Service-Ergebnisse defensiv in Route-Payload."""
    if result is None:
        return {
            "ok": False,
            "status": "error",
            "route": route,
            "errors": ["service returned no result"],
        }

    if hasattr(result, "to_dict") and callable(result.to_dict):
        try:
            result = result.to_dict()
        except Exception:
            pass

    if isinstance(result, Mapping):
        payload = dict(result)
    else:
        payload = {
            "ok": True,
            "status": "ok",
            default_payload_key: json_safe(result),
        }

    payload.setdefault("route", route)
    payload.setdefault("ok", bool(payload.get("ok", True)))
    payload.setdefault("status", "ok" if payload.get("ok") else "error")
    payload.setdefault("request", get_request_context_payload())

    return payload


# ---------------------------------------------------------------------------
# Backend selection
# ---------------------------------------------------------------------------

def should_use_legacy_file_backend(query_args: Mapping[str, Any] | None = None) -> bool:
    """Ermittelt, ob explizit der legacy/dateibasierte Backend-Pfad genutzt werden soll."""
    query = dict(query_args or get_query_args())
    source = safe_str(query.get("source"), default="").lower()

    if source in {"file", "files", "legacy", "scan", "source"}:
        return True

    if safe_bool(query.get("legacy"), default=False):
        return True

    if safe_bool(query.get("file"), default=False):
        return True

    return False


def call_legacy_route_service(function_name: str, *, route: str, **kwargs: Any) -> dict[str, Any]:
    """Ruft legacy services.library_route_service defensiv auf."""
    try:
        service = _legacy_route_service()
        function = getattr(service, function_name, None)

        if not callable(function):
            raise RuntimeError(f"legacy route service has no {function_name!r}")

        result = function(**kwargs)
        payload = dict(result) if isinstance(result, Mapping) else {"result": result}
        payload.setdefault("ok", True)
        payload.setdefault("status", "ok")
        payload.setdefault("route", route)
        payload.setdefault("backend", "legacy_file")
        return payload

    except Exception as exc:
        return {
            "ok": False,
            "status": "unavailable",
            "route": route,
            "backend": "legacy_file",
            "message": "legacy library route service is unavailable",
            "errors": ["legacy library route service is unavailable"],
            "error": exception_to_dict(exc, include_traceback=True),
            "_http_status": 503,
        }


def call_published_service(callback: Callable[[Any], Any], *, route: str) -> dict[str, Any]:
    """Erzeugt CreativeLibraryService und ruft Callback defensiv auf."""
    try:
        service = _create_published_service()
    except Exception as exc:
        return {
            "ok": False,
            "status": "unavailable",
            "route": route,
            "backend": "published_db",
            "message": "creative library service is unavailable",
            "errors": ["creative library service is unavailable"],
            "error": exception_to_dict(exc, include_traceback=True),
            "_http_status": 503,
        }

    try:
        result = callback(service)
        payload = service_result_to_route_payload(result, route=route)
        payload.setdefault("backend", "published_db")
        return payload
    except Exception as exc:
        return {
            "ok": False,
            "status": "error",
            "route": route,
            "backend": "published_db",
            "message": f"{route} route failed",
            "errors": [f"{route} route failed"],
            "error": exception_to_dict(exc, include_traceback=True),
            "_http_status": 500,
        }


def call_db_sync_service(callback: Callable[[Any], Any], *, route: str) -> dict[str, Any]:
    """Erzeugt LibraryDbSyncService und ruft Callback defensiv auf."""
    try:
        service = _create_db_sync_service()
    except Exception as exc:
        return {
            "ok": False,
            "status": "unavailable",
            "route": route,
            "backend": "db_sync",
            "message": "library db sync service is unavailable",
            "errors": ["library db sync service is unavailable"],
            "error": exception_to_dict(exc, include_traceback=True),
            "_http_status": 503,
        }

    try:
        result = callback(service)
        payload = service_result_to_route_payload(result, route=route)
        payload.setdefault("backend", "db_sync")
        payload.setdefault("writes_database", True)
        return payload
    except Exception as exc:
        return {
            "ok": False,
            "status": "error",
            "route": route,
            "backend": "db_sync",
            "message": f"{route} route failed",
            "errors": [f"{route} route failed"],
            "error": exception_to_dict(exc, include_traceback=True),
            "_http_status": 500,
        }


# ---------------------------------------------------------------------------
# Route metadata
# ---------------------------------------------------------------------------

def make_route_metadata() -> dict[str, Any]:
    """Liefert Routen-Metadaten."""
    try:
        route_prefix = get_library_route_prefix_safe()
    except Exception:
        route_prefix = DEFAULT_LIBRARY_ROUTE_PREFIX

    return {
        "component": LIBRARY_ROUTES_COMPONENT,
        "version": LIBRARY_ROUTES_VERSION,
        "route_prefix": route_prefix,
        "routes": {
            "health": f"{route_prefix}{HEALTH_ROUTE}",
            "routes": f"{route_prefix}{ROUTES_ROUTE}",
            "selftest": f"{route_prefix}{SELFTEST_ROUTE}",
            "scan": f"{route_prefix}{SCAN_ROUTE}",
            "sync": f"{route_prefix}{SYNC_ROUTE}",
            "blocks": f"{route_prefix}{BLOCKS_ROUTE}",
            "block_detail": f"{route_prefix}/blocks/<block_id>",
            "block_variants": f"{route_prefix}/blocks/<block_id>/variants",
            "tree": f"{route_prefix}{TREE_ROUTE}",
            "published": f"{route_prefix}{PUBLISHED_ROUTE}",
            "items": f"{route_prefix}{ITEMS_ROUTE}",
            "item_detail": f"{route_prefix}/items/<item_ref>",
            "item_variants": f"{route_prefix}/items/<item_ref>/variants",
            "item_revisions": f"{route_prefix}/items/<item_ref>/revisions",
            "item_assets": f"{route_prefix}/items/<item_ref>/assets",
            "item_documents": f"{route_prefix}/items/<item_ref>/documents",
            "vplib_item": f"{route_prefix}/vplib/<vplib_uid>",
            "scan_runs": f"{route_prefix}{SCAN_RUNS_ROUTE}",
            "scan_run_finish": f"{route_prefix}/scan-runs/<scan_run_ref>/finish",
            "scan_run_issues": f"{route_prefix}/scan-runs/<scan_run_ref>/issues",
            "inventory_slots": f"{route_prefix}{INVENTORY_SLOTS_ROUTE}",
            "inventory_slot": f"{route_prefix}/inventory/slots/<slot_index>",
            "cache_clear": f"{route_prefix}{CACHE_CLEAR_ROUTE}",
        },
        "supported_query": {
            "general": list(GENERAL_QUERY_KEYS),
            "taxonomy": list(TAXONOMY_QUERY_KEYS),
            "sync": list(SYNC_QUERY_KEYS),
            "all": list(SUPPORTED_QUERY_KEYS),
        },
        "imports": {
            "flask": {
                "ok": _FLASK_IMPORT_ERROR is None,
                "error": exception_to_dict(_FLASK_IMPORT_ERROR),
            },
            "settings": {
                "ok": _SETTINGS_IMPORT_ERROR is None,
                "error": exception_to_dict(_SETTINGS_IMPORT_ERROR),
            },
            "legacy_route_service": get_legacy_route_service_status(),
            "creative_library_service": get_published_service_status(),
            "library_db_sync_service": get_db_sync_service_status(),
        },
    }


def get_legacy_route_service_status() -> dict[str, Any]:
    try:
        module = _legacy_route_service()
        return {
            "ok": True,
            "module": getattr(module, "__name__", ""),
        }
    except Exception as exc:
        return {
            "ok": False,
            "error": exception_to_dict(exc),
        }


def get_published_service_status() -> dict[str, Any]:
    try:
        service = _create_published_service()
        health = service.get_health() if hasattr(service, "get_health") else {"ok": True}
        return {
            "ok": True,
            "service": type(service).__name__,
            "health": json_safe(health),
        }
    except Exception as exc:
        return {
            "ok": False,
            "error": exception_to_dict(exc),
        }


def get_db_sync_service_status() -> dict[str, Any]:
    try:
        service = _create_db_sync_service()
        health = (
            service.health(check_repository=False, check_scan_service=False)
            if hasattr(service, "health")
            else {"ok": True}
        )
        return {
            "ok": True,
            "service": type(service).__name__,
            "health": json_safe(health),
        }
    except Exception as exc:
        return {
            "ok": False,
            "error": exception_to_dict(exc),
        }


def get_route_map_payload() -> dict[str, Any]:
    """Route map payload."""
    metadata = make_route_metadata()

    return {
        "ok": True,
        "status": "ok",
        "route": "routes",
        "component": LIBRARY_ROUTES_COMPONENT,
        "version": LIBRARY_ROUTES_VERSION,
        "route_metadata": metadata,
        "routes": metadata.get("routes", {}),
        "supported_query": metadata.get("supported_query", {}),
    }


# ---------------------------------------------------------------------------
# DB/published route payload builders
# ---------------------------------------------------------------------------

def published_library_payload_from_query(route: str) -> dict[str, Any]:
    query = get_query_args()
    return call_published_service(
        lambda service: service.get_library(
            user_id=query.get("user_id"),
            domain=query.get("domain"),
            category=query.get("category"),
            subcategory=query.get("subcategory"),
            object_kind=query.get("object_kind"),
            status=query.get("status"),
            source_scope=query.get("source_scope"),
            include_deleted=safe_bool(query.get("include_deleted"), default=False),
            include_current_revision=safe_bool(query.get("include_current_revision"), default=True),
            include_revisions=safe_bool(query.get("include_revisions"), default=False),
            include_variants=safe_bool(query.get("include_variants"), default=False),
            include_assets=safe_bool(query.get("include_assets"), default=False),
            include_documents=safe_bool(query.get("include_documents"), default=False),
            active_only=safe_bool(query.get("active_only"), default=True),
            visible_only=safe_bool(query.get("visible_only"), default=False),
            limit=safe_int(query.get("limit"), default=250, minimum=1, maximum=5000) or 250,
            offset=safe_int(query.get("offset"), default=0, minimum=0) or 0,
        ),
        route=route,
    )


def block_list_payload_from_db() -> dict[str, Any]:
    payload = published_library_payload_from_query("blocks")
    payload.setdefault("route", "blocks")
    payload.setdefault("backend", "published_db")

    service_payload = payload.get("payload")
    if isinstance(service_payload, Mapping):
        items = service_payload.get("items", [])
        payload.setdefault("blocks", items)
        payload.setdefault("items", items)
        payload.setdefault("block_count", len(items) if isinstance(items, list) else 0)

    return payload


def item_detail_payload_from_db(item_ref: Any, *, route: str = "item_detail") -> dict[str, Any]:
    query = get_query_args()

    return call_published_service(
        lambda service: service.get_item(
            item_ref,
            include_current_revision=safe_bool(query.get("include_current_revision"), default=True),
            include_revisions=safe_bool(query.get("include_revisions"), default=False),
            include_variants=safe_bool(query.get("include_variants"), default=True),
            include_assets=safe_bool(query.get("include_assets"), default=True),
            include_documents=safe_bool(query.get("include_documents"), default=True),
        ),
        route=route,
    )


def item_children_payload(item_ref: Any, child_key: str, *, route: str) -> dict[str, Any]:
    payload = item_detail_payload_from_db(
        item_ref,
        route=route,
    )

    service_payload = payload.get("payload")
    item_payload = {}
    if isinstance(service_payload, Mapping):
        item_payload = service_payload.get("item", {}) if isinstance(service_payload.get("item"), Mapping) else {}

    items = item_payload.get(child_key, []) if isinstance(item_payload, Mapping) else []

    return {
        "ok": bool(payload.get("ok", False)),
        "status": payload.get("status", "ok" if payload.get("ok") else "error"),
        "route": route,
        "backend": "published_db",
        "item_ref": item_ref,
        "count": len(items) if isinstance(items, list) else 0,
        "items": items if isinstance(items, list) else [],
        "source_response": payload,
    }


def tree_payload_from_db() -> dict[str, Any]:
    query = get_query_args()
    query = dict(query)
    query["include_current_revision"] = False
    query["include_variants"] = False
    query["include_assets"] = False
    query["include_documents"] = False
    query["limit"] = query.get("limit") or 5000

    payload = call_published_service(
        lambda service: service.get_library(
            user_id=query.get("user_id"),
            domain=query.get("domain"),
            category=query.get("category"),
            subcategory=query.get("subcategory"),
            object_kind=query.get("object_kind"),
            include_deleted=safe_bool(query.get("include_deleted"), default=False),
            include_current_revision=False,
            include_revisions=False,
            include_variants=False,
            include_assets=False,
            include_documents=False,
            active_only=safe_bool(query.get("active_only"), default=True),
            visible_only=safe_bool(query.get("visible_only"), default=False),
            limit=safe_int(query.get("limit"), default=5000, minimum=1, maximum=5000) or 5000,
            offset=safe_int(query.get("offset"), default=0, minimum=0) or 0,
        ),
        route="tree",
    )

    service_payload = payload.get("payload")
    items = []
    if isinstance(service_payload, Mapping):
        items = service_payload.get("items", []) if isinstance(service_payload.get("items"), list) else []

    tree = build_taxonomy_tree_from_items(items)

    return {
        "ok": bool(payload.get("ok", False)),
        "status": payload.get("status", "ok" if payload.get("ok") else "error"),
        "route": "tree",
        "backend": "published_db",
        "tree": tree,
        "item_count": len(items),
        "source_response": payload,
    }


def build_taxonomy_tree_from_items(items: list[Any]) -> dict[str, Any]:
    """Builds a simple domain/category/subcategory tree from item payloads."""
    tree: dict[str, Any] = {
        "domains": [],
        "by_domain": {},
    }

    by_domain: dict[str, dict[str, Any]] = {}

    for item in items:
        if not isinstance(item, Mapping):
            continue

        domain = safe_str(item.get("domain"), default="unknown")
        category = safe_str(item.get("category"), default="unknown")
        subcategory = safe_str(item.get("subcategory"), default="unknown")

        domain_node = by_domain.setdefault(
            domain,
            {
                "id": domain,
                "label": domain,
                "categories": [],
                "by_category": {},
                "item_count": 0,
            },
        )
        domain_node["item_count"] += 1

        by_category = domain_node["by_category"]
        category_node = by_category.setdefault(
            category,
            {
                "id": category,
                "label": category,
                "subcategories": [],
                "by_subcategory": {},
                "item_count": 0,
            },
        )
        category_node["item_count"] += 1

        by_subcategory = category_node["by_subcategory"]
        subcategory_node = by_subcategory.setdefault(
            subcategory,
            {
                "id": subcategory,
                "label": subcategory,
                "items": [],
                "item_count": 0,
            },
        )
        subcategory_node["item_count"] += 1
        subcategory_node["items"].append(item)

    for domain_key in sorted(by_domain.keys()):
        domain_node = by_domain[domain_key]

        for category_key in sorted(domain_node["by_category"].keys()):
            category_node = domain_node["by_category"][category_key]

            for subcategory_key in sorted(category_node["by_subcategory"].keys()):
                category_node["subcategories"].append(category_node["by_subcategory"][subcategory_key])

            category_node.pop("by_subcategory", None)
            domain_node["categories"].append(category_node)

        domain_node.pop("by_category", None)
        tree["domains"].append(domain_node)

    tree["by_domain"] = by_domain
    return tree


def first_non_empty(*values: Any) -> Any:
    for value in values:
        if value is None:
            continue
        if isinstance(value, str) and not value.strip():
            continue
        return value
    return None


# ---------------------------------------------------------------------------
# Sync route payload
# ---------------------------------------------------------------------------

def sync_payload_from_request() -> dict[str, Any]:
    """
    Handles POST /sync.

    This is the explicit DB write route.

    Supported bodies:
        {} or {"scan": true}
            -> run filesystem scan and sync to DB

        {"scan_result": {...}}
            -> sync existing scan/pipeline result to DB

        {"items": [...]}, {"blocks": [...]}, {"candidates": [...]}
            -> sync existing candidates to DB

        {"publish_payload": {...}} or {"package_payload": {...}}
            -> wraps single payload as one sync candidate
    """
    body = get_request_payload()
    query = get_query_args()

    source_root = first_non_empty(
        body.get("source_root"),
        body.get("sourceRoot"),
        query.get("source_root"),
        query.get("sourceRoot"),
    )
    force_refresh = safe_bool(
        first_non_empty(body.get("force_refresh"), query.get("force_refresh")),
        default=True,
    )
    publish_valid_only = first_non_empty(
        body.get("publish_valid_only"),
        body.get("publishValidOnly"),
        query.get("publish_valid_only"),
        query.get("publishValidOnly"),
    )
    mark_missing_deleted = first_non_empty(
        body.get("mark_missing_deleted"),
        body.get("markMissingDeleted"),
        query.get("mark_missing_deleted"),
        query.get("markMissingDeleted"),
    )
    include_raw_documents = first_non_empty(
        body.get("include_raw_documents"),
        body.get("includeRawDocuments"),
        query.get("include_raw_documents"),
        query.get("includeRawDocuments"),
    )
    triggered_by = first_non_empty(
        body.get("triggered_by"),
        body.get("triggeredBy"),
        "api:/library/sync",
    )

    scan_options = {}
    if isinstance(body.get("scan_options"), Mapping):
        scan_options.update(dict(body.get("scan_options")))
    if isinstance(body.get("scanOptions"), Mapping):
        scan_options.update(dict(body.get("scanOptions")))

    for key in (
        "include_invalid",
        "enabled_only",
        "use_cache",
        "include_raw_pipeline",
        "include_taxonomy_payload",
        "force_taxonomy_reload",
        "validate_taxonomy",
        "require_taxonomy",
        "include_empty_taxonomy_nodes",
        "include_inactive_taxonomy_nodes",
    ):
        if key in body:
            scan_options[key] = body[key]
        elif key in query:
            scan_options[key] = query[key]

    explicit_scan_result = first_non_empty(
        body.get("scan_result"),
        body.get("scanResult"),
        body.get("pipeline_result"),
        body.get("pipelineResult"),
        body.get("library_scan_result"),
        body.get("libraryScanResult"),
    )

    if explicit_scan_result is not None:
        return call_db_sync_service(
            lambda service: service.sync_scan_result_to_db(
                explicit_scan_result,
                publish_valid_only=safe_bool(publish_valid_only, default=True) if publish_valid_only is not None else None,
                mark_missing_deleted=safe_bool(mark_missing_deleted, default=False) if mark_missing_deleted is not None else None,
            ),
            route="sync",
        )

    if any(isinstance(body.get(key), list) for key in ("items", "blocks", "candidates", "results")):
        return call_db_sync_service(
            lambda service: service.sync_scan_result_to_db(
                body,
                publish_valid_only=safe_bool(publish_valid_only, default=True) if publish_valid_only is not None else None,
                mark_missing_deleted=safe_bool(mark_missing_deleted, default=False) if mark_missing_deleted is not None else None,
            ),
            route="sync",
        )

    single_payload = first_non_empty(
        body.get("publish_payload"),
        body.get("publishPayload"),
        body.get("package_payload"),
        body.get("packagePayload"),
        body.get("sync_payload"),
        body.get("syncPayload"),
        body.get("payload"),
    )

    if isinstance(single_payload, Mapping):
        return call_db_sync_service(
            lambda service: service.sync_scan_result_to_db(
                {"items": [single_payload]},
                publish_valid_only=safe_bool(publish_valid_only, default=True) if publish_valid_only is not None else None,
                mark_missing_deleted=safe_bool(mark_missing_deleted, default=False) if mark_missing_deleted is not None else None,
            ),
            route="sync",
        )

    allow_scan = safe_bool(
        first_non_empty(
            body.get("scan"),
            body.get("allow_scan"),
            query.get("scan"),
            query.get("allow_scan"),
        ),
        default=True,
    )
    if not allow_scan:
        return {
            "ok": False,
            "status": "invalid_request",
            "route": "sync",
            "backend": "db_sync",
            "errors": [
                "No scan_result/items/publish_payload supplied and scan execution is disabled."
            ],
            "_http_status": 400,
        }

    return call_db_sync_service(
        lambda service: service.sync_library_source(
            source_root=source_root,
            force_refresh=force_refresh,
            triggered_by=triggered_by,
            publish_valid_only=safe_bool(publish_valid_only, default=True) if publish_valid_only is not None else None,
            mark_missing_deleted=safe_bool(mark_missing_deleted, default=False) if mark_missing_deleted is not None else None,
            include_raw_documents=safe_bool(include_raw_documents, default=True) if include_raw_documents is not None else None,
            scan_options=scan_options,
        ),
        route="sync",
    )


# ---------------------------------------------------------------------------
# Blueprint creation
# ---------------------------------------------------------------------------

def create_library_blueprint() -> Any:
    """Erzeugt den Flask Blueprint für die Library-Routen."""
    if Blueprint is None:
        raise RuntimeError(
            f"Flask Blueprint is unavailable: {exception_to_dict(_FLASK_IMPORT_ERROR)}"
        )

    route_prefix = get_library_route_prefix_safe()

    blueprint_obj = Blueprint(
        "library_bp",
        __name__,
        url_prefix=route_prefix,
    )

    # -----------------------------------------------------------------------
    # Diagnostics
    # -----------------------------------------------------------------------

    @blueprint_obj.get(HEALTH_ROUTE)
    def library_health() -> Any:
        """GET /api/v1/vplib/library/health"""
        try:
            legacy_payload = call_legacy_route_service(
                "get_health_payload",
                route="legacy_health",
                query_args=get_query_args(),
                payload=get_json_payload(),
            )
            published_health = get_published_service_status()
            db_sync_health = get_db_sync_service_status()

            is_ok = bool(published_health.get("ok")) and bool(db_sync_health.get("ok"))

            payload = {
                "ok": is_ok,
                "healthy": is_ok,
                "status": "healthy" if is_ok else "degraded",
                "route": "health",
                "route_metadata": make_route_metadata(),
                "request": get_request_context_payload(),
                "legacy_file_backend": legacy_payload,
                "published_db_backend": published_health,
                "db_sync_backend": db_sync_health,
                "scan_get_writes_database": False,
                "sync_post_writes_database": True,
            }

            return make_json_response(payload)

        except Exception as exc:
            return make_exception_response(
                exc,
                message="library health route failed",
            )

    @blueprint_obj.get(ROUTES_ROUTE)
    def library_routes() -> Any:
        """GET /api/v1/vplib/library/routes"""
        try:
            payload = get_route_map_payload()
            payload.setdefault("request", get_request_context_payload())
            return make_json_response(payload)
        except Exception as exc:
            return make_exception_response(
                exc,
                message="library routes route failed",
            )

    @blueprint_obj.get(SELFTEST_ROUTE)
    def library_selftest() -> Any:
        """GET /api/v1/vplib/library/selftest"""
        try:
            payload = {
                "ok": True,
                "healthy": True,
                "status": "ok",
                "route": "selftest",
                "route_metadata": make_route_metadata(),
                "request": get_request_context_payload(),
                "legacy_file_backend": get_legacy_route_service_status(),
                "published_db_backend": get_published_service_status(),
                "db_sync_backend": get_db_sync_service_status(),
            }
            return make_json_response(payload)
        except Exception as exc:
            return make_exception_response(
                exc,
                message="library selftest route failed",
            )

    # -----------------------------------------------------------------------
    # Scan / Sync
    # -----------------------------------------------------------------------

    @blueprint_obj.get(SCAN_ROUTE)
    def library_scan() -> Any:
        """
        GET /api/v1/vplib/library/scan

        Führt dateibasierten Scan aus und schreibt nicht in die DB.
        """
        try:
            payload = call_legacy_route_service(
                "get_scan_payload",
                route="scan",
                query_args=get_query_args(),
                payload=get_json_payload(),
            )
            payload.setdefault("route", "scan")
            payload.setdefault("request", get_request_context_payload())
            payload["writes_database"] = False
            payload["sync_route"] = f"{get_library_route_prefix_safe()}{SYNC_ROUTE}"

            return make_json_response(payload)

        except Exception as exc:
            return make_exception_response(
                exc,
                message="library scan route failed",
            )

    @blueprint_obj.post(SYNC_ROUTE)
    def library_sync() -> Any:
        """
        POST /api/v1/vplib/library/sync

        Explizite schreibende Synchronisation in die published DB.
        """
        try:
            payload = sync_payload_from_request()
            payload.setdefault("route", "sync")
            payload.setdefault("request", get_request_context_payload())
            payload.setdefault("backend", "db_sync")
            payload["writes_database"] = True

            return make_json_response(payload)

        except Exception as exc:
            return make_exception_response(
                exc,
                message="library sync route failed",
            )

    # -----------------------------------------------------------------------
    # Compatibility blocks/tree routes
    # -----------------------------------------------------------------------

    @blueprint_obj.get(BLOCKS_ROUTE)
    def library_blocks() -> Any:
        """
        GET /api/v1/vplib/library/blocks

        Default: published DB.
        Legacy file backend: ?source=file or ?legacy=true.
        """
        try:
            if should_use_legacy_file_backend():
                payload = call_legacy_route_service(
                    "get_blocks_payload",
                    route="blocks",
                    query_args=get_query_args(),
                    payload=get_json_payload(),
                )
            else:
                payload = block_list_payload_from_db()

            payload.setdefault("route", "blocks")
            payload.setdefault("request", get_request_context_payload())

            return make_json_response(payload)

        except Exception as exc:
            return make_exception_response(
                exc,
                message="library blocks route failed",
            )

    @blueprint_obj.get(TREE_ROUTE)
    def library_tree() -> Any:
        """
        GET /api/v1/vplib/library/tree

        Default: DB tree from published items.
        Legacy file backend: ?source=file or ?legacy=true.
        """
        try:
            if should_use_legacy_file_backend():
                payload = call_legacy_route_service(
                    "get_tree_payload",
                    route="tree",
                    query_args=get_query_args(),
                    payload=get_json_payload(),
                )
            else:
                payload = tree_payload_from_db()

            payload.setdefault("route", "tree")
            payload.setdefault("request", get_request_context_payload())

            return make_json_response(payload)

        except Exception as exc:
            return make_exception_response(
                exc,
                message="library tree route failed",
            )

    @blueprint_obj.get(BLOCK_VARIANTS_ROUTE)
    def library_block_variants(block_id: str) -> Any:
        """
        GET /api/v1/vplib/library/blocks/<block_id>/variants

        Compatibility alias for item variants.
        """
        try:
            if should_use_legacy_file_backend():
                payload = call_legacy_route_service(
                    "get_block_variants_payload",
                    route="block_variants",
                    block_id=block_id,
                    query_args=get_query_args(),
                    payload=get_json_payload(),
                )
            else:
                payload = item_children_payload(block_id, "variants", route="block_variants")

            payload.setdefault("route", "block_variants")
            payload.setdefault("block_id", block_id)
            payload.setdefault("request", get_request_context_payload())

            return make_json_response(payload)

        except Exception as exc:
            return make_exception_response(
                exc,
                message="library block variants route failed",
            )

    @blueprint_obj.get(BLOCK_DETAIL_ROUTE)
    def library_block_detail(block_id: str) -> Any:
        """
        GET /api/v1/vplib/library/blocks/<block_id>

        Compatibility alias for published item detail.
        """
        try:
            if should_use_legacy_file_backend():
                payload = call_legacy_route_service(
                    "get_block_detail_payload",
                    route="block_detail",
                    block_id=block_id,
                    query_args=get_query_args(),
                    payload=get_json_payload(),
                )
            else:
                payload = item_detail_payload_from_db(block_id, route="block_detail")

            payload.setdefault("route", "block_detail")
            payload.setdefault("block_id", block_id)
            payload.setdefault("request", get_request_context_payload())

            return make_json_response(payload)

        except Exception as exc:
            return make_exception_response(
                exc,
                message="library block detail route failed",
            )

    # -----------------------------------------------------------------------
    # Published DB read routes
    # -----------------------------------------------------------------------

    @blueprint_obj.get(PUBLISHED_ROUTE)
    def library_published() -> Any:
        """GET /api/v1/vplib/library/published"""
        try:
            payload = published_library_payload_from_query("published")
            payload.setdefault("request", get_request_context_payload())
            return make_json_response(payload)
        except Exception as exc:
            return make_exception_response(
                exc,
                message="library published route failed",
            )

    @blueprint_obj.get(ITEMS_ROUTE)
    def library_items() -> Any:
        """GET /api/v1/vplib/library/items"""
        try:
            payload = published_library_payload_from_query("items")
            payload.setdefault("request", get_request_context_payload())
            return make_json_response(payload)
        except Exception as exc:
            return make_exception_response(
                exc,
                message="library items route failed",
            )

    @blueprint_obj.get(VPLIB_ITEM_ROUTE)
    def library_item_by_vplib_uid(vplib_uid: str) -> Any:
        """GET /api/v1/vplib/library/vplib/<vplib_uid>"""
        try:
            query = get_query_args()
            payload = call_published_service(
                lambda service: service.get_item_by_vplib_uid(
                    vplib_uid,
                    include_current_revision=safe_bool(query.get("include_current_revision"), default=True),
                    include_revisions=safe_bool(query.get("include_revisions"), default=False),
                    include_variants=safe_bool(query.get("include_variants"), default=True),
                    include_assets=safe_bool(query.get("include_assets"), default=True),
                    include_documents=safe_bool(query.get("include_documents"), default=True),
                ),
                route="vplib_item",
            )
            payload.setdefault("vplib_uid", vplib_uid)
            payload.setdefault("request", get_request_context_payload())
            return make_json_response(payload)
        except Exception as exc:
            return make_exception_response(
                exc,
                message="library vplib item route failed",
            )

    @blueprint_obj.get(ITEM_VARIANTS_ROUTE)
    def library_item_variants(item_ref: str) -> Any:
        """GET /api/v1/vplib/library/items/<item_ref>/variants"""
        try:
            payload = item_children_payload(item_ref, "variants", route="item_variants")
            payload.setdefault("request", get_request_context_payload())
            return make_json_response(payload)
        except Exception as exc:
            return make_exception_response(
                exc,
                message="library item variants route failed",
            )

    @blueprint_obj.get(ITEM_REVISIONS_ROUTE)
    def library_item_revisions(item_ref: str) -> Any:
        """GET /api/v1/vplib/library/items/<item_ref>/revisions"""
        try:
            payload = call_published_service(
                lambda service: service.list_revisions(
                    item_ref,
                    include_deleted=safe_bool(get_query_args().get("include_deleted"), default=False),
                    active_only=safe_bool(get_query_args().get("active_only"), default=True),
                ),
                route="item_revisions",
            )
            payload.setdefault("item_ref", item_ref)
            payload.setdefault("request", get_request_context_payload())
            return make_json_response(payload)
        except Exception as exc:
            return make_exception_response(
                exc,
                message="library item revisions route failed",
            )

    @blueprint_obj.get(ITEM_ASSETS_ROUTE)
    def library_item_assets(item_ref: str) -> Any:
        """GET /api/v1/vplib/library/items/<item_ref>/assets"""
        try:
            payload = item_children_payload(item_ref, "assets", route="item_assets")
            payload.setdefault("request", get_request_context_payload())
            return make_json_response(payload)
        except Exception as exc:
            return make_exception_response(
                exc,
                message="library item assets route failed",
            )

    @blueprint_obj.get(ITEM_DOCUMENTS_ROUTE)
    def library_item_documents(item_ref: str) -> Any:
        """GET /api/v1/vplib/library/items/<item_ref>/documents"""
        try:
            payload = item_children_payload(item_ref, "documents", route="item_documents")
            payload.setdefault("request", get_request_context_payload())
            return make_json_response(payload)
        except Exception as exc:
            return make_exception_response(
                exc,
                message="library item documents route failed",
            )

    @blueprint_obj.get(ITEM_DETAIL_ROUTE)
    def library_item_detail(item_ref: str) -> Any:
        """GET /api/v1/vplib/library/items/<item_ref>"""
        try:
            payload = item_detail_payload_from_db(item_ref, route="item_detail")
            payload.setdefault("item_ref", item_ref)
            payload.setdefault("request", get_request_context_payload())
            return make_json_response(payload)
        except Exception as exc:
            return make_exception_response(
                exc,
                message="library item detail route failed",
            )

    # -----------------------------------------------------------------------
    # Scan run routes
    # -----------------------------------------------------------------------

    @blueprint_obj.get(SCAN_RUNS_ROUTE)
    def library_scan_runs() -> Any:
        """GET /api/v1/vplib/library/scan-runs"""
        try:
            query = get_query_args()
            payload = call_published_service(
                lambda service: service.list_scan_runs(
                    scan_run_uid=query.get("scan_run_uid"),
                    status=query.get("status"),
                    source_root=query.get("source_root"),
                    limit=safe_int(query.get("limit"), default=250, minimum=1, maximum=5000) or 250,
                    offset=safe_int(query.get("offset"), default=0, minimum=0) or 0,
                ),
                route="scan_runs",
            )
            payload.setdefault("request", get_request_context_payload())
            return make_json_response(payload)
        except Exception as exc:
            return make_exception_response(
                exc,
                message="library scan-runs route failed",
            )

    @blueprint_obj.post(SCAN_RUNS_ROUTE)
    def library_scan_run_start() -> Any:
        """POST /api/v1/vplib/library/scan-runs"""
        try:
            payload_body = get_request_payload()
            payload = call_published_service(
                lambda service: service.start_scan_run(
                    payload_body,
                    commit=safe_bool(payload_body.get("commit"), default=True),
                ),
                route="scan_run_start",
            )
            payload.setdefault("request", get_request_context_payload())
            return make_json_response(payload)
        except Exception as exc:
            return make_exception_response(
                exc,
                message="library scan-run start route failed",
            )

    @blueprint_obj.post(SCAN_RUN_FINISH_ROUTE)
    def library_scan_run_finish(scan_run_ref: str) -> Any:
        """POST /api/v1/vplib/library/scan-runs/<scan_run_ref>/finish"""
        try:
            payload_body = get_request_payload()
            payload = call_published_service(
                lambda service: service.finish_scan_run(
                    scan_run_ref,
                    status=payload_body.get("status") or "completed",
                    counters=payload_body.get("counters") if isinstance(payload_body.get("counters"), Mapping) else payload_body,
                    errors=payload_body.get("errors") if isinstance(payload_body.get("errors"), list) else None,
                    commit=safe_bool(payload_body.get("commit"), default=True),
                ),
                route="scan_run_finish",
            )
            payload.setdefault("scan_run_ref", scan_run_ref)
            payload.setdefault("request", get_request_context_payload())
            return make_json_response(payload)
        except Exception as exc:
            return make_exception_response(
                exc,
                message="library scan-run finish route failed",
            )

    @blueprint_obj.get(SCAN_RUN_ISSUES_ROUTE)
    def library_scan_run_issues(scan_run_ref: str) -> Any:
        """GET /api/v1/vplib/library/scan-runs/<scan_run_ref>/issues"""
        try:
            query = get_query_args()
            payload = call_published_service(
                lambda service: service.list_scan_issues(
                    scan_run_ref,
                    severity=query.get("severity"),
                    limit=safe_int(query.get("limit"), default=250, minimum=1, maximum=5000) or 250,
                ),
                route="scan_run_issues",
            )
            payload.setdefault("scan_run_ref", scan_run_ref)
            payload.setdefault("request", get_request_context_payload())
            return make_json_response(payload)
        except Exception as exc:
            return make_exception_response(
                exc,
                message="library scan-run issues route failed",
            )

    @blueprint_obj.post(SCAN_RUN_ISSUES_ROUTE)
    def library_scan_run_issue_add(scan_run_ref: str) -> Any:
        """POST /api/v1/vplib/library/scan-runs/<scan_run_ref>/issues"""
        try:
            payload_body = get_request_payload()
            payload = call_published_service(
                lambda service: service.record_scan_issue(
                    scan_run_ref,
                    payload_body,
                    commit=safe_bool(payload_body.get("commit"), default=True),
                ),
                route="scan_run_issue_add",
            )
            payload.setdefault("scan_run_ref", scan_run_ref)
            payload.setdefault("request", get_request_context_payload())
            return make_json_response(payload)
        except Exception as exc:
            return make_exception_response(
                exc,
                message="library scan-run issue add route failed",
            )

    # -----------------------------------------------------------------------
    # Inventory slots
    # -----------------------------------------------------------------------

    @blueprint_obj.get(INVENTORY_SLOTS_ROUTE)
    def library_inventory_slots() -> Any:
        """GET /api/v1/vplib/library/inventory/slots"""
        try:
            query = get_query_args()
            payload = call_published_service(
                lambda service: service.list_inventory_slots(
                    user_id=query.get("user_id") or 1,
                ),
                route="inventory_slots",
            )
            payload.setdefault("request", get_request_context_payload())
            return make_json_response(payload)
        except Exception as exc:
            return make_exception_response(
                exc,
                message="library inventory slots route failed",
            )

    @blueprint_obj.post(INVENTORY_SLOT_ROUTE)
    def library_inventory_slot_set(slot_index: int) -> Any:
        """POST /api/v1/vplib/library/inventory/slots/<slot_index>"""
        try:
            payload_body = get_request_payload()
            payload = call_published_service(
                lambda service: service.set_inventory_slot(
                    user_id=payload_body.get("user_id") or 1,
                    slot_index=slot_index,
                    item_ref=first_non_empty(
                        payload_body.get("item_ref"),
                        payload_body.get("item_id"),
                        payload_body.get("vplib_uid"),
                        payload_body.get("family_id"),
                    ),
                    variant_ref=first_non_empty(
                        payload_body.get("variant_ref"),
                        payload_body.get("variant_id"),
                        payload_body.get("variant_uid"),
                    ),
                    payload=payload_body,
                    commit=safe_bool(payload_body.get("commit"), default=True),
                ),
                route="inventory_slot_set",
            )
            payload.setdefault("slot_index", slot_index)
            payload.setdefault("request", get_request_context_payload())
            return make_json_response(payload)
        except Exception as exc:
            return make_exception_response(
                exc,
                message="library inventory slot set route failed",
            )

    @blueprint_obj.delete(INVENTORY_SLOT_ROUTE)
    def library_inventory_slot_clear(slot_index: int) -> Any:
        """DELETE /api/v1/vplib/library/inventory/slots/<slot_index>"""
        try:
            payload_body = get_request_payload()
            payload = call_published_service(
                lambda service: service.clear_inventory_slot(
                    user_id=payload_body.get("user_id") or get_query_args().get("user_id") or 1,
                    slot_index=slot_index,
                    commit=safe_bool(payload_body.get("commit"), default=True),
                ),
                route="inventory_slot_clear",
            )
            payload.setdefault("slot_index", slot_index)
            payload.setdefault("request", get_request_context_payload())
            return make_json_response(payload)
        except Exception as exc:
            return make_exception_response(
                exc,
                message="library inventory slot clear route failed",
            )

    # -----------------------------------------------------------------------
    # Cache clear
    # -----------------------------------------------------------------------

    @blueprint_obj.post(CACHE_CLEAR_ROUTE)
    def library_cache_clear() -> Any:
        """POST /api/v1/vplib/library/cache/clear"""
        try:
            body = get_request_payload()
            legacy_payload = call_legacy_route_service(
                "handle_library_cache_clear_request",
                route="cache_clear_legacy",
                query_args=get_query_args(),
                payload=body,
            )

            published_payload = call_published_service(
                lambda service: service.get_health(),
                route="cache_clear_published_health",
            )

            db_sync_payload = call_db_sync_service(
                lambda service: service.health(
                    check_repository=False,
                    check_scan_service=False,
                ),
                route="cache_clear_db_sync_health",
            )

            cleared = clear_library_routes_caches()

            payload = {
                "ok": True,
                "status": "ok",
                "route": "cache_clear",
                "cleared": cleared.get("cleared", []),
                "legacy": legacy_payload,
                "published": published_payload,
                "db_sync": db_sync_payload,
                "request": get_request_context_payload(),
            }

            return make_json_response(payload)

        except Exception as exc:
            return make_exception_response(
                exc,
                message="library cache clear route failed",
            )

    return blueprint_obj


# Blueprint wird beim Import erzeugt, damit `src/routes/__init__.py` ihn wie
# bestehende Blueprints registrieren kann.
try:
    library_bp = create_library_blueprint()
except Exception as blueprint_exc:  # pragma: no cover - defensive fallback
    library_bp = None
    _BLUEPRINT_CREATE_ERROR: BaseException | None = blueprint_exc
else:
    _BLUEPRINT_CREATE_ERROR = None

bp = library_bp
blueprint = library_bp


# ---------------------------------------------------------------------------
# Registration helpers
# ---------------------------------------------------------------------------

def get_library_blueprint() -> Any:
    """Gibt den Library Blueprint zurück oder wirft eine klare Exception."""
    if library_bp is None:
        raise RuntimeError(
            f"library blueprint is unavailable: {exception_to_dict(_BLUEPRINT_CREATE_ERROR)}"
        )

    return library_bp


def is_library_blueprint_available() -> bool:
    """Boolescher Blueprint-Status."""
    return library_bp is not None


def get_library_routes_health() -> dict[str, Any]:
    """
    Health-Status dieser Route-Datei.

    Führt keinen Scan aus.
    """
    route_metadata = make_route_metadata()

    errors: list[str] = []
    warnings: list[str] = []

    if _FLASK_IMPORT_ERROR is not None:
        errors.append("flask import failed")

    if _SETTINGS_IMPORT_ERROR is not None:
        warnings.append("library settings import failed; fallback route prefix is active")

    if _BLUEPRINT_CREATE_ERROR is not None:
        errors.append("library blueprint creation failed")

    legacy_status = get_legacy_route_service_status()
    published_status = get_published_service_status()
    db_sync_status = get_db_sync_service_status()

    if not legacy_status.get("ok"):
        warnings.append("legacy file route service unavailable")

    if not published_status.get("ok"):
        errors.append("creative library service unavailable")

    if not db_sync_status.get("ok"):
        errors.append("library db sync service unavailable")

    healthy = len(errors) == 0 and library_bp is not None

    return {
        "ok": healthy,
        "healthy": healthy,
        "component": LIBRARY_ROUTES_COMPONENT,
        "version": LIBRARY_ROUTES_VERSION,
        "generated_at": utc_now_iso(),
        "blueprint": {
            "available": library_bp is not None,
            "name": getattr(library_bp, "name", None) if library_bp is not None else None,
            "url_prefix": getattr(library_bp, "url_prefix", None) if library_bp is not None else None,
            "error": exception_to_dict(_BLUEPRINT_CREATE_ERROR),
        },
        "route_metadata": route_metadata,
        "legacy_file_backend": legacy_status,
        "published_db_backend": published_status,
        "db_sync_backend": db_sync_status,
        "scan_get_writes_database": False,
        "sync_post_writes_database": True,
        "warnings": warnings,
        "errors": errors,
    }


def assert_library_routes_ready() -> None:
    """Wirft RuntimeError, wenn die Library-Routen nicht bereit sind."""
    health = get_library_routes_health()

    if health.get("healthy"):
        return

    raise RuntimeError(
        f"library routes are not ready: errors={health.get('errors')}"
    )


def clear_library_routes_caches() -> dict[str, Any]:
    """Leert lokale Route-Import-Caches."""
    cleared: list[Any] = []

    for cached_func in (
        _load_legacy_route_service_module,
        _load_creative_library_service_module,
        _load_db_sync_service_module,
    ):
        try:
            cached_func.cache_clear()
            cleared.append(getattr(cached_func, "__name__", str(cached_func)))
        except Exception:
            pass

    try:
        module = _load_db_sync_service_module()
        clear_func = getattr(module, "clear_library_db_sync_service_caches", None)
        if callable(clear_func):
            result = clear_func()
            cleared.append({"library_db_sync_service": result})
    except Exception:
        pass

    return {
        "ok": True,
        "cleared": cleared,
    }


# Compatibility aliases for route registries.
get_library_route_list = get_route_map_payload
get_library_route_map = get_route_map_payload


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

__all__: Final[tuple[str, ...]] = (
    "LIBRARY_ROUTES_VERSION",
    "LIBRARY_ROUTES_COMPONENT",
    "DEFAULT_BLUEPRINT_NAME",
    "HEALTH_ROUTE",
    "ROUTES_ROUTE",
    "SELFTEST_ROUTE",
    "SCAN_ROUTE",
    "SYNC_ROUTE",
    "BLOCKS_ROUTE",
    "TREE_ROUTE",
    "CACHE_CLEAR_ROUTE",
    "BLOCK_VARIANTS_ROUTE",
    "BLOCK_DETAIL_ROUTE",
    "PUBLISHED_ROUTE",
    "ITEMS_ROUTE",
    "ITEM_DETAIL_ROUTE",
    "ITEM_VARIANTS_ROUTE",
    "ITEM_REVISIONS_ROUTE",
    "ITEM_ASSETS_ROUTE",
    "ITEM_DOCUMENTS_ROUTE",
    "VPLIB_ITEM_ROUTE",
    "SCAN_RUNS_ROUTE",
    "SCAN_RUN_FINISH_ROUTE",
    "SCAN_RUN_ISSUES_ROUTE",
    "INVENTORY_SLOTS_ROUTE",
    "INVENTORY_SLOT_ROUTE",
    "GENERAL_QUERY_KEYS",
    "TAXONOMY_QUERY_KEYS",
    "SYNC_QUERY_KEYS",
    "SUPPORTED_QUERY_KEYS",
    "library_bp",
    "bp",
    "blueprint",
    "utc_now_iso",
    "exception_to_dict",
    "json_safe",
    "safe_str",
    "safe_bool",
    "safe_int",
    "safe_mapping",
    "normalize_query_args",
    "get_query_args",
    "get_json_payload",
    "get_form_payload",
    "get_request_payload",
    "get_request_context_payload",
    "response_http_status",
    "strip_internal_http_status",
    "make_json_response",
    "make_exception_response",
    "service_result_to_route_payload",
    "should_use_legacy_file_backend",
    "call_legacy_route_service",
    "call_published_service",
    "call_db_sync_service",
    "make_route_metadata",
    "get_legacy_route_service_status",
    "get_published_service_status",
    "get_db_sync_service_status",
    "get_route_map_payload",
    "get_library_route_list",
    "get_library_route_map",
    "published_library_payload_from_query",
    "block_list_payload_from_db",
    "item_detail_payload_from_db",
    "item_children_payload",
    "tree_payload_from_db",
    "build_taxonomy_tree_from_items",
    "sync_payload_from_request",
    "first_non_empty",
    "create_library_blueprint",
    "get_library_blueprint",
    "is_library_blueprint_available",
    "get_library_routes_health",
    "assert_library_routes_ready",
    "clear_library_routes_caches",
)