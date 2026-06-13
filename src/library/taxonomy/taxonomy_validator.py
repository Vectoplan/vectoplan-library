# services/vectoplan-library/src/library/taxonomy/taxonomy_validator.py
"""
VECTOPLAN Library Taxonomy Validator.

This module validates the canonical VPLIB taxonomy registry and related runtime
inputs such as Create-Wizard selections, source paths, family IDs and package IDs.

It is intentionally framework-free:
- no Flask imports
- no route imports
- no scanner imports
- no create-service imports

Responsibilities:
- validate raw taxonomy JSON dictionaries before and after model parsing
- validate TaxonomyRegistryModel structure
- validate domain/category/subcategory consistency
- validate object_kind constraints
- validate canonical source paths
- validate expected family_id/package_id patterns
- provide robust, API-friendly TaxonomyValidationResult objects

The validator is deliberately strict enough to prevent taxonomy drift, but it
does not perform file I/O. Loading belongs to taxonomy_registry.py.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from functools import cached_property
from typing import Any, Dict, Iterable, List, Mapping, Optional, Sequence, Set, Tuple, Union

try:
    from .taxonomy_models import (
        DEFAULT_SCHEMA_VERSION,
        DEFAULT_TAXONOMY_VERSION,
        PACKAGE_ID_PREFIX,
        TAXONOMY_ID_PREFIX,
        TaxonomyCategory,
        TaxonomyConstraints,
        TaxonomyDomain,
        TaxonomyIssue,
        TaxonomyLevel,
        TaxonomyModelError,
        TaxonomyNode,
        TaxonomyRegistryModel,
        TaxonomyResolvedSelection,
        TaxonomySelection,
        TaxonomyStatus,
        TaxonomySubcategory,
        TaxonomyValidationResult,
        as_mapping,
        as_sequence,
        coerce_slug_tuple,
        first_existing,
        is_valid_slug,
        make_json_safe,
        normalize_identifier_prefix,
        normalize_slug,
        safe_bool,
        safe_int,
        safe_str,
    )
except ImportError:  # pragma: no cover - defensive fallback for direct script execution
    from taxonomy_models import (  # type: ignore
        DEFAULT_SCHEMA_VERSION,
        DEFAULT_TAXONOMY_VERSION,
        PACKAGE_ID_PREFIX,
        TAXONOMY_ID_PREFIX,
        TaxonomyCategory,
        TaxonomyConstraints,
        TaxonomyDomain,
        TaxonomyIssue,
        TaxonomyLevel,
        TaxonomyModelError,
        TaxonomyNode,
        TaxonomyRegistryModel,
        TaxonomyResolvedSelection,
        TaxonomySelection,
        TaxonomyStatus,
        TaxonomySubcategory,
        TaxonomyValidationResult,
        as_mapping,
        as_sequence,
        coerce_slug_tuple,
        first_existing,
        is_valid_slug,
        make_json_safe,
        normalize_identifier_prefix,
        normalize_slug,
        safe_bool,
        safe_int,
        safe_str,
    )


KNOWN_OBJECT_KINDS: Tuple[str, ...] = (
    "cell_block",
    "multi_cell_module",
    "catalog_object",
    "adaptive_system",
)

KNOWN_VPLIB_MODULES: Tuple[str, ...] = (
    "family",
    "variants",
    "editor",
    "render",
    "physical",
    "material",
    "calculation",
    "analysis",
    "dynamic",
    "manufacturer",
    "docs",
    "tests",
)

RESERVED_TOP_LEVEL_KEYS: Tuple[str, ...] = (
    "schema_version",
    "taxonomy_version",
    "version",
    "label",
    "description",
    "constraints",
    "defaults",
    "metadata",
    "domains",
    "tabs",
    "reiter",
)

REQUIRED_NODE_FIELDS: Tuple[str, ...] = (
    "id",
    "label",
)

CANONICAL_SOURCE_DEPTH = 4
LEGACY_SOURCE_DEPTH = 3


class TaxonomyValidatorError(ValueError):
    """Raised when validator execution itself fails unexpectedly."""


@dataclass(frozen=True)
class TaxonomyValidatorConfig:
    """Configuration for taxonomy validation behavior."""

    known_object_kinds: Tuple[str, ...] = KNOWN_OBJECT_KINDS
    known_modules: Tuple[str, ...] = KNOWN_VPLIB_MODULES

    require_domains: bool = True
    require_categories: bool = True
    require_subcategories: bool = True

    min_domains: int = 1
    min_categories_per_domain: int = 1
    min_subcategories_per_category: int = 1

    allow_empty_labels: bool = False
    allow_disabled_nodes: bool = True
    allow_deprecated_nodes: bool = True
    allow_experimental_nodes: bool = True

    warn_on_duplicate_sort_order: bool = True
    warn_on_deprecated_nodes: bool = True
    warn_on_experimental_nodes: bool = False
    warn_on_unknown_modules: bool = True
    warn_on_missing_descriptions: bool = False

    enforce_unique_aliases_per_level: bool = True
    enforce_unique_source_segments_per_parent: bool = True
    enforce_object_kind_constraints: bool = True

    allow_legacy_source_depth: bool = True
    canonical_source_depth: int = CANONICAL_SOURCE_DEPTH

    family_id_prefix: str = TAXONOMY_ID_PREFIX
    package_id_prefix: str = PACKAGE_ID_PREFIX

    @classmethod
    def from_constraints(
        cls,
        constraints: Optional[TaxonomyConstraints],
        *,
        known_object_kinds: Sequence[str] = KNOWN_OBJECT_KINDS,
        known_modules: Sequence[str] = KNOWN_VPLIB_MODULES,
    ) -> "TaxonomyValidatorConfig":
        if constraints is None:
            return cls(
                known_object_kinds=tuple(known_object_kinds),
                known_modules=tuple(known_modules),
            )

        return cls(
            known_object_kinds=tuple(known_object_kinds),
            known_modules=tuple(known_modules),
            require_domains=True,
            require_categories=bool(constraints.require_category),
            require_subcategories=bool(constraints.require_subcategory),
            enforce_object_kind_constraints=bool(constraints.enforce_object_kind_constraints),
            allow_legacy_source_depth=bool(constraints.allow_legacy_source_depth),
            canonical_source_depth=safe_int(
                constraints.canonical_source_depth,
                CANONICAL_SOURCE_DEPTH,
                minimum=LEGACY_SOURCE_DEPTH,
            ),
            family_id_prefix=normalize_identifier_prefix(
                constraints.family_id_prefix,
                default=TAXONOMY_ID_PREFIX,
            ),
            package_id_prefix=normalize_identifier_prefix(
                constraints.package_id_prefix,
                default=PACKAGE_ID_PREFIX,
            ),
        )

    @property
    def known_object_kind_set(self) -> Set[str]:
        return set(coerce_slug_tuple(self.known_object_kinds))

    @property
    def known_module_set(self) -> Set[str]:
        return set(coerce_slug_tuple(self.known_modules))


@dataclass(frozen=True)
class TaxonomySourcePathValidation:
    """Structured result for source path validation."""

    valid: bool
    legacy: bool
    parts: Tuple[str, ...]
    domain: str = ""
    category: str = ""
    subcategory: str = ""
    family_slug: str = ""
    selection: Optional[TaxonomySelection] = None
    resolved: Optional[TaxonomyResolvedSelection] = None
    issues: TaxonomyValidationResult = field(default_factory=TaxonomyValidationResult.ok)

    @property
    def classification_path(self) -> str:
        if self.selection:
            return self.selection.classification_path
        return "/".join(part for part in (self.domain, self.category, self.subcategory) if part)

    @property
    def source_path(self) -> str:
        return "/".join(part for part in self.parts if part)

    def to_dict(self) -> Dict[str, Any]:
        return make_json_safe(
            {
                "valid": self.valid,
                "legacy": self.legacy,
                "parts": list(self.parts),
                "domain": self.domain,
                "category": self.category,
                "subcategory": self.subcategory,
                "family_slug": self.family_slug,
                "classification_path": self.classification_path,
                "source_path": self.source_path,
                "selection": self.selection.to_dict() if self.selection else None,
                "resolved": self.resolved.to_dict() if self.resolved else None,
                "issues": self.issues.to_dict(),
            }
        )


class TaxonomyValidator:
    """
    Validator for registry models and taxonomy-related runtime inputs.

    The class does not own or load the taxonomy data file. Pass a
    TaxonomyRegistryModel explicitly or validate raw data dictionaries with
    validate_raw_registry_data().
    """

    def __init__(
        self,
        registry: Optional[TaxonomyRegistryModel] = None,
        *,
        config: Optional[TaxonomyValidatorConfig] = None,
    ) -> None:
        self.registry = registry
        self.config = config or TaxonomyValidatorConfig.from_constraints(
            registry.constraints if registry else None
        )

    @cached_property
    def known_object_kinds(self) -> Set[str]:
        return self.config.known_object_kind_set

    @cached_property
    def known_modules(self) -> Set[str]:
        return self.config.known_module_set

    def with_registry(self, registry: TaxonomyRegistryModel) -> "TaxonomyValidator":
        return TaxonomyValidator(
            registry=registry,
            config=TaxonomyValidatorConfig.from_constraints(
                registry.constraints,
                known_object_kinds=tuple(self.known_object_kinds),
                known_modules=tuple(self.known_modules),
            ),
        )

    def validate_raw_registry_data(self, data: Any) -> TaxonomyValidationResult:
        """
        Validate raw JSON-like registry data.

        This first checks the raw dictionary shape, then attempts to parse it
        through TaxonomyRegistryModel, then validates the parsed model.
        """

        issues: List[TaxonomyIssue] = []

        try:
            source = as_mapping(data)
            if not source:
                return TaxonomyValidationResult.from_issues(
                    (
                        TaxonomyIssue.error(
                            "taxonomy_raw_registry_empty",
                            "Taxonomy registry data must be a non-empty object.",
                            field="registry",
                        ),
                    )
                )

            issues.extend(self._validate_raw_root(source))

            domains_raw = first_existing(source, "domains", "tabs", "reiter", default=())
            issues.extend(
                self._validate_raw_node_list(
                    domains_raw,
                    level=TaxonomyLevel.DOMAIN,
                    parent_path=(),
                )
            )

            model: Optional[TaxonomyRegistryModel] = None
            try:
                model = TaxonomyRegistryModel.from_dict(source)
            except Exception as exc:
                issues.append(
                    TaxonomyIssue.error(
                        "taxonomy_model_parse_failed",
                        f"Taxonomy registry could not be parsed into model objects: {exc}",
                        field="registry",
                    )
                )

            if model is not None:
                model_result = self.with_registry(model).validate_registry_model(model)
                issues.extend(model_result.issues)

            return TaxonomyValidationResult.from_issues(issues)

        except Exception as exc:
            return TaxonomyValidationResult.from_issues(
                (
                    TaxonomyIssue.error(
                        "taxonomy_raw_validation_failed",
                        f"Taxonomy raw validation failed unexpectedly: {exc}",
                        field="registry",
                    ),
                )
            )

    def validate_registry_model(
        self,
        registry: Optional[TaxonomyRegistryModel] = None,
    ) -> TaxonomyValidationResult:
        """Validate a parsed TaxonomyRegistryModel."""

        model = registry or self.registry
        if model is None:
            return TaxonomyValidationResult.from_issues(
                (
                    TaxonomyIssue.error(
                        "taxonomy_registry_missing",
                        "Taxonomy registry model is required.",
                        field="registry",
                    ),
                )
            )

        issues: List[TaxonomyIssue] = []

        try:
            issues.extend(self._validate_registry_header(model))
            issues.extend(self._validate_registry_domains(model))
            issues.extend(self._validate_registry_uniqueness(model))
            issues.extend(self._validate_registry_defaults(model))
            return TaxonomyValidationResult.from_issues(issues)
        except Exception as exc:
            return TaxonomyValidationResult.from_issues(
                (
                    TaxonomyIssue.error(
                        "taxonomy_registry_validation_failed",
                        f"Taxonomy registry validation failed unexpectedly: {exc}",
                        field="registry",
                    ),
                )
            )

    def validate_selection(
        self,
        domain: Any,
        category: Any,
        subcategory: Any,
        *,
        object_kind: Any = "",
        allow_deprecated: Optional[bool] = None,
        allow_experimental: Optional[bool] = None,
    ) -> TaxonomyValidationResult:
        """Validate a Create-Wizard/API taxonomy selection."""

        if self.registry is None:
            return TaxonomyValidationResult.from_issues(
                (
                    TaxonomyIssue.error(
                        "taxonomy_registry_missing",
                        "Cannot validate taxonomy selection without registry.",
                        field="registry",
                    ),
                )
            )

        try:
            return self.registry.validate_selection(
                domain,
                category,
                subcategory,
                object_kind=object_kind,
                allow_deprecated=allow_deprecated,
                allow_experimental=allow_experimental,
            )
        except Exception as exc:
            return TaxonomyValidationResult.from_issues(
                (
                    TaxonomyIssue.error(
                        "taxonomy_selection_validation_failed",
                        f"Taxonomy selection validation failed unexpectedly: {exc}",
                        field="taxonomy",
                    ),
                )
            )

    def resolve_selection(
        self,
        domain: Any,
        category: Any,
        subcategory: Any,
    ) -> Optional[TaxonomyResolvedSelection]:
        if self.registry is None:
            return None
        try:
            return self.registry.resolve(domain, category, subcategory)
        except Exception:
            return None

    def validate_source_path(
        self,
        source_path: Union[str, Sequence[str]],
        *,
        object_kind: Any = "",
        expect_family_slug: bool = True,
    ) -> TaxonomySourcePathValidation:
        """
        Validate a source path below src/library/source.

        Canonical path:
            <domain>/<category>/<subcategory>/<family_slug>

        Legacy path:
            <domain>/<category>/<family_slug>

        Legacy paths are accepted only when config.allow_legacy_source_depth is true.
        """

        issues: List[TaxonomyIssue] = []

        try:
            parts = normalize_source_path_parts(source_path)
            depth = len(parts)

            if expect_family_slug:
                valid_depths = {self.config.canonical_source_depth}
                if self.config.allow_legacy_source_depth:
                    valid_depths.add(LEGACY_SOURCE_DEPTH)

                if depth not in valid_depths:
                    issues.append(
                        TaxonomyIssue.error(
                            "taxonomy_source_path_depth_invalid",
                            (
                                "Source path must be "
                                "'<domain>/<category>/<subcategory>/<family_slug>'"
                                + (
                                    " or legacy '<domain>/<category>/<family_slug>'"
                                    if self.config.allow_legacy_source_depth
                                    else ""
                                )
                                + "."
                            ),
                            field="source_path",
                            path=parts,
                            details={
                                "depth": depth,
                                "expected_depth": self.config.canonical_source_depth,
                                "allow_legacy_source_depth": self.config.allow_legacy_source_depth,
                            },
                        )
                    )
                    return self._source_path_result(parts, issues=issues)

            else:
                valid_depths = {3}
                if depth not in valid_depths:
                    issues.append(
                        TaxonomyIssue.error(
                            "taxonomy_classification_path_depth_invalid",
                            "Classification path must be '<domain>/<category>/<subcategory>'.",
                            field="classification_path",
                            path=parts,
                            details={"depth": depth, "expected_depth": 3},
                        )
                    )
                    return self._source_path_result(parts, issues=issues)

            legacy = expect_family_slug and depth == LEGACY_SOURCE_DEPTH

            domain = parts[0] if depth >= 1 else ""
            category = parts[1] if depth >= 2 else ""

            if legacy:
                subcategory = ""
                family_slug = parts[2] if depth >= 3 else ""
                issues.append(
                    TaxonomyIssue.warning(
                        "taxonomy_source_path_legacy_depth",
                        (
                            "Legacy source path depth detected. New packages should use "
                            "'<domain>/<category>/<subcategory>/<family_slug>'."
                        ),
                        field="source_path",
                        path=parts,
                    )
                )
            else:
                subcategory = parts[2] if depth >= 3 else ""
                family_slug = parts[3] if expect_family_slug and depth >= 4 else ""

            if expect_family_slug and not family_slug:
                issues.append(
                    TaxonomyIssue.error(
                        "taxonomy_source_path_family_slug_missing",
                        "Source path requires a family_slug as final segment.",
                        field="family_slug",
                        path=parts,
                    )
                )

            if family_slug and not is_valid_slug(family_slug):
                issues.append(
                    TaxonomyIssue.error(
                        "taxonomy_source_path_family_slug_invalid",
                        f"Invalid family_slug '{family_slug}' in source path.",
                        field="family_slug",
                        path=parts,
                        details={"family_slug": family_slug},
                    )
                )

            selection_result = TaxonomyValidationResult.ok()
            resolved: Optional[TaxonomyResolvedSelection] = None
            selection = TaxonomySelection.from_values(domain, category, subcategory)

            if legacy:
                if self.registry is not None:
                    domain_node = self.registry.get_domain(domain)
                    category_node = self.registry.get_category(domain, category)
                    if not domain_node:
                        issues.append(
                            TaxonomyIssue.error(
                                "taxonomy_source_path_domain_unknown",
                                f"Unknown domain '{domain}' in legacy source path.",
                                field="domain",
                                path=parts,
                            )
                        )
                    if domain_node and not category_node:
                        issues.append(
                            TaxonomyIssue.error(
                                "taxonomy_source_path_category_unknown",
                                f"Unknown category '{category}' in legacy source path.",
                                field="category",
                                path=parts,
                            )
                        )
            else:
                selection_result = self.validate_selection(
                    domain,
                    category,
                    subcategory,
                    object_kind=object_kind,
                )
                issues.extend(selection_result.issues)

                if selection_result.valid:
                    resolved = self.resolve_selection(domain, category, subcategory)

            result = TaxonomyValidationResult.from_issues(issues)

            return TaxonomySourcePathValidation(
                valid=result.valid,
                legacy=legacy,
                parts=parts,
                domain=domain,
                category=category,
                subcategory=subcategory,
                family_slug=family_slug,
                selection=selection,
                resolved=resolved,
                issues=result,
            )

        except Exception as exc:
            parts = normalize_source_path_parts(source_path)
            issues.append(
                TaxonomyIssue.error(
                    "taxonomy_source_path_validation_failed",
                    f"Source path validation failed unexpectedly: {exc}",
                    field="source_path",
                    path=parts,
                )
            )
            return self._source_path_result(parts, issues=issues)

    def validate_family_identifiers(
        self,
        *,
        domain: Any,
        category: Any,
        subcategory: Any,
        family_slug: Any,
        family_id: Any = "",
        package_id: Any = "",
    ) -> TaxonomyValidationResult:
        """
        Validate family_id and package_id against the canonical taxonomy pattern.

        Expected:
            family_id:  vp.<domain>.<category>.<subcategory>.<family_slug>
            package_id: vplib.vp.<domain>.<category>.<subcategory>.<family_slug>
        """

        issues: List[TaxonomyIssue] = []
        selection = TaxonomySelection.from_values(domain, category, subcategory)
        normalized_family_slug = normalize_slug(family_slug, default="")
        normalized_family_id = safe_str(family_id, "")
        normalized_package_id = safe_str(package_id, "")

        selection_result = self.validate_selection(
            selection.domain,
            selection.category,
            selection.subcategory,
        )
        issues.extend(selection_result.issues)

        if not normalized_family_slug:
            issues.append(
                TaxonomyIssue.error(
                    "taxonomy_family_slug_missing",
                    "family_slug is required to validate family identifiers.",
                    field="family_slug",
                )
            )
        elif not is_valid_slug(normalized_family_slug):
            issues.append(
                TaxonomyIssue.error(
                    "taxonomy_family_slug_invalid",
                    f"Invalid family_slug '{normalized_family_slug}'.",
                    field="family_slug",
                )
            )

        if selection_result.valid and normalized_family_slug:
            try:
                expected_family_id = selection.family_id(
                    normalized_family_slug,
                    prefix=self.config.family_id_prefix,
                )
                expected_package_id = selection.package_id(
                    normalized_family_slug,
                    prefix=self.config.package_id_prefix,
                )

                if normalized_family_id and normalized_family_id != expected_family_id:
                    issues.append(
                        TaxonomyIssue.error(
                            "taxonomy_family_id_mismatch",
                            "family_id does not match taxonomy selection and family_slug.",
                            field="family_id",
                            details={
                                "actual": normalized_family_id,
                                "expected": expected_family_id,
                            },
                        )
                    )

                if normalized_package_id and normalized_package_id != expected_package_id:
                    issues.append(
                        TaxonomyIssue.error(
                            "taxonomy_package_id_mismatch",
                            "package_id does not match taxonomy selection and family_slug.",
                            field="package_id",
                            details={
                                "actual": normalized_package_id,
                                "expected": expected_package_id,
                            },
                        )
                    )

            except Exception as exc:
                issues.append(
                    TaxonomyIssue.error(
                        "taxonomy_identifier_validation_failed",
                        f"Could not build expected family/package identifiers: {exc}",
                        field="identifiers",
                    )
                )

        return TaxonomyValidationResult.from_issues(issues)

    def validate_classification_payload(
        self,
        payload: Any,
        *,
        object_kind: Any = "",
    ) -> TaxonomyValidationResult:
        """
        Validate a family/classification.json-like payload.

        Supported shapes:
            {
              "domain": "...",
              "category": "...",
              "subcategory": "..."
            }

        Also accepted:
            {
              "classification": {
                "domain": "...",
                "category": "...",
                "subcategory": "..."
              }
            }
        """

        source = as_mapping(payload)
        classification = as_mapping(source.get("classification")) or source
        selection = TaxonomySelection.from_payload(classification)
        return self.validate_selection(
            selection.domain,
            selection.category,
            selection.subcategory,
            object_kind=object_kind,
        )

    def _validate_raw_root(self, source: Mapping[str, Any]) -> List[TaxonomyIssue]:
        issues: List[TaxonomyIssue] = []

        schema_version = safe_str(source.get("schema_version"), "")
        taxonomy_version = safe_str(first_existing(source, "taxonomy_version", "version", default=""), "")
        label = safe_str(source.get("label"), "")

        if not schema_version:
            issues.append(
                TaxonomyIssue.warning(
                    "taxonomy_schema_version_missing",
                    "Taxonomy registry should define schema_version.",
                    field="schema_version",
                )
            )

        if schema_version and schema_version != DEFAULT_SCHEMA_VERSION:
            issues.append(
                TaxonomyIssue.warning(
                    "taxonomy_schema_version_unexpected",
                    f"Unexpected taxonomy schema_version '{schema_version}'.",
                    field="schema_version",
                    details={"expected": DEFAULT_SCHEMA_VERSION, "actual": schema_version},
                )
            )

        if not taxonomy_version:
            issues.append(
                TaxonomyIssue.error(
                    "taxonomy_version_missing",
                    "Taxonomy registry must define taxonomy_version.",
                    field="taxonomy_version",
                )
            )

        if taxonomy_version and not is_reasonable_version_string(taxonomy_version):
            issues.append(
                TaxonomyIssue.warning(
                    "taxonomy_version_unusual",
                    f"Taxonomy version '{taxonomy_version}' has an unusual format.",
                    field="taxonomy_version",
                )
            )

        if not label:
            issues.append(
                TaxonomyIssue.warning(
                    "taxonomy_label_missing",
                    "Taxonomy registry should define a human-readable label.",
                    field="label",
                )
            )

        domains_raw = first_existing(source, "domains", "tabs", "reiter", default=())
        if not isinstance(domains_raw, list):
            issues.append(
                TaxonomyIssue.error(
                    "taxonomy_domains_not_list",
                    "Taxonomy registry field 'domains' must be a list.",
                    field="domains",
                )
            )
        elif self.config.require_domains and len(domains_raw) < self.config.min_domains:
            issues.append(
                TaxonomyIssue.error(
                    "taxonomy_domains_empty",
                    "Taxonomy registry must contain at least one domain.",
                    field="domains",
                )
            )

        constraints = as_mapping(source.get("constraints", {}))
        if constraints:
            canonical_depth = safe_int(
                constraints.get("canonical_source_depth"),
                CANONICAL_SOURCE_DEPTH,
                minimum=LEGACY_SOURCE_DEPTH,
            )
            if canonical_depth != CANONICAL_SOURCE_DEPTH:
                issues.append(
                    TaxonomyIssue.warning(
                        "taxonomy_canonical_depth_unexpected",
                        (
                            "Canonical source depth should normally be 4: "
                            "<domain>/<category>/<subcategory>/<family_slug>."
                        ),
                        field="constraints.canonical_source_depth",
                        details={"actual": canonical_depth, "expected": CANONICAL_SOURCE_DEPTH},
                    )
                )

        return issues

    def _validate_raw_node_list(
        self,
        nodes_raw: Any,
        *,
        level: TaxonomyLevel,
        parent_path: Tuple[str, ...],
    ) -> List[TaxonomyIssue]:
        issues: List[TaxonomyIssue] = []
        nodes = as_sequence(nodes_raw)

        if not isinstance(nodes_raw, (list, tuple)):
            issues.append(
                TaxonomyIssue.error(
                    "taxonomy_raw_node_list_invalid",
                    f"Taxonomy {level.value} list must be an array.",
                    field=level.value,
                    path=parent_path,
                )
            )
            return issues

        seen_ids: Set[str] = set()
        seen_aliases: Set[str] = set()
        seen_sort_orders: Dict[int, str] = {}

        for index, node_raw in enumerate(nodes):
            node_path = (*parent_path, f"{level.value}[{index}]")
            source = as_mapping(node_raw)

            if not source:
                issues.append(
                    TaxonomyIssue.error(
                        "taxonomy_raw_node_invalid",
                        f"Taxonomy {level.value} entry must be an object.",
                        field=level.value,
                        path=node_path,
                    )
                )
                continue

            node_id = normalize_slug(first_existing(source, "id", "slug", "key", "name", default=""), default="")
            label = safe_str(first_existing(source, "label", "title", "name", default=""), "")
            sort_order = safe_int(first_existing(source, "sort_order", "order", "position", default=1000), 1000)
            status = safe_str(source.get("status"), TaxonomyStatus.ACTIVE.value).strip().lower()
            aliases = coerce_slug_tuple(source.get("aliases", ()))
            source_segment = normalize_slug(
                first_existing(source, "source_path_segment", "path_segment", default=node_id),
                default="",
            )

            if not node_id:
                issues.append(
                    TaxonomyIssue.error(
                        "taxonomy_raw_node_id_missing",
                        f"Taxonomy {level.value} entry requires id.",
                        field="id",
                        path=node_path,
                    )
                )
            elif not is_valid_slug(node_id):
                issues.append(
                    TaxonomyIssue.error(
                        "taxonomy_raw_node_id_invalid",
                        f"Invalid taxonomy {level.value} id '{node_id}'.",
                        field="id",
                        path=node_path,
                    )
                )
            elif node_id in seen_ids:
                issues.append(
                    TaxonomyIssue.error(
                        "taxonomy_raw_node_id_duplicate",
                        f"Duplicate taxonomy {level.value} id '{node_id}'.",
                        field="id",
                        path=node_path,
                    )
                )
            else:
                seen_ids.add(node_id)

            if not label and not self.config.allow_empty_labels:
                issues.append(
                    TaxonomyIssue.error(
                        "taxonomy_raw_node_label_missing",
                        f"Taxonomy {level.value} '{node_id or index}' requires label.",
                        field="label",
                        path=node_path,
                    )
                )

            if source_segment and not is_valid_slug(source_segment):
                issues.append(
                    TaxonomyIssue.error(
                        "taxonomy_raw_source_path_segment_invalid",
                        f"Invalid source_path_segment '{source_segment}'.",
                        field="source_path_segment",
                        path=node_path,
                    )
                )

            if status and status not in {item.value for item in TaxonomyStatus}:
                issues.append(
                    TaxonomyIssue.warning(
                        "taxonomy_raw_node_status_unknown",
                        f"Unknown taxonomy status '{status}'.",
                        field="status",
                        path=node_path,
                    )
                )

            if self.config.warn_on_duplicate_sort_order and sort_order in seen_sort_orders:
                issues.append(
                    TaxonomyIssue.warning(
                        "taxonomy_raw_sort_order_duplicate",
                        (
                            f"Duplicate sort_order {sort_order} in {level.value} list. "
                            "This is allowed but may produce ambiguous UI order."
                        ),
                        field="sort_order",
                        path=node_path,
                        details={
                            "sort_order": sort_order,
                            "first_id": seen_sort_orders[sort_order],
                            "current_id": node_id,
                        },
                    )
                )
            else:
                seen_sort_orders[sort_order] = node_id

            for alias in aliases:
                if alias == node_id:
                    issues.append(
                        TaxonomyIssue.warning(
                            "taxonomy_raw_alias_same_as_id",
                            f"Alias '{alias}' is identical to node id.",
                            field="aliases",
                            path=node_path,
                        )
                    )
                if self.config.enforce_unique_aliases_per_level and alias in seen_aliases:
                    issues.append(
                        TaxonomyIssue.error(
                            "taxonomy_raw_alias_duplicate",
                            f"Duplicate alias '{alias}' in {level.value} list.",
                            field="aliases",
                            path=node_path,
                        )
                    )
                seen_aliases.add(alias)

            issues.extend(
                self._validate_raw_string_array(
                    source,
                    key="allowed_object_kinds",
                    known_values=self.known_object_kinds,
                    node_path=node_path,
                    allow_empty=True,
                )
            )
            issues.extend(
                self._validate_raw_string_array(
                    source,
                    key="recommended_object_kinds",
                    known_values=self.known_object_kinds,
                    node_path=node_path,
                    allow_empty=True,
                )
            )
            issues.extend(
                self._validate_raw_string_array(
                    source,
                    key="required_modules",
                    known_values=self.known_modules,
                    node_path=node_path,
                    allow_empty=True,
                    warn_unknown=self.config.warn_on_unknown_modules,
                )
            )
            issues.extend(
                self._validate_raw_string_array(
                    source,
                    key="recommended_modules",
                    known_values=self.known_modules,
                    node_path=node_path,
                    allow_empty=True,
                    warn_unknown=self.config.warn_on_unknown_modules,
                )
            )

            if self.config.warn_on_missing_descriptions and not safe_str(source.get("description"), ""):
                issues.append(
                    TaxonomyIssue.warning(
                        "taxonomy_raw_description_missing",
                        f"Taxonomy {level.value} '{node_id}' should define description.",
                        field="description",
                        path=node_path,
                    )
                )

            if level == TaxonomyLevel.DOMAIN:
                categories_raw = first_existing(source, "categories", "children", default=())
                if self.config.require_categories and len(as_sequence(categories_raw)) < self.config.min_categories_per_domain:
                    issues.append(
                        TaxonomyIssue.error(
                            "taxonomy_raw_domain_categories_empty",
                            f"Domain '{node_id}' must contain at least one category.",
                            field="categories",
                            path=node_path,
                        )
                    )
                issues.extend(
                    self._validate_raw_node_list(
                        categories_raw,
                        level=TaxonomyLevel.CATEGORY,
                        parent_path=(*parent_path, node_id or f"domain_{index}"),
                    )
                )

            elif level == TaxonomyLevel.CATEGORY:
                subcategories_raw = first_existing(source, "subcategories", "children", default=())
                if self.config.require_subcategories and len(as_sequence(subcategories_raw)) < self.config.min_subcategories_per_category:
                    issues.append(
                        TaxonomyIssue.error(
                            "taxonomy_raw_category_subcategories_empty",
                            f"Category '{node_id}' must contain at least one subcategory.",
                            field="subcategories",
                            path=node_path,
                        )
                    )
                issues.extend(
                    self._validate_raw_node_list(
                        subcategories_raw,
                        level=TaxonomyLevel.SUBCATEGORY,
                        parent_path=(*parent_path, node_id or f"category_{index}"),
                    )
                )

        return issues

    def _validate_raw_string_array(
        self,
        source: Mapping[str, Any],
        *,
        key: str,
        known_values: Set[str],
        node_path: Tuple[str, ...],
        allow_empty: bool = True,
        warn_unknown: bool = False,
    ) -> List[TaxonomyIssue]:
        issues: List[TaxonomyIssue] = []

        if key not in source:
            return issues

        raw_value = source.get(key)
        if raw_value in (None, ""):
            if not allow_empty:
                issues.append(
                    TaxonomyIssue.error(
                        "taxonomy_raw_array_empty",
                        f"Field '{key}' must not be empty.",
                        field=key,
                        path=node_path,
                    )
                )
            return issues

        if not isinstance(raw_value, list):
            issues.append(
                TaxonomyIssue.error(
                    "taxonomy_raw_array_invalid",
                    f"Field '{key}' must be an array.",
                    field=key,
                    path=node_path,
                )
            )
            return issues

        seen: Set[str] = set()
        for index, item in enumerate(raw_value):
            normalized = normalize_slug(item, default="")
            item_path = (*node_path, f"{key}[{index}]")

            if not normalized:
                issues.append(
                    TaxonomyIssue.error(
                        "taxonomy_raw_array_item_empty",
                        f"Field '{key}' contains an empty item.",
                        field=key,
                        path=item_path,
                    )
                )
                continue

            if normalized in seen:
                issues.append(
                    TaxonomyIssue.warning(
                        "taxonomy_raw_array_item_duplicate",
                        f"Field '{key}' contains duplicate item '{normalized}'.",
                        field=key,
                        path=item_path,
                    )
                )
            seen.add(normalized)

            if known_values and normalized not in known_values:
                factory = TaxonomyIssue.warning if warn_unknown else TaxonomyIssue.error
                issues.append(
                    factory(
                        "taxonomy_raw_array_item_unknown",
                        f"Field '{key}' contains unknown item '{normalized}'.",
                        field=key,
                        path=item_path,
                        details={
                            "item": normalized,
                            "known_values": sorted(known_values),
                        },
                    )
                )

        return issues

    def _validate_registry_header(self, registry: TaxonomyRegistryModel) -> List[TaxonomyIssue]:
        issues: List[TaxonomyIssue] = []

        if not safe_str(registry.schema_version, ""):
            issues.append(
                TaxonomyIssue.warning(
                    "taxonomy_schema_version_missing",
                    "Taxonomy registry should define schema_version.",
                    field="schema_version",
                )
            )

        if not safe_str(registry.taxonomy_version, ""):
            issues.append(
                TaxonomyIssue.error(
                    "taxonomy_version_missing",
                    "Taxonomy registry must define taxonomy_version.",
                    field="taxonomy_version",
                )
            )

        if not safe_str(registry.label, ""):
            issues.append(
                TaxonomyIssue.warning(
                    "taxonomy_label_missing",
                    "Taxonomy registry should define label.",
                    field="label",
                )
            )

        if registry.constraints.canonical_source_depth != CANONICAL_SOURCE_DEPTH:
            issues.append(
                TaxonomyIssue.warning(
                    "taxonomy_canonical_source_depth_unexpected",
                    "Canonical source depth should be 4.",
                    field="constraints.canonical_source_depth",
                    details={
                        "actual": registry.constraints.canonical_source_depth,
                        "expected": CANONICAL_SOURCE_DEPTH,
                    },
                )
            )

        return issues

    def _validate_registry_domains(self, registry: TaxonomyRegistryModel) -> List[TaxonomyIssue]:
        issues: List[TaxonomyIssue] = []

        if self.config.require_domains and len(registry.domains) < self.config.min_domains:
            issues.append(
                TaxonomyIssue.error(
                    "taxonomy_domains_empty",
                    "Taxonomy registry must contain at least one domain.",
                    field="domains",
                )
            )

        for domain in registry.domains:
            issues.extend(self._validate_domain(domain))

        return issues

    def _validate_domain(self, domain: TaxonomyDomain) -> List[TaxonomyIssue]:
        issues: List[TaxonomyIssue] = []
        path = (domain.id,)

        issues.extend(self._validate_node_common(domain, path=path))

        if domain.level != TaxonomyLevel.DOMAIN:
            issues.append(
                TaxonomyIssue.error(
                    "taxonomy_domain_level_invalid",
                    f"Domain '{domain.id}' has invalid level '{domain.level.value}'.",
                    field="level",
                    path=path,
                )
            )

        if self.config.require_categories and len(domain.categories) < self.config.min_categories_per_domain:
            issues.append(
                TaxonomyIssue.error(
                    "taxonomy_domain_categories_empty",
                    f"Domain '{domain.id}' must contain at least one category.",
                    field="categories",
                    path=path,
                )
            )

        issues.extend(
            self._validate_child_uniqueness(
                children=domain.categories,
                parent_path=path,
                child_level=TaxonomyLevel.CATEGORY,
            )
        )

        for category in domain.categories:
            issues.extend(self._validate_category(category, domain=domain))

        return issues

    def _validate_category(self, category: TaxonomyCategory, *, domain: TaxonomyDomain) -> List[TaxonomyIssue]:
        issues: List[TaxonomyIssue] = []
        path = (domain.id, category.id)

        issues.extend(self._validate_node_common(category, path=path))

        if category.level != TaxonomyLevel.CATEGORY:
            issues.append(
                TaxonomyIssue.error(
                    "taxonomy_category_level_invalid",
                    f"Category '{category.id}' has invalid level '{category.level.value}'.",
                    field="level",
                    path=path,
                )
            )

        if self.config.require_subcategories and len(category.subcategories) < self.config.min_subcategories_per_category:
            issues.append(
                TaxonomyIssue.error(
                    "taxonomy_category_subcategories_empty",
                    f"Category '{domain.id}/{category.id}' must contain at least one subcategory.",
                    field="subcategories",
                    path=path,
                )
            )

        issues.extend(
            self._validate_child_uniqueness(
                children=category.subcategories,
                parent_path=path,
                child_level=TaxonomyLevel.SUBCATEGORY,
            )
        )

        for subcategory in category.subcategories:
            issues.extend(
                self._validate_subcategory(
                    subcategory,
                    domain=domain,
                    category=category,
                )
            )

        return issues

    def _validate_subcategory(
        self,
        subcategory: TaxonomySubcategory,
        *,
        domain: TaxonomyDomain,
        category: TaxonomyCategory,
    ) -> List[TaxonomyIssue]:
        issues: List[TaxonomyIssue] = []
        path = (domain.id, category.id, subcategory.id)

        issues.extend(self._validate_node_common(subcategory, path=path))

        if subcategory.level != TaxonomyLevel.SUBCATEGORY:
            issues.append(
                TaxonomyIssue.error(
                    "taxonomy_subcategory_level_invalid",
                    f"Subcategory '{subcategory.id}' has invalid level '{subcategory.level.value}'.",
                    field="level",
                    path=path,
                )
            )

        return issues

    def _validate_node_common(
        self,
        node: TaxonomyNode,
        *,
        path: Tuple[str, ...],
    ) -> List[TaxonomyIssue]:
        issues: List[TaxonomyIssue] = []

        if not node.id:
            issues.append(
                TaxonomyIssue.error(
                    "taxonomy_node_id_missing",
                    f"Taxonomy {node.level.value} requires id.",
                    field="id",
                    path=path,
                )
            )
        elif not is_valid_slug(node.id):
            issues.append(
                TaxonomyIssue.error(
                    "taxonomy_node_id_invalid",
                    f"Invalid taxonomy {node.level.value} id '{node.id}'.",
                    field="id",
                    path=path,
                )
            )

        if not node.label and not self.config.allow_empty_labels:
            issues.append(
                TaxonomyIssue.error(
                    "taxonomy_node_label_missing",
                    f"Taxonomy {node.level.value} '{node.id}' requires label.",
                    field="label",
                    path=path,
                )
            )

        if not node.source_path_segment:
            issues.append(
                TaxonomyIssue.error(
                    "taxonomy_node_source_segment_missing",
                    f"Taxonomy {node.level.value} '{node.id}' requires source_path_segment.",
                    field="source_path_segment",
                    path=path,
                )
            )
        elif not is_valid_slug(node.source_path_segment):
            issues.append(
                TaxonomyIssue.error(
                    "taxonomy_node_source_segment_invalid",
                    f"Invalid source_path_segment '{node.source_path_segment}'.",
                    field="source_path_segment",
                    path=path,
                )
            )

        if node.status == TaxonomyStatus.DISABLED and not self.config.allow_disabled_nodes:
            issues.append(
                TaxonomyIssue.error(
                    "taxonomy_node_disabled_not_allowed",
                    f"Disabled taxonomy node '{node.id}' is not allowed.",
                    field="status",
                    path=path,
                )
            )

        if node.status == TaxonomyStatus.DEPRECATED and self.config.warn_on_deprecated_nodes:
            issues.append(
                TaxonomyIssue.warning(
                    "taxonomy_node_deprecated",
                    f"Taxonomy {node.level.value} '{node.id}' is deprecated.",
                    field="status",
                    path=path,
                )
            )

        if node.status == TaxonomyStatus.EXPERIMENTAL and self.config.warn_on_experimental_nodes:
            issues.append(
                TaxonomyIssue.warning(
                    "taxonomy_node_experimental",
                    f"Taxonomy {node.level.value} '{node.id}' is experimental.",
                    field="status",
                    path=path,
                )
            )

        issues.extend(self._validate_object_kind_tuple(node.allowed_object_kinds, field_name="allowed_object_kinds", path=path))
        issues.extend(self._validate_object_kind_tuple(node.recommended_object_kinds, field_name="recommended_object_kinds", path=path))
        issues.extend(self._validate_module_tuple(node.required_modules, field_name="required_modules", path=path))
        issues.extend(self._validate_module_tuple(node.recommended_modules, field_name="recommended_modules", path=path))

        return issues

    def _validate_object_kind_tuple(
        self,
        values: Sequence[str],
        *,
        field_name: str,
        path: Tuple[str, ...],
    ) -> List[TaxonomyIssue]:
        issues: List[TaxonomyIssue] = []
        seen: Set[str] = set()

        for value in values:
            normalized = normalize_slug(value, default="")
            if not normalized:
                issues.append(
                    TaxonomyIssue.error(
                        "taxonomy_object_kind_empty",
                        f"Empty object kind in '{field_name}'.",
                        field=field_name,
                        path=path,
                    )
                )
                continue

            if normalized in seen:
                issues.append(
                    TaxonomyIssue.warning(
                        "taxonomy_object_kind_duplicate",
                        f"Duplicate object kind '{normalized}' in '{field_name}'.",
                        field=field_name,
                        path=path,
                    )
                )
            seen.add(normalized)

            if normalized not in self.known_object_kinds:
                issues.append(
                    TaxonomyIssue.error(
                        "taxonomy_object_kind_unknown",
                        f"Unknown object kind '{normalized}' in '{field_name}'.",
                        field=field_name,
                        path=path,
                        details={
                            "object_kind": normalized,
                            "known_object_kinds": sorted(self.known_object_kinds),
                        },
                    )
                )

        return issues

    def _validate_module_tuple(
        self,
        values: Sequence[str],
        *,
        field_name: str,
        path: Tuple[str, ...],
    ) -> List[TaxonomyIssue]:
        issues: List[TaxonomyIssue] = []
        seen: Set[str] = set()

        for value in values:
            normalized = normalize_slug(value, default="")
            if not normalized:
                issues.append(
                    TaxonomyIssue.error(
                        "taxonomy_module_empty",
                        f"Empty module in '{field_name}'.",
                        field=field_name,
                        path=path,
                    )
                )
                continue

            if normalized in seen:
                issues.append(
                    TaxonomyIssue.warning(
                        "taxonomy_module_duplicate",
                        f"Duplicate module '{normalized}' in '{field_name}'.",
                        field=field_name,
                        path=path,
                    )
                )
            seen.add(normalized)

            if self.config.warn_on_unknown_modules and normalized not in self.known_modules:
                issues.append(
                    TaxonomyIssue.warning(
                        "taxonomy_module_unknown",
                        f"Unknown module '{normalized}' in '{field_name}'.",
                        field=field_name,
                        path=path,
                        details={
                            "module": normalized,
                            "known_modules": sorted(self.known_modules),
                        },
                    )
                )

        return issues

    def _validate_child_uniqueness(
        self,
        *,
        children: Sequence[TaxonomyNode],
        parent_path: Tuple[str, ...],
        child_level: TaxonomyLevel,
    ) -> List[TaxonomyIssue]:
        issues: List[TaxonomyIssue] = []

        ids: Set[str] = set()
        aliases: Set[str] = set()
        source_segments: Set[str] = set()
        sort_orders: Dict[int, str] = {}

        for child in children:
            child_path = (*parent_path, child.id)

            if child.id in ids:
                issues.append(
                    TaxonomyIssue.error(
                        "taxonomy_child_id_duplicate",
                        f"Duplicate {child_level.value} id '{child.id}'.",
                        field="id",
                        path=child_path,
                    )
                )
            ids.add(child.id)

            if self.config.enforce_unique_source_segments_per_parent:
                if child.source_path_segment in source_segments:
                    issues.append(
                        TaxonomyIssue.error(
                            "taxonomy_child_source_segment_duplicate",
                            (
                                f"Duplicate source_path_segment '{child.source_path_segment}' "
                                f"in {child_level.value} list."
                            ),
                            field="source_path_segment",
                            path=child_path,
                        )
                    )
                source_segments.add(child.source_path_segment)

            for alias in child.aliases:
                if alias in ids:
                    issues.append(
                        TaxonomyIssue.error(
                            "taxonomy_child_alias_conflicts_with_id",
                            f"Alias '{alias}' conflicts with an existing {child_level.value} id.",
                            field="aliases",
                            path=child_path,
                        )
                    )

                if self.config.enforce_unique_aliases_per_level and alias in aliases:
                    issues.append(
                        TaxonomyIssue.error(
                            "taxonomy_child_alias_duplicate",
                            f"Duplicate alias '{alias}' in {child_level.value} list.",
                            field="aliases",
                            path=child_path,
                        )
                    )
                aliases.add(alias)

            if self.config.warn_on_duplicate_sort_order:
                if child.sort_order in sort_orders:
                    issues.append(
                        TaxonomyIssue.warning(
                            "taxonomy_child_sort_order_duplicate",
                            f"Duplicate sort_order {child.sort_order} in {child_level.value} list.",
                            field="sort_order",
                            path=child_path,
                            details={
                                "sort_order": child.sort_order,
                                "first_id": sort_orders[child.sort_order],
                                "current_id": child.id,
                            },
                        )
                    )
                else:
                    sort_orders[child.sort_order] = child.id

        return issues

    def _validate_registry_uniqueness(self, registry: TaxonomyRegistryModel) -> List[TaxonomyIssue]:
        issues: List[TaxonomyIssue] = []

        full_paths: Set[Tuple[str, str, str]] = set()
        classification_paths: Set[str] = set()

        for domain in registry.domains:
            for category in domain.categories:
                for subcategory in category.subcategories:
                    path_tuple = (domain.id, category.id, subcategory.id)
                    classification_path = "/".join(path_tuple)

                    if path_tuple in full_paths:
                        issues.append(
                            TaxonomyIssue.error(
                                "taxonomy_classification_path_duplicate",
                                f"Duplicate classification path '{classification_path}'.",
                                field="classification_path",
                                path=path_tuple,
                            )
                        )
                    full_paths.add(path_tuple)

                    if classification_path in classification_paths:
                        issues.append(
                            TaxonomyIssue.error(
                                "taxonomy_classification_path_string_duplicate",
                                f"Duplicate classification path string '{classification_path}'.",
                                field="classification_path",
                                path=path_tuple,
                            )
                        )
                    classification_paths.add(classification_path)

        return issues

    def _validate_registry_defaults(self, registry: TaxonomyRegistryModel) -> List[TaxonomyIssue]:
        issues: List[TaxonomyIssue] = []

        defaults = registry.defaults
        if not defaults.domain and not defaults.category and not defaults.subcategory:
            return issues

        result = registry.validate_selection(
            defaults.domain,
            defaults.category,
            defaults.subcategory,
            object_kind=defaults.object_kind,
        )

        for issue in result.issues:
            issues.append(
                TaxonomyIssue.warning(
                    "taxonomy_defaults_invalid",
                    f"Taxonomy defaults are invalid: {issue.message}",
                    field=issue.field or "defaults",
                    path=issue.path,
                    details=issue.to_dict(),
                )
            )

        return issues

    def _source_path_result(
        self,
        parts: Tuple[str, ...],
        *,
        issues: Iterable[TaxonomyIssue],
    ) -> TaxonomySourcePathValidation:
        result = TaxonomyValidationResult.from_issues(issues)

        domain = parts[0] if len(parts) > 0 else ""
        category = parts[1] if len(parts) > 1 else ""
        subcategory = parts[2] if len(parts) > 2 else ""
        family_slug = parts[3] if len(parts) > 3 else ""

        legacy = len(parts) == LEGACY_SOURCE_DEPTH

        return TaxonomySourcePathValidation(
            valid=result.valid,
            legacy=legacy,
            parts=parts,
            domain=domain,
            category=category,
            subcategory="" if legacy else subcategory,
            family_slug=family_slug if not legacy else subcategory,
            selection=TaxonomySelection.from_values(domain, category, "" if legacy else subcategory),
            resolved=None,
            issues=result,
        )


def validate_taxonomy_registry_data(data: Any) -> TaxonomyValidationResult:
    """Validate raw taxonomy JSON-like data."""

    return TaxonomyValidator().validate_raw_registry_data(data)


def validate_taxonomy_registry_model(registry: TaxonomyRegistryModel) -> TaxonomyValidationResult:
    """Validate a parsed taxonomy registry model."""

    return TaxonomyValidator(registry).validate_registry_model(registry)


def assert_valid_taxonomy_registry(registry: TaxonomyRegistryModel) -> TaxonomyRegistryModel:
    """Raise TaxonomyValidatorError if the parsed taxonomy registry is invalid."""

    result = validate_taxonomy_registry_model(registry)
    if not result.valid:
        error_messages = "; ".join(issue.message for issue in result.errors)
        raise TaxonomyValidatorError(error_messages or "Taxonomy registry is invalid.")
    return registry


def validate_taxonomy_selection(
    registry: TaxonomyRegistryModel,
    domain: Any,
    category: Any,
    subcategory: Any,
    *,
    object_kind: Any = "",
) -> TaxonomyValidationResult:
    """Validate a domain/category/subcategory selection."""

    return TaxonomyValidator(registry).validate_selection(
        domain,
        category,
        subcategory,
        object_kind=object_kind,
    )


def validate_taxonomy_source_path(
    registry: TaxonomyRegistryModel,
    source_path: Union[str, Sequence[str]],
    *,
    object_kind: Any = "",
    expect_family_slug: bool = True,
) -> TaxonomySourcePathValidation:
    """Validate a source path below src/library/source."""

    return TaxonomyValidator(registry).validate_source_path(
        source_path,
        object_kind=object_kind,
        expect_family_slug=expect_family_slug,
    )


def validate_taxonomy_family_identifiers(
    registry: TaxonomyRegistryModel,
    *,
    domain: Any,
    category: Any,
    subcategory: Any,
    family_slug: Any,
    family_id: Any = "",
    package_id: Any = "",
) -> TaxonomyValidationResult:
    """Validate family_id and package_id against taxonomy selection."""

    return TaxonomyValidator(registry).validate_family_identifiers(
        domain=domain,
        category=category,
        subcategory=subcategory,
        family_slug=family_slug,
        family_id=family_id,
        package_id=package_id,
    )


def normalize_source_path_parts(source_path: Union[str, Sequence[str]]) -> Tuple[str, ...]:
    """
    Normalize source path input into slug parts.

    Accepts:
    - "hochbau/waende/aussenwaende/ziegelwand"
    - "hochbau\\waende\\aussenwaende\\ziegelwand"
    - ["hochbau", "waende", "aussenwaende", "ziegelwand"]
    """

    if isinstance(source_path, str):
        raw_parts = source_path.replace("\\", "/").split("/")
    else:
        raw_parts = list(as_sequence(source_path))

    normalized: List[str] = []
    for part in raw_parts:
        text = safe_str(part, "")
        if not text or text in {".", ".."}:
            continue

        slug = normalize_slug(text, default="")
        if slug:
            normalized.append(slug)

    return tuple(normalized)


def is_reasonable_version_string(value: Any) -> bool:
    raw = safe_str(value, "")
    if not raw:
        return False
    if raw.startswith("v") and raw[1:].replace(".", "").isdigit():
        return True
    if raw.replace(".", "").isdigit():
        return True
    return False


__all__ = [
    "CANONICAL_SOURCE_DEPTH",
    "KNOWN_OBJECT_KINDS",
    "KNOWN_VPLIB_MODULES",
    "LEGACY_SOURCE_DEPTH",
    "REQUIRED_NODE_FIELDS",
    "RESERVED_TOP_LEVEL_KEYS",
    "TaxonomySourcePathValidation",
    "TaxonomyValidator",
    "TaxonomyValidatorConfig",
    "TaxonomyValidatorError",
    "assert_valid_taxonomy_registry",
    "is_reasonable_version_string",
    "normalize_source_path_parts",
    "validate_taxonomy_family_identifiers",
    "validate_taxonomy_registry_data",
    "validate_taxonomy_registry_model",
    "validate_taxonomy_selection",
    "validate_taxonomy_source_path",
]