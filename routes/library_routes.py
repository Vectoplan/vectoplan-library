# services/vectoplan-library/src/routes/library_routes.py
"""
Flask-Routen für die VECTOPLAN Creative-Library-API.

Diese Datei ist der HTTP-Adapter für die dateibasierte Library-Schicht.

Sie ist bewusst dünn gehalten:

    HTTP / Flask
      -> routes/library_routes.py
      -> services/library_route_service.py
      -> library.services.*
      -> scanner / validation / read_models / taxonomy

Diese Datei enthält keine Business-Logik.

Zielrouten:

    GET  /api/v1/vplib/library/health
    GET  /api/v1/vplib/library/scan
    GET  /api/v1/vplib/library/blocks
    GET  /api/v1/vplib/library/blocks/<block_id>
    GET  /api/v1/vplib/library/blocks/<block_id>/variants
    GET  /api/v1/vplib/library/tree

Optionale Dev-/Debug-Route:

    POST /api/v1/vplib/library/cache/clear

Phase 1:

- Source-Ordner lesen
- alle gültigen Blöcke listen
- einzelnen Block per ID lesen
- Varianten per ID lesen
- Tree anzeigen
- Backend-Taxonomie für Navigation und Labels nutzen
- keine Datenbank
- kein Persistieren
- kein Kopieren nach `creative_library`

Query-Parameter, die an den Route-Service weitergereicht werden:

    Allgemein:
        force_refresh=true|false
        use_cache=true|false
        include_invalid=true|false
        enabled_only=true|false
        include_raw_pipeline=true|false

    Taxonomie:
        domain=<domain>
        category=<category>
        subcategory=<subcategory>
        object_kind=<object_kind>
        q=<search text>
        include_empty_taxonomy_nodes=true|false
        include_inactive_taxonomy_nodes=true|false
        include_taxonomy_payload=true|false
        force_taxonomy_reload=true|false

Wichtig:

- Taxonomie-Fachlogik liegt nicht in dieser Datei.
- Route-Service und Scan-Service interpretieren die Query-Parameter.
- Diese Datei liest Request-Daten nur defensiv und serialisiert Antworten.
"""

from __future__ import annotations

import traceback
from dataclasses import asdict, is_dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Final, Mapping


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
# Optional route-service/settings imports
# ---------------------------------------------------------------------------

_ROUTE_SERVICE_IMPORT_ERROR: BaseException | None = None
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


try:
    from services.library_route_service import (
        LIBRARY_ROUTE_SERVICE_COMPONENT,
        LIBRARY_ROUTE_SERVICE_VERSION,
        ERROR_HTTP_STATUS,
        DEFAULT_RESPONSE_HTTP_STATUS,
        get_block_detail_payload,
        get_block_variants_payload,
        get_blocks_payload,
        get_health_payload,
        get_scan_payload,
        get_tree_payload,
        handle_library_cache_clear_request,
        response_http_status,
    )
except Exception as import_exc:  # pragma: no cover - defensive fallback
    _ROUTE_SERVICE_IMPORT_ERROR = import_exc

    LIBRARY_ROUTE_SERVICE_COMPONENT = "library-route-service"
    LIBRARY_ROUTE_SERVICE_VERSION = "0.1.0"
    ERROR_HTTP_STATUS = 500
    DEFAULT_RESPONSE_HTTP_STATUS = 200

    def response_http_status(payload: Mapping[str, Any]) -> int:
        status = str(payload.get("status", "ok")).lower()

        if status == "not_found":
            return 404

        if status in {"bad_request", "invalid"}:
            return 400

        if status == "unauthorized":
            return 401

        if status == "forbidden":
            return 403

        if status == "conflict":
            return 409

        if status in {"error", "unhealthy"}:
            return 500

        if status == "unavailable":
            return 503

        return 200

    def _unavailable_payload(route_name: str) -> dict[str, Any]:
        return {
            "ok": False,
            "status": "error",
            "route": route_name,
            "message": "library route service is unavailable",
            "errors": ["library route service is unavailable"],
            "error": exception_to_dict(_ROUTE_SERVICE_IMPORT_ERROR),
            "generated_at": utc_now_iso(),
        }

    def get_health_payload(*args: Any, **kwargs: Any) -> dict[str, Any]:
        return _unavailable_payload("health")

    def get_scan_payload(*args: Any, **kwargs: Any) -> dict[str, Any]:
        return _unavailable_payload("scan")

    def get_blocks_payload(*args: Any, **kwargs: Any) -> dict[str, Any]:
        return _unavailable_payload("blocks")

    def get_block_detail_payload(block_id: Any, *args: Any, **kwargs: Any) -> dict[str, Any]:
        payload = _unavailable_payload("block_detail")
        payload["block_id"] = str(block_id)
        return payload

    def get_block_variants_payload(block_id: Any, *args: Any, **kwargs: Any) -> dict[str, Any]:
        payload = _unavailable_payload("block_variants")
        payload["block_id"] = str(block_id)
        return payload

    def get_tree_payload(*args: Any, **kwargs: Any) -> dict[str, Any]:
        return _unavailable_payload("tree")

    def handle_library_cache_clear_request(*args: Any, **kwargs: Any) -> dict[str, Any]:
        return _unavailable_payload("cache_clear")


# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

LIBRARY_ROUTES_VERSION: Final[str] = "0.2.0"
LIBRARY_ROUTES_COMPONENT: Final[str] = "library-routes"

DEFAULT_BLUEPRINT_NAME: Final[str] = "library_bp"

HEALTH_ROUTE: Final[str] = "/health"
SCAN_ROUTE: Final[str] = "/scan"
BLOCKS_ROUTE: Final[str] = "/blocks"
TREE_ROUTE: Final[str] = "/tree"
CACHE_CLEAR_ROUTE: Final[str] = "/cache/clear"

# Wichtig:
# Variantenroute vor Detailroute registrieren, damit `/variants` nicht als Teil
# eines path-block_id missverstanden wird.
BLOCK_VARIANTS_ROUTE: Final[str] = "/blocks/<path:block_id>/variants"
BLOCK_DETAIL_ROUTE: Final[str] = "/blocks/<path:block_id>"

GENERAL_QUERY_KEYS: Final[tuple[str, ...]] = (
    "force_refresh",
    "use_cache",
    "include_invalid",
    "enabled_only",
    "include_raw_pipeline",
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

SUPPORTED_QUERY_KEYS: Final[tuple[str, ...]] = (
    *GENERAL_QUERY_KEYS,
    *TAXONOMY_QUERY_KEYS,
)


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

        text = str(value).strip()
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

    if text in {"1", "true", "yes", "y", "ja", "on", "enabled"}:
        return True

    if text in {"0", "false", "no", "n", "nein", "off", "disabled"}:
        return False

    return default


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
            return dict(value)
        except Exception:
            return {}

    to_dict = getattr(value, "to_dict", None)

    if callable(to_dict):
        try:
            raw = to_dict(flat=False)
            if isinstance(raw, Mapping):
                result: dict[str, Any] = {}
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

    Diese Funktion interpretiert keine Fachlogik. Sie macht nur Bool-ähnliche
    technische Flags stabiler und lässt Filterwerte unverändert.
    """

    source = dict(query_args or {})
    result: dict[str, Any] = {}

    bool_keys = {
        "force_refresh",
        "use_cache",
        "include_invalid",
        "enabled_only",
        "include_raw_pipeline",
        "include_empty_taxonomy_nodes",
        "include_inactive_taxonomy_nodes",
        "include_taxonomy_payload",
        "force_taxonomy_reload",
    }

    for key, value in source.items():
        key_text = safe_str(key, default="")
        if not key_text:
            continue

        if key_text in bool_keys:
            result[key_text] = safe_bool(value, default=False)
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
    """
    Liest JSON-Body defensiv.

    Für GET-Routen ist das normalerweise leer. Die Funktion ist trotzdem
    vorhanden, damit Debug-/POST-Routen dieselbe Route-Service-Schnittstelle
    verwenden können.
    """

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


def strip_internal_http_status(payload: Mapping[str, Any]) -> tuple[dict[str, Any], int]:
    """
    Entfernt `_http_status` aus Payload und gibt HTTP-Status separat zurück.
    """

    data = dict(payload)
    explicit_status = data.pop("_http_status", None)

    try:
        status_code = int(explicit_status) if explicit_status is not None else response_http_status(data)
    except Exception:
        status_code = DEFAULT_RESPONSE_HTTP_STATUS

    return data, status_code


def make_json_response(payload: Mapping[str, Any] | None, *, fallback_status: int = DEFAULT_RESPONSE_HTTP_STATUS) -> Any:
    """
    Baut eine Flask-JSON-Response.

    Diese Funktion ist die einzige Stelle, an der jsonify verwendet wird.
    """

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
            "scan": f"{route_prefix}{SCAN_ROUTE}",
            "blocks": f"{route_prefix}{BLOCKS_ROUTE}",
            "block_detail": f"{route_prefix}/blocks/<block_id>",
            "block_variants": f"{route_prefix}/blocks/<block_id>/variants",
            "tree": f"{route_prefix}{TREE_ROUTE}",
            "cache_clear": f"{route_prefix}{CACHE_CLEAR_ROUTE}",
        },
        "supported_query": {
            "general": list(GENERAL_QUERY_KEYS),
            "taxonomy": list(TAXONOMY_QUERY_KEYS),
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
            "route_service": {
                "ok": _ROUTE_SERVICE_IMPORT_ERROR is None,
                "error": exception_to_dict(_ROUTE_SERVICE_IMPORT_ERROR),
            },
        },
    }


# ---------------------------------------------------------------------------
# Blueprint creation
# ---------------------------------------------------------------------------

def create_library_blueprint() -> Any:
    """
    Erzeugt den Flask Blueprint für die Library-Routen.

    Falls Flask nicht importierbar ist, wird eine RuntimeError geworfen. Das ist
    korrekt, weil diese Datei als Flask-Route-Datei ohne Flask nicht sinnvoll
    registrierbar ist.
    """

    if Blueprint is None:
        raise RuntimeError(
            f"Flask Blueprint is unavailable: {exception_to_dict(_FLASK_IMPORT_ERROR)}"
        )

    route_prefix = get_library_route_prefix_safe()

    blueprint = Blueprint(
        "library_bp",
        __name__,
        url_prefix=route_prefix,
    )

    # -----------------------------------------------------------------------
    # Health
    # -----------------------------------------------------------------------

    @blueprint.get(HEALTH_ROUTE)
    def library_health() -> Any:
        """
        GET /api/v1/vplib/library/health

        Optional:
            ?include_taxonomy_payload=true
            ?force_taxonomy_reload=true
        """

        try:
            payload = get_health_payload(
                query_args=get_query_args(),
                payload=get_json_payload(),
            )
            payload.setdefault("route", "health")
            payload.setdefault("route_metadata", make_route_metadata())
            payload.setdefault("request", get_request_context_payload())

            return make_json_response(payload)

        except Exception as exc:
            return make_exception_response(
                exc,
                message="library health route failed",
            )

    # -----------------------------------------------------------------------
    # Scan
    # -----------------------------------------------------------------------

    @blueprint.get(SCAN_ROUTE)
    def library_scan() -> Any:
        """
        GET /api/v1/vplib/library/scan

        Führt dateibasierten Scan aus und gibt Kandidaten, gelesene Items und
        Statusinformationen zurück.

        Relevante Query-Parameter:
            force_refresh
            use_cache
            include_invalid
            include_raw_pipeline
            include_taxonomy_payload
            force_taxonomy_reload
        """

        try:
            payload = get_scan_payload(
                query_args=get_query_args(),
                payload=get_json_payload(),
            )
            payload.setdefault("route", "scan")
            payload.setdefault("request", get_request_context_payload())

            return make_json_response(payload)

        except Exception as exc:
            return make_exception_response(
                exc,
                message="library scan route failed",
            )

    # -----------------------------------------------------------------------
    # Blocks list
    # -----------------------------------------------------------------------

    @blueprint.get(BLOCKS_ROUTE)
    def library_blocks() -> Any:
        """
        GET /api/v1/vplib/library/blocks

        Gibt alle gültigen Creative-Library-Blöcke/-Objekte zurück.

        Relevante Query-Parameter:
            domain
            category
            subcategory
            object_kind
            q
            force_refresh
            use_cache
            include_invalid
            force_taxonomy_reload
        """

        try:
            payload = get_blocks_payload(
                query_args=get_query_args(),
                payload=get_json_payload(),
            )
            payload.setdefault("route", "blocks")
            payload.setdefault("request", get_request_context_payload())

            return make_json_response(payload)

        except Exception as exc:
            return make_exception_response(
                exc,
                message="library blocks route failed",
            )

    # -----------------------------------------------------------------------
    # Tree
    # -----------------------------------------------------------------------

    @blueprint.get(TREE_ROUTE)
    def library_tree() -> Any:
        """
        GET /api/v1/vplib/library/tree

        Gibt Domain/Kategorie/Subkategorie-Baum zurück.

        Relevante Query-Parameter:
            include_empty_taxonomy_nodes
            include_inactive_taxonomy_nodes
            force_refresh
            use_cache
            force_taxonomy_reload
        """

        try:
            payload = get_tree_payload(
                query_args=get_query_args(),
                payload=get_json_payload(),
            )
            payload.setdefault("route", "tree")
            payload.setdefault("request", get_request_context_payload())

            return make_json_response(payload)

        except Exception as exc:
            return make_exception_response(
                exc,
                message="library tree route failed",
            )

    # -----------------------------------------------------------------------
    # Block variants
    # -----------------------------------------------------------------------

    @blueprint.get(BLOCK_VARIANTS_ROUTE)
    def library_block_variants(block_id: str) -> Any:
        """
        GET /api/v1/vplib/library/blocks/<block_id>/variants

        Gibt Varianten eines Blocks/Objekts zurück.
        """

        try:
            payload = get_block_variants_payload(
                block_id,
                query_args=get_query_args(),
                payload=get_json_payload(),
            )
            payload.setdefault("route", "block_variants")
            payload.setdefault("block_id", block_id)
            payload.setdefault("request", get_request_context_payload())

            return make_json_response(payload)

        except Exception as exc:
            return make_exception_response(
                exc,
                message="library block variants route failed",
            )

    # -----------------------------------------------------------------------
    # Block detail
    # -----------------------------------------------------------------------

    @blueprint.get(BLOCK_DETAIL_ROUTE)
    def library_block_detail(block_id: str) -> Any:
        """
        GET /api/v1/vplib/library/blocks/<block_id>

        Gibt Details eines Blocks/Objekts per stabiler ID zurück.
        """

        try:
            payload = get_block_detail_payload(
                block_id,
                query_args=get_query_args(),
                payload=get_json_payload(),
            )
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
    # Optional cache clear
    # -----------------------------------------------------------------------

    @blueprint.post(CACHE_CLEAR_ROUTE)
    def library_cache_clear() -> Any:
        """
        POST /api/v1/vplib/library/cache/clear

        Leert den optionalen in-memory Scan-Cache und die lokalen
        Taxonomie-Read-Model-Caches.
        """

        try:
            payload = handle_library_cache_clear_request(
                query_args=get_query_args(),
                payload=get_json_payload(),
            )
            payload.setdefault("route", "cache_clear")
            payload.setdefault("request", get_request_context_payload())

            return make_json_response(payload)

        except Exception as exc:
            return make_exception_response(
                exc,
                message="library cache clear route failed",
            )

    return blueprint


# Blueprint wird beim Import erzeugt, damit `src/routes/__init__.py` ihn wie
# bestehende Blueprints registrieren kann.
try:
    library_bp = create_library_blueprint()
except Exception as blueprint_exc:  # pragma: no cover - defensive fallback
    library_bp = None
    _BLUEPRINT_CREATE_ERROR: BaseException | None = blueprint_exc
else:
    _BLUEPRINT_CREATE_ERROR = None


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

    if _ROUTE_SERVICE_IMPORT_ERROR is not None:
        errors.append("library route service import failed")

    if _SETTINGS_IMPORT_ERROR is not None:
        warnings.append("library settings import failed; fallback route prefix is active")

    if _BLUEPRINT_CREATE_ERROR is not None:
        errors.append("library blueprint creation failed")

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


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

__all__: Final[tuple[str, ...]] = (
    "LIBRARY_ROUTES_VERSION",
    "LIBRARY_ROUTES_COMPONENT",
    "DEFAULT_BLUEPRINT_NAME",
    "HEALTH_ROUTE",
    "SCAN_ROUTE",
    "BLOCKS_ROUTE",
    "TREE_ROUTE",
    "CACHE_CLEAR_ROUTE",
    "BLOCK_VARIANTS_ROUTE",
    "BLOCK_DETAIL_ROUTE",
    "GENERAL_QUERY_KEYS",
    "TAXONOMY_QUERY_KEYS",
    "SUPPORTED_QUERY_KEYS",
    "library_bp",
    "utc_now_iso",
    "exception_to_dict",
    "json_safe",
    "safe_str",
    "safe_bool",
    "safe_mapping",
    "normalize_query_args",
    "get_query_args",
    "get_json_payload",
    "get_request_context_payload",
    "strip_internal_http_status",
    "make_json_response",
    "make_exception_response",
    "make_route_metadata",
    "create_library_blueprint",
    "get_library_blueprint",
    "is_library_blueprint_available",
    "get_library_routes_health",
    "assert_library_routes_ready",
)