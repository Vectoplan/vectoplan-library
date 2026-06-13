# services/vectoplan-library/src/library/read_models/library_index_builder.py
"""
Library Index Builder für die VECTOPLAN Creative-Library-Schicht.

Diese Datei baut aus gelesenen, validierten und fingerprinteten VPLIB-Paketen
einen in-memory Creative-Library-Index.

Hauptziel:

- stabile Liste aller gültigen Blöcke/Objekte
- Zugriff per stabiler ID
- Tree-Struktur für Domain/Kategorie/Subkategorie
- Duplikaterkennung
- Trennung gültiger und ungültiger Items
- Vorbereitung für spätere DB-Upserts

Zielrouten:

    GET /api/v1/vplib/library/blocks
    GET /api/v1/vplib/library/blocks/<block_id>
    GET /api/v1/vplib/library/tree

Diese Datei:

- schreibt nichts
- scannt nicht selbst
- liest keine Dateien
- validiert nicht selbst
- erzeugt keine Datenbankeinträge
- baut nur einen Index aus vorhandenen Items oder Pipeline-Ergebnissen

Spätere DB-Regel:

    family_id bleibt stabil
    revision_hash zeigt Inhaltsänderungen

Version 0.1.2:

- Fallback-`safe_int` unterstützt `maximum`.
- Mapping-, Dataclass- und Domain-Objekte werden einheitlicher behandelt.
- Tree-, Blocks- und Index-Responses sind robuster gegen fehlende Felder.
- Duplikate erzeugen keine Folgefehler, auch wenn `LibraryDuplicateId`
  abweichend konstruiert werden muss.
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

LIBRARY_INDEX_BUILDER_VERSION: Final[str] = "0.1.2"
LIBRARY_INDEX_BUILDER_COMPONENT: Final[str] = "library-index-builder"

DEFAULT_INDEX_STATUS: Final[str] = "unknown"
DEFAULT_INDEX_SORT: Final[str] = "classification"

INDEX_STATUS_VALUES: Final[tuple[str, ...]] = (
    "unknown",
    "ok",
    "healthy",
    "empty",
    "partial",
    "invalid",
    "error",
)

INDEX_SORT_VALUES: Final[tuple[str, ...]] = (
    "classification",
    "label",
    "id",
    "object_kind",
    "updated_at",
)

TREE_ROOT_KEY: Final[str] = "root"
UNKNOWN_TREE_KEY: Final[str] = "unknown"


# ---------------------------------------------------------------------------
# Generic helpers used before optional imports
# ---------------------------------------------------------------------------

def utc_now_iso() -> str:
    """
    UTC-Zeit im ISO-Format.
    """

    try:
        return datetime.now(timezone.utc).isoformat()
    except Exception:
        return datetime.utcnow().replace(tzinfo=timezone.utc).isoformat()


def exception_to_dict(
    exc: BaseException | None,
    *,
    include_traceback: bool = False,
) -> dict[str, Any] | None:
    """
    Serialisiert Exceptions JSON-kompatibel.
    """

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


def _fallback_safe_str(value: Any, *, default: str = "") -> str:
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


def _fallback_safe_int(
    value: Any,
    *,
    default: int = 0,
    minimum: int | None = None,
    maximum: int | None = None,
) -> int:
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


def _fallback_safe_bool(value: Any, *, default: bool = False) -> bool:
    try:
        if isinstance(value, bool):
            return value

        if value is None:
            return default

        if isinstance(value, int) and value in {0, 1}:
            return bool(value)

        text = str(value).strip().lower()

        if text in {"1", "true", "yes", "y", "on", "enabled", "enable"}:
            return True

        if text in {"0", "false", "no", "n", "off", "disabled", "disable"}:
            return False

        return default

    except Exception:
        return default


def _fallback_safe_path_str(value: Any) -> str | None:
    try:
        if value is None:
            return None

        if isinstance(value, Path):
            return str(value)

        text = str(value).strip()
        return text or None

    except Exception:
        return None


def _fallback_normalize_stable_id(value: Any, *, fallback: str | None = None) -> str:
    try:
        text = _fallback_safe_str(value, default="").lower()
        text = text.replace("/", ".").replace("\\", ".").replace(" ", "_")
        text = "".join(ch for ch in text if ch.isalnum() or ch in "._:-")
        text = text.strip("._:-")

        if text:
            return text

        if fallback is not None:
            fallback_text = _fallback_safe_str(fallback, default="").lower()
            fallback_text = fallback_text.replace("/", ".").replace("\\", ".").replace(" ", "_")
            fallback_text = "".join(ch for ch in fallback_text if ch.isalnum() or ch in "._:-")
            return fallback_text.strip("._:-")

        return ""

    except Exception:
        return ""


def _fallback_humanize_identifier(value: Any, *, fallback: str = "Unnamed Library Item") -> str:
    try:
        text = _fallback_safe_str(value, default="")

        if not text:
            return fallback

        last = text.replace(":", ".").replace("/", ".").replace("\\", ".").split(".")[-1]
        last = last.replace("_", " ").replace("-", " ").strip()

        return " ".join(part.capitalize() for part in last.split()) if last else fallback

    except Exception:
        return fallback


def json_safe(value: Any) -> Any:
    """
    Defensiver JSON-Safe-Konverter.
    """

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


def ensure_mapping(value: Any) -> dict[str, Any]:
    """
    Normalisiert Mapping-artige Werte zu dict.
    """

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
    """
    Normalisiert beliebige Werte zu tuple[str, ...].
    """

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
                    text = _fallback_safe_str(item, default="")
                    if text:
                        result_from_mapping.append(text)
            return tuple(result_from_mapping)

        if isinstance(value, Iterable):
            result: list[str] = []

            for item in value:
                text = _fallback_safe_str(item, default="")
                if text:
                    result.append(text)

            return tuple(result)

        text = _fallback_safe_str(value, default="")
        return (text,) if text else ()

    except Exception:
        return ()


# ---------------------------------------------------------------------------
# Optional imports
# ---------------------------------------------------------------------------

_ITEM_IMPORT_ERROR: BaseException | None = None
_SCAN_RESULT_IMPORT_ERROR: BaseException | None = None
_SUMMARY_IMPORT_ERROR: BaseException | None = None
_DETAIL_IMPORT_ERROR: BaseException | None = None

try:
    from library.domain.library_item import (
        LibraryItem,
        LibraryItemStatus,
        filter_valid_library_items,
        humanize_identifier,
        index_library_items_by_id,
        library_items_to_summary_dicts,
        normalize_stable_id,
        safe_bool,
        safe_int,
        safe_path_str,
        safe_str,
        sort_library_items,
    )
except Exception as import_exc:  # pragma: no cover - defensive fallback
    _ITEM_IMPORT_ERROR = import_exc

    LibraryItem = None  # type: ignore[assignment]

    class LibraryItemStatus:  # type: ignore[no-redef]
        VALID = type("StatusValue", (), {"value": "valid"})()
        INVALID = type("StatusValue", (), {"value": "invalid"})()
        ERROR = type("StatusValue", (), {"value": "error"})()
        DUPLICATE = type("StatusValue", (), {"value": "duplicate"})()
        DISABLED = type("StatusValue", (), {"value": "disabled"})()

    safe_str = _fallback_safe_str
    safe_int = _fallback_safe_int
    safe_bool = _fallback_safe_bool
    safe_path_str = _fallback_safe_path_str
    normalize_stable_id = _fallback_normalize_stable_id
    humanize_identifier = _fallback_humanize_identifier

    def sort_library_items(items: Iterable[Any], *, by: str = "classification") -> list[Any]:
        return sort_items_for_index(items, sort_by=by)

    def filter_valid_library_items(items: Iterable[Any], *, enabled_only: bool = True) -> list[Any]:
        result: list[Any] = []

        for item in items or ():
            if enabled_only and not get_item_enabled(item):
                continue

            if item_is_valid(item):
                result.append(item)

        return result

    def index_library_items_by_id(items: Iterable[Any]) -> tuple[dict[str, Any], list[Any]]:
        indexed: dict[str, Any] = {}
        duplicates: list[Any] = []

        for item in items or ():
            item_id = get_item_id(item)

            if not item_id:
                continue

            if item_id in indexed:
                duplicates.append(item)
                continue

            indexed[item_id] = item

        return indexed, duplicates

    def library_items_to_summary_dicts(items: Iterable[Any], *, sort: bool = True) -> list[dict[str, Any]]:
        item_list = sort_items_for_index(items) if sort else list(items or ())
        result: list[dict[str, Any]] = []

        for item in item_list:
            result.append(item_to_summary(item))

        return result


try:
    from library.domain.scan_result import (
        LibraryDuplicateId,
        LibraryScanResult,
        build_blocks_response,
    )
except Exception as import_exc:  # pragma: no cover - defensive fallback
    _SCAN_RESULT_IMPORT_ERROR = import_exc

    LibraryScanResult = Any  # type: ignore[assignment]

    @dataclass(frozen=True)
    class LibraryDuplicateId:  # type: ignore[no-redef]
        id: str
        first_path: str | None = None
        duplicate_path: str | None = None
        package_id: str | None = None
        family_id: str | None = None
        message: str = "duplicate library item id"

        def to_dict(self) -> dict[str, Any]:
            return {
                "id": self.id,
                "first_path": self.first_path,
                "duplicate_path": self.duplicate_path,
                "package_id": self.package_id,
                "family_id": self.family_id,
                "message": self.message,
            }

    def build_blocks_response(result: Any) -> dict[str, Any]:
        if hasattr(result, "to_blocks_response_dict") and callable(result.to_blocks_response_dict):
            return result.to_blocks_response_dict()

        return {
            "ok": True,
            "status": "ok",
            "items": [],
            "count": 0,
        }


try:
    from library.read_models.block_summary_builder import (
        BlockSummaryBuilderOptions,
        build_library_items_from_results,
    )
except Exception as import_exc:  # pragma: no cover - defensive fallback
    _SUMMARY_IMPORT_ERROR = import_exc

    @dataclass(frozen=True)
    class BlockSummaryBuilderOptions:  # type: ignore[no-redef]
        include_invalid: bool = False
        enabled_only: bool = False
        sort: bool = True
        sort_by: str = "classification"
        include_metadata: bool = True
        include_validation_details: bool = False

        def to_dict(self) -> dict[str, Any]:
            return asdict(self)

    def build_library_items_from_results(
        *,
        read_results: Iterable[Any],
        validation_results: Iterable[Any] | None = None,
        fingerprint_results: Iterable[Any] | None = None,
        options: Any = None,
    ) -> list[Any]:
        result: list[Any] = []
        read_list = list(read_results or ())

        for read_result in read_list:
            item_id = normalize_stable_id(
                get_item_attr(read_result, "family_id")
                or get_item_attr(read_result, "package_id")
                or get_item_attr(read_result, "relative_package_root")
                or "unknown.library_item",
                fallback="unknown.library_item",
            )
            result.append(
                {
                    "id": item_id,
                    "family_id": item_id,
                    "label": humanize_identifier(item_id),
                    "status": "candidate",
                    "enabled": True,
                }
            )

        return result


try:
    from library.read_models.block_detail_builder import (
        BlockDetailBuilderOptions,
        build_block_detail_result_by_id,
        build_block_detail_response_by_id,
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
        fail_on_id_mismatch: bool = False

        def to_dict(self) -> dict[str, Any]:
            return asdict(self)

    def build_block_detail_result_by_id(*args: Any, **kwargs: Any) -> Any:
        return None

    def build_block_detail_response_by_id(*args: Any, **kwargs: Any) -> dict[str, Any]:
        block_id = args[0] if args else kwargs.get("block_id")
        normalized_id = normalize_stable_id(block_id, fallback=safe_str(block_id, default="unknown"))

        return {
            "ok": False,
            "status": "not_found",
            "block_id": normalized_id,
            "item": None,
            "errors": ["detail builder is not available"],
        }


# ---------------------------------------------------------------------------
# Generic helpers after imports
# ---------------------------------------------------------------------------

def normalize_index_status(value: Any) -> str:
    """
    Normalisiert Index-Status.
    """

    try:
        text = safe_str(value, default=DEFAULT_INDEX_STATUS).lower()

        if text in INDEX_STATUS_VALUES:
            return text

        return DEFAULT_INDEX_STATUS

    except Exception:
        return DEFAULT_INDEX_STATUS


def normalize_sort_mode(value: Any) -> str:
    """
    Normalisiert Sortiermodus.
    """

    try:
        text = safe_str(value, default=DEFAULT_INDEX_SORT).lower()

        if text in INDEX_SORT_VALUES:
            return text

        return DEFAULT_INDEX_SORT

    except Exception:
        return DEFAULT_INDEX_SORT


def get_item_attr(item: Any, key: str, *, default: Any = None) -> Any:
    """
    Liest Mapping-Key oder Attribut.
    """

    try:
        if item is None:
            return default

        if isinstance(item, Mapping):
            return item.get(key, default)

        return getattr(item, key, default)

    except Exception:
        return default


def get_nested_item_attr(item: Any, path: str, *, default: Any = None) -> Any:
    """
    Liest verschachtelte Mapping-/Attribut-Werte.
    """

    try:
        current: Any = item

        for part in str(path).split("."):
            if current is None:
                return default

            if isinstance(current, Mapping):
                current = current.get(part, default)
            else:
                current = getattr(current, part, default)

        return current

    except Exception:
        return default


def get_item_id(item: Any) -> str | None:
    """
    Extrahiert stabile Item-ID.
    """

    try:
        value = (
            get_item_attr(item, "id")
            or get_item_attr(item, "family_id")
            or get_item_attr(item, "package_id")
            or get_item_attr(item, "slug")
        )
        normalized = normalize_stable_id(value)

        return normalized or None

    except Exception:
        return None


def get_item_family_id(item: Any) -> str | None:
    """
    Extrahiert Family-ID.
    """

    try:
        value = get_item_attr(item, "family_id") or get_item_attr(item, "id")
        normalized = normalize_stable_id(value)

        return normalized or None

    except Exception:
        return None


def get_item_status(item: Any) -> str:
    """
    Extrahiert Item-Status.
    """

    return safe_str(get_item_attr(item, "status"), default="unknown").lower()


def get_item_enabled(item: Any) -> bool:
    """
    Extrahiert Enabled-Status.
    """

    return safe_bool(get_item_attr(item, "enabled"), default=True)


def get_item_revision_hash(item: Any) -> str | None:
    """
    Extrahiert Revision-Hash.
    """

    value = (
        get_item_attr(item, "revision_hash")
        or get_nested_item_attr(item, "metadata.fingerprint.revision_hash")
        or get_nested_item_attr(item, "fingerprint.revision_hash")
    )
    text = safe_str(value, default="")

    return text or None


def get_item_label(item: Any) -> str:
    """
    Extrahiert Label.
    """

    value = (
        get_item_attr(item, "label")
        or get_item_attr(item, "display_label")
        or get_nested_item_attr(item, "inventory.label")
        or humanize_identifier(get_item_id(item))
    )

    return safe_str(value, default=humanize_identifier(get_item_id(item)))


def get_item_domain(item: Any) -> str:
    """
    Extrahiert Domain.
    """

    value = (
        get_item_attr(item, "domain")
        or get_nested_item_attr(item, "classification.domain")
        or get_nested_item_attr(item, "metadata.classification.domain")
    )

    return safe_str(value, default=UNKNOWN_TREE_KEY).lower()


def get_item_category(item: Any) -> str:
    """
    Extrahiert Kategorie.
    """

    value = (
        get_item_attr(item, "category")
        or get_nested_item_attr(item, "classification.category")
        or get_nested_item_attr(item, "metadata.classification.category")
    )

    return safe_str(value, default=UNKNOWN_TREE_KEY).lower()


def get_item_subcategory(item: Any) -> str:
    """
    Extrahiert Subkategorie.
    """

    value = (
        get_item_attr(item, "subcategory")
        or get_nested_item_attr(item, "classification.subcategory")
        or get_nested_item_attr(item, "metadata.classification.subcategory")
    )

    return safe_str(value, default=UNKNOWN_TREE_KEY).lower()


def get_item_object_kind(item: Any) -> str:
    """
    Extrahiert object_kind.
    """

    return safe_str(get_item_attr(item, "object_kind"), default="unknown").lower()


def item_is_valid(item: Any) -> bool:
    """
    Prüft, ob ein Item gültig ist.
    """

    try:
        if safe_bool(get_item_attr(item, "is_valid"), default=False):
            return True

        status = get_item_status(item)

        if status == "valid":
            validation_valid = get_nested_item_attr(item, "validation.valid", default=None)

            if validation_valid is None:
                return True

            return safe_bool(validation_valid, default=True)

        return False

    except Exception:
        return False


def item_to_summary(item: Any) -> dict[str, Any]:
    """
    Serialisiert Item kompakt.
    """

    try:
        if hasattr(item, "to_summary_dict") and callable(item.to_summary_dict):
            data = item.to_summary_dict()
            return dict(data) if isinstance(data, Mapping) else {"value": data}

        if hasattr(item, "to_dict") and callable(item.to_dict):
            data = item.to_dict()
            if isinstance(data, Mapping):
                return dict(data)
            return {"value": data}

        if isinstance(item, Mapping):
            return dict(item)

        return {
            "id": get_item_id(item),
            "family_id": get_item_family_id(item),
            "label": get_item_label(item),
            "status": get_item_status(item),
            "enabled": get_item_enabled(item),
            "domain": get_item_domain(item),
            "category": get_item_category(item),
            "subcategory": get_item_subcategory(item),
            "object_kind": get_item_object_kind(item),
            "revision_hash": get_item_revision_hash(item),
        }

    except Exception as exc:
        return {
            "id": get_item_id(item),
            "status": "error",
            "error": exception_to_dict(exc),
        }


def normalize_items(items: Iterable[Any] | None) -> list[Any]:
    """
    Normalisiert Items-Liste.
    """

    result: list[Any] = []

    try:
        if items is None:
            return result

        for item in items:
            if item is None:
                continue

            result.append(item)

        return result

    except Exception:
        return result


def sort_items_for_index(items: Iterable[Any], *, sort_by: str = DEFAULT_INDEX_SORT) -> list[Any]:
    """
    Sortiert Items für stabile API-Ausgaben.
    """

    mode = normalize_sort_mode(sort_by)

    try:
        item_list = list(items or ())
    except Exception:
        item_list = []

    try:
        if mode == "id":
            return sorted(item_list, key=lambda item: get_item_id(item) or "")

        if mode == "label":
            return sorted(item_list, key=lambda item: (get_item_label(item).lower(), get_item_id(item) or ""))

        if mode == "object_kind":
            return sorted(
                item_list,
                key=lambda item: (
                    get_item_object_kind(item),
                    get_item_label(item).lower(),
                    get_item_id(item) or "",
                ),
            )

        if mode == "updated_at":
            return sorted(
                item_list,
                key=lambda item: (
                    safe_str(get_item_attr(item, "updated_at"), default=""),
                    get_item_id(item) or "",
                ),
                reverse=True,
            )

        return sorted(
            item_list,
            key=lambda item: (
                get_item_domain(item),
                get_item_category(item),
                get_item_subcategory(item),
                get_item_label(item).lower(),
                get_item_id(item) or "",
            ),
        )

    except Exception:
        return item_list


def make_duplicate_info(first_item: Any, duplicate_item: Any) -> Any:
    """
    Baut Duplicate-Info.

    Gibt bevorzugt `LibraryDuplicateId` zurück. Wenn dessen Konstruktor in einem
    anderen Stand abweicht, wird ein kompatibles Dict zurückgegeben.
    """

    duplicate_id = get_item_id(duplicate_item) or get_item_id(first_item) or "unknown.duplicate"

    payload = {
        "id": duplicate_id,
        "first_path": safe_path_str(get_item_attr(first_item, "package_root") or get_item_attr(first_item, "source_path")),
        "duplicate_path": safe_path_str(get_item_attr(duplicate_item, "package_root") or get_item_attr(duplicate_item, "source_path")),
        "package_id": safe_str(get_item_attr(duplicate_item, "package_id"), default="") or None,
        "family_id": get_item_family_id(duplicate_item),
        "message": "duplicate library item id",
    }

    try:
        return LibraryDuplicateId(**payload)
    except Exception:
        return payload


def duplicate_to_dict(duplicate: Any) -> dict[str, Any]:
    """
    Serialisiert Duplicate-Info robust.
    """

    try:
        if hasattr(duplicate, "to_dict") and callable(duplicate.to_dict):
            data = duplicate.to_dict()
            return dict(data) if isinstance(data, Mapping) else {"value": data}

        if is_dataclass(duplicate):
            return asdict(duplicate)

        if isinstance(duplicate, Mapping):
            return dict(duplicate)

        return {"value": str(duplicate)}

    except Exception as exc:
        return {
            "status": "error",
            "error": exception_to_dict(exc),
        }


# ---------------------------------------------------------------------------
# Tree models
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class LibraryTreeNode:
    """
    Knoten im Creative-Library-Baum.
    """

    key: str
    label: str
    level: str
    path: str
    count: int = 0
    item_ids: tuple[str, ...] = field(default_factory=tuple)
    children: dict[str, "LibraryTreeNode"] = field(default_factory=dict)

    def __post_init__(self) -> None:
        object.__setattr__(self, "key", safe_str(self.key, default=UNKNOWN_TREE_KEY))
        object.__setattr__(self, "label", safe_str(self.label, default=humanize_identifier(self.key)))
        object.__setattr__(self, "level", safe_str(self.level, default="unknown"))
        object.__setattr__(self, "path", safe_str(self.path, default=""))
        object.__setattr__(self, "count", safe_int(self.count, default=0, minimum=0))
        object.__setattr__(self, "item_ids", tuple(sorted(tuple_of_strings(self.item_ids))))
        object.__setattr__(self, "children", dict(self.children or {}))

    def to_dict(self) -> dict[str, Any]:
        return {
            "key": self.key,
            "label": self.label,
            "level": self.level,
            "path": self.path,
            "count": self.count,
            "item_ids": list(self.item_ids),
            "children": {
                key: child.to_dict() if hasattr(child, "to_dict") else json_safe(child)
                for key, child in sorted(self.children.items())
            },
        }


def build_tree_from_items(items: Iterable[Any]) -> dict[str, Any]:
    """
    Baut Domain/Kategorie/Subkategorie-Baum aus Items.
    """

    root: dict[str, Any] = {
        "key": TREE_ROOT_KEY,
        "label": "Library",
        "level": "root",
        "path": "",
        "count": 0,
        "item_ids": [],
        "children": {},
    }

    for item in items or ():
        try:
            item_id = get_item_id(item)

            if not item_id:
                continue

            domain = get_item_domain(item) or UNKNOWN_TREE_KEY
            category = get_item_category(item) or UNKNOWN_TREE_KEY
            subcategory = get_item_subcategory(item) or UNKNOWN_TREE_KEY

            domain_node = root["children"].setdefault(
                domain,
                {
                    "key": domain,
                    "label": humanize_identifier(domain),
                    "level": "domain",
                    "path": domain,
                    "count": 0,
                    "item_ids": [],
                    "children": {},
                },
            )

            category_node = domain_node["children"].setdefault(
                category,
                {
                    "key": category,
                    "label": humanize_identifier(category),
                    "level": "category",
                    "path": f"{domain}/{category}",
                    "count": 0,
                    "item_ids": [],
                    "children": {},
                },
            )

            subcategory_node = category_node["children"].setdefault(
                subcategory,
                {
                    "key": subcategory,
                    "label": humanize_identifier(subcategory),
                    "level": "subcategory",
                    "path": f"{domain}/{category}/{subcategory}",
                    "count": 0,
                    "item_ids": [],
                    "children": {},
                },
            )

            for node in (root, domain_node, category_node, subcategory_node):
                node["count"] = safe_int(node.get("count"), default=0, minimum=0) + 1

                if item_id not in node["item_ids"]:
                    node["item_ids"].append(item_id)

        except Exception:
            continue

    return sort_tree_dict(root)


def sort_tree_dict(node: dict[str, Any]) -> dict[str, Any]:
    """
    Sortiert Tree-Knoten rekursiv stabil.
    """

    try:
        children = node.get("children") or {}
        sorted_children: dict[str, Any] = {}

        for key in sorted(children.keys()):
            sorted_children[key] = sort_tree_dict(children[key])

        node["children"] = sorted_children
        node["item_ids"] = sorted(tuple_of_strings(node.get("item_ids")))
        node["count"] = safe_int(node.get("count"), default=0, minimum=0)

    except Exception:
        pass

    return node


# ---------------------------------------------------------------------------
# Index models
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class LibraryIndexBuilderOptions:
    """
    Optionen für den Library Index Builder.
    """

    include_invalid: bool = False
    enabled_only: bool = False
    fail_on_duplicates: bool = False
    sort: bool = True
    sort_by: str = DEFAULT_INDEX_SORT
    include_tree: bool = True
    include_items_by_id: bool = False
    include_metadata: bool = True

    def __post_init__(self) -> None:
        object.__setattr__(self, "include_invalid", safe_bool(self.include_invalid, default=False))
        object.__setattr__(self, "enabled_only", safe_bool(self.enabled_only, default=False))
        object.__setattr__(self, "fail_on_duplicates", safe_bool(self.fail_on_duplicates, default=False))
        object.__setattr__(self, "sort", safe_bool(self.sort, default=True))
        object.__setattr__(self, "sort_by", normalize_sort_mode(self.sort_by))
        object.__setattr__(self, "include_tree", safe_bool(self.include_tree, default=True))
        object.__setattr__(self, "include_items_by_id", safe_bool(self.include_items_by_id, default=False))
        object.__setattr__(self, "include_metadata", safe_bool(self.include_metadata, default=True))

    def to_dict(self) -> dict[str, Any]:
        return {
            "include_invalid": self.include_invalid,
            "enabled_only": self.enabled_only,
            "fail_on_duplicates": self.fail_on_duplicates,
            "sort": self.sort,
            "sort_by": self.sort_by,
            "include_tree": self.include_tree,
            "include_items_by_id": self.include_items_by_id,
            "include_metadata": self.include_metadata,
        }


@dataclass(frozen=True)
class LibraryIndexStats:
    """
    Statistiken des Library-Index.
    """

    total_count: int = 0
    valid_count: int = 0
    invalid_count: int = 0
    disabled_count: int = 0
    duplicate_count: int = 0
    unique_count: int = 0
    domain_count: int = 0
    category_count: int = 0
    subcategory_count: int = 0
    object_kind_count: int = 0
    revision_hash_count: int = 0

    def __post_init__(self) -> None:
        for field_name in (
            "total_count",
            "valid_count",
            "invalid_count",
            "disabled_count",
            "duplicate_count",
            "unique_count",
            "domain_count",
            "category_count",
            "subcategory_count",
            "object_kind_count",
            "revision_hash_count",
        ):
            object.__setattr__(
                self,
                field_name,
                safe_int(getattr(self, field_name), default=0, minimum=0),
            )

    def to_dict(self) -> dict[str, Any]:
        return {
            "total_count": self.total_count,
            "valid_count": self.valid_count,
            "invalid_count": self.invalid_count,
            "disabled_count": self.disabled_count,
            "duplicate_count": self.duplicate_count,
            "unique_count": self.unique_count,
            "domain_count": self.domain_count,
            "category_count": self.category_count,
            "subcategory_count": self.subcategory_count,
            "object_kind_count": self.object_kind_count,
            "revision_hash_count": self.revision_hash_count,
        }

    @classmethod
    def from_items(
        cls,
        *,
        total_items: Iterable[Any],
        valid_items: Iterable[Any],
        invalid_items: Iterable[Any],
        duplicates: Iterable[Any],
        unique_items_by_id: Mapping[str, Any],
    ) -> "LibraryIndexStats":
        total_list = list(total_items or ())
        valid_list = list(valid_items or ())
        invalid_list = list(invalid_items or ())
        duplicate_list = list(duplicates or ())

        enabled_false_count = sum(
            1
            for item in total_list
            if not get_item_enabled(item)
        )

        domains = {
            get_item_domain(item)
            for item in valid_list
            if get_item_domain(item)
        }
        categories = {
            f"{get_item_domain(item)}/{get_item_category(item)}"
            for item in valid_list
            if get_item_category(item)
        }
        subcategories = {
            f"{get_item_domain(item)}/{get_item_category(item)}/{get_item_subcategory(item)}"
            for item in valid_list
            if get_item_subcategory(item)
        }
        object_kinds = {
            get_item_object_kind(item)
            for item in valid_list
            if get_item_object_kind(item)
        }
        revision_hashes = {
            get_item_revision_hash(item)
            for item in valid_list
            if get_item_revision_hash(item)
        }

        return cls(
            total_count=len(total_list),
            valid_count=len(valid_list),
            invalid_count=len(invalid_list),
            disabled_count=enabled_false_count,
            duplicate_count=len(duplicate_list),
            unique_count=len(unique_items_by_id or {}),
            domain_count=len(domains),
            category_count=len(categories),
            subcategory_count=len(subcategories),
            object_kind_count=len(object_kinds),
            revision_hash_count=len(revision_hashes),
        )


@dataclass(frozen=True)
class LibraryIndex:
    """
    In-memory Creative-Library-Index.
    """

    ok: bool
    status: str
    items: tuple[Any, ...] = field(default_factory=tuple)
    invalid_items: tuple[Any, ...] = field(default_factory=tuple)
    duplicates: tuple[Any, ...] = field(default_factory=tuple)
    items_by_id: dict[str, Any] = field(default_factory=dict)
    tree: dict[str, Any] = field(default_factory=dict)
    stats: LibraryIndexStats = field(default_factory=LibraryIndexStats)
    source_root: str | None = None
    generated_at: str = field(default_factory=utc_now_iso)
    warnings: tuple[str, ...] = field(default_factory=tuple)
    errors: tuple[str, ...] = field(default_factory=tuple)
    options: LibraryIndexBuilderOptions = field(default_factory=LibraryIndexBuilderOptions)
    metadata: dict[str, Any] = field(default_factory=dict)
    version: str = LIBRARY_INDEX_BUILDER_VERSION

    def __post_init__(self) -> None:
        status = normalize_index_status(self.status)
        warnings = tuple_of_strings(self.warnings)
        errors = tuple_of_strings(self.errors)

        if not isinstance(self.options, LibraryIndexBuilderOptions):
            object.__setattr__(self, "options", LibraryIndexBuilderOptions())

        if not isinstance(self.stats, LibraryIndexStats):
            object.__setattr__(self, "stats", LibraryIndexStats())

        if status == "unknown":
            if errors:
                status = "error"
            elif self.duplicates and self.options.fail_on_duplicates:
                status = "invalid"
            elif self.items:
                status = "ok"
            elif self.invalid_items:
                status = "partial"
            else:
                status = "empty"

        object.__setattr__(self, "ok", bool(self.ok and status not in {"error", "invalid"}))
        object.__setattr__(self, "status", status)
        object.__setattr__(self, "items", tuple(self.items or ()))
        object.__setattr__(self, "invalid_items", tuple(self.invalid_items or ()))
        object.__setattr__(self, "duplicates", tuple(self.duplicates or ()))
        object.__setattr__(self, "items_by_id", dict(self.items_by_id or {}))
        object.__setattr__(self, "tree", dict(self.tree or {}))
        object.__setattr__(self, "source_root", safe_path_str(self.source_root))
        object.__setattr__(self, "generated_at", safe_str(self.generated_at, default=utc_now_iso()))
        object.__setattr__(self, "warnings", warnings)
        object.__setattr__(self, "errors", errors)
        object.__setattr__(self, "metadata", dict(self.metadata or {}))
        object.__setattr__(self, "version", safe_str(self.version, default=LIBRARY_INDEX_BUILDER_VERSION))

    @property
    def count(self) -> int:
        return len(self.items)

    @property
    def invalid_count(self) -> int:
        return len(self.invalid_items)

    @property
    def duplicate_count(self) -> int:
        return len(self.duplicates)

    @property
    def item_ids(self) -> list[str]:
        return sorted(self.items_by_id.keys())

    def get_item(self, item_id: Any) -> Any | None:
        """
        Sucht Item per stabiler ID.
        """

        normalized_id = normalize_stable_id(item_id)

        if not normalized_id:
            return None

        return self.items_by_id.get(normalized_id)

    def has_item(self, item_id: Any) -> bool:
        """
        Prüft Item-Präsenz.
        """

        return self.get_item(item_id) is not None

    def to_blocks_response_dict(self) -> dict[str, Any]:
        """
        Antwort für:
          GET /api/v1/vplib/library/blocks
        """

        items = sort_items_for_index(self.items, sort_by=self.options.sort_by) if self.options.sort else list(self.items)

        return {
            "ok": self.ok,
            "status": self.status,
            "source_root": self.source_root,
            "count": len(items),
            "items": library_items_to_summary_dicts(items, sort=False),
            "stats": self.stats.to_dict(),
            "generated_at": self.generated_at,
            "warnings": list(self.warnings),
            "errors": list(self.errors),
        }

    def to_tree_response_dict(self) -> dict[str, Any]:
        """
        Antwort für:
          GET /api/v1/vplib/library/tree
        """

        return {
            "ok": self.ok,
            "status": self.status,
            "source_root": self.source_root,
            "tree": json_safe(self.tree),
            "stats": self.stats.to_dict(),
            "generated_at": self.generated_at,
            "warnings": list(self.warnings),
            "errors": list(self.errors),
        }

    def to_dict(self) -> dict[str, Any]:
        """
        Vollständige Index-Serialisierung.
        """

        result: dict[str, Any] = {
            "ok": self.ok,
            "status": self.status,
            "source_root": self.source_root,
            "count": self.count,
            "invalid_count": self.invalid_count,
            "duplicate_count": self.duplicate_count,
            "item_ids": self.item_ids,
            "items": library_items_to_summary_dicts(
                sort_items_for_index(self.items, sort_by=self.options.sort_by) if self.options.sort else self.items,
                sort=False,
            ),
            "stats": self.stats.to_dict(),
            "generated_at": self.generated_at,
            "warnings": list(self.warnings),
            "errors": list(self.errors),
            "options": self.options.to_dict(),
            "version": self.version,
        }

        if self.options.include_invalid:
            result["invalid_items"] = library_items_to_summary_dicts(self.invalid_items, sort=False)

        if self.duplicates:
            result["duplicates"] = [
                duplicate_to_dict(duplicate)
                for duplicate in self.duplicates
            ]

        if self.options.include_tree:
            result["tree"] = json_safe(self.tree)

        if self.options.include_items_by_id:
            result["items_by_id"] = {
                item_id: item_to_summary(item)
                for item_id, item in sorted(self.items_by_id.items())
            }

        if self.options.include_metadata:
            result["metadata"] = json_safe(self.metadata)

        return result

    @classmethod
    def empty(
        cls,
        *,
        source_root: Any = None,
        options: LibraryIndexBuilderOptions | None = None,
        warning: str | None = None,
    ) -> "LibraryIndex":
        warnings = (warning,) if warning else ()

        return cls(
            ok=True,
            status="empty",
            items=(),
            invalid_items=(),
            duplicates=(),
            items_by_id={},
            tree=build_tree_from_items(()),
            stats=LibraryIndexStats(),
            source_root=safe_path_str(source_root),
            warnings=warnings,
            errors=(),
            options=options or LibraryIndexBuilderOptions(),
            metadata={},
        )

    @classmethod
    def error(
        cls,
        exc: BaseException,
        *,
        source_root: Any = None,
        options: LibraryIndexBuilderOptions | None = None,
        include_traceback: bool = False,
    ) -> "LibraryIndex":
        error_data = exception_to_dict(exc, include_traceback=include_traceback)
        message = safe_str(error_data.get("message") if error_data else None, default="library index build failed")

        return cls(
            ok=False,
            status="error",
            items=(),
            invalid_items=(),
            duplicates=(),
            items_by_id={},
            tree=build_tree_from_items(()),
            stats=LibraryIndexStats(),
            source_root=safe_path_str(source_root),
            warnings=(),
            errors=(message,),
            options=options or LibraryIndexBuilderOptions(),
            metadata={"exception": error_data},
        )


# ---------------------------------------------------------------------------
# Main builders
# ---------------------------------------------------------------------------

def build_library_index_from_items(
    items: Iterable[Any] | None,
    *,
    source_root: Any = None,
    options: LibraryIndexBuilderOptions | None = None,
) -> LibraryIndex:
    """
    Baut einen Creative-Library-Index aus LibraryItems.
    """

    builder_options = options if isinstance(options, LibraryIndexBuilderOptions) else LibraryIndexBuilderOptions()

    try:
        all_items = normalize_items(items)

        if not all_items:
            return LibraryIndex.empty(
                source_root=source_root,
                options=builder_options,
            )

        valid_candidates: list[Any] = []
        invalid_items: list[Any] = []
        disabled_items: list[Any] = []

        for item in all_items:
            try:
                enabled = get_item_enabled(item)
                valid = item_is_valid(item)

                if builder_options.enabled_only and not enabled:
                    disabled_items.append(item)
                    continue

                if valid and enabled:
                    valid_candidates.append(item)
                else:
                    invalid_items.append(item)

            except Exception:
                invalid_items.append(item)

        items_by_id: dict[str, Any] = {}
        duplicates: list[Any] = []

        for item in valid_candidates:
            item_id = get_item_id(item)

            if not item_id:
                invalid_items.append(item)
                continue

            if item_id in items_by_id:
                duplicates.append(
                    make_duplicate_info(
                        items_by_id[item_id],
                        item,
                    )
                )
                invalid_items.append(item)
                continue

            items_by_id[item_id] = item

        unique_valid_items = list(items_by_id.values())

        if builder_options.sort:
            unique_valid_items = sort_items_for_index(
                unique_valid_items,
                sort_by=builder_options.sort_by,
            )

        tree = build_tree_from_items(unique_valid_items) if builder_options.include_tree else {}

        warnings: list[str] = []
        errors: list[str] = []

        if duplicates:
            message = f"{len(duplicates)} duplicate library item ids detected"

            if builder_options.fail_on_duplicates:
                errors.append(message)
            else:
                warnings.append(message)

        stats = LibraryIndexStats.from_items(
            total_items=all_items,
            valid_items=unique_valid_items,
            invalid_items=invalid_items,
            duplicates=duplicates,
            unique_items_by_id=items_by_id,
        )

        if errors:
            status = "invalid"
        elif unique_valid_items and invalid_items:
            status = "partial"
        elif unique_valid_items:
            status = "ok"
        elif invalid_items:
            status = "invalid"
        else:
            status = "empty"

        visible_invalid_items = tuple(invalid_items if builder_options.include_invalid else ())

        return LibraryIndex(
            ok=status in {"ok", "partial", "empty"},
            status=status,
            items=tuple(unique_valid_items),
            invalid_items=visible_invalid_items,
            duplicates=tuple(duplicates),
            items_by_id=items_by_id,
            tree=tree,
            stats=stats,
            source_root=safe_path_str(source_root),
            warnings=tuple(warnings),
            errors=tuple(errors),
            options=builder_options,
            metadata={
                "input_count": len(all_items),
                "disabled_filtered_count": len(disabled_items),
                "invalid_total_count": len(invalid_items),
                "imports": get_import_status(),
            },
        )

    except Exception as exc:
        return LibraryIndex.error(
            exc,
            source_root=source_root,
            options=builder_options,
        )


def build_library_items_from_results_safe(
    *,
    read_results: Iterable[Any],
    validation_results: Iterable[Any] | None = None,
    fingerprint_results: Iterable[Any] | None = None,
    options: Any = None,
) -> tuple[Any, ...]:
    """
    Baut LibraryItems aus Pipeline-Ergebnissen mit Signatur-Fallbacks.
    """

    read_tuple = tuple(read_results or ())
    validation_tuple = tuple(validation_results or ())
    fingerprint_tuple = tuple(fingerprint_results or ())

    try:
        return tuple(
            build_library_items_from_results(
                read_results=read_tuple,
                validation_results=validation_tuple,
                fingerprint_results=fingerprint_tuple,
                options=options,
            )
        )
    except TypeError:
        try:
            return tuple(
                build_library_items_from_results(
                    read_results=read_tuple,
                    validation_results=validation_tuple,
                    fingerprint_results=fingerprint_tuple,
                )
            )
        except TypeError:
            return tuple(
                build_library_items_from_results(
                    read_tuple,
                    validation_tuple,
                    fingerprint_tuple,
                )
            )


def build_library_index_from_pipeline(
    *,
    read_results: Iterable[Any],
    validation_results: Iterable[Any] | None = None,
    fingerprint_results: Iterable[Any] | None = None,
    source_root: Any = None,
    options: LibraryIndexBuilderOptions | None = None,
) -> LibraryIndex:
    """
    Baut einen Creative-Library-Index aus Pipeline-Ergebnissen.
    """

    builder_options = options if isinstance(options, LibraryIndexBuilderOptions) else LibraryIndexBuilderOptions()

    try:
        try:
            summary_options = BlockSummaryBuilderOptions(
                include_invalid=True,
                enabled_only=False,
                sort=True,
                sort_by=builder_options.sort_by,
                include_metadata=True,
                include_validation_details=False,
            )
        except Exception:
            summary_options = None

        items = build_library_items_from_results_safe(
            read_results=read_results,
            validation_results=validation_results,
            fingerprint_results=fingerprint_results,
            options=summary_options,
        )

        return build_library_index_from_items(
            items,
            source_root=source_root,
            options=builder_options,
        )

    except Exception as exc:
        return LibraryIndex.error(
            exc,
            source_root=source_root,
            options=builder_options,
        )


def build_library_index_from_scan_result(
    scan_result: Any,
    *,
    options: LibraryIndexBuilderOptions | None = None,
) -> LibraryIndex:
    """
    Baut einen Index aus einem ScanResult oder kompatiblem Mapping.
    """

    builder_options = options if isinstance(options, LibraryIndexBuilderOptions) else LibraryIndexBuilderOptions()

    try:
        if isinstance(scan_result, Mapping):
            items = scan_result.get("items") or ()
            source_root = scan_result.get("source_root")
        else:
            items = getattr(scan_result, "items", ())
            source_root = getattr(scan_result, "source_root", None)

        return build_library_index_from_items(
            items,
            source_root=source_root,
            options=builder_options,
        )

    except Exception as exc:
        return LibraryIndex.error(
            exc,
            options=builder_options,
        )


# ---------------------------------------------------------------------------
# Query helpers
# ---------------------------------------------------------------------------

def find_library_item_by_id(
    index: LibraryIndex | Mapping[str, Any] | None,
    block_id: Any,
) -> Any | None:
    """
    Sucht ein Item per ID in einem LibraryIndex oder kompatiblen Mapping.
    """

    normalized_id = normalize_stable_id(block_id)

    if not normalized_id or index is None:
        return None

    try:
        if isinstance(index, LibraryIndex):
            return index.get_item(normalized_id)

        if isinstance(index, Mapping):
            items_by_id = index.get("items_by_id")

            if isinstance(items_by_id, Mapping):
                item = items_by_id.get(normalized_id)

                if item is not None:
                    return item

            for item in index.get("items") or ():
                if get_item_id(item) == normalized_id:
                    return item

    except Exception:
        return None

    return None


def index_items_from_any(index: LibraryIndex | Mapping[str, Any] | None) -> list[Any]:
    """
    Extrahiert Items aus LibraryIndex oder Mapping.
    """

    try:
        if index is None:
            return []

        if isinstance(index, LibraryIndex):
            return list(index.items)

        if isinstance(index, Mapping):
            items = index.get("items")
            if isinstance(items, Iterable) and not isinstance(items, (str, bytes, Mapping)):
                return list(items)

            items_by_id = index.get("items_by_id")
            if isinstance(items_by_id, Mapping):
                return list(items_by_id.values())

    except Exception:
        return []

    return []


def filter_index_items(
    index: LibraryIndex | Mapping[str, Any],
    *,
    domain: Any = None,
    category: Any = None,
    subcategory: Any = None,
    object_kind: Any = None,
    q: Any = None,
) -> list[Any]:
    """
    Filtert Index-Items für Query-Parameter.
    """

    domain_filter = safe_str(domain, default="").lower()
    category_filter = safe_str(category, default="").lower()
    subcategory_filter = safe_str(subcategory, default="").lower()
    object_kind_filter = safe_str(object_kind, default="").lower()
    query = safe_str(q, default="").lower()

    result: list[Any] = []

    for item in index_items_from_any(index):
        try:
            if domain_filter and get_item_domain(item) != domain_filter:
                continue

            if category_filter and get_item_category(item) != category_filter:
                continue

            if subcategory_filter and get_item_subcategory(item) != subcategory_filter:
                continue

            if object_kind_filter and get_item_object_kind(item) != object_kind_filter:
                continue

            if query:
                searchable = " ".join(
                    [
                        get_item_id(item) or "",
                        get_item_family_id(item) or "",
                        get_item_label(item),
                        get_item_domain(item),
                        get_item_category(item),
                        get_item_subcategory(item),
                        get_item_object_kind(item),
                        safe_str(get_item_attr(item, "description"), default=""),
                    ]
                ).lower()

                if query not in searchable:
                    continue

            result.append(item)

        except Exception:
            continue

    return result


# ---------------------------------------------------------------------------
# Response helpers
# ---------------------------------------------------------------------------

def build_blocks_response_from_index(
    index: LibraryIndex | Mapping[str, Any] | None,
    *,
    domain: Any = None,
    category: Any = None,
    subcategory: Any = None,
    object_kind: Any = None,
    q: Any = None,
) -> dict[str, Any]:
    """
    Baut Antwort für:
      GET /api/v1/vplib/library/blocks
    """

    try:
        has_filters = any(
            safe_str(value, default="")
            for value in (domain, category, subcategory, object_kind, q)
        )

        if isinstance(index, LibraryIndex):
            if has_filters:
                filtered_items = filter_index_items(
                    index,
                    domain=domain,
                    category=category,
                    subcategory=subcategory,
                    object_kind=object_kind,
                    q=q,
                )

                return {
                    "ok": index.ok,
                    "status": index.status if filtered_items else "empty",
                    "source_root": index.source_root,
                    "count": len(filtered_items),
                    "items": library_items_to_summary_dicts(filtered_items, sort=False),
                    "filters": {
                        "domain": safe_str(domain, default="") or None,
                        "category": safe_str(category, default="") or None,
                        "subcategory": safe_str(subcategory, default="") or None,
                        "object_kind": safe_str(object_kind, default="") or None,
                        "q": safe_str(q, default="") or None,
                    },
                    "stats": index.stats.to_dict(),
                    "generated_at": index.generated_at,
                    "warnings": list(index.warnings),
                    "errors": list(index.errors),
                }

            return index.to_blocks_response_dict()

        if isinstance(index, Mapping):
            items = index_items_from_any(index)

            if has_filters:
                filtered_items = filter_index_items(
                    index,
                    domain=domain,
                    category=category,
                    subcategory=subcategory,
                    object_kind=object_kind,
                    q=q,
                )
            else:
                filtered_items = items

            return {
                "ok": safe_bool(index.get("ok"), default=True),
                "status": safe_str(index.get("status"), default="ok" if filtered_items else "empty"),
                "source_root": safe_path_str(index.get("source_root")),
                "count": len(filtered_items),
                "items": [item_to_summary(item) for item in filtered_items],
                "filters": {
                    "domain": safe_str(domain, default="") or None,
                    "category": safe_str(category, default="") or None,
                    "subcategory": safe_str(subcategory, default="") or None,
                    "object_kind": safe_str(object_kind, default="") or None,
                    "q": safe_str(q, default="") or None,
                } if has_filters else {},
                "stats": json_safe(index.get("stats") or {}),
                "generated_at": safe_str(index.get("generated_at"), default=utc_now_iso()),
                "warnings": list(tuple_of_strings(index.get("warnings"))),
                "errors": list(tuple_of_strings(index.get("errors"))),
            }

        return {
            "ok": False,
            "status": "error",
            "count": 0,
            "items": [],
            "errors": ["library index is empty"],
        }

    except Exception as exc:
        return {
            "ok": False,
            "status": "error",
            "count": 0,
            "items": [],
            "errors": ["could not build blocks response from index"],
            "error": exception_to_dict(exc),
        }


def build_tree_response_from_index(
    index: LibraryIndex | Mapping[str, Any] | None,
) -> dict[str, Any]:
    """
    Baut Antwort für:
      GET /api/v1/vplib/library/tree
    """

    try:
        if isinstance(index, LibraryIndex):
            return index.to_tree_response_dict()

        if isinstance(index, Mapping):
            tree = index.get("tree")

            if not tree:
                tree = build_tree_from_items(index_items_from_any(index))

            return {
                "ok": safe_bool(index.get("ok"), default=True),
                "status": safe_str(index.get("status"), default="ok" if tree else "empty"),
                "source_root": safe_path_str(index.get("source_root")),
                "tree": json_safe(tree or {}),
                "stats": json_safe(index.get("stats") or {}),
                "generated_at": safe_str(index.get("generated_at"), default=utc_now_iso()),
                "warnings": list(tuple_of_strings(index.get("warnings"))),
                "errors": list(tuple_of_strings(index.get("errors"))),
            }

        return {
            "ok": False,
            "status": "error",
            "tree": {},
            "errors": ["library index is empty"],
        }

    except Exception as exc:
        return {
            "ok": False,
            "status": "error",
            "tree": {},
            "errors": ["could not build tree response from index"],
            "error": exception_to_dict(exc),
        }


def build_index_response(
    index: LibraryIndex | Mapping[str, Any] | None,
) -> dict[str, Any]:
    """
    Baut vollständige Index-Antwort.
    """

    try:
        if isinstance(index, LibraryIndex):
            return index.to_dict()

        if isinstance(index, Mapping):
            return json_safe(index)

        return {
            "ok": False,
            "status": "error",
            "errors": ["library index is empty"],
        }

    except Exception as exc:
        return {
            "ok": False,
            "status": "error",
            "errors": ["could not serialize library index"],
            "error": exception_to_dict(exc),
        }


# ---------------------------------------------------------------------------
# Health
# ---------------------------------------------------------------------------

def get_import_status() -> dict[str, Any]:
    """
    Liefert Importstatus optionaler Abhängigkeiten.
    """

    return {
        "item": {
            "ok": _ITEM_IMPORT_ERROR is None,
            "error": exception_to_dict(_ITEM_IMPORT_ERROR),
        },
        "scan_result": {
            "ok": _SCAN_RESULT_IMPORT_ERROR is None,
            "error": exception_to_dict(_SCAN_RESULT_IMPORT_ERROR),
        },
        "summary": {
            "ok": _SUMMARY_IMPORT_ERROR is None,
            "error": exception_to_dict(_SUMMARY_IMPORT_ERROR),
        },
        "detail": {
            "ok": _DETAIL_IMPORT_ERROR is None,
            "error": exception_to_dict(_DETAIL_IMPORT_ERROR),
        },
    }


def get_library_index_builder_health() -> dict[str, Any]:
    """
    Health-Status des Library Index Builders.
    """

    warnings: list[str] = []
    errors: list[str] = []

    imports = get_import_status()

    for name, status in imports.items():
        if not status.get("ok"):
            warnings.append(f"{name} import failed; fallback helpers may be active")

    try:
        options = LibraryIndexBuilderOptions()
        options_dict = options.to_dict()
    except Exception as exc:
        options_dict = {}
        errors.append(f"could not build index options: {exc}")

    try:
        empty_index = LibraryIndex.empty()
        self_test_ok = empty_index.status == "empty"
    except Exception as exc:
        self_test_ok = False
        errors.append(f"index self-test failed: {exc}")

    try:
        max_test = safe_int("999999", default=500, minimum=1, maximum=5000)
        if max_test != 5000:
            errors.append(f"safe_int maximum self-test failed: expected 5000, got {max_test}")
    except Exception as exc:
        errors.append(f"safe_int maximum self-test failed: {exc}")

    healthy = len(errors) == 0

    return {
        "ok": healthy,
        "healthy": healthy,
        "component": LIBRARY_INDEX_BUILDER_COMPONENT,
        "version": LIBRARY_INDEX_BUILDER_VERSION,
        "generated_at": utc_now_iso(),
        "self_test": {
            "ok": self_test_ok,
        },
        "options": options_dict,
        "imports": imports,
        "warnings": warnings,
        "errors": errors,
    }


def assert_library_index_builder_ready() -> None:
    """
    Wirft RuntimeError, wenn der Index Builder nicht bereit ist.
    """

    health = get_library_index_builder_health()

    if health.get("healthy"):
        return

    raise RuntimeError(
        f"library index builder is not ready: errors={health.get('errors')}"
    )


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

__all__: Final[tuple[str, ...]] = (
    "LIBRARY_INDEX_BUILDER_VERSION",
    "LIBRARY_INDEX_BUILDER_COMPONENT",
    "DEFAULT_INDEX_STATUS",
    "DEFAULT_INDEX_SORT",
    "INDEX_STATUS_VALUES",
    "INDEX_SORT_VALUES",
    "TREE_ROOT_KEY",
    "UNKNOWN_TREE_KEY",
    "LibraryTreeNode",
    "LibraryIndexBuilderOptions",
    "LibraryIndexStats",
    "LibraryIndex",
    "utc_now_iso",
    "exception_to_dict",
    "json_safe",
    "ensure_mapping",
    "tuple_of_strings",
    "normalize_index_status",
    "normalize_sort_mode",
    "get_item_attr",
    "get_nested_item_attr",
    "get_item_id",
    "get_item_family_id",
    "get_item_status",
    "get_item_enabled",
    "get_item_revision_hash",
    "get_item_label",
    "get_item_domain",
    "get_item_category",
    "get_item_subcategory",
    "get_item_object_kind",
    "item_is_valid",
    "item_to_summary",
    "normalize_items",
    "sort_items_for_index",
    "make_duplicate_info",
    "duplicate_to_dict",
    "build_tree_from_items",
    "sort_tree_dict",
    "build_library_index_from_items",
    "build_library_items_from_results_safe",
    "build_library_index_from_pipeline",
    "build_library_index_from_scan_result",
    "find_library_item_by_id",
    "index_items_from_any",
    "filter_index_items",
    "build_blocks_response_from_index",
    "build_tree_response_from_index",
    "build_index_response",
    "get_import_status",
    "get_library_index_builder_health",
    "assert_library_index_builder_ready",
)