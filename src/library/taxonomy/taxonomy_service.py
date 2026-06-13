# services/vectoplan-library/src/library/taxonomy/taxonomy_service.py
"""
VECTOPLAN Library Taxonomy Service.

Central framework-free service layer for the VPLIB taxonomy.

This service connects:
- taxonomy_models.py
- taxonomy_registry.py
- taxonomy_validator.py

It intentionally does not import Flask, route modules, create routes, scanner
routes or template code. Route services and backend services should depend on
this module, not the other way around.

Responsibilities:
- load the canonical taxonomy registry
- provide stable API payloads for routes and Create-Wizard options
- validate domain/category/subcategory selections
- resolve selections to labels and metadata
- build canonical source paths
- build canonical family_id and package_id values
- validate source paths and classification payloads
- expose health/status information
- cache expensive payloads safely

Canonical source path:
    src/library/source/{domain}/{category}/{subcategory}/{family_slug}

Canonical family_id:
    vp.{domain}.{category}.{subcategory}.{family_slug}

Canonical package_id:
    vplib.vp.{domain}.{category}.{subcategory}.{family_slug}
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field as dataclass_field
from threading import RLock
from typing import Any, Dict, Iterable, List, Mapping, Optional, Sequence, Tuple

try:
    from .taxonomy_models import (
        PACKAGE_ID_PREFIX,
        TAXONOMY_ID_PREFIX,
        TaxonomyIssue,
        TaxonomyModelError,
        TaxonomyRegistryModel,
        TaxonomyResolvedSelection,
        TaxonomySelection,
        TaxonomyValidationResult,
        make_json_safe,
        normalize_identifier_prefix,
        normalize_slug,
        safe_bool,
        safe_int,
        safe_str,
    )
    from .taxonomy_registry import (
        TaxonomyRegistry,
        TaxonomyRegistryLoadError,
        TaxonomyRegistryLoadResult,
        get_default_taxonomy_registry,
    )
    from .taxonomy_validator import (
        TaxonomySourcePathValidation,
        TaxonomyValidator,
        TaxonomyValidatorConfig,
        normalize_source_path_parts,
    )
except ImportError:  # pragma: no cover - defensive fallback for direct script execution
    from taxonomy_models import (  # type: ignore
        PACKAGE_ID_PREFIX,
        TAXONOMY_ID_PREFIX,
        TaxonomyIssue,
        TaxonomyModelError,
        TaxonomyRegistryModel,
        TaxonomyResolvedSelection,
        TaxonomySelection,
        TaxonomyValidationResult,
        make_json_safe,
        normalize_identifier_prefix,
        normalize_slug,
        safe_bool,
        safe_int,
        safe_str,
    )
    from taxonomy_registry import (  # type: ignore
        TaxonomyRegistry,
        TaxonomyRegistryLoadError,
        TaxonomyRegistryLoadResult,
        get_default_taxonomy_registry,
    )
    from taxonomy_validator import (  # type: ignore
        TaxonomySourcePathValidation,
        TaxonomyValidator,
        TaxonomyValidatorConfig,
        normalize_source_path_parts,
    )


LOGGER = logging.getLogger(__name__)

TAXONOMY_REQUIRED_FIELDS: Tuple[str, str, str] = (
    "domain",
    "category",
    "subcategory",
)

DEFAULT_INCLUDE_INACTIVE = False
DEFAULT_ALLOW_STALE_ON_ERROR = True
DEFAULT_CACHE_PAYLOADS = True
DEFAULT_CACHE_MAX_ITEMS = 64


class TaxonomyServiceError(RuntimeError):
    """Base error for taxonomy service operations."""


class TaxonomyServiceUnavailableError(TaxonomyServiceError):
    """Raised when the taxonomy registry cannot be loaded."""


class TaxonomySelectionError(TaxonomyServiceError):
    """Raised when a taxonomy selection cannot be resolved."""


@dataclass(frozen=True)
class TaxonomyServiceConfig:
    """
    Runtime behavior for TaxonomyService.

    This config intentionally mirrors registry constraints where appropriate,
    but stays service-specific for cache and payload behavior.
    """

    include_inactive: bool = DEFAULT_INCLUDE_INACTIVE
    allow_stale_on_error: bool = DEFAULT_ALLOW_STALE_ON_ERROR
    cache_payloads: bool = DEFAULT_CACHE_PAYLOADS
    cache_max_items: int = DEFAULT_CACHE_MAX_ITEMS

    include_tree_by_default: bool = True
    include_options_by_default: bool = True
    include_lookup_by_default: bool = True
    include_validation_in_health: bool = True

    family_id_prefix: str = TAXONOMY_ID_PREFIX
    package_id_prefix: str = PACKAGE_ID_PREFIX

    @classmethod
    def from_registry(cls, registry: TaxonomyRegistryModel) -> "TaxonomyServiceConfig":
        constraints = registry.constraints

        return cls(
            include_inactive=False,
            allow_stale_on_error=True,
            cache_payloads=True,
            cache_max_items=DEFAULT_CACHE_MAX_ITEMS,
            include_tree_by_default=True,
            include_options_by_default=True,
            include_lookup_by_default=True,
            include_validation_in_health=True,
            family_id_prefix=normalize_identifier_prefix(
                constraints.family_id_prefix,
                default=TAXONOMY_ID_PREFIX,
            ),
            package_id_prefix=normalize_identifier_prefix(
                constraints.package_id_prefix,
                default=PACKAGE_ID_PREFIX,
            ),
        )

    def to_dict(self) -> Dict[str, Any]:
        return {
            "include_inactive": self.include_inactive,
            "allow_stale_on_error": self.allow_stale_on_error,
            "cache_payloads": self.cache_payloads,
            "cache_max_items": self.cache_max_items,
            "include_tree_by_default": self.include_tree_by_default,
            "include_options_by_default": self.include_options_by_default,
            "include_lookup_by_default": self.include_lookup_by_default,
            "include_validation_in_health": self.include_validation_in_health,
            "family_id_prefix": self.family_id_prefix,
            "package_id_prefix": self.package_id_prefix,
        }


@dataclass(frozen=True)
class TaxonomyCounts:
    """Small summary of taxonomy registry size."""

    domains: int = 0
    categories: int = 0
    subcategories: int = 0
    active_domains: int = 0
    active_categories: int = 0
    active_subcategories: int = 0

    @classmethod
    def from_registry(cls, registry: TaxonomyRegistryModel) -> "TaxonomyCounts":
        domains = list(registry.domains)
        categories = [category for domain in domains for category in domain.categories]
        subcategories = [
            subcategory
            for domain in domains
            for category in domain.categories
            for subcategory in category.subcategories
        ]

        return cls(
            domains=len(domains),
            categories=len(categories),
            subcategories=len(subcategories),
            active_domains=sum(1 for item in domains if item.is_active),
            active_categories=sum(1 for item in categories if item.is_active),
            active_subcategories=sum(1 for item in subcategories if item.is_active),
        )

    def to_dict(self) -> Dict[str, int]:
        return {
            "domains": self.domains,
            "categories": self.categories,
            "subcategories": self.subcategories,
            "active_domains": self.active_domains,
            "active_categories": self.active_categories,
            "active_subcategories": self.active_subcategories,
        }


@dataclass(frozen=True)
class TaxonomyBuildResult:
    """
    Result for canonical path/identifier building.

    This is used by create services, package planning, archive creation and save
    logic. It remains safe to serialize into API responses.
    """

    selection: TaxonomySelection
    family_slug: str = ""
    object_kind: str = ""
    taxonomy_version: str = ""
    resolved: Optional[TaxonomyResolvedSelection] = None
    source_parts: Tuple[str, ...] = dataclass_field(default_factory=tuple)
    source_path: str = ""
    classification_path: str = ""
    family_id: str = ""
    package_id: str = ""
    issues: TaxonomyValidationResult = dataclass_field(default_factory=TaxonomyValidationResult.ok)

    @property
    def valid(self) -> bool:
        return self.issues.valid and self.resolved is not None and bool(self.family_slug)

    @property
    def has_errors(self) -> bool:
        return self.issues.has_errors

    def to_dict(self) -> Dict[str, Any]:
        return make_json_safe(
            {
                "valid": self.valid,
                "taxonomy_version": self.taxonomy_version,
                "selection": self.selection.to_dict(),
                "resolved": self.resolved.to_dict() if self.resolved else None,
                "family_slug": self.family_slug,
                "object_kind": self.object_kind,
                "source_parts": list(self.source_parts),
                "source_path": self.source_path,
                "classification_path": self.classification_path,
                "family_id": self.family_id,
                "package_id": self.package_id,
                "issues": self.issues.to_dict(),
            }
        )


@dataclass(frozen=True)
class TaxonomyPayloadCacheEntry:
    """Internal payload-cache entry."""

    key: Tuple[Any, ...]
    payload: Mapping[str, Any]


class TaxonomyService:
    """
    Central access layer for taxonomy registry, validation and payload building.

    Typical usage:

        service = TaxonomyService()
        options = service.get_create_options_payload()
        result = service.build_family_reference(
            domain="hochbau",
            category="waende",
            subcategory="aussenwaende",
            family_slug="ziegelwand",
            object_kind="cell_block",
        )
    """

    def __init__(
        self,
        *,
        registry_loader: Optional[TaxonomyRegistry] = None,
        registry: Optional[TaxonomyRegistryModel] = None,
        config: Optional[TaxonomyServiceConfig] = None,
        logger: Optional[logging.Logger] = None,
    ) -> None:
        self.registry_loader = registry_loader or get_default_taxonomy_registry()
        self._static_registry = registry
        self.config = config
        self.logger = logger or LOGGER

        self._lock = RLock()
        self._payload_cache: Dict[Tuple[Any, ...], TaxonomyPayloadCacheEntry] = {}
        self._payload_cache_order: List[Tuple[Any, ...]] = []

    @property
    def is_static(self) -> bool:
        return self._static_registry is not None

    def clear_cache(self) -> None:
        with self._lock:
            self._payload_cache.clear()
            self._payload_cache_order.clear()

        if self.registry_loader:
            try:
                self.registry_loader.clear_cache()
            except Exception:
                self.logger.debug("Could not clear taxonomy registry loader cache.", exc_info=True)

    def load_registry(
        self,
        *,
        force_reload: bool = False,
        allow_stale_on_error: Optional[bool] = None,
    ) -> TaxonomyRegistryModel:
        registry, _result = self._load_registry_with_result(
            force_reload=force_reload,
            allow_stale_on_error=allow_stale_on_error,
        )
        return registry

    def load_registry_result(
        self,
        *,
        force_reload: bool = False,
        allow_stale_on_error: Optional[bool] = None,
    ) -> Optional[TaxonomyRegistryLoadResult]:
        _registry, result = self._load_registry_with_result(
            force_reload=force_reload,
            allow_stale_on_error=allow_stale_on_error,
        )
        return result

    def get_validator(
        self,
        *,
        registry: Optional[TaxonomyRegistryModel] = None,
        force_reload: bool = False,
    ) -> TaxonomyValidator:
        model = registry or self.load_registry(force_reload=force_reload)
        return TaxonomyValidator(
            model,
            config=TaxonomyValidatorConfig.from_constraints(model.constraints),
        )

    def health(
        self,
        *,
        force_reload: bool = False,
        include_registry_state: bool = False,
    ) -> Dict[str, Any]:
        """
        Return a route-friendly health payload.

        This method catches exceptions and never raises under normal use.
        """

        try:
            registry, load_result = self._load_registry_with_result(
                force_reload=force_reload,
                allow_stale_on_error=True,
            )
            counts = TaxonomyCounts.from_registry(registry)
            validation = TaxonomyValidationResult.ok()

            if self._effective_config(registry).include_validation_in_health:
                validation = self.get_validator(registry=registry).validate_registry_model(registry)

            healthy = validation.valid and counts.domains > 0 and counts.categories > 0 and counts.subcategories > 0

            payload: Dict[str, Any] = {
                "healthy": healthy,
                "component": "taxonomy-service",
                "schema_version": registry.schema_version,
                "taxonomy_version": registry.taxonomy_version,
                "label": registry.label,
                "counts": counts.to_dict(),
                "required_fields": list(TAXONOMY_REQUIRED_FIELDS),
                "validation": validation.to_dict(),
                "cache": {
                    "payload_cache_enabled": self._effective_config(registry).cache_payloads,
                    "payload_cache_items": len(self._payload_cache),
                    "static_registry": self.is_static,
                },
            }

            if load_result:
                payload["registry_load"] = load_result.to_dict(include_registry=False)

            if include_registry_state and self.registry_loader and not self.is_static:
                try:
                    payload["registry_state"] = self.registry_loader.state()
                except Exception as exc:
                    payload["registry_state"] = {
                        "error": safe_str(exc, "Could not read registry state."),
                    }

            return make_json_safe(payload)

        except Exception as exc:
            self.logger.exception("Taxonomy service health check failed.")
            return make_json_safe(
                {
                    "healthy": False,
                    "component": "taxonomy-service",
                    "error": safe_str(exc, "Taxonomy service health check failed."),
                    "required_fields": list(TAXONOMY_REQUIRED_FIELDS),
                }
            )

    def get_taxonomy_payload(
        self,
        *,
        include_inactive: Optional[bool] = None,
        include_tree: Optional[bool] = None,
        include_options: Optional[bool] = None,
        include_lookup: Optional[bool] = None,
        force_reload: bool = False,
    ) -> Dict[str, Any]:
        """
        Return the canonical taxonomy API payload.

        Intended for:
            GET /api/v1/vplib/taxonomy
        """

        registry, load_result = self._load_registry_with_result(
            force_reload=force_reload,
            allow_stale_on_error=None,
        )
        config = self._effective_config(registry)

        resolved_include_inactive = config.include_inactive if include_inactive is None else bool(include_inactive)
        resolved_include_tree = config.include_tree_by_default if include_tree is None else bool(include_tree)
        resolved_include_options = config.include_options_by_default if include_options is None else bool(include_options)
        resolved_include_lookup = config.include_lookup_by_default if include_lookup is None else bool(include_lookup)

        cache_key = self._cache_key(
            "taxonomy_payload",
            registry,
            load_result,
            resolved_include_inactive,
            resolved_include_tree,
            resolved_include_options,
            resolved_include_lookup,
        )

        cached = self._cache_get(cache_key)
        if cached is not None:
            return cached

        payload: Dict[str, Any] = {
            "ok": True,
            "schema_version": registry.schema_version,
            "taxonomy_version": registry.taxonomy_version,
            "label": registry.label,
            "description": registry.description,
            "required_fields": list(TAXONOMY_REQUIRED_FIELDS),
            "constraints": registry.constraints.to_dict(),
            "defaults": registry.defaults.to_dict(),
            "metadata": make_json_safe(registry.metadata),
            "counts": TaxonomyCounts.from_registry(registry).to_dict(),
        }

        if resolved_include_tree:
            payload["tree"] = registry.to_tree_dict(
                include_inactive=resolved_include_inactive,
                include_options=True,
            )

        if resolved_include_options:
            payload["options"] = registry.to_options_payload(
                include_inactive=resolved_include_inactive,
            )

        if resolved_include_lookup:
            payload["lookup"] = registry.to_lookup_payload()

        if load_result:
            payload["registry_load"] = load_result.to_dict(include_registry=False)

        payload = make_json_safe(payload)
        self._cache_set(cache_key, payload)

        return payload

    def get_create_options_payload(
        self,
        *,
        include_inactive: Optional[bool] = None,
        force_reload: bool = False,
    ) -> Dict[str, Any]:
        """
        Return Create-Wizard-friendly taxonomy options.

        Intended for merging into:
            GET /api/v1/vplib/create/options

        The payload intentionally exposes direct keys such as "domains",
        "categories_by_domain" and "subcategories_by_category" so the existing
        frontend can consume the taxonomy without knowing the full registry
        shape.
        """

        registry, load_result = self._load_registry_with_result(
            force_reload=force_reload,
            allow_stale_on_error=None,
        )
        config = self._effective_config(registry)
        resolved_include_inactive = config.include_inactive if include_inactive is None else bool(include_inactive)

        cache_key = self._cache_key(
            "create_options_payload",
            registry,
            load_result,
            resolved_include_inactive,
        )

        cached = self._cache_get(cache_key)
        if cached is not None:
            return cached

        options = registry.to_options_payload(include_inactive=resolved_include_inactive)

        payload: Dict[str, Any] = {
            "taxonomy_version": registry.taxonomy_version,
            "taxonomy_schema_version": registry.schema_version,
            "required_fields": list(TAXONOMY_REQUIRED_FIELDS),
            "domains": options.get("domains", []),
            "categories_by_domain": options.get("categories_by_domain", {}),
            "subcategories_by_category": options.get("subcategories_by_category", {}),
            "defaults": options.get("defaults", {}),
            "constraints": options.get("constraints", {}),
            "taxonomy": {
                "schema_version": registry.schema_version,
                "taxonomy_version": registry.taxonomy_version,
                "label": registry.label,
                "description": registry.description,
                "required_fields": list(TAXONOMY_REQUIRED_FIELDS),
                "tree": registry.to_tree_dict(
                    include_inactive=resolved_include_inactive,
                    include_options=True,
                ),
                "lookup": registry.to_lookup_payload(),
            },
        }

        if load_result:
            payload["registry_load"] = load_result.to_dict(include_registry=False)

        payload = make_json_safe(payload)
        self._cache_set(cache_key, payload)

        return payload

    def get_tree_payload(
        self,
        *,
        include_inactive: Optional[bool] = None,
        force_reload: bool = False,
    ) -> Dict[str, Any]:
        registry, load_result = self._load_registry_with_result(
            force_reload=force_reload,
            allow_stale_on_error=None,
        )
        config = self._effective_config(registry)
        resolved_include_inactive = config.include_inactive if include_inactive is None else bool(include_inactive)

        cache_key = self._cache_key(
            "tree_payload",
            registry,
            load_result,
            resolved_include_inactive,
        )

        cached = self._cache_get(cache_key)
        if cached is not None:
            return cached

        payload = registry.to_tree_dict(
            include_inactive=resolved_include_inactive,
            include_options=True,
        )
        payload["ok"] = True
        payload["counts"] = TaxonomyCounts.from_registry(registry).to_dict()

        payload = make_json_safe(payload)
        self._cache_set(cache_key, payload)

        return payload

    def get_options_payload(
        self,
        *,
        include_inactive: Optional[bool] = None,
        force_reload: bool = False,
    ) -> Dict[str, Any]:
        registry, load_result = self._load_registry_with_result(
            force_reload=force_reload,
            allow_stale_on_error=None,
        )
        config = self._effective_config(registry)
        resolved_include_inactive = config.include_inactive if include_inactive is None else bool(include_inactive)

        cache_key = self._cache_key(
            "options_payload",
            registry,
            load_result,
            resolved_include_inactive,
        )

        cached = self._cache_get(cache_key)
        if cached is not None:
            return cached

        payload = registry.to_options_payload(include_inactive=resolved_include_inactive)
        payload["ok"] = True
        payload["required_fields"] = list(TAXONOMY_REQUIRED_FIELDS)
        payload["counts"] = TaxonomyCounts.from_registry(registry).to_dict()

        payload = make_json_safe(payload)
        self._cache_set(cache_key, payload)

        return payload

    def get_lookup_payload(
        self,
        *,
        force_reload: bool = False,
    ) -> Dict[str, Any]:
        registry, load_result = self._load_registry_with_result(
            force_reload=force_reload,
            allow_stale_on_error=None,
        )

        cache_key = self._cache_key("lookup_payload", registry, load_result)

        cached = self._cache_get(cache_key)
        if cached is not None:
            return cached

        payload = {
            "ok": True,
            "schema_version": registry.schema_version,
            "taxonomy_version": registry.taxonomy_version,
            "lookup": registry.to_lookup_payload(),
        }

        payload = make_json_safe(payload)
        self._cache_set(cache_key, payload)

        return payload

    def validate_selection(
        self,
        domain: Any,
        category: Any,
        subcategory: Any,
        *,
        object_kind: Any = "",
        force_reload: bool = False,
    ) -> TaxonomyValidationResult:
        try:
            registry = self.load_registry(force_reload=force_reload)
            return self.get_validator(registry=registry).validate_selection(
                domain,
                category,
                subcategory,
                object_kind=object_kind,
            )
        except Exception as exc:
            return TaxonomyValidationResult.from_issues(
                (
                    TaxonomyIssue.error(
                        "taxonomy_service_selection_validation_failed",
                        f"Taxonomy selection validation failed: {exc}",
                        field="taxonomy",
                    ),
                )
            )

    def validate_payload(
        self,
        payload: Any,
        *,
        object_kind: Any = "",
        force_reload: bool = False,
    ) -> TaxonomyValidationResult:
        source = as_mapping(payload)
        selection = TaxonomySelection.from_payload(source)
        resolved_object_kind = normalize_slug(
            object_kind or source.get("object_kind"),
            default="",
        )

        return self.validate_selection(
            selection.domain,
            selection.category,
            selection.subcategory,
            object_kind=resolved_object_kind,
            force_reload=force_reload,
        )

    def resolve_selection(
        self,
        domain: Any,
        category: Any,
        subcategory: Any,
        *,
        force_reload: bool = False,
    ) -> TaxonomyResolvedSelection:
        registry = self.load_registry(force_reload=force_reload)

        try:
            return registry.resolve(domain, category, subcategory)
        except TaxonomyModelError as exc:
            raise TaxonomySelectionError(str(exc)) from exc

    def try_resolve_selection(
        self,
        domain: Any,
        category: Any,
        subcategory: Any,
        *,
        force_reload: bool = False,
    ) -> Optional[TaxonomyResolvedSelection]:
        try:
            return self.resolve_selection(
                domain,
                category,
                subcategory,
                force_reload=force_reload,
            )
        except Exception:
            return None

    def resolve_payload(
        self,
        payload: Any,
        *,
        force_reload: bool = False,
    ) -> TaxonomyResolvedSelection:
        selection = TaxonomySelection.from_payload(payload)
        return self.resolve_selection(
            selection.domain,
            selection.category,
            selection.subcategory,
            force_reload=force_reload,
        )

    def build_family_reference(
        self,
        *,
        domain: Any,
        category: Any,
        subcategory: Any,
        family_slug: Any,
        object_kind: Any = "",
        force_reload: bool = False,
    ) -> TaxonomyBuildResult:
        """
        Build canonical source path, family_id and package_id.

        This method does not write files. It is safe for draft, validate,
        package-plan, download and save workflows.
        """

        registry = self.load_registry(force_reload=force_reload)
        config = self._effective_config(registry)

        selection = TaxonomySelection.from_values(domain, category, subcategory)
        normalized_family_slug = normalize_slug(family_slug, default="")
        normalized_object_kind = normalize_slug(object_kind, default="")

        issues: List[TaxonomyIssue] = []

        validation = self.get_validator(registry=registry).validate_selection(
            selection.domain,
            selection.category,
            selection.subcategory,
            object_kind=normalized_object_kind,
        )
        issues.extend(validation.issues)

        if not normalized_family_slug:
            issues.append(
                TaxonomyIssue.error(
                    "taxonomy_family_slug_missing",
                    "family_slug is required to build taxonomy source path and identifiers.",
                    field="family_slug",
                )
            )

        resolved: Optional[TaxonomyResolvedSelection] = None

        if not any(issue.is_error for issue in issues):
            try:
                resolved = registry.resolve(
                    selection.domain,
                    selection.category,
                    selection.subcategory,
                )
            except Exception as exc:
                issues.append(
                    TaxonomyIssue.error(
                        "taxonomy_resolve_failed",
                        f"Taxonomy selection could not be resolved: {exc}",
                        field="taxonomy",
                        path=selection.path_tuple,
                    )
                )

        result_issues = TaxonomyValidationResult.from_issues(issues)

        if not result_issues.valid or not resolved:
            return TaxonomyBuildResult(
                selection=selection,
                family_slug=normalized_family_slug,
                object_kind=normalized_object_kind,
                taxonomy_version=registry.taxonomy_version,
                resolved=resolved,
                source_parts=selection.source_parts(normalized_family_slug),
                source_path=selection.source_path(normalized_family_slug),
                classification_path=selection.classification_path,
                family_id="",
                package_id="",
                issues=result_issues,
            )

        try:
            source_parts = resolved.selection.source_parts(normalized_family_slug)
            source_path = resolved.selection.source_path(normalized_family_slug)
            family_id = resolved.family_id(
                normalized_family_slug,
                prefix=config.family_id_prefix,
            )
            package_id = resolved.package_id(
                normalized_family_slug,
                prefix=config.package_id_prefix,
            )
        except Exception as exc:
            result_issues = result_issues.add(
                TaxonomyIssue.error(
                    "taxonomy_reference_build_failed",
                    f"Could not build taxonomy reference: {exc}",
                    field="taxonomy",
                    path=selection.path_tuple,
                )
            )
            source_parts = resolved.selection.source_parts(normalized_family_slug)
            source_path = resolved.selection.source_path(normalized_family_slug)
            family_id = ""
            package_id = ""

        return TaxonomyBuildResult(
            selection=resolved.selection,
            family_slug=normalized_family_slug,
            object_kind=normalized_object_kind,
            taxonomy_version=registry.taxonomy_version,
            resolved=resolved,
            source_parts=source_parts,
            source_path=source_path,
            classification_path=resolved.classification_path,
            family_id=family_id,
            package_id=package_id,
            issues=result_issues,
        )

    def build_family_reference_from_payload(
        self,
        payload: Any,
        *,
        family_slug: Any = "",
        force_reload: bool = False,
    ) -> TaxonomyBuildResult:
        source = as_mapping(payload)
        selection = TaxonomySelection.from_payload(source)

        resolved_family_slug = normalize_slug(
            family_slug
            or source.get("family_slug")
            or source.get("slug")
            or source.get("family_id_slug")
            or source.get("family_name"),
            default="",
        )

        return self.build_family_reference(
            domain=selection.domain,
            category=selection.category,
            subcategory=selection.subcategory,
            family_slug=resolved_family_slug,
            object_kind=source.get("object_kind", ""),
            force_reload=force_reload,
        )

    def build_classification_document(
        self,
        *,
        domain: Any,
        category: Any,
        subcategory: Any,
        object_kind: Any = "",
        include_node_metadata: bool = True,
        force_reload: bool = False,
    ) -> Dict[str, Any]:
        """
        Build a family/classification.json-compatible document fragment.

        This is intended for create/default generation.
        """

        registry = self.load_registry(force_reload=force_reload)
        resolved = self.resolve_selection(
            domain,
            category,
            subcategory,
            force_reload=force_reload,
        )

        payload: Dict[str, Any] = {
            "taxonomy_version": registry.taxonomy_version,
            "domain": resolved.selection.domain,
            "category": resolved.selection.category,
            "subcategory": resolved.selection.subcategory,
            "classification_path": resolved.classification_path,
            "labels": {
                "domain": resolved.domain.label,
                "category": resolved.category.label,
                "subcategory": resolved.subcategory.label,
            },
        }

        normalized_object_kind = normalize_slug(object_kind, default="")
        if normalized_object_kind:
            payload["object_kind"] = normalized_object_kind

        if include_node_metadata:
            payload["nodes"] = {
                "domain": resolved.domain.to_dict(),
                "category": resolved.category.to_dict(),
                "subcategory": resolved.subcategory.to_dict(),
            }
            payload["tags"] = {
                "domain": list(resolved.domain.tags),
                "category": list(resolved.category.tags),
                "subcategory": list(resolved.subcategory.tags),
            }
            payload["use_contexts"] = sorted(
                set(
                    list(resolved.domain.use_contexts)
                    + list(resolved.category.use_contexts)
                    + list(resolved.subcategory.use_contexts)
                )
            )

        return make_json_safe(payload)

    def build_manifest_taxonomy_fragment(
        self,
        *,
        domain: Any,
        category: Any,
        subcategory: Any,
        family_slug: Any,
        object_kind: Any = "",
        force_reload: bool = False,
    ) -> Dict[str, Any]:
        """
        Build a manifest-friendly taxonomy fragment.

        This does not attempt to build the whole manifest; it only returns the
        taxonomy-related identity data.
        """

        reference = self.build_family_reference(
            domain=domain,
            category=category,
            subcategory=subcategory,
            family_slug=family_slug,
            object_kind=object_kind,
            force_reload=force_reload,
        )

        return make_json_safe(
            {
                "valid": reference.valid,
                "taxonomy_version": reference.taxonomy_version,
                "classification_path": reference.classification_path,
                "source_path": reference.source_path,
                "family_id": reference.family_id,
                "package_id": reference.package_id,
                "domain": reference.selection.domain,
                "category": reference.selection.category,
                "subcategory": reference.selection.subcategory,
                "family_slug": reference.family_slug,
                "object_kind": reference.object_kind,
                "issues": reference.issues.to_dict(),
            }
        )

    def validate_source_path(
        self,
        source_path: Any,
        *,
        object_kind: Any = "",
        expect_family_slug: bool = True,
        force_reload: bool = False,
    ) -> TaxonomySourcePathValidation:
        registry = self.load_registry(force_reload=force_reload)

        return self.get_validator(registry=registry).validate_source_path(
            source_path,
            object_kind=object_kind,
            expect_family_slug=expect_family_slug,
        )

    def normalize_source_path(self, source_path: Any) -> str:
        return "/".join(normalize_source_path_parts(source_path))

    def validate_classification_payload(
        self,
        payload: Any,
        *,
        object_kind: Any = "",
        force_reload: bool = False,
    ) -> TaxonomyValidationResult:
        registry = self.load_registry(force_reload=force_reload)

        return self.get_validator(registry=registry).validate_classification_payload(
            payload,
            object_kind=object_kind,
        )

    def get_domain_options(
        self,
        *,
        include_inactive: Optional[bool] = None,
        force_reload: bool = False,
    ) -> List[Dict[str, Any]]:
        return list(
            self.get_options_payload(
                include_inactive=include_inactive,
                force_reload=force_reload,
            ).get("domains", [])
        )

    def get_category_options(
        self,
        domain: Any,
        *,
        include_inactive: Optional[bool] = None,
        force_reload: bool = False,
    ) -> List[Dict[str, Any]]:
        options = self.get_options_payload(
            include_inactive=include_inactive,
            force_reload=force_reload,
        )
        domain_id = normalize_slug(domain, default="")
        return list(options.get("categories_by_domain", {}).get(domain_id, []))

    def get_subcategory_options(
        self,
        domain: Any,
        category: Any,
        *,
        include_inactive: Optional[bool] = None,
        force_reload: bool = False,
    ) -> List[Dict[str, Any]]:
        options = self.get_options_payload(
            include_inactive=include_inactive,
            force_reload=force_reload,
        )
        domain_id = normalize_slug(domain, default="")
        category_id = normalize_slug(category, default="")
        key = f"{domain_id}/{category_id}"
        return list(options.get("subcategories_by_category", {}).get(key, []))

    def _load_registry_with_result(
        self,
        *,
        force_reload: bool = False,
        allow_stale_on_error: Optional[bool] = None,
    ) -> Tuple[TaxonomyRegistryModel, Optional[TaxonomyRegistryLoadResult]]:
        if self._static_registry is not None:
            return self._static_registry, None

        resolved_allow_stale = (
            self.config.allow_stale_on_error
            if self.config is not None and allow_stale_on_error is None
            else DEFAULT_ALLOW_STALE_ON_ERROR
            if allow_stale_on_error is None
            else bool(allow_stale_on_error)
        )

        try:
            result = self.registry_loader.load_result(
                force_reload=force_reload,
                allow_stale_on_error=resolved_allow_stale,
            )
            registry = result.require_registry()
            return registry, result
        except TaxonomyRegistryLoadError:
            raise
        except Exception as exc:
            raise TaxonomyServiceUnavailableError(
                f"Taxonomy registry is unavailable: {exc}"
            ) from exc

    def _effective_config(self, registry: TaxonomyRegistryModel) -> TaxonomyServiceConfig:
        if self.config:
            return self.config

        return TaxonomyServiceConfig.from_registry(registry)

    def _cache_key(
        self,
        name: str,
        registry: TaxonomyRegistryModel,
        load_result: Optional[TaxonomyRegistryLoadResult],
        *parts: Any,
    ) -> Tuple[Any, ...]:
        if load_result is not None:
            registry_key = load_result.fingerprint.cache_key
        else:
            registry_key = f"static:{registry.taxonomy_version}:{id(registry)}"

        return (name, registry_key, *parts)

    def _cache_get(self, key: Tuple[Any, ...]) -> Optional[Dict[str, Any]]:
        config = self._safe_current_config()

        if not config.cache_payloads:
            return None

        with self._lock:
            entry = self._payload_cache.get(key)
            if not entry:
                return None

            return copy_payload(entry.payload)

    def _cache_set(self, key: Tuple[Any, ...], payload: Mapping[str, Any]) -> None:
        config = self._safe_current_config()

        if not config.cache_payloads:
            return

        with self._lock:
            self._payload_cache[key] = TaxonomyPayloadCacheEntry(
                key=key,
                payload=copy_payload(payload),
            )

            if key in self._payload_cache_order:
                self._payload_cache_order.remove(key)

            self._payload_cache_order.append(key)

            max_items = safe_int(config.cache_max_items, DEFAULT_CACHE_MAX_ITEMS, minimum=1)

            while len(self._payload_cache_order) > max_items:
                oldest = self._payload_cache_order.pop(0)
                self._payload_cache.pop(oldest, None)

    def _safe_current_config(self) -> TaxonomyServiceConfig:
        if self.config:
            return self.config

        try:
            if self._static_registry:
                return TaxonomyServiceConfig.from_registry(self._static_registry)

            cached = self.registry_loader.get_cached_registry()
            if cached:
                return TaxonomyServiceConfig.from_registry(cached)
        except Exception:
            pass

        return TaxonomyServiceConfig()


_DEFAULT_SERVICE_LOCK = RLock()
_DEFAULT_SERVICE: Optional[TaxonomyService] = None


def get_default_taxonomy_service(
    *,
    force_new: bool = False,
    registry_loader: Optional[TaxonomyRegistry] = None,
    registry: Optional[TaxonomyRegistryModel] = None,
    config: Optional[TaxonomyServiceConfig] = None,
) -> TaxonomyService:
    """Return the process-wide default taxonomy service."""

    global _DEFAULT_SERVICE

    with _DEFAULT_SERVICE_LOCK:
        if force_new or _DEFAULT_SERVICE is None or registry is not None or registry_loader is not None:
            _DEFAULT_SERVICE = TaxonomyService(
                registry_loader=registry_loader,
                registry=registry,
                config=config,
            )

        return _DEFAULT_SERVICE


def reset_default_taxonomy_service() -> None:
    """Reset the process-wide default taxonomy service."""

    global _DEFAULT_SERVICE

    with _DEFAULT_SERVICE_LOCK:
        _DEFAULT_SERVICE = None


def copy_payload(payload: Mapping[str, Any]) -> Dict[str, Any]:
    """
    Return a JSON-safe deep copy-like payload.

    make_json_safe recursively rebuilds dict/list/tuple structures, which is
    sufficient for route payload caching.
    """

    safe_payload = make_json_safe(payload)
    if isinstance(safe_payload, dict):
        return safe_payload
    return {"value": safe_payload}


def as_mapping(value: Any) -> Mapping[str, Any]:
    if isinstance(value, Mapping):
        return value

    return {}


__all__ = [
    "DEFAULT_ALLOW_STALE_ON_ERROR",
    "DEFAULT_CACHE_MAX_ITEMS",
    "DEFAULT_CACHE_PAYLOADS",
    "DEFAULT_INCLUDE_INACTIVE",
    "TAXONOMY_REQUIRED_FIELDS",
    "TaxonomyBuildResult",
    "TaxonomyCounts",
    "TaxonomyPayloadCacheEntry",
    "TaxonomySelectionError",
    "TaxonomyService",
    "TaxonomyServiceConfig",
    "TaxonomyServiceError",
    "TaxonomyServiceUnavailableError",
    "as_mapping",
    "copy_payload",
    "get_default_taxonomy_service",
    "reset_default_taxonomy_service",
]