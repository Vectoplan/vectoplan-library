# services/vectoplan-library/src/library/read_models/block_summary_builder.py
"""
Block Summary Builder für die VECTOPLAN Creative-Library-Schicht.

Diese Datei baut kompakte API-taugliche Listenmodelle für Blöcke/Objekte aus
gelesenen und validierten VPLIB-Paketen.

Hauptzielroute:

    GET /api/v1/vplib/library/blocks

Diese Datei:

- schreibt nichts
- scannt nicht selbst
- liest keine Dateien
- validiert nicht selbst
- baut nur ein Read-Model aus vorhandenen Ergebnissen
- reichert Summary-Items mit Backend-Taxonomie-Labels an, wenn verfügbar

Input typischerweise:

- PackageReadResult aus `package_reader.py`
- LibraryPackageValidationResult aus `library_package_validator.py`
- PackageFingerprintResult aus `package_fingerprint.py`

Output:

- LibraryItem
- dict-Summaries für API-Antworten

Taxonomie-Regel:

    Die Backend-Taxonomie ist die kanonische Quelle für:
    - domain / Reiter
    - category
    - subcategory
    - domain_label
    - category_label
    - subcategory_label
    - taxonomy_path
    - taxonomy_version

Version 0.2.0:

- Summary-Items enthalten `taxonomy`.
- Summary-Items enthalten `domain_label`, `category_label`, `subcategory_label`.
- Summary-Items enthalten `taxonomy_path` und `taxonomy_version`.
- Reader-, Validator- und Discovery-Metadaten werden als Taxonomie-Quelle
  berücksichtigt.
- Backend-Taxonomie wird defensiv gecacht.
- Existing public functions bleiben rückwärtskompatibel.
"""

from __future__ import annotations

import traceback
from collections.abc import Iterable, Mapping
from dataclasses import asdict, dataclass, field, is_dataclass
from datetime import datetime, timezone
from pathlib import Path
from threading import RLock
from typing import Any, Final


# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

BLOCK_SUMMARY_BUILDER_VERSION: Final[str] = "0.2.0"
BLOCK_SUMMARY_BUILDER_COMPONENT: Final[str] = "library-block-summary-builder"

DEFAULT_SUMMARY_STATUS: Final[str] = "candidate"
DEFAULT_SUMMARY_SORT: Final[str] = "classification"

SUMMARY_STATUS_VALUES: Final[tuple[str, ...]] = (
    "candidate",
    "valid",
    "invalid",
    "duplicate",
    "error",
    "disabled",
    "empty",
    "partial",
    "ok",
)

SUMMARY_SORT_VALUES: Final[tuple[str, ...]] = (
    "classification",
    "label",
    "id",
    "object_kind",
    "updated_at",
)

DEFAULT_VARIANT_ID_FALLBACK: Final[str] = "default"
UNKNOWN_ITEM_ID: Final[str] = "unknown.library_item"
UNKNOWN_ERROR_ITEM_ID: Final[str] = "unknown.error_item"

UNKNOWN_TAXONOMY_KEY: Final[str] = "unknown"


# ---------------------------------------------------------------------------
# Generic fallback helpers
# ---------------------------------------------------------------------------

def utc_now_iso() -> str:
    try:
        return datetime.now(timezone.utc).isoformat()
    except Exception:
        return datetime.utcnow().replace(tzinfo=timezone.utc).isoformat()


def exception_to_dict(
    exc: BaseException | None,
    *,
    include_traceback: bool = False,
) -> dict[str, Any] | None:
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

        if text in {"1", "true", "yes", "y", "ja", "on", "enabled", "enable", "active"}:
            return True

        if text in {"0", "false", "no", "n", "nein", "off", "disabled", "disable", "inactive"}:
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


def _fallback_ensure_dict(value: Any) -> dict[str, Any]:
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


def _fallback_ensure_list_of_strings(value: Any) -> list[str]:
    try:
        if value is None:
            return []

        if isinstance(value, str):
            text = value.strip()
            return [text] if text else []

        if isinstance(value, Mapping):
            return [
                _fallback_safe_str(key, default="")
                for key in value.keys()
                if _fallback_safe_str(key, default="")
            ]

        if isinstance(value, Iterable):
            result: list[str] = []
            for item in value:
                text = _fallback_safe_str(item, default="")
                if text:
                    result.append(text)
            return result

        text = _fallback_safe_str(value, default="")
        return [text] if text else []

    except Exception:
        return []


def _fallback_deep_get(
    data: Mapping[str, Any] | None,
    path: str,
    *,
    default: Any = None,
) -> Any:
    if not isinstance(data, Mapping):
        return default

    try:
        current: Any = data

        for part in str(path).split("."):
            if not isinstance(current, Mapping):
                return default

            if part not in current:
                return default

            current = current[part]

        return current

    except Exception:
        return default


def _fallback_first_non_empty(*values: Any, default: Any = None) -> Any:
    try:
        for value in values:
            if value is None:
                continue

            if isinstance(value, str) and not value.strip():
                continue

            if isinstance(value, (list, tuple, set, dict)) and not value:
                continue

            return value

        return default

    except Exception:
        return default


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


def _fallback_normalize_variant_id(value: Any) -> str:
    return _fallback_normalize_stable_id(value, fallback=DEFAULT_VARIANT_ID_FALLBACK) or DEFAULT_VARIANT_ID_FALLBACK


def _fallback_normalize_object_kind(value: Any) -> str:
    try:
        text = _fallback_safe_str(value, default="unknown").lower()

        aliases = {
            "block": "cell_block",
            "cell": "cell_block",
            "cellblock": "cell_block",
            "cell-block": "cell_block",
            "cell_block": "cell_block",
            "multi_cell": "multi_cell_module",
            "multi-cell": "multi_cell_module",
            "multi_cell_module": "multi_cell_module",
            "module": "multi_cell_module",
            "object": "catalog_object",
            "catalog": "catalog_object",
            "catalog-object": "catalog_object",
            "catalog_object": "catalog_object",
            "adaptive": "adaptive_system",
            "system": "adaptive_system",
            "adaptive-system": "adaptive_system",
            "adaptive_system": "adaptive_system",
        }

        normalized = aliases.get(text, text)

        if normalized in {"cell_block", "multi_cell_module", "catalog_object", "adaptive_system"}:
            return normalized

        return "unknown"

    except Exception:
        return "unknown"


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


def _fallback_extract_variant_ids(value: Any) -> list[str]:
    result: list[str] = []

    try:
        if value is None:
            return result

        if isinstance(value, Mapping):
            for key, item in value.items():
                if isinstance(item, Mapping):
                    candidate = item.get("variant_id") or item.get("id") or key
                else:
                    candidate = key

                normalized = _fallback_normalize_variant_id(candidate)

                if normalized and normalized not in result:
                    result.append(normalized)

            return result

        if isinstance(value, str):
            normalized = _fallback_normalize_variant_id(value)
            return [normalized] if normalized else []

        if isinstance(value, Iterable):
            for item in value:
                if isinstance(item, Mapping):
                    candidate = item.get("variant_id") or item.get("id") or item.get("slug")
                else:
                    candidate = item

                normalized = _fallback_normalize_variant_id(candidate)

                if normalized and normalized not in result:
                    result.append(normalized)

            return result

    except Exception:
        return result

    return result


def _fallback_normalize_slug(value: Any, *, default: str = "") -> str:
    try:
        text = _fallback_safe_str(value, default="").lower()
        if not text:
            return default

        replacements = {
            "ä": "ae",
            "ö": "oe",
            "ü": "ue",
            "ß": "ss",
        }
        for source, target in replacements.items():
            text = text.replace(source, target)

        chars: list[str] = []
        previous_sep = False

        for char in text:
            if char.isalnum():
                chars.append(char)
                previous_sep = False
            else:
                if not previous_sep:
                    chars.append("_")
                    previous_sep = True

        normalized = "".join(chars).strip("_-")
        return normalized or default

    except Exception:
        return default


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


# ---------------------------------------------------------------------------
# Optional imports
# ---------------------------------------------------------------------------

_ITEM_IMPORT_ERROR: BaseException | None = None
_DETAIL_IMPORT_ERROR: BaseException | None = None
_VALIDATION_IMPORT_ERROR: BaseException | None = None
_READER_IMPORT_ERROR: BaseException | None = None
_FINGERPRINT_IMPORT_ERROR: BaseException | None = None
_TAXONOMY_IMPORT_ERROR: BaseException | None = None

try:
    from library.domain.library_item import (
        DEFAULT_VARIANT_ID,
        LibraryItem,
        LibraryItemAssetRefs,
        LibraryItemClassification,
        LibraryItemStatus,
        LibraryItemValidationSummary,
        deep_get,
        ensure_dict,
        ensure_list_of_strings,
        extract_variant_ids,
        filter_valid_library_items,
        first_non_empty,
        humanize_identifier,
        index_library_items_by_id,
        library_items_to_summary_dicts,
        normalize_object_kind,
        normalize_stable_id,
        normalize_variant_id,
        safe_bool,
        safe_int,
        safe_path_str,
        safe_str,
        sort_library_items,
    )
except Exception as import_exc:  # pragma: no cover - defensive fallback
    _ITEM_IMPORT_ERROR = import_exc

    DEFAULT_VARIANT_ID = DEFAULT_VARIANT_ID_FALLBACK
    LibraryItem = None  # type: ignore[assignment]

    class LibraryItemStatus:  # type: ignore[no-redef]
        VALID = type("StatusValue", (), {"value": "valid"})()
        INVALID = type("StatusValue", (), {"value": "invalid"})()
        ERROR = type("StatusValue", (), {"value": "error"})()
        CANDIDATE = type("StatusValue", (), {"value": "candidate"})()

    @dataclass(frozen=True)
    class LibraryItemValidationSummary:  # type: ignore[no-redef]
        valid: bool = False
        warning_count: int = 0
        error_count: int = 0
        fatal_count: int = 0
        warnings: tuple[str, ...] = field(default_factory=tuple)
        errors: tuple[str, ...] = field(default_factory=tuple)

        def __post_init__(self) -> None:
            object.__setattr__(self, "valid", _fallback_safe_bool(self.valid, default=False))
            object.__setattr__(self, "warning_count", _fallback_safe_int(self.warning_count, default=0, minimum=0))
            object.__setattr__(self, "error_count", _fallback_safe_int(self.error_count, default=0, minimum=0))
            object.__setattr__(self, "fatal_count", _fallback_safe_int(self.fatal_count, default=0, minimum=0))
            object.__setattr__(self, "warnings", tuple(_fallback_ensure_list_of_strings(self.warnings)))
            object.__setattr__(self, "errors", tuple(_fallback_ensure_list_of_strings(self.errors)))

        def to_dict(self) -> dict[str, Any]:
            return {
                "valid": self.valid,
                "warning_count": self.warning_count,
                "error_count": self.error_count,
                "fatal_count": self.fatal_count,
                "warnings": list(self.warnings),
                "errors": list(self.errors),
            }

    @dataclass(frozen=True)
    class LibraryItemClassification:  # type: ignore[no-redef]
        domain: str | None = None
        category: str | None = None
        subcategory: str | None = None
        classification_path: str | None = None

        def to_dict(self) -> dict[str, Any]:
            return {
                "domain": self.domain,
                "category": self.category,
                "subcategory": self.subcategory,
                "classification_path": self.classification_path,
            }

    @dataclass(frozen=True)
    class LibraryItemAssetRefs:  # type: ignore[no-redef]
        icon_ref: str | None = None
        preview_ref: str | None = None
        mesh_ref: str | None = None
        thumbnail_ref: str | None = None
        material_refs: tuple[str, ...] = field(default_factory=tuple)

        def to_dict(self) -> dict[str, Any]:
            return {
                "icon_ref": self.icon_ref,
                "preview_ref": self.preview_ref,
                "mesh_ref": self.mesh_ref,
                "thumbnail_ref": self.thumbnail_ref,
                "material_refs": list(self.material_refs),
            }

    safe_str = _fallback_safe_str
    safe_int = _fallback_safe_int
    safe_bool = _fallback_safe_bool
    safe_path_str = _fallback_safe_path_str
    ensure_dict = _fallback_ensure_dict
    ensure_list_of_strings = _fallback_ensure_list_of_strings
    deep_get = _fallback_deep_get
    first_non_empty = _fallback_first_non_empty
    normalize_stable_id = _fallback_normalize_stable_id
    normalize_variant_id = _fallback_normalize_variant_id
    normalize_object_kind = _fallback_normalize_object_kind
    humanize_identifier = _fallback_humanize_identifier
    extract_variant_ids = _fallback_extract_variant_ids

    def sort_library_items(items: Iterable[Any], *, by: str = "classification") -> list[Any]:
        item_list = list(items or ())

        if by == "id":
            return sorted(item_list, key=lambda item: safe_str(get_attr_or_key(item, "id"), default=""))

        if by == "label":
            return sorted(item_list, key=lambda item: safe_str(get_attr_or_key(item, "label"), default="").lower())

        return sorted(
            item_list,
            key=lambda item: (
                safe_str(get_attr_or_key(item, "domain"), default=""),
                safe_str(get_attr_or_key(item, "category"), default=""),
                safe_str(get_attr_or_key(item, "subcategory"), default=""),
                safe_str(get_attr_or_key(item, "label"), default="").lower(),
                safe_str(get_attr_or_key(item, "id"), default=""),
            ),
        )

    def filter_valid_library_items(items: Iterable[Any], *, enabled_only: bool = True) -> list[Any]:
        result: list[Any] = []
        for item in items or ():
            if enabled_only and safe_bool(get_attr_or_key(item, "enabled"), default=True) is False:
                continue
            if summary_item_is_valid(item):
                result.append(item)
        return result

    def index_library_items_by_id(items: Iterable[Any]) -> tuple[dict[str, Any], list[Any]]:
        by_id: dict[str, Any] = {}
        duplicates: list[Any] = []
        for item in items or ():
            item_id = safe_str(get_attr_or_key(item, "id"), default="")
            if not item_id:
                continue
            if item_id in by_id:
                duplicates.append(item)
            else:
                by_id[item_id] = item
        return by_id, duplicates

    def library_items_to_summary_dicts(items: Iterable[Any], *, sort: bool = True) -> list[dict[str, Any]]:
        item_list = sort_library_items(items) if sort else list(items or ())
        result: list[dict[str, Any]] = []
        for item in item_list:
            result.append(item_to_summary_dict(item))
        return result


try:
    from library.domain.library_detail import (
        extract_family_id_from_documents,
        extract_package_id_from_documents,
        extract_variants_from_documents,
        get_document_dict,
        normalize_documents,
    )
except Exception as import_exc:  # pragma: no cover - defensive fallback
    _DETAIL_IMPORT_ERROR = import_exc

    def normalize_documents(documents: Mapping[str, Any] | None) -> dict[str, Any]:
        if not isinstance(documents, Mapping):
            return {}
        result: dict[str, Any] = {}
        for key, value in documents.items():
            normalized_key = str(key).replace("\\", "/").strip("/")
            if normalized_key:
                result[normalized_key] = value
        return result

    def get_document_dict(documents: Mapping[str, Any] | None, key: str) -> dict[str, Any]:
        doc = normalize_documents(documents).get(key)
        return dict(doc) if isinstance(doc, Mapping) else {}

    def extract_package_id_from_documents(documents: Mapping[str, Any] | None) -> str | None:
        manifest = get_document_dict(documents, "vplib.manifest.json")
        value = manifest.get("package_id") or manifest.get("id")
        return safe_str(value, default="") or None

    def extract_family_id_from_documents(documents: Mapping[str, Any] | None) -> str | None:
        docs = normalize_documents(documents)
        manifest = get_document_dict(docs, "vplib.manifest.json")
        identity = get_document_dict(docs, "family/identity.json")
        value = (
            manifest.get("family_id")
            or identity.get("family_id")
            or identity.get("id")
            or manifest.get("id")
            or manifest.get("package_id")
        )
        return normalize_stable_id(value) or None

    def extract_variants_from_documents(documents: Mapping[str, Any] | None) -> list[Any]:
        docs = normalize_documents(documents)
        variants_index = get_document_dict(docs, "variants/index.json")
        raw_variants = variants_index.get("variants") or variants_index.get("variant_ids") or []

        variants: list[Any] = []

        if isinstance(raw_variants, Mapping):
            for key, value in raw_variants.items():
                payload = dict(value) if isinstance(value, Mapping) else {}
                payload.setdefault("variant_id", key)
                variants.append(payload)

        elif isinstance(raw_variants, Iterable) and not isinstance(raw_variants, (str, bytes)):
            for item in raw_variants:
                if isinstance(item, Mapping):
                    variants.append(dict(item))
                else:
                    variants.append({"variant_id": item})

        if not variants and "variants/default.json" in docs:
            variants.append({"variant_id": DEFAULT_VARIANT_ID, "is_default": True})

        return variants


try:
    from library.validation.library_package_validator import (
        LibraryPackageValidationResult,
        validation_result_to_item_validation_summary,
        validation_result_to_status,
    )
except Exception as import_exc:  # pragma: no cover - defensive fallback
    _VALIDATION_IMPORT_ERROR = import_exc

    LibraryPackageValidationResult = Any  # type: ignore[assignment]

    def validation_result_to_item_validation_summary(result: Any) -> LibraryItemValidationSummary:
        if isinstance(result, Mapping):
            warnings = ensure_list_of_strings(result.get("warnings"))
            errors = ensure_list_of_strings(result.get("errors"))
            issues = result.get("issues")
            if issues and not errors:
                for issue in ensure_list_of_strings(issues):
                    errors.append(issue)

            return LibraryItemValidationSummary(
                valid=safe_bool(result.get("valid"), default=False),
                warning_count=safe_int(result.get("warning_count"), default=len(warnings), minimum=0),
                error_count=safe_int(result.get("error_count"), default=len(errors), minimum=0),
                fatal_count=safe_int(result.get("fatal_count"), default=0, minimum=0),
                warnings=tuple(warnings),
                errors=tuple(errors),
            )

        return LibraryItemValidationSummary()

    def validation_result_to_status(result: Any) -> str:
        if isinstance(result, Mapping):
            if safe_bool(result.get("valid"), default=False):
                return LibraryItemStatus.VALID.value
            return LibraryItemStatus.INVALID.value
        return LibraryItemStatus.CANDIDATE.value


try:
    from library.scanner.package_reader import PackageReadResult, read_result_to_document_mapping
except Exception as import_exc:  # pragma: no cover - defensive fallback
    _READER_IMPORT_ERROR = import_exc
    PackageReadResult = Any  # type: ignore[assignment]

    def read_result_to_document_mapping(result: Any) -> dict[str, Any]:
        if isinstance(result, Mapping):
            return normalize_documents(result.get("documents"))
        return normalize_documents(getattr(result, "documents", None))


try:
    from library.scanner.package_fingerprint import PackageFingerprintResult
except Exception as import_exc:  # pragma: no cover - defensive fallback
    _FINGERPRINT_IMPORT_ERROR = import_exc
    PackageFingerprintResult = Any  # type: ignore[assignment]


try:
    from library.taxonomy import (
        get_default_taxonomy_service,
        normalize_slug as taxonomy_normalize_slug,
    )
except Exception as import_exc:  # pragma: no cover - defensive fallback
    _TAXONOMY_IMPORT_ERROR = import_exc
    get_default_taxonomy_service = None  # type: ignore[assignment]
    taxonomy_normalize_slug = _fallback_normalize_slug  # type: ignore[assignment]


# ---------------------------------------------------------------------------
# Taxonomy cache / helpers
# ---------------------------------------------------------------------------

_TAXONOMY_CACHE_LOCK = RLock()
_TAXONOMY_CACHE: dict[str, Any] = {
    "payload": None,
    "lookup": None,
    "taxonomy_version": None,
    "loaded_at": None,
    "error": None,
}


def clear_taxonomy_cache() -> None:
    """Leert nur den lokalen Taxonomie-Cache dieses Summary-Builders."""
    with _TAXONOMY_CACHE_LOCK:
        _TAXONOMY_CACHE["payload"] = None
        _TAXONOMY_CACHE["lookup"] = None
        _TAXONOMY_CACHE["taxonomy_version"] = None
        _TAXONOMY_CACHE["loaded_at"] = None
        _TAXONOMY_CACHE["error"] = None


def taxonomy_available() -> bool:
    return get_default_taxonomy_service is not None and _TAXONOMY_IMPORT_ERROR is None


def normalize_taxonomy_key(value: Any, *, default: str = "") -> str:
    return taxonomy_normalize_slug(value, default=default)


def load_taxonomy_payload(*, force_reload: bool = False) -> dict[str, Any]:
    """
    Lädt Backend-Taxonomie defensiv und gecacht.

    Der Summary Builder darf bei Taxonomieproblemen nicht hart abbrechen.
    """
    with _TAXONOMY_CACHE_LOCK:
        if not force_reload and isinstance(_TAXONOMY_CACHE.get("payload"), Mapping):
            return dict(_TAXONOMY_CACHE["payload"])

        if not taxonomy_available():
            payload = {
                "ok": False,
                "available": False,
                "error": exception_to_dict(_TAXONOMY_IMPORT_ERROR),
            }
            _TAXONOMY_CACHE["payload"] = payload
            _TAXONOMY_CACHE["lookup"] = {}
            _TAXONOMY_CACHE["taxonomy_version"] = None
            _TAXONOMY_CACHE["loaded_at"] = utc_now_iso()
            _TAXONOMY_CACHE["error"] = payload["error"]
            return payload

        try:
            service = get_default_taxonomy_service()  # type: ignore[misc]
            payload = service.get_taxonomy_payload(
                include_inactive=False,
                include_tree=True,
                include_options=True,
                include_lookup=True,
                force_reload=force_reload,
            )
            payload = ensure_dict(payload)
            lookup = build_taxonomy_lookup_from_payload(payload)

            _TAXONOMY_CACHE["payload"] = payload
            _TAXONOMY_CACHE["lookup"] = lookup
            _TAXONOMY_CACHE["taxonomy_version"] = safe_str(payload.get("taxonomy_version"), default="") or None
            _TAXONOMY_CACHE["loaded_at"] = utc_now_iso()
            _TAXONOMY_CACHE["error"] = None

            return payload

        except Exception as exc:
            payload = {
                "ok": False,
                "available": True,
                "error": exception_to_dict(exc),
            }
            _TAXONOMY_CACHE["payload"] = payload
            _TAXONOMY_CACHE["lookup"] = {}
            _TAXONOMY_CACHE["taxonomy_version"] = None
            _TAXONOMY_CACHE["loaded_at"] = utc_now_iso()
            _TAXONOMY_CACHE["error"] = payload["error"]
            return payload


def get_taxonomy_lookup(*, force_reload: bool = False) -> dict[str, dict[str, Any]]:
    with _TAXONOMY_CACHE_LOCK:
        if not force_reload and isinstance(_TAXONOMY_CACHE.get("lookup"), Mapping):
            return dict(_TAXONOMY_CACHE["lookup"])

    payload = load_taxonomy_payload(force_reload=force_reload)
    return build_taxonomy_lookup_from_payload(payload)


def get_cached_taxonomy_version() -> str | None:
    with _TAXONOMY_CACHE_LOCK:
        value = _TAXONOMY_CACHE.get("taxonomy_version")
    text = safe_str(value, default="")
    return text or None


def build_taxonomy_lookup_from_payload(payload: Mapping[str, Any] | None) -> dict[str, dict[str, Any]]:
    """
    Baut flache Lookups aus dem Backend-Taxonomie-Payload.

    Keys:
        domain:<domain>
        category:<domain>/<category>
        subcategory:<domain>/<category>/<subcategory>
    """
    result: dict[str, dict[str, Any]] = {}
    root = ensure_dict(payload)
    tree = ensure_dict(root.get("tree"))

    if not tree:
        taxonomy = ensure_dict(root.get("taxonomy"))
        tree = ensure_dict(taxonomy.get("tree"))

    domains = tree.get("domains")
    if not isinstance(domains, list):
        options = ensure_dict(root.get("options"))
        domains = options.get("domains")

    if not isinstance(domains, list):
        return result

    for domain_index, domain_entry in enumerate(domains):
        if not isinstance(domain_entry, Mapping):
            continue

        domain_id = normalize_taxonomy_key(domain_entry.get("id"))
        if not domain_id:
            continue

        domain_payload = {
            "id": domain_id,
            "label": safe_str(domain_entry.get("label"), default=humanize_identifier(domain_id)),
            "description": safe_str(domain_entry.get("description"), default=""),
            "status": safe_str(domain_entry.get("status"), default="active"),
            "sort_order": safe_int(domain_entry.get("sort_order"), default=domain_index * 100, minimum=0),
        }
        result[f"domain:{domain_id}"] = domain_payload

        categories = domain_entry.get("categories")
        if not isinstance(categories, list):
            categories_by_domain = ensure_dict(ensure_dict(root.get("options")).get("categories_by_domain"))
            categories = categories_by_domain.get(domain_id, [])

        if not isinstance(categories, list):
            continue

        for category_index, category_entry in enumerate(categories):
            if not isinstance(category_entry, Mapping):
                continue

            category_id = normalize_taxonomy_key(category_entry.get("id"))
            if not category_id:
                continue

            category_payload = {
                "id": category_id,
                "label": safe_str(category_entry.get("label"), default=humanize_identifier(category_id)),
                "description": safe_str(category_entry.get("description"), default=""),
                "status": safe_str(category_entry.get("status"), default="active"),
                "sort_order": safe_int(category_entry.get("sort_order"), default=category_index * 100, minimum=0),
                "domain": domain_id,
            }
            result[f"category:{domain_id}/{category_id}"] = category_payload

            subcategories = category_entry.get("subcategories")
            if not isinstance(subcategories, list):
                subcategories_by_category = ensure_dict(ensure_dict(root.get("options")).get("subcategories_by_category"))
                subcategories = subcategories_by_category.get(f"{domain_id}/{category_id}", [])

            if not isinstance(subcategories, list):
                continue

            for subcategory_index, subcategory_entry in enumerate(subcategories):
                if not isinstance(subcategory_entry, Mapping):
                    continue

                subcategory_id = normalize_taxonomy_key(subcategory_entry.get("id"))
                if not subcategory_id:
                    continue

                subcategory_payload = {
                    "id": subcategory_id,
                    "label": safe_str(subcategory_entry.get("label"), default=humanize_identifier(subcategory_id)),
                    "description": safe_str(subcategory_entry.get("description"), default=""),
                    "status": safe_str(subcategory_entry.get("status"), default="active"),
                    "sort_order": safe_int(subcategory_entry.get("sort_order"), default=subcategory_index * 100, minimum=0),
                    "domain": domain_id,
                    "category": category_id,
                }
                result[f"subcategory:{domain_id}/{category_id}/{subcategory_id}"] = subcategory_payload

    return result


def taxonomy_entry(
    lookup: Mapping[str, dict[str, Any]],
    *,
    level: str,
    domain: str = "",
    category: str = "",
    subcategory: str = "",
) -> dict[str, Any]:
    if level == "domain":
        return dict(lookup.get(f"domain:{domain}", {}))

    if level == "category":
        return dict(lookup.get(f"category:{domain}/{category}", {}))

    if level == "subcategory":
        return dict(lookup.get(f"subcategory:{domain}/{category}/{subcategory}", {}))

    return {}


def taxonomy_label(
    lookup: Mapping[str, dict[str, Any]],
    *,
    level: str,
    key: str,
    domain: str = "",
    category: str = "",
) -> str:
    if level == "domain":
        entry = taxonomy_entry(lookup, level="domain", domain=key)
    elif level == "category":
        entry = taxonomy_entry(lookup, level="category", domain=domain, category=key)
    elif level == "subcategory":
        entry = taxonomy_entry(lookup, level="subcategory", domain=domain, category=category, subcategory=key)
    else:
        entry = {}

    return safe_str(entry.get("label"), default=humanize_identifier(key))


def normalize_taxonomy_path(domain: Any, category: Any, subcategory: Any) -> str:
    parts = [
        normalize_taxonomy_key(domain),
        normalize_taxonomy_key(category),
        normalize_taxonomy_key(subcategory),
    ]
    return "/".join(part for part in parts if part)


def extract_taxonomy_context(
    *,
    read_result: Any = None,
    validation_result: Any = None,
    documents: Mapping[str, Any] | None = None,
    lookup: Mapping[str, dict[str, Any]] | None = None,
) -> dict[str, Any]:
    """
    Extrahiert Taxonomie aus Validator, Reader, Discovery, Dokumenten und
    Backend-Taxonomie-Lookup.
    """
    docs = normalize_documents(documents)
    manifest = get_document_dict(docs, "vplib.manifest.json")
    classification_doc = get_document_dict(docs, "family/classification.json")
    inventory = get_document_dict(docs, "editor/inventory.json")

    read_metadata = ensure_dict(get_attr_or_key(read_result, "metadata"))
    validation_metadata = ensure_dict(get_attr_or_key(validation_result, "metadata"))

    read_taxonomy = ensure_dict(read_metadata.get("taxonomy"))
    validation_taxonomy = ensure_dict(validation_metadata.get("taxonomy"))
    discovery_taxonomy = ensure_dict(ensure_dict(read_metadata.get("discovery")).get("taxonomy"))

    domain = first_non_empty(
        get_attr_or_key(validation_result, "domain"),
        validation_taxonomy.get("domain"),
        get_attr_or_key(read_result, "domain"),
        read_taxonomy.get("domain"),
        discovery_taxonomy.get("domain"),
        deep_get(manifest, "domain"),
        deep_get(manifest, "classification.domain"),
        deep_get(classification_doc, "domain"),
        deep_get(classification_doc, "classification.domain"),
        deep_get(inventory, "domain"),
    )
    category = first_non_empty(
        get_attr_or_key(validation_result, "category"),
        validation_taxonomy.get("category"),
        get_attr_or_key(read_result, "category"),
        read_taxonomy.get("category"),
        discovery_taxonomy.get("category"),
        deep_get(manifest, "category"),
        deep_get(manifest, "classification.category"),
        deep_get(classification_doc, "category"),
        deep_get(classification_doc, "classification.category"),
        deep_get(inventory, "category"),
    )
    subcategory = first_non_empty(
        get_attr_or_key(validation_result, "subcategory"),
        validation_taxonomy.get("subcategory"),
        get_attr_or_key(read_result, "subcategory"),
        read_taxonomy.get("subcategory"),
        discovery_taxonomy.get("subcategory"),
        deep_get(manifest, "subcategory"),
        deep_get(manifest, "classification.subcategory"),
        deep_get(classification_doc, "subcategory"),
        deep_get(classification_doc, "classification.subcategory"),
        deep_get(inventory, "subcategory"),
    )

    domain = normalize_taxonomy_key(domain)
    category = normalize_taxonomy_key(category)
    subcategory = normalize_taxonomy_key(subcategory)

    taxonomy_version = first_non_empty(
        get_attr_or_key(validation_result, "taxonomy_version"),
        validation_taxonomy.get("taxonomy_version"),
        get_attr_or_key(read_result, "taxonomy_version"),
        read_taxonomy.get("taxonomy_version"),
        discovery_taxonomy.get("taxonomy_version"),
        deep_get(manifest, "taxonomy_version"),
        deep_get(classification_doc, "taxonomy_version"),
        get_cached_taxonomy_version(),
    )

    taxonomy_path = first_non_empty(
        get_attr_or_key(validation_result, "classification_path"),
        validation_taxonomy.get("classification_path"),
        get_attr_or_key(read_result, "classification_path"),
        read_taxonomy.get("classification_path"),
        discovery_taxonomy.get("classification_path"),
        deep_get(manifest, "classification_path"),
        deep_get(manifest, "classification.path"),
        deep_get(classification_doc, "classification_path"),
        deep_get(classification_doc, "classification.path"),
    )
    taxonomy_path = safe_str(taxonomy_path, default="") or normalize_taxonomy_path(domain, category, subcategory)

    source_path = first_non_empty(
        get_attr_or_key(validation_result, "source_path"),
        validation_taxonomy.get("source_path"),
        get_attr_or_key(read_result, "source_path"),
        read_taxonomy.get("source_path"),
        discovery_taxonomy.get("source_path"),
        deep_get(manifest, "source_path"),
        deep_get(classification_doc, "source_path"),
    )

    labels = ensure_dict(read_taxonomy.get("labels")) or ensure_dict(validation_taxonomy.get("labels")) or ensure_dict(classification_doc.get("labels"))
    taxonomy_lookup = lookup if isinstance(lookup, Mapping) else get_taxonomy_lookup()

    domain_label = first_non_empty(
        labels.get("domain"),
        taxonomy_label(taxonomy_lookup, level="domain", key=domain) if domain else "",
        humanize_identifier(domain),
    )
    category_label = first_non_empty(
        labels.get("category"),
        taxonomy_label(taxonomy_lookup, level="category", key=category, domain=domain) if category else "",
        humanize_identifier(category),
    )
    subcategory_label = first_non_empty(
        labels.get("subcategory"),
        taxonomy_label(taxonomy_lookup, level="subcategory", key=subcategory, domain=domain, category=category) if subcategory else "",
        humanize_identifier(subcategory),
    )

    return {
        "domain": domain or None,
        "category": category or None,
        "subcategory": subcategory or None,
        "domain_label": safe_str(domain_label, default="") or None,
        "category_label": safe_str(category_label, default="") or None,
        "subcategory_label": safe_str(subcategory_label, default="") or None,
        "taxonomy_path": taxonomy_path or None,
        "classification_path": taxonomy_path or None,
        "source_path": safe_str(source_path, default="") or None,
        "taxonomy_version": safe_str(taxonomy_version, default="") or None,
        "labels": {
            "domain": safe_str(domain_label, default="") or None,
            "category": safe_str(category_label, default="") or None,
            "subcategory": safe_str(subcategory_label, default="") or None,
        },
        "source": {
            "has_reader_taxonomy": bool(read_taxonomy),
            "has_validation_taxonomy": bool(validation_taxonomy),
            "has_discovery_taxonomy": bool(discovery_taxonomy),
            "has_document_taxonomy": bool(classification_doc),
            "has_backend_taxonomy": bool(taxonomy_lookup),
        },
    }


def enrich_summary_with_taxonomy(summary: Mapping[str, Any], *, lookup: Mapping[str, dict[str, Any]] | None = None) -> dict[str, Any]:
    """
    Reicht Taxonomie-Labels und Pfade in vorhandene Summary-Dicts nach.
    """
    result = dict(summary)
    metadata = ensure_dict(result.get("metadata"))
    taxonomy_in_metadata = ensure_dict(metadata.get("taxonomy"))
    classification = ensure_dict(result.get("classification"))
    taxonomy_existing = ensure_dict(result.get("taxonomy"))

    context = extract_taxonomy_context(
        read_result={
            "domain": result.get("domain") or taxonomy_existing.get("domain") or taxonomy_in_metadata.get("domain"),
            "category": result.get("category") or taxonomy_existing.get("category") or taxonomy_in_metadata.get("category"),
            "subcategory": result.get("subcategory") or taxonomy_existing.get("subcategory") or taxonomy_in_metadata.get("subcategory"),
            "classification_path": result.get("classification_path") or taxonomy_existing.get("taxonomy_path"),
            "taxonomy_version": result.get("taxonomy_version") or taxonomy_existing.get("taxonomy_version"),
            "metadata": metadata,
        },
        validation_result=None,
        documents={},
        lookup=lookup,
    )

    domain = context.get("domain") or result.get("domain") or classification.get("domain")
    category = context.get("category") or result.get("category") or classification.get("category")
    subcategory = context.get("subcategory") or result.get("subcategory") or classification.get("subcategory")

    result["domain"] = domain
    result["category"] = category
    result["subcategory"] = subcategory
    result["domain_label"] = context.get("domain_label")
    result["category_label"] = context.get("category_label")
    result["subcategory_label"] = context.get("subcategory_label")
    result["taxonomy_path"] = context.get("taxonomy_path")
    result["classification_path"] = context.get("classification_path")
    result["taxonomy_version"] = context.get("taxonomy_version")

    result["taxonomy"] = {
        "domain": domain,
        "category": category,
        "subcategory": subcategory,
        "domain_label": context.get("domain_label"),
        "category_label": context.get("category_label"),
        "subcategory_label": context.get("subcategory_label"),
        "taxonomy_path": context.get("taxonomy_path"),
        "classification_path": context.get("classification_path"),
        "source_path": context.get("source_path"),
        "taxonomy_version": context.get("taxonomy_version"),
        "source": context.get("source"),
    }

    return json_safe(result)


# ---------------------------------------------------------------------------
# Generic helpers after optional imports
# ---------------------------------------------------------------------------

def normalize_summary_status(value: Any) -> str:
    try:
        text = safe_str(value, default=DEFAULT_SUMMARY_STATUS).lower()

        if text in SUMMARY_STATUS_VALUES:
            return text

        return DEFAULT_SUMMARY_STATUS

    except Exception:
        return DEFAULT_SUMMARY_STATUS


def normalize_sort_mode(value: Any) -> str:
    try:
        text = safe_str(value, default=DEFAULT_SUMMARY_SORT).lower()

        if text in SUMMARY_SORT_VALUES:
            return text

        return DEFAULT_SUMMARY_SORT

    except Exception:
        return DEFAULT_SUMMARY_SORT


def get_attr_or_key(value: Any, key: str, *, default: Any = None) -> Any:
    try:
        if value is None:
            return default

        if isinstance(value, Mapping):
            return value.get(key, default)

        return getattr(value, key, default)

    except Exception:
        return default


def item_to_summary_dict(item: Any) -> dict[str, Any]:
    """Serialisiert ein Item robust als Summary-Dict und reichert Taxonomie an."""
    try:
        if hasattr(item, "to_summary_dict") and callable(item.to_summary_dict):
            data = item.to_summary_dict()
            summary = dict(data) if isinstance(data, Mapping) else {"value": data}

        elif hasattr(item, "to_dict") and callable(item.to_dict):
            data = item.to_dict()
            summary = dict(data) if isinstance(data, Mapping) else {"value": data}

        elif isinstance(item, Mapping):
            summary = dict(item)

        else:
            summary = {
                "id": get_attr_or_key(item, "id"),
                "family_id": get_attr_or_key(item, "family_id"),
                "label": get_attr_or_key(item, "label"),
                "status": get_attr_or_key(item, "status"),
                "domain": get_attr_or_key(item, "domain"),
                "category": get_attr_or_key(item, "category"),
                "subcategory": get_attr_or_key(item, "subcategory"),
            }

        return enrich_summary_with_taxonomy(summary)

    except Exception as exc:
        return {
            "status": "error",
            "error": exception_to_dict(exc),
        }


def summary_item_is_valid(item: Any) -> bool:
    """Prüft defensiv, ob ein Summary-Item gültig ist."""
    try:
        if safe_bool(get_attr_or_key(item, "is_valid"), default=False):
            return True

        status = safe_str(get_attr_or_key(item, "status"), default="").lower()

        if status != LibraryItemStatus.VALID.value:
            return False

        validation_valid = deep_get(
            ensure_dict(get_attr_or_key(item, "validation")),
            "valid",
            default=None,
        )

        if validation_valid is None:
            validation_valid = get_attr_or_key(get_attr_or_key(item, "validation"), "valid", default=None)

        if validation_valid is None:
            return True

        return safe_bool(validation_valid, default=True)

    except Exception:
        return False


def validation_summary_from_result(result: Any) -> LibraryItemValidationSummary:
    """Baut eine ValidationSummary robust aus ValidationResult oder Mapping."""
    if result is None:
        return LibraryItemValidationSummary(
            valid=False,
            warning_count=0,
            error_count=0,
            fatal_count=0,
            warnings=(),
            errors=(),
        )

    try:
        summary = validation_result_to_item_validation_summary(result)
        if isinstance(summary, LibraryItemValidationSummary):
            return summary

        if isinstance(summary, Mapping):
            warnings = ensure_list_of_strings(summary.get("warnings"))
            errors = ensure_list_of_strings(summary.get("errors"))
            return LibraryItemValidationSummary(
                valid=safe_bool(summary.get("valid"), default=False),
                warning_count=safe_int(summary.get("warning_count"), default=len(warnings), minimum=0),
                error_count=safe_int(summary.get("error_count"), default=len(errors), minimum=0),
                fatal_count=safe_int(summary.get("fatal_count"), default=0, minimum=0),
                warnings=tuple(warnings),
                errors=tuple(errors),
            )

    except Exception:
        pass

    try:
        warnings = ensure_list_of_strings(get_attr_or_key(result, "warnings"))
        errors = ensure_list_of_strings(get_attr_or_key(result, "errors"))
        return LibraryItemValidationSummary(
            valid=safe_bool(get_attr_or_key(result, "valid"), default=False),
            warning_count=safe_int(get_attr_or_key(result, "warning_count"), default=len(warnings), minimum=0),
            error_count=safe_int(get_attr_or_key(result, "error_count"), default=len(errors), minimum=0),
            fatal_count=safe_int(get_attr_or_key(result, "fatal_count"), default=0, minimum=0),
            warnings=tuple(warnings),
            errors=tuple(errors),
        )

    except Exception:
        return LibraryItemValidationSummary()


def status_from_validation_result(result: Any) -> str:
    """Baut Item-Status robust aus ValidationResult."""
    if result is None:
        return LibraryItemStatus.CANDIDATE.value

    try:
        status = validation_result_to_status(result)
        normalized = normalize_summary_status(status)

        if normalized in {"valid", "invalid", "error", "disabled", "duplicate"}:
            return normalized

    except Exception:
        pass

    try:
        raw_status = safe_str(get_attr_or_key(result, "status"), default="").lower()

        if raw_status in SUMMARY_STATUS_VALUES:
            return raw_status

        if safe_bool(get_attr_or_key(result, "valid"), default=False):
            return LibraryItemStatus.VALID.value

        return LibraryItemStatus.INVALID.value

    except Exception:
        return LibraryItemStatus.INVALID.value


def extract_documents_from_any(value: Any) -> dict[str, Any]:
    """Extrahiert Dokumente aus ReadResult, Mapping oder direktem Dokumentmapping."""
    try:
        if value is None:
            return {}

        if isinstance(value, Mapping):
            if "documents" in value:
                return normalize_documents(value.get("documents"))

            if any(str(key).endswith(".json") or "/" in str(key) for key in value.keys()):
                return normalize_documents(value)

            return {}

        if hasattr(value, "documents"):
            return normalize_documents(getattr(value, "documents"))

        return read_result_to_document_mapping(value)

    except Exception:
        return {}


def extract_revision_hash(fingerprint: Any = None, read_result: Any = None) -> str | None:
    """Extrahiert revision_hash aus Fingerprint oder ReadResult."""
    try:
        value = first_non_empty(
            get_attr_or_key(fingerprint, "revision_hash"),
            get_attr_or_key(fingerprint, "hash"),
            get_attr_or_key(fingerprint, "package_hash"),
            get_attr_or_key(read_result, "revision_hash"),
            deep_get(ensure_dict(get_attr_or_key(read_result, "metadata")), "fingerprint.revision_hash"),
        )
        text = safe_str(value, default="")
        return text or None
    except Exception:
        return None


def extract_source_path(read_result: Any = None) -> str | None:
    """Extrahiert Source-/Package-Pfad."""
    return safe_path_str(
        first_non_empty(
            get_attr_or_key(read_result, "package_root"),
            get_attr_or_key(read_result, "source_path"),
        )
    )


def extract_relative_package_root(read_result: Any = None) -> str | None:
    return safe_path_str(get_attr_or_key(read_result, "relative_package_root"))


def extract_package_root(read_result: Any = None) -> str | None:
    return safe_path_str(get_attr_or_key(read_result, "package_root"))


def extract_scanned_at(read_result: Any = None) -> str | None:
    return safe_str(
        first_non_empty(
            get_attr_or_key(read_result, "finished_at"),
            get_attr_or_key(read_result, "scanned_at"),
            get_attr_or_key(read_result, "read_at"),
            get_attr_or_key(read_result, "generated_at"),
        ),
        default="",
    ) or None


def extract_package_version(documents: Mapping[str, Any]) -> str | None:
    manifest = get_document_dict(documents, "vplib.manifest.json")
    value = first_non_empty(
        deep_get(manifest, "package_version"),
        deep_get(manifest, "version"),
    )
    return safe_str(value, default="") or None


def extract_schema_version(documents: Mapping[str, Any]) -> str | None:
    manifest = get_document_dict(documents, "vplib.manifest.json")
    value = first_non_empty(
        deep_get(manifest, "schema_version"),
        deep_get(manifest, "vplib_schema_version"),
    )
    return safe_str(value, default="") or None


def extract_created_at(documents: Mapping[str, Any]) -> str | None:
    manifest = get_document_dict(documents, "vplib.manifest.json")
    identity = get_document_dict(documents, "family/identity.json")
    value = first_non_empty(
        deep_get(manifest, "created_at"),
        deep_get(identity, "created_at"),
    )
    return safe_str(value, default="") or None


def extract_updated_at(documents: Mapping[str, Any]) -> str | None:
    manifest = get_document_dict(documents, "vplib.manifest.json")
    identity = get_document_dict(documents, "family/identity.json")
    value = first_non_empty(
        deep_get(manifest, "updated_at"),
        deep_get(identity, "updated_at"),
    )
    return safe_str(value, default="") or None


def extract_classification(documents: Mapping[str, Any]) -> LibraryItemClassification:
    """Extrahiert Domain/Kategorie/Subkategorie aus Dokumenten."""
    context = extract_taxonomy_context(documents=documents)
    return LibraryItemClassification(
        domain=context.get("domain"),
        category=context.get("category"),
        subcategory=context.get("subcategory"),
        classification_path=context.get("classification_path") or context.get("taxonomy_path"),
    )


def extract_asset_refs(documents: Mapping[str, Any]) -> LibraryItemAssetRefs:
    """Extrahiert kompakte Asset-Referenzen."""
    inventory = get_document_dict(documents, "editor/inventory.json")
    render_variants = get_document_dict(documents, "render/render_variants.json")
    render_bounds = get_document_dict(documents, "render/bounds.json")
    materials = get_document_dict(documents, "render/materials.json")

    icon_ref = first_non_empty(
        deep_get(inventory, "icon_ref"),
        deep_get(inventory, "icon"),
        deep_get(render_variants, "icon_ref"),
        deep_get(render_variants, "icon"),
        deep_get(render_variants, "default.icon_ref"),
    )

    preview_ref = first_non_empty(
        deep_get(inventory, "preview_ref"),
        deep_get(inventory, "preview"),
        deep_get(render_variants, "preview_ref"),
        deep_get(render_variants, "preview"),
        deep_get(render_variants, "default.preview_ref"),
    )

    mesh_ref = first_non_empty(
        deep_get(render_variants, "mesh_ref"),
        deep_get(render_variants, "mesh"),
        deep_get(render_variants, "default.mesh_ref"),
        deep_get(render_bounds, "mesh_ref"),
    )

    thumbnail_ref = first_non_empty(
        deep_get(inventory, "thumbnail_ref"),
        deep_get(inventory, "thumbnail"),
        deep_get(render_variants, "thumbnail_ref"),
    )

    material_refs = first_non_empty(
        deep_get(materials, "material_refs"),
        deep_get(render_variants, "material_refs"),
        default=[],
    )

    return LibraryItemAssetRefs(
        icon_ref=safe_path_str(icon_ref),
        preview_ref=safe_path_str(preview_ref),
        mesh_ref=safe_path_str(mesh_ref),
        thumbnail_ref=safe_path_str(thumbnail_ref),
        material_refs=tuple(ensure_list_of_strings(material_refs)),
    )


def extract_variant_summary(documents: Mapping[str, Any]) -> tuple[str, int, tuple[str, ...]]:
    """Extrahiert Default-Variante, Variant-Count und Variant-IDs."""
    variants_index = get_document_dict(documents, "variants/index.json")
    default_variant_doc = get_document_dict(documents, "variants/default.json")

    default_variant_id = first_non_empty(
        deep_get(variants_index, "default_variant_id"),
        deep_get(variants_index, "default"),
        deep_get(default_variant_doc, "variant_id"),
        deep_get(default_variant_doc, "id"),
        DEFAULT_VARIANT_ID,
    )
    normalized_default_variant_id = normalize_variant_id(default_variant_id)

    variant_ids_raw = first_non_empty(
        deep_get(variants_index, "variant_ids"),
        deep_get(variants_index, "variants"),
        default=[],
    )

    variant_ids = extract_variant_ids(variant_ids_raw)

    if not variant_ids:
        extracted_variants = extract_variants_from_documents(documents)
        variant_ids = [
            normalize_variant_id(
                first_non_empty(
                    get_attr_or_key(variant, "variant_id"),
                    get_attr_or_key(variant, "id"),
                )
            )
            for variant in extracted_variants
        ]

    if not variant_ids and "variants/default.json" in documents:
        variant_ids = [normalized_default_variant_id]

    deduped: list[str] = []

    for variant_id in variant_ids:
        normalized = normalize_variant_id(variant_id)
        if normalized and normalized not in deduped:
            deduped.append(normalized)

    variant_count = safe_int(
        first_non_empty(
            deep_get(variants_index, "variant_count"),
            len(deduped),
        ),
        default=len(deduped),
        minimum=0,
    )

    return normalized_default_variant_id, variant_count, tuple(deduped)


def extract_label_and_description(documents: Mapping[str, Any], family_id: str | None) -> tuple[str, str | None]:
    """Extrahiert Label und Description."""
    manifest = get_document_dict(documents, "vplib.manifest.json")
    identity = get_document_dict(documents, "family/identity.json")
    inventory = get_document_dict(documents, "editor/inventory.json")

    label = first_non_empty(
        deep_get(identity, "label"),
        deep_get(identity, "name"),
        deep_get(identity, "family_name"),
        deep_get(manifest, "family_name"),
        deep_get(inventory, "label"),
        humanize_identifier(family_id),
    )

    description = first_non_empty(
        deep_get(identity, "description"),
        deep_get(inventory, "description"),
        deep_get(manifest, "description"),
    )

    return safe_str(label, default=humanize_identifier(family_id)), safe_str(description, default="") or None


def extract_tags(documents: Mapping[str, Any]) -> tuple[str, ...]:
    """Extrahiert Tags."""
    manifest = get_document_dict(documents, "vplib.manifest.json")
    identity = get_document_dict(documents, "family/identity.json")
    inventory = get_document_dict(documents, "editor/inventory.json")
    classification = get_document_dict(documents, "family/classification.json")

    tags = first_non_empty(
        deep_get(identity, "tags"),
        deep_get(inventory, "tags"),
        deep_get(classification, "tags"),
        deep_get(manifest, "tags"),
        default=[],
    )

    return tuple(ensure_list_of_strings(tags))


def extract_enabled(documents: Mapping[str, Any]) -> bool:
    """Extrahiert enabled/visible Status."""
    manifest = get_document_dict(documents, "vplib.manifest.json")
    identity = get_document_dict(documents, "family/identity.json")
    inventory = get_document_dict(documents, "editor/inventory.json")

    enabled = first_non_empty(
        deep_get(manifest, "enabled"),
        deep_get(identity, "enabled"),
        deep_get(inventory, "enabled"),
        deep_get(inventory, "visible"),
        True,
    )

    return safe_bool(enabled, default=True)


# ---------------------------------------------------------------------------
# Builder options / result
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class BlockSummaryBuilderOptions:
    """Optionen für den Summary Builder."""

    include_invalid: bool = False
    enabled_only: bool = False
    sort: bool = True
    sort_by: str = DEFAULT_SUMMARY_SORT
    include_metadata: bool = True
    include_validation_details: bool = False
    include_taxonomy_labels: bool = True
    force_taxonomy_reload: bool = False

    def __post_init__(self) -> None:
        object.__setattr__(self, "include_invalid", safe_bool(self.include_invalid, default=False))
        object.__setattr__(self, "enabled_only", safe_bool(self.enabled_only, default=False))
        object.__setattr__(self, "sort", safe_bool(self.sort, default=True))
        object.__setattr__(self, "sort_by", normalize_sort_mode(self.sort_by))
        object.__setattr__(self, "include_metadata", safe_bool(self.include_metadata, default=True))
        object.__setattr__(self, "include_validation_details", safe_bool(self.include_validation_details, default=False))
        object.__setattr__(self, "include_taxonomy_labels", safe_bool(self.include_taxonomy_labels, default=True))
        object.__setattr__(self, "force_taxonomy_reload", safe_bool(self.force_taxonomy_reload, default=False))

    def to_dict(self) -> dict[str, Any]:
        return {
            "include_invalid": self.include_invalid,
            "enabled_only": self.enabled_only,
            "sort": self.sort,
            "sort_by": self.sort_by,
            "include_metadata": self.include_metadata,
            "include_validation_details": self.include_validation_details,
            "include_taxonomy_labels": self.include_taxonomy_labels,
            "force_taxonomy_reload": self.force_taxonomy_reload,
        }


@dataclass(frozen=True)
class BlockSummaryBuildResult:
    """Ergebnis des Summary Builders."""

    ok: bool
    status: str
    items: tuple[Any, ...] = field(default_factory=tuple)
    invalid_items: tuple[Any, ...] = field(default_factory=tuple)
    duplicates: tuple[Any, ...] = field(default_factory=tuple)
    generated_at: str = field(default_factory=utc_now_iso)
    warnings: tuple[str, ...] = field(default_factory=tuple)
    errors: tuple[str, ...] = field(default_factory=tuple)
    options: BlockSummaryBuilderOptions = field(default_factory=BlockSummaryBuilderOptions)
    metadata: dict[str, Any] = field(default_factory=dict)
    version: str = BLOCK_SUMMARY_BUILDER_VERSION

    def __post_init__(self) -> None:
        warnings = tuple(ensure_list_of_strings(self.warnings))
        errors = tuple(ensure_list_of_strings(self.errors))

        if not isinstance(self.options, BlockSummaryBuilderOptions):
            object.__setattr__(self, "options", BlockSummaryBuilderOptions())

        status = normalize_summary_status(self.status)

        if status == "candidate":
            if errors:
                status = "error"
            elif self.items and self.invalid_items:
                status = "partial"
            elif self.items:
                status = "valid"
            elif self.invalid_items:
                status = "invalid"
            else:
                status = "empty"

        object.__setattr__(self, "ok", bool(self.ok and status != "error"))
        object.__setattr__(self, "status", status)
        object.__setattr__(self, "items", tuple(self.items or ()))
        object.__setattr__(self, "invalid_items", tuple(self.invalid_items or ()))
        object.__setattr__(self, "duplicates", tuple(self.duplicates or ()))
        object.__setattr__(self, "generated_at", safe_str(self.generated_at, default=utc_now_iso()))
        object.__setattr__(self, "warnings", warnings)
        object.__setattr__(self, "errors", errors)
        object.__setattr__(self, "metadata", ensure_dict(self.metadata))
        object.__setattr__(self, "version", safe_str(self.version, default=BLOCK_SUMMARY_BUILDER_VERSION))

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
    def error_count(self) -> int:
        return len(self.errors)

    @property
    def warning_count(self) -> int:
        return len(self.warnings)

    def to_dict(self) -> dict[str, Any]:
        valid_items = self.items

        if self.options.sort:
            valid_items = tuple(sort_library_items(valid_items, by=self.options.sort_by))

        result: dict[str, Any] = {
            "ok": self.ok,
            "status": self.status,
            "count": self.count,
            "items": library_items_to_summary_dicts(valid_items, sort=False),
            "invalid_count": self.invalid_count,
            "duplicate_count": self.duplicate_count,
            "error_count": self.error_count,
            "warning_count": self.warning_count,
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
                item_to_summary_dict(item)
                for item in self.duplicates
            ]

        if self.options.include_metadata:
            result["metadata"] = json_safe(self.metadata)

        return result

    @classmethod
    def error(
        cls,
        exc: BaseException,
        *,
        options: BlockSummaryBuilderOptions | None = None,
        include_traceback: bool = False,
    ) -> "BlockSummaryBuildResult":
        error_data = exception_to_dict(exc, include_traceback=include_traceback)
        message = safe_str(error_data.get("message") if error_data else None, default="block summary build failed")

        return cls(
            ok=False,
            status="error",
            items=(),
            invalid_items=(),
            duplicates=(),
            warnings=(),
            errors=(message,),
            options=options or BlockSummaryBuilderOptions(),
            metadata={"exception": error_data},
        )


# ---------------------------------------------------------------------------
# Main builder
# ---------------------------------------------------------------------------

def build_library_item_from_parts(
    *,
    read_result: Any = None,
    validation_result: Any = None,
    fingerprint_result: Any = None,
    documents: Mapping[str, Any] | None = None,
) -> Any:
    """Baut ein LibraryItem aus Reader-, Validation- und Fingerprint-Ergebnissen."""
    normalized_documents = normalize_documents(
        documents if documents is not None else extract_documents_from_any(read_result)
    )

    taxonomy_context = extract_taxonomy_context(
        read_result=read_result,
        validation_result=validation_result,
        documents=normalized_documents,
    )

    package_id = first_non_empty(
        get_attr_or_key(validation_result, "package_id"),
        get_attr_or_key(read_result, "package_id"),
        extract_package_id_from_documents(normalized_documents),
    )

    family_id = first_non_empty(
        get_attr_or_key(validation_result, "family_id"),
        get_attr_or_key(read_result, "family_id"),
        extract_family_id_from_documents(normalized_documents),
    )

    normalized_family_id = normalize_stable_id(family_id, fallback=package_id)

    if not normalized_family_id:
        normalized_family_id = normalize_stable_id(
            first_non_empty(
                extract_relative_package_root(read_result),
                extract_package_root(read_result),
                UNKNOWN_ITEM_ID,
            ),
            fallback=UNKNOWN_ITEM_ID,
        )

    label, description = extract_label_and_description(
        normalized_documents,
        normalized_family_id,
    )

    manifest = get_document_dict(normalized_documents, "vplib.manifest.json")
    identity = get_document_dict(normalized_documents, "family/identity.json")
    classification_doc = get_document_dict(normalized_documents, "family/classification.json")
    physical_base = get_document_dict(normalized_documents, "physical/base.json")

    object_kind = first_non_empty(
        get_attr_or_key(validation_result, "object_kind"),
        get_attr_or_key(read_result, "object_kind"),
        deep_get(manifest, "object_kind"),
        deep_get(identity, "object_kind"),
        deep_get(classification_doc, "object_kind"),
        deep_get(physical_base, "object_kind"),
    )

    default_variant_id, variant_count, variant_ids = extract_variant_summary(normalized_documents)
    classification = LibraryItemClassification(
        domain=taxonomy_context.get("domain"),
        category=taxonomy_context.get("category"),
        subcategory=taxonomy_context.get("subcategory"),
        classification_path=taxonomy_context.get("classification_path") or taxonomy_context.get("taxonomy_path"),
    )
    assets = extract_asset_refs(normalized_documents)

    validation_summary = validation_summary_from_result(validation_result)
    status = status_from_validation_result(validation_result)

    read_ok = get_attr_or_key(read_result, "ok", default=None)
    if read_ok is False and status in {"candidate", "valid"}:
        status = LibraryItemStatus.INVALID.value
        read_errors = ensure_list_of_strings(get_attr_or_key(read_result, "errors"))
        if read_errors and not validation_summary.errors:
            validation_summary = LibraryItemValidationSummary(
                valid=False,
                warning_count=validation_summary.warning_count,
                error_count=len(read_errors),
                fatal_count=validation_summary.fatal_count,
                warnings=validation_summary.warnings,
                errors=tuple(read_errors),
            )

    revision_hash = extract_revision_hash(
        fingerprint=fingerprint_result,
        read_result=read_result,
    )

    metadata = {
        "document_count": len(normalized_documents),
        "document_keys": sorted(normalized_documents.keys()),
        "read_status": get_attr_or_key(read_result, "status"),
        "validation_status": get_attr_or_key(validation_result, "status"),
        "fingerprint_status": get_attr_or_key(fingerprint_result, "status"),
        "taxonomy": taxonomy_context,
    }

    if fingerprint_result is not None:
        metadata["fingerprint"] = {
            "revision_hash": revision_hash,
            "algorithm": get_attr_or_key(fingerprint_result, "algorithm"),
            "file_count": get_attr_or_key(fingerprint_result, "file_count"),
            "included_file_count": get_attr_or_key(fingerprint_result, "included_file_count"),
        }

    if LibraryItem is not None:
        return LibraryItem(
            id=normalized_family_id,
            family_id=normalized_family_id,
            package_id=safe_str(package_id, default="") or None,
            slug=normalized_family_id,
            label=label,
            description=description,
            object_kind=normalize_object_kind(object_kind),
            status=status,
            enabled=extract_enabled(normalized_documents),
            default_variant_id=default_variant_id,
            variant_count=variant_count,
            variant_ids=variant_ids,
            classification=classification,
            assets=assets,
            validation=validation_summary,
            source_path=extract_source_path(read_result),
            package_root=extract_package_root(read_result),
            relative_package_root=extract_relative_package_root(read_result),
            package_version=extract_package_version(normalized_documents),
            schema_version=extract_schema_version(normalized_documents),
            revision_hash=revision_hash,
            created_at=extract_created_at(normalized_documents),
            updated_at=extract_updated_at(normalized_documents),
            scanned_at=extract_scanned_at(read_result) or utc_now_iso(),
            tags=extract_tags(normalized_documents),
            metadata=metadata,
        )

    return {
        "id": normalized_family_id,
        "family_id": normalized_family_id,
        "package_id": safe_str(package_id, default="") or None,
        "slug": normalized_family_id,
        "label": label,
        "description": description,
        "object_kind": normalize_object_kind(object_kind),
        "status": status,
        "enabled": extract_enabled(normalized_documents),
        "default_variant_id": default_variant_id,
        "variant_count": variant_count,
        "variant_ids": list(variant_ids),
        "classification": classification.to_dict(),
        "domain": taxonomy_context.get("domain"),
        "category": taxonomy_context.get("category"),
        "subcategory": taxonomy_context.get("subcategory"),
        "domain_label": taxonomy_context.get("domain_label"),
        "category_label": taxonomy_context.get("category_label"),
        "subcategory_label": taxonomy_context.get("subcategory_label"),
        "classification_path": taxonomy_context.get("classification_path"),
        "taxonomy_path": taxonomy_context.get("taxonomy_path"),
        "taxonomy_version": taxonomy_context.get("taxonomy_version"),
        "taxonomy": taxonomy_context,
        "assets": assets.to_dict(),
        "icon_ref": assets.icon_ref,
        "preview_ref": assets.preview_ref,
        "validation": validation_summary.to_dict(),
        "source_path": extract_source_path(read_result),
        "package_root": extract_package_root(read_result),
        "relative_package_root": extract_relative_package_root(read_result),
        "package_version": extract_package_version(normalized_documents),
        "schema_version": extract_schema_version(normalized_documents),
        "revision_hash": revision_hash,
        "created_at": extract_created_at(normalized_documents),
        "updated_at": extract_updated_at(normalized_documents),
        "scanned_at": extract_scanned_at(read_result) or utc_now_iso(),
        "tags": list(extract_tags(normalized_documents)),
        "metadata": metadata,
    }


def build_library_item_from_read_result(
    read_result: Any,
    *,
    validation_result: Any = None,
    fingerprint_result: Any = None,
) -> Any:
    return build_library_item_from_parts(
        read_result=read_result,
        validation_result=validation_result,
        fingerprint_result=fingerprint_result,
    )


def build_library_items_from_results(
    *,
    read_results: Iterable[Any],
    validation_results: Iterable[Any] | None = None,
    fingerprint_results: Iterable[Any] | None = None,
    options: BlockSummaryBuilderOptions | Mapping[str, Any] | None = None,
) -> list[Any]:
    """
    Baut mehrere LibraryItems aus parallelen Ergebnislisten.

    `options` ist bewusst optional. Der Scan-Service kann dieses Argument
    übergeben, ältere Aufrufer müssen es aber nicht kennen.
    """
    builder_options = coerce_summary_options(options)

    if builder_options.force_taxonomy_reload:
        load_taxonomy_payload(force_reload=True)

    read_list = list(read_results or ())
    validation_list = list(validation_results or ())
    fingerprint_list = list(fingerprint_results or ())

    items: list[Any] = []

    for index, read_result in enumerate(read_list):
        try:
            validation_result = validation_list[index] if index < len(validation_list) else None
            fingerprint_result = fingerprint_list[index] if index < len(fingerprint_list) else None

            item = build_library_item_from_parts(
                read_result=read_result,
                validation_result=validation_result,
                fingerprint_result=fingerprint_result,
            )

            if builder_options.enabled_only and not safe_bool(get_attr_or_key(item, "enabled"), default=True):
                continue

            if not builder_options.include_invalid and not summary_item_is_valid(item):
                continue

            items.append(item)

        except Exception as exc:
            error_item = build_error_summary_item(
                exc,
                read_result=read_result,
                validation_result=validation_list[index] if index < len(validation_list) else None,
                fingerprint_result=fingerprint_list[index] if index < len(fingerprint_list) else None,
            )

            if builder_options.include_invalid:
                items.append(error_item)

    if builder_options.sort:
        try:
            return sort_library_items(items, by=builder_options.sort_by)
        except Exception:
            return items

    return items


def build_error_summary_item(
    exc: BaseException,
    *,
    read_result: Any = None,
    validation_result: Any = None,
    fingerprint_result: Any = None,
) -> Any:
    """Baut ein Fehler-Item, damit ein kaputtes Package nicht die gesamte Liste zerstört."""
    package_id = first_non_empty(
        get_attr_or_key(read_result, "package_id"),
        get_attr_or_key(validation_result, "package_id"),
    )
    family_id = first_non_empty(
        get_attr_or_key(read_result, "family_id"),
        get_attr_or_key(validation_result, "family_id"),
        package_id,
        extract_relative_package_root(read_result),
        UNKNOWN_ERROR_ITEM_ID,
    )
    normalized_id = normalize_stable_id(family_id, fallback=UNKNOWN_ERROR_ITEM_ID)
    error_message = safe_str(exc, default=exc.__class__.__name__)

    validation_summary = LibraryItemValidationSummary(
        valid=False,
        warning_count=0,
        error_count=1,
        fatal_count=0,
        warnings=(),
        errors=(error_message,),
    )

    taxonomy_context = extract_taxonomy_context(read_result=read_result, validation_result=validation_result, documents={})

    if LibraryItem is not None:
        return LibraryItem(
            id=normalized_id,
            family_id=normalized_id,
            package_id=safe_str(package_id, default="") or None,
            slug=normalized_id,
            label=humanize_identifier(normalized_id),
            description="Library item could not be built.",
            object_kind="unknown",
            status=LibraryItemStatus.ERROR.value,
            enabled=False,
            default_variant_id=DEFAULT_VARIANT_ID,
            variant_count=0,
            variant_ids=(),
            classification=LibraryItemClassification(
                domain=taxonomy_context.get("domain"),
                category=taxonomy_context.get("category"),
                subcategory=taxonomy_context.get("subcategory"),
                classification_path=taxonomy_context.get("classification_path"),
            ),
            assets=LibraryItemAssetRefs(),
            validation=validation_summary,
            source_path=extract_source_path(read_result),
            package_root=extract_package_root(read_result),
            relative_package_root=extract_relative_package_root(read_result),
            revision_hash=extract_revision_hash(fingerprint_result, read_result),
            scanned_at=utc_now_iso(),
            tags=(),
            metadata={
                "exception": exception_to_dict(exc),
                "read_status": get_attr_or_key(read_result, "status"),
                "validation_status": get_attr_or_key(validation_result, "status"),
                "taxonomy": taxonomy_context,
            },
        )

    return {
        "id": normalized_id,
        "family_id": normalized_id,
        "package_id": safe_str(package_id, default="") or None,
        "label": humanize_identifier(normalized_id),
        "object_kind": "unknown",
        "status": "error",
        "enabled": False,
        "domain": taxonomy_context.get("domain"),
        "category": taxonomy_context.get("category"),
        "subcategory": taxonomy_context.get("subcategory"),
        "taxonomy": taxonomy_context,
        "validation": validation_summary.to_dict(),
        "source_path": extract_source_path(read_result),
        "revision_hash": extract_revision_hash(fingerprint_result, read_result),
        "metadata": {
            "exception": exception_to_dict(exc),
            "taxonomy": taxonomy_context,
        },
    }


def coerce_summary_options(
    value: BlockSummaryBuilderOptions | Mapping[str, Any] | None = None,
) -> BlockSummaryBuilderOptions:
    """Normalisiert optionale Summary-Options."""
    if isinstance(value, BlockSummaryBuilderOptions):
        return value

    if value is None:
        return BlockSummaryBuilderOptions()

    try:
        data = ensure_dict(value)

        if not data:
            return BlockSummaryBuilderOptions()

        allowed = {
            "include_invalid",
            "enabled_only",
            "sort",
            "sort_by",
            "include_metadata",
            "include_validation_details",
            "include_taxonomy_labels",
            "force_taxonomy_reload",
        }

        return BlockSummaryBuilderOptions(
            **{key: item for key, item in data.items() if key in allowed}
        )

    except Exception:
        return BlockSummaryBuilderOptions()


def build_block_summary_result(
    *,
    items: Iterable[Any],
    options: BlockSummaryBuilderOptions | Mapping[str, Any] | None = None,
) -> BlockSummaryBuildResult:
    """Baut ein SummaryResult aus LibraryItems."""
    builder_options = coerce_summary_options(options)

    if builder_options.force_taxonomy_reload:
        load_taxonomy_payload(force_reload=True)

    try:
        item_list = list(items or ())
        valid_items: list[Any] = []
        invalid_items: list[Any] = []

        for item in item_list:
            try:
                enabled = safe_bool(get_attr_or_key(item, "enabled"), default=True)

                if builder_options.enabled_only and not enabled:
                    continue

                if summary_item_is_valid(item):
                    valid_items.append(item)
                else:
                    invalid_items.append(item)

            except Exception:
                invalid_items.append(item)

        indexed, duplicates = index_library_items_by_id(valid_items)
        unique_valid_items = list(indexed.values())

        if builder_options.sort:
            unique_valid_items = sort_library_items(
                unique_valid_items,
                by=builder_options.sort_by,
            )

        errors: list[str] = []
        warnings: list[str] = []

        if duplicates:
            warnings.append(f"{len(duplicates)} duplicate library item ids detected")

        taxonomy_payload = load_taxonomy_payload()
        if builder_options.include_taxonomy_labels and not taxonomy_payload.get("ok"):
            warnings.append("taxonomy payload unavailable; taxonomy labels may be derived from slugs")

        visible_invalid_items = tuple(invalid_items if builder_options.include_invalid else ())

        if unique_valid_items and visible_invalid_items:
            status = "partial"
        elif unique_valid_items:
            status = "valid"
        elif visible_invalid_items:
            status = "invalid"
        else:
            status = "empty"

        return BlockSummaryBuildResult(
            ok=status != "error",
            status=status,
            items=tuple(unique_valid_items),
            invalid_items=visible_invalid_items,
            duplicates=tuple(duplicates),
            warnings=tuple(warnings),
            errors=tuple(errors),
            options=builder_options,
            metadata={
                "input_count": len(item_list),
                "valid_input_count": len(valid_items),
                "invalid_input_count": len(invalid_items),
                "unique_valid_count": len(unique_valid_items),
                "duplicate_count": len(duplicates),
                "taxonomy": {
                    "available": taxonomy_available(),
                    "payload_ok": bool(taxonomy_payload.get("ok")),
                    "taxonomy_version": safe_str(taxonomy_payload.get("taxonomy_version"), default="") or None,
                    "cache_loaded_at": _TAXONOMY_CACHE.get("loaded_at"),
                },
                "imports": get_import_status(),
            },
        )

    except Exception as exc:
        return BlockSummaryBuildResult.error(
            exc,
            options=builder_options,
        )


def build_block_summary_result_from_pipeline(
    *,
    read_results: Iterable[Any],
    validation_results: Iterable[Any] | None = None,
    fingerprint_results: Iterable[Any] | None = None,
    options: BlockSummaryBuilderOptions | Mapping[str, Any] | None = None,
) -> BlockSummaryBuildResult:
    """Baut ein vollständiges SummaryResult aus Reader-, Validator- und Fingerprint-Ergebnissen."""
    builder_options = coerce_summary_options(options)

    try:
        items = build_library_items_from_results(
            read_results=read_results,
            validation_results=validation_results,
            fingerprint_results=fingerprint_results,
            options=BlockSummaryBuilderOptions(
                include_invalid=True,
                enabled_only=builder_options.enabled_only,
                sort=builder_options.sort,
                sort_by=builder_options.sort_by,
                include_metadata=builder_options.include_metadata,
                include_validation_details=builder_options.include_validation_details,
                include_taxonomy_labels=builder_options.include_taxonomy_labels,
                force_taxonomy_reload=builder_options.force_taxonomy_reload,
            ),
        )

        return build_block_summary_result(
            items=items,
            options=builder_options,
        )

    except Exception as exc:
        return BlockSummaryBuildResult.error(
            exc,
            options=builder_options,
        )


# ---------------------------------------------------------------------------
# Response helpers
# ---------------------------------------------------------------------------

def build_blocks_response_from_items(
    items: Iterable[Any],
    *,
    options: BlockSummaryBuilderOptions | Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    result = build_block_summary_result(
        items=items,
        options=options,
    )
    return result.to_dict()


def build_blocks_response_from_pipeline(
    *,
    read_results: Iterable[Any],
    validation_results: Iterable[Any] | None = None,
    fingerprint_results: Iterable[Any] | None = None,
    options: BlockSummaryBuilderOptions | Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    result = build_block_summary_result_from_pipeline(
        read_results=read_results,
        validation_results=validation_results,
        fingerprint_results=fingerprint_results,
        options=options,
    )
    return result.to_dict()


def build_single_summary_dict(
    *,
    read_result: Any = None,
    validation_result: Any = None,
    fingerprint_result: Any = None,
    documents: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    try:
        item = build_library_item_from_parts(
            read_result=read_result,
            validation_result=validation_result,
            fingerprint_result=fingerprint_result,
            documents=documents,
        )

        return item_to_summary_dict(item)

    except Exception as exc:
        return {
            "ok": False,
            "status": "error",
            "error": exception_to_dict(exc),
        }


# ---------------------------------------------------------------------------
# Health
# ---------------------------------------------------------------------------

def get_import_status() -> dict[str, Any]:
    return {
        "item": {
            "ok": _ITEM_IMPORT_ERROR is None,
            "error": exception_to_dict(_ITEM_IMPORT_ERROR),
        },
        "detail": {
            "ok": _DETAIL_IMPORT_ERROR is None,
            "error": exception_to_dict(_DETAIL_IMPORT_ERROR),
        },
        "validation": {
            "ok": _VALIDATION_IMPORT_ERROR is None,
            "error": exception_to_dict(_VALIDATION_IMPORT_ERROR),
        },
        "reader": {
            "ok": _READER_IMPORT_ERROR is None,
            "error": exception_to_dict(_READER_IMPORT_ERROR),
        },
        "fingerprint": {
            "ok": _FINGERPRINT_IMPORT_ERROR is None,
            "error": exception_to_dict(_FINGERPRINT_IMPORT_ERROR),
        },
        "taxonomy": {
            "ok": _TAXONOMY_IMPORT_ERROR is None,
            "error": exception_to_dict(_TAXONOMY_IMPORT_ERROR),
        },
    }


def get_block_summary_builder_health() -> dict[str, Any]:
    warnings: list[str] = []
    errors: list[str] = []

    imports = get_import_status()

    for name, status in imports.items():
        if not status.get("ok"):
            warnings.append(f"{name} import failed; fallback helpers may be active")

    try:
        options = BlockSummaryBuilderOptions()
        options_dict = options.to_dict()
    except Exception as exc:
        options_dict = {}
        errors.append(f"could not build summary options: {exc}")

    try:
        safe_int_self_test = safe_int("999999", default=500, minimum=1, maximum=5000)
        if safe_int_self_test != 5000:
            errors.append(f"safe_int maximum self-test failed: expected 5000, got {safe_int_self_test}")
    except Exception as exc:
        errors.append(f"safe_int maximum self-test failed: {exc}")

    try:
        empty_result = build_block_summary_result(items=(), options=BlockSummaryBuilderOptions())
        self_test_ok = empty_result.status == "empty"
    except Exception as exc:
        self_test_ok = False
        errors.append(f"summary self-test failed: {exc}")

    taxonomy_health: dict[str, Any] = {
        "available": taxonomy_available(),
        "import_error": exception_to_dict(_TAXONOMY_IMPORT_ERROR),
        "cache_loaded_at": _TAXONOMY_CACHE.get("loaded_at"),
    }
    if taxonomy_available():
        try:
            taxonomy_payload = load_taxonomy_payload()
            taxonomy_health.update(
                {
                    "payload_ok": bool(taxonomy_payload.get("ok")),
                    "taxonomy_version": safe_str(taxonomy_payload.get("taxonomy_version"), default="") or None,
                    "error": taxonomy_payload.get("error"),
                }
            )
        except Exception as exc:
            taxonomy_health.update(
                {
                    "payload_ok": False,
                    "error": exception_to_dict(exc),
                }
            )
            warnings.append("taxonomy payload health check failed")

    healthy = len(errors) == 0

    return {
        "ok": healthy,
        "healthy": healthy,
        "component": BLOCK_SUMMARY_BUILDER_COMPONENT,
        "version": BLOCK_SUMMARY_BUILDER_VERSION,
        "generated_at": utc_now_iso(),
        "self_test": {
            "ok": self_test_ok,
        },
        "options": options_dict,
        "taxonomy": json_safe(taxonomy_health),
        "imports": imports,
        "warnings": warnings,
        "errors": errors,
    }


def assert_block_summary_builder_ready() -> None:
    health = get_block_summary_builder_health()

    if health.get("healthy"):
        return

    raise RuntimeError(
        f"block summary builder is not ready: errors={health.get('errors')}"
    )


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

__all__: Final[tuple[str, ...]] = (
    "BLOCK_SUMMARY_BUILDER_VERSION",
    "BLOCK_SUMMARY_BUILDER_COMPONENT",
    "DEFAULT_SUMMARY_STATUS",
    "DEFAULT_SUMMARY_SORT",
    "SUMMARY_STATUS_VALUES",
    "SUMMARY_SORT_VALUES",
    "BlockSummaryBuilderOptions",
    "BlockSummaryBuildResult",
    "utc_now_iso",
    "exception_to_dict",
    "json_safe",
    "clear_taxonomy_cache",
    "taxonomy_available",
    "normalize_taxonomy_key",
    "load_taxonomy_payload",
    "get_taxonomy_lookup",
    "get_cached_taxonomy_version",
    "build_taxonomy_lookup_from_payload",
    "taxonomy_entry",
    "taxonomy_label",
    "normalize_taxonomy_path",
    "extract_taxonomy_context",
    "enrich_summary_with_taxonomy",
    "normalize_summary_status",
    "normalize_sort_mode",
    "get_attr_or_key",
    "item_to_summary_dict",
    "summary_item_is_valid",
    "validation_summary_from_result",
    "status_from_validation_result",
    "extract_documents_from_any",
    "extract_revision_hash",
    "extract_source_path",
    "extract_relative_package_root",
    "extract_package_root",
    "extract_scanned_at",
    "extract_package_version",
    "extract_schema_version",
    "extract_created_at",
    "extract_updated_at",
    "extract_classification",
    "extract_asset_refs",
    "extract_variant_summary",
    "extract_label_and_description",
    "extract_tags",
    "extract_enabled",
    "build_library_item_from_parts",
    "build_library_item_from_read_result",
    "build_library_items_from_results",
    "build_error_summary_item",
    "coerce_summary_options",
    "build_block_summary_result",
    "build_block_summary_result_from_pipeline",
    "build_blocks_response_from_items",
    "build_blocks_response_from_pipeline",
    "build_single_summary_dict",
    "get_import_status",
    "get_block_summary_builder_health",
    "assert_block_summary_builder_ready",
)