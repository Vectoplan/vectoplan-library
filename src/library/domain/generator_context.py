# src/library/domain/generator_context.py
from __future__ import annotations

"""
Domain models and safe helpers for the VPLIB generator context.

This module is intentionally dependency-light:
- no Flask imports
- no SQLAlchemy imports
- no repository imports
- no service imports
- no file-system writes
- no HTTP calls

It defines stable, JSON-serializable structures that can be filled by
`library_generator_context_service.py` and consumed by:
- create route services
- create/draft workflow services
- diagnostics/selftest services
- frontend context builders
- tests

The module is designed to be forward-compatible and robust against partially
available services. Unknown, missing, or malformed payloads are normalized into
safe defaults instead of crashing whenever possible.
"""

import copy
import hashlib
import json
import threading
import time
import uuid
from collections.abc import Mapping as MappingABC
from collections.abc import Sequence as SequenceABC
from dataclasses import dataclass, field, fields, is_dataclass
from datetime import datetime, timezone
from enum import Enum
from typing import Any, Callable, Dict, Iterable, List, Mapping, Optional, Tuple


GENERATOR_CONTEXT_SCHEMA_VERSION = "generator_context.v1"
GENERATOR_CONTEXT_COMPONENT = "library.generator_context"
DEFAULT_USER_ID = 1
DEFAULT_INVENTORY_KEY = "default"
DEFAULT_OWNER_SCOPE_SYSTEM = "system"
DEFAULT_CONTEXT_TTL_SECONDS = 60
DEFAULT_CONTEXT_CACHE_MAX_ENTRIES = 128

DEFAULT_CREATE_API_ROUTES: Dict[str, str] = {
    "create_health": "/api/v1/vplib/create/health",
    "create_options": "/api/v1/vplib/create/options",
    "create_context": "/api/v1/vplib/create/context",
    "create_draft": "/api/v1/vplib/create/draft",
    "create_validate": "/api/v1/vplib/create/validate",
    "create_package_plan": "/api/v1/vplib/create/package-plan",
    "create_download": "/api/v1/vplib/create/download",
    "create_save": "/api/v1/vplib/create/save",
}

DEFAULT_DEFINITION_API_ROUTES: Dict[str, str] = {
    "definitions_health": "/api/v1/vplib/definitions/health",
    "definitions_options": "/api/v1/vplib/definitions/options",
    "definitions_payload": "/api/v1/vplib/definitions/payload",
    "definitions_current": "/api/v1/vplib/definitions/current",
    "resolve_family_profile": "/api/v1/vplib/definitions/resolve-family-profile",
    "resolve_variant_profile": "/api/v1/vplib/definitions/resolve-variant-profile",
    "empty_variant_values": "/api/v1/vplib/definitions/empty-variant-values",
    "validate_variant": "/api/v1/vplib/definitions/validate-variant",
}

DEFAULT_TAXONOMY_API_ROUTES: Dict[str, str] = {
    "taxonomy_health": "/api/v1/vplib/taxonomy/health",
    "taxonomy_create_options": "/api/v1/vplib/taxonomy/create-options",
    "taxonomy_resolved": "/api/v1/vplib/taxonomy/resolved",
    "taxonomy_tree": "/api/v1/vplib/taxonomy/tree",
    "taxonomy_lookup": "/api/v1/vplib/taxonomy/lookup",
}

DEFAULT_FILE_API_ROUTES: Dict[str, str] = {
    "files_health": "/api/v1/vplib/files/health",
    "files_upload": "/api/v1/vplib/files",
    "files_upload_constraints": "/api/v1/vplib/files/upload-constraints",
    "files_context": "/api/v1/vplib/files/context",
    "files_links": "/api/v1/vplib/files/links",
}

DEFAULT_DRAFT_API_ROUTES: Dict[str, str] = {
    "drafts_health": "/api/v1/vplib/library/drafts/health",
    "drafts_list": "/api/v1/vplib/library/drafts",
    "drafts_create": "/api/v1/vplib/library/drafts",
    "drafts_validate": "/api/v1/vplib/library/drafts/{draft_ref}/validate",
    "drafts_publish_prepare": "/api/v1/vplib/library/drafts/{draft_ref}/publish/prepare",
    "drafts_publish": "/api/v1/vplib/library/drafts/{draft_ref}/publish",
}

DEFAULT_GENERATOR_ROUTES: Dict[str, str] = {
    **DEFAULT_CREATE_API_ROUTES,
    **DEFAULT_DEFINITION_API_ROUTES,
    **DEFAULT_TAXONOMY_API_ROUTES,
    **DEFAULT_FILE_API_ROUTES,
    **DEFAULT_DRAFT_API_ROUTES,
}


class _StringEnum(str, Enum):
    """Small Python-version-safe string enum base."""

    def __str__(self) -> str:
        return self.value


class GeneratorContextStatus(_StringEnum):
    UNKNOWN = "unknown"
    UNAVAILABLE = "unavailable"
    PARTIAL = "partial"
    READY = "ready"
    INVALID = "invalid"
    ERROR = "error"


class GeneratorContextSource(_StringEnum):
    UNKNOWN = "unknown"
    DEFAULT = "default"
    PAYLOAD = "payload"
    REQUEST = "request"
    REGISTRY = "registry"
    DATABASE = "database"
    SERVICE = "service"
    CACHE = "cache"
    FALLBACK = "fallback"
    MIXED = "mixed"


class GeneratorContextSection(_StringEnum):
    ROOT = "root"
    ROUTES = "routes"
    USER = "user"
    DEFINITIONS = "definitions"
    TAXONOMY = "taxonomy"
    UPLOADS = "uploads"
    FILES = "files"
    DRAFT = "draft"
    PUBLISHED = "published"
    CAPABILITIES = "capabilities"
    DIAGNOSTICS = "diagnostics"
    METADATA = "metadata"


class GeneratorContextIssueSeverity(_StringEnum):
    INFO = "info"
    WARNING = "warning"
    ERROR = "error"
    FATAL = "fatal"


class GeneratorContextAction(_StringEnum):
    CONTEXT = "context"
    OPTIONS = "options"
    DRAFT = "draft"
    VALIDATE = "validate"
    PACKAGE_PLAN = "package-plan"
    DOWNLOAD = "download"
    SAVE = "save"
    PERSIST_DRAFT = "persist-draft"
    PUBLISH_PREPARE = "publish-prepare"
    PUBLISH = "publish"
    SYNC = "sync"


class GeneratorSerializableMixin:
    """Mixin for deterministic JSON-safe serialization."""

    def to_dict(self, include_none: bool = False) -> Dict[str, Any]:
        value = to_json_compatible(self, include_none=include_none)
        if isinstance(value, dict):
            return value
        return {"value": value}

    def copy(self) -> "GeneratorSerializableMixin":
        try:
            return copy.deepcopy(self)
        except Exception:
            return self


def utc_now_iso() -> str:
    """Return a stable UTC ISO timestamp."""
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def new_context_uid(prefix: str = "generator_context") -> str:
    """Return a non-security-sensitive context identifier."""
    safe_prefix = normalize_key(prefix, default="generator_context")
    return f"{safe_prefix}:{uuid.uuid4().hex}"


def normalize_key(value: Any, default: str = "") -> str:
    """Normalize user/API keys into compact lower-case technical keys."""
    if value is None:
        return default
    try:
        text = str(value).strip()
    except Exception:
        return default
    if not text:
        return default
    text = text.replace("\\", "/")
    text = text.replace(" ", "_")
    text = text.replace("-", "_")
    text = text.lower()
    while "__" in text:
        text = text.replace("__", "_")
    return text.strip("_") or default


def normalize_slug(value: Any, default: str = "") -> str:
    """Normalize slugs but preserve slash-separated taxonomy paths."""
    if value is None:
        return default
    try:
        text = str(value).strip()
    except Exception:
        return default
    if not text:
        return default
    text = text.replace("\\", "/")
    text = text.replace(" ", "_")
    text = text.replace("-", "_")
    text = text.lower()
    text = "/".join(part.strip("_") for part in text.split("/") if part.strip("_"))
    return text or default


def normalize_owner_scope(user_id: Any = None, owner_scope: Any = None) -> str:
    """Normalize the owner scope used throughout Library/Generator contexts."""
    explicit_scope = normalize_slug(owner_scope, default="")
    if explicit_scope:
        return explicit_scope

    safe_user_id = safe_int(user_id, default=None)
    if safe_user_id is None:
        return DEFAULT_OWNER_SCOPE_SYSTEM
    return f"user:{safe_user_id}"


def normalize_taxonomy_path(
    domain: Any = None,
    category: Any = None,
    subcategory: Any = None,
    path: Any = None,
) -> str:
    """Build or normalize a canonical taxonomy path."""
    explicit_path = normalize_slug(path, default="")
    if explicit_path:
        return explicit_path

    parts = [
        normalize_slug(domain, default=""),
        normalize_slug(category, default=""),
        normalize_slug(subcategory, default=""),
    ]
    return "/".join(part for part in parts if part)


def safe_str(value: Any, default: str = "") -> str:
    if value is None:
        return default
    try:
        text = str(value)
    except Exception:
        return default
    return text if text != "" else default


def safe_bool(value: Any, default: bool = False) -> bool:
    if value is None:
        return default
    if isinstance(value, bool):
        return value
    if isinstance(value, (int, float)):
        return bool(value)
    try:
        text = str(value).strip().lower()
    except Exception:
        return default

    if text in {"1", "true", "yes", "y", "on", "enabled", "active"}:
        return True
    if text in {"0", "false", "no", "n", "off", "disabled", "inactive"}:
        return False
    return default


def safe_int(value: Any, default: Optional[int] = 0) -> Optional[int]:
    if value is None:
        return default
    if isinstance(value, bool):
        return int(value)
    try:
        return int(value)
    except Exception:
        try:
            return int(float(str(value).strip()))
        except Exception:
            return default


def safe_float(value: Any, default: Optional[float] = 0.0) -> Optional[float]:
    if value is None:
        return default
    if isinstance(value, bool):
        return float(int(value))
    try:
        return float(value)
    except Exception:
        return default


def safe_list(value: Any) -> List[Any]:
    if value is None:
        return []
    if isinstance(value, list):
        return value
    if isinstance(value, tuple):
        return list(value)
    if isinstance(value, set):
        return list(value)
    if isinstance(value, str):
        stripped = value.strip()
        if not stripped:
            return []
        parsed = parse_json_safe(stripped, default=None)
        if isinstance(parsed, list):
            return parsed
        return [stripped]
    if isinstance(value, SequenceABC) and not isinstance(value, (bytes, bytearray, str)):
        try:
            return list(value)
        except Exception:
            return []
    return [value]


def safe_mapping(value: Any) -> Dict[str, Any]:
    if value is None:
        return {}
    if isinstance(value, MappingABC):
        return dict(value)
    if isinstance(value, str):
        parsed = parse_json_safe(value, default={})
        if isinstance(parsed, MappingABC):
            return dict(parsed)
    return {}


def safe_deepcopy(value: Any, default: Any = None) -> Any:
    try:
        return copy.deepcopy(value)
    except Exception:
        return default if default is not None else value


def parse_json_safe(value: Any, default: Any = None) -> Any:
    if value is None:
        return default
    if isinstance(value, (dict, list, tuple, int, float, bool)):
        return value
    try:
        text = str(value).strip()
    except Exception:
        return default
    if not text:
        return default
    try:
        return json.loads(text)
    except Exception:
        return default


def first_present(mapping: Mapping[str, Any], *keys: str, default: Any = None) -> Any:
    if not isinstance(mapping, MappingABC):
        return default
    for key in keys:
        if key in mapping and mapping[key] is not None:
            return mapping[key]
    return default


def enum_value(value: Any, enum_cls: Any, default: Any) -> Any:
    if isinstance(value, enum_cls):
        return value

    if value is None:
        return default

    try:
        text = str(value).strip()
    except Exception:
        return default

    if not text:
        return default

    text_lower = text.lower()
    for item in enum_cls:
        if text_lower == item.value.lower() or text_lower == item.name.lower():
            return item

    return default


def normalize_status(value: Any, default: GeneratorContextStatus = GeneratorContextStatus.UNKNOWN) -> GeneratorContextStatus:
    return enum_value(value, GeneratorContextStatus, default)


def normalize_source(value: Any, default: GeneratorContextSource = GeneratorContextSource.UNKNOWN) -> GeneratorContextSource:
    return enum_value(value, GeneratorContextSource, default)


def normalize_section(value: Any, default: GeneratorContextSection = GeneratorContextSection.ROOT) -> GeneratorContextSection:
    return enum_value(value, GeneratorContextSection, default)


def normalize_severity(
    value: Any,
    default: GeneratorContextIssueSeverity = GeneratorContextIssueSeverity.INFO,
) -> GeneratorContextIssueSeverity:
    return enum_value(value, GeneratorContextIssueSeverity, default)


def normalize_action(value: Any, default: Optional[GeneratorContextAction] = None) -> Optional[GeneratorContextAction]:
    return enum_value(value, GeneratorContextAction, default)


def normalize_extension(value: Any) -> str:
    text = safe_str(value, default="").strip().lower()
    if not text:
        return ""
    if "/" in text or "\\" in text:
        text = text.replace("\\", "/").split("/")[-1]
    if "." in text:
        text = text.split(".")[-1]
    return f".{text.strip('.')}" if text.strip(".") else ""


def normalize_mime_type(value: Any) -> str:
    text = safe_str(value, default="").strip().lower()
    if not text or "/" not in text:
        return ""
    return text


def to_json_compatible(value: Any, include_none: bool = False) -> Any:
    """Convert values into JSON-compatible structures with defensive fallbacks."""
    if value is None:
        return None

    if isinstance(value, Enum):
        return value.value

    if isinstance(value, (str, int, float, bool)):
        return value

    if isinstance(value, datetime):
        try:
            return value.isoformat()
        except Exception:
            return safe_str(value)

    if is_dataclass(value):
        result: Dict[str, Any] = {}
        for item in fields(value):
            try:
                raw = getattr(value, item.name)
            except Exception:
                continue
            if raw is None and not include_none:
                continue
            result[item.name] = to_json_compatible(raw, include_none=include_none)
        return result

    if isinstance(value, MappingABC):
        result = {}
        for key, item in value.items():
            safe_key = safe_str(key, default="")
            if not safe_key:
                continue
            if item is None and not include_none:
                continue
            result[safe_key] = to_json_compatible(item, include_none=include_none)
        return result

    if isinstance(value, (list, tuple, set)):
        return [to_json_compatible(item, include_none=include_none) for item in value]

    if isinstance(value, bytes):
        try:
            return value.decode("utf-8")
        except Exception:
            return repr(value)

    try:
        json.dumps(value)
        return value
    except Exception:
        return safe_str(value)


def stable_json_dumps(value: Any, include_none: bool = False) -> str:
    safe_value = to_json_compatible(value, include_none=include_none)
    try:
        return json.dumps(
            safe_value,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
            default=str,
        )
    except Exception:
        return json.dumps(str(safe_value), ensure_ascii=False)


def stable_hash(value: Any, prefix: str = "sha256") -> str:
    payload = stable_json_dumps(value)
    digest = hashlib.sha256(payload.encode("utf-8")).hexdigest()
    return f"{prefix}:{digest}" if prefix else digest


def normalize_record_map(
    value: Any,
    key_candidates: Iterable[str] = ("key", "id", "uid", "slug", "name"),
) -> Dict[str, Dict[str, Any]]:
    """
    Normalize a list/dict of records into a dict keyed by a stable technical key.

    Accepts:
    - {"a": {...}, "b": {...}}
    - [{"key": "a"}, {"id": "b"}]
    - JSON string of either shape
    """
    raw = parse_json_safe(value, default=value)

    if isinstance(raw, MappingABC):
        result: Dict[str, Dict[str, Any]] = {}
        for map_key, map_value in raw.items():
            safe_key = normalize_key(map_key, default="")
            if not safe_key:
                continue
            if isinstance(map_value, MappingABC):
                record = dict(map_value)
            else:
                record = {"value": map_value}
            record.setdefault("key", safe_key)
            result[safe_key] = record
        return result

    result = {}
    for item in safe_list(raw):
        if not isinstance(item, MappingABC):
            continue
        record = dict(item)
        record_key = ""
        for key_candidate in key_candidates:
            candidate = normalize_key(record.get(key_candidate), default="")
            if candidate:
                record_key = candidate
                break
        if not record_key:
            record_key = normalize_key(record.get("label"), default="")
        if not record_key:
            continue
        record.setdefault("key", record_key)
        result[record_key] = record
    return result


def merge_mappings(*mappings: Any) -> Dict[str, Any]:
    """Shallow merge mappings while ignoring invalid values."""
    result: Dict[str, Any] = {}
    for mapping in mappings:
        if isinstance(mapping, MappingABC):
            result.update(dict(mapping))
    return result


@dataclass
class GeneratorContextIssue(GeneratorSerializableMixin):
    severity: GeneratorContextIssueSeverity = GeneratorContextIssueSeverity.INFO
    code: str = "info"
    message: str = ""
    section: GeneratorContextSection = GeneratorContextSection.ROOT
    field: Optional[str] = None
    path: Optional[str] = None
    source: GeneratorContextSource = GeneratorContextSource.UNKNOWN
    details: Dict[str, Any] = field(default_factory=dict)
    active: bool = True
    created_at: str = field(default_factory=utc_now_iso)

    @classmethod
    def from_mapping(cls, value: Any) -> "GeneratorContextIssue":
        data = safe_mapping(value)
        return cls(
            severity=normalize_severity(data.get("severity"), GeneratorContextIssueSeverity.INFO),
            code=normalize_key(data.get("code"), default="info"),
            message=safe_str(data.get("message"), default=""),
            section=normalize_section(data.get("section"), GeneratorContextSection.ROOT),
            field=safe_str(data.get("field"), default="") or None,
            path=safe_str(data.get("path"), default="") or None,
            source=normalize_source(data.get("source"), GeneratorContextSource.UNKNOWN),
            details=safe_mapping(data.get("details") or data.get("payload") or data.get("meta")),
            active=safe_bool(data.get("active"), default=True),
            created_at=safe_str(data.get("created_at"), default=utc_now_iso()),
        )

    @classmethod
    def info(cls, code: str, message: str, section: Any = GeneratorContextSection.ROOT, **details: Any) -> "GeneratorContextIssue":
        return cls(
            severity=GeneratorContextIssueSeverity.INFO,
            code=normalize_key(code, default="info"),
            message=safe_str(message),
            section=normalize_section(section),
            details=safe_mapping(details),
        )

    @classmethod
    def warning(cls, code: str, message: str, section: Any = GeneratorContextSection.ROOT, **details: Any) -> "GeneratorContextIssue":
        return cls(
            severity=GeneratorContextIssueSeverity.WARNING,
            code=normalize_key(code, default="warning"),
            message=safe_str(message),
            section=normalize_section(section),
            details=safe_mapping(details),
        )

    @classmethod
    def error(cls, code: str, message: str, section: Any = GeneratorContextSection.ROOT, **details: Any) -> "GeneratorContextIssue":
        return cls(
            severity=GeneratorContextIssueSeverity.ERROR,
            code=normalize_key(code, default="error"),
            message=safe_str(message),
            section=normalize_section(section),
            details=safe_mapping(details),
        )

    @classmethod
    def fatal(cls, code: str, message: str, section: Any = GeneratorContextSection.ROOT, **details: Any) -> "GeneratorContextIssue":
        return cls(
            severity=GeneratorContextIssueSeverity.FATAL,
            code=normalize_key(code, default="fatal"),
            message=safe_str(message),
            section=normalize_section(section),
            details=safe_mapping(details),
        )

    @property
    def blocking(self) -> bool:
        return self.active and self.severity in {
            GeneratorContextIssueSeverity.ERROR,
            GeneratorContextIssueSeverity.FATAL,
        }


@dataclass
class GeneratorContextDiagnostics(GeneratorSerializableMixin):
    status: GeneratorContextStatus = GeneratorContextStatus.UNKNOWN
    healthy: bool = False
    issues: List[GeneratorContextIssue] = field(default_factory=list)
    checked_at: str = field(default_factory=utc_now_iso)
    duration_ms: Optional[int] = None
    timings_ms: Dict[str, int] = field(default_factory=dict)
    metadata: Dict[str, Any] = field(default_factory=dict)

    @classmethod
    def from_mapping(cls, value: Any) -> "GeneratorContextDiagnostics":
        data = safe_mapping(value)
        issues = [GeneratorContextIssue.from_mapping(item) for item in safe_list(data.get("issues"))]
        diagnostics = cls(
            status=normalize_status(data.get("status"), GeneratorContextStatus.UNKNOWN),
            healthy=safe_bool(data.get("healthy"), default=False),
            issues=issues,
            checked_at=safe_str(data.get("checked_at"), default=utc_now_iso()),
            duration_ms=safe_int(data.get("duration_ms"), default=None),
            timings_ms={
                safe_str(key): int(safe_int(item, default=0) or 0)
                for key, item in safe_mapping(data.get("timings_ms")).items()
            },
            metadata=safe_mapping(data.get("metadata") or data.get("meta")),
        )
        diagnostics.refresh()
        return diagnostics

    def add_issue(self, issue: Any) -> None:
        try:
            parsed = issue if isinstance(issue, GeneratorContextIssue) else GeneratorContextIssue.from_mapping(issue)
            self.issues.append(parsed)
            self.refresh()
        except Exception:
            self.issues.append(
                GeneratorContextIssue.error(
                    "diagnostics_issue_parse_failed",
                    "Could not parse diagnostics issue.",
                    GeneratorContextSection.DIAGNOSTICS,
                )
            )
            self.refresh()

    def add_info(self, code: str, message: str, section: Any = GeneratorContextSection.ROOT, **details: Any) -> None:
        self.add_issue(GeneratorContextIssue.info(code, message, section, **details))

    def add_warning(self, code: str, message: str, section: Any = GeneratorContextSection.ROOT, **details: Any) -> None:
        self.add_issue(GeneratorContextIssue.warning(code, message, section, **details))

    def add_error(self, code: str, message: str, section: Any = GeneratorContextSection.ROOT, **details: Any) -> None:
        self.add_issue(GeneratorContextIssue.error(code, message, section, **details))

    def add_fatal(self, code: str, message: str, section: Any = GeneratorContextSection.ROOT, **details: Any) -> None:
        self.add_issue(GeneratorContextIssue.fatal(code, message, section, **details))

    def extend(self, issues: Iterable[Any]) -> None:
        for issue in issues:
            self.add_issue(issue)
        self.refresh()

    def merge(self, other: Any) -> None:
        parsed = other if isinstance(other, GeneratorContextDiagnostics) else GeneratorContextDiagnostics.from_mapping(other)
        self.issues.extend(parsed.issues)
        self.timings_ms.update(parsed.timings_ms)
        self.metadata.update(parsed.metadata)
        self.refresh()

    @property
    def issue_count(self) -> int:
        return len([issue for issue in self.issues if issue.active])

    @property
    def warning_count(self) -> int:
        return len(
            [
                issue
                for issue in self.issues
                if issue.active and issue.severity == GeneratorContextIssueSeverity.WARNING
            ]
        )

    @property
    def error_count(self) -> int:
        return len(
            [
                issue
                for issue in self.issues
                if issue.active and issue.severity == GeneratorContextIssueSeverity.ERROR
            ]
        )

    @property
    def fatal_count(self) -> int:
        return len(
            [
                issue
                for issue in self.issues
                if issue.active and issue.severity == GeneratorContextIssueSeverity.FATAL
            ]
        )

    @property
    def blocking_count(self) -> int:
        return len([issue for issue in self.issues if issue.blocking])

    def refresh(self) -> None:
        self.healthy = self.blocking_count == 0
        if self.fatal_count > 0:
            self.status = GeneratorContextStatus.ERROR
        elif self.error_count > 0:
            self.status = GeneratorContextStatus.INVALID
        elif self.warning_count > 0:
            self.status = GeneratorContextStatus.PARTIAL
        elif self.issues:
            self.status = GeneratorContextStatus.READY
        elif self.status == GeneratorContextStatus.UNKNOWN:
            self.status = GeneratorContextStatus.READY


@dataclass
class GeneratorRouteRef(GeneratorSerializableMixin):
    key: str
    path: str
    method: str = "GET"
    description: str = ""
    required: bool = False
    available: bool = True
    source: GeneratorContextSource = GeneratorContextSource.DEFAULT
    metadata: Dict[str, Any] = field(default_factory=dict)

    @classmethod
    def from_mapping(cls, key: str, value: Any) -> "GeneratorRouteRef":
        if isinstance(value, str):
            return cls(key=normalize_key(key), path=value)

        data = safe_mapping(value)
        return cls(
            key=normalize_key(data.get("key"), default=normalize_key(key)),
            path=safe_str(data.get("path") or data.get("url") or data.get("route"), default=""),
            method=safe_str(data.get("method"), default="GET").upper(),
            description=safe_str(data.get("description"), default=""),
            required=safe_bool(data.get("required"), default=False),
            available=safe_bool(data.get("available"), default=True),
            source=normalize_source(data.get("source"), GeneratorContextSource.DEFAULT),
            metadata=safe_mapping(data.get("metadata") or data.get("meta")),
        )


@dataclass
class GeneratorRouteContext(GeneratorSerializableMixin):
    status: GeneratorContextStatus = GeneratorContextStatus.READY
    source: GeneratorContextSource = GeneratorContextSource.DEFAULT
    routes: Dict[str, GeneratorRouteRef] = field(default_factory=dict)
    diagnostics: GeneratorContextDiagnostics = field(default_factory=GeneratorContextDiagnostics)
    loaded_at: str = field(default_factory=utc_now_iso)

    @classmethod
    def default(cls) -> "GeneratorRouteContext":
        return cls(
            status=GeneratorContextStatus.READY,
            source=GeneratorContextSource.DEFAULT,
            routes={
                key: GeneratorRouteRef(key=key, path=path, source=GeneratorContextSource.DEFAULT)
                for key, path in DEFAULT_GENERATOR_ROUTES.items()
            },
        )

    @classmethod
    def from_mapping(cls, value: Any) -> "GeneratorRouteContext":
        data = safe_mapping(value)
        route_payload = data.get("routes", data)
        routes: Dict[str, GeneratorRouteRef] = {}

        if isinstance(route_payload, MappingABC):
            for key, item in route_payload.items():
                if key in {"status", "source", "diagnostics", "loaded_at", "metadata"}:
                    continue
                parsed_key = normalize_key(key, default="")
                if parsed_key:
                    routes[parsed_key] = GeneratorRouteRef.from_mapping(parsed_key, item)

        default_routes = cls.default().routes
        for key, route in default_routes.items():
            routes.setdefault(key, route)

        return cls(
            status=normalize_status(data.get("status"), GeneratorContextStatus.READY),
            source=normalize_source(data.get("source"), GeneratorContextSource.MIXED),
            routes=routes,
            diagnostics=GeneratorContextDiagnostics.from_mapping(data.get("diagnostics")),
            loaded_at=safe_str(data.get("loaded_at"), default=utc_now_iso()),
        )

    def get_path(self, key: str, default: str = "") -> str:
        route = self.routes.get(normalize_key(key, default=""))
        return route.path if route else default

    def require(self, key: str) -> Optional[GeneratorRouteRef]:
        route = self.routes.get(normalize_key(key, default=""))
        if route and route.available and route.path:
            return route
        self.diagnostics.add_error(
            "route_missing",
            f"Required route is missing: {key}",
            GeneratorContextSection.ROUTES,
            route_key=key,
        )
        return None


@dataclass
class GeneratorDefinitionContext(GeneratorSerializableMixin):
    status: GeneratorContextStatus = GeneratorContextStatus.UNKNOWN
    source: GeneratorContextSource = GeneratorContextSource.UNKNOWN
    schema_version: str = ""
    definitions_version: str = ""
    datasets: Dict[str, Dict[str, Any]] = field(default_factory=dict)
    variables: Dict[str, Dict[str, Any]] = field(default_factory=dict)
    units: Dict[str, Dict[str, Any]] = field(default_factory=dict)
    materials: Dict[str, Dict[str, Any]] = field(default_factory=dict)
    document_types: Dict[str, Dict[str, Any]] = field(default_factory=dict)
    object_kinds: Dict[str, Dict[str, Any]] = field(default_factory=dict)
    family_profiles: Dict[str, Dict[str, Any]] = field(default_factory=dict)
    variant_profiles: Dict[str, Dict[str, Any]] = field(default_factory=dict)
    profile_bindings: Dict[str, Dict[str, Any]] = field(default_factory=dict)
    overrides: Dict[str, Dict[str, Any]] = field(default_factory=dict)
    raw_payload: Dict[str, Any] = field(default_factory=dict)
    diagnostics: GeneratorContextDiagnostics = field(default_factory=GeneratorContextDiagnostics)
    loaded_at: str = field(default_factory=utc_now_iso)

    @classmethod
    def from_mapping(cls, value: Any) -> "GeneratorDefinitionContext":
        data = safe_mapping(value)

        catalog = safe_mapping(
            first_present(
                data,
                "catalog",
                "definition_catalog",
                "definitions",
                "payload",
                default=data,
            )
        )

        context = cls(
            status=normalize_status(data.get("status") or catalog.get("status"), GeneratorContextStatus.UNKNOWN),
            source=normalize_source(data.get("source") or catalog.get("source"), GeneratorContextSource.MIXED),
            schema_version=safe_str(data.get("schema_version") or catalog.get("schema_version"), default=""),
            definitions_version=safe_str(
                data.get("definitions_version") or catalog.get("definitions_version"),
                default="",
            ),
            datasets=normalize_record_map(catalog.get("datasets") or data.get("datasets")),
            variables=normalize_record_map(catalog.get("variables") or data.get("variables"), ("variable_key", "key", "id")),
            units=normalize_record_map(catalog.get("units") or data.get("units"), ("unit_id", "unit_key", "key", "id")),
            materials=normalize_record_map(catalog.get("materials") or data.get("materials"), ("material_id", "material_key", "key", "id")),
            document_types=normalize_record_map(
                catalog.get("document_types") or catalog.get("documentTypes") or data.get("document_types"),
                ("document_type_id", "document_type", "key", "id"),
            ),
            object_kinds=normalize_record_map(
                catalog.get("object_kinds") or catalog.get("objectKinds") or data.get("object_kinds"),
                ("object_kind_id", "object_kind", "key", "id"),
            ),
            family_profiles=normalize_record_map(
                catalog.get("family_profiles") or catalog.get("familyProfiles") or data.get("family_profiles"),
                ("family_profile_id", "profile_id", "key", "id"),
            ),
            variant_profiles=normalize_record_map(
                catalog.get("variant_profiles") or catalog.get("variantProfiles") or data.get("variant_profiles"),
                ("variant_profile_id", "profile_id", "key", "id"),
            ),
            profile_bindings=normalize_record_map(
                catalog.get("profile_bindings") or catalog.get("profileBindings") or data.get("profile_bindings"),
                ("binding_id", "key", "id"),
            ),
            overrides=normalize_record_map(catalog.get("overrides") or data.get("overrides"), ("override_uid", "key", "id")),
            raw_payload=safe_deepcopy(catalog, default={}),
            diagnostics=GeneratorContextDiagnostics.from_mapping(data.get("diagnostics") or catalog.get("diagnostics")),
            loaded_at=safe_str(data.get("loaded_at"), default=utc_now_iso()),
        )
        context.refresh_status()
        return context

    @property
    def ready(self) -> bool:
        return self.status == GeneratorContextStatus.READY

    def refresh_status(self) -> None:
        if self.diagnostics.blocking_count > 0:
            self.status = GeneratorContextStatus.INVALID
            return

        has_core = bool(self.object_kinds or self.family_profiles or self.variant_profiles)
        if has_core:
            self.status = GeneratorContextStatus.READY
        elif self.raw_payload:
            self.status = GeneratorContextStatus.PARTIAL
        elif self.status == GeneratorContextStatus.UNKNOWN:
            self.status = GeneratorContextStatus.UNAVAILABLE

    def get_collection(self, name: str) -> Dict[str, Dict[str, Any]]:
        normalized = normalize_key(name)
        return {
            "datasets": self.datasets,
            "variables": self.variables,
            "units": self.units,
            "materials": self.materials,
            "document_types": self.document_types,
            "object_kinds": self.object_kinds,
            "family_profiles": self.family_profiles,
            "variant_profiles": self.variant_profiles,
            "profile_bindings": self.profile_bindings,
            "overrides": self.overrides,
        }.get(normalized, {})

    def get_record(self, collection: str, key: Any) -> Optional[Dict[str, Any]]:
        record_key = normalize_key(key, default="")
        if not record_key:
            return None
        return self.get_collection(collection).get(record_key)

    def has_object_kind(self, object_kind: Any) -> bool:
        return normalize_key(object_kind) in self.object_kinds

    def get_object_kind(self, object_kind: Any) -> Optional[Dict[str, Any]]:
        return self.object_kinds.get(normalize_key(object_kind))

    def get_family_profile(self, profile_id: Any) -> Optional[Dict[str, Any]]:
        return self.family_profiles.get(normalize_key(profile_id))

    def get_variant_profile(self, profile_id: Any) -> Optional[Dict[str, Any]]:
        return self.variant_profiles.get(normalize_key(profile_id))

    def list_object_kind_keys(self) -> List[str]:
        return sorted(self.object_kinds.keys())

    def list_family_profile_keys(self) -> List[str]:
        return sorted(self.family_profiles.keys())

    def list_variant_profile_keys(self) -> List[str]:
        return sorted(self.variant_profiles.keys())


@dataclass
class GeneratorTaxonomyContext(GeneratorSerializableMixin):
    status: GeneratorContextStatus = GeneratorContextStatus.UNKNOWN
    source: GeneratorContextSource = GeneratorContextSource.UNKNOWN
    user_id: Optional[int] = DEFAULT_USER_ID
    owner_scope: str = "user:1"
    domain: str = ""
    category: str = ""
    subcategory: str = ""
    taxonomy_path: str = ""
    nodes: Dict[str, Dict[str, Any]] = field(default_factory=dict)
    tree: Dict[str, Any] = field(default_factory=dict)
    create_options: Dict[str, Any] = field(default_factory=dict)
    resolved_payload: Dict[str, Any] = field(default_factory=dict)
    diagnostics: GeneratorContextDiagnostics = field(default_factory=GeneratorContextDiagnostics)
    loaded_at: str = field(default_factory=utc_now_iso)

    @classmethod
    def from_mapping(cls, value: Any) -> "GeneratorTaxonomyContext":
        data = safe_mapping(value)
        selection = safe_mapping(data.get("selection"))
        domain = first_present(data, "domain", default=selection.get("domain"))
        category = first_present(data, "category", default=selection.get("category"))
        subcategory = first_present(data, "subcategory", default=selection.get("subcategory"))
        path = first_present(data, "taxonomy_path", "path", default=selection.get("taxonomy_path"))

        user_id = safe_int(data.get("user_id"), default=DEFAULT_USER_ID)
        context = cls(
            status=normalize_status(data.get("status"), GeneratorContextStatus.UNKNOWN),
            source=normalize_source(data.get("source"), GeneratorContextSource.MIXED),
            user_id=user_id,
            owner_scope=normalize_owner_scope(user_id=user_id, owner_scope=data.get("owner_scope")),
            domain=normalize_slug(domain),
            category=normalize_slug(category),
            subcategory=normalize_slug(subcategory),
            taxonomy_path=normalize_taxonomy_path(domain, category, subcategory, path),
            nodes=normalize_record_map(data.get("nodes"), ("node_key", "node_uid", "taxonomy_path", "key", "id")),
            tree=safe_mapping(data.get("tree")),
            create_options=safe_mapping(data.get("create_options") or data.get("options")),
            resolved_payload=safe_mapping(data.get("resolved") or data.get("resolved_payload") or data.get("payload")),
            diagnostics=GeneratorContextDiagnostics.from_mapping(data.get("diagnostics")),
            loaded_at=safe_str(data.get("loaded_at"), default=utc_now_iso()),
        )
        context.refresh_status()
        return context

    @property
    def selection(self) -> Dict[str, str]:
        return {
            "domain": self.domain,
            "category": self.category,
            "subcategory": self.subcategory,
            "taxonomy_path": self.current_taxonomy_path,
        }

    @property
    def current_taxonomy_path(self) -> str:
        return normalize_taxonomy_path(self.domain, self.category, self.subcategory, self.taxonomy_path)

    def refresh_status(self) -> None:
        if self.diagnostics.blocking_count > 0:
            self.status = GeneratorContextStatus.INVALID
            return
        if self.nodes or self.tree or self.create_options or self.resolved_payload:
            self.status = GeneratorContextStatus.READY
        elif self.status == GeneratorContextStatus.UNKNOWN:
            self.status = GeneratorContextStatus.UNAVAILABLE

    def has_selection(self) -> bool:
        return bool(self.current_taxonomy_path)

    def matches(self, domain: Any = None, category: Any = None, subcategory: Any = None) -> bool:
        expected = normalize_taxonomy_path(domain, category, subcategory)
        return bool(expected and expected == self.current_taxonomy_path)


@dataclass
class GeneratorUploadContext(GeneratorSerializableMixin):
    status: GeneratorContextStatus = GeneratorContextStatus.UNKNOWN
    source: GeneratorContextSource = GeneratorContextSource.UNKNOWN
    constraints: Dict[str, Any] = field(default_factory=dict)
    allowed_extensions: List[str] = field(default_factory=list)
    blocked_extensions: List[str] = field(default_factory=list)
    allowed_mime_types: List[str] = field(default_factory=list)
    blocked_mime_types: List[str] = field(default_factory=list)
    max_size_mb: Optional[float] = None
    storage_backends: List[str] = field(default_factory=list)
    document_types: Dict[str, Dict[str, Any]] = field(default_factory=dict)
    upload_groups: Dict[str, Dict[str, Any]] = field(default_factory=dict)
    diagnostics: GeneratorContextDiagnostics = field(default_factory=GeneratorContextDiagnostics)
    loaded_at: str = field(default_factory=utc_now_iso)

    @classmethod
    def from_mapping(cls, value: Any) -> "GeneratorUploadContext":
        data = safe_mapping(value)
        constraints = safe_mapping(data.get("constraints") or data.get("upload_constraints") or data.get("payload"))
        raw_allowed_extensions = first_present(data, "allowed_extensions", default=constraints.get("allowed_extensions"))
        raw_blocked_extensions = first_present(data, "blocked_extensions", "dangerous_extensions", default=constraints.get("blocked_extensions"))
        raw_allowed_mime_types = first_present(data, "allowed_mime_types", default=constraints.get("allowed_mime_types"))
        raw_blocked_mime_types = first_present(data, "blocked_mime_types", default=constraints.get("blocked_mime_types"))

        context = cls(
            status=normalize_status(data.get("status"), GeneratorContextStatus.UNKNOWN),
            source=normalize_source(data.get("source"), GeneratorContextSource.MIXED),
            constraints=constraints,
            allowed_extensions=sorted({normalize_extension(item) for item in safe_list(raw_allowed_extensions) if normalize_extension(item)}),
            blocked_extensions=sorted({normalize_extension(item) for item in safe_list(raw_blocked_extensions) if normalize_extension(item)}),
            allowed_mime_types=sorted({normalize_mime_type(item) for item in safe_list(raw_allowed_mime_types) if normalize_mime_type(item)}),
            blocked_mime_types=sorted({normalize_mime_type(item) for item in safe_list(raw_blocked_mime_types) if normalize_mime_type(item)}),
            max_size_mb=safe_float(first_present(data, "max_size_mb", default=constraints.get("max_size_mb")), default=None),
            storage_backends=[normalize_key(item) for item in safe_list(data.get("storage_backends") or constraints.get("storage_backends")) if normalize_key(item)],
            document_types=normalize_record_map(data.get("document_types") or constraints.get("document_types"), ("document_type_id", "document_type", "key", "id")),
            upload_groups=normalize_record_map(data.get("upload_groups") or constraints.get("upload_groups"), ("upload_group", "key", "id")),
            diagnostics=GeneratorContextDiagnostics.from_mapping(data.get("diagnostics")),
            loaded_at=safe_str(data.get("loaded_at"), default=utc_now_iso()),
        )
        context.refresh_status()
        return context

    @property
    def max_size_bytes(self) -> Optional[int]:
        if self.max_size_mb is None:
            return None
        try:
            return int(float(self.max_size_mb) * 1024 * 1024)
        except Exception:
            return None

    def refresh_status(self) -> None:
        if self.diagnostics.blocking_count > 0:
            self.status = GeneratorContextStatus.INVALID
            return
        if self.constraints or self.allowed_extensions or self.document_types:
            self.status = GeneratorContextStatus.READY
        elif self.status == GeneratorContextStatus.UNKNOWN:
            self.status = GeneratorContextStatus.UNAVAILABLE

    def allows_extension(self, filename_or_extension: Any) -> bool:
        extension = normalize_extension(filename_or_extension)
        if not extension:
            return False
        if extension in self.blocked_extensions:
            return False
        if self.allowed_extensions:
            return extension in self.allowed_extensions
        return True

    def allows_mime_type(self, mime_type: Any) -> bool:
        normalized = normalize_mime_type(mime_type)
        if not normalized:
            return False
        if normalized in self.blocked_mime_types:
            return False
        if self.allowed_mime_types:
            return normalized in self.allowed_mime_types
        return True


@dataclass
class GeneratorUserContext(GeneratorSerializableMixin):
    user_id: Optional[int] = DEFAULT_USER_ID
    owner_scope: str = "user:1"
    inventory_key: str = DEFAULT_INVENTORY_KEY
    active_collection_uid: str = ""
    active_collection_key: str = ""
    active_slot_index: Optional[int] = None
    roles: List[str] = field(default_factory=list)
    permissions: List[str] = field(default_factory=list)
    payload: Dict[str, Any] = field(default_factory=dict)
    metadata: Dict[str, Any] = field(default_factory=dict)

    @classmethod
    def default(cls) -> "GeneratorUserContext":
        return cls()

    @classmethod
    def from_mapping(cls, value: Any) -> "GeneratorUserContext":
        data = safe_mapping(value)
        user_id = safe_int(data.get("user_id"), default=DEFAULT_USER_ID)
        return cls(
            user_id=user_id,
            owner_scope=normalize_owner_scope(user_id=user_id, owner_scope=data.get("owner_scope")),
            inventory_key=normalize_key(data.get("inventory_key"), default=DEFAULT_INVENTORY_KEY),
            active_collection_uid=safe_str(data.get("active_collection_uid"), default=""),
            active_collection_key=normalize_key(data.get("active_collection_key"), default=""),
            active_slot_index=safe_int(data.get("active_slot_index"), default=None),
            roles=[normalize_key(item) for item in safe_list(data.get("roles")) if normalize_key(item)],
            permissions=[normalize_key(item) for item in safe_list(data.get("permissions")) if normalize_key(item)],
            payload=safe_mapping(data.get("payload")),
            metadata=safe_mapping(data.get("metadata") or data.get("meta")),
        )

    def can(self, permission: Any) -> bool:
        normalized = normalize_key(permission)
        return normalized in self.permissions or "admin" in self.roles


@dataclass
class GeneratorDraftContext(GeneratorSerializableMixin):
    status: GeneratorContextStatus = GeneratorContextStatus.UNKNOWN
    source: GeneratorContextSource = GeneratorContextSource.UNKNOWN
    draft_ref: str = ""
    draft_uid: str = ""
    draft_key: str = ""
    draft_mode: str = ""
    stage: str = ""
    target_item_ref: str = ""
    base_revision_ref: str = ""
    published_revision_ref: str = ""
    payload: Dict[str, Any] = field(default_factory=dict)
    variants: List[Dict[str, Any]] = field(default_factory=list)
    assets: List[Dict[str, Any]] = field(default_factory=list)
    documents: List[Dict[str, Any]] = field(default_factory=list)
    validation_issues: List[Dict[str, Any]] = field(default_factory=list)
    context_snapshot: Dict[str, Any] = field(default_factory=dict)
    diagnostics: GeneratorContextDiagnostics = field(default_factory=GeneratorContextDiagnostics)
    loaded_at: str = field(default_factory=utc_now_iso)

    @classmethod
    def empty(cls) -> "GeneratorDraftContext":
        return cls(status=GeneratorContextStatus.UNAVAILABLE)

    @classmethod
    def from_mapping(cls, value: Any) -> "GeneratorDraftContext":
        data = safe_mapping(value)
        draft_payload = safe_mapping(data.get("draft") or data.get("payload") or data)
        context = cls(
            status=normalize_status(draft_payload.get("status") or data.get("status"), GeneratorContextStatus.UNKNOWN),
            source=normalize_source(data.get("source"), GeneratorContextSource.MIXED),
            draft_ref=safe_str(first_present(draft_payload, "draft_ref", "id", "draft_uid"), default=""),
            draft_uid=safe_str(draft_payload.get("draft_uid"), default=""),
            draft_key=normalize_key(draft_payload.get("draft_key"), default=""),
            draft_mode=normalize_key(draft_payload.get("draft_mode"), default=""),
            stage=normalize_key(draft_payload.get("stage"), default=""),
            target_item_ref=safe_str(draft_payload.get("target_item_ref") or draft_payload.get("target_item_id"), default=""),
            base_revision_ref=safe_str(draft_payload.get("base_revision_ref") or draft_payload.get("base_revision_id"), default=""),
            published_revision_ref=safe_str(
                draft_payload.get("published_revision_ref") or draft_payload.get("published_revision_id"),
                default="",
            ),
            payload=draft_payload,
            variants=[safe_mapping(item) for item in safe_list(draft_payload.get("variants"))],
            assets=[safe_mapping(item) for item in safe_list(draft_payload.get("assets"))],
            documents=[safe_mapping(item) for item in safe_list(draft_payload.get("documents"))],
            validation_issues=[safe_mapping(item) for item in safe_list(draft_payload.get("validation_issues"))],
            context_snapshot=safe_mapping(draft_payload.get("context_snapshot") or draft_payload.get("generator_context")),
            diagnostics=GeneratorContextDiagnostics.from_mapping(data.get("diagnostics")),
            loaded_at=safe_str(data.get("loaded_at"), default=utc_now_iso()),
        )
        context.refresh_status()
        return context

    def refresh_status(self) -> None:
        if self.diagnostics.blocking_count > 0:
            self.status = GeneratorContextStatus.INVALID
            return
        if self.draft_ref or self.draft_uid or self.payload:
            if self.status in {GeneratorContextStatus.UNKNOWN, GeneratorContextStatus.UNAVAILABLE}:
                self.status = GeneratorContextStatus.READY
        elif self.status == GeneratorContextStatus.UNKNOWN:
            self.status = GeneratorContextStatus.UNAVAILABLE


@dataclass
class GeneratorPublishedContext(GeneratorSerializableMixin):
    status: GeneratorContextStatus = GeneratorContextStatus.UNKNOWN
    source: GeneratorContextSource = GeneratorContextSource.UNKNOWN
    item_ref: str = ""
    vplib_uid: str = ""
    family_id: str = ""
    package_id: str = ""
    revision_hash: str = ""
    current_revision_ref: str = ""
    item_payload: Dict[str, Any] = field(default_factory=dict)
    variants: List[Dict[str, Any]] = field(default_factory=list)
    assets: List[Dict[str, Any]] = field(default_factory=list)
    documents: List[Dict[str, Any]] = field(default_factory=list)
    diagnostics: GeneratorContextDiagnostics = field(default_factory=GeneratorContextDiagnostics)
    loaded_at: str = field(default_factory=utc_now_iso)

    @classmethod
    def empty(cls) -> "GeneratorPublishedContext":
        return cls(status=GeneratorContextStatus.UNAVAILABLE)

    @classmethod
    def from_mapping(cls, value: Any) -> "GeneratorPublishedContext":
        data = safe_mapping(value)
        item = safe_mapping(data.get("item") or data.get("family") or data.get("payload") or data)
        context = cls(
            status=normalize_status(item.get("status") or data.get("status"), GeneratorContextStatus.UNKNOWN),
            source=normalize_source(data.get("source"), GeneratorContextSource.MIXED),
            item_ref=safe_str(first_present(item, "item_ref", "id", "vplib_uid", "family_id"), default=""),
            vplib_uid=safe_str(item.get("vplib_uid"), default=""),
            family_id=safe_str(item.get("family_id"), default=""),
            package_id=safe_str(item.get("package_id"), default=""),
            revision_hash=safe_str(item.get("revision_hash") or item.get("current_revision_hash"), default=""),
            current_revision_ref=safe_str(item.get("current_revision_ref") or item.get("current_revision_id"), default=""),
            item_payload=item,
            variants=[safe_mapping(item) for item in safe_list(data.get("variants") or item.get("variants"))],
            assets=[safe_mapping(item) for item in safe_list(data.get("assets") or item.get("assets"))],
            documents=[safe_mapping(item) for item in safe_list(data.get("documents") or item.get("documents"))],
            diagnostics=GeneratorContextDiagnostics.from_mapping(data.get("diagnostics")),
            loaded_at=safe_str(data.get("loaded_at"), default=utc_now_iso()),
        )
        context.refresh_status()
        return context

    def refresh_status(self) -> None:
        if self.diagnostics.blocking_count > 0:
            self.status = GeneratorContextStatus.INVALID
            return
        if self.item_ref or self.vplib_uid or self.item_payload:
            if self.status in {GeneratorContextStatus.UNKNOWN, GeneratorContextStatus.UNAVAILABLE}:
                self.status = GeneratorContextStatus.READY
        elif self.status == GeneratorContextStatus.UNKNOWN:
            self.status = GeneratorContextStatus.UNAVAILABLE


@dataclass
class GeneratorFileContext(GeneratorSerializableMixin):
    status: GeneratorContextStatus = GeneratorContextStatus.UNKNOWN
    source: GeneratorContextSource = GeneratorContextSource.UNKNOWN
    files: Dict[str, Dict[str, Any]] = field(default_factory=dict)
    versions: Dict[str, Dict[str, Any]] = field(default_factory=dict)
    links: Dict[str, Dict[str, Any]] = field(default_factory=dict)
    context_files: Dict[str, List[Dict[str, Any]]] = field(default_factory=dict)
    diagnostics: GeneratorContextDiagnostics = field(default_factory=GeneratorContextDiagnostics)
    loaded_at: str = field(default_factory=utc_now_iso)

    @classmethod
    def from_mapping(cls, value: Any) -> "GeneratorFileContext":
        data = safe_mapping(value)
        context_files_raw = safe_mapping(data.get("context_files") or data.get("contexts"))
        context_files = {
            normalize_key(key): [safe_mapping(item) for item in safe_list(items)]
            for key, items in context_files_raw.items()
        }
        context = cls(
            status=normalize_status(data.get("status"), GeneratorContextStatus.UNKNOWN),
            source=normalize_source(data.get("source"), GeneratorContextSource.MIXED),
            files=normalize_record_map(data.get("files"), ("file_uid", "file_ref", "id", "key")),
            versions=normalize_record_map(data.get("versions"), ("version_uid", "version_ref", "id", "key")),
            links=normalize_record_map(data.get("links"), ("link_uid", "link_ref", "id", "key")),
            context_files=context_files,
            diagnostics=GeneratorContextDiagnostics.from_mapping(data.get("diagnostics")),
            loaded_at=safe_str(data.get("loaded_at"), default=utc_now_iso()),
        )
        context.refresh_status()
        return context

    def refresh_status(self) -> None:
        if self.diagnostics.blocking_count > 0:
            self.status = GeneratorContextStatus.INVALID
            return
        if self.files or self.versions or self.links or self.context_files:
            self.status = GeneratorContextStatus.READY
        elif self.status == GeneratorContextStatus.UNKNOWN:
            self.status = GeneratorContextStatus.UNAVAILABLE


@dataclass
class GeneratorCapabilities(GeneratorSerializableMixin):
    supports_context: bool = True
    supports_options: bool = True
    supports_validate: bool = True
    supports_package_plan: bool = True
    supports_download: bool = True
    supports_source_save: bool = False
    supports_persistent_drafts: bool = False
    supports_publish_prepare: bool = False
    supports_publish: bool = False
    supports_files: bool = False
    supports_user_inventory: bool = False
    supports_taxonomy_overrides: bool = False
    supports_definition_seed: bool = False
    supports_db_sync: bool = False
    supports_create_preview: bool = False
    payload_schema_version: str = "create_payload.v1"
    api_version: str = "v1"
    supported_actions: List[str] = field(default_factory=lambda: [item.value for item in GeneratorContextAction])
    supported_object_kinds: List[str] = field(default_factory=list)
    supported_modules: List[str] = field(default_factory=list)
    metadata: Dict[str, Any] = field(default_factory=dict)

    @classmethod
    def from_mapping(cls, value: Any) -> "GeneratorCapabilities":
        data = safe_mapping(value)
        defaults = cls()
        return cls(
            supports_context=safe_bool(data.get("supports_context"), defaults.supports_context),
            supports_options=safe_bool(data.get("supports_options"), defaults.supports_options),
            supports_validate=safe_bool(data.get("supports_validate"), defaults.supports_validate),
            supports_package_plan=safe_bool(data.get("supports_package_plan"), defaults.supports_package_plan),
            supports_download=safe_bool(data.get("supports_download"), defaults.supports_download),
            supports_source_save=safe_bool(data.get("supports_source_save"), defaults.supports_source_save),
            supports_persistent_drafts=safe_bool(data.get("supports_persistent_drafts"), defaults.supports_persistent_drafts),
            supports_publish_prepare=safe_bool(data.get("supports_publish_prepare"), defaults.supports_publish_prepare),
            supports_publish=safe_bool(data.get("supports_publish"), defaults.supports_publish),
            supports_files=safe_bool(data.get("supports_files"), defaults.supports_files),
            supports_user_inventory=safe_bool(data.get("supports_user_inventory"), defaults.supports_user_inventory),
            supports_taxonomy_overrides=safe_bool(data.get("supports_taxonomy_overrides"), defaults.supports_taxonomy_overrides),
            supports_definition_seed=safe_bool(data.get("supports_definition_seed"), defaults.supports_definition_seed),
            supports_db_sync=safe_bool(data.get("supports_db_sync"), defaults.supports_db_sync),
            supports_create_preview=safe_bool(data.get("supports_create_preview"), defaults.supports_create_preview),
            payload_schema_version=safe_str(data.get("payload_schema_version"), defaults.payload_schema_version),
            api_version=safe_str(data.get("api_version"), defaults.api_version),
            supported_actions=[
                normalize_key(item)
                for item in safe_list(data.get("supported_actions") or defaults.supported_actions)
                if normalize_key(item)
            ],
            supported_object_kinds=[
                normalize_key(item)
                for item in safe_list(data.get("supported_object_kinds"))
                if normalize_key(item)
            ],
            supported_modules=[
                normalize_key(item)
                for item in safe_list(data.get("supported_modules"))
                if normalize_key(item)
            ],
            metadata=safe_mapping(data.get("metadata") or data.get("meta")),
        )

    def supports(self, action: Any) -> bool:
        normalized = normalize_key(action)
        if not normalized:
            return False

        boolean_flag = f"supports_{normalized.replace('-', '_')}"
        if hasattr(self, boolean_flag):
            return safe_bool(getattr(self, boolean_flag), default=False)

        return normalized in self.supported_actions


@dataclass
class GeneratorContext(GeneratorSerializableMixin):
    schema_version: str = GENERATOR_CONTEXT_SCHEMA_VERSION
    context_uid: str = field(default_factory=new_context_uid)
    status: GeneratorContextStatus = GeneratorContextStatus.UNKNOWN
    source: GeneratorContextSource = GeneratorContextSource.MIXED
    created_at: str = field(default_factory=utc_now_iso)
    loaded_at: str = field(default_factory=utc_now_iso)
    routes: GeneratorRouteContext = field(default_factory=GeneratorRouteContext.default)
    user: GeneratorUserContext = field(default_factory=GeneratorUserContext.default)
    definitions: GeneratorDefinitionContext = field(default_factory=GeneratorDefinitionContext)
    taxonomy: GeneratorTaxonomyContext = field(default_factory=GeneratorTaxonomyContext)
    uploads: GeneratorUploadContext = field(default_factory=GeneratorUploadContext)
    files: GeneratorFileContext = field(default_factory=GeneratorFileContext)
    draft: GeneratorDraftContext = field(default_factory=GeneratorDraftContext.empty)
    published: GeneratorPublishedContext = field(default_factory=GeneratorPublishedContext.empty)
    capabilities: GeneratorCapabilities = field(default_factory=GeneratorCapabilities)
    diagnostics: GeneratorContextDiagnostics = field(default_factory=GeneratorContextDiagnostics)
    request_payload: Dict[str, Any] = field(default_factory=dict)
    generator_payload: Dict[str, Any] = field(default_factory=dict)
    metadata: Dict[str, Any] = field(default_factory=dict)

    @classmethod
    def empty(cls) -> "GeneratorContext":
        context = cls(status=GeneratorContextStatus.UNAVAILABLE)
        context.diagnostics.add_warning(
            "generator_context_empty",
            "Generator context is empty.",
            GeneratorContextSection.ROOT,
        )
        return context

    @classmethod
    def from_mapping(cls, value: Any) -> "GeneratorContext":
        data = safe_mapping(value)

        context = cls(
            schema_version=safe_str(data.get("schema_version"), default=GENERATOR_CONTEXT_SCHEMA_VERSION),
            context_uid=safe_str(data.get("context_uid"), default=new_context_uid()),
            status=normalize_status(data.get("status"), GeneratorContextStatus.UNKNOWN),
            source=normalize_source(data.get("source"), GeneratorContextSource.MIXED),
            created_at=safe_str(data.get("created_at"), default=utc_now_iso()),
            loaded_at=safe_str(data.get("loaded_at"), default=utc_now_iso()),
            routes=GeneratorRouteContext.from_mapping(data.get("routes") or data.get("route_context")),
            user=GeneratorUserContext.from_mapping(data.get("user") or data.get("user_context")),
            definitions=GeneratorDefinitionContext.from_mapping(data.get("definitions") or data.get("definition_context")),
            taxonomy=GeneratorTaxonomyContext.from_mapping(data.get("taxonomy") or data.get("taxonomy_context")),
            uploads=GeneratorUploadContext.from_mapping(data.get("uploads") or data.get("upload_context")),
            files=GeneratorFileContext.from_mapping(data.get("files") or data.get("file_context")),
            draft=GeneratorDraftContext.from_mapping(data.get("draft") or data.get("draft_context")),
            published=GeneratorPublishedContext.from_mapping(data.get("published") or data.get("published_context")),
            capabilities=GeneratorCapabilities.from_mapping(data.get("capabilities")),
            diagnostics=GeneratorContextDiagnostics.from_mapping(data.get("diagnostics")),
            request_payload=safe_mapping(data.get("request_payload")),
            generator_payload=safe_mapping(data.get("generator_payload")),
            metadata=safe_mapping(data.get("metadata") or data.get("meta")),
        )
        context.refresh_status()
        return context

    @property
    def ready(self) -> bool:
        return self.status == GeneratorContextStatus.READY and self.diagnostics.blocking_count == 0

    @property
    def partial(self) -> bool:
        return self.status == GeneratorContextStatus.PARTIAL

    @property
    def blocking(self) -> bool:
        return self.diagnostics.blocking_count > 0

    def refresh_status(self) -> None:
        section_statuses = [
            self.definitions.status,
            self.taxonomy.status,
            self.uploads.status,
            self.routes.status,
        ]

        if self.diagnostics.blocking_count > 0:
            self.status = GeneratorContextStatus.INVALID
            return

        if any(status == GeneratorContextStatus.ERROR for status in section_statuses):
            self.status = GeneratorContextStatus.ERROR
            return

        if any(status == GeneratorContextStatus.INVALID for status in section_statuses):
            self.status = GeneratorContextStatus.INVALID
            return

        ready_count = len([status for status in section_statuses if status == GeneratorContextStatus.READY])
        unavailable_count = len(
            [
                status
                for status in section_statuses
                if status in {GeneratorContextStatus.UNAVAILABLE, GeneratorContextStatus.UNKNOWN}
            ]
        )

        if ready_count == len(section_statuses):
            self.status = GeneratorContextStatus.READY
        elif ready_count > 0 and unavailable_count < len(section_statuses):
            self.status = GeneratorContextStatus.PARTIAL
        elif self.status == GeneratorContextStatus.UNKNOWN:
            self.status = GeneratorContextStatus.UNAVAILABLE

    def validate_minimum(
        self,
        require_definitions: bool = True,
        require_taxonomy: bool = True,
        require_uploads: bool = False,
        require_routes: bool = True,
    ) -> GeneratorContextDiagnostics:
        diagnostics = GeneratorContextDiagnostics()

        if require_definitions and self.definitions.status not in {
            GeneratorContextStatus.READY,
            GeneratorContextStatus.PARTIAL,
        }:
            diagnostics.add_error(
                "definitions_context_unavailable",
                "Generator definitions context is not available.",
                GeneratorContextSection.DEFINITIONS,
            )

        if require_taxonomy and self.taxonomy.status not in {
            GeneratorContextStatus.READY,
            GeneratorContextStatus.PARTIAL,
        }:
            diagnostics.add_error(
                "taxonomy_context_unavailable",
                "Generator taxonomy context is not available.",
                GeneratorContextSection.TAXONOMY,
            )

        if require_uploads and self.uploads.status not in {
            GeneratorContextStatus.READY,
            GeneratorContextStatus.PARTIAL,
        }:
            diagnostics.add_error(
                "upload_context_unavailable",
                "Generator upload context is not available.",
                GeneratorContextSection.UPLOADS,
            )

        if require_routes and self.routes.status not in {
            GeneratorContextStatus.READY,
            GeneratorContextStatus.PARTIAL,
        }:
            diagnostics.add_error(
                "route_context_unavailable",
                "Generator route context is not available.",
                GeneratorContextSection.ROUTES,
            )

        diagnostics.refresh()
        return diagnostics

    def add_diagnostics(self, diagnostics: Any) -> None:
        self.diagnostics.merge(diagnostics)
        self.refresh_status()

    def set_request_payload(self, payload: Any) -> None:
        self.request_payload = safe_mapping(payload)

    def set_generator_payload(self, payload: Any) -> None:
        self.generator_payload = safe_mapping(payload)

    def stable_hash(self) -> str:
        payload = self.to_dict(include_none=False)
        payload.pop("created_at", None)
        payload.pop("loaded_at", None)
        payload.pop("context_uid", None)
        return stable_hash(payload)

    def cache_key(self, *extra_parts: Any) -> str:
        parts = [
            self.schema_version,
            self.user.owner_scope,
            self.user.inventory_key,
            self.taxonomy.current_taxonomy_path,
            self.definitions.definitions_version,
            self.capabilities.payload_schema_version,
        ]
        parts.extend(safe_str(part) for part in extra_parts if part is not None)
        return stable_hash("|".join(parts), prefix="generator_context_cache")

    def to_public_dict(self, include_diagnostics: bool = True) -> Dict[str, Any]:
        payload = self.to_dict(include_none=False)
        if not include_diagnostics:
            payload.pop("diagnostics", None)
        return payload


@dataclass
class GeneratorContextCacheEntry(GeneratorSerializableMixin):
    key: str
    value: Any
    created_monotonic: float
    ttl_seconds: int = DEFAULT_CONTEXT_TTL_SECONDS
    created_at: str = field(default_factory=utc_now_iso)
    metadata: Dict[str, Any] = field(default_factory=dict)

    @property
    def age_seconds(self) -> float:
        return max(0.0, time.monotonic() - self.created_monotonic)

    @property
    def expired(self) -> bool:
        if self.ttl_seconds <= 0:
            return False
        return self.age_seconds > self.ttl_seconds


@dataclass
class GeneratorContextCacheResult(GeneratorSerializableMixin):
    key: str
    value: Any = None
    hit: bool = False
    stale: bool = False
    error: Optional[str] = None
    metadata: Dict[str, Any] = field(default_factory=dict)

    @property
    def ok(self) -> bool:
        return self.error is None


class GeneratorContextMemoryCache:
    """
    Small thread-safe in-memory cache.

    This is intentionally simple. Service layers can use it for short-lived
    generator contexts without coupling the domain model to Flask, Redis,
    SQLAlchemy, or app config.
    """

    def __init__(
        self,
        default_ttl_seconds: int = DEFAULT_CONTEXT_TTL_SECONDS,
        max_entries: int = DEFAULT_CONTEXT_CACHE_MAX_ENTRIES,
        copy_values: bool = True,
        name: str = "generator_context_memory_cache",
    ) -> None:
        self.default_ttl_seconds = max(0, int(default_ttl_seconds))
        self.max_entries = max(1, int(max_entries))
        self.copy_values = bool(copy_values)
        self.name = normalize_key(name, default="generator_context_memory_cache")
        self._items: Dict[str, GeneratorContextCacheEntry] = {}
        self._lock = threading.RLock()
        self._hits = 0
        self._misses = 0
        self._sets = 0
        self._errors = 0

    def _copy_value(self, value: Any) -> Any:
        if not self.copy_values:
            return value
        try:
            return copy.deepcopy(value)
        except Exception:
            return value

    def _normalize_cache_key(self, key: Any) -> str:
        text = safe_str(key, default="")
        if not text:
            text = stable_hash({"empty": True}, prefix="cache_key")
        return text

    def get_entry(self, key: Any, allow_expired: bool = False) -> Optional[GeneratorContextCacheEntry]:
        cache_key = self._normalize_cache_key(key)
        try:
            with self._lock:
                entry = self._items.get(cache_key)
                if entry is None:
                    self._misses += 1
                    return None
                if entry.expired and not allow_expired:
                    self._items.pop(cache_key, None)
                    self._misses += 1
                    return None
                self._hits += 1
                return entry
        except Exception:
            self._errors += 1
            return None

    def get(self, key: Any, default: Any = None) -> Any:
        entry = self.get_entry(key)
        if entry is None:
            return default
        return self._copy_value(entry.value)

    def set(
        self,
        key: Any,
        value: Any,
        ttl_seconds: Optional[int] = None,
        metadata: Optional[Mapping[str, Any]] = None,
    ) -> GeneratorContextCacheEntry:
        cache_key = self._normalize_cache_key(key)
        ttl = self.default_ttl_seconds if ttl_seconds is None else max(0, int(ttl_seconds))
        entry = GeneratorContextCacheEntry(
            key=cache_key,
            value=self._copy_value(value),
            created_monotonic=time.monotonic(),
            ttl_seconds=ttl,
            metadata=safe_mapping(metadata),
        )
        with self._lock:
            self._items[cache_key] = entry
            self._sets += 1
            self.prune()
        return entry

    def delete(self, key: Any) -> bool:
        cache_key = self._normalize_cache_key(key)
        with self._lock:
            existed = cache_key in self._items
            self._items.pop(cache_key, None)
            return existed

    def clear(self) -> int:
        with self._lock:
            count = len(self._items)
            self._items.clear()
            return count

    def prune(self) -> int:
        removed = 0
        with self._lock:
            expired_keys = [key for key, entry in self._items.items() if entry.expired]
            for key in expired_keys:
                self._items.pop(key, None)
                removed += 1

            if len(self._items) <= self.max_entries:
                return removed

            sorted_items = sorted(
                self._items.items(),
                key=lambda item: item[1].created_monotonic,
            )
            overflow = len(self._items) - self.max_entries
            for key, _entry in sorted_items[:overflow]:
                self._items.pop(key, None)
                removed += 1
        return removed

    def get_or_set_result(
        self,
        key: Any,
        factory: Callable[[], Any],
        ttl_seconds: Optional[int] = None,
        allow_stale_on_error: bool = True,
        fallback: Any = None,
        metadata: Optional[Mapping[str, Any]] = None,
    ) -> GeneratorContextCacheResult:
        cache_key = self._normalize_cache_key(key)

        fresh_entry = self.get_entry(cache_key, allow_expired=False)
        if fresh_entry is not None:
            return GeneratorContextCacheResult(
                key=cache_key,
                value=self._copy_value(fresh_entry.value),
                hit=True,
                stale=False,
                metadata={"cache": self.name, **safe_mapping(metadata)},
            )

        stale_entry = self.get_entry(cache_key, allow_expired=True) if allow_stale_on_error else None

        try:
            value = factory()
            self.set(cache_key, value, ttl_seconds=ttl_seconds, metadata=metadata)
            return GeneratorContextCacheResult(
                key=cache_key,
                value=self._copy_value(value),
                hit=False,
                stale=False,
                metadata={"cache": self.name, **safe_mapping(metadata)},
            )
        except Exception as exc:
            self._errors += 1
            if stale_entry is not None:
                return GeneratorContextCacheResult(
                    key=cache_key,
                    value=self._copy_value(stale_entry.value),
                    hit=True,
                    stale=True,
                    error=safe_str(exc, default="factory_error"),
                    metadata={"cache": self.name, "fallback": "stale", **safe_mapping(metadata)},
                )
            return GeneratorContextCacheResult(
                key=cache_key,
                value=fallback,
                hit=False,
                stale=False,
                error=safe_str(exc, default="factory_error"),
                metadata={"cache": self.name, "fallback": "default", **safe_mapping(metadata)},
            )

    def get_or_set(
        self,
        key: Any,
        factory: Callable[[], Any],
        ttl_seconds: Optional[int] = None,
        allow_stale_on_error: bool = True,
        fallback: Any = None,
        metadata: Optional[Mapping[str, Any]] = None,
    ) -> Any:
        return self.get_or_set_result(
            key=key,
            factory=factory,
            ttl_seconds=ttl_seconds,
            allow_stale_on_error=allow_stale_on_error,
            fallback=fallback,
            metadata=metadata,
        ).value

    def stats(self) -> Dict[str, Any]:
        with self._lock:
            self.prune()
            return {
                "name": self.name,
                "size": len(self._items),
                "max_entries": self.max_entries,
                "default_ttl_seconds": self.default_ttl_seconds,
                "hits": self._hits,
                "misses": self._misses,
                "sets": self._sets,
                "errors": self._errors,
                "keys": sorted(self._items.keys()),
            }


_DEFAULT_CONTEXT_CACHE = GeneratorContextMemoryCache()


def get_default_generator_context_cache() -> GeneratorContextMemoryCache:
    return _DEFAULT_CONTEXT_CACHE


def try_cache_get_or_set(
    key: Any,
    factory: Callable[[], Any],
    ttl_seconds: Optional[int] = None,
    cache: Optional[GeneratorContextMemoryCache] = None,
    allow_stale_on_error: bool = True,
    fallback: Any = None,
    metadata: Optional[Mapping[str, Any]] = None,
) -> GeneratorContextCacheResult:
    """
    Safe cache helper.

    It never raises for cache/factory failures. It returns a result object with
    either:
    - fresh cached value
    - newly created value
    - stale value on factory error
    - fallback on failure
    """
    selected_cache = cache or get_default_generator_context_cache()
    try:
        return selected_cache.get_or_set_result(
            key=key,
            factory=factory,
            ttl_seconds=ttl_seconds,
            allow_stale_on_error=allow_stale_on_error,
            fallback=fallback,
            metadata=metadata,
        )
    except Exception as exc:
        return GeneratorContextCacheResult(
            key=safe_str(key, default="unknown"),
            value=fallback,
            hit=False,
            stale=False,
            error=safe_str(exc, default="cache_error"),
            metadata={"cache": "try_cache_get_or_set", **safe_mapping(metadata)},
        )


def build_minimal_generator_context(
    user_id: Any = DEFAULT_USER_ID,
    inventory_key: Any = DEFAULT_INVENTORY_KEY,
    request_payload: Optional[Mapping[str, Any]] = None,
    metadata: Optional[Mapping[str, Any]] = None,
) -> GeneratorContext:
    """Build a safe minimal context for tests, fallback responses, or diagnostics."""
    user = GeneratorUserContext.from_mapping(
        {
            "user_id": user_id,
            "inventory_key": inventory_key,
        }
    )
    context = GeneratorContext(
        status=GeneratorContextStatus.PARTIAL,
        source=GeneratorContextSource.FALLBACK,
        user=user,
        request_payload=safe_mapping(request_payload),
        metadata=safe_mapping(metadata),
    )
    context.diagnostics.add_warning(
        "minimal_generator_context",
        "Using minimal fallback generator context.",
        GeneratorContextSection.ROOT,
    )
    context.refresh_status()
    return context


def get_generator_context_domain_health(include_cache: bool = True) -> Dict[str, Any]:
    """Return import/serialization/cache health for this domain module."""
    diagnostics = GeneratorContextDiagnostics()
    health: Dict[str, Any] = {
        "ok": True,
        "component": GENERATOR_CONTEXT_COMPONENT,
        "schema_version": GENERATOR_CONTEXT_SCHEMA_VERSION,
        "status": GeneratorContextStatus.READY.value,
        "checked_at": utc_now_iso(),
        "exports": [
            "GeneratorContext",
            "GeneratorDefinitionContext",
            "GeneratorTaxonomyContext",
            "GeneratorUploadContext",
            "GeneratorDraftContext",
            "GeneratorPublishedContext",
            "GeneratorFileContext",
            "GeneratorCapabilities",
            "GeneratorContextMemoryCache",
        ],
    }

    try:
        sample = build_minimal_generator_context()
        sample.to_dict()
        sample.stable_hash()
    except Exception as exc:
        diagnostics.add_error(
            "generator_context_domain_selftest_failed",
            "Generator context domain selftest failed.",
            GeneratorContextSection.DIAGNOSTICS,
            error=safe_str(exc),
        )

    if include_cache:
        try:
            health["cache"] = get_default_generator_context_cache().stats()
        except Exception as exc:
            diagnostics.add_warning(
                "generator_context_cache_stats_failed",
                "Generator context cache stats failed.",
                GeneratorContextSection.DIAGNOSTICS,
                error=safe_str(exc),
            )

    diagnostics.refresh()
    if diagnostics.blocking_count > 0:
        health["ok"] = False
        health["status"] = diagnostics.status.value

    health["diagnostics"] = diagnostics.to_dict()
    return health


def assert_generator_context_domain_ready() -> bool:
    """Raise RuntimeError when the domain module is not ready."""
    health = get_generator_context_domain_health(include_cache=False)
    if not health.get("ok"):
        raise RuntimeError(f"{GENERATOR_CONTEXT_COMPONENT} is not ready: {health}")
    return True


def clear_generator_context_domain_caches() -> Dict[str, Any]:
    """Clear module-local caches."""
    cleared = 0
    try:
        cleared = get_default_generator_context_cache().clear()
    except Exception:
        cleared = 0
    return {
        "ok": True,
        "component": GENERATOR_CONTEXT_COMPONENT,
        "cleared": cleared,
        "cleared_at": utc_now_iso(),
    }


__all__ = [
    "GENERATOR_CONTEXT_SCHEMA_VERSION",
    "GENERATOR_CONTEXT_COMPONENT",
    "DEFAULT_USER_ID",
    "DEFAULT_INVENTORY_KEY",
    "DEFAULT_GENERATOR_ROUTES",
    "GeneratorContextStatus",
    "GeneratorContextSource",
    "GeneratorContextSection",
    "GeneratorContextIssueSeverity",
    "GeneratorContextAction",
    "GeneratorContextIssue",
    "GeneratorContextDiagnostics",
    "GeneratorRouteRef",
    "GeneratorRouteContext",
    "GeneratorDefinitionContext",
    "GeneratorTaxonomyContext",
    "GeneratorUploadContext",
    "GeneratorUserContext",
    "GeneratorDraftContext",
    "GeneratorPublishedContext",
    "GeneratorFileContext",
    "GeneratorCapabilities",
    "GeneratorContext",
    "GeneratorContextCacheEntry",
    "GeneratorContextCacheResult",
    "GeneratorContextMemoryCache",
    "utc_now_iso",
    "new_context_uid",
    "normalize_key",
    "normalize_slug",
    "normalize_owner_scope",
    "normalize_taxonomy_path",
    "normalize_extension",
    "normalize_mime_type",
    "safe_str",
    "safe_bool",
    "safe_int",
    "safe_float",
    "safe_list",
    "safe_mapping",
    "safe_deepcopy",
    "parse_json_safe",
    "to_json_compatible",
    "stable_json_dumps",
    "stable_hash",
    "normalize_record_map",
    "merge_mappings",
    "get_default_generator_context_cache",
    "try_cache_get_or_set",
    "build_minimal_generator_context",
    "get_generator_context_domain_health",
    "assert_generator_context_domain_ready",
    "clear_generator_context_domain_caches",
]