# src/library/services/library_generator_diagnostics_service.py
from __future__ import annotations

"""
Diagnostics service for the VPLIB generator context integration.

This service checks whether the central generator context infrastructure is
usable for the Create/Draft/Validate/Package-Plan/Save pipeline.

Scope:
- checks importability
- checks context service health
- checks minimal context creation
- checks real context creation
- checks create-options payload
- checks frontend context payload
- checks route contract
- checks payload contract
- checks definition/taxonomy/upload sections
- checks capabilities
- checks cache behavior

Intentional boundaries:
- no Flask imports
- no SQLAlchemy imports
- no direct repository calls
- no migrations
- no db.create_all()
- no package/source writes
- no HTTP calls to local routes

This is not a package validator. It validates the generator integration
surface, not one concrete VPLIB package.
"""

import copy
import threading
import time
import traceback
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Callable, Dict, Iterable, List, Mapping, Optional, Sequence, Tuple

try:
    from ..domain.generator_context import (
        DEFAULT_GENERATOR_ROUTES,
        DEFAULT_INVENTORY_KEY,
        DEFAULT_USER_ID,
        GENERATOR_CONTEXT_SCHEMA_VERSION,
        GeneratorContext,
        GeneratorContextDiagnostics,
        GeneratorContextIssue,
        GeneratorContextIssueSeverity,
        GeneratorContextMemoryCache,
        GeneratorContextSection,
        GeneratorContextSource,
        GeneratorContextStatus,
        build_minimal_generator_context,
        normalize_key,
        safe_bool,
        safe_deepcopy,
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
        get_generator_context_builder_health,
    )
    from .library_generator_context_service import (
        LibraryGeneratorContextRequest,
        LibraryGeneratorContextService,
        get_library_generator_context_service,
        get_library_generator_context_service_health,
    )
except Exception:  # pragma: no cover - fallback for alternate import roots
    from library.domain.generator_context import (
        DEFAULT_GENERATOR_ROUTES,
        DEFAULT_INVENTORY_KEY,
        DEFAULT_USER_ID,
        GENERATOR_CONTEXT_SCHEMA_VERSION,
        GeneratorContext,
        GeneratorContextDiagnostics,
        GeneratorContextIssue,
        GeneratorContextIssueSeverity,
        GeneratorContextMemoryCache,
        GeneratorContextSection,
        GeneratorContextSource,
        GeneratorContextStatus,
        build_minimal_generator_context,
        normalize_key,
        safe_bool,
        safe_deepcopy,
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
        get_generator_context_builder_health,
    )
    from library.services.library_generator_context_service import (
        LibraryGeneratorContextRequest,
        LibraryGeneratorContextService,
        get_library_generator_context_service,
        get_library_generator_context_service_health,
    )


LIBRARY_GENERATOR_DIAGNOSTICS_SERVICE_COMPONENT = "library.services.library_generator_diagnostics_service"
LIBRARY_GENERATOR_DIAGNOSTICS_SERVICE_SCHEMA_VERSION = "library_generator_diagnostics_service.v1"

DEFAULT_DIAGNOSTICS_CACHE_TTL_SECONDS = 15
DEFAULT_DIAGNOSTICS_CACHE_MAX_ENTRIES = 64

REQUIRED_ROUTE_KEYS = [
    "create_health",
    "create_options",
    "create_context",
    "create_draft",
    "create_validate",
    "create_package_plan",
    "create_download",
    "create_save",
]

REQUIRED_PAYLOAD_CONTRACT_SECTIONS = [
    "identity",
    "taxonomy",
    "variables",
    "geometry",
    "technical",
    "uploads",
]

DEFAULT_CHECK_ORDER = [
    "imports",
    "context_service_health",
    "builder_health",
    "minimal_context",
    "real_context",
    "route_contract",
    "payload_contract",
    "create_options",
    "frontend_context",
    "definitions_context",
    "taxonomy_context",
    "upload_context",
    "capabilities",
    "cache",
]

OPTIONAL_CHECK_ORDER = [
    "files_context",
    "draft_context",
    "published_context",
    "builder_modes",
]


class DiagnosticCheckStatus(str, Enum):
    UNKNOWN = "unknown"
    SKIPPED = "skipped"
    PASSED = "passed"
    WARNING = "warning"
    FAILED = "failed"
    ERROR = "error"

    def __str__(self) -> str:
        return self.value


@dataclass
class LibraryGeneratorDiagnosticsRequest:
    """
    Request object for diagnostics.

    This is an internal request object, not an HTTP request.
    """

    user_id: Optional[int] = DEFAULT_USER_ID
    inventory_key: str = DEFAULT_INVENTORY_KEY
    context_request: Dict[str, Any] = field(default_factory=dict)

    checks: List[str] = field(default_factory=list)
    include_optional: bool = False
    include_payloads: bool = False
    include_tracebacks: bool = False
    include_cache: bool = True
    check_dependencies: bool = True

    force_refresh: bool = False
    prefer_cache: bool = True
    cache_ttl_seconds: int = DEFAULT_DIAGNOSTICS_CACHE_TTL_SECONDS

    metadata: Dict[str, Any] = field(default_factory=dict)

    @classmethod
    def from_mapping(cls, value: Any = None) -> "LibraryGeneratorDiagnosticsRequest":
        data = safe_mapping(value)

        user_id = safe_int(data.get("user_id"), DEFAULT_USER_ID)
        inventory_key = normalize_key(data.get("inventory_key"), DEFAULT_INVENTORY_KEY)

        raw_context_request = safe_mapping(
            data.get("context_request")
            or data.get("generator_context_request")
            or data.get("request")
        )

        if not raw_context_request:
            raw_context_request = {
                "user_id": user_id,
                "inventory_key": inventory_key,
            }

        raw_checks = safe_list(data.get("checks") or data.get("check_keys"))
        checks = [normalize_key(item) for item in raw_checks if normalize_key(item)]

        return cls(
            user_id=user_id,
            inventory_key=inventory_key,
            context_request=raw_context_request,
            checks=checks,
            include_optional=safe_bool(data.get("include_optional"), False),
            include_payloads=safe_bool(data.get("include_payloads"), False),
            include_tracebacks=safe_bool(data.get("include_tracebacks"), False),
            include_cache=safe_bool(data.get("include_cache"), True),
            check_dependencies=safe_bool(data.get("check_dependencies"), True),
            force_refresh=safe_bool(data.get("force_refresh") or data.get("refresh"), False),
            prefer_cache=safe_bool(data.get("prefer_cache"), True),
            cache_ttl_seconds=max(
                0,
                int(safe_int(data.get("cache_ttl_seconds"), DEFAULT_DIAGNOSTICS_CACHE_TTL_SECONDS) or 0),
            ),
            metadata=safe_mapping(data.get("metadata") or data.get("meta")),
        )

    def to_dict(self) -> Dict[str, Any]:
        return to_json_compatible(self)

    def cache_key(self) -> str:
        payload = self.to_dict()
        payload["force_refresh"] = False
        payload["prefer_cache"] = True
        return stable_hash(payload, prefix="library_generator_diagnostics_request")


@dataclass
class DiagnosticCheckResult:
    key: str
    label: str = ""
    status: DiagnosticCheckStatus = DiagnosticCheckStatus.UNKNOWN
    ok: bool = False
    required: bool = False
    skipped: bool = False
    duration_ms: Optional[int] = None
    issues: List[GeneratorContextIssue] = field(default_factory=list)
    payload: Dict[str, Any] = field(default_factory=dict)
    error: str = ""
    traceback: str = ""
    checked_at: str = field(default_factory=utc_now_iso)
    metadata: Dict[str, Any] = field(default_factory=dict)

    @property
    def warning_count(self) -> int:
        return len(
            [
                issue
                for issue in self.issues
                if issue.severity == GeneratorContextIssueSeverity.WARNING
            ]
        )

    @property
    def error_count(self) -> int:
        return len(
            [
                issue
                for issue in self.issues
                if issue.severity == GeneratorContextIssueSeverity.ERROR
            ]
        )

    @property
    def fatal_count(self) -> int:
        return len(
            [
                issue
                for issue in self.issues
                if issue.severity == GeneratorContextIssueSeverity.FATAL
            ]
        )

    @property
    def blocking_count(self) -> int:
        return len([issue for issue in self.issues if issue.blocking])

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

    def refresh_status(self) -> None:
        if self.skipped:
            self.status = DiagnosticCheckStatus.SKIPPED
            self.ok = not self.required
            return

        if self.error or self.fatal_count > 0:
            self.status = DiagnosticCheckStatus.ERROR
            self.ok = False
            return

        if self.error_count > 0:
            self.status = DiagnosticCheckStatus.FAILED
            self.ok = False
            return

        if self.warning_count > 0:
            self.status = DiagnosticCheckStatus.WARNING
            self.ok = True
            return

        if self.status == DiagnosticCheckStatus.UNKNOWN:
            self.status = DiagnosticCheckStatus.PASSED

        self.ok = self.status in {
            DiagnosticCheckStatus.PASSED,
            DiagnosticCheckStatus.WARNING,
        }

    def to_dict(self, include_payload: bool = True, include_traceback: bool = False) -> Dict[str, Any]:
        payload = {
            "key": self.key,
            "label": self.label,
            "status": self.status.value,
            "ok": self.ok,
            "required": self.required,
            "skipped": self.skipped,
            "duration_ms": self.duration_ms,
            "checked_at": self.checked_at,
            "issue_count": len(self.issues),
            "warning_count": self.warning_count,
            "error_count": self.error_count,
            "fatal_count": self.fatal_count,
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
class GeneratorDiagnosticsReport:
    schema_version: str = LIBRARY_GENERATOR_DIAGNOSTICS_SERVICE_SCHEMA_VERSION
    component: str = LIBRARY_GENERATOR_DIAGNOSTICS_SERVICE_COMPONENT
    status: GeneratorContextStatus = GeneratorContextStatus.UNKNOWN
    ok: bool = False
    request: LibraryGeneratorDiagnosticsRequest = field(default_factory=LibraryGeneratorDiagnosticsRequest)
    checks: List[DiagnosticCheckResult] = field(default_factory=list)
    diagnostics: GeneratorContextDiagnostics = field(default_factory=GeneratorContextDiagnostics)
    generated_at: str = field(default_factory=utc_now_iso)
    duration_ms: Optional[int] = None
    cache_key: str = ""
    cache_hit: bool = False
    cache_stale: bool = False
    metadata: Dict[str, Any] = field(default_factory=dict)

    @property
    def check_count(self) -> int:
        return len(self.checks)

    @property
    def passed_count(self) -> int:
        return len([check for check in self.checks if check.status == DiagnosticCheckStatus.PASSED])

    @property
    def warning_count(self) -> int:
        return len([check for check in self.checks if check.status == DiagnosticCheckStatus.WARNING])

    @property
    def failed_count(self) -> int:
        return len(
            [
                check
                for check in self.checks
                if check.status in {DiagnosticCheckStatus.FAILED, DiagnosticCheckStatus.ERROR}
            ]
        )

    @property
    def skipped_count(self) -> int:
        return len([check for check in self.checks if check.status == DiagnosticCheckStatus.SKIPPED])

    @property
    def required_failed_count(self) -> int:
        return len([check for check in self.checks if check.required and not check.ok])

    @property
    def blocking_count(self) -> int:
        return self.required_failed_count + self.diagnostics.blocking_count

    def refresh(self) -> None:
        self.diagnostics.refresh()

        if self.required_failed_count > 0 or self.diagnostics.blocking_count > 0:
            self.status = GeneratorContextStatus.INVALID
            self.ok = False
            return

        if self.failed_count > 0:
            self.status = GeneratorContextStatus.PARTIAL
            self.ok = True
            return

        if self.warning_count > 0:
            self.status = GeneratorContextStatus.PARTIAL
            self.ok = True
            return

        if self.checks:
            self.status = GeneratorContextStatus.READY
            self.ok = True
            return

        self.status = GeneratorContextStatus.UNKNOWN
        self.ok = False

    def to_dict(self, include_payloads: Optional[bool] = None, include_tracebacks: Optional[bool] = None) -> Dict[str, Any]:
        include_payloads = self.request.include_payloads if include_payloads is None else include_payloads
        include_tracebacks = self.request.include_tracebacks if include_tracebacks is None else include_tracebacks

        self.refresh()

        return {
            "ok": self.ok,
            "status": self.status.value,
            "component": self.component,
            "schema_version": self.schema_version,
            "context_schema_version": GENERATOR_CONTEXT_SCHEMA_VERSION,
            "generated_at": self.generated_at,
            "duration_ms": self.duration_ms,
            "cache_key": self.cache_key,
            "cache_hit": self.cache_hit,
            "cache_stale": self.cache_stale,
            "summary": {
                "check_count": self.check_count,
                "passed_count": self.passed_count,
                "warning_count": self.warning_count,
                "failed_count": self.failed_count,
                "skipped_count": self.skipped_count,
                "required_failed_count": self.required_failed_count,
                "blocking_count": self.blocking_count,
            },
            "request": self.request.to_dict(),
            "checks": [
                check.to_dict(
                    include_payload=include_payloads,
                    include_traceback=include_tracebacks,
                )
                for check in self.checks
            ],
            "diagnostics": self.diagnostics.to_dict(),
            "metadata": to_json_compatible(self.metadata),
        }


@dataclass
class DiagnosticCheckSpec:
    key: str
    label: str
    required: bool
    runner: Callable[["LibraryGeneratorDiagnosticsService", LibraryGeneratorDiagnosticsRequest], DiagnosticCheckResult]


def _traceback_text() -> str:
    try:
        return traceback.format_exc(limit=12)
    except Exception:
        return ""


def _status_value(value: Any) -> str:
    if isinstance(value, Enum):
        return safe_str(value.value, "unknown")
    return normalize_key(value, "unknown")


def _safe_payload(value: Any) -> Dict[str, Any]:
    payload = to_json_compatible(value)
    return payload if isinstance(payload, dict) else {"value": payload}


def _check_ok_payload(payload: Mapping[str, Any]) -> bool:
    if "ok" in payload:
        return safe_bool(payload.get("ok"), False)
    status = normalize_key(payload.get("status"), "ready")
    return status not in {"error", "invalid", "unavailable"}


def _new_check(key: str, label: str, required: bool) -> DiagnosticCheckResult:
    return DiagnosticCheckResult(
        key=normalize_key(key),
        label=label,
        required=required,
        status=DiagnosticCheckStatus.UNKNOWN,
    )


def _issue_from_exception(
    code: str,
    message: str,
    exc: Exception,
    section: GeneratorContextSection = GeneratorContextSection.DIAGNOSTICS,
) -> GeneratorContextIssue:
    return GeneratorContextIssue.error(
        code=code,
        message=message,
        section=section,
        error=safe_str(exc),
        exception_type=type(exc).__name__,
    )


class LibraryGeneratorDiagnosticsService:
    """
    Diagnostics facade for the generator context integration.

    It consumes `LibraryGeneratorContextService` and `GeneratorContextBuilder`
    and reports whether the integration surface is ready enough for the next
    generator workflow steps.
    """

    def __init__(
        self,
        context_service: Optional[LibraryGeneratorContextService] = None,
        builder: Optional[GeneratorContextBuilder] = None,
        cache: Optional[GeneratorContextMemoryCache] = None,
        default_ttl_seconds: int = DEFAULT_DIAGNOSTICS_CACHE_TTL_SECONDS,
    ) -> None:
        self.context_service = context_service or get_library_generator_context_service()
        self.builder = builder or get_default_generator_context_builder()
        self.cache = cache or GeneratorContextMemoryCache(
            default_ttl_seconds=default_ttl_seconds,
            max_entries=DEFAULT_DIAGNOSTICS_CACHE_MAX_ENTRIES,
            name="library_generator_diagnostics_service_cache",
        )
        self.default_ttl_seconds = max(0, int(default_ttl_seconds))
        self._lock = threading.RLock()

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def run_diagnostics(
        self,
        request: Any = None,
        force_refresh: Optional[bool] = None,
        use_cache: Optional[bool] = None,
    ) -> GeneratorDiagnosticsReport:
        parsed_request = self.normalize_request(request)

        if force_refresh is not None:
            parsed_request.force_refresh = bool(force_refresh)
        if use_cache is not None:
            parsed_request.prefer_cache = bool(use_cache)

        cache_key = parsed_request.cache_key()

        if parsed_request.force_refresh or not parsed_request.prefer_cache:
            return self._run_diagnostics_uncached(parsed_request, cache_key=cache_key)

        cache_result = try_cache_get_or_set(
            key=cache_key,
            factory=lambda: self._run_diagnostics_uncached(parsed_request, cache_key=cache_key),
            ttl_seconds=parsed_request.cache_ttl_seconds,
            cache=self.cache,
            allow_stale_on_error=True,
            fallback=self._fallback_report(parsed_request, cache_key=cache_key),
            metadata={
                "component": LIBRARY_GENERATOR_DIAGNOSTICS_SERVICE_COMPONENT,
            },
        )

        report = cache_result.value
        if not isinstance(report, GeneratorDiagnosticsReport):
            report = self._fallback_report(parsed_request, cache_key=cache_key)

        report.cache_key = cache_key
        report.cache_hit = cache_result.hit
        report.cache_stale = cache_result.stale

        if cache_result.error:
            report.diagnostics.add_warning(
                "diagnostics_cache_warning",
                "Diagnostics cache returned a warning.",
                GeneratorContextSection.DIAGNOSTICS,
                error=cache_result.error,
            )
            report.refresh()

        return report

    def get_payload(
        self,
        request: Any = None,
        force_refresh: Optional[bool] = None,
        use_cache: Optional[bool] = None,
    ) -> Dict[str, Any]:
        return self.run_diagnostics(
            request=request,
            force_refresh=force_refresh,
            use_cache=use_cache,
        ).to_dict()

    def get_health(
        self,
        include_cache: bool = True,
        check_context_service: bool = True,
    ) -> Dict[str, Any]:
        diagnostics = GeneratorContextDiagnostics()

        try:
            minimal_request = LibraryGeneratorDiagnosticsRequest(
                checks=["imports", "minimal_context"],
                include_payloads=False,
                include_tracebacks=False,
                include_cache=include_cache,
                check_dependencies=False,
                prefer_cache=False,
                force_refresh=True,
            )
            report = self.run_diagnostics(minimal_request, force_refresh=True, use_cache=False)
            if not report.ok:
                diagnostics.add_warning(
                    "diagnostics_selftest_partial",
                    "Diagnostics selftest completed with warnings.",
                    GeneratorContextSection.DIAGNOSTICS,
                    report_status=report.status.value,
                )
        except Exception as exc:
            diagnostics.add_error(
                "diagnostics_selftest_failed",
                "Diagnostics selftest failed.",
                GeneratorContextSection.DIAGNOSTICS,
                error=safe_str(exc),
            )

        context_service_health: Dict[str, Any] = {}
        if check_context_service:
            try:
                context_service_health = self.context_service.get_health(
                    check_dependencies=False,
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

        diagnostics.refresh()

        payload = {
            "ok": diagnostics.blocking_count == 0,
            "status": diagnostics.status.value,
            "component": LIBRARY_GENERATOR_DIAGNOSTICS_SERVICE_COMPONENT,
            "schema_version": LIBRARY_GENERATOR_DIAGNOSTICS_SERVICE_SCHEMA_VERSION,
            "context_schema_version": GENERATOR_CONTEXT_SCHEMA_VERSION,
            "checked_at": utc_now_iso(),
            "diagnostics": diagnostics.to_dict(),
            "context_service": context_service_health,
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

    def assert_ready(self, require_context_service: bool = False) -> bool:
        health = self.get_health(
            include_cache=False,
            check_context_service=require_context_service,
        )
        if not health.get("ok"):
            raise RuntimeError(f"{LIBRARY_GENERATOR_DIAGNOSTICS_SERVICE_COMPONENT} is not ready: {health}")
        return True

    def clear_caches(self) -> Dict[str, Any]:
        cleared = self.cache.clear()

        context_cleared: Dict[str, Any] = {}
        try:
            context_cleared = self.context_service.clear_caches()
        except Exception as exc:
            context_cleared = {
                "ok": False,
                "error": safe_str(exc),
            }

        builder_cleared = 0
        try:
            if self.builder.cache is not None:
                builder_cleared = self.builder.cache.clear()
        except Exception:
            builder_cleared = 0

        return {
            "ok": True,
            "component": LIBRARY_GENERATOR_DIAGNOSTICS_SERVICE_COMPONENT,
            "cleared_at": utc_now_iso(),
            "cleared": {
                "diagnostics_cache": cleared,
                "context_service": context_cleared,
                "builder_cache": builder_cleared,
            },
        }

    # ------------------------------------------------------------------
    # Request / check selection
    # ------------------------------------------------------------------

    def normalize_request(self, request: Any = None) -> LibraryGeneratorDiagnosticsRequest:
        if isinstance(request, LibraryGeneratorDiagnosticsRequest):
            return request
        return LibraryGeneratorDiagnosticsRequest.from_mapping(request)

    def get_check_specs(self, include_optional: bool = False) -> Dict[str, DiagnosticCheckSpec]:
        specs = {
            "imports": DiagnosticCheckSpec(
                key="imports",
                label="Imports and module boundaries",
                required=True,
                runner=LibraryGeneratorDiagnosticsService.check_imports,
            ),
            "context_service_health": DiagnosticCheckSpec(
                key="context_service_health",
                label="Generator context service health",
                required=True,
                runner=LibraryGeneratorDiagnosticsService.check_context_service_health,
            ),
            "builder_health": DiagnosticCheckSpec(
                key="builder_health",
                label="Generator context builder health",
                required=True,
                runner=LibraryGeneratorDiagnosticsService.check_builder_health,
            ),
            "minimal_context": DiagnosticCheckSpec(
                key="minimal_context",
                label="Minimal context construction",
                required=True,
                runner=LibraryGeneratorDiagnosticsService.check_minimal_context,
            ),
            "real_context": DiagnosticCheckSpec(
                key="real_context",
                label="Service-backed context construction",
                required=True,
                runner=LibraryGeneratorDiagnosticsService.check_real_context,
            ),
            "route_contract": DiagnosticCheckSpec(
                key="route_contract",
                label="Create/generator route contract",
                required=True,
                runner=LibraryGeneratorDiagnosticsService.check_route_contract,
            ),
            "payload_contract": DiagnosticCheckSpec(
                key="payload_contract",
                label="Create payload contract",
                required=True,
                runner=LibraryGeneratorDiagnosticsService.check_payload_contract,
            ),
            "create_options": DiagnosticCheckSpec(
                key="create_options",
                label="Create options payload",
                required=True,
                runner=LibraryGeneratorDiagnosticsService.check_create_options,
            ),
            "frontend_context": DiagnosticCheckSpec(
                key="frontend_context",
                label="Frontend context payload",
                required=True,
                runner=LibraryGeneratorDiagnosticsService.check_frontend_context,
            ),
            "definitions_context": DiagnosticCheckSpec(
                key="definitions_context",
                label="Definitions context",
                required=False,
                runner=LibraryGeneratorDiagnosticsService.check_definitions_context,
            ),
            "taxonomy_context": DiagnosticCheckSpec(
                key="taxonomy_context",
                label="Taxonomy context",
                required=False,
                runner=LibraryGeneratorDiagnosticsService.check_taxonomy_context,
            ),
            "upload_context": DiagnosticCheckSpec(
                key="upload_context",
                label="Upload constraints context",
                required=False,
                runner=LibraryGeneratorDiagnosticsService.check_upload_context,
            ),
            "capabilities": DiagnosticCheckSpec(
                key="capabilities",
                label="Generator capabilities",
                required=False,
                runner=LibraryGeneratorDiagnosticsService.check_capabilities,
            ),
            "cache": DiagnosticCheckSpec(
                key="cache",
                label="Cache behavior",
                required=False,
                runner=LibraryGeneratorDiagnosticsService.check_cache,
            ),
        }

        if include_optional:
            specs.update(
                {
                    "files_context": DiagnosticCheckSpec(
                        key="files_context",
                        label="File metadata context",
                        required=False,
                        runner=LibraryGeneratorDiagnosticsService.check_files_context,
                    ),
                    "draft_context": DiagnosticCheckSpec(
                        key="draft_context",
                        label="Draft context",
                        required=False,
                        runner=LibraryGeneratorDiagnosticsService.check_draft_context,
                    ),
                    "published_context": DiagnosticCheckSpec(
                        key="published_context",
                        label="Published item context",
                        required=False,
                        runner=LibraryGeneratorDiagnosticsService.check_published_context,
                    ),
                    "builder_modes": DiagnosticCheckSpec(
                        key="builder_modes",
                        label="Builder modes",
                        required=False,
                        runner=LibraryGeneratorDiagnosticsService.check_builder_modes,
                    ),
                }
            )

        return specs

    def select_check_keys(self, request: LibraryGeneratorDiagnosticsRequest) -> List[str]:
        specs = self.get_check_specs(include_optional=request.include_optional)

        if request.checks:
            return [key for key in request.checks if key in specs]

        keys = list(DEFAULT_CHECK_ORDER)
        if request.include_optional:
            keys.extend(OPTIONAL_CHECK_ORDER)

        return [key for key in keys if key in specs]

    # ------------------------------------------------------------------
    # Main diagnostics execution
    # ------------------------------------------------------------------

    def _run_diagnostics_uncached(
        self,
        request: LibraryGeneratorDiagnosticsRequest,
        cache_key: str = "",
    ) -> GeneratorDiagnosticsReport:
        started = time.monotonic()
        report = GeneratorDiagnosticsReport(
            request=request,
            cache_key=cache_key,
            metadata={
                "component": LIBRARY_GENERATOR_DIAGNOSTICS_SERVICE_COMPONENT,
                "schema_version": LIBRARY_GENERATOR_DIAGNOSTICS_SERVICE_SCHEMA_VERSION,
            },
        )

        specs = self.get_check_specs(include_optional=request.include_optional)
        selected_keys = self.select_check_keys(request)

        for key in selected_keys:
            spec = specs.get(key)
            if spec is None:
                skipped = DiagnosticCheckResult(
                    key=key,
                    label=key,
                    required=False,
                    skipped=True,
                    status=DiagnosticCheckStatus.SKIPPED,
                    ok=True,
                )
                skipped.add_warning(
                    "diagnostic_check_unknown",
                    "Diagnostic check is unknown and was skipped.",
                    check_key=key,
                )
                report.checks.append(skipped)
                continue

            result = self._execute_check(spec, request)
            report.checks.append(result)

        missing_requested = [
            key
            for key in request.checks
            if key not in specs
        ]
        for key in missing_requested:
            issue = GeneratorContextIssue.warning(
                "requested_check_unavailable",
                "Requested diagnostic check is unavailable.",
                GeneratorContextSection.DIAGNOSTICS,
                check_key=key,
            )
            report.diagnostics.add_issue(issue)

        report.duration_ms = int((time.monotonic() - started) * 1000)
        report.refresh()
        return report

    def _execute_check(
        self,
        spec: DiagnosticCheckSpec,
        request: LibraryGeneratorDiagnosticsRequest,
    ) -> DiagnosticCheckResult:
        started = time.monotonic()
        result = _new_check(spec.key, spec.label, spec.required)

        try:
            result = spec.runner(self, request)
            if not isinstance(result, DiagnosticCheckResult):
                converted = _new_check(spec.key, spec.label, spec.required)
                converted.payload = _safe_payload(result)
                converted.ok = _check_ok_payload(converted.payload)
                converted.status = DiagnosticCheckStatus.PASSED if converted.ok else DiagnosticCheckStatus.FAILED
                result = converted

            result.key = spec.key
            result.label = spec.label
            result.required = spec.required
            result.duration_ms = int((time.monotonic() - started) * 1000)
            result.refresh_status()
            return result
        except Exception as exc:
            result.error = safe_str(exc)
            result.traceback = _traceback_text()
            result.duration_ms = int((time.monotonic() - started) * 1000)
            result.add_issue(
                _issue_from_exception(
                    code=f"{spec.key}_check_failed",
                    message=f"Diagnostic check failed: {spec.key}",
                    exc=exc,
                )
            )
            result.refresh_status()
            return result

    def _fallback_report(
        self,
        request: LibraryGeneratorDiagnosticsRequest,
        cache_key: str = "",
    ) -> GeneratorDiagnosticsReport:
        diagnostics = GeneratorContextDiagnostics()
        diagnostics.add_error(
            "diagnostics_report_fallback",
            "Diagnostics report fallback was used.",
            GeneratorContextSection.DIAGNOSTICS,
        )
        diagnostics.refresh()

        report = GeneratorDiagnosticsReport(
            status=GeneratorContextStatus.ERROR,
            ok=False,
            request=request,
            diagnostics=diagnostics,
            cache_key=cache_key,
        )
        report.refresh()
        return report

    # ------------------------------------------------------------------
    # Individual checks
    # ------------------------------------------------------------------

    def check_imports(self, request: LibraryGeneratorDiagnosticsRequest) -> DiagnosticCheckResult:
        result = _new_check("imports", "Imports and module boundaries", True)

        imported_symbols = {
            "GeneratorContext": GeneratorContext,
            "GeneratorContextBuilder": GeneratorContextBuilder,
            "LibraryGeneratorContextService": LibraryGeneratorContextService,
            "LibraryGeneratorContextRequest": LibraryGeneratorContextRequest,
        }

        missing = [
            name
            for name, value in imported_symbols.items()
            if value is None
        ]

        if missing:
            result.add_error(
                "required_symbols_missing",
                "Required generator-context symbols are missing.",
                missing=missing,
            )
        else:
            result.add_info(
                "required_symbols_available",
                "Required generator-context symbols are importable.",
                symbols=sorted(imported_symbols.keys()),
            )

        result.payload = {
            "component": LIBRARY_GENERATOR_DIAGNOSTICS_SERVICE_COMPONENT,
            "schema_version": LIBRARY_GENERATOR_DIAGNOSTICS_SERVICE_SCHEMA_VERSION,
            "context_schema_version": GENERATOR_CONTEXT_SCHEMA_VERSION,
            "symbols": sorted(imported_symbols.keys()),
            "missing": missing,
            "boundaries": {
                "flask_imports": False,
                "sqlalchemy_imports": False,
                "repository_imports": False,
                "http_calls": False,
            },
        }
        result.refresh_status()
        return result

    def check_context_service_health(self, request: LibraryGeneratorDiagnosticsRequest) -> DiagnosticCheckResult:
        result = _new_check("context_service_health", "Generator context service health", True)

        health = self.context_service.get_health(
            check_dependencies=request.check_dependencies,
            include_cache=request.include_cache,
        )

        result.payload = health

        if not safe_bool(health.get("ok"), False):
            result.add_error(
                "context_service_health_not_ok",
                "Generator context service health is not OK.",
                status=health.get("status"),
            )
        else:
            result.add_info(
                "context_service_health_ok",
                "Generator context service health is OK.",
                status=health.get("status"),
            )

        dependencies = safe_mapping(health.get("dependencies"))
        unavailable_required = [
            key
            for key in ("definitions", "taxonomy")
            if not safe_bool(safe_mapping(dependencies.get(key)).get("available"), True)
        ]

        if unavailable_required:
            result.add_warning(
                "context_service_required_dependencies_unavailable",
                "Some relevant context-service dependencies are unavailable.",
                dependencies=unavailable_required,
            )

        result.refresh_status()
        return result

    def check_builder_health(self, request: LibraryGeneratorDiagnosticsRequest) -> DiagnosticCheckResult:
        result = _new_check("builder_health", "Generator context builder health", True)

        health = get_generator_context_builder_health(include_cache=request.include_cache)
        result.payload = health

        if not safe_bool(health.get("ok"), False):
            result.add_error(
                "builder_health_not_ok",
                "Generator context builder health is not OK.",
                status=health.get("status"),
            )
        else:
            result.add_info(
                "builder_health_ok",
                "Generator context builder health is OK.",
                status=health.get("status"),
            )

        result.refresh_status()
        return result

    def check_minimal_context(self, request: LibraryGeneratorDiagnosticsRequest) -> DiagnosticCheckResult:
        result = _new_check("minimal_context", "Minimal context construction", True)

        context = build_minimal_generator_context(
            user_id=request.user_id,
            inventory_key=request.inventory_key,
            metadata={
                "diagnostics": True,
            },
        )

        payload = context.to_dict()
        context_hash = context.stable_hash()

        result.payload = {
            "context_uid": context.context_uid,
            "status": context.status.value,
            "hash": context_hash,
            "has_routes": bool(context.routes.routes),
            "has_user": context.user.user_id is not None,
            "issue_count": context.diagnostics.issue_count,
        }

        if not context.context_uid:
            result.add_error(
                "minimal_context_uid_missing",
                "Minimal context has no context_uid.",
            )

        if not context.routes.routes:
            result.add_error(
                "minimal_context_routes_missing",
                "Minimal context has no default routes.",
            )

        if context.user.user_id is None:
            result.add_warning(
                "minimal_context_user_missing",
                "Minimal context has no user_id.",
            )

        result.add_info(
            "minimal_context_created",
            "Minimal generator context was created.",
            status=context.status.value,
        )

        result.refresh_status()
        return result

    def check_real_context(self, request: LibraryGeneratorDiagnosticsRequest) -> DiagnosticCheckResult:
        result = _new_check("real_context", "Service-backed context construction", True)

        context_request = self._context_request_for_check(request)
        context = self.context_service.get_context(
            request=context_request,
            force_refresh=request.force_refresh,
            use_cache=request.prefer_cache,
        )

        minimum = context.validate_minimum(
            require_definitions=True,
            require_taxonomy=True,
            require_uploads=False,
            require_routes=True,
        )

        result.payload = {
            "context_uid": context.context_uid,
            "status": context.status.value,
            "ready": context.ready,
            "partial": context.partial,
            "section_status": {
                "routes": context.routes.status.value,
                "definitions": context.definitions.status.value,
                "taxonomy": context.taxonomy.status.value,
                "uploads": context.uploads.status.value,
                "files": context.files.status.value,
                "draft": context.draft.status.value,
                "published": context.published.status.value,
            },
            "counts": {
                "routes": len(context.routes.routes),
                "object_kinds": len(context.definitions.object_kinds),
                "family_profiles": len(context.definitions.family_profiles),
                "variant_profiles": len(context.definitions.variant_profiles),
                "taxonomy_nodes": len(context.taxonomy.nodes),
                "allowed_extensions": len(context.uploads.allowed_extensions),
                "document_types": len(context.uploads.document_types),
                "issues": context.diagnostics.issue_count,
                "minimum_blocking": minimum.blocking_count,
            },
            "minimum": minimum.to_dict(),
        }

        if context.status in {GeneratorContextStatus.ERROR, GeneratorContextStatus.INVALID}:
            result.add_error(
                "real_context_invalid",
                "Service-backed generator context is invalid.",
                status=context.status.value,
            )

        if minimum.blocking_count > 0:
            result.add_error(
                "real_context_minimum_failed",
                "Service-backed generator context failed minimum viability checks.",
                minimum=minimum.to_dict(),
            )

        if context.status == GeneratorContextStatus.PARTIAL:
            result.add_warning(
                "real_context_partial",
                "Service-backed generator context is partial.",
                section_status=result.payload["section_status"],
            )

        if context.status == GeneratorContextStatus.READY:
            result.add_info(
                "real_context_ready",
                "Service-backed generator context is ready.",
            )

        result.refresh_status()
        return result

    def check_route_contract(self, request: LibraryGeneratorDiagnosticsRequest) -> DiagnosticCheckResult:
        result = _new_check("route_contract", "Create/generator route contract", True)

        context = self._get_context_for_checks(request)
        route_keys = set(context.routes.routes.keys())

        missing = [
            key
            for key in REQUIRED_ROUTE_KEYS
            if key not in route_keys or not context.routes.get_path(key)
        ]

        result.payload = {
            "required": REQUIRED_ROUTE_KEYS,
            "available": sorted(route_keys),
            "missing": missing,
            "routes": {
                key: context.routes.get_path(key)
                for key in sorted(route_keys)
            },
        }

        if missing:
            result.add_error(
                "required_generator_routes_missing",
                "Required generator/create routes are missing.",
                missing=missing,
            )
        else:
            result.add_info(
                "required_generator_routes_available",
                "Required generator/create routes are available.",
            )

        duplicate_paths: Dict[str, List[str]] = {}
        for key in route_keys:
            path = context.routes.get_path(key)
            if not path:
                continue
            duplicate_paths.setdefault(path, []).append(key)

        duplicates = {
            path: keys
            for path, keys in duplicate_paths.items()
            if len(keys) > 1
        }

        if duplicates:
            result.add_warning(
                "generator_route_paths_duplicate",
                "Some generator route paths are used by multiple keys.",
                duplicates=duplicates,
            )

        result.refresh_status()
        return result

    def check_payload_contract(self, request: LibraryGeneratorDiagnosticsRequest) -> DiagnosticCheckResult:
        result = _new_check("payload_contract", "Create payload contract", True)

        context = self._get_context_for_checks(request)
        payload = self.builder.build_payload_contract_payload(context)

        stable_fields = safe_mapping(payload.get("stable_fields"))
        missing_sections = [
            section
            for section in REQUIRED_PAYLOAD_CONTRACT_SECTIONS
            if section not in stable_fields
        ]

        duplicate_guards = safe_list(payload.get("duplicate_formdata_guards"))

        result.payload = {
            "schema_version": payload.get("schema_version"),
            "required_fields": payload.get("required_fields"),
            "stable_sections": sorted(stable_fields.keys()),
            "missing_sections": missing_sections,
            "duplicate_formdata_guards": duplicate_guards,
            "payload_contract": payload if request.include_payloads else {},
        }

        if missing_sections:
            result.add_error(
                "payload_contract_sections_missing",
                "Payload contract is missing required sections.",
                missing=missing_sections,
            )

        if "object_kind" not in duplicate_guards:
            result.add_warning(
                "payload_contract_object_kind_guard_missing",
                "Payload contract does not explicitly guard against duplicate object_kind FormData.",
            )

        if not missing_sections:
            result.add_info(
                "payload_contract_available",
                "Payload contract is structurally available.",
            )

        result.refresh_status()
        return result

    def check_create_options(self, request: LibraryGeneratorDiagnosticsRequest) -> DiagnosticCheckResult:
        result = _new_check("create_options", "Create options payload", True)

        payload = self.context_service.get_create_options(
            request=self._context_request_for_check(request),
            build_options={
                "include_diagnostics": True,
                "include_raw_payloads": request.include_payloads,
                "compact": True,
            },
            force_refresh=request.force_refresh,
            use_cache=request.prefer_cache,
        )

        data = safe_mapping(payload.get("data"))
        object_kinds = safe_list(data.get("object_kinds"))
        family_profiles = safe_list(data.get("family_profiles"))
        variant_profiles = safe_list(data.get("variant_profiles"))
        taxonomy = safe_mapping(data.get("taxonomy"))
        uploads = safe_mapping(data.get("uploads"))

        result.payload = {
            "ok": payload.get("ok"),
            "status": payload.get("status"),
            "counts": {
                "object_kinds": len(object_kinds),
                "family_profiles": len(family_profiles),
                "variant_profiles": len(variant_profiles),
                "document_types": len(safe_list(data.get("document_types"))),
                "variables": len(safe_list(data.get("variables"))),
                "materials": len(safe_list(data.get("materials"))),
            },
            "has_taxonomy": bool(taxonomy),
            "has_uploads": bool(uploads),
            "payload": payload if request.include_payloads else {},
        }

        if not safe_bool(payload.get("ok"), False):
            result.add_error(
                "create_options_not_ok",
                "Create options payload is not OK.",
                status=payload.get("status"),
            )

        if not object_kinds:
            result.add_warning(
                "create_options_object_kinds_empty",
                "Create options contain no object kinds.",
            )

        if not family_profiles:
            result.add_warning(
                "create_options_family_profiles_empty",
                "Create options contain no family profiles.",
            )

        if not variant_profiles:
            result.add_warning(
                "create_options_variant_profiles_empty",
                "Create options contain no variant profiles.",
            )

        if not taxonomy:
            result.add_warning(
                "create_options_taxonomy_missing",
                "Create options contain no taxonomy block.",
            )

        if not uploads:
            result.add_warning(
                "create_options_uploads_missing",
                "Create options contain no uploads block.",
            )

        result.refresh_status()
        return result

    def check_frontend_context(self, request: LibraryGeneratorDiagnosticsRequest) -> DiagnosticCheckResult:
        result = _new_check("frontend_context", "Frontend context payload", True)

        payload = self.context_service.get_frontend_context(
            request=self._context_request_for_check(request),
            build_options={
                "include_diagnostics": True,
                "include_raw_payloads": request.include_payloads,
                "compact": True,
            },
            force_refresh=request.force_refresh,
            use_cache=request.prefer_cache,
        )

        data = safe_mapping(payload.get("data"))
        window_payload = safe_mapping(payload.get("window_payload"))
        api = safe_mapping(data.get("api"))
        options = safe_mapping(data.get("options"))
        payload_contract = safe_mapping(data.get("payload_contract"))

        result.payload = {
            "ok": payload.get("ok"),
            "status": payload.get("status"),
            "has_data": bool(data),
            "has_window_payload": bool(window_payload),
            "has_api": bool(api),
            "has_options": bool(options),
            "has_payload_contract": bool(payload_contract),
            "window_keys": sorted(window_payload.keys()),
            "payload": payload if request.include_payloads else {},
        }

        if not data:
            result.add_error(
                "frontend_context_data_missing",
                "Frontend context payload has no data block.",
            )

        if not window_payload:
            result.add_error(
                "frontend_context_window_payload_missing",
                "Frontend context payload has no window_payload block.",
            )

        for required_window_key in (
            "VectoplanCreateContext",
            "VectoplanCreateUploadConfig",
            "VectoplanDefinitionContext",
            "VectoplanTaxonomyContext",
        ):
            if required_window_key not in window_payload:
                result.add_warning(
                    "frontend_context_window_key_missing",
                    "Frontend context window payload is missing an expected key.",
                    window_key=required_window_key,
                )

        if not api:
            result.add_error(
                "frontend_context_api_missing",
                "Frontend context payload has no API block.",
            )

        if not payload_contract:
            result.add_error(
                "frontend_context_payload_contract_missing",
                "Frontend context payload has no payload contract.",
            )

        result.refresh_status()
        return result

    def check_definitions_context(self, request: LibraryGeneratorDiagnosticsRequest) -> DiagnosticCheckResult:
        result = _new_check("definitions_context", "Definitions context", False)

        context = self._get_context_for_checks(request)
        definitions = context.definitions

        result.payload = {
            "status": definitions.status.value,
            "source": definitions.source.value,
            "definitions_version": definitions.definitions_version,
            "counts": {
                "datasets": len(definitions.datasets),
                "variables": len(definitions.variables),
                "units": len(definitions.units),
                "materials": len(definitions.materials),
                "document_types": len(definitions.document_types),
                "object_kinds": len(definitions.object_kinds),
                "family_profiles": len(definitions.family_profiles),
                "variant_profiles": len(definitions.variant_profiles),
                "profile_bindings": len(definitions.profile_bindings),
            },
        }

        if definitions.status == GeneratorContextStatus.UNAVAILABLE:
            result.add_warning(
                "definitions_context_unavailable",
                "Definitions context is unavailable.",
            )
        elif definitions.status in {GeneratorContextStatus.ERROR, GeneratorContextStatus.INVALID}:
            result.add_error(
                "definitions_context_invalid",
                "Definitions context is invalid.",
                status=definitions.status.value,
            )
        else:
            result.add_info(
                "definitions_context_loaded",
                "Definitions context was loaded.",
                status=definitions.status.value,
            )

        if not definitions.object_kinds:
            result.add_warning(
                "definitions_object_kinds_empty",
                "Definitions context contains no object kinds.",
            )

        if not definitions.family_profiles:
            result.add_warning(
                "definitions_family_profiles_empty",
                "Definitions context contains no family profiles.",
            )

        if not definitions.variant_profiles:
            result.add_warning(
                "definitions_variant_profiles_empty",
                "Definitions context contains no variant profiles.",
            )

        result.refresh_status()
        return result

    def check_taxonomy_context(self, request: LibraryGeneratorDiagnosticsRequest) -> DiagnosticCheckResult:
        result = _new_check("taxonomy_context", "Taxonomy context", False)

        context = self._get_context_for_checks(request)
        taxonomy = context.taxonomy

        result.payload = {
            "status": taxonomy.status.value,
            "source": taxonomy.source.value,
            "user_id": taxonomy.user_id,
            "owner_scope": taxonomy.owner_scope,
            "selection": taxonomy.selection,
            "taxonomy_path": taxonomy.current_taxonomy_path,
            "counts": {
                "nodes": len(taxonomy.nodes),
                "tree_roots": len(taxonomy.tree),
                "create_options_keys": len(taxonomy.create_options),
            },
        }

        if taxonomy.status == GeneratorContextStatus.UNAVAILABLE:
            result.add_warning(
                "taxonomy_context_unavailable",
                "Taxonomy context is unavailable.",
            )
        elif taxonomy.status in {GeneratorContextStatus.ERROR, GeneratorContextStatus.INVALID}:
            result.add_error(
                "taxonomy_context_invalid",
                "Taxonomy context is invalid.",
                status=taxonomy.status.value,
            )
        else:
            result.add_info(
                "taxonomy_context_loaded",
                "Taxonomy context was loaded.",
                status=taxonomy.status.value,
            )

        if not taxonomy.tree and not taxonomy.nodes and not taxonomy.create_options:
            result.add_warning(
                "taxonomy_context_empty",
                "Taxonomy context contains no tree, nodes or create options.",
            )

        result.refresh_status()
        return result

    def check_upload_context(self, request: LibraryGeneratorDiagnosticsRequest) -> DiagnosticCheckResult:
        result = _new_check("upload_context", "Upload constraints context", False)

        context = self._get_context_for_checks(request)
        uploads = context.uploads

        result.payload = {
            "status": uploads.status.value,
            "source": uploads.source.value,
            "counts": {
                "allowed_extensions": len(uploads.allowed_extensions),
                "blocked_extensions": len(uploads.blocked_extensions),
                "allowed_mime_types": len(uploads.allowed_mime_types),
                "blocked_mime_types": len(uploads.blocked_mime_types),
                "document_types": len(uploads.document_types),
                "upload_groups": len(uploads.upload_groups),
            },
            "max_size_mb": uploads.max_size_mb,
            "storage_backends": uploads.storage_backends,
        }

        if uploads.status == GeneratorContextStatus.UNAVAILABLE:
            result.add_warning(
                "upload_context_unavailable",
                "Upload context is unavailable.",
            )
        elif uploads.status in {GeneratorContextStatus.ERROR, GeneratorContextStatus.INVALID}:
            result.add_error(
                "upload_context_invalid",
                "Upload context is invalid.",
                status=uploads.status.value,
            )
        else:
            result.add_info(
                "upload_context_loaded",
                "Upload context was loaded.",
                status=uploads.status.value,
            )

        if not uploads.allowed_extensions and not uploads.document_types:
            result.add_warning(
                "upload_context_constraints_empty",
                "Upload context contains no allowed extensions or document type rules.",
            )

        result.refresh_status()
        return result

    def check_capabilities(self, request: LibraryGeneratorDiagnosticsRequest) -> DiagnosticCheckResult:
        result = _new_check("capabilities", "Generator capabilities", False)

        context = self._get_context_for_checks(request)
        capabilities = context.capabilities.to_dict()

        result.payload = {
            "capabilities": capabilities,
            "supported_object_kinds": capabilities.get("supported_object_kinds", []),
            "supported_actions": capabilities.get("supported_actions", []),
        }

        for expected_action in (
            "context",
            "options",
            "draft",
            "validate",
            "package-plan",
            "download",
            "save",
        ):
            supported_actions = safe_list(capabilities.get("supported_actions"))
            if expected_action not in supported_actions:
                result.add_warning(
                    "capability_action_missing",
                    "Expected generator action is not listed as supported.",
                    action=expected_action,
                )

        if not safe_bool(capabilities.get("supports_context"), False):
            result.add_error(
                "capability_context_missing",
                "Generator capability supports_context is false.",
            )

        if not safe_bool(capabilities.get("supports_options"), False):
            result.add_error(
                "capability_options_missing",
                "Generator capability supports_options is false.",
            )

        result.refresh_status()
        return result

    def check_cache(self, request: LibraryGeneratorDiagnosticsRequest) -> DiagnosticCheckResult:
        result = _new_check("cache", "Cache behavior", False)

        key = stable_hash(
            {
                "component": LIBRARY_GENERATOR_DIAGNOSTICS_SERVICE_COMPONENT,
                "check": "cache",
                "request": request.to_dict(),
            },
            prefix="diagnostics_cache_check",
        )

        value = {
            "created_at": utc_now_iso(),
            "marker": key,
        }

        self.cache.set(key, value, ttl_seconds=10)
        loaded = self.cache.get(key)

        context_cache_stats = {}
        try:
            context_cache_stats = self.context_service.cache.stats()
        except Exception:
            context_cache_stats = {}

        builder_cache_stats = {}
        try:
            builder_cache_stats = self.builder.cache.stats() if self.builder.cache is not None else {}
        except Exception:
            builder_cache_stats = {}

        result.payload = {
            "cache_key": key,
            "loaded": loaded,
            "diagnostics_cache": self.cache.stats(),
            "context_cache": context_cache_stats,
            "builder_cache": builder_cache_stats,
        }

        if not isinstance(loaded, dict) or loaded.get("marker") != key:
            result.add_error(
                "diagnostics_cache_roundtrip_failed",
                "Diagnostics cache did not return the stored value.",
            )
        else:
            result.add_info(
                "diagnostics_cache_roundtrip_ok",
                "Diagnostics cache roundtrip succeeded.",
            )

        result.refresh_status()
        return result

    def check_files_context(self, request: LibraryGeneratorDiagnosticsRequest) -> DiagnosticCheckResult:
        result = _new_check("files_context", "File metadata context", False)

        context_request = self._context_request_for_check(request)
        context_request.include_files = True

        context = self.context_service.get_context(
            request=context_request,
            force_refresh=request.force_refresh,
            use_cache=request.prefer_cache,
        )

        files = context.files
        result.payload = {
            "status": files.status.value,
            "source": files.source.value,
            "counts": {
                "files": len(files.files),
                "versions": len(files.versions),
                "links": len(files.links),
                "contexts": len(files.context_files),
            },
        }

        if files.status == GeneratorContextStatus.UNAVAILABLE:
            result.add_warning(
                "files_context_unavailable",
                "Files context is unavailable.",
            )
        elif files.status in {GeneratorContextStatus.ERROR, GeneratorContextStatus.INVALID}:
            result.add_error(
                "files_context_invalid",
                "Files context is invalid.",
                status=files.status.value,
            )
        else:
            result.add_info(
                "files_context_loaded",
                "Files context was loaded.",
                status=files.status.value,
            )

        result.refresh_status()
        return result

    def check_draft_context(self, request: LibraryGeneratorDiagnosticsRequest) -> DiagnosticCheckResult:
        result = _new_check("draft_context", "Draft context", False)

        context_request = self._context_request_for_check(request)
        context_request.include_draft = True

        if not context_request.draft_ref:
            result.skipped = True
            result.add_warning(
                "draft_context_skipped_no_draft_ref",
                "Draft context check was skipped because no draft_ref was provided.",
            )
            result.refresh_status()
            return result

        context = self.context_service.get_context(
            request=context_request,
            force_refresh=request.force_refresh,
            use_cache=request.prefer_cache,
        )

        draft = context.draft
        result.payload = {
            "status": draft.status.value,
            "source": draft.source.value,
            "draft_ref": draft.draft_ref,
            "draft_uid": draft.draft_uid,
            "counts": {
                "variants": len(draft.variants),
                "assets": len(draft.assets),
                "documents": len(draft.documents),
                "validation_issues": len(draft.validation_issues),
            },
        }

        if draft.status == GeneratorContextStatus.UNAVAILABLE:
            result.add_warning(
                "draft_context_unavailable",
                "Draft context is unavailable.",
            )
        elif draft.status in {GeneratorContextStatus.ERROR, GeneratorContextStatus.INVALID}:
            result.add_error(
                "draft_context_invalid",
                "Draft context is invalid.",
                status=draft.status.value,
            )
        else:
            result.add_info(
                "draft_context_loaded",
                "Draft context was loaded.",
                status=draft.status.value,
            )

        result.refresh_status()
        return result

    def check_published_context(self, request: LibraryGeneratorDiagnosticsRequest) -> DiagnosticCheckResult:
        result = _new_check("published_context", "Published item context", False)

        context_request = self._context_request_for_check(request)
        context_request.include_published = True

        if not (context_request.item_ref or context_request.vplib_uid or context_request.family_id or context_request.package_id):
            result.skipped = True
            result.add_warning(
                "published_context_skipped_no_item_ref",
                "Published context check was skipped because no item_ref/vplib_uid/family_id/package_id was provided.",
            )
            result.refresh_status()
            return result

        context = self.context_service.get_context(
            request=context_request,
            force_refresh=request.force_refresh,
            use_cache=request.prefer_cache,
        )

        published = context.published
        result.payload = {
            "status": published.status.value,
            "source": published.source.value,
            "item_ref": published.item_ref,
            "vplib_uid": published.vplib_uid,
            "family_id": published.family_id,
            "package_id": published.package_id,
            "revision_hash": published.revision_hash,
            "counts": {
                "variants": len(published.variants),
                "assets": len(published.assets),
                "documents": len(published.documents),
            },
        }

        if published.status == GeneratorContextStatus.UNAVAILABLE:
            result.add_warning(
                "published_context_unavailable",
                "Published context is unavailable.",
            )
        elif published.status in {GeneratorContextStatus.ERROR, GeneratorContextStatus.INVALID}:
            result.add_error(
                "published_context_invalid",
                "Published context is invalid.",
                status=published.status.value,
            )
        else:
            result.add_info(
                "published_context_loaded",
                "Published context was loaded.",
                status=published.status.value,
            )

        result.refresh_status()
        return result

    def check_builder_modes(self, request: LibraryGeneratorDiagnosticsRequest) -> DiagnosticCheckResult:
        result = _new_check("builder_modes", "Builder modes", False)

        context = self._get_context_for_checks(request)
        modes = [
            GeneratorContextViewMode.PUBLIC,
            GeneratorContextViewMode.FRONTEND,
            GeneratorContextViewMode.OPTIONS,
            GeneratorContextViewMode.DIAGNOSTICS,
            GeneratorContextViewMode.HEALTH,
            GeneratorContextViewMode.TEST,
            GeneratorContextViewMode.COMPACT,
        ]

        mode_results: Dict[str, Any] = {}
        failed_modes: List[str] = []

        for mode in modes:
            try:
                build_result = self.builder.build(
                    context=context,
                    mode=mode,
                    options={
                        "include_diagnostics": True,
                        "include_raw_payloads": False,
                        "compact": True,
                    },
                    use_cache=False,
                )
                mode_results[mode.value] = {
                    "ok": build_result.ok,
                    "status": build_result.status,
                    "duration_ms": build_result.duration_ms,
                    "payload_keys": sorted(build_result.payload.keys()),
                }
                if not build_result.ok:
                    failed_modes.append(mode.value)
            except Exception as exc:
                failed_modes.append(mode.value)
                mode_results[mode.value] = {
                    "ok": False,
                    "error": safe_str(exc),
                }

        result.payload = {
            "modes": mode_results,
            "failed_modes": failed_modes,
        }

        if failed_modes:
            result.add_warning(
                "builder_modes_partial",
                "Some builder modes failed.",
                failed_modes=failed_modes,
            )
        else:
            result.add_info(
                "builder_modes_ok",
                "All builder modes produced payloads.",
            )

        result.refresh_status()
        return result

    # ------------------------------------------------------------------
    # Shared helpers
    # ------------------------------------------------------------------

    def _context_request_for_check(
        self,
        request: LibraryGeneratorDiagnosticsRequest,
    ) -> LibraryGeneratorContextRequest:
        payload = dict(request.context_request or {})
        payload.setdefault("user_id", request.user_id)
        payload.setdefault("inventory_key", request.inventory_key)
        payload.setdefault("include_definitions", True)
        payload.setdefault("include_taxonomy", True)
        payload.setdefault("include_uploads", True)
        payload.setdefault("include_routes", True)
        payload.setdefault("include_capabilities", True)
        payload.setdefault("include_vplib_health", True)
        payload.setdefault("force_refresh", request.force_refresh)
        payload.setdefault("prefer_cache", request.prefer_cache)
        return LibraryGeneratorContextRequest.from_mapping(payload)

    def _get_context_for_checks(
        self,
        request: LibraryGeneratorDiagnosticsRequest,
    ) -> GeneratorContext:
        return self.context_service.get_context(
            request=self._context_request_for_check(request),
            force_refresh=request.force_refresh,
            use_cache=request.prefer_cache,
        )


_DEFAULT_DIAGNOSTICS_SERVICE_LOCK = threading.RLock()
_DEFAULT_DIAGNOSTICS_SERVICE: Optional[LibraryGeneratorDiagnosticsService] = None


def get_library_generator_diagnostics_service(
    force_new: bool = False,
) -> LibraryGeneratorDiagnosticsService:
    global _DEFAULT_DIAGNOSTICS_SERVICE

    with _DEFAULT_DIAGNOSTICS_SERVICE_LOCK:
        if force_new or _DEFAULT_DIAGNOSTICS_SERVICE is None:
            _DEFAULT_DIAGNOSTICS_SERVICE = LibraryGeneratorDiagnosticsService()
        return _DEFAULT_DIAGNOSTICS_SERVICE


def run_generator_diagnostics(
    request: Any = None,
    force_refresh: Optional[bool] = None,
    use_cache: Optional[bool] = None,
) -> GeneratorDiagnosticsReport:
    return get_library_generator_diagnostics_service().run_diagnostics(
        request=request,
        force_refresh=force_refresh,
        use_cache=use_cache,
    )


def get_generator_diagnostics_payload(
    request: Any = None,
    force_refresh: Optional[bool] = None,
    use_cache: Optional[bool] = None,
) -> Dict[str, Any]:
    return get_library_generator_diagnostics_service().get_payload(
        request=request,
        force_refresh=force_refresh,
        use_cache=use_cache,
    )


def get_library_generator_diagnostics_service_health(
    include_cache: bool = True,
    check_context_service: bool = True,
) -> Dict[str, Any]:
    return get_library_generator_diagnostics_service().get_health(
        include_cache=include_cache,
        check_context_service=check_context_service,
    )


def assert_library_generator_diagnostics_service_ready(
    require_context_service: bool = False,
) -> bool:
    return get_library_generator_diagnostics_service().assert_ready(
        require_context_service=require_context_service,
    )


def clear_library_generator_diagnostics_service_caches() -> Dict[str, Any]:
    return get_library_generator_diagnostics_service().clear_caches()


__all__ = [
    "LIBRARY_GENERATOR_DIAGNOSTICS_SERVICE_COMPONENT",
    "LIBRARY_GENERATOR_DIAGNOSTICS_SERVICE_SCHEMA_VERSION",
    "DEFAULT_DIAGNOSTICS_CACHE_TTL_SECONDS",
    "DEFAULT_DIAGNOSTICS_CACHE_MAX_ENTRIES",
    "REQUIRED_ROUTE_KEYS",
    "REQUIRED_PAYLOAD_CONTRACT_SECTIONS",
    "DEFAULT_CHECK_ORDER",
    "OPTIONAL_CHECK_ORDER",
    "DiagnosticCheckStatus",
    "LibraryGeneratorDiagnosticsRequest",
    "DiagnosticCheckResult",
    "GeneratorDiagnosticsReport",
    "DiagnosticCheckSpec",
    "LibraryGeneratorDiagnosticsService",
    "get_library_generator_diagnostics_service",
    "run_generator_diagnostics",
    "get_generator_diagnostics_payload",
    "get_library_generator_diagnostics_service_health",
    "assert_library_generator_diagnostics_service_ready",
    "clear_library_generator_diagnostics_service_caches",
]