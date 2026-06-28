# src/library/services/library_generator_context_service.py
from __future__ import annotations

"""
Central read-only service facade for the VPLIB generator context.

This service is the first real integration point between the new central
Library/DB/API structure and the VPLIB generator.

Responsibilities:
- collect definition catalog data
- collect taxonomy/create taxonomy data
- collect upload constraints
- collect optional file metadata context
- collect optional draft context
- collect optional published item context
- collect VPLIB/create capabilities
- return a single `GeneratorContext`
- expose API/UI/read-model payloads via `generator_context_builder`

Intentional boundaries:
- no Flask imports
- no SQLAlchemy session usage
- no direct repository calls
- no migrations
- no db.create_all()
- no source/package writes
- no HTTP calls to local routes

The service uses lazy imports and defensive method probing because the
surrounding services are still evolving. Missing optional services result in
partial contexts with diagnostics instead of hard crashes.
"""

import importlib
import inspect
import threading
import time
import traceback
from dataclasses import dataclass, field
from types import ModuleType
from typing import Any, Callable, Dict, Iterable, List, Mapping, Optional, Sequence, Tuple

try:
    from ..domain.generator_context import (
        DEFAULT_GENERATOR_ROUTES,
        DEFAULT_INVENTORY_KEY,
        DEFAULT_USER_ID,
        GENERATOR_CONTEXT_SCHEMA_VERSION,
        GeneratorCapabilities,
        GeneratorContext,
        GeneratorContextDiagnostics,
        GeneratorContextIssue,
        GeneratorContextIssueSeverity,
        GeneratorContextMemoryCache,
        GeneratorContextSection,
        GeneratorContextSource,
        GeneratorContextStatus,
        GeneratorDefinitionContext,
        GeneratorDraftContext,
        GeneratorFileContext,
        GeneratorPublishedContext,
        GeneratorRouteContext,
        GeneratorTaxonomyContext,
        GeneratorUploadContext,
        GeneratorUserContext,
        build_minimal_generator_context,
        merge_mappings,
        normalize_key,
        normalize_owner_scope,
        normalize_slug,
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
        GeneratorContextBuilder,
        GeneratorContextBuildOptions,
        GeneratorContextBuildResult,
        GeneratorContextViewMode,
        build_generator_context_payload,
        get_default_generator_context_builder,
    )
except Exception:  # pragma: no cover - fallback for alternate import roots
    from library.domain.generator_context import (
        DEFAULT_GENERATOR_ROUTES,
        DEFAULT_INVENTORY_KEY,
        DEFAULT_USER_ID,
        GENERATOR_CONTEXT_SCHEMA_VERSION,
        GeneratorCapabilities,
        GeneratorContext,
        GeneratorContextDiagnostics,
        GeneratorContextIssue,
        GeneratorContextIssueSeverity,
        GeneratorContextMemoryCache,
        GeneratorContextSection,
        GeneratorContextSource,
        GeneratorContextStatus,
        GeneratorDefinitionContext,
        GeneratorDraftContext,
        GeneratorFileContext,
        GeneratorPublishedContext,
        GeneratorRouteContext,
        GeneratorTaxonomyContext,
        GeneratorUploadContext,
        GeneratorUserContext,
        build_minimal_generator_context,
        merge_mappings,
        normalize_key,
        normalize_owner_scope,
        normalize_slug,
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
        GeneratorContextBuilder,
        GeneratorContextBuildOptions,
        GeneratorContextBuildResult,
        GeneratorContextViewMode,
        build_generator_context_payload,
        get_default_generator_context_builder,
    )


LIBRARY_GENERATOR_CONTEXT_SERVICE_COMPONENT = "library.services.library_generator_context_service"
LIBRARY_GENERATOR_CONTEXT_SERVICE_SCHEMA_VERSION = "library_generator_context_service.v1"

DEFAULT_SERVICE_CACHE_TTL_SECONDS = 30
DEFAULT_SERVICE_CACHE_MAX_ENTRIES = 128

DEPENDENCY_DEFINITIONS = "definitions"
DEPENDENCY_TAXONOMY = "taxonomy"
DEPENDENCY_FILES = "files"
DEPENDENCY_DRAFTS = "drafts"
DEPENDENCY_PUBLISHED = "published"
DEPENDENCY_CREATE = "create"
DEPENDENCY_VPLIB = "vplib"

DEPENDENCY_KEYS = [
    DEPENDENCY_DEFINITIONS,
    DEPENDENCY_TAXONOMY,
    DEPENDENCY_FILES,
    DEPENDENCY_DRAFTS,
    DEPENDENCY_PUBLISHED,
    DEPENDENCY_CREATE,
    DEPENDENCY_VPLIB,
]


@dataclass
class LibraryGeneratorContextRequest:
    """
    Request object for building a generator context.

    This is not an HTTP request. It is an internal normalized request that can
    be built from HTTP query params, JSON payloads, tests or service calls.
    """

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

    include_definitions: bool = True
    include_taxonomy: bool = True
    include_uploads: bool = True
    include_files: bool = False
    include_draft: bool = False
    include_published: bool = False
    include_routes: bool = True
    include_capabilities: bool = True
    include_vplib_health: bool = True

    force_refresh: bool = False
    prefer_cache: bool = True
    cache_ttl_seconds: int = DEFAULT_SERVICE_CACHE_TTL_SECONDS

    request_payload: Dict[str, Any] = field(default_factory=dict)
    route_payload: Dict[str, Any] = field(default_factory=dict)
    metadata: Dict[str, Any] = field(default_factory=dict)

    @classmethod
    def from_mapping(cls, value: Any = None) -> "LibraryGeneratorContextRequest":
        data = safe_mapping(value)

        user_id = safe_int(data.get("user_id"), DEFAULT_USER_ID)
        owner_scope = normalize_owner_scope(user_id=user_id, owner_scope=data.get("owner_scope"))

        selection = safe_mapping(data.get("selection"))
        domain = normalize_slug(data.get("domain") or selection.get("domain"))
        category = normalize_slug(data.get("category") or selection.get("category"))
        subcategory = normalize_slug(data.get("subcategory") or selection.get("subcategory"))
        taxonomy_path = normalize_taxonomy_path(
            domain=domain,
            category=category,
            subcategory=subcategory,
            path=data.get("taxonomy_path") or data.get("path") or selection.get("taxonomy_path"),
        )

        draft_ref = safe_str(
            data.get("draft_ref")
            or data.get("draft_id")
            or data.get("draft_uid")
            or data.get("draft_key"),
            "",
        )

        item_ref = safe_str(
            data.get("item_ref")
            or data.get("item_id")
            or data.get("family_ref")
            or data.get("family_db_id"),
            "",
        )

        return cls(
            user_id=user_id,
            owner_scope=owner_scope,
            inventory_key=normalize_key(data.get("inventory_key"), DEFAULT_INVENTORY_KEY),
            domain=domain,
            category=category,
            subcategory=subcategory,
            taxonomy_path=taxonomy_path,
            draft_ref=draft_ref,
            item_ref=item_ref,
            vplib_uid=safe_str(data.get("vplib_uid"), ""),
            family_id=safe_str(data.get("family_id"), ""),
            package_id=safe_str(data.get("package_id"), ""),
            include_definitions=safe_bool(data.get("include_definitions"), True),
            include_taxonomy=safe_bool(data.get("include_taxonomy"), True),
            include_uploads=safe_bool(data.get("include_uploads"), True),
            include_files=safe_bool(data.get("include_files"), False),
            include_draft=safe_bool(data.get("include_draft"), bool(draft_ref)),
            include_published=safe_bool(
                data.get("include_published"),
                bool(item_ref or data.get("vplib_uid") or data.get("family_id") or data.get("package_id")),
            ),
            include_routes=safe_bool(data.get("include_routes"), True),
            include_capabilities=safe_bool(data.get("include_capabilities"), True),
            include_vplib_health=safe_bool(data.get("include_vplib_health"), True),
            force_refresh=safe_bool(data.get("force_refresh") or data.get("refresh"), False),
            prefer_cache=safe_bool(data.get("prefer_cache"), True),
            cache_ttl_seconds=max(
                0,
                int(safe_int(data.get("cache_ttl_seconds"), DEFAULT_SERVICE_CACHE_TTL_SECONDS) or 0),
            ),
            request_payload=safe_mapping(data.get("request_payload") or data.get("payload")),
            route_payload=safe_mapping(data.get("route_payload") or data.get("routes")),
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

    def to_dict(self) -> Dict[str, Any]:
        return to_json_compatible(self)

    def cache_key(self, suffix: str = "") -> str:
        payload = self.to_dict()
        payload["suffix"] = safe_str(suffix, "")
        payload["force_refresh"] = False
        payload["prefer_cache"] = True
        return stable_hash(payload, prefix="library_generator_context_request")


@dataclass
class DependencyResolution:
    key: str
    module_name: str = ""
    status: GeneratorContextStatus = GeneratorContextStatus.UNKNOWN
    available: bool = False
    module: Optional[ModuleType] = None
    service: Any = None
    error: str = ""
    traceback: str = ""
    loaded_at: str = field(default_factory=utc_now_iso)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "key": self.key,
            "module_name": self.module_name,
            "status": self.status.value,
            "available": self.available,
            "service_type": type(self.service).__name__ if self.service is not None else "",
            "error": self.error,
            "loaded_at": self.loaded_at,
        }


@dataclass
class ServiceCallResult:
    ok: bool
    key: str
    method: str
    payload: Any = None
    error: str = ""
    duration_ms: Optional[int] = None
    metadata: Dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "ok": self.ok,
            "key": self.key,
            "method": self.method,
            "payload": to_json_compatible(self.payload),
            "error": self.error,
            "duration_ms": self.duration_ms,
            "metadata": to_json_compatible(self.metadata),
        }


def _module_candidates(key: str) -> List[str]:
    """Return import candidates for a dependency key."""
    return {
        DEPENDENCY_DEFINITIONS: [
            ".library_definition_catalog_service",
            "library.services.library_definition_catalog_service",
            "src.library.services.library_definition_catalog_service",
        ],
        DEPENDENCY_TAXONOMY: [
            ".library_taxonomy_user_service",
            "library.services.library_taxonomy_user_service",
            "src.library.services.library_taxonomy_user_service",
        ],
        DEPENDENCY_FILES: [
            ".library_file_service",
            "library.services.library_file_service",
            "src.library.services.library_file_service",
        ],
        DEPENDENCY_DRAFTS: [
            ".creative_library_draft_service",
            "library.services.creative_library_draft_service",
            "src.library.services.creative_library_draft_service",
        ],
        DEPENDENCY_PUBLISHED: [
            ".creative_library_service",
            "library.services.creative_library_service",
            "src.library.services.creative_library_service",
        ],
        DEPENDENCY_CREATE: [
            ".library_create_service",
            "library.services.library_create_service",
            "src.library.services.library_create_service",
        ],
        DEPENDENCY_VPLIB: [
            "vplib",
            "src.vplib",
        ],
    }.get(key, [])


def _factory_candidates(key: str) -> List[str]:
    """Return service factory/singleton candidates for a dependency module."""
    return {
        DEPENDENCY_DEFINITIONS: [
            "get_library_definition_catalog_service",
            "get_definition_catalog_service",
            "get_catalog_service",
            "get_service",
            "library_definition_catalog_service",
            "definition_catalog_service",
            "service",
        ],
        DEPENDENCY_TAXONOMY: [
            "get_library_taxonomy_user_service",
            "get_taxonomy_user_service",
            "get_taxonomy_service",
            "get_service",
            "library_taxonomy_user_service",
            "taxonomy_user_service",
            "service",
        ],
        DEPENDENCY_FILES: [
            "get_library_file_service",
            "get_file_service",
            "get_service",
            "library_file_service",
            "file_service",
            "service",
        ],
        DEPENDENCY_DRAFTS: [
            "get_creative_library_draft_service",
            "get_library_draft_service",
            "get_draft_service",
            "get_service",
            "creative_library_draft_service",
            "draft_service",
            "service",
        ],
        DEPENDENCY_PUBLISHED: [
            "get_creative_library_service",
            "get_library_service",
            "get_service",
            "creative_library_service",
            "published_service",
            "service",
        ],
        DEPENDENCY_CREATE: [
            "get_library_create_service",
            "get_create_service",
            "get_service",
            "library_create_service",
            "create_service",
            "service",
        ],
        DEPENDENCY_VPLIB: [
            "get_vplib_service",
            "get_service",
            "service",
        ],
    }.get(key, ["get_service", "service"])


def _safe_traceback() -> str:
    try:
        return traceback.format_exc(limit=8)
    except Exception:
        return ""


def _coerce_payload(value: Any) -> Any:
    """
    Convert arbitrary service return values into JSON-compatible Python data.

    Keeps dict/list shapes when possible.
    """
    if value is None:
        return {}

    if isinstance(value, (dict, list, tuple, str, int, float, bool)):
        parsed = parse_json_safe(value, default=value)
        return to_json_compatible(parsed)

    if hasattr(value, "to_dict") and callable(getattr(value, "to_dict")):
        try:
            return to_json_compatible(value.to_dict())
        except Exception:
            pass

    if hasattr(value, "as_dict") and callable(getattr(value, "as_dict")):
        try:
            return to_json_compatible(value.as_dict())
        except Exception:
            pass

    try:
        return to_json_compatible(value)
    except Exception:
        return {"value": safe_str(value)}


def _unwrap_response(value: Any) -> Dict[str, Any]:
    """
    Normalize service response shapes.

    Many existing services may return either:
    - raw domain dict
    - {"ok": true, "data": {...}}
    - {"status": "...", "payload": {...}}
    - dataclass with to_dict()
    """
    payload = _coerce_payload(value)

    if isinstance(payload, dict):
        data = safe_mapping(payload.get("data"))
        payload_data = safe_mapping(payload.get("payload"))
        result = dict(payload)

        if data:
            result = merge_mappings(result, data)
            result.setdefault("_response_data", data)

        if payload_data:
            result = merge_mappings(result, payload_data)
            result.setdefault("_response_payload", payload_data)

        return result

    if isinstance(payload, list):
        return {"items": payload}

    return {"value": payload}


def _deep_merge(left: Any, right: Any) -> Dict[str, Any]:
    """
    Deep-ish merge for service payloads.

    Dict values are recursively merged. Lists are replaced by right side when
    non-empty; otherwise left is kept.
    """
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


def _callable_accepts_kwargs(func: Callable[..., Any]) -> bool:
    try:
        signature = inspect.signature(func)
    except Exception:
        return True

    for parameter in signature.parameters.values():
        if parameter.kind == parameter.VAR_KEYWORD:
            return True

    return False


def _filtered_kwargs(func: Callable[..., Any], kwargs: Mapping[str, Any]) -> Dict[str, Any]:
    if not kwargs:
        return {}

    if _callable_accepts_kwargs(func):
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


class LibraryGeneratorContextService:
    """
    Read-only service facade for generator context construction.

    The service intentionally delegates to existing services instead of
    repositories or routes. It can run in partial mode when optional services
    are unavailable.
    """

    def __init__(
        self,
        cache: Optional[GeneratorContextMemoryCache] = None,
        builder: Optional[GeneratorContextBuilder] = None,
        default_ttl_seconds: int = DEFAULT_SERVICE_CACHE_TTL_SECONDS,
        cache_max_entries: int = DEFAULT_SERVICE_CACHE_MAX_ENTRIES,
    ) -> None:
        self.cache = cache or GeneratorContextMemoryCache(
            default_ttl_seconds=default_ttl_seconds,
            max_entries=cache_max_entries,
            name="library_generator_context_service_cache",
        )
        self.builder = builder or get_default_generator_context_builder()
        self.default_ttl_seconds = max(0, int(default_ttl_seconds))
        self.cache_max_entries = max(1, int(cache_max_entries))
        self._dependency_cache: Dict[str, DependencyResolution] = {}
        self._lock = threading.RLock()

    # ---------------------------------------------------------------------
    # Public API
    # ---------------------------------------------------------------------

    def get_context(
        self,
        request: Any = None,
        force_refresh: Optional[bool] = None,
        use_cache: Optional[bool] = None,
    ) -> GeneratorContext:
        """
        Build and return a complete read-only GeneratorContext.

        `request` may be:
        - LibraryGeneratorContextRequest
        - dict-like object
        - None
        """
        parsed_request = self.normalize_request(request)
        if force_refresh is not None:
            parsed_request.force_refresh = bool(force_refresh)
        if use_cache is not None:
            parsed_request.prefer_cache = bool(use_cache)

        cache_key = parsed_request.cache_key("context")

        if parsed_request.force_refresh or not parsed_request.prefer_cache:
            return self._build_context_uncached(parsed_request)

        cache_result = try_cache_get_or_set(
            key=cache_key,
            factory=lambda: self._build_context_uncached(parsed_request),
            ttl_seconds=parsed_request.cache_ttl_seconds,
            cache=self.cache,
            allow_stale_on_error=True,
            fallback=build_minimal_generator_context(
                user_id=parsed_request.user_id,
                inventory_key=parsed_request.inventory_key,
                request_payload=parsed_request.request_payload,
                metadata={
                    "fallback_reason": "context_cache_factory_failed",
                    "cache_key": cache_key,
                },
            ),
            metadata={
                "component": LIBRARY_GENERATOR_CONTEXT_SERVICE_COMPONENT,
                "request": parsed_request.to_dict(),
            },
        )

        context = cache_result.value if isinstance(cache_result.value, GeneratorContext) else GeneratorContext.from_mapping(cache_result.value)
        if cache_result.hit:
            context.source = GeneratorContextSource.CACHE
        if cache_result.stale:
            context.diagnostics.add_warning(
                "generator_context_cache_stale",
                "Using stale generator context from cache after a refresh error.",
                GeneratorContextSection.DIAGNOSTICS,
                cache_key=cache_key,
                error=cache_result.error,
            )
            context.refresh_status()

        return context

    def get_context_result(
        self,
        request: Any = None,
        mode: Any = GeneratorContextViewMode.PUBLIC,
        build_options: Any = None,
        force_refresh: Optional[bool] = None,
        use_cache: Optional[bool] = None,
    ) -> GeneratorContextBuildResult:
        context = self.get_context(
            request=request,
            force_refresh=force_refresh,
            use_cache=use_cache,
        )
        options = build_options if build_options is not None else {}
        return self.builder.build(
            context=context,
            mode=mode,
            options=options,
            use_cache=use_cache,
        )

    def get_context_payload(
        self,
        request: Any = None,
        mode: Any = GeneratorContextViewMode.PUBLIC,
        build_options: Any = None,
        force_refresh: Optional[bool] = None,
        use_cache: Optional[bool] = None,
    ) -> Dict[str, Any]:
        return self.get_context_result(
            request=request,
            mode=mode,
            build_options=build_options,
            force_refresh=force_refresh,
            use_cache=use_cache,
        ).payload

    def get_frontend_context(
        self,
        request: Any = None,
        build_options: Any = None,
        force_refresh: Optional[bool] = None,
        use_cache: Optional[bool] = None,
    ) -> Dict[str, Any]:
        return self.get_context_payload(
            request=request,
            mode=GeneratorContextViewMode.FRONTEND,
            build_options=build_options,
            force_refresh=force_refresh,
            use_cache=use_cache,
        )

    def get_create_options(
        self,
        request: Any = None,
        build_options: Any = None,
        force_refresh: Optional[bool] = None,
        use_cache: Optional[bool] = None,
    ) -> Dict[str, Any]:
        return self.get_context_payload(
            request=request,
            mode=GeneratorContextViewMode.OPTIONS,
            build_options=build_options,
            force_refresh=force_refresh,
            use_cache=use_cache,
        )

    def get_diagnostics(
        self,
        request: Any = None,
        build_options: Any = None,
        force_refresh: Optional[bool] = None,
        use_cache: Optional[bool] = None,
    ) -> Dict[str, Any]:
        return self.get_context_payload(
            request=request,
            mode=GeneratorContextViewMode.DIAGNOSTICS,
            build_options=build_options,
            force_refresh=force_refresh,
            use_cache=use_cache,
        )

    def get_health(
        self,
        check_dependencies: bool = True,
        include_cache: bool = True,
    ) -> Dict[str, Any]:
        diagnostics = GeneratorContextDiagnostics()

        dependency_payload: Dict[str, Any] = {}
        if check_dependencies:
            for key in DEPENDENCY_KEYS:
                resolution = self.resolve_dependency(key, force_refresh=True)
                dependency_payload[key] = resolution.to_dict()
                if key in {DEPENDENCY_DEFINITIONS, DEPENDENCY_TAXONOMY} and not resolution.available:
                    diagnostics.add_warning(
                        f"{key}_dependency_unavailable",
                        f"Dependency is unavailable: {key}",
                        GeneratorContextSection.DIAGNOSTICS,
                        dependency=key,
                        error=resolution.error,
                    )

        try:
            minimal_context = build_minimal_generator_context()
            builder_health = self.builder.build_health_payload(minimal_context)
        except Exception as exc:
            builder_health = {
                "ok": False,
                "error": safe_str(exc),
            }
            diagnostics.add_error(
                "generator_context_builder_unavailable",
                "Generator context builder failed during health check.",
                GeneratorContextSection.DIAGNOSTICS,
                error=safe_str(exc),
            )

        diagnostics.refresh()

        payload: Dict[str, Any] = {
            "ok": diagnostics.blocking_count == 0,
            "status": diagnostics.status.value,
            "component": LIBRARY_GENERATOR_CONTEXT_SERVICE_COMPONENT,
            "schema_version": LIBRARY_GENERATOR_CONTEXT_SERVICE_SCHEMA_VERSION,
            "context_schema_version": GENERATOR_CONTEXT_SCHEMA_VERSION,
            "checked_at": utc_now_iso(),
            "dependencies": dependency_payload,
            "builder": builder_health,
            "diagnostics": diagnostics.to_dict(),
        }

        if include_cache:
            payload["cache"] = self.cache.stats()
            try:
                payload["builder_cache"] = self.builder.cache.stats() if self.builder.cache is not None else None
            except Exception:
                payload["builder_cache"] = None

        return payload

    def assert_ready(self, require_dependencies: bool = False) -> bool:
        health = self.get_health(check_dependencies=require_dependencies, include_cache=False)
        if not health.get("ok"):
            raise RuntimeError(f"{LIBRARY_GENERATOR_CONTEXT_SERVICE_COMPONENT} is not ready: {health}")
        return True

    def clear_caches(self) -> Dict[str, Any]:
        cleared_context = self.cache.clear()
        with self._lock:
            dependency_count = len(self._dependency_cache)
            self._dependency_cache.clear()

        builder_cleared = 0
        try:
            if self.builder.cache is not None:
                builder_cleared = self.builder.cache.clear()
        except Exception:
            builder_cleared = 0

        return {
            "ok": True,
            "component": LIBRARY_GENERATOR_CONTEXT_SERVICE_COMPONENT,
            "cleared_at": utc_now_iso(),
            "cleared": {
                "context_cache": cleared_context,
                "dependency_cache": dependency_count,
                "builder_cache": builder_cleared,
            },
        }

    # ---------------------------------------------------------------------
    # Request normalization
    # ---------------------------------------------------------------------

    def normalize_request(self, request: Any = None) -> LibraryGeneratorContextRequest:
        if isinstance(request, LibraryGeneratorContextRequest):
            return request
        return LibraryGeneratorContextRequest.from_mapping(request)

    # ---------------------------------------------------------------------
    # Context build pipeline
    # ---------------------------------------------------------------------

    def _build_context_uncached(self, request: LibraryGeneratorContextRequest) -> GeneratorContext:
        started = time.monotonic()
        diagnostics = GeneratorContextDiagnostics()
        timings: Dict[str, int] = {}

        user_context = GeneratorUserContext.from_mapping(
            {
                "user_id": request.user_id,
                "owner_scope": request.owner_scope,
                "inventory_key": request.inventory_key,
            }
        )

        context = GeneratorContext(
            status=GeneratorContextStatus.UNKNOWN,
            source=GeneratorContextSource.SERVICE,
            routes=GeneratorRouteContext.default(),
            user=user_context,
            request_payload=safe_mapping(request.request_payload),
            metadata={
                "component": LIBRARY_GENERATOR_CONTEXT_SERVICE_COMPONENT,
                "service_schema_version": LIBRARY_GENERATOR_CONTEXT_SERVICE_SCHEMA_VERSION,
                "request": request.to_dict(),
                **safe_mapping(request.metadata),
            },
        )

        if request.include_routes:
            context.routes = self._timed_section(
                "routes",
                timings,
                diagnostics,
                lambda: self.load_route_context(request),
                fallback=GeneratorRouteContext.default(),
            )

        if request.include_definitions:
            context.definitions = self._timed_section(
                "definitions",
                timings,
                diagnostics,
                lambda: self.load_definition_context(request),
                fallback=GeneratorDefinitionContext(
                    status=GeneratorContextStatus.UNAVAILABLE,
                    source=GeneratorContextSource.FALLBACK,
                ),
            )

        if request.include_taxonomy:
            context.taxonomy = self._timed_section(
                "taxonomy",
                timings,
                diagnostics,
                lambda: self.load_taxonomy_context(request),
                fallback=GeneratorTaxonomyContext(
                    status=GeneratorContextStatus.UNAVAILABLE,
                    source=GeneratorContextSource.FALLBACK,
                    user_id=request.user_id,
                    owner_scope=request.owner_scope,
                    domain=request.domain,
                    category=request.category,
                    subcategory=request.subcategory,
                    taxonomy_path=request.current_taxonomy_path,
                ),
            )

        if request.include_uploads:
            context.uploads = self._timed_section(
                "uploads",
                timings,
                diagnostics,
                lambda: self.load_upload_context(request, context.definitions),
                fallback=GeneratorUploadContext(
                    status=GeneratorContextStatus.UNAVAILABLE,
                    source=GeneratorContextSource.FALLBACK,
                ),
            )

        if request.include_files:
            context.files = self._timed_section(
                "files",
                timings,
                diagnostics,
                lambda: self.load_file_context(request),
                fallback=GeneratorFileContext(
                    status=GeneratorContextStatus.UNAVAILABLE,
                    source=GeneratorContextSource.FALLBACK,
                ),
            )

        if request.include_draft:
            context.draft = self._timed_section(
                "draft",
                timings,
                diagnostics,
                lambda: self.load_draft_context(request),
                fallback=GeneratorDraftContext.empty(),
            )

        if request.include_published:
            context.published = self._timed_section(
                "published",
                timings,
                diagnostics,
                lambda: self.load_published_context(request),
                fallback=GeneratorPublishedContext.empty(),
            )

        if request.include_capabilities:
            context.capabilities = self._timed_section(
                "capabilities",
                timings,
                diagnostics,
                lambda: self.load_capabilities(request, context),
                fallback=GeneratorCapabilities(),
            )

        if request.include_vplib_health:
            vplib_diagnostics = self._timed_section(
                "vplib_health",
                timings,
                diagnostics,
                lambda: self.load_vplib_diagnostics(request),
                fallback=GeneratorContextDiagnostics(),
            )
            context.diagnostics.merge(vplib_diagnostics)

        diagnostics.duration_ms = int((time.monotonic() - started) * 1000)
        diagnostics.timings_ms.update(timings)
        diagnostics.refresh()

        context.diagnostics.merge(diagnostics)
        context.diagnostics.timings_ms.update(timings)
        context.loaded_at = utc_now_iso()
        context.refresh_status()

        return context

    def _timed_section(
        self,
        key: str,
        timings: Dict[str, int],
        diagnostics: GeneratorContextDiagnostics,
        factory: Callable[[], Any],
        fallback: Any,
    ) -> Any:
        started = time.monotonic()
        try:
            value = factory()
            timings[key] = int((time.monotonic() - started) * 1000)
            return value
        except Exception as exc:
            timings[key] = int((time.monotonic() - started) * 1000)
            diagnostics.add_warning(
                f"{normalize_key(key)}_load_failed",
                f"Could not load generator context section: {key}",
                GeneratorContextSection.DIAGNOSTICS,
                section=key,
                error=safe_str(exc),
            )
            return fallback

    # ---------------------------------------------------------------------
    # Section loaders
    # ---------------------------------------------------------------------

    def load_route_context(self, request: LibraryGeneratorContextRequest) -> GeneratorRouteContext:
        payload = {
            "status": GeneratorContextStatus.READY.value,
            "source": GeneratorContextSource.DEFAULT.value,
            "routes": DEFAULT_GENERATOR_ROUTES,
        }

        if request.route_payload:
            payload = _deep_merge(payload, {"routes": request.route_payload})

        return GeneratorRouteContext.from_mapping(payload)

    def load_definition_context(self, request: LibraryGeneratorContextRequest) -> GeneratorDefinitionContext:
        resolution = self.resolve_dependency(DEPENDENCY_DEFINITIONS)
        diagnostics = GeneratorContextDiagnostics()

        if not resolution.available:
            diagnostics.add_warning(
                "definitions_service_unavailable",
                "Definition catalog service is unavailable.",
                GeneratorContextSection.DEFINITIONS,
                error=resolution.error,
            )
            return GeneratorDefinitionContext(
                status=GeneratorContextStatus.UNAVAILABLE,
                source=GeneratorContextSource.FALLBACK,
                diagnostics=diagnostics,
            )

        payload = {
            "status": GeneratorContextStatus.PARTIAL.value,
            "source": GeneratorContextSource.SERVICE.value,
        }

        call_specs = [
            (
                "current_catalog",
                [
                    "get_current_catalog",
                    "get_catalog",
                    "get_definition_catalog",
                    "get_current",
                    "current",
                    "build_current_catalog",
                ],
            ),
            (
                "payload",
                [
                    "get_payload",
                    "get_definitions_payload",
                    "get_current_payload",
                    "get_catalog_payload",
                ],
            ),
            (
                "options",
                [
                    "get_options",
                    "get_create_options",
                    "get_create_options_payload",
                    "build_create_options",
                ],
            ),
            (
                "create_context",
                [
                    "get_create_context",
                    "get_create_context_payload",
                    "build_create_context",
                ],
            ),
            (
                "health",
                [
                    "get_health",
                    "health",
                    "get_library_definition_catalog_service_health",
                    "get_definition_catalog_health",
                ],
            ),
        ]

        for label, method_names in call_specs:
            result = self.call_first_available(
                resolution,
                method_names=method_names,
                kwargs={
                    "user_id": request.user_id,
                    "owner_scope": request.owner_scope,
                    "inventory_key": request.inventory_key,
                    "domain": request.domain,
                    "category": request.category,
                    "subcategory": request.subcategory,
                    "taxonomy_path": request.current_taxonomy_path,
                    "include_inactive": True,
                },
            )
            if result.ok:
                payload = _deep_merge(payload, {label: _unwrap_response(result.payload)})
                payload = _deep_merge(payload, _unwrap_response(result.payload))
            elif label in {"current_catalog", "payload"}:
                diagnostics.add_warning(
                    f"definitions_{label}_unavailable",
                    f"Definition catalog call failed: {label}",
                    GeneratorContextSection.DEFINITIONS,
                    error=result.error,
                )

        context = GeneratorDefinitionContext.from_mapping(payload)
        context.diagnostics.merge(diagnostics)
        context.refresh_status()
        return context

    def load_taxonomy_context(self, request: LibraryGeneratorContextRequest) -> GeneratorTaxonomyContext:
        resolution = self.resolve_dependency(DEPENDENCY_TAXONOMY)
        diagnostics = GeneratorContextDiagnostics()

        base_payload = {
            "status": GeneratorContextStatus.PARTIAL.value,
            "source": GeneratorContextSource.SERVICE.value,
            "user_id": request.user_id,
            "owner_scope": request.owner_scope,
            "domain": request.domain,
            "category": request.category,
            "subcategory": request.subcategory,
            "taxonomy_path": request.current_taxonomy_path,
        }

        if not resolution.available:
            diagnostics.add_warning(
                "taxonomy_service_unavailable",
                "Taxonomy service is unavailable.",
                GeneratorContextSection.TAXONOMY,
                error=resolution.error,
            )
            base_payload["status"] = GeneratorContextStatus.UNAVAILABLE.value
            base_payload["source"] = GeneratorContextSource.FALLBACK.value
            context = GeneratorTaxonomyContext.from_mapping(base_payload)
            context.diagnostics.merge(diagnostics)
            return context

        payload = dict(base_payload)

        call_specs = [
            (
                "create_options",
                [
                    "get_create_options",
                    "get_taxonomy_create_options",
                    "get_create_options_payload",
                    "get_options",
                    "create_options",
                ],
            ),
            (
                "resolved",
                [
                    "get_resolved_taxonomy",
                    "get_resolved",
                    "resolve_taxonomy",
                    "get_user_resolved_taxonomy",
                ],
            ),
            (
                "tree",
                [
                    "get_tree",
                    "get_taxonomy_tree",
                    "get_tree_payload",
                ],
            ),
            (
                "nodes",
                [
                    "list_nodes",
                    "get_nodes",
                    "list_taxonomy_nodes",
                ],
            ),
            (
                "health",
                [
                    "get_health",
                    "health",
                    "get_taxonomy_health",
                    "get_library_taxonomy_user_service_health",
                ],
            ),
        ]

        for label, method_names in call_specs:
            result = self.call_first_available(
                resolution,
                method_names=method_names,
                kwargs={
                    "user_id": request.user_id,
                    "owner_scope": request.owner_scope,
                    "domain": request.domain,
                    "category": request.category,
                    "subcategory": request.subcategory,
                    "taxonomy_path": request.current_taxonomy_path,
                },
            )
            if result.ok:
                value = _unwrap_response(result.payload)
                if label == "nodes" and "items" in value:
                    payload["nodes"] = value["items"]
                else:
                    payload[label] = value
                    payload = _deep_merge(payload, value)
            elif label in {"create_options", "resolved"}:
                diagnostics.add_warning(
                    f"taxonomy_{label}_unavailable",
                    f"Taxonomy call failed: {label}",
                    GeneratorContextSection.TAXONOMY,
                    error=result.error,
                )

        context = GeneratorTaxonomyContext.from_mapping(payload)
        context.diagnostics.merge(diagnostics)
        context.refresh_status()
        return context

    def load_upload_context(
        self,
        request: LibraryGeneratorContextRequest,
        definitions: Optional[GeneratorDefinitionContext] = None,
    ) -> GeneratorUploadContext:
        diagnostics = GeneratorContextDiagnostics()
        payload: Dict[str, Any] = {
            "status": GeneratorContextStatus.PARTIAL.value,
            "source": GeneratorContextSource.MIXED.value,
        }

        file_resolution = self.resolve_dependency(DEPENDENCY_FILES)
        definitions_resolution = self.resolve_dependency(DEPENDENCY_DEFINITIONS)

        # Prefer FileService for file/storage constraints.
        if file_resolution.available:
            result = self.call_first_available(
                file_resolution,
                method_names=[
                    "get_upload_constraints",
                    "get_upload_constraints_payload",
                    "get_constraints",
                    "get_file_constraints",
                    "build_upload_constraints",
                ],
                kwargs={
                    "user_id": request.user_id,
                    "owner_scope": request.owner_scope,
                    "domain": request.domain,
                    "category": request.category,
                    "subcategory": request.subcategory,
                    "taxonomy_path": request.current_taxonomy_path,
                },
            )
            if result.ok:
                payload = _deep_merge(payload, _unwrap_response(result.payload))
            else:
                diagnostics.add_warning(
                    "file_upload_constraints_unavailable",
                    "File upload constraints could not be loaded from file service.",
                    GeneratorContextSection.UPLOADS,
                    error=result.error,
                )

        # Fallback/augment from DefinitionCatalogService.
        if definitions_resolution.available:
            result = self.call_first_available(
                definitions_resolution,
                method_names=[
                    "get_upload_constraints",
                    "get_upload_constraints_payload",
                    "get_document_type_constraints",
                    "get_create_context",
                    "get_create_context_payload",
                ],
                kwargs={
                    "user_id": request.user_id,
                    "owner_scope": request.owner_scope,
                    "domain": request.domain,
                    "category": request.category,
                    "subcategory": request.subcategory,
                    "taxonomy_path": request.current_taxonomy_path,
                },
            )
            if result.ok:
                payload = _deep_merge(payload, _unwrap_response(result.payload))

        if definitions is not None and definitions.document_types:
            payload.setdefault("document_types", definitions.document_types)

        if not file_resolution.available and not definitions_resolution.available:
            diagnostics.add_warning(
                "upload_context_dependencies_unavailable",
                "Neither file service nor definition service is available for upload constraints.",
                GeneratorContextSection.UPLOADS,
            )
            payload["status"] = GeneratorContextStatus.UNAVAILABLE.value
            payload["source"] = GeneratorContextSource.FALLBACK.value

        context = GeneratorUploadContext.from_mapping(payload)
        context.diagnostics.merge(diagnostics)
        context.refresh_status()
        return context

    def load_file_context(self, request: LibraryGeneratorContextRequest) -> GeneratorFileContext:
        resolution = self.resolve_dependency(DEPENDENCY_FILES)
        diagnostics = GeneratorContextDiagnostics()

        if not resolution.available:
            diagnostics.add_warning(
                "file_service_unavailable",
                "File service is unavailable.",
                GeneratorContextSection.FILES,
                error=resolution.error,
            )
            return GeneratorFileContext(
                status=GeneratorContextStatus.UNAVAILABLE,
                source=GeneratorContextSource.FALLBACK,
                diagnostics=diagnostics,
            )

        payload: Dict[str, Any] = {
            "status": GeneratorContextStatus.PARTIAL.value,
            "source": GeneratorContextSource.SERVICE.value,
        }

        call_specs = [
            (
                "context_files",
                [
                    "get_context_files",
                    "list_context_files",
                    "get_files_for_context",
                    "list_files_for_context",
                ],
            ),
            (
                "files",
                [
                    "list_files",
                    "get_files",
                    "search_files",
                ],
            ),
            (
                "links",
                [
                    "list_links",
                    "get_links",
                    "list_file_links",
                ],
            ),
        ]

        for label, method_names in call_specs:
            result = self.call_first_available(
                resolution,
                method_names=method_names,
                kwargs={
                    "user_id": request.user_id,
                    "owner_scope": request.owner_scope,
                    "context_type": "generator",
                    "context_uid": request.draft_ref or request.item_ref or request.vplib_uid,
                    "draft_ref": request.draft_ref,
                    "item_ref": request.item_ref,
                    "vplib_uid": request.vplib_uid,
                    "limit": 100,
                },
            )
            if result.ok:
                value = _unwrap_response(result.payload)
                if label == "context_files":
                    payload["context_files"] = value.get("context_files") or value.get("items") or value
                else:
                    payload[label] = value.get("items") or value.get(label) or value

        context = GeneratorFileContext.from_mapping(payload)
        context.diagnostics.merge(diagnostics)
        context.refresh_status()
        return context

    def load_draft_context(self, request: LibraryGeneratorContextRequest) -> GeneratorDraftContext:
        resolution = self.resolve_dependency(DEPENDENCY_DRAFTS)
        diagnostics = GeneratorContextDiagnostics()

        if not request.draft_ref:
            diagnostics.add_warning(
                "draft_ref_missing",
                "Draft context was requested but no draft_ref was provided.",
                GeneratorContextSection.DRAFT,
            )
            context = GeneratorDraftContext.empty()
            context.diagnostics.merge(diagnostics)
            return context

        if not resolution.available:
            diagnostics.add_warning(
                "draft_service_unavailable",
                "Draft service is unavailable.",
                GeneratorContextSection.DRAFT,
                error=resolution.error,
            )
            context = GeneratorDraftContext.empty()
            context.diagnostics.merge(diagnostics)
            return context

        result = self.call_first_available(
            resolution,
            method_names=[
                "get_draft",
                "get",
                "get_by_ref",
                "get_draft_by_ref",
                "read_draft",
                "load_draft",
            ],
            kwargs={
                "draft_ref": request.draft_ref,
                "user_id": request.user_id,
                "owner_scope": request.owner_scope,
                "include_children": True,
                "include_issues": True,
                "include_audit": False,
            },
            positional_variants=[
                (request.draft_ref,),
                (request.draft_ref, request.user_id),
            ],
        )

        if not result.ok:
            diagnostics.add_warning(
                "draft_load_failed",
                "Draft could not be loaded.",
                GeneratorContextSection.DRAFT,
                draft_ref=request.draft_ref,
                error=result.error,
            )
            context = GeneratorDraftContext.empty()
            context.diagnostics.merge(diagnostics)
            return context

        payload = _unwrap_response(result.payload)
        context = GeneratorDraftContext.from_mapping(payload)
        context.diagnostics.merge(diagnostics)
        context.refresh_status()
        return context

    def load_published_context(self, request: LibraryGeneratorContextRequest) -> GeneratorPublishedContext:
        resolution = self.resolve_dependency(DEPENDENCY_PUBLISHED)
        diagnostics = GeneratorContextDiagnostics()

        if not resolution.available:
            diagnostics.add_warning(
                "published_service_unavailable",
                "Published Creative Library service is unavailable.",
                GeneratorContextSection.PUBLISHED,
                error=resolution.error,
            )
            context = GeneratorPublishedContext.empty()
            context.diagnostics.merge(diagnostics)
            return context

        identity_kwargs = {
            "item_ref": request.item_ref,
            "vplib_uid": request.vplib_uid,
            "family_id": request.family_id,
            "package_id": request.package_id,
            "user_id": request.user_id,
            "owner_scope": request.owner_scope,
            "include_variants": True,
            "include_assets": True,
            "include_documents": True,
            "include_revisions": True,
        }

        method_names = [
            "get_item",
            "get_item_detail",
            "get_family",
            "get_family_detail",
            "get_published_item",
            "get_published_family",
        ]

        if request.vplib_uid:
            method_names = [
                "get_item_by_vplib_uid",
                "get_by_vplib_uid",
                "get_published_by_vplib_uid",
            ] + method_names

        result = self.call_first_available(
            resolution,
            method_names=method_names,
            kwargs=identity_kwargs,
            positional_variants=[
                tuple([request.vplib_uid]) if request.vplib_uid else tuple(),
                tuple([request.item_ref]) if request.item_ref else tuple(),
                tuple([request.family_id]) if request.family_id else tuple(),
            ],
        )

        if not result.ok:
            diagnostics.add_warning(
                "published_context_load_failed",
                "Published context could not be loaded.",
                GeneratorContextSection.PUBLISHED,
                item_ref=request.item_ref,
                vplib_uid=request.vplib_uid,
                error=result.error,
            )
            context = GeneratorPublishedContext.empty()
            context.diagnostics.merge(diagnostics)
            return context

        payload = _unwrap_response(result.payload)
        context = GeneratorPublishedContext.from_mapping(payload)
        context.diagnostics.merge(diagnostics)
        context.refresh_status()
        return context

    def load_capabilities(
        self,
        request: LibraryGeneratorContextRequest,
        context: GeneratorContext,
    ) -> GeneratorCapabilities:
        definitions = context.definitions
        dependency_status = {
            key: self.resolve_dependency(key).available
            for key in DEPENDENCY_KEYS
        }

        create_resolution = self.resolve_dependency(DEPENDENCY_CREATE)
        draft_resolution = self.resolve_dependency(DEPENDENCY_DRAFTS)
        file_resolution = self.resolve_dependency(DEPENDENCY_FILES)
        published_resolution = self.resolve_dependency(DEPENDENCY_PUBLISHED)

        payload: Dict[str, Any] = {
            "supports_context": True,
            "supports_options": True,
            "supports_validate": self.has_any_method(
                create_resolution,
                [
                    "validate",
                    "validate_payload",
                    "validate_draft",
                    "validate_create_payload",
                    "build_validation_result",
                ],
            ),
            "supports_package_plan": self.has_any_method(
                create_resolution,
                [
                    "build_package_plan",
                    "get_package_plan",
                    "package_plan",
                    "create_package_plan",
                ],
            ),
            "supports_download": self.has_any_method(
                create_resolution,
                [
                    "download",
                    "build_download",
                    "create_download",
                    "create_archive",
                    "build_archive",
                ],
            ),
            "supports_source_save": self.has_any_method(
                create_resolution,
                [
                    "save",
                    "save_source",
                    "save_package",
                    "save_source_package",
                    "write_source_package",
                ],
            ),
            "supports_persistent_drafts": draft_resolution.available,
            "supports_publish_prepare": self.has_any_method(
                draft_resolution,
                [
                    "publish_prepare",
                    "prepare_publish",
                    "build_publish_payload",
                    "prepare_draft_publish",
                ],
            ),
            "supports_publish": self.has_any_method(
                draft_resolution,
                [
                    "publish",
                    "publish_draft",
                ],
            ) or self.has_any_method(
                published_resolution,
                [
                    "publish_bundle",
                    "sync_package_payload",
                    "publish",
                ],
            ),
            "supports_files": file_resolution.available,
            "supports_user_inventory": False,
            "supports_taxonomy_overrides": self.resolve_dependency(DEPENDENCY_TAXONOMY).available,
            "supports_definition_seed": self.has_any_method(
                self.resolve_dependency(DEPENDENCY_DEFINITIONS),
                [
                    "seed",
                    "seed_run",
                    "run_seed",
                    "seed_definitions",
                ],
            ),
            "supports_db_sync": self.has_any_method(
                published_resolution,
                [
                    "publish_bundle",
                    "sync_package_payload",
                    "start_scan_run",
                    "finish_scan_run",
                ],
            ),
            "supports_create_preview": False,
            "supported_object_kinds": definitions.list_object_kind_keys(),
            "supported_modules": [],
            "metadata": {
                "dependency_status": dependency_status,
                "source": "library_generator_context_service",
            },
        }

        return GeneratorCapabilities.from_mapping(payload)

    def load_vplib_diagnostics(self, request: LibraryGeneratorContextRequest) -> GeneratorContextDiagnostics:
        diagnostics = GeneratorContextDiagnostics()
        resolution = self.resolve_dependency(DEPENDENCY_VPLIB)

        if not resolution.available:
            diagnostics.add_warning(
                "vplib_package_unavailable",
                "VPLIB package could not be imported.",
                GeneratorContextSection.CAPABILITIES,
                error=resolution.error,
            )
            diagnostics.refresh()
            return diagnostics

        result = self.call_first_available(
            resolution,
            method_names=[
                "get_vplib_health",
                "get_health",
                "health",
                "get_vplib_status",
            ],
            kwargs={},
        )

        if not result.ok:
            diagnostics.add_warning(
                "vplib_health_unavailable",
                "VPLIB health could not be loaded.",
                GeneratorContextSection.CAPABILITIES,
                error=result.error,
            )
            diagnostics.refresh()
            return diagnostics

        payload = _unwrap_response(result.payload)
        ok = safe_bool(payload.get("ok"), True)
        status = normalize_key(payload.get("status"), "ready")

        if not ok or status in {"error", "invalid", "unavailable"}:
            diagnostics.add_warning(
                "vplib_health_not_ready",
                "VPLIB health reported a non-ready state.",
                GeneratorContextSection.CAPABILITIES,
                health=payload,
            )
        else:
            diagnostics.add_info(
                "vplib_health_ready",
                "VPLIB package health is available.",
                GeneratorContextSection.CAPABILITIES,
            )

        diagnostics.refresh()
        return diagnostics

    # ---------------------------------------------------------------------
    # Lazy dependency handling
    # ---------------------------------------------------------------------

    def resolve_dependency(
        self,
        key: str,
        force_refresh: bool = False,
    ) -> DependencyResolution:
        normalized_key = normalize_key(key)

        with self._lock:
            if not force_refresh and normalized_key in self._dependency_cache:
                return self._dependency_cache[normalized_key]

        resolution = self._resolve_dependency_uncached(normalized_key)

        with self._lock:
            self._dependency_cache[normalized_key] = resolution

        return resolution

    def _resolve_dependency_uncached(self, key: str) -> DependencyResolution:
        candidates = _module_candidates(key)
        last_error = ""

        for module_name in candidates:
            try:
                module = self._import_module_candidate(module_name)
                service = self._resolve_service_object(key, module)

                return DependencyResolution(
                    key=key,
                    module_name=getattr(module, "__name__", module_name),
                    status=GeneratorContextStatus.READY,
                    available=True,
                    module=module,
                    service=service,
                )
            except Exception as exc:
                last_error = safe_str(exc)

        return DependencyResolution(
            key=key,
            module_name=",".join(candidates),
            status=GeneratorContextStatus.UNAVAILABLE,
            available=False,
            error=last_error or "no_import_candidate_available",
            traceback=_safe_traceback(),
        )

    def _import_module_candidate(self, module_name: str) -> ModuleType:
        if module_name.startswith("."):
            if not __package__:
                raise ImportError(f"Relative import not available for {module_name}")
            return importlib.import_module(module_name, package=__package__)

        return importlib.import_module(module_name)

    def _resolve_service_object(self, key: str, module: ModuleType) -> Any:
        for candidate in _factory_candidates(key):
            attr = getattr(module, candidate, None)
            if attr is None:
                continue

            if callable(attr) and candidate.startswith("get_"):
                try:
                    service = attr()
                    if service is not None:
                        return service
                except TypeError:
                    continue
                except Exception:
                    continue

            if not callable(attr):
                return attr

            if candidate in {"service", "library_definition_catalog_service", "definition_catalog_service"}:
                return attr

        return module

    # ---------------------------------------------------------------------
    # Service method probing
    # ---------------------------------------------------------------------

    def has_any_method(
        self,
        resolution: DependencyResolution,
        method_names: Sequence[str],
    ) -> bool:
        if not resolution.available:
            return False

        targets = self._method_targets(resolution)
        for target in targets:
            for method_name in method_names:
                if callable(getattr(target, method_name, None)):
                    return True

        return False

    def call_first_available(
        self,
        resolution: DependencyResolution,
        method_names: Sequence[str],
        kwargs: Optional[Mapping[str, Any]] = None,
        positional_variants: Optional[Sequence[Tuple[Any, ...]]] = None,
    ) -> ServiceCallResult:
        started = time.monotonic()

        if not resolution.available:
            return ServiceCallResult(
                ok=False,
                key=resolution.key,
                method="",
                error=resolution.error or "dependency_unavailable",
                duration_ms=int((time.monotonic() - started) * 1000),
            )

        targets = self._method_targets(resolution)
        last_error = ""
        call_kwargs = safe_mapping(kwargs)
        positional_variants = positional_variants or []

        for target in targets:
            for method_name in method_names:
                method = getattr(target, method_name, None)
                if not callable(method):
                    continue

                result = self._try_call_method(
                    key=resolution.key,
                    method_name=method_name,
                    method=method,
                    kwargs=call_kwargs,
                    positional_variants=positional_variants,
                    started=started,
                )
                if result.ok:
                    return result
                last_error = result.error

        return ServiceCallResult(
            ok=False,
            key=resolution.key,
            method=",".join(method_names),
            error=last_error or "no_candidate_method_available",
            duration_ms=int((time.monotonic() - started) * 1000),
        )

    def _method_targets(self, resolution: DependencyResolution) -> List[Any]:
        targets: List[Any] = []

        if resolution.service is not None:
            targets.append(resolution.service)

        if resolution.module is not None and resolution.module is not resolution.service:
            targets.append(resolution.module)

        return targets

    def _try_call_method(
        self,
        key: str,
        method_name: str,
        method: Callable[..., Any],
        kwargs: Mapping[str, Any],
        positional_variants: Sequence[Tuple[Any, ...]],
        started: float,
    ) -> ServiceCallResult:
        errors: List[str] = []

        # 1. Try filtered keyword call.
        try:
            filtered = _filtered_kwargs(method, kwargs)
            payload = method(**filtered)
            return ServiceCallResult(
                ok=True,
                key=key,
                method=method_name,
                payload=payload,
                duration_ms=int((time.monotonic() - started) * 1000),
                metadata={"call_style": "kwargs"},
            )
        except TypeError as exc:
            errors.append(f"kwargs:{safe_str(exc)}")
        except Exception as exc:
            return ServiceCallResult(
                ok=False,
                key=key,
                method=method_name,
                error=safe_str(exc),
                duration_ms=int((time.monotonic() - started) * 1000),
                metadata={"call_style": "kwargs"},
            )

        # 2. Try explicit positional variants.
        for args in positional_variants:
            if not args:
                continue
            try:
                payload = method(*args)
                return ServiceCallResult(
                    ok=True,
                    key=key,
                    method=method_name,
                    payload=payload,
                    duration_ms=int((time.monotonic() - started) * 1000),
                    metadata={"call_style": "positional", "arg_count": len(args)},
                )
            except TypeError as exc:
                errors.append(f"positional:{safe_str(exc)}")
            except Exception as exc:
                return ServiceCallResult(
                    ok=False,
                    key=key,
                    method=method_name,
                    error=safe_str(exc),
                    duration_ms=int((time.monotonic() - started) * 1000),
                    metadata={"call_style": "positional", "arg_count": len(args)},
                )

        # 3. Try no-arg call.
        try:
            payload = method()
            return ServiceCallResult(
                ok=True,
                key=key,
                method=method_name,
                payload=payload,
                duration_ms=int((time.monotonic() - started) * 1000),
                metadata={"call_style": "no_args"},
            )
        except TypeError as exc:
            errors.append(f"no_args:{safe_str(exc)}")
        except Exception as exc:
            return ServiceCallResult(
                ok=False,
                key=key,
                method=method_name,
                error=safe_str(exc),
                duration_ms=int((time.monotonic() - started) * 1000),
                metadata={"call_style": "no_args"},
            )

        # 4. Try dict payload as single arg.
        try:
            payload = method(dict(kwargs))
            return ServiceCallResult(
                ok=True,
                key=key,
                method=method_name,
                payload=payload,
                duration_ms=int((time.monotonic() - started) * 1000),
                metadata={"call_style": "dict_arg"},
            )
        except TypeError as exc:
            errors.append(f"dict_arg:{safe_str(exc)}")
        except Exception as exc:
            return ServiceCallResult(
                ok=False,
                key=key,
                method=method_name,
                error=safe_str(exc),
                duration_ms=int((time.monotonic() - started) * 1000),
                metadata={"call_style": "dict_arg"},
            )

        return ServiceCallResult(
            ok=False,
            key=key,
            method=method_name,
            error="; ".join(errors) or "method_call_failed",
            duration_ms=int((time.monotonic() - started) * 1000),
        )


_DEFAULT_SERVICE_LOCK = threading.RLock()
_DEFAULT_SERVICE: Optional[LibraryGeneratorContextService] = None


def get_library_generator_context_service(
    force_new: bool = False,
) -> LibraryGeneratorContextService:
    global _DEFAULT_SERVICE

    with _DEFAULT_SERVICE_LOCK:
        if force_new or _DEFAULT_SERVICE is None:
            _DEFAULT_SERVICE = LibraryGeneratorContextService()
        return _DEFAULT_SERVICE


def get_generator_context(
    request: Any = None,
    force_refresh: Optional[bool] = None,
    use_cache: Optional[bool] = None,
) -> GeneratorContext:
    return get_library_generator_context_service().get_context(
        request=request,
        force_refresh=force_refresh,
        use_cache=use_cache,
    )


def get_generator_context_payload(
    request: Any = None,
    mode: Any = GeneratorContextViewMode.PUBLIC,
    build_options: Any = None,
    force_refresh: Optional[bool] = None,
    use_cache: Optional[bool] = None,
) -> Dict[str, Any]:
    return get_library_generator_context_service().get_context_payload(
        request=request,
        mode=mode,
        build_options=build_options,
        force_refresh=force_refresh,
        use_cache=use_cache,
    )


def get_generator_frontend_context(
    request: Any = None,
    build_options: Any = None,
    force_refresh: Optional[bool] = None,
    use_cache: Optional[bool] = None,
) -> Dict[str, Any]:
    return get_library_generator_context_service().get_frontend_context(
        request=request,
        build_options=build_options,
        force_refresh=force_refresh,
        use_cache=use_cache,
    )


def get_generator_create_options(
    request: Any = None,
    build_options: Any = None,
    force_refresh: Optional[bool] = None,
    use_cache: Optional[bool] = None,
) -> Dict[str, Any]:
    return get_library_generator_context_service().get_create_options(
        request=request,
        build_options=build_options,
        force_refresh=force_refresh,
        use_cache=use_cache,
    )


def get_generator_diagnostics(
    request: Any = None,
    build_options: Any = None,
    force_refresh: Optional[bool] = None,
    use_cache: Optional[bool] = None,
) -> Dict[str, Any]:
    return get_library_generator_context_service().get_diagnostics(
        request=request,
        build_options=build_options,
        force_refresh=force_refresh,
        use_cache=use_cache,
    )


def get_library_generator_context_service_health(
    check_dependencies: bool = True,
    include_cache: bool = True,
) -> Dict[str, Any]:
    return get_library_generator_context_service().get_health(
        check_dependencies=check_dependencies,
        include_cache=include_cache,
    )


def assert_library_generator_context_service_ready(
    require_dependencies: bool = False,
) -> bool:
    return get_library_generator_context_service().assert_ready(
        require_dependencies=require_dependencies,
    )


def clear_library_generator_context_service_caches() -> Dict[str, Any]:
    return get_library_generator_context_service().clear_caches()


__all__ = [
    "LIBRARY_GENERATOR_CONTEXT_SERVICE_COMPONENT",
    "LIBRARY_GENERATOR_CONTEXT_SERVICE_SCHEMA_VERSION",
    "DEFAULT_SERVICE_CACHE_TTL_SECONDS",
    "DEFAULT_SERVICE_CACHE_MAX_ENTRIES",
    "LibraryGeneratorContextRequest",
    "DependencyResolution",
    "ServiceCallResult",
    "LibraryGeneratorContextService",
    "get_library_generator_context_service",
    "get_generator_context",
    "get_generator_context_payload",
    "get_generator_frontend_context",
    "get_generator_create_options",
    "get_generator_diagnostics",
    "get_library_generator_context_service_health",
    "assert_library_generator_context_service_ready",
    "clear_library_generator_context_service_caches",
]