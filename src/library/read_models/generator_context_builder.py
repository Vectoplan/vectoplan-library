# src/library/read_models/generator_context_builder.py
from __future__ import annotations

"""
Read-model builders for the VPLIB generator context.

This module converts the internal domain model from
`src/library/domain/generator_context.py` into stable API/UI payloads.

Intentional boundaries:
- no Flask imports
- no SQLAlchemy imports
- no repository imports
- no service imports
- no file-system writes
- no HTTP calls

The builder can be used by:
- `library_generator_context_service.py`
- `routes/create.py`
- diagnostics/selftest endpoints
- template context generation
- tests

It is defensive by design. Malformed or partial input is normalized into
stable payloads with diagnostics instead of crashing where possible.
"""

import copy
import json
import time
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Callable, Dict, Iterable, List, Mapping, Optional, Sequence, Tuple, Union

try:
    from ..domain.generator_context import (
        DEFAULT_CREATE_API_ROUTES,
        DEFAULT_DEFINITION_API_ROUTES,
        DEFAULT_DRAFT_API_ROUTES,
        DEFAULT_FILE_API_ROUTES,
        DEFAULT_GENERATOR_ROUTES,
        DEFAULT_INVENTORY_KEY,
        DEFAULT_TAXONOMY_API_ROUTES,
        DEFAULT_USER_ID,
        GENERATOR_CONTEXT_COMPONENT,
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
        GeneratorDefinitionContext,
        GeneratorDraftContext,
        GeneratorFileContext,
        GeneratorPublishedContext,
        GeneratorRouteContext,
        GeneratorRouteRef,
        GeneratorTaxonomyContext,
        GeneratorUploadContext,
        GeneratorUserContext,
        build_minimal_generator_context,
        get_default_generator_context_cache,
        merge_mappings,
        normalize_action,
        normalize_key,
        normalize_slug,
        parse_json_safe,
        safe_bool,
        safe_deepcopy,
        safe_float,
        safe_int,
        safe_list,
        safe_mapping,
        safe_str,
        stable_hash,
        stable_json_dumps,
        to_json_compatible,
        try_cache_get_or_set,
        utc_now_iso,
    )
except Exception:  # pragma: no cover - import fallback for non-package execution
    from library.domain.generator_context import (
        DEFAULT_CREATE_API_ROUTES,
        DEFAULT_DEFINITION_API_ROUTES,
        DEFAULT_DRAFT_API_ROUTES,
        DEFAULT_FILE_API_ROUTES,
        DEFAULT_GENERATOR_ROUTES,
        DEFAULT_INVENTORY_KEY,
        DEFAULT_TAXONOMY_API_ROUTES,
        DEFAULT_USER_ID,
        GENERATOR_CONTEXT_COMPONENT,
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
        GeneratorDefinitionContext,
        GeneratorDraftContext,
        GeneratorFileContext,
        GeneratorPublishedContext,
        GeneratorRouteContext,
        GeneratorRouteRef,
        GeneratorTaxonomyContext,
        GeneratorUploadContext,
        GeneratorUserContext,
        build_minimal_generator_context,
        get_default_generator_context_cache,
        merge_mappings,
        normalize_action,
        normalize_key,
        normalize_slug,
        parse_json_safe,
        safe_bool,
        safe_deepcopy,
        safe_float,
        safe_int,
        safe_list,
        safe_mapping,
        safe_str,
        stable_hash,
        stable_json_dumps,
        to_json_compatible,
        try_cache_get_or_set,
        utc_now_iso,
    )


GENERATOR_CONTEXT_BUILDER_COMPONENT = "library.read_models.generator_context_builder"
GENERATOR_CONTEXT_BUILDER_SCHEMA_VERSION = "generator_context_builder.v1"
DEFAULT_BUILDER_CACHE_TTL_SECONDS = 30
DEFAULT_BUILDER_RECORD_LIMIT = 500
DEFAULT_COMPACT_RECORD_LIMIT = 100

FRONTEND_WINDOW_CONTEXT_NAME = "VectoplanCreateContext"
FRONTEND_WINDOW_UPLOAD_CONFIG_NAME = "VectoplanCreateUploadConfig"
FRONTEND_WINDOW_DEFINITION_CONTEXT_NAME = "VectoplanDefinitionContext"
FRONTEND_WINDOW_TAXONOMY_CONTEXT_NAME = "VectoplanTaxonomyContext"

DEFAULT_FRONTEND_STEP_CONFIG: List[Dict[str, Any]] = [
    {
        "index": 1,
        "key": "identity",
        "label": "Grunddaten",
        "technical_key": "identity",
        "required": True,
    },
    {
        "index": 2,
        "key": "taxonomy",
        "label": "Taxonomie",
        "technical_key": "taxonomy",
        "required": True,
    },
    {
        "index": 3,
        "key": "variables",
        "label": "Variablen",
        "technical_key": "object-variants",
        "aliases": ["object", "object-variants", "variables"],
        "required": True,
    },
    {
        "index": 4,
        "key": "geometry",
        "label": "Geometrie",
        "technical_key": "geometry",
        "required": True,
    },
    {
        "index": 5,
        "key": "technical",
        "label": "Technik",
        "technical_key": "technical",
        "required": False,
    },
    {
        "index": 6,
        "key": "actions",
        "label": "Erzeugen",
        "technical_key": "actions",
        "required": True,
    },
]


class GeneratorContextViewMode(str, Enum):
    FULL = "full"
    PUBLIC = "public"
    FRONTEND = "frontend"
    OPTIONS = "options"
    DIAGNOSTICS = "diagnostics"
    HEALTH = "health"
    TEST = "test"
    COMPACT = "compact"

    def __str__(self) -> str:
        return self.value


@dataclass
class GeneratorContextBuildOptions:
    """
    Controls how large or detailed generated payloads should be.

    These options are intentionally transport-neutral. The same builder can be
    used by HTTP routes, service diagnostics, unit tests or prestart checks.
    """

    include_diagnostics: bool = True
    include_raw_payloads: bool = False
    include_routes: bool = True
    include_records: bool = True
    include_record_maps: bool = False
    include_empty_sections: bool = True
    include_metadata: bool = True
    include_request_payload: bool = False
    include_generator_payload: bool = False
    compact: bool = False
    max_records: int = DEFAULT_BUILDER_RECORD_LIMIT
    max_compact_records: int = DEFAULT_COMPACT_RECORD_LIMIT
    sort_records: bool = True
    route_prefix: str = ""
    locale: str = "de"
    user_id: Optional[int] = DEFAULT_USER_ID
    inventory_key: str = DEFAULT_INVENTORY_KEY
    source: str = ""
    cache_ttl_seconds: int = DEFAULT_BUILDER_CACHE_TTL_SECONDS
    cache_enabled: bool = True
    allow_stale_cache_on_error: bool = True

    @classmethod
    def from_mapping(cls, value: Any) -> "GeneratorContextBuildOptions":
        data = safe_mapping(value)
        return cls(
            include_diagnostics=safe_bool(data.get("include_diagnostics"), True),
            include_raw_payloads=safe_bool(data.get("include_raw_payloads"), False),
            include_routes=safe_bool(data.get("include_routes"), True),
            include_records=safe_bool(data.get("include_records"), True),
            include_record_maps=safe_bool(data.get("include_record_maps"), False),
            include_empty_sections=safe_bool(data.get("include_empty_sections"), True),
            include_metadata=safe_bool(data.get("include_metadata"), True),
            include_request_payload=safe_bool(data.get("include_request_payload"), False),
            include_generator_payload=safe_bool(data.get("include_generator_payload"), False),
            compact=safe_bool(data.get("compact"), False),
            max_records=max(0, int(safe_int(data.get("max_records"), DEFAULT_BUILDER_RECORD_LIMIT) or 0)),
            max_compact_records=max(
                0,
                int(safe_int(data.get("max_compact_records"), DEFAULT_COMPACT_RECORD_LIMIT) or 0),
            ),
            sort_records=safe_bool(data.get("sort_records"), True),
            route_prefix=safe_str(data.get("route_prefix"), ""),
            locale=safe_str(data.get("locale"), "de"),
            user_id=safe_int(data.get("user_id"), DEFAULT_USER_ID),
            inventory_key=normalize_key(data.get("inventory_key"), DEFAULT_INVENTORY_KEY),
            source=safe_str(data.get("source"), ""),
            cache_ttl_seconds=max(0, int(safe_int(data.get("cache_ttl_seconds"), DEFAULT_BUILDER_CACHE_TTL_SECONDS) or 0)),
            cache_enabled=safe_bool(data.get("cache_enabled"), True),
            allow_stale_cache_on_error=safe_bool(data.get("allow_stale_cache_on_error"), True),
        )

    def to_dict(self) -> Dict[str, Any]:
        return to_json_compatible(self)

    def cache_fragment(self) -> str:
        return stable_hash(self.to_dict(), prefix="build_options")


@dataclass
class GeneratorContextBuildResult:
    ok: bool
    status: str
    mode: str
    payload: Dict[str, Any]
    diagnostics: GeneratorContextDiagnostics = field(default_factory=GeneratorContextDiagnostics)
    built_at: str = field(default_factory=utc_now_iso)
    duration_ms: Optional[int] = None
    cache_key: Optional[str] = None
    cache_hit: bool = False
    cache_stale: bool = False
    metadata: Dict[str, Any] = field(default_factory=dict)

    def to_dict(self, include_payload: bool = True) -> Dict[str, Any]:
        result = {
            "ok": self.ok,
            "status": self.status,
            "mode": self.mode,
            "built_at": self.built_at,
            "duration_ms": self.duration_ms,
            "cache_key": self.cache_key,
            "cache_hit": self.cache_hit,
            "cache_stale": self.cache_stale,
            "diagnostics": self.diagnostics.to_dict(),
            "metadata": to_json_compatible(self.metadata),
        }
        if include_payload:
            result["payload"] = to_json_compatible(self.payload)
        return result


def _mode(value: Any, default: GeneratorContextViewMode = GeneratorContextViewMode.PUBLIC) -> GeneratorContextViewMode:
    if isinstance(value, GeneratorContextViewMode):
        return value

    text = normalize_key(value, default="")
    if not text:
        return default

    text = text.replace("_", "-")
    aliases = {
        "api": GeneratorContextViewMode.PUBLIC,
        "ui": GeneratorContextViewMode.FRONTEND,
        "create": GeneratorContextViewMode.FRONTEND,
        "create-options": GeneratorContextViewMode.OPTIONS,
        "diag": GeneratorContextViewMode.DIAGNOSTICS,
        "selftest": GeneratorContextViewMode.TEST,
    }
    if text in aliases:
        return aliases[text]

    for item in GeneratorContextViewMode:
        if text == item.value:
            return item

    return default


def _status_value(value: Any) -> str:
    if isinstance(value, Enum):
        return safe_str(value.value, "unknown")
    return normalize_key(value, "unknown")


def _issue_to_dict(issue: Any) -> Dict[str, Any]:
    parsed = issue if isinstance(issue, GeneratorContextIssue) else GeneratorContextIssue.from_mapping(issue)
    return parsed.to_dict()


def _diagnostics_summary(diagnostics: Any) -> Dict[str, Any]:
    parsed = diagnostics if isinstance(diagnostics, GeneratorContextDiagnostics) else GeneratorContextDiagnostics.from_mapping(diagnostics)
    return {
        "status": _status_value(parsed.status),
        "healthy": parsed.healthy,
        "issue_count": parsed.issue_count,
        "warning_count": parsed.warning_count,
        "error_count": parsed.error_count,
        "fatal_count": parsed.fatal_count,
        "blocking_count": parsed.blocking_count,
        "checked_at": parsed.checked_at,
        "duration_ms": parsed.duration_ms,
    }


def _diagnostics_payload(
    diagnostics: Any,
    include_issues: bool = True,
    max_issues: int = DEFAULT_BUILDER_RECORD_LIMIT,
) -> Dict[str, Any]:
    parsed = diagnostics if isinstance(diagnostics, GeneratorContextDiagnostics) else GeneratorContextDiagnostics.from_mapping(diagnostics)
    payload = _diagnostics_summary(parsed)
    if include_issues:
        payload["issues"] = [_issue_to_dict(issue) for issue in parsed.issues[:max_issues]]
    if parsed.timings_ms:
        payload["timings_ms"] = dict(parsed.timings_ms)
    if parsed.metadata:
        payload["metadata"] = to_json_compatible(parsed.metadata)
    return payload


def _context_from_any(value: Any) -> GeneratorContext:
    if isinstance(value, GeneratorContext):
        return value

    if isinstance(value, Mapping):
        return GeneratorContext.from_mapping(value)

    if value is None:
        return build_minimal_generator_context()

    try:
        mapping = json.loads(str(value))
        if isinstance(mapping, Mapping):
            return GeneratorContext.from_mapping(mapping)
    except Exception:
        pass

    return build_minimal_generator_context(metadata={"input_type": type(value).__name__})


def _safe_dict(value: Any, include_none: bool = False) -> Dict[str, Any]:
    payload = to_json_compatible(value, include_none=include_none)
    return payload if isinstance(payload, dict) else {"value": payload}


def _safe_public_value(value: Any) -> Any:
    return to_json_compatible(value, include_none=False)


def _copy_dict(value: Any) -> Dict[str, Any]:
    try:
        payload = copy.deepcopy(value)
    except Exception:
        payload = value
    return safe_mapping(payload)


def _pick(record: Mapping[str, Any], *keys: str, default: Any = None) -> Any:
    for key in keys:
        if key in record and record[key] is not None:
            return record[key]
    return default


def _record_key(record: Mapping[str, Any], fallback: str = "") -> str:
    for key in (
        "key",
        "id",
        "uid",
        "slug",
        "name",
        "variable_key",
        "unit_id",
        "material_id",
        "document_type_id",
        "object_kind_id",
        "family_profile_id",
        "variant_profile_id",
        "profile_id",
        "binding_id",
        "node_key",
        "taxonomy_path",
    ):
        value = normalize_key(record.get(key), "")
        if value:
            return value
    return normalize_key(fallback, "")


def _record_label(record: Mapping[str, Any], fallback: str = "") -> str:
    for key in ("label", "name", "title", "display_name", "displayName", "key", "id"):
        value = safe_str(record.get(key), "")
        if value:
            return value
    return fallback


def _record_description(record: Mapping[str, Any]) -> str:
    for key in ("description", "summary", "help", "tooltip"):
        value = safe_str(record.get(key), "")
        if value:
            return value
    return ""


def _record_sort_value(record: Mapping[str, Any]) -> Tuple[int, str]:
    sort_order = safe_int(_pick(record, "sort_order", "order", "position", default=999999), 999999)
    label = _record_label(record)
    return int(sort_order or 999999), label.lower()


def _compact_record(
    record: Mapping[str, Any],
    fallback_key: str = "",
    include_extra: bool = True,
) -> Dict[str, Any]:
    key = _record_key(record, fallback=fallback_key)
    payload: Dict[str, Any] = {
        "key": key,
        "id": safe_str(_pick(record, "id", "uid", "key", default=key), key),
        "label": _record_label(record, fallback=key),
    }

    description = _record_description(record)
    if description:
        payload["description"] = description

    for source_key, target_key in (
        ("value_type", "value_type"),
        ("widget", "widget"),
        ("unit", "unit"),
        ("unit_id", "unit_id"),
        ("document_type", "document_type"),
        ("object_kind", "object_kind"),
        ("family_profile_id", "family_profile_id"),
        ("variant_profile_id", "variant_profile_id"),
        ("domain", "domain"),
        ("category", "category"),
        ("subcategory", "subcategory"),
        ("taxonomy_path", "taxonomy_path"),
        ("required", "required"),
        ("required_default", "required"),
        ("active", "active"),
        ("visible", "visible"),
        ("status", "status"),
        ("sort_order", "sort_order"),
    ):
        if source_key in record and record[source_key] is not None:
            payload[target_key] = _safe_public_value(record[source_key])

    if include_extra:
        for source_key in (
            "options",
            "options_json",
            "default_value",
            "default_values",
            "default_values_json",
            "sections",
            "sections_json",
            "required_fields",
            "required_fields_json",
            "optional_fields",
            "optional_fields_json",
            "summary_fields",
            "summary_fields_json",
            "document_types",
            "document_types_json",
            "allowed_extensions",
            "allowed_extensions_json",
            "allowed_mime_types",
            "allowed_mime_types_json",
            "max_size_mb",
            "multiple",
            "upload_group",
            "future_overlay_ready",
            "supports_product_like_variants",
        ):
            if source_key in record and record[source_key] is not None:
                payload[source_key] = _safe_public_value(record[source_key])

    return payload


def _records_from_map(
    records: Mapping[str, Mapping[str, Any]],
    options: GeneratorContextBuildOptions,
    compact: Optional[bool] = None,
) -> List[Dict[str, Any]]:
    if not records:
        return []

    use_compact = options.compact if compact is None else compact
    max_records = options.max_compact_records if use_compact else options.max_records

    items: List[Tuple[str, Dict[str, Any]]] = []
    for key, record in records.items():
        if isinstance(record, Mapping):
            items.append((safe_str(key), dict(record)))

    if options.sort_records:
        items.sort(key=lambda pair: _record_sort_value(pair[1]))

    limited = items[:max_records] if max_records > 0 else items

    if use_compact:
        return [_compact_record(record, fallback_key=key, include_extra=False) for key, record in limited]

    return [
        {
            **_compact_record(record, fallback_key=key, include_extra=True),
            "payload": _safe_public_value(record) if options.include_raw_payloads else None,
        }
        for key, record in limited
    ]


def _maybe_drop_none(payload: Dict[str, Any]) -> Dict[str, Any]:
    return {key: value for key, value in payload.items() if value is not None}


def _maybe_include(condition: bool, value: Any) -> Any:
    return value if condition else None


def _routes_payload(
    routes: GeneratorRouteContext,
    options: GeneratorContextBuildOptions,
) -> Dict[str, Any]:
    route_items: Dict[str, Any] = {}
    for key, route in sorted(routes.routes.items()):
        path = route.path
        if options.route_prefix and path.startswith("/"):
            path = f"{options.route_prefix.rstrip('/')}{path}"
        route_items[key] = {
            "key": route.key,
            "path": path,
            "method": route.method,
            "required": route.required,
            "available": route.available,
            "description": route.description,
        }

    payload = {
        "status": _status_value(routes.status),
        "source": _status_value(routes.source),
        "loaded_at": routes.loaded_at,
        "routes": route_items,
    }

    if options.include_diagnostics:
        payload["diagnostics"] = _diagnostics_payload(routes.diagnostics, max_issues=options.max_records)

    return payload


def _section_status_payload(context: GeneratorContext) -> Dict[str, Any]:
    return {
        "routes": _status_value(context.routes.status),
        "definitions": _status_value(context.definitions.status),
        "taxonomy": _status_value(context.taxonomy.status),
        "uploads": _status_value(context.uploads.status),
        "files": _status_value(context.files.status),
        "draft": _status_value(context.draft.status),
        "published": _status_value(context.published.status),
        "capabilities": "ready",
        "diagnostics": _status_value(context.diagnostics.status),
    }


def _counts_payload(context: GeneratorContext) -> Dict[str, Any]:
    definitions = context.definitions
    taxonomy = context.taxonomy
    uploads = context.uploads
    files = context.files
    draft = context.draft
    published = context.published

    return {
        "routes": len(context.routes.routes),
        "datasets": len(definitions.datasets),
        "variables": len(definitions.variables),
        "units": len(definitions.units),
        "materials": len(definitions.materials),
        "document_types": len(definitions.document_types),
        "object_kinds": len(definitions.object_kinds),
        "family_profiles": len(definitions.family_profiles),
        "variant_profiles": len(definitions.variant_profiles),
        "profile_bindings": len(definitions.profile_bindings),
        "taxonomy_nodes": len(taxonomy.nodes),
        "allowed_extensions": len(uploads.allowed_extensions),
        "blocked_extensions": len(uploads.blocked_extensions),
        "files": len(files.files),
        "file_versions": len(files.versions),
        "file_links": len(files.links),
        "draft_variants": len(draft.variants),
        "draft_assets": len(draft.assets),
        "draft_documents": len(draft.documents),
        "published_variants": len(published.variants),
        "published_assets": len(published.assets),
        "published_documents": len(published.documents),
        "issues": context.diagnostics.issue_count,
        "blocking_issues": context.diagnostics.blocking_count,
    }


@dataclass
class GeneratorContextBuilder:
    """
    Converts `GeneratorContext` domain objects into API/UI read models.

    This class deliberately contains no infrastructure access. It can safely be
    instantiated in tests, route handlers or service layers.
    """

    cache: Optional[GeneratorContextMemoryCache] = None
    default_options: GeneratorContextBuildOptions = field(default_factory=GeneratorContextBuildOptions)
    component: str = GENERATOR_CONTEXT_BUILDER_COMPONENT
    schema_version: str = GENERATOR_CONTEXT_BUILDER_SCHEMA_VERSION

    def __post_init__(self) -> None:
        if self.cache is None:
            self.cache = GeneratorContextMemoryCache(
                default_ttl_seconds=self.default_options.cache_ttl_seconds,
                name="generator_context_builder_cache",
            )

    def normalize_context(self, context: Any) -> GeneratorContext:
        try:
            parsed = _context_from_any(context)
            parsed.refresh_status()
            return parsed
        except Exception as exc:
            fallback = build_minimal_generator_context(
                metadata={
                    "builder_error": safe_str(exc),
                    "input_type": type(context).__name__,
                }
            )
            fallback.diagnostics.add_error(
                "generator_context_parse_failed",
                "Could not normalize generator context.",
                GeneratorContextSection.ROOT,
                error=safe_str(exc),
            )
            fallback.refresh_status()
            return fallback

    def normalize_options(self, options: Any = None) -> GeneratorContextBuildOptions:
        if isinstance(options, GeneratorContextBuildOptions):
            return options
        if options is None:
            return copy.deepcopy(self.default_options)
        return GeneratorContextBuildOptions.from_mapping(options)

    def build(
        self,
        context: Any,
        mode: Any = GeneratorContextViewMode.PUBLIC,
        options: Any = None,
        use_cache: Optional[bool] = None,
    ) -> GeneratorContextBuildResult:
        parsed_mode = _mode(mode)
        parsed_context = self.normalize_context(context)
        parsed_options = self.normalize_options(options)
        should_cache = parsed_options.cache_enabled if use_cache is None else bool(use_cache)

        if should_cache:
            cache_key = self.build_cache_key(parsed_context, parsed_mode, parsed_options)

            def factory() -> GeneratorContextBuildResult:
                return self._build_uncached(parsed_context, parsed_mode, parsed_options, cache_key=cache_key)

            cache_result = try_cache_get_or_set(
                key=cache_key,
                factory=factory,
                ttl_seconds=parsed_options.cache_ttl_seconds,
                cache=self.cache,
                allow_stale_on_error=parsed_options.allow_stale_cache_on_error,
                fallback=self._build_uncached(parsed_context, parsed_mode, parsed_options, cache_key=cache_key),
                metadata={
                    "builder_component": self.component,
                    "mode": parsed_mode.value,
                },
            )

            result = cache_result.value
            if isinstance(result, GeneratorContextBuildResult):
                result.cache_key = cache_key
                result.cache_hit = cache_result.hit
                result.cache_stale = cache_result.stale
                if cache_result.error:
                    result.diagnostics.add_warning(
                        "generator_context_builder_cache_warning",
                        "Generator context builder cache returned a warning.",
                        GeneratorContextSection.DIAGNOSTICS,
                        error=cache_result.error,
                    )
                return result

        return self._build_uncached(parsed_context, parsed_mode, parsed_options)

    def _build_uncached(
        self,
        context: GeneratorContext,
        mode: GeneratorContextViewMode,
        options: GeneratorContextBuildOptions,
        cache_key: Optional[str] = None,
    ) -> GeneratorContextBuildResult:
        started = time.monotonic()
        diagnostics = GeneratorContextDiagnostics()
        payload: Dict[str, Any]

        try:
            if mode == GeneratorContextViewMode.FULL:
                payload = self.build_full_context_payload(context, options)
            elif mode == GeneratorContextViewMode.PUBLIC:
                payload = self.build_public_context_payload(context, options)
            elif mode == GeneratorContextViewMode.FRONTEND:
                payload = self.build_frontend_context_payload(context, options)
            elif mode == GeneratorContextViewMode.OPTIONS:
                payload = self.build_create_options_payload(context, options)
            elif mode == GeneratorContextViewMode.DIAGNOSTICS:
                payload = self.build_diagnostics_payload(context, options)
            elif mode == GeneratorContextViewMode.HEALTH:
                payload = self.build_health_payload(context, options)
            elif mode == GeneratorContextViewMode.TEST:
                payload = self.build_test_snapshot_payload(context, options)
            elif mode == GeneratorContextViewMode.COMPACT:
                compact_options = copy.deepcopy(options)
                compact_options.compact = True
                payload = self.build_public_context_payload(context, compact_options)
            else:
                payload = self.build_public_context_payload(context, options)

            diagnostics.merge(context.diagnostics)
        except Exception as exc:
            diagnostics.add_error(
                "generator_context_build_failed",
                "Failed to build generator context read model.",
                GeneratorContextSection.DIAGNOSTICS,
                error=safe_str(exc),
                mode=mode.value,
            )
            payload = self.build_error_payload(context, diagnostics, options)

        duration_ms = int((time.monotonic() - started) * 1000)
        diagnostics.duration_ms = duration_ms
        diagnostics.refresh()

        status = _status_value(payload.get("status") or diagnostics.status)
        ok = diagnostics.blocking_count == 0 and status not in {
            GeneratorContextStatus.ERROR.value,
            GeneratorContextStatus.INVALID.value,
        }

        return GeneratorContextBuildResult(
            ok=ok,
            status=status,
            mode=mode.value,
            payload=payload,
            diagnostics=diagnostics,
            duration_ms=duration_ms,
            cache_key=cache_key,
            metadata={
                "builder_component": self.component,
                "builder_schema_version": self.schema_version,
            },
        )

    def build_cache_key(
        self,
        context: GeneratorContext,
        mode: GeneratorContextViewMode,
        options: GeneratorContextBuildOptions,
    ) -> str:
        return stable_hash(
            {
                "component": self.component,
                "schema_version": self.schema_version,
                "mode": mode.value,
                "context_hash": context.stable_hash(),
                "options": options.cache_fragment(),
            },
            prefix="generator_context_builder",
        )

    def build_full_context_payload(
        self,
        context: Any,
        options: Any = None,
    ) -> Dict[str, Any]:
        parsed_context = self.normalize_context(context)
        parsed_options = self.normalize_options(options)

        payload = parsed_context.to_public_dict(include_diagnostics=parsed_options.include_diagnostics)

        if not parsed_options.include_raw_payloads:
            payload.pop("request_payload", None)
            payload.pop("generator_payload", None)
            if "definitions" in payload:
                payload["definitions"].pop("raw_payload", None)
            if "draft" in payload:
                payload["draft"].pop("context_snapshot", None)

        if not parsed_options.include_routes:
            payload.pop("routes", None)

        return self._wrap_payload(
            payload=payload,
            context=parsed_context,
            options=parsed_options,
            kind="full_context",
        )

    def build_public_context_payload(
        self,
        context: Any,
        options: Any = None,
    ) -> Dict[str, Any]:
        parsed_context = self.normalize_context(context)
        parsed_options = self.normalize_options(options)

        payload: Dict[str, Any] = {
            "schema_version": GENERATOR_CONTEXT_SCHEMA_VERSION,
            "builder_schema_version": self.schema_version,
            "context_uid": parsed_context.context_uid,
            "status": _status_value(parsed_context.status),
            "source": _status_value(parsed_context.source),
            "created_at": parsed_context.created_at,
            "loaded_at": parsed_context.loaded_at,
            "section_status": _section_status_payload(parsed_context),
            "counts": _counts_payload(parsed_context),
            "user": self.build_user_payload(parsed_context.user, parsed_options),
            "capabilities": self.build_capabilities_payload(parsed_context.capabilities, parsed_options),
            "definitions": self.build_definition_payload(parsed_context.definitions, parsed_options),
            "taxonomy": self.build_taxonomy_payload(parsed_context.taxonomy, parsed_options),
            "uploads": self.build_upload_payload(parsed_context.uploads, parsed_options),
        }

        if parsed_options.include_routes:
            payload["routes"] = _routes_payload(parsed_context.routes, parsed_options)

        if parsed_context.files.status != GeneratorContextStatus.UNAVAILABLE or parsed_options.include_empty_sections:
            payload["files"] = self.build_file_payload(parsed_context.files, parsed_options)

        if parsed_context.draft.status != GeneratorContextStatus.UNAVAILABLE or parsed_options.include_empty_sections:
            payload["draft"] = self.build_draft_payload(parsed_context.draft, parsed_options)

        if parsed_context.published.status != GeneratorContextStatus.UNAVAILABLE or parsed_options.include_empty_sections:
            payload["published"] = self.build_published_payload(parsed_context.published, parsed_options)

        if parsed_options.include_request_payload:
            payload["request_payload"] = _safe_public_value(parsed_context.request_payload)

        if parsed_options.include_generator_payload:
            payload["generator_payload"] = _safe_public_value(parsed_context.generator_payload)

        if parsed_options.include_diagnostics:
            payload["diagnostics"] = _diagnostics_payload(
                parsed_context.diagnostics,
                max_issues=parsed_options.max_records,
            )

        if parsed_options.include_metadata:
            payload["metadata"] = {
                "component": GENERATOR_CONTEXT_COMPONENT,
                "builder_component": self.component,
                "builder_schema_version": self.schema_version,
                **_copy_dict(parsed_context.metadata),
            }

        return self._wrap_payload(
            payload=payload,
            context=parsed_context,
            options=parsed_options,
            kind="public_context",
        )

    def build_frontend_context_payload(
        self,
        context: Any,
        options: Any = None,
    ) -> Dict[str, Any]:
        parsed_context = self.normalize_context(context)
        parsed_options = self.normalize_options(options)

        create_options = self.build_create_options_payload(parsed_context, parsed_options)
        routes = _routes_payload(parsed_context.routes, parsed_options)

        upload_config = {
            "status": _status_value(parsed_context.uploads.status),
            "constraints": _safe_public_value(parsed_context.uploads.constraints),
            "allowed_extensions": list(parsed_context.uploads.allowed_extensions),
            "blocked_extensions": list(parsed_context.uploads.blocked_extensions),
            "allowed_mime_types": list(parsed_context.uploads.allowed_mime_types),
            "blocked_mime_types": list(parsed_context.uploads.blocked_mime_types),
            "max_size_mb": parsed_context.uploads.max_size_mb,
            "max_size_bytes": parsed_context.uploads.max_size_bytes,
            "storage_backends": list(parsed_context.uploads.storage_backends),
            "document_types": _records_from_map(parsed_context.uploads.document_types, parsed_options, compact=True),
            "upload_groups": _records_from_map(parsed_context.uploads.upload_groups, parsed_options, compact=True),
            "metadata_fields": [
                "geometry_model_uploads_json",
                "technical_document_uploads_json",
                "variant_document_uploads_json",
            ],
        }

        frontend_context = {
            "schema_version": GENERATOR_CONTEXT_SCHEMA_VERSION,
            "builder_schema_version": self.schema_version,
            "context_uid": parsed_context.context_uid,
            "status": _status_value(parsed_context.status),
            "generated_at": utc_now_iso(),
            "locale": parsed_options.locale,
            "steps": copy.deepcopy(DEFAULT_FRONTEND_STEP_CONFIG),
            "api": {
                "routes": routes.get("routes", {}),
                "create": {
                    key: routes.get("routes", {}).get(key, {}).get("path", path)
                    for key, path in DEFAULT_CREATE_API_ROUTES.items()
                },
                "definitions": {
                    key: routes.get("routes", {}).get(key, {}).get("path", path)
                    for key, path in DEFAULT_DEFINITION_API_ROUTES.items()
                },
                "taxonomy": {
                    key: routes.get("routes", {}).get(key, {}).get("path", path)
                    for key, path in DEFAULT_TAXONOMY_API_ROUTES.items()
                },
                "files": {
                    key: routes.get("routes", {}).get(key, {}).get("path", path)
                    for key, path in DEFAULT_FILE_API_ROUTES.items()
                },
                "drafts": {
                    key: routes.get("routes", {}).get(key, {}).get("path", path)
                    for key, path in DEFAULT_DRAFT_API_ROUTES.items()
                },
            },
            "user": self.build_user_payload(parsed_context.user, parsed_options),
            "capabilities": self.build_capabilities_payload(parsed_context.capabilities, parsed_options),
            "options": create_options.get("data", create_options),
            "definition_context": self.build_definition_payload(parsed_context.definitions, parsed_options),
            "taxonomy_context": self.build_taxonomy_payload(parsed_context.taxonomy, parsed_options),
            "upload_config": upload_config,
            "payload_contract": self.build_payload_contract_payload(parsed_context, parsed_options),
            "section_status": _section_status_payload(parsed_context),
            "counts": _counts_payload(parsed_context),
        }

        if parsed_options.include_diagnostics:
            frontend_context["diagnostics"] = _diagnostics_payload(
                parsed_context.diagnostics,
                max_issues=parsed_options.max_records,
            )

        window_payload = {
            FRONTEND_WINDOW_CONTEXT_NAME: frontend_context,
            FRONTEND_WINDOW_UPLOAD_CONFIG_NAME: upload_config,
            FRONTEND_WINDOW_DEFINITION_CONTEXT_NAME: frontend_context["definition_context"],
            FRONTEND_WINDOW_TAXONOMY_CONTEXT_NAME: frontend_context["taxonomy_context"],
        }

        payload = {
            "schema_version": self.schema_version,
            "status": _status_value(parsed_context.status),
            "generated_at": utc_now_iso(),
            "data": frontend_context,
            "window_payload": window_payload,
            "window_names": {
                "context": FRONTEND_WINDOW_CONTEXT_NAME,
                "upload_config": FRONTEND_WINDOW_UPLOAD_CONFIG_NAME,
                "definition_context": FRONTEND_WINDOW_DEFINITION_CONTEXT_NAME,
                "taxonomy_context": FRONTEND_WINDOW_TAXONOMY_CONTEXT_NAME,
            },
        }

        return self._wrap_payload(
            payload=payload,
            context=parsed_context,
            options=parsed_options,
            kind="frontend_context",
        )

    def build_create_options_payload(
        self,
        context: Any,
        options: Any = None,
    ) -> Dict[str, Any]:
        parsed_context = self.normalize_context(context)
        parsed_options = self.normalize_options(options)
        definitions = parsed_context.definitions
        taxonomy = parsed_context.taxonomy

        object_kinds = _records_from_map(definitions.object_kinds, parsed_options, compact=parsed_options.compact)
        family_profiles = _records_from_map(definitions.family_profiles, parsed_options, compact=parsed_options.compact)
        variant_profiles = _records_from_map(definitions.variant_profiles, parsed_options, compact=parsed_options.compact)
        document_types = _records_from_map(definitions.document_types, parsed_options, compact=parsed_options.compact)
        variables = _records_from_map(definitions.variables, parsed_options, compact=True)
        materials = _records_from_map(definitions.materials, parsed_options, compact=True)
        units = _records_from_map(definitions.units, parsed_options, compact=True)
        profile_bindings = _records_from_map(definitions.profile_bindings, parsed_options, compact=True)

        data = {
            "schema_version": self.schema_version,
            "context_uid": parsed_context.context_uid,
            "status": _status_value(parsed_context.status),
            "definitions_version": definitions.definitions_version,
            "taxonomy_selection": taxonomy.selection,
            "taxonomy_path": taxonomy.current_taxonomy_path,
            "object_kinds": object_kinds,
            "family_profiles": family_profiles,
            "variant_profiles": variant_profiles,
            "document_types": document_types,
            "variables": variables,
            "materials": materials,
            "units": units,
            "profile_bindings": profile_bindings,
            "taxonomy": {
                "status": _status_value(taxonomy.status),
                "selection": taxonomy.selection,
                "create_options": _safe_public_value(taxonomy.create_options),
                "tree": _safe_public_value(taxonomy.tree),
            },
            "uploads": {
                "status": _status_value(parsed_context.uploads.status),
                "allowed_extensions": list(parsed_context.uploads.allowed_extensions),
                "blocked_extensions": list(parsed_context.uploads.blocked_extensions),
                "allowed_mime_types": list(parsed_context.uploads.allowed_mime_types),
                "blocked_mime_types": list(parsed_context.uploads.blocked_mime_types),
                "max_size_mb": parsed_context.uploads.max_size_mb,
                "max_size_bytes": parsed_context.uploads.max_size_bytes,
            },
            "capabilities": self.build_capabilities_payload(parsed_context.capabilities, parsed_options),
            "payload_contract": self.build_payload_contract_payload(parsed_context, parsed_options),
            "defaults": self.build_default_values_payload(parsed_context, parsed_options),
        }

        if parsed_options.include_routes:
            data["routes"] = _routes_payload(parsed_context.routes, parsed_options).get("routes", {})

        payload = {
            "ok": parsed_context.status in {GeneratorContextStatus.READY, GeneratorContextStatus.PARTIAL},
            "status": _status_value(parsed_context.status),
            "generated_at": utc_now_iso(),
            "data": data,
        }

        if parsed_options.include_diagnostics:
            payload["diagnostics"] = _diagnostics_payload(
                parsed_context.diagnostics,
                max_issues=parsed_options.max_records,
            )

        return payload

    def build_definition_payload(
        self,
        definitions: Any,
        options: Any = None,
    ) -> Dict[str, Any]:
        parsed_definitions = (
            definitions if isinstance(definitions, GeneratorDefinitionContext) else GeneratorDefinitionContext.from_mapping(definitions)
        )
        parsed_options = self.normalize_options(options)

        payload: Dict[str, Any] = {
            "status": _status_value(parsed_definitions.status),
            "source": _status_value(parsed_definitions.source),
            "schema_version": parsed_definitions.schema_version,
            "definitions_version": parsed_definitions.definitions_version,
            "loaded_at": parsed_definitions.loaded_at,
            "counts": {
                "datasets": len(parsed_definitions.datasets),
                "variables": len(parsed_definitions.variables),
                "units": len(parsed_definitions.units),
                "materials": len(parsed_definitions.materials),
                "document_types": len(parsed_definitions.document_types),
                "object_kinds": len(parsed_definitions.object_kinds),
                "family_profiles": len(parsed_definitions.family_profiles),
                "variant_profiles": len(parsed_definitions.variant_profiles),
                "profile_bindings": len(parsed_definitions.profile_bindings),
                "overrides": len(parsed_definitions.overrides),
            },
        }

        if parsed_options.include_records:
            payload["records"] = {
                "datasets": _records_from_map(parsed_definitions.datasets, parsed_options),
                "variables": _records_from_map(parsed_definitions.variables, parsed_options),
                "units": _records_from_map(parsed_definitions.units, parsed_options),
                "materials": _records_from_map(parsed_definitions.materials, parsed_options),
                "document_types": _records_from_map(parsed_definitions.document_types, parsed_options),
                "object_kinds": _records_from_map(parsed_definitions.object_kinds, parsed_options),
                "family_profiles": _records_from_map(parsed_definitions.family_profiles, parsed_options),
                "variant_profiles": _records_from_map(parsed_definitions.variant_profiles, parsed_options),
                "profile_bindings": _records_from_map(parsed_definitions.profile_bindings, parsed_options),
            }
            if parsed_definitions.overrides:
                payload["records"]["overrides"] = _records_from_map(parsed_definitions.overrides, parsed_options)

        if parsed_options.include_record_maps:
            payload["record_maps"] = {
                "datasets": _safe_public_value(parsed_definitions.datasets),
                "variables": _safe_public_value(parsed_definitions.variables),
                "units": _safe_public_value(parsed_definitions.units),
                "materials": _safe_public_value(parsed_definitions.materials),
                "document_types": _safe_public_value(parsed_definitions.document_types),
                "object_kinds": _safe_public_value(parsed_definitions.object_kinds),
                "family_profiles": _safe_public_value(parsed_definitions.family_profiles),
                "variant_profiles": _safe_public_value(parsed_definitions.variant_profiles),
                "profile_bindings": _safe_public_value(parsed_definitions.profile_bindings),
                "overrides": _safe_public_value(parsed_definitions.overrides),
            }

        if parsed_options.include_raw_payloads:
            payload["raw_payload"] = _safe_public_value(parsed_definitions.raw_payload)

        if parsed_options.include_diagnostics:
            payload["diagnostics"] = _diagnostics_payload(
                parsed_definitions.diagnostics,
                max_issues=parsed_options.max_records,
            )

        return payload

    def build_taxonomy_payload(
        self,
        taxonomy: Any,
        options: Any = None,
    ) -> Dict[str, Any]:
        parsed_taxonomy = taxonomy if isinstance(taxonomy, GeneratorTaxonomyContext) else GeneratorTaxonomyContext.from_mapping(taxonomy)
        parsed_options = self.normalize_options(options)

        payload: Dict[str, Any] = {
            "status": _status_value(parsed_taxonomy.status),
            "source": _status_value(parsed_taxonomy.source),
            "loaded_at": parsed_taxonomy.loaded_at,
            "user_id": parsed_taxonomy.user_id,
            "owner_scope": parsed_taxonomy.owner_scope,
            "selection": parsed_taxonomy.selection,
            "taxonomy_path": parsed_taxonomy.current_taxonomy_path,
            "counts": {
                "nodes": len(parsed_taxonomy.nodes),
                "tree_roots": len(parsed_taxonomy.tree),
                "create_options": len(parsed_taxonomy.create_options),
            },
            "create_options": _safe_public_value(parsed_taxonomy.create_options),
            "tree": _safe_public_value(parsed_taxonomy.tree),
        }

        if parsed_options.include_records:
            payload["nodes"] = _records_from_map(parsed_taxonomy.nodes, parsed_options, compact=parsed_options.compact)

        if parsed_options.include_record_maps:
            payload["node_map"] = _safe_public_value(parsed_taxonomy.nodes)

        if parsed_options.include_raw_payloads:
            payload["resolved_payload"] = _safe_public_value(parsed_taxonomy.resolved_payload)

        if parsed_options.include_diagnostics:
            payload["diagnostics"] = _diagnostics_payload(
                parsed_taxonomy.diagnostics,
                max_issues=parsed_options.max_records,
            )

        return payload

    def build_upload_payload(
        self,
        uploads: Any,
        options: Any = None,
    ) -> Dict[str, Any]:
        parsed_uploads = uploads if isinstance(uploads, GeneratorUploadContext) else GeneratorUploadContext.from_mapping(uploads)
        parsed_options = self.normalize_options(options)

        payload: Dict[str, Any] = {
            "status": _status_value(parsed_uploads.status),
            "source": _status_value(parsed_uploads.source),
            "loaded_at": parsed_uploads.loaded_at,
            "constraints": _safe_public_value(parsed_uploads.constraints),
            "allowed_extensions": list(parsed_uploads.allowed_extensions),
            "blocked_extensions": list(parsed_uploads.blocked_extensions),
            "allowed_mime_types": list(parsed_uploads.allowed_mime_types),
            "blocked_mime_types": list(parsed_uploads.blocked_mime_types),
            "max_size_mb": parsed_uploads.max_size_mb,
            "max_size_bytes": parsed_uploads.max_size_bytes,
            "storage_backends": list(parsed_uploads.storage_backends),
            "counts": {
                "document_types": len(parsed_uploads.document_types),
                "upload_groups": len(parsed_uploads.upload_groups),
                "allowed_extensions": len(parsed_uploads.allowed_extensions),
                "blocked_extensions": len(parsed_uploads.blocked_extensions),
            },
        }

        if parsed_options.include_records:
            payload["document_types"] = _records_from_map(parsed_uploads.document_types, parsed_options)
            payload["upload_groups"] = _records_from_map(parsed_uploads.upload_groups, parsed_options)

        if parsed_options.include_record_maps:
            payload["document_type_map"] = _safe_public_value(parsed_uploads.document_types)
            payload["upload_group_map"] = _safe_public_value(parsed_uploads.upload_groups)

        if parsed_options.include_diagnostics:
            payload["diagnostics"] = _diagnostics_payload(
                parsed_uploads.diagnostics,
                max_issues=parsed_options.max_records,
            )

        return payload

    def build_file_payload(
        self,
        files: Any,
        options: Any = None,
    ) -> Dict[str, Any]:
        parsed_files = files if isinstance(files, GeneratorFileContext) else GeneratorFileContext.from_mapping(files)
        parsed_options = self.normalize_options(options)

        payload: Dict[str, Any] = {
            "status": _status_value(parsed_files.status),
            "source": _status_value(parsed_files.source),
            "loaded_at": parsed_files.loaded_at,
            "counts": {
                "files": len(parsed_files.files),
                "versions": len(parsed_files.versions),
                "links": len(parsed_files.links),
                "contexts": len(parsed_files.context_files),
            },
        }

        if parsed_options.include_records:
            payload["files"] = _records_from_map(parsed_files.files, parsed_options, compact=True)
            payload["versions"] = _records_from_map(parsed_files.versions, parsed_options, compact=True)
            payload["links"] = _records_from_map(parsed_files.links, parsed_options, compact=True)
            payload["context_files"] = {
                key: [_safe_public_value(item) for item in items[: parsed_options.max_records]]
                for key, items in parsed_files.context_files.items()
            }

        if parsed_options.include_record_maps:
            payload["file_map"] = _safe_public_value(parsed_files.files)
            payload["version_map"] = _safe_public_value(parsed_files.versions)
            payload["link_map"] = _safe_public_value(parsed_files.links)

        if parsed_options.include_diagnostics:
            payload["diagnostics"] = _diagnostics_payload(
                parsed_files.diagnostics,
                max_issues=parsed_options.max_records,
            )

        return payload

    def build_draft_payload(
        self,
        draft: Any,
        options: Any = None,
    ) -> Dict[str, Any]:
        parsed_draft = draft if isinstance(draft, GeneratorDraftContext) else GeneratorDraftContext.from_mapping(draft)
        parsed_options = self.normalize_options(options)

        payload: Dict[str, Any] = {
            "status": _status_value(parsed_draft.status),
            "source": _status_value(parsed_draft.source),
            "loaded_at": parsed_draft.loaded_at,
            "draft_ref": parsed_draft.draft_ref,
            "draft_uid": parsed_draft.draft_uid,
            "draft_key": parsed_draft.draft_key,
            "draft_mode": parsed_draft.draft_mode,
            "stage": parsed_draft.stage,
            "target_item_ref": parsed_draft.target_item_ref,
            "base_revision_ref": parsed_draft.base_revision_ref,
            "published_revision_ref": parsed_draft.published_revision_ref,
            "counts": {
                "variants": len(parsed_draft.variants),
                "assets": len(parsed_draft.assets),
                "documents": len(parsed_draft.documents),
                "validation_issues": len(parsed_draft.validation_issues),
            },
        }

        if parsed_options.include_records:
            payload["variants"] = [_safe_public_value(item) for item in parsed_draft.variants[: parsed_options.max_records]]
            payload["assets"] = [_safe_public_value(item) for item in parsed_draft.assets[: parsed_options.max_records]]
            payload["documents"] = [_safe_public_value(item) for item in parsed_draft.documents[: parsed_options.max_records]]
            payload["validation_issues"] = [
                _safe_public_value(item)
                for item in parsed_draft.validation_issues[: parsed_options.max_records]
            ]

        if parsed_options.include_raw_payloads:
            payload["payload"] = _safe_public_value(parsed_draft.payload)
            payload["context_snapshot"] = _safe_public_value(parsed_draft.context_snapshot)

        if parsed_options.include_diagnostics:
            payload["diagnostics"] = _diagnostics_payload(
                parsed_draft.diagnostics,
                max_issues=parsed_options.max_records,
            )

        return payload

    def build_published_payload(
        self,
        published: Any,
        options: Any = None,
    ) -> Dict[str, Any]:
        parsed_published = (
            published if isinstance(published, GeneratorPublishedContext) else GeneratorPublishedContext.from_mapping(published)
        )
        parsed_options = self.normalize_options(options)

        payload: Dict[str, Any] = {
            "status": _status_value(parsed_published.status),
            "source": _status_value(parsed_published.source),
            "loaded_at": parsed_published.loaded_at,
            "item_ref": parsed_published.item_ref,
            "vplib_uid": parsed_published.vplib_uid,
            "family_id": parsed_published.family_id,
            "package_id": parsed_published.package_id,
            "revision_hash": parsed_published.revision_hash,
            "current_revision_ref": parsed_published.current_revision_ref,
            "counts": {
                "variants": len(parsed_published.variants),
                "assets": len(parsed_published.assets),
                "documents": len(parsed_published.documents),
            },
        }

        if parsed_options.include_records:
            payload["variants"] = [_safe_public_value(item) for item in parsed_published.variants[: parsed_options.max_records]]
            payload["assets"] = [_safe_public_value(item) for item in parsed_published.assets[: parsed_options.max_records]]
            payload["documents"] = [_safe_public_value(item) for item in parsed_published.documents[: parsed_options.max_records]]

        if parsed_options.include_raw_payloads:
            payload["item_payload"] = _safe_public_value(parsed_published.item_payload)

        if parsed_options.include_diagnostics:
            payload["diagnostics"] = _diagnostics_payload(
                parsed_published.diagnostics,
                max_issues=parsed_options.max_records,
            )

        return payload

    def build_user_payload(
        self,
        user: Any,
        options: Any = None,
    ) -> Dict[str, Any]:
        parsed_user = user if isinstance(user, GeneratorUserContext) else GeneratorUserContext.from_mapping(user)

        return {
            "user_id": parsed_user.user_id,
            "owner_scope": parsed_user.owner_scope,
            "inventory_key": parsed_user.inventory_key,
            "active_collection_uid": parsed_user.active_collection_uid,
            "active_collection_key": parsed_user.active_collection_key,
            "active_slot_index": parsed_user.active_slot_index,
            "roles": list(parsed_user.roles),
            "permissions": list(parsed_user.permissions),
        }

    def build_capabilities_payload(
        self,
        capabilities: Any,
        options: Any = None,
    ) -> Dict[str, Any]:
        parsed_capabilities = (
            capabilities if isinstance(capabilities, GeneratorCapabilities) else GeneratorCapabilities.from_mapping(capabilities)
        )
        payload = parsed_capabilities.to_dict()

        if not self.normalize_options(options).include_metadata:
            payload.pop("metadata", None)

        return payload

    def build_payload_contract_payload(
        self,
        context: Any,
        options: Any = None,
    ) -> Dict[str, Any]:
        parsed_context = self.normalize_context(context)

        return {
            "schema_version": parsed_context.capabilities.payload_schema_version or "create_payload.v1",
            "required_fields": [
                "family_name",
                "domain",
                "category",
                "subcategory",
                "object_kind",
            ],
            "stable_fields": {
                "identity": [
                    "family_name",
                    "family_description",
                ],
                "taxonomy": [
                    "domain",
                    "category",
                    "subcategory",
                ],
                "variables": [
                    "object_kind",
                    "family_profile_id",
                    "variant_profile_id",
                    "definition_variants_json",
                    "default_variant_id",
                    "variants",
                ],
                "geometry": [
                    "primitive_shape",
                    "geometry_width",
                    "geometry_height",
                    "geometry_depth",
                    "geometry_unit",
                    "editor_cells_x",
                    "editor_cells_y",
                    "editor_cells_z",
                    "geometry_model_uploads_json",
                ],
                "technical": [
                    "material_class",
                    "variables",
                    "technical_document_uploads_json",
                ],
                "uploads": [
                    "geometry_model_uploads_json",
                    "technical_document_uploads_json",
                    "variant_document_uploads_json",
                ],
            },
            "frontend_aliases": {
                "variables": ["object", "object-variants", "variables"],
                "object_variants": ["object", "object-variants", "variables"],
            },
            "duplicate_formdata_guards": [
                "object_kind",
                "family_profile_id",
                "variant_profile_id",
                "definition_variants_json",
                "default_variant_id",
            ],
        }

    def build_default_values_payload(
        self,
        context: Any,
        options: Any = None,
    ) -> Dict[str, Any]:
        parsed_context = self.normalize_context(context)
        taxonomy = parsed_context.taxonomy

        object_kind_keys = parsed_context.definitions.list_object_kind_keys()
        family_profile_keys = parsed_context.definitions.list_family_profile_keys()
        variant_profile_keys = parsed_context.definitions.list_variant_profile_keys()

        return {
            "user_id": parsed_context.user.user_id or DEFAULT_USER_ID,
            "inventory_key": parsed_context.user.inventory_key or DEFAULT_INVENTORY_KEY,
            "domain": taxonomy.domain or "hochbau",
            "category": taxonomy.category or "bloecke",
            "subcategory": taxonomy.subcategory or "basis",
            "taxonomy_path": taxonomy.current_taxonomy_path or "hochbau/bloecke/basis",
            "object_kind": object_kind_keys[0] if object_kind_keys else "",
            "family_profile_id": family_profile_keys[0] if family_profile_keys else "",
            "variant_profile_id": variant_profile_keys[0] if variant_profile_keys else "",
            "default_variant_id": "default",
            "geometry_unit": "m",
            "editor_cells_x": 1,
            "editor_cells_y": 1,
            "editor_cells_z": 1,
        }

    def build_diagnostics_payload(
        self,
        context: Any,
        options: Any = None,
    ) -> Dict[str, Any]:
        parsed_context = self.normalize_context(context)
        parsed_options = self.normalize_options(options)

        section_diagnostics = {
            "root": _diagnostics_payload(parsed_context.diagnostics, max_issues=parsed_options.max_records),
            "routes": _diagnostics_payload(parsed_context.routes.diagnostics, max_issues=parsed_options.max_records),
            "definitions": _diagnostics_payload(parsed_context.definitions.diagnostics, max_issues=parsed_options.max_records),
            "taxonomy": _diagnostics_payload(parsed_context.taxonomy.diagnostics, max_issues=parsed_options.max_records),
            "uploads": _diagnostics_payload(parsed_context.uploads.diagnostics, max_issues=parsed_options.max_records),
            "files": _diagnostics_payload(parsed_context.files.diagnostics, max_issues=parsed_options.max_records),
            "draft": _diagnostics_payload(parsed_context.draft.diagnostics, max_issues=parsed_options.max_records),
            "published": _diagnostics_payload(parsed_context.published.diagnostics, max_issues=parsed_options.max_records),
        }

        minimum = parsed_context.validate_minimum(
            require_definitions=True,
            require_taxonomy=True,
            require_uploads=False,
            require_routes=True,
        )

        return {
            "ok": parsed_context.diagnostics.blocking_count == 0 and minimum.blocking_count == 0,
            "status": _status_value(parsed_context.status),
            "component": self.component,
            "schema_version": self.schema_version,
            "context_schema_version": parsed_context.schema_version,
            "context_uid": parsed_context.context_uid,
            "checked_at": utc_now_iso(),
            "section_status": _section_status_payload(parsed_context),
            "counts": _counts_payload(parsed_context),
            "minimum": _diagnostics_payload(minimum, max_issues=parsed_options.max_records),
            "sections": section_diagnostics,
            "cache": self.cache.stats() if self.cache is not None else None,
        }

    def build_health_payload(
        self,
        context: Any = None,
        options: Any = None,
    ) -> Dict[str, Any]:
        parsed_context = self.normalize_context(context) if context is not None else build_minimal_generator_context()
        parsed_options = self.normalize_options(options)

        minimum = parsed_context.validate_minimum(
            require_definitions=False,
            require_taxonomy=False,
            require_uploads=False,
            require_routes=False,
        )

        payload = {
            "ok": minimum.blocking_count == 0,
            "status": _status_value(parsed_context.status),
            "component": self.component,
            "schema_version": self.schema_version,
            "context_schema_version": GENERATOR_CONTEXT_SCHEMA_VERSION,
            "checked_at": utc_now_iso(),
            "section_status": _section_status_payload(parsed_context),
            "counts": _counts_payload(parsed_context),
            "cache": self.cache.stats() if self.cache is not None else None,
        }

        if parsed_options.include_diagnostics:
            payload["diagnostics"] = _diagnostics_payload(minimum, max_issues=parsed_options.max_records)

        return payload

    def build_test_snapshot_payload(
        self,
        context: Any,
        options: Any = None,
    ) -> Dict[str, Any]:
        parsed_context = self.normalize_context(context)
        parsed_options = self.normalize_options(options)

        return {
            "ok": parsed_context.status in {GeneratorContextStatus.READY, GeneratorContextStatus.PARTIAL},
            "status": _status_value(parsed_context.status),
            "component": self.component,
            "schema_version": self.schema_version,
            "built_at": utc_now_iso(),
            "context_uid": parsed_context.context_uid,
            "stable_hash": parsed_context.stable_hash(),
            "section_status": _section_status_payload(parsed_context),
            "counts": _counts_payload(parsed_context),
            "route_keys": sorted(parsed_context.routes.routes.keys()),
            "object_kind_keys": parsed_context.definitions.list_object_kind_keys(),
            "family_profile_keys": parsed_context.definitions.list_family_profile_keys(),
            "variant_profile_keys": parsed_context.definitions.list_variant_profile_keys(),
            "taxonomy_selection": parsed_context.taxonomy.selection,
            "upload_constraints": {
                "allowed_extensions": parsed_context.uploads.allowed_extensions,
                "blocked_extensions": parsed_context.uploads.blocked_extensions,
                "allowed_mime_types": parsed_context.uploads.allowed_mime_types,
                "blocked_mime_types": parsed_context.uploads.blocked_mime_types,
                "max_size_mb": parsed_context.uploads.max_size_mb,
            },
            "capabilities": self.build_capabilities_payload(parsed_context.capabilities, parsed_options),
            "diagnostics": _diagnostics_payload(parsed_context.diagnostics, max_issues=parsed_options.max_records),
        }

    def build_error_payload(
        self,
        context: Any,
        diagnostics: GeneratorContextDiagnostics,
        options: Any = None,
    ) -> Dict[str, Any]:
        parsed_context = self.normalize_context(context)

        return {
            "ok": False,
            "status": GeneratorContextStatus.ERROR.value,
            "component": self.component,
            "schema_version": self.schema_version,
            "context_uid": parsed_context.context_uid,
            "built_at": utc_now_iso(),
            "section_status": _section_status_payload(parsed_context),
            "counts": _counts_payload(parsed_context),
            "diagnostics": _diagnostics_payload(diagnostics),
        }

    def _wrap_payload(
        self,
        payload: Dict[str, Any],
        context: GeneratorContext,
        options: GeneratorContextBuildOptions,
        kind: str,
    ) -> Dict[str, Any]:
        wrapped = dict(payload)

        if "ok" not in wrapped:
            wrapped["ok"] = context.status in {GeneratorContextStatus.READY, GeneratorContextStatus.PARTIAL}

        wrapped.setdefault("status", _status_value(context.status))
        wrapped.setdefault("kind", kind)
        wrapped.setdefault("built_at", utc_now_iso())
        wrapped.setdefault("component", self.component)
        wrapped.setdefault("schema_version", self.schema_version)

        if not options.include_empty_sections:
            wrapped = {
                key: value
                for key, value in wrapped.items()
                if value not in ({}, [], None)
            }

        return wrapped


_DEFAULT_BUILDER = GeneratorContextBuilder()


def get_default_generator_context_builder() -> GeneratorContextBuilder:
    return _DEFAULT_BUILDER


def clear_generator_context_builder_caches() -> Dict[str, Any]:
    builder = get_default_generator_context_builder()
    cleared = 0
    try:
        if builder.cache is not None:
            cleared = builder.cache.clear()
    except Exception:
        cleared = 0

    return {
        "ok": True,
        "component": GENERATOR_CONTEXT_BUILDER_COMPONENT,
        "cleared": cleared,
        "cleared_at": utc_now_iso(),
    }


def build_generator_context_payload(
    context: Any,
    mode: Any = GeneratorContextViewMode.PUBLIC,
    options: Any = None,
    use_cache: Optional[bool] = None,
) -> Dict[str, Any]:
    result = get_default_generator_context_builder().build(
        context=context,
        mode=mode,
        options=options,
        use_cache=use_cache,
    )
    return result.payload


def build_generator_context_result(
    context: Any,
    mode: Any = GeneratorContextViewMode.PUBLIC,
    options: Any = None,
    use_cache: Optional[bool] = None,
) -> GeneratorContextBuildResult:
    return get_default_generator_context_builder().build(
        context=context,
        mode=mode,
        options=options,
        use_cache=use_cache,
    )


def build_generator_frontend_context_payload(
    context: Any,
    options: Any = None,
    use_cache: Optional[bool] = None,
) -> Dict[str, Any]:
    return build_generator_context_payload(
        context=context,
        mode=GeneratorContextViewMode.FRONTEND,
        options=options,
        use_cache=use_cache,
    )


def build_generator_create_options_payload(
    context: Any,
    options: Any = None,
    use_cache: Optional[bool] = None,
) -> Dict[str, Any]:
    return build_generator_context_payload(
        context=context,
        mode=GeneratorContextViewMode.OPTIONS,
        options=options,
        use_cache=use_cache,
    )


def build_generator_diagnostics_payload(
    context: Any,
    options: Any = None,
    use_cache: Optional[bool] = None,
) -> Dict[str, Any]:
    return build_generator_context_payload(
        context=context,
        mode=GeneratorContextViewMode.DIAGNOSTICS,
        options=options,
        use_cache=use_cache,
    )


def build_generator_health_payload(
    context: Any = None,
    options: Any = None,
    use_cache: Optional[bool] = None,
) -> Dict[str, Any]:
    return build_generator_context_payload(
        context=context,
        mode=GeneratorContextViewMode.HEALTH,
        options=options,
        use_cache=use_cache,
    )


def build_generator_test_snapshot_payload(
    context: Any,
    options: Any = None,
    use_cache: Optional[bool] = None,
) -> Dict[str, Any]:
    return build_generator_context_payload(
        context=context,
        mode=GeneratorContextViewMode.TEST,
        options=options,
        use_cache=use_cache,
    )


def get_generator_context_builder_health(include_cache: bool = True) -> Dict[str, Any]:
    diagnostics = GeneratorContextDiagnostics()
    builder = get_default_generator_context_builder()

    try:
        sample_context = build_minimal_generator_context()
        sample_payload = builder.build_health_payload(sample_context)
        if not isinstance(sample_payload, dict):
            diagnostics.add_error(
                "builder_health_payload_invalid",
                "Generator context builder health payload is not a dictionary.",
                GeneratorContextSection.DIAGNOSTICS,
            )
    except Exception as exc:
        diagnostics.add_error(
            "builder_health_selftest_failed",
            "Generator context builder selftest failed.",
            GeneratorContextSection.DIAGNOSTICS,
            error=safe_str(exc),
        )

    diagnostics.refresh()

    payload: Dict[str, Any] = {
        "ok": diagnostics.blocking_count == 0,
        "status": _status_value(diagnostics.status),
        "component": GENERATOR_CONTEXT_BUILDER_COMPONENT,
        "schema_version": GENERATOR_CONTEXT_BUILDER_SCHEMA_VERSION,
        "context_schema_version": GENERATOR_CONTEXT_SCHEMA_VERSION,
        "checked_at": utc_now_iso(),
        "diagnostics": _diagnostics_payload(diagnostics),
        "exports": [
            "GeneratorContextBuilder",
            "GeneratorContextBuildOptions",
            "GeneratorContextBuildResult",
            "build_generator_context_payload",
            "build_generator_frontend_context_payload",
            "build_generator_create_options_payload",
            "build_generator_diagnostics_payload",
            "build_generator_health_payload",
            "build_generator_test_snapshot_payload",
        ],
    }

    if include_cache:
        try:
            payload["cache"] = builder.cache.stats() if builder.cache is not None else None
        except Exception as exc:
            payload["cache_error"] = safe_str(exc)

    return payload


def assert_generator_context_builder_ready() -> bool:
    health = get_generator_context_builder_health(include_cache=False)
    if not health.get("ok"):
        raise RuntimeError(f"{GENERATOR_CONTEXT_BUILDER_COMPONENT} is not ready: {health}")
    return True


__all__ = [
    "GENERATOR_CONTEXT_BUILDER_COMPONENT",
    "GENERATOR_CONTEXT_BUILDER_SCHEMA_VERSION",
    "DEFAULT_BUILDER_CACHE_TTL_SECONDS",
    "DEFAULT_BUILDER_RECORD_LIMIT",
    "DEFAULT_COMPACT_RECORD_LIMIT",
    "FRONTEND_WINDOW_CONTEXT_NAME",
    "FRONTEND_WINDOW_UPLOAD_CONFIG_NAME",
    "FRONTEND_WINDOW_DEFINITION_CONTEXT_NAME",
    "FRONTEND_WINDOW_TAXONOMY_CONTEXT_NAME",
    "DEFAULT_FRONTEND_STEP_CONFIG",
    "GeneratorContextViewMode",
    "GeneratorContextBuildOptions",
    "GeneratorContextBuildResult",
    "GeneratorContextBuilder",
    "get_default_generator_context_builder",
    "clear_generator_context_builder_caches",
    "build_generator_context_payload",
    "build_generator_context_result",
    "build_generator_frontend_context_payload",
    "build_generator_create_options_payload",
    "build_generator_diagnostics_payload",
    "build_generator_health_payload",
    "build_generator_test_snapshot_payload",
    "get_generator_context_builder_health",
    "assert_generator_context_builder_ready",
]