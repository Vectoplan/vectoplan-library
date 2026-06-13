# services/vectoplan-library/src/library/domain/scan_result.py
"""
Domain-Modelle für Scan-Ergebnisse der Creative-Library-Schicht.

Diese Datei beschreibt die API- und servicefähigen Ergebnisstrukturen für:

- Source-Root-Scans
- erkannte VPLIB-Kandidaten
- gültige Blöcke/Objekte
- ungültige Pakete
- doppelte IDs
- Scan-Fehler
- spätere Route-Antworten

Geplante Hauptverwendung:

    GET /api/v1/vplib/library/scan
    GET /api/v1/vplib/library/blocks

Diese Datei bleibt unabhängig von Flask, Datenbank, konkreter Discovery und
konkreter Validierung. Scanner, Validatoren und Routes können dieses Modell
verwenden, ohne voneinander abhängig zu werden.
"""

from __future__ import annotations

import time
import traceback
from dataclasses import asdict, dataclass, field, is_dataclass, replace
from datetime import datetime, timezone
from enum import Enum
from pathlib import Path
from typing import Any, Final, Iterable, Mapping


# ---------------------------------------------------------------------------
# Optional dependency on library_item
# ---------------------------------------------------------------------------

_LIBRARY_ITEM_IMPORT_ERROR: BaseException | None = None

try:
    from library.domain.library_item import (
        LibraryItem,
        LibraryItemValidationSummary,
        ensure_dict,
        ensure_list_of_strings,
        exception_to_dict,
        filter_valid_library_items,
        index_library_items_by_id,
        library_items_to_summary_dicts,
        normalize_stable_id,
        safe_bool,
        safe_int,
        safe_path_str,
        safe_str,
    )
except Exception as import_exc:  # pragma: no cover - defensive fallback
    _LIBRARY_ITEM_IMPORT_ERROR = import_exc

    LibraryItem = None  # type: ignore[assignment]

    def exception_to_dict(
        exc: BaseException,
        *,
        include_traceback: bool = False,
    ) -> dict[str, Any]:
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

    def safe_str(value: Any, *, default: str = "") -> str:
        try:
            if value is None:
                return default

            text = str(value).strip()
            return text if text else default

        except Exception:
            return default

    def safe_int(value: Any, *, default: int = 0, minimum: int | None = None) -> int:
        try:
            number = int(value)
        except Exception:
            number = default

        if minimum is not None:
            number = max(minimum, number)

        return number

    def safe_bool(value: Any, *, default: bool = False) -> bool:
        if isinstance(value, bool):
            return value

        if value is None:
            return default

        try:
            text = str(value).strip().lower()
        except Exception:
            return default

        if text in {"1", "true", "yes", "y", "on", "enabled"}:
            return True

        if text in {"0", "false", "no", "n", "off", "disabled"}:
            return False

        return default

    def safe_path_str(value: Any) -> str | None:
        try:
            if value is None:
                return None

            if isinstance(value, Path):
                return str(value)

            text = str(value).strip()
            return text or None

        except Exception:
            return None

    def ensure_dict(value: Any) -> dict[str, Any]:
        if isinstance(value, Mapping):
            try:
                return dict(value)
            except Exception:
                return {}

        return {}

    def ensure_list_of_strings(value: Any) -> list[str]:
        if value is None:
            return []

        if isinstance(value, str):
            text = value.strip()
            return [text] if text else []

        if isinstance(value, Iterable):
            result: list[str] = []
            for item in value:
                text = safe_str(item, default="")
                if text:
                    result.append(text)
            return result

        text = safe_str(value, default="")
        return [text] if text else []

    def normalize_stable_id(value: Any, *, fallback: str | None = None) -> str:
        text = safe_str(value, default="").lower()
        text = text.replace("/", ".").replace("\\", ".").replace(" ", "_")
        text = "".join(ch for ch in text if ch.isalnum() or ch in "._:-")
        text = text.strip("._:-")

        if text:
            return text

        if fallback is not None:
            return normalize_stable_id(fallback)

        return ""

    @dataclass(frozen=True)
    class LibraryItemValidationSummary:  # type: ignore[no-redef]
        valid: bool = False
        warning_count: int = 0
        error_count: int = 0
        fatal_count: int = 0
        warnings: tuple[str, ...] = field(default_factory=tuple)
        errors: tuple[str, ...] = field(default_factory=tuple)

        def to_dict(self) -> dict[str, Any]:
            return {
                "valid": self.valid,
                "warning_count": self.warning_count,
                "error_count": self.error_count,
                "fatal_count": self.fatal_count,
                "warnings": list(self.warnings),
                "errors": list(self.errors),
            }

    def library_items_to_summary_dicts(
        items: Iterable[Any],
        *,
        sort: bool = True,
    ) -> list[dict[str, Any]]:
        result: list[dict[str, Any]] = []

        for item in items:
            if hasattr(item, "to_summary_dict") and callable(item.to_summary_dict):
                result.append(item.to_summary_dict())
            elif hasattr(item, "to_dict") and callable(item.to_dict):
                result.append(item.to_dict())
            elif isinstance(item, Mapping):
                result.append(dict(item))
            else:
                result.append({"value": str(item)})

        return result

    def filter_valid_library_items(
        items: Iterable[Any],
        *,
        enabled_only: bool = True,
    ) -> list[Any]:
        result: list[Any] = []

        for item in items:
            try:
                if enabled_only and hasattr(item, "enabled") and not item.enabled:
                    continue

                if getattr(item, "is_valid", False):
                    result.append(item)

            except Exception:
                continue

        return result

    def index_library_items_by_id(
        items: Iterable[Any],
    ) -> tuple[dict[str, Any], list[Any]]:
        items_by_id: dict[str, Any] = {}
        duplicates: list[Any] = []

        for item in items:
            item_id = safe_str(getattr(item, "id", None), default="")

            if not item_id:
                continue

            if item_id in items_by_id:
                duplicates.append(item)
                continue

            items_by_id[item_id] = item

        return items_by_id, duplicates


# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

LIBRARY_SCAN_RESULT_MODEL_VERSION: Final[str] = "0.1.0"

DEFAULT_SCAN_STATUS: Final[str] = "unknown"
DEFAULT_SCAN_MODE: Final[str] = "filesystem"
DEFAULT_CANDIDATE_STATUS: Final[str] = "candidate"

VALID_SCAN_STATUSES: Final[tuple[str, ...]] = (
    "unknown",
    "ok",
    "partial",
    "empty",
    "invalid",
    "error",
)

VALID_CANDIDATE_STATUSES: Final[tuple[str, ...]] = (
    "unknown",
    "candidate",
    "valid",
    "invalid",
    "duplicate",
    "skipped",
    "error",
)

TERMINAL_ERROR_STATUSES: Final[tuple[str, ...]] = (
    "invalid",
    "duplicate",
    "error",
)


# ---------------------------------------------------------------------------
# Enums
# ---------------------------------------------------------------------------

class LibraryScanStatus(str, Enum):
    UNKNOWN = "unknown"
    OK = "ok"
    PARTIAL = "partial"
    EMPTY = "empty"
    INVALID = "invalid"
    ERROR = "error"


class LibraryScanCandidateStatus(str, Enum):
    UNKNOWN = "unknown"
    CANDIDATE = "candidate"
    VALID = "valid"
    INVALID = "invalid"
    DUPLICATE = "duplicate"
    SKIPPED = "skipped"
    ERROR = "error"


# ---------------------------------------------------------------------------
# Generic helpers
# ---------------------------------------------------------------------------

def utc_now_iso() -> str:
    """
    UTC-Zeit im ISO-Format.
    """

    return datetime.now(timezone.utc).isoformat()


def monotonic_ms() -> int:
    """
    Monotone Zeit in Millisekunden für Dauerberechnung.
    """

    try:
        return int(time.monotonic() * 1000)
    except Exception:
        return 0


def normalize_status(value: Any, *, allowed: tuple[str, ...], default: str) -> str:
    """
    Normalisiert einen Status gegen erlaubte Werte.
    """

    text = safe_str(value, default=default).lower()

    if text in allowed:
        return text

    return default


def normalize_candidate_status(value: Any) -> str:
    return normalize_status(
        value,
        allowed=VALID_CANDIDATE_STATUSES,
        default=DEFAULT_CANDIDATE_STATUS,
    )


def normalize_scan_status(value: Any) -> str:
    return normalize_status(
        value,
        allowed=VALID_SCAN_STATUSES,
        default=DEFAULT_SCAN_STATUS,
    )


def json_safe(value: Any) -> Any:
    """
    Wandelt Werte defensiv in JSON-kompatible Strukturen um.
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


def tuple_of_strings(value: Any) -> tuple[str, ...]:
    """
    Normalisiert Werte zu tuple[str, ...].
    """

    return tuple(ensure_list_of_strings(value))


def tuple_of_dicts(value: Any) -> tuple[dict[str, Any], ...]:
    """
    Normalisiert Werte zu tuple[dict[str, Any], ...].
    """

    if value is None:
        return ()

    if isinstance(value, Mapping):
        return (dict(value),)

    if isinstance(value, Iterable) and not isinstance(value, str):
        result: list[dict[str, Any]] = []

        for item in value:
            if isinstance(item, Mapping):
                result.append(dict(item))
            elif hasattr(item, "to_dict") and callable(item.to_dict):
                result.append(ensure_dict(item.to_dict()))
            else:
                result.append({"value": str(item)})

        return tuple(result)

    return ({"value": str(value)},)


def item_id_from_any(value: Any) -> str | None:
    """
    Extrahiert eine stabile Item-ID aus LibraryItem, Mapping oder String.
    """

    try:
        if value is None:
            return None

        if isinstance(value, str):
            normalized = normalize_stable_id(value)
            return normalized or None

        if isinstance(value, Mapping):
            candidate = (
                value.get("id")
                or value.get("family_id")
                or value.get("package_id")
            )
            normalized = normalize_stable_id(candidate)
            return normalized or None

        candidate = (
            getattr(value, "id", None)
            or getattr(value, "family_id", None)
            or getattr(value, "package_id", None)
        )
        normalized = normalize_stable_id(candidate)
        return normalized or None

    except Exception:
        return None


def item_to_summary_dict(value: Any) -> dict[str, Any]:
    """
    Serialisiert ein LibraryItem oder Mapping zu einer kompakten Summary.
    """

    try:
        if value is None:
            return {}

        if hasattr(value, "to_summary_dict") and callable(value.to_summary_dict):
            return ensure_dict(value.to_summary_dict())

        if hasattr(value, "to_dict") and callable(value.to_dict):
            return ensure_dict(value.to_dict())

        if isinstance(value, Mapping):
            return dict(value)

        return {"value": str(value)}

    except Exception as exc:
        return {
            "status": "error",
            "error": exception_to_dict(exc),
        }


def validation_summary_from_any(value: Any) -> LibraryItemValidationSummary:
    """
    Normalisiert unterschiedliche Validierungsformen zu
    LibraryItemValidationSummary.
    """

    if isinstance(value, LibraryItemValidationSummary):
        return value

    if isinstance(value, Mapping):
        warnings = tuple_of_strings(
            value.get("warnings")
            or value.get("warning_messages")
            or []
        )
        errors = tuple_of_strings(
            value.get("errors")
            or value.get("error_messages")
            or []
        )

        valid = safe_bool(
            value.get("valid")
            if "valid" in value
            else value.get("ok"),
            default=False,
        )

        return LibraryItemValidationSummary(
            valid=valid,
            warning_count=safe_int(
                value.get("warning_count"),
                default=len(warnings),
                minimum=0,
            ),
            error_count=safe_int(
                value.get("error_count"),
                default=len(errors),
                minimum=0,
            ),
            fatal_count=safe_int(value.get("fatal_count"), default=0, minimum=0),
            warnings=warnings,
            errors=errors,
        )

    return LibraryItemValidationSummary()


def derive_candidate_status(
    *,
    valid: bool,
    duplicate: bool = False,
    skipped: bool = False,
    errors: Iterable[Any] | None = None,
    explicit_status: Any = None,
) -> str:
    """
    Leitet einen Kandidatenstatus robust ab.
    """

    explicit = safe_str(explicit_status, default="")

    if explicit:
        normalized = normalize_candidate_status(explicit)

        if normalized != DEFAULT_CANDIDATE_STATUS or explicit == DEFAULT_CANDIDATE_STATUS:
            return normalized

    if duplicate:
        return LibraryScanCandidateStatus.DUPLICATE.value

    if skipped:
        return LibraryScanCandidateStatus.SKIPPED.value

    error_list = ensure_list_of_strings(errors)

    if error_list:
        return LibraryScanCandidateStatus.INVALID.value

    if valid:
        return LibraryScanCandidateStatus.VALID.value

    return LibraryScanCandidateStatus.CANDIDATE.value


def calculate_duration_ms(
    *,
    started_monotonic_ms: int | None = None,
    finished_monotonic_ms: int | None = None,
    fallback: int = 0,
) -> int:
    """
    Berechnet eine robuste Dauer in Millisekunden.
    """

    try:
        if started_monotonic_ms is None or finished_monotonic_ms is None:
            return fallback

        return max(0, int(finished_monotonic_ms) - int(started_monotonic_ms))

    except Exception:
        return fallback


# ---------------------------------------------------------------------------
# Submodels
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class LibraryScanMessage:
    """
    Einzelne Scan-Meldung.

    Geeignet für Fehler, Warnungen und Hinweise.
    """

    level: str
    message: str
    code: str | None = None
    path: str | None = None
    document_key: str | None = None
    data: dict[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        level = safe_str(self.level, default="info").lower()

        if level not in {"debug", "info", "warning", "error", "fatal"}:
            level = "info"

        object.__setattr__(self, "level", level)
        object.__setattr__(self, "message", safe_str(self.message, default=""))
        object.__setattr__(self, "code", safe_str(self.code, default="") or None)
        object.__setattr__(self, "path", safe_path_str(self.path))
        object.__setattr__(self, "document_key", safe_str(self.document_key, default="") or None)
        object.__setattr__(self, "data", ensure_dict(self.data))

    @classmethod
    def from_raw(
        cls,
        value: Any,
        *,
        level: str = "info",
    ) -> "LibraryScanMessage":
        if isinstance(value, LibraryScanMessage):
            return value

        if isinstance(value, Mapping):
            return cls(
                level=safe_str(value.get("level"), default=level),
                message=safe_str(value.get("message"), default=str(value)),
                code=safe_str(value.get("code"), default="") or None,
                path=safe_path_str(value.get("path")),
                document_key=safe_str(value.get("document_key"), default="") or None,
                data=ensure_dict(value.get("data")),
            )

        return cls(
            level=level,
            message=safe_str(value, default=""),
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "level": self.level,
            "message": self.message,
            "code": self.code,
            "path": self.path,
            "document_key": self.document_key,
            "data": json_safe(self.data),
        }


@dataclass(frozen=True)
class LibraryDuplicateId:
    """
    Beschreibung einer doppelten ID im Scan.

    Für spätere DB-Upserts ist das kritisch, weil `family_id` stabil und
    eindeutig sein muss.
    """

    id: str
    first_path: str | None = None
    duplicate_path: str | None = None
    package_id: str | None = None
    family_id: str | None = None
    message: str = "duplicate library item id"

    def __post_init__(self) -> None:
        normalized_id = normalize_stable_id(self.id, fallback="unknown.duplicate")
        object.__setattr__(self, "id", normalized_id)
        object.__setattr__(self, "first_path", safe_path_str(self.first_path))
        object.__setattr__(self, "duplicate_path", safe_path_str(self.duplicate_path))
        object.__setattr__(self, "package_id", safe_str(self.package_id, default="") or None)
        object.__setattr__(self, "family_id", normalize_stable_id(self.family_id) or None)
        object.__setattr__(self, "message", safe_str(self.message, default="duplicate library item id"))

    @classmethod
    def from_items(
        cls,
        first_item: Any,
        duplicate_item: Any,
    ) -> "LibraryDuplicateId":
        item_id = (
            item_id_from_any(duplicate_item)
            or item_id_from_any(first_item)
            or "unknown.duplicate"
        )

        return cls(
            id=item_id,
            first_path=safe_path_str(getattr(first_item, "package_root", None) or getattr(first_item, "source_path", None)),
            duplicate_path=safe_path_str(getattr(duplicate_item, "package_root", None) or getattr(duplicate_item, "source_path", None)),
            package_id=safe_str(getattr(duplicate_item, "package_id", None), default="") or None,
            family_id=normalize_stable_id(getattr(duplicate_item, "family_id", None)) or None,
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "first_path": self.first_path,
            "duplicate_path": self.duplicate_path,
            "package_id": self.package_id,
            "family_id": self.family_id,
            "message": self.message,
        }


@dataclass(frozen=True)
class LibraryScanCandidate:
    """
    Ein einzelner erkannter möglicher VPLIB-Package-Ordner.
    """

    candidate_id: str
    status: str = DEFAULT_CANDIDATE_STATUS
    valid: bool = False

    package_id: str | None = None
    family_id: str | None = None
    item_id: str | None = None
    label: str | None = None
    object_kind: str | None = None

    source_path: str | None = None
    package_root: str | None = None
    relative_package_root: str | None = None
    manifest_path: str | None = None

    document_count: int = 0
    loaded_document_keys: tuple[str, ...] = field(default_factory=tuple)
    missing_required_files: tuple[str, ...] = field(default_factory=tuple)

    revision_hash: str | None = None
    discovered_at: str | None = None
    scanned_at: str | None = None

    item_summary: dict[str, Any] = field(default_factory=dict)
    validation: LibraryItemValidationSummary = field(default_factory=LibraryItemValidationSummary)

    warnings: tuple[str, ...] = field(default_factory=tuple)
    errors: tuple[str, ...] = field(default_factory=tuple)
    messages: tuple[LibraryScanMessage, ...] = field(default_factory=tuple)

    metadata: dict[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        normalized_candidate_id = normalize_stable_id(
            self.candidate_id,
            fallback=self.item_id or self.family_id or self.package_id or "unknown.candidate",
        )

        normalized_item_id = normalize_stable_id(
            self.item_id,
            fallback=self.family_id or normalized_candidate_id,
        ) or None

        normalized_family_id = normalize_stable_id(
            self.family_id,
            fallback=normalized_item_id or normalized_candidate_id,
        ) or None

        warnings = tuple_of_strings(self.warnings)
        errors = tuple_of_strings(self.errors)

        message_list = normalize_scan_messages(self.messages)

        if warnings:
            message_list.extend(
                LibraryScanMessage(level="warning", message=message)
                for message in warnings
            )

        if errors:
            message_list.extend(
                LibraryScanMessage(level="error", message=message)
                for message in errors
            )

        status = derive_candidate_status(
            valid=self.valid,
            duplicate=False,
            skipped=False,
            errors=errors,
            explicit_status=self.status,
        )

        object.__setattr__(self, "candidate_id", normalized_candidate_id)
        object.__setattr__(self, "status", status)
        object.__setattr__(self, "valid", bool(self.valid and status == "valid"))
        object.__setattr__(self, "package_id", safe_str(self.package_id, default="") or None)
        object.__setattr__(self, "family_id", normalized_family_id)
        object.__setattr__(self, "item_id", normalized_item_id or normalized_family_id or normalized_candidate_id)
        object.__setattr__(self, "label", safe_str(self.label, default="") or None)
        object.__setattr__(self, "object_kind", safe_str(self.object_kind, default="") or None)
        object.__setattr__(self, "source_path", safe_path_str(self.source_path))
        object.__setattr__(self, "package_root", safe_path_str(self.package_root))
        object.__setattr__(self, "relative_package_root", safe_path_str(self.relative_package_root))
        object.__setattr__(self, "manifest_path", safe_path_str(self.manifest_path))
        object.__setattr__(self, "document_count", safe_int(self.document_count, default=0, minimum=0))
        object.__setattr__(self, "loaded_document_keys", tuple_of_strings(self.loaded_document_keys))
        object.__setattr__(self, "missing_required_files", tuple_of_strings(self.missing_required_files))
        object.__setattr__(self, "revision_hash", safe_str(self.revision_hash, default="") or None)
        object.__setattr__(self, "discovered_at", safe_str(self.discovered_at, default="") or None)
        object.__setattr__(self, "scanned_at", safe_str(self.scanned_at, default="") or None)
        object.__setattr__(self, "item_summary", ensure_dict(self.item_summary))
        object.__setattr__(self, "validation", validation_summary_from_any(self.validation))
        object.__setattr__(self, "warnings", warnings)
        object.__setattr__(self, "errors", errors)
        object.__setattr__(self, "messages", tuple(message_list))
        object.__setattr__(self, "metadata", ensure_dict(self.metadata))

    @property
    def is_valid(self) -> bool:
        return self.status == LibraryScanCandidateStatus.VALID.value and self.valid

    @property
    def is_invalid(self) -> bool:
        return self.status in TERMINAL_ERROR_STATUSES

    @property
    def has_errors(self) -> bool:
        return bool(self.errors) or self.validation.error_count > 0 or self.validation.fatal_count > 0

    @property
    def has_warnings(self) -> bool:
        return bool(self.warnings) or self.validation.warning_count > 0

    @property
    def effective_id(self) -> str:
        return self.item_id or self.family_id or self.package_id or self.candidate_id

    def with_status(
        self,
        status: str,
        *,
        valid: bool | None = None,
        errors: Iterable[Any] | None = None,
        warnings: Iterable[Any] | None = None,
    ) -> "LibraryScanCandidate":
        """
        Erstellt eine Kopie mit geändertem Status.
        """

        next_errors = self.errors
        next_warnings = self.warnings

        if errors is not None:
            next_errors = tuple_of_strings(errors)

        if warnings is not None:
            next_warnings = tuple_of_strings(warnings)

        normalized_status = normalize_candidate_status(status)
        next_valid = bool(valid) if valid is not None else normalized_status == "valid"

        return replace(
            self,
            status=normalized_status,
            valid=next_valid,
            errors=next_errors,
            warnings=next_warnings,
        )

    def to_dict(
        self,
        *,
        include_item_summary: bool = True,
        include_messages: bool = True,
    ) -> dict[str, Any]:
        result: dict[str, Any] = {
            "candidate_id": self.candidate_id,
            "status": self.status,
            "valid": self.valid,
            "is_valid": self.is_valid,
            "is_invalid": self.is_invalid,
            "package_id": self.package_id,
            "family_id": self.family_id,
            "item_id": self.item_id,
            "effective_id": self.effective_id,
            "label": self.label,
            "object_kind": self.object_kind,
            "source_path": self.source_path,
            "package_root": self.package_root,
            "relative_package_root": self.relative_package_root,
            "manifest_path": self.manifest_path,
            "document_count": self.document_count,
            "loaded_document_keys": list(self.loaded_document_keys),
            "missing_required_files": list(self.missing_required_files),
            "revision_hash": self.revision_hash,
            "discovered_at": self.discovered_at,
            "scanned_at": self.scanned_at,
            "validation": self.validation.to_dict(),
            "warnings": list(self.warnings),
            "errors": list(self.errors),
            "metadata": json_safe(self.metadata),
        }

        if include_item_summary:
            result["item_summary"] = json_safe(self.item_summary)

        if include_messages:
            result["messages"] = [
                message.to_dict()
                for message in self.messages
            ]

        return result

    @classmethod
    def from_raw(
        cls,
        *,
        candidate_id: Any = None,
        status: Any = DEFAULT_CANDIDATE_STATUS,
        valid: Any = False,
        package_id: Any = None,
        family_id: Any = None,
        item_id: Any = None,
        label: Any = None,
        object_kind: Any = None,
        source_path: Any = None,
        package_root: Any = None,
        relative_package_root: Any = None,
        manifest_path: Any = None,
        document_count: Any = 0,
        loaded_document_keys: Any = None,
        missing_required_files: Any = None,
        revision_hash: Any = None,
        discovered_at: Any = None,
        scanned_at: Any = None,
        item_summary: Mapping[str, Any] | None = None,
        validation: Any = None,
        warnings: Any = None,
        errors: Any = None,
        messages: Any = None,
        metadata: Mapping[str, Any] | None = None,
    ) -> "LibraryScanCandidate":
        effective_candidate_id = first_non_empty_local(
            candidate_id,
            item_id,
            family_id,
            package_id,
            package_root,
            source_path,
            "unknown.candidate",
        )

        return cls(
            candidate_id=effective_candidate_id,
            status=status,
            valid=safe_bool(valid, default=False),
            package_id=package_id,
            family_id=family_id,
            item_id=item_id,
            label=label,
            object_kind=object_kind,
            source_path=source_path,
            package_root=package_root,
            relative_package_root=relative_package_root,
            manifest_path=manifest_path,
            document_count=document_count,
            loaded_document_keys=tuple_of_strings(loaded_document_keys),
            missing_required_files=tuple_of_strings(missing_required_files),
            revision_hash=revision_hash,
            discovered_at=discovered_at,
            scanned_at=scanned_at,
            item_summary=ensure_dict(item_summary),
            validation=validation_summary_from_any(validation),
            warnings=tuple_of_strings(warnings),
            errors=tuple_of_strings(errors),
            messages=tuple(normalize_scan_messages(messages)),
            metadata=ensure_dict(metadata),
        )

    @classmethod
    def from_item(
        cls,
        item: Any,
        *,
        status: Any | None = None,
        validation: Any = None,
        warnings: Any = None,
        errors: Any = None,
        messages: Any = None,
    ) -> "LibraryScanCandidate":
        item_summary = item_to_summary_dict(item)

        item_id = item_id_from_any(item)
        family_id = (
            safe_str(item_summary.get("family_id"), default="")
            or safe_str(getattr(item, "family_id", None), default="")
            or item_id
        )
        package_id = (
            safe_str(item_summary.get("package_id"), default="")
            or safe_str(getattr(item, "package_id", None), default="")
            or None
        )

        item_valid = bool(getattr(item, "is_valid", False))
        item_status = status or item_summary.get("status") or getattr(item, "status", None)

        return cls.from_raw(
            candidate_id=item_id or family_id or package_id,
            status=item_status or ("valid" if item_valid else "candidate"),
            valid=item_valid,
            package_id=package_id,
            family_id=family_id,
            item_id=item_id,
            label=item_summary.get("label") or getattr(item, "label", None),
            object_kind=item_summary.get("object_kind") or getattr(item, "object_kind", None),
            source_path=item_summary.get("source_path") or getattr(item, "source_path", None),
            package_root=item_summary.get("package_root") or getattr(item, "package_root", None),
            relative_package_root=item_summary.get("relative_package_root") or getattr(item, "relative_package_root", None),
            manifest_path=None,
            document_count=safe_int(
                getattr(item, "metadata", {}).get("document_count")
                if isinstance(getattr(item, "metadata", None), Mapping)
                else item_summary.get("document_count"),
                default=0,
                minimum=0,
            ),
            loaded_document_keys=(
                getattr(item, "metadata", {}).get("document_keys")
                if isinstance(getattr(item, "metadata", None), Mapping)
                else []
            ),
            revision_hash=item_summary.get("revision_hash") or getattr(item, "revision_hash", None),
            scanned_at=item_summary.get("scanned_at") or getattr(item, "scanned_at", None),
            item_summary=item_summary,
            validation=validation or getattr(item, "validation", None) or item_summary.get("validation"),
            warnings=warnings,
            errors=errors,
            messages=messages,
        )


@dataclass(frozen=True)
class LibraryScanStats:
    """
    Aggregierte Scan-Zahlen.
    """

    candidate_count: int = 0
    valid_count: int = 0
    invalid_count: int = 0
    duplicate_count: int = 0
    skipped_count: int = 0
    error_count: int = 0
    warning_count: int = 0
    item_count: int = 0
    document_count: int = 0
    duration_ms: int = 0

    @property
    def has_candidates(self) -> bool:
        return self.candidate_count > 0

    @property
    def has_valid_items(self) -> bool:
        return self.valid_count > 0

    @property
    def has_errors(self) -> bool:
        return self.error_count > 0

    @property
    def has_warnings(self) -> bool:
        return self.warning_count > 0

    def to_dict(self) -> dict[str, Any]:
        return {
            "candidate_count": self.candidate_count,
            "valid_count": self.valid_count,
            "invalid_count": self.invalid_count,
            "duplicate_count": self.duplicate_count,
            "skipped_count": self.skipped_count,
            "error_count": self.error_count,
            "warning_count": self.warning_count,
            "item_count": self.item_count,
            "document_count": self.document_count,
            "duration_ms": self.duration_ms,
            "has_candidates": self.has_candidates,
            "has_valid_items": self.has_valid_items,
            "has_errors": self.has_errors,
            "has_warnings": self.has_warnings,
        }

    @classmethod
    def from_candidates(
        cls,
        candidates: Iterable[LibraryScanCandidate],
        *,
        item_count: int = 0,
        duration_ms: int = 0,
        duplicate_count: int | None = None,
    ) -> "LibraryScanStats":
        candidate_list = list(candidates)

        valid_count = sum(1 for candidate in candidate_list if candidate.status == "valid")
        invalid_count = sum(1 for candidate in candidate_list if candidate.status == "invalid")
        candidate_duplicate_count = sum(1 for candidate in candidate_list if candidate.status == "duplicate")
        skipped_count = sum(1 for candidate in candidate_list if candidate.status == "skipped")
        status_error_count = sum(1 for candidate in candidate_list if candidate.status == "error")

        warning_count = 0
        error_count = status_error_count
        document_count = 0

        for candidate in candidate_list:
            warning_count += len(candidate.warnings)
            warning_count += candidate.validation.warning_count

            error_count += len(candidate.errors)
            error_count += candidate.validation.error_count
            error_count += candidate.validation.fatal_count

            document_count += candidate.document_count

        return cls(
            candidate_count=len(candidate_list),
            valid_count=valid_count,
            invalid_count=invalid_count,
            duplicate_count=duplicate_count if duplicate_count is not None else candidate_duplicate_count,
            skipped_count=skipped_count,
            error_count=error_count,
            warning_count=warning_count,
            item_count=safe_int(item_count, default=0, minimum=0),
            document_count=document_count,
            duration_ms=safe_int(duration_ms, default=0, minimum=0),
        )


# ---------------------------------------------------------------------------
# Main scan result
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class LibraryScanResult:
    """
    Gesamtergebnis eines Library-Source-Scans.
    """

    ok: bool
    status: str
    source_root: str | None = None
    scan_mode: str = DEFAULT_SCAN_MODE

    started_at: str | None = None
    finished_at: str | None = None
    duration_ms: int = 0

    candidates: tuple[LibraryScanCandidate, ...] = field(default_factory=tuple)
    items: tuple[Any, ...] = field(default_factory=tuple)
    duplicates: tuple[LibraryDuplicateId, ...] = field(default_factory=tuple)

    stats: LibraryScanStats = field(default_factory=LibraryScanStats)
    warnings: tuple[str, ...] = field(default_factory=tuple)
    errors: tuple[str, ...] = field(default_factory=tuple)
    messages: tuple[LibraryScanMessage, ...] = field(default_factory=tuple)

    settings: dict[str, Any] = field(default_factory=dict)
    metadata: dict[str, Any] = field(default_factory=dict)

    model_version: str = LIBRARY_SCAN_RESULT_MODEL_VERSION

    def __post_init__(self) -> None:
        candidates = tuple(normalize_scan_candidates(self.candidates))
        duplicates = tuple(normalize_duplicates(self.duplicates))
        warnings = tuple_of_strings(self.warnings)
        errors = tuple_of_strings(self.errors)

        messages = normalize_scan_messages(self.messages)

        for warning in warnings:
            messages.append(LibraryScanMessage(level="warning", message=warning))

        for error in errors:
            messages.append(LibraryScanMessage(level="error", message=error))

        stats = self.stats

        if not isinstance(stats, LibraryScanStats):
            stats = LibraryScanStats.from_candidates(
                candidates,
                item_count=len(self.items),
                duration_ms=self.duration_ms,
                duplicate_count=len(duplicates),
            )

        if stats.candidate_count == 0 and candidates:
            stats = LibraryScanStats.from_candidates(
                candidates,
                item_count=len(self.items),
                duration_ms=self.duration_ms,
                duplicate_count=len(duplicates),
            )

        normalized_status = normalize_scan_status(self.status)

        if normalized_status == DEFAULT_SCAN_STATUS:
            normalized_status = derive_scan_status(
                ok=self.ok,
                candidate_count=stats.candidate_count,
                valid_count=stats.valid_count,
                error_count=stats.error_count + len(errors),
                duplicate_count=stats.duplicate_count,
            )

        effective_ok = bool(self.ok and normalized_status in {"ok", "empty", "partial"})

        object.__setattr__(self, "ok", effective_ok)
        object.__setattr__(self, "status", normalized_status)
        object.__setattr__(self, "source_root", safe_path_str(self.source_root))
        object.__setattr__(self, "scan_mode", safe_str(self.scan_mode, default=DEFAULT_SCAN_MODE))
        object.__setattr__(self, "started_at", safe_str(self.started_at, default="") or None)
        object.__setattr__(self, "finished_at", safe_str(self.finished_at, default="") or None)
        object.__setattr__(self, "duration_ms", safe_int(self.duration_ms, default=stats.duration_ms, minimum=0))
        object.__setattr__(self, "candidates", candidates)
        object.__setattr__(self, "items", tuple(self.items or ()))
        object.__setattr__(self, "duplicates", duplicates)
        object.__setattr__(self, "stats", stats)
        object.__setattr__(self, "warnings", warnings)
        object.__setattr__(self, "errors", errors)
        object.__setattr__(self, "messages", tuple(messages))
        object.__setattr__(self, "settings", ensure_dict(self.settings))
        object.__setattr__(self, "metadata", ensure_dict(self.metadata))

    @property
    def candidate_count(self) -> int:
        return self.stats.candidate_count

    @property
    def valid_count(self) -> int:
        return self.stats.valid_count

    @property
    def invalid_count(self) -> int:
        return self.stats.invalid_count

    @property
    def duplicate_count(self) -> int:
        return self.stats.duplicate_count

    @property
    def error_count(self) -> int:
        return self.stats.error_count + len(self.errors)

    @property
    def warning_count(self) -> int:
        return self.stats.warning_count + len(self.warnings)

    @property
    def item_count(self) -> int:
        return self.stats.item_count or len(self.items)

    @property
    def is_empty(self) -> bool:
        return self.candidate_count == 0 and self.item_count == 0

    @property
    def has_errors(self) -> bool:
        return self.error_count > 0 or self.status == "error"

    @property
    def has_warnings(self) -> bool:
        return self.warning_count > 0

    @property
    def valid_items(self) -> list[Any]:
        return filter_valid_library_items(self.items)

    def get_candidate_by_id(self, item_id: Any) -> LibraryScanCandidate | None:
        """
        Findet einen Kandidaten nach item_id/family_id/package_id/candidate_id.
        """

        normalized_id = normalize_stable_id(item_id)

        if not normalized_id:
            return None

        for candidate in self.candidates:
            candidate_ids = {
                normalize_stable_id(candidate.candidate_id),
                normalize_stable_id(candidate.item_id),
                normalize_stable_id(candidate.family_id),
                normalize_stable_id(candidate.package_id),
            }

            if normalized_id in candidate_ids:
                return candidate

        return None

    def get_item_by_id(self, item_id: Any) -> Any | None:
        """
        Findet ein Item nach stabiler ID.
        """

        normalized_id = normalize_stable_id(item_id)

        if not normalized_id:
            return None

        for item in self.items:
            if item_id_from_any(item) == normalized_id:
                return item

        return None

    def to_dict(
        self,
        *,
        include_candidates: bool = True,
        include_items: bool = True,
        include_item_summaries: bool = True,
        include_messages: bool = True,
    ) -> dict[str, Any]:
        result: dict[str, Any] = {
            "ok": self.ok,
            "status": self.status,
            "source_root": self.source_root,
            "scan_mode": self.scan_mode,
            "started_at": self.started_at,
            "finished_at": self.finished_at,
            "duration_ms": self.duration_ms,
            "candidate_count": self.candidate_count,
            "valid_count": self.valid_count,
            "invalid_count": self.invalid_count,
            "duplicate_count": self.duplicate_count,
            "error_count": self.error_count,
            "warning_count": self.warning_count,
            "item_count": self.item_count,
            "is_empty": self.is_empty,
            "has_errors": self.has_errors,
            "has_warnings": self.has_warnings,
            "stats": self.stats.to_dict(),
            "duplicates": [
                duplicate.to_dict()
                for duplicate in self.duplicates
            ],
            "warnings": list(self.warnings),
            "errors": list(self.errors),
            "settings": json_safe(self.settings),
            "metadata": json_safe(self.metadata),
            "model_version": self.model_version,
        }

        if include_candidates:
            result["candidates"] = [
                candidate.to_dict(
                    include_item_summary=include_item_summaries,
                    include_messages=include_messages,
                )
                for candidate in self.candidates
            ]

        if include_items:
            result["items"] = library_items_to_summary_dicts(self.items)

        if include_messages:
            result["messages"] = [
                message.to_dict()
                for message in self.messages
            ]

        return result

    def to_scan_response_dict(self) -> dict[str, Any]:
        """
        Vollständige Antwort für:
          GET /api/v1/vplib/library/scan
        """

        return self.to_dict(
            include_candidates=True,
            include_items=True,
            include_item_summaries=True,
            include_messages=True,
        )

    def to_blocks_response_dict(self) -> dict[str, Any]:
        """
        Kompakte Antwortbasis für:
          GET /api/v1/vplib/library/blocks
        """

        items = library_items_to_summary_dicts(self.valid_items)

        return {
            "ok": self.ok and not self.has_errors,
            "status": "ok" if self.ok and not self.has_errors else self.status,
            "source_root": self.source_root,
            "count": len(items),
            "items": items,
            "scan": {
                "status": self.status,
                "candidate_count": self.candidate_count,
                "valid_count": self.valid_count,
                "invalid_count": self.invalid_count,
                "duplicate_count": self.duplicate_count,
                "error_count": self.error_count,
                "warning_count": self.warning_count,
                "duration_ms": self.duration_ms,
                "finished_at": self.finished_at,
            },
        }

    @classmethod
    def empty(
        cls,
        *,
        source_root: Any = None,
        message: str | None = None,
        settings: Mapping[str, Any] | None = None,
    ) -> "LibraryScanResult":
        warnings = [message] if message else []

        return cls(
            ok=True,
            status=LibraryScanStatus.EMPTY.value,
            source_root=safe_path_str(source_root),
            scan_mode=DEFAULT_SCAN_MODE,
            started_at=utc_now_iso(),
            finished_at=utc_now_iso(),
            duration_ms=0,
            candidates=(),
            items=(),
            duplicates=(),
            stats=LibraryScanStats(),
            warnings=tuple(warnings),
            errors=(),
            settings=ensure_dict(settings),
            metadata={},
        )

    @classmethod
    def error(
        cls,
        exc: BaseException,
        *,
        source_root: Any = None,
        started_at: Any = None,
        duration_ms: int = 0,
        include_traceback: bool = False,
        settings: Mapping[str, Any] | None = None,
    ) -> "LibraryScanResult":
        error_data = exception_to_dict(exc, include_traceback=include_traceback)

        return cls(
            ok=False,
            status=LibraryScanStatus.ERROR.value,
            source_root=safe_path_str(source_root),
            scan_mode=DEFAULT_SCAN_MODE,
            started_at=safe_str(started_at, default="") or utc_now_iso(),
            finished_at=utc_now_iso(),
            duration_ms=duration_ms,
            candidates=(),
            items=(),
            duplicates=(),
            stats=LibraryScanStats(error_count=1, duration_ms=duration_ms),
            warnings=(),
            errors=(safe_str(error_data.get("message"), default="scan failed"),),
            messages=(
                LibraryScanMessage(
                    level="error",
                    message=safe_str(error_data.get("message"), default="scan failed"),
                    code=safe_str(error_data.get("type"), default="Exception"),
                    data=error_data,
                ),
            ),
            settings=ensure_dict(settings),
            metadata={"exception": error_data},
        )

    @classmethod
    def from_parts(
        cls,
        *,
        source_root: Any = None,
        candidates: Iterable[LibraryScanCandidate] | None = None,
        items: Iterable[Any] | None = None,
        duplicates: Iterable[LibraryDuplicateId] | None = None,
        warnings: Iterable[Any] | None = None,
        errors: Iterable[Any] | None = None,
        messages: Iterable[Any] | None = None,
        started_at: Any = None,
        finished_at: Any = None,
        duration_ms: int = 0,
        settings: Mapping[str, Any] | None = None,
        metadata: Mapping[str, Any] | None = None,
    ) -> "LibraryScanResult":
        candidate_tuple = tuple(normalize_scan_candidates(candidates))
        item_tuple = tuple(items or ())
        duplicate_tuple = tuple(normalize_duplicates(duplicates))
        warning_tuple = tuple_of_strings(warnings)
        error_tuple = tuple_of_strings(errors)

        stats = LibraryScanStats.from_candidates(
            candidate_tuple,
            item_count=len(item_tuple),
            duration_ms=duration_ms,
            duplicate_count=len(duplicate_tuple),
        )

        status = derive_scan_status(
            ok=len(error_tuple) == 0,
            candidate_count=stats.candidate_count,
            valid_count=stats.valid_count,
            error_count=stats.error_count + len(error_tuple),
            duplicate_count=stats.duplicate_count,
        )

        return cls(
            ok=status in {"ok", "empty", "partial"},
            status=status,
            source_root=safe_path_str(source_root),
            scan_mode=DEFAULT_SCAN_MODE,
            started_at=safe_str(started_at, default="") or utc_now_iso(),
            finished_at=safe_str(finished_at, default="") or utc_now_iso(),
            duration_ms=duration_ms,
            candidates=candidate_tuple,
            items=item_tuple,
            duplicates=duplicate_tuple,
            stats=stats,
            warnings=warning_tuple,
            errors=error_tuple,
            messages=tuple(normalize_scan_messages(messages)),
            settings=ensure_dict(settings),
            metadata=ensure_dict(metadata),
        )


# ---------------------------------------------------------------------------
# Normalization / builders
# ---------------------------------------------------------------------------

def first_non_empty_local(*values: Any, default: Any = None) -> Any:
    """
    Lokaler Helper, damit diese Datei nicht hart von weiteren Utilities abhängt.
    """

    for value in values:
        if value is None:
            continue

        if isinstance(value, str) and not value.strip():
            continue

        if isinstance(value, (list, tuple, set, dict)) and not value:
            continue

        return value

    return default


def normalize_scan_messages(value: Any) -> list[LibraryScanMessage]:
    """
    Normalisiert beliebige Meldungsformen.
    """

    if value is None:
        return []

    if isinstance(value, LibraryScanMessage):
        return [value]

    if isinstance(value, str):
        text = value.strip()
        return [LibraryScanMessage(level="info", message=text)] if text else []

    if isinstance(value, Mapping):
        return [LibraryScanMessage.from_raw(value)]

    if isinstance(value, Iterable):
        result: list[LibraryScanMessage] = []

        for item in value:
            try:
                result.append(LibraryScanMessage.from_raw(item))
            except Exception:
                continue

        return result

    return [LibraryScanMessage(level="info", message=str(value))]


def normalize_scan_candidates(value: Any) -> list[LibraryScanCandidate]:
    """
    Normalisiert beliebige Kandidatenformen.
    """

    if value is None:
        return []

    if isinstance(value, LibraryScanCandidate):
        return [value]

    if isinstance(value, Mapping):
        return [
            LibraryScanCandidate.from_raw(
                candidate_id=value.get("candidate_id") or value.get("id") or value.get("family_id") or value.get("package_id"),
                status=value.get("status", DEFAULT_CANDIDATE_STATUS),
                valid=value.get("valid", False),
                package_id=value.get("package_id"),
                family_id=value.get("family_id"),
                item_id=value.get("item_id") or value.get("id"),
                label=value.get("label"),
                object_kind=value.get("object_kind"),
                source_path=value.get("source_path"),
                package_root=value.get("package_root"),
                relative_package_root=value.get("relative_package_root"),
                manifest_path=value.get("manifest_path"),
                document_count=value.get("document_count", 0),
                loaded_document_keys=value.get("loaded_document_keys"),
                missing_required_files=value.get("missing_required_files"),
                revision_hash=value.get("revision_hash"),
                discovered_at=value.get("discovered_at"),
                scanned_at=value.get("scanned_at"),
                item_summary=value.get("item_summary"),
                validation=value.get("validation"),
                warnings=value.get("warnings"),
                errors=value.get("errors"),
                messages=value.get("messages"),
                metadata=value.get("metadata"),
            )
        ]

    if isinstance(value, Iterable) and not isinstance(value, str):
        result: list[LibraryScanCandidate] = []

        for item in value:
            try:
                if isinstance(item, LibraryScanCandidate):
                    result.append(item)
                elif isinstance(item, Mapping):
                    result.extend(normalize_scan_candidates(item))
                else:
                    result.append(LibraryScanCandidate.from_item(item))

            except Exception as exc:
                result.append(
                    LibraryScanCandidate.from_raw(
                        candidate_id="unknown.candidate",
                        status="error",
                        valid=False,
                        errors=[str(exc)],
                        metadata={"normalization_error": exception_to_dict(exc)},
                    )
                )

        return result

    return [
        LibraryScanCandidate.from_raw(
            candidate_id=str(value),
            status="candidate",
            valid=False,
        )
    ]


def normalize_duplicates(value: Any) -> list[LibraryDuplicateId]:
    """
    Normalisiert beliebige Duplicate-Formen.
    """

    if value is None:
        return []

    if isinstance(value, LibraryDuplicateId):
        return [value]

    if isinstance(value, Mapping):
        return [
            LibraryDuplicateId(
                id=value.get("id") or value.get("family_id") or value.get("item_id") or "unknown.duplicate",
                first_path=value.get("first_path"),
                duplicate_path=value.get("duplicate_path"),
                package_id=value.get("package_id"),
                family_id=value.get("family_id"),
                message=value.get("message", "duplicate library item id"),
            )
        ]

    if isinstance(value, Iterable) and not isinstance(value, str):
        result: list[LibraryDuplicateId] = []

        for item in value:
            try:
                result.extend(normalize_duplicates(item))
            except Exception:
                continue

        return result

    return [
        LibraryDuplicateId(
            id=safe_str(value, default="unknown.duplicate"),
        )
    ]


def derive_scan_status(
    *,
    ok: bool,
    candidate_count: int,
    valid_count: int,
    error_count: int,
    duplicate_count: int,
) -> str:
    """
    Leitet den Gesamtstatus eines Scans ab.
    """

    if error_count > 0 and valid_count == 0:
        return LibraryScanStatus.ERROR.value

    if duplicate_count > 0 and valid_count == 0:
        return LibraryScanStatus.INVALID.value

    if candidate_count == 0:
        return LibraryScanStatus.EMPTY.value if ok else LibraryScanStatus.ERROR.value

    if error_count > 0 or duplicate_count > 0:
        return LibraryScanStatus.PARTIAL.value

    if valid_count == 0:
        return LibraryScanStatus.INVALID.value

    return LibraryScanStatus.OK.value


def candidates_from_items(
    items: Iterable[Any],
    *,
    status: str | None = None,
) -> list[LibraryScanCandidate]:
    """
    Baut Scan-Kandidaten aus LibraryItems.
    """

    result: list[LibraryScanCandidate] = []

    for item in items:
        try:
            result.append(
                LibraryScanCandidate.from_item(
                    item,
                    status=status,
                )
            )
        except Exception as exc:
            result.append(
                LibraryScanCandidate.from_raw(
                    candidate_id=item_id_from_any(item) or "unknown.item",
                    status="error",
                    valid=False,
                    errors=[str(exc)],
                    metadata={"exception": exception_to_dict(exc)},
                )
            )

    return result


def detect_duplicate_items(items: Iterable[Any]) -> list[LibraryDuplicateId]:
    """
    Erkennt doppelte stabile IDs in einer Item-Liste.
    """

    try:
        items_by_id, duplicates = index_library_items_by_id(items)
        result: list[LibraryDuplicateId] = []

        for duplicate in duplicates:
            duplicate_id = item_id_from_any(duplicate)

            if not duplicate_id:
                continue

            first = items_by_id.get(duplicate_id)

            result.append(
                LibraryDuplicateId.from_items(
                    first,
                    duplicate,
                )
            )

        return result

    except Exception:
        return []


def mark_duplicate_candidates(
    candidates: Iterable[LibraryScanCandidate],
    duplicates: Iterable[LibraryDuplicateId],
) -> list[LibraryScanCandidate]:
    """
    Markiert Kandidaten mit doppelten IDs als duplicate.
    """

    duplicate_ids = {
        duplicate.id
        for duplicate in duplicates
        if duplicate.id
    }

    result: list[LibraryScanCandidate] = []

    for candidate in candidates:
        try:
            if candidate.effective_id in duplicate_ids:
                result.append(
                    candidate.with_status(
                        "duplicate",
                        valid=False,
                        errors=[
                            f"duplicate library item id: {candidate.effective_id}",
                        ],
                    )
                )
            else:
                result.append(candidate)

        except Exception:
            result.append(candidate)

    return result


def build_scan_result_from_items(
    *,
    source_root: Any = None,
    items: Iterable[Any] | None = None,
    warnings: Iterable[Any] | None = None,
    errors: Iterable[Any] | None = None,
    started_at: Any = None,
    started_monotonic_ms: int | None = None,
    settings: Mapping[str, Any] | None = None,
    metadata: Mapping[str, Any] | None = None,
) -> LibraryScanResult:
    """
    Baut ein ScanResult aus bereits erstellten LibraryItems.

    Diese Funktion ist nützlich für die spätere Service-Schicht:
      Discovery/Reader/Validator -> Items -> ScanResult
    """

    item_tuple = tuple(items or ())
    duplicates = detect_duplicate_items(item_tuple)
    candidates = candidates_from_items(item_tuple)
    candidates = mark_duplicate_candidates(candidates, duplicates)

    finished_monotonic = monotonic_ms()
    duration = calculate_duration_ms(
        started_monotonic_ms=started_monotonic_ms,
        finished_monotonic_ms=finished_monotonic,
        fallback=0,
    )

    return LibraryScanResult.from_parts(
        source_root=source_root,
        candidates=candidates,
        items=item_tuple,
        duplicates=duplicates,
        warnings=warnings,
        errors=errors,
        started_at=started_at or utc_now_iso(),
        finished_at=utc_now_iso(),
        duration_ms=duration,
        settings=settings,
        metadata=metadata,
    )


def build_scan_response(
    result: LibraryScanResult | Mapping[str, Any] | None,
) -> dict[str, Any]:
    """
    Baut eine standardisierte API-Antwort für die Scan-Route.
    """

    try:
        if isinstance(result, LibraryScanResult):
            return result.to_scan_response_dict()

        if isinstance(result, Mapping):
            return json_safe(result)

        return {
            "ok": False,
            "status": "error",
            "errors": ["scan result is empty"],
        }

    except Exception as exc:
        return {
            "ok": False,
            "status": "error",
            "errors": ["could not serialize scan result"],
            "error": exception_to_dict(exc),
        }


def build_blocks_response(
    result: LibraryScanResult | Mapping[str, Any] | None,
) -> dict[str, Any]:
    """
    Baut eine standardisierte API-Antwort für die Blocklisten-Route.
    """

    try:
        if isinstance(result, LibraryScanResult):
            return result.to_blocks_response_dict()

        if isinstance(result, Mapping):
            items = result.get("items") or []
            return {
                "ok": safe_bool(result.get("ok"), default=True),
                "status": safe_str(result.get("status"), default="ok"),
                "count": len(items) if isinstance(items, list) else 0,
                "items": json_safe(items),
                "scan": json_safe(result),
            }

        return {
            "ok": False,
            "status": "error",
            "count": 0,
            "items": [],
            "errors": ["scan result is empty"],
        }

    except Exception as exc:
        return {
            "ok": False,
            "status": "error",
            "count": 0,
            "items": [],
            "errors": ["could not serialize blocks response"],
            "error": exception_to_dict(exc),
        }


def build_empty_scan_result(
    *,
    source_root: Any = None,
    message: str | None = None,
    settings: Mapping[str, Any] | None = None,
) -> LibraryScanResult:
    """
    Convenience-Wrapper für leere Scan-Ergebnisse.
    """

    return LibraryScanResult.empty(
        source_root=source_root,
        message=message,
        settings=settings,
    )


def build_error_scan_result(
    exc: BaseException,
    *,
    source_root: Any = None,
    started_at: Any = None,
    started_monotonic_ms: int | None = None,
    include_traceback: bool = False,
    settings: Mapping[str, Any] | None = None,
) -> LibraryScanResult:
    """
    Convenience-Wrapper für fehlerhafte Scan-Ergebnisse.
    """

    duration = calculate_duration_ms(
        started_monotonic_ms=started_monotonic_ms,
        finished_monotonic_ms=monotonic_ms(),
        fallback=0,
    )

    return LibraryScanResult.error(
        exc,
        source_root=source_root,
        started_at=started_at,
        duration_ms=duration,
        include_traceback=include_traceback,
        settings=settings,
    )


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

__all__: Final[tuple[str, ...]] = (
    "LIBRARY_SCAN_RESULT_MODEL_VERSION",
    "DEFAULT_SCAN_STATUS",
    "DEFAULT_SCAN_MODE",
    "DEFAULT_CANDIDATE_STATUS",
    "VALID_SCAN_STATUSES",
    "VALID_CANDIDATE_STATUSES",
    "TERMINAL_ERROR_STATUSES",
    "LibraryScanStatus",
    "LibraryScanCandidateStatus",
    "LibraryScanMessage",
    "LibraryDuplicateId",
    "LibraryScanCandidate",
    "LibraryScanStats",
    "LibraryScanResult",
    "utc_now_iso",
    "monotonic_ms",
    "normalize_status",
    "normalize_candidate_status",
    "normalize_scan_status",
    "json_safe",
    "tuple_of_strings",
    "tuple_of_dicts",
    "item_id_from_any",
    "item_to_summary_dict",
    "validation_summary_from_any",
    "derive_candidate_status",
    "calculate_duration_ms",
    "first_non_empty_local",
    "normalize_scan_messages",
    "normalize_scan_candidates",
    "normalize_duplicates",
    "derive_scan_status",
    "candidates_from_items",
    "detect_duplicate_items",
    "mark_duplicate_candidates",
    "build_scan_result_from_items",
    "build_scan_response",
    "build_blocks_response",
    "build_empty_scan_result",
    "build_error_scan_result",
)