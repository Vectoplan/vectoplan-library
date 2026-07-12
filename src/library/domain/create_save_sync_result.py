# services/vectoplan-library/src/library/domain/create_save_sync_result.py
"""Domain contract for Create -> Source Save -> DB Sync -> Published Verify.

The workflow spans two persistence systems: the source filesystem and
PostgreSQL. It is therefore a saga, not one ACID transaction. This module
models that saga without importing Flask, SQLAlchemy, repositories, scanners,
or filesystem services.

All public result objects are immutable, bounded during serialization,
JSON-safe, cache-aware, and suitable for route responses, audit logs,
diagnostics, and integration tests.
"""

from __future__ import annotations

from dataclasses import dataclass, field, fields, is_dataclass, replace
from datetime import date, datetime, time, timezone
from decimal import Decimal
from enum import Enum
from functools import lru_cache
from itertools import islice
from pathlib import Path
from types import MappingProxyType
from typing import Any, Iterable, Mapping
from uuid import UUID, uuid4


SCHEMA_VERSION = "vectoplan_library.domain.create_save_sync_result.v1"
COMPONENT = "create-save-sync-result"
COMPONENT_VERSION = "1.0.0"

MAX_JSON_DEPTH = 24
MAX_MAPPING_ITEMS = 250
MAX_SEQUENCE_ITEMS = 500
MAX_STRING_LENGTH = 16_384
MAX_ISSUES = 250
MAX_PHASES = 32


class CreateSaveSyncResultError(ValueError):
    """Raised when a result violates a domain invariant."""


class CreateSaveSyncStatus(str, Enum):
    PENDING = "pending"
    RUNNING = "running"
    SOURCE_SAVED = "source_saved"
    PUBLISHED = "published"
    UNCHANGED = "unchanged"
    INVALID = "invalid"
    CONFLICT = "conflict"
    PARTIAL_FAILURE = "partial_failure"
    FAILED = "failed"


class CreateSaveSyncPhase(str, Enum):
    REQUEST = "request"
    SOURCE_SAVE = "source_save"
    PACKAGE_SCAN = "package_scan"
    PACKAGE_VALIDATION = "package_validation"
    DB_SYNC = "db_sync"
    CACHE_INVALIDATION = "cache_invalidation"
    PUBLISHED_VERIFICATION = "published_verification"
    COMPLETED = "completed"


class CreateSaveSyncPhaseState(str, Enum):
    PENDING = "pending"
    RUNNING = "running"
    SUCCEEDED = "succeeded"
    SKIPPED = "skipped"
    FAILED = "failed"


class CreateSaveSyncIssueSeverity(str, Enum):
    INFO = "info"
    WARNING = "warning"
    ERROR = "error"
    FATAL = "fatal"


class CreateSaveSyncOperation(str, Enum):
    NONE = "none"
    INSERTED = "inserted"
    UPDATED = "updated"
    UNCHANGED = "unchanged"
    SKIPPED = "skipped"


_TERMINAL_STATUSES = frozenset(
    {
        CreateSaveSyncStatus.PUBLISHED,
        CreateSaveSyncStatus.UNCHANGED,
        CreateSaveSyncStatus.INVALID,
        CreateSaveSyncStatus.CONFLICT,
        CreateSaveSyncStatus.PARTIAL_FAILURE,
        CreateSaveSyncStatus.FAILED,
    }
)
_SUCCESS_STATUSES = frozenset(
    {
        CreateSaveSyncStatus.PUBLISHED,
        CreateSaveSyncStatus.UNCHANGED,
    }
)
_PHASE_ORDER = {
    phase: index
    for index, phase in enumerate(
        (
            CreateSaveSyncPhase.REQUEST,
            CreateSaveSyncPhase.SOURCE_SAVE,
            CreateSaveSyncPhase.PACKAGE_SCAN,
            CreateSaveSyncPhase.PACKAGE_VALIDATION,
            CreateSaveSyncPhase.DB_SYNC,
            CreateSaveSyncPhase.CACHE_INVALIDATION,
            CreateSaveSyncPhase.PUBLISHED_VERIFICATION,
            CreateSaveSyncPhase.COMPLETED,
        )
    )
}


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


@lru_cache(maxsize=512)
def _parse_datetime_cached(value: str) -> datetime:
    normalized = value.strip()
    if not normalized:
        raise ValueError("datetime must not be empty")
    if normalized.endswith("Z"):
        normalized = f"{normalized[:-1]}+00:00"
    parsed = datetime.fromisoformat(normalized)
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


@lru_cache(maxsize=256)
def _parse_status_cached(value: str) -> CreateSaveSyncStatus:
    return CreateSaveSyncStatus(value.strip().lower().replace("-", "_"))


@lru_cache(maxsize=256)
def _parse_phase_cached(value: str) -> CreateSaveSyncPhase:
    return CreateSaveSyncPhase(value.strip().lower().replace("-", "_"))


@lru_cache(maxsize=256)
def _parse_phase_state_cached(value: str) -> CreateSaveSyncPhaseState:
    return CreateSaveSyncPhaseState(value.strip().lower().replace("-", "_"))


@lru_cache(maxsize=256)
def _parse_severity_cached(value: str) -> CreateSaveSyncIssueSeverity:
    return CreateSaveSyncIssueSeverity(value.strip().lower().replace("-", "_"))


@lru_cache(maxsize=256)
def _parse_operation_cached(value: str) -> CreateSaveSyncOperation:
    return CreateSaveSyncOperation(value.strip().lower().replace("-", "_"))


def _coerce_datetime(
    value: datetime | str | None,
    *,
    default: datetime | None = None,
) -> datetime | None:
    if value is None:
        return default
    if isinstance(value, datetime):
        parsed = value
        if parsed.tzinfo is None:
            parsed = parsed.replace(tzinfo=timezone.utc)
        return parsed.astimezone(timezone.utc)
    if isinstance(value, str):
        return _parse_datetime_cached(value)
    raise TypeError(f"unsupported datetime type: {type(value).__name__}")


def _isoformat(value: datetime | None) -> str | None:
    normalized = _coerce_datetime(value)
    return (
        normalized.isoformat().replace("+00:00", "Z")
        if normalized is not None
        else None
    )


def _coerce_status(value: CreateSaveSyncStatus | str | None) -> CreateSaveSyncStatus:
    if value is None:
        return CreateSaveSyncStatus.PENDING
    return value if isinstance(value, CreateSaveSyncStatus) else _parse_status_cached(str(value))


def _coerce_phase(value: CreateSaveSyncPhase | str | None) -> CreateSaveSyncPhase:
    if value is None:
        return CreateSaveSyncPhase.REQUEST
    return value if isinstance(value, CreateSaveSyncPhase) else _parse_phase_cached(str(value))


def _coerce_phase_state(
    value: CreateSaveSyncPhaseState | str | None,
) -> CreateSaveSyncPhaseState:
    if value is None:
        return CreateSaveSyncPhaseState.PENDING
    return (
        value
        if isinstance(value, CreateSaveSyncPhaseState)
        else _parse_phase_state_cached(str(value))
    )


def _coerce_severity(
    value: CreateSaveSyncIssueSeverity | str | None,
) -> CreateSaveSyncIssueSeverity:
    if value is None:
        return CreateSaveSyncIssueSeverity.ERROR
    return (
        value
        if isinstance(value, CreateSaveSyncIssueSeverity)
        else _parse_severity_cached(str(value))
    )


def _coerce_operation(
    value: CreateSaveSyncOperation | str | None,
) -> CreateSaveSyncOperation:
    if value is None:
        return CreateSaveSyncOperation.NONE
    return (
        value
        if isinstance(value, CreateSaveSyncOperation)
        else _parse_operation_cached(str(value))
    )


def _required_text(value: Any, field_name: str) -> str:
    normalized = str(value).strip() if value is not None else ""
    if not normalized:
        raise CreateSaveSyncResultError(f"{field_name} must not be empty")
    return normalized


def _optional_text(value: Any) -> str | None:
    if value is None:
        return None
    normalized = str(value).strip()
    return normalized or None


def _optional_id(value: Any) -> str | int | None:
    if value is None:
        return None
    if isinstance(value, bool):
        return str(value).lower()
    if isinstance(value, int):
        return value
    return _optional_text(value)


def _boolean(value: Any, *, default: bool = False) -> bool:
    if value is None:
        return default
    if isinstance(value, bool):
        return value
    if isinstance(value, int) and value in (0, 1):
        return bool(value)
    if isinstance(value, str):
        normalized = value.strip().lower()
        if normalized in {"1", "true", "yes", "on", "enabled"}:
            return True
        if normalized in {"0", "false", "no", "off", "disabled", ""}:
            return False
    raise TypeError(f"unsupported boolean value: {value!r}")


def _truncate(value: str) -> str:
    if len(value) <= MAX_STRING_LENGTH:
        return value
    omitted = len(value) - MAX_STRING_LENGTH
    return f"{value[:MAX_STRING_LENGTH]}…<truncated:{omitted}>"


def _exception_dict(error: BaseException) -> dict[str, str]:
    return {
        "type": type(error).__name__,
        "message": _truncate(str(error)),
    }


def _freeze_json(
    value: Any,
    *,
    depth: int = 0,
    seen: set[int] | None = None,
) -> Any:
    """Bound and deeply freeze arbitrary values into a JSON-safe form."""

    if depth > MAX_JSON_DEPTH:
        return "<max-depth-reached>"

    if value is None or isinstance(value, (bool, int, float)):
        return value
    if isinstance(value, str):
        return _truncate(value)
    if isinstance(value, Enum):
        return _freeze_json(value.value, depth=depth + 1, seen=seen)
    if isinstance(value, Decimal):
        return str(value)
    if isinstance(value, UUID):
        return str(value)
    if isinstance(value, Path):
        return str(value)
    if isinstance(value, datetime):
        return _isoformat(value)
    if isinstance(value, date):
        return value.isoformat()
    if isinstance(value, time):
        return value.isoformat()
    if isinstance(value, bytes):
        return f"<bytes:{len(value)}>"
    if isinstance(value, BaseException):
        return MappingProxyType(_exception_dict(value))

    seen = seen or set()
    object_id = id(value)
    if object_id in seen:
        return "<recursive-reference>"

    if isinstance(value, Mapping):
        seen.add(object_id)
        try:
            output: dict[str, Any] = {}
            for key, item in islice(value.items(), MAX_MAPPING_ITEMS):
                output[_truncate(str(key))] = _freeze_json(
                    item,
                    depth=depth + 1,
                    seen=seen,
                )
            try:
                omitted = max(0, len(value) - MAX_MAPPING_ITEMS)
            except Exception:
                omitted = 0
            if omitted:
                output["_truncated_items"] = omitted
            return MappingProxyType(output)
        finally:
            seen.discard(object_id)

    if is_dataclass(value):
        seen.add(object_id)
        try:
            return MappingProxyType(
                {
                    data_field.name: _freeze_json(
                        getattr(value, data_field.name),
                        depth=depth + 1,
                        seen=seen,
                    )
                    for data_field in fields(value)
                }
            )
        finally:
            seen.discard(object_id)

    to_dict = getattr(value, "to_dict", None)
    if callable(to_dict):
        seen.add(object_id)
        try:
            try:
                converted = to_dict()
            except Exception as error:  # defensive serialization boundary
                converted = {
                    "_type": type(value).__name__,
                    "_serialization_error": _exception_dict(error),
                }
            return _freeze_json(converted, depth=depth + 1, seen=seen)
        finally:
            seen.discard(object_id)

    if isinstance(value, (list, tuple, set, frozenset)):
        seen.add(object_id)
        try:
            output = [
                _freeze_json(item, depth=depth + 1, seen=seen)
                for item in islice(value, MAX_SEQUENCE_ITEMS)
            ]
            try:
                omitted = max(0, len(value) - MAX_SEQUENCE_ITEMS)
            except Exception:
                omitted = 0
            if omitted:
                output.append(f"<truncated-items:{omitted}>")
            return tuple(output)
        finally:
            seen.discard(object_id)

    try:
        return _truncate(str(value))
    except Exception as error:  # last-resort serialization
        return MappingProxyType(
            {
                "_type": type(value).__name__,
                "_serialization_error": _exception_dict(error),
            }
        )


def _thaw_json(value: Any) -> Any:
    if isinstance(value, Mapping):
        return {str(key): _thaw_json(item) for key, item in value.items()}
    if isinstance(value, tuple):
        return [_thaw_json(item) for item in value]
    if isinstance(value, Enum):
        return value.value
    return value


def _freeze_mapping(value: Mapping[str, Any] | None) -> Mapping[str, Any]:
    if value is None:
        return MappingProxyType({})
    if not isinstance(value, Mapping):
        raise TypeError(f"expected mapping, got {type(value).__name__}")
    normalized = _freeze_json(value)
    if not isinstance(normalized, Mapping):
        raise TypeError("mapping normalization failed")
    return normalized


def _duration_ms(started_at: datetime | None, finished_at: datetime | None) -> int | None:
    if started_at is None or finished_at is None:
        return None
    return max(0, int((finished_at - started_at).total_seconds() * 1000))


@dataclass(frozen=True, slots=True)
class CreateSaveSyncIssue:
    code: str
    message: str
    severity: CreateSaveSyncIssueSeverity = CreateSaveSyncIssueSeverity.ERROR
    phase: CreateSaveSyncPhase = CreateSaveSyncPhase.REQUEST
    retryable: bool = False
    details: Mapping[str, Any] = field(default_factory=dict)
    created_at: datetime = field(default_factory=_utc_now)

    def __post_init__(self) -> None:
        object.__setattr__(self, "code", _required_text(self.code, "issue.code"))
        object.__setattr__(self, "message", _required_text(self.message, "issue.message"))
        object.__setattr__(self, "severity", _coerce_severity(self.severity))
        object.__setattr__(self, "phase", _coerce_phase(self.phase))
        object.__setattr__(self, "retryable", _boolean(self.retryable))
        object.__setattr__(self, "details", _freeze_mapping(self.details))
        object.__setattr__(
            self,
            "created_at",
            _coerce_datetime(self.created_at, default=_utc_now()),
        )

    @property
    def blocking(self) -> bool:
        return self.severity in {
            CreateSaveSyncIssueSeverity.ERROR,
            CreateSaveSyncIssueSeverity.FATAL,
        }

    def to_dict(self) -> dict[str, Any]:
        return {
            "code": self.code,
            "message": self.message,
            "severity": self.severity.value,
            "phase": self.phase.value,
            "retryable": self.retryable,
            "blocking": self.blocking,
            "details": _thaw_json(self.details),
            "created_at": _isoformat(self.created_at),
        }

    @classmethod
    def from_mapping(cls, value: Mapping[str, Any]) -> "CreateSaveSyncIssue":
        if not isinstance(value, Mapping):
            raise TypeError("issue must be a mapping")
        return cls(
            code=value.get("code") or value.get("error_code") or "unknown_issue",
            message=value.get("message") or value.get("error") or "Unknown issue",
            severity=value.get("severity", CreateSaveSyncIssueSeverity.ERROR),
            phase=value.get("phase", CreateSaveSyncPhase.REQUEST),
            retryable=value.get("retryable", False),
            details=value.get("details") or value.get("context") or {},
            created_at=value.get("created_at") or _utc_now(),
        )


def _normalize_issues(
    values: (
        Iterable[CreateSaveSyncIssue | Mapping[str, Any]]
        | Mapping[str, Any]
        | str
        | None
    ),
) -> tuple[CreateSaveSyncIssue, ...]:
    if values is None:
        return ()
    if isinstance(values, CreateSaveSyncIssue):
        return (values,)
    if isinstance(values, Mapping):
        values = (values,)
    elif isinstance(values, str):
        values = (
            {
                "code": "message",
                "message": values,
                "severity": "error",
            },
        )

    output: list[CreateSaveSyncIssue] = []
    for index, value in enumerate(values):
        if index >= MAX_ISSUES:
            output.append(
                CreateSaveSyncIssue(
                    code="issues_truncated",
                    message=f"Issue list exceeded {MAX_ISSUES} entries.",
                    severity=CreateSaveSyncIssueSeverity.WARNING,
                    phase=CreateSaveSyncPhase.COMPLETED,
                    details={"max_issues": MAX_ISSUES},
                )
            )
            break
        if isinstance(value, CreateSaveSyncIssue):
            output.append(value)
        elif isinstance(value, Mapping):
            output.append(CreateSaveSyncIssue.from_mapping(value))
        else:
            output.append(
                CreateSaveSyncIssue(
                    code="invalid_issue_value",
                    message="An issue entry could not be normalized.",
                    severity=CreateSaveSyncIssueSeverity.WARNING,
                    phase=CreateSaveSyncPhase.COMPLETED,
                    details={"type": type(value).__name__, "value": value},
                )
            )
    return tuple(output)


@dataclass(frozen=True, slots=True)
class CreateSaveSyncPhaseResult:
    phase: CreateSaveSyncPhase
    state: CreateSaveSyncPhaseState = CreateSaveSyncPhaseState.PENDING
    started_at: datetime | None = None
    finished_at: datetime | None = None
    details: Mapping[str, Any] = field(default_factory=dict)
    issues: tuple[CreateSaveSyncIssue, ...] = field(default_factory=tuple)

    def __post_init__(self) -> None:
        phase = _coerce_phase(self.phase)
        state = _coerce_phase_state(self.state)
        started_at = _coerce_datetime(self.started_at)
        finished_at = _coerce_datetime(self.finished_at)

        if finished_at is not None and started_at is None:
            started_at = finished_at
        if started_at is not None and finished_at is not None and finished_at < started_at:
            raise CreateSaveSyncResultError(
                f"{phase.value}: finished_at must not be before started_at"
            )
        if state == CreateSaveSyncPhaseState.RUNNING and finished_at is not None:
            raise CreateSaveSyncResultError(
                f"{phase.value}: running phase must not have finished_at"
            )
        if state in {
            CreateSaveSyncPhaseState.SUCCEEDED,
            CreateSaveSyncPhaseState.SKIPPED,
            CreateSaveSyncPhaseState.FAILED,
        } and finished_at is None:
            finished_at = _utc_now()
            started_at = started_at or finished_at

        issues = _normalize_issues(self.issues)
        if state == CreateSaveSyncPhaseState.FAILED and not any(
            issue.blocking for issue in issues
        ):
            raise CreateSaveSyncResultError(
                f"{phase.value}: failed phase requires a blocking issue"
            )

        object.__setattr__(self, "phase", phase)
        object.__setattr__(self, "state", state)
        object.__setattr__(self, "started_at", started_at)
        object.__setattr__(self, "finished_at", finished_at)
        object.__setattr__(self, "details", _freeze_mapping(self.details))
        object.__setattr__(self, "issues", issues)

    @property
    def duration_ms(self) -> int | None:
        return _duration_ms(self.started_at, self.finished_at)

    @property
    def successful(self) -> bool:
        return self.state in {
            CreateSaveSyncPhaseState.SUCCEEDED,
            CreateSaveSyncPhaseState.SKIPPED,
        }

    def to_dict(self) -> dict[str, Any]:
        return {
            "phase": self.phase.value,
            "state": self.state.value,
            "successful": self.successful,
            "started_at": _isoformat(self.started_at),
            "finished_at": _isoformat(self.finished_at),
            "duration_ms": self.duration_ms,
            "details": _thaw_json(self.details),
            "issues": [issue.to_dict() for issue in self.issues],
        }

    @classmethod
    def from_mapping(
        cls,
        value: Mapping[str, Any],
    ) -> "CreateSaveSyncPhaseResult":
        if not isinstance(value, Mapping):
            raise TypeError("phase result must be a mapping")
        return cls(
            phase=value.get("phase", CreateSaveSyncPhase.REQUEST),
            state=value.get("state", CreateSaveSyncPhaseState.PENDING),
            started_at=value.get("started_at"),
            finished_at=value.get("finished_at"),
            details=value.get("details") or {},
            issues=value.get("issues") or (),
        )


def _normalize_phases(
    values: (
        Iterable[CreateSaveSyncPhaseResult | Mapping[str, Any]]
        | Mapping[str, Any]
        | None
    ),
) -> tuple[CreateSaveSyncPhaseResult, ...]:
    if values is None:
        return ()
    if isinstance(values, CreateSaveSyncPhaseResult):
        return (values,)
    if isinstance(values, Mapping):
        values = (values,)

    by_phase: dict[CreateSaveSyncPhase, CreateSaveSyncPhaseResult] = {}
    for index, value in enumerate(values):
        if index >= MAX_PHASES:
            break
        if isinstance(value, CreateSaveSyncPhaseResult):
            normalized = value
        elif isinstance(value, Mapping):
            normalized = CreateSaveSyncPhaseResult.from_mapping(value)
        else:
            raise TypeError(
                f"invalid phase result type: {type(value).__name__}"
            )
        by_phase[normalized.phase] = normalized

    return tuple(
        sorted(
            by_phase.values(),
            key=lambda item: _PHASE_ORDER.get(item.phase, MAX_PHASES),
        )
    )


@dataclass(frozen=True, slots=True)
class CreateSaveSyncResult:
    """Complete observable outcome for exactly one saved VPLIB package."""

    status: CreateSaveSyncStatus = CreateSaveSyncStatus.PENDING

    vplib_uid: str | None = None
    family_id: str | None = None
    package_id: str | None = None
    source_path: str | None = None
    target_dir: str | None = None
    revision_hash: str | None = None

    item_id: str | int | None = None
    current_revision_id: str | int | None = None
    scan_run_id: str | int | None = None

    source_saved: bool = False
    package_scanned: bool = False
    package_valid: bool = False
    db_synced: bool = False
    published_verified: bool = False
    needs_sync: bool = False
    retryable: bool = False

    sync_operation: CreateSaveSyncOperation = CreateSaveSyncOperation.NONE
    revision_created: bool = False

    published_item: Mapping[str, Any] = field(default_factory=dict)
    phases: tuple[CreateSaveSyncPhaseResult, ...] = field(default_factory=tuple)
    issues: tuple[CreateSaveSyncIssue, ...] = field(default_factory=tuple)
    metadata: Mapping[str, Any] = field(default_factory=dict)

    operation_id: str = field(default_factory=lambda: str(uuid4()))
    correlation_id: str | None = None
    started_at: datetime = field(default_factory=_utc_now)
    finished_at: datetime | None = None

    schema_version: str = SCHEMA_VERSION
    component: str = COMPONENT
    component_version: str = COMPONENT_VERSION

    def __post_init__(self) -> None:
        status = _coerce_status(self.status)
        operation = _coerce_operation(self.sync_operation)
        started_at = _coerce_datetime(self.started_at, default=_utc_now())
        finished_at = _coerce_datetime(self.finished_at)

        if started_at is None:
            started_at = _utc_now()
        if finished_at is not None and finished_at < started_at:
            raise CreateSaveSyncResultError(
                "finished_at must not be before started_at"
            )
        if status in _TERMINAL_STATUSES and finished_at is None:
            finished_at = _utc_now()
        if status not in _TERMINAL_STATUSES and finished_at is not None:
            raise CreateSaveSyncResultError(
                f"non-terminal status {status.value} must not have finished_at"
            )

        normalized = {
            "vplib_uid": _optional_text(self.vplib_uid),
            "family_id": _optional_text(self.family_id),
            "package_id": _optional_text(self.package_id),
            "source_path": _optional_text(self.source_path),
            "target_dir": _optional_text(self.target_dir),
            "revision_hash": _optional_text(self.revision_hash),
            "item_id": _optional_id(self.item_id),
            "current_revision_id": _optional_id(self.current_revision_id),
            "scan_run_id": _optional_id(self.scan_run_id),
            "source_saved": _boolean(self.source_saved),
            "package_scanned": _boolean(self.package_scanned),
            "package_valid": _boolean(self.package_valid),
            "db_synced": _boolean(self.db_synced),
            "published_verified": _boolean(self.published_verified),
            "needs_sync": _boolean(self.needs_sync),
            "retryable": _boolean(self.retryable),
            "revision_created": _boolean(self.revision_created),
            "published_item": _freeze_mapping(self.published_item),
            "phases": _normalize_phases(self.phases),
            "issues": _normalize_issues(self.issues),
            "metadata": _freeze_mapping(self.metadata),
            "operation_id": _required_text(
                self.operation_id or str(uuid4()),
                "operation_id",
            ),
            "correlation_id": _optional_text(self.correlation_id),
            "schema_version": _required_text(self.schema_version, "schema_version"),
            "component": _required_text(self.component, "component"),
            "component_version": _required_text(
                self.component_version,
                "component_version",
            ),
        }
        normalized["correlation_id"] = (
            normalized["correlation_id"] or normalized["operation_id"]
        )

        self._validate_invariants(status=status, operation=operation, **normalized)

        object.__setattr__(self, "status", status)
        object.__setattr__(self, "sync_operation", operation)
        object.__setattr__(self, "started_at", started_at)
        object.__setattr__(self, "finished_at", finished_at)
        for name, value in normalized.items():
            object.__setattr__(self, name, value)

    @staticmethod
    def _validate_invariants(
        *,
        status: CreateSaveSyncStatus,
        operation: CreateSaveSyncOperation,
        vplib_uid: str | None,
        family_id: str | None,
        package_id: str | None,
        source_path: str | None,
        target_dir: str | None,
        revision_hash: str | None,
        item_id: str | int | None,
        current_revision_id: str | int | None,
        scan_run_id: str | int | None,
        source_saved: bool,
        package_scanned: bool,
        package_valid: bool,
        db_synced: bool,
        published_verified: bool,
        needs_sync: bool,
        retryable: bool,
        revision_created: bool,
        published_item: Mapping[str, Any],
        phases: tuple[CreateSaveSyncPhaseResult, ...],
        issues: tuple[CreateSaveSyncIssue, ...],
        metadata: Mapping[str, Any],
        operation_id: str,
        correlation_id: str,
        schema_version: str,
        component: str,
        component_version: str,
    ) -> None:
        del (
            family_id,
            package_id,
            item_id,
            current_revision_id,
            scan_run_id,
            retryable,
            phases,
            issues,
            metadata,
            operation_id,
            correlation_id,
            schema_version,
            component,
            component_version,
        )

        if source_saved and not all((vplib_uid, source_path, target_dir)):
            raise CreateSaveSyncResultError(
                "source_saved requires vplib_uid, source_path, and target_dir"
            )
        if package_scanned and not source_saved:
            raise CreateSaveSyncResultError(
                "package_scanned requires source_saved"
            )
        if package_scanned and not revision_hash:
            raise CreateSaveSyncResultError(
                "package_scanned requires revision_hash"
            )
        if package_valid and not package_scanned:
            raise CreateSaveSyncResultError(
                "package_valid requires package_scanned"
            )
        if db_synced and not package_valid:
            raise CreateSaveSyncResultError(
                "db_synced requires package_valid"
            )
        if published_verified and not db_synced:
            raise CreateSaveSyncResultError(
                "published_verified requires db_synced"
            )
        if published_verified and not published_item:
            raise CreateSaveSyncResultError(
                "published_verified requires published_item"
            )
        if published_verified and needs_sync:
            raise CreateSaveSyncResultError(
                "published_verified and needs_sync cannot both be true"
            )
        if db_synced and needs_sync:
            raise CreateSaveSyncResultError(
                "db_synced and needs_sync cannot both be true"
            )
        if revision_created and not db_synced:
            raise CreateSaveSyncResultError(
                "revision_created requires db_synced"
            )
        if operation == CreateSaveSyncOperation.UNCHANGED and revision_created:
            raise CreateSaveSyncResultError(
                "unchanged sync must not create a revision"
            )
        if operation in {
            CreateSaveSyncOperation.INSERTED,
            CreateSaveSyncOperation.UPDATED,
            CreateSaveSyncOperation.UNCHANGED,
        } and not db_synced:
            raise CreateSaveSyncResultError(
                f"{operation.value} requires db_synced"
            )
        if status == CreateSaveSyncStatus.SOURCE_SAVED and not (
            source_saved and needs_sync
        ):
            raise CreateSaveSyncResultError(
                "source_saved status requires source_saved=true and needs_sync=true"
            )
        if status in _SUCCESS_STATUSES:
            if not all(
                (
                    source_saved,
                    package_scanned,
                    package_valid,
                    db_synced,
                    published_verified,
                )
            ):
                raise CreateSaveSyncResultError(
                    f"{status.value} requires all workflow phases to succeed"
                )
            if status == CreateSaveSyncStatus.PUBLISHED and operation not in {
                CreateSaveSyncOperation.INSERTED,
                CreateSaveSyncOperation.UPDATED,
            }:
                raise CreateSaveSyncResultError(
                    "published requires inserted or updated operation"
                )
            if status == CreateSaveSyncStatus.UNCHANGED and (
                operation != CreateSaveSyncOperation.UNCHANGED
            ):
                raise CreateSaveSyncResultError(
                    "unchanged requires unchanged operation"
                )

    @property
    def ok(self) -> bool:
        return self.status in _SUCCESS_STATUSES and self.published_verified

    @property
    def success(self) -> bool:
        return self.ok

    @property
    def terminal(self) -> bool:
        return self.status in _TERMINAL_STATUSES

    @property
    def duration_ms(self) -> int | None:
        return _duration_ms(self.started_at, self.finished_at)

    @property
    def blocking_issues(self) -> tuple[CreateSaveSyncIssue, ...]:
        return tuple(issue for issue in self.issues if issue.blocking)

    @property
    def warnings(self) -> tuple[CreateSaveSyncIssue, ...]:
        return tuple(
            issue
            for issue in self.issues
            if issue.severity == CreateSaveSyncIssueSeverity.WARNING
        )

    @property
    def phase_map(self) -> Mapping[str, CreateSaveSyncPhaseResult]:
        return MappingProxyType(
            {phase.phase.value: phase for phase in self.phases}
        )

    def get_phase(
        self,
        phase: CreateSaveSyncPhase | str,
    ) -> CreateSaveSyncPhaseResult | None:
        normalized = _coerce_phase(phase)
        return next(
            (item for item in self.phases if item.phase == normalized),
            None,
        )

    def with_updates(self, **changes: Any) -> "CreateSaveSyncResult":
        return replace(self, **changes)

    def with_issue(
        self,
        issue: CreateSaveSyncIssue | Mapping[str, Any],
    ) -> "CreateSaveSyncResult":
        normalized = (
            issue
            if isinstance(issue, CreateSaveSyncIssue)
            else CreateSaveSyncIssue.from_mapping(issue)
        )
        return replace(
            self,
            issues=(*self.issues, normalized),
            retryable=self.retryable or normalized.retryable,
        )

    def with_phase(
        self,
        phase_result: CreateSaveSyncPhaseResult | Mapping[str, Any],
    ) -> "CreateSaveSyncResult":
        normalized = (
            phase_result
            if isinstance(phase_result, CreateSaveSyncPhaseResult)
            else CreateSaveSyncPhaseResult.from_mapping(phase_result)
        )
        phases = {
            current.phase: current
            for current in self.phases
        }
        phases[normalized.phase] = normalized

        issues = list(self.issues)
        known = {
            (item.code, item.message, item.phase, item.created_at)
            for item in issues
        }
        for issue in normalized.issues:
            key = (issue.code, issue.message, issue.phase, issue.created_at)
            if key not in known:
                issues.append(issue)
                known.add(key)

        return replace(
            self,
            phases=tuple(phases.values()),
            issues=tuple(issues),
            retryable=self.retryable
            or any(issue.retryable for issue in normalized.issues),
        )

    def to_summary_dict(self) -> dict[str, Any]:
        return {
            "schema_version": self.schema_version,
            "component": self.component,
            "component_version": self.component_version,
            "ok": self.ok,
            "success": self.success,
            "status": self.status.value,
            "terminal": self.terminal,
            "operation_id": self.operation_id,
            "correlation_id": self.correlation_id,
            "vplib_uid": self.vplib_uid,
            "family_id": self.family_id,
            "package_id": self.package_id,
            "source_path": self.source_path,
            "revision_hash": self.revision_hash,
            "item_id": self.item_id,
            "current_revision_id": self.current_revision_id,
            "scan_run_id": self.scan_run_id,
            "source_saved": self.source_saved,
            "package_scanned": self.package_scanned,
            "package_valid": self.package_valid,
            "db_synced": self.db_synced,
            "published_verified": self.published_verified,
            "needs_sync": self.needs_sync,
            "retryable": self.retryable,
            "sync_operation": self.sync_operation.value,
            "revision_created": self.revision_created,
            "issue_count": len(self.issues),
            "blocking_issue_count": len(self.blocking_issues),
            "warning_count": len(self.warnings),
            "started_at": _isoformat(self.started_at),
            "finished_at": _isoformat(self.finished_at),
            "duration_ms": self.duration_ms,
        }

    def to_dict(self) -> dict[str, Any]:
        payload = self.to_summary_dict()
        payload.update(
            {
                "target_dir": self.target_dir,
                "published_item": _thaw_json(self.published_item),
                "phases": [phase.to_dict() for phase in self.phases],
                "issues": [issue.to_dict() for issue in self.issues],
                "metadata": _thaw_json(self.metadata),
            }
        )
        return payload

    @classmethod
    def start(
        cls,
        *,
        vplib_uid: str | None = None,
        family_id: str | None = None,
        package_id: str | None = None,
        operation_id: str | None = None,
        correlation_id: str | None = None,
        metadata: Mapping[str, Any] | None = None,
    ) -> "CreateSaveSyncResult":
        return cls(
            status=CreateSaveSyncStatus.RUNNING,
            vplib_uid=vplib_uid,
            family_id=family_id,
            package_id=package_id,
            operation_id=operation_id or str(uuid4()),
            correlation_id=correlation_id,
            metadata=metadata or {},
        )

    @classmethod
    def from_mapping(
        cls,
        value: Mapping[str, Any],
    ) -> "CreateSaveSyncResult":
        if not isinstance(value, Mapping):
            raise TypeError("result must be a mapping")

        source = value
        for key in ("payload", "result", "data"):
            nested = source.get(key)
            if isinstance(nested, Mapping):
                source = nested
                break

        return cls(
            status=source.get("status", CreateSaveSyncStatus.PENDING),
            vplib_uid=source.get("vplib_uid") or source.get("vplibUid"),
            family_id=source.get("family_id") or source.get("familyId"),
            package_id=source.get("package_id") or source.get("packageId"),
            source_path=source.get("source_path") or source.get("sourcePath"),
            target_dir=source.get("target_dir") or source.get("targetDir"),
            revision_hash=source.get("revision_hash") or source.get("revisionHash"),
            item_id=source.get("item_id") or source.get("itemId"),
            current_revision_id=(
                source.get("current_revision_id")
                or source.get("currentRevisionId")
            ),
            scan_run_id=source.get("scan_run_id") or source.get("scanRunId"),
            source_saved=source.get("source_saved", False),
            package_scanned=source.get("package_scanned", False),
            package_valid=source.get("package_valid", False),
            db_synced=source.get("db_synced", False),
            published_verified=source.get("published_verified", False),
            needs_sync=source.get("needs_sync", False),
            retryable=source.get("retryable", False),
            sync_operation=source.get(
                "sync_operation",
                CreateSaveSyncOperation.NONE,
            ),
            revision_created=source.get("revision_created", False),
            published_item=source.get("published_item") or {},
            phases=source.get("phases") or (),
            issues=source.get("issues") or source.get("errors") or (),
            metadata=source.get("metadata") or {},
            operation_id=(
                source.get("operation_id")
                or source.get("operationId")
                or str(uuid4())
            ),
            correlation_id=(
                source.get("correlation_id")
                or source.get("correlationId")
            ),
            started_at=source.get("started_at") or _utc_now(),
            finished_at=source.get("finished_at"),
            schema_version=source.get("schema_version", SCHEMA_VERSION),
            component=source.get("component", COMPONENT),
            component_version=source.get(
                "component_version",
                COMPONENT_VERSION,
            ),
        )


def create_save_sync_result_from_mapping(
    value: Mapping[str, Any] | CreateSaveSyncResult,
) -> CreateSaveSyncResult:
    if isinstance(value, CreateSaveSyncResult):
        return value
    return CreateSaveSyncResult.from_mapping(value)


def get_create_save_sync_result_health() -> dict[str, Any]:
    """Return a safe health and parser-cache snapshot."""

    errors: list[dict[str, str]] = []
    checks = {
        "construct": False,
        "serialize": False,
        "roundtrip": False,
    }

    try:
        probe = CreateSaveSyncResult.start(
            metadata={"health_probe": True},
        )
        checks["construct"] = probe.status == CreateSaveSyncStatus.RUNNING
        serialized = probe.to_dict()
        checks["serialize"] = isinstance(serialized, dict)
        roundtrip = CreateSaveSyncResult.from_mapping(serialized)
        checks["roundtrip"] = (
            roundtrip.operation_id == probe.operation_id
            and roundtrip.status == probe.status
        )
    except Exception as error:  # health must never raise
        errors.append(_exception_dict(error))

    cache: dict[str, Any] = {}
    for name, function in (
        ("datetime", _parse_datetime_cached),
        ("status", _parse_status_cached),
        ("phase", _parse_phase_cached),
        ("phase_state", _parse_phase_state_cached),
        ("severity", _parse_severity_cached),
        ("operation", _parse_operation_cached),
    ):
        try:
            info = function.cache_info()
            cache[name] = {
                "hits": info.hits,
                "misses": info.misses,
                "maxsize": info.maxsize,
                "currsize": info.currsize,
            }
        except Exception as error:  # diagnostics only
            cache[name] = {"error": _exception_dict(error)}

    ok = all(checks.values()) and not errors
    return {
        "ok": ok,
        "healthy": ok,
        "status": "ok" if ok else "degraded",
        "schema_version": SCHEMA_VERSION,
        "component": COMPONENT,
        "component_version": COMPONENT_VERSION,
        "checks": checks,
        "cache": cache,
        "errors": errors,
    }


def assert_create_save_sync_result_ready() -> None:
    health = get_create_save_sync_result_health()
    if not health.get("ok"):
        raise CreateSaveSyncResultError(
            f"{COMPONENT} is not ready: {health.get('errors', [])}"
        )


def clear_create_save_sync_result_caches() -> dict[str, Any]:
    """Clear all bounded parser caches without propagating cleanup errors."""

    cleared: list[str] = []
    errors: list[dict[str, str]] = []

    for name, function in (
        ("datetime", _parse_datetime_cached),
        ("status", _parse_status_cached),
        ("phase", _parse_phase_cached),
        ("phase_state", _parse_phase_state_cached),
        ("severity", _parse_severity_cached),
        ("operation", _parse_operation_cached),
    ):
        try:
            function.cache_clear()
            cleared.append(name)
        except Exception as error:  # cache cleanup must never raise
            errors.append({"cache": name, **_exception_dict(error)})

    return {
        "ok": not errors,
        "status": "cleared" if not errors else "partial",
        "component": COMPONENT,
        "cleared": cleared,
        "errors": errors,
    }


health = get_create_save_sync_result_health
get_health = get_create_save_sync_result_health
clear_caches = clear_create_save_sync_result_caches


__all__ = [
    "SCHEMA_VERSION",
    "COMPONENT",
    "COMPONENT_VERSION",
    "CreateSaveSyncResultError",
    "CreateSaveSyncStatus",
    "CreateSaveSyncPhase",
    "CreateSaveSyncPhaseState",
    "CreateSaveSyncIssueSeverity",
    "CreateSaveSyncOperation",
    "CreateSaveSyncIssue",
    "CreateSaveSyncPhaseResult",
    "CreateSaveSyncResult",
    "create_save_sync_result_from_mapping",
    "get_create_save_sync_result_health",
    "assert_create_save_sync_result_ready",
    "clear_create_save_sync_result_caches",
    "health",
    "get_health",
    "clear_caches",
]
