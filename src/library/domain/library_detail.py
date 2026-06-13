# services/vectoplan-library/src/library/domain/library_detail.py
"""
Domain-Modell für die Detailansicht eines Creative-Library-Blocks/-Objekts.

Ein `LibraryItemDetail` ist die ausführliche, API-taugliche Repräsentation
eines konkreten VPLIB-Pakets aus `src/library/source`.

Diese Datei ist für die spätere Detailroute gedacht:

    GET /api/v1/vplib/library/blocks/<block_id>

Sie bündelt:

- Summary / LibraryItem
- Manifest
- Module-Dokument
- Family-Dokumente
- Taxonomie / Klassifikation
- Varianten
- Editor-Profile
- Render-Profile
- Physical-/Material-/Calculation-Daten
- Manufacturer-/Analysis-/Dynamic-Daten
- Dokumentgruppen
- Validierungsstatus
- Source-/Package-Metadaten
- optional rohe Dokumentdaten

Diese Datei bleibt unabhängig von Flask, Datenbank und konkreter Route.

Taxonomie-Regel:

    Backend-Taxonomie ist kanonisch für:
    - Domain/Reiter
    - Kategorie
    - Subkategorie
    - Labels
    - taxonomy_path
    - classification_path
    - source_path
    - taxonomy_version

Version 0.2.0:

- Detailmodell enthält `LibraryTaxonomyDetail`.
- Detailantworten enthalten `taxonomy` und `classification`.
- Summary-Daten werden mit Taxonomie-Feldern angereichert.
- `family/classification.json`, Manifest, Inventory und Item-Metadaten werden
  als Taxonomiequellen berücksichtigt.
- Source-Detail enthält zusätzlich taxonomy/source_path, classification_path
  und taxonomy_version.
- Variantenantworten und Detailantworten bleiben stabil gegen fehlende optionale
  Dokumente.
- Fallback-`safe_int` unterstützt weiterhin `maximum`.
"""

from __future__ import annotations

import re
import traceback
from collections.abc import Iterable, Mapping
from dataclasses import asdict, dataclass, field, is_dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Final


# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

LIBRARY_DETAIL_MODEL_VERSION: Final[str] = "0.2.0"
LIBRARY_DETAIL_MODEL_COMPONENT: Final[str] = "library-detail-model"

MANIFEST_DOCUMENT_KEY: Final[str] = "vplib.manifest.json"
MODULES_DOCUMENT_KEY: Final[str] = "vplib.modules.json"

FAMILY_PREFIX: Final[str] = "family/"
VARIANTS_PREFIX: Final[str] = "variants/"
EDITOR_PREFIX: Final[str] = "editor/"
RENDER_PREFIX: Final[str] = "render/"
PHYSICAL_PREFIX: Final[str] = "physical/"
MATERIAL_PREFIX: Final[str] = "material/"
CALCULATION_PREFIX: Final[str] = "calculation/"
MANUFACTURER_PREFIX: Final[str] = "manufacturer/"
ANALYSIS_PREFIX: Final[str] = "analysis/"
DYNAMIC_PREFIX: Final[str] = "dynamic/"
DOCS_PREFIX: Final[str] = "docs/"
TESTS_PREFIX: Final[str] = "tests/"
ASSETS_PREFIX: Final[str] = "assets/"

KNOWN_DOCUMENT_GROUPS: Final[tuple[str, ...]] = (
    "root",
    "family",
    "variants",
    "editor",
    "render",
    "physical",
    "material",
    "calculation",
    "manufacturer",
    "analysis",
    "dynamic",
    "docs",
    "tests",
    "assets",
    "unknown",
)

DETAIL_PROFILE_GROUPS: Final[tuple[str, ...]] = (
    "family",
    "variants",
    "editor",
    "render",
    "physical",
    "material",
    "calculation",
    "manufacturer",
    "analysis",
    "dynamic",
)

DEFAULT_DETAIL_STATUS: Final[str] = "candidate"
DEFAULT_VARIANT_ID_FALLBACK: Final[str] = "default"
UNKNOWN_LIBRARY_ITEM_ID: Final[str] = "unknown.library_item"
UNKNOWN_TAXONOMY_VALUE: Final[str] = "unknown"

CANONICAL_SOURCE_DEPTH: Final[int] = 4
LEGACY_SOURCE_DEPTH: Final[int] = 3

TAXONOMY_DOCUMENT_KEY: Final[str] = "family/classification.json"


# ---------------------------------------------------------------------------
# Generic fallback helpers used before optional imports
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


def _fallback_normalize_status(value: Any) -> str:
    text = _fallback_safe_str(value, default="unknown").lower()

    if text in {"unknown", "candidate", "valid", "invalid", "duplicate", "error", "disabled"}:
        return text

    return "unknown"


def _fallback_normalize_object_kind(value: Any) -> str:
    text = _fallback_safe_str(value, default="unknown").lower()

    aliases = {
        "block": "cell_block",
        "cell": "cell_block",
        "cellblock": "cell_block",
        "cell-block": "cell_block",
        "cell_block": "cell_block",
        "multi_cell": "multi_cell_module",
        "multi-cell": "multi_cell_module",
        "module": "multi_cell_module",
        "object": "catalog_object",
        "catalog": "catalog_object",
        "adaptive": "adaptive_system",
        "system": "adaptive_system",
    }

    normalized = aliases.get(text, text)

    if normalized in {"cell_block", "multi_cell_module", "catalog_object", "adaptive_system"}:
        return normalized

    return "unknown"


def _fallback_humanize_identifier(value: Any, *, fallback: str = "Unnamed Library Item") -> str:
    try:
        text = _fallback_safe_str(value, default="")

        if not text:
            return fallback

        last_part = text.replace(":", ".").replace("/", ".").replace("\\", ".").split(".")[-1]
        last_part = last_part.replace("_", " ").replace("-", " ").strip()

        if not last_part:
            return fallback

        return " ".join(part.capitalize() for part in last_part.split())

    except Exception:
        return fallback


def _fallback_normalize_taxonomy_slug(value: Any, *, fallback: str = "") -> str:
    try:
        text = _fallback_safe_str(value, default="").lower()

        if not text:
            return fallback

        replacements = {
            "ä": "ae",
            "ö": "oe",
            "ü": "ue",
            "ß": "ss",
        }

        for source, target in replacements.items():
            text = text.replace(source, target)

        text = re.sub(r"[^a-z0-9]+", "_", text)
        text = re.sub(r"_+", "_", text).strip("_-")

        return text or fallback

    except Exception:
        return fallback


def _fallback_normalize_taxonomy_path(value: Any) -> str | None:
    try:
        if value is None:
            return None

        if isinstance(value, Path):
            raw_parts = value.parts
        elif isinstance(value, str):
            raw_parts = value.replace("\\", "/").split("/")
        elif isinstance(value, Iterable) and not isinstance(value, (bytes, Mapping)):
            raw_parts = list(value)
        else:
            raw_parts = str(value).replace("\\", "/").split("/")

        parts: list[str] = []

        for part in raw_parts:
            text = _fallback_safe_str(part, default="")
            if not text or text in {".", ".."}:
                continue
            if text.endswith(":"):
                continue

            normalized = _fallback_normalize_taxonomy_slug(text)
            if normalized:
                parts.append(normalized)

        path = "/".join(parts)
        return path or None

    except Exception:
        return None


def _fallback_build_taxonomy_path(
    domain: Any = None,
    category: Any = None,
    subcategory: Any = None,
) -> str | None:
    parts = [
        _fallback_normalize_taxonomy_slug(domain),
        _fallback_normalize_taxonomy_slug(category),
        _fallback_normalize_taxonomy_slug(subcategory),
    ]
    parts = [part for part in parts if part]
    return "/".join(parts) if parts else None


def json_safe(value: Any) -> Any:
    """Wandelt beliebige Werte defensiv in JSON-kompatible Strukturen um."""
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

        return str(value)

    except Exception as exc:
        return {
            "serialization_error": exception_to_dict(exc),
            "fallback": str(type(value)),
        }


# ---------------------------------------------------------------------------
# Optional dependency on library_item
# ---------------------------------------------------------------------------

_LIBRARY_ITEM_IMPORT_ERROR: BaseException | None = None

try:
    from library.domain.library_item import (
        DEFAULT_VARIANT_ID,
        LibraryItem,
        LibraryItemValidationSummary,
        build_taxonomy_path,
        deep_get,
        ensure_dict,
        ensure_list_of_strings,
        first_non_empty,
        humanize_identifier,
        normalize_object_kind,
        normalize_stable_id,
        normalize_status,
        normalize_taxonomy_path,
        normalize_taxonomy_slug,
        normalize_variant_id,
        safe_bool,
        safe_int,
        safe_path_str,
        safe_str,
    )
except Exception as import_exc:  # pragma: no cover - defensive fallback
    _LIBRARY_ITEM_IMPORT_ERROR = import_exc

    DEFAULT_VARIANT_ID = DEFAULT_VARIANT_ID_FALLBACK
    LibraryItem = None  # type: ignore[assignment]

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
    normalize_status = _fallback_normalize_status
    normalize_object_kind = _fallback_normalize_object_kind
    normalize_taxonomy_slug = _fallback_normalize_taxonomy_slug
    normalize_taxonomy_path = _fallback_normalize_taxonomy_path
    build_taxonomy_path = _fallback_build_taxonomy_path
    humanize_identifier = _fallback_humanize_identifier

    @dataclass(frozen=True)
    class LibraryItemValidationSummary:  # type: ignore[no-redef]
        valid: bool = False
        warning_count: int = 0
        error_count: int = 0
        fatal_count: int = 0
        warnings: tuple[str, ...] = field(default_factory=tuple)
        errors: tuple[str, ...] = field(default_factory=tuple)

        def __post_init__(self) -> None:
            object.__setattr__(self, "valid", safe_bool(self.valid, default=False))
            object.__setattr__(self, "warning_count", safe_int(self.warning_count, default=0, minimum=0))
            object.__setattr__(self, "error_count", safe_int(self.error_count, default=0, minimum=0))
            object.__setattr__(self, "fatal_count", safe_int(self.fatal_count, default=0, minimum=0))
            object.__setattr__(self, "warnings", tuple(ensure_list_of_strings(self.warnings)))
            object.__setattr__(self, "errors", tuple(ensure_list_of_strings(self.errors)))

        def to_dict(self) -> dict[str, Any]:
            return {
                "valid": self.valid,
                "warning_count": self.warning_count,
                "error_count": self.error_count,
                "fatal_count": self.fatal_count,
                "warnings": list(self.warnings),
                "errors": list(self.errors),
            }


# ---------------------------------------------------------------------------
# Generic helpers
# ---------------------------------------------------------------------------

def document_group_for_key(document_key: Any) -> str:
    """Ordnet einen Dokumentpfad einer fachlichen Gruppe zu."""
    key = safe_str(document_key, default="").replace("\\", "/").strip("/")

    if not key:
        return "unknown"

    if "/" not in key:
        return "root"

    if key.startswith(FAMILY_PREFIX):
        return "family"

    if key.startswith(VARIANTS_PREFIX):
        return "variants"

    if key.startswith(EDITOR_PREFIX):
        return "editor"

    if key.startswith(RENDER_PREFIX):
        return "render"

    if key.startswith(PHYSICAL_PREFIX):
        return "physical"

    if key.startswith(MATERIAL_PREFIX):
        return "material"

    if key.startswith(CALCULATION_PREFIX):
        return "calculation"

    if key.startswith(MANUFACTURER_PREFIX):
        return "manufacturer"

    if key.startswith(ANALYSIS_PREFIX):
        return "analysis"

    if key.startswith(DYNAMIC_PREFIX):
        return "dynamic"

    if key.startswith(DOCS_PREFIX):
        return "docs"

    if key.startswith(TESTS_PREFIX):
        return "tests"

    if key.startswith(ASSETS_PREFIX):
        return "assets"

    return "unknown"


def document_name_for_key(document_key: Any) -> str:
    """Gibt den Dateinamen eines Dokumentkeys zurück."""
    key = safe_str(document_key, default="").replace("\\", "/").strip("/")

    if not key:
        return ""

    return key.split("/")[-1]


def normalize_document_key(document_key: Any) -> str:
    """Normalisiert einen Dokumentkey auf eine paketrelative Form."""
    key = safe_str(document_key, default="")
    key = key.replace("\\", "/").strip("/")

    while "//" in key:
        key = key.replace("//", "/")

    return key


def normalize_documents(documents: Mapping[str, Any] | None) -> dict[str, Any]:
    """Normalisiert ein Dokument-Mapping robust."""
    if not isinstance(documents, Mapping):
        return {}

    normalized: dict[str, Any] = {}

    for raw_key, value in documents.items():
        try:
            key = normalize_document_key(raw_key)

            if not key:
                continue

            normalized[key] = value

        except Exception:
            continue

    return normalized


def get_document(
    documents: Mapping[str, Any] | None,
    key: str,
    *,
    default: Any = None,
) -> Any:
    """Liest ein Dokument defensiv aus dem Mapping."""
    normalized = normalize_documents(documents)
    normalized_key = normalize_document_key(key)

    return normalized.get(normalized_key, default)


def get_document_dict(
    documents: Mapping[str, Any] | None,
    key: str,
) -> dict[str, Any]:
    """Liest ein Dokument als Dict."""
    return ensure_dict(get_document(documents, key, default={}))


def group_documents(
    documents: Mapping[str, Any] | None,
) -> dict[str, dict[str, Any]]:
    """Gruppiert Dokumente nach fachlichem Prefix."""
    normalized = normalize_documents(documents)
    grouped: dict[str, dict[str, Any]] = {
        group: {}
        for group in KNOWN_DOCUMENT_GROUPS
    }

    for key, value in normalized.items():
        group = document_group_for_key(key)
        grouped.setdefault(group, {})
        grouped[group][key] = value

    return {
        group: values
        for group, values in grouped.items()
        if values
    }


def extract_nested_document_group(
    documents: Mapping[str, Any] | None,
    group: str,
) -> dict[str, Any]:
    """
    Extrahiert eine Dokumentgruppe als Mapping mit kurzen Namen.

    Beispiel:
      "family/identity.json" -> "identity"
    """

    grouped = group_documents(documents)
    group_docs = grouped.get(group, {})
    result: dict[str, Any] = {}

    for key, value in group_docs.items():
        name = document_name_for_key(key)
        short_name = name

        if short_name.endswith(".json"):
            short_name = short_name[:-5]

        if not short_name:
            short_name = key

        result[short_name] = value

    return result


def make_validation_summary(value: Any) -> LibraryItemValidationSummary:
    """Normalisiert verschiedene Validierungsformen."""
    if isinstance(value, LibraryItemValidationSummary):
        return value

    if isinstance(value, Mapping):
        warnings = ensure_list_of_strings(
            first_non_empty(
                value.get("warnings"),
                value.get("warning_messages"),
                default=[],
            )
        )
        errors = ensure_list_of_strings(
            first_non_empty(
                value.get("errors"),
                value.get("error_messages"),
                default=[],
            )
        )

        if not warnings and "issues" in value:
            for issue in ensure_list_of_strings(value.get("issues")):
                errors.append(issue)

        valid = safe_bool(
            first_non_empty(
                value.get("valid"),
                value.get("ok"),
                default=False,
            ),
            default=False,
        )

        return LibraryItemValidationSummary(
            valid=valid,
            warning_count=safe_int(
                first_non_empty(value.get("warning_count"), len(warnings)),
                default=len(warnings),
                minimum=0,
            ),
            error_count=safe_int(
                first_non_empty(value.get("error_count"), len(errors)),
                default=len(errors),
                minimum=0,
            ),
            fatal_count=safe_int(value.get("fatal_count"), default=0, minimum=0),
            warnings=tuple(warnings),
            errors=tuple(errors),
        )

    if value is not None:
        warnings = ensure_list_of_strings(get_item_attr(value, "warnings"))
        errors = ensure_list_of_strings(get_item_attr(value, "errors"))

        return LibraryItemValidationSummary(
            valid=safe_bool(get_item_attr(value, "valid"), default=False),
            warning_count=safe_int(get_item_attr(value, "warning_count"), default=len(warnings), minimum=0),
            error_count=safe_int(get_item_attr(value, "error_count"), default=len(errors), minimum=0),
            fatal_count=safe_int(get_item_attr(value, "fatal_count"), default=0, minimum=0),
            warnings=tuple(warnings),
            errors=tuple(errors),
        )

    return LibraryItemValidationSummary(
        valid=False,
        warning_count=0,
        error_count=0,
        fatal_count=0,
        warnings=(),
        errors=(),
    )


def item_to_summary_dict(item: Any) -> dict[str, Any]:
    """Serialisiert ein LibraryItem oder Mapping robust zu einer Summary."""
    if item is None:
        return {}

    try:
        if hasattr(item, "to_summary_dict") and callable(item.to_summary_dict):
            return ensure_dict(item.to_summary_dict())

        if hasattr(item, "to_dict") and callable(item.to_dict):
            data = ensure_dict(item.to_dict())
            keys = (
                "id",
                "family_id",
                "package_id",
                "slug",
                "label",
                "description",
                "object_kind",
                "status",
                "enabled",
                "domain",
                "category",
                "subcategory",
                "domain_label",
                "category_label",
                "subcategory_label",
                "classification_path",
                "taxonomy_path",
                "taxonomy_version",
                "taxonomy",
                "default_variant_id",
                "variant_count",
                "icon_ref",
                "preview_ref",
                "revision_hash",
                "source_path",
                "package_root",
                "relative_package_root",
                "package_version",
                "updated_at",
                "scanned_at",
            )
            return {
                key: data.get(key)
                for key in keys
                if key in data
            }

        if isinstance(item, Mapping):
            return dict(item)

    except Exception as exc:
        return {
            "status": "error",
            "error": exception_to_dict(exc),
        }

    return {
        "value": str(item),
    }


def get_item_attr(item: Any, name: str, *, default: Any = None) -> Any:
    """Liest ein Attribut oder Mapping-Feld aus einem Item."""
    if item is None:
        return default

    try:
        if isinstance(item, Mapping):
            return item.get(name, default)

        return getattr(item, name, default)

    except Exception:
        return default


def extract_package_id_from_documents(documents: Mapping[str, Any] | None) -> str | None:
    manifest = get_document_dict(documents, MANIFEST_DOCUMENT_KEY)

    package_id = first_non_empty(
        deep_get(manifest, "package_id"),
        deep_get(manifest, "id"),
    )

    text = safe_str(package_id, default="")
    return text or None


def extract_family_id_from_documents(documents: Mapping[str, Any] | None) -> str | None:
    manifest = get_document_dict(documents, MANIFEST_DOCUMENT_KEY)
    identity = get_document_dict(documents, "family/identity.json")

    family_id = first_non_empty(
        deep_get(manifest, "family_id"),
        deep_get(identity, "family_id"),
        deep_get(identity, "id"),
        deep_get(manifest, "id"),
        deep_get(manifest, "package_id"),
    )

    normalized = normalize_stable_id(family_id)

    return normalized or None


# ---------------------------------------------------------------------------
# Taxonomy helpers
# ---------------------------------------------------------------------------

def extract_taxonomy_from_documents(
    documents: Mapping[str, Any] | None,
    *,
    item: Any = None,
) -> dict[str, Any]:
    """
    Extrahiert Taxonomie aus Item, Manifest, Classification und Inventory.
    """

    normalized = normalize_documents(documents)
    manifest = get_document_dict(normalized, MANIFEST_DOCUMENT_KEY)
    classification = get_document_dict(normalized, TAXONOMY_DOCUMENT_KEY)
    inventory = get_document_dict(normalized, "editor/inventory.json")

    item_summary = item_to_summary_dict(item)
    item_taxonomy = ensure_dict(item_summary.get("taxonomy"))
    metadata = ensure_dict(get_item_attr(item, "metadata"))
    metadata_taxonomy = ensure_dict(metadata.get("taxonomy"))

    domain = first_non_empty(
        item_taxonomy.get("domain"),
        metadata_taxonomy.get("domain"),
        item_summary.get("domain"),
        get_item_attr(item, "domain"),
        deep_get(manifest, "domain"),
        deep_get(manifest, "classification.domain"),
        deep_get(classification, "domain"),
        deep_get(classification, "classification.domain"),
        deep_get(inventory, "domain"),
    )
    category = first_non_empty(
        item_taxonomy.get("category"),
        metadata_taxonomy.get("category"),
        item_summary.get("category"),
        get_item_attr(item, "category"),
        deep_get(manifest, "category"),
        deep_get(manifest, "classification.category"),
        deep_get(classification, "category"),
        deep_get(classification, "classification.category"),
        deep_get(inventory, "category"),
    )
    subcategory = first_non_empty(
        item_taxonomy.get("subcategory"),
        metadata_taxonomy.get("subcategory"),
        item_summary.get("subcategory"),
        get_item_attr(item, "subcategory"),
        deep_get(manifest, "subcategory"),
        deep_get(manifest, "classification.subcategory"),
        deep_get(classification, "subcategory"),
        deep_get(classification, "classification.subcategory"),
        deep_get(inventory, "subcategory"),
    )

    domain = normalize_taxonomy_slug(domain) if domain else None
    category = normalize_taxonomy_slug(category) if category else None
    subcategory = normalize_taxonomy_slug(subcategory) if subcategory else None

    labels = (
        ensure_dict(item_taxonomy.get("labels"))
        or ensure_dict(metadata_taxonomy.get("labels"))
        or ensure_dict(deep_get(classification, "labels"))
        or ensure_dict(deep_get(manifest, "labels"))
        or ensure_dict(deep_get(inventory, "labels"))
    )

    domain_label = first_non_empty(
        item_taxonomy.get("domain_label"),
        metadata_taxonomy.get("domain_label"),
        item_summary.get("domain_label"),
        labels.get("domain"),
        humanize_identifier(domain) if domain else None,
    )
    category_label = first_non_empty(
        item_taxonomy.get("category_label"),
        metadata_taxonomy.get("category_label"),
        item_summary.get("category_label"),
        labels.get("category"),
        humanize_identifier(category) if category else None,
    )
    subcategory_label = first_non_empty(
        item_taxonomy.get("subcategory_label"),
        metadata_taxonomy.get("subcategory_label"),
        item_summary.get("subcategory_label"),
        labels.get("subcategory"),
        humanize_identifier(subcategory) if subcategory else None,
    )

    taxonomy_path = normalize_taxonomy_path(
        first_non_empty(
            item_taxonomy.get("taxonomy_path"),
            metadata_taxonomy.get("taxonomy_path"),
            item_summary.get("taxonomy_path"),
            deep_get(manifest, "taxonomy_path"),
            deep_get(classification, "taxonomy_path"),
            deep_get(manifest, "classification_path"),
            deep_get(manifest, "classification.path"),
            deep_get(classification, "classification_path"),
            deep_get(classification, "path"),
        )
    ) or build_taxonomy_path(domain, category, subcategory)

    classification_path = normalize_taxonomy_path(
        first_non_empty(
            item_taxonomy.get("classification_path"),
            metadata_taxonomy.get("classification_path"),
            item_summary.get("classification_path"),
            deep_get(manifest, "classification_path"),
            deep_get(manifest, "classification.path"),
            deep_get(classification, "classification_path"),
            deep_get(classification, "path"),
            taxonomy_path,
        )
    )

    source_path = normalize_taxonomy_path(
        first_non_empty(
            item_taxonomy.get("source_path"),
            metadata_taxonomy.get("source_path"),
            item_summary.get("source_path"),
            deep_get(manifest, "source_path"),
            deep_get(classification, "source_path"),
            deep_get(inventory, "source_path"),
        )
    )

    taxonomy_version = safe_str(
        first_non_empty(
            item_taxonomy.get("taxonomy_version"),
            metadata_taxonomy.get("taxonomy_version"),
            item_summary.get("taxonomy_version"),
            deep_get(manifest, "taxonomy_version"),
            deep_get(manifest, "classification.taxonomy_version"),
            deep_get(classification, "taxonomy_version"),
            deep_get(classification, "classification.taxonomy_version"),
            deep_get(inventory, "taxonomy_version"),
        ),
        default="",
    ) or None

    source = (
        ensure_dict(item_taxonomy.get("source"))
        or ensure_dict(metadata_taxonomy.get("source"))
        or {}
    )

    return {
        "domain": domain,
        "category": category,
        "subcategory": subcategory,
        "domain_label": safe_str(domain_label, default="") or None,
        "category_label": safe_str(category_label, default="") or None,
        "subcategory_label": safe_str(subcategory_label, default="") or None,
        "taxonomy_path": taxonomy_path,
        "classification_path": classification_path,
        "source_path": source_path,
        "taxonomy_version": taxonomy_version,
        "labels": {
            "domain": safe_str(domain_label, default="") or None,
            "category": safe_str(category_label, default="") or None,
            "subcategory": safe_str(subcategory_label, default="") or None,
        },
        "source": {
            **source,
            "has_item_taxonomy": bool(item_taxonomy),
            "has_metadata_taxonomy": bool(metadata_taxonomy),
            "has_classification_document": bool(classification),
        },
    }


def build_classification_payload(
    documents: Mapping[str, Any] | None,
    *,
    taxonomy: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    """
    Baut den Detail-Klassifikationsblock mit Dokumentquellen.
    """

    normalized = normalize_documents(documents)
    manifest = get_document_dict(normalized, MANIFEST_DOCUMENT_KEY)
    classification = get_document_dict(normalized, TAXONOMY_DOCUMENT_KEY)
    inventory = get_document_dict(normalized, "editor/inventory.json")
    taxonomy_payload = ensure_dict(taxonomy) or extract_taxonomy_from_documents(normalized)

    return {
        "domain": taxonomy_payload.get("domain"),
        "category": taxonomy_payload.get("category"),
        "subcategory": taxonomy_payload.get("subcategory"),
        "domain_label": taxonomy_payload.get("domain_label"),
        "category_label": taxonomy_payload.get("category_label"),
        "subcategory_label": taxonomy_payload.get("subcategory_label"),
        "taxonomy_path": taxonomy_payload.get("taxonomy_path"),
        "classification_path": taxonomy_payload.get("classification_path"),
        "source_path": taxonomy_payload.get("source_path"),
        "taxonomy_version": taxonomy_payload.get("taxonomy_version"),
        "labels": taxonomy_payload.get("labels"),
        "source": taxonomy_payload.get("source"),
        "documents": {
            "classification": json_safe(classification),
            "manifest_classification": json_safe(manifest.get("classification")),
            "inventory_classification": json_safe(inventory.get("classification")),
        },
    }


# ---------------------------------------------------------------------------
# Detail submodels
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class LibraryDocumentEntry:
    """Ein einzelnes Dokument innerhalb eines VPLIB-Pakets."""

    key: str
    group: str
    name: str
    present: bool = True
    data: Any = None
    error: dict[str, Any] | None = None

    def __post_init__(self) -> None:
        normalized_key = normalize_document_key(self.key)
        object.__setattr__(self, "key", normalized_key)
        object.__setattr__(self, "group", safe_str(self.group, default=document_group_for_key(normalized_key)))
        object.__setattr__(self, "name", safe_str(self.name, default=document_name_for_key(normalized_key)))
        object.__setattr__(self, "present", safe_bool(self.present, default=True))
        object.__setattr__(self, "error", ensure_dict(self.error) if self.error else None)

    @classmethod
    def from_raw(
        cls,
        key: Any,
        data: Any,
        *,
        error: dict[str, Any] | None = None,
    ) -> "LibraryDocumentEntry":
        normalized_key = normalize_document_key(key)

        return cls(
            key=normalized_key,
            group=document_group_for_key(normalized_key),
            name=document_name_for_key(normalized_key),
            present=True,
            data=data,
            error=error,
        )

    def to_dict(self, *, include_data: bool = True) -> dict[str, Any]:
        result: dict[str, Any] = {
            "key": self.key,
            "group": self.group,
            "name": self.name,
            "present": self.present,
            "error": json_safe(self.error),
        }

        if include_data:
            result["data"] = json_safe(self.data)

        return result


@dataclass(frozen=True)
class LibraryTaxonomyDetail:
    """Taxonomie-Detailblock für Detailantworten."""

    domain: str | None = None
    category: str | None = None
    subcategory: str | None = None
    domain_label: str | None = None
    category_label: str | None = None
    subcategory_label: str | None = None
    taxonomy_path: str | None = None
    classification_path: str | None = None
    source_path: str | None = None
    taxonomy_version: str | None = None
    labels: dict[str, Any] = field(default_factory=dict)
    source: dict[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        domain = normalize_taxonomy_slug(self.domain) if self.domain else None
        category = normalize_taxonomy_slug(self.category) if self.category else None
        subcategory = normalize_taxonomy_slug(self.subcategory) if self.subcategory else None

        taxonomy_path = normalize_taxonomy_path(self.taxonomy_path) or build_taxonomy_path(domain, category, subcategory)
        classification_path = normalize_taxonomy_path(self.classification_path) or taxonomy_path
        source_path = normalize_taxonomy_path(self.source_path)

        domain_label = safe_str(self.domain_label, default="") or (humanize_identifier(domain) if domain else None)
        category_label = safe_str(self.category_label, default="") or (humanize_identifier(category) if category else None)
        subcategory_label = safe_str(self.subcategory_label, default="") or (humanize_identifier(subcategory) if subcategory else None)

        labels = ensure_dict(self.labels)
        labels.setdefault("domain", domain_label)
        labels.setdefault("category", category_label)
        labels.setdefault("subcategory", subcategory_label)

        object.__setattr__(self, "domain", domain)
        object.__setattr__(self, "category", category)
        object.__setattr__(self, "subcategory", subcategory)
        object.__setattr__(self, "domain_label", domain_label)
        object.__setattr__(self, "category_label", category_label)
        object.__setattr__(self, "subcategory_label", subcategory_label)
        object.__setattr__(self, "taxonomy_path", taxonomy_path)
        object.__setattr__(self, "classification_path", classification_path)
        object.__setattr__(self, "source_path", source_path)
        object.__setattr__(self, "taxonomy_version", safe_str(self.taxonomy_version, default="") or None)
        object.__setattr__(self, "labels", labels)
        object.__setattr__(self, "source", ensure_dict(self.source))

    @classmethod
    def from_payload(cls, payload: Mapping[str, Any] | None) -> "LibraryTaxonomyDetail":
        data = ensure_dict(payload)

        return cls(
            domain=data.get("domain"),
            category=data.get("category"),
            subcategory=data.get("subcategory"),
            domain_label=data.get("domain_label"),
            category_label=data.get("category_label"),
            subcategory_label=data.get("subcategory_label"),
            taxonomy_path=data.get("taxonomy_path"),
            classification_path=data.get("classification_path"),
            source_path=data.get("source_path"),
            taxonomy_version=data.get("taxonomy_version"),
            labels=ensure_dict(data.get("labels")),
            source=ensure_dict(data.get("source")),
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "domain": self.domain,
            "category": self.category,
            "subcategory": self.subcategory,
            "domain_label": self.domain_label,
            "category_label": self.category_label,
            "subcategory_label": self.subcategory_label,
            "taxonomy_path": self.taxonomy_path,
            "classification_path": self.classification_path,
            "source_path": self.source_path,
            "taxonomy_version": self.taxonomy_version,
            "labels": json_safe(self.labels),
            "source": json_safe(self.source),
        }


@dataclass(frozen=True)
class LibraryVariantDetail:
    """Detailinformationen zu einer Variante."""

    variant_id: str
    label: str | None = None
    description: str | None = None
    is_default: bool = False
    status: str = "unknown"
    sort_order: int = 0
    document_key: str | None = None
    overrides: dict[str, Any] = field(default_factory=dict)
    data: dict[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        object.__setattr__(self, "variant_id", normalize_variant_id(self.variant_id))
        object.__setattr__(self, "label", safe_str(self.label, default="") or None)
        object.__setattr__(self, "description", safe_str(self.description, default="") or None)
        object.__setattr__(self, "is_default", safe_bool(self.is_default, default=False))
        object.__setattr__(self, "status", normalize_status(self.status))
        object.__setattr__(self, "sort_order", safe_int(self.sort_order, default=0, minimum=0))
        object.__setattr__(self, "document_key", normalize_document_key(self.document_key) if self.document_key else None)
        object.__setattr__(self, "overrides", ensure_dict(self.overrides))
        object.__setattr__(self, "data", ensure_dict(self.data))

    @classmethod
    def from_document(
        cls,
        *,
        variant_id: Any,
        data: Mapping[str, Any] | None,
        document_key: Any = None,
        default_variant_id: Any = DEFAULT_VARIANT_ID,
        sort_order: int = 0,
    ) -> "LibraryVariantDetail":
        safe_data = ensure_dict(data)

        normalized_variant_id = normalize_variant_id(
            first_non_empty(
                deep_get(safe_data, "variant_id"),
                deep_get(safe_data, "id"),
                variant_id,
            )
        )
        normalized_default_id = normalize_variant_id(default_variant_id)

        label = first_non_empty(
            deep_get(safe_data, "label"),
            deep_get(safe_data, "name"),
            humanize_identifier(normalized_variant_id),
        )

        description = first_non_empty(
            deep_get(safe_data, "description"),
            deep_get(safe_data, "summary"),
        )

        overrides = first_non_empty(
            deep_get(safe_data, "overrides"),
            deep_get(safe_data, "variant_overrides"),
            default={},
        )

        status = first_non_empty(
            deep_get(safe_data, "status"),
            deep_get(safe_data, "lifecycle_status"),
            "unknown",
        )

        return cls(
            variant_id=normalized_variant_id,
            label=safe_str(label, default="") or None,
            description=safe_str(description, default="") or None,
            is_default=normalized_variant_id == normalized_default_id,
            status=normalize_status(status),
            sort_order=safe_int(sort_order, default=0, minimum=0),
            document_key=normalize_document_key(document_key) if document_key else None,
            overrides=ensure_dict(overrides),
            data=safe_data,
        )

    def to_dict(self, *, include_data: bool = True) -> dict[str, Any]:
        result: dict[str, Any] = {
            "variant_id": self.variant_id,
            "id": self.variant_id,
            "label": self.label,
            "description": self.description,
            "is_default": self.is_default,
            "status": self.status,
            "sort_order": self.sort_order,
            "document_key": self.document_key,
            "overrides": json_safe(self.overrides),
        }

        if include_data:
            result["data"] = json_safe(self.data)

        return result


@dataclass(frozen=True)
class LibraryModuleDetail:
    """Detailinformationen zu einem aktiven oder bekannten VPLIB-Modul."""

    module_name: str
    active: bool = False
    required: bool = False
    optional: bool = False
    status: str = "unknown"
    version: str | None = None
    documents: tuple[str, ...] = field(default_factory=tuple)
    missing_documents: tuple[str, ...] = field(default_factory=tuple)

    def __post_init__(self) -> None:
        object.__setattr__(self, "module_name", safe_str(self.module_name, default="unknown"))
        object.__setattr__(self, "active", safe_bool(self.active, default=False))
        object.__setattr__(self, "required", safe_bool(self.required, default=False))
        object.__setattr__(self, "optional", safe_bool(self.optional, default=False))
        object.__setattr__(self, "status", safe_str(self.status, default="unknown"))
        object.__setattr__(self, "version", safe_str(self.version, default="") or None)
        object.__setattr__(self, "documents", tuple(ensure_list_of_strings(self.documents)))
        object.__setattr__(self, "missing_documents", tuple(ensure_list_of_strings(self.missing_documents)))

    def to_dict(self) -> dict[str, Any]:
        return {
            "module_name": self.module_name,
            "active": self.active,
            "required": self.required,
            "optional": self.optional,
            "status": self.status,
            "version": self.version,
            "documents": list(self.documents),
            "missing_documents": list(self.missing_documents),
        }


@dataclass(frozen=True)
class LibrarySourceDetail:
    """Source-/Dateisystem-Metadaten eines Detailobjekts."""

    source_path: str | None = None
    package_root: str | None = None
    relative_package_root: str | None = None
    source_root: str | None = None
    discovered_at: str | None = None
    scanned_at: str | None = None
    revision_hash: str | None = None
    classification_path: str | None = None
    taxonomy_path: str | None = None
    taxonomy_version: str | None = None

    def __post_init__(self) -> None:
        object.__setattr__(self, "source_path", safe_path_str(self.source_path))
        object.__setattr__(self, "package_root", safe_path_str(self.package_root))
        object.__setattr__(self, "relative_package_root", safe_path_str(self.relative_package_root))
        object.__setattr__(self, "source_root", safe_path_str(self.source_root))
        object.__setattr__(self, "discovered_at", safe_str(self.discovered_at, default="") or None)
        object.__setattr__(self, "scanned_at", safe_str(self.scanned_at, default="") or None)
        object.__setattr__(self, "revision_hash", safe_str(self.revision_hash, default="") or None)
        object.__setattr__(self, "classification_path", normalize_taxonomy_path(self.classification_path))
        object.__setattr__(self, "taxonomy_path", normalize_taxonomy_path(self.taxonomy_path))
        object.__setattr__(self, "taxonomy_version", safe_str(self.taxonomy_version, default="") or None)

    def to_dict(self) -> dict[str, Any]:
        return {
            "source_path": self.source_path,
            "package_root": self.package_root,
            "relative_package_root": self.relative_package_root,
            "source_root": self.source_root,
            "discovered_at": self.discovered_at,
            "scanned_at": self.scanned_at,
            "revision_hash": self.revision_hash,
            "classification_path": self.classification_path,
            "taxonomy_path": self.taxonomy_path,
            "taxonomy_version": self.taxonomy_version,
        }


# ---------------------------------------------------------------------------
# Extraction helpers
# ---------------------------------------------------------------------------

def extract_variants_from_documents(
    documents: Mapping[str, Any] | None,
) -> list[LibraryVariantDetail]:
    """
    Extrahiert Varianten aus `variants/index.json`, `variants/default.json`
    und allen weiteren `variants/*.json`-Dokumenten.
    """

    normalized = normalize_documents(documents)
    variants_index = get_document_dict(normalized, "variants/index.json")
    default_variant_doc = get_document_dict(normalized, "variants/default.json")

    default_variant_id = first_non_empty(
        deep_get(variants_index, "default_variant_id"),
        deep_get(variants_index, "default"),
        deep_get(default_variant_doc, "variant_id"),
        deep_get(default_variant_doc, "id"),
        DEFAULT_VARIANT_ID,
    )

    variant_entries: list[LibraryVariantDetail] = []
    seen: set[str] = set()

    raw_variants = first_non_empty(
        deep_get(variants_index, "variants"),
        deep_get(variants_index, "variant_ids"),
        default=[],
    )

    if isinstance(raw_variants, Mapping):
        iterable: Iterable[Any] = raw_variants.items()
    elif isinstance(raw_variants, Iterable) and not isinstance(raw_variants, (str, bytes)):
        iterable = raw_variants
    elif raw_variants:
        iterable = [raw_variants]
    else:
        iterable = []

    sort_order = 0

    for raw_entry in iterable:
        try:
            if isinstance(raw_entry, tuple) and len(raw_entry) == 2:
                raw_id, raw_data = raw_entry
                data = ensure_dict(raw_data)
                variant_id = first_non_empty(
                    deep_get(data, "variant_id"),
                    deep_get(data, "id"),
                    raw_id,
                )
            elif isinstance(raw_entry, Mapping):
                data = ensure_dict(raw_entry)
                variant_id = first_non_empty(
                    deep_get(data, "variant_id"),
                    deep_get(data, "id"),
                    deep_get(data, "slug"),
                )
            else:
                data = {}
                variant_id = raw_entry

            normalized_variant_id = normalize_variant_id(variant_id)

            if normalized_variant_id in seen:
                continue

            candidate_document_keys = (
                f"variants/{normalized_variant_id}.json",
                "variants/default.json" if normalized_variant_id == normalize_variant_id(default_variant_id) else "",
            )

            document_key = None
            document_data: dict[str, Any] = {}

            for candidate_key in candidate_document_keys:
                if not candidate_key:
                    continue
                candidate_data = get_document_dict(normalized, candidate_key)
                if candidate_data:
                    document_key = candidate_key
                    document_data = candidate_data
                    break

            merged_data: dict[str, Any] = {}
            merged_data.update(data)
            merged_data.update(document_data)

            variant_entries.append(
                LibraryVariantDetail.from_document(
                    variant_id=normalized_variant_id,
                    data=merged_data,
                    document_key=document_key,
                    default_variant_id=default_variant_id,
                    sort_order=sort_order,
                )
            )
            seen.add(normalized_variant_id)
            sort_order += 1

        except Exception:
            continue

    try:
        default_id = normalize_variant_id(
            first_non_empty(
                deep_get(default_variant_doc, "variant_id"),
                deep_get(default_variant_doc, "id"),
                default_variant_id,
            )
        )

        if default_id not in seen:
            variant_entries.append(
                LibraryVariantDetail.from_document(
                    variant_id=default_id,
                    data=default_variant_doc,
                    document_key="variants/default.json" if default_variant_doc else None,
                    default_variant_id=default_variant_id,
                    sort_order=sort_order,
                )
            )
            seen.add(default_id)
            sort_order += 1

    except Exception:
        pass

    for key, data in normalized.items():
        try:
            if not key.startswith(VARIANTS_PREFIX):
                continue

            if key in {"variants/index.json", "variants/default.json"}:
                continue

            filename = document_name_for_key(key)

            if not filename.endswith(".json"):
                continue

            guessed_variant_id = filename[:-5]
            safe_data = ensure_dict(data)
            normalized_variant_id = normalize_variant_id(
                first_non_empty(
                    deep_get(safe_data, "variant_id"),
                    deep_get(safe_data, "id"),
                    guessed_variant_id,
                )
            )

            if normalized_variant_id in seen:
                continue

            variant_entries.append(
                LibraryVariantDetail.from_document(
                    variant_id=normalized_variant_id,
                    data=safe_data,
                    document_key=key,
                    default_variant_id=default_variant_id,
                    sort_order=sort_order,
                )
            )
            seen.add(normalized_variant_id)
            sort_order += 1

        except Exception:
            continue

    return sorted(
        variant_entries,
        key=lambda item: (
            not item.is_default,
            item.sort_order,
            item.variant_id,
        ),
    )


def _extract_module_names(value: Any) -> set[str]:
    """Extrahiert Modulnamen aus Liste, Dict oder String."""
    result: set[str] = set()

    if value is None:
        return result

    if isinstance(value, str):
        text = value.strip()
        if text:
            result.add(text)
        return result

    if isinstance(value, Mapping):
        for key, item in value.items():
            name = first_non_empty(
                deep_get(item, "name") if isinstance(item, Mapping) else None,
                deep_get(item, "module_name") if isinstance(item, Mapping) else None,
                deep_get(item, "id") if isinstance(item, Mapping) else None,
                key,
            )
            text = safe_str(name, default="")
            if text:
                result.add(text)
        return result

    if isinstance(value, Iterable):
        for item in value:
            if isinstance(item, Mapping):
                name = first_non_empty(
                    deep_get(item, "name"),
                    deep_get(item, "module_name"),
                    deep_get(item, "id"),
                )
            else:
                name = item

            text = safe_str(name, default="")
            if text:
                result.add(text)

    return result


def extract_modules_from_documents(
    documents: Mapping[str, Any] | None,
) -> list[LibraryModuleDetail]:
    """Extrahiert Moduldetails aus `vplib.modules.json`."""
    normalized = normalize_documents(documents)
    modules_doc = get_document_dict(normalized, MODULES_DOCUMENT_KEY)

    active_modules = _extract_module_names(
        first_non_empty(
            deep_get(modules_doc, "active_modules"),
            deep_get(modules_doc, "modules"),
            deep_get(modules_doc, "enabled_modules"),
            default=[],
        )
    )
    required_modules = _extract_module_names(
        deep_get(modules_doc, "required_modules")
    )
    optional_modules = _extract_module_names(
        deep_get(modules_doc, "optional_modules")
    )

    module_versions = ensure_dict(deep_get(modules_doc, "module_versions"))
    module_documents = ensure_dict(deep_get(modules_doc, "module_documents"))

    all_module_names = sorted(active_modules | required_modules | optional_modules)

    result: list[LibraryModuleDetail] = []

    for module_name in all_module_names:
        try:
            docs = ensure_list_of_strings(module_documents.get(module_name))
            missing_docs = [
                doc
                for doc in docs
                if normalize_document_key(doc) not in normalized
            ]

            active = module_name in active_modules
            required = module_name in required_modules
            optional = module_name in optional_modules

            if active and not missing_docs:
                status = "available"
            elif active and missing_docs:
                status = "incomplete"
            elif not active:
                status = "inactive"
            else:
                status = "unknown"

            version = safe_str(module_versions.get(module_name), default="") or None

            result.append(
                LibraryModuleDetail(
                    module_name=module_name,
                    active=active,
                    required=required,
                    optional=optional,
                    status=status,
                    version=version,
                    documents=tuple(docs),
                    missing_documents=tuple(missing_docs),
                )
            )

        except Exception:
            result.append(
                LibraryModuleDetail(
                    module_name=safe_str(module_name, default="unknown"),
                    active=False,
                    required=False,
                    optional=False,
                    status="error",
                    version=None,
                    documents=(),
                    missing_documents=(),
                )
            )

    return result


def build_document_entries(
    documents: Mapping[str, Any] | None,
) -> list[LibraryDocumentEntry]:
    """Baut Dokumenteinträge aus einem Dokument-Mapping."""
    normalized = normalize_documents(documents)
    entries: list[LibraryDocumentEntry] = []

    for key in sorted(normalized.keys()):
        try:
            entries.append(
                LibraryDocumentEntry.from_raw(
                    key=key,
                    data=normalized[key],
                )
            )
        except Exception as exc:
            entries.append(
                LibraryDocumentEntry(
                    key=normalize_document_key(key),
                    group=document_group_for_key(key),
                    name=document_name_for_key(key),
                    present=True,
                    data=None,
                    error=exception_to_dict(exc),
                )
            )

    return entries


def build_profile_groups(
    documents: Mapping[str, Any] | None,
) -> dict[str, dict[str, Any]]:
    """Baut gruppierte Profilansichten für Detailantworten."""
    result: dict[str, dict[str, Any]] = {}

    for group in DETAIL_PROFILE_GROUPS:
        try:
            result[group] = extract_nested_document_group(documents, group)
        except Exception as exc:
            result[group] = {
                "_error": exception_to_dict(exc),
            }

    return result


def build_family_payload(documents: Mapping[str, Any] | None) -> dict[str, Any]:
    """Baut eine kompakte Family-Ansicht."""
    family_group = extract_nested_document_group(documents, "family")

    return {
        "identity": json_safe(family_group.get("identity", {})),
        "classification": json_safe(family_group.get("classification", {})),
        "lifecycle": json_safe(family_group.get("lifecycle", {})),
        "aliases": json_safe(family_group.get("aliases", {})),
        "metadata": json_safe(family_group.get("metadata", {})),
        "documents": json_safe(family_group),
    }


def build_package_payload(documents: Mapping[str, Any] | None) -> dict[str, Any]:
    """Baut Root-Package-Daten aus Manifest und Modules."""
    manifest = get_document_dict(documents, MANIFEST_DOCUMENT_KEY)
    modules = get_document_dict(documents, MODULES_DOCUMENT_KEY)

    return {
        "package_id": first_non_empty(
            deep_get(manifest, "package_id"),
            deep_get(manifest, "id"),
        ),
        "family_id": first_non_empty(
            deep_get(manifest, "family_id"),
            extract_family_id_from_documents(documents),
        ),
        "object_kind": normalize_object_kind(deep_get(manifest, "object_kind")),
        "package_version": first_non_empty(
            deep_get(manifest, "package_version"),
            deep_get(manifest, "version"),
        ),
        "schema_version": first_non_empty(
            deep_get(manifest, "schema_version"),
            deep_get(manifest, "vplib_schema_version"),
        ),
        "manifest": json_safe(manifest),
        "modules": json_safe(modules),
    }


# ---------------------------------------------------------------------------
# Main detail model
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class LibraryItemDetail:
    """Vollständiges Detailmodell für einen Creative-Library-Eintrag."""

    id: str
    family_id: str
    summary: dict[str, Any]
    package: dict[str, Any]
    family: dict[str, Any]
    variants: tuple[LibraryVariantDetail, ...]
    modules: tuple[LibraryModuleDetail, ...]
    profiles: dict[str, dict[str, Any]]
    validation: LibraryItemValidationSummary
    source: LibrarySourceDetail
    taxonomy: LibraryTaxonomyDetail = field(default_factory=LibraryTaxonomyDetail)
    classification: dict[str, Any] = field(default_factory=dict)
    documents: tuple[LibraryDocumentEntry, ...] = field(default_factory=tuple)
    raw_documents: dict[str, Any] = field(default_factory=dict)
    status: str = DEFAULT_DETAIL_STATUS
    generated_at: str = field(default_factory=utc_now_iso)
    warnings: tuple[str, ...] = field(default_factory=tuple)
    errors: tuple[str, ...] = field(default_factory=tuple)
    model_version: str = LIBRARY_DETAIL_MODEL_VERSION

    def __post_init__(self) -> None:
        object.__setattr__(self, "id", normalize_stable_id(self.id, fallback=UNKNOWN_LIBRARY_ITEM_ID) or UNKNOWN_LIBRARY_ITEM_ID)
        object.__setattr__(self, "family_id", normalize_stable_id(self.family_id, fallback=self.id) or self.id)
        object.__setattr__(self, "summary", ensure_dict(self.summary))
        object.__setattr__(self, "package", ensure_dict(self.package))
        object.__setattr__(self, "family", ensure_dict(self.family))
        object.__setattr__(self, "variants", tuple(self.variants or ()))
        object.__setattr__(self, "modules", tuple(self.modules or ()))
        object.__setattr__(self, "profiles", ensure_dict(self.profiles))

        if not isinstance(self.validation, LibraryItemValidationSummary):
            object.__setattr__(self, "validation", make_validation_summary(self.validation))

        if not isinstance(self.source, LibrarySourceDetail):
            object.__setattr__(self, "source", LibrarySourceDetail())

        if not isinstance(self.taxonomy, LibraryTaxonomyDetail):
            object.__setattr__(self, "taxonomy", LibraryTaxonomyDetail.from_payload(self.taxonomy))

        object.__setattr__(self, "classification", ensure_dict(self.classification))
        object.__setattr__(self, "documents", tuple(self.documents or ()))
        object.__setattr__(self, "raw_documents", normalize_documents(self.raw_documents))
        object.__setattr__(self, "status", normalize_status(self.status))
        object.__setattr__(self, "generated_at", safe_str(self.generated_at, default=utc_now_iso()))
        object.__setattr__(self, "warnings", tuple(ensure_list_of_strings(self.warnings)))
        object.__setattr__(self, "errors", tuple(ensure_list_of_strings(self.errors)))
        object.__setattr__(self, "model_version", safe_str(self.model_version, default=LIBRARY_DETAIL_MODEL_VERSION))

    @property
    def variant_count(self) -> int:
        return len(self.variants)

    @property
    def module_count(self) -> int:
        return len(self.modules)

    @property
    def document_count(self) -> int:
        return len(self.documents)

    @property
    def is_valid(self) -> bool:
        return self.status == "valid" and self.validation.valid

    def to_dict(
        self,
        *,
        include_raw_documents: bool = True,
        include_document_data: bool = False,
    ) -> dict[str, Any]:
        """
        JSON-kompatible Detailserialisierung.

        `include_raw_documents=True`
          Gibt die gelesenen VPLIB-Dokumente unter `raw_documents` aus.

        `include_document_data=False`
          Die Dokumentliste enthält standardmäßig nur Metadaten. Die Rohdaten
          stehen bereits in `raw_documents`.
        """

        result: dict[str, Any] = {
            "id": self.id,
            "family_id": self.family_id,
            "status": self.status,
            "is_valid": self.is_valid,
            "summary": json_safe(self.summary),
            "taxonomy": self.taxonomy.to_dict(),
            "classification": json_safe(self.classification),
            "package": json_safe(self.package),
            "family": json_safe(self.family),
            "variants": [
                variant.to_dict(include_data=include_raw_documents)
                for variant in self.variants
            ],
            "variant_count": self.variant_count,
            "modules": [
                module.to_dict()
                for module in self.modules
            ],
            "module_count": self.module_count,
            "profiles": json_safe(self.profiles),
            "validation": self.validation.to_dict(),
            "source": self.source.to_dict(),
            "documents": [
                document.to_dict(include_data=include_document_data)
                for document in self.documents
            ],
            "document_count": self.document_count,
            "document_keys": [
                document.key
                for document in self.documents
            ],
            "generated_at": self.generated_at,
            "warnings": list(self.warnings),
            "errors": list(self.errors),
            "model_version": self.model_version,
        }

        if include_raw_documents:
            result["raw_documents"] = json_safe(self.raw_documents)

        return result

    def to_public_dict(self) -> dict[str, Any]:
        """Detailantwort mit Rohdokumenten, aber ohne doppelte Dokumentdaten."""
        return self.to_dict(
            include_raw_documents=True,
            include_document_data=False,
        )

    def to_summary_dict(self) -> dict[str, Any]:
        """Kompakte Detail-Metadaten ohne Rohdokumente."""
        return {
            "id": self.id,
            "family_id": self.family_id,
            "status": self.status,
            "is_valid": self.is_valid,
            "summary": json_safe(self.summary),
            "taxonomy": self.taxonomy.to_dict(),
            "classification": json_safe(self.classification),
            "variant_count": self.variant_count,
            "module_count": self.module_count,
            "document_count": self.document_count,
            "validation": self.validation.to_dict(),
            "source": self.source.to_dict(),
            "generated_at": self.generated_at,
            "warnings": list(self.warnings),
            "errors": list(self.errors),
            "model_version": self.model_version,
        }

    @classmethod
    def from_documents(
        cls,
        documents: Mapping[str, Any] | None,
        *,
        item: Any = None,
        validation: Any = None,
        source_path: Any = None,
        package_root: Any = None,
        relative_package_root: Any = None,
        source_root: Any = None,
        discovered_at: Any = None,
        scanned_at: Any = None,
        revision_hash: Any = None,
        status: str = DEFAULT_DETAIL_STATUS,
        include_raw_documents: bool = True,
    ) -> "LibraryItemDetail":
        """
        Baut ein Detailmodell aus gelesenen VPLIB-Dokumenten.

        Diese Factory ist defensiv:
        - fehlende optionale Dokumente sind erlaubt
        - kaputte Zusatzdaten erzeugen Warnungen statt harter Fehler
        - wenn `LibraryItem.from_documents` verfügbar ist, wird automatisch
          eine Summary erzeugt
        """

        warnings: list[str] = []
        errors: list[str] = []

        normalized_documents = normalize_documents(documents)

        if _LIBRARY_ITEM_IMPORT_ERROR is not None:
            warnings.append(
                "library_item import failed; detail model uses fallback helpers"
            )

        validation_summary = make_validation_summary(validation)

        generated_scanned_at = safe_str(scanned_at, default="") or utc_now_iso()
        normalized_revision_hash = safe_str(revision_hash, default="") or None

        built_item = item

        if built_item is None:
            try:
                item_class = globals().get("LibraryItem")

                if item_class is not None and hasattr(item_class, "from_documents"):
                    built_item = item_class.from_documents(
                        normalized_documents,
                        source_path=source_path,
                        package_root=package_root,
                        relative_package_root=relative_package_root,
                        revision_hash=normalized_revision_hash,
                        status=status,
                        validation=validation_summary,
                        scanned_at=generated_scanned_at,
                    )

            except TypeError:
                try:
                    item_class = globals().get("LibraryItem")

                    if item_class is not None and hasattr(item_class, "from_documents"):
                        built_item = item_class.from_documents(
                            normalized_documents,
                            source_path=source_path,
                            package_root=package_root,
                            relative_package_root=relative_package_root,
                            revision_hash=normalized_revision_hash,
                            status=status,
                            scanned_at=generated_scanned_at,
                        )
                except Exception as exc:
                    warnings.append(
                        f"could not build LibraryItem summary from documents: {exc}"
                    )

            except Exception as exc:
                warnings.append(
                    f"could not build LibraryItem summary from documents: {exc}"
                )

        summary = item_to_summary_dict(built_item)
        taxonomy_payload = extract_taxonomy_from_documents(
            normalized_documents,
            item=built_item or summary,
        )
        taxonomy_detail = LibraryTaxonomyDetail.from_payload(taxonomy_payload)
        classification_payload = build_classification_payload(
            normalized_documents,
            taxonomy=taxonomy_detail.to_dict(),
        )

        family_id = normalize_stable_id(
            first_non_empty(
                get_item_attr(built_item, "family_id"),
                summary.get("family_id"),
                extract_family_id_from_documents(normalized_documents),
            )
        )

        if not family_id:
            family_id = UNKNOWN_LIBRARY_ITEM_ID
            errors.append("family_id could not be resolved")

        item_id = normalize_stable_id(
            first_non_empty(
                get_item_attr(built_item, "id"),
                summary.get("id"),
                family_id,
            ),
            fallback=family_id,
        )

        package_payload = build_package_payload(normalized_documents)
        family_payload = build_family_payload(normalized_documents)
        variants = tuple(extract_variants_from_documents(normalized_documents))
        modules = tuple(extract_modules_from_documents(normalized_documents))
        profiles = build_profile_groups(normalized_documents)
        document_entries = tuple(build_document_entries(normalized_documents))

        source_detail = LibrarySourceDetail(
            source_path=safe_path_str(
                first_non_empty(
                    source_path,
                    taxonomy_payload.get("source_path"),
                    get_item_attr(built_item, "source_path"),
                    summary.get("source_path"),
                )
            ),
            package_root=safe_path_str(
                first_non_empty(
                    package_root,
                    get_item_attr(built_item, "package_root"),
                    summary.get("package_root"),
                )
            ),
            relative_package_root=safe_path_str(
                first_non_empty(
                    relative_package_root,
                    get_item_attr(built_item, "relative_package_root"),
                    summary.get("relative_package_root"),
                )
            ),
            source_root=safe_path_str(source_root),
            discovered_at=safe_str(discovered_at, default="") or None,
            scanned_at=generated_scanned_at,
            revision_hash=safe_str(
                first_non_empty(
                    normalized_revision_hash,
                    get_item_attr(built_item, "revision_hash"),
                    summary.get("revision_hash"),
                ),
                default="",
            ) or None,
            classification_path=taxonomy_payload.get("classification_path"),
            taxonomy_path=taxonomy_payload.get("taxonomy_path"),
            taxonomy_version=taxonomy_payload.get("taxonomy_version"),
        )

        if not summary:
            summary = {
                "id": item_id,
                "family_id": family_id,
                "label": humanize_identifier(family_id),
                "status": normalize_status(status),
            }

        summary.setdefault("id", item_id)
        summary.setdefault("family_id", family_id)
        summary.setdefault("label", humanize_identifier(family_id))
        summary.setdefault("variant_count", len(variants))
        summary.setdefault("taxonomy", taxonomy_detail.to_dict())
        summary.setdefault("domain", taxonomy_detail.domain)
        summary.setdefault("category", taxonomy_detail.category)
        summary.setdefault("subcategory", taxonomy_detail.subcategory)
        summary.setdefault("domain_label", taxonomy_detail.domain_label)
        summary.setdefault("category_label", taxonomy_detail.category_label)
        summary.setdefault("subcategory_label", taxonomy_detail.subcategory_label)
        summary.setdefault("taxonomy_path", taxonomy_detail.taxonomy_path)
        summary.setdefault("classification_path", taxonomy_detail.classification_path)
        summary.setdefault("taxonomy_version", taxonomy_detail.taxonomy_version)

        if source_detail.revision_hash and "revision_hash" not in summary:
            summary["revision_hash"] = source_detail.revision_hash

        if validation_summary.error_count > 0 or validation_summary.fatal_count > 0:
            normalized_status = "invalid"
        elif validation_summary.valid:
            normalized_status = "valid"
        else:
            normalized_status = normalize_status(status)

        raw_documents = normalized_documents if include_raw_documents else {}

        return cls(
            id=item_id,
            family_id=family_id,
            summary=summary,
            taxonomy=taxonomy_detail,
            classification=classification_payload,
            package=package_payload,
            family=family_payload,
            variants=variants,
            modules=modules,
            profiles=profiles,
            validation=validation_summary,
            source=source_detail,
            documents=document_entries,
            raw_documents=raw_documents,
            status=normalized_status,
            generated_at=utc_now_iso(),
            warnings=tuple(warnings),
            errors=tuple(errors),
        )

    @classmethod
    def from_item_and_documents(
        cls,
        item: Any,
        documents: Mapping[str, Any] | None,
        *,
        validation: Any = None,
        source_root: Any = None,
        include_raw_documents: bool = True,
    ) -> "LibraryItemDetail":
        """Convenience-Factory, wenn bereits ein `LibraryItem` existiert."""
        return cls.from_documents(
            documents,
            item=item,
            validation=validation,
            source_path=get_item_attr(item, "source_path"),
            package_root=get_item_attr(item, "package_root"),
            relative_package_root=get_item_attr(item, "relative_package_root"),
            source_root=source_root,
            scanned_at=get_item_attr(item, "scanned_at"),
            revision_hash=get_item_attr(item, "revision_hash"),
            status=get_item_attr(item, "status", default=DEFAULT_DETAIL_STATUS),
            include_raw_documents=include_raw_documents,
        )


# ---------------------------------------------------------------------------
# Response helpers
# ---------------------------------------------------------------------------

def build_detail_response(
    detail: LibraryItemDetail | Mapping[str, Any] | None,
    *,
    ok: bool | None = None,
    include_raw_documents: bool = True,
) -> dict[str, Any]:
    """Baut eine standardisierte API-Antwort für eine Detailroute."""
    try:
        if isinstance(detail, LibraryItemDetail):
            payload = detail.to_dict(
                include_raw_documents=include_raw_documents,
                include_document_data=False,
            )
            response_ok = detail.is_valid if ok is None else bool(ok)

            return {
                "ok": response_ok,
                "status": "ok" if response_ok else detail.status,
                "item": payload,
                "taxonomy": payload.get("taxonomy"),
            }

        if isinstance(detail, Mapping):
            response_ok = bool(ok) if ok is not None else True
            item_payload = json_safe(detail)
            taxonomy_payload = item_payload.get("taxonomy") if isinstance(item_payload, Mapping) else None

            return {
                "ok": response_ok,
                "status": "ok" if response_ok else "error",
                "item": item_payload,
                "taxonomy": taxonomy_payload,
            }

        return {
            "ok": False,
            "status": "not_found",
            "item": None,
            "taxonomy": None,
            "errors": ["library item detail is empty"],
        }

    except Exception as exc:
        return {
            "ok": False,
            "status": "error",
            "item": None,
            "taxonomy": None,
            "errors": [str(exc)],
            "error": exception_to_dict(exc),
        }


def build_not_found_detail_response(block_id: Any) -> dict[str, Any]:
    """Standardantwort, wenn ein Block per ID nicht gefunden wurde."""
    normalized_id = normalize_stable_id(block_id, fallback=safe_str(block_id, default="unknown"))

    return {
        "ok": False,
        "status": "not_found",
        "item": None,
        "block_id": normalized_id,
        "taxonomy": None,
        "errors": [
            f"library block not found: {normalized_id}",
        ],
    }


def build_error_detail_response(
    block_id: Any,
    exc: BaseException,
    *,
    include_traceback: bool = False,
) -> dict[str, Any]:
    """Standardantwort für unerwartete Detailfehler."""
    normalized_id = normalize_stable_id(block_id, fallback=safe_str(block_id, default="unknown"))

    return {
        "ok": False,
        "status": "error",
        "item": None,
        "block_id": normalized_id,
        "taxonomy": None,
        "errors": [
            f"could not load library block detail: {normalized_id}",
        ],
        "error": exception_to_dict(exc, include_traceback=include_traceback),
    }


# ---------------------------------------------------------------------------
# Health
# ---------------------------------------------------------------------------

def get_library_detail_model_health() -> dict[str, Any]:
    """
    Health-Status des Detail-Domainmodells.

    Führt keine Dateioperationen aus.
    """

    warnings: list[str] = []
    errors: list[str] = []

    if _LIBRARY_ITEM_IMPORT_ERROR is not None:
        warnings.append("library_item import failed; fallback item helpers are active")

    try:
        safe_int_self_test = safe_int("999999", default=500, minimum=1, maximum=5000)
        if safe_int_self_test != 5000:
            errors.append(f"safe_int maximum self-test failed: expected 5000, got {safe_int_self_test}")
    except Exception as exc:
        errors.append(f"safe_int maximum self-test failed: {exc}")

    try:
        docs = {
            "vplib.manifest.json": {
                "package_id": "vp.test.block",
                "family_id": "vp.test.block",
                "object_kind": "cell_block",
                "classification": {
                    "domain": "hochbau",
                    "category": "waende",
                    "subcategory": "aussenwaende",
                },
            },
            "family/identity.json": {
                "id": "vp.test.block",
                "label": "Test Block",
            },
            "family/classification.json": {
                "domain": "hochbau",
                "category": "waende",
                "subcategory": "aussenwaende",
                "taxonomy_version": "self-test",
                "labels": {
                    "domain": "Hochbau",
                    "category": "Wände",
                    "subcategory": "Außenwände",
                },
            },
            "variants/default.json": {
                "variant_id": "default",
            },
        }
        detail = LibraryItemDetail.from_documents(
            docs,
            validation={
                "valid": True,
                "warnings": [],
                "errors": [],
            },
            status="valid",
        )
        self_test_ok = (
            detail.id == "vp.test.block"
            and detail.variant_count == 1
            and detail.taxonomy.domain == "hochbau"
            and detail.taxonomy.category == "waende"
            and detail.taxonomy.subcategory == "aussenwaende"
        )
    except Exception as exc:
        self_test_ok = False
        errors.append(f"detail self-test failed: {exc}")

    healthy = len(errors) == 0

    return {
        "ok": healthy,
        "healthy": healthy,
        "component": LIBRARY_DETAIL_MODEL_COMPONENT,
        "version": LIBRARY_DETAIL_MODEL_VERSION,
        "generated_at": utc_now_iso(),
        "self_test": {
            "ok": self_test_ok,
        },
        "taxonomy": {
            "supported": True,
            "canonical_source_depth": CANONICAL_SOURCE_DEPTH,
            "legacy_source_depth": LEGACY_SOURCE_DEPTH,
            "taxonomy_document_key": TAXONOMY_DOCUMENT_KEY,
        },
        "imports": {
            "library_item": {
                "ok": _LIBRARY_ITEM_IMPORT_ERROR is None,
                "error": exception_to_dict(_LIBRARY_ITEM_IMPORT_ERROR),
            },
        },
        "warnings": warnings,
        "errors": errors,
    }


def assert_library_detail_model_ready() -> None:
    """Wirft RuntimeError, wenn das Detailmodell nicht bereit ist."""
    health = get_library_detail_model_health()

    if health.get("healthy"):
        return

    raise RuntimeError(
        f"library detail model is not ready: errors={health.get('errors')}"
    )


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

__all__: Final[tuple[str, ...]] = (
    "LIBRARY_DETAIL_MODEL_VERSION",
    "LIBRARY_DETAIL_MODEL_COMPONENT",
    "MANIFEST_DOCUMENT_KEY",
    "MODULES_DOCUMENT_KEY",
    "FAMILY_PREFIX",
    "VARIANTS_PREFIX",
    "EDITOR_PREFIX",
    "RENDER_PREFIX",
    "PHYSICAL_PREFIX",
    "MATERIAL_PREFIX",
    "CALCULATION_PREFIX",
    "MANUFACTURER_PREFIX",
    "ANALYSIS_PREFIX",
    "DYNAMIC_PREFIX",
    "DOCS_PREFIX",
    "TESTS_PREFIX",
    "ASSETS_PREFIX",
    "KNOWN_DOCUMENT_GROUPS",
    "DETAIL_PROFILE_GROUPS",
    "DEFAULT_DETAIL_STATUS",
    "DEFAULT_VARIANT_ID_FALLBACK",
    "UNKNOWN_LIBRARY_ITEM_ID",
    "UNKNOWN_TAXONOMY_VALUE",
    "CANONICAL_SOURCE_DEPTH",
    "LEGACY_SOURCE_DEPTH",
    "TAXONOMY_DOCUMENT_KEY",
    "LibraryDocumentEntry",
    "LibraryTaxonomyDetail",
    "LibraryVariantDetail",
    "LibraryModuleDetail",
    "LibrarySourceDetail",
    "LibraryItemDetail",
    "utc_now_iso",
    "exception_to_dict",
    "json_safe",
    "document_group_for_key",
    "document_name_for_key",
    "normalize_document_key",
    "normalize_documents",
    "get_document",
    "get_document_dict",
    "group_documents",
    "extract_nested_document_group",
    "make_validation_summary",
    "item_to_summary_dict",
    "get_item_attr",
    "extract_package_id_from_documents",
    "extract_family_id_from_documents",
    "extract_taxonomy_from_documents",
    "build_classification_payload",
    "extract_variants_from_documents",
    "extract_modules_from_documents",
    "build_document_entries",
    "build_profile_groups",
    "build_family_payload",
    "build_package_payload",
    "build_detail_response",
    "build_not_found_detail_response",
    "build_error_detail_response",
    "get_library_detail_model_health",
    "assert_library_detail_model_ready",
)