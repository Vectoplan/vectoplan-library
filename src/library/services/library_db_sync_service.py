# services/vectoplan-library/src/library/services/library_db_sync_service.py
"""
DB-Sync-Service für die VECTOPLAN Creative Library.

Diese Datei schließt die persistente Schleife:

    src/library/source
        -> Scanner
        -> Reader
        -> Validation
        -> Fingerprint
        -> Read-/Scan-Result
        -> library_db_sync_service
        -> creative_library Tabellen
        -> DB-basierte Read-Services / API

Aufgaben:

- dateibasierten Library-Scan auslösen
- vorhandene Scan-/Pipeline-Ergebnisse in DB schreiben
- ScanRun in der Datenbank anlegen und abschließen
- gültige Packages anhand vplib_uid upserten
- Revisionen erzeugen
- Varianten, Assets und Dokumente revisionsbezogen speichern
- Issues speichern
- ungültige Packages als Issues protokollieren
- optional fehlende Packages als deleted/inactive markieren
- robust mit unterschiedlichen ScanResult-/Pipeline-Strukturen umgehen
- Manifest-/Dokumentdaten notfalls direkt aus dem Package-Verzeichnis laden

Architekturregeln:

- Dieser Service erzeugt keine vplib_uid.
- Fehlende oder ungültige vplib_uid wird nicht repariert.
- Die DB übernimmt vplib_uid aus vplib.manifest.json.
- Scanner/Reader/Validator/Fingerprint schreiben weiterhin nicht direkt in die DB.
- Repository-Details liegen in src/library/repositories/creative_library_repository.py.
- Der Publish-/Read-Service liegt in src/library/services/creative_library_service.py.
- API-Routen sollen diesen Service für POST /api/v1/vplib/library/sync nutzen.

Kompatibilität:

- Ältere Domain-Dataclasses aus library.domain.sync_result werden genutzt, falls vorhanden.
- Wenn sie nicht vorhanden sind, stellt diese Datei kleine lokale Fallback-Dataclasses bereit.
- Ältere Repository-Methoden wie upsert_family werden weiterhin optional unterstützt.
- Neue Repository-Methoden wie upsert_item/create_revision/upsert_variant/create_asset/create_document
  werden bevorzugt.
"""

from __future__ import annotations

import importlib
import json
import os
import threading
import time
import traceback as traceback_module
import uuid
from dataclasses import asdict, dataclass, field, fields, is_dataclass
from datetime import datetime, timezone
from pathlib import Path
from types import ModuleType
from typing import Any, Callable, Iterable, Mapping, Optional, Sequence


# ---------------------------------------------------------------------------
# Optional domain imports with fallback
# ---------------------------------------------------------------------------

_SYNC_RESULT_IMPORT_ERROR: BaseException | None = None

try:
    from ..domain.sync_result import (
        DEFAULT_SYNC_MODE,
        DEFAULT_SYNC_SOURCE,
        DEFAULT_SYNC_TARGET,
        LibrarySyncCandidateResult,
        LibrarySyncCandidateStatus,
        LibrarySyncIssue,
        LibrarySyncIssueSeverity,
        LibrarySyncOperation,
        LibrarySyncOperationResult,
        LibrarySyncResult,
        LibrarySyncRunInfo,
        LibrarySyncStats,
        LibrarySyncStatus,
        build_empty_sync_result,
        build_error_sync_result,
        build_sync_response,
    )
except Exception as import_exc:  # pragma: no cover - defensive fallback
    _SYNC_RESULT_IMPORT_ERROR = import_exc

    class _EnumValue(str):
        @property
        def value(self) -> str:
            return str(self)

    class LibrarySyncStatus:
        RUNNING = _EnumValue("running")
        FINISHED = _EnumValue("finished")
        PARTIAL = _EnumValue("partial")
        EMPTY = _EnumValue("empty")
        ERROR = _EnumValue("error")

    class LibrarySyncCandidateStatus:
        SCANNED = _EnumValue("scanned")
        INSERTED = _EnumValue("inserted")
        UPDATED = _EnumValue("updated")
        REVISION_CREATED = _EnumValue("revision_created")
        UNCHANGED = _EnumValue("unchanged")
        SKIPPED = _EnumValue("skipped")
        INVALID = _EnumValue("invalid")
        ERROR = _EnumValue("error")

    class LibrarySyncIssueSeverity:
        INFO = _EnumValue("info")
        WARNING = _EnumValue("warning")
        ERROR = _EnumValue("error")

    class LibrarySyncOperation:
        NONE = _EnumValue("none")
        SCAN = _EnumValue("scan")
        UPSERT_FAMILY = _EnumValue("upsert_family")
        UPSERT_ITEM = _EnumValue("upsert_item")
        CREATE_REVISION = _EnumValue("create_revision")
        SKIP_REVISION = _EnumValue("skip_revision")
        REPLACE_VARIANTS = _EnumValue("replace_variants")
        REPLACE_ASSETS = _EnumValue("replace_assets")
        REPLACE_DOCUMENTS = _EnumValue("replace_documents")
        SAVE_ISSUE = _EnumValue("save_issue")
        MARK_MISSING_DELETED = _EnumValue("mark_missing_deleted")

    DEFAULT_SYNC_MODE = "source_to_db"
    DEFAULT_SYNC_SOURCE = "src/library/source"
    DEFAULT_SYNC_TARGET = "creative_library"

    @dataclass
    class LibrarySyncIssue:
        severity: str = "error"
        code: str = "sync.issue"
        message: str = ""
        scope: str | None = None
        path: str | None = None
        field: str | None = None
        source_path: str | None = None
        vplib_uid: str | None = None
        family_id: str | None = None
        package_id: str | None = None
        revision_hash: str | None = None
        operation: str = "none"
        metadata: dict[str, Any] = field(default_factory=dict)

        @classmethod
        def from_mapping(cls, value: Mapping[str, Any] | Any) -> "LibrarySyncIssue":
            data = to_mapping(value)
            return cls(
                severity=str(data.get("severity") or data.get("level") or "error"),
                code=str(data.get("code") or "sync.issue"),
                message=str(data.get("message") or data.get("error") or ""),
                scope=normalize_string(data.get("scope")),
                path=normalize_string(data.get("path")),
                field=normalize_string(data.get("field")),
                source_path=normalize_string(data.get("source_path")),
                vplib_uid=normalize_vplib_uid(data.get("vplib_uid")),
                family_id=normalize_string(data.get("family_id")),
                package_id=normalize_string(data.get("package_id")),
                revision_hash=normalize_string(data.get("revision_hash")),
                operation=str(data.get("operation") or "none"),
                metadata=to_mapping(data.get("metadata")),
            )

        def to_dict(self) -> dict[str, Any]:
            return json_safe(asdict(self))

    @dataclass
    class LibrarySyncOperationResult:
        operation: str
        status: str = "ok"
        affected_count: int = 0
        created_count: int = 0
        updated_count: int = 0
        skipped_count: int = 0
        message: str | None = None
        metadata: dict[str, Any] = field(default_factory=dict)

        def to_dict(self) -> dict[str, Any]:
            return json_safe(asdict(self))

    @dataclass
    class LibrarySyncStats:
        total_count: int = 0
        published_count: int = 0
        inserted_count: int = 0
        updated_count: int = 0
        unchanged_count: int = 0
        skipped_count: int = 0
        invalid_count: int = 0
        error_count: int = 0
        issue_count: int = 0
        marked_missing_deleted_count: int = 0

        def to_dict(self) -> dict[str, Any]:
            return json_safe(asdict(self))

    @dataclass
    class LibrarySyncRunInfo:
        mode: str = DEFAULT_SYNC_MODE
        source: str = DEFAULT_SYNC_SOURCE
        target: str = DEFAULT_SYNC_TARGET
        source_root: str | None = None
        triggered_by: str | None = None
        force_refresh: bool = True
        publish_valid_only: bool = True
        mark_missing_deleted: bool = False
        started_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
        finished_at: datetime | None = None
        duration_ms: int | None = None
        scan_run_id: Any = None
        metadata: dict[str, Any] = field(default_factory=dict)

        def to_dict(self) -> dict[str, Any]:
            return json_safe(asdict(self))

    @dataclass
    class LibrarySyncCandidateResult:
        status: str = "scanned"
        valid: bool = False
        published: bool = False
        skipped: bool = False
        vplib_uid: str | None = None
        family_id: str | None = None
        package_id: str | None = None
        family_slug: str | None = None
        label: str | None = None
        object_kind: str | None = None
        domain: str | None = None
        category: str | None = None
        subcategory: str | None = None
        source_path: str | None = None
        package_root: str | None = None
        revision_hash: str | None = None
        previous_revision_hash: str | None = None
        validation_status: str | None = None
        scan_run_id: Any = None
        family_db_id: Any = None
        item_db_id: Any = None
        revision_db_id: Any = None
        family_created: bool = False
        family_updated: bool = False
        item_created: bool = False
        item_updated: bool = False
        revision_created: bool = False
        variant_count: int = 0
        asset_count: int = 0
        document_count: int = 0
        issue_count: int = 0
        error_count: int = 0
        started_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
        finished_at: datetime | None = None
        duration_ms: int | None = None
        operations: list[LibrarySyncOperationResult] = field(default_factory=list)
        issues: list[LibrarySyncIssue] = field(default_factory=list)
        metadata: dict[str, Any] = field(default_factory=dict)

        def add_issue(self, issue: LibrarySyncIssue) -> None:
            self.issues.append(issue)
            self.issue_count = len(self.issues)
            if str(issue.severity).lower() == "error":
                self.error_count += 1

        def add_operation(self, operation: LibrarySyncOperationResult) -> None:
            self.operations.append(operation)

        def to_dict(self) -> dict[str, Any]:
            data = asdict(self)
            data["operations"] = [op.to_dict() for op in self.operations]
            data["issues"] = [issue.to_dict() for issue in self.issues]
            return json_safe(data)

    @dataclass
    class LibrarySyncResult:
        ok: bool = False
        status: str = "running"
        message: str = ""
        run: LibrarySyncRunInfo = field(default_factory=LibrarySyncRunInfo)
        stats: LibrarySyncStats = field(default_factory=LibrarySyncStats)
        candidates: list[LibrarySyncCandidateResult] = field(default_factory=list)
        issues: list[LibrarySyncIssue] = field(default_factory=list)
        metadata: dict[str, Any] = field(default_factory=dict)

        def add_candidate(self, candidate: LibrarySyncCandidateResult) -> None:
            self.candidates.append(candidate)
            self.stats.total_count = len(self.candidates)
            if candidate.published:
                self.stats.published_count += 1
            if candidate.family_created or candidate.item_created:
                self.stats.inserted_count += 1
            if candidate.family_updated or candidate.item_updated:
                self.stats.updated_count += 1
            if candidate.status == LibrarySyncCandidateStatus.UNCHANGED.value:
                self.stats.unchanged_count += 1
            if candidate.skipped:
                self.stats.skipped_count += 1
            if not candidate.valid:
                self.stats.invalid_count += 1
            if candidate.error_count:
                self.stats.error_count += candidate.error_count
            self.stats.issue_count += candidate.issue_count

        def add_issue(self, issue: LibrarySyncIssue) -> None:
            self.issues.append(issue)
            self.stats.issue_count += 1
            if str(issue.severity).lower() == "error":
                self.stats.error_count += 1

        def finish(self, message: str | None = None) -> "LibrarySyncResult":
            self.run.finished_at = datetime.now(timezone.utc)
            if self.run.started_at:
                self.run.duration_ms = max(
                    0,
                    int((self.run.finished_at - self.run.started_at).total_seconds() * 1000),
                )
            if self.stats.error_count:
                self.status = LibrarySyncStatus.PARTIAL.value if self.stats.published_count else LibrarySyncStatus.ERROR.value
            elif self.stats.total_count == 0:
                self.status = LibrarySyncStatus.EMPTY.value
            else:
                self.status = LibrarySyncStatus.FINISHED.value
            self.ok = self.status in {LibrarySyncStatus.FINISHED.value, LibrarySyncStatus.EMPTY.value, LibrarySyncStatus.PARTIAL.value}
            if message:
                self.message = message
            return self

        def to_dict(self) -> dict[str, Any]:
            return {
                "ok": self.ok,
                "status": self.status,
                "message": self.message,
                "run": self.run.to_dict(),
                "stats": self.stats.to_dict(),
                "candidates": [candidate.to_dict() for candidate in self.candidates],
                "issues": [issue.to_dict() for issue in self.issues],
                "metadata": json_safe(self.metadata),
            }

    def build_empty_sync_result(*, message: str, run: LibrarySyncRunInfo) -> LibrarySyncResult:
        result = LibrarySyncResult(
            ok=True,
            status=LibrarySyncStatus.EMPTY.value,
            message=message,
            run=run,
            stats=LibrarySyncStats(total_count=0),
            candidates=[],
            issues=[],
        )
        return result

    def build_error_sync_result(
        exc: BaseException,
        *,
        message: str,
        run: LibrarySyncRunInfo,
        include_traceback: bool = True,
    ) -> LibrarySyncResult:
        issue = LibrarySyncIssue(
            severity=LibrarySyncIssueSeverity.ERROR.value,
            code="sync.error",
            message=str(exc),
            metadata={
                "exception_type": exc.__class__.__name__,
                "traceback": traceback_module.format_exc() if include_traceback else None,
            },
        )
        result = LibrarySyncResult(
            ok=False,
            status=LibrarySyncStatus.ERROR.value,
            message=message,
            run=run,
            stats=LibrarySyncStats(total_count=0, error_count=1, issue_count=1),
            candidates=[],
            issues=[issue],
        )
        return result.finish(message=message)

    def build_sync_response(result: LibrarySyncResult) -> dict[str, Any]:
        return result.to_dict()


# ---------------------------------------------------------------------------
# Metadata
# ---------------------------------------------------------------------------

LIBRARY_DB_SYNC_SERVICE_NAME = "library_db_sync_service"
LIBRARY_DB_SYNC_COMPONENT_NAME = "creative_library_db_sync"
LIBRARY_DB_SYNC_API_VERSION = "v1"
LIBRARY_DB_SYNC_IMPLEMENTATION_STAGE = "db-sync-service"

__version__ = "1.0.0"


# ---------------------------------------------------------------------------
# Environment / defaults
# ---------------------------------------------------------------------------

ENV_SYNC_ENABLED = "VPLIB_LIBRARY_SYNC_ENABLED"
ENV_SYNC_STRICT = "VPLIB_LIBRARY_SYNC_STRICT"
ENV_SYNC_AUTOCOMMIT = "VPLIB_LIBRARY_SYNC_AUTOCOMMIT"
ENV_SYNC_MARK_MISSING_DELETED = "VPLIB_LIBRARY_SYNC_MARK_MISSING_DELETED"
ENV_SYNC_CONTINUE_ON_CANDIDATE_ERROR = "VPLIB_LIBRARY_SYNC_CONTINUE_ON_CANDIDATE_ERROR"
ENV_SYNC_INCLUDE_RAW_DOCUMENTS = "VPLIB_LIBRARY_SYNC_INCLUDE_RAW_DOCUMENTS"

DEFAULT_SYNC_ENABLED = True
DEFAULT_SYNC_STRICT = False
DEFAULT_SYNC_AUTOCOMMIT = True
DEFAULT_SYNC_MARK_MISSING_DELETED = False
DEFAULT_SYNC_CONTINUE_ON_CANDIDATE_ERROR = True
DEFAULT_SYNC_INCLUDE_RAW_DOCUMENTS = True

DEFAULT_REPOSITORY_FACTORY_IMPORT = "library.repositories.creative_library_repository"
DEFAULT_CREATIVE_SERVICE_IMPORT = "library.services.creative_library_service"
DEFAULT_SCAN_SERVICE_IMPORT = "library.services.library_scan_service"

REPOSITORY_IMPORT_PATHS = (
    "library.repositories.creative_library_repository",
    "src.library.repositories.creative_library_repository",
    "vectoplan_library.library.repositories.creative_library_repository",
    "vectoplan_library.src.library.repositories.creative_library_repository",
    "library.repositories.sql",
    "src.library.repositories.sql",
)

CREATIVE_SERVICE_IMPORT_PATHS = (
    "library.services.creative_library_service",
    "src.library.services.creative_library_service",
    "vectoplan_library.library.services.creative_library_service",
    "vectoplan_library.src.library.services.creative_library_service",
)

SCAN_SERVICE_IMPORT_PATHS = (
    "library.services.library_scan_service",
    "src.library.services.library_scan_service",
    "vectoplan_library.library.services.library_scan_service",
    "vectoplan_library.src.library.services.library_scan_service",
)

DEFAULT_DOCUMENT_LIMIT_FOR_DETAIL_PAYLOAD = 10_000
DEFAULT_ISSUE_LIMIT_PER_CANDIDATE = 2_000

MANIFEST_DOCUMENT_KEYS = (
    "vplib.manifest.json",
    "manifest.json",
    "package.manifest.json",
)

IDENTITY_DOCUMENT_KEYS = (
    "family/identity.json",
    "identity.json",
)

CLASSIFICATION_DOCUMENT_KEYS = (
    "family/classification.json",
    "classification.json",
)

INVENTORY_DOCUMENT_KEYS = (
    "editor/inventory.json",
    "inventory.json",
)

MODULES_DOCUMENT_KEYS = (
    "vplib.modules.json",
    "modules.json",
)

DOCUMENT_WRAPPER_KEYS = (
    "payload",
    "document",
    "content",
    "data",
    "json",
    "value",
)

DOCUMENT_PATH_KEYS = (
    "relative_path",
    "document_path",
    "field_key",
    "path",
    "name",
)


# ---------------------------------------------------------------------------
# Internal import caches
# ---------------------------------------------------------------------------

_CACHE_LOCK = threading.RLock()
_IMPORT_CACHE: dict[str, ModuleType] = {}
_IMPORT_ERROR_CACHE: dict[str, dict[str, Any]] = {}
_DEFAULT_SERVICE: Optional["LibraryDbSyncService"] = None


# ---------------------------------------------------------------------------
# Exceptions
# ---------------------------------------------------------------------------

class LibraryDbSyncServiceError(RuntimeError):
    """Basisklasse für DB-Sync-Service-Fehler."""


class LibraryDbSyncDisabledError(LibraryDbSyncServiceError):
    """DB-Sync ist per Konfiguration deaktiviert."""


class LibraryDbSyncImportError(LibraryDbSyncServiceError):
    """Benötigtes Modul konnte nicht importiert werden."""


class LibraryDbSyncValidationError(LibraryDbSyncServiceError):
    """Ungültiger Sync-Payload oder ungültiger Kandidat."""


class LibraryDbSyncCandidateError(LibraryDbSyncServiceError):
    """Fehler beim Synchronisieren eines einzelnen Kandidaten."""


# ---------------------------------------------------------------------------
# Config
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class LibraryDbSyncServiceConfig:
    """Konfiguration für LibraryDbSyncService."""

    repository: Any = None
    repository_factory: Any = None
    creative_service: Any = None
    creative_service_factory: Any = None
    scan_service: Any = None

    enabled: bool = DEFAULT_SYNC_ENABLED
    strict: bool = DEFAULT_SYNC_STRICT
    autocommit: bool = DEFAULT_SYNC_AUTOCOMMIT
    mark_missing_deleted: bool = DEFAULT_SYNC_MARK_MISSING_DELETED
    continue_on_candidate_error: bool = DEFAULT_SYNC_CONTINUE_ON_CANDIDATE_ERROR
    include_raw_documents: bool = DEFAULT_SYNC_INCLUDE_RAW_DOCUMENTS
    publish_valid_only: bool = True

    repository_import_path: str = DEFAULT_REPOSITORY_FACTORY_IMPORT
    creative_service_import_path: str = DEFAULT_CREATIVE_SERVICE_IMPORT
    scan_service_import_path: str = DEFAULT_SCAN_SERVICE_IMPORT

    document_limit_for_detail_payload: int = DEFAULT_DOCUMENT_LIMIT_FOR_DETAIL_PAYLOAD
    issue_limit_per_candidate: int = DEFAULT_ISSUE_LIMIT_PER_CANDIDATE

    def __post_init__(self) -> None:
        object.__setattr__(self, "enabled", safe_bool(self.enabled, DEFAULT_SYNC_ENABLED))
        object.__setattr__(self, "strict", safe_bool(self.strict, DEFAULT_SYNC_STRICT))
        object.__setattr__(self, "autocommit", safe_bool(self.autocommit, DEFAULT_SYNC_AUTOCOMMIT))
        object.__setattr__(self, "mark_missing_deleted", safe_bool(self.mark_missing_deleted, DEFAULT_SYNC_MARK_MISSING_DELETED))
        object.__setattr__(
            self,
            "continue_on_candidate_error",
            safe_bool(self.continue_on_candidate_error, DEFAULT_SYNC_CONTINUE_ON_CANDIDATE_ERROR),
        )
        object.__setattr__(
            self,
            "include_raw_documents",
            safe_bool(self.include_raw_documents, DEFAULT_SYNC_INCLUDE_RAW_DOCUMENTS),
        )
        object.__setattr__(self, "publish_valid_only", safe_bool(self.publish_valid_only, True))
        object.__setattr__(self, "document_limit_for_detail_payload", safe_int(self.document_limit_for_detail_payload, DEFAULT_DOCUMENT_LIMIT_FOR_DETAIL_PAYLOAD))
        object.__setattr__(self, "issue_limit_per_candidate", safe_int(self.issue_limit_per_candidate, DEFAULT_ISSUE_LIMIT_PER_CANDIDATE))


# ---------------------------------------------------------------------------
# Generic helpers
# ---------------------------------------------------------------------------

def utcnow() -> datetime:
    """Timezone-aware UTC timestamp."""
    return datetime.now(timezone.utc)


def monotonic_ms() -> int:
    """Monotonic timestamp in Millisekunden."""
    return int(time.monotonic() * 1000)


def duration_ms(start_ms: Optional[int], end_ms: Optional[int] = None) -> Optional[int]:
    if start_ms is None:
        return None
    return max(0, (end_ms or monotonic_ms()) - start_ms)


def env_bool(name: str, default: bool = False) -> bool:
    value = os.getenv(name)
    if value is None:
        return default
    return str(value).strip().lower() in {"1", "true", "yes", "y", "on"}


def normalize_string(value: Any) -> Optional[str]:
    if value is None:
        return None
    text = str(value).replace("\x00", "").strip()
    return text or None


def normalize_vplib_uid(value: Any) -> Optional[str]:
    text = normalize_string(value)
    if not text:
        return None

    # vplib_uid kann UUID sein, muss aber im VPLIB-Kontext nur stabil übernommen
    # werden. Deshalb: UUIDs normalisieren, andere saubere Strings lowercased
    # übernehmen. Keine Neugenerierung.
    try:
        return str(uuid.UUID(text)).lower()
    except Exception:
        return text.lower()


def safe_int(value: Any, default: int = 0) -> int:
    try:
        if value is None:
            return default
        return int(value)
    except Exception:
        return default


def safe_bool(value: Any, default: bool = False) -> bool:
    if value is None:
        return default

    if isinstance(value, bool):
        return value

    text = str(value).strip().lower()

    if text in {"1", "true", "yes", "y", "on", "active", "enabled", "valid"}:
        return True

    if text in {"0", "false", "no", "n", "off", "inactive", "disabled", "invalid"}:
        return False

    return default


def dataclass_shallow_dict(value: Any) -> dict[str, Any]:
    """Wandelt Dataclasses ohne rekursives asdict(...) in ein Dict."""
    if not is_dataclass(value):
        return {}

    result: dict[str, Any] = {}

    try:
        for field_info in fields(value):
            try:
                result[field_info.name] = getattr(value, field_info.name)
            except Exception:
                continue
    except Exception:
        return {}

    return result


def json_safe(value: Any) -> Any:
    """Defensiv JSON-kompatible Struktur bauen."""
    if value is None:
        return None

    if isinstance(value, (str, int, float, bool)):
        return value

    if isinstance(value, datetime):
        return value.isoformat()

    if isinstance(value, Path):
        return str(value)

    to_dict = getattr(value, "to_dict", None)
    if callable(to_dict):
        for kwargs in ({}, {"include_raw_documents": False}, {"flat": True}):
            try:
                return json_safe(to_dict(**kwargs))
            except TypeError:
                continue
            except Exception:
                break

    if is_dataclass(value):
        return json_safe(dataclass_shallow_dict(value))

    if isinstance(value, Mapping):
        return {str(key): json_safe(item) for key, item in value.items()}

    if isinstance(value, (list, tuple, set)):
        return [json_safe(item) for item in value]

    try:
        json.dumps(value)
        return value
    except TypeError:
        return str(value)


def to_mapping(value: Any) -> dict[str, Any]:
    """Konvertiert Mapping, Dataclass oder Fremdobjekt defensiv in Dict."""
    if value is None:
        return {}

    if isinstance(value, Mapping):
        return dict(value)

    if hasattr(value, "to_dict") and callable(value.to_dict):
        for kwargs in ({}, {"include_raw_documents": False}, {"flat": True}):
            try:
                result = value.to_dict(**kwargs)
                if isinstance(result, Mapping):
                    return dict(result)
            except TypeError:
                continue
            except Exception:
                break

    if is_dataclass(value):
        return dataclass_shallow_dict(value)

    result: dict[str, Any] = {}

    for name in dir(value):
        if name.startswith("_"):
            continue
        try:
            item = getattr(value, name)
        except Exception:
            continue
        if callable(item):
            continue
        result[name] = item

    return result


def first_non_empty(*values: Any) -> Any:
    for value in values:
        if value is None:
            continue
        if isinstance(value, str) and not value.strip():
            continue
        return value
    return None


def get_direct_value(value: Any, key: str, default: Any = None) -> Any:
    """Liest einen direkten Mapping-Key oder ein Attribut ohne Vollserialisierung."""
    try:
        if value is None:
            return default
        if isinstance(value, Mapping):
            return value.get(key, default)
        return getattr(value, key, default)
    except Exception:
        return default


def deep_get(data: Any, *paths: str, default: Any = None) -> Any:
    """Liest verschachtelte Dict-/Objektwerte."""
    for path in paths:
        current = data
        found = True

        for part in str(path).split("."):
            if current is None:
                found = False
                break

            if isinstance(current, Mapping):
                if part in current:
                    current = current.get(part)
                else:
                    found = False
                    break
            else:
                try:
                    current = getattr(current, part)
                except Exception:
                    found = False
                    break

        if found and current is not None:
            return current

    return default


def mapping_get_any(data: Mapping[str, Any], keys: Sequence[str], default: Any = None) -> Any:
    for key in keys:
        if key in data and data.get(key) is not None:
            return data.get(key)
    return default


def exception_to_issue(
    exc: BaseException,
    *,
    code: str,
    scope: Optional[str] = None,
    path: Optional[str] = None,
    vplib_uid: Optional[str] = None,
    family_id: Optional[str] = None,
    package_id: Optional[str] = None,
    operation: str = LibrarySyncOperation.NONE.value,
) -> LibrarySyncIssue:
    return LibrarySyncIssue(
        severity=LibrarySyncIssueSeverity.ERROR.value,
        code=code,
        message=str(exc),
        scope=scope,
        path=path,
        vplib_uid=vplib_uid,
        family_id=family_id,
        package_id=package_id,
        operation=operation,
        metadata={
            "exception_type": exc.__class__.__name__,
            "traceback": traceback_module.format_exc(),
        },
    )


# ---------------------------------------------------------------------------
# Safe imports
# ---------------------------------------------------------------------------

def safe_import_module(
    module_path: str,
    *,
    required: bool = False,
    force_reload: bool = False,
) -> Optional[ModuleType]:
    """Importiert ein Modul robust und cached Modul oder Fehler."""
    normalized_path = str(module_path or "").strip()

    if not normalized_path:
        if required:
            raise LibraryDbSyncImportError("Empty import path.")
        return None

    with _CACHE_LOCK:
        if not force_reload and normalized_path in _IMPORT_CACHE:
            return _IMPORT_CACHE[normalized_path]

    try:
        with _CACHE_LOCK:
            if force_reload and normalized_path in _IMPORT_CACHE:
                module = importlib.reload(_IMPORT_CACHE[normalized_path])
            else:
                module = importlib.import_module(normalized_path)

            _IMPORT_CACHE[normalized_path] = module
            _IMPORT_ERROR_CACHE.pop(normalized_path, None)
            return module

    except Exception as exc:
        payload = {
            "module_path": normalized_path,
            "error_type": exc.__class__.__name__,
            "error": str(exc),
            "traceback": traceback_module.format_exc(),
        }

        with _CACHE_LOCK:
            _IMPORT_CACHE.pop(normalized_path, None)
            _IMPORT_ERROR_CACHE[normalized_path] = payload

        if required:
            raise LibraryDbSyncImportError(
                f"Unable to import {normalized_path}: "
                f"{exc.__class__.__name__}: {exc}"
            ) from exc

        return None


def import_first(import_paths: Sequence[str], *, required: bool = False) -> ModuleType | None:
    errors: list[str] = []

    for path in import_paths:
        try:
            module = safe_import_module(path, required=False)
            if module is not None:
                return module
        except Exception as exc:
            errors.append(f"{path}: {exc}")

    if required:
        raise LibraryDbSyncImportError("Unable to import any module: " + " | ".join(errors))

    return None


def clear_library_db_sync_import_cache() -> dict[str, Any]:
    """Leert nur Import-Caches dieses Moduls."""
    with _CACHE_LOCK:
        modules = sorted(_IMPORT_CACHE.keys())
        errors = sorted(_IMPORT_ERROR_CACHE.keys())
        _IMPORT_CACHE.clear()
        _IMPORT_ERROR_CACHE.clear()

    return {
        "ok": True,
        "cleared_modules": modules,
        "cleared_import_errors": errors,
    }


# ---------------------------------------------------------------------------
# Document / filesystem extraction helpers
# ---------------------------------------------------------------------------

def normalize_document_path(value: Any) -> Optional[str]:
    """Normalisiert Dokumentpfade für interne Mapping-Keys."""
    text = normalize_string(value)

    if not text:
        return None

    normalized = text.replace("\\", "/").lstrip("./")

    while "//" in normalized:
        normalized = normalized.replace("//", "/")

    return normalized or None


def unwrap_document_payload(value: Any) -> Any:
    """Entpackt häufige Dokument-Wrapper."""
    if value is None:
        return {}

    if is_dataclass(value):
        value = dataclass_shallow_dict(value)

    if not isinstance(value, Mapping):
        data = to_mapping(value)
        if data:
            value = data
        else:
            return value

    mapping = dict(value)
    has_path_hint = any(key in mapping for key in DOCUMENT_PATH_KEYS)

    for wrapper_key in DOCUMENT_WRAPPER_KEYS:
        if wrapper_key not in mapping:
            continue

        payload = mapping.get(wrapper_key)

        if isinstance(payload, Mapping):
            if has_path_hint:
                return dict(payload)

            non_wrapper_keys = {
                key
                for key in mapping.keys()
                if key not in DOCUMENT_WRAPPER_KEYS
                and key not in DOCUMENT_PATH_KEYS
                and key not in {"metadata", "meta", "checksum", "type", "document_type", "module"}
            }

            if not non_wrapper_keys:
                return dict(payload)

        if isinstance(payload, (list, tuple)):
            if has_path_hint:
                return list(payload)

    return mapping


def document_mapping_from_value(value: Any) -> dict[str, Any]:
    """Baut ein Dokumentmapping aus Mapping/List/Row-Strukturen."""
    if value is None:
        return {}

    if is_dataclass(value):
        value = dataclass_shallow_dict(value)

    if isinstance(value, (list, tuple, set)):
        result: dict[str, Any] = {}

        for item in value:
            item_data = to_mapping(item)
            path = normalize_document_path(first_non_empty(*(item_data.get(key) for key in DOCUMENT_PATH_KEYS)))

            if not path:
                continue

            result[path] = unwrap_document_payload(item_data)

        return result

    if not isinstance(value, Mapping):
        data = to_mapping(value)
        if not data:
            return {}
        value = data

    mapping = dict(value)

    single_path = normalize_document_path(first_non_empty(*(mapping.get(key) for key in DOCUMENT_PATH_KEYS)))
    if single_path and any(key in mapping for key in DOCUMENT_WRAPPER_KEYS):
        return {single_path: unwrap_document_payload(mapping)}

    result = {}

    for raw_key, raw_value in mapping.items():
        normalized_key = normalize_document_path(raw_key)

        if not normalized_key:
            continue

        raw_value_data = to_mapping(raw_value)
        internal_path = normalize_document_path(
            first_non_empty(*(raw_value_data.get(key) for key in DOCUMENT_PATH_KEYS))
        )

        key = internal_path or normalized_key
        result[key] = unwrap_document_payload(raw_value)

    return result


def get_candidate_path_candidates(value: Any) -> list[Path]:
    """Ermittelt mögliche Package-Pfade aus Candidate/Summary/ReadResult."""
    data = to_mapping(value)
    summary = extract_summary_payload(value)

    read_result = first_non_empty(
        data.get("read_result"),
        data.get("read"),
        data.get("package_read_result"),
    )
    read_data = to_mapping(read_result)

    raw_values = [
        data.get("package_root"),
        data.get("source_path"),
        data.get("root"),
        data.get("path"),
        data.get("relative_package_root"),
        data.get("relative_path"),
        summary.get("package_root"),
        summary.get("source_path"),
        summary.get("root"),
        summary.get("path"),
        summary.get("relative_package_root"),
        summary.get("relative_path"),
        read_data.get("package_root"),
        read_data.get("source_path"),
        read_data.get("root"),
        read_data.get("path"),
        read_data.get("relative_package_root"),
        read_data.get("relative_path"),
    ]

    result: list[Path] = []

    for raw in raw_values:
        text = normalize_string(raw)

        if not text:
            continue

        path = Path(text)

        if not path.is_absolute():
            path = Path.cwd() / path

        candidates = [path]

        if path.suffix:
            candidates.append(path.parent)

        for candidate in candidates:
            try:
                resolved = candidate.resolve()
            except Exception:
                resolved = candidate

            if resolved not in result:
                result.append(resolved)

    return result


def find_existing_package_root(value: Any) -> Optional[Path]:
    """Findet einen existierenden Package-Root-Pfad."""
    for candidate in get_candidate_path_candidates(value):
        try:
            if candidate.is_file():
                candidate = candidate.parent

            if not candidate.exists() or not candidate.is_dir():
                continue

            if (candidate / "vplib.manifest.json").is_file():
                return candidate

            if (candidate / "manifest.json").is_file():
                return candidate

        except Exception:
            continue

    return None


def read_json_file(path: Path) -> dict[str, Any]:
    """Liest JSON-Datei defensiv als Dict."""
    try:
        if not path.is_file():
            return {}

        data = json.loads(path.read_text(encoding="utf-8"))

        if isinstance(data, Mapping):
            return dict(data)

        return {"value": data}

    except Exception:
        return {}


def load_documents_from_package_root(
    package_root: Path,
    *,
    limit: int = DEFAULT_DOCUMENT_LIMIT_FOR_DETAIL_PAYLOAD,
) -> dict[str, Any]:
    """Lädt JSON-Dokumente direkt aus einem Package-Root."""
    result: dict[str, Any] = {}

    try:
        root = package_root.resolve()
    except Exception:
        root = package_root

    if not root.exists() or not root.is_dir():
        return result

    preferred_files = [
        "vplib.manifest.json",
        "manifest.json",
        "family/identity.json",
        "family/classification.json",
        "editor/inventory.json",
        "variants/index.json",
        "variants/default.json",
        "vplib.modules.json",
    ]

    for relative_name in preferred_files:
        if len(result) >= limit:
            break

        path = root / relative_name
        payload = read_json_file(path)

        if payload:
            result[normalize_document_path(relative_name) or relative_name] = payload

    if len(result) >= limit:
        return result

    try:
        json_files = sorted(root.rglob("*.json"))
    except Exception:
        json_files = []

    for path in json_files:
        if len(result) >= limit:
            break

        try:
            relative_path = normalize_document_path(path.relative_to(root))
        except Exception:
            relative_path = normalize_document_path(path.name)

        if not relative_path or relative_path in result:
            continue

        payload = read_json_file(path)

        if payload:
            result[relative_path] = payload

    return result


def augment_documents_from_filesystem(
    value: Any,
    documents: Optional[Mapping[str, Any]] = None,
) -> dict[str, Any]:
    """Ergänzt Dokumente aus dem Dateisystem, falls Scanner unvollständig ist."""
    current = document_mapping_from_value(documents or {})
    has_manifest = bool(get_document(current, *MANIFEST_DOCUMENT_KEYS))
    package_root = find_existing_package_root(value)

    if package_root is None:
        return current

    filesystem_documents = load_documents_from_package_root(package_root)

    if not filesystem_documents:
        return current

    merged = dict(filesystem_documents)
    merged.update(current)

    if not has_manifest:
        manifest = get_document(filesystem_documents, *MANIFEST_DOCUMENT_KEYS)
        if manifest:
            merged["vplib.manifest.json"] = manifest

    return merged


def extract_documents_from_any(value: Any) -> dict[str, Any]:
    """Extrahiert Package-Dokumente aus verschiedenen Pipeline-Formen."""
    data = to_mapping(value)

    direct = first_non_empty(
        data.get("documents"),
        data.get("raw_documents"),
        data.get("document_mapping"),
        data.get("loaded_documents"),
    )

    direct_documents = document_mapping_from_value(direct)
    if direct_documents:
        return augment_documents_from_filesystem(value, direct_documents)

    read_result = first_non_empty(
        data.get("read_result"),
        data.get("read"),
        data.get("package_read_result"),
    )
    read_data = to_mapping(read_result)

    nested = first_non_empty(
        read_data.get("documents"),
        read_data.get("raw_documents"),
        read_data.get("loaded_documents"),
        read_data.get("document_mapping"),
    )

    nested_documents = document_mapping_from_value(nested)
    if nested_documents:
        return augment_documents_from_filesystem(value, nested_documents)

    item = first_non_empty(data.get("item"), data.get("summary"), data.get("library_item"), data.get("block"))
    item_data = to_mapping(item)

    item_documents = first_non_empty(
        item_data.get("documents"),
        item_data.get("raw_documents"),
        item_data.get("document_mapping"),
        item_data.get("loaded_documents"),
    )

    item_document_mapping = document_mapping_from_value(item_documents)
    if item_document_mapping:
        return augment_documents_from_filesystem(value, item_document_mapping)

    return augment_documents_from_filesystem(value, {})


def get_document(documents: Mapping[str, Any], *keys: str) -> dict[str, Any]:
    """Liest ein Dokument aus einem Mapping."""
    normalized_documents = document_mapping_from_value(documents)

    for key in keys:
        normalized_key = normalize_document_path(key)
        if not normalized_key:
            continue
        value = normalized_documents.get(normalized_key)
        if isinstance(value, Mapping):
            return dict(unwrap_document_payload(value))

    for key in keys:
        normalized_key = normalize_document_path(key)
        if not normalized_key:
            continue

        suffix = f"/{normalized_key}"

        for document_key, value in normalized_documents.items():
            candidate_key = normalize_document_path(document_key)
            if not candidate_key:
                continue
            if candidate_key == normalized_key or candidate_key.endswith(suffix):
                payload = unwrap_document_payload(value)
                if isinstance(payload, Mapping):
                    return dict(payload)

    return {}


def extract_manifest(documents: Mapping[str, Any]) -> dict[str, Any]:
    return get_document(documents, *MANIFEST_DOCUMENT_KEYS)


def extract_identity(documents: Mapping[str, Any]) -> dict[str, Any]:
    return get_document(documents, *IDENTITY_DOCUMENT_KEYS)


def extract_classification(documents: Mapping[str, Any]) -> dict[str, Any]:
    return get_document(documents, *CLASSIFICATION_DOCUMENT_KEYS)


def extract_inventory(documents: Mapping[str, Any]) -> dict[str, Any]:
    return get_document(documents, *INVENTORY_DOCUMENT_KEYS)


def extract_modules(documents: Mapping[str, Any]) -> dict[str, Any]:
    return get_document(documents, *MODULES_DOCUMENT_KEYS)


def extract_validation_payload(value: Any) -> dict[str, Any]:
    data = to_mapping(value)

    validation = first_non_empty(
        data.get("validation"),
        data.get("validation_result"),
        data.get("validation_summary"),
    )

    validation_data = to_mapping(validation)
    if validation_data:
        return validation_data

    item = first_non_empty(data.get("item"), data.get("summary"), data.get("library_item"))
    item_data = to_mapping(item)

    return to_mapping(item_data.get("validation"))


def extract_fingerprint_payload(value: Any) -> dict[str, Any]:
    data = to_mapping(value)

    fingerprint = first_non_empty(
        data.get("fingerprint"),
        data.get("fingerprint_result"),
        data.get("package_fingerprint"),
    )

    return to_mapping(fingerprint)


def extract_summary_payload(value: Any) -> dict[str, Any]:
    data = to_mapping(value)

    summary = first_non_empty(
        data.get("summary"),
        data.get("item"),
        data.get("library_item"),
        data.get("block"),
    )

    summary_data = to_mapping(summary)

    if summary_data:
        return summary_data

    return data


def extract_source_path(value: Any, documents: Optional[Mapping[str, Any]] = None) -> Optional[str]:
    data = to_mapping(value)
    summary = extract_summary_payload(value)
    docs = documents or extract_documents_from_any(value)
    manifest = extract_manifest(docs)
    package_root = find_existing_package_root(value)

    return normalize_string(
        first_non_empty(
            data.get("source_path"),
            data.get("relative_package_root"),
            data.get("relative_path"),
            summary.get("source_path"),
            summary.get("relative_package_root"),
            manifest.get("source_path"),
            str(package_root) if package_root else None,
        )
    )


def extract_package_root(value: Any) -> Optional[str]:
    data = to_mapping(value)
    summary = extract_summary_payload(value)
    package_root = find_existing_package_root(value)

    return normalize_string(
        first_non_empty(
            data.get("package_root"),
            data.get("root"),
            data.get("path"),
            summary.get("package_root"),
            summary.get("root"),
            summary.get("path"),
            str(package_root) if package_root else None,
        )
    )


def extract_revision_hash(value: Any) -> Optional[str]:
    data = to_mapping(value)
    summary = extract_summary_payload(value)
    fingerprint = extract_fingerprint_payload(value)
    documents = extract_documents_from_any(value)

    explicit = normalize_string(
        first_non_empty(
            data.get("revision_hash"),
            data.get("hash"),
            data.get("content_hash"),
            summary.get("revision_hash"),
            fingerprint.get("revision_hash"),
            fingerprint.get("hash"),
            fingerprint.get("content_hash"),
        )
    )

    if explicit:
        return explicit

    # Defensive fallback: if fingerprint is missing, hash package documents.
    if documents:
        try:
            encoded = json.dumps(json_safe(documents), sort_keys=True, ensure_ascii=False).encode("utf-8")
            return hashlib_sha256_hex(encoded)
        except Exception:
            return None

    return None


def hashlib_sha256_hex(value: bytes) -> str:
    import hashlib

    return hashlib.sha256(value).hexdigest()


def extract_vplib_uid(value: Any, documents: Optional[Mapping[str, Any]] = None) -> Optional[str]:
    data = to_mapping(value)
    summary = extract_summary_payload(value)
    docs = documents or extract_documents_from_any(value)
    manifest = extract_manifest(docs)
    identity = extract_identity(docs)

    return normalize_vplib_uid(
        first_non_empty(
            data.get("vplib_uid"),
            data.get("vplibUid"),
            data.get("vplib_uid_v1"),
            data.get("uid"),
            summary.get("vplib_uid"),
            summary.get("vplibUid"),
            summary.get("vplib_uid_v1"),
            summary.get("uid"),
            manifest.get("vplib_uid"),
            manifest.get("vplibUid"),
            manifest.get("vplib_uid_v1"),
            manifest.get("uid"),
            identity.get("vplib_uid"),
            identity.get("vplibUid"),
            identity.get("uid"),
        )
    )


def extract_family_id(value: Any, documents: Optional[Mapping[str, Any]] = None) -> Optional[str]:
    data = to_mapping(value)
    summary = extract_summary_payload(value)
    docs = documents or extract_documents_from_any(value)
    manifest = extract_manifest(docs)
    identity = extract_identity(docs)

    return normalize_string(
        first_non_empty(
            data.get("family_id"),
            summary.get("family_id"),
            manifest.get("family_id"),
            identity.get("family_id"),
            identity.get("id"),
        )
    )


def extract_package_id(value: Any, documents: Optional[Mapping[str, Any]] = None) -> Optional[str]:
    data = to_mapping(value)
    summary = extract_summary_payload(value)
    docs = documents or extract_documents_from_any(value)
    manifest = extract_manifest(docs)

    return normalize_string(
        first_non_empty(
            data.get("package_id"),
            summary.get("package_id"),
            manifest.get("package_id"),
            manifest.get("id"),
        )
    )


def extract_variant_ids(value: Any, documents: Optional[Mapping[str, Any]] = None) -> list[str]:
    data = to_mapping(value)
    summary = extract_summary_payload(value)

    raw = first_non_empty(
        data.get("variant_ids"),
        summary.get("variant_ids"),
        summary.get("variants"),
        data.get("variants"),
    )

    if isinstance(raw, Mapping):
        variants = raw.get("items") or raw.get("variants") or raw.get("ids") or raw.keys()
    else:
        variants = raw or []

    result: list[str] = []

    for item in variants:
        if isinstance(item, Mapping):
            variant_id = first_non_empty(item.get("variant_id"), item.get("id"), item.get("key"))
        else:
            variant_id = item

        text = normalize_string(variant_id)
        if text and text not in result:
            result.append(text)

    docs = documents or extract_documents_from_any(value)
    index_doc = get_document(docs, "variants/index.json")

    index_variants = first_non_empty(
        index_doc.get("variants"),
        index_doc.get("items"),
        index_doc.get("variant_ids"),
    )

    if isinstance(index_variants, Mapping):
        index_variants = index_variants.keys()

    for item in index_variants or []:
        if isinstance(item, Mapping):
            variant_id = first_non_empty(item.get("variant_id"), item.get("id"), item.get("key"))
        else:
            variant_id = item

        text = normalize_string(variant_id)
        if text and text not in result:
            result.append(text)

    if not result:
        default_doc = get_document(docs, "variants/default.json")
        default_id = normalize_string(
            first_non_empty(
                default_doc.get("variant_id"),
                default_doc.get("id"),
                "default" if default_doc else None,
            )
        )
        if default_id:
            result.append(default_id)

    return result


def candidate_is_valid(value: Any) -> bool:
    data = to_mapping(value)
    summary = extract_summary_payload(value)
    validation = extract_validation_payload(value)

    explicit = first_non_empty(
        data.get("valid"),
        data.get("is_valid"),
        summary.get("valid"),
        summary.get("is_valid"),
        validation.get("valid"),
        validation.get("ok"),
    )

    if explicit is not None:
        return safe_bool(explicit, False)

    status = str(
        first_non_empty(
            data.get("status"),
            summary.get("status"),
            validation.get("status"),
            validation.get("validation_status"),
        )
        or ""
    ).strip().lower()

    if status in {"valid", "ok", "published", "active", "success"}:
        return True

    if status in {"invalid", "error", "fatal", "failed", "duplicate"}:
        return False

    error_count = safe_int(
        first_non_empty(
            data.get("error_count"),
            summary.get("error_count"),
            validation.get("error_count"),
            validation.get("errors_count"),
            validation.get("fatal_count"),
        ),
        0,
    )

    fatal_count = safe_int(validation.get("fatal_count"), 0)

    return error_count == 0 and fatal_count == 0


# ---------------------------------------------------------------------------
# Payload builders
# ---------------------------------------------------------------------------

def build_family_upsert_payload(value: Any) -> dict[str, Any]:
    data = to_mapping(value)
    summary = extract_summary_payload(value)
    documents = extract_documents_from_any(value)

    manifest = extract_manifest(documents)
    identity = extract_identity(documents)
    classification = extract_classification(documents)
    inventory = extract_inventory(documents)
    package_root = extract_package_root(value)

    uid = extract_vplib_uid(value, documents)
    family_id = extract_family_id(value, documents)
    package_id = extract_package_id(value, documents)

    family_slug = first_non_empty(
        data.get("family_slug"),
        data.get("slug"),
        summary.get("family_slug"),
        summary.get("slug"),
        manifest.get("family_slug"),
        manifest.get("slug"),
        identity.get("family_slug"),
        identity.get("slug"),
        Path(package_root).name if package_root else None,
    )

    label = first_non_empty(
        data.get("label"),
        data.get("family_name"),
        summary.get("label"),
        summary.get("family_name"),
        manifest.get("label"),
        manifest.get("family_name"),
        manifest.get("name"),
        inventory.get("label"),
        inventory.get("name"),
        identity.get("label"),
        identity.get("name"),
        family_slug,
        family_id,
    )

    manifest_classification = to_mapping(manifest.get("classification"))

    classification_payload = first_non_empty(
        summary.get("classification"),
        data.get("classification"),
        classification,
        manifest_classification,
        {},
    )

    classification_data = to_mapping(classification_payload)

    domain = first_non_empty(
        data.get("domain"),
        summary.get("domain"),
        classification_data.get("domain"),
        classification_data.get("domain_id"),
        manifest_classification.get("domain"),
    )
    category = first_non_empty(
        data.get("category"),
        summary.get("category"),
        classification_data.get("category"),
        classification_data.get("category_id"),
        manifest_classification.get("category"),
    )
    subcategory = first_non_empty(
        data.get("subcategory"),
        summary.get("subcategory"),
        classification_data.get("subcategory"),
        classification_data.get("subcategory_id"),
        manifest_classification.get("subcategory"),
    )

    variant_ids = extract_variant_ids(value, documents)
    default_variant_id = first_non_empty(
        summary.get("default_variant_id"),
        data.get("default_variant_id"),
        inventory.get("default_variant_id"),
        variant_ids[0] if variant_ids else None,
    )

    return {
        "vplib_uid": uid,
        "family_id": family_id,
        "package_id": package_id,
        "family_slug": family_slug,
        "slug": family_slug,
        "label": label,
        "name": label,
        "title": label,
        "description": first_non_empty(
            data.get("description"),
            summary.get("description"),
            manifest.get("description"),
            inventory.get("description"),
            identity.get("description"),
        ),
        "object_kind": first_non_empty(
            data.get("object_kind"),
            summary.get("object_kind"),
            manifest.get("object_kind"),
            identity.get("object_kind"),
            inventory.get("object_kind"),
        ),
        "domain": domain,
        "category": category,
        "subcategory": subcategory,
        "source_path": extract_source_path(value, documents),
        "package_root": package_root,
        "classification_path": first_non_empty(
            summary.get("classification_path"),
            data.get("classification_path"),
            classification_data.get("classification_path"),
            classification_data.get("path"),
            manifest_classification.get("path"),
        ),
        "source_scope": "imported",
        "active": True,
        "visible": safe_bool(
            first_non_empty(
                data.get("visible"),
                summary.get("visible"),
                manifest.get("visible"),
                inventory.get("visible"),
            ),
            True,
        ),
        "enabled": safe_bool(
            first_non_empty(
                data.get("enabled"),
                summary.get("enabled"),
                manifest.get("enabled"),
                inventory.get("enabled"),
            ),
            True,
        ),
        "publication_status": "published",
        "status": "published",
        "default_variant_id": default_variant_id,
        "variant_count": len(variant_ids),
        "revision_hash": extract_revision_hash(value),
        "scanned_at": utcnow(),
        "published_at": utcnow(),
        "manifest_payload": manifest,
        "classification_payload": classification_data or manifest_classification,
        "metadata": {
            "classification": classification_data or manifest_classification,
            "inventory": inventory,
            "manifest": manifest,
            "source": LIBRARY_DB_SYNC_SERVICE_NAME,
        },
        "summary_payload": json_safe(
            {
                **summary,
                "vplib_uid": uid,
                "family_id": family_id,
                "package_id": package_id,
                "family_slug": family_slug,
                "label": label,
                "object_kind": first_non_empty(
                    data.get("object_kind"),
                    summary.get("object_kind"),
                    manifest.get("object_kind"),
                    identity.get("object_kind"),
                    inventory.get("object_kind"),
                ),
                "domain": domain,
                "category": category,
                "subcategory": subcategory,
            }
        ),
        "payload": json_safe(data),
    }


def build_revision_upsert_payload(value: Any, *, scan_run_id: Any = None) -> dict[str, Any]:
    data = to_mapping(value)
    summary = extract_summary_payload(value)
    documents = extract_documents_from_any(value)
    manifest = extract_manifest(documents)
    modules = extract_modules(documents)
    identity = extract_identity(documents)
    classification = extract_classification(documents)
    validation = extract_validation_payload(value)

    revision_hash = extract_revision_hash(value)

    detail_payload = first_non_empty(
        data.get("detail"),
        data.get("detail_payload"),
        data.get("raw_detail"),
        {},
    )

    return {
        "vplib_uid": extract_vplib_uid(value, documents),
        "family_id": extract_family_id(value, documents),
        "package_id": extract_package_id(value, documents),
        "revision_hash": revision_hash,
        "version": first_non_empty(
            data.get("version"),
            data.get("package_version"),
            summary.get("package_version"),
            manifest.get("package_version"),
            manifest.get("version"),
        ),
        "package_version": first_non_empty(
            data.get("package_version"),
            summary.get("package_version"),
            manifest.get("package_version"),
            manifest.get("version"),
        ),
        "schema_version": first_non_empty(
            data.get("schema_version"),
            summary.get("schema_version"),
            manifest.get("schema_version"),
        ),
        "validation_status": first_non_empty(
            validation.get("status"),
            validation.get("validation_status"),
            "valid" if candidate_is_valid(value) else "invalid",
        ),
        "publication_status": "published",
        "scan_run_id": scan_run_id,
        "source_path": extract_source_path(value, documents),
        "created_at": utcnow(),
        "published_at": utcnow(),
        "manifest_payload": manifest,
        "modules_payload": modules,
        "family_payload": identity,
        "classification_payload": classification,
        "summary_payload": json_safe(summary),
        "detail_payload": json_safe(detail_payload),
        "raw_documents": json_safe(documents),
        "documents": json_safe(documents),
        "document_bundle": {
            "manifest": manifest,
            "modules": modules,
            "family": identity,
            "classification": classification,
            "documents": documents,
        },
        "validation_payload": json_safe(validation),
        "metadata": {
            "source": LIBRARY_DB_SYNC_SERVICE_NAME,
            "document_count": len(documents),
            "manifest": manifest,
            "revision_hash": revision_hash,
        },
        "payload": json_safe(data),
    }


def extract_variant_payloads(value: Any) -> list[dict[str, Any]]:
    documents = extract_documents_from_any(value)
    uid = extract_vplib_uid(value, documents)
    revision_hash = extract_revision_hash(value)

    variants: list[dict[str, Any]] = []
    seen: set[str] = set()

    data = to_mapping(value)
    summary = extract_summary_payload(value)

    raw_variants = first_non_empty(
        data.get("variants"),
        summary.get("variants"),
    )

    if isinstance(raw_variants, Mapping):
        raw_variants = raw_variants.get("items") or raw_variants.get("variants") or raw_variants.values()

    for index, raw_variant in enumerate(raw_variants or []):
        variant_data = to_mapping(raw_variant)
        variant_id = normalize_string(first_non_empty(variant_data.get("variant_id"), variant_data.get("id"), variant_data.get("key")))

        if not variant_id or variant_id in seen:
            continue

        seen.add(variant_id)
        variants.append(
            {
                "vplib_uid": uid,
                "variant_id": variant_id,
                "variant_key": variant_id,
                "label": first_non_empty(variant_data.get("label"), variant_data.get("name"), variant_id),
                "description": variant_data.get("description"),
                "is_default": safe_bool(variant_data.get("is_default"), index == 0),
                "enabled": safe_bool(variant_data.get("enabled"), True),
                "visible": safe_bool(variant_data.get("visible"), True),
                "active": safe_bool(variant_data.get("active"), True),
                "sort_order": safe_int(variant_data.get("sort_order"), index),
                "revision_hash": revision_hash,
                "definition_values": variant_data.get("definition_values") or variant_data.get("definition_values_json") or variant_data.get("overrides") or {},
                "summary": variant_data.get("summary") or {},
                "payload": json_safe(variant_data),
                "resolved_payload": json_safe(variant_data.get("resolved_payload") or variant_data.get("resolved") or {}),
                "metadata": {},
            }
        )

    index_doc = get_document(documents, "variants/index.json")
    default_doc = get_document(documents, "variants/default.json")

    default_variant_id = normalize_string(
        first_non_empty(
            index_doc.get("default_variant_id"),
            default_doc.get("variant_id"),
            default_doc.get("id"),
            "default" if default_doc else None,
        )
    )

    for path, document in documents.items():
        normalized_path = str(path).replace("\\", "/")

        if not normalized_path.startswith("variants/") or not normalized_path.endswith(".json"):
            continue

        if normalized_path == "variants/index.json":
            continue

        document_data = to_mapping(document)
        variant_id = normalize_string(
            first_non_empty(
                document_data.get("variant_id"),
                document_data.get("id"),
                normalized_path.removeprefix("variants/").removesuffix(".json"),
            )
        )

        if not variant_id or variant_id in seen:
            continue

        seen.add(variant_id)
        variants.append(
            {
                "vplib_uid": uid,
                "variant_id": variant_id,
                "variant_key": variant_id,
                "label": first_non_empty(document_data.get("label"), document_data.get("name"), variant_id),
                "description": document_data.get("description"),
                "is_default": variant_id == default_variant_id or normalized_path == "variants/default.json",
                "enabled": safe_bool(document_data.get("enabled"), True),
                "visible": safe_bool(document_data.get("visible"), True),
                "active": safe_bool(document_data.get("active"), True),
                "sort_order": len(variants),
                "revision_hash": revision_hash,
                "definition_values": document_data.get("definition_values") or document_data.get("overrides") or {},
                "summary": document_data.get("summary") or {},
                "payload": json_safe(document_data),
                "resolved_payload": json_safe(document_data.get("resolved_payload") or {}),
                "metadata": {
                    "document_path": normalized_path,
                },
            }
        )

    for variant_id in extract_variant_ids(value, documents):
        if variant_id in seen:
            continue

        seen.add(variant_id)
        variants.append(
            {
                "vplib_uid": uid,
                "variant_id": variant_id,
                "variant_key": variant_id,
                "label": variant_id,
                "description": None,
                "is_default": variant_id == default_variant_id or not variants,
                "enabled": True,
                "visible": True,
                "active": True,
                "sort_order": len(variants),
                "revision_hash": revision_hash,
                "definition_values": {},
                "summary": {},
                "payload": {},
                "resolved_payload": {},
                "metadata": {
                    "source": "variant_ids",
                },
            }
        )

    return variants


def extract_asset_payloads(value: Any) -> list[dict[str, Any]]:
    documents = extract_documents_from_any(value)
    data = to_mapping(value)
    summary = extract_summary_payload(value)
    uid = extract_vplib_uid(value, documents)
    revision_hash = extract_revision_hash(value)

    raw_assets = first_non_empty(
        data.get("assets"),
        summary.get("assets"),
        data.get("asset_refs"),
        summary.get("asset_refs"),
        {},
    )

    assets: list[dict[str, Any]] = []

    if isinstance(raw_assets, Mapping):
        iterable = raw_assets.items()
    elif isinstance(raw_assets, list):
        iterable = enumerate(raw_assets)
    else:
        iterable = []

    for index_or_role, asset_value in iterable:
        if asset_value is None:
            continue

        if isinstance(asset_value, Mapping):
            asset_data = dict(asset_value)
        else:
            asset_data = {"path": asset_value}

        role = asset_data.get("role") or index_or_role

        assets.append(
            {
                "vplib_uid": uid,
                "asset_kind": asset_data.get("asset_kind") or asset_data.get("kind") or asset_data.get("asset_type") or asset_data.get("type"),
                "role": role,
                "asset_type": asset_data.get("asset_type") or asset_data.get("type"),
                "path": first_non_empty(asset_data.get("path"), asset_data.get("relative_path"), asset_data.get("uri")),
                "relative_path": asset_data.get("relative_path") or asset_data.get("path"),
                "uri": asset_data.get("uri") or asset_data.get("url"),
                "url": asset_data.get("url"),
                "label": asset_data.get("label") or role,
                "filename": asset_data.get("filename"),
                "mime_type": asset_data.get("mime_type") or asset_data.get("content_type"),
                "checksum": asset_data.get("checksum") or asset_data.get("sha256"),
                "sha256": asset_data.get("sha256") or asset_data.get("checksum"),
                "size_bytes": asset_data.get("size_bytes"),
                "revision_hash": revision_hash,
                "payload": json_safe(asset_data),
                "metadata": {},
            }
        )

    return assets


def extract_document_payloads(value: Any) -> list[dict[str, Any]]:
    documents = extract_documents_from_any(value)
    uid = extract_vplib_uid(value, documents)
    revision_hash = extract_revision_hash(value)

    payloads: list[dict[str, Any]] = []

    for path, document in documents.items():
        relative_path = str(path).replace("\\", "/").strip()

        if not relative_path:
            continue

        module = relative_path.split("/", 1)[0] if "/" in relative_path else "root"

        payloads.append(
            {
                "vplib_uid": uid,
                "relative_path": relative_path,
                "field_key": relative_path,
                "title": relative_path,
                "document_type": "json" if relative_path.endswith(".json") else None,
                "document_kind": "source_document",
                "module": module,
                "revision_hash": revision_hash,
                "payload": {
                    "path": relative_path,
                    "content": json_safe(document),
                },
                "metadata": {},
            }
        )

    return payloads


def extract_issue_payloads(value: Any) -> list[dict[str, Any]]:
    data = to_mapping(value)
    validation = extract_validation_payload(value)
    documents = extract_documents_from_any(value)

    uid = extract_vplib_uid(value, documents)
    family_id = extract_family_id(value, documents)
    package_id = extract_package_id(value, documents)
    revision_hash = extract_revision_hash(value)

    raw_issues = first_non_empty(
        data.get("issues"),
        data.get("messages"),
        validation.get("issues"),
        validation.get("messages"),
        validation.get("errors"),
        [],
    )

    if isinstance(raw_issues, Mapping):
        raw_issues = raw_issues.values()

    issues: list[dict[str, Any]] = []

    for raw_issue in raw_issues or []:
        issue_data = to_mapping(raw_issue)

        if not issue_data:
            issue_data = {"message": str(raw_issue)}

        severity = first_non_empty(
            issue_data.get("severity"),
            issue_data.get("level"),
            "error" if issue_data.get("error") else "warning",
        )

        issues.append(
            {
                "vplib_uid": uid,
                "family_id": family_id,
                "package_id": package_id,
                "revision_hash": revision_hash,
                "severity": severity,
                "code": issue_data.get("code"),
                "message": first_non_empty(issue_data.get("message"), issue_data.get("error"), str(raw_issue)),
                "path": issue_data.get("path"),
                "field": issue_data.get("field"),
                "scope": issue_data.get("scope"),
                "source_path": extract_source_path(value, documents),
                "payload": json_safe(issue_data),
                "metadata": {},
            }
        )

    return issues


def build_publish_payload_from_candidate(candidate: Any) -> dict[str, Any]:
    """Baut CreativeLibraryService.publish_bundle-kompatiblen Payload."""
    documents = extract_documents_from_any(candidate)
    manifest = extract_manifest(documents)
    identity = extract_identity(documents)
    classification = extract_classification(documents)
    modules = extract_modules(documents)

    family_payload = build_family_upsert_payload(candidate)
    revision_payload = build_revision_upsert_payload(candidate)

    variants = extract_variant_payloads(candidate)
    assets = extract_asset_payloads(candidate)
    document_rows = extract_document_payloads(candidate)

    return {
        "schema_version": "library_db_sync_service.publish_payload.v1",
        "source": LIBRARY_DB_SYNC_SERVICE_NAME,
        "vplib_uid": family_payload.get("vplib_uid"),
        "family_id": family_payload.get("family_id"),
        "package_id": family_payload.get("package_id"),
        "title": family_payload.get("label"),
        "label": family_payload.get("label"),
        "name": family_payload.get("label"),
        "description": family_payload.get("description"),
        "source_path": family_payload.get("source_path"),
        "package_root": family_payload.get("package_root"),
        "classification_path": family_payload.get("classification_path"),
        "domain": family_payload.get("domain"),
        "category": family_payload.get("category"),
        "subcategory": family_payload.get("subcategory"),
        "object_kind": family_payload.get("object_kind"),
        "revision_hash": revision_payload.get("revision_hash"),
        "package_version": revision_payload.get("package_version"),
        "manifest_payload": manifest or family_payload.get("manifest_payload") or {},
        "modules_payload": modules,
        "family_payload": identity,
        "classification_payload": classification or family_payload.get("classification_payload") or {},
        "generator_payload": {
            "component": LIBRARY_DB_SYNC_SERVICE_NAME,
            "version": __version__,
            "candidate_summary": json_safe(extract_summary_payload(candidate)),
        },
        "validation_payload": extract_validation_payload(candidate),
        "variants": variants,
        "assets": assets,
        "documents": document_rows,
        "document_bundle": {
            "manifest": manifest,
            "modules": modules,
            "family": identity,
            "classification": classification,
            "documents": documents,
            "variants": variants,
            "assets": assets,
        },
        "payload": {
            "candidate": json_safe(candidate),
            "family": family_payload,
            "revision": revision_payload,
        },
        "metadata": {
            "source": LIBRARY_DB_SYNC_SERVICE_NAME,
            "document_count": len(documents),
        },
    }


def extract_pipeline_candidates(scan_result: Any) -> list[Any]:
    """Extrahiert Sync-Kandidaten ohne tiefe Vollserialisierung."""
    if scan_result is None:
        return []

    if isinstance(scan_result, (list, tuple)):
        return list(scan_result)

    for key in (
        "pipeline_entries",
        "entries",
        "candidates",
        "items",
        "valid_items",
        "blocks",
        "results",
    ):
        value = get_direct_value(scan_result, key)

        if isinstance(value, (list, tuple)):
            return list(value)

    combined: list[Any] = []

    for key in ("valid_items", "invalid_items", "skipped_items"):
        value = get_direct_value(scan_result, key)
        if isinstance(value, (list, tuple)):
            combined.extend(value)

    if combined:
        return combined

    for key in ("scan_result", "result", "library_scan_result"):
        nested = get_direct_value(scan_result, key)
        if nested is not None and nested is not scan_result:
            nested_candidates = extract_pipeline_candidates(nested)
            if nested_candidates:
                return nested_candidates

    data = to_mapping(scan_result)

    for key in (
        "pipeline_entries",
        "entries",
        "candidates",
        "items",
        "valid_items",
        "blocks",
        "results",
    ):
        value = data.get(key)
        if isinstance(value, (list, tuple)):
            return list(value)

    payload = data.get("payload")
    if isinstance(payload, Mapping):
        return extract_pipeline_candidates(payload)

    return []


# ---------------------------------------------------------------------------
# Service implementation
# ---------------------------------------------------------------------------

class LibraryDbSyncService:
    """Orchestriert ScanResult/PipelineResult -> creative_library DB."""

    def __init__(
        self,
        *,
        repository: Any = None,
        repository_factory: Any = None,
        creative_service: Any = None,
        creative_service_factory: Any = None,
        scan_service: Any = None,
        config: Optional[LibraryDbSyncServiceConfig] = None,
    ) -> None:
        if config is None:
            config = LibraryDbSyncServiceConfig(
                repository=repository,
                repository_factory=repository_factory,
                creative_service=creative_service,
                creative_service_factory=creative_service_factory,
                scan_service=scan_service,
                enabled=env_bool(ENV_SYNC_ENABLED, DEFAULT_SYNC_ENABLED),
                strict=env_bool(ENV_SYNC_STRICT, DEFAULT_SYNC_STRICT),
                autocommit=env_bool(ENV_SYNC_AUTOCOMMIT, DEFAULT_SYNC_AUTOCOMMIT),
                mark_missing_deleted=env_bool(
                    ENV_SYNC_MARK_MISSING_DELETED,
                    DEFAULT_SYNC_MARK_MISSING_DELETED,
                ),
                continue_on_candidate_error=env_bool(
                    ENV_SYNC_CONTINUE_ON_CANDIDATE_ERROR,
                    DEFAULT_SYNC_CONTINUE_ON_CANDIDATE_ERROR,
                ),
                include_raw_documents=env_bool(
                    ENV_SYNC_INCLUDE_RAW_DOCUMENTS,
                    DEFAULT_SYNC_INCLUDE_RAW_DOCUMENTS,
                ),
            )

        self.config = config
        self._repository = repository if repository is not None else config.repository
        self._repository_factory = repository_factory if repository_factory is not None else config.repository_factory
        self._creative_service = creative_service if creative_service is not None else config.creative_service
        self._creative_service_factory = creative_service_factory if creative_service_factory is not None else config.creative_service_factory
        self._scan_service = scan_service if scan_service is not None else config.scan_service

    # ------------------------------------------------------------------
    # Dependency loading
    # ------------------------------------------------------------------

    def get_repository(self) -> Any:
        """Liefert das Repository für creative_library DB-Zugriffe."""
        if self._repository is not None:
            return self._repository

        if callable(self._repository_factory):
            self._repository = self._repository_factory()
            return self._repository

        module = safe_import_module(self.config.repository_import_path, required=False)
        if module is None:
            module = import_first(REPOSITORY_IMPORT_PATHS, required=True)

        for factory_name in (
            "create_creative_library_repository",
            "get_creative_library_repository",
            "get_default_creative_library_repository",
        ):
            factory = getattr(module, factory_name, None)
            if callable(factory):
                self._repository = factory()
                return self._repository

        repo_class = getattr(module, "CreativeLibraryRepository", None)
        if repo_class is not None:
            self._repository = repo_class()
            return self._repository

        raise LibraryDbSyncImportError(
            "No repository factory found. Expected create_creative_library_repository "
            "or CreativeLibraryRepository."
        )

    def get_creative_service(self, *, repository: Any = None) -> Any:
        """Liefert CreativeLibraryService für publish_bundle, wenn verfügbar."""
        if repository is None and self._creative_service is not None:
            return self._creative_service

        if callable(self._creative_service_factory):
            service = self._creative_service_factory(repository=repository)
            if repository is None:
                self._creative_service = service
            return service

        module = safe_import_module(self.config.creative_service_import_path, required=False)
        if module is None:
            module = import_first(CREATIVE_SERVICE_IMPORT_PATHS, required=False)

        if module is None:
            return None

        for factory_name in (
            "create_creative_library_service",
            "create_library_service",
            "create_published_library_service",
        ):
            factory = getattr(module, factory_name, None)
            if callable(factory):
                try:
                    service = factory(repository=repository)
                except TypeError:
                    service = factory()
                if repository is None:
                    self._creative_service = service
                return service

        for class_name in (
            "CreativeLibraryService",
            "LibraryService",
            "PublishedLibraryService",
        ):
            service_class = getattr(module, class_name, None)
            if service_class is not None:
                try:
                    service = service_class(repository=repository)
                except TypeError:
                    service = service_class()
                if repository is None:
                    self._creative_service = service
                return service

        return None

    def get_scan_service(self) -> Any:
        """Liefert das dateibasierte Library-Scan-Service-Modul oder Objekt."""
        if self._scan_service is not None:
            return self._scan_service

        module = safe_import_module(self.config.scan_service_import_path, required=False)
        if module is None:
            module = import_first(SCAN_SERVICE_IMPORT_PATHS, required=True)

        self._scan_service = module
        return module

    # ------------------------------------------------------------------
    # Public sync entrypoints
    # ------------------------------------------------------------------

    def sync_library_source(
        self,
        *,
        source_root: Optional[str] = None,
        force_refresh: bool = True,
        triggered_by: Optional[str] = None,
        publish_valid_only: Optional[bool] = None,
        mark_missing_deleted: Optional[bool] = None,
        include_raw_documents: Optional[bool] = None,
        scan_options: Optional[Mapping[str, Any]] = None,
    ) -> LibrarySyncResult:
        """Führt einen dateibasierten Scan aus und synchronisiert das Ergebnis in DB."""
        self._assert_enabled()

        started_ms = monotonic_ms()

        run_info = LibrarySyncRunInfo(
            mode=DEFAULT_SYNC_MODE,
            source=DEFAULT_SYNC_SOURCE,
            target=DEFAULT_SYNC_TARGET,
            source_root=source_root,
            triggered_by=triggered_by,
            force_refresh=force_refresh,
            publish_valid_only=self.config.publish_valid_only if publish_valid_only is None else bool(publish_valid_only),
            mark_missing_deleted=self.config.mark_missing_deleted if mark_missing_deleted is None else bool(mark_missing_deleted),
            started_at=utcnow(),
            metadata={"scan_options": dict(scan_options or {})},
        )

        repository = self.get_repository()
        scan_run = None

        try:
            scan_run = self._create_scan_run(repository, run_info)
            run_info.scan_run_id = self._get_object_id(scan_run)

            scan_result = self._run_scan(
                source_root=source_root,
                force_refresh=force_refresh,
                include_raw_documents=self.config.include_raw_documents if include_raw_documents is None else bool(include_raw_documents),
                scan_options=scan_options or {},
            )

            result = self.sync_scan_result_to_db(
                scan_result,
                scan_run=scan_run,
                run_info=run_info,
                publish_valid_only=publish_valid_only,
                mark_missing_deleted=mark_missing_deleted,
                repository=repository,
            )

            result.run.duration_ms = duration_ms(started_ms)
            result.finish(message="Library DB sync finished.")

            self._finish_scan_run(repository, scan_run, result)

            if self.config.autocommit:
                self._commit(repository)

            return result

        except Exception as exc:
            self._rollback(repository)

            if scan_run is not None:
                try:
                    self._fail_scan_run(repository, scan_run, exc)
                    if self.config.autocommit:
                        self._commit(repository)
                except Exception:
                    self._rollback(repository)

            return build_error_sync_result(
                exc,
                message="Library DB sync failed.",
                run=run_info,
                include_traceback=True,
            )

    def sync_scan_result_to_db(
        self,
        scan_result: Any,
        *,
        scan_run: Any = None,
        run_info: Optional[LibrarySyncRunInfo] = None,
        publish_valid_only: Optional[bool] = None,
        mark_missing_deleted: Optional[bool] = None,
        repository: Any = None,
    ) -> LibrarySyncResult:
        """Synchronisiert ein vorhandenes Scan-/Pipeline-Ergebnis in die Datenbank."""
        self._assert_enabled()

        repository = repository or self.get_repository()

        run_info = run_info or LibrarySyncRunInfo(
            mode=DEFAULT_SYNC_MODE,
            source=DEFAULT_SYNC_SOURCE,
            target=DEFAULT_SYNC_TARGET,
            started_at=utcnow(),
        )

        if scan_run is not None:
            run_info.scan_run_id = run_info.scan_run_id or self._get_object_id(scan_run)

        candidates = extract_pipeline_candidates(scan_result)

        if not candidates:
            return build_empty_sync_result(
                message="No scan candidates found for DB sync.",
                run=run_info,
            ).finish()

        result = LibrarySyncResult(
            ok=False,
            status=LibrarySyncStatus.RUNNING.value,
            message="Library DB sync running.",
            run=run_info,
            stats=LibrarySyncStats(total_count=0),
            candidates=[],
            metadata={"candidate_count": len(candidates)},
        )

        active_vplib_uids: list[str] = []

        publish_valid_only_effective = (
            self.config.publish_valid_only
            if publish_valid_only is None
            else bool(publish_valid_only)
        )

        for raw_candidate in candidates:
            try:
                candidate_result = self.sync_candidate_to_db(
                    raw_candidate,
                    scan_run=scan_run,
                    repository=repository,
                    publish_valid_only=publish_valid_only_effective,
                )

                if candidate_result.vplib_uid:
                    active_vplib_uids.append(candidate_result.vplib_uid)

                result.add_candidate(candidate_result)

            except Exception as exc:
                issue = exception_to_issue(
                    exc,
                    code="sync.candidate_failed",
                    scope="candidate",
                    operation=LibrarySyncOperation.UPSERT_FAMILY.value,
                )

                failed_candidate = LibrarySyncCandidateResult(
                    status=LibrarySyncCandidateStatus.ERROR.value,
                    valid=False,
                    issues=[issue],
                    error_count=1,
                    issue_count=1,
                    metadata={"raw_candidate_type": raw_candidate.__class__.__name__},
                )

                result.add_candidate(failed_candidate)
                result.add_issue(issue)

                if not self.config.continue_on_candidate_error:
                    raise LibraryDbSyncCandidateError(str(exc)) from exc

        mark_missing_deleted_effective = (
            self.config.mark_missing_deleted
            if mark_missing_deleted is None
            else bool(mark_missing_deleted)
        )

        if mark_missing_deleted_effective:
            deleted_count = self._mark_missing_deleted(repository, active_vplib_uids)
            result.stats.marked_missing_deleted_count = deleted_count
            if deleted_count:
                result.add_issue(
                    LibrarySyncIssue(
                        severity=LibrarySyncIssueSeverity.INFO.value,
                        code="sync.missing_marked_deleted",
                        message=f"Marked {deleted_count} missing families as deleted.",
                        operation=LibrarySyncOperation.MARK_MISSING_DELETED.value,
                    )
                )

        result.finish(message="Library DB sync finished.")
        return result

    def sync_candidate_to_db(
        self,
        candidate: Any,
        *,
        scan_run: Any = None,
        repository: Any = None,
        publish_valid_only: bool = True,
    ) -> LibrarySyncCandidateResult:
        """Synchronisiert einen einzelnen Kandidaten in die DB."""
        started_ms = monotonic_ms()
        repository = repository or self.get_repository()

        documents = extract_documents_from_any(candidate)
        uid = extract_vplib_uid(candidate, documents)
        family_id = extract_family_id(candidate, documents)
        package_id = extract_package_id(candidate, documents)
        revision_hash = extract_revision_hash(candidate)
        source_path = extract_source_path(candidate, documents)
        package_root = extract_package_root(candidate)
        is_valid = candidate_is_valid(candidate)

        family_payload = build_family_upsert_payload(candidate)

        candidate_result = LibrarySyncCandidateResult(
            status=LibrarySyncCandidateStatus.SCANNED.value,
            vplib_uid=uid,
            family_id=family_id,
            package_id=package_id,
            family_slug=family_payload.get("family_slug"),
            label=family_payload.get("label"),
            object_kind=family_payload.get("object_kind"),
            domain=family_payload.get("domain"),
            category=family_payload.get("category"),
            subcategory=family_payload.get("subcategory"),
            source_path=source_path,
            package_root=package_root,
            revision_hash=revision_hash,
            valid=is_valid,
            validation_status="valid" if is_valid else "invalid",
            started_at=utcnow(),
            scan_run_id=self._get_object_id(scan_run),
            metadata={
                "document_count": len(documents),
                "manifest_loaded": bool(extract_manifest(documents)),
            },
        )

        issue_payloads = extract_issue_payloads(candidate)

        if not uid:
            issue = LibrarySyncIssue(
                severity=LibrarySyncIssueSeverity.ERROR.value,
                code="sync.missing_vplib_uid",
                message="Candidate has no vplib_uid. It cannot be synchronized.",
                scope="candidate",
                source_path=source_path,
                family_id=family_id,
                package_id=package_id,
                revision_hash=revision_hash,
                metadata={
                    "document_count": len(documents),
                    "manifest_loaded": bool(extract_manifest(documents)),
                    "package_root": package_root,
                },
            )
            candidate_result.add_issue(issue)
            self._save_issue(repository, issue, scan_run=scan_run)
            candidate_result.status = LibrarySyncCandidateStatus.INVALID.value
            candidate_result.finished_at = utcnow()
            candidate_result.duration_ms = duration_ms(started_ms)
            return candidate_result

        if not revision_hash and is_valid:
            issue = LibrarySyncIssue(
                severity=LibrarySyncIssueSeverity.ERROR.value,
                code="sync.missing_revision_hash",
                message="Candidate has no revision_hash. It cannot be published.",
                scope="candidate",
                source_path=source_path,
                vplib_uid=uid,
                family_id=family_id,
                package_id=package_id,
            )
            candidate_result.add_issue(issue)
            self._save_issue(repository, issue, scan_run=scan_run)
            candidate_result.status = LibrarySyncCandidateStatus.INVALID.value
            candidate_result.finished_at = utcnow()
            candidate_result.duration_ms = duration_ms(started_ms)
            return candidate_result

        if not is_valid and publish_valid_only:
            self._persist_candidate_issues(
                repository,
                candidate_result,
                issue_payloads,
                scan_run=scan_run,
                default_issue=LibrarySyncIssue(
                    severity=LibrarySyncIssueSeverity.WARNING.value,
                    code="sync.invalid_skipped",
                    message="Candidate is invalid and was skipped.",
                    scope="candidate",
                    source_path=source_path,
                    vplib_uid=uid,
                    family_id=family_id,
                    package_id=package_id,
                    revision_hash=revision_hash,
                ),
            )
            candidate_result.status = LibrarySyncCandidateStatus.SKIPPED.value
            candidate_result.skipped = True
            candidate_result.finished_at = utcnow()
            candidate_result.duration_ms = duration_ms(started_ms)
            return candidate_result

        publish_payload = build_publish_payload_from_candidate(candidate)
        publish_result = self._publish_candidate_payload(
            repository,
            publish_payload,
            scan_run=scan_run,
        )

        self._apply_publish_result_to_candidate(candidate_result, publish_result)

        for issue_payload in issue_payloads[: self.config.issue_limit_per_candidate]:
            issue = LibrarySyncIssue.from_mapping(issue_payload)
            candidate_result.add_issue(issue)
            self._save_issue(repository, issue, scan_run=scan_run)

        if candidate_result.revision_created:
            candidate_result.status = LibrarySyncCandidateStatus.REVISION_CREATED.value
        elif candidate_result.item_created or candidate_result.family_created:
            candidate_result.status = LibrarySyncCandidateStatus.INSERTED.value
        elif candidate_result.item_updated or candidate_result.family_updated:
            candidate_result.status = LibrarySyncCandidateStatus.UPDATED.value
        else:
            candidate_result.status = LibrarySyncCandidateStatus.UNCHANGED.value

        candidate_result.published = True
        candidate_result.finished_at = utcnow()
        candidate_result.duration_ms = duration_ms(started_ms)
        return candidate_result

    # ------------------------------------------------------------------
    # Internals: scan
    # ------------------------------------------------------------------

    def _run_scan(
        self,
        *,
        source_root: Optional[str],
        force_refresh: bool,
        include_raw_documents: bool,
        scan_options: Mapping[str, Any],
    ) -> Any:
        scan_service = self.get_scan_service()

        raw_options = dict(scan_options or {})
        raw_options.setdefault("include_invalid", True)
        raw_options.setdefault("include_raw_pipeline", False)
        raw_options.setdefault("include_index", False)
        raw_options.setdefault("include_scan_result", False)
        raw_options.setdefault("include_discovery_result", False)
        raw_options.setdefault("include_read_results", False)
        raw_options.setdefault("include_validation_results", False)
        raw_options.setdefault("include_fingerprint_results", False)
        raw_options.setdefault("include_taxonomy_payload", False)

        if include_raw_documents:
            raw_options.setdefault("include_read_artifacts", True)

        options_object = None
        options_cls = getattr(scan_service, "LibraryScanServiceOptions", None)

        if callable(options_cls):
            allowed_option_keys = set(getattr(options_cls, "__dataclass_fields__", {}).keys())
            try:
                options_object = options_cls(
                    **{
                        key: value
                        for key, value in raw_options.items()
                        if key in allowed_option_keys
                    }
                )
            except Exception:
                options_object = None

        for function_name in (
            "scan_library_source",
            "scan_library_source_no_cache",
            "scan_library_for_blocks",
        ):
            scan_function = getattr(scan_service, function_name, None)

            if callable(scan_function):
                try:
                    return scan_function(
                        source_root=source_root,
                        force_refresh=force_refresh,
                        options=options_object or raw_options,
                    )
                except TypeError:
                    try:
                        return scan_function(
                            source_root=source_root,
                            force_refresh=force_refresh,
                        )
                    except TypeError:
                        if source_root:
                            return scan_function(source_root=source_root)
                        return scan_function()

        raise LibraryDbSyncImportError(
            "Scan service does not expose a supported scan function. "
            "Expected one of: scan_library_source, scan_library_source_no_cache, "
            "scan_library_for_blocks."
        )

    # ------------------------------------------------------------------
    # Internals: publish through new service/repository
    # ------------------------------------------------------------------

    def _publish_candidate_payload(
        self,
        repository: Any,
        publish_payload: Mapping[str, Any],
        *,
        scan_run: Any = None,
    ) -> dict[str, Any]:
        """Publishes using CreativeLibraryService if available, otherwise repository fallback."""
        service = self.get_creative_service(repository=repository)

        if service is not None:
            for method_name in (
                "publish_bundle",
                "publish_document_bundle",
                "sync_package_payload",
                "publish",
            ):
                method = getattr(service, method_name, None)
                if callable(method):
                    try:
                        result = method(
                            publish_payload,
                            source_scope="imported",
                            scan_run_ref=self._get_object_id(scan_run),
                            mark_current=True,
                            replace_children=False,
                            validate=False,
                            commit=False,
                        )
                    except TypeError:
                        try:
                            result = method(
                                publish_payload,
                                scan_run_ref=self._get_object_id(scan_run),
                                commit=False,
                            )
                        except TypeError:
                            result = method(publish_payload)
                    return json_safe(result) if isinstance(json_safe(result), Mapping) else {"result": json_safe(result)}

        return self._publish_with_repository(repository, publish_payload, scan_run=scan_run)

    def _publish_with_repository(
        self,
        repository: Any,
        publish_payload: Mapping[str, Any],
        *,
        scan_run: Any = None,
    ) -> dict[str, Any]:
        item_payload = self._build_repository_item_payload(publish_payload)
        item, item_created = self._upsert_item(repository, item_payload)

        revision_payload = self._build_repository_revision_payload(
            publish_payload,
            scan_run_id=self._get_object_id(scan_run),
        )
        revision = self._create_revision(repository, item, revision_payload)

        variants = []
        assets = []
        documents = []

        for variant_payload in publish_payload.get("variants") or []:
            variants.append(self._upsert_variant(repository, item, revision, variant_payload))

        for asset_payload in publish_payload.get("assets") or []:
            assets.append(self._create_asset(repository, item, revision, asset_payload))

        for document_payload in publish_payload.get("documents") or []:
            documents.append(self._create_document(repository, item, revision, document_payload))

        return {
            "ok": True,
            "status": "ok",
            "payload": {
                "created": item_created,
                "updated": not item_created,
                "item": json_safe(item),
                "revision": json_safe(revision),
                "children": {
                    "variants": [json_safe(value) for value in variants],
                    "assets": [json_safe(value) for value in assets],
                    "documents": [json_safe(value) for value in documents],
                    "counts": {
                        "variant_count": len(variants),
                        "asset_count": len(assets),
                        "document_count": len(documents),
                    },
                },
                "vplib_uid": publish_payload.get("vplib_uid"),
            },
        }

    def _build_repository_item_payload(self, publish_payload: Mapping[str, Any]) -> dict[str, Any]:
        return {
            "vplib_uid": publish_payload.get("vplib_uid"),
            "family_id": publish_payload.get("family_id"),
            "package_id": publish_payload.get("package_id"),
            "source_scope": "imported",
            "source_path": publish_payload.get("source_path"),
            "classification_path": publish_payload.get("classification_path"),
            "domain": publish_payload.get("domain"),
            "category": publish_payload.get("category"),
            "subcategory": publish_payload.get("subcategory"),
            "object_kind": publish_payload.get("object_kind"),
            "label": publish_payload.get("label") or publish_payload.get("title"),
            "name": publish_payload.get("name") or publish_payload.get("label") or publish_payload.get("title"),
            "title": publish_payload.get("title") or publish_payload.get("label"),
            "description": publish_payload.get("description"),
            "status": "published",
            "active": True,
            "visible": True,
            "manifest_payload": publish_payload.get("manifest_payload") or {},
            "classification_payload": publish_payload.get("classification_payload") or {},
            "payload": json_safe(dict(publish_payload)),
            "metadata": {
                "source": LIBRARY_DB_SYNC_SERVICE_NAME,
                "revision_hash": publish_payload.get("revision_hash"),
            },
        }

    def _build_repository_revision_payload(self, publish_payload: Mapping[str, Any], *, scan_run_id: Any = None) -> dict[str, Any]:
        return {
            "vplib_uid": publish_payload.get("vplib_uid"),
            "family_id": publish_payload.get("family_id"),
            "package_id": publish_payload.get("package_id"),
            "revision_hash": publish_payload.get("revision_hash"),
            "version": publish_payload.get("package_version"),
            "package_version": publish_payload.get("package_version"),
            "source_path": publish_payload.get("source_path"),
            "scan_run_id": scan_run_id,
            "manifest_payload": publish_payload.get("manifest_payload") or {},
            "modules_payload": publish_payload.get("modules_payload") or {},
            "family_payload": publish_payload.get("family_payload") or {},
            "classification_payload": publish_payload.get("classification_payload") or {},
            "document_bundle": publish_payload.get("document_bundle") or {},
            "generator_payload": publish_payload.get("generator_payload") or {},
            "validation_payload": publish_payload.get("validation_payload") or {},
            "payload": json_safe(dict(publish_payload)),
            "metadata": {
                "source": LIBRARY_DB_SYNC_SERVICE_NAME,
                "revision_hash": publish_payload.get("revision_hash"),
            },
            "active": True,
        }

    def _apply_publish_result_to_candidate(
        self,
        candidate_result: LibrarySyncCandidateResult,
        publish_result: Mapping[str, Any],
    ) -> None:
        data = to_mapping(publish_result)
        payload = to_mapping(data.get("payload"))

        candidate_result.metadata["publish_result"] = json_safe(data)

        created = safe_bool(payload.get("created"), False)
        updated = safe_bool(payload.get("updated"), False)

        candidate_result.family_created = created
        candidate_result.family_updated = updated
        candidate_result.item_created = created
        candidate_result.item_updated = updated

        item_payload = to_mapping(payload.get("item"))
        revision_payload = to_mapping(payload.get("revision"))
        children = to_mapping(payload.get("children"))
        counts = to_mapping(children.get("counts"))

        candidate_result.family_db_id = first_non_empty(item_payload.get("id"), item_payload.get("item_id"))
        candidate_result.item_db_id = candidate_result.family_db_id
        candidate_result.revision_db_id = first_non_empty(revision_payload.get("id"), revision_payload.get("revision_id"))
        candidate_result.revision_created = bool(revision_payload) or safe_bool(payload.get("revision_created"), True)

        candidate_result.variant_count = safe_int(counts.get("variant_count"), 0)
        candidate_result.asset_count = safe_int(counts.get("asset_count"), 0)
        candidate_result.document_count = safe_int(counts.get("document_count"), 0)

        candidate_result.add_operation(
            LibrarySyncOperationResult(
                operation=LibrarySyncOperation.UPSERT_ITEM.value if hasattr(LibrarySyncOperation, "UPSERT_ITEM") else LibrarySyncOperation.UPSERT_FAMILY.value,
                status=LibrarySyncCandidateStatus.INSERTED.value if created else LibrarySyncCandidateStatus.UPDATED.value,
                affected_count=1,
                created_count=1 if created else 0,
                updated_count=1 if updated else 0,
            )
        )
        candidate_result.add_operation(
            LibrarySyncOperationResult(
                operation=LibrarySyncOperation.CREATE_REVISION.value,
                status=LibrarySyncCandidateStatus.REVISION_CREATED.value,
                affected_count=1,
                created_count=1,
            )
        )
        candidate_result.add_operation(
            LibrarySyncOperationResult(
                operation=LibrarySyncOperation.REPLACE_VARIANTS.value,
                status=LibrarySyncCandidateStatus.UPDATED.value,
                affected_count=candidate_result.variant_count,
                created_count=candidate_result.variant_count,
            )
        )
        candidate_result.add_operation(
            LibrarySyncOperationResult(
                operation=LibrarySyncOperation.REPLACE_ASSETS.value,
                status=LibrarySyncCandidateStatus.UPDATED.value,
                affected_count=candidate_result.asset_count,
                created_count=candidate_result.asset_count,
            )
        )
        candidate_result.add_operation(
            LibrarySyncOperationResult(
                operation=LibrarySyncOperation.REPLACE_DOCUMENTS.value,
                status=LibrarySyncCandidateStatus.UPDATED.value,
                affected_count=candidate_result.document_count,
                created_count=candidate_result.document_count,
            )
        )

    def _persist_candidate_issues(
        self,
        repository: Any,
        candidate_result: LibrarySyncCandidateResult,
        issue_payloads: Sequence[Mapping[str, Any]],
        *,
        scan_run: Any = None,
        default_issue: LibrarySyncIssue,
    ) -> None:
        if issue_payloads:
            for issue_payload in issue_payloads[: self.config.issue_limit_per_candidate]:
                issue = LibrarySyncIssue.from_mapping(issue_payload)
                candidate_result.add_issue(issue)
                self._save_issue(repository, issue, scan_run=scan_run)
        else:
            candidate_result.add_issue(default_issue)
            self._save_issue(repository, default_issue, scan_run=scan_run)

    # ------------------------------------------------------------------
    # Internals: repository delegation, new API first, legacy fallback
    # ------------------------------------------------------------------

    def _create_scan_run(self, repository: Any, run_info: LibrarySyncRunInfo) -> Any:
        for method_name in ("start_scan_run", "create_scan_run"):
            method = getattr(repository, method_name, None)
            if callable(method):
                try:
                    return method(
                        {
                            "source_root": run_info.source_root,
                            "mode": run_info.mode,
                            "triggered_by": run_info.triggered_by,
                            "status": "running",
                            "started_at": run_info.started_at,
                            "metadata": run_info.metadata,
                        },
                        commit=False,
                    )
                except TypeError:
                    return method(
                        {
                            "source_root": run_info.source_root,
                            "mode": run_info.mode,
                            "triggered_by": run_info.triggered_by,
                            "status": "running",
                            "started_at": run_info.started_at,
                            "metadata": run_info.metadata,
                        }
                    )
        return None

    def _finish_scan_run(self, repository: Any, scan_run: Any, result: LibrarySyncResult) -> None:
        if scan_run is None:
            return

        method = getattr(repository, "finish_scan_run", None)
        if callable(method):
            try:
                method(
                    scan_run,
                    counters=result.stats.to_dict(),
                    status="completed" if result.ok else "failed",
                    errors=[issue.to_dict() for issue in result.issues],
                    commit=False,
                )
            except TypeError:
                method(scan_run, status="completed" if result.ok else "failed", commit=False)

    def _fail_scan_run(self, repository: Any, scan_run: Any, exc: BaseException) -> None:
        if scan_run is None:
            return

        fail_method = getattr(repository, "fail_scan_run", None)
        if callable(fail_method):
            try:
                fail_method(scan_run, error=exc, commit=False)
                return
            except TypeError:
                pass

        finish_method = getattr(repository, "finish_scan_run", None)
        if callable(finish_method):
            try:
                finish_method(
                    scan_run,
                    status="failed",
                    errors=[{"message": str(exc), "type": exc.__class__.__name__}],
                    commit=False,
                )
            except TypeError:
                finish_method(scan_run, status="failed", commit=False)

    def _upsert_item(self, repository: Any, payload: Mapping[str, Any]) -> tuple[Any, bool]:
        for method_name in ("upsert_item", "upsert_family"):
            method = getattr(repository, method_name, None)
            if callable(method):
                result = method(payload, commit=False)
                if isinstance(result, tuple) and len(result) >= 2:
                    return result[0], bool(result[1])
                return result, True

        raise LibraryDbSyncImportError("Repository does not expose upsert_item/upsert_family.")

    def _create_revision(self, repository: Any, item: Any, payload: Mapping[str, Any]) -> Any:
        method = getattr(repository, "create_revision", None)
        if callable(method):
            item_ref = self._get_object_id(item)
            return method(item_ref, payload, mark_current=True, commit=False)

        legacy = getattr(repository, "upsert_revision_if_changed", None)
        if callable(legacy):
            revision, _created = legacy(item, payload, scan_run=None, commit=False)
            return revision

        raise LibraryDbSyncImportError("Repository does not expose create_revision/upsert_revision_if_changed.")

    def _upsert_variant(self, repository: Any, item: Any, revision: Any, payload: Mapping[str, Any]) -> Any:
        method = getattr(repository, "upsert_variant", None)
        if callable(method):
            result = method(
                payload,
                item_ref=self._get_object_id(item),
                revision_ref=self._get_object_id(revision),
                commit=False,
            )
            if isinstance(result, tuple):
                return result[0]
            return result

        replace = getattr(repository, "replace_variants", None)
        if callable(replace):
            values = replace(item, revision, [payload], commit=False)
            return list(values or [None])[0]

        return None

    def _create_asset(self, repository: Any, item: Any, revision: Any, payload: Mapping[str, Any]) -> Any:
        method = getattr(repository, "create_asset", None)
        if callable(method):
            return method(
                payload,
                item_ref=self._get_object_id(item),
                revision_ref=self._get_object_id(revision),
                commit=False,
            )

        replace = getattr(repository, "replace_assets", None)
        if callable(replace):
            values = replace(item, revision, [payload], commit=False)
            return list(values or [None])[0]

        return None

    def _create_document(self, repository: Any, item: Any, revision: Any, payload: Mapping[str, Any]) -> Any:
        method = getattr(repository, "create_document", None)
        if callable(method):
            return method(
                payload,
                item_ref=self._get_object_id(item),
                revision_ref=self._get_object_id(revision),
                commit=False,
            )

        replace = getattr(repository, "replace_documents", None)
        if callable(replace):
            values = replace(item, revision, [payload], commit=False)
            return list(values or [None])[0]

        return None

    def _save_issue(
        self,
        repository: Any,
        issue: LibrarySyncIssue,
        *,
        scan_run: Any = None,
        family: Any = None,
        revision: Any = None,
    ) -> Any:
        payload = issue.to_dict() if hasattr(issue, "to_dict") else json_safe(issue)

        for method_name in ("record_scan_issue", "add_issue", "create_issue"):
            method = getattr(repository, method_name, None)
            if callable(method):
                try:
                    if method_name == "record_scan_issue" and scan_run is not None:
                        return method(scan_run, payload, commit=False)
                    return method(payload, scan_run=scan_run, family=family, revision=revision, commit=False)
                except TypeError:
                    try:
                        return method(payload, commit=False)
                    except TypeError:
                        return method(payload)

        return None

    def _mark_missing_deleted(self, repository: Any, active_vplib_uids: Iterable[str]) -> int:
        for method_name in ("mark_missing_families_deleted", "mark_missing_items_deleted"):
            method = getattr(repository, method_name, None)
            if callable(method):
                return safe_int(method(active_vplib_uids, commit=False), 0)

        return 0

    def _commit(self, repository: Any) -> None:
        commit = getattr(repository, "commit", None)
        if callable(commit):
            commit()

    def _rollback(self, repository: Any) -> None:
        rollback = getattr(repository, "rollback", None)
        if callable(rollback):
            rollback()

    def _get_object_id(self, obj: Any) -> Any:
        if obj is None:
            return None

        for name in ("id", "pk", "uuid", "scan_run_id"):
            try:
                value = getattr(obj, name)
            except Exception:
                continue
            if value is not None:
                return value

        data = to_mapping(obj)

        return first_non_empty(
            data.get("id"),
            data.get("pk"),
            data.get("uuid"),
            data.get("scan_run_id"),
        )

    def _assert_enabled(self) -> None:
        if not self.config.enabled:
            raise LibraryDbSyncDisabledError(
                f"Library DB sync is disabled. Enable {ENV_SYNC_ENABLED}=true."
            )

    # ------------------------------------------------------------------
    # Health
    # ------------------------------------------------------------------

    def health(
        self,
        *,
        check_repository: bool = False,
        check_scan_service: bool = False,
        check_creative_service: bool = False,
        include_traceback: bool = False,
    ) -> dict[str, Any]:
        errors: list[dict[str, Any]] = []
        warnings: list[dict[str, Any]] = []

        repository_health: dict[str, Any] = {"checked": check_repository, "available": None}
        scan_service_health: dict[str, Any] = {"checked": check_scan_service, "available": None}
        creative_service_health: dict[str, Any] = {"checked": check_creative_service, "available": None}

        if check_repository:
            try:
                repository = self.get_repository()
                health_function = getattr(repository, "get_health", None) or getattr(repository, "health", None)

                if callable(health_function):
                    try:
                        repository_health = health_function(
                            strict=self.config.strict,
                            check_session=True,
                            include_traceback=include_traceback,
                        )
                    except TypeError:
                        repository_health = health_function()
                else:
                    repository_health = {
                        "checked": True,
                        "available": repository is not None,
                        "status": "loaded_no_health_function",
                    }

                if not repository_health.get("ok", repository_health.get("available", False)):
                    errors.append(
                        {
                            "scope": "repository",
                            "error": "Repository health is not ok.",
                            "health": repository_health,
                        }
                    )

            except Exception as exc:
                payload = {
                    "scope": "repository",
                    "error_type": exc.__class__.__name__,
                    "error": str(exc),
                }
                if include_traceback:
                    payload["traceback"] = traceback_module.format_exc()
                errors.append(payload)
                repository_health = {"checked": True, "available": False, "error": payload}

        if check_scan_service:
            try:
                scan_service = self.get_scan_service()
                health_function = getattr(scan_service, "get_library_scan_service_health", None) or getattr(scan_service, "get_health", None)
                if callable(health_function):
                    try:
                        payload = health_function()
                    except TypeError:
                        payload = health_function(refresh_settings=False)
                    scan_service_health = {
                        "checked": True,
                        "available": True,
                        "module": getattr(scan_service, "__name__", None),
                        "health": json_safe(payload),
                    }
                else:
                    scan_service_health = {
                        "checked": True,
                        "available": scan_service is not None,
                        "module": getattr(scan_service, "__name__", None),
                    }
            except Exception as exc:
                payload = {
                    "scope": "scan_service",
                    "error_type": exc.__class__.__name__,
                    "error": str(exc),
                }
                if include_traceback:
                    payload["traceback"] = traceback_module.format_exc()
                errors.append(payload)
                scan_service_health = {"checked": True, "available": False, "error": payload}

        if check_creative_service:
            try:
                creative_service = self.get_creative_service(repository=None)
                health_function = getattr(creative_service, "get_health", None) if creative_service is not None else None
                creative_service_health = {
                    "checked": True,
                    "available": creative_service is not None,
                    "service": type(creative_service).__name__ if creative_service is not None else None,
                    "health": json_safe(health_function()) if callable(health_function) else {},
                }
            except Exception as exc:
                payload = {
                    "scope": "creative_service",
                    "error_type": exc.__class__.__name__,
                    "error": str(exc),
                }
                if include_traceback:
                    payload["traceback"] = traceback_module.format_exc()
                warnings.append(payload)
                creative_service_health = {"checked": True, "available": False, "error": payload}

        if not self.config.enabled:
            warnings.append(
                {
                    "scope": "config",
                    "warning": "DB sync is disabled.",
                    "env": ENV_SYNC_ENABLED,
                }
            )

        if _SYNC_RESULT_IMPORT_ERROR is not None:
            warnings.append(
                {
                    "scope": "domain.sync_result",
                    "warning": "Using local sync_result fallback dataclasses.",
                    "error": str(_SYNC_RESULT_IMPORT_ERROR),
                }
            )

        ok = not errors

        if not ok:
            status = "error"
        elif warnings:
            status = "partial"
        else:
            status = "ok"

        return {
            "ok": ok,
            "status": status,
            "component": LIBRARY_DB_SYNC_COMPONENT_NAME,
            "service": LIBRARY_DB_SYNC_SERVICE_NAME,
            "api_version": LIBRARY_DB_SYNC_API_VERSION,
            "implementation_stage": LIBRARY_DB_SYNC_IMPLEMENTATION_STAGE,
            "version": __version__,
            "config": {
                "enabled": self.config.enabled,
                "strict": self.config.strict,
                "autocommit": self.config.autocommit,
                "mark_missing_deleted": self.config.mark_missing_deleted,
                "continue_on_candidate_error": self.config.continue_on_candidate_error,
                "include_raw_documents": self.config.include_raw_documents,
                "publish_valid_only": self.config.publish_valid_only,
                "repository_import_path": self.config.repository_import_path,
                "creative_service_import_path": self.config.creative_service_import_path,
                "scan_service_import_path": self.config.scan_service_import_path,
            },
            "repository": repository_health,
            "scan_service": scan_service_health,
            "creative_service": creative_service_health,
            "imports": {
                "cached_modules": sorted(_IMPORT_CACHE.keys()),
                "cached_errors": _IMPORT_ERROR_CACHE,
            },
            "warnings": warnings,
            "errors": errors,
        }


# ---------------------------------------------------------------------------
# Module-level factory / API
# ---------------------------------------------------------------------------

def create_library_db_sync_service(
    *,
    repository: Any = None,
    repository_factory: Any = None,
    creative_service: Any = None,
    creative_service_factory: Any = None,
    scan_service: Any = None,
    config: Optional[LibraryDbSyncServiceConfig] = None,
) -> LibraryDbSyncService:
    """Erstellt eine neue DB-Sync-Service-Instanz."""
    return LibraryDbSyncService(
        repository=repository,
        repository_factory=repository_factory,
        creative_service=creative_service,
        creative_service_factory=creative_service_factory,
        scan_service=scan_service,
        config=config,
    )


def get_library_db_sync_service(
    *,
    use_cache: bool = True,
    force_new: bool = False,
    repository: Any = None,
    repository_factory: Any = None,
    creative_service: Any = None,
    creative_service_factory: Any = None,
    scan_service: Any = None,
    config: Optional[LibraryDbSyncServiceConfig] = None,
) -> LibraryDbSyncService:
    """Liefert den Default-DB-Sync-Service."""
    global _DEFAULT_SERVICE

    if force_new or not use_cache:
        return create_library_db_sync_service(
            repository=repository,
            repository_factory=repository_factory,
            creative_service=creative_service,
            creative_service_factory=creative_service_factory,
            scan_service=scan_service,
            config=config,
        )

    with _CACHE_LOCK:
        if _DEFAULT_SERVICE is None:
            _DEFAULT_SERVICE = create_library_db_sync_service(
                repository=repository,
                repository_factory=repository_factory,
                creative_service=creative_service,
                creative_service_factory=creative_service_factory,
                scan_service=scan_service,
                config=config,
            )

        return _DEFAULT_SERVICE


def sync_library_to_db(
    *,
    source_root: Optional[str] = None,
    force_refresh: bool = True,
    triggered_by: Optional[str] = None,
    publish_valid_only: Optional[bool] = None,
    mark_missing_deleted: Optional[bool] = None,
    include_raw_documents: Optional[bool] = None,
    scan_options: Optional[Mapping[str, Any]] = None,
    service: Optional[LibraryDbSyncService] = None,
) -> LibrarySyncResult:
    """Top-Level Convenience-Funktion für Filesystem -> DB Sync."""
    sync_service = service or get_library_db_sync_service()

    return sync_service.sync_library_source(
        source_root=source_root,
        force_refresh=force_refresh,
        triggered_by=triggered_by,
        publish_valid_only=publish_valid_only,
        mark_missing_deleted=mark_missing_deleted,
        include_raw_documents=include_raw_documents,
        scan_options=scan_options,
    )


def sync_library_to_database_response(
    *,
    source_root: Optional[str] = None,
    force_refresh: bool = True,
    triggered_by: Optional[str] = None,
    publish_valid_only: Optional[bool] = None,
    mark_missing_deleted: Optional[bool] = None,
    include_raw_documents: Optional[bool] = None,
    scan_options: Optional[Mapping[str, Any]] = None,
    service: Optional[LibraryDbSyncService] = None,
) -> dict[str, Any]:
    """Kompakte JSON-kompatible Antwort für POST /library/sync."""
    result = sync_library_to_db(
        source_root=source_root,
        force_refresh=force_refresh,
        triggered_by=triggered_by,
        publish_valid_only=publish_valid_only,
        mark_missing_deleted=mark_missing_deleted,
        include_raw_documents=include_raw_documents,
        scan_options=scan_options,
        service=service,
    )

    try:
        payload = build_sync_response(result)
    except Exception:
        to_dict = getattr(result, "to_dict", None)
        if callable(to_dict):
            try:
                payload = to_dict()
            except TypeError:
                payload = to_dict(flat=True)
        else:
            payload = json_safe(result)

    return json_safe(payload)


def sync_scan_result_to_db(
    scan_result: Any,
    *,
    scan_run: Any = None,
    run_info: Optional[LibrarySyncRunInfo] = None,
    publish_valid_only: Optional[bool] = None,
    mark_missing_deleted: Optional[bool] = None,
    repository: Any = None,
    service: Optional[LibraryDbSyncService] = None,
) -> LibrarySyncResult:
    """Top-Level Convenience-Funktion für vorhandenes ScanResult -> DB Sync."""
    sync_service = service or get_library_db_sync_service(repository=repository)

    return sync_service.sync_scan_result_to_db(
        scan_result,
        scan_run=scan_run,
        run_info=run_info,
        publish_valid_only=publish_valid_only,
        mark_missing_deleted=mark_missing_deleted,
        repository=repository,
    )


def get_library_db_sync_service_health(
    *,
    check_repository: bool = False,
    check_scan_service: bool = False,
    check_creative_service: bool = False,
    include_traceback: bool = False,
) -> dict[str, Any]:
    """Health-Check für den DB-Sync-Service."""
    service = get_library_db_sync_service()

    return service.health(
        check_repository=check_repository,
        check_scan_service=check_scan_service,
        check_creative_service=check_creative_service,
        include_traceback=include_traceback,
    )


def assert_library_db_sync_service_ready(
    *,
    check_repository: bool = True,
    check_scan_service: bool = True,
    check_creative_service: bool = False,
) -> dict[str, Any]:
    """Wirft RuntimeError, wenn der DB-Sync-Service nicht bereit ist."""
    health = get_library_db_sync_service_health(
        check_repository=check_repository,
        check_scan_service=check_scan_service,
        check_creative_service=check_creative_service,
    )

    if not health.get("ok"):
        raise LibraryDbSyncServiceError(
            "Library DB sync service is not ready "
            f"(status={health.get('status')}, errors={health.get('errors')})."
        )

    return health


def clear_library_db_sync_service_cache() -> dict[str, Any]:
    """Leert Import- und Default-Service-Caches."""
    global _DEFAULT_SERVICE

    with _CACHE_LOCK:
        _DEFAULT_SERVICE = None

    import_result = clear_library_db_sync_import_cache()

    return {
        "ok": True,
        "default_service_cleared": True,
        "imports": import_result,
    }


clear_library_db_sync_service_caches = clear_library_db_sync_service_cache
clear_db_sync_cache = clear_library_db_sync_service_cache
clear_db_sync_caches = clear_library_db_sync_service_cache


# ---------------------------------------------------------------------------
# Public exports
# ---------------------------------------------------------------------------

__all__ = [
    # Metadata
    "LIBRARY_DB_SYNC_SERVICE_NAME",
    "LIBRARY_DB_SYNC_COMPONENT_NAME",
    "LIBRARY_DB_SYNC_API_VERSION",
    "LIBRARY_DB_SYNC_IMPLEMENTATION_STAGE",
    "__version__",

    # Env / defaults
    "ENV_SYNC_ENABLED",
    "ENV_SYNC_STRICT",
    "ENV_SYNC_AUTOCOMMIT",
    "ENV_SYNC_MARK_MISSING_DELETED",
    "ENV_SYNC_CONTINUE_ON_CANDIDATE_ERROR",
    "ENV_SYNC_INCLUDE_RAW_DOCUMENTS",
    "DEFAULT_SYNC_ENABLED",
    "DEFAULT_SYNC_STRICT",
    "DEFAULT_SYNC_AUTOCOMMIT",
    "DEFAULT_SYNC_MARK_MISSING_DELETED",
    "DEFAULT_SYNC_CONTINUE_ON_CANDIDATE_ERROR",
    "DEFAULT_SYNC_INCLUDE_RAW_DOCUMENTS",
    "DEFAULT_REPOSITORY_FACTORY_IMPORT",
    "DEFAULT_CREATIVE_SERVICE_IMPORT",
    "DEFAULT_SCAN_SERVICE_IMPORT",
    "REPOSITORY_IMPORT_PATHS",
    "CREATIVE_SERVICE_IMPORT_PATHS",
    "SCAN_SERVICE_IMPORT_PATHS",
    "DEFAULT_DOCUMENT_LIMIT_FOR_DETAIL_PAYLOAD",
    "DEFAULT_ISSUE_LIMIT_PER_CANDIDATE",

    # Exceptions
    "LibraryDbSyncServiceError",
    "LibraryDbSyncDisabledError",
    "LibraryDbSyncImportError",
    "LibraryDbSyncValidationError",
    "LibraryDbSyncCandidateError",

    # Config / service
    "LibraryDbSyncServiceConfig",
    "LibraryDbSyncService",

    # Generic helpers
    "utcnow",
    "monotonic_ms",
    "duration_ms",
    "env_bool",
    "normalize_string",
    "normalize_vplib_uid",
    "safe_int",
    "safe_bool",
    "json_safe",
    "to_mapping",
    "first_non_empty",
    "get_direct_value",
    "deep_get",
    "mapping_get_any",
    "exception_to_issue",

    # Import helpers
    "safe_import_module",
    "import_first",
    "clear_library_db_sync_import_cache",

    # Document helpers
    "normalize_document_path",
    "unwrap_document_payload",
    "document_mapping_from_value",
    "get_candidate_path_candidates",
    "find_existing_package_root",
    "read_json_file",
    "load_documents_from_package_root",
    "augment_documents_from_filesystem",

    # Candidate extraction
    "extract_documents_from_any",
    "get_document",
    "extract_manifest",
    "extract_identity",
    "extract_classification",
    "extract_inventory",
    "extract_modules",
    "extract_validation_payload",
    "extract_fingerprint_payload",
    "extract_summary_payload",
    "extract_source_path",
    "extract_package_root",
    "extract_revision_hash",
    "extract_vplib_uid",
    "extract_family_id",
    "extract_package_id",
    "extract_variant_ids",
    "candidate_is_valid",
    "extract_pipeline_candidates",

    # Payload builders
    "build_family_upsert_payload",
    "build_revision_upsert_payload",
    "extract_variant_payloads",
    "extract_asset_payloads",
    "extract_document_payloads",
    "extract_issue_payloads",
    "build_publish_payload_from_candidate",

    # Top-level API
    "create_library_db_sync_service",
    "get_library_db_sync_service",
    "sync_library_to_db",
    "sync_library_to_database_response",
    "sync_scan_result_to_db",
    "get_library_db_sync_service_health",
    "assert_library_db_sync_service_ready",
    "clear_library_db_sync_service_cache",
    "clear_library_db_sync_service_caches",
    "clear_db_sync_cache",
    "clear_db_sync_caches",

    # Reexported/fallback domain helpers
    "DEFAULT_SYNC_MODE",
    "DEFAULT_SYNC_SOURCE",
    "DEFAULT_SYNC_TARGET",
    "LibrarySyncCandidateResult",
    "LibrarySyncCandidateStatus",
    "LibrarySyncIssue",
    "LibrarySyncIssueSeverity",
    "LibrarySyncOperation",
    "LibrarySyncOperationResult",
    "LibrarySyncResult",
    "LibrarySyncRunInfo",
    "LibrarySyncStats",
    "LibrarySyncStatus",
    "build_empty_sync_result",
    "build_error_sync_result",
    "build_sync_response",
]