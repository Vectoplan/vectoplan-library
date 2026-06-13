# services/vectoplan-library/src/library/domain/sync_result.py
"""
Domain-Modelle für den DB-Sync der VECTOPLAN Creative Library.

Diese Datei beschreibt ausschließlich API-/Service-taugliche Ergebnisstrukturen
für den Ablauf:

    src/library/source
        → scan
        → validation
        → fingerprint
        → library_db_sync_service
        → creative_library Tabellen
        → SyncResult

Wichtig:

- keine Flask-Abhängigkeit
- keine SQLAlchemy-Abhängigkeit
- keine Datenbankzugriffe
- keine Scanner-Imports
- keine Repository-Imports
- keine Schreiboperationen
- robust serialisierbar
- tolerant gegenüber Dicts, Dataclasses und fremden Objekten
- geeignet für API-Responses, Admin-UI, Logs und Tests

Diese Datei ist bewusst eigenständig, damit der spätere
library_db_sync_service.py sie ohne Importzyklen verwenden kann.

Technischer Hinweis:

`LibrarySyncIssue` besitzt fachlich ein Feld namens `field`. Deshalb darf der
Dataclasses-Helper nicht unter demselben Namen importiert werden. Diese Datei
importiert ihn als `dataclass_field`, damit Klassenattribute namens `field`
keine Import-/Class-Body-Kollision erzeugen.
"""

from __future__ import annotations

import traceback as traceback_module
from dataclasses import asdict, dataclass, field as dataclass_field, is_dataclass
from datetime import datetime, timezone
from enum import Enum
from functools import lru_cache
from pathlib import Path
from typing import Any, Dict, Iterable, List, Mapping, Optional, Sequence, Tuple


# ---------------------------------------------------------------------------
# Metadata
# ---------------------------------------------------------------------------

SYNC_RESULT_COMPONENT_NAME = "creative_library_sync_result"
SYNC_RESULT_API_VERSION = "v1"
SYNC_RESULT_MODEL_VERSION = "sync-result.v1"

__version__ = "0.1.1"


# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

DEFAULT_SYNC_MODE = "filesystem_to_db"
DEFAULT_SYNC_SOURCE = "filesystem"
DEFAULT_SYNC_TARGET = "database"

DEFAULT_LIMIT_WARNINGS = 500
DEFAULT_LIMIT_ERRORS = 500
DEFAULT_LIMIT_CANDIDATES = 5000


# ---------------------------------------------------------------------------
# Enums
# ---------------------------------------------------------------------------


class LibrarySyncStatus(str, Enum):
    """Gesamtstatus eines Sync-Laufs."""

    UNKNOWN = "unknown"
    PENDING = "pending"
    RUNNING = "running"
    OK = "ok"
    PARTIAL = "partial"
    EMPTY = "empty"
    FAILED = "failed"
    ERROR = "error"
    CANCELLED = "cancelled"

    @classmethod
    def values(cls) -> Tuple[str, ...]:
        return tuple(item.value for item in cls)


class LibrarySyncCandidateStatus(str, Enum):
    """Status eines einzelnen Sync-Kandidaten."""

    UNKNOWN = "unknown"
    SCANNED = "scanned"
    VALID = "valid"
    INVALID = "invalid"
    SKIPPED = "skipped"
    INSERTED = "inserted"
    UPDATED = "updated"
    UNCHANGED = "unchanged"
    REVISION_CREATED = "revision_created"
    PUBLISHED = "published"
    UNPUBLISHED = "unpublished"
    DELETED = "deleted"
    DUPLICATE = "duplicate"
    FAILED = "failed"
    ERROR = "error"

    @classmethod
    def values(cls) -> Tuple[str, ...]:
        return tuple(item.value for item in cls)


class LibrarySyncIssueSeverity(str, Enum):
    """Severity eines Sync-Issues."""

    DEBUG = "debug"
    INFO = "info"
    WARNING = "warning"
    ERROR = "error"
    FATAL = "fatal"

    @classmethod
    def values(cls) -> Tuple[str, ...]:
        return tuple(item.value for item in cls)


class LibrarySyncOperation(str, Enum):
    """Operation, die während eines Syncs ausgeführt wurde."""

    NONE = "none"
    SCAN = "scan"
    VALIDATE = "validate"
    UPSERT_FAMILY = "upsert_family"
    CREATE_REVISION = "create_revision"
    SKIP_REVISION = "skip_revision"
    REPLACE_VARIANTS = "replace_variants"
    REPLACE_ASSETS = "replace_assets"
    REPLACE_DOCUMENTS = "replace_documents"
    SAVE_ISSUES = "save_issues"
    MARK_MISSING_DELETED = "mark_missing_deleted"
    PUBLISH = "publish"
    UNPUBLISH = "unpublish"
    DELETE = "delete"
    ROLLBACK = "rollback"

    @classmethod
    def values(cls) -> Tuple[str, ...]:
        return tuple(item.value for item in cls)


# ---------------------------------------------------------------------------
# Normalization helpers with small caches
# ---------------------------------------------------------------------------


@lru_cache(maxsize=256)
def normalize_sync_status(value: Any) -> str:
    text = str(value or "").strip().lower()

    aliases = {
        "success": LibrarySyncStatus.OK.value,
        "successful": LibrarySyncStatus.OK.value,
        "done": LibrarySyncStatus.OK.value,
        "finished": LibrarySyncStatus.OK.value,
        "complete": LibrarySyncStatus.OK.value,
        "completed": LibrarySyncStatus.OK.value,
        "warning": LibrarySyncStatus.PARTIAL.value,
        "warnings": LibrarySyncStatus.PARTIAL.value,
        "partial_success": LibrarySyncStatus.PARTIAL.value,
        "fail": LibrarySyncStatus.FAILED.value,
        "failure": LibrarySyncStatus.FAILED.value,
        "exception": LibrarySyncStatus.ERROR.value,
    }

    if text in aliases:
        return aliases[text]

    if text in LibrarySyncStatus.values():
        return text

    return LibrarySyncStatus.UNKNOWN.value


@lru_cache(maxsize=512)
def normalize_candidate_status(value: Any) -> str:
    text = str(value or "").strip().lower()

    aliases = {
        "new": LibrarySyncCandidateStatus.INSERTED.value,
        "created": LibrarySyncCandidateStatus.INSERTED.value,
        "changed": LibrarySyncCandidateStatus.UPDATED.value,
        "modified": LibrarySyncCandidateStatus.UPDATED.value,
        "same": LibrarySyncCandidateStatus.UNCHANGED.value,
        "no_change": LibrarySyncCandidateStatus.UNCHANGED.value,
        "no_changes": LibrarySyncCandidateStatus.UNCHANGED.value,
        "revision": LibrarySyncCandidateStatus.REVISION_CREATED.value,
        "new_revision": LibrarySyncCandidateStatus.REVISION_CREATED.value,
        "publishable": LibrarySyncCandidateStatus.VALID.value,
        "not_publishable": LibrarySyncCandidateStatus.INVALID.value,
        "duplicate_uid": LibrarySyncCandidateStatus.DUPLICATE.value,
        "fail": LibrarySyncCandidateStatus.FAILED.value,
        "failure": LibrarySyncCandidateStatus.FAILED.value,
        "exception": LibrarySyncCandidateStatus.ERROR.value,
    }

    if text in aliases:
        return aliases[text]

    if text in LibrarySyncCandidateStatus.values():
        return text

    return LibrarySyncCandidateStatus.UNKNOWN.value


@lru_cache(maxsize=256)
def normalize_issue_severity(value: Any) -> str:
    text = str(value or "").strip().lower()

    aliases = {
        "warn": LibrarySyncIssueSeverity.WARNING.value,
        "err": LibrarySyncIssueSeverity.ERROR.value,
        "critical": LibrarySyncIssueSeverity.FATAL.value,
        "fatal_error": LibrarySyncIssueSeverity.FATAL.value,
    }

    if text in aliases:
        return aliases[text]

    if text in LibrarySyncIssueSeverity.values():
        return text

    return LibrarySyncIssueSeverity.WARNING.value


@lru_cache(maxsize=256)
def normalize_sync_operation(value: Any) -> str:
    text = str(value or "").strip().lower().replace("-", "_").replace(" ", "_")

    aliases = {
        "insert_family": LibrarySyncOperation.UPSERT_FAMILY.value,
        "update_family": LibrarySyncOperation.UPSERT_FAMILY.value,
        "family_upsert": LibrarySyncOperation.UPSERT_FAMILY.value,
        "revision_create": LibrarySyncOperation.CREATE_REVISION.value,
        "revision_created": LibrarySyncOperation.CREATE_REVISION.value,
        "variants": LibrarySyncOperation.REPLACE_VARIANTS.value,
        "assets": LibrarySyncOperation.REPLACE_ASSETS.value,
        "documents": LibrarySyncOperation.REPLACE_DOCUMENTS.value,
        "issues": LibrarySyncOperation.SAVE_ISSUES.value,
        "missing_deleted": LibrarySyncOperation.MARK_MISSING_DELETED.value,
    }

    if text in aliases:
        return aliases[text]

    if text in LibrarySyncOperation.values():
        return text

    return LibrarySyncOperation.NONE.value


def clear_sync_result_caches() -> Dict[str, Any]:
    """Leert alle lokalen Normalisierungs-Caches dieser Datei."""

    normalize_sync_status.cache_clear()
    normalize_candidate_status.cache_clear()
    normalize_issue_severity.cache_clear()
    normalize_sync_operation.cache_clear()

    return {
        "ok": True,
        "cleared": [
            "normalize_sync_status",
            "normalize_candidate_status",
            "normalize_issue_severity",
            "normalize_sync_operation",
        ],
    }


# ---------------------------------------------------------------------------
# Generic helpers
# ---------------------------------------------------------------------------


def utcnow() -> datetime:
    """Timezone-aware UTC timestamp."""

    return datetime.now(timezone.utc)


def safe_isoformat(value: Any) -> Optional[str]:
    if value is None:
        return None

    if isinstance(value, datetime):
        return value.isoformat()

    text = str(value).strip()
    return text or None


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

    if text in {"1", "true", "yes", "y", "on"}:
        return True

    if text in {"0", "false", "no", "n", "off"}:
        return False

    return default


def normalize_string(value: Any) -> Optional[str]:
    if value is None:
        return None

    text = str(value).strip()
    return text or None


def normalize_vplib_uid(value: Any) -> Optional[str]:
    text = normalize_string(value)
    return text.lower() if text else None


def json_safe(value: Any) -> Any:
    """Konvertiert typische Python-Objekte in JSON-kompatible Strukturen."""

    if value is None:
        return None

    if is_dataclass(value):
        return json_safe(asdict(value))

    if isinstance(value, Mapping):
        return {str(key): json_safe(item) for key, item in value.items()}

    if isinstance(value, (list, tuple, set)):
        return [json_safe(item) for item in value]

    if isinstance(value, datetime):
        return value.isoformat()

    if isinstance(value, Path):
        return str(value)

    if isinstance(value, Enum):
        return value.value

    return value


def to_mapping(value: Any) -> Dict[str, Any]:
    """
    Konvertiert Mapping, Dataclass oder fremdes Objekt defensiv in ein Dict.

    Diese Funktion wirft nicht, sondern liefert bei unbekannten/kaputten
    Objekten ein bestmögliches Teil-Dict.
    """

    if value is None:
        return {}

    if isinstance(value, Mapping):
        return dict(value)

    if is_dataclass(value):
        return dict(asdict(value))

    if hasattr(value, "to_dict") and callable(value.to_dict):
        try:
            result = value.to_dict()
            if isinstance(result, Mapping):
                return dict(result)
        except Exception:
            pass

    result: Dict[str, Any] = {}

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


def truncate_list(values: Sequence[Any], limit: int) -> List[Any]:
    if limit <= 0:
        return []

    return list(values[:limit])


def exception_to_issue(
    exc: BaseException,
    *,
    code: str = "sync.exception",
    scope: Optional[str] = None,
    path: Optional[str] = None,
    include_traceback: bool = True,
) -> "LibrarySyncIssue":
    metadata: Dict[str, Any] = {
        "exception_type": exc.__class__.__name__,
    }

    if include_traceback:
        metadata["traceback"] = traceback_module.format_exc()

    return LibrarySyncIssue(
        severity=LibrarySyncIssueSeverity.ERROR.value,
        code=code,
        message=str(exc),
        scope=scope,
        path=path,
        metadata=metadata,
    )


# ---------------------------------------------------------------------------
# Domain models
# ---------------------------------------------------------------------------


@dataclass
class LibrarySyncIssue:
    """
    Einzelnes Issue aus Sync, Scan, Validation, DB-Upsert oder Publication.

    Ein Issue kann global sein oder einem konkreten Package/Kandidaten gehören.
    """

    severity: str = LibrarySyncIssueSeverity.WARNING.value
    code: Optional[str] = None
    message: Optional[str] = None
    scope: Optional[str] = None
    path: Optional[str] = None
    field: Optional[str] = None
    source_path: Optional[str] = None
    vplib_uid: Optional[str] = None
    family_id: Optional[str] = None
    package_id: Optional[str] = None
    revision_hash: Optional[str] = None
    operation: str = LibrarySyncOperation.NONE.value
    created_at: datetime = dataclass_field(default_factory=utcnow)
    payload: Dict[str, Any] = dataclass_field(default_factory=dict)
    metadata: Dict[str, Any] = dataclass_field(default_factory=dict)

    def __post_init__(self) -> None:
        self.severity = normalize_issue_severity(self.severity)
        self.operation = normalize_sync_operation(self.operation)
        self.vplib_uid = normalize_vplib_uid(self.vplib_uid)
        self.family_id = normalize_string(self.family_id)
        self.package_id = normalize_string(self.package_id)
        self.revision_hash = normalize_string(self.revision_hash)

    @property
    def is_error(self) -> bool:
        return self.severity in {
            LibrarySyncIssueSeverity.ERROR.value,
            LibrarySyncIssueSeverity.FATAL.value,
        }

    @property
    def is_warning(self) -> bool:
        return self.severity == LibrarySyncIssueSeverity.WARNING.value

    @classmethod
    def from_mapping(cls, value: Any) -> "LibrarySyncIssue":
        data = to_mapping(value)

        return cls(
            severity=data.get("severity") or data.get("level") or LibrarySyncIssueSeverity.WARNING.value,
            code=data.get("code"),
            message=data.get("message") or data.get("error"),
            scope=data.get("scope"),
            path=data.get("path"),
            field=data.get("field"),
            source_path=data.get("source_path"),
            vplib_uid=data.get("vplib_uid"),
            family_id=data.get("family_id"),
            package_id=data.get("package_id"),
            revision_hash=data.get("revision_hash"),
            operation=data.get("operation") or LibrarySyncOperation.NONE.value,
            created_at=data.get("created_at") or utcnow(),
            payload=dict(data.get("payload") or {}),
            metadata=dict(data.get("metadata") or data.get("meta") or {}),
        )

    def to_dict(self) -> Dict[str, Any]:
        return {
            "severity": self.severity,
            "code": self.code,
            "message": self.message,
            "scope": self.scope,
            "path": self.path,
            "field": self.field,
            "source_path": self.source_path,
            "vplib_uid": self.vplib_uid,
            "family_id": self.family_id,
            "package_id": self.package_id,
            "revision_hash": self.revision_hash,
            "operation": self.operation,
            "created_at": safe_isoformat(self.created_at),
            "payload": json_safe(self.payload),
            "metadata": json_safe(self.metadata),
            "is_error": self.is_error,
            "is_warning": self.is_warning,
        }


@dataclass
class LibrarySyncOperationResult:
    """
    Ergebnis einer einzelnen Operation innerhalb eines Kandidaten-Syncs.

    Beispiele:
        - family upserted
        - revision unchanged
        - variants replaced
        - assets replaced
        - documents replaced
    """

    operation: str = LibrarySyncOperation.NONE.value
    status: str = LibrarySyncCandidateStatus.UNKNOWN.value
    message: Optional[str] = None
    affected_count: int = 0
    created_count: int = 0
    updated_count: int = 0
    skipped_count: int = 0
    error_count: int = 0
    started_at: Optional[datetime] = None
    finished_at: Optional[datetime] = None
    duration_ms: Optional[int] = None
    payload: Dict[str, Any] = dataclass_field(default_factory=dict)
    metadata: Dict[str, Any] = dataclass_field(default_factory=dict)

    def __post_init__(self) -> None:
        self.operation = normalize_sync_operation(self.operation)
        self.status = normalize_candidate_status(self.status)
        self.affected_count = safe_int(self.affected_count)
        self.created_count = safe_int(self.created_count)
        self.updated_count = safe_int(self.updated_count)
        self.skipped_count = safe_int(self.skipped_count)
        self.error_count = safe_int(self.error_count)

    @classmethod
    def from_mapping(cls, value: Any) -> "LibrarySyncOperationResult":
        data = to_mapping(value)

        return cls(
            operation=data.get("operation") or LibrarySyncOperation.NONE.value,
            status=data.get("status") or LibrarySyncCandidateStatus.UNKNOWN.value,
            message=data.get("message"),
            affected_count=data.get("affected_count", data.get("count", 0)),
            created_count=data.get("created_count", 0),
            updated_count=data.get("updated_count", 0),
            skipped_count=data.get("skipped_count", 0),
            error_count=data.get("error_count", 0),
            started_at=data.get("started_at"),
            finished_at=data.get("finished_at"),
            duration_ms=data.get("duration_ms"),
            payload=dict(data.get("payload") or {}),
            metadata=dict(data.get("metadata") or data.get("meta") or {}),
        )

    def to_dict(self) -> Dict[str, Any]:
        return {
            "operation": self.operation,
            "status": self.status,
            "message": self.message,
            "affected_count": self.affected_count,
            "created_count": self.created_count,
            "updated_count": self.updated_count,
            "skipped_count": self.skipped_count,
            "error_count": self.error_count,
            "started_at": safe_isoformat(self.started_at),
            "finished_at": safe_isoformat(self.finished_at),
            "duration_ms": self.duration_ms,
            "payload": json_safe(self.payload),
            "metadata": json_safe(self.metadata),
        }


@dataclass
class LibrarySyncCandidateResult:
    """
    Sync-Ergebnis für ein einzelnes Package / eine einzelne Family.

    Primäre technische Identität:
        vplib_uid

    Semantische Identitäten:
        family_id
        package_id
    """

    status: str = LibrarySyncCandidateStatus.UNKNOWN.value
    vplib_uid: Optional[str] = None
    family_id: Optional[str] = None
    package_id: Optional[str] = None
    family_slug: Optional[str] = None
    label: Optional[str] = None
    object_kind: Optional[str] = None
    domain: Optional[str] = None
    category: Optional[str] = None
    subcategory: Optional[str] = None
    source_path: Optional[str] = None
    package_root: Optional[str] = None
    revision_hash: Optional[str] = None
    previous_revision_hash: Optional[str] = None
    revision_created: bool = False
    family_created: bool = False
    family_updated: bool = False
    published: bool = False
    skipped: bool = False
    duplicate: bool = False
    valid: Optional[bool] = None
    validation_status: Optional[str] = None
    scan_run_id: Any = None
    family_db_id: Any = None
    revision_db_id: Any = None
    variant_count: int = 0
    asset_count: int = 0
    document_count: int = 0
    issue_count: int = 0
    warning_count: int = 0
    error_count: int = 0
    operations: List[LibrarySyncOperationResult] = dataclass_field(default_factory=list)
    issues: List[LibrarySyncIssue] = dataclass_field(default_factory=list)
    payload: Dict[str, Any] = dataclass_field(default_factory=dict)
    metadata: Dict[str, Any] = dataclass_field(default_factory=dict)
    started_at: Optional[datetime] = None
    finished_at: Optional[datetime] = None
    duration_ms: Optional[int] = None

    def __post_init__(self) -> None:
        self.status = normalize_candidate_status(self.status)
        self.vplib_uid = normalize_vplib_uid(self.vplib_uid)
        self.family_id = normalize_string(self.family_id)
        self.package_id = normalize_string(self.package_id)
        self.family_slug = normalize_string(self.family_slug)
        self.revision_hash = normalize_string(self.revision_hash)
        self.previous_revision_hash = normalize_string(self.previous_revision_hash)

        self.variant_count = safe_int(self.variant_count)
        self.asset_count = safe_int(self.asset_count)
        self.document_count = safe_int(self.document_count)
        self.issue_count = safe_int(self.issue_count)
        self.warning_count = safe_int(self.warning_count)
        self.error_count = safe_int(self.error_count)

        self.operations = [
            item if isinstance(item, LibrarySyncOperationResult) else LibrarySyncOperationResult.from_mapping(item)
            for item in self.operations
        ]

        self.issues = [
            item if isinstance(item, LibrarySyncIssue) else LibrarySyncIssue.from_mapping(item)
            for item in self.issues
        ]

        if self.issue_count == 0:
            self.issue_count = len(self.issues)

        if self.warning_count == 0:
            self.warning_count = sum(1 for issue in self.issues if issue.is_warning)

        if self.error_count == 0:
            self.error_count = sum(1 for issue in self.issues if issue.is_error)

        if self.valid is None:
            self.valid = self.status in {
                LibrarySyncCandidateStatus.VALID.value,
                LibrarySyncCandidateStatus.INSERTED.value,
                LibrarySyncCandidateStatus.UPDATED.value,
                LibrarySyncCandidateStatus.UNCHANGED.value,
                LibrarySyncCandidateStatus.REVISION_CREATED.value,
                LibrarySyncCandidateStatus.PUBLISHED.value,
            }

    @property
    def ok(self) -> bool:
        return self.error_count == 0 and self.status not in {
            LibrarySyncCandidateStatus.INVALID.value,
            LibrarySyncCandidateStatus.FAILED.value,
            LibrarySyncCandidateStatus.ERROR.value,
            LibrarySyncCandidateStatus.DUPLICATE.value,
        }

    @property
    def changed(self) -> bool:
        return bool(self.family_created or self.family_updated or self.revision_created)

    @classmethod
    def from_mapping(cls, value: Any) -> "LibrarySyncCandidateResult":
        data = to_mapping(value)

        return cls(
            status=data.get("status") or LibrarySyncCandidateStatus.UNKNOWN.value,
            vplib_uid=data.get("vplib_uid"),
            family_id=data.get("family_id"),
            package_id=data.get("package_id"),
            family_slug=data.get("family_slug") or data.get("slug"),
            label=data.get("label") or data.get("name"),
            object_kind=data.get("object_kind"),
            domain=data.get("domain"),
            category=data.get("category"),
            subcategory=data.get("subcategory"),
            source_path=data.get("source_path"),
            package_root=data.get("package_root"),
            revision_hash=data.get("revision_hash"),
            previous_revision_hash=data.get("previous_revision_hash"),
            revision_created=safe_bool(data.get("revision_created"), False),
            family_created=safe_bool(data.get("family_created"), False),
            family_updated=safe_bool(data.get("family_updated"), False),
            published=safe_bool(data.get("published"), False),
            skipped=safe_bool(data.get("skipped"), False),
            duplicate=safe_bool(data.get("duplicate"), False),
            valid=data.get("valid"),
            validation_status=data.get("validation_status"),
            scan_run_id=data.get("scan_run_id"),
            family_db_id=data.get("family_db_id"),
            revision_db_id=data.get("revision_db_id"),
            variant_count=data.get("variant_count", 0),
            asset_count=data.get("asset_count", 0),
            document_count=data.get("document_count", 0),
            issue_count=data.get("issue_count", 0),
            warning_count=data.get("warning_count", 0),
            error_count=data.get("error_count", 0),
            operations=[
                LibrarySyncOperationResult.from_mapping(item)
                for item in data.get("operations", []) or []
            ],
            issues=[
                LibrarySyncIssue.from_mapping(item)
                for item in data.get("issues", []) or []
            ],
            payload=dict(data.get("payload") or {}),
            metadata=dict(data.get("metadata") or data.get("meta") or {}),
            started_at=data.get("started_at"),
            finished_at=data.get("finished_at"),
            duration_ms=data.get("duration_ms"),
        )

    def add_issue(self, issue: Any) -> None:
        sync_issue = issue if isinstance(issue, LibrarySyncIssue) else LibrarySyncIssue.from_mapping(issue)
        self.issues.append(sync_issue)
        self.issue_count += 1

        if sync_issue.is_warning:
            self.warning_count += 1

        if sync_issue.is_error:
            self.error_count += 1

    def add_operation(self, operation: Any) -> None:
        sync_operation = (
            operation
            if isinstance(operation, LibrarySyncOperationResult)
            else LibrarySyncOperationResult.from_mapping(operation)
        )
        self.operations.append(sync_operation)

    def to_dict(
        self,
        *,
        include_issues: bool = True,
        include_operations: bool = True,
        issue_limit: int = DEFAULT_LIMIT_WARNINGS,
    ) -> Dict[str, Any]:
        issues = self.issues

        return {
            "ok": self.ok,
            "changed": self.changed,
            "status": self.status,
            "vplib_uid": self.vplib_uid,
            "family_id": self.family_id,
            "package_id": self.package_id,
            "family_slug": self.family_slug,
            "label": self.label,
            "object_kind": self.object_kind,
            "domain": self.domain,
            "category": self.category,
            "subcategory": self.subcategory,
            "source_path": self.source_path,
            "package_root": self.package_root,
            "revision_hash": self.revision_hash,
            "previous_revision_hash": self.previous_revision_hash,
            "revision_created": self.revision_created,
            "family_created": self.family_created,
            "family_updated": self.family_updated,
            "published": self.published,
            "skipped": self.skipped,
            "duplicate": self.duplicate,
            "valid": self.valid,
            "validation_status": self.validation_status,
            "scan_run_id": self.scan_run_id,
            "family_db_id": self.family_db_id,
            "revision_db_id": self.revision_db_id,
            "variant_count": self.variant_count,
            "asset_count": self.asset_count,
            "document_count": self.document_count,
            "issue_count": self.issue_count,
            "warning_count": self.warning_count,
            "error_count": self.error_count,
            "operations": [
                item.to_dict()
                for item in self.operations
            ] if include_operations else [],
            "issues": [
                item.to_dict()
                for item in truncate_list(issues, issue_limit)
            ] if include_issues else [],
            "issues_truncated": include_issues and len(issues) > issue_limit,
            "payload": json_safe(self.payload),
            "metadata": json_safe(self.metadata),
            "started_at": safe_isoformat(self.started_at),
            "finished_at": safe_isoformat(self.finished_at),
            "duration_ms": self.duration_ms,
        }


@dataclass
class LibrarySyncStats:
    """Aggregierte Zähler eines Sync-Laufs."""

    total_count: int = 0
    scanned_count: int = 0
    valid_count: int = 0
    invalid_count: int = 0
    inserted_count: int = 0
    updated_count: int = 0
    unchanged_count: int = 0
    revision_created_count: int = 0
    published_count: int = 0
    skipped_count: int = 0
    duplicate_count: int = 0
    deleted_count: int = 0
    failed_count: int = 0
    warning_count: int = 0
    error_count: int = 0
    issue_count: int = 0
    family_count: int = 0
    variant_count: int = 0
    asset_count: int = 0
    document_count: int = 0
    marked_missing_deleted_count: int = 0

    def __post_init__(self) -> None:
        for field_name in self.__dataclass_fields__:
            setattr(self, field_name, safe_int(getattr(self, field_name), 0))

    @classmethod
    def from_candidates(cls, candidates: Iterable[LibrarySyncCandidateResult]) -> "LibrarySyncStats":
        stats = cls()

        for candidate in candidates:
            stats.apply_candidate(candidate)

        return stats

    @classmethod
    def from_mapping(cls, value: Any) -> "LibrarySyncStats":
        data = to_mapping(value)

        return cls(
            total_count=data.get("total_count", data.get("total", 0)),
            scanned_count=data.get("scanned_count", data.get("scanned", 0)),
            valid_count=data.get("valid_count", data.get("valid", 0)),
            invalid_count=data.get("invalid_count", data.get("invalid", 0)),
            inserted_count=data.get("inserted_count", data.get("inserted", 0)),
            updated_count=data.get("updated_count", data.get("updated", 0)),
            unchanged_count=data.get("unchanged_count", data.get("unchanged", 0)),
            revision_created_count=data.get("revision_created_count", data.get("revisions_created", 0)),
            published_count=data.get("published_count", data.get("published", 0)),
            skipped_count=data.get("skipped_count", data.get("skipped", 0)),
            duplicate_count=data.get("duplicate_count", data.get("duplicates", 0)),
            deleted_count=data.get("deleted_count", data.get("deleted", 0)),
            failed_count=data.get("failed_count", data.get("failed", 0)),
            warning_count=data.get("warning_count", data.get("warnings", 0)),
            error_count=data.get("error_count", data.get("errors", 0)),
            issue_count=data.get("issue_count", data.get("issues", 0)),
            family_count=data.get("family_count", data.get("families", 0)),
            variant_count=data.get("variant_count", data.get("variants", 0)),
            asset_count=data.get("asset_count", data.get("assets", 0)),
            document_count=data.get("document_count", data.get("documents", 0)),
            marked_missing_deleted_count=data.get(
                "marked_missing_deleted_count",
                data.get("missing_deleted", 0),
            ),
        )

    def apply_candidate(self, candidate: LibrarySyncCandidateResult) -> None:
        self.total_count += 1

        if candidate.status == LibrarySyncCandidateStatus.SCANNED.value:
            self.scanned_count += 1

        if candidate.valid:
            self.valid_count += 1
        else:
            self.invalid_count += 1

        if candidate.status == LibrarySyncCandidateStatus.INSERTED.value or candidate.family_created:
            self.inserted_count += 1

        if candidate.status == LibrarySyncCandidateStatus.UPDATED.value or candidate.family_updated:
            self.updated_count += 1

        if candidate.status == LibrarySyncCandidateStatus.UNCHANGED.value:
            self.unchanged_count += 1

        if candidate.revision_created:
            self.revision_created_count += 1

        if candidate.published or candidate.status == LibrarySyncCandidateStatus.PUBLISHED.value:
            self.published_count += 1

        if candidate.skipped or candidate.status == LibrarySyncCandidateStatus.SKIPPED.value:
            self.skipped_count += 1

        if candidate.duplicate or candidate.status == LibrarySyncCandidateStatus.DUPLICATE.value:
            self.duplicate_count += 1

        if candidate.status == LibrarySyncCandidateStatus.DELETED.value:
            self.deleted_count += 1

        if candidate.status in {
            LibrarySyncCandidateStatus.FAILED.value,
            LibrarySyncCandidateStatus.ERROR.value,
        }:
            self.failed_count += 1

        self.warning_count += candidate.warning_count
        self.error_count += candidate.error_count
        self.issue_count += candidate.issue_count
        self.variant_count += candidate.variant_count
        self.asset_count += candidate.asset_count
        self.document_count += candidate.document_count

        if candidate.vplib_uid:
            self.family_count += 1

    def merge(self, other: Any) -> "LibrarySyncStats":
        other_stats = other if isinstance(other, LibrarySyncStats) else LibrarySyncStats.from_mapping(other)

        for field_name in self.__dataclass_fields__:
            setattr(
                self,
                field_name,
                safe_int(getattr(self, field_name), 0)
                + safe_int(getattr(other_stats, field_name), 0),
            )

        return self

    @property
    def ok(self) -> bool:
        return self.error_count == 0 and self.failed_count == 0

    def to_dict(self) -> Dict[str, int]:
        return {
            "total_count": self.total_count,
            "scanned_count": self.scanned_count,
            "valid_count": self.valid_count,
            "invalid_count": self.invalid_count,
            "inserted_count": self.inserted_count,
            "updated_count": self.updated_count,
            "unchanged_count": self.unchanged_count,
            "revision_created_count": self.revision_created_count,
            "published_count": self.published_count,
            "skipped_count": self.skipped_count,
            "duplicate_count": self.duplicate_count,
            "deleted_count": self.deleted_count,
            "failed_count": self.failed_count,
            "warning_count": self.warning_count,
            "error_count": self.error_count,
            "issue_count": self.issue_count,
            "family_count": self.family_count,
            "variant_count": self.variant_count,
            "asset_count": self.asset_count,
            "document_count": self.document_count,
            "marked_missing_deleted_count": self.marked_missing_deleted_count,
        }


@dataclass
class LibrarySyncRunInfo:
    """Metadaten eines DB-Sync-Laufs."""

    sync_run_id: Any = None
    scan_run_id: Any = None
    mode: str = DEFAULT_SYNC_MODE
    source: str = DEFAULT_SYNC_SOURCE
    target: str = DEFAULT_SYNC_TARGET
    source_root: Optional[str] = None
    triggered_by: Optional[str] = None
    force_refresh: bool = False
    publish_valid_only: bool = True
    mark_missing_deleted: bool = False
    started_at: datetime = dataclass_field(default_factory=utcnow)
    finished_at: Optional[datetime] = None
    duration_ms: Optional[int] = None
    metadata: Dict[str, Any] = dataclass_field(default_factory=dict)

    @classmethod
    def from_mapping(cls, value: Any) -> "LibrarySyncRunInfo":
        data = to_mapping(value)

        return cls(
            sync_run_id=data.get("sync_run_id"),
            scan_run_id=data.get("scan_run_id"),
            mode=data.get("mode") or DEFAULT_SYNC_MODE,
            source=data.get("source") or DEFAULT_SYNC_SOURCE,
            target=data.get("target") or DEFAULT_SYNC_TARGET,
            source_root=data.get("source_root"),
            triggered_by=data.get("triggered_by"),
            force_refresh=safe_bool(data.get("force_refresh"), False),
            publish_valid_only=safe_bool(data.get("publish_valid_only"), True),
            mark_missing_deleted=safe_bool(data.get("mark_missing_deleted"), False),
            started_at=data.get("started_at") or utcnow(),
            finished_at=data.get("finished_at"),
            duration_ms=data.get("duration_ms"),
            metadata=dict(data.get("metadata") or data.get("meta") or {}),
        )

    def finish(self) -> None:
        if self.finished_at is None:
            self.finished_at = utcnow()

        if self.duration_ms is None and self.started_at and self.finished_at:
            try:
                self.duration_ms = int((self.finished_at - self.started_at).total_seconds() * 1000)
            except Exception:
                self.duration_ms = None

    def to_dict(self) -> Dict[str, Any]:
        return {
            "sync_run_id": self.sync_run_id,
            "scan_run_id": self.scan_run_id,
            "mode": self.mode,
            "source": self.source,
            "target": self.target,
            "source_root": self.source_root,
            "triggered_by": self.triggered_by,
            "force_refresh": self.force_refresh,
            "publish_valid_only": self.publish_valid_only,
            "mark_missing_deleted": self.mark_missing_deleted,
            "started_at": safe_isoformat(self.started_at),
            "finished_at": safe_isoformat(self.finished_at),
            "duration_ms": self.duration_ms,
            "metadata": json_safe(self.metadata),
        }


@dataclass
class LibrarySyncResult:
    """
    Gesamtergebnis eines Creative-Library-DB-Syncs.

    Dieses Modell ist die primäre Rückgabe von:

        library_db_sync_service.sync_library_to_db(...)
        POST /api/v1/vplib/library/sync
    """

    ok: bool = False
    status: str = LibrarySyncStatus.UNKNOWN.value
    message: Optional[str] = None
    run: LibrarySyncRunInfo = dataclass_field(default_factory=LibrarySyncRunInfo)
    stats: LibrarySyncStats = dataclass_field(default_factory=LibrarySyncStats)
    candidates: List[LibrarySyncCandidateResult] = dataclass_field(default_factory=list)
    issues: List[LibrarySyncIssue] = dataclass_field(default_factory=list)
    warnings: List[LibrarySyncIssue] = dataclass_field(default_factory=list)
    errors: List[LibrarySyncIssue] = dataclass_field(default_factory=list)
    payload: Dict[str, Any] = dataclass_field(default_factory=dict)
    metadata: Dict[str, Any] = dataclass_field(default_factory=dict)
    model_version: str = SYNC_RESULT_MODEL_VERSION
    generated_at: datetime = dataclass_field(default_factory=utcnow)

    def __post_init__(self) -> None:
        self.status = normalize_sync_status(self.status)

        if not isinstance(self.run, LibrarySyncRunInfo):
            self.run = LibrarySyncRunInfo.from_mapping(self.run)

        if not isinstance(self.stats, LibrarySyncStats):
            self.stats = LibrarySyncStats.from_mapping(self.stats)

        self.candidates = [
            item if isinstance(item, LibrarySyncCandidateResult) else LibrarySyncCandidateResult.from_mapping(item)
            for item in self.candidates
        ]

        self.issues = [
            item if isinstance(item, LibrarySyncIssue) else LibrarySyncIssue.from_mapping(item)
            for item in self.issues
        ]

        self.warnings = [
            item if isinstance(item, LibrarySyncIssue) else LibrarySyncIssue.from_mapping(item)
            for item in self.warnings
        ]

        self.errors = [
            item if isinstance(item, LibrarySyncIssue) else LibrarySyncIssue.from_mapping(item)
            for item in self.errors
        ]

        self._recalculate_status()

    @classmethod
    def from_mapping(cls, value: Any) -> "LibrarySyncResult":
        data = to_mapping(value)

        return cls(
            ok=safe_bool(data.get("ok"), False),
            status=data.get("status") or LibrarySyncStatus.UNKNOWN.value,
            message=data.get("message"),
            run=LibrarySyncRunInfo.from_mapping(data.get("run") or {}),
            stats=LibrarySyncStats.from_mapping(data.get("stats") or {}),
            candidates=[
                LibrarySyncCandidateResult.from_mapping(item)
                for item in data.get("candidates", []) or []
            ],
            issues=[
                LibrarySyncIssue.from_mapping(item)
                for item in data.get("issues", []) or []
            ],
            warnings=[
                LibrarySyncIssue.from_mapping(item)
                for item in data.get("warnings", []) or []
            ],
            errors=[
                LibrarySyncIssue.from_mapping(item)
                for item in data.get("errors", []) or []
            ],
            payload=dict(data.get("payload") or {}),
            metadata=dict(data.get("metadata") or data.get("meta") or {}),
            model_version=data.get("model_version") or SYNC_RESULT_MODEL_VERSION,
            generated_at=data.get("generated_at") or utcnow(),
        )

    @classmethod
    def empty(
        cls,
        *,
        message: str = "No library packages found for sync.",
        run: Optional[LibrarySyncRunInfo] = None,
    ) -> "LibrarySyncResult":
        return cls(
            ok=True,
            status=LibrarySyncStatus.EMPTY.value,
            message=message,
            run=run or LibrarySyncRunInfo(),
            stats=LibrarySyncStats(),
            candidates=[],
        )

    @classmethod
    def failure(
        cls,
        exc: Optional[BaseException] = None,
        *,
        message: Optional[str] = None,
        run: Optional[LibrarySyncRunInfo] = None,
        include_traceback: bool = True,
    ) -> "LibrarySyncResult":
        issue = None

        if exc is not None:
            issue = exception_to_issue(
                exc,
                code="sync.failed",
                scope="library_sync",
                include_traceback=include_traceback,
            )
        else:
            issue = LibrarySyncIssue(
                severity=LibrarySyncIssueSeverity.ERROR.value,
                code="sync.failed",
                message=message or "Library sync failed.",
                scope="library_sync",
            )

        return cls(
            ok=False,
            status=LibrarySyncStatus.FAILED.value,
            message=message or issue.message,
            run=run or LibrarySyncRunInfo(),
            stats=LibrarySyncStats(error_count=1, issue_count=1, failed_count=1),
            issues=[issue],
            errors=[issue],
        )

    def add_candidate(self, candidate: Any) -> LibrarySyncCandidateResult:
        sync_candidate = (
            candidate
            if isinstance(candidate, LibrarySyncCandidateResult)
            else LibrarySyncCandidateResult.from_mapping(candidate)
        )

        self.candidates.append(sync_candidate)
        self.stats.apply_candidate(sync_candidate)

        for issue in sync_candidate.issues:
            self.add_issue(issue)

        self._recalculate_status()
        return sync_candidate

    def add_issue(self, issue: Any) -> LibrarySyncIssue:
        sync_issue = issue if isinstance(issue, LibrarySyncIssue) else LibrarySyncIssue.from_mapping(issue)

        self.issues.append(sync_issue)

        if sync_issue.is_warning:
            self.warnings.append(sync_issue)

        if sync_issue.is_error:
            self.errors.append(sync_issue)

        self.stats.issue_count += 1

        if sync_issue.is_warning:
            self.stats.warning_count += 1

        if sync_issue.is_error:
            self.stats.error_count += 1

        self._recalculate_status()
        return sync_issue

    def finish(self, *, message: Optional[str] = None) -> "LibrarySyncResult":
        self.run.finish()

        if message is not None:
            self.message = message

        self._recalculate_status(final=True)
        self.generated_at = utcnow()
        return self

    def _recalculate_status(self, *, final: bool = False) -> None:
        error_count = self.stats.error_count + len(self.errors)
        failed_count = self.stats.failed_count

        if error_count > 0 or failed_count > 0:
            self.ok = False
            self.status = LibrarySyncStatus.FAILED.value if final else LibrarySyncStatus.ERROR.value
            return

        if self.stats.total_count == 0 and not self.candidates:
            self.ok = True
            self.status = LibrarySyncStatus.EMPTY.value if final else self.status
            return

        if self.stats.warning_count > 0 or self.warnings:
            self.ok = True
            self.status = LibrarySyncStatus.PARTIAL.value
            return

        self.ok = True
        self.status = LibrarySyncStatus.OK.value if final else LibrarySyncStatus.RUNNING.value

    def to_dict(
        self,
        *,
        include_candidates: bool = True,
        include_issues: bool = True,
        include_candidate_issues: bool = True,
        include_operations: bool = True,
        candidate_limit: int = DEFAULT_LIMIT_CANDIDATES,
        issue_limit: int = DEFAULT_LIMIT_ERRORS,
    ) -> Dict[str, Any]:
        candidates = self.candidates
        issues = self.issues
        warnings = self.warnings
        errors = self.errors

        return {
            "ok": self.ok,
            "status": self.status,
            "message": self.message,
            "run": self.run.to_dict(),
            "stats": self.stats.to_dict(),
            "candidates": [
                item.to_dict(
                    include_issues=include_candidate_issues,
                    include_operations=include_operations,
                )
                for item in truncate_list(candidates, candidate_limit)
            ] if include_candidates else [],
            "candidates_truncated": include_candidates and len(candidates) > candidate_limit,
            "issues": [
                item.to_dict()
                for item in truncate_list(issues, issue_limit)
            ] if include_issues else [],
            "issues_truncated": include_issues and len(issues) > issue_limit,
            "warnings": [
                item.to_dict()
                for item in truncate_list(warnings, issue_limit)
            ] if include_issues else [],
            "warnings_truncated": include_issues and len(warnings) > issue_limit,
            "errors": [
                item.to_dict()
                for item in truncate_list(errors, issue_limit)
            ] if include_issues else [],
            "errors_truncated": include_issues and len(errors) > issue_limit,
            "payload": json_safe(self.payload),
            "metadata": json_safe(self.metadata),
            "model_version": self.model_version,
            "generated_at": safe_isoformat(self.generated_at),
        }


# ---------------------------------------------------------------------------
# Builders / convenience functions
# ---------------------------------------------------------------------------


def build_sync_result_from_candidates(
    candidates: Iterable[Any],
    *,
    run: Optional[LibrarySyncRunInfo] = None,
    message: Optional[str] = None,
    finish: bool = True,
) -> LibrarySyncResult:
    result = LibrarySyncResult(
        status=LibrarySyncStatus.RUNNING.value,
        run=run or LibrarySyncRunInfo(),
        message=message,
    )

    for candidate in candidates:
        result.add_candidate(candidate)

    if finish:
        result.finish(message=message)

    return result


def build_empty_sync_result(
    *,
    message: str = "No library packages found for sync.",
    run: Optional[LibrarySyncRunInfo] = None,
) -> LibrarySyncResult:
    return LibrarySyncResult.empty(message=message, run=run)


def build_error_sync_result(
    exc: Optional[BaseException] = None,
    *,
    message: Optional[str] = None,
    run: Optional[LibrarySyncRunInfo] = None,
    include_traceback: bool = True,
) -> LibrarySyncResult:
    return LibrarySyncResult.failure(
        exc,
        message=message,
        run=run,
        include_traceback=include_traceback,
    )


def build_sync_response(
    result: Any,
    *,
    include_candidates: bool = True,
    include_issues: bool = True,
    include_candidate_issues: bool = True,
    include_operations: bool = True,
) -> Dict[str, Any]:
    sync_result = result if isinstance(result, LibrarySyncResult) else LibrarySyncResult.from_mapping(result)

    return sync_result.to_dict(
        include_candidates=include_candidates,
        include_issues=include_issues,
        include_candidate_issues=include_candidate_issues,
        include_operations=include_operations,
    )


def get_sync_result_health() -> Dict[str, Any]:
    """Leichter Health-Check für die Domain-Datei."""

    return {
        "ok": True,
        "status": "ok",
        "component": SYNC_RESULT_COMPONENT_NAME,
        "api_version": SYNC_RESULT_API_VERSION,
        "model_version": SYNC_RESULT_MODEL_VERSION,
        "version": __version__,
        "enums": {
            "sync_status": list(LibrarySyncStatus.values()),
            "candidate_status": list(LibrarySyncCandidateStatus.values()),
            "issue_severity": list(LibrarySyncIssueSeverity.values()),
            "operation": list(LibrarySyncOperation.values()),
        },
        "cache": {
            "normalize_sync_status": normalize_sync_status.cache_info()._asdict(),
            "normalize_candidate_status": normalize_candidate_status.cache_info()._asdict(),
            "normalize_issue_severity": normalize_issue_severity.cache_info()._asdict(),
            "normalize_sync_operation": normalize_sync_operation.cache_info()._asdict(),
        },
    }


def assert_sync_result_ready() -> Dict[str, Any]:
    health = get_sync_result_health()

    if not health.get("ok"):
        raise RuntimeError("Sync result domain models are not ready.")

    return health


# ---------------------------------------------------------------------------
# Public exports
# ---------------------------------------------------------------------------

__all__ = [
    # Metadata
    "SYNC_RESULT_COMPONENT_NAME",
    "SYNC_RESULT_API_VERSION",
    "SYNC_RESULT_MODEL_VERSION",
    "DEFAULT_SYNC_MODE",
    "DEFAULT_SYNC_SOURCE",
    "DEFAULT_SYNC_TARGET",

    # Enums
    "LibrarySyncStatus",
    "LibrarySyncCandidateStatus",
    "LibrarySyncIssueSeverity",
    "LibrarySyncOperation",

    # Helpers
    "utcnow",
    "safe_isoformat",
    "safe_int",
    "safe_bool",
    "normalize_string",
    "normalize_vplib_uid",
    "normalize_sync_status",
    "normalize_candidate_status",
    "normalize_issue_severity",
    "normalize_sync_operation",
    "clear_sync_result_caches",
    "json_safe",
    "to_mapping",
    "exception_to_issue",

    # Models
    "LibrarySyncIssue",
    "LibrarySyncOperationResult",
    "LibrarySyncCandidateResult",
    "LibrarySyncStats",
    "LibrarySyncRunInfo",
    "LibrarySyncResult",

    # Builders
    "build_sync_result_from_candidates",
    "build_empty_sync_result",
    "build_error_sync_result",
    "build_sync_response",

    # Health
    "get_sync_result_health",
    "assert_sync_result_ready",
]