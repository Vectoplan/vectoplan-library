# services/vectoplan-library/src/services/library_route_service.py
"""
Route-Service für die VECTOPLAN Creative-Library-API.

Diese Datei ist der HTTP-nahe Adapter zwischen:

    routes/library_routes.py
      -> services/library_route_service.py
      -> library.services.library_scan_service
      -> library.services.library_block_service
      -> scanner / validation / read_models / taxonomy

Diese Datei muss die Symbole exportieren, die `routes.library_routes.py`
direkt oder dynamisch verwendet. Wenn eines davon fehlt, fällt
library_routes.py in den kontrollierten Fallback.

Wichtige Grenzen:

- keine Flask-Abhängigkeit in dieser Datei
- keine Datenbanklogik
- kein Schreiben
- keine UI-Logik
- keine Scans beim Import
- nur Request-Normalisierung, Service-Delegation und Response-Envelopes
- GET /scan bleibt read-only
- POST /sync liegt nicht hier, sondern in routes/library_routes.py über
  CreativeLibraryService

Version 1.0.0:

- Query-Parameter `domain/category/subcategory/object_kind/q` werden vollständig
  geparst und bis in Scan-/Block-Service weitergereicht.
- Taxonomie-Flags werden vollständig geparst.
- Scan-, Blocks- und Tree-Routen bevorzugen `library_scan_service`.
- Detail- und Variantenrouten bleiben über `library_block_service` angebunden.
- Cache-Clear leert Scan-Cache und Taxonomie-nahe Read-Model-Caches, sofern
  verfügbar.
- Health enthält Taxonomie-, Scan-Service-, Block-Service- und Basis-Subhealth.
- Import großer Services erfolgt lazy, nicht beim Modulimport.
"""

from __future__ import annotations

import importlib
import inspect
import os
import traceback
from collections.abc import Iterable, Mapping
from dataclasses import asdict, dataclass, field, is_dataclass
from datetime import datetime, timezone
from functools import lru_cache
from pathlib import Path
from types import ModuleType
from typing import Any, Callable, Final


# ---------------------------------------------------------------------------
# Constants required by routes.library_routes
# ---------------------------------------------------------------------------

LIBRARY_ROUTE_SERVICE_VERSION: Final[str] = "1.0.0"
LIBRARY_ROUTE_SERVICE_COMPONENT: Final[str] = "library-route-service"

DEFAULT_LIBRARY_ROUTE_PREFIX: Final[str] = "/api/v1/vplib/library"

DEFAULT_RESPONSE_HTTP_STATUS: Final[int] = 200
BAD_REQUEST_HTTP_STATUS: Final[int] = 400
NOT_FOUND_HTTP_STATUS: Final[int] = 404
CONFLICT_HTTP_STATUS: Final[int] = 409
ERROR_HTTP_STATUS: Final[int] = 500
UNAVAILABLE_HTTP_STATUS: Final[int] = 503

DEFAULT_LIMIT: Final[int] = 500
MAX_LIMIT: Final[int] = 5000

ROUTE_SERVICE_STATUS_VALUES: Final[tuple[str, ...]] = (
    "unknown",
    "ok",
    "healthy",
    "unhealthy",
    "unavailable",
    "not_found",
    "bad_request",
    "empty",
    "partial",
    "invalid",
    "invalid_request",
    "conflict",
    "error",
    "failed",
)

BOOLEAN_PARAM_NAMES: Final[tuple[str, ...]] = (
    "force_refresh",
    "forceRefresh",
    "refresh",
    "no_cache",
    "noCache",
    "use_cache",
    "useCache",
    "cache",
    "include_invalid",
    "includeInvalid",
    "invalid",
    "enabled_only",
    "enabledOnly",
    "include_raw_pipeline",
    "includeRawPipeline",
    "raw_pipeline",
    "rawPipeline",
    "debug",
    "include_raw_documents",
    "includeRawDocuments",
    "raw_documents",
    "rawDocuments",
    "include_profiles",
    "includeProfiles",
    "profiles",
    "include_metadata",
    "includeMetadata",
    "metadata",
    "strict_errors",
    "strictErrors",
    "strict",
    "validate_taxonomy",
    "validateTaxonomy",
    "require_taxonomy",
    "requireTaxonomy",
    "use_taxonomy_labels",
    "useTaxonomyLabels",
    "include_empty_taxonomy_nodes",
    "includeEmptyTaxonomyNodes",
    "empty_taxonomy",
    "emptyTaxonomy",
    "include_inactive_taxonomy_nodes",
    "includeInactiveTaxonomyNodes",
    "include_taxonomy_payload",
    "includeTaxonomyPayload",
    "force_taxonomy_reload",
    "forceTaxonomyReload",
    "include_subhealth",
    "includeSubhealth",
    "subhealth",
    "deep",
    "include_traceback",
    "includeTraceback",
    "traceback",
    "refresh_settings",
    "refreshSettings",
)

INTEGER_PARAM_NAMES: Final[tuple[str, ...]] = (
    "limit",
    "offset",
)

FILTER_PARAM_NAMES: Final[tuple[str, ...]] = (
    "domain",
    "category",
    "subcategory",
    "sub_category",
    "subCategory",
    "object_kind",
    "objectKind",
    "kind",
    "q",
    "query",
    "search",
)

SOURCE_ROOT_ENV_KEYS: Final[tuple[str, ...]] = (
    "VECTOPLAN_LIBRARY_SOURCE_ROOT",
    "VPLIB_CREATE_SOURCE_ROOT",
    "LIBRARY_SOURCE_ROOT",
)

ROUTE_PREFIX_ENV_KEYS: Final[tuple[str, ...]] = (
    "LIBRARY_ROUTE_PREFIX",
    "VECTOPLAN_LIBRARY_ROUTE_PREFIX",
)


# ---------------------------------------------------------------------------
# Generic helpers
# ---------------------------------------------------------------------------

def utc_now_iso() -> str:
    """Liefert eine UTC-Zeit im ISO-Format."""
    try:
        return datetime.now(timezone.utc).isoformat()
    except Exception:
        return datetime.utcnow().replace(tzinfo=timezone.utc).isoformat()


def exception_to_dict(
    exc: BaseException | None,
    *,
    include_traceback: bool = False,
) -> dict[str, Any] | None:
    """Serialisiert Exceptions JSON-kompatibel."""
    if exc is None:
        return None

    try:
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

    except Exception as serialization_exc:
        return {
            "type": "ExceptionSerializationError",
            "message": str(serialization_exc),
            "original_type": str(type(exc)),
        }


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
            return {str(key): json_safe(item) for key, item in value.items()}

        if isinstance(value, (list, tuple, set)):
            return [json_safe(item) for item in value]

        to_dict = getattr(value, "to_dict", None)
        if callable(to_dict):
            try:
                return json_safe(to_dict())
            except TypeError:
                return json_safe(to_dict(flat=True))

        to_summary_dict = getattr(value, "to_summary_dict", None)
        if callable(to_summary_dict):
            return json_safe(to_summary_dict())

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

        if isinstance(value, bytes):
            text = value.decode("utf-8", errors="replace").strip()
        else:
            text = str(value).replace("\x00", "").strip()

        return text if text else default

    except Exception:
        return default


def safe_int(
    value: Any,
    *,
    default: int = 0,
    minimum: int | None = None,
    maximum: int | None = None,
) -> int:
    """Robuste Integer-Konvertierung mit optionaler Unter- und Obergrenze."""
    try:
        if value is None:
            number = int(default)
        elif isinstance(value, bool):
            number = int(value)
        elif isinstance(value, int):
            number = value
        elif isinstance(value, float):
            number = int(value)
        else:
            text = str(value).strip()
            if not text:
                number = int(default)
            else:
                try:
                    number = int(text)
                except Exception:
                    number = int(float(text))
    except Exception:
        try:
            number = int(default)
        except Exception:
            number = 0

    try:
        min_value = int(minimum) if minimum is not None else None
        max_value = int(maximum) if maximum is not None else None

        if min_value is not None and max_value is not None and min_value > max_value:
            min_value, max_value = max_value, min_value

        if min_value is not None:
            number = max(min_value, number)

        if max_value is not None:
            number = min(max_value, number)

        return int(number)

    except Exception:
        try:
            return int(default)
        except Exception:
            return 0


def parse_bool(value: Any, *, default: bool = False) -> bool:
    """Robuste Bool-Konvertierung für Query-/Payload-Werte."""
    try:
        if isinstance(value, bool):
            return value

        if value is None:
            return default

        if isinstance(value, int) and value in {0, 1}:
            return bool(value)

        text = safe_str(value, default="").lower()

        if text in {"1", "true", "yes", "y", "ja", "on", "enabled", "enable", "active"}:
            return True

        if text in {"0", "false", "no", "n", "nein", "off", "disabled", "disable", "inactive"}:
            return False

        return default

    except Exception:
        return default


def normalize_query_text(value: Any) -> str | None:
    """Normalisiert optionale Query-Texte."""
    if isinstance(value, (list, tuple)):
        value = value[0] if value else None

    text = safe_str(value, default="")
    return text or None


def normalize_slug_like(value: Any) -> str | None:
    """
    Normalisiert einfache Filterwerte.

    Bewusst nicht zu aggressiv, damit IDs wie `vp.hochbau...` erhalten bleiben.
    """
    text = normalize_query_text(value)
    if not text:
        return None

    cleaned = text.strip()
    return cleaned or None


def normalize_block_id(value: Any) -> str:
    """Normalisiert Block-IDs für API-Routen."""
    try:
        text = safe_str(value, default="").lower()
        text = text.replace("/", ".").replace("\\", ".").replace(" ", "_")
        text = "".join(ch for ch in text if ch.isalnum() or ch in "._:-")
        return text.strip("._:-")
    except Exception:
        return ""


def tuple_of_strings(value: Any) -> tuple[str, ...]:
    """Normalisiert beliebige Werte zu tuple[str, ...]."""
    try:
        if value is None:
            return ()

        if isinstance(value, str):
            text = value.strip()
            return (text,) if text else ()

        if isinstance(value, Mapping):
            result_from_mapping: list[str] = []
            for key, item in value.items():
                if key in {"message", "error", "detail"}:
                    text = safe_str(item, default="")
                    if text:
                        result_from_mapping.append(text)
            return tuple(result_from_mapping)

        if isinstance(value, Iterable):
            result: list[str] = []
            for item in value:
                text = safe_str(item, default="")
                if text:
                    result.append(text)
            return tuple(result)

        text = safe_str(value, default="")
        return (text,) if text else ()

    except Exception:
        return ()


def safe_mapping(value: Any) -> dict[str, Any]:
    """
    Normalisiert Mapping-artige Request-Objekte.

    Unterstützt:
    - dict
    - Flask/Werkzeug MultiDict via to_dict(flat=False/True)
    - Objekte mit to_dict()
    """
    try:
        if value is None:
            return {}

        if isinstance(value, Mapping):
            getlist = getattr(value, "getlist", None)
            if callable(getlist):
                result: dict[str, Any] = {}
                try:
                    keys = value.keys()
                except Exception:
                    keys = []
                for key in keys:
                    try:
                        values = getlist(key)
                    except Exception:
                        values = []
                    if len(values) == 1:
                        result[str(key)] = values[0]
                    elif len(values) > 1:
                        result[str(key)] = list(values)
                    else:
                        result[str(key)] = value.get(key)
                if result:
                    return result

            return dict(value)

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
                raw = to_dict()
                return dict(raw) if isinstance(raw, Mapping) else {}
            except Exception:
                return {}

        if is_dataclass(value):
            return asdict(value)

        return dict(value)

    except Exception:
        return {}


def normalize_param_mapping(value: Mapping[str, Any] | None) -> dict[str, Any]:
    """Normalisiert bekannte Bool-/Integer-Parameter, ohne Fachwerte zu verändern."""
    source = safe_mapping(value)
    result: dict[str, Any] = {}

    for key, item in source.items():
        key_text = safe_str(key, default="")
        if not key_text:
            continue

        if key_text in BOOLEAN_PARAM_NAMES:
            result[key_text] = parse_bool(item, default=False)
        elif key_text in INTEGER_PARAM_NAMES:
            default = DEFAULT_LIMIT if key_text == "limit" else 0
            result[key_text] = safe_int(item, default=default, minimum=0, maximum=MAX_LIMIT)
        else:
            result[key_text] = item

    return result


def merge_params(
    query_args: Mapping[str, Any] | None = None,
    payload: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    """
    Merged Query- und Payload-Parameter.

    Payload gewinnt bewusst gegen Query-Parameter.
    """
    merged: dict[str, Any] = {}

    try:
        merged.update(normalize_param_mapping(query_args))
        merged.update(normalize_param_mapping(payload))
    except Exception:
        return {}

    return merged


def get_param(
    params: Mapping[str, Any] | None,
    *names: str,
    default: Any = None,
) -> Any:
    """Liest einen Parameter unter mehreren möglichen Alias-Namen."""
    try:
        if not params:
            return default

        for name in names:
            if name in params:
                value = params.get(name)

                if isinstance(value, (list, tuple)):
                    return value[0] if value else default

                return value

        return default

    except Exception:
        return default


def parse_limit(value: Any, *, default: int = DEFAULT_LIMIT) -> int:
    """Parst Limit für Listenrouten."""
    return safe_int(value, default=default, minimum=1, maximum=MAX_LIMIT)


def parse_offset(value: Any, *, default: int = 0) -> int:
    """Parst Offset für Listenrouten."""
    return safe_int(value, default=default, minimum=0)


def response_http_status(payload: Mapping[str, Any]) -> int:
    """Leitet den HTTP-Status aus einem Payload-Status ab."""
    try:
        if bool(payload.get("ok", False)):
            return DEFAULT_RESPONSE_HTTP_STATUS

        status = safe_str(payload.get("status"), default="ok").lower()

        if status == "not_found":
            return NOT_FOUND_HTTP_STATUS

        if status in {"bad_request", "invalid", "invalid_request"}:
            return BAD_REQUEST_HTTP_STATUS

        if status == "conflict":
            return CONFLICT_HTTP_STATUS

        if status == "unavailable":
            return UNAVAILABLE_HTTP_STATUS

        if status in {"error", "unhealthy", "failed"}:
            return ERROR_HTTP_STATUS

        return DEFAULT_RESPONSE_HTTP_STATUS

    except Exception:
        return ERROR_HTTP_STATUS


def make_response_envelope(
    payload: Mapping[str, Any] | None,
    *,
    http_status: int | None = None,
) -> dict[str, Any]:
    """
    Ergänzt generierte Zeit und internen HTTP-Status.

    `_http_status` bleibt intern für `routes.library_routes.py`.
    """
    try:
        data = dict(payload or {})
    except Exception as exc:
        data = {
            "ok": False,
            "status": "error",
            "message": "could not build response envelope",
            "errors": [str(exc)],
            "error": exception_to_dict(exc),
        }

    data.setdefault("generated_at", utc_now_iso())
    data.setdefault("component", LIBRARY_ROUTE_SERVICE_COMPONENT)
    data.setdefault("route_service_version", LIBRARY_ROUTE_SERVICE_VERSION)
    data.setdefault("backend", "legacy_file")

    if http_status is not None:
        data["_http_status"] = safe_int(http_status, default=ERROR_HTTP_STATUS, minimum=100, maximum=599)
    elif "_http_status" in data:
        data["_http_status"] = safe_int(data.get("_http_status"), default=response_http_status(data), minimum=100, maximum=599)
    else:
        data["_http_status"] = response_http_status(data)

    return data


def unavailable_response(message: str, exc: BaseException | None = None) -> dict[str, Any]:
    """Standardantwort für nicht verfügbare optionale Backend-Abhängigkeiten."""
    return {
        "ok": False,
        "status": "unavailable",
        "message": message,
        "errors": [message],
        "error": exception_to_dict(exc),
        "generated_at": utc_now_iso(),
        "backend": "legacy_file",
    }


def apply_list_pagination(payload: Mapping[str, Any], *, limit: int, offset: int) -> dict[str, Any]:
    """
    Wendet Pagination auf Payloads mit `items` an, falls der Backend-Service das
    nicht bereits selbst getan hat.
    """
    data = dict(payload)

    items = data.get("items")
    if not isinstance(items, list):
        return data

    total_count = len(items)
    sliced = items[offset:offset + limit]

    data["items"] = sliced
    data["count"] = len(sliced)
    data["total_count"] = data.get("total_count", total_count)
    data["pagination"] = {
        "limit": limit,
        "offset": offset,
        "returned": len(sliced),
        "total": total_count,
        "has_more": offset + limit < total_count,
    }

    return data


# ---------------------------------------------------------------------------
# Settings fallback helpers
# ---------------------------------------------------------------------------

def get_library_route_prefix_safe() -> str:
    """Liefert den API-Route-Prefix aus ENV oder Default."""
    for env_key in ROUTE_PREFIX_ENV_KEYS:
        value = safe_str(os.getenv(env_key), default="")
        if value:
            return value
    return DEFAULT_LIBRARY_ROUTE_PREFIX


def get_library_source_root_safe() -> str | None:
    """Liefert den Library-Source-Root aus ENV, falls gesetzt."""
    for env_key in SOURCE_ROOT_ENV_KEYS:
        value = safe_str(os.getenv(env_key), default="")
        if value:
            return value
    return None


def get_library_route_plan(*, refresh: bool = False) -> dict[str, Any]:
    """Liefert die erwarteten Route-Pfade."""
    route_prefix = get_library_route_prefix_safe()

    return {
        "route_prefix": route_prefix,
        "health_route_path": "/health",
        "routes_route_path": "/routes",
        "selftest_route_path": "/selftest",
        "scan_route_path": "/scan",
        "sync_route_path": "/sync",
        "blocks_route_path": "/blocks",
        "tree_route_path": "/tree",
        "cache_clear_route_path": "/cache/clear",
        "block_detail_route_template": "/blocks/<block_id>",
        "block_variants_route_template": "/blocks/<block_id>/variants",
        "published_full_path": f"{route_prefix}/published",
        "items_full_path": f"{route_prefix}/items",
        "health_full_path": f"{route_prefix}/health",
        "scan_full_path": f"{route_prefix}/scan",
        "sync_full_path": f"{route_prefix}/sync",
        "blocks_full_path": f"{route_prefix}/blocks",
        "tree_full_path": f"{route_prefix}/tree",
        "cache_clear_full_path": f"{route_prefix}/cache/clear",
        "block_detail_full_path": f"{route_prefix}/blocks/<block_id>",
        "block_variants_full_path": f"{route_prefix}/blocks/<block_id>/variants",
        "refresh_requested": bool(refresh),
    }


def get_settings_summary(*, refresh: bool = False) -> dict[str, Any]:
    """Minimale Settings-Zusammenfassung ohne Abhängigkeit auf config.library_settings."""
    return {
        "ok": True,
        "route_plan": get_library_route_plan(refresh=refresh),
        "source_root": get_library_source_root_safe(),
    }


def get_library_settings_health(*, refresh: bool = False) -> dict[str, Any]:
    """Health für Settings-Fallback dieser Route-Schicht."""
    return {
        "ok": True,
        "healthy": True,
        "settings_summary": get_settings_summary(refresh=refresh),
    }


# ---------------------------------------------------------------------------
# Lazy optional backend imports
# ---------------------------------------------------------------------------

@lru_cache(maxsize=1)
def _load_optional_module(module_name: str) -> ModuleType:
    return importlib.import_module(module_name)


def _optional_module_status(module_name: str) -> dict[str, Any]:
    try:
        module = _load_optional_module(module_name)
        return {
            "ok": True,
            "module": getattr(module, "__name__", module_name),
        }
    except Exception as exc:
        return {
            "ok": False,
            "error": exception_to_dict(exc),
        }


def _get_optional_attr(module_name: str, attr_name: str) -> Any:
    module = _load_optional_module(module_name)
    return getattr(module, attr_name)


def _try_get_optional_attr(module_names: Sequence[str], attr_name: str) -> tuple[Any | None, BaseException | None]:
    last_exc: BaseException | None = None

    for module_name in module_names:
        try:
            module = _load_optional_module(module_name)
            value = getattr(module, attr_name)
            return value, None
        except Exception as exc:
            last_exc = exc

    return None, last_exc


LIBRARY_MODULE_NAMES: Final[tuple[str, ...]] = (
    "library",
    "src.library",
    "vectoplan_library.library",
    "vectoplan_library.src.library",
)

DOMAIN_MODULE_NAMES: Final[tuple[str, ...]] = (
    "library.domain",
    "src.library.domain",
    "vectoplan_library.library.domain",
    "vectoplan_library.src.library.domain",
)

SCANNER_MODULE_NAMES: Final[tuple[str, ...]] = (
    "library.scanner",
    "src.library.scanner",
    "vectoplan_library.library.scanner",
    "vectoplan_library.src.library.scanner",
)

VALIDATION_MODULE_NAMES: Final[tuple[str, ...]] = (
    "library.validation",
    "src.library.validation",
    "vectoplan_library.library.validation",
    "vectoplan_library.src.library.validation",
)

READ_MODELS_MODULE_NAMES: Final[tuple[str, ...]] = (
    "library.read_models",
    "src.library.read_models",
    "vectoplan_library.library.read_models",
    "vectoplan_library.src.library.read_models",
)

SERVICES_MODULE_NAMES: Final[tuple[str, ...]] = (
    "library.services",
    "src.library.services",
    "vectoplan_library.library.services",
    "vectoplan_library.src.library.services",
)

TAXONOMY_MODULE_NAMES: Final[tuple[str, ...]] = (
    "library.taxonomy",
    "src.library.taxonomy",
    "vectoplan_library.library.taxonomy",
    "vectoplan_library.src.library.taxonomy",
)

SCAN_SERVICE_MODULE_NAMES: Final[tuple[str, ...]] = (
    "library.services.library_scan_service",
    "src.library.services.library_scan_service",
    "vectoplan_library.library.services.library_scan_service",
    "vectoplan_library.src.library.services.library_scan_service",
)

BLOCK_SERVICE_MODULE_NAMES: Final[tuple[str, ...]] = (
    "library.services.library_block_service",
    "src.library.services.library_block_service",
    "vectoplan_library.library.services.library_block_service",
    "vectoplan_library.src.library.services.library_block_service",
)


# ---------------------------------------------------------------------------
# Request options
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class LibraryRouteRequestOptions:
    source_root: str | None = None
    force_refresh: bool = False
    use_cache: bool = False
    include_invalid: bool = False
    enabled_only: bool = False
    include_raw_pipeline: bool = False
    include_raw_documents: bool = True
    include_profiles: bool = True
    include_metadata: bool = True
    strict_errors: bool = False
    limit: int = DEFAULT_LIMIT
    offset: int = 0

    domain: str | None = None
    category: str | None = None
    subcategory: str | None = None
    object_kind: str | None = None
    q: str | None = None

    validate_taxonomy: bool = True
    require_taxonomy: bool = True
    use_taxonomy_labels: bool = True
    include_empty_taxonomy_nodes: bool = False
    include_inactive_taxonomy_nodes: bool = False
    include_taxonomy_payload: bool = False
    force_taxonomy_reload: bool = False

    include_subhealth: bool = True
    include_traceback: bool = False
    refresh_settings: bool = False

    def __post_init__(self) -> None:
        object.__setattr__(self, "source_root", normalize_query_text(self.source_root) or get_library_source_root_safe())
        object.__setattr__(self, "force_refresh", parse_bool(self.force_refresh, default=False))
        object.__setattr__(self, "use_cache", parse_bool(self.use_cache, default=False))

        if self.force_refresh:
            object.__setattr__(self, "use_cache", False)

        object.__setattr__(self, "include_invalid", parse_bool(self.include_invalid, default=False))
        object.__setattr__(self, "enabled_only", parse_bool(self.enabled_only, default=False))
        object.__setattr__(self, "include_raw_pipeline", parse_bool(self.include_raw_pipeline, default=False))
        object.__setattr__(self, "include_raw_documents", parse_bool(self.include_raw_documents, default=True))
        object.__setattr__(self, "include_profiles", parse_bool(self.include_profiles, default=True))
        object.__setattr__(self, "include_metadata", parse_bool(self.include_metadata, default=True))
        object.__setattr__(self, "strict_errors", parse_bool(self.strict_errors, default=False))
        object.__setattr__(self, "limit", parse_limit(self.limit))
        object.__setattr__(self, "offset", parse_offset(self.offset))

        object.__setattr__(self, "domain", normalize_slug_like(self.domain))
        object.__setattr__(self, "category", normalize_slug_like(self.category))
        object.__setattr__(self, "subcategory", normalize_slug_like(self.subcategory))
        object.__setattr__(self, "object_kind", normalize_slug_like(self.object_kind))
        object.__setattr__(self, "q", normalize_query_text(self.q))

        object.__setattr__(self, "validate_taxonomy", parse_bool(self.validate_taxonomy, default=True))
        object.__setattr__(self, "require_taxonomy", parse_bool(self.require_taxonomy, default=True))
        object.__setattr__(self, "use_taxonomy_labels", parse_bool(self.use_taxonomy_labels, default=True))
        object.__setattr__(self, "include_empty_taxonomy_nodes", parse_bool(self.include_empty_taxonomy_nodes, default=False))
        object.__setattr__(self, "include_inactive_taxonomy_nodes", parse_bool(self.include_inactive_taxonomy_nodes, default=False))
        object.__setattr__(self, "include_taxonomy_payload", parse_bool(self.include_taxonomy_payload, default=False))
        object.__setattr__(self, "force_taxonomy_reload", parse_bool(self.force_taxonomy_reload, default=False))

        object.__setattr__(self, "include_subhealth", parse_bool(self.include_subhealth, default=True))
        object.__setattr__(self, "include_traceback", parse_bool(self.include_traceback, default=False))
        object.__setattr__(self, "refresh_settings", parse_bool(self.refresh_settings, default=False))

    def _base_service_kwargs(self) -> dict[str, Any]:
        return {
            "use_cache": self.use_cache,
            "force_refresh": self.force_refresh,
            "include_invalid": self.include_invalid,
            "enabled_only": self.enabled_only,
            "include_raw_pipeline": self.include_raw_pipeline,
            "include_raw_documents": self.include_raw_documents,
            "include_profiles": self.include_profiles,
            "include_metadata": self.include_metadata,
            "strict_errors": self.strict_errors,
            "limit": self.limit,
            "offset": self.offset,
        }

    def _taxonomy_service_kwargs(self) -> dict[str, Any]:
        return {
            "validate_taxonomy": self.validate_taxonomy,
            "require_taxonomy": self.require_taxonomy,
            "use_taxonomy_labels": self.use_taxonomy_labels,
            "include_empty_taxonomy_nodes": self.include_empty_taxonomy_nodes,
            "include_inactive_taxonomy_nodes": self.include_inactive_taxonomy_nodes,
            "include_taxonomy_payload": self.include_taxonomy_payload,
            "force_taxonomy_reload": self.force_taxonomy_reload,
        }

    def to_block_service_options(self) -> Any:
        """Baut Block-Service-Optionen."""
        option_class, _error = _try_get_optional_attr(BLOCK_SERVICE_MODULE_NAMES, "LibraryBlockServiceOptions")

        if option_class is None:
            return {
                **self._base_service_kwargs(),
                **self._taxonomy_service_kwargs(),
            }

        attempts = (
            {
                **self._base_service_kwargs(),
                **self._taxonomy_service_kwargs(),
            },
            self._base_service_kwargs(),
            {},
        )

        for kwargs in attempts:
            try:
                return option_class(**kwargs)
            except Exception:
                continue

        return option_class()

    def to_scan_service_options(self) -> Any:
        """Baut Scan-Service-Optionen mit Taxonomie-Pipeline-Feldern."""
        option_class, _error = _try_get_optional_attr(SCAN_SERVICE_MODULE_NAMES, "LibraryScanServiceOptions")

        attempts = (
            {
                "include_invalid": self.include_invalid,
                "enabled_only": self.enabled_only,
                "use_cache": self.use_cache,
                "cache_ttl_seconds": DEFAULT_RESPONSE_HTTP_STATUS,
                "refresh_settings": self.refresh_settings,
                "include_raw_pipeline": self.include_raw_pipeline,
                "include_index": True,
                "include_scan_result": True,
                "include_discovery_result": self.include_raw_pipeline,
                "include_read_results": self.include_raw_pipeline,
                "include_validation_results": self.include_raw_pipeline,
                "include_fingerprint_results": self.include_raw_pipeline,
                "strict_errors": self.strict_errors,
                "validate_taxonomy": self.validate_taxonomy,
                "require_taxonomy": self.require_taxonomy,
                "use_taxonomy_labels": self.use_taxonomy_labels,
                "include_empty_taxonomy_nodes": self.include_empty_taxonomy_nodes,
                "include_inactive_taxonomy_nodes": self.include_inactive_taxonomy_nodes,
                "include_taxonomy_payload": self.include_taxonomy_payload,
                "force_taxonomy_reload": self.force_taxonomy_reload,
            },
            {
                "include_invalid": self.include_invalid,
                "enabled_only": self.enabled_only,
                "use_cache": self.use_cache,
                "refresh_settings": self.refresh_settings,
                "include_raw_pipeline": self.include_raw_pipeline,
                "strict_errors": self.strict_errors,
            },
            {},
        )

        if option_class is not None:
            for kwargs in attempts:
                try:
                    return option_class(**kwargs)
                except Exception:
                    continue

        return {
            **self._base_service_kwargs(),
            **self._taxonomy_service_kwargs(),
        }

    def filter_kwargs(self) -> dict[str, Any]:
        return {
            "domain": self.domain,
            "category": self.category,
            "subcategory": self.subcategory,
            "object_kind": self.object_kind,
            "q": self.q,
        }

    def to_dict(self) -> dict[str, Any]:
        return {
            "source_root": self.source_root,
            "force_refresh": self.force_refresh,
            "use_cache": self.use_cache,
            "include_invalid": self.include_invalid,
            "enabled_only": self.enabled_only,
            "include_raw_pipeline": self.include_raw_pipeline,
            "include_raw_documents": self.include_raw_documents,
            "include_profiles": self.include_profiles,
            "include_metadata": self.include_metadata,
            "strict_errors": self.strict_errors,
            "limit": self.limit,
            "offset": self.offset,
            "domain": self.domain,
            "category": self.category,
            "subcategory": self.subcategory,
            "object_kind": self.object_kind,
            "q": self.q,
            "validate_taxonomy": self.validate_taxonomy,
            "require_taxonomy": self.require_taxonomy,
            "use_taxonomy_labels": self.use_taxonomy_labels,
            "include_empty_taxonomy_nodes": self.include_empty_taxonomy_nodes,
            "include_inactive_taxonomy_nodes": self.include_inactive_taxonomy_nodes,
            "include_taxonomy_payload": self.include_taxonomy_payload,
            "force_taxonomy_reload": self.force_taxonomy_reload,
            "include_subhealth": self.include_subhealth,
            "include_traceback": self.include_traceback,
            "refresh_settings": self.refresh_settings,
        }


def parse_library_route_request_options(
    query_args: Mapping[str, Any] | None = None,
    payload: Mapping[str, Any] | None = None,
) -> LibraryRouteRequestOptions:
    """Parst Query-/Payload-Parameter für alle Library-Routen."""
    params = merge_params(query_args, payload)

    force_refresh = parse_bool(
        get_param(params, "force_refresh", "forceRefresh", "refresh", "no_cache", "noCache"),
        default=False,
    )

    use_cache = parse_bool(
        get_param(params, "use_cache", "useCache", "cache"),
        default=False,
    )

    if force_refresh:
        use_cache = False

    return LibraryRouteRequestOptions(
        source_root=normalize_query_text(get_param(params, "source_root", "sourceRoot", "root")),
        force_refresh=force_refresh,
        use_cache=use_cache,
        include_invalid=parse_bool(
            get_param(params, "include_invalid", "includeInvalid", "invalid"),
            default=False,
        ),
        enabled_only=parse_bool(
            get_param(params, "enabled_only", "enabledOnly"),
            default=False,
        ),
        include_raw_pipeline=parse_bool(
            get_param(params, "include_raw_pipeline", "includeRawPipeline", "raw_pipeline", "rawPipeline", "debug"),
            default=False,
        ),
        include_raw_documents=parse_bool(
            get_param(params, "include_raw_documents", "includeRawDocuments", "raw_documents", "rawDocuments"),
            default=True,
        ),
        include_profiles=parse_bool(
            get_param(params, "include_profiles", "includeProfiles", "profiles"),
            default=True,
        ),
        include_metadata=parse_bool(
            get_param(params, "include_metadata", "includeMetadata", "metadata"),
            default=True,
        ),
        strict_errors=parse_bool(
            get_param(params, "strict_errors", "strictErrors", "strict"),
            default=False,
        ),
        limit=parse_limit(get_param(params, "limit", default=DEFAULT_LIMIT), default=DEFAULT_LIMIT),
        offset=parse_offset(get_param(params, "offset", default=0), default=0),
        domain=normalize_query_text(get_param(params, "domain")),
        category=normalize_query_text(get_param(params, "category")),
        subcategory=normalize_query_text(get_param(params, "subcategory", "sub_category", "subCategory")),
        object_kind=normalize_query_text(get_param(params, "object_kind", "objectKind", "kind")),
        q=normalize_query_text(get_param(params, "q", "query", "search")),
        validate_taxonomy=parse_bool(
            get_param(params, "validate_taxonomy", "validateTaxonomy"),
            default=True,
        ),
        require_taxonomy=parse_bool(
            get_param(params, "require_taxonomy", "requireTaxonomy"),
            default=True,
        ),
        use_taxonomy_labels=parse_bool(
            get_param(params, "use_taxonomy_labels", "useTaxonomyLabels"),
            default=True,
        ),
        include_empty_taxonomy_nodes=parse_bool(
            get_param(params, "include_empty_taxonomy_nodes", "includeEmptyTaxonomyNodes", "empty_taxonomy", "emptyTaxonomy"),
            default=False,
        ),
        include_inactive_taxonomy_nodes=parse_bool(
            get_param(params, "include_inactive_taxonomy_nodes", "includeInactiveTaxonomyNodes"),
            default=False,
        ),
        include_taxonomy_payload=parse_bool(
            get_param(params, "include_taxonomy_payload", "includeTaxonomyPayload"),
            default=False,
        ),
        force_taxonomy_reload=parse_bool(
            get_param(params, "force_taxonomy_reload", "forceTaxonomyReload"),
            default=False,
        ),
        include_subhealth=parse_bool(
            get_param(params, "include_subhealth", "includeSubhealth", "subhealth", "deep"),
            default=True,
        ),
        include_traceback=parse_bool(
            get_param(params, "include_traceback", "includeTraceback", "traceback"),
            default=False,
        ),
        refresh_settings=parse_bool(
            get_param(params, "refresh_settings", "refreshSettings"),
            default=False,
        ),
    )


# ---------------------------------------------------------------------------
# Result
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class LibraryRouteServiceResult:
    ok: bool
    status: str
    payload: dict[str, Any] = field(default_factory=dict)
    http_status: int = DEFAULT_RESPONSE_HTTP_STATUS
    generated_at: str = field(default_factory=utc_now_iso)
    warnings: tuple[str, ...] = field(default_factory=tuple)
    errors: tuple[str, ...] = field(default_factory=tuple)
    metadata: dict[str, Any] = field(default_factory=dict)
    version: str = LIBRARY_ROUTE_SERVICE_VERSION

    def __post_init__(self) -> None:
        status = safe_str(self.status, default="unknown").lower()

        if status not in ROUTE_SERVICE_STATUS_VALUES:
            status = "unknown"

        warnings = tuple_of_strings(self.warnings)
        errors = tuple_of_strings(self.errors)

        if status == "unknown":
            status = "error" if errors else ("ok" if self.ok else "error")

        object.__setattr__(
            self,
            "ok",
            bool(self.ok and status not in {"error", "bad_request", "not_found", "invalid", "invalid_request", "unavailable", "failed"}),
        )
        object.__setattr__(self, "status", status)
        object.__setattr__(
            self,
            "http_status",
            safe_int(self.http_status, default=response_http_status({"status": status}), minimum=100, maximum=599),
        )
        object.__setattr__(self, "generated_at", safe_str(self.generated_at, default=utc_now_iso()))
        object.__setattr__(self, "warnings", warnings)
        object.__setattr__(self, "errors", errors)
        object.__setattr__(self, "payload", dict(self.payload or {}))
        object.__setattr__(self, "metadata", dict(self.metadata or {}))
        object.__setattr__(self, "version", safe_str(self.version, default=LIBRARY_ROUTE_SERVICE_VERSION))

    def to_dict(self, *, include_http_status: bool = True) -> dict[str, Any]:
        result: dict[str, Any] = {
            "ok": self.ok,
            "status": self.status,
            "generated_at": self.generated_at,
            "warnings": list(self.warnings),
            "errors": list(self.errors),
            "version": self.version,
            "component": LIBRARY_ROUTE_SERVICE_COMPONENT,
            "backend": "legacy_file",
        }

        result.update(json_safe(self.payload))

        if self.metadata:
            result["metadata"] = json_safe(self.metadata)

        if include_http_status:
            result["_http_status"] = self.http_status

        return result

    @classmethod
    def error(
        cls,
        exc: BaseException,
        *,
        message: str,
        include_traceback: bool = False,
    ) -> "LibraryRouteServiceResult":
        error_data = exception_to_dict(exc, include_traceback=include_traceback)
        error_message = safe_str(error_data.get("message") if error_data else None, default=message)

        return cls(
            ok=False,
            status="error",
            payload={
                "message": message,
                "error": error_data,
            },
            http_status=ERROR_HTTP_STATUS,
            warnings=(),
            errors=(error_message,),
            metadata={},
        )

    @classmethod
    def bad_request(
        cls,
        message: str,
        *,
        payload: Mapping[str, Any] | None = None,
    ) -> "LibraryRouteServiceResult":
        return cls(
            ok=False,
            status="bad_request",
            payload={
                "message": message,
                **dict(payload or {}),
            },
            http_status=BAD_REQUEST_HTTP_STATUS,
            warnings=(),
            errors=(message,),
            metadata={},
        )


# ---------------------------------------------------------------------------
# Service call helpers
# ---------------------------------------------------------------------------

def _safe_payload(value: Any) -> dict[str, Any]:
    if isinstance(value, Mapping):
        return dict(value)

    if hasattr(value, "to_dict") and callable(value.to_dict):
        try:
            raw = value.to_dict()
        except TypeError:
            raw = value.to_dict(flat=True)
        return dict(raw) if isinstance(raw, Mapping) else {"value": json_safe(raw)}

    return {"value": json_safe(value)}


def _filter_supported_kwargs(func: Callable[..., Any], kwargs: Mapping[str, Any]) -> dict[str, Any]:
    try:
        signature = inspect.signature(func)
    except Exception:
        return dict(kwargs)

    for parameter in signature.parameters.values():
        if parameter.kind == inspect.Parameter.VAR_KEYWORD:
            return dict(kwargs)

    supported = set(signature.parameters.keys())
    return {key: value for key, value in kwargs.items() if key in supported}


def _call_function_flexible(func: Callable[..., Any], *args: Any, **kwargs: Any) -> Any:
    filtered_kwargs = _filter_supported_kwargs(func, kwargs)

    try:
        return func(*args, **filtered_kwargs)
    except TypeError:
        if args:
            try:
                return func(*args)
            except TypeError:
                pass
        if filtered_kwargs:
            try:
                return func(**filtered_kwargs)
            except TypeError:
                pass
        return func()


def _get_scan_service_attr(attr_name: str) -> tuple[Any | None, BaseException | None]:
    return _try_get_optional_attr(SCAN_SERVICE_MODULE_NAMES, attr_name)


def _get_block_service_attr(attr_name: str) -> tuple[Any | None, BaseException | None]:
    return _try_get_optional_attr(BLOCK_SERVICE_MODULE_NAMES, attr_name)


def _call_scan_service_scan(options: LibraryRouteRequestOptions) -> dict[str, Any]:
    func, exc = _get_scan_service_attr("get_library_scan_response")
    if not callable(func):
        return unavailable_response("library scan service is unavailable", exc)

    response = _call_function_flexible(
        func,
        source_root=options.source_root,
        options=options.to_scan_service_options(),
        force_refresh=options.force_refresh,
    )
    payload = _safe_payload(response)
    payload.setdefault("service", "library_scan_service")
    return payload


def _call_scan_service_blocks(options: LibraryRouteRequestOptions) -> dict[str, Any]:
    func, exc = _get_scan_service_attr("get_library_blocks_response")
    if not callable(func):
        return unavailable_response("library scan service is unavailable", exc)

    response = _call_function_flexible(
        func,
        source_root=options.source_root,
        domain=options.domain,
        category=options.category,
        subcategory=options.subcategory,
        object_kind=options.object_kind,
        q=options.q,
        options=options.to_scan_service_options(),
        force_refresh=options.force_refresh,
    )
    payload = _safe_payload(response)
    payload.setdefault("service", "library_scan_service")
    return payload


def _call_scan_service_tree(options: LibraryRouteRequestOptions) -> dict[str, Any]:
    func, exc = _get_scan_service_attr("get_library_tree_response")
    if not callable(func):
        return unavailable_response("library scan service is unavailable", exc)

    response = _call_function_flexible(
        func,
        source_root=options.source_root,
        options=options.to_scan_service_options(),
        force_refresh=options.force_refresh,
    )
    payload = _safe_payload(response)
    payload.setdefault("service", "library_scan_service")
    return payload


def _call_block_service_scan(options: LibraryRouteRequestOptions) -> dict[str, Any]:
    func, exc = _get_block_service_attr("scan_library_for_blocks_response")
    if not callable(func):
        return unavailable_response("library block service is unavailable", exc)

    response = _call_function_flexible(
        func,
        source_root=options.source_root,
        options=options.to_block_service_options(),
    )
    payload = _safe_payload(response)
    payload.setdefault("service", "library_block_service")
    return payload


def _call_block_service_blocks(options: LibraryRouteRequestOptions) -> dict[str, Any]:
    func, exc = _get_block_service_attr("list_library_blocks_response")
    if not callable(func):
        return unavailable_response("library block service is unavailable", exc)

    response = _call_function_flexible(
        func,
        source_root=options.source_root,
        domain=options.domain,
        category=options.category,
        subcategory=options.subcategory,
        object_kind=options.object_kind,
        q=options.q,
        options=options.to_block_service_options(),
    )
    payload = _safe_payload(response)
    payload.setdefault("service", "library_block_service")
    return payload


def _call_block_service_tree(options: LibraryRouteRequestOptions) -> dict[str, Any]:
    func, exc = _get_block_service_attr("get_library_tree_response_from_block_service")
    if not callable(func):
        return unavailable_response("library block service is unavailable", exc)

    response = _call_function_flexible(
        func,
        source_root=options.source_root,
        options=options.to_block_service_options(),
    )
    payload = _safe_payload(response)
    payload.setdefault("service", "library_block_service")
    return payload


def _call_block_service_detail(block_id: str, options: LibraryRouteRequestOptions) -> dict[str, Any]:
    func, exc = _get_block_service_attr("get_library_block_detail_response")
    if not callable(func):
        return unavailable_response("library block service is unavailable", exc)

    response = _call_function_flexible(
        func,
        block_id,
        source_root=options.source_root,
        options=options.to_block_service_options(),
    )
    payload = _safe_payload(response)
    payload.setdefault("service", "library_block_service")
    return payload


def _call_block_service_variants(block_id: str, options: LibraryRouteRequestOptions) -> dict[str, Any]:
    func, exc = _get_block_service_attr("get_library_block_variants_response")
    if not callable(func):
        return unavailable_response("library block service is unavailable", exc)

    response = _call_function_flexible(
        func,
        block_id,
        source_root=options.source_root,
        options=options.to_block_service_options(),
    )
    payload = _safe_payload(response)
    payload.setdefault("service", "library_block_service")
    return payload


def item_matches_filter(item: Mapping[str, Any], *, options: LibraryRouteRequestOptions) -> bool:
    taxonomy = safe_mapping(item.get("taxonomy"))

    domain = safe_str(item.get("domain") or taxonomy.get("domain"), default="")
    category = safe_str(item.get("category") or taxonomy.get("category"), default="")
    subcategory = safe_str(item.get("subcategory") or taxonomy.get("subcategory"), default="")
    object_kind = safe_str(item.get("object_kind") or item.get("kind"), default="")

    if options.domain and domain != options.domain:
        return False

    if options.category and category != options.category:
        return False

    if options.subcategory and subcategory != options.subcategory:
        return False

    if options.object_kind and object_kind != options.object_kind:
        return False

    if options.q:
        haystack = " ".join(
            [
                safe_str(item.get("id"), default=""),
                safe_str(item.get("block_id"), default=""),
                safe_str(item.get("vplib_uid"), default=""),
                safe_str(item.get("family_id"), default=""),
                safe_str(item.get("package_id"), default=""),
                safe_str(item.get("label"), default=""),
                safe_str(item.get("name"), default=""),
                safe_str(item.get("title"), default=""),
                safe_str(item.get("description"), default=""),
                domain,
                category,
                subcategory,
                object_kind,
            ]
        ).lower()

        if options.q.lower() not in haystack:
            return False

    return True


def _extract_items_from_payload(payload: Mapping[str, Any]) -> list[Any] | None:
    for key in ("items", "blocks", "objects", "families"):
        value = payload.get(key)
        if isinstance(value, list):
            return value

    data = payload.get("data")
    if isinstance(data, Mapping):
        return _extract_items_from_payload(data)

    payload_inner = payload.get("payload")
    if isinstance(payload_inner, Mapping):
        return _extract_items_from_payload(payload_inner)

    return None


def _set_items_in_payload(payload: dict[str, Any], items: list[Any]) -> dict[str, Any]:
    if "items" in payload:
        payload["items"] = items
        return payload

    if "blocks" in payload:
        payload["blocks"] = items
        return payload

    payload["items"] = items
    return payload


def apply_route_filters(payload: Mapping[str, Any], *, options: LibraryRouteRequestOptions) -> dict[str, Any]:
    """Wendet Route-Filter lokal an, falls Backend-Service keine Filter kennt."""
    data = dict(payload)
    items = _extract_items_from_payload(data)

    if not isinstance(items, list):
        return data

    if not any((options.domain, options.category, options.subcategory, options.object_kind, options.q)):
        paged = apply_list_pagination({"items": items}, limit=options.limit, offset=options.offset)
        _set_items_in_payload(data, paged["items"])
        data["count"] = paged["count"]
        data["total_count"] = paged["total_count"]
        data["pagination"] = paged["pagination"]
        return data

    filtered = [
        item
        for item in items
        if isinstance(item, Mapping) and item_matches_filter(item, options=options)
    ]

    data = _set_items_in_payload(data, filtered)
    data["count"] = len(filtered)
    data["filters"] = {
        "domain": options.domain,
        "category": options.category,
        "subcategory": options.subcategory,
        "object_kind": options.object_kind,
        "q": options.q,
    }

    paged = apply_list_pagination({"items": filtered}, limit=options.limit, offset=options.offset)
    _set_items_in_payload(data, paged["items"])
    data["count"] = paged["count"]
    data["total_count"] = paged["total_count"]
    data["pagination"] = paged["pagination"]
    return data


# ---------------------------------------------------------------------------
# Health
# ---------------------------------------------------------------------------

def get_import_status() -> dict[str, Any]:
    """Liefert Importstatus aller optionalen Backend-Module."""
    return {
        "library": _module_group_status(LIBRARY_MODULE_NAMES),
        "domain": _module_group_status(DOMAIN_MODULE_NAMES),
        "scanner": _module_group_status(SCANNER_MODULE_NAMES),
        "validation": _module_group_status(VALIDATION_MODULE_NAMES),
        "read_models": _module_group_status(READ_MODELS_MODULE_NAMES),
        "services": _module_group_status(SERVICES_MODULE_NAMES),
        "block_service": _module_group_status(BLOCK_SERVICE_MODULE_NAMES),
        "scan_service": _module_group_status(SCAN_SERVICE_MODULE_NAMES),
        "taxonomy": _module_group_status(TAXONOMY_MODULE_NAMES),
    }


def _module_group_status(module_names: Sequence[str]) -> dict[str, Any]:
    errors: list[dict[str, Any] | None] = []

    for module_name in module_names:
        try:
            module = _load_optional_module(module_name)
            return {
                "ok": True,
                "module": getattr(module, "__name__", module_name),
            }
        except Exception as exc:
            errors.append(exception_to_dict(exc))

    return {
        "ok": False,
        "errors": errors,
    }


def _run_health_check(name: str, fn: Any, *, include_traceback: bool = False) -> dict[str, Any]:
    """Führt einen Health-Check defensiv aus."""
    try:
        result = fn()
        if isinstance(result, Mapping):
            return dict(json_safe(result))

        return {
            "ok": False,
            "healthy": False,
            "status": "invalid_health_result",
            "value": json_safe(result),
        }

    except Exception as exc:
        return {
            "ok": False,
            "healthy": False,
            "status": "health_error",
            "component": name,
            "error": exception_to_dict(exc, include_traceback=include_traceback),
        }


def get_taxonomy_service() -> Any:
    factory, exc = _try_get_optional_attr(TAXONOMY_MODULE_NAMES, "get_default_taxonomy_service")
    if not callable(factory):
        raise RuntimeError(f"Taxonomie-Service ist nicht verfügbar: {exc}")
    return factory()


def get_taxonomy_health_payload(
    *,
    include_traceback: bool = False,
    force_reload: bool = False,
) -> dict[str, Any]:
    """Taxonomie-Health defensiv laden."""
    try:
        service = get_taxonomy_service()
        return service.health(
            force_reload=force_reload,
            include_registry_state=False,
        )
    except Exception as exc:
        return {
            "ok": False,
            "healthy": False,
            "available": False,
            "error": exception_to_dict(exc, include_traceback=include_traceback),
        }


def _optional_health(module_names: Sequence[str], function_name: str, *, include_traceback: bool = False, **kwargs: Any) -> dict[str, Any]:
    func, exc = _try_get_optional_attr(module_names, function_name)
    if not callable(func):
        return {
            "ok": False,
            "healthy": False,
            "status": "unavailable",
            "error": exception_to_dict(exc, include_traceback=include_traceback),
        }

    try:
        result = _call_function_flexible(func, **kwargs)
        return _safe_payload(result)
    except Exception as call_exc:
        return {
            "ok": False,
            "healthy": False,
            "status": "health_error",
            "error": exception_to_dict(call_exc, include_traceback=include_traceback),
        }


def get_library_route_service_health(
    *,
    include_subhealth: bool = True,
    include_traceback: bool = False,
    refresh_settings: bool = False,
    force_taxonomy_reload: bool = False,
) -> dict[str, Any]:
    """Health-Status des Route-Service."""
    warnings: list[str] = []
    errors: list[str] = []

    imports = get_import_status()

    for name, status in imports.items():
        if not status.get("ok"):
            if name in {"block_service", "scan_service", "taxonomy"}:
                errors.append(f"{name} import failed")
            else:
                warnings.append(f"{name} import failed; fallback may be active")

    subhealth: dict[str, Any] = {}

    if include_subhealth:
        checks = {
            "library": lambda: _optional_health(LIBRARY_MODULE_NAMES, "get_library_health", strict=False, include_traceback=include_traceback),
            "settings": lambda: get_library_settings_health(refresh=refresh_settings),
            "domain": lambda: _optional_health(DOMAIN_MODULE_NAMES, "get_domain_health", include_traceback=include_traceback),
            "scanner": lambda: _optional_health(SCANNER_MODULE_NAMES, "get_scanner_health", include_traceback=include_traceback, include_subhealth=True),
            "validation": lambda: _optional_health(VALIDATION_MODULE_NAMES, "get_validation_health", include_traceback=include_traceback, include_subhealth=True),
            "read_models": lambda: _optional_health(READ_MODELS_MODULE_NAMES, "get_read_models_health", include_traceback=include_traceback, include_subhealth=True),
            "services": lambda: _optional_health(SERVICES_MODULE_NAMES, "get_services_health", include_traceback=include_traceback, include_subhealth=True),
            "block_service": lambda: _optional_health(BLOCK_SERVICE_MODULE_NAMES, "get_library_block_service_health", include_traceback=include_traceback),
            "scan_service": lambda: _optional_health(SCAN_SERVICE_MODULE_NAMES, "get_library_scan_service_health", refresh_settings=refresh_settings, include_traceback=include_traceback),
            "taxonomy": lambda: get_taxonomy_health_payload(
                include_traceback=include_traceback,
                force_reload=force_taxonomy_reload,
            ),
        }

        for name, fn in checks.items():
            health = _run_health_check(name, fn, include_traceback=include_traceback)
            subhealth[name] = health

            if health.get("healthy") is False and name in {"block_service", "scan_service", "taxonomy"}:
                errors.append(f"{name} subhealth failed")

    try:
        safe_int_self_test = safe_int("999999", default=DEFAULT_LIMIT, minimum=1, maximum=MAX_LIMIT)
        if safe_int_self_test != MAX_LIMIT:
            errors.append(f"route safe_int maximum self-test failed: expected {MAX_LIMIT}, got {safe_int_self_test}")
    except Exception as exc:
        errors.append(f"route safe_int maximum self-test failed: {exc}")

    try:
        options = LibraryRouteRequestOptions()
        route_options_dict = options.to_dict()
        block_options_dict = json_safe(options.to_block_service_options())
        scan_options_dict = json_safe(options.to_scan_service_options())
    except Exception as exc:
        route_options_dict = {}
        block_options_dict = {}
        scan_options_dict = {}
        errors.append(f"could not build route request options: {exc}")

    healthy = len(errors) == 0

    return {
        "ok": healthy,
        "healthy": healthy,
        "status": "healthy" if healthy else "unhealthy",
        "component": LIBRARY_ROUTE_SERVICE_COMPONENT,
        "version": LIBRARY_ROUTE_SERVICE_VERSION,
        "generated_at": utc_now_iso(),
        "route_prefix": get_library_route_prefix_safe(),
        "route_plan": get_library_route_plan(refresh=refresh_settings),
        "imports": imports,
        "subhealth": subhealth,
        "settings_summary": get_settings_summary(refresh=refresh_settings),
        "self_tests": {
            "route_options": route_options_dict,
            "block_options": block_options_dict,
            "scan_options": scan_options_dict,
        },
        "supported_filters": {
            "domain": True,
            "category": True,
            "subcategory": True,
            "object_kind": True,
            "q": True,
        },
        "taxonomy_options": {
            "validate_taxonomy": True,
            "require_taxonomy": True,
            "use_taxonomy_labels": True,
            "include_empty_taxonomy_nodes": True,
            "include_inactive_taxonomy_nodes": True,
            "include_taxonomy_payload": True,
            "force_taxonomy_reload": True,
        },
        "writes_database": False,
        "warnings": warnings,
        "errors": errors,
    }


# ---------------------------------------------------------------------------
# Route handlers
# ---------------------------------------------------------------------------

def handle_library_health_request(
    query_args: Mapping[str, Any] | None = None,
    payload: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    try:
        options = parse_library_route_request_options(query_args, payload)

        health = get_library_route_service_health(
            include_subhealth=options.include_subhealth,
            include_traceback=options.include_traceback,
            refresh_settings=options.refresh_settings,
            force_taxonomy_reload=options.force_taxonomy_reload,
        )

        health["request"] = options.to_dict()
        health["route"] = "health"

        return make_response_envelope(health)

    except Exception as exc:
        return LibraryRouteServiceResult.error(
            exc,
            message="library health request failed",
        ).to_dict()


def handle_library_scan_request(
    query_args: Mapping[str, Any] | None = None,
    payload: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    try:
        options = parse_library_route_request_options(query_args, payload)

        response = _call_scan_service_scan(options)

        if response.get("status") == "unavailable":
            response = _call_block_service_scan(options)

        response.setdefault("route", "scan")
        response.setdefault("request", options.to_dict())
        response.setdefault("writes_database", False)

        return make_response_envelope(response)

    except Exception as exc:
        return LibraryRouteServiceResult.error(
            exc,
            message="library scan request failed",
        ).to_dict()


def handle_library_blocks_request(
    query_args: Mapping[str, Any] | None = None,
    payload: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    try:
        options = parse_library_route_request_options(query_args, payload)

        response = _call_scan_service_blocks(options)

        if response.get("status") == "unavailable":
            response = _call_block_service_blocks(options)

        response = apply_route_filters(response, options=options)
        response.setdefault("route", "blocks")
        response.setdefault("request", options.to_dict())
        response.setdefault("filters", options.filter_kwargs())
        response.setdefault("writes_database", False)

        return make_response_envelope(response)

    except Exception as exc:
        return LibraryRouteServiceResult.error(
            exc,
            message="library blocks request failed",
        ).to_dict()


def handle_library_block_detail_request(
    block_id: Any,
    query_args: Mapping[str, Any] | None = None,
    payload: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    try:
        normalized_block_id = normalize_block_id(block_id)

        if not normalized_block_id:
            return LibraryRouteServiceResult.bad_request(
                "block_id is required",
                payload={"block_id": block_id},
            ).to_dict()

        options = parse_library_route_request_options(query_args, payload)

        response = _call_block_service_detail(normalized_block_id, options)

        response.setdefault("route", "block_detail")
        response.setdefault("request", options.to_dict())
        response.setdefault("block_id", normalized_block_id)
        response.setdefault("writes_database", False)

        return make_response_envelope(response)

    except Exception as exc:
        return LibraryRouteServiceResult.error(
            exc,
            message="library block detail request failed",
        ).to_dict()


def handle_library_block_variants_request(
    block_id: Any,
    query_args: Mapping[str, Any] | None = None,
    payload: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    try:
        normalized_block_id = normalize_block_id(block_id)

        if not normalized_block_id:
            return LibraryRouteServiceResult.bad_request(
                "block_id is required",
                payload={"block_id": block_id},
            ).to_dict()

        options = parse_library_route_request_options(query_args, payload)

        response = _call_block_service_variants(normalized_block_id, options)

        response.setdefault("route", "block_variants")
        response.setdefault("request", options.to_dict())
        response.setdefault("block_id", normalized_block_id)
        response.setdefault("writes_database", False)

        return make_response_envelope(response)

    except Exception as exc:
        return LibraryRouteServiceResult.error(
            exc,
            message="library block variants request failed",
        ).to_dict()


def handle_library_tree_request(
    query_args: Mapping[str, Any] | None = None,
    payload: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    try:
        options = parse_library_route_request_options(query_args, payload)

        response = _call_scan_service_tree(options)

        if response.get("status") == "unavailable":
            response = _call_block_service_tree(options)

        response.setdefault("route", "tree")
        response.setdefault("request", options.to_dict())
        response.setdefault("writes_database", False)

        return make_response_envelope(response)

    except Exception as exc:
        return LibraryRouteServiceResult.error(
            exc,
            message="library tree request failed",
        ).to_dict()


def handle_library_cache_clear_request(
    query_args: Mapping[str, Any] | None = None,
    payload: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    try:
        options = parse_library_route_request_options(query_args, payload)

        cleared: dict[str, Any] = {
            "scan_cache": False,
            "taxonomy_cache": False,
            "lazy_import_caches": False,
        }
        warnings: list[str] = []

        try:
            func, exc = _get_scan_service_attr("clear_library_scan_cache")
            if callable(func):
                func()
                cleared["scan_cache"] = True
            elif exc is not None:
                warnings.append(f"clear_library_scan_cache unavailable: {exc}")
        except Exception as exc:
            warnings.append(f"clear_library_scan_cache failed: {exc}")

        try:
            taxonomy_service = get_taxonomy_service()
            clear_func = getattr(taxonomy_service, "clear_cache", None)
            if callable(clear_func):
                clear_func()
                cleared["taxonomy_cache"] = True
        except Exception as exc:
            warnings.append(f"taxonomy cache clear failed: {exc}")

        try:
            clear_library_route_service_caches()
            cleared["lazy_import_caches"] = True
        except Exception as exc:
            warnings.append(f"route service lazy cache clear failed: {exc}")

        return make_response_envelope(
            {
                "ok": not warnings,
                "status": "ok" if not warnings else "partial",
                "message": "library scan cache cleared",
                "cleared": cleared,
                "warnings": warnings,
                "request": options.to_dict(),
                "writes_database": False,
            },
            http_status=200 if not warnings else 207,
        )

    except Exception as exc:
        return LibraryRouteServiceResult.error(
            exc,
            message="library cache clear request failed",
        ).to_dict()


# ---------------------------------------------------------------------------
# Compatibility aliases used by routes.library_routes
# ---------------------------------------------------------------------------

def get_health_payload(
    query_args: Mapping[str, Any] | None = None,
    payload: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    return handle_library_health_request(query_args=query_args, payload=payload)


def get_scan_payload(
    query_args: Mapping[str, Any] | None = None,
    payload: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    return handle_library_scan_request(query_args=query_args, payload=payload)


def get_blocks_payload(
    query_args: Mapping[str, Any] | None = None,
    payload: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    return handle_library_blocks_request(query_args=query_args, payload=payload)


def get_block_detail_payload(
    block_id: Any,
    query_args: Mapping[str, Any] | None = None,
    payload: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    return handle_library_block_detail_request(
        block_id,
        query_args=query_args,
        payload=payload,
    )


def get_block_variants_payload(
    block_id: Any,
    query_args: Mapping[str, Any] | None = None,
    payload: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    return handle_library_block_variants_request(
        block_id,
        query_args=query_args,
        payload=payload,
    )


def get_tree_payload(
    query_args: Mapping[str, Any] | None = None,
    payload: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    return handle_library_tree_request(query_args=query_args, payload=payload)


def clear_library_route_service_caches() -> dict[str, Any]:
    """Leert lokale Lazy-Import-Caches dieses Route-Service."""
    cleared: list[str] = []

    try:
        _load_optional_module.cache_clear()
        cleared.append("_load_optional_module")
    except Exception:
        pass

    return {
        "ok": True,
        "cleared": cleared,
    }


__all__: Final[tuple[str, ...]] = (
    "LIBRARY_ROUTE_SERVICE_VERSION",
    "LIBRARY_ROUTE_SERVICE_COMPONENT",
    "DEFAULT_LIBRARY_ROUTE_PREFIX",
    "DEFAULT_RESPONSE_HTTP_STATUS",
    "BAD_REQUEST_HTTP_STATUS",
    "NOT_FOUND_HTTP_STATUS",
    "CONFLICT_HTTP_STATUS",
    "ERROR_HTTP_STATUS",
    "UNAVAILABLE_HTTP_STATUS",
    "DEFAULT_LIMIT",
    "MAX_LIMIT",
    "LibraryRouteRequestOptions",
    "LibraryRouteServiceResult",
    "utc_now_iso",
    "exception_to_dict",
    "json_safe",
    "safe_str",
    "safe_int",
    "parse_bool",
    "normalize_query_text",
    "normalize_slug_like",
    "normalize_block_id",
    "tuple_of_strings",
    "safe_mapping",
    "normalize_param_mapping",
    "merge_params",
    "get_param",
    "parse_limit",
    "parse_offset",
    "response_http_status",
    "make_response_envelope",
    "unavailable_response",
    "apply_list_pagination",
    "get_library_route_prefix_safe",
    "get_library_source_root_safe",
    "get_library_route_plan",
    "get_settings_summary",
    "get_library_settings_health",
    "parse_library_route_request_options",
    "apply_route_filters",
    "get_import_status",
    "get_taxonomy_service",
    "get_taxonomy_health_payload",
    "get_library_route_service_health",
    "handle_library_health_request",
    "handle_library_scan_request",
    "handle_library_blocks_request",
    "handle_library_block_detail_request",
    "handle_library_block_variants_request",
    "handle_library_tree_request",
    "handle_library_cache_clear_request",
    "get_health_payload",
    "get_scan_payload",
    "get_blocks_payload",
    "get_block_detail_payload",
    "get_block_variants_payload",
    "get_tree_payload",
    "clear_library_route_service_caches",
)