# src/library/services/library_generator_workflow_service.py
from __future__ import annotations

"""
Workflow service for the VPLIB generator integration.

This service orchestrates generator actions:
- context
- options
- draft payload
- validation
- package plan
- download preparation
- source save delegation
- persistent draft creation
- draft publish preparation
- optional publish delegation

Intentional boundaries:
- no Flask imports
- no SQLAlchemy imports
- no direct repository calls
- no migrations
- no db.create_all()
- no direct source/file-system writes in this file
- no HTTP calls to local routes

All infrastructure work is delegated to existing services:
- library_create_service
- creative_library_draft_service
- library_file_service
- creative_library_service
- library_generator_context_service

This service is deliberately defensive because existing services may still have
different method names while the architecture is being consolidated.
"""

import copy
import importlib
import inspect
import json
import threading
import time
import traceback
import uuid
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Callable, Dict, Iterable, List, Mapping, Optional, Sequence, Tuple

try:
    from ..domain.generator_context import (
        DEFAULT_INVENTORY_KEY,
        DEFAULT_USER_ID,
        GENERATOR_CONTEXT_SCHEMA_VERSION,
        GeneratorCapabilities,
        GeneratorContext,
        GeneratorContextAction,
        GeneratorContextDiagnostics,
        GeneratorContextIssue,
        GeneratorContextIssueSeverity,
        GeneratorContextMemoryCache,
        GeneratorContextSection,
        GeneratorContextSource,
        GeneratorContextStatus,
        GeneratorDraftContext,
        build_minimal_generator_context,
        merge_mappings,
        normalize_action,
        normalize_key,
        normalize_owner_scope,
        normalize_taxonomy_path,
        parse_json_safe,
        safe_bool,
        safe_deepcopy,
        safe_float,
        safe_int,
        safe_list,
        safe_mapping,
        safe_str,
        stable_hash,
        to_json_compatible,
        try_cache_get_or_set,
        utc_now_iso,
    )
    from ..read_models.generator_context_builder import (
        GeneratorContextBuildOptions,
        GeneratorContextBuilder,
        GeneratorContextViewMode,
        get_default_generator_context_builder,
    )
    from .library_generator_context_service import (
        LibraryGeneratorContextRequest,
        LibraryGeneratorContextService,
        ServiceCallResult,
        get_library_generator_context_service,
    )
except Exception:  # pragma: no cover - fallback for alternate import roots
    from library.domain.generator_context import (
        DEFAULT_INVENTORY_KEY,
        DEFAULT_USER_ID,
        GENERATOR_CONTEXT_SCHEMA_VERSION,
        GeneratorCapabilities,
        GeneratorContext,
        GeneratorContextAction,
        GeneratorContextDiagnostics,
        GeneratorContextIssue,
        GeneratorContextIssueSeverity,
        GeneratorContextMemoryCache,
        GeneratorContextSection,
        GeneratorContextSource,
        GeneratorContextStatus,
        GeneratorDraftContext,
        build_minimal_generator_context,
        merge_mappings,
        normalize_action,
        normalize_key,
        normalize_owner_scope,
        normalize_taxonomy_path,
        parse_json_safe,
        safe_bool,
        safe_deepcopy,
        safe_float,
        safe_int,
        safe_list,
        safe_mapping,
        safe_str,
        stable_hash,
        to_json_compatible,
        try_cache_get_or_set,
        utc_now_iso,
    )
    from library.read_models.generator_context_builder import (
        GeneratorContextBuildOptions,
        GeneratorContextBuilder,
        GeneratorContextViewMode,
        get_default_generator_context_builder,
    )
    from library.services.library_generator_context_service import (
        LibraryGeneratorContextRequest,
        LibraryGeneratorContextService,
        ServiceCallResult,
        get_library_generator_context_service,
    )


LIBRARY_GENERATOR_WORKFLOW_SERVICE_COMPONENT = "library.services.library_generator_workflow_service"
LIBRARY_GENERATOR_WORKFLOW_SERVICE_SCHEMA_VERSION = "library_generator_workflow_service.v1"

DEFAULT_WORKFLOW_CACHE_TTL_SECONDS = 20
DEFAULT_WORKFLOW_CACHE_MAX_ENTRIES = 128

WORKFLOW_ACTION_CONTEXT = "context"
WORKFLOW_ACTION_OPTIONS = "options"
WORKFLOW_ACTION_DRAFT = "draft"
WORKFLOW_ACTION_VALIDATE = "validate"
WORKFLOW_ACTION_PACKAGE_PLAN = "package_plan"
WORKFLOW_ACTION_DOWNLOAD = "download"
WORKFLOW_ACTION_SAVE = "save"
WORKFLOW_ACTION_PERSIST_DRAFT = "persist_draft"
WORKFLOW_ACTION_PUBLISH_PREPARE = "publish_prepare"
WORKFLOW_ACTION_PUBLISH = "publish"
WORKFLOW_ACTION_SYNC = "sync"

SUPPORTED_WORKFLOW_ACTIONS = [
    WORKFLOW_ACTION_CONTEXT,
    WORKFLOW_ACTION_OPTIONS,
    WORKFLOW_ACTION_DRAFT,
    WORKFLOW_ACTION_VALIDATE,
    WORKFLOW_ACTION_PACKAGE_PLAN,
    WORKFLOW_ACTION_DOWNLOAD,
    WORKFLOW_ACTION_SAVE,
    WORKFLOW_ACTION_PERSIST_DRAFT,
    WORKFLOW_ACTION_PUBLISH_PREPARE,
    WORKFLOW_ACTION_PUBLISH,
    WORKFLOW_ACTION_SYNC,
]

WRITE_ACTIONS = {
    WORKFLOW_ACTION_SAVE,
    WORKFLOW_ACTION_PERSIST_DRAFT,
    WORKFLOW_ACTION_PUBLISH,
    WORKFLOW_ACTION_SYNC,
}

DRAFT_WRITE_ACTIONS = {
    WORKFLOW_ACTION_PERSIST_DRAFT,
}

SOURCE_WRITE_ACTIONS = {
    WORKFLOW_ACTION_SAVE,
}

PUBLISHED_WRITE_ACTIONS = {
    WORKFLOW_ACTION_PUBLISH,
    WORKFLOW_ACTION_SYNC,
}


class GeneratorWorkflowStatus(str, Enum):
    UNKNOWN = "unknown"
    READY = "ready"
    PARTIAL = "partial"
    VALID = "valid"
    INVALID = "invalid"
    CREATED = "created"
    PLANNED = "planned"
    PREPARED = "prepared"
    SAVED = "saved"
    PERSISTED = "persisted"
    PUBLISHED = "published"
    SKIPPED = "skipped"
    UNAVAILABLE = "unavailable"
    ERROR = "error"

    def __str__(self) -> str:
        return self.value


class GeneratorWorkflowMode(str, Enum):
    DRY_RUN = "dry_run"
    PREVIEW = "preview"
    EXECUTE = "execute"
    TEST = "test"

    def __str__(self) -> str:
        return self.value


@dataclass
class LibraryGeneratorWorkflowRequest:
    """
    Internal workflow request.

    This is not an HTTP request. Route services should normalize incoming
    JSON/Form/Multipart values into this structure or a mapping compatible
    with it.
    """

    action: str = WORKFLOW_ACTION_DRAFT
    mode: GeneratorWorkflowMode = GeneratorWorkflowMode.PREVIEW

    user_id: Optional[int] = DEFAULT_USER_ID
    owner_scope: str = "user:1"
    inventory_key: str = DEFAULT_INVENTORY_KEY

    domain: str = ""
    category: str = ""
    subcategory: str = ""
    taxonomy_path: str = ""

    draft_ref: str = ""
    item_ref: str = ""
    vplib_uid: str = ""
    family_id: str = ""
    package_id: str = ""

    payload: Dict[str, Any] = field(default_factory=dict)
    files: Dict[str, Any] = field(default_factory=dict)
    upload_metadata: Dict[str, Any] = field(default_factory=dict)

    persist: bool = False
    save_source: bool = False
    publish: bool = False
    sync_after_save: bool = False
    validate_before_write: bool = True
    validate_after_write: bool = False
    allow_source_write: bool = False
    allow_publish_write: bool = False
    allow_draft_write: bool = True
    dry_run: bool = False

    include_context: bool = True
    include_options: bool = True
    include_files: bool = False
    include_draft: bool = False
    include_published: bool = False

    force_refresh: bool = False
    prefer_cache: bool = True
    cache_ttl_seconds: int = DEFAULT_WORKFLOW_CACHE_TTL_SECONDS

    correlation_id: str = ""
    metadata: Dict[str, Any] = field(default_factory=dict)

    @classmethod
    def from_mapping(cls, value: Any = None) -> "LibraryGeneratorWorkflowRequest":
        data = safe_mapping(value)

        raw_action = (
            data.get("action")
            or data.get("workflow_action")
            or data.get("intent")
            or data.get("operation")
            or WORKFLOW_ACTION_DRAFT
        )

        action = normalize_workflow_action(raw_action)
        mode = normalize_workflow_mode(data.get("mode") or data.get("workflow_mode"))

        user_id = safe_int(data.get("user_id"), DEFAULT_USER_ID)
        owner_scope = normalize_owner_scope(user_id=user_id, owner_scope=data.get("owner_scope"))

        payload = safe_mapping(
            data.get("payload")
            or data.get("request_payload")
            or data.get("create_payload")
            or data.get("draft_payload")
            or {}
        )

        # Allow top-level create fields as payload if no explicit payload was provided.
        if not payload:
            payload = {
                key: val
                for key, val in data.items()
                if key
                not in {
                    "action",
                    "workflow_action",
                    "intent",
                    "operation",
                    "mode",
                    "workflow_mode",
                    "files",
                    "metadata",
                    "meta",
                    "force_refresh",
                    "prefer_cache",
                    "cache_ttl_seconds",
                }
            }

        selection = safe_mapping(data.get("selection"))
        domain = safe_str(data.get("domain") or selection.get("domain") or payload.get("domain"), "")
        category = safe_str(data.get("category") or selection.get("category") or payload.get("category"), "")
        subcategory = safe_str(data.get("subcategory") or selection.get("subcategory") or payload.get("subcategory"), "")
        taxonomy_path = normalize_taxonomy_path(
            domain=domain,
            category=category,
            subcategory=subcategory,
            path=data.get("taxonomy_path") or selection.get("taxonomy_path") or payload.get("taxonomy_path"),
        )

        draft_ref = safe_str(
            data.get("draft_ref")
            or data.get("draft_id")
            or data.get("draft_uid")
            or payload.get("draft_ref")
            or payload.get("draft_uid"),
            "",
        )

        item_ref = safe_str(
            data.get("item_ref")
            or data.get("item_id")
            or data.get("family_ref")
            or payload.get("item_ref")
            or payload.get("item_id"),
            "",
        )

        correlation_id = safe_str(data.get("correlation_id"), "")
        if not correlation_id:
            correlation_id = f"generator_workflow:{uuid.uuid4().hex}"

        persist_default = action == WORKFLOW_ACTION_PERSIST_DRAFT or safe_bool(data.get("persist"), False)
        save_default = action == WORKFLOW_ACTION_SAVE or safe_bool(data.get("save_source"), False)
        publish_default = action == WORKFLOW_ACTION_PUBLISH or safe_bool(data.get("publish"), False)

        return cls(
            action=action,
            mode=mode,
            user_id=user_id,
            owner_scope=owner_scope,
            inventory_key=normalize_key(data.get("inventory_key"), DEFAULT_INVENTORY_KEY),
            domain=domain,
            category=category,
            subcategory=subcategory,
            taxonomy_path=taxonomy_path,
            draft_ref=draft_ref,
            item_ref=item_ref,
            vplib_uid=safe_str(data.get("vplib_uid") or payload.get("vplib_uid"), ""),
            family_id=safe_str(data.get("family_id") or payload.get("family_id"), ""),
            package_id=safe_str(data.get("package_id") or payload.get("package_id"), ""),
            payload=payload,
            files=safe_mapping(data.get("files") or data.get("request_files") or data.get("uploads")),
            upload_metadata=safe_mapping(
                data.get("upload_metadata")
                or data.get("upload_payload")
                or {
                    "geometry_model_uploads_json": payload.get("geometry_model_uploads_json"),
                    "technical_document_uploads_json": payload.get("technical_document_uploads_json"),
                    "variant_document_uploads_json": payload.get("variant_document_uploads_json"),
                }
            ),
            persist=persist_default,
            save_source=save_default,
            publish=publish_default,
            sync_after_save=safe_bool(data.get("sync_after_save"), False),
            validate_before_write=safe_bool(data.get("validate_before_write"), True),
            validate_after_write=safe_bool(data.get("validate_after_write"), False),
            allow_source_write=safe_bool(data.get("allow_source_write"), False),
            allow_publish_write=safe_bool(data.get("allow_publish_write"), False),
            allow_draft_write=safe_bool(data.get("allow_draft_write"), True),
            dry_run=safe_bool(data.get("dry_run"), mode == GeneratorWorkflowMode.DRY_RUN),
            include_context=safe_bool(data.get("include_context"), True),
            include_options=safe_bool(data.get("include_options"), True),
            include_files=safe_bool(data.get("include_files"), bool(data.get("files") or data.get("uploads"))),
            include_draft=safe_bool(data.get("include_draft"), bool(draft_ref)),
            include_published=safe_bool(data.get("include_published"), bool(item_ref or data.get("vplib_uid"))),
            force_refresh=safe_bool(data.get("force_refresh") or data.get("refresh"), False),
            prefer_cache=safe_bool(data.get("prefer_cache"), True),
            cache_ttl_seconds=max(
                0,
                int(safe_int(data.get("cache_ttl_seconds"), DEFAULT_WORKFLOW_CACHE_TTL_SECONDS) or 0),
            ),
            correlation_id=correlation_id,
            metadata=safe_mapping(data.get("metadata") or data.get("meta")),
        )

    @property
    def current_taxonomy_path(self) -> str:
        return normalize_taxonomy_path(
            domain=self.domain,
            category=self.category,
            subcategory=self.subcategory,
            path=self.taxonomy_path,
        )

    @property
    def is_write_action(self) -> bool:
        return self.action in WRITE_ACTIONS

    @property
    def is_source_write_action(self) -> bool:
        return self.action in SOURCE_WRITE_ACTIONS

    @property
    def is_published_write_action(self) -> bool:
        return self.action in PUBLISHED_WRITE_ACTIONS

    @property
    def is_draft_write_action(self) -> bool:
        return self.action in DRAFT_WRITE_ACTIONS

    def to_dict(self) -> Dict[str, Any]:
        return to_json_compatible(self)

    def cache_key(self, suffix: str = "") -> str:
        payload = self.to_dict()
        payload["suffix"] = safe_str(suffix, "")
        payload["force_refresh"] = False
        payload["prefer_cache"] = True

        # Do not put raw file objects into the stable key.
        payload["files"] = list(self.files.keys()) if isinstance(self.files, dict) else []

        return stable_hash(payload, prefix="library_generator_workflow_request")

    def to_context_request(self) -> LibraryGeneratorContextRequest:
        return LibraryGeneratorContextRequest.from_mapping(
            {
                "user_id": self.user_id,
                "owner_scope": self.owner_scope,
                "inventory_key": self.inventory_key,
                "domain": self.domain,
                "category": self.category,
                "subcategory": self.subcategory,
                "taxonomy_path": self.current_taxonomy_path,
                "draft_ref": self.draft_ref,
                "item_ref": self.item_ref,
                "vplib_uid": self.vplib_uid,
                "family_id": self.family_id,
                "package_id": self.package_id,
                "include_definitions": True,
                "include_taxonomy": True,
                "include_uploads": True,
                "include_files": self.include_files,
                "include_draft": self.include_draft,
                "include_published": self.include_published,
                "include_routes": True,
                "include_capabilities": True,
                "include_vplib_health": True,
                "force_refresh": self.force_refresh,
                "prefer_cache": self.prefer_cache,
                "cache_ttl_seconds": self.cache_ttl_seconds,
                "request_payload": self.payload,
                "metadata": {
                    "correlation_id": self.correlation_id,
                    "workflow_action": self.action,
                    **safe_mapping(self.metadata),
                },
            }
        )


@dataclass
class GeneratorWorkflowStep:
    key: str
    label: str = ""
    status: GeneratorWorkflowStatus = GeneratorWorkflowStatus.UNKNOWN
    ok: bool = False
    skipped: bool = False
    started_at: str = field(default_factory=utc_now_iso)
    finished_at: str = ""
    duration_ms: Optional[int] = None
    payload: Dict[str, Any] = field(default_factory=dict)
    issues: List[GeneratorContextIssue] = field(default_factory=list)
    error: str = ""
    traceback: str = ""
    metadata: Dict[str, Any] = field(default_factory=dict)

    def add_issue(self, issue: GeneratorContextIssue) -> None:
        self.issues.append(issue)
        self.refresh_status()

    def add_info(self, code: str, message: str, **details: Any) -> None:
        self.add_issue(
            GeneratorContextIssue.info(
                code=code,
                message=message,
                section=GeneratorContextSection.DIAGNOSTICS,
                **details,
            )
        )

    def add_warning(self, code: str, message: str, **details: Any) -> None:
        self.add_issue(
            GeneratorContextIssue.warning(
                code=code,
                message=message,
                section=GeneratorContextSection.DIAGNOSTICS,
                **details,
            )
        )

    def add_error(self, code: str, message: str, **details: Any) -> None:
        self.add_issue(
            GeneratorContextIssue.error(
                code=code,
                message=message,
                section=GeneratorContextSection.DIAGNOSTICS,
                **details,
            )
        )

    @property
    def blocking_count(self) -> int:
        return len([issue for issue in self.issues if issue.blocking])

    @property
    def warning_count(self) -> int:
        return len(
            [
                issue
                for issue in self.issues
                if issue.severity == GeneratorContextIssueSeverity.WARNING
            ]
        )

    def refresh_status(self) -> None:
        if self.skipped:
            self.status = GeneratorWorkflowStatus.SKIPPED
            self.ok = True
            return

        if self.error or self.blocking_count > 0:
            self.status = GeneratorWorkflowStatus.ERROR
            self.ok = False
            return

        if self.status == GeneratorWorkflowStatus.UNKNOWN:
            self.status = GeneratorWorkflowStatus.READY

        self.ok = self.status not in {
            GeneratorWorkflowStatus.ERROR,
            GeneratorWorkflowStatus.INVALID,
            GeneratorWorkflowStatus.UNAVAILABLE,
        }

    def finish(self) -> None:
        self.finished_at = utc_now_iso()
        try:
            # Approximation only; started_at is ISO, so duration should be set by callers where exact monotonic time is known.
            if self.duration_ms is None:
                self.duration_ms = 0
        except Exception:
            self.duration_ms = None
        self.refresh_status()

    def to_dict(self, include_payload: bool = True, include_traceback: bool = False) -> Dict[str, Any]:
        payload = {
            "key": self.key,
            "label": self.label,
            "status": self.status.value,
            "ok": self.ok,
            "skipped": self.skipped,
            "started_at": self.started_at,
            "finished_at": self.finished_at,
            "duration_ms": self.duration_ms,
            "issue_count": len(self.issues),
            "warning_count": self.warning_count,
            "blocking_count": self.blocking_count,
            "issues": [issue.to_dict() for issue in self.issues],
            "error": self.error,
            "metadata": to_json_compatible(self.metadata),
        }

        if include_payload:
            payload["payload"] = to_json_compatible(self.payload)

        if include_traceback:
            payload["traceback"] = self.traceback

        return payload


@dataclass
class GeneratorWorkflowResult:
    ok: bool = False
    status: GeneratorWorkflowStatus = GeneratorWorkflowStatus.UNKNOWN
    action: str = WORKFLOW_ACTION_DRAFT
    mode: GeneratorWorkflowMode = GeneratorWorkflowMode.PREVIEW
    correlation_id: str = ""
    request: LibraryGeneratorWorkflowRequest = field(default_factory=LibraryGeneratorWorkflowRequest)
    context: Optional[GeneratorContext] = None
    payload: Dict[str, Any] = field(default_factory=dict)
    draft_payload: Dict[str, Any] = field(default_factory=dict)
    validation_payload: Dict[str, Any] = field(default_factory=dict)
    package_plan_payload: Dict[str, Any] = field(default_factory=dict)
    download_payload: Dict[str, Any] = field(default_factory=dict)
    save_payload: Dict[str, Any] = field(default_factory=dict)
    persistent_draft_payload: Dict[str, Any] = field(default_factory=dict)
    publish_prepare_payload: Dict[str, Any] = field(default_factory=dict)
    publish_payload: Dict[str, Any] = field(default_factory=dict)
    sync_payload: Dict[str, Any] = field(default_factory=dict)
    steps: List[GeneratorWorkflowStep] = field(default_factory=list)
    diagnostics: GeneratorContextDiagnostics = field(default_factory=GeneratorContextDiagnostics)
    created_at: str = field(default_factory=utc_now_iso)
    duration_ms: Optional[int] = None
    cache_key: str = ""
    cache_hit: bool = False
    cache_stale: bool = False
    metadata: Dict[str, Any] = field(default_factory=dict)

    @property
    def step_count(self) -> int:
        return len(self.steps)

    @property
    def failed_step_count(self) -> int:
        return len([step for step in self.steps if not step.ok and not step.skipped])

    @property
    def warning_step_count(self) -> int:
        return len([step for step in self.steps if step.warning_count > 0])

    @property
    def blocking_count(self) -> int:
        return self.diagnostics.blocking_count + self.failed_step_count

    def add_step(self, step: GeneratorWorkflowStep) -> None:
        self.steps.append(step)
        for issue in step.issues:
            self.diagnostics.add_issue(issue)
        self.refresh_status()

    def add_issue(self, issue: GeneratorContextIssue) -> None:
        self.diagnostics.add_issue(issue)
        self.refresh_status()

    def add_info(self, code: str, message: str, **details: Any) -> None:
        self.add_issue(
            GeneratorContextIssue.info(
                code=code,
                message=message,
                section=GeneratorContextSection.DIAGNOSTICS,
                **details,
            )
        )

    def add_warning(self, code: str, message: str, **details: Any) -> None:
        self.add_issue(
            GeneratorContextIssue.warning(
                code=code,
                message=message,
                section=GeneratorContextSection.DIAGNOSTICS,
                **details,
            )
        )

    def add_error(self, code: str, message: str, **details: Any) -> None:
        self.add_issue(
            GeneratorContextIssue.error(
                code=code,
                message=message,
                section=GeneratorContextSection.DIAGNOSTICS,
                **details,
            )
        )

    def refresh_status(self) -> None:
        self.diagnostics.refresh()

        if self.diagnostics.blocking_count > 0 or self.failed_step_count > 0:
            self.status = GeneratorWorkflowStatus.ERROR
            self.ok = False
            return

        if self.status == GeneratorWorkflowStatus.UNKNOWN:
            self.status = GeneratorWorkflowStatus.READY

        self.ok = self.status not in {
            GeneratorWorkflowStatus.ERROR,
            GeneratorWorkflowStatus.INVALID,
            GeneratorWorkflowStatus.UNAVAILABLE,
        }

    def to_dict(
        self,
        include_context: bool = False,
        include_payloads: bool = True,
        include_tracebacks: bool = False,
    ) -> Dict[str, Any]:
        self.refresh_status()

        payload = {
            "ok": self.ok,
            "status": self.status.value,
            "action": self.action,
            "mode": self.mode.value,
            "correlation_id": self.correlation_id,
            "component": LIBRARY_GENERATOR_WORKFLOW_SERVICE_COMPONENT,
            "schema_version": LIBRARY_GENERATOR_WORKFLOW_SERVICE_SCHEMA_VERSION,
            "context_schema_version": GENERATOR_CONTEXT_SCHEMA_VERSION,
            "created_at": self.created_at,
            "duration_ms": self.duration_ms,
            "cache_key": self.cache_key,
            "cache_hit": self.cache_hit,
            "cache_stale": self.cache_stale,
            "summary": {
                "step_count": self.step_count,
                "failed_step_count": self.failed_step_count,
                "warning_step_count": self.warning_step_count,
                "blocking_count": self.blocking_count,
            },
            "request": self.request.to_dict(),
            "steps": [
                step.to_dict(
                    include_payload=include_payloads,
                    include_traceback=include_tracebacks,
                )
                for step in self.steps
            ],
            "diagnostics": self.diagnostics.to_dict(),
            "metadata": to_json_compatible(self.metadata),
        }

        if include_payloads:
            payload["payload"] = to_json_compatible(self.payload)
            payload["draft_payload"] = to_json_compatible(self.draft_payload)
            payload["validation_payload"] = to_json_compatible(self.validation_payload)
            payload["package_plan_payload"] = to_json_compatible(self.package_plan_payload)
            payload["download_payload"] = to_json_compatible(self.download_payload)
            payload["save_payload"] = to_json_compatible(self.save_payload)
            payload["persistent_draft_payload"] = to_json_compatible(self.persistent_draft_payload)
            payload["publish_prepare_payload"] = to_json_compatible(self.publish_prepare_payload)
            payload["publish_payload"] = to_json_compatible(self.publish_payload)
            payload["sync_payload"] = to_json_compatible(self.sync_payload)

        if include_context and self.context is not None:
            payload["context"] = self.context.to_public_dict(include_diagnostics=True)

        return payload


def normalize_workflow_action(value: Any) -> str:
    """Normalize action names to internal underscore-style workflow action keys."""
    if isinstance(value, GeneratorContextAction):
        raw = value.value
    else:
        raw = safe_str(value, "")

    normalized = normalize_key(raw, WORKFLOW_ACTION_DRAFT)

    aliases = {
        "package_plan": WORKFLOW_ACTION_PACKAGE_PLAN,
        "packageplan": WORKFLOW_ACTION_PACKAGE_PLAN,
        "plan": WORKFLOW_ACTION_PACKAGE_PLAN,
        "download_package": WORKFLOW_ACTION_DOWNLOAD,
        "archive": WORKFLOW_ACTION_DOWNLOAD,
        "source_save": WORKFLOW_ACTION_SAVE,
        "save_source": WORKFLOW_ACTION_SAVE,
        "save_package": WORKFLOW_ACTION_SAVE,
        "persistent_draft": WORKFLOW_ACTION_PERSIST_DRAFT,
        "persist": WORKFLOW_ACTION_PERSIST_DRAFT,
        "persist_draft": WORKFLOW_ACTION_PERSIST_DRAFT,
        "publish_prepare": WORKFLOW_ACTION_PUBLISH_PREPARE,
        "prepare_publish": WORKFLOW_ACTION_PUBLISH_PREPARE,
        "publish_preparation": WORKFLOW_ACTION_PUBLISH_PREPARE,
        "options": WORKFLOW_ACTION_OPTIONS,
        "create_options": WORKFLOW_ACTION_OPTIONS,
        "context": WORKFLOW_ACTION_CONTEXT,
        "generator_context": WORKFLOW_ACTION_CONTEXT,
        "validation": WORKFLOW_ACTION_VALIDATE,
        "validate": WORKFLOW_ACTION_VALIDATE,
        "draft": WORKFLOW_ACTION_DRAFT,
        "create_draft": WORKFLOW_ACTION_DRAFT,
        "sync": WORKFLOW_ACTION_SYNC,
        "db_sync": WORKFLOW_ACTION_SYNC,
    }

    normalized = aliases.get(normalized, normalized)

    if normalized not in SUPPORTED_WORKFLOW_ACTIONS:
        return WORKFLOW_ACTION_DRAFT

    return normalized


def normalize_workflow_mode(value: Any) -> GeneratorWorkflowMode:
    if isinstance(value, GeneratorWorkflowMode):
        return value

    normalized = normalize_key(value, GeneratorWorkflowMode.PREVIEW.value)
    aliases = {
        "dryrun": GeneratorWorkflowMode.DRY_RUN,
        "dry_run": GeneratorWorkflowMode.DRY_RUN,
        "preview": GeneratorWorkflowMode.PREVIEW,
        "execute": GeneratorWorkflowMode.EXECUTE,
        "run": GeneratorWorkflowMode.EXECUTE,
        "test": GeneratorWorkflowMode.TEST,
    }

    if normalized in aliases:
        return aliases[normalized]

    for mode in GeneratorWorkflowMode:
        if normalized == mode.value:
            return mode

    return GeneratorWorkflowMode.PREVIEW


def _traceback_text() -> str:
    try:
        return traceback.format_exc(limit=12)
    except Exception:
        return ""


def _coerce_payload(value: Any) -> Dict[str, Any]:
    if value is None:
        return {}

    if isinstance(value, dict):
        return to_json_compatible(value)

    if hasattr(value, "to_dict") and callable(getattr(value, "to_dict")):
        try:
            payload = value.to_dict()
            return payload if isinstance(payload, dict) else {"value": payload}
        except Exception:
            pass

    if hasattr(value, "as_dict") and callable(getattr(value, "as_dict")):
        try:
            payload = value.as_dict()
            return payload if isinstance(payload, dict) else {"value": payload}
        except Exception:
            pass

    if isinstance(value, str):
        parsed = parse_json_safe(value, default=None)
        if isinstance(parsed, dict):
            return parsed
        return {"value": value}

    if isinstance(value, (list, tuple)):
        return {"items": to_json_compatible(list(value))}

    try:
        payload = to_json_compatible(value)
        return payload if isinstance(payload, dict) else {"value": payload}
    except Exception:
        return {"value": safe_str(value)}


def _unwrap_response(value: Any) -> Dict[str, Any]:
    """
    Normalize different service response shapes into a flat-ish dict.
    """
    payload = _coerce_payload(value)
    result = dict(payload)

    for key in ("data", "payload", "result", "draft", "item", "package_plan", "validation", "download", "save"):
        nested = safe_mapping(payload.get(key))
        if nested:
            result.setdefault(f"_{key}", nested)
            result.update({k: v for k, v in nested.items() if k not in result})

    return result


def _response_ok(payload: Mapping[str, Any], default: bool = True) -> bool:
    if "ok" in payload:
        return safe_bool(payload.get("ok"), default)

    status = normalize_key(payload.get("status"), "")
    if status in {"error", "invalid", "failed", "unavailable"}:
        return False
    if status in {"ok", "ready", "valid", "created", "planned", "prepared", "saved", "persisted", "published"}:
        return True

    success = payload.get("success")
    if success is not None:
        return safe_bool(success, default)

    return default


def _deep_merge(left: Any, right: Any) -> Dict[str, Any]:
    base = safe_mapping(left)
    overlay = safe_mapping(right)
    result = dict(base)

    for key, value in overlay.items():
        if isinstance(value, Mapping) and isinstance(result.get(key), Mapping):
            result[key] = _deep_merge(result[key], value)
        elif isinstance(value, list):
            if value:
                result[key] = value
            elif key not in result:
                result[key] = []
        elif value is not None:
            result[key] = value

    return result


def _method_accepts_kwargs(func: Callable[..., Any]) -> bool:
    try:
        signature = inspect.signature(func)
    except Exception:
        return True
    return any(parameter.kind == parameter.VAR_KEYWORD for parameter in signature.parameters.values())


def _filtered_kwargs(func: Callable[..., Any], kwargs: Mapping[str, Any]) -> Dict[str, Any]:
    if _method_accepts_kwargs(func):
        return dict(kwargs)

    try:
        signature = inspect.signature(func)
    except Exception:
        return dict(kwargs)

    allowed = {
        name
        for name, parameter in signature.parameters.items()
        if parameter.kind in {parameter.POSITIONAL_OR_KEYWORD, parameter.KEYWORD_ONLY}
    }

    return {key: value for key, value in kwargs.items() if key in allowed}


class LibraryGeneratorWorkflowService:
    """
    Orchestrates generator workflow actions through existing services.

    This service is the boundary between Create/API layer and the VPLIB generator
    logic. It is allowed to orchestrate writes conceptually, but actual writes
    are always delegated to the responsible services.
    """

    def __init__(
        self,
        context_service: Optional[LibraryGeneratorContextService] = None,
        builder: Optional[GeneratorContextBuilder] = None,
        cache: Optional[GeneratorContextMemoryCache] = None,
        default_ttl_seconds: int = DEFAULT_WORKFLOW_CACHE_TTL_SECONDS,
    ) -> None:
        self.context_service = context_service or get_library_generator_context_service()
        self.builder = builder or get_default_generator_context_builder()
        self.cache = cache or GeneratorContextMemoryCache(
            default_ttl_seconds=default_ttl_seconds,
            max_entries=DEFAULT_WORKFLOW_CACHE_MAX_ENTRIES,
            name="library_generator_workflow_service_cache",
        )
        self.default_ttl_seconds = max(0, int(default_ttl_seconds))
        self._lock = threading.RLock()

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def run(
        self,
        request: Any = None,
        force_refresh: Optional[bool] = None,
        use_cache: Optional[bool] = None,
    ) -> GeneratorWorkflowResult:
        parsed_request = self.normalize_request(request)

        if force_refresh is not None:
            parsed_request.force_refresh = bool(force_refresh)
        if use_cache is not None:
            parsed_request.prefer_cache = bool(use_cache)

        # Write-like workflows should not be result-cached by default.
        should_cache = parsed_request.prefer_cache and not parsed_request.is_write_action and not parsed_request.force_refresh
        cache_key = parsed_request.cache_key("workflow")

        if not should_cache:
            return self._run_uncached(parsed_request, cache_key=cache_key)

        cache_result = try_cache_get_or_set(
            key=cache_key,
            factory=lambda: self._run_uncached(parsed_request, cache_key=cache_key),
            ttl_seconds=parsed_request.cache_ttl_seconds,
            cache=self.cache,
            allow_stale_on_error=True,
            fallback=self._fallback_result(parsed_request, cache_key=cache_key),
            metadata={
                "component": LIBRARY_GENERATOR_WORKFLOW_SERVICE_COMPONENT,
                "action": parsed_request.action,
            },
        )

        result = cache_result.value
        if not isinstance(result, GeneratorWorkflowResult):
            result = self._fallback_result(parsed_request, cache_key=cache_key)

        result.cache_key = cache_key
        result.cache_hit = cache_result.hit
        result.cache_stale = cache_result.stale

        if cache_result.error:
            result.add_warning(
                "generator_workflow_cache_warning",
                "Generator workflow cache returned a warning.",
                error=cache_result.error,
            )

        return result

    def run_payload(
        self,
        request: Any = None,
        force_refresh: Optional[bool] = None,
        use_cache: Optional[bool] = None,
        include_context: bool = False,
        include_payloads: bool = True,
        include_tracebacks: bool = False,
    ) -> Dict[str, Any]:
        return self.run(
            request=request,
            force_refresh=force_refresh,
            use_cache=use_cache,
        ).to_dict(
            include_context=include_context,
            include_payloads=include_payloads,
            include_tracebacks=include_tracebacks,
        )

    def get_context(self, request: Any = None) -> GeneratorWorkflowResult:
        req = self.normalize_request(request)
        req.action = WORKFLOW_ACTION_CONTEXT
        return self.run(req)

    def get_options(self, request: Any = None) -> GeneratorWorkflowResult:
        req = self.normalize_request(request)
        req.action = WORKFLOW_ACTION_OPTIONS
        return self.run(req)

    def create_draft_payload(self, payload: Any = None, request: Any = None) -> GeneratorWorkflowResult:
        req = self.normalize_request(_merge_request_payload(request, payload))
        req.action = WORKFLOW_ACTION_DRAFT
        return self.run(req)

    def validate_payload(self, payload: Any = None, request: Any = None) -> GeneratorWorkflowResult:
        req = self.normalize_request(_merge_request_payload(request, payload))
        req.action = WORKFLOW_ACTION_VALIDATE
        return self.run(req)

    def build_package_plan(self, payload: Any = None, request: Any = None) -> GeneratorWorkflowResult:
        req = self.normalize_request(_merge_request_payload(request, payload))
        req.action = WORKFLOW_ACTION_PACKAGE_PLAN
        return self.run(req)

    def prepare_download(self, payload: Any = None, request: Any = None) -> GeneratorWorkflowResult:
        req = self.normalize_request(_merge_request_payload(request, payload))
        req.action = WORKFLOW_ACTION_DOWNLOAD
        return self.run(req)

    def save_source_package(self, payload: Any = None, request: Any = None) -> GeneratorWorkflowResult:
        req = self.normalize_request(_merge_request_payload(request, payload))
        req.action = WORKFLOW_ACTION_SAVE
        req.save_source = True
        return self.run(req, use_cache=False)

    def create_persistent_draft(self, payload: Any = None, request: Any = None) -> GeneratorWorkflowResult:
        req = self.normalize_request(_merge_request_payload(request, payload))
        req.action = WORKFLOW_ACTION_PERSIST_DRAFT
        req.persist = True
        return self.run(req, use_cache=False)

    def publish_prepare(self, draft_ref: Any = None, payload: Any = None, request: Any = None) -> GeneratorWorkflowResult:
        req = self.normalize_request(_merge_request_payload(request, payload))
        req.action = WORKFLOW_ACTION_PUBLISH_PREPARE
        if draft_ref:
            req.draft_ref = safe_str(draft_ref)
            req.include_draft = True
        return self.run(req)

    def publish(self, draft_ref: Any = None, payload: Any = None, request: Any = None) -> GeneratorWorkflowResult:
        req = self.normalize_request(_merge_request_payload(request, payload))
        req.action = WORKFLOW_ACTION_PUBLISH
        req.publish = True
        if draft_ref:
            req.draft_ref = safe_str(draft_ref)
            req.include_draft = True
        return self.run(req, use_cache=False)

    def get_health(self, include_cache: bool = True, check_dependencies: bool = True) -> Dict[str, Any]:
        diagnostics = GeneratorContextDiagnostics()

        context_service_health: Dict[str, Any] = {}
        try:
            context_service_health = self.context_service.get_health(
                check_dependencies=check_dependencies,
                include_cache=include_cache,
            )
            if not safe_bool(context_service_health.get("ok"), False):
                diagnostics.add_warning(
                    "context_service_health_not_ok",
                    "Generator context service health is not OK.",
                    GeneratorContextSection.DIAGNOSTICS,
                    status=context_service_health.get("status"),
                )
        except Exception as exc:
            diagnostics.add_error(
                "context_service_health_failed",
                "Generator context service health failed.",
                GeneratorContextSection.DIAGNOSTICS,
                error=safe_str(exc),
            )

        # Exercise a read-only minimal workflow.
        try:
            minimal = self.run(
                LibraryGeneratorWorkflowRequest(
                    action=WORKFLOW_ACTION_CONTEXT,
                    mode=GeneratorWorkflowMode.TEST,
                    force_refresh=True,
                    prefer_cache=False,
                ),
                use_cache=False,
            )
            if not minimal.ok:
                diagnostics.add_warning(
                    "minimal_workflow_not_ok",
                    "Minimal workflow did not return ok.",
                    GeneratorContextSection.DIAGNOSTICS,
                    status=minimal.status.value,
                )
        except Exception as exc:
            diagnostics.add_error(
                "minimal_workflow_failed",
                "Minimal workflow failed.",
                GeneratorContextSection.DIAGNOSTICS,
                error=safe_str(exc),
            )

        diagnostics.refresh()

        payload: Dict[str, Any] = {
            "ok": diagnostics.blocking_count == 0,
            "status": diagnostics.status.value,
            "component": LIBRARY_GENERATOR_WORKFLOW_SERVICE_COMPONENT,
            "schema_version": LIBRARY_GENERATOR_WORKFLOW_SERVICE_SCHEMA_VERSION,
            "context_schema_version": GENERATOR_CONTEXT_SCHEMA_VERSION,
            "checked_at": utc_now_iso(),
            "supported_actions": SUPPORTED_WORKFLOW_ACTIONS,
            "write_actions": sorted(WRITE_ACTIONS),
            "context_service": context_service_health,
            "diagnostics": diagnostics.to_dict(),
        }

        if include_cache:
            payload["cache"] = self.cache.stats()
            try:
                payload["context_service_cache"] = self.context_service.cache.stats()
            except Exception:
                payload["context_service_cache"] = None
            try:
                payload["builder_cache"] = self.builder.cache.stats() if self.builder.cache is not None else None
            except Exception:
                payload["builder_cache"] = None

        return payload

    def assert_ready(self, require_dependencies: bool = False) -> bool:
        health = self.get_health(include_cache=False, check_dependencies=require_dependencies)
        if not health.get("ok"):
            raise RuntimeError(f"{LIBRARY_GENERATOR_WORKFLOW_SERVICE_COMPONENT} is not ready: {health}")
        return True

    def clear_caches(self) -> Dict[str, Any]:
        cleared_workflow = self.cache.clear()

        context_cleared: Dict[str, Any] = {}
        try:
            context_cleared = self.context_service.clear_caches()
        except Exception as exc:
            context_cleared = {"ok": False, "error": safe_str(exc)}

        builder_cleared = 0
        try:
            if self.builder.cache is not None:
                builder_cleared = self.builder.cache.clear()
        except Exception:
            builder_cleared = 0

        return {
            "ok": True,
            "component": LIBRARY_GENERATOR_WORKFLOW_SERVICE_COMPONENT,
            "cleared_at": utc_now_iso(),
            "cleared": {
                "workflow_cache": cleared_workflow,
                "context_service": context_cleared,
                "builder_cache": builder_cleared,
            },
        }

    # ------------------------------------------------------------------
    # Request normalization
    # ------------------------------------------------------------------

    def normalize_request(self, request: Any = None) -> LibraryGeneratorWorkflowRequest:
        if isinstance(request, LibraryGeneratorWorkflowRequest):
            return request
        return LibraryGeneratorWorkflowRequest.from_mapping(request)

    # ------------------------------------------------------------------
    # Internal workflow execution
    # ------------------------------------------------------------------

    def _run_uncached(
        self,
        request: LibraryGeneratorWorkflowRequest,
        cache_key: str = "",
    ) -> GeneratorWorkflowResult:
        started = time.monotonic()
        result = GeneratorWorkflowResult(
            action=request.action,
            mode=request.mode,
            correlation_id=request.correlation_id,
            request=request,
            cache_key=cache_key,
            metadata={
                "component": LIBRARY_GENERATOR_WORKFLOW_SERVICE_COMPONENT,
                "schema_version": LIBRARY_GENERATOR_WORKFLOW_SERVICE_SCHEMA_VERSION,
            },
        )

        try:
            context = self._load_context(request, result)
            result.context = context

            if request.action == WORKFLOW_ACTION_CONTEXT:
                self._action_context(request, result, context)
            elif request.action == WORKFLOW_ACTION_OPTIONS:
                self._action_options(request, result, context)
            elif request.action == WORKFLOW_ACTION_DRAFT:
                self._action_draft(request, result, context)
            elif request.action == WORKFLOW_ACTION_VALIDATE:
                self._action_validate(request, result, context)
            elif request.action == WORKFLOW_ACTION_PACKAGE_PLAN:
                self._action_package_plan(request, result, context)
            elif request.action == WORKFLOW_ACTION_DOWNLOAD:
                self._action_download(request, result, context)
            elif request.action == WORKFLOW_ACTION_SAVE:
                self._action_save(request, result, context)
            elif request.action == WORKFLOW_ACTION_PERSIST_DRAFT:
                self._action_persist_draft(request, result, context)
            elif request.action == WORKFLOW_ACTION_PUBLISH_PREPARE:
                self._action_publish_prepare(request, result, context)
            elif request.action == WORKFLOW_ACTION_PUBLISH:
                self._action_publish(request, result, context)
            elif request.action == WORKFLOW_ACTION_SYNC:
                self._action_sync(request, result, context)
            else:
                result.add_error(
                    "workflow_action_unknown",
                    "Unknown generator workflow action.",
                    action=request.action,
                )

        except Exception as exc:
            result.add_error(
                "workflow_failed",
                "Generator workflow failed.",
                error=safe_str(exc),
                exception_type=type(exc).__name__,
            )
            result.metadata["traceback"] = _traceback_text()

        result.duration_ms = int((time.monotonic() - started) * 1000)
        result.refresh_status()
        return result

    def _fallback_result(
        self,
        request: LibraryGeneratorWorkflowRequest,
        cache_key: str = "",
    ) -> GeneratorWorkflowResult:
        result = GeneratorWorkflowResult(
            ok=False,
            status=GeneratorWorkflowStatus.ERROR,
            action=request.action,
            mode=request.mode,
            correlation_id=request.correlation_id,
            request=request,
            cache_key=cache_key,
        )
        result.add_error(
            "workflow_fallback_result",
            "Generator workflow fallback result was used.",
        )
        return result

    def _load_context(
        self,
        request: LibraryGeneratorWorkflowRequest,
        result: GeneratorWorkflowResult,
    ) -> GeneratorContext:
        step = GeneratorWorkflowStep(
            key="load_context",
            label="Load generator context",
        )
        started = time.monotonic()

        try:
            context = self.context_service.get_context(
                request=request.to_context_request(),
                force_refresh=request.force_refresh,
                use_cache=request.prefer_cache,
            )

            if context.status in {GeneratorContextStatus.ERROR, GeneratorContextStatus.INVALID}:
                step.add_error(
                    "workflow_context_invalid",
                    "Generator context is invalid.",
                    context_status=context.status.value,
                )
            elif context.status == GeneratorContextStatus.PARTIAL:
                step.add_warning(
                    "workflow_context_partial",
                    "Generator context is partial.",
                    context_status=context.status.value,
                )
            else:
                step.add_info(
                    "workflow_context_loaded",
                    "Generator context was loaded.",
                    context_status=context.status.value,
                )

            step.status = GeneratorWorkflowStatus.READY
            step.payload = {
                "context_uid": context.context_uid,
                "status": context.status.value,
                "section_status": {
                    "routes": context.routes.status.value,
                    "definitions": context.definitions.status.value,
                    "taxonomy": context.taxonomy.status.value,
                    "uploads": context.uploads.status.value,
                    "files": context.files.status.value,
                    "draft": context.draft.status.value,
                    "published": context.published.status.value,
                },
            }

            step.duration_ms = int((time.monotonic() - started) * 1000)
            step.finish()
            result.add_step(step)
            return context
        except Exception as exc:
            step.error = safe_str(exc)
            step.traceback = _traceback_text()
            step.status = GeneratorWorkflowStatus.ERROR
            step.duration_ms = int((time.monotonic() - started) * 1000)
            step.add_error(
                "workflow_context_load_failed",
                "Could not load generator context.",
                error=safe_str(exc),
            )
            step.finish()
            result.add_step(step)
            return build_minimal_generator_context(
                user_id=request.user_id,
                inventory_key=request.inventory_key,
                request_payload=request.payload,
                metadata={
                    "fallback_reason": "workflow_context_load_failed",
                    "correlation_id": request.correlation_id,
                },
            )

    # ------------------------------------------------------------------
    # Action handlers
    # ------------------------------------------------------------------

    def _action_context(
        self,
        request: LibraryGeneratorWorkflowRequest,
        result: GeneratorWorkflowResult,
        context: GeneratorContext,
    ) -> None:
        payload = self.builder.build(
            context=context,
            mode=GeneratorContextViewMode.PUBLIC,
            options={
                "include_diagnostics": True,
                "include_raw_payloads": False,
                "compact": True,
            },
            use_cache=request.prefer_cache,
        ).payload

        result.payload = payload
        result.status = GeneratorWorkflowStatus.READY
        result.add_info(
            "workflow_context_ready",
            "Generator context payload was built.",
        )

    def _action_options(
        self,
        request: LibraryGeneratorWorkflowRequest,
        result: GeneratorWorkflowResult,
        context: GeneratorContext,
    ) -> None:
        payload = self.builder.build(
            context=context,
            mode=GeneratorContextViewMode.OPTIONS,
            options={
                "include_diagnostics": True,
                "include_raw_payloads": False,
                "compact": True,
            },
            use_cache=request.prefer_cache,
        ).payload

        result.payload = payload
        result.status = GeneratorWorkflowStatus.READY if _response_ok(payload) else GeneratorWorkflowStatus.PARTIAL
        if not _response_ok(payload):
            result.add_warning(
                "workflow_options_partial",
                "Create options payload is partial or not OK.",
                status=payload.get("status"),
            )

    def _action_draft(
        self,
        request: LibraryGeneratorWorkflowRequest,
        result: GeneratorWorkflowResult,
        context: GeneratorContext,
    ) -> None:
        draft_payload = self._build_create_draft_payload(request, context, result)
        result.draft_payload = draft_payload
        result.payload = draft_payload

        if _response_ok(draft_payload):
            result.status = GeneratorWorkflowStatus.CREATED
        else:
            result.status = GeneratorWorkflowStatus.PARTIAL
            result.add_warning(
                "workflow_draft_payload_partial",
                "Draft payload was created but response is partial.",
                response_status=draft_payload.get("status"),
            )

    def _action_validate(
        self,
        request: LibraryGeneratorWorkflowRequest,
        result: GeneratorWorkflowResult,
        context: GeneratorContext,
    ) -> None:
        validation_payload = self._validate_create_payload(request, context, result)
        result.validation_payload = validation_payload
        result.payload = validation_payload

        if _response_ok(validation_payload):
            result.status = GeneratorWorkflowStatus.VALID
        else:
            result.status = GeneratorWorkflowStatus.INVALID
            result.add_error(
                "workflow_validation_failed",
                "Generator payload validation failed.",
                response_status=validation_payload.get("status"),
            )

    def _action_package_plan(
        self,
        request: LibraryGeneratorWorkflowRequest,
        result: GeneratorWorkflowResult,
        context: GeneratorContext,
    ) -> None:
        if request.validate_before_write:
            validation_payload = self._validate_create_payload(request, context, result)
            result.validation_payload = validation_payload
            if not _response_ok(validation_payload):
                result.status = GeneratorWorkflowStatus.INVALID
                result.add_error(
                    "workflow_package_plan_validation_failed",
                    "Package plan was not built because validation failed.",
                    validation_status=validation_payload.get("status"),
                )
                return

        package_plan_payload = self._build_package_plan_payload(request, context, result)
        result.package_plan_payload = package_plan_payload
        result.payload = package_plan_payload

        if _response_ok(package_plan_payload):
            result.status = GeneratorWorkflowStatus.PLANNED
        else:
            result.status = GeneratorWorkflowStatus.PARTIAL
            result.add_warning(
                "workflow_package_plan_partial",
                "Package plan response is partial.",
                response_status=package_plan_payload.get("status"),
            )

    def _action_download(
        self,
        request: LibraryGeneratorWorkflowRequest,
        result: GeneratorWorkflowResult,
        context: GeneratorContext,
    ) -> None:
        if request.validate_before_write:
            validation_payload = self._validate_create_payload(request, context, result)
            result.validation_payload = validation_payload
            if not _response_ok(validation_payload):
                result.status = GeneratorWorkflowStatus.INVALID
                result.add_error(
                    "workflow_download_validation_failed",
                    "Download was not prepared because validation failed.",
                    validation_status=validation_payload.get("status"),
                )
                return

        download_payload = self._prepare_download_payload(request, context, result)
        result.download_payload = download_payload
        result.payload = download_payload

        if _response_ok(download_payload):
            result.status = GeneratorWorkflowStatus.PREPARED
        else:
            result.status = GeneratorWorkflowStatus.PARTIAL
            result.add_warning(
                "workflow_download_partial",
                "Download response is partial.",
                response_status=download_payload.get("status"),
            )

    def _action_save(
        self,
        request: LibraryGeneratorWorkflowRequest,
        result: GeneratorWorkflowResult,
        context: GeneratorContext,
    ) -> None:
        if not request.allow_source_write and not request.dry_run:
            result.status = GeneratorWorkflowStatus.SKIPPED
            result.add_warning(
                "workflow_save_blocked",
                "Source save was blocked because allow_source_write is false.",
            )
            return

        if request.validate_before_write:
            validation_payload = self._validate_create_payload(request, context, result)
            result.validation_payload = validation_payload
            if not _response_ok(validation_payload):
                result.status = GeneratorWorkflowStatus.INVALID
                result.add_error(
                    "workflow_save_validation_failed",
                    "Source save was not executed because validation failed.",
                    validation_status=validation_payload.get("status"),
                )
                return

        save_payload = self._save_source_payload(request, context, result)
        result.save_payload = save_payload
        result.payload = save_payload

        if _response_ok(save_payload):
            result.status = GeneratorWorkflowStatus.SAVED
        else:
            result.status = GeneratorWorkflowStatus.PARTIAL
            result.add_warning(
                "workflow_save_partial",
                "Source save response is partial.",
                response_status=save_payload.get("status"),
            )

        if request.sync_after_save:
            sync_payload = self._sync_after_save(request, context, result)
            result.sync_payload = sync_payload

    def _action_persist_draft(
        self,
        request: LibraryGeneratorWorkflowRequest,
        result: GeneratorWorkflowResult,
        context: GeneratorContext,
    ) -> None:
        if not request.allow_draft_write and not request.dry_run:
            result.status = GeneratorWorkflowStatus.SKIPPED
            result.add_warning(
                "workflow_persistent_draft_blocked",
                "Persistent draft creation was blocked because allow_draft_write is false.",
            )
            return

        draft_payload = self._build_create_draft_payload(request, context, result)
        result.draft_payload = draft_payload

        persistent_payload = self._persist_draft_payload(request, context, result, draft_payload)
        result.persistent_draft_payload = persistent_payload
        result.payload = persistent_payload

        if _response_ok(persistent_payload):
            result.status = GeneratorWorkflowStatus.PERSISTED
        else:
            result.status = GeneratorWorkflowStatus.PARTIAL
            result.add_warning(
                "workflow_persistent_draft_partial",
                "Persistent draft response is partial.",
                response_status=persistent_payload.get("status"),
            )

    def _action_publish_prepare(
        self,
        request: LibraryGeneratorWorkflowRequest,
        result: GeneratorWorkflowResult,
        context: GeneratorContext,
    ) -> None:
        publish_prepare_payload = self._prepare_publish_payload(request, context, result)
        result.publish_prepare_payload = publish_prepare_payload
        result.payload = publish_prepare_payload

        if _response_ok(publish_prepare_payload):
            result.status = GeneratorWorkflowStatus.PREPARED
        else:
            result.status = GeneratorWorkflowStatus.PARTIAL
            result.add_warning(
                "workflow_publish_prepare_partial",
                "Publish prepare response is partial.",
                response_status=publish_prepare_payload.get("status"),
            )

    def _action_publish(
        self,
        request: LibraryGeneratorWorkflowRequest,
        result: GeneratorWorkflowResult,
        context: GeneratorContext,
    ) -> None:
        if not request.allow_publish_write and not request.dry_run:
            result.status = GeneratorWorkflowStatus.SKIPPED
            result.add_warning(
                "workflow_publish_blocked",
                "Publish was blocked because allow_publish_write is false.",
            )
            return

        publish_prepare_payload = self._prepare_publish_payload(request, context, result)
        result.publish_prepare_payload = publish_prepare_payload

        if not _response_ok(publish_prepare_payload):
            result.status = GeneratorWorkflowStatus.INVALID
            result.add_error(
                "workflow_publish_prepare_failed",
                "Publish was not executed because publish prepare failed.",
                response_status=publish_prepare_payload.get("status"),
            )
            return

        publish_payload = self._publish_payload(request, context, result, publish_prepare_payload)
        result.publish_payload = publish_payload
        result.payload = publish_payload

        if _response_ok(publish_payload):
            result.status = GeneratorWorkflowStatus.PUBLISHED
        else:
            result.status = GeneratorWorkflowStatus.PARTIAL
            result.add_warning(
                "workflow_publish_partial",
                "Publish response is partial.",
                response_status=publish_payload.get("status"),
            )

    def _action_sync(
        self,
        request: LibraryGeneratorWorkflowRequest,
        result: GeneratorWorkflowResult,
        context: GeneratorContext,
    ) -> None:
        if not request.allow_publish_write and not request.dry_run:
            result.status = GeneratorWorkflowStatus.SKIPPED
            result.add_warning(
                "workflow_sync_blocked",
                "DB sync was blocked because allow_publish_write is false.",
            )
            return

        sync_payload = self._sync_after_save(request, context, result)
        result.sync_payload = sync_payload
        result.payload = sync_payload

        if _response_ok(sync_payload):
            result.status = GeneratorWorkflowStatus.PUBLISHED
        else:
            result.status = GeneratorWorkflowStatus.PARTIAL
            result.add_warning(
                "workflow_sync_partial",
                "Sync response is partial.",
                response_status=sync_payload.get("status"),
            )

    # ------------------------------------------------------------------
    # Operation helpers
    # ------------------------------------------------------------------

    def _build_create_draft_payload(
        self,
        request: LibraryGeneratorWorkflowRequest,
        context: GeneratorContext,
        result: GeneratorWorkflowResult,
    ) -> Dict[str, Any]:
        step = self._start_step("create_draft_payload", "Build create draft payload")
        started = time.monotonic()

        try:
            create_resolution = self.context_service.resolve_dependency("create")
            payload = self._call_dependency(
                create_resolution,
                method_names=[
                    "build_draft",
                    "build_draft_payload",
                    "create_draft_payload",
                    "create_draft",
                    "build_create_draft",
                    "normalize_create_payload",
                ],
                kwargs=self._common_operation_kwargs(request, context),
                positional_variants=[
                    (request.payload,),
                    (request.payload, context),
                ],
            )

            if not payload.ok:
                fallback = self._fallback_draft_payload(request, context)
                step.add_warning(
                    "create_draft_service_unavailable",
                    "Create service did not provide a draft payload; fallback draft payload was built.",
                    error=payload.error,
                )
                step.payload = fallback
                step.status = GeneratorWorkflowStatus.PARTIAL
                return fallback

            unwrapped = _unwrap_response(payload.payload)
            step.payload = unwrapped
            step.status = GeneratorWorkflowStatus.CREATED
            step.add_info(
                "create_draft_payload_created",
                "Create draft payload was built.",
                method=payload.method,
            )
            return unwrapped
        except Exception as exc:
            fallback = self._fallback_draft_payload(request, context)
            step.error = safe_str(exc)
            step.traceback = _traceback_text()
            step.add_warning(
                "create_draft_payload_fallback",
                "Create draft payload fallback was used after an exception.",
                error=safe_str(exc),
            )
            step.payload = fallback
            step.status = GeneratorWorkflowStatus.PARTIAL
            return fallback
        finally:
            step.duration_ms = int((time.monotonic() - started) * 1000)
            step.finish()
            result.add_step(step)

    def _validate_create_payload(
        self,
        request: LibraryGeneratorWorkflowRequest,
        context: GeneratorContext,
        result: GeneratorWorkflowResult,
    ) -> Dict[str, Any]:
        step = self._start_step("validate_payload", "Validate generator payload")
        started = time.monotonic()

        try:
            create_resolution = self.context_service.resolve_dependency("create")
            payload = self._call_dependency(
                create_resolution,
                method_names=[
                    "validate",
                    "validate_payload",
                    "validate_create_payload",
                    "validate_draft",
                    "build_validation_result",
                ],
                kwargs=self._common_operation_kwargs(request, context),
                positional_variants=[
                    (request.payload,),
                    (request.payload, context),
                ],
            )

            if not payload.ok:
                fallback = self._fallback_validation_payload(request, context, service_error=payload.error)
                step.add_warning(
                    "validation_service_unavailable",
                    "Create validation service did not return a result; fallback validation was used.",
                    error=payload.error,
                )
                step.payload = fallback
                step.status = GeneratorWorkflowStatus.PARTIAL if _response_ok(fallback) else GeneratorWorkflowStatus.INVALID
                return fallback

            unwrapped = _unwrap_response(payload.payload)
            step.payload = unwrapped
            step.status = GeneratorWorkflowStatus.VALID if _response_ok(unwrapped) else GeneratorWorkflowStatus.INVALID
            if _response_ok(unwrapped):
                step.add_info(
                    "payload_validation_ok",
                    "Payload validation completed.",
                    method=payload.method,
                )
            else:
                step.add_error(
                    "payload_validation_not_ok",
                    "Payload validation returned a non-OK response.",
                    method=payload.method,
                    response_status=unwrapped.get("status"),
                )
            return unwrapped
        except Exception as exc:
            fallback = self._fallback_validation_payload(request, context, service_error=safe_str(exc))
            step.error = safe_str(exc)
            step.traceback = _traceback_text()
            step.add_warning(
                "payload_validation_fallback",
                "Fallback validation was used after an exception.",
                error=safe_str(exc),
            )
            step.payload = fallback
            step.status = GeneratorWorkflowStatus.PARTIAL if _response_ok(fallback) else GeneratorWorkflowStatus.INVALID
            return fallback
        finally:
            step.duration_ms = int((time.monotonic() - started) * 1000)
            step.finish()
            result.add_step(step)

    def _build_package_plan_payload(
        self,
        request: LibraryGeneratorWorkflowRequest,
        context: GeneratorContext,
        result: GeneratorWorkflowResult,
    ) -> Dict[str, Any]:
        step = self._start_step("package_plan", "Build package plan")
        started = time.monotonic()

        try:
            create_resolution = self.context_service.resolve_dependency("create")
            payload = self._call_dependency(
                create_resolution,
                method_names=[
                    "build_package_plan",
                    "get_package_plan",
                    "package_plan",
                    "create_package_plan",
                    "build_plan",
                    "plan_package",
                ],
                kwargs=self._common_operation_kwargs(request, context),
                positional_variants=[
                    (request.payload,),
                    (request.payload, context),
                ],
            )

            if not payload.ok:
                fallback = self._fallback_package_plan_payload(request, context, service_error=payload.error)
                step.add_warning(
                    "package_plan_service_unavailable",
                    "Package plan service did not return a result; fallback plan was used.",
                    error=payload.error,
                )
                step.payload = fallback
                step.status = GeneratorWorkflowStatus.PARTIAL
                return fallback

            unwrapped = _unwrap_response(payload.payload)
            step.payload = unwrapped
            step.status = GeneratorWorkflowStatus.PLANNED if _response_ok(unwrapped) else GeneratorWorkflowStatus.PARTIAL
            step.add_info(
                "package_plan_built",
                "Package plan was built.",
                method=payload.method,
            )
            return unwrapped
        except Exception as exc:
            fallback = self._fallback_package_plan_payload(request, context, service_error=safe_str(exc))
            step.error = safe_str(exc)
            step.traceback = _traceback_text()
            step.add_warning(
                "package_plan_fallback",
                "Fallback package plan was used after an exception.",
                error=safe_str(exc),
            )
            step.payload = fallback
            step.status = GeneratorWorkflowStatus.PARTIAL
            return fallback
        finally:
            step.duration_ms = int((time.monotonic() - started) * 1000)
            step.finish()
            result.add_step(step)

    def _prepare_download_payload(
        self,
        request: LibraryGeneratorWorkflowRequest,
        context: GeneratorContext,
        result: GeneratorWorkflowResult,
    ) -> Dict[str, Any]:
        step = self._start_step("download", "Prepare download")
        started = time.monotonic()

        try:
            create_resolution = self.context_service.resolve_dependency("create")
            payload = self._call_dependency(
                create_resolution,
                method_names=[
                    "download",
                    "build_download",
                    "create_download",
                    "create_archive",
                    "build_archive",
                    "build_download_payload",
                ],
                kwargs=self._common_operation_kwargs(request, context),
                positional_variants=[
                    (request.payload,),
                    (request.payload, context),
                ],
            )

            if not payload.ok:
                fallback = {
                    "ok": False,
                    "status": GeneratorWorkflowStatus.UNAVAILABLE.value,
                    "error": payload.error,
                    "message": "Download service is unavailable.",
                    "dry_run": request.dry_run,
                }
                step.add_warning(
                    "download_service_unavailable",
                    "Download service is unavailable.",
                    error=payload.error,
                )
                step.payload = fallback
                step.status = GeneratorWorkflowStatus.UNAVAILABLE
                return fallback

            unwrapped = _unwrap_response(payload.payload)
            step.payload = unwrapped
            step.status = GeneratorWorkflowStatus.PREPARED if _response_ok(unwrapped) else GeneratorWorkflowStatus.PARTIAL
            step.add_info(
                "download_prepared",
                "Download was prepared.",
                method=payload.method,
            )
            return unwrapped
        except Exception as exc:
            fallback = {
                "ok": False,
                "status": GeneratorWorkflowStatus.ERROR.value,
                "error": safe_str(exc),
                "message": "Download preparation failed.",
            }
            step.error = safe_str(exc)
            step.traceback = _traceback_text()
            step.add_error(
                "download_failed",
                "Download preparation failed.",
                error=safe_str(exc),
            )
            step.payload = fallback
            step.status = GeneratorWorkflowStatus.ERROR
            return fallback
        finally:
            step.duration_ms = int((time.monotonic() - started) * 1000)
            step.finish()
            result.add_step(step)

    def _save_source_payload(
        self,
        request: LibraryGeneratorWorkflowRequest,
        context: GeneratorContext,
        result: GeneratorWorkflowResult,
    ) -> Dict[str, Any]:
        step = self._start_step("save_source", "Save source package")
        started = time.monotonic()

        try:
            create_resolution = self.context_service.resolve_dependency("create")
            payload = self._call_dependency(
                create_resolution,
                method_names=[
                    "save",
                    "save_source",
                    "save_package",
                    "save_source_package",
                    "write_source_package",
                    "create_source_package",
                ],
                kwargs=self._common_operation_kwargs(
                    request,
                    context,
                    extra={
                        "allow_source_write": request.allow_source_write,
                        "dry_run": request.dry_run,
                    },
                ),
                positional_variants=[
                    (request.payload,),
                    (request.payload, context),
                ],
            )

            if not payload.ok:
                fallback = {
                    "ok": False,
                    "status": GeneratorWorkflowStatus.UNAVAILABLE.value,
                    "error": payload.error,
                    "message": "Source save service is unavailable.",
                    "dry_run": request.dry_run,
                }
                step.add_warning(
                    "save_source_service_unavailable",
                    "Source save service is unavailable.",
                    error=payload.error,
                )
                step.payload = fallback
                step.status = GeneratorWorkflowStatus.UNAVAILABLE
                return fallback

            unwrapped = _unwrap_response(payload.payload)
            step.payload = unwrapped
            step.status = GeneratorWorkflowStatus.SAVED if _response_ok(unwrapped) else GeneratorWorkflowStatus.PARTIAL
            step.add_info(
                "source_save_executed",
                "Source save was delegated.",
                method=payload.method,
            )
            return unwrapped
        except Exception as exc:
            fallback = {
                "ok": False,
                "status": GeneratorWorkflowStatus.ERROR.value,
                "error": safe_str(exc),
                "message": "Source save failed.",
            }
            step.error = safe_str(exc)
            step.traceback = _traceback_text()
            step.add_error(
                "source_save_failed",
                "Source save failed.",
                error=safe_str(exc),
            )
            step.payload = fallback
            step.status = GeneratorWorkflowStatus.ERROR
            return fallback
        finally:
            step.duration_ms = int((time.monotonic() - started) * 1000)
            step.finish()
            result.add_step(step)

    def _persist_draft_payload(
        self,
        request: LibraryGeneratorWorkflowRequest,
        context: GeneratorContext,
        result: GeneratorWorkflowResult,
        draft_payload: Mapping[str, Any],
    ) -> Dict[str, Any]:
        step = self._start_step("persist_draft", "Persist generator draft")
        started = time.monotonic()

        try:
            draft_resolution = self.context_service.resolve_dependency("drafts")
            payload_to_persist = self._build_persistent_draft_input(request, context, draft_payload)

            payload = self._call_dependency(
                draft_resolution,
                method_names=[
                    "create_draft",
                    "create",
                    "create_from_payload",
                    "create_persistent_draft",
                    "save_draft",
                    "upsert_draft",
                ],
                kwargs={
                    "payload": payload_to_persist,
                    "draft_payload": payload_to_persist,
                    "user_id": request.user_id,
                    "owner_scope": request.owner_scope,
                    "commit": True,
                    "dry_run": request.dry_run,
                },
                positional_variants=[
                    (payload_to_persist,),
                    (payload_to_persist, request.user_id),
                ],
            )

            if not payload.ok:
                fallback = {
                    "ok": False,
                    "status": GeneratorWorkflowStatus.UNAVAILABLE.value,
                    "error": payload.error,
                    "message": "Draft persistence service is unavailable.",
                    "draft_payload": payload_to_persist,
                }
                step.add_warning(
                    "persist_draft_service_unavailable",
                    "Draft persistence service is unavailable.",
                    error=payload.error,
                )
                step.payload = fallback
                step.status = GeneratorWorkflowStatus.UNAVAILABLE
                return fallback

            unwrapped = _unwrap_response(payload.payload)
            step.payload = unwrapped
            step.status = GeneratorWorkflowStatus.PERSISTED if _response_ok(unwrapped) else GeneratorWorkflowStatus.PARTIAL
            step.add_info(
                "draft_persisted",
                "Generator draft was persisted.",
                method=payload.method,
            )
            return unwrapped
        except Exception as exc:
            fallback = {
                "ok": False,
                "status": GeneratorWorkflowStatus.ERROR.value,
                "error": safe_str(exc),
                "message": "Persistent draft creation failed.",
            }
            step.error = safe_str(exc)
            step.traceback = _traceback_text()
            step.add_error(
                "persist_draft_failed",
                "Persistent draft creation failed.",
                error=safe_str(exc),
            )
            step.payload = fallback
            step.status = GeneratorWorkflowStatus.ERROR
            return fallback
        finally:
            step.duration_ms = int((time.monotonic() - started) * 1000)
            step.finish()
            result.add_step(step)

    def _prepare_publish_payload(
        self,
        request: LibraryGeneratorWorkflowRequest,
        context: GeneratorContext,
        result: GeneratorWorkflowResult,
    ) -> Dict[str, Any]:
        step = self._start_step("publish_prepare", "Prepare publish payload")
        started = time.monotonic()

        try:
            draft_resolution = self.context_service.resolve_dependency("drafts")
            payload = self._call_dependency(
                draft_resolution,
                method_names=[
                    "publish_prepare",
                    "prepare_publish",
                    "prepare_draft_publish",
                    "build_publish_payload",
                    "build_publish_prepare_payload",
                ],
                kwargs={
                    "draft_ref": request.draft_ref,
                    "payload": request.payload,
                    "context": context,
                    "generator_context": context,
                    "user_id": request.user_id,
                    "owner_scope": request.owner_scope,
                    "dry_run": request.dry_run,
                },
                positional_variants=[
                    (request.draft_ref,),
                    (request.draft_ref, request.user_id),
                    (request.payload,),
                    (request.payload, context),
                ],
            )

            if not payload.ok:
                fallback = self._fallback_publish_prepare_payload(request, context, service_error=payload.error)
                step.add_warning(
                    "publish_prepare_service_unavailable",
                    "Publish prepare service is unavailable; fallback payload was built.",
                    error=payload.error,
                )
                step.payload = fallback
                step.status = GeneratorWorkflowStatus.PARTIAL
                return fallback

            unwrapped = _unwrap_response(payload.payload)
            step.payload = unwrapped
            step.status = GeneratorWorkflowStatus.PREPARED if _response_ok(unwrapped) else GeneratorWorkflowStatus.PARTIAL
            step.add_info(
                "publish_prepare_built",
                "Publish prepare payload was built.",
                method=payload.method,
            )
            return unwrapped
        except Exception as exc:
            fallback = self._fallback_publish_prepare_payload(request, context, service_error=safe_str(exc))
            step.error = safe_str(exc)
            step.traceback = _traceback_text()
            step.add_warning(
                "publish_prepare_fallback",
                "Publish prepare fallback was used after an exception.",
                error=safe_str(exc),
            )
            step.payload = fallback
            step.status = GeneratorWorkflowStatus.PARTIAL
            return fallback
        finally:
            step.duration_ms = int((time.monotonic() - started) * 1000)
            step.finish()
            result.add_step(step)

    def _publish_payload(
        self,
        request: LibraryGeneratorWorkflowRequest,
        context: GeneratorContext,
        result: GeneratorWorkflowResult,
        publish_prepare_payload: Mapping[str, Any],
    ) -> Dict[str, Any]:
        step = self._start_step("publish", "Publish generator payload")
        started = time.monotonic()

        try:
            draft_resolution = self.context_service.resolve_dependency("drafts")
            published_resolution = self.context_service.resolve_dependency("published")

            # Prefer DraftService publish if a draft_ref exists.
            if request.draft_ref:
                payload = self._call_dependency(
                    draft_resolution,
                    method_names=[
                        "publish",
                        "publish_draft",
                        "publish_from_draft",
                    ],
                    kwargs={
                        "draft_ref": request.draft_ref,
                        "payload": publish_prepare_payload,
                        "publish_payload": publish_prepare_payload,
                        "user_id": request.user_id,
                        "owner_scope": request.owner_scope,
                        "dry_run": request.dry_run,
                    },
                    positional_variants=[
                        (request.draft_ref,),
                        (request.draft_ref, request.user_id),
                    ],
                )
                if payload.ok:
                    unwrapped = _unwrap_response(payload.payload)
                    step.payload = unwrapped
                    step.status = GeneratorWorkflowStatus.PUBLISHED if _response_ok(unwrapped) else GeneratorWorkflowStatus.PARTIAL
                    step.add_info(
                        "draft_publish_executed",
                        "Draft publish was delegated.",
                        method=payload.method,
                    )
                    return unwrapped

            # Fallback to published creative library service.
            payload = self._call_dependency(
                published_resolution,
                method_names=[
                    "publish_bundle",
                    "publish",
                    "sync_package_payload",
                    "upsert_published_payload",
                ],
                kwargs={
                    "payload": publish_prepare_payload,
                    "publish_payload": publish_prepare_payload,
                    "user_id": request.user_id,
                    "owner_scope": request.owner_scope,
                    "dry_run": request.dry_run,
                },
                positional_variants=[
                    (publish_prepare_payload,),
                    (publish_prepare_payload, request.user_id),
                ],
            )

            if not payload.ok:
                fallback = {
                    "ok": False,
                    "status": GeneratorWorkflowStatus.UNAVAILABLE.value,
                    "error": payload.error,
                    "message": "Publish service is unavailable.",
                }
                step.add_warning(
                    "publish_service_unavailable",
                    "Publish service is unavailable.",
                    error=payload.error,
                )
                step.payload = fallback
                step.status = GeneratorWorkflowStatus.UNAVAILABLE
                return fallback

            unwrapped = _unwrap_response(payload.payload)
            step.payload = unwrapped
            step.status = GeneratorWorkflowStatus.PUBLISHED if _response_ok(unwrapped) else GeneratorWorkflowStatus.PARTIAL
            step.add_info(
                "publish_executed",
                "Publish was delegated.",
                method=payload.method,
            )
            return unwrapped
        except Exception as exc:
            fallback = {
                "ok": False,
                "status": GeneratorWorkflowStatus.ERROR.value,
                "error": safe_str(exc),
                "message": "Publish failed.",
            }
            step.error = safe_str(exc)
            step.traceback = _traceback_text()
            step.add_error(
                "publish_failed",
                "Publish failed.",
                error=safe_str(exc),
            )
            step.payload = fallback
            step.status = GeneratorWorkflowStatus.ERROR
            return fallback
        finally:
            step.duration_ms = int((time.monotonic() - started) * 1000)
            step.finish()
            result.add_step(step)

    def _sync_after_save(
        self,
        request: LibraryGeneratorWorkflowRequest,
        context: GeneratorContext,
        result: GeneratorWorkflowResult,
    ) -> Dict[str, Any]:
        step = self._start_step("sync", "Sync source/payload to Published DB")
        started = time.monotonic()

        try:
            published_resolution = self.context_service.resolve_dependency("published")
            payload = self._call_dependency(
                published_resolution,
                method_names=[
                    "sync_package_payload",
                    "publish_bundle",
                    "sync",
                    "sync_library_to_db",
                    "sync_library_source",
                ],
                kwargs={
                    "payload": request.payload,
                    "generator_context": context,
                    "user_id": request.user_id,
                    "owner_scope": request.owner_scope,
                    "dry_run": request.dry_run,
                    "force_refresh": request.force_refresh,
                },
                positional_variants=[
                    (request.payload,),
                    (request.payload, request.user_id),
                ],
            )

            if not payload.ok:
                fallback = {
                    "ok": False,
                    "status": GeneratorWorkflowStatus.UNAVAILABLE.value,
                    "error": payload.error,
                    "message": "Sync service is unavailable.",
                }
                step.add_warning(
                    "sync_service_unavailable",
                    "Sync service is unavailable.",
                    error=payload.error,
                )
                step.payload = fallback
                step.status = GeneratorWorkflowStatus.UNAVAILABLE
                return fallback

            unwrapped = _unwrap_response(payload.payload)
            step.payload = unwrapped
            step.status = GeneratorWorkflowStatus.PUBLISHED if _response_ok(unwrapped) else GeneratorWorkflowStatus.PARTIAL
            step.add_info(
                "sync_executed",
                "Sync was delegated.",
                method=payload.method,
            )
            return unwrapped
        except Exception as exc:
            fallback = {
                "ok": False,
                "status": GeneratorWorkflowStatus.ERROR.value,
                "error": safe_str(exc),
                "message": "Sync failed.",
            }
            step.error = safe_str(exc)
            step.traceback = _traceback_text()
            step.add_error(
                "sync_failed",
                "Sync failed.",
                error=safe_str(exc),
            )
            step.payload = fallback
            step.status = GeneratorWorkflowStatus.ERROR
            return fallback
        finally:
            step.duration_ms = int((time.monotonic() - started) * 1000)
            step.finish()
            result.add_step(step)

    # ------------------------------------------------------------------
    # Generic dependency call helper
    # ------------------------------------------------------------------

    def _call_dependency(
        self,
        resolution: Any,
        method_names: Sequence[str],
        kwargs: Mapping[str, Any],
        positional_variants: Optional[Sequence[Tuple[Any, ...]]] = None,
    ) -> ServiceCallResult:
        return self.context_service.call_first_available(
            resolution,
            method_names=method_names,
            kwargs=kwargs,
            positional_variants=positional_variants,
        )

    def _common_operation_kwargs(
        self,
        request: LibraryGeneratorWorkflowRequest,
        context: GeneratorContext,
        extra: Optional[Mapping[str, Any]] = None,
    ) -> Dict[str, Any]:
        payload = self._enrich_payload(request, context)

        kwargs = {
            "payload": payload,
            "request_payload": payload,
            "create_payload": payload,
            "draft_payload": payload,
            "files": request.files,
            "upload_metadata": request.upload_metadata,
            "context": context,
            "generator_context": context,
            "user_id": request.user_id,
            "owner_scope": request.owner_scope,
            "inventory_key": request.inventory_key,
            "domain": request.domain or payload.get("domain"),
            "category": request.category or payload.get("category"),
            "subcategory": request.subcategory or payload.get("subcategory"),
            "taxonomy_path": request.current_taxonomy_path or payload.get("taxonomy_path"),
            "draft_ref": request.draft_ref,
            "item_ref": request.item_ref,
            "vplib_uid": request.vplib_uid or payload.get("vplib_uid"),
            "family_id": request.family_id or payload.get("family_id"),
            "package_id": request.package_id or payload.get("package_id"),
            "dry_run": request.dry_run,
            "mode": request.mode.value,
            "correlation_id": request.correlation_id,
            "metadata": {
                "workflow_action": request.action,
                "correlation_id": request.correlation_id,
                **safe_mapping(request.metadata),
            },
        }

        if extra:
            kwargs.update(dict(extra))

        return kwargs

    def _enrich_payload(
        self,
        request: LibraryGeneratorWorkflowRequest,
        context: GeneratorContext,
    ) -> Dict[str, Any]:
        payload = safe_deepcopy(request.payload, default={})
        if not isinstance(payload, dict):
            payload = {}

        payload.setdefault("user_id", request.user_id)
        payload.setdefault("owner_scope", request.owner_scope)
        payload.setdefault("inventory_key", request.inventory_key)

        if request.domain:
            payload.setdefault("domain", request.domain)
        if request.category:
            payload.setdefault("category", request.category)
        if request.subcategory:
            payload.setdefault("subcategory", request.subcategory)

        taxonomy_path = request.current_taxonomy_path or context.taxonomy.current_taxonomy_path
        if taxonomy_path:
            payload.setdefault("taxonomy_path", taxonomy_path)

        if request.vplib_uid:
            payload.setdefault("vplib_uid", request.vplib_uid)
        if request.family_id:
            payload.setdefault("family_id", request.family_id)
        if request.package_id:
            payload.setdefault("package_id", request.package_id)
        if request.draft_ref:
            payload.setdefault("draft_ref", request.draft_ref)

        if request.upload_metadata:
            payload.setdefault("upload_metadata", request.upload_metadata)

        payload.setdefault(
            "generator_context_snapshot",
            {
                "context_uid": context.context_uid,
                "schema_version": context.schema_version,
                "status": context.status.value,
                "definitions_version": context.definitions.definitions_version,
                "taxonomy_path": context.taxonomy.current_taxonomy_path,
                "payload_schema_version": context.capabilities.payload_schema_version,
            },
        )

        payload.setdefault(
            "generator_workflow",
            {
                "action": request.action,
                "mode": request.mode.value,
                "correlation_id": request.correlation_id,
                "created_at": utc_now_iso(),
            },
        )

        return payload

    def _build_persistent_draft_input(
        self,
        request: LibraryGeneratorWorkflowRequest,
        context: GeneratorContext,
        draft_payload: Mapping[str, Any],
    ) -> Dict[str, Any]:
        enriched = self._enrich_payload(request, context)

        return {
            **safe_mapping(draft_payload),
            "payload": enriched,
            "generator_payload": enriched,
            "generator_context_snapshot": context.to_public_dict(include_diagnostics=False),
            "user_id": request.user_id,
            "owner_scope": request.owner_scope,
            "draft_mode": "create",
            "source_scope": "generated",
            "status": "draft",
            "stage": "generator",
            "correlation_id": request.correlation_id,
        }

    # ------------------------------------------------------------------
    # Fallback payloads
    # ------------------------------------------------------------------

    def _fallback_draft_payload(
        self,
        request: LibraryGeneratorWorkflowRequest,
        context: GeneratorContext,
    ) -> Dict[str, Any]:
        payload = self._enrich_payload(request, context)

        family_name = safe_str(payload.get("family_name") or payload.get("label") or payload.get("name"), "Untitled")
        family_id = safe_str(payload.get("family_id"), "") or normalize_key(family_name, "untitled")
        package_id = safe_str(payload.get("package_id"), "") or family_id

        return {
            "ok": True,
            "status": GeneratorWorkflowStatus.CREATED.value,
            "source": "fallback",
            "draft": {
                "family_name": family_name,
                "family_description": safe_str(payload.get("family_description") or payload.get("description"), ""),
                "family_id": family_id,
                "package_id": package_id,
                "object_kind": safe_str(payload.get("object_kind"), ""),
                "domain": safe_str(payload.get("domain"), ""),
                "category": safe_str(payload.get("category"), ""),
                "subcategory": safe_str(payload.get("subcategory"), ""),
                "taxonomy_path": safe_str(payload.get("taxonomy_path"), ""),
                "default_variant_id": safe_str(payload.get("default_variant_id"), "default"),
                "definition_variants_json": payload.get("definition_variants_json"),
                "payload": payload,
            },
            "diagnostics": {
                "fallback": True,
                "reason": "create_service_unavailable_or_partial",
            },
        }

    def _fallback_validation_payload(
        self,
        request: LibraryGeneratorWorkflowRequest,
        context: GeneratorContext,
        service_error: str = "",
    ) -> Dict[str, Any]:
        payload = self._enrich_payload(request, context)
        issues: List[Dict[str, Any]] = []

        required_fields = ["family_name", "domain", "category", "subcategory", "object_kind"]
        for field_name in required_fields:
            if not safe_str(payload.get(field_name), ""):
                issues.append(
                    {
                        "severity": "error",
                        "code": f"{field_name}_missing",
                        "message": f"Required field is missing: {field_name}",
                        "field": field_name,
                    }
                )

        if context.definitions.object_kinds and payload.get("object_kind"):
            object_kind = normalize_key(payload.get("object_kind"))
            if object_kind not in context.definitions.object_kinds:
                issues.append(
                    {
                        "severity": "warning",
                        "code": "object_kind_unknown",
                        "message": "Object kind is not known in current definitions context.",
                        "field": "object_kind",
                        "value": object_kind,
                    }
                )

        ok = not any(issue.get("severity") in {"error", "fatal"} for issue in issues)

        return {
            "ok": ok,
            "status": GeneratorWorkflowStatus.VALID.value if ok else GeneratorWorkflowStatus.INVALID.value,
            "source": "fallback",
            "issues": issues,
            "issue_count": len(issues),
            "service_error": service_error,
        }

    def _fallback_package_plan_payload(
        self,
        request: LibraryGeneratorWorkflowRequest,
        context: GeneratorContext,
        service_error: str = "",
    ) -> Dict[str, Any]:
        payload = self._enrich_payload(request, context)
        domain = normalize_key(payload.get("domain"), "unknown")
        category = normalize_key(payload.get("category"), "unknown")
        subcategory = normalize_key(payload.get("subcategory"), "unknown")
        family_id = normalize_key(payload.get("family_id") or payload.get("family_name"), "untitled")

        package_root = f"src/library/source/{domain}/{category}/{subcategory}/{family_id}"

        return {
            "ok": True,
            "status": GeneratorWorkflowStatus.PLANNED.value,
            "source": "fallback",
            "package_plan": {
                "package_root": package_root,
                "documents": [
                    "vplib.manifest.json",
                    "vplib.modules.json",
                    "family/identity.json",
                    "family/classification.json",
                    "variants/index.json",
                    "variants/default.json",
                ],
                "directories": [
                    "family",
                    "variants",
                    "editor",
                    "render",
                    "physical",
                    "material",
                    "calculation",
                    "manufacturer",
                    "docs",
                    "assets",
                ],
                "metadata": {
                    "fallback": True,
                    "service_error": service_error,
                },
            },
        }

    def _fallback_publish_prepare_payload(
        self,
        request: LibraryGeneratorWorkflowRequest,
        context: GeneratorContext,
        service_error: str = "",
    ) -> Dict[str, Any]:
        payload = self._enrich_payload(request, context)

        return {
            "ok": True,
            "status": GeneratorWorkflowStatus.PREPARED.value,
            "source": "fallback",
            "publish_payload": {
                "payload": payload,
                "draft_ref": request.draft_ref,
                "vplib_uid": request.vplib_uid or payload.get("vplib_uid"),
                "family_id": request.family_id or payload.get("family_id"),
                "package_id": request.package_id or payload.get("package_id"),
                "taxonomy_path": request.current_taxonomy_path or payload.get("taxonomy_path"),
                "generator_context_snapshot": context.to_public_dict(include_diagnostics=False),
                "metadata": {
                    "fallback": True,
                    "service_error": service_error,
                },
            },
        }

    # ------------------------------------------------------------------
    # Step helpers
    # ------------------------------------------------------------------

    def _start_step(self, key: str, label: str) -> GeneratorWorkflowStep:
        return GeneratorWorkflowStep(
            key=normalize_key(key),
            label=label,
            status=GeneratorWorkflowStatus.UNKNOWN,
        )


def _merge_request_payload(request: Any = None, payload: Any = None) -> Dict[str, Any]:
    base = safe_mapping(request)
    if isinstance(request, LibraryGeneratorWorkflowRequest):
        base = request.to_dict()

    explicit_payload = safe_mapping(payload)
    if explicit_payload:
        current_payload = safe_mapping(base.get("payload"))
        base["payload"] = _deep_merge(current_payload, explicit_payload)

    return base


_DEFAULT_WORKFLOW_SERVICE_LOCK = threading.RLock()
_DEFAULT_WORKFLOW_SERVICE: Optional[LibraryGeneratorWorkflowService] = None


def get_library_generator_workflow_service(
    force_new: bool = False,
) -> LibraryGeneratorWorkflowService:
    global _DEFAULT_WORKFLOW_SERVICE

    with _DEFAULT_WORKFLOW_SERVICE_LOCK:
        if force_new or _DEFAULT_WORKFLOW_SERVICE is None:
            _DEFAULT_WORKFLOW_SERVICE = LibraryGeneratorWorkflowService()
        return _DEFAULT_WORKFLOW_SERVICE


def run_generator_workflow(
    request: Any = None,
    force_refresh: Optional[bool] = None,
    use_cache: Optional[bool] = None,
) -> GeneratorWorkflowResult:
    return get_library_generator_workflow_service().run(
        request=request,
        force_refresh=force_refresh,
        use_cache=use_cache,
    )


def run_generator_workflow_payload(
    request: Any = None,
    force_refresh: Optional[bool] = None,
    use_cache: Optional[bool] = None,
    include_context: bool = False,
    include_payloads: bool = True,
    include_tracebacks: bool = False,
) -> Dict[str, Any]:
    return get_library_generator_workflow_service().run_payload(
        request=request,
        force_refresh=force_refresh,
        use_cache=use_cache,
        include_context=include_context,
        include_payloads=include_payloads,
        include_tracebacks=include_tracebacks,
    )


def create_generator_draft_payload(
    payload: Any = None,
    request: Any = None,
) -> Dict[str, Any]:
    return get_library_generator_workflow_service().create_draft_payload(
        payload=payload,
        request=request,
    ).to_dict(include_context=False, include_payloads=True)


def validate_generator_payload(
    payload: Any = None,
    request: Any = None,
) -> Dict[str, Any]:
    return get_library_generator_workflow_service().validate_payload(
        payload=payload,
        request=request,
    ).to_dict(include_context=False, include_payloads=True)


def build_generator_package_plan(
    payload: Any = None,
    request: Any = None,
) -> Dict[str, Any]:
    return get_library_generator_workflow_service().build_package_plan(
        payload=payload,
        request=request,
    ).to_dict(include_context=False, include_payloads=True)


def prepare_generator_download(
    payload: Any = None,
    request: Any = None,
) -> Dict[str, Any]:
    return get_library_generator_workflow_service().prepare_download(
        payload=payload,
        request=request,
    ).to_dict(include_context=False, include_payloads=True)


def save_generator_source_package(
    payload: Any = None,
    request: Any = None,
) -> Dict[str, Any]:
    return get_library_generator_workflow_service().save_source_package(
        payload=payload,
        request=request,
    ).to_dict(include_context=False, include_payloads=True)


def create_generator_persistent_draft(
    payload: Any = None,
    request: Any = None,
) -> Dict[str, Any]:
    return get_library_generator_workflow_service().create_persistent_draft(
        payload=payload,
        request=request,
    ).to_dict(include_context=False, include_payloads=True)


def prepare_generator_publish(
    draft_ref: Any = None,
    payload: Any = None,
    request: Any = None,
) -> Dict[str, Any]:
    return get_library_generator_workflow_service().publish_prepare(
        draft_ref=draft_ref,
        payload=payload,
        request=request,
    ).to_dict(include_context=False, include_payloads=True)


def get_library_generator_workflow_service_health(
    include_cache: bool = True,
    check_dependencies: bool = True,
) -> Dict[str, Any]:
    return get_library_generator_workflow_service().get_health(
        include_cache=include_cache,
        check_dependencies=check_dependencies,
    )


def assert_library_generator_workflow_service_ready(
    require_dependencies: bool = False,
) -> bool:
    return get_library_generator_workflow_service().assert_ready(
        require_dependencies=require_dependencies,
    )


def clear_library_generator_workflow_service_caches() -> Dict[str, Any]:
    return get_library_generator_workflow_service().clear_caches()


__all__ = [
    "LIBRARY_GENERATOR_WORKFLOW_SERVICE_COMPONENT",
    "LIBRARY_GENERATOR_WORKFLOW_SERVICE_SCHEMA_VERSION",
    "DEFAULT_WORKFLOW_CACHE_TTL_SECONDS",
    "DEFAULT_WORKFLOW_CACHE_MAX_ENTRIES",
    "WORKFLOW_ACTION_CONTEXT",
    "WORKFLOW_ACTION_OPTIONS",
    "WORKFLOW_ACTION_DRAFT",
    "WORKFLOW_ACTION_VALIDATE",
    "WORKFLOW_ACTION_PACKAGE_PLAN",
    "WORKFLOW_ACTION_DOWNLOAD",
    "WORKFLOW_ACTION_SAVE",
    "WORKFLOW_ACTION_PERSIST_DRAFT",
    "WORKFLOW_ACTION_PUBLISH_PREPARE",
    "WORKFLOW_ACTION_PUBLISH",
    "WORKFLOW_ACTION_SYNC",
    "SUPPORTED_WORKFLOW_ACTIONS",
    "WRITE_ACTIONS",
    "GeneratorWorkflowStatus",
    "GeneratorWorkflowMode",
    "LibraryGeneratorWorkflowRequest",
    "GeneratorWorkflowStep",
    "GeneratorWorkflowResult",
    "normalize_workflow_action",
    "normalize_workflow_mode",
    "LibraryGeneratorWorkflowService",
    "get_library_generator_workflow_service",
    "run_generator_workflow",
    "run_generator_workflow_payload",
    "create_generator_draft_payload",
    "validate_generator_payload",
    "build_generator_package_plan",
    "prepare_generator_download",
    "save_generator_source_package",
    "create_generator_persistent_draft",
    "prepare_generator_publish",
    "get_library_generator_workflow_service_health",
    "assert_library_generator_workflow_service_ready",
    "clear_library_generator_workflow_service_caches",
]