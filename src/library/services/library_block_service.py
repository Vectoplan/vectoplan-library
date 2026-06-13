# services/vectoplan-library/src/library/services/library_block_service.py
"""
Library Block Service für die VECTOPLAN Creative-Library-Schicht.

Diese Datei stellt block-/objektbezogene Backend-Operationen bereit.

Zielrouten:

    GET /api/v1/vplib/library/blocks
    GET /api/v1/vplib/library/blocks/<block_id>
    GET /api/v1/vplib/library/blocks/<block_id>/variants
    GET /api/v1/vplib/library/tree

Diese Datei baut auf dem Scan Service auf:

    library_scan_service.scan_library_source()
      -> Discovery
      -> Reader
      -> Validation
      -> Fingerprint
      -> Items
      -> Index

Der Block Service ist die fachliche Zugriffsschicht auf diesen Index.

Wichtige Grenzen:

- keine Flask-Abhängigkeit
- keine Datenbank
- kein Schreiben
- kein Kopieren nach `creative_library`
- keine UI-Logik
- kein automatischer Scan beim Import

Taxonomie-Regel:

    Backend-Taxonomie ist kanonisch für:
    - Domain/Reiter
    - Kategorie
    - Subkategorie
    - Labels
    - Source-Pfade
    - Tree-Sortierung

Version 0.2.0:

- Block-Service-Optionen enthalten Taxonomieflags.
- Options werden an `LibraryScanServiceOptions` weitergereicht.
- Listenroute unterstützt domain/category/subcategory/object_kind/q.
- Tree kann leere Backend-Taxonomie-Knoten anzeigen.
- Detail- und Variantenantworten bewahren Taxonomie-Metadaten.
- Health enthält Taxonomie- und Scan-Service-Status.
- Rückwärtskompatibilität zu älteren Scan-/Index-/Detail-Builder-Signaturen.
"""

from __future__ import annotations

import traceback
from collections.abc import Iterable, Mapping
from dataclasses import asdict, dataclass, field, is_dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Final


# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

LIBRARY_BLOCK_SERVICE_VERSION: Final[str] = "0.2.0"
LIBRARY_BLOCK_SERVICE_COMPONENT: Final[str] = "library-block-service"

DEFAULT_BLOCK_SERVICE_STATUS: Final[str] = "unknown"

BLOCK_SERVICE_STATUS_VALUES: Final[tuple[str, ...]] = (
    "unknown",
    "ok",
    "healthy",
    "unavailable",
    "not_found",
    "empty",
    "partial",
    "invalid",
    "error",
)

DEFAULT_BLOCK_LIST_LIMIT: Final[int] = 500
MAX_BLOCK_LIST_LIMIT: Final[int] = 5000
DEFAULT_SCAN_CACHE_TTL_SECONDS: Final[int] = 5

UNKNOWN_TAXONOMY_VALUE: Final[str] = "unknown"


# ---------------------------------------------------------------------------
# Generic helpers
# ---------------------------------------------------------------------------

def utc_now_iso() -> str:
    """UTC-Zeit im ISO-Format."""
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

        if hasattr(value, "to_dict") and callable(value.to_dict):
            try:
                return json_safe(value.to_dict())
            except TypeError:
                return json_safe(value.to_dict(flat=True))

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

        if isinstance(value, bytes):
            text = value.decode("utf-8", errors="replace").strip()
        else:
            text = str(value).strip()

        return text if text else default

    except Exception:
        return default


def safe_bool(value: Any, *, default: bool = False) -> bool:
    """Robuste Bool-Konvertierung."""
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


def safe_path_str(value: Any) -> str | None:
    """Wandelt Pfade defensiv in Strings."""
    try:
        if value is None:
            return None

        if isinstance(value, Path):
            return str(value)

        text = str(value).strip()
        return text or None

    except Exception:
        return None


def ensure_mapping(value: Any) -> dict[str, Any]:
    """Normalisiert Mapping-artige Werte zu dict."""
    try:
        if value is None:
            return {}

        if isinstance(value, Mapping):
            return dict(value)

        if is_dataclass(value):
            return asdict(value)

        to_dict = getattr(value, "to_dict", None)
        if callable(to_dict):
            try:
                raw = to_dict()
            except TypeError:
                raw = to_dict(flat=True)
            return dict(raw) if isinstance(raw, Mapping) else {}

        return {}

    except Exception:
        return {}


def tuple_of_strings(value: Any) -> tuple[str, ...]:
    """Normalisiert Werte zu tuple[str, ...]."""
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


def normalize_stable_id(value: Any, *, fallback: str | None = None) -> str:
    """Lokale stabile ID-Normalisierung."""
    try:
        text = safe_str(value, default="").lower()
        text = text.replace("/", ".").replace("\\", ".").replace(" ", "_")
        text = "".join(ch for ch in text if ch.isalnum() or ch in "._:-")
        text = text.strip("._:-")

        if text:
            return text

        if fallback is not None:
            fallback_text = safe_str(fallback, default="").lower()
            fallback_text = fallback_text.replace("/", ".").replace("\\", ".").replace(" ", "_")
            fallback_text = "".join(ch for ch in fallback_text if ch.isalnum() or ch in "._:-")
            return fallback_text.strip("._:-")

        return ""

    except Exception:
        return ""


def normalize_filter_value(value: Any) -> str | None:
    """Normalisiert optionale Filterwerte."""
    if isinstance(value, (list, tuple)):
        value = value[0] if value else None

    text = safe_str(value, default="")
    return text or None


def normalize_service_status(value: Any) -> str:
    """Normalisiert Block-Service-Status."""
    try:
        text = safe_str(value, default=DEFAULT_BLOCK_SERVICE_STATUS).lower()

        if text in BLOCK_SERVICE_STATUS_VALUES:
            return text

        return DEFAULT_BLOCK_SERVICE_STATUS

    except Exception:
        return DEFAULT_BLOCK_SERVICE_STATUS


def get_attr_or_key(value: Any, key: str, *, default: Any = None) -> Any:
    """Liest Mapping-Key oder Attribut."""
    try:
        if value is None:
            return default

        if isinstance(value, Mapping):
            return value.get(key, default)

        return getattr(value, key, default)

    except Exception:
        return default


def deep_get(value: Any, path: str, *, default: Any = None) -> Any:
    """Liest dotted-path aus Mapping/Objekt."""
    current = value

    try:
        for part in path.split("."):
            if current is None:
                return default

            if isinstance(current, Mapping):
                current = current.get(part, default)
            else:
                current = getattr(current, part, default)

        return current
    except Exception:
        return default


def parse_limit(value: Any, *, default: int = DEFAULT_BLOCK_LIST_LIMIT) -> int:
    """Parst Limit für Listenrouten."""
    return safe_int(value, default=default, minimum=1, maximum=MAX_BLOCK_LIST_LIMIT)


def parse_offset(value: Any, *, default: int = 0) -> int:
    """Parst Offset für Listenrouten."""
    return safe_int(value, default=default, minimum=0)


def parse_force_refresh(value: Any) -> bool:
    """Parst force_refresh Query-Wert."""
    return safe_bool(value, default=False)


def get_item_id(item: Any) -> str | None:
    """Extrahiert stabile Item-ID."""
    value = (
        get_attr_or_key(item, "id")
        or get_attr_or_key(item, "family_id")
        or get_attr_or_key(item, "package_id")
        or get_attr_or_key(item, "slug")
    )
    normalized = normalize_stable_id(value)
    return normalized or None


def get_item_status(item: Any) -> str:
    """Extrahiert Item-Status."""
    return safe_str(get_attr_or_key(item, "status"), default="unknown").lower()


def get_item_taxonomy(item: Any) -> dict[str, Any]:
    """Extrahiert Taxonomie-Daten aus Item/Summary."""
    taxonomy = ensure_mapping(get_attr_or_key(item, "taxonomy"))

    if taxonomy:
        return taxonomy

    metadata = ensure_mapping(get_attr_or_key(item, "metadata"))
    taxonomy = ensure_mapping(metadata.get("taxonomy"))

    if taxonomy:
        return taxonomy

    return {
        "domain": get_attr_or_key(item, "domain"),
        "category": get_attr_or_key(item, "category"),
        "subcategory": get_attr_or_key(item, "subcategory"),
        "object_kind": get_attr_or_key(item, "object_kind"),
    }


def item_to_summary(item: Any) -> dict[str, Any]:
    """Serialisiert ein Item robust als Summary."""
    try:
        if hasattr(item, "to_summary_dict") and callable(item.to_summary_dict):
            raw = item.to_summary_dict()
            summary = dict(raw) if isinstance(raw, Mapping) else {"value": raw}
        elif hasattr(item, "to_dict") and callable(item.to_dict):
            raw = item.to_dict()
            summary = dict(raw) if isinstance(raw, Mapping) else {"value": raw}
        elif isinstance(item, Mapping):
            summary = dict(item)
        else:
            summary = {
                "id": get_item_id(item),
                "family_id": get_attr_or_key(item, "family_id"),
                "package_id": get_attr_or_key(item, "package_id"),
                "label": get_attr_or_key(item, "label"),
                "status": get_item_status(item),
                "object_kind": get_attr_or_key(item, "object_kind"),
            }

        taxonomy = get_item_taxonomy(summary)
        summary.setdefault("domain", taxonomy.get("domain"))
        summary.setdefault("category", taxonomy.get("category"))
        summary.setdefault("subcategory", taxonomy.get("subcategory"))
        summary.setdefault("taxonomy", taxonomy)

        return json_safe(summary)

    except Exception as exc:
        return {
            "status": "error",
            "error": exception_to_dict(exc),
        }


def item_matches_id(item: Any, block_id: Any) -> bool:
    """Prüft, ob ein Item zu einer Block-ID passt."""
    normalized = normalize_stable_id(block_id)

    if not normalized:
        return False

    try:
        candidates = {
            normalize_stable_id(get_attr_or_key(item, "id")),
            normalize_stable_id(get_attr_or_key(item, "family_id")),
            normalize_stable_id(get_attr_or_key(item, "package_id")),
            normalize_stable_id(get_attr_or_key(item, "slug")),
            normalize_stable_id(get_attr_or_key(item, "display_id")),
        }

        return normalized in {candidate for candidate in candidates if candidate}

    except Exception:
        return False


def item_matches_filter(
    item: Any,
    *,
    domain: Any = None,
    category: Any = None,
    subcategory: Any = None,
    object_kind: Any = None,
    q: Any = None,
) -> bool:
    """Prüft lokale Filter auf Item/Summary."""
    summary = item_to_summary(item)
    taxonomy = ensure_mapping(summary.get("taxonomy"))

    item_domain = safe_str(summary.get("domain") or taxonomy.get("domain"), default="")
    item_category = safe_str(summary.get("category") or taxonomy.get("category"), default="")
    item_subcategory = safe_str(summary.get("subcategory") or taxonomy.get("subcategory"), default="")
    item_object_kind = safe_str(summary.get("object_kind") or taxonomy.get("object_kind"), default="")

    domain_filter = normalize_filter_value(domain)
    category_filter = normalize_filter_value(category)
    subcategory_filter = normalize_filter_value(subcategory)
    object_kind_filter = normalize_filter_value(object_kind)
    query = safe_str(q, default="").lower()

    if domain_filter and item_domain != domain_filter:
        return False

    if category_filter and item_category != category_filter:
        return False

    if subcategory_filter and item_subcategory != subcategory_filter:
        return False

    if object_kind_filter and item_object_kind != object_kind_filter:
        return False

    if query:
        haystack = " ".join(
            [
                safe_str(summary.get("id"), default=""),
                safe_str(summary.get("family_id"), default=""),
                safe_str(summary.get("package_id"), default=""),
                safe_str(summary.get("label"), default=""),
                safe_str(summary.get("description"), default=""),
                item_domain,
                item_category,
                item_subcategory,
                item_object_kind,
            ]
        ).lower()

        if query not in haystack:
            return False

    return True


def get_index_items(index: Any) -> list[Any]:
    """Extrahiert Items aus einem Index-Objekt oder Mapping."""
    try:
        if index is None:
            return []

        if isinstance(index, Mapping):
            items = index.get("items")
            if isinstance(items, Iterable) and not isinstance(items, (str, bytes, Mapping)):
                return list(items)

            items_by_id = index.get("items_by_id")
            if isinstance(items_by_id, Mapping):
                return list(items_by_id.values())

            return []

        items = get_attr_or_key(index, "items", default=None)
        if isinstance(items, Iterable) and not isinstance(items, (str, bytes, Mapping)):
            return list(items)

        items_by_id = get_attr_or_key(index, "items_by_id", default=None)
        if isinstance(items_by_id, Mapping):
            return list(items_by_id.values())

    except Exception:
        return []

    return []


def find_library_item_by_id(index: Any, block_id: Any) -> Any | None:
    """Sucht ein Item in Index/Mappings per ID."""
    normalized_id = normalize_stable_id(block_id)

    if not normalized_id:
        return None

    try:
        if isinstance(index, Mapping):
            items_by_id = index.get("items_by_id")
            if isinstance(items_by_id, Mapping) and normalized_id in items_by_id:
                return items_by_id[normalized_id]

            for item in index.get("items") or ():
                if item_matches_id(item, normalized_id):
                    return item

        items = get_index_items(index)
        for item in items:
            if item_matches_id(item, normalized_id):
                return item

    except Exception:
        return None

    return None


def extract_documents_from_read_result(read_result: Any) -> dict[str, Any]:
    """Extrahiert Dokumente aus einem PackageReadResult-ähnlichen Objekt."""
    try:
        if read_result is None:
            return {}

        if isinstance(read_result, Mapping):
            documents = read_result.get("documents")
            if isinstance(documents, Mapping):
                return dict(documents)

        documents = get_attr_or_key(read_result, "documents", default=None)

        if isinstance(documents, Mapping):
            return dict(documents)

        if isinstance(documents, Iterable) and not isinstance(documents, (str, bytes)):
            result: dict[str, Any] = {}

            for document in documents:
                key = (
                    get_attr_or_key(document, "key")
                    or get_attr_or_key(document, "document_key")
                    or get_attr_or_key(document, "path")
                    or get_attr_or_key(document, "relative_path")
                )
                content = (
                    get_attr_or_key(document, "content")
                    or get_attr_or_key(document, "data")
                    or get_attr_or_key(document, "json_data")
                    or get_attr_or_key(document, "payload")
                )
                normalized_key = safe_str(key, default="")

                if normalized_key:
                    result[normalized_key] = content

            return result

    except Exception:
        return {}

    return {}


def read_result_matches_id(read_result: Any, block_id: Any) -> bool:
    """Prüft defensiv, ob ein ReadResult zu einer Block-ID passt."""
    normalized = normalize_stable_id(block_id)

    if not normalized:
        return False

    try:
        documents = extract_documents_from_read_result(read_result)
        manifest = ensure_mapping(documents.get("vplib.manifest.json"))
        identity = ensure_mapping(documents.get("family/identity.json"))

        candidates = {
            normalize_stable_id(get_attr_or_key(read_result, "id")),
            normalize_stable_id(get_attr_or_key(read_result, "item_id")),
            normalize_stable_id(get_attr_or_key(read_result, "family_id")),
            normalize_stable_id(get_attr_or_key(read_result, "package_id")),
            normalize_stable_id(manifest.get("family_id")),
            normalize_stable_id(manifest.get("package_id")),
            normalize_stable_id(manifest.get("id")),
            normalize_stable_id(identity.get("family_id")),
            normalize_stable_id(identity.get("id")),
        }

        return normalized in {candidate for candidate in candidates if candidate}

    except Exception:
        return False


def find_matching_read_result(
    block_id: Any,
    *,
    read_results: Iterable[Any],
    items: Iterable[Any] | None = None,
) -> Any | None:
    """Findet das passende ReadResult zu einer Block-ID."""
    normalized = normalize_stable_id(block_id)

    if not normalized:
        return None

    read_result_list = list(read_results or ())
    item_list = list(items or ())

    try:
        for index, item in enumerate(item_list):
            if item_matches_id(item, normalized) and index < len(read_result_list):
                return read_result_list[index]
    except Exception:
        pass

    try:
        for read_result in read_result_list:
            if read_result_matches_id(read_result, normalized):
                return read_result
    except Exception:
        pass

    return None


def normalize_variant_payloads(value: Any) -> list[dict[str, Any]]:
    """Normalisiert verschiedene Variantenindex-Formen zu einer Liste von Dicts."""
    result: list[dict[str, Any]] = []

    try:
        if value is None:
            return result

        if isinstance(value, Mapping):
            for key, item in value.items():
                item_data = ensure_mapping(item)
                variant_id = item_data.get("variant_id") or item_data.get("id") or key
                normalized_id = normalize_stable_id(variant_id, fallback=safe_str(key, default="default"))

                if not normalized_id:
                    continue

                payload = dict(item_data)
                payload.setdefault("variant_id", normalized_id)
                payload.setdefault("id", normalized_id)
                result.append(payload)

            return result

        if isinstance(value, str):
            normalized = normalize_stable_id(value, fallback="default")
            return [{"variant_id": normalized, "id": normalized}] if normalized else []

        if isinstance(value, Iterable):
            for item in value:
                if isinstance(item, Mapping):
                    item_data = dict(item)
                    variant_id = item_data.get("variant_id") or item_data.get("id") or item_data.get("slug")
                    normalized_id = normalize_stable_id(variant_id, fallback="default")
                    if normalized_id:
                        item_data.setdefault("variant_id", normalized_id)
                        item_data.setdefault("id", normalized_id)
                        result.append(item_data)
                else:
                    normalized_id = normalize_stable_id(item, fallback="")
                    if normalized_id:
                        result.append({"variant_id": normalized_id, "id": normalized_id})

            return result

    except Exception:
        return result

    return result


def paginate_items(
    items: Iterable[Any],
    *,
    limit: int = DEFAULT_BLOCK_LIST_LIMIT,
    offset: int = 0,
) -> tuple[list[Any], dict[str, Any]]:
    """Paginiert Items."""
    try:
        item_list = list(items or ())
    except Exception:
        item_list = []

    safe_limit = parse_limit(limit)
    safe_offset = parse_offset(offset)

    sliced = item_list[safe_offset:safe_offset + safe_limit]

    return sliced, {
        "limit": safe_limit,
        "offset": safe_offset,
        "total": len(item_list),
        "count": len(sliced),
        "has_more": safe_offset + safe_limit < len(item_list),
    }


# ---------------------------------------------------------------------------
# Optional imports
# ---------------------------------------------------------------------------

_SCAN_SERVICE_IMPORT_ERROR: BaseException | None = None
_INDEX_IMPORT_ERROR: BaseException | None = None
_DETAIL_IMPORT_ERROR: BaseException | None = None
_TAXONOMY_IMPORT_ERROR: BaseException | None = None

try:
    from library.services.library_scan_service import (
        LibraryScanPipelineResult,
        LibraryScanServiceOptions,
        get_taxonomy_health_safe,
        scan_library_source,
    )
except Exception as import_exc:  # pragma: no cover - defensive fallback
    _SCAN_SERVICE_IMPORT_ERROR = import_exc

    LibraryScanPipelineResult = Any  # type: ignore[assignment]

    @dataclass(frozen=True)
    class LibraryScanServiceOptions:  # type: ignore[no-redef]
        include_invalid: bool = True
        enabled_only: bool = False
        use_cache: bool = False
        cache_ttl_seconds: int = DEFAULT_SCAN_CACHE_TTL_SECONDS
        refresh_settings: bool = False
        include_raw_pipeline: bool = False
        include_index: bool = True
        include_scan_result: bool = True
        include_discovery_result: bool = True
        include_read_results: bool = False
        include_validation_results: bool = False
        include_fingerprint_results: bool = False
        strict_errors: bool = False
        validate_taxonomy: bool = True
        require_taxonomy: bool = True
        use_taxonomy_labels: bool = True
        include_empty_taxonomy_nodes: bool = False
        include_inactive_taxonomy_nodes: bool = False
        include_taxonomy_payload: bool = False
        force_taxonomy_reload: bool = False

        def to_dict(self) -> dict[str, Any]:
            return asdict(self)

    def scan_library_source(*args: Any, **kwargs: Any) -> Any:
        raise RuntimeError(f"library scan service is unavailable: {_SCAN_SERVICE_IMPORT_ERROR}")

    def get_taxonomy_health_safe(*args: Any, **kwargs: Any) -> dict[str, Any]:
        return {
            "ok": False,
            "healthy": False,
            "available": False,
            "error": exception_to_dict(_SCAN_SERVICE_IMPORT_ERROR),
        }


try:
    from library.read_models.library_index_builder import (
        LibraryIndex,
        build_blocks_response_from_index,
        build_tree_response_from_index,
    )
except Exception as import_exc:  # pragma: no cover - defensive fallback
    _INDEX_IMPORT_ERROR = import_exc
    LibraryIndex = Any  # type: ignore[assignment]

    def build_blocks_response_from_index(index: Any, **kwargs: Any) -> dict[str, Any]:
        try:
            items = get_index_items(index)
            filtered = [
                item
                for item in items
                if item_matches_filter(
                    item,
                    domain=kwargs.get("domain"),
                    category=kwargs.get("category"),
                    subcategory=kwargs.get("subcategory"),
                    object_kind=kwargs.get("object_kind"),
                    q=kwargs.get("q"),
                )
            ]
            return {
                "ok": True,
                "status": "ok" if filtered else "empty",
                "count": len(filtered),
                "items": [item_to_summary(item) for item in filtered],
                "filters": {
                    "domain": kwargs.get("domain"),
                    "category": kwargs.get("category"),
                    "subcategory": kwargs.get("subcategory"),
                    "object_kind": kwargs.get("object_kind"),
                    "q": kwargs.get("q"),
                },
            }
        except Exception as exc:
            return {
                "ok": False,
                "status": "error",
                "count": 0,
                "items": [],
                "errors": [str(exc)],
            }

    def build_tree_response_from_index(index: Any) -> dict[str, Any]:
        try:
            items = get_index_items(index)
            tree: dict[str, Any] = {}

            for item in items:
                summary = item_to_summary(item)
                taxonomy = ensure_mapping(summary.get("taxonomy"))
                domain = safe_str(summary.get("domain") or taxonomy.get("domain"), default=UNKNOWN_TAXONOMY_VALUE)
                category = safe_str(summary.get("category") or taxonomy.get("category"), default=UNKNOWN_TAXONOMY_VALUE)
                subcategory = safe_str(summary.get("subcategory") or taxonomy.get("subcategory"), default=UNKNOWN_TAXONOMY_VALUE)
                item_id = safe_str(summary.get("id"), default="")

                tree.setdefault(domain, {})
                tree[domain].setdefault(category, {})
                tree[domain][category].setdefault(subcategory, [])

                if item_id:
                    tree[domain][category][subcategory].append(summary)

            return {
                "ok": True,
                "status": "ok" if items else "empty",
                "tree": tree,
                "count": len(items),
            }

        except Exception as exc:
            return {
                "ok": False,
                "status": "error",
                "tree": {},
                "errors": [str(exc)],
            }


try:
    from library.read_models.block_detail_builder import (
        BlockDetailBuilderOptions,
        build_block_detail_response_by_id,
        build_block_variants_response_from_parts,
    )
except Exception as import_exc:  # pragma: no cover - defensive fallback
    _DETAIL_IMPORT_ERROR = import_exc

    @dataclass(frozen=True)
    class BlockDetailBuilderOptions:  # type: ignore[no-redef]
        include_raw_documents: bool = True
        include_document_groups: bool = True
        include_validation_raw: bool = True
        include_fingerprint: bool = True
        include_profiles: bool = True
        include_metadata: bool = True
        include_taxonomy: bool = True
        force_taxonomy_reload: bool = False
        fail_on_id_mismatch: bool = False

        def to_dict(self) -> dict[str, Any]:
            return asdict(self)

    def build_block_detail_response_by_id(
        block_id: Any,
        *,
        read_results: Iterable[Any],
        validation_results: Iterable[Any] | None = None,
        fingerprint_results: Iterable[Any] | None = None,
        items: Iterable[Any] | None = None,
        options: Any = None,
    ) -> dict[str, Any]:
        normalized_id = normalize_stable_id(block_id, fallback=safe_str(block_id, default="unknown"))
        matched_item = None

        try:
            for item in items or ():
                if item_matches_id(item, normalized_id):
                    matched_item = item
                    break

            if matched_item is None:
                return {
                    "ok": False,
                    "status": "not_found",
                    "block_id": normalized_id,
                    "item": None,
                    "errors": [f"library block not found: {normalized_id}"],
                }

            return {
                "ok": True,
                "status": "ok",
                "block_id": normalized_id,
                "item": item_to_summary(matched_item),
            }

        except Exception as exc:
            return {
                "ok": False,
                "status": "error",
                "block_id": normalized_id,
                "item": None,
                "errors": [str(exc)],
            }

    def build_block_variants_response_from_parts(
        *,
        read_result: Any = None,
        documents: Mapping[str, Any] | None = None,
        block_id: Any = None,
    ) -> dict[str, Any]:
        normalized_id = normalize_stable_id(block_id, fallback=safe_str(block_id, default="unknown"))

        try:
            docs = ensure_mapping(documents) or extract_documents_from_read_result(read_result)
            variants_index = ensure_mapping(docs.get("variants/index.json"))
            default_variant = ensure_mapping(docs.get("variants/default.json"))

            raw_variants = (
                variants_index.get("variants")
                or variants_index.get("variant_ids")
                or variants_index.get("items")
                or []
            )

            variants = normalize_variant_payloads(raw_variants)

            if not variants and default_variant:
                variants = [default_variant]

            if not variants:
                default_variant_id = (
                    variants_index.get("default_variant_id")
                    or variants_index.get("default")
                    or default_variant.get("variant_id")
                    or default_variant.get("id")
                    or "default"
                )
                variants = [{"variant_id": normalize_stable_id(default_variant_id, fallback="default")}]

            return {
                "ok": True,
                "status": "ok",
                "block_id": normalized_id,
                "count": len(variants),
                "variants": variants,
            }

        except Exception as exc:
            return {
                "ok": False,
                "status": "error",
                "block_id": normalized_id,
                "count": 0,
                "variants": [],
                "errors": [str(exc)],
            }


try:
    from library.taxonomy import get_default_taxonomy_service
except Exception as import_exc:  # pragma: no cover - defensive fallback
    _TAXONOMY_IMPORT_ERROR = import_exc
    get_default_taxonomy_service = None  # type: ignore[assignment]


# ---------------------------------------------------------------------------
# Options / result
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class LibraryBlockServiceOptions:
    """Optionen für blockbezogene Servicezugriffe."""

    use_cache: bool = False
    force_refresh: bool = False
    include_invalid: bool = False
    enabled_only: bool = False
    include_raw_pipeline: bool = False
    include_raw_documents: bool = True
    include_profiles: bool = True
    include_metadata: bool = True
    strict_errors: bool = False
    limit: int = DEFAULT_BLOCK_LIST_LIMIT
    offset: int = 0

    validate_taxonomy: bool = True
    require_taxonomy: bool = True
    use_taxonomy_labels: bool = True
    include_empty_taxonomy_nodes: bool = False
    include_inactive_taxonomy_nodes: bool = False
    include_taxonomy_payload: bool = False
    force_taxonomy_reload: bool = False

    def __post_init__(self) -> None:
        object.__setattr__(self, "use_cache", safe_bool(self.use_cache, default=False))
        object.__setattr__(self, "force_refresh", safe_bool(self.force_refresh, default=False))
        object.__setattr__(self, "include_invalid", safe_bool(self.include_invalid, default=False))
        object.__setattr__(self, "enabled_only", safe_bool(self.enabled_only, default=False))
        object.__setattr__(self, "include_raw_pipeline", safe_bool(self.include_raw_pipeline, default=False))
        object.__setattr__(self, "include_raw_documents", safe_bool(self.include_raw_documents, default=True))
        object.__setattr__(self, "include_profiles", safe_bool(self.include_profiles, default=True))
        object.__setattr__(self, "include_metadata", safe_bool(self.include_metadata, default=True))
        object.__setattr__(self, "strict_errors", safe_bool(self.strict_errors, default=False))
        object.__setattr__(self, "limit", parse_limit(self.limit))
        object.__setattr__(self, "offset", parse_offset(self.offset))

        object.__setattr__(self, "validate_taxonomy", safe_bool(self.validate_taxonomy, default=True))
        object.__setattr__(self, "require_taxonomy", safe_bool(self.require_taxonomy, default=True))
        object.__setattr__(self, "use_taxonomy_labels", safe_bool(self.use_taxonomy_labels, default=True))
        object.__setattr__(self, "include_empty_taxonomy_nodes", safe_bool(self.include_empty_taxonomy_nodes, default=False))
        object.__setattr__(self, "include_inactive_taxonomy_nodes", safe_bool(self.include_inactive_taxonomy_nodes, default=False))
        object.__setattr__(self, "include_taxonomy_payload", safe_bool(self.include_taxonomy_payload, default=False))
        object.__setattr__(self, "force_taxonomy_reload", safe_bool(self.force_taxonomy_reload, default=False))

        if self.force_refresh:
            object.__setattr__(self, "use_cache", False)

    def to_scan_options(
        self,
        *,
        include_read_artifacts: bool = False,
        include_scan_payload: bool = False,
    ) -> Any:
        """Wandelt Block-Service-Optionen in Scan-Service-Optionen um."""
        include_artifacts = bool(include_read_artifacts or self.include_raw_pipeline)

        attempts = (
            {
                "include_invalid": self.include_invalid,
                "enabled_only": self.enabled_only,
                "use_cache": self.use_cache,
                "cache_ttl_seconds": DEFAULT_SCAN_CACHE_TTL_SECONDS,
                "refresh_settings": False,
                "include_raw_pipeline": self.include_raw_pipeline,
                "include_index": True,
                "include_scan_result": bool(include_scan_payload),
                "include_discovery_result": bool(include_scan_payload),
                "include_read_results": include_artifacts,
                "include_validation_results": include_artifacts,
                "include_fingerprint_results": include_artifacts,
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
                "cache_ttl_seconds": DEFAULT_SCAN_CACHE_TTL_SECONDS,
                "include_raw_pipeline": self.include_raw_pipeline,
                "include_index": True,
                "include_scan_result": bool(include_scan_payload),
                "include_discovery_result": bool(include_scan_payload),
                "include_read_results": include_artifacts,
                "include_validation_results": include_artifacts,
                "include_fingerprint_results": include_artifacts,
                "strict_errors": self.strict_errors,
            },
            {},
        )

        for kwargs in attempts:
            try:
                return LibraryScanServiceOptions(**kwargs)
            except Exception:
                continue

        return LibraryScanServiceOptions()

    def to_detail_options(self) -> Any:
        """Wandelt Block-Service-Optionen in Detail-Builder-Optionen um."""
        attempts = (
            {
                "include_raw_documents": self.include_raw_documents,
                "include_document_groups": True,
                "include_validation_raw": True,
                "include_fingerprint": True,
                "include_profiles": self.include_profiles,
                "include_metadata": self.include_metadata,
                "include_taxonomy": True,
                "force_taxonomy_reload": self.force_taxonomy_reload,
                "fail_on_id_mismatch": False,
            },
            {
                "include_raw_documents": self.include_raw_documents,
                "include_document_groups": True,
                "include_validation_raw": True,
                "include_fingerprint": True,
                "include_profiles": self.include_profiles,
                "include_metadata": self.include_metadata,
                "fail_on_id_mismatch": False,
            },
            {},
        )

        for kwargs in attempts:
            try:
                return BlockDetailBuilderOptions(**kwargs)
            except Exception:
                continue

        return BlockDetailBuilderOptions()

    def to_dict(self) -> dict[str, Any]:
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
            "validate_taxonomy": self.validate_taxonomy,
            "require_taxonomy": self.require_taxonomy,
            "use_taxonomy_labels": self.use_taxonomy_labels,
            "include_empty_taxonomy_nodes": self.include_empty_taxonomy_nodes,
            "include_inactive_taxonomy_nodes": self.include_inactive_taxonomy_nodes,
            "include_taxonomy_payload": self.include_taxonomy_payload,
            "force_taxonomy_reload": self.force_taxonomy_reload,
        }


def coerce_block_service_options(value: Any = None) -> LibraryBlockServiceOptions:
    """Normalisiert beliebige Optionswerte auf `LibraryBlockServiceOptions`."""
    try:
        if isinstance(value, LibraryBlockServiceOptions):
            return value

        if value is None:
            return LibraryBlockServiceOptions()

        data = ensure_mapping(value)

        if not data:
            to_dict = getattr(value, "to_dict", None)
            if callable(to_dict):
                data = ensure_mapping(to_dict())

        if not data:
            return LibraryBlockServiceOptions()

        allowed = {
            "use_cache",
            "force_refresh",
            "include_invalid",
            "enabled_only",
            "include_raw_pipeline",
            "include_raw_documents",
            "include_profiles",
            "include_metadata",
            "strict_errors",
            "limit",
            "offset",
            "validate_taxonomy",
            "require_taxonomy",
            "use_taxonomy_labels",
            "include_empty_taxonomy_nodes",
            "include_inactive_taxonomy_nodes",
            "include_taxonomy_payload",
            "force_taxonomy_reload",
        }

        return LibraryBlockServiceOptions(
            **{key: item for key, item in data.items() if key in allowed}
        )

    except Exception:
        return LibraryBlockServiceOptions()


@dataclass(frozen=True)
class LibraryBlockServiceResult:
    """Generisches Ergebnis eines Block-Service-Zugriffs."""

    ok: bool
    status: str
    data: dict[str, Any] = field(default_factory=dict)
    block_id: str | None = None
    generated_at: str = field(default_factory=utc_now_iso)
    warnings: tuple[str, ...] = field(default_factory=tuple)
    errors: tuple[str, ...] = field(default_factory=tuple)
    options: LibraryBlockServiceOptions = field(default_factory=LibraryBlockServiceOptions)
    metadata: dict[str, Any] = field(default_factory=dict)
    version: str = LIBRARY_BLOCK_SERVICE_VERSION

    def __post_init__(self) -> None:
        status = normalize_service_status(self.status)
        warnings = tuple_of_strings(self.warnings)
        errors = tuple_of_strings(self.errors)

        if status == "unknown":
            if errors:
                status = "error"
            elif self.ok:
                status = "ok"
            else:
                status = "error"

        object.__setattr__(self, "ok", bool(self.ok and status not in {"error", "not_found", "invalid", "unavailable"}))
        object.__setattr__(self, "status", status)
        object.__setattr__(self, "block_id", normalize_stable_id(self.block_id) or None)
        object.__setattr__(self, "generated_at", safe_str(self.generated_at, default=utc_now_iso()))
        object.__setattr__(self, "warnings", warnings)
        object.__setattr__(self, "errors", errors)
        object.__setattr__(self, "data", dict(self.data or {}))
        object.__setattr__(self, "metadata", dict(self.metadata or {}))
        object.__setattr__(self, "options", coerce_block_service_options(self.options))
        object.__setattr__(self, "version", safe_str(self.version, default=LIBRARY_BLOCK_SERVICE_VERSION))

    def to_dict(self) -> dict[str, Any]:
        result: dict[str, Any] = {
            "ok": self.ok,
            "status": self.status,
            "generated_at": self.generated_at,
            "warnings": list(self.warnings),
            "errors": list(self.errors),
            "version": self.version,
        }

        if self.block_id:
            result["block_id"] = self.block_id

        result.update(json_safe(self.data))

        if self.options.include_metadata:
            result["metadata"] = json_safe(self.metadata)
            result["options"] = self.options.to_dict()

        return result

    @classmethod
    def error(
        cls,
        exc: BaseException,
        *,
        block_id: Any = None,
        options: LibraryBlockServiceOptions | Mapping[str, Any] | None = None,
        include_traceback: bool = False,
        data: Mapping[str, Any] | None = None,
    ) -> "LibraryBlockServiceResult":
        service_options = coerce_block_service_options(options)
        error_data = exception_to_dict(exc, include_traceback=include_traceback)
        message = safe_str(
            error_data.get("message") if error_data else None,
            default="library block service failed",
        )

        return cls(
            ok=False,
            status="error",
            data=dict(data or {}),
            block_id=normalize_stable_id(block_id) if block_id is not None else None,
            warnings=(),
            errors=(message,),
            options=service_options,
            metadata={"exception": error_data},
        )

    @classmethod
    def not_found(
        cls,
        block_id: Any,
        *,
        options: LibraryBlockServiceOptions | Mapping[str, Any] | None = None,
    ) -> "LibraryBlockServiceResult":
        service_options = coerce_block_service_options(options)
        normalized = normalize_stable_id(block_id, fallback=safe_str(block_id, default="unknown"))

        return cls(
            ok=False,
            status="not_found",
            data={"item": None},
            block_id=normalized,
            warnings=(),
            errors=(f"library block not found: {normalized}",),
            options=service_options,
            metadata={},
        )


# ---------------------------------------------------------------------------
# Pipeline helpers
# ---------------------------------------------------------------------------

def get_pipeline_read_results(pipeline: Any) -> tuple[Any, ...]:
    return tuple(get_attr_or_key(pipeline, "read_results", default=()) or ())


def get_pipeline_validation_results(pipeline: Any) -> tuple[Any, ...]:
    return tuple(get_attr_or_key(pipeline, "validation_results", default=()) or ())


def get_pipeline_fingerprint_results(pipeline: Any) -> tuple[Any, ...]:
    return tuple(get_attr_or_key(pipeline, "fingerprint_results", default=()) or ())


def get_pipeline_items(pipeline: Any) -> tuple[Any, ...]:
    return tuple(get_attr_or_key(pipeline, "items", default=()) or ())


def get_pipeline_index(pipeline: Any) -> Any:
    return (
        get_attr_or_key(pipeline, "index")
        or get_attr_or_key(pipeline, "library_index")
        or get_attr_or_key(pipeline, "read_index")
    )


def get_pipeline_taxonomy_version(pipeline: Any) -> str | None:
    value = (
        get_attr_or_key(pipeline, "taxonomy_version")
        or deep_get(pipeline, "taxonomy.taxonomy_version")
        or deep_get(pipeline, "metadata.taxonomy_version")
    )
    text = safe_str(value, default="")
    return text or None


def scan_for_block_access(
    *,
    source_root: Any = None,
    options: LibraryBlockServiceOptions,
    include_read_artifacts: bool = False,
    include_scan_payload: bool = False,
) -> Any:
    """Führt Scan für Blockzugriffe aus."""
    return scan_library_source(
        source_root=source_root,
        options=options.to_scan_options(
            include_read_artifacts=include_read_artifacts,
            include_scan_payload=include_scan_payload,
        ),
        force_refresh=options.force_refresh,
    )


# ---------------------------------------------------------------------------
# Main service functions
# ---------------------------------------------------------------------------

def list_library_blocks(
    *,
    source_root: Any = None,
    domain: Any = None,
    category: Any = None,
    subcategory: Any = None,
    object_kind: Any = None,
    q: Any = None,
    options: LibraryBlockServiceOptions | Mapping[str, Any] | None = None,
) -> LibraryBlockServiceResult:
    """Listet gültige Creative-Library-Blöcke/-Objekte."""
    service_options = coerce_block_service_options(options)

    try:
        pipeline = scan_for_block_access(
            source_root=source_root,
            options=service_options,
            include_read_artifacts=False,
            include_scan_payload=False,
        )

        index = get_pipeline_index(pipeline)

        try:
            response = build_blocks_response_from_index(
                index,
                domain=domain,
                category=category,
                subcategory=subcategory,
                object_kind=object_kind,
                q=q,
            )
        except TypeError:
            response = build_blocks_response_from_index(index)

        response = ensure_mapping(response)
        raw_items = response.get("items") or []

        if isinstance(raw_items, Iterable) and not isinstance(raw_items, (str, bytes, Mapping)):
            filtered_items = [
                item
                for item in raw_items
                if item_matches_filter(
                    item,
                    domain=domain,
                    category=category,
                    subcategory=subcategory,
                    object_kind=object_kind,
                    q=q,
                )
            ]
        else:
            filtered_items = []

        paginated_items, pagination = paginate_items(
            filtered_items,
            limit=service_options.limit,
            offset=service_options.offset,
        )

        scan_errors = tuple_of_strings(get_attr_or_key(pipeline, "errors"))
        response_errors = tuple_of_strings(response.get("errors"))
        strict_errors = scan_errors + response_errors if service_options.strict_errors else ()

        taxonomy_payload = response.get("taxonomy") if isinstance(response.get("taxonomy"), Mapping) else {}

        data = {
            "source_root": safe_path_str(get_attr_or_key(pipeline, "source_root")),
            "count": len(paginated_items),
            "total_count": len(filtered_items),
            "items": [item_to_summary(item) for item in paginated_items],
            "pagination": pagination,
            "filters": {
                "domain": normalize_filter_value(domain),
                "category": normalize_filter_value(category),
                "subcategory": normalize_filter_value(subcategory),
                "object_kind": normalize_filter_value(object_kind),
                "q": normalize_filter_value(q),
            },
            "taxonomy_version": get_pipeline_taxonomy_version(pipeline) or safe_str(response.get("taxonomy_version"), default="") or None,
            "taxonomy": taxonomy_payload,
            "scan": {
                "status": get_attr_or_key(pipeline, "status"),
                "candidate_count": get_attr_or_key(pipeline, "candidate_count"),
                "canonical_candidate_count": get_attr_or_key(pipeline, "canonical_candidate_count"),
                "legacy_candidate_count": get_attr_or_key(pipeline, "legacy_candidate_count"),
                "read_count": get_attr_or_key(pipeline, "read_count"),
                "validation_count": get_attr_or_key(pipeline, "validation_count"),
                "fingerprint_count": get_attr_or_key(pipeline, "fingerprint_count"),
                "item_count": get_attr_or_key(pipeline, "item_count"),
                "valid_item_count": get_attr_or_key(pipeline, "valid_item_count"),
                "invalid_item_count": get_attr_or_key(pipeline, "invalid_item_count"),
                "duration_ms": get_attr_or_key(pipeline, "duration_ms"),
                "generated_at": get_attr_or_key(pipeline, "finished_at"),
            },
        }

        raw_status = safe_str(response.get("status"), default="")
        status = raw_status or ("ok" if filtered_items else "empty")

        if not filtered_items:
            status = "empty"

        if response.get("ok") is False and status == "ok":
            status = "partial"

        return LibraryBlockServiceResult(
            ok=status in {"ok", "partial", "empty"},
            status=status,
            data=data,
            warnings=tuple_of_strings(get_attr_or_key(pipeline, "warnings")) + tuple_of_strings(response.get("warnings")),
            errors=strict_errors,
            options=service_options,
            metadata={
                "pipeline_status": get_attr_or_key(pipeline, "status"),
                "raw_response_status": response.get("status"),
                "index_available": index is not None,
            },
        )

    except Exception as exc:
        return LibraryBlockServiceResult.error(
            exc,
            options=service_options,
        )


def get_library_block_detail(
    block_id: Any,
    *,
    source_root: Any = None,
    options: LibraryBlockServiceOptions | Mapping[str, Any] | None = None,
) -> LibraryBlockServiceResult:
    """Liefert Detaildaten eines Blocks/Objekts per stabiler ID."""
    service_options = coerce_block_service_options(options)
    normalized_id = normalize_stable_id(block_id, fallback=safe_str(block_id, default="unknown"))

    try:
        if not normalized_id:
            return LibraryBlockServiceResult.not_found(
                block_id,
                options=service_options,
            )

        pipeline = scan_for_block_access(
            source_root=source_root,
            options=service_options,
            include_read_artifacts=True,
            include_scan_payload=False,
        )

        response = build_block_detail_response_by_id(
            normalized_id,
            read_results=get_pipeline_read_results(pipeline),
            validation_results=get_pipeline_validation_results(pipeline),
            fingerprint_results=get_pipeline_fingerprint_results(pipeline),
            items=get_pipeline_items(pipeline),
            options=service_options.to_detail_options(),
        )

        response = ensure_mapping(response)

        if not response.get("ok"):
            status = safe_str(response.get("status"), default="not_found")

            if status == "not_found":
                return LibraryBlockServiceResult.not_found(
                    normalized_id,
                    options=service_options,
                )

            return LibraryBlockServiceResult(
                ok=False,
                status=status,
                data=response,
                block_id=normalized_id,
                warnings=tuple_of_strings(response.get("warnings")),
                errors=tuple_of_strings(response.get("errors")),
                options=service_options,
                metadata={
                    "pipeline_status": get_attr_or_key(pipeline, "status"),
                    "source_root": safe_path_str(get_attr_or_key(pipeline, "source_root")),
                    "taxonomy_version": get_pipeline_taxonomy_version(pipeline),
                },
            )

        response.setdefault("taxonomy_version", get_pipeline_taxonomy_version(pipeline))

        return LibraryBlockServiceResult(
            ok=True,
            status="ok",
            data=response,
            block_id=normalized_id,
            warnings=tuple_of_strings(response.get("warnings")),
            errors=tuple_of_strings(response.get("errors")) if service_options.strict_errors else (),
            options=service_options,
            metadata={
                "pipeline_status": get_attr_or_key(pipeline, "status"),
                "source_root": safe_path_str(get_attr_or_key(pipeline, "source_root")),
                "read_result_count": len(get_pipeline_read_results(pipeline)),
                "taxonomy_version": get_pipeline_taxonomy_version(pipeline),
            },
        )

    except Exception as exc:
        return LibraryBlockServiceResult.error(
            exc,
            block_id=normalized_id,
            options=service_options,
        )


def get_library_block_variants(
    block_id: Any,
    *,
    source_root: Any = None,
    options: LibraryBlockServiceOptions | Mapping[str, Any] | None = None,
) -> LibraryBlockServiceResult:
    """Liefert Varianten eines Blocks/Objekts per ID."""
    service_options = coerce_block_service_options(options)
    normalized_id = normalize_stable_id(block_id, fallback=safe_str(block_id, default="unknown"))

    try:
        if not normalized_id:
            return LibraryBlockServiceResult.not_found(
                block_id,
                options=service_options,
            )

        pipeline = scan_for_block_access(
            source_root=source_root,
            options=service_options,
            include_read_artifacts=True,
            include_scan_payload=False,
        )

        read_results = get_pipeline_read_results(pipeline)
        items = get_pipeline_items(pipeline)

        matching_read_result = find_matching_read_result(
            normalized_id,
            read_results=read_results,
            items=items,
        )

        if matching_read_result is None:
            return LibraryBlockServiceResult.not_found(
                normalized_id,
                options=service_options,
            )

        response = build_block_variants_response_from_parts(
            read_result=matching_read_result,
            documents=extract_documents_from_read_result(matching_read_result),
            block_id=normalized_id,
        )

        response = ensure_mapping(response)
        response.setdefault("taxonomy_version", get_pipeline_taxonomy_version(pipeline))

        return LibraryBlockServiceResult(
            ok=bool(response.get("ok")),
            status=safe_str(response.get("status"), default="ok" if response.get("ok") else "error"),
            data=response,
            block_id=normalized_id,
            warnings=tuple_of_strings(response.get("warnings")),
            errors=tuple_of_strings(response.get("errors")),
            options=service_options,
            metadata={
                "pipeline_status": get_attr_or_key(pipeline, "status"),
                "source_root": safe_path_str(get_attr_or_key(pipeline, "source_root")),
                "read_result_count": len(read_results),
                "taxonomy_version": get_pipeline_taxonomy_version(pipeline),
            },
        )

    except Exception as exc:
        return LibraryBlockServiceResult.error(
            exc,
            block_id=normalized_id,
            options=service_options,
        )


def get_library_tree(
    *,
    source_root: Any = None,
    options: LibraryBlockServiceOptions | Mapping[str, Any] | None = None,
) -> LibraryBlockServiceResult:
    """Liefert Domain/Kategorie/Subkategorie-Baum."""
    service_options = coerce_block_service_options(options)

    try:
        pipeline = scan_for_block_access(
            source_root=source_root,
            options=service_options,
            include_read_artifacts=False,
            include_scan_payload=False,
        )

        index = get_pipeline_index(pipeline)
        response = ensure_mapping(build_tree_response_from_index(index))

        status = safe_str(response.get("status"), default="ok")

        if response.get("ok") is False and status == "ok":
            status = "partial"

        response.setdefault("taxonomy_version", get_pipeline_taxonomy_version(pipeline))
        response.setdefault(
            "taxonomy",
            {
                "taxonomy_version": get_pipeline_taxonomy_version(pipeline),
                "include_empty_taxonomy_nodes": service_options.include_empty_taxonomy_nodes,
                "include_inactive_taxonomy_nodes": service_options.include_inactive_taxonomy_nodes,
                "use_taxonomy_labels": service_options.use_taxonomy_labels,
            },
        )

        return LibraryBlockServiceResult(
            ok=bool(response.get("ok", True)),
            status=status,
            data=response,
            warnings=tuple_of_strings(response.get("warnings")),
            errors=tuple_of_strings(response.get("errors")) if service_options.strict_errors else (),
            options=service_options,
            metadata={
                "pipeline_status": get_attr_or_key(pipeline, "status"),
                "source_root": safe_path_str(get_attr_or_key(pipeline, "source_root")),
                "index_available": index is not None,
                "taxonomy_version": get_pipeline_taxonomy_version(pipeline),
            },
        )

    except Exception as exc:
        return LibraryBlockServiceResult.error(
            exc,
            options=service_options,
        )


def scan_library_for_blocks(
    *,
    source_root: Any = None,
    options: LibraryBlockServiceOptions | Mapping[str, Any] | None = None,
) -> LibraryBlockServiceResult:
    """Wrapper für eine ausführliche Scan-Antwort aus Block-Service-Sicht."""
    service_options = coerce_block_service_options(options)

    try:
        pipeline = scan_for_block_access(
            source_root=source_root,
            options=service_options,
            include_read_artifacts=service_options.include_raw_pipeline,
            include_scan_payload=True,
        )

        if hasattr(pipeline, "to_scan_response_dict") and callable(pipeline.to_scan_response_dict):
            data = pipeline.to_scan_response_dict()
        elif hasattr(pipeline, "to_dict") and callable(pipeline.to_dict):
            data = pipeline.to_dict()
        else:
            data = json_safe(pipeline)

        if not isinstance(data, Mapping):
            data = {"scan": data}

        data = dict(data)
        data.setdefault("taxonomy_version", get_pipeline_taxonomy_version(pipeline))

        return LibraryBlockServiceResult(
            ok=bool(data.get("ok", True)),
            status=safe_str(data.get("status"), default="ok"),
            data=data,
            warnings=tuple_of_strings(data.get("warnings")),
            errors=tuple_of_strings(data.get("errors")) if service_options.strict_errors else (),
            options=service_options,
            metadata={
                "source_root": safe_path_str(get_attr_or_key(pipeline, "source_root")),
                "pipeline_status": get_attr_or_key(pipeline, "status"),
                "taxonomy_version": get_pipeline_taxonomy_version(pipeline),
            },
        )

    except Exception as exc:
        return LibraryBlockServiceResult.error(
            exc,
            options=service_options,
        )


# ---------------------------------------------------------------------------
# Direct response helpers for route service
# ---------------------------------------------------------------------------

def list_library_blocks_response(**kwargs: Any) -> dict[str, Any]:
    """Direkter Dict-Wrapper für Listenroute."""
    return list_library_blocks(**kwargs).to_dict()


def get_library_block_detail_response(block_id: Any, **kwargs: Any) -> dict[str, Any]:
    """Direkter Dict-Wrapper für Detailroute."""
    return get_library_block_detail(block_id, **kwargs).to_dict()


def get_library_block_variants_response(block_id: Any, **kwargs: Any) -> dict[str, Any]:
    """Direkter Dict-Wrapper für Variantenroute."""
    return get_library_block_variants(block_id, **kwargs).to_dict()


def get_library_tree_response_from_block_service(**kwargs: Any) -> dict[str, Any]:
    """Direkter Dict-Wrapper für Tree-Route."""
    return get_library_tree(**kwargs).to_dict()


def scan_library_for_blocks_response(**kwargs: Any) -> dict[str, Any]:
    """Direkter Dict-Wrapper für Scan-Route."""
    return scan_library_for_blocks(**kwargs).to_dict()


# ---------------------------------------------------------------------------
# Health
# ---------------------------------------------------------------------------

def get_import_status() -> dict[str, Any]:
    """Liefert Importstatus optionaler Abhängigkeiten."""
    return {
        "scan_service": {
            "ok": _SCAN_SERVICE_IMPORT_ERROR is None,
            "error": exception_to_dict(_SCAN_SERVICE_IMPORT_ERROR),
        },
        "index": {
            "ok": _INDEX_IMPORT_ERROR is None,
            "error": exception_to_dict(_INDEX_IMPORT_ERROR),
        },
        "detail": {
            "ok": _DETAIL_IMPORT_ERROR is None,
            "error": exception_to_dict(_DETAIL_IMPORT_ERROR),
        },
        "taxonomy": {
            "ok": _TAXONOMY_IMPORT_ERROR is None,
            "error": exception_to_dict(_TAXONOMY_IMPORT_ERROR),
        },
    }


def get_taxonomy_health_payload() -> dict[str, Any]:
    """Taxonomie-Health defensiv laden."""
    try:
        return ensure_mapping(get_taxonomy_health_safe(force_reload=False, include_registry_state=False))
    except Exception:
        pass

    if get_default_taxonomy_service is None:
        return {
            "ok": False,
            "healthy": False,
            "available": False,
            "error": exception_to_dict(_TAXONOMY_IMPORT_ERROR),
        }

    try:
        service = get_default_taxonomy_service()  # type: ignore[misc]
        return ensure_mapping(
            service.health(
                force_reload=False,
                include_registry_state=False,
            )
        )
    except Exception as exc:
        return {
            "ok": False,
            "healthy": False,
            "available": True,
            "error": exception_to_dict(exc),
        }


def get_library_block_service_health() -> dict[str, Any]:
    """Health-Status des Library Block Service. Führt keinen Scan aus."""
    warnings: list[str] = []
    errors: list[str] = []

    imports = get_import_status()

    for name, status in imports.items():
        if not status.get("ok"):
            if name == "scan_service":
                errors.append("scan_service import failed")
            else:
                warnings.append(f"{name} import failed; fallback may be active")

    try:
        options = LibraryBlockServiceOptions()
        options_dict = options.to_dict()
        scan_options_dict = json_safe(options.to_scan_options())
        detail_options_dict = json_safe(options.to_detail_options())
    except Exception as exc:
        options_dict = {}
        scan_options_dict = {}
        detail_options_dict = {}
        errors.append(f"could not build block service options: {exc}")

    try:
        safe_int_self_test = safe_int("999999", default=DEFAULT_BLOCK_LIST_LIMIT, minimum=1, maximum=MAX_BLOCK_LIST_LIMIT)
        if safe_int_self_test != MAX_BLOCK_LIST_LIMIT:
            errors.append(
                f"safe_int maximum self-test failed: expected {MAX_BLOCK_LIST_LIMIT}, got {safe_int_self_test}"
            )
    except Exception as exc:
        errors.append(f"safe_int maximum self-test failed: {exc}")

    try:
        parse_limit_self_test = parse_limit("999999")
        if parse_limit_self_test != MAX_BLOCK_LIST_LIMIT:
            errors.append(
                f"parse_limit self-test failed: expected {MAX_BLOCK_LIST_LIMIT}, got {parse_limit_self_test}"
            )
    except Exception as exc:
        errors.append(f"parse_limit self-test failed: {exc}")

    try:
        taxonomy_health = get_taxonomy_health_payload()
        if not taxonomy_health.get("healthy"):
            errors.append("taxonomy service is not healthy")
    except Exception as exc:
        taxonomy_health = {
            "ok": False,
            "healthy": False,
            "error": exception_to_dict(exc),
        }
        errors.append(f"taxonomy health check failed: {exc}")

    healthy = len(errors) == 0

    return {
        "ok": healthy,
        "healthy": healthy,
        "component": LIBRARY_BLOCK_SERVICE_COMPONENT,
        "version": LIBRARY_BLOCK_SERVICE_VERSION,
        "generated_at": utc_now_iso(),
        "options": options_dict,
        "scan_options": scan_options_dict,
        "detail_options": detail_options_dict,
        "taxonomy": json_safe(taxonomy_health),
        "imports": imports,
        "warnings": warnings,
        "errors": errors,
    }


def assert_library_block_service_ready() -> None:
    """Wirft RuntimeError, wenn der Block Service nicht bereit ist."""
    health = get_library_block_service_health()

    if health.get("healthy"):
        return

    raise RuntimeError(
        f"library block service is not ready: errors={health.get('errors')}"
    )


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

__all__: Final[tuple[str, ...]] = (
    "LIBRARY_BLOCK_SERVICE_VERSION",
    "LIBRARY_BLOCK_SERVICE_COMPONENT",
    "DEFAULT_BLOCK_SERVICE_STATUS",
    "BLOCK_SERVICE_STATUS_VALUES",
    "DEFAULT_BLOCK_LIST_LIMIT",
    "MAX_BLOCK_LIST_LIMIT",
    "DEFAULT_SCAN_CACHE_TTL_SECONDS",
    "UNKNOWN_TAXONOMY_VALUE",
    "LibraryBlockServiceOptions",
    "LibraryBlockServiceResult",
    "utc_now_iso",
    "exception_to_dict",
    "json_safe",
    "safe_str",
    "safe_bool",
    "safe_int",
    "safe_path_str",
    "ensure_mapping",
    "tuple_of_strings",
    "normalize_stable_id",
    "normalize_filter_value",
    "normalize_service_status",
    "get_attr_or_key",
    "deep_get",
    "parse_limit",
    "parse_offset",
    "parse_force_refresh",
    "get_item_id",
    "get_item_status",
    "get_item_taxonomy",
    "item_to_summary",
    "item_matches_id",
    "item_matches_filter",
    "get_index_items",
    "find_library_item_by_id",
    "extract_documents_from_read_result",
    "read_result_matches_id",
    "find_matching_read_result",
    "normalize_variant_payloads",
    "paginate_items",
    "coerce_block_service_options",
    "get_pipeline_read_results",
    "get_pipeline_validation_results",
    "get_pipeline_fingerprint_results",
    "get_pipeline_items",
    "get_pipeline_index",
    "get_pipeline_taxonomy_version",
    "scan_for_block_access",
    "list_library_blocks",
    "get_library_block_detail",
    "get_library_block_variants",
    "get_library_tree",
    "scan_library_for_blocks",
    "list_library_blocks_response",
    "get_library_block_detail_response",
    "get_library_block_variants_response",
    "get_library_tree_response_from_block_service",
    "scan_library_for_blocks_response",
    "get_import_status",
    "get_taxonomy_health_payload",
    "get_library_block_service_health",
    "assert_library_block_service_ready",
)