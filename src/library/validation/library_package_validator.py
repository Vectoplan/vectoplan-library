# services/vectoplan-library/src/library/validation/library_package_validator.py
"""
Library Package Validator für die VECTOPLAN Creative-Library-Schicht.

Diese Datei validiert gelesene VPLIB-Pakete für die Verwendung als
Creative-Library-Block oder Creative-Library-Objekt.

Wichtige Trennung:

- `src/vplib/validators`
  Technische VPLIB-Validierung:
  Schema, Semantik, Assets, Package-Konsistenz.

- `src/library/validation`
  Fachliche Creative-Library-Validierung:
  stabile IDs, Katalogtauglichkeit, Varianten-Nutzbarkeit, sichtbare
  Read-Model-Daten, spätere DB-Upsert-Fähigkeit.

Diese Datei:

- schreibt nichts ins Dateisystem
- erzeugt keine Datenbankeinträge
- kopiert keine Pakete
- führt keine Route-Logik aus
- kann mit oder ohne vorhandene VPLIB-Validatoren arbeiten
- behandelt fehlende VPLIB-Validatoren standardmäßig als Warnung, nicht als
  Fatal Error

Ziel für Phase 1:

    source package -> reader -> library validator -> block list/detail route

Ein Paket soll erst als Creative-Library-Item erscheinen, wenn diese Datei es
als gültig bewertet.

Version 0.1.3:

- Fallback-`safe_int` unterstützt `maximum`.
- VPLIB-Core-Validator ist optional und nicht-strikt standardmäßig nicht fatal.
- Externe VPLIB-Validator-Signaturen werden defensiv adaptiert.
- Mapping-, Dataclass- und Objekt-Ergebnisse werden robuster normalisiert.
- Health erzeugt keine falschen harten Fehler bei optionalen VPLIB-Fallbacks.
- Dict-/Mapping-Optionen werden vor Attributzugriffen normalisiert.
"""

from __future__ import annotations

import inspect
import re
import traceback
from collections.abc import Callable, Iterable, Mapping
from dataclasses import asdict, dataclass, field, is_dataclass
from datetime import datetime, timezone
from enum import Enum
from pathlib import Path
from typing import Any, Final


# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

LIBRARY_PACKAGE_VALIDATOR_VERSION: Final[str] = "0.1.3"
LIBRARY_PACKAGE_VALIDATOR_COMPONENT: Final[str] = "library-package-validator"

DEFAULT_VALIDATION_MODE: Final[str] = "library_read"
DEFAULT_VALIDATION_STATUS: Final[str] = "unknown"

DEFAULT_OBJECT_KIND_FALLBACK: Final[str] = "unknown"
DEFAULT_VARIANT_ID_FALLBACK: Final[str] = "default"

STABLE_LIBRARY_ID_PATTERN: Final[re.Pattern[str]] = re.compile(
    r"^[a-z0-9][a-z0-9._:-]*[a-z0-9]$|^[a-z0-9]$"
)

RECOMMENDED_ID_PREFIXES: Final[tuple[str, ...]] = (
    "vp.",
    "vplib.",
    "vectoplan.",
)

VALID_ISSUE_LEVELS: Final[tuple[str, ...]] = (
    "debug",
    "info",
    "warning",
    "error",
    "fatal",
)

VALID_VALIDATION_STATUSES: Final[tuple[str, ...]] = (
    "unknown",
    "valid",
    "invalid",
    "partial",
    "error",
)

MIN_REQUIRED_DOCUMENT_KEYS: Final[tuple[str, ...]] = (
    "vplib.manifest.json",
    "vplib.modules.json",
    "family/identity.json",
    "variants/index.json",
    "variants/default.json",
)

RECOMMENDED_DOCUMENT_KEYS: Final[tuple[str, ...]] = (
    "family/classification.json",
    "editor/inventory.json",
    "editor/placement.json",
    "manufacturer/contract.json",
)

TECHNICAL_OBJECT_REQUIRED_DOCUMENTS: Final[tuple[str, ...]] = (
    "physical/base.json",
)

VISIBLE_LIBRARY_RECOMMENDED_DOCUMENTS: Final[tuple[str, ...]] = (
    "editor/inventory.json",
    "render/render_variants.json",
)

TECHNICAL_OBJECT_KINDS: Final[tuple[str, ...]] = (
    "cell_block",
    "multi_cell_module",
    "adaptive_system",
)


# ---------------------------------------------------------------------------
# Generic fallback helpers used before optional imports
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
        text = _fallback_safe_str(value, default=DEFAULT_OBJECT_KIND_FALLBACK).lower()

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

        if normalized in {
            "cell_block",
            "multi_cell_module",
            "catalog_object",
            "adaptive_system",
        }:
            return normalized

        return DEFAULT_OBJECT_KIND_FALLBACK

    except Exception:
        return DEFAULT_OBJECT_KIND_FALLBACK


def _fallback_humanize_identifier(value: Any, *, fallback: str = "Unnamed Library Item") -> str:
    try:
        text = _fallback_safe_str(value, default="")

        if not text:
            return fallback

        last = re.split(r"[.:/\\]", text)[-1]
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

        return str(value)

    except Exception as exc:
        return {
            "serialization_error": exception_to_dict(exc),
            "fallback_type": str(type(value)),
        }


# ---------------------------------------------------------------------------
# Optional imports
# ---------------------------------------------------------------------------

_DETAIL_IMPORT_ERROR: BaseException | None = None
_ITEM_IMPORT_ERROR: BaseException | None = None
_READER_IMPORT_ERROR: BaseException | None = None
_VPLIB_VALIDATORS_IMPORT_ERROR: BaseException | None = None

try:
    from library.domain.library_detail import (
        MANIFEST_DOCUMENT_KEY,
        MODULES_DOCUMENT_KEY,
        extract_family_id_from_documents,
        extract_modules_from_documents,
        extract_package_id_from_documents,
        extract_variants_from_documents,
        get_document_dict,
        normalize_documents,
    )
except Exception as import_exc:  # pragma: no cover - defensive fallback
    _DETAIL_IMPORT_ERROR = import_exc

    MANIFEST_DOCUMENT_KEY = "vplib.manifest.json"
    MODULES_DOCUMENT_KEY = "vplib.modules.json"

    def normalize_documents(documents: Mapping[str, Any] | None) -> dict[str, Any]:
        if not isinstance(documents, Mapping):
            return {}

        result: dict[str, Any] = {}

        for key, value in documents.items():
            normalized_key = str(key).replace("\\", "/").strip("/")
            if normalized_key:
                result[normalized_key] = value

        return result

    def get_document_dict(
        documents: Mapping[str, Any] | None,
        key: str,
    ) -> dict[str, Any]:
        doc = normalize_documents(documents).get(normalize_document_key(key))
        return dict(doc) if isinstance(doc, Mapping) else {}

    def extract_package_id_from_documents(documents: Mapping[str, Any] | None) -> str | None:
        manifest = get_document_dict(documents, MANIFEST_DOCUMENT_KEY)
        value = manifest.get("package_id") or manifest.get("id")
        return safe_str(value, default="") or None

    def extract_family_id_from_documents(documents: Mapping[str, Any] | None) -> str | None:
        docs = normalize_documents(documents)
        manifest = get_document_dict(docs, MANIFEST_DOCUMENT_KEY)
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
        variants: list[Any] = []

        variants_index = get_document_dict(docs, "variants/index.json")
        raw_variants = variants_index.get("variants") or variants_index.get("variant_ids") or []

        if isinstance(raw_variants, Mapping):
            for key, value in raw_variants.items():
                payload = dict(value) if isinstance(value, Mapping) else {}
                payload.setdefault("variant_id", key)
                variants.append(payload)

        elif isinstance(raw_variants, Iterable) and not isinstance(raw_variants, (str, bytes)):
            for value in raw_variants:
                if isinstance(value, Mapping):
                    variants.append(dict(value))
                else:
                    variants.append({"variant_id": value})

        if not variants and "variants/default.json" in docs:
            variants.append({"variant_id": DEFAULT_VARIANT_ID, "is_default": True})

        return variants

    def extract_modules_from_documents(documents: Mapping[str, Any] | None) -> list[Any]:
        docs = normalize_documents(documents)
        modules_doc = get_document_dict(docs, MODULES_DOCUMENT_KEY)
        raw_modules = (
            modules_doc.get("active_modules")
            or modules_doc.get("modules")
            or modules_doc.get("enabled_modules")
            or []
        )
        modules: list[Any] = []

        if isinstance(raw_modules, Mapping):
            for module_name, data in raw_modules.items():
                payload = dict(data) if isinstance(data, Mapping) else {}
                payload.setdefault("module_name", module_name)
                payload.setdefault("active", True)
                modules.append(payload)

        elif isinstance(raw_modules, Iterable) and not isinstance(raw_modules, (str, bytes)):
            for module_name in raw_modules:
                modules.append(
                    {
                        "module_name": safe_str(module_name, default="unknown"),
                        "active": True,
                    }
                )

        return modules


try:
    from library.domain.library_item import (
        DEFAULT_OBJECT_KIND,
        DEFAULT_VARIANT_ID,
        VALID_OBJECT_KINDS,
        LibraryItem,
        LibraryItemStatus,
        LibraryItemValidationSummary,
        deep_get,
        ensure_dict,
        ensure_list_of_strings,
        first_non_empty,
        humanize_identifier,
        normalize_object_kind,
        normalize_stable_id,
        normalize_variant_id,
        safe_bool,
        safe_int,
        safe_path_str,
        safe_str,
    )
except Exception as import_exc:  # pragma: no cover - defensive fallback
    _ITEM_IMPORT_ERROR = import_exc

    DEFAULT_OBJECT_KIND = DEFAULT_OBJECT_KIND_FALLBACK
    DEFAULT_VARIANT_ID = DEFAULT_VARIANT_ID_FALLBACK
    VALID_OBJECT_KINDS = (
        "cell_block",
        "multi_cell_module",
        "catalog_object",
        "adaptive_system",
    )

    class LibraryItemStatus:  # type: ignore[no-redef]
        VALID = type("StatusValue", (), {"value": "valid"})()
        INVALID = type("StatusValue", (), {"value": "invalid"})()
        ERROR = type("StatusValue", (), {"value": "error"})()

    LibraryItem = None  # type: ignore[assignment]

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


try:
    from library.scanner.package_reader import (
        PackageReadResult,
        read_result_to_document_mapping,
    )
except Exception as import_exc:  # pragma: no cover - defensive fallback
    _READER_IMPORT_ERROR = import_exc

    PackageReadResult = Any  # type: ignore[assignment]

    def read_result_to_document_mapping(result: Any) -> dict[str, Any]:
        if isinstance(result, Mapping):
            return normalize_documents(result.get("documents"))

        return normalize_documents(getattr(result, "documents", None))


try:
    import vplib.validators.package_validator as vplib_package_validator
except Exception as import_exc:  # pragma: no cover - defensive fallback
    _VPLIB_VALIDATORS_IMPORT_ERROR = import_exc
    vplib_package_validator = None  # type: ignore[assignment]


# ---------------------------------------------------------------------------
# Enums
# ---------------------------------------------------------------------------

class LibraryValidationIssueLevel(str, Enum):
    DEBUG = "debug"
    INFO = "info"
    WARNING = "warning"
    ERROR = "error"
    FATAL = "fatal"


class LibraryPackageValidationStatus(str, Enum):
    UNKNOWN = "unknown"
    VALID = "valid"
    INVALID = "invalid"
    PARTIAL = "partial"
    ERROR = "error"


# ---------------------------------------------------------------------------
# Generic helpers after imports
# ---------------------------------------------------------------------------

def tuple_of_strings(value: Any) -> tuple[str, ...]:
    """
    Normalisiert Werte zu tuple[str, ...].
    """

    return tuple(ensure_list_of_strings(value))


def get_attr_or_key(value: Any, key: str, *, default: Any = None) -> Any:
    """
    Liest Mapping-Key oder Attribut.
    """

    try:
        if value is None:
            return default

        if isinstance(value, Mapping):
            return value.get(key, default)

        return getattr(value, key, default)

    except Exception:
        return default


def normalize_issue_level(value: Any) -> str:
    """
    Normalisiert Issue-Level.
    """

    text = safe_str(value, default="info").lower()

    if text in VALID_ISSUE_LEVELS:
        return text

    return "info"


def normalize_validation_status(value: Any) -> str:
    """
    Normalisiert Validierungsstatus.
    """

    text = safe_str(value, default=DEFAULT_VALIDATION_STATUS).lower()

    if text in VALID_VALIDATION_STATUSES:
        return text

    return DEFAULT_VALIDATION_STATUS


def normalize_document_key(document_key: Any) -> str:
    """
    Normalisiert Dokumentkeys.
    """

    text = safe_str(document_key, default="")
    text = text.replace("\\", "/").strip("/")

    while "//" in text:
        text = text.replace("//", "/")

    return text


def has_document(documents: Mapping[str, Any], key: str) -> bool:
    """
    Prüft Dokumentpräsenz.
    """

    return normalize_document_key(key) in normalize_documents(documents)


def get_document(documents: Mapping[str, Any], key: str) -> Any:
    """
    Liest Dokument defensiv.
    """

    return normalize_documents(documents).get(normalize_document_key(key))


def variant_id_from_any(value: Any) -> str | None:
    """
    Extrahiert eine Varianten-ID aus Variantenmodell, Mapping oder String.
    """

    try:
        if value is None:
            return None

        if isinstance(value, str):
            normalized = normalize_variant_id(value)
            return normalized or None

        if isinstance(value, Mapping):
            candidate = (
                value.get("variant_id")
                or value.get("id")
                or value.get("slug")
            )
            normalized = normalize_variant_id(candidate)
            return normalized or None

        candidate = (
            getattr(value, "variant_id", None)
            or getattr(value, "id", None)
            or getattr(value, "slug", None)
        )
        normalized = normalize_variant_id(candidate)
        return normalized or None

    except Exception:
        return None


def extract_variant_ids_from_documents(documents: Mapping[str, Any]) -> list[str]:
    """
    Extrahiert Varianten-IDs aus Dokumenten.
    """

    result: list[str] = []

    try:
        variants = extract_variants_from_documents(documents)

        for variant in variants:
            variant_id = variant_id_from_any(variant)

            if variant_id and variant_id not in result:
                result.append(variant_id)

    except Exception:
        pass

    variants_index = get_document_dict(documents, "variants/index.json")
    raw_variants = first_non_empty(
        deep_get(variants_index, "variants"),
        deep_get(variants_index, "variant_ids"),
        default=[],
    )

    try:
        if isinstance(raw_variants, Mapping):
            for key, item in raw_variants.items():
                variant_id = variant_id_from_any(item) or normalize_variant_id(key)
                if variant_id and variant_id not in result:
                    result.append(variant_id)

        elif isinstance(raw_variants, Iterable) and not isinstance(raw_variants, (str, bytes)):
            for item in raw_variants:
                variant_id = variant_id_from_any(item)
                if variant_id and variant_id not in result:
                    result.append(variant_id)

        elif raw_variants:
            variant_id = variant_id_from_any(raw_variants)
            if variant_id and variant_id not in result:
                result.append(variant_id)

    except Exception:
        pass

    if not result and has_document(documents, "variants/default.json"):
        result.append(DEFAULT_VARIANT_ID)

    return result


def extract_default_variant_id_from_documents(documents: Mapping[str, Any]) -> str:
    """
    Extrahiert die Default-Variante.
    """

    variants_index = get_document_dict(documents, "variants/index.json")
    default_variant = get_document_dict(documents, "variants/default.json")

    value = first_non_empty(
        deep_get(variants_index, "default_variant_id"),
        deep_get(variants_index, "default"),
        deep_get(default_variant, "variant_id"),
        deep_get(default_variant, "id"),
        DEFAULT_VARIANT_ID,
    )

    return normalize_variant_id(value)


def extract_classification_from_documents(documents: Mapping[str, Any]) -> dict[str, Any]:
    """
    Extrahiert Domain/Kategorie/Subkategorie aus Manifest oder Classification.
    """

    manifest = get_document_dict(documents, MANIFEST_DOCUMENT_KEY)
    classification = get_document_dict(documents, "family/classification.json")

    domain = first_non_empty(
        deep_get(manifest, "classification.domain"),
        deep_get(classification, "domain"),
        deep_get(classification, "classification.domain"),
    )
    category = first_non_empty(
        deep_get(manifest, "classification.category"),
        deep_get(classification, "category"),
        deep_get(classification, "classification.category"),
    )
    subcategory = first_non_empty(
        deep_get(manifest, "classification.subcategory"),
        deep_get(classification, "subcategory"),
        deep_get(classification, "classification.subcategory"),
    )

    return {
        "domain": safe_str(domain, default="") or None,
        "category": safe_str(category, default="") or None,
        "subcategory": safe_str(subcategory, default="") or None,
    }


def extract_object_kind_from_documents(documents: Mapping[str, Any]) -> str:
    """
    Extrahiert object_kind.
    """

    manifest = get_document_dict(documents, MANIFEST_DOCUMENT_KEY)
    identity = get_document_dict(documents, "family/identity.json")
    classification = get_document_dict(documents, "family/classification.json")
    physical_base = get_document_dict(documents, "physical/base.json")

    value = first_non_empty(
        deep_get(manifest, "object_kind"),
        deep_get(identity, "object_kind"),
        deep_get(classification, "object_kind"),
        deep_get(physical_base, "object_kind"),
    )

    return normalize_object_kind(value)


def extract_label_from_documents(documents: Mapping[str, Any]) -> str | None:
    """
    Extrahiert ein sichtbares Label.
    """

    manifest = get_document_dict(documents, MANIFEST_DOCUMENT_KEY)
    identity = get_document_dict(documents, "family/identity.json")
    inventory = get_document_dict(documents, "editor/inventory.json")

    value = first_non_empty(
        deep_get(identity, "label"),
        deep_get(identity, "name"),
        deep_get(identity, "family_name"),
        deep_get(manifest, "family_name"),
        deep_get(inventory, "label"),
    )

    text = safe_str(value, default="")
    return text or None


def is_stable_library_id(value: Any) -> bool:
    """
    Prüft, ob eine ID für spätere DB-Upserts geeignet ist.
    """

    normalized = normalize_stable_id(value)

    if not normalized:
        return False

    return bool(STABLE_LIBRARY_ID_PATTERN.match(normalized))


def has_recommended_id_prefix(value: Any) -> bool:
    """
    Prüft optional empfohlene Prefixe.
    """

    normalized = normalize_stable_id(value)

    return any(normalized.startswith(prefix) for prefix in RECOMMENDED_ID_PREFIXES)


# ---------------------------------------------------------------------------
# Dataclasses
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class LibraryValidationIssue:
    """
    Einzelnes Validierungsproblem oder Hinweis.
    """

    level: str
    message: str
    code: str | None = None
    document_key: str | None = None
    field_path: str | None = None
    value: Any = None
    source: str = "library"
    data: dict[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        object.__setattr__(self, "level", normalize_issue_level(self.level))
        object.__setattr__(self, "message", safe_str(self.message, default=""))
        object.__setattr__(self, "code", safe_str(self.code, default="") or None)
        object.__setattr__(self, "document_key", normalize_document_key(self.document_key) if self.document_key else None)
        object.__setattr__(self, "field_path", safe_str(self.field_path, default="") or None)
        object.__setattr__(self, "source", safe_str(self.source, default="library"))
        object.__setattr__(self, "data", ensure_dict(self.data))

    @property
    def is_error(self) -> bool:
        return self.level in {"error", "fatal"}

    @property
    def is_warning(self) -> bool:
        return self.level == "warning"

    @property
    def is_fatal(self) -> bool:
        return self.level == "fatal"

    @classmethod
    def warning(
        cls,
        message: str,
        *,
        code: str | None = None,
        document_key: str | None = None,
        field_path: str | None = None,
        value: Any = None,
        source: str = "library",
        data: Mapping[str, Any] | None = None,
    ) -> "LibraryValidationIssue":
        return cls(
            level="warning",
            message=message,
            code=code,
            document_key=document_key,
            field_path=field_path,
            value=value,
            source=source,
            data=ensure_dict(data),
        )

    @classmethod
    def error(
        cls,
        message: str,
        *,
        code: str | None = None,
        document_key: str | None = None,
        field_path: str | None = None,
        value: Any = None,
        source: str = "library",
        data: Mapping[str, Any] | None = None,
    ) -> "LibraryValidationIssue":
        return cls(
            level="error",
            message=message,
            code=code,
            document_key=document_key,
            field_path=field_path,
            value=value,
            source=source,
            data=ensure_dict(data),
        )

    @classmethod
    def fatal(
        cls,
        message: str,
        *,
        code: str | None = None,
        document_key: str | None = None,
        field_path: str | None = None,
        value: Any = None,
        source: str = "library",
        data: Mapping[str, Any] | None = None,
    ) -> "LibraryValidationIssue":
        return cls(
            level="fatal",
            message=message,
            code=code,
            document_key=document_key,
            field_path=field_path,
            value=value,
            source=source,
            data=ensure_dict(data),
        )

    @classmethod
    def info(
        cls,
        message: str,
        *,
        code: str | None = None,
        source: str = "library",
        data: Mapping[str, Any] | None = None,
    ) -> "LibraryValidationIssue":
        return cls(
            level="info",
            message=message,
            code=code,
            source=source,
            data=ensure_dict(data),
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "level": self.level,
            "message": self.message,
            "code": self.code,
            "document_key": self.document_key,
            "field_path": self.field_path,
            "value": json_safe(self.value),
            "source": self.source,
            "data": json_safe(self.data),
        }


@dataclass(frozen=True)
class LibraryPackageValidatorOptions:
    """
    Optionen für die Library-Package-Validierung.
    """

    strict_vplib_validation: bool = False
    require_vplib_validator: bool = False
    require_recommended_documents: bool = False
    require_classification: bool = True
    # Kompatibilität mit älteren/externen Scan-Optionen.
    # Einige Aufrufer übergeben dicts mit require_taxonomy statt
    # require_classification. Beide Flags bleiben bewusst vorhanden.
    require_taxonomy: bool = True
    strict_taxonomy: bool = False
    allow_legacy_source_depth: bool = True
    validate_vplib_uid: bool = True
    publish_valid_only: bool = True
    include_warnings: bool = True
    require_visible_label: bool = True
    require_editor_inventory: bool = True
    require_editor_placement: bool = True
    require_manufacturer_contract: bool = True
    require_default_variant_in_index: bool = True
    require_stable_family_id: bool = True
    warn_on_missing_recommended_id_prefix: bool = True
    allow_unknown_object_kind: bool = False
    allow_empty_variants: bool = False
    validation_mode: str = DEFAULT_VALIDATION_MODE

    def __post_init__(self) -> None:
        object.__setattr__(self, "strict_vplib_validation", safe_bool(self.strict_vplib_validation, default=False))
        object.__setattr__(self, "require_vplib_validator", safe_bool(self.require_vplib_validator, default=False))
        object.__setattr__(self, "require_recommended_documents", safe_bool(self.require_recommended_documents, default=False))
        require_taxonomy = safe_bool(self.require_taxonomy, default=True)
        require_classification = safe_bool(self.require_classification, default=require_taxonomy)

        # Wenn ein Aufrufer explizit require_taxonomy=False setzt, soll die
        # ältere Library-Regel require_classification nicht versehentlich auf
        # ihrem Default True bleiben.
        if require_taxonomy is False and self.require_classification is True:
            require_classification = False

        object.__setattr__(self, "require_classification", require_classification)
        object.__setattr__(self, "require_taxonomy", require_taxonomy)
        object.__setattr__(self, "strict_taxonomy", safe_bool(self.strict_taxonomy, default=False))
        object.__setattr__(self, "allow_legacy_source_depth", safe_bool(self.allow_legacy_source_depth, default=True))
        object.__setattr__(self, "validate_vplib_uid", safe_bool(self.validate_vplib_uid, default=True))
        object.__setattr__(self, "publish_valid_only", safe_bool(self.publish_valid_only, default=True))
        object.__setattr__(self, "include_warnings", safe_bool(self.include_warnings, default=True))
        object.__setattr__(self, "require_visible_label", safe_bool(self.require_visible_label, default=True))
        object.__setattr__(self, "require_editor_inventory", safe_bool(self.require_editor_inventory, default=True))
        object.__setattr__(self, "require_editor_placement", safe_bool(self.require_editor_placement, default=True))
        object.__setattr__(self, "require_manufacturer_contract", safe_bool(self.require_manufacturer_contract, default=True))
        object.__setattr__(self, "require_default_variant_in_index", safe_bool(self.require_default_variant_in_index, default=True))
        object.__setattr__(self, "require_stable_family_id", safe_bool(self.require_stable_family_id, default=True))
        object.__setattr__(self, "warn_on_missing_recommended_id_prefix", safe_bool(self.warn_on_missing_recommended_id_prefix, default=True))
        object.__setattr__(self, "allow_unknown_object_kind", safe_bool(self.allow_unknown_object_kind, default=False))
        object.__setattr__(self, "allow_empty_variants", safe_bool(self.allow_empty_variants, default=False))
        object.__setattr__(self, "validation_mode", safe_str(self.validation_mode, default=DEFAULT_VALIDATION_MODE))

    def to_dict(self) -> dict[str, Any]:
        return {
            "strict_vplib_validation": self.strict_vplib_validation,
            "require_vplib_validator": self.require_vplib_validator,
            "require_recommended_documents": self.require_recommended_documents,
            "require_classification": self.require_classification,
            "require_taxonomy": self.require_taxonomy,
            "strict_taxonomy": self.strict_taxonomy,
            "allow_legacy_source_depth": self.allow_legacy_source_depth,
            "validate_vplib_uid": self.validate_vplib_uid,
            "publish_valid_only": self.publish_valid_only,
            "include_warnings": self.include_warnings,
            "require_visible_label": self.require_visible_label,
            "require_editor_inventory": self.require_editor_inventory,
            "require_editor_placement": self.require_editor_placement,
            "require_manufacturer_contract": self.require_manufacturer_contract,
            "require_default_variant_in_index": self.require_default_variant_in_index,
            "require_stable_family_id": self.require_stable_family_id,
            "warn_on_missing_recommended_id_prefix": self.warn_on_missing_recommended_id_prefix,
            "allow_unknown_object_kind": self.allow_unknown_object_kind,
            "allow_empty_variants": self.allow_empty_variants,
            "validation_mode": self.validation_mode,
        }


def coerce_validator_options(
    options: LibraryPackageValidatorOptions | Mapping[str, Any] | Any | None = None,
    **overrides: Any,
) -> LibraryPackageValidatorOptions:
    """
    Normalisiert Validator-Optionen auf LibraryPackageValidatorOptions.

    Hintergrund:
    Der Scan-/Route-Pfad übergibt teilweise normale dicts, während dieser
    Validator intern Attributzugriff nutzt, z. B. options.require_classification
    oder kompatibel options.require_taxonomy. Ohne Normalisierung entsteht der
    Fehler:

        AttributeError: 'dict' object has no attribute 'require_taxonomy'

    Diese Funktion akzeptiert:
    - LibraryPackageValidatorOptions
    - Mapping/dict
    - Dataclass
    - Objekt mit to_dict()
    - beliebiges Objekt mit Attributen
    """

    if isinstance(options, LibraryPackageValidatorOptions):
        data = options.to_dict()
    elif options is None:
        data = {}
    elif is_dataclass(options):
        data = dict(asdict(options))
    elif isinstance(options, Mapping):
        data = dict(options)
    else:
        to_dict = getattr(options, "to_dict", None)
        if callable(to_dict):
            try:
                raw = to_dict()
            except TypeError:
                raw = to_dict(flat=True)
            data = dict(raw) if isinstance(raw, Mapping) else {}
        else:
            data = {}
            for name in dir(options):
                if name.startswith("_"):
                    continue
                try:
                    value = getattr(options, name)
                except Exception:
                    continue
                if callable(value):
                    continue
                data[name] = value

    for key, value in overrides.items():
        if value is not None:
            data[key] = value

    # Legacy-/Route-Kompatibilität: require_taxonomy bedeutet in dieser Datei
    # fachlich require_classification.
    if "require_taxonomy" in data and "require_classification" not in data:
        data["require_classification"] = data.get("require_taxonomy")

    # Umgekehrt bleibt require_taxonomy für Health/Debug-Payloads sichtbar.
    if "require_classification" in data and "require_taxonomy" not in data:
        data["require_taxonomy"] = data.get("require_classification")

    valid_keys = set(getattr(LibraryPackageValidatorOptions, "__dataclass_fields__", {}).keys())
    filtered = {key: value for key, value in data.items() if key in valid_keys}

    return LibraryPackageValidatorOptions(**filtered)


@dataclass(frozen=True)
class VplibValidationAdapterResult:
    """
    Normalisiertes Ergebnis der optionalen VPLIB-Kernvalidierung.
    """

    attempted: bool
    available: bool
    ok: bool
    valid: bool
    callable_name: str | None = None
    raw_result: Any = None
    warnings: tuple[str, ...] = field(default_factory=tuple)
    errors: tuple[str, ...] = field(default_factory=tuple)
    issues: tuple[LibraryValidationIssue, ...] = field(default_factory=tuple)

    def __post_init__(self) -> None:
        object.__setattr__(self, "attempted", safe_bool(self.attempted, default=False))
        object.__setattr__(self, "available", safe_bool(self.available, default=False))
        object.__setattr__(self, "ok", safe_bool(self.ok, default=False))
        object.__setattr__(self, "valid", safe_bool(self.valid, default=False))
        object.__setattr__(self, "callable_name", safe_str(self.callable_name, default="") or None)
        object.__setattr__(self, "warnings", tuple_of_strings(self.warnings))
        object.__setattr__(self, "errors", tuple_of_strings(self.errors))
        object.__setattr__(self, "issues", tuple(normalize_issues(self.issues)))

    def to_dict(self, *, include_raw_result: bool = False) -> dict[str, Any]:
        result: dict[str, Any] = {
            "attempted": self.attempted,
            "available": self.available,
            "ok": self.ok,
            "valid": self.valid,
            "callable_name": self.callable_name,
            "warnings": list(self.warnings),
            "errors": list(self.errors),
            "issues": [
                issue.to_dict()
                for issue in self.issues
            ],
        }

        if include_raw_result:
            result["raw_result"] = json_safe(self.raw_result)

        return result


@dataclass(frozen=True)
class LibraryPackageValidationResult:
    """
    Gesamtergebnis einer Library-Package-Validierung.
    """

    ok: bool
    valid: bool
    status: str

    package_id: str | None = None
    family_id: str | None = None
    item_id: str | None = None
    label: str | None = None
    object_kind: str | None = None

    document_count: int = 0
    missing_required_documents: tuple[str, ...] = field(default_factory=tuple)
    missing_recommended_documents: tuple[str, ...] = field(default_factory=tuple)

    variant_ids: tuple[str, ...] = field(default_factory=tuple)
    default_variant_id: str | None = None

    issues: tuple[LibraryValidationIssue, ...] = field(default_factory=tuple)
    vplib_validation: VplibValidationAdapterResult | None = None

    validated_at: str = field(default_factory=utc_now_iso)
    validation_mode: str = DEFAULT_VALIDATION_MODE
    options: LibraryPackageValidatorOptions = field(default_factory=LibraryPackageValidatorOptions)
    metadata: dict[str, Any] = field(default_factory=dict)
    version: str = LIBRARY_PACKAGE_VALIDATOR_VERSION

    def __post_init__(self) -> None:
        if not isinstance(self.options, LibraryPackageValidatorOptions):
            object.__setattr__(self, "options", LibraryPackageValidatorOptions())

        issues = tuple(normalize_issues(self.issues))
        missing_required = tuple_of_strings(self.missing_required_documents)
        missing_recommended = tuple_of_strings(self.missing_recommended_documents)
        variant_ids = tuple_of_strings(self.variant_ids)

        error_count = sum(1 for issue in issues if issue.level == "error")
        fatal_count = sum(1 for issue in issues if issue.level == "fatal")

        status = normalize_validation_status(self.status)

        if status == "unknown":
            if fatal_count > 0 or error_count > 0:
                status = "invalid"
            elif self.valid:
                status = "valid"
            else:
                status = "partial"

        effective_valid = bool(self.valid and fatal_count == 0 and error_count == 0)
        effective_ok = bool(self.ok and status in {"valid", "partial"} and fatal_count == 0)

        if status == "valid" and not effective_valid:
            status = "invalid"

        object.__setattr__(self, "ok", effective_ok)
        object.__setattr__(self, "valid", effective_valid)
        object.__setattr__(self, "status", status)
        object.__setattr__(self, "package_id", safe_str(self.package_id, default="") or None)
        object.__setattr__(self, "family_id", normalize_stable_id(self.family_id) or None)
        object.__setattr__(self, "item_id", normalize_stable_id(self.item_id, fallback=self.family_id) or None)
        object.__setattr__(self, "label", safe_str(self.label, default="") or None)
        object.__setattr__(self, "object_kind", normalize_object_kind(self.object_kind))
        object.__setattr__(self, "document_count", safe_int(self.document_count, default=0, minimum=0))
        object.__setattr__(self, "missing_required_documents", missing_required)
        object.__setattr__(self, "missing_recommended_documents", missing_recommended)
        object.__setattr__(self, "variant_ids", variant_ids)
        object.__setattr__(self, "default_variant_id", normalize_variant_id(self.default_variant_id) if self.default_variant_id else None)
        object.__setattr__(self, "issues", issues)
        object.__setattr__(self, "validated_at", safe_str(self.validated_at, default=utc_now_iso()))
        object.__setattr__(self, "validation_mode", safe_str(self.validation_mode, default=DEFAULT_VALIDATION_MODE))
        object.__setattr__(self, "metadata", ensure_dict(self.metadata))
        object.__setattr__(self, "version", safe_str(self.version, default=LIBRARY_PACKAGE_VALIDATOR_VERSION))

    @property
    def warning_count(self) -> int:
        return sum(1 for issue in self.issues if issue.level == "warning")

    @property
    def error_count(self) -> int:
        return sum(1 for issue in self.issues if issue.level == "error")

    @property
    def fatal_count(self) -> int:
        return sum(1 for issue in self.issues if issue.level == "fatal")

    @property
    def info_count(self) -> int:
        return sum(1 for issue in self.issues if issue.level == "info")

    @property
    def warnings(self) -> tuple[str, ...]:
        return tuple(issue.message for issue in self.issues if issue.level == "warning")

    @property
    def errors(self) -> tuple[str, ...]:
        return tuple(issue.message for issue in self.issues if issue.level in {"error", "fatal"})

    def to_summary(self) -> LibraryItemValidationSummary:
        """
        Wandelt Ergebnis in kompakte LibraryItemValidationSummary.
        """

        return LibraryItemValidationSummary(
            valid=self.valid,
            warning_count=self.warning_count,
            error_count=self.error_count,
            fatal_count=self.fatal_count,
            warnings=self.warnings,
            errors=self.errors,
        )

    def to_dict(self, *, include_vplib_raw_result: bool = False) -> dict[str, Any]:
        return {
            "ok": self.ok,
            "valid": self.valid,
            "status": self.status,
            "package_id": self.package_id,
            "family_id": self.family_id,
            "item_id": self.item_id,
            "label": self.label,
            "object_kind": self.object_kind,
            "document_count": self.document_count,
            "missing_required_documents": list(self.missing_required_documents),
            "missing_recommended_documents": list(self.missing_recommended_documents),
            "variant_ids": list(self.variant_ids),
            "default_variant_id": self.default_variant_id,
            "warning_count": self.warning_count,
            "error_count": self.error_count,
            "fatal_count": self.fatal_count,
            "info_count": self.info_count,
            "warnings": list(self.warnings),
            "errors": list(self.errors),
            "issues": [
                issue.to_dict()
                for issue in self.issues
            ],
            "vplib_validation": (
                self.vplib_validation.to_dict(include_raw_result=include_vplib_raw_result)
                if self.vplib_validation
                else None
            ),
            "validated_at": self.validated_at,
            "validation_mode": self.validation_mode,
            "options": self.options.to_dict(),
            "metadata": json_safe(self.metadata),
            "version": self.version,
        }

    @classmethod
    def error(
        cls,
        exc: BaseException,
        *,
        package_id: Any = None,
        family_id: Any = None,
        options: LibraryPackageValidatorOptions | None = None,
        include_traceback: bool = False,
    ) -> "LibraryPackageValidationResult":
        error_data = exception_to_dict(exc, include_traceback=include_traceback)
        message = safe_str(error_data.get("message") if error_data else None, default="library package validation failed")

        return cls(
            ok=False,
            valid=False,
            status="error",
            package_id=safe_str(package_id, default="") or None,
            family_id=normalize_stable_id(family_id) or None,
            item_id=normalize_stable_id(family_id) or None,
            issues=(
                LibraryValidationIssue.fatal(
                    message,
                    code=safe_str(error_data.get("type") if error_data else None, default="Exception"),
                    source="library",
                    data={"exception": error_data},
                ),
            ),
            options=coerce_validator_options(options),
            metadata={"exception": error_data},
        )


# ---------------------------------------------------------------------------
# Issue normalization
# ---------------------------------------------------------------------------

def normalize_issues(value: Any) -> list[LibraryValidationIssue]:
    """
    Normalisiert beliebige Issue-Formen.
    """

    if value is None:
        return []

    if isinstance(value, LibraryValidationIssue):
        return [value]

    if isinstance(value, str):
        text = value.strip()
        return [LibraryValidationIssue.error(text)] if text else []

    if isinstance(value, Mapping):
        return [
            LibraryValidationIssue(
                level=value.get("level") or value.get("severity") or "error",
                message=value.get("message") or value.get("msg") or str(value),
                code=value.get("code"),
                document_key=value.get("document_key") or value.get("path"),
                field_path=value.get("field_path") or value.get("field"),
                value=value.get("value"),
                source=value.get("source") or "unknown",
                data=ensure_dict(value.get("data") or value.get("details")),
            )
        ]

    if hasattr(value, "message") or hasattr(value, "severity") or hasattr(value, "code"):
        return [
            LibraryValidationIssue(
                level=get_attr_or_key(value, "level") or get_attr_or_key(value, "severity") or "error",
                message=get_attr_or_key(value, "message") or str(value),
                code=get_attr_or_key(value, "code"),
                document_key=get_attr_or_key(value, "document_key") or get_attr_or_key(value, "path"),
                field_path=get_attr_or_key(value, "field_path") or get_attr_or_key(value, "field"),
                value=get_attr_or_key(value, "value"),
                source=get_attr_or_key(value, "source") or "unknown",
                data=ensure_dict(get_attr_or_key(value, "data") or get_attr_or_key(value, "details")),
            )
        ]

    if isinstance(value, Iterable):
        result: list[LibraryValidationIssue] = []

        for item in value:
            try:
                result.extend(normalize_issues(item))
            except Exception:
                continue

        return result

    return [
        LibraryValidationIssue.error(str(value))
    ]


def issue_from_exception(
    exc: BaseException,
    *,
    code: str | None = None,
    source: str = "library",
    include_traceback: bool = False,
) -> LibraryValidationIssue:
    """
    Baut ein Issue aus einer Exception.
    """

    return LibraryValidationIssue.error(
        safe_str(exc, default=exc.__class__.__name__),
        code=code or exc.__class__.__name__,
        source=source,
        data={
            "exception": exception_to_dict(exc, include_traceback=include_traceback),
        },
    )


def demote_vplib_issues_for_non_strict_mode(
    issues: Iterable[LibraryValidationIssue],
) -> tuple[LibraryValidationIssue, ...]:
    """
    Wandelt VPLIB-Error/Fatal-Issues in Warnings um, wenn der VPLIB-Validator
    nicht strikt verwendet wird.

    Library-eigene Regeln bleiben davon unberührt.
    """

    result: list[LibraryValidationIssue] = []

    for issue in issues:
        if issue.source == "vplib" and issue.level in {"error", "fatal"}:
            result.append(
                LibraryValidationIssue.warning(
                    issue.message,
                    code=issue.code or "vplib_non_strict_issue",
                    document_key=issue.document_key,
                    field_path=issue.field_path,
                    value=issue.value,
                    source=issue.source,
                    data={
                        **issue.data,
                        "original_level": issue.level,
                        "demoted_by": "non_strict_vplib_validation",
                    },
                )
            )
        else:
            result.append(issue)

    return tuple(result)


# ---------------------------------------------------------------------------
# VPLIB validator adapter
# ---------------------------------------------------------------------------

def _find_callable(module: Any, names: Iterable[str]) -> tuple[str | None, Callable[..., Any] | None]:
    """
    Findet den ersten verfügbaren Callable in einem Modul.
    """

    if module is None:
        return None, None

    for name in names:
        try:
            value = getattr(module, name, None)
            if callable(value):
                return name, value
        except Exception:
            continue

    return None, None


def _call_validator_with_supported_signature(
    func: Callable[..., Any],
    *,
    documents: Mapping[str, Any],
    package_root: Any = None,
    read_result: Any = None,
) -> Any:
    """
    Ruft einen externen Validator defensiv mit mehreren möglichen Signaturen auf.

    Hintergrund:
    Die VPLIB-Core-API kann sich noch verändern. Diese Adapterfunktion
    verhindert, dass die Library-Schicht bei kleinen API-Unterschieden sofort
    bricht.
    """

    call_attempts: list[tuple[tuple[Any, ...], dict[str, Any]]] = [
        ((documents,), {}),
        ((), {"documents": documents}),
        ((), {"package_documents": documents}),
        ((), {"document_mapping": documents}),
    ]

    if read_result is not None:
        call_attempts.extend(
            [
                ((read_result,), {}),
                ((), {"read_result": read_result}),
                ((), {"package": read_result}),
            ]
        )

    if package_root is not None:
        call_attempts.extend(
            [
                ((), {"documents": documents, "package_root": package_root}),
                ((), {"package_documents": documents, "package_root": package_root}),
            ]
        )

    try:
        signature = inspect.signature(func)
        parameters = signature.parameters

        kwargs: dict[str, Any] = {}

        if "documents" in parameters:
            kwargs["documents"] = documents
        elif "package_documents" in parameters:
            kwargs["package_documents"] = documents
        elif "document_mapping" in parameters:
            kwargs["document_mapping"] = documents

        if "package_root" in parameters and package_root is not None:
            kwargs["package_root"] = package_root

        if "read_result" in parameters and read_result is not None:
            kwargs["read_result"] = read_result

        if kwargs:
            return func(**kwargs)

    except Exception:
        pass

    last_error: BaseException | None = None

    for args, kwargs in call_attempts:
        try:
            return func(*args, **kwargs)
        except TypeError as exc:
            last_error = exc
            continue

    if last_error is not None:
        raise last_error

    return func(documents)


def _extract_valid_flag_from_result(result: Any) -> bool | None:
    """
    Extrahiert ein valid/ok-Flag aus unbekannten Validator-Ergebnissen.
    """

    try:
        if isinstance(result, bool):
            return result

        if isinstance(result, Mapping):
            if "valid" in result:
                return safe_bool(result.get("valid"), default=False)
            if "ok" in result:
                return safe_bool(result.get("ok"), default=False)
            if "healthy" in result:
                return safe_bool(result.get("healthy"), default=False)

        for attr in ("valid", "ok", "healthy"):
            if hasattr(result, attr):
                return safe_bool(getattr(result, attr), default=False)

    except Exception:
        return None

    return None


def _extract_messages_from_result(result: Any, key_candidates: Iterable[str]) -> list[str]:
    """
    Extrahiert Warnungen/Fehler aus unbekannten Validator-Ergebnissen.
    """

    messages: list[str] = []

    try:
        if isinstance(result, Mapping):
            for key in key_candidates:
                value = result.get(key)
                messages.extend(ensure_list_of_strings(value))

        else:
            for key in key_candidates:
                value = getattr(result, key, None)
                messages.extend(ensure_list_of_strings(value))

    except Exception:
        return messages

    deduped: list[str] = []

    for message in messages:
        if message not in deduped:
            deduped.append(message)

    return deduped


def _extract_issues_from_vplib_result(result: Any) -> list[LibraryValidationIssue]:
    """
    Extrahiert Issues aus unbekanntem VPLIB-Validator-Ergebnis.
    """

    issues: list[LibraryValidationIssue] = []

    try:
        raw_issues: Any = None

        if isinstance(result, Mapping):
            raw_issues = (
                result.get("issues")
                or result.get("reports")
                or result.get("errors")
            )
        else:
            raw_issues = (
                getattr(result, "issues", None)
                or getattr(result, "reports", None)
                or getattr(result, "errors", None)
            )

        if raw_issues:
            for issue in normalize_issues(raw_issues):
                issues.append(
                    LibraryValidationIssue(
                        level=issue.level,
                        message=issue.message,
                        code=issue.code,
                        document_key=issue.document_key,
                        field_path=issue.field_path,
                        value=issue.value,
                        source="vplib",
                        data=issue.data,
                    )
                )

    except Exception:
        pass

    return issues


def run_vplib_validation_adapter(
    documents: Mapping[str, Any],
    *,
    package_root: Any = None,
    read_result: Any = None,
    options: LibraryPackageValidatorOptions | None = None,
) -> VplibValidationAdapterResult:
    """
    Führt optionale VPLIB-Kernvalidierung aus.

    Wenn keine passende VPLIB-Validator-Funktion gefunden wird, ist das in
    Phase 1 standardmäßig eine Warnung. Erst `require_vplib_validator=True`
    macht es zum Fehler.

    Nicht-strikter Modus:
      VPLIB-Core-Fehler werden zu Warnings demoted, damit frühe Library-
      Integration nicht von strikter Core-Schema-Validierung blockiert wird.
      Library-eigene Pflichtregeln bleiben weiterhin harte Fehler.
    """

    validator_options = coerce_validator_options(options)
    normalized_documents = normalize_documents(documents)

    if vplib_package_validator is None:
        issue_level = "error" if validator_options.require_vplib_validator else "warning"
        issue = LibraryValidationIssue(
            level=issue_level,
            message="vplib package validator is not available",
            code="vplib_validator_unavailable",
            source="vplib",
            data={
                "import_error": exception_to_dict(_VPLIB_VALIDATORS_IMPORT_ERROR),
            },
        )

        return VplibValidationAdapterResult(
            attempted=False,
            available=False,
            ok=not validator_options.require_vplib_validator,
            valid=not validator_options.require_vplib_validator,
            callable_name=None,
            raw_result=None,
            warnings=(issue.message,) if issue.level == "warning" else (),
            errors=(issue.message,) if issue.level in {"error", "fatal"} else (),
            issues=(issue,),
        )

    callable_names = (
        "validate_package",
        "validate_package_documents",
        "validate_document_bundle",
        "validate_documents",
        "validate_package_mapping",
        "validate",
    )

    callable_name, func = _find_callable(vplib_package_validator, callable_names)

    if func is None:
        issue_level = "error" if validator_options.require_vplib_validator else "warning"
        issue = LibraryValidationIssue(
            level=issue_level,
            message="no supported callable found in vplib package validator",
            code="vplib_validator_callable_missing",
            source="vplib",
            data={
                "module": getattr(vplib_package_validator, "__name__", None),
                "expected_callables": list(callable_names),
            },
        )

        return VplibValidationAdapterResult(
            attempted=False,
            available=True,
            ok=not validator_options.require_vplib_validator,
            valid=not validator_options.require_vplib_validator,
            callable_name=None,
            raw_result=None,
            warnings=(issue.message,) if issue.level == "warning" else (),
            errors=(issue.message,) if issue.level in {"error", "fatal"} else (),
            issues=(issue,),
        )

    try:
        raw_result = _call_validator_with_supported_signature(
            func,
            documents=normalized_documents,
            package_root=package_root,
            read_result=read_result,
        )

        valid_flag = _extract_valid_flag_from_result(raw_result)
        raw_valid = bool(valid_flag) if valid_flag is not None else True

        warnings = _extract_messages_from_result(
            raw_result,
            ("warnings", "warning_messages"),
        )
        errors = _extract_messages_from_result(
            raw_result,
            ("errors", "error_messages", "fatal_errors"),
        )

        issues = _extract_issues_from_vplib_result(raw_result)

        for warning in warnings:
            issues.append(
                LibraryValidationIssue.warning(
                    warning,
                    code="vplib_warning",
                    source="vplib",
                )
            )

        for error in errors:
            issues.append(
                LibraryValidationIssue.error(
                    error,
                    code="vplib_error",
                    source="vplib",
                )
            )

        if not validator_options.strict_vplib_validation:
            issues = list(demote_vplib_issues_for_non_strict_mode(issues))

        has_errors = any(issue.level in {"error", "fatal"} for issue in issues)

        adapter_ok = not has_errors
        adapter_valid = raw_valid and not has_errors

        if not validator_options.strict_vplib_validation:
            adapter_ok = True
            adapter_valid = True

        return VplibValidationAdapterResult(
            attempted=True,
            available=True,
            ok=adapter_ok,
            valid=adapter_valid,
            callable_name=callable_name,
            raw_result=raw_result,
            warnings=tuple(issue.message for issue in issues if issue.level == "warning"),
            errors=tuple(issue.message for issue in issues if issue.level in {"error", "fatal"}),
            issues=tuple(issues),
        )

    except Exception as exc:
        issue_level = "error" if validator_options.strict_vplib_validation else "warning"
        issue = LibraryValidationIssue(
            level=issue_level,
            message=f"vplib validator failed: {exc}",
            code="vplib_validator_exception",
            source="vplib",
            data={
                "callable_name": callable_name,
                "exception": exception_to_dict(exc),
            },
        )

        return VplibValidationAdapterResult(
            attempted=True,
            available=True,
            ok=not validator_options.strict_vplib_validation,
            valid=not validator_options.strict_vplib_validation,
            callable_name=callable_name,
            raw_result=None,
            warnings=(issue.message,) if issue.level == "warning" else (),
            errors=(issue.message,) if issue.level in {"error", "fatal"} else (),
            issues=(issue,),
        )


# ---------------------------------------------------------------------------
# Library validation rules
# ---------------------------------------------------------------------------

def validate_required_documents(
    documents: Mapping[str, Any],
    *,
    options: LibraryPackageValidatorOptions,
) -> tuple[list[LibraryValidationIssue], tuple[str, ...]]:
    """
    Prüft minimale Pflichtdokumente.
    """

    issues: list[LibraryValidationIssue] = []
    missing: list[str] = []
    normalized_documents = normalize_documents(documents)

    for key in MIN_REQUIRED_DOCUMENT_KEYS:
        if not has_document(normalized_documents, key):
            missing.append(key)
            issues.append(
                LibraryValidationIssue.error(
                    f"required document is missing: {key}",
                    code="missing_required_document",
                    document_key=key,
                    source="library",
                )
            )

    return issues, tuple(missing)


def validate_recommended_documents(
    documents: Mapping[str, Any],
    *,
    options: LibraryPackageValidatorOptions,
) -> tuple[list[LibraryValidationIssue], tuple[str, ...]]:
    """
    Prüft empfohlene beziehungsweise je nach Optionen verpflichtende Dokumente.
    """

    issues: list[LibraryValidationIssue] = []
    missing: list[str] = []
    normalized_documents = normalize_documents(documents)

    recommended = list(RECOMMENDED_DOCUMENT_KEYS)

    if options.require_editor_inventory and "editor/inventory.json" not in recommended:
        recommended.append("editor/inventory.json")

    if options.require_editor_placement and "editor/placement.json" not in recommended:
        recommended.append("editor/placement.json")

    if options.require_manufacturer_contract and "manufacturer/contract.json" not in recommended:
        recommended.append("manufacturer/contract.json")

    for key in recommended:
        if has_document(normalized_documents, key):
            continue

        missing.append(key)

        required = (
            options.require_recommended_documents
            or (key == "editor/inventory.json" and options.require_editor_inventory)
            or (key == "editor/placement.json" and options.require_editor_placement)
            or (key == "manufacturer/contract.json" and options.require_manufacturer_contract)
        )

        if required:
            issues.append(
                LibraryValidationIssue.error(
                    f"recommended document is required for library use: {key}",
                    code="missing_required_library_document",
                    document_key=key,
                    source="library",
                )
            )
        else:
            issues.append(
                LibraryValidationIssue.warning(
                    f"recommended document is missing: {key}",
                    code="missing_recommended_document",
                    document_key=key,
                    source="library",
                )
            )

    return issues, tuple(missing)


def validate_identity_rules(
    documents: Mapping[str, Any],
    *,
    options: LibraryPackageValidatorOptions,
) -> list[LibraryValidationIssue]:
    """
    Prüft stabile Identität.
    """

    issues: list[LibraryValidationIssue] = []

    package_id = extract_package_id_from_documents(documents)
    family_id = extract_family_id_from_documents(documents)

    if not package_id:
        issues.append(
            LibraryValidationIssue.error(
                "package_id is missing",
                code="missing_package_id",
                document_key=MANIFEST_DOCUMENT_KEY,
                field_path="package_id",
                source="library",
            )
        )

    if not family_id:
        issues.append(
            LibraryValidationIssue.error(
                "family_id is missing",
                code="missing_family_id",
                document_key=MANIFEST_DOCUMENT_KEY,
                field_path="family_id",
                source="library",
            )
        )
        return issues

    normalized_family_id = normalize_stable_id(family_id)

    if options.require_stable_family_id and not is_stable_library_id(family_id):
        issues.append(
            LibraryValidationIssue.error(
                "family_id is not stable or URL-safe",
                code="invalid_family_id",
                document_key=MANIFEST_DOCUMENT_KEY,
                field_path="family_id",
                value=family_id,
                source="library",
                data={
                    "normalized_family_id": normalized_family_id,
                    "allowed_pattern": STABLE_LIBRARY_ID_PATTERN.pattern,
                },
            )
        )

    if options.warn_on_missing_recommended_id_prefix and normalized_family_id and not has_recommended_id_prefix(normalized_family_id):
        issues.append(
            LibraryValidationIssue.warning(
                "family_id does not use a recommended VECTOPLAN prefix",
                code="non_recommended_family_id_prefix",
                document_key=MANIFEST_DOCUMENT_KEY,
                field_path="family_id",
                value=family_id,
                source="library",
                data={
                    "recommended_prefixes": list(RECOMMENDED_ID_PREFIXES),
                },
            )
        )

    identity = get_document_dict(documents, "family/identity.json")
    identity_family_id = first_non_empty(
        deep_get(identity, "family_id"),
        deep_get(identity, "id"),
    )

    if identity_family_id and normalize_stable_id(identity_family_id) != normalized_family_id:
        issues.append(
            LibraryValidationIssue.error(
                "family_id mismatch between manifest and family/identity.json",
                code="family_id_mismatch",
                document_key="family/identity.json",
                field_path="family_id",
                value=identity_family_id,
                source="library",
                data={
                    "manifest_family_id": normalized_family_id,
                    "identity_family_id": normalize_stable_id(identity_family_id),
                },
            )
        )

    return issues


def validate_object_kind_rules(
    documents: Mapping[str, Any],
    *,
    options: LibraryPackageValidatorOptions,
) -> list[LibraryValidationIssue]:
    """
    Prüft unterstützte object_kind.
    """

    issues: list[LibraryValidationIssue] = []
    object_kind = extract_object_kind_from_documents(documents)

    if object_kind == DEFAULT_OBJECT_KIND or object_kind not in VALID_OBJECT_KINDS:
        if options.allow_unknown_object_kind:
            issues.append(
                LibraryValidationIssue.warning(
                    "object_kind is unknown",
                    code="unknown_object_kind",
                    document_key=MANIFEST_DOCUMENT_KEY,
                    field_path="object_kind",
                    value=object_kind,
                    source="library",
                    data={
                        "valid_object_kinds": list(VALID_OBJECT_KINDS),
                    },
                )
            )
        else:
            issues.append(
                LibraryValidationIssue.error(
                    "object_kind is missing or unsupported",
                    code="invalid_object_kind",
                    document_key=MANIFEST_DOCUMENT_KEY,
                    field_path="object_kind",
                    value=object_kind,
                    source="library",
                    data={
                        "valid_object_kinds": list(VALID_OBJECT_KINDS),
                    },
                )
            )

    if object_kind in TECHNICAL_OBJECT_KINDS:
        for key in TECHNICAL_OBJECT_REQUIRED_DOCUMENTS:
            if not has_document(documents, key):
                issues.append(
                    LibraryValidationIssue.warning(
                        f"technical object should provide document: {key}",
                        code="missing_technical_document",
                        document_key=key,
                        source="library",
                    )
                )

    return issues


def validate_classification_rules(
    documents: Mapping[str, Any],
    *,
    options: LibraryPackageValidatorOptions,
) -> list[LibraryValidationIssue]:
    """
    Prüft Katalogklassifikation.
    """

    issues: list[LibraryValidationIssue] = []
    classification = extract_classification_from_documents(documents)

    domain = safe_str(classification.get("domain"), default="")
    category = safe_str(classification.get("category"), default="")
    subcategory = safe_str(classification.get("subcategory"), default="")

    if options.require_classification:
        if not domain:
            issues.append(
                LibraryValidationIssue.error(
                    "classification domain is missing",
                    code="missing_classification_domain",
                    document_key="family/classification.json",
                    field_path="domain",
                    source="library",
                )
            )

        if not category:
            issues.append(
                LibraryValidationIssue.error(
                    "classification category is missing",
                    code="missing_classification_category",
                    document_key="family/classification.json",
                    field_path="category",
                    source="library",
                )
            )

    if not subcategory:
        issues.append(
            LibraryValidationIssue.warning(
                "classification subcategory is missing",
                code="missing_classification_subcategory",
                document_key="family/classification.json",
                field_path="subcategory",
                source="library",
            )
        )

    return issues


def validate_variant_rules(
    documents: Mapping[str, Any],
    *,
    options: LibraryPackageValidatorOptions,
) -> list[LibraryValidationIssue]:
    """
    Prüft Varianten-Nutzbarkeit.
    """

    issues: list[LibraryValidationIssue] = []

    variant_ids = extract_variant_ids_from_documents(documents)
    default_variant_id = extract_default_variant_id_from_documents(documents)

    if not variant_ids:
        if options.allow_empty_variants:
            issues.append(
                LibraryValidationIssue.warning(
                    "no variants found",
                    code="no_variants",
                    document_key="variants/index.json",
                    source="library",
                )
            )
        else:
            issues.append(
                LibraryValidationIssue.error(
                    "no variants found",
                    code="no_variants",
                    document_key="variants/index.json",
                    source="library",
                )
            )

    if not has_document(documents, "variants/default.json"):
        issues.append(
            LibraryValidationIssue.error(
                "default variant document is missing",
                code="missing_default_variant_document",
                document_key="variants/default.json",
                source="library",
            )
        )

    if options.require_default_variant_in_index and variant_ids and default_variant_id not in variant_ids:
        issues.append(
            LibraryValidationIssue.error(
                "default_variant_id is not present in variants index",
                code="default_variant_not_indexed",
                document_key="variants/index.json",
                field_path="default_variant_id",
                value=default_variant_id,
                source="library",
                data={
                    "variant_ids": variant_ids,
                },
            )
        )

    for variant_id in variant_ids:
        if not is_stable_library_id(variant_id):
            issues.append(
                LibraryValidationIssue.error(
                    "variant_id is not stable or URL-safe",
                    code="invalid_variant_id",
                    document_key="variants/index.json",
                    value=variant_id,
                    source="library",
                )
            )

    return issues


def validate_visible_library_rules(
    documents: Mapping[str, Any],
    *,
    options: LibraryPackageValidatorOptions,
) -> list[LibraryValidationIssue]:
    """
    Prüft Mindestdaten für Creative-Library-Anzeige.
    """

    issues: list[LibraryValidationIssue] = []

    label = extract_label_from_documents(documents)
    family_id = extract_family_id_from_documents(documents)

    if options.require_visible_label and not label:
        issues.append(
            LibraryValidationIssue.error(
                "visible library label is missing",
                code="missing_visible_label",
                document_key="family/identity.json",
                field_path="label",
                source="library",
                data={
                    "fallback_label": humanize_identifier(family_id),
                },
            )
        )

    for key in VISIBLE_LIBRARY_RECOMMENDED_DOCUMENTS:
        if not has_document(documents, key):
            issues.append(
                LibraryValidationIssue.warning(
                    f"visible library document is missing: {key}",
                    code="missing_visible_library_document",
                    document_key=key,
                    source="library",
                )
            )

    inventory = get_document_dict(documents, "editor/inventory.json")

    if inventory:
        enabled = first_non_empty(
            deep_get(inventory, "enabled"),
            deep_get(inventory, "visible"),
            True,
        )

        if not safe_bool(enabled, default=True):
            issues.append(
                LibraryValidationIssue.warning(
                    "inventory item is marked as disabled or invisible",
                    code="inventory_disabled",
                    document_key="editor/inventory.json",
                    field_path="enabled",
                    value=enabled,
                    source="library",
                )
            )

    return issues


def validate_module_rules(
    documents: Mapping[str, Any],
    *,
    options: LibraryPackageValidatorOptions,
) -> list[LibraryValidationIssue]:
    """
    Prüft grundlegende Modul-Dokument-Konsistenz.
    """

    issues: list[LibraryValidationIssue] = []

    modules_doc = get_document_dict(documents, MODULES_DOCUMENT_KEY)

    if not modules_doc:
        return issues

    try:
        modules = extract_modules_from_documents(documents)

        for module in modules:
            module_name = safe_str(
                get_attr_or_key(module, "module_name")
                or get_attr_or_key(module, "name")
                or get_attr_or_key(module, "id"),
                default="unknown",
            )
            active = safe_bool(get_attr_or_key(module, "active"), default=False)
            missing_docs = tuple_of_strings(get_attr_or_key(module, "missing_documents", default=()))

            if active and missing_docs:
                issues.append(
                    LibraryValidationIssue.error(
                        f"active module has missing documents: {module_name}",
                        code="active_module_missing_documents",
                        document_key=MODULES_DOCUMENT_KEY,
                        field_path=module_name,
                        value=list(missing_docs),
                        source="library",
                    )
                )

    except Exception as exc:
        issues.append(
            issue_from_exception(
                exc,
                code="module_rule_validation_failed",
                source="library",
            )
        )

    return issues


# ---------------------------------------------------------------------------
# Main validation
# ---------------------------------------------------------------------------

def validate_library_documents(
    documents: Mapping[str, Any] | None,
    *,
    package_root: Any = None,
    read_result: Any = None,
    options: LibraryPackageValidatorOptions | None = None,
) -> LibraryPackageValidationResult:
    """
    Validiert ein bereits gelesenes VPLIB-Dokumentmapping für die Creative Library.
    """

    validator_options = coerce_validator_options(options)

    try:
        normalized_documents = normalize_documents(documents)
        issues: list[LibraryValidationIssue] = []

        package_id = extract_package_id_from_documents(normalized_documents)
        family_id = extract_family_id_from_documents(normalized_documents)
        item_id = normalize_stable_id(family_id, fallback=package_id) or None
        label = extract_label_from_documents(normalized_documents)
        object_kind = extract_object_kind_from_documents(normalized_documents)
        variant_ids = extract_variant_ids_from_documents(normalized_documents)
        default_variant_id = extract_default_variant_id_from_documents(normalized_documents)

        required_issues, missing_required = validate_required_documents(
            normalized_documents,
            options=validator_options,
        )
        issues.extend(required_issues)

        recommended_issues, missing_recommended = validate_recommended_documents(
            normalized_documents,
            options=validator_options,
        )
        issues.extend(recommended_issues)

        issues.extend(validate_identity_rules(normalized_documents, options=validator_options))
        issues.extend(validate_object_kind_rules(normalized_documents, options=validator_options))
        issues.extend(validate_classification_rules(normalized_documents, options=validator_options))
        issues.extend(validate_variant_rules(normalized_documents, options=validator_options))
        issues.extend(validate_visible_library_rules(normalized_documents, options=validator_options))
        issues.extend(validate_module_rules(normalized_documents, options=validator_options))

        vplib_validation = run_vplib_validation_adapter(
            normalized_documents,
            package_root=package_root,
            read_result=read_result,
            options=validator_options,
        )
        issues.extend(vplib_validation.issues)

        error_count = sum(1 for issue in issues if issue.level == "error")
        fatal_count = sum(1 for issue in issues if issue.level == "fatal")

        valid = error_count == 0 and fatal_count == 0

        if validator_options.strict_vplib_validation and not vplib_validation.valid:
            valid = False

        status = "valid" if valid else "invalid"

        return LibraryPackageValidationResult(
            ok=valid,
            valid=valid,
            status=status,
            package_id=package_id,
            family_id=family_id,
            item_id=item_id,
            label=label,
            object_kind=object_kind,
            document_count=len(normalized_documents),
            missing_required_documents=missing_required,
            missing_recommended_documents=missing_recommended,
            variant_ids=tuple(variant_ids),
            default_variant_id=default_variant_id,
            issues=tuple(issues),
            vplib_validation=vplib_validation,
            validated_at=utc_now_iso(),
            validation_mode=validator_options.validation_mode,
            options=validator_options,
            metadata={
                "document_keys": sorted(normalized_documents.keys()),
                "package_root": safe_path_str(package_root),
                "imports": get_import_status(),
            },
        )

    except Exception as exc:
        return LibraryPackageValidationResult.error(
            exc,
            package_id=extract_package_id_from_documents(documents or {}),
            family_id=extract_family_id_from_documents(documents or {}),
            options=validator_options,
        )


def validate_read_result(
    read_result: Any,
    *,
    options: LibraryPackageValidatorOptions | None = None,
) -> LibraryPackageValidationResult:
    """
    Validiert ein PackageReadResult oder kompatibles Mapping.
    """

    validator_options = coerce_validator_options(options)

    try:
        documents = read_result_to_document_mapping(read_result)

        if isinstance(read_result, Mapping):
            package_root = read_result.get("package_root")
        else:
            package_root = getattr(read_result, "package_root", None)

        return validate_library_documents(
            documents,
            package_root=package_root,
            read_result=read_result,
            options=validator_options,
        )

    except Exception as exc:
        return LibraryPackageValidationResult.error(
            exc,
            package_id=None,
            family_id=None,
            options=validator_options,
        )


def validate_read_results(
    read_results: Iterable[Any],
    *,
    options: LibraryPackageValidatorOptions | None = None,
) -> list[LibraryPackageValidationResult]:
    """
    Validiert mehrere PackageReadResults.
    """

    validator_options = coerce_validator_options(options)
    results: list[LibraryPackageValidationResult] = []

    for read_result in read_results or ():
        try:
            results.append(
                validate_read_result(
                    read_result,
                    options=validator_options,
                )
            )
        except Exception as exc:
            results.append(
                LibraryPackageValidationResult.error(
                    exc,
                    options=validator_options,
                )
            )

    return results


def validation_result_to_item_validation_summary(
    result: LibraryPackageValidationResult | Mapping[str, Any] | None,
) -> LibraryItemValidationSummary:
    """
    Wandelt Validierungsergebnis in LibraryItemValidationSummary.
    """

    if isinstance(result, LibraryPackageValidationResult):
        return result.to_summary()

    if isinstance(result, Mapping):
        warnings = ensure_list_of_strings(result.get("warnings"))
        errors = ensure_list_of_strings(result.get("errors"))

        if not warnings and "issues" in result:
            for issue in normalize_issues(result.get("issues")):
                if issue.level == "warning":
                    warnings.append(issue.message)
                elif issue.level in {"error", "fatal"}:
                    errors.append(issue.message)

        return LibraryItemValidationSummary(
            valid=safe_bool(result.get("valid"), default=False),
            warning_count=safe_int(result.get("warning_count"), default=len(warnings), minimum=0),
            error_count=safe_int(result.get("error_count"), default=len(errors), minimum=0),
            fatal_count=safe_int(result.get("fatal_count"), default=0, minimum=0),
            warnings=tuple(warnings),
            errors=tuple(errors),
        )

    return LibraryItemValidationSummary()


def validation_result_to_status(
    result: LibraryPackageValidationResult | Mapping[str, Any] | None,
) -> str:
    """
    Wandelt Validierungsergebnis in LibraryItemStatus.
    """

    if isinstance(result, LibraryPackageValidationResult):
        return LibraryItemStatus.VALID.value if result.valid else LibraryItemStatus.INVALID.value

    if isinstance(result, Mapping):
        return LibraryItemStatus.VALID.value if safe_bool(result.get("valid"), default=False) else LibraryItemStatus.INVALID.value

    return LibraryItemStatus.INVALID.value


# ---------------------------------------------------------------------------
# Response helpers
# ---------------------------------------------------------------------------

def build_validation_response(
    result: LibraryPackageValidationResult | Mapping[str, Any] | None,
    *,
    include_vplib_raw_result: bool = False,
) -> dict[str, Any]:
    """
    Baut eine JSON-kompatible Validierungsantwort.
    """

    try:
        if isinstance(result, LibraryPackageValidationResult):
            return result.to_dict(include_vplib_raw_result=include_vplib_raw_result)

        if isinstance(result, Mapping):
            return json_safe(result)

        return {
            "ok": False,
            "valid": False,
            "status": "error",
            "errors": ["validation result is empty"],
        }

    except Exception as exc:
        return {
            "ok": False,
            "valid": False,
            "status": "error",
            "errors": ["could not serialize validation result"],
            "error": exception_to_dict(exc),
        }


def build_many_validation_response(
    results: Iterable[LibraryPackageValidationResult],
    *,
    include_vplib_raw_result: bool = False,
) -> dict[str, Any]:
    """
    Baut eine JSON-kompatible Antwort für mehrere Validierungen.
    """

    result_list = list(results or ())

    valid_count = sum(1 for result in result_list if result.valid)
    invalid_count = sum(1 for result in result_list if not result.valid)
    error_count = sum(1 for result in result_list if result.status == "error")

    return {
        "ok": error_count == 0,
        "status": "ok" if error_count == 0 else "partial" if valid_count > 0 else "error",
        "count": len(result_list),
        "valid_count": valid_count,
        "invalid_count": invalid_count,
        "error_count": error_count,
        "results": [
            result.to_dict(include_vplib_raw_result=include_vplib_raw_result)
            for result in result_list
        ],
    }


# ---------------------------------------------------------------------------
# Health
# ---------------------------------------------------------------------------

def get_import_status() -> dict[str, Any]:
    """
    Liefert Importstatus optionaler Abhängigkeiten.
    """

    return {
        "detail": {
            "ok": _DETAIL_IMPORT_ERROR is None,
            "error": exception_to_dict(_DETAIL_IMPORT_ERROR),
        },
        "item": {
            "ok": _ITEM_IMPORT_ERROR is None,
            "error": exception_to_dict(_ITEM_IMPORT_ERROR),
        },
        "reader": {
            "ok": _READER_IMPORT_ERROR is None,
            "error": exception_to_dict(_READER_IMPORT_ERROR),
        },
        "vplib_validators": {
            "ok": _VPLIB_VALIDATORS_IMPORT_ERROR is None,
            "error": exception_to_dict(_VPLIB_VALIDATORS_IMPORT_ERROR),
        },
    }


def get_library_package_validator_health() -> dict[str, Any]:
    """
    Health-Status der Library-Package-Validator-Schicht.

    Führt keine echte Paketvalidierung aus.
    """

    warnings: list[str] = []
    errors: list[str] = []

    imports = get_import_status()

    if _DETAIL_IMPORT_ERROR is not None:
        warnings.append("library_detail import failed; fallback document helpers are active")

    if _ITEM_IMPORT_ERROR is not None:
        warnings.append("library_item import failed; fallback item helpers are active")

    if _READER_IMPORT_ERROR is not None:
        warnings.append("package_reader import failed; direct document validation still works")

    if _VPLIB_VALIDATORS_IMPORT_ERROR is not None:
        warnings.append("vplib package validator import failed; library-only validation is active")

    try:
        options = LibraryPackageValidatorOptions()
        options_dict = options.to_dict()
    except Exception as exc:
        options_dict = {}
        errors.append(f"could not build validator options: {exc}")

    try:
        safe_int_self_test = safe_int("999999", default=500, minimum=1, maximum=5000)
        if safe_int_self_test != 5000:
            errors.append(f"safe_int maximum self-test failed: expected 5000, got {safe_int_self_test}")
    except Exception as exc:
        errors.append(f"safe_int maximum self-test failed: {exc}")

    try:
        adapter = run_vplib_validation_adapter(
            {},
            options=LibraryPackageValidatorOptions(
                strict_vplib_validation=False,
                require_vplib_validator=False,
            ),
        )
        adapter_status = adapter.to_dict(include_raw_result=False)
    except Exception as exc:
        adapter_status = {
            "ok": False,
            "error": exception_to_dict(exc),
        }
        warnings.append("vplib adapter health check failed")

    healthy = len(errors) == 0

    return {
        "ok": healthy,
        "healthy": healthy,
        "component": LIBRARY_PACKAGE_VALIDATOR_COMPONENT,
        "version": LIBRARY_PACKAGE_VALIDATOR_VERSION,
        "generated_at": utc_now_iso(),
        "options": options_dict,
        "vplib_adapter": adapter_status,
        "imports": imports,
        "warnings": warnings,
        "errors": errors,
    }


def assert_library_package_validator_ready() -> None:
    """
    Wirft RuntimeError, wenn der Validator nicht bereit ist.
    """

    health = get_library_package_validator_health()

    if health.get("healthy"):
        return

    raise RuntimeError(
        f"library package validator is not ready: errors={health.get('errors')}"
    )


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

__all__: Final[tuple[str, ...]] = (
    "LIBRARY_PACKAGE_VALIDATOR_VERSION",
    "LIBRARY_PACKAGE_VALIDATOR_COMPONENT",
    "DEFAULT_VALIDATION_MODE",
    "DEFAULT_VALIDATION_STATUS",
    "DEFAULT_OBJECT_KIND_FALLBACK",
    "DEFAULT_VARIANT_ID_FALLBACK",
    "STABLE_LIBRARY_ID_PATTERN",
    "RECOMMENDED_ID_PREFIXES",
    "VALID_ISSUE_LEVELS",
    "VALID_VALIDATION_STATUSES",
    "MIN_REQUIRED_DOCUMENT_KEYS",
    "RECOMMENDED_DOCUMENT_KEYS",
    "TECHNICAL_OBJECT_REQUIRED_DOCUMENTS",
    "VISIBLE_LIBRARY_RECOMMENDED_DOCUMENTS",
    "TECHNICAL_OBJECT_KINDS",
    "LibraryValidationIssueLevel",
    "LibraryPackageValidationStatus",
    "LibraryValidationIssue",
    "LibraryPackageValidatorOptions",
    "coerce_validator_options",
    "VplibValidationAdapterResult",
    "LibraryPackageValidationResult",
    "utc_now_iso",
    "exception_to_dict",
    "json_safe",
    "tuple_of_strings",
    "get_attr_or_key",
    "normalize_issue_level",
    "normalize_validation_status",
    "normalize_document_key",
    "has_document",
    "get_document",
    "variant_id_from_any",
    "extract_variant_ids_from_documents",
    "extract_default_variant_id_from_documents",
    "extract_classification_from_documents",
    "extract_object_kind_from_documents",
    "extract_label_from_documents",
    "is_stable_library_id",
    "has_recommended_id_prefix",
    "normalize_issues",
    "issue_from_exception",
    "demote_vplib_issues_for_non_strict_mode",
    "run_vplib_validation_adapter",
    "validate_required_documents",
    "validate_recommended_documents",
    "validate_identity_rules",
    "validate_object_kind_rules",
    "validate_classification_rules",
    "validate_variant_rules",
    "validate_visible_library_rules",
    "validate_module_rules",
    "validate_library_documents",
    "validate_read_result",
    "validate_read_results",
    "validation_result_to_item_validation_summary",
    "validation_result_to_status",
    "build_validation_response",
    "build_many_validation_response",
    "get_import_status",
    "get_library_package_validator_health",
    "assert_library_package_validator_ready",
)