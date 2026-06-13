# services/vectoplan-library/src/library/read_models/block_detail_builder.py
"""
Block Detail Builder für die VECTOPLAN Creative-Library-Schicht.

Diese Datei baut die ausführliche API-Detailansicht eines Blocks/Objekts aus
gelesenen, validierten und fingerprinteten VPLIB-Paketen.

Hauptzielroute:

    GET /api/v1/vplib/library/blocks/<block_id>

Diese Route soll später beweisen:

- der Block wurde im Source-Ordner gefunden
- seine VPLIB-Dokumente wurden gelesen
- seine Library-Validierung wurde ausgeführt
- seine stabile ID wurde erkannt
- seine Varianten sind abrufbar
- seine technischen Dokumente sind sichtbar
- sein `revision_hash` ist vorhanden
- seine Taxonomie wurde aus Backend-/Dokument-/Reader-/Validator-Daten aufgelöst
- die Detaildaten stammen aus echten Dateien, nicht aus Mock-Daten

Diese Datei:

- schreibt nichts
- scannt nicht selbst
- liest keine Dateien
- validiert nicht selbst
- erzeugt keine Datenbankeinträge
- baut nur ein Read-Model aus vorhandenen Pipeline-Ergebnissen

Input typischerweise:

- PackageReadResult aus `package_reader.py`
- LibraryPackageValidationResult aus `library_package_validator.py`
- PackageFingerprintResult aus `package_fingerprint.py`
- optional LibraryItem aus `block_summary_builder.py`

Output:

- LibraryItemDetail, wenn verfügbar
- standardisierte Detail-API-Antworten
- Variantenantworten für /blocks/<block_id>/variants

Taxonomie-Regel:

    Backend-Taxonomie ist kanonisch für Labels, Pfade und Navigation.

Detailantwort enthält:

- taxonomy.domain
- taxonomy.category
- taxonomy.subcategory
- taxonomy.domain_label
- taxonomy.category_label
- taxonomy.subcategory_label
- taxonomy.taxonomy_path
- taxonomy.classification_path
- taxonomy.source_path
- taxonomy.taxonomy_version
- taxonomy.source

Version 0.2.0:

- Taxonomie-Kontext wird vollständig in Detailantwort eingebunden.
- Detail-Fallback enthält `taxonomy`, `classification`, `source.source_path`.
- Variantenantwort enthält Taxonomie-Kontext.
- Health prüft Taxonomie-Verfügbarkeit.
- Bestehende Public-APIs bleiben rückwärtskompatibel.
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

BLOCK_DETAIL_BUILDER_VERSION: Final[str] = "0.2.0"
BLOCK_DETAIL_BUILDER_COMPONENT: Final[str] = "library-block-detail-builder"

DEFAULT_DETAIL_STATUS: Final[str] = "candidate"
DEFAULT_VARIANT_ID_FALLBACK: Final[str] = "default"
UNKNOWN_BLOCK_ID: Final[str] = "unknown.library_item"
UNKNOWN_TAXONOMY_KEY: Final[str] = "unknown"

DETAIL_STATUS_VALUES: Final[tuple[str, ...]] = (
    "candidate",
    "valid",
    "invalid",
    "not_found",
    "error",
    "ok",
    "empty",
    "partial",
)

DEFAULT_DETAIL_DOCUMENT_GROUP_ORDER: Final[tuple[str, ...]] = (
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


# ---------------------------------------------------------------------------
# Generic fallback helpers
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
_SUMMARY_IMPORT_ERROR: BaseException | None = None
_TAXONOMY_IMPORT_ERROR: BaseException | None = None

try:
    from library.domain.library_item import (
        DEFAULT_VARIANT_ID,
        LibraryItem,
        LibraryItemStatus,
        LibraryItemValidationSummary,
        deep_get,
        ensure_dict,
        ensure_list_of_strings,
        first_non_empty,
        humanize_identifier,
        normalize_stable_id,
        normalize_variant_id,
        safe_bool,
        safe_int,
        safe_path_str,
        safe_str,
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
    humanize_identifier = _fallback_humanize_identifier


try:
    from library.domain.library_detail import (
        LibraryItemDetail,
        LibraryModuleDetail,
        LibrarySourceDetail,
        LibraryVariantDetail,
        build_detail_response,
        build_error_detail_response,
        build_not_found_detail_response,
        extract_family_id_from_documents,
        extract_modules_from_documents,
        extract_package_id_from_documents,
        extract_variants_from_documents,
        get_document_dict,
        group_documents,
        make_validation_summary,
        normalize_documents,
    )
except Exception as import_exc:  # pragma: no cover - defensive fallback
    _DETAIL_IMPORT_ERROR = import_exc

    LibraryItemDetail = None  # type: ignore[assignment]
    LibraryVariantDetail = Any  # type: ignore[assignment]
    LibraryModuleDetail = Any  # type: ignore[assignment]

    @dataclass(frozen=True)
    class LibrarySourceDetail:  # type: ignore[no-redef]
        source_path: str | None = None
        package_root: str | None = None
        relative_package_root: str | None = None
        source_root: str | None = None
        discovered_at: str | None = None
        scanned_at: str | None = None
        revision_hash: str | None = None

        def to_dict(self) -> dict[str, Any]:
            return {
                "source_path": self.source_path,
                "package_root": self.package_root,
                "relative_package_root": self.relative_package_root,
                "source_root": self.source_root,
                "discovered_at": self.discovered_at,
                "scanned_at": self.scanned_at,
                "revision_hash": self.revision_hash,
            }

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
        variants: list[Any] = []

        variants_index = get_document_dict(docs, "variants/index.json")
        raw_variants = variants_index.get("variants") or variants_index.get("variant_ids") or []

        if isinstance(raw_variants, Mapping):
            for key, value in raw_variants.items():
                variant_data = dict(value) if isinstance(value, Mapping) else {}
                variant_data.setdefault("variant_id", key)
                variants.append(variant_data)

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
        modules_doc = get_document_dict(docs, "vplib.modules.json")
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

    def group_documents(documents: Mapping[str, Any] | None) -> dict[str, dict[str, Any]]:
        grouped: dict[str, dict[str, Any]] = {}

        for key, value in normalize_documents(documents).items():
            group = "root" if "/" not in key else key.split("/", 1)[0]
            grouped.setdefault(group, {})
            grouped[group][key] = value

        return grouped

    def make_validation_summary(value: Any) -> LibraryItemValidationSummary:
        if isinstance(value, LibraryItemValidationSummary):
            return value

        if isinstance(value, Mapping):
            warnings = ensure_list_of_strings(value.get("warnings"))
            errors = ensure_list_of_strings(value.get("errors"))

            return LibraryItemValidationSummary(
                valid=safe_bool(value.get("valid"), default=False),
                warning_count=safe_int(value.get("warning_count"), default=len(warnings), minimum=0),
                error_count=safe_int(value.get("error_count"), default=len(errors), minimum=0),
                fatal_count=safe_int(value.get("fatal_count"), default=0, minimum=0),
                warnings=tuple(warnings),
                errors=tuple(errors),
            )

        return LibraryItemValidationSummary()

    def build_detail_response(detail: Any, *, ok: bool | None = None, include_raw_documents: bool = True) -> dict[str, Any]:
        if detail is None:
            return {
                "ok": False,
                "status": "not_found",
                "item": None,
            }

        return {
            "ok": bool(ok) if ok is not None else True,
            "status": "ok",
            "item": safe_detail_to_dict(detail, include_raw_documents=include_raw_documents),
        }

    def build_not_found_detail_response(block_id: Any) -> dict[str, Any]:
        normalized_id = normalize_stable_id(block_id, fallback=safe_str(block_id, default="unknown"))

        return {
            "ok": False,
            "status": "not_found",
            "item": None,
            "block_id": normalized_id,
            "errors": [f"library block not found: {normalized_id}"],
        }

    def build_error_detail_response(block_id: Any, exc: BaseException, *, include_traceback: bool = False) -> dict[str, Any]:
        normalized_id = normalize_stable_id(block_id, fallback=safe_str(block_id, default="unknown"))

        return {
            "ok": False,
            "status": "error",
            "item": None,
            "block_id": normalized_id,
            "errors": [f"could not build library block detail: {normalized_id}"],
            "error": exception_to_dict(exc, include_traceback=include_traceback),
        }


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
        return make_validation_summary(result)

    def validation_result_to_status(result: Any) -> str:
        if isinstance(result, Mapping):
            return "valid" if safe_bool(result.get("valid"), default=False) else "invalid"

        return "valid" if safe_bool(getattr(result, "valid", False), default=False) else "invalid"


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
    from library.read_models.block_summary_builder import (
        build_library_item_from_parts,
        enrich_summary_with_taxonomy,
        extract_revision_hash,
        extract_taxonomy_context,
        get_taxonomy_lookup,
        load_taxonomy_payload,
    )
except Exception as import_exc:  # pragma: no cover - defensive fallback
    _SUMMARY_IMPORT_ERROR = import_exc

    def extract_revision_hash(fingerprint: Any = None, read_result: Any = None) -> str | None:
        value = first_non_empty(
            get_attr_or_key(fingerprint, "revision_hash"),
            get_attr_or_key(fingerprint, "hash"),
            get_attr_or_key(fingerprint, "package_hash"),
            get_attr_or_key(read_result, "revision_hash"),
        )
        text = safe_str(value, default="")
        return text or None

    def extract_taxonomy_context(
        *,
        read_result: Any = None,
        validation_result: Any = None,
        documents: Mapping[str, Any] | None = None,
        lookup: Mapping[str, dict[str, Any]] | None = None,
    ) -> dict[str, Any]:
        docs = normalize_documents(documents)
        manifest = get_document_dict(docs, "vplib.manifest.json")
        classification = get_document_dict(docs, "family/classification.json")

        domain = first_non_empty(
            get_attr_or_key(validation_result, "domain"),
            get_attr_or_key(read_result, "domain"),
            deep_get(manifest, "domain"),
            deep_get(manifest, "classification.domain"),
            deep_get(classification, "domain"),
            deep_get(classification, "classification.domain"),
        )
        category = first_non_empty(
            get_attr_or_key(validation_result, "category"),
            get_attr_or_key(read_result, "category"),
            deep_get(manifest, "category"),
            deep_get(manifest, "classification.category"),
            deep_get(classification, "category"),
            deep_get(classification, "classification.category"),
        )
        subcategory = first_non_empty(
            get_attr_or_key(validation_result, "subcategory"),
            get_attr_or_key(read_result, "subcategory"),
            deep_get(manifest, "subcategory"),
            deep_get(manifest, "classification.subcategory"),
            deep_get(classification, "subcategory"),
            deep_get(classification, "classification.subcategory"),
        )
        taxonomy_version = first_non_empty(
            get_attr_or_key(validation_result, "taxonomy_version"),
            get_attr_or_key(read_result, "taxonomy_version"),
            deep_get(manifest, "taxonomy_version"),
            deep_get(classification, "taxonomy_version"),
        )

        domain = _fallback_normalize_slug(domain, default="")
        category = _fallback_normalize_slug(category, default="")
        subcategory = _fallback_normalize_slug(subcategory, default="")
        taxonomy_path = "/".join(part for part in (domain, category, subcategory) if part)

        return {
            "domain": domain or None,
            "category": category or None,
            "subcategory": subcategory or None,
            "domain_label": humanize_identifier(domain) if domain else None,
            "category_label": humanize_identifier(category) if category else None,
            "subcategory_label": humanize_identifier(subcategory) if subcategory else None,
            "taxonomy_path": taxonomy_path or None,
            "classification_path": taxonomy_path or None,
            "source_path": first_non_empty(deep_get(manifest, "source_path"), deep_get(classification, "source_path")),
            "taxonomy_version": safe_str(taxonomy_version, default="") or None,
            "labels": {
                "domain": humanize_identifier(domain) if domain else None,
                "category": humanize_identifier(category) if category else None,
                "subcategory": humanize_identifier(subcategory) if subcategory else None,
            },
            "source": {
                "fallback": True,
            },
        }

    def enrich_summary_with_taxonomy(summary: Mapping[str, Any], *, lookup: Mapping[str, dict[str, Any]] | None = None) -> dict[str, Any]:
        result = dict(summary)
        context = extract_taxonomy_context(
            read_result=result,
            documents={},
            lookup=lookup,
        )
        result["taxonomy"] = context
        result["domain"] = context.get("domain")
        result["category"] = context.get("category")
        result["subcategory"] = context.get("subcategory")
        result["domain_label"] = context.get("domain_label")
        result["category_label"] = context.get("category_label")
        result["subcategory_label"] = context.get("subcategory_label")
        result["taxonomy_path"] = context.get("taxonomy_path")
        result["classification_path"] = context.get("classification_path")
        result["taxonomy_version"] = context.get("taxonomy_version")
        return result

    def get_taxonomy_lookup(*, force_reload: bool = False) -> dict[str, dict[str, Any]]:
        return {}

    def load_taxonomy_payload(*, force_reload: bool = False) -> dict[str, Any]:
        return {
            "ok": False,
            "available": False,
            "fallback": True,
        }

    def build_library_item_from_parts(
        *,
        read_result: Any = None,
        validation_result: Any = None,
        fingerprint_result: Any = None,
        documents: Mapping[str, Any] | None = None,
    ) -> dict[str, Any]:
        docs = normalize_documents(documents if documents is not None else read_result_to_document_mapping(read_result))
        family_id = extract_family_id_from_documents(docs)
        package_id = extract_package_id_from_documents(docs)
        item_id = normalize_stable_id(family_id, fallback=package_id) or UNKNOWN_BLOCK_ID
        taxonomy_context = extract_taxonomy_context(
            read_result=read_result,
            validation_result=validation_result,
            documents=docs,
        )

        return {
            "id": item_id,
            "family_id": item_id,
            "package_id": package_id,
            "label": humanize_identifier(item_id),
            "status": validation_result_to_status(validation_result),
            "validation": validation_result_to_item_validation_summary(validation_result).to_dict(),
            "revision_hash": extract_revision_hash(fingerprint_result, read_result),
            "source_path": safe_path_str(get_attr_or_key(read_result, "package_root")),
            "package_root": safe_path_str(get_attr_or_key(read_result, "package_root")),
            "relative_package_root": safe_path_str(get_attr_or_key(read_result, "relative_package_root")),
            "domain": taxonomy_context.get("domain"),
            "category": taxonomy_context.get("category"),
            "subcategory": taxonomy_context.get("subcategory"),
            "taxonomy": taxonomy_context,
            "metadata": {
                "taxonomy": taxonomy_context,
            },
        }


try:
    from library.taxonomy import get_default_taxonomy_service
except Exception as import_exc:  # pragma: no cover - defensive fallback
    _TAXONOMY_IMPORT_ERROR = import_exc
    get_default_taxonomy_service = None  # type: ignore[assignment]


# ---------------------------------------------------------------------------
# Taxonomy helpers
# ---------------------------------------------------------------------------

_TAXONOMY_HEALTH_LOCK = RLock()
_TAXONOMY_HEALTH_CACHE: dict[str, Any] = {
    "payload": None,
    "loaded_at": None,
    "error": None,
}


def taxonomy_available() -> bool:
    return (
        (_TAXONOMY_IMPORT_ERROR is None and get_default_taxonomy_service is not None)
        or _SUMMARY_IMPORT_ERROR is None
    )


def get_taxonomy_health_payload(*, force_reload: bool = False) -> dict[str, Any]:
    with _TAXONOMY_HEALTH_LOCK:
        if not force_reload and isinstance(_TAXONOMY_HEALTH_CACHE.get("payload"), Mapping):
            return dict(_TAXONOMY_HEALTH_CACHE["payload"])

        try:
            payload = load_taxonomy_payload(force_reload=force_reload)
            result = {
                "available": taxonomy_available(),
                "payload_ok": bool(payload.get("ok")),
                "taxonomy_version": safe_str(payload.get("taxonomy_version"), default="") or None,
                "error": payload.get("error"),
            }
            _TAXONOMY_HEALTH_CACHE["payload"] = result
            _TAXONOMY_HEALTH_CACHE["loaded_at"] = utc_now_iso()
            _TAXONOMY_HEALTH_CACHE["error"] = result.get("error")
            return result
        except Exception as exc:
            result = {
                "available": taxonomy_available(),
                "payload_ok": False,
                "error": exception_to_dict(exc),
            }
            _TAXONOMY_HEALTH_CACHE["payload"] = result
            _TAXONOMY_HEALTH_CACHE["loaded_at"] = utc_now_iso()
            _TAXONOMY_HEALTH_CACHE["error"] = result.get("error")
            return result


def build_detail_taxonomy_payload(
    *,
    read_result: Any = None,
    validation_result: Any = None,
    documents: Mapping[str, Any] | None = None,
    item: Any = None,
) -> dict[str, Any]:
    """
    Baut den kanonischen Taxonomieblock für Detailantworten.
    """
    docs = normalize_documents(documents)
    item_summary = safe_detail_to_dict(item, include_raw_documents=False) if item is not None else {}
    item_metadata = ensure_dict(item_summary.get("metadata"))
    item_taxonomy = ensure_dict(item_summary.get("taxonomy")) or ensure_dict(item_metadata.get("taxonomy"))

    context = extract_taxonomy_context(
        read_result=read_result or item_summary,
        validation_result=validation_result,
        documents=docs,
        lookup=get_taxonomy_lookup(),
    )

    for key in (
        "domain",
        "category",
        "subcategory",
        "domain_label",
        "category_label",
        "subcategory_label",
        "taxonomy_path",
        "classification_path",
        "source_path",
        "taxonomy_version",
    ):
        if not context.get(key) and item_taxonomy.get(key):
            context[key] = item_taxonomy.get(key)

    return json_safe(context)


def build_classification_payload(
    *,
    documents: Mapping[str, Any],
    taxonomy: Mapping[str, Any],
) -> dict[str, Any]:
    """
    Baut einen konsolidierten Klassifikationsblock.
    """
    classification = get_document_dict(documents, "family/classification.json")
    manifest = get_document_dict(documents, "vplib.manifest.json")
    inventory = get_document_dict(documents, "editor/inventory.json")

    return {
        "domain": taxonomy.get("domain"),
        "category": taxonomy.get("category"),
        "subcategory": taxonomy.get("subcategory"),
        "domain_label": taxonomy.get("domain_label"),
        "category_label": taxonomy.get("category_label"),
        "subcategory_label": taxonomy.get("subcategory_label"),
        "classification_path": taxonomy.get("classification_path") or taxonomy.get("taxonomy_path"),
        "taxonomy_path": taxonomy.get("taxonomy_path"),
        "source_path": taxonomy.get("source_path"),
        "taxonomy_version": taxonomy.get("taxonomy_version"),
        "labels": taxonomy.get("labels"),
        "source": taxonomy.get("source"),
        "documents": {
            "classification": json_safe(classification),
            "manifest_classification": json_safe(manifest.get("classification")),
            "inventory_classification": json_safe(inventory.get("classification")),
        },
    }


# ---------------------------------------------------------------------------
# Generic helpers after optional imports
# ---------------------------------------------------------------------------

def normalize_detail_status(value: Any) -> str:
    """Normalisiert Detail-Status."""
    try:
        text = safe_str(value, default=DEFAULT_DETAIL_STATUS).lower()

        if text in DETAIL_STATUS_VALUES:
            return text

        return DEFAULT_DETAIL_STATUS

    except Exception:
        return DEFAULT_DETAIL_STATUS


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


def safe_detail_to_dict(detail: Any, *, include_raw_documents: bool = True) -> dict[str, Any]:
    """Serialisiert Detail-Objekte robust, auch wenn to_dict-Signaturen abweichen."""
    try:
        if detail is None:
            return {}

        if hasattr(detail, "to_dict") and callable(detail.to_dict):
            try:
                data = detail.to_dict(
                    include_raw_documents=include_raw_documents,
                    include_document_data=False,
                )
            except TypeError:
                try:
                    data = detail.to_dict(include_raw_documents=include_raw_documents)
                except TypeError:
                    data = detail.to_dict()

            result = dict(data) if isinstance(data, Mapping) else {"value": data}
            return enrich_summary_with_taxonomy(result)

        if is_dataclass(detail):
            result = asdict(detail)
            return enrich_summary_with_taxonomy(result)

        if isinstance(detail, Mapping):
            return enrich_summary_with_taxonomy(dict(detail))

        return {"value": str(detail)}

    except Exception as exc:
        return {
            "status": "error",
            "error": exception_to_dict(exc),
        }


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


def extract_source_path(read_result: Any = None) -> str | None:
    """Extrahiert Source-/Package-Pfad."""
    return safe_path_str(
        first_non_empty(
            get_attr_or_key(read_result, "package_root"),
            get_attr_or_key(read_result, "source_path"),
        )
    )


def extract_package_root(read_result: Any = None) -> str | None:
    return safe_path_str(get_attr_or_key(read_result, "package_root"))


def extract_relative_package_root(read_result: Any = None) -> str | None:
    return safe_path_str(get_attr_or_key(read_result, "relative_package_root"))


def extract_source_root(read_result: Any = None) -> str | None:
    return safe_path_str(get_attr_or_key(read_result, "source_root"))


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


def extract_discovered_at(read_result: Any = None) -> str | None:
    return safe_str(
        first_non_empty(
            get_attr_or_key(read_result, "discovered_at"),
            deep_get(ensure_dict(get_attr_or_key(read_result, "metadata")), "discovery.discovered_at"),
        ),
        default="",
    ) or None


def extract_document_groups(documents: Mapping[str, Any]) -> dict[str, dict[str, Any]]:
    """Gruppiert Dokumente stabil für Detailantworten."""
    try:
        grouped = group_documents(documents)
    except Exception:
        grouped = {}

        for key, value in normalize_documents(documents).items():
            group = "root" if "/" not in key else key.split("/", 1)[0]
            grouped.setdefault(group, {})
            grouped[group][key] = value

    ordered: dict[str, dict[str, Any]] = {}

    for group in DEFAULT_DETAIL_DOCUMENT_GROUP_ORDER:
        if group in grouped:
            ordered[group] = grouped[group]

    for group, values in grouped.items():
        if group not in ordered:
            ordered[group] = values

    return ordered


def normalize_variant_payload(value: Any, *, fallback_id: str = DEFAULT_VARIANT_ID) -> dict[str, Any]:
    """Normalisiert einen Varianten-Payload."""
    try:
        if isinstance(value, Mapping):
            payload = dict(value)
            variant_id = first_non_empty(
                payload.get("variant_id"),
                payload.get("id"),
                payload.get("slug"),
                fallback_id,
            )
        else:
            payload = {}
            variant_id = first_non_empty(
                get_attr_or_key(value, "variant_id"),
                get_attr_or_key(value, "id"),
                value if isinstance(value, str) else None,
                fallback_id,
            )

        normalized_id = normalize_variant_id(variant_id)

        payload.setdefault("variant_id", normalized_id)
        payload.setdefault("id", normalized_id)
        payload.setdefault("label", first_non_empty(payload.get("label"), payload.get("name"), humanize_identifier(normalized_id)))

        return payload

    except Exception:
        normalized_id = normalize_variant_id(fallback_id)
        return {
            "variant_id": normalized_id,
            "id": normalized_id,
            "label": humanize_identifier(normalized_id),
        }


def extract_variant_payloads(documents: Mapping[str, Any]) -> list[dict[str, Any]]:
    """Baut eine robuste Variantenliste für Detailantworten."""
    normalized_documents = normalize_documents(documents)
    variants: list[dict[str, Any]] = []

    try:
        extracted = extract_variants_from_documents(normalized_documents)

        for variant in extracted:
            if hasattr(variant, "to_dict") and callable(variant.to_dict):
                try:
                    raw = variant.to_dict(include_data=True)
                except TypeError:
                    raw = variant.to_dict()
                variants.append(normalize_variant_payload(raw))
            else:
                variants.append(normalize_variant_payload(variant))

    except Exception:
        pass

    variants_index = get_document_dict(normalized_documents, "variants/index.json")
    default_variant = get_document_dict(normalized_documents, "variants/default.json")

    raw_variants = first_non_empty(
        deep_get(variants_index, "variants"),
        deep_get(variants_index, "variant_ids"),
        default=None,
    )

    if raw_variants and not variants:
        if isinstance(raw_variants, Mapping):
            for key, value in raw_variants.items():
                payload = dict(value) if isinstance(value, Mapping) else {}
                payload.setdefault("variant_id", key)
                variants.append(normalize_variant_payload(payload, fallback_id=key))

        elif isinstance(raw_variants, Iterable) and not isinstance(raw_variants, (str, bytes)):
            for value in raw_variants:
                variants.append(normalize_variant_payload(value))

        else:
            variants.append(normalize_variant_payload(raw_variants))

    if not variants and default_variant:
        variants.append(
            normalize_variant_payload(
                {
                    **default_variant,
                    "variant_id": first_non_empty(
                        deep_get(default_variant, "variant_id"),
                        deep_get(default_variant, "id"),
                        deep_get(variants_index, "default_variant_id"),
                        deep_get(variants_index, "default"),
                        DEFAULT_VARIANT_ID,
                    ),
                    "is_default": True,
                    "data": default_variant,
                }
            )
        )

    if not variants:
        variants.append(
            normalize_variant_payload(
                {
                    "variant_id": DEFAULT_VARIANT_ID,
                    "is_default": True,
                }
            )
        )

    deduped: list[dict[str, Any]] = []
    seen: set[str] = set()

    for variant in variants:
        variant_id = normalize_variant_id(variant.get("variant_id") or variant.get("id"))
        if not variant_id or variant_id in seen:
            continue
        seen.add(variant_id)
        variant["variant_id"] = variant_id
        variant["id"] = variant_id
        deduped.append(variant)

    return deduped


def extract_module_payloads(documents: Mapping[str, Any]) -> list[dict[str, Any]]:
    """Baut eine robuste Modulliste für Detailantworten."""
    modules: list[dict[str, Any]] = []
    normalized_documents = normalize_documents(documents)

    try:
        extracted = extract_modules_from_documents(normalized_documents)

        for module in extracted:
            if hasattr(module, "to_dict") and callable(module.to_dict):
                modules.append(module.to_dict())
            elif isinstance(module, Mapping):
                modules.append(dict(module))
            else:
                modules.append(
                    {
                        "module_name": safe_str(get_attr_or_key(module, "module_name"), default="unknown"),
                        "active": safe_bool(get_attr_or_key(module, "active"), default=False),
                    }
                )

    except Exception:
        modules = []

    if modules:
        return modules

    modules_doc = get_document_dict(normalized_documents, "vplib.modules.json")

    active_modules = first_non_empty(
        deep_get(modules_doc, "active_modules"),
        deep_get(modules_doc, "modules"),
        deep_get(modules_doc, "enabled_modules"),
        default=[],
    )

    if isinstance(active_modules, Mapping):
        for module_name, data in active_modules.items():
            modules.append(
                {
                    "module_name": safe_str(module_name, default="unknown"),
                    "active": True,
                    "data": json_safe(data),
                }
            )

    elif isinstance(active_modules, Iterable) and not isinstance(active_modules, (str, bytes)):
        for module_name in active_modules:
            modules.append(
                {
                    "module_name": safe_str(module_name, default="unknown"),
                    "active": True,
                }
            )

    return modules


def extract_fingerprint_payload(fingerprint_result: Any = None, read_result: Any = None) -> dict[str, Any]:
    """Extrahiert Fingerprint-Informationen."""
    if fingerprint_result is None:
        revision_hash = extract_revision_hash(None, read_result)

        return {
            "revision_hash": revision_hash,
            "available": revision_hash is not None,
        }

    try:
        if hasattr(fingerprint_result, "to_dict") and callable(fingerprint_result.to_dict):
            try:
                payload = fingerprint_result.to_dict(include_files=False)
            except TypeError:
                payload = fingerprint_result.to_dict()
        elif isinstance(fingerprint_result, Mapping):
            payload = dict(fingerprint_result)
        else:
            payload = {
                "revision_hash": get_attr_or_key(fingerprint_result, "revision_hash"),
                "algorithm": get_attr_or_key(fingerprint_result, "algorithm"),
                "status": get_attr_or_key(fingerprint_result, "status"),
            }

        payload = ensure_dict(payload)
        payload.setdefault("revision_hash", extract_revision_hash(fingerprint_result, read_result))
        payload.setdefault("available", bool(payload.get("revision_hash")))
        return json_safe(payload)

    except Exception as exc:
        return {
            "available": False,
            "error": exception_to_dict(exc),
        }


def extract_validation_payload(validation_result: Any = None) -> dict[str, Any]:
    """Extrahiert Validierungsinformationen."""
    summary = validation_result_to_item_validation_summary(validation_result)

    try:
        if hasattr(validation_result, "to_dict") and callable(validation_result.to_dict):
            raw = validation_result.to_dict()
        elif isinstance(validation_result, Mapping):
            raw = dict(validation_result)
        else:
            raw = None

        return {
            "valid": summary.valid,
            "warning_count": summary.warning_count,
            "error_count": summary.error_count,
            "fatal_count": summary.fatal_count,
            "warnings": list(summary.warnings),
            "errors": list(summary.errors),
            "status": validation_result_to_status(validation_result),
            "raw": json_safe(raw),
        }

    except Exception as exc:
        return {
            "valid": False,
            "warning_count": 0,
            "error_count": 1,
            "fatal_count": 0,
            "warnings": [],
            "errors": [safe_str(exc, default="validation serialization failed")],
            "status": "error",
            "raw": None,
        }


def extract_package_payload(documents: Mapping[str, Any]) -> dict[str, Any]:
    """Baut Package-Wurzelinformationen."""
    manifest = get_document_dict(documents, "vplib.manifest.json")
    modules = get_document_dict(documents, "vplib.modules.json")

    return {
        "package_id": extract_package_id_from_documents(documents),
        "family_id": extract_family_id_from_documents(documents),
        "object_kind": first_non_empty(
            deep_get(manifest, "object_kind"),
            deep_get(get_document_dict(documents, "family/identity.json"), "object_kind"),
        ),
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


def extract_family_payload(documents: Mapping[str, Any]) -> dict[str, Any]:
    """Baut Family-Informationen."""
    return {
        "identity": json_safe(get_document_dict(documents, "family/identity.json")),
        "classification": json_safe(get_document_dict(documents, "family/classification.json")),
        "lifecycle": json_safe(get_document_dict(documents, "family/lifecycle.json")),
        "aliases": json_safe(get_document_dict(documents, "family/aliases.json")),
        "metadata": json_safe(get_document_dict(documents, "family/metadata.json")),
    }


def extract_profile_payloads(documents: Mapping[str, Any]) -> dict[str, Any]:
    """Baut technische Profilgruppen."""
    grouped = extract_document_groups(documents)

    return {
        "editor": json_safe(grouped.get("editor", {})),
        "render": json_safe(grouped.get("render", {})),
        "physical": json_safe(grouped.get("physical", {})),
        "material": json_safe(grouped.get("material", {})),
        "calculation": json_safe(grouped.get("calculation", {})),
        "manufacturer": json_safe(grouped.get("manufacturer", {})),
        "analysis": json_safe(grouped.get("analysis", {})),
        "dynamic": json_safe(grouped.get("dynamic", {})),
    }


# ---------------------------------------------------------------------------
# Builder options / result
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class BlockDetailBuilderOptions:
    """Optionen für den Detail Builder."""

    include_raw_documents: bool = True
    include_document_groups: bool = True
    include_validation_raw: bool = True
    include_fingerprint: bool = True
    include_profiles: bool = True
    include_metadata: bool = True
    include_taxonomy: bool = True
    force_taxonomy_reload: bool = False
    fail_on_id_mismatch: bool = False

    def __post_init__(self) -> None:
        object.__setattr__(self, "include_raw_documents", safe_bool(self.include_raw_documents, default=True))
        object.__setattr__(self, "include_document_groups", safe_bool(self.include_document_groups, default=True))
        object.__setattr__(self, "include_validation_raw", safe_bool(self.include_validation_raw, default=True))
        object.__setattr__(self, "include_fingerprint", safe_bool(self.include_fingerprint, default=True))
        object.__setattr__(self, "include_profiles", safe_bool(self.include_profiles, default=True))
        object.__setattr__(self, "include_metadata", safe_bool(self.include_metadata, default=True))
        object.__setattr__(self, "include_taxonomy", safe_bool(self.include_taxonomy, default=True))
        object.__setattr__(self, "force_taxonomy_reload", safe_bool(self.force_taxonomy_reload, default=False))
        object.__setattr__(self, "fail_on_id_mismatch", safe_bool(self.fail_on_id_mismatch, default=False))

    def to_dict(self) -> dict[str, Any]:
        return {
            "include_raw_documents": self.include_raw_documents,
            "include_document_groups": self.include_document_groups,
            "include_validation_raw": self.include_validation_raw,
            "include_fingerprint": self.include_fingerprint,
            "include_profiles": self.include_profiles,
            "include_metadata": self.include_metadata,
            "include_taxonomy": self.include_taxonomy,
            "force_taxonomy_reload": self.force_taxonomy_reload,
            "fail_on_id_mismatch": self.fail_on_id_mismatch,
        }


def coerce_detail_options(
    value: BlockDetailBuilderOptions | Mapping[str, Any] | None = None,
) -> BlockDetailBuilderOptions:
    """Normalisiert optionale Detail-Options."""
    if isinstance(value, BlockDetailBuilderOptions):
        return value

    if value is None:
        return BlockDetailBuilderOptions()

    try:
        data = ensure_dict(value)

        if not data:
            return BlockDetailBuilderOptions()

        allowed = {
            "include_raw_documents",
            "include_document_groups",
            "include_validation_raw",
            "include_fingerprint",
            "include_profiles",
            "include_metadata",
            "include_taxonomy",
            "force_taxonomy_reload",
            "fail_on_id_mismatch",
        }

        return BlockDetailBuilderOptions(
            **{key: item for key, item in data.items() if key in allowed}
        )

    except Exception:
        return BlockDetailBuilderOptions()


@dataclass(frozen=True)
class BlockDetailBuildResult:
    """Ergebnis des Detail Builders."""

    ok: bool
    status: str
    item: Any = None
    detail: Any = None
    block_id: str | None = None
    generated_at: str = field(default_factory=utc_now_iso)
    warnings: tuple[str, ...] = field(default_factory=tuple)
    errors: tuple[str, ...] = field(default_factory=tuple)
    options: BlockDetailBuilderOptions = field(default_factory=BlockDetailBuilderOptions)
    metadata: dict[str, Any] = field(default_factory=dict)
    version: str = BLOCK_DETAIL_BUILDER_VERSION

    def __post_init__(self) -> None:
        warnings = tuple(ensure_list_of_strings(self.warnings))
        errors = tuple(ensure_list_of_strings(self.errors))
        status = normalize_detail_status(self.status)

        if not isinstance(self.options, BlockDetailBuilderOptions):
            object.__setattr__(self, "options", BlockDetailBuilderOptions())

        if status == "candidate":
            if errors:
                status = "error"
            elif self.detail is not None:
                status = "valid"
            else:
                status = "not_found"

        object.__setattr__(self, "ok", bool(self.ok and status not in {"error", "not_found"}))
        object.__setattr__(self, "status", status)
        object.__setattr__(self, "block_id", normalize_stable_id(self.block_id) or None)
        object.__setattr__(self, "generated_at", safe_str(self.generated_at, default=utc_now_iso()))
        object.__setattr__(self, "warnings", warnings)
        object.__setattr__(self, "errors", errors)
        object.__setattr__(self, "metadata", ensure_dict(self.metadata))
        object.__setattr__(self, "version", safe_str(self.version, default=BLOCK_DETAIL_BUILDER_VERSION))

    def to_dict(self) -> dict[str, Any]:
        if self.detail is not None:
            item_payload = safe_detail_to_dict(
                self.detail,
                include_raw_documents=self.options.include_raw_documents,
            )
        elif self.item is not None:
            item_payload = safe_detail_to_dict(
                self.item,
                include_raw_documents=self.options.include_raw_documents,
            )
        else:
            item_payload = None

        result: dict[str, Any] = {
            "ok": self.ok,
            "status": self.status,
            "block_id": self.block_id,
            "item": item_payload,
            "generated_at": self.generated_at,
            "warnings": list(self.warnings),
            "errors": list(self.errors),
            "options": self.options.to_dict(),
            "version": self.version,
        }

        if self.options.include_metadata:
            result["metadata"] = json_safe(self.metadata)

        return result

    @classmethod
    def not_found(
        cls,
        block_id: Any,
        *,
        options: BlockDetailBuilderOptions | Mapping[str, Any] | None = None,
    ) -> "BlockDetailBuildResult":
        builder_options = coerce_detail_options(options)
        normalized_id = normalize_stable_id(block_id, fallback=safe_str(block_id, default="unknown"))

        return cls(
            ok=False,
            status="not_found",
            item=None,
            detail=None,
            block_id=normalized_id,
            warnings=(),
            errors=(f"library block not found: {normalized_id}",),
            options=builder_options,
            metadata={},
        )

    @classmethod
    def error(
        cls,
        exc: BaseException,
        *,
        block_id: Any = None,
        options: BlockDetailBuilderOptions | Mapping[str, Any] | None = None,
        include_traceback: bool = False,
    ) -> "BlockDetailBuildResult":
        builder_options = coerce_detail_options(options)
        error_data = exception_to_dict(exc, include_traceback=include_traceback)
        normalized_id = normalize_stable_id(block_id, fallback=safe_str(block_id, default="unknown")) if block_id is not None else None
        message = safe_str(error_data.get("message") if error_data else None, default="block detail build failed")

        return cls(
            ok=False,
            status="error",
            item=None,
            detail=None,
            block_id=normalized_id,
            warnings=(),
            errors=(message,),
            options=builder_options,
            metadata={"exception": error_data},
        )


# ---------------------------------------------------------------------------
# Main builder
# ---------------------------------------------------------------------------

def build_library_item_detail_if_possible(
    *,
    item: Any,
    documents: Mapping[str, Any],
    validation_summary: LibraryItemValidationSummary,
    read_result: Any = None,
    options: BlockDetailBuilderOptions,
) -> Any | None:
    """Baut LibraryItemDetail, falls die Domain-Klasse verfügbar und kompatibel ist."""
    if LibraryItemDetail is None:
        return None

    if not hasattr(LibraryItemDetail, "from_item_and_documents"):
        return None

    try:
        return LibraryItemDetail.from_item_and_documents(
            item,
            documents,
            validation=validation_summary,
            source_root=extract_source_root(read_result),
            include_raw_documents=options.include_raw_documents,
        )
    except TypeError:
        try:
            return LibraryItemDetail.from_item_and_documents(
                item,
                documents,
                validation=validation_summary,
                source_root=extract_source_root(read_result),
            )
        except TypeError:
            try:
                return LibraryItemDetail.from_item_and_documents(
                    item,
                    documents,
                )
            except Exception:
                return None
        except Exception:
            return None
    except Exception:
        return None


def build_detail_fallback_dict(
    *,
    item: Any,
    documents: Mapping[str, Any],
    read_result: Any = None,
    validation_result: Any = None,
    fingerprint_result: Any = None,
    options: BlockDetailBuilderOptions,
) -> dict[str, Any]:
    """Baut eine Detailantwort als Dict, falls LibraryItemDetail nicht verfügbar ist."""
    summary = safe_detail_to_dict(item, include_raw_documents=False)

    family_id = normalize_stable_id(
        first_non_empty(
            get_attr_or_key(item, "family_id"),
            summary.get("family_id") if isinstance(summary, Mapping) else None,
            extract_family_id_from_documents(documents),
        )
    )
    item_id = normalize_stable_id(
        first_non_empty(
            get_attr_or_key(item, "id"),
            summary.get("id") if isinstance(summary, Mapping) else None,
            family_id,
        ),
        fallback=family_id,
    )

    validation_payload = extract_validation_payload(validation_result)
    fingerprint_payload = extract_fingerprint_payload(fingerprint_result, read_result)
    variants = extract_variant_payloads(documents)
    modules = extract_module_payloads(documents)
    normalized_documents = normalize_documents(documents)
    taxonomy_payload = build_detail_taxonomy_payload(
        read_result=read_result,
        validation_result=validation_result,
        documents=normalized_documents,
        item=item,
    )
    classification_payload = build_classification_payload(
        documents=normalized_documents,
        taxonomy=taxonomy_payload,
    )

    payload: dict[str, Any] = {
        "id": item_id,
        "family_id": family_id,
        "status": "valid" if validation_payload.get("valid") else "invalid",
        "summary": json_safe(summary),
        "taxonomy": taxonomy_payload,
        "classification": classification_payload,
        "package": extract_package_payload(normalized_documents),
        "family": extract_family_payload(normalized_documents),
        "variants": variants,
        "variant_count": len(variants),
        "modules": modules,
        "module_count": len(modules),
        "validation": validation_payload,
        "source": LibrarySourceDetail(
            source_path=taxonomy_payload.get("source_path") or extract_source_path(read_result),
            package_root=extract_package_root(read_result),
            relative_package_root=extract_relative_package_root(read_result),
            source_root=extract_source_root(read_result),
            discovered_at=extract_discovered_at(read_result),
            scanned_at=extract_scanned_at(read_result),
            revision_hash=fingerprint_payload.get("revision_hash"),
        ).to_dict(),
        "generated_at": utc_now_iso(),
    }

    if options.include_profiles:
        payload["profiles"] = extract_profile_payloads(normalized_documents)

    if options.include_document_groups:
        payload["document_groups"] = json_safe(extract_document_groups(normalized_documents))
        payload["document_keys"] = sorted(normalized_documents.keys())
        payload["document_count"] = len(normalized_documents)

    if options.include_fingerprint:
        payload["fingerprint"] = fingerprint_payload

    if options.include_raw_documents:
        payload["raw_documents"] = json_safe(normalized_documents)

    return json_safe(payload)


def build_block_detail_from_parts(
    *,
    read_result: Any = None,
    validation_result: Any = None,
    fingerprint_result: Any = None,
    item: Any = None,
    documents: Mapping[str, Any] | None = None,
    block_id: Any = None,
    options: BlockDetailBuilderOptions | Mapping[str, Any] | None = None,
) -> BlockDetailBuildResult:
    """Baut ein vollständiges Detailmodell aus Pipeline-Ergebnissen."""
    builder_options = coerce_detail_options(options)

    try:
        if builder_options.force_taxonomy_reload:
            try:
                load_taxonomy_payload(force_reload=True)
            except Exception:
                pass

        normalized_documents = normalize_documents(
            documents if documents is not None else extract_documents_from_any(read_result)
        )

        if not normalized_documents and item is None:
            raise ValueError("no package documents or item available for detail build")

        built_item = item

        if built_item is None:
            built_item = build_library_item_from_parts(
                read_result=read_result,
                validation_result=validation_result,
                fingerprint_result=fingerprint_result,
                documents=normalized_documents,
            )

        requested_id = normalize_stable_id(block_id) if block_id is not None else None
        built_item_id = normalize_stable_id(
            first_non_empty(
                get_attr_or_key(built_item, "id"),
                get_attr_or_key(built_item, "family_id"),
                extract_family_id_from_documents(normalized_documents),
            )
        )

        if requested_id and built_item_id and requested_id != built_item_id:
            message = f"requested block_id does not match package item id: {requested_id} != {built_item_id}"

            if builder_options.fail_on_id_mismatch:
                raise ValueError(message)

            warnings = (message,)
        else:
            warnings = ()

        validation_summary = validation_result_to_item_validation_summary(validation_result)
        revision_hash = extract_revision_hash(fingerprint_result, read_result)

        detail = build_library_item_detail_if_possible(
            item=built_item,
            documents=normalized_documents,
            validation_summary=validation_summary,
            read_result=read_result,
            options=builder_options,
        )

        if detail is None:
            detail = build_detail_fallback_dict(
                item=built_item,
                documents=normalized_documents,
                read_result=read_result,
                validation_result=validation_result,
                fingerprint_result=fingerprint_result,
                options=builder_options,
            )
        elif builder_options.include_taxonomy:
            detail_dict = safe_detail_to_dict(detail, include_raw_documents=builder_options.include_raw_documents)
            taxonomy_payload = build_detail_taxonomy_payload(
                read_result=read_result,
                validation_result=validation_result,
                documents=normalized_documents,
                item=built_item,
            )
            detail_dict["taxonomy"] = taxonomy_payload
            detail_dict["classification"] = build_classification_payload(
                documents=normalized_documents,
                taxonomy=taxonomy_payload,
            )
            detail = detail_dict

        taxonomy_payload = build_detail_taxonomy_payload(
            read_result=read_result,
            validation_result=validation_result,
            documents=normalized_documents,
            item=built_item,
        )

        return BlockDetailBuildResult(
            ok=True,
            status="valid" if validation_summary.valid else "invalid",
            item=built_item,
            detail=detail,
            block_id=built_item_id or requested_id,
            warnings=warnings,
            errors=(),
            options=builder_options,
            metadata={
                "fingerprint": extract_fingerprint_payload(fingerprint_result, read_result),
                "revision_hash": revision_hash,
                "validation": extract_validation_payload(validation_result),
                "taxonomy": taxonomy_payload,
                "document_count": len(normalized_documents),
                "imports": get_import_status(),
            },
        )

    except Exception as exc:
        return BlockDetailBuildResult.error(
            exc,
            block_id=block_id,
            options=builder_options,
        )


def build_block_detail_from_read_result(
    read_result: Any,
    *,
    validation_result: Any = None,
    fingerprint_result: Any = None,
    block_id: Any = None,
    options: BlockDetailBuilderOptions | Mapping[str, Any] | None = None,
) -> BlockDetailBuildResult:
    """Convenience-Wrapper für ein einzelnes PackageReadResult."""
    return build_block_detail_from_parts(
        read_result=read_result,
        validation_result=validation_result,
        fingerprint_result=fingerprint_result,
        block_id=block_id,
        options=options,
    )


def find_pipeline_entry_by_block_id(
    block_id: Any,
    *,
    read_results: Iterable[Any],
    validation_results: Iterable[Any] | None = None,
    fingerprint_results: Iterable[Any] | None = None,
    items: Iterable[Any] | None = None,
) -> tuple[Any | None, Any | None, Any | None, Any | None]:
    """
    Findet passende Pipeline-Ergebnisse zu einer stabilen Block-ID.

    Rückgabe:
        (read_result, validation_result, fingerprint_result, item)
    """
    normalized_id = normalize_stable_id(block_id)

    if not normalized_id:
        return None, None, None, None

    read_list = list(read_results or ())
    validation_list = list(validation_results or ())
    fingerprint_list = list(fingerprint_results or ())
    item_list = list(items or ())

    max_len = max(
        len(read_list),
        len(validation_list),
        len(fingerprint_list),
        len(item_list),
    )

    for index in range(max_len):
        read_result = read_list[index] if index < len(read_list) else None
        validation_result = validation_list[index] if index < len(validation_list) else None
        fingerprint_result = fingerprint_list[index] if index < len(fingerprint_list) else None
        item = item_list[index] if index < len(item_list) else None

        candidate_ids = {
            normalize_stable_id(get_attr_or_key(item, "id")),
            normalize_stable_id(get_attr_or_key(item, "family_id")),
            normalize_stable_id(get_attr_or_key(item, "package_id")),
            normalize_stable_id(get_attr_or_key(read_result, "item_id")),
            normalize_stable_id(get_attr_or_key(read_result, "family_id")),
            normalize_stable_id(get_attr_or_key(read_result, "package_id")),
            normalize_stable_id(get_attr_or_key(validation_result, "item_id")),
            normalize_stable_id(get_attr_or_key(validation_result, "family_id")),
            normalize_stable_id(get_attr_or_key(validation_result, "package_id")),
        }

        documents = extract_documents_from_any(read_result)

        if documents:
            candidate_ids.add(normalize_stable_id(extract_family_id_from_documents(documents)))
            candidate_ids.add(normalize_stable_id(extract_package_id_from_documents(documents)))

        if normalized_id in {candidate_id for candidate_id in candidate_ids if candidate_id}:
            return read_result, validation_result, fingerprint_result, item

    return None, None, None, None


def build_block_detail_result_by_id(
    block_id: Any,
    *,
    read_results: Iterable[Any],
    validation_results: Iterable[Any] | None = None,
    fingerprint_results: Iterable[Any] | None = None,
    items: Iterable[Any] | None = None,
    options: BlockDetailBuilderOptions | Mapping[str, Any] | None = None,
) -> BlockDetailBuildResult:
    """Baut Detailmodell aus parallelen Pipeline-Listen anhand einer Block-ID."""
    builder_options = coerce_detail_options(options)
    normalized_id = normalize_stable_id(block_id, fallback=safe_str(block_id, default="unknown"))

    try:
        read_result, validation_result, fingerprint_result, item = find_pipeline_entry_by_block_id(
            normalized_id,
            read_results=read_results,
            validation_results=validation_results,
            fingerprint_results=fingerprint_results,
            items=items,
        )

        if read_result is None and item is None:
            return BlockDetailBuildResult.not_found(
                normalized_id,
                options=builder_options,
            )

        return build_block_detail_from_parts(
            read_result=read_result,
            validation_result=validation_result,
            fingerprint_result=fingerprint_result,
            item=item,
            block_id=normalized_id,
            options=builder_options,
        )

    except Exception as exc:
        return BlockDetailBuildResult.error(
            exc,
            block_id=normalized_id,
            options=builder_options,
        )


# ---------------------------------------------------------------------------
# Response helpers
# ---------------------------------------------------------------------------

def build_block_detail_response_from_parts(
    *,
    read_result: Any = None,
    validation_result: Any = None,
    fingerprint_result: Any = None,
    item: Any = None,
    documents: Mapping[str, Any] | None = None,
    block_id: Any = None,
    options: BlockDetailBuilderOptions | Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    """Baut direkt eine API-Antwort aus Pipeline-Teilen."""
    result = build_block_detail_from_parts(
        read_result=read_result,
        validation_result=validation_result,
        fingerprint_result=fingerprint_result,
        item=item,
        documents=documents,
        block_id=block_id,
        options=options,
    )

    return result.to_dict()


def build_block_detail_response_by_id(
    block_id: Any,
    *,
    read_results: Iterable[Any],
    validation_results: Iterable[Any] | None = None,
    fingerprint_results: Iterable[Any] | None = None,
    items: Iterable[Any] | None = None,
    options: BlockDetailBuilderOptions | Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    """Baut direkt eine API-Antwort anhand einer Block-ID."""
    result = build_block_detail_result_by_id(
        block_id,
        read_results=read_results,
        validation_results=validation_results,
        fingerprint_results=fingerprint_results,
        items=items,
        options=options,
    )

    return result.to_dict()


def build_block_variants_response_from_parts(
    *,
    read_result: Any = None,
    documents: Mapping[str, Any] | None = None,
    block_id: Any = None,
) -> dict[str, Any]:
    """
    Baut eine kompakte Variantenantwort für:

        GET /api/v1/vplib/library/blocks/<block_id>/variants
    """
    try:
        normalized_documents = normalize_documents(
            documents if documents is not None else extract_documents_from_any(read_result)
        )

        family_id = normalize_stable_id(
            first_non_empty(
                block_id,
                get_attr_or_key(read_result, "family_id"),
                extract_family_id_from_documents(normalized_documents),
            ),
            fallback=safe_str(block_id, default="unknown"),
        )

        taxonomy_payload = build_detail_taxonomy_payload(
            read_result=read_result,
            documents=normalized_documents,
        )
        variants = extract_variant_payloads(normalized_documents)

        return {
            "ok": True,
            "status": "ok" if variants else "empty",
            "block_id": family_id,
            "taxonomy": taxonomy_payload,
            "count": len(variants),
            "variants": json_safe(variants),
        }

    except Exception as exc:
        return {
            "ok": False,
            "status": "error",
            "block_id": normalize_stable_id(block_id, fallback=safe_str(block_id, default="unknown")),
            "taxonomy": {},
            "count": 0,
            "variants": [],
            "errors": [safe_str(exc, default="could not build variants response")],
            "error": exception_to_dict(exc),
        }


# ---------------------------------------------------------------------------
# Health
# ---------------------------------------------------------------------------

def get_import_status() -> dict[str, Any]:
    """Liefert Importstatus optionaler Abhängigkeiten."""
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
        "summary": {
            "ok": _SUMMARY_IMPORT_ERROR is None,
            "error": exception_to_dict(_SUMMARY_IMPORT_ERROR),
        },
        "taxonomy": {
            "ok": _TAXONOMY_IMPORT_ERROR is None,
            "error": exception_to_dict(_TAXONOMY_IMPORT_ERROR),
        },
    }


def get_block_detail_builder_health() -> dict[str, Any]:
    """Health-Status des Block Detail Builders."""
    warnings: list[str] = []
    errors: list[str] = []

    imports = get_import_status()

    for name, status in imports.items():
        if not status.get("ok"):
            warnings.append(f"{name} import failed; fallback helpers may be active")

    try:
        options = BlockDetailBuilderOptions()
        options_dict = options.to_dict()
    except Exception as exc:
        options_dict = {}
        errors.append(f"could not build detail options: {exc}")

    try:
        safe_int_self_test = safe_int("999999", default=500, minimum=1, maximum=5000)
        if safe_int_self_test != 5000:
            errors.append(f"safe_int maximum self-test failed: expected 5000, got {safe_int_self_test}")
    except Exception as exc:
        errors.append(f"safe_int maximum self-test failed: {exc}")

    try:
        empty_variants = build_block_variants_response_from_parts(
            documents={"variants/default.json": {"variant_id": "default"}},
            block_id="vp.test.block",
        )
        self_test_ok = bool(empty_variants.get("ok")) and empty_variants.get("count") == 1
    except Exception as exc:
        self_test_ok = False
        errors.append(f"detail self-test failed: {exc}")

    try:
        taxonomy_health = get_taxonomy_health_payload()
        if not taxonomy_health.get("payload_ok"):
            warnings.append("taxonomy payload is unavailable or not healthy")
    except Exception as exc:
        taxonomy_health = {
            "available": taxonomy_available(),
            "payload_ok": False,
            "error": exception_to_dict(exc),
        }
        warnings.append("taxonomy health check failed")

    healthy = len(errors) == 0

    return {
        "ok": healthy,
        "healthy": healthy,
        "component": BLOCK_DETAIL_BUILDER_COMPONENT,
        "version": BLOCK_DETAIL_BUILDER_VERSION,
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


def assert_block_detail_builder_ready() -> None:
    """Wirft RuntimeError, wenn der Detail Builder nicht bereit ist."""
    health = get_block_detail_builder_health()

    if health.get("healthy"):
        return

    raise RuntimeError(
        f"block detail builder is not ready: errors={health.get('errors')}"
    )


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

__all__: Final[tuple[str, ...]] = (
    "BLOCK_DETAIL_BUILDER_VERSION",
    "BLOCK_DETAIL_BUILDER_COMPONENT",
    "DEFAULT_DETAIL_STATUS",
    "DETAIL_STATUS_VALUES",
    "DEFAULT_DETAIL_DOCUMENT_GROUP_ORDER",
    "BlockDetailBuilderOptions",
    "BlockDetailBuildResult",
    "utc_now_iso",
    "exception_to_dict",
    "json_safe",
    "taxonomy_available",
    "get_taxonomy_health_payload",
    "build_detail_taxonomy_payload",
    "build_classification_payload",
    "normalize_detail_status",
    "get_attr_or_key",
    "safe_detail_to_dict",
    "extract_documents_from_any",
    "extract_source_path",
    "extract_package_root",
    "extract_relative_package_root",
    "extract_source_root",
    "extract_scanned_at",
    "extract_discovered_at",
    "extract_document_groups",
    "normalize_variant_payload",
    "extract_variant_payloads",
    "extract_module_payloads",
    "extract_fingerprint_payload",
    "extract_validation_payload",
    "extract_package_payload",
    "extract_family_payload",
    "extract_profile_payloads",
    "coerce_detail_options",
    "build_library_item_detail_if_possible",
    "build_detail_fallback_dict",
    "build_block_detail_from_parts",
    "build_block_detail_from_read_result",
    "find_pipeline_entry_by_block_id",
    "build_block_detail_result_by_id",
    "build_block_detail_response_from_parts",
    "build_block_detail_response_by_id",
    "build_block_variants_response_from_parts",
    "get_import_status",
    "get_block_detail_builder_health",
    "assert_block_detail_builder_ready",
)