# services/vectoplan-library/src/library/definitions/definition_registry.py
"""
Registry for VECTOPLAN Library Definitions.

The registry is responsible for loading, normalizing, validating and exposing
backend-owned definition datasets:

- object_kinds.v1.json
- family_profiles.v1.json
- variant_profiles.v1.json
- variables.v1.json
- units.v1.json
- materials.v1.json
- document_types.v1.json
- profile_bindings.v1.json

Design goals:
- safe imports
- no Flask dependency
- no scan execution during import
- robust path discovery
- lru-cache backed singleton access
- defensive JSON loading
- explicit health payloads
- forward-compatible dataset shapes
- cross-reference validation after parsing
- enough lookup helpers for create-flow, scanner, validators and read-models

Important cache rule:
- lru_cache must receive only hashable arguments.
- DefinitionRegistryOptions contains mutable metadata, so cached functions must
  use only options.cache_key(), never the options object itself.

Important profile resolution rule:
- A binding may define family_profile_id and variant_profile_id.
- During first family-profile resolution, no family_profile_id is known yet.
  Therefore a binding must not be rejected only because its family_profile_id is
  set while the request family_profile_id is empty.
- If family_profile_id is explicitly provided by the caller, it must match.
- Bindings with match.use_only_if_family_profile_selected=true only match when
  a family_profile_id was explicitly provided.

This file is intentionally usable before the config layer has been extended.
It tries config-backed paths first and falls back to ./data next to this file.
"""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass, field
from datetime import datetime, timezone
from functools import lru_cache
from pathlib import Path
from typing import Any, Dict, Iterable, List, Mapping, Optional, Sequence, Tuple

from .definition_models import (
    DEFINITION_DEFAULT_VERSION,
    DEFINITION_SCHEMA_VERSION,
    DefinitionDatasetError,
    DefinitionsRegistrySnapshot,
    DocumentTypeDefinition,
    FamilyProfileDefinition,
    MaterialDefinition,
    ObjectKindDefinition,
    ProfileBindingDefinition,
    UnitDefinition,
    VariableDefinition,
    VariantProfileDefinition,
    build_registry_snapshot,
    parse_dataset_items,
)


DEFINITION_REGISTRY_VERSION = "0.1.2"

DEFINITIONS_DATASETS: Tuple[str, ...] = (
    "object_kinds",
    "family_profiles",
    "variant_profiles",
    "variables",
    "units",
    "materials",
    "document_types",
    "profile_bindings",
)

DATASET_FILENAMES: Mapping[str, str] = {
    "object_kinds": "object_kinds.{version}.json",
    "family_profiles": "family_profiles.{version}.json",
    "variant_profiles": "variant_profiles.{version}.json",
    "variables": "variables.{version}.json",
    "units": "units.{version}.json",
    "materials": "materials.{version}.json",
    "document_types": "document_types.{version}.json",
    "profile_bindings": "profile_bindings.{version}.json",
}

COMBINED_DATASET_FILENAMES: Tuple[str, ...] = (
    "definitions.{version}.json",
    "library_definitions.{version}.json",
    "definitions.json",
)

STRICT_REFERENCE_VALIDATION_DEFAULT = True

_CACHE_KEY_LENGTH = 9

_LOGGER = logging.getLogger(__name__)


@dataclass(frozen=True)
class DefinitionRegistryOptions:
    """
    Runtime options for the definitions registry.

    `definitions_root` can point either to:
    - src/library/definitions
    - src/library/definitions/data
    - any directory containing the JSON dataset files
    """

    definitions_root: Optional[Path] = None
    definitions_version: str = DEFINITION_DEFAULT_VERSION
    schema_version: str = DEFINITION_SCHEMA_VERSION
    include_inactive: bool = False
    strict_references: bool = STRICT_REFERENCE_VALIDATION_DEFAULT
    allow_missing_datasets: bool = True
    allow_empty_datasets: bool = True
    use_config_fallback: bool = True
    source_label: str = "definitions"
    metadata: Dict[str, Any] = field(default_factory=dict)

    @classmethod
    def from_mapping(cls, data: Optional[Mapping[str, Any]]) -> "DefinitionRegistryOptions":
        if not data:
            return cls()

        root = data.get("definitions_root") or data.get("root") or data.get("data_root")
        return cls(
            definitions_root=_normalize_optional_path(root),
            definitions_version=_clean_string(
                data.get("definitions_version") or data.get("version"),
                default=DEFINITION_DEFAULT_VERSION,
            ),
            schema_version=_clean_string(
                data.get("schema_version"),
                default=DEFINITION_SCHEMA_VERSION,
            ),
            include_inactive=_as_bool(data.get("include_inactive"), default=False),
            strict_references=_as_bool(
                data.get("strict_references"),
                default=STRICT_REFERENCE_VALIDATION_DEFAULT,
            ),
            allow_missing_datasets=_as_bool(data.get("allow_missing_datasets"), default=True),
            allow_empty_datasets=_as_bool(data.get("allow_empty_datasets"), default=True),
            use_config_fallback=_as_bool(data.get("use_config_fallback"), default=True),
            source_label=_clean_string(data.get("source_label"), default="definitions"),
            metadata=_copy_mapping(data.get("metadata")),
        )

    def cache_key(self) -> Tuple[Any, ...]:
        """
        Return a stable, hashable cache key.

        Do not pass DefinitionRegistryOptions itself into lru_cache. The
        metadata dict is intentionally excluded from the cache key because it
        is diagnostic-only and does not affect loaded registry content.
        """
        return (
            _path_cache_value(self.definitions_root),
            self.definitions_version,
            self.schema_version,
            bool(self.include_inactive),
            bool(self.strict_references),
            bool(self.allow_missing_datasets),
            bool(self.allow_empty_datasets),
            bool(self.use_config_fallback),
            self.source_label,
        )

    def to_dict(self) -> Dict[str, Any]:
        return {
            "definitions_root": str(self.definitions_root) if self.definitions_root else None,
            "definitions_version": self.definitions_version,
            "schema_version": self.schema_version,
            "include_inactive": self.include_inactive,
            "strict_references": self.strict_references,
            "allow_missing_datasets": self.allow_missing_datasets,
            "allow_empty_datasets": self.allow_empty_datasets,
            "use_config_fallback": self.use_config_fallback,
            "source_label": self.source_label,
            "metadata": dict(self.metadata),
        }


@dataclass
class DatasetLoadResult:
    dataset_name: str
    path: Optional[Path] = None
    found: bool = False
    ok: bool = False
    item_count: int = 0
    error: Optional[str] = None
    warning: Optional[str] = None

    def to_dict(self) -> Dict[str, Any]:
        return _drop_empty(
            {
                "dataset_name": self.dataset_name,
                "path": str(self.path) if self.path else None,
                "found": self.found,
                "ok": self.ok,
                "item_count": self.item_count,
                "error": self.error,
                "warning": self.warning,
            }
        )


@dataclass
class RegistryLoadResult:
    snapshot: DefinitionsRegistrySnapshot
    options: DefinitionRegistryOptions
    data_root: Path
    dataset_results: Dict[str, DatasetLoadResult] = field(default_factory=dict)
    combined_file: Optional[Path] = None
    warnings: List[str] = field(default_factory=list)
    errors: List[str] = field(default_factory=list)

    @property
    def ok(self) -> bool:
        return not self.errors and self.snapshot.ok

    @property
    def healthy(self) -> bool:
        return self.ok

    def to_dict(self) -> Dict[str, Any]:
        return {
            "ok": self.ok,
            "healthy": self.healthy,
            "status": "healthy" if self.healthy else "degraded",
            "data_root": str(self.data_root),
            "combined_file": str(self.combined_file) if self.combined_file else None,
            "options": self.options.to_dict(),
            "datasets": {
                key: value.to_dict()
                for key, value in self.dataset_results.items()
            },
            "warnings": list(self.warnings),
            "errors": list(self.errors),
            "snapshot": self.snapshot.summary(),
        }


class DefinitionRegistry:
    """
    Loaded and indexed view of the definitions datasets.

    This class is immutable from the outside. It exposes lookup helpers and
    profile-resolution helpers but does not mutate loaded definitions.
    """

    def __init__(
        self,
        snapshot: DefinitionsRegistrySnapshot,
        *,
        options: Optional[DefinitionRegistryOptions] = None,
        data_root: Optional[Path] = None,
        load_result: Optional[RegistryLoadResult] = None,
    ) -> None:
        self._snapshot = snapshot
        self._options = options or DefinitionRegistryOptions()
        self._data_root = data_root
        self._load_result = load_result

        self._object_kinds_by_id = _index_by_id(snapshot.object_kinds)
        self._family_profiles_by_id = _index_by_id(snapshot.family_profiles)
        self._variant_profiles_by_id = _index_by_id(snapshot.variant_profiles)
        self._variables_by_key = _index_by_id(snapshot.variables)
        self._units_by_id = _index_by_id(snapshot.units)
        self._materials_by_id = _index_by_id(snapshot.materials)
        self._document_types_by_id = _index_by_id(snapshot.document_types)
        self._profile_bindings_by_id = _index_by_id(snapshot.profile_bindings)

    @property
    def snapshot(self) -> DefinitionsRegistrySnapshot:
        return self._snapshot

    @property
    def options(self) -> DefinitionRegistryOptions:
        return self._options

    @property
    def data_root(self) -> Optional[Path]:
        return self._data_root

    @property
    def load_result(self) -> Optional[RegistryLoadResult]:
        return self._load_result

    @property
    def ok(self) -> bool:
        return self._snapshot.ok

    @property
    def healthy(self) -> bool:
        return self._snapshot.healthy

    def counts(self, *, include_inactive: bool = True) -> Dict[str, int]:
        return self._snapshot.counts(include_inactive=include_inactive)

    def to_dict(
        self,
        *,
        include_inactive: bool = False,
        include_internal: bool = False,
        include_extra: bool = True,
        language: str = "de",
    ) -> Dict[str, Any]:
        payload = self._snapshot.to_dict(
            include_inactive=include_inactive,
            include_internal=include_internal,
            include_extra=include_extra,
            language=language,
        )

        if include_internal:
            payload["registry"] = {
                "version": DEFINITION_REGISTRY_VERSION,
                "data_root": str(self._data_root) if self._data_root else None,
                "options": self._options.to_dict(),
                "load_result": self._load_result.to_dict() if self._load_result else None,
            }

        return payload

    def summary(self) -> Dict[str, Any]:
        payload = self._snapshot.summary()
        payload.update(
            {
                "registry_version": DEFINITION_REGISTRY_VERSION,
                "data_root": str(self._data_root) if self._data_root else None,
            }
        )
        return payload

    def health(self) -> Dict[str, Any]:
        load_result_payload = self._load_result.to_dict() if self._load_result else None
        return {
            "ok": self.ok,
            "healthy": self.healthy,
            "status": "healthy" if self.healthy else "degraded",
            "component": "library.definitions.registry",
            "version": DEFINITION_REGISTRY_VERSION,
            "definitions_version": self._snapshot.definitions_version,
            "schema_version": self._snapshot.schema_version,
            "data_root": str(self._data_root) if self._data_root else None,
            "counts": self.counts(include_inactive=True),
            "warnings": list(self._snapshot.warnings),
            "errors": list(self._snapshot.errors),
            "load_result": load_result_payload,
        }

    def get_object_kind(self, object_kind: str) -> Optional[ObjectKindDefinition]:
        return self._object_kinds_by_id.get(_clean_string(object_kind))

    def get_family_profile(self, profile_id: str) -> Optional[FamilyProfileDefinition]:
        return self._family_profiles_by_id.get(_clean_string(profile_id))

    def get_variant_profile(self, profile_id: str) -> Optional[VariantProfileDefinition]:
        return self._variant_profiles_by_id.get(_clean_string(profile_id))

    def get_variable(self, variable_key: str) -> Optional[VariableDefinition]:
        return self._variables_by_key.get(_clean_string(variable_key))

    def get_unit(self, unit_id: str) -> Optional[UnitDefinition]:
        return self._units_by_id.get(_clean_string(unit_id))

    def get_material(self, material_id: str) -> Optional[MaterialDefinition]:
        return self._materials_by_id.get(_clean_string(material_id))

    def get_document_type(self, document_type_id: str) -> Optional[DocumentTypeDefinition]:
        return self._document_types_by_id.get(_clean_string(document_type_id))

    def get_profile_binding(self, binding_id: str) -> Optional[ProfileBindingDefinition]:
        return self._profile_bindings_by_id.get(_clean_string(binding_id))

    def list_object_kinds(self, *, include_inactive: bool = False) -> Tuple[ObjectKindDefinition, ...]:
        return _filter_active(self._snapshot.object_kinds, include_inactive=include_inactive)

    def list_family_profiles(self, *, include_inactive: bool = False) -> Tuple[FamilyProfileDefinition, ...]:
        return _filter_active(self._snapshot.family_profiles, include_inactive=include_inactive)

    def list_variant_profiles(self, *, include_inactive: bool = False) -> Tuple[VariantProfileDefinition, ...]:
        return _filter_active(self._snapshot.variant_profiles, include_inactive=include_inactive)

    def list_variables(self, *, include_inactive: bool = False) -> Tuple[VariableDefinition, ...]:
        return _filter_active(self._snapshot.variables, include_inactive=include_inactive)

    def list_units(self, *, include_inactive: bool = False) -> Tuple[UnitDefinition, ...]:
        return _filter_active(self._snapshot.units, include_inactive=include_inactive)

    def list_materials(self, *, include_inactive: bool = False) -> Tuple[MaterialDefinition, ...]:
        return _filter_active(self._snapshot.materials, include_inactive=include_inactive)

    def list_document_types(self, *, include_inactive: bool = False) -> Tuple[DocumentTypeDefinition, ...]:
        return _filter_active(self._snapshot.document_types, include_inactive=include_inactive)

    def list_profile_bindings(self, *, include_inactive: bool = False) -> Tuple[ProfileBindingDefinition, ...]:
        return _filter_active(self._snapshot.profile_bindings, include_inactive=include_inactive)

    def resolve_family_profile_for_context(
        self,
        *,
        domain: Optional[str] = None,
        category: Optional[str] = None,
        subcategory: Optional[str] = None,
        object_kind: Optional[str] = None,
        family_profile_id: Optional[str] = None,
    ) -> Dict[str, Any]:
        explicit_family_profile_id = _clean_string(family_profile_id)
        if explicit_family_profile_id:
            family_profile = self.get_family_profile(explicit_family_profile_id)
            if family_profile:
                return {
                    "ok": True,
                    "status": "resolved",
                    "strategy": "explicit",
                    "family_profile_id": family_profile.id,
                    "family_profile": family_profile.to_dict(),
                }

            return {
                "ok": False,
                "status": "not_found",
                "strategy": "explicit",
                "family_profile_id": explicit_family_profile_id,
                "error": f"Unknown family_profile_id: {explicit_family_profile_id}",
            }

        binding = self.find_best_profile_binding(
            domain=domain,
            category=category,
            subcategory=subcategory,
            object_kind=object_kind,
            family_profile_id=None,
        )

        if binding and binding.family_profile_id:
            family_profile = self.get_family_profile(binding.family_profile_id)
            if family_profile:
                return {
                    "ok": True,
                    "status": "resolved",
                    "strategy": "profile_binding",
                    "binding_id": binding.id,
                    "family_profile_id": family_profile.id,
                    "family_profile": family_profile.to_dict(),
                }

        object_kind_definition = self.get_object_kind(object_kind or "")
        if object_kind_definition and object_kind_definition.default_family_profile_id:
            family_profile = self.get_family_profile(object_kind_definition.default_family_profile_id)
            if family_profile:
                return {
                    "ok": True,
                    "status": "resolved",
                    "strategy": "object_kind_default",
                    "object_kind": object_kind_definition.id,
                    "family_profile_id": family_profile.id,
                    "family_profile": family_profile.to_dict(),
                }

        return {
            "ok": False,
            "status": "not_found",
            "strategy": "none",
            "context": {
                "domain": domain,
                "category": category,
                "subcategory": subcategory,
                "object_kind": object_kind,
                "family_profile_id": family_profile_id,
            },
            "error": "No matching family profile found",
        }

    def resolve_variant_profile_for_context(
        self,
        *,
        domain: Optional[str] = None,
        category: Optional[str] = None,
        subcategory: Optional[str] = None,
        object_kind: Optional[str] = None,
        family_profile_id: Optional[str] = None,
        variant_profile_id: Optional[str] = None,
    ) -> Dict[str, Any]:
        explicit_variant_profile_id = _clean_string(variant_profile_id)
        clean_family_profile_id = _clean_string(family_profile_id)

        if explicit_variant_profile_id:
            variant_profile = self.get_variant_profile(explicit_variant_profile_id)
            if variant_profile:
                return {
                    "ok": True,
                    "status": "resolved",
                    "strategy": "explicit",
                    "variant_profile_id": variant_profile.id,
                    "variant_profile": variant_profile.to_dict(),
                }

            return {
                "ok": False,
                "status": "not_found",
                "strategy": "explicit",
                "variant_profile_id": explicit_variant_profile_id,
                "error": f"Unknown variant_profile_id: {explicit_variant_profile_id}",
            }

        family_result = self.resolve_family_profile_for_context(
            domain=domain,
            category=category,
            subcategory=subcategory,
            object_kind=object_kind,
            family_profile_id=clean_family_profile_id,
        )

        resolved_family_profile_id = clean_family_profile_id
        if family_result.get("ok"):
            resolved_family_profile_id = _clean_string(family_result.get("family_profile_id"))

        binding = self.find_best_profile_binding(
            domain=domain,
            category=category,
            subcategory=subcategory,
            object_kind=object_kind,
            family_profile_id=resolved_family_profile_id or None,
        )

        if binding and binding.variant_profile_id:
            variant_profile = self.get_variant_profile(binding.variant_profile_id)
            if variant_profile:
                return {
                    "ok": True,
                    "status": "resolved",
                    "strategy": "profile_binding",
                    "binding_id": binding.id,
                    "family_profile_id": resolved_family_profile_id or binding.family_profile_id,
                    "variant_profile_id": variant_profile.id,
                    "variant_profile": variant_profile.to_dict(),
                }

        if resolved_family_profile_id:
            family_profile = self.get_family_profile(resolved_family_profile_id)
            if family_profile and family_profile.default_variant_profile_id:
                variant_profile = self.get_variant_profile(family_profile.default_variant_profile_id)
                if variant_profile:
                    return {
                        "ok": True,
                        "status": "resolved",
                        "strategy": "family_profile_default",
                        "family_profile_id": family_profile.id,
                        "variant_profile_id": variant_profile.id,
                        "variant_profile": variant_profile.to_dict(),
                    }

        object_kind_definition = self.get_object_kind(object_kind or "")
        if object_kind_definition and object_kind_definition.default_variant_profile_id:
            variant_profile = self.get_variant_profile(object_kind_definition.default_variant_profile_id)
            if variant_profile:
                return {
                    "ok": True,
                    "status": "resolved",
                    "strategy": "object_kind_default",
                    "object_kind": object_kind_definition.id,
                    "variant_profile_id": variant_profile.id,
                    "variant_profile": variant_profile.to_dict(),
                }

        return {
            "ok": False,
            "status": "not_found",
            "strategy": "none",
            "context": {
                "domain": domain,
                "category": category,
                "subcategory": subcategory,
                "object_kind": object_kind,
                "family_profile_id": family_profile_id,
                "variant_profile_id": variant_profile_id,
            },
            "family_resolution": family_result,
            "error": "No matching variant profile found",
        }

    def find_best_profile_binding(
        self,
        *,
        domain: Optional[str] = None,
        category: Optional[str] = None,
        subcategory: Optional[str] = None,
        object_kind: Optional[str] = None,
        family_profile_id: Optional[str] = None,
    ) -> Optional[ProfileBindingDefinition]:
        """
        Find the best profile binding for the given context.

        This deliberately does not call ProfileBindingDefinition.matches_context()
        directly because that model method treats a binding's family_profile_id
        as a required input match. That behavior is too strict when the registry
        is trying to resolve the family_profile_id for the first time.

        Matching rules:
        - domain/category/subcategory/object_kind are normal exact-or-wildcard
          fields.
        - If caller provides family_profile_id, binding.family_profile_id must
          either match or be empty.
        - If caller does not provide family_profile_id, bindings with a
          family_profile_id may still match because they are the source of the
          family profile.
        - match.use_only_if_family_profile_selected=true requires caller to
          explicitly provide family_profile_id.
        - More specific taxonomy/object matches outrank generic fallbacks.
        - Lower priority wins after specificity.
        """
        clean_domain = _clean_string(domain)
        clean_category = _clean_string(category)
        clean_subcategory = _clean_string(subcategory)
        clean_object_kind = _clean_string(object_kind)
        clean_family_profile_id = _clean_string(family_profile_id)

        scored_candidates: List[Tuple[Tuple[int, int, int, str], ProfileBindingDefinition]] = []

        for binding in self._snapshot.profile_bindings:
            match = _profile_binding_match_score(
                binding,
                domain=clean_domain,
                category=clean_category,
                subcategory=clean_subcategory,
                object_kind=clean_object_kind,
                family_profile_id=clean_family_profile_id,
            )

            if match is None:
                continue

            scored_candidates.append((match, binding))

        if not scored_candidates:
            return None

        scored_candidates.sort(key=lambda item: item[0])
        return scored_candidates[0][1]

    def get_variables_for_variant_profile(
        self,
        variant_profile_id: str,
        *,
        include_inactive: bool = False,
    ) -> Tuple[VariableDefinition, ...]:
        variant_profile = self.get_variant_profile(variant_profile_id)
        if not variant_profile:
            return tuple()

        variables: List[VariableDefinition] = []
        seen = set()

        for field_key in variant_profile.all_field_keys:
            variable = self.get_variable(field_key)
            if not variable:
                continue
            if not include_inactive and not variable.active:
                continue
            if variable.key in seen:
                continue
            variables.append(variable)
            seen.add(variable.key)

        return tuple(variables)

    def build_variant_profile_payload(
        self,
        variant_profile_id: str,
        *,
        include_inactive: bool = False,
        include_extra: bool = True,
        language: str = "de",
    ) -> Dict[str, Any]:
        variant_profile = self.get_variant_profile(variant_profile_id)
        if not variant_profile:
            return {
                "ok": False,
                "status": "not_found",
                "variant_profile_id": variant_profile_id,
                "error": f"Unknown variant_profile_id: {variant_profile_id}",
            }

        variables = self.get_variables_for_variant_profile(
            variant_profile_id,
            include_inactive=include_inactive,
        )

        return {
            "ok": True,
            "status": "ok",
            "variant_profile_id": variant_profile.id,
            "variant_profile": variant_profile.to_dict(
                include_extra=include_extra,
                include_inactive=include_inactive,
                language=language,
            ),
            "variables": {
                variable.key: variable.to_dict(
                    include_extra=include_extra,
                    include_inactive=include_inactive,
                    language=language,
                )
                for variable in variables
            },
        }


def get_definition_registry(
    *,
    definitions_root: Optional[Any] = None,
    definitions_version: str = DEFINITION_DEFAULT_VERSION,
    force_reload: bool = False,
    strict_references: bool = STRICT_REFERENCE_VALIDATION_DEFAULT,
    allow_missing_datasets: bool = True,
    allow_empty_datasets: bool = True,
    use_config_fallback: bool = True,
) -> DefinitionRegistry:
    """
    Public cached registry accessor.

    `force_reload=True` clears the cache before loading.
    """
    if force_reload:
        clear_definition_registry_cache()

    options = DefinitionRegistryOptions(
        definitions_root=_normalize_optional_path(definitions_root),
        definitions_version=_clean_string(definitions_version, default=DEFINITION_DEFAULT_VERSION),
        schema_version=DEFINITION_SCHEMA_VERSION,
        strict_references=bool(strict_references),
        allow_missing_datasets=bool(allow_missing_datasets),
        allow_empty_datasets=bool(allow_empty_datasets),
        use_config_fallback=bool(use_config_fallback),
    )

    return _get_definition_registry_cached(options.cache_key())


def get_definitions_registry(**kwargs: Any) -> DefinitionRegistry:
    return get_definition_registry(**kwargs)


def create_definition_registry(**kwargs: Any) -> DefinitionRegistry:
    cleaned_kwargs = dict(kwargs)
    cleaned_kwargs["force_reload"] = True
    return get_definition_registry(**cleaned_kwargs)


def create_definitions_registry(**kwargs: Any) -> DefinitionRegistry:
    return create_definition_registry(**kwargs)


@lru_cache(maxsize=16)
def _get_definition_registry_cached(cache_key: Tuple[Any, ...]) -> DefinitionRegistry:
    """
    Cached registry builder.

    Only `cache_key` is accepted here. This avoids lru_cache receiving
    DefinitionRegistryOptions, which contains mutable metadata and is therefore
    unsafe as a cached argument.
    """
    options = _options_from_cache_key(cache_key)
    load_result = load_registry(options)
    return DefinitionRegistry(
        load_result.snapshot,
        options=options,
        data_root=load_result.data_root,
        load_result=load_result,
    )


def _options_from_cache_key(cache_key: Tuple[Any, ...]) -> DefinitionRegistryOptions:
    if not isinstance(cache_key, tuple) or len(cache_key) != _CACHE_KEY_LENGTH:
        raise ValueError(
            "Invalid definition registry cache key. "
            f"Expected tuple length {_CACHE_KEY_LENGTH}, got {cache_key!r}"
        )

    (
        definitions_root,
        definitions_version,
        schema_version,
        include_inactive,
        strict_references,
        allow_missing_datasets,
        allow_empty_datasets,
        use_config_fallback,
        source_label,
    ) = cache_key

    return DefinitionRegistryOptions(
        definitions_root=_normalize_optional_path(definitions_root),
        definitions_version=_clean_string(definitions_version, default=DEFINITION_DEFAULT_VERSION),
        schema_version=_clean_string(schema_version, default=DEFINITION_SCHEMA_VERSION),
        include_inactive=bool(include_inactive),
        strict_references=bool(strict_references),
        allow_missing_datasets=bool(allow_missing_datasets),
        allow_empty_datasets=bool(allow_empty_datasets),
        use_config_fallback=bool(use_config_fallback),
        source_label=_clean_string(source_label, default="definitions"),
        metadata={
            "from_cache_key": True,
        },
    )


def load_registry(options: Optional[DefinitionRegistryOptions] = None) -> RegistryLoadResult:
    options = options or DefinitionRegistryOptions()
    warnings: List[str] = []
    errors: List[str] = []

    data_root = resolve_definitions_data_root(options)
    loaded_at = datetime.now(timezone.utc).isoformat()

    dataset_results: Dict[str, DatasetLoadResult] = {}
    parsed_datasets: Dict[str, Tuple[Any, ...]] = {
        dataset_name: tuple()
        for dataset_name in DEFINITIONS_DATASETS
    }

    combined_file = _find_combined_dataset_file(
        data_root,
        definitions_version=options.definitions_version,
    )

    if combined_file:
        try:
            combined_data = _load_json_file(combined_file)
            for dataset_name in DEFINITIONS_DATASETS:
                dataset_result, parsed_items = _parse_dataset_from_combined_file(
                    dataset_name,
                    combined_data,
                    combined_file,
                    options=options,
                )
                dataset_results[dataset_name] = dataset_result
                parsed_datasets[dataset_name] = parsed_items
                if dataset_result.warning:
                    warnings.append(dataset_result.warning)
                if dataset_result.error:
                    errors.append(dataset_result.error)
        except Exception as exc:
            error = f"Could not load combined definitions file {combined_file}: {_format_exception(exc)}"
            errors.append(error)
            _LOGGER.exception(error)
            for dataset_name in DEFINITIONS_DATASETS:
                dataset_results[dataset_name] = DatasetLoadResult(
                    dataset_name=dataset_name,
                    path=combined_file,
                    found=True,
                    ok=False,
                    error=error,
                )
    else:
        for dataset_name in DEFINITIONS_DATASETS:
            dataset_result, parsed_items = _load_single_dataset(
                dataset_name,
                data_root,
                options=options,
            )
            dataset_results[dataset_name] = dataset_result
            parsed_datasets[dataset_name] = parsed_items

            if dataset_result.warning:
                warnings.append(dataset_result.warning)
            if dataset_result.error:
                errors.append(dataset_result.error)

    reference_warnings, reference_errors = validate_snapshot_references_from_items(
        object_kinds=parsed_datasets["object_kinds"],
        family_profiles=parsed_datasets["family_profiles"],
        variant_profiles=parsed_datasets["variant_profiles"],
        variables=parsed_datasets["variables"],
        units=parsed_datasets["units"],
        materials=parsed_datasets["materials"],
        document_types=parsed_datasets["document_types"],
        profile_bindings=parsed_datasets["profile_bindings"],
        strict=options.strict_references,
    )
    warnings.extend(reference_warnings)
    errors.extend(reference_errors)

    snapshot = build_registry_snapshot(
        definitions_version=options.definitions_version,
        schema_version=options.schema_version,
        source=str(data_root),
        loaded_at=loaded_at,
        object_kinds=parsed_datasets["object_kinds"],
        family_profiles=parsed_datasets["family_profiles"],
        variant_profiles=parsed_datasets["variant_profiles"],
        variables=parsed_datasets["variables"],
        units=parsed_datasets["units"],
        materials=parsed_datasets["materials"],
        document_types=parsed_datasets["document_types"],
        profile_bindings=parsed_datasets["profile_bindings"],
        warnings=warnings,
        errors=errors,
        metadata={
            **options.metadata,
            "registry_version": DEFINITION_REGISTRY_VERSION,
            "combined_file": str(combined_file) if combined_file else None,
        },
    )

    return RegistryLoadResult(
        snapshot=snapshot,
        options=options,
        data_root=data_root,
        dataset_results=dataset_results,
        combined_file=combined_file,
        warnings=warnings,
        errors=errors,
    )


def resolve_definitions_data_root(options: Optional[DefinitionRegistryOptions] = None) -> Path:
    options = options or DefinitionRegistryOptions()

    candidates: List[Path] = []

    if options.definitions_root:
        candidates.extend(_expand_root_candidates(options.definitions_root))

    if options.use_config_fallback:
        config_root = _try_get_config_definitions_root()
        if config_root:
            candidates.extend(_expand_root_candidates(config_root))

    module_root = Path(__file__).resolve().parent
    candidates.extend(
        [
            module_root / "data",
            module_root,
        ]
    )

    seen = set()
    normalized_candidates: List[Path] = []

    for candidate in candidates:
        try:
            normalized = candidate.resolve()
        except Exception:
            normalized = candidate

        key = str(normalized)
        if key in seen:
            continue

        seen.add(key)
        normalized_candidates.append(normalized)

    for candidate in normalized_candidates:
        if _looks_like_definitions_data_root(candidate, options.definitions_version):
            return candidate

    return normalized_candidates[0] if normalized_candidates else (module_root / "data")


def _expand_root_candidates(root: Path) -> List[Path]:
    return [
        root,
        root / "data",
        root / "definitions",
        root / "definitions" / "data",
    ]


def _looks_like_definitions_data_root(path: Path, definitions_version: str) -> bool:
    if not path.exists() or not path.is_dir():
        return False

    if _find_combined_dataset_file(path, definitions_version=definitions_version):
        return True

    for dataset_name in DEFINITIONS_DATASETS:
        if _dataset_file_path(path, dataset_name, definitions_version).exists():
            return True

    return False


def _try_get_config_definitions_root() -> Optional[Path]:
    """
    Best-effort config integration.

    This intentionally catches everything because the registry must work while
    config/library_settings.py has not yet been extended.
    """
    library_settings = None

    try:
        from src.config import library_settings as absolute_library_settings  # type: ignore

        library_settings = absolute_library_settings
    except Exception:
        try:
            from ...config import library_settings as relative_library_settings  # type: ignore

            library_settings = relative_library_settings
        except Exception:
            return None

    candidates = (
        "DEFINITIONS_ROOT",
        "LIBRARY_DEFINITIONS_ROOT",
        "definitions_root",
        "library_definitions_root",
    )

    for attr in candidates:
        value = getattr(library_settings, attr, None)
        if value:
            return _normalize_optional_path(value)

    getter_names = (
        "get_definitions_root",
        "get_library_definitions_root",
        "definitions_root",
    )

    for getter_name in getter_names:
        getter = getattr(library_settings, getter_name, None)
        if not callable(getter):
            continue

        try:
            value = getter()
        except Exception:
            continue

        if value:
            return _normalize_optional_path(value)

    summary_getter = getattr(library_settings, "get_library_settings_summary", None)
    if callable(summary_getter):
        try:
            summary = summary_getter()
        except Exception:
            summary = None

        if isinstance(summary, Mapping):
            direct_value = (
                summary.get("definitions_root")
                or summary.get("library_definitions_root")
            )
            if direct_value:
                return _normalize_optional_path(direct_value)

            paths = summary.get("paths")
            if isinstance(paths, Mapping):
                path_value = (
                    paths.get("definitions_root")
                    or paths.get("library_definitions_root")
                )
                if path_value:
                    return _normalize_optional_path(path_value)

    return None


def _load_single_dataset(
    dataset_name: str,
    data_root: Path,
    *,
    options: DefinitionRegistryOptions,
) -> Tuple[DatasetLoadResult, Tuple[Any, ...]]:
    path = _dataset_file_path(data_root, dataset_name, options.definitions_version)

    if not path.exists():
        message = f"Definitions dataset file missing: {path}"
        result = DatasetLoadResult(
            dataset_name=dataset_name,
            path=path,
            found=False,
            ok=bool(options.allow_missing_datasets),
            item_count=0,
            warning=message if options.allow_missing_datasets else None,
            error=None if options.allow_missing_datasets else message,
        )
        return result, tuple()

    try:
        raw_data = _load_json_file(path)
        parsed_items = parse_dataset_items(
            dataset_name,
            raw_data,
            allow_empty=options.allow_empty_datasets,
        )
        result = DatasetLoadResult(
            dataset_name=dataset_name,
            path=path,
            found=True,
            ok=True,
            item_count=len(parsed_items),
        )
        return result, parsed_items
    except Exception as exc:
        error = f"Could not load definitions dataset {dataset_name!r} from {path}: {_format_exception(exc)}"
        _LOGGER.exception(error)
        result = DatasetLoadResult(
            dataset_name=dataset_name,
            path=path,
            found=True,
            ok=False,
            item_count=0,
            error=error,
        )
        return result, tuple()


def _parse_dataset_from_combined_file(
    dataset_name: str,
    combined_data: Mapping[str, Any],
    path: Path,
    *,
    options: DefinitionRegistryOptions,
) -> Tuple[DatasetLoadResult, Tuple[Any, ...]]:
    if not isinstance(combined_data, Mapping):
        error = f"Combined definitions file must contain a JSON object: {path}"
        return (
            DatasetLoadResult(
                dataset_name=dataset_name,
                path=path,
                found=True,
                ok=False,
                error=error,
            ),
            tuple(),
        )

    if dataset_name not in combined_data:
        message = f"Definitions dataset {dataset_name!r} missing in combined file: {path}"
        return (
            DatasetLoadResult(
                dataset_name=dataset_name,
                path=path,
                found=False,
                ok=bool(options.allow_missing_datasets),
                warning=message if options.allow_missing_datasets else None,
                error=None if options.allow_missing_datasets else message,
            ),
            tuple(),
        )

    try:
        parsed_items = parse_dataset_items(
            dataset_name,
            combined_data.get(dataset_name),
            allow_empty=options.allow_empty_datasets,
        )
        return (
            DatasetLoadResult(
                dataset_name=dataset_name,
                path=path,
                found=True,
                ok=True,
                item_count=len(parsed_items),
            ),
            parsed_items,
        )
    except Exception as exc:
        error = f"Could not parse dataset {dataset_name!r} in combined file {path}: {_format_exception(exc)}"
        _LOGGER.exception(error)
        return (
            DatasetLoadResult(
                dataset_name=dataset_name,
                path=path,
                found=True,
                ok=False,
                error=error,
            ),
            tuple(),
        )


def _dataset_file_path(data_root: Path, dataset_name: str, definitions_version: str) -> Path:
    filename_pattern = DATASET_FILENAMES.get(dataset_name)
    if not filename_pattern:
        return data_root / f"{dataset_name}.{definitions_version}.json"
    return data_root / filename_pattern.format(version=definitions_version)


def _find_combined_dataset_file(data_root: Path, *, definitions_version: str) -> Optional[Path]:
    for filename_pattern in COMBINED_DATASET_FILENAMES:
        path = data_root / filename_pattern.format(version=definitions_version)
        if path.exists() and path.is_file():
            return path
    return None


def _load_json_file(path: Path) -> Any:
    try:
        with path.open("r", encoding="utf-8") as handle:
            return json.load(handle)
    except json.JSONDecodeError as exc:
        raise DefinitionDatasetError(
            f"Invalid JSON in {path}: line {exc.lineno}, column {exc.colno}: {exc.msg}"
        ) from exc


def validate_snapshot_references_from_items(
    *,
    object_kinds: Sequence[ObjectKindDefinition],
    family_profiles: Sequence[FamilyProfileDefinition],
    variant_profiles: Sequence[VariantProfileDefinition],
    variables: Sequence[VariableDefinition],
    units: Sequence[UnitDefinition],
    materials: Sequence[MaterialDefinition],
    document_types: Sequence[DocumentTypeDefinition],
    profile_bindings: Sequence[ProfileBindingDefinition],
    strict: bool = True,
) -> Tuple[List[str], List[str]]:
    warnings: List[str] = []
    errors: List[str] = []

    object_kind_ids = _id_set(object_kinds)
    family_profile_ids = _id_set(family_profiles)
    variant_profile_ids = _id_set(variant_profiles)
    variable_keys = _id_set(variables)
    unit_ids = _id_set(units)
    material_ids = _id_set(materials)
    document_type_ids = _id_set(document_types)

    def issue(message: str, *, fatal: bool = True) -> None:
        if fatal and strict:
            errors.append(message)
        else:
            warnings.append(message)

    for object_kind in object_kinds:
        _check_references(
            owner=f"object_kind:{object_kind.id}",
            field_name="allowed_family_profiles",
            values=object_kind.allowed_family_profiles,
            known_ids=family_profile_ids,
            issue=issue,
            fatal=True,
        )
        _check_reference(
            owner=f"object_kind:{object_kind.id}",
            field_name="default_family_profile_id",
            value=object_kind.default_family_profile_id,
            known_ids=family_profile_ids,
            issue=issue,
            fatal=True,
        )
        _check_reference(
            owner=f"object_kind:{object_kind.id}",
            field_name="default_variant_profile_id",
            value=object_kind.default_variant_profile_id,
            known_ids=variant_profile_ids,
            issue=issue,
            fatal=True,
        )

    for family_profile in family_profiles:
        _check_references(
            owner=f"family_profile:{family_profile.id}",
            field_name="object_kinds",
            values=family_profile.object_kinds,
            known_ids=object_kind_ids,
            issue=issue,
            fatal=True,
        )
        _check_references(
            owner=f"family_profile:{family_profile.id}",
            field_name="allowed_variant_profiles",
            values=family_profile.allowed_variant_profiles,
            known_ids=variant_profile_ids,
            issue=issue,
            fatal=True,
        )
        _check_reference(
            owner=f"family_profile:{family_profile.id}",
            field_name="default_variant_profile_id",
            value=family_profile.default_variant_profile_id,
            known_ids=variant_profile_ids,
            issue=issue,
            fatal=True,
        )

    for variant_profile in variant_profiles:
        _check_references(
            owner=f"variant_profile:{variant_profile.id}",
            field_name="family_profiles",
            values=variant_profile.family_profiles,
            known_ids=family_profile_ids,
            issue=issue,
            fatal=True,
        )
        _check_references(
            owner=f"variant_profile:{variant_profile.id}",
            field_name="object_kinds",
            values=variant_profile.object_kinds,
            known_ids=object_kind_ids,
            issue=issue,
            fatal=True,
        )
        _check_references(
            owner=f"variant_profile:{variant_profile.id}",
            field_name="all_fields",
            values=variant_profile.all_field_keys,
            known_ids=variable_keys,
            issue=issue,
            fatal=True,
        )
        _check_references(
            owner=f"variant_profile:{variant_profile.id}",
            field_name="document_types",
            values=variant_profile.document_types,
            known_ids=document_type_ids,
            issue=issue,
            fatal=True,
        )

    for variable in variables:
        _check_reference(
            owner=f"variable:{variable.key}",
            field_name="unit",
            value=variable.unit,
            known_ids=unit_ids,
            issue=issue,
            fatal=True,
        )
        _check_references(
            owner=f"variable:{variable.key}",
            field_name="applies_to",
            values=variable.applies_to,
            known_ids=family_profile_ids | variant_profile_ids,
            issue=issue,
            fatal=False,
        )

    for material in materials:
        _check_reference(
            owner=f"material:{material.id}",
            field_name="parent_material_id",
            value=material.parent_material_id,
            known_ids=material_ids,
            issue=issue,
            fatal=True,
        )
        _check_references(
            owner=f"material:{material.id}",
            field_name="compatible_family_profiles",
            values=material.compatible_family_profiles,
            known_ids=family_profile_ids,
            issue=issue,
            fatal=True,
        )
        _check_references(
            owner=f"material:{material.id}",
            field_name="compatible_variant_profiles",
            values=material.compatible_variant_profiles,
            known_ids=variant_profile_ids,
            issue=issue,
            fatal=True,
        )

    for document_type in document_types:
        _check_references(
            owner=f"document_type:{document_type.id}",
            field_name="required_for_profiles",
            values=document_type.required_for_profiles,
            known_ids=family_profile_ids | variant_profile_ids,
            issue=issue,
            fatal=True,
        )

    for binding in profile_bindings:
        _check_reference(
            owner=f"profile_binding:{binding.id}",
            field_name="object_kind",
            value=binding.object_kind,
            known_ids=object_kind_ids,
            issue=issue,
            fatal=True,
        )
        _check_reference(
            owner=f"profile_binding:{binding.id}",
            field_name="family_profile_id",
            value=binding.family_profile_id,
            known_ids=family_profile_ids,
            issue=issue,
            fatal=True,
        )
        _check_reference(
            owner=f"profile_binding:{binding.id}",
            field_name="variant_profile_id",
            value=binding.variant_profile_id,
            known_ids=variant_profile_ids,
            issue=issue,
            fatal=True,
        )

    return warnings, errors


def _profile_binding_match_score(
    binding: ProfileBindingDefinition,
    *,
    domain: str,
    category: str,
    subcategory: str,
    object_kind: str,
    family_profile_id: str,
) -> Optional[Tuple[int, int, int, str]]:
    if not getattr(binding, "active", True):
        return None

    binding_match = getattr(binding, "match", None)
    if not isinstance(binding_match, Mapping):
        binding_match = {}

    if _as_bool(binding_match.get("use_only_if_family_profile_selected"), default=False):
        if not family_profile_id:
            return None

    if not _profile_binding_field_matches(binding.domain, domain):
        return None

    if not _profile_binding_field_matches(binding.category, category):
        return None

    if not _profile_binding_field_matches(binding.subcategory, subcategory):
        return None

    if not _profile_binding_field_matches(binding.object_kind, object_kind):
        return None

    if family_profile_id:
        if binding.family_profile_id and binding.family_profile_id != family_profile_id:
            return None

    specificity = _profile_binding_specificity_score(
        binding,
        include_family_profile=bool(family_profile_id),
    )
    priority = int(getattr(binding, "priority", 1000) or 1000)
    sort_order = int(getattr(binding, "sort_order", 1000) or 1000)
    binding_id = str(getattr(binding, "id", ""))

    # Lower tuple wins:
    # - more specificity first
    # - lower priority second
    # - lower sort order third
    # - deterministic id last
    return (
        -specificity,
        priority,
        sort_order,
        binding_id,
    )


def _profile_binding_field_matches(expected: Optional[str], actual: str) -> bool:
    clean_expected = _clean_string(expected)
    if not clean_expected:
        return True

    clean_actual = _clean_string(actual)
    if not clean_actual:
        return False

    return clean_expected == clean_actual


def _profile_binding_specificity_score(
    binding: ProfileBindingDefinition,
    *,
    include_family_profile: bool,
) -> int:
    score = 0

    if _clean_string(binding.domain):
        score += 1

    if _clean_string(binding.category):
        score += 1

    if _clean_string(binding.subcategory):
        score += 1

    if _clean_string(binding.object_kind):
        score += 1

    if include_family_profile and _clean_string(binding.family_profile_id):
        score += 1

    if _clean_string(binding.variant_profile_id):
        score += 1

    return score


def _check_reference(
    *,
    owner: str,
    field_name: str,
    value: Optional[str],
    known_ids: Iterable[str],
    issue: Any,
    fatal: bool = True,
) -> None:
    clean = _clean_string(value)
    if not clean:
        return
    if clean not in known_ids:
        issue(
            f"{owner}.{field_name} references unknown definition {clean!r}",
            fatal=fatal,
        )


def _check_references(
    *,
    owner: str,
    field_name: str,
    values: Sequence[str],
    known_ids: Iterable[str],
    issue: Any,
    fatal: bool = True,
) -> None:
    for value in values or ():
        _check_reference(
            owner=owner,
            field_name=field_name,
            value=value,
            known_ids=known_ids,
            issue=issue,
            fatal=fatal,
        )


def get_definition_registry_health(
    *,
    force_reload: bool = False,
    definitions_root: Optional[Any] = None,
) -> Dict[str, Any]:
    try:
        registry = get_definition_registry(
            force_reload=force_reload,
            definitions_root=definitions_root,
        )
        return registry.health()
    except Exception as exc:
        return {
            "ok": False,
            "healthy": False,
            "status": "unavailable",
            "component": "library.definitions.registry",
            "version": DEFINITION_REGISTRY_VERSION,
            "error": _format_exception(exc),
        }


def get_definitions_registry_health(**kwargs: Any) -> Dict[str, Any]:
    return get_definition_registry_health(**kwargs)


def get_definitions_health(**kwargs: Any) -> Dict[str, Any]:
    return get_definition_registry_health(**kwargs)


def get_definitions_payload(
    *,
    include_inactive: bool = False,
    include_internal: bool = False,
    include_extra: bool = True,
    language: str = "de",
    force_reload: bool = False,
    definitions_root: Optional[Any] = None,
) -> Dict[str, Any]:
    registry = get_definition_registry(
        force_reload=force_reload,
        definitions_root=definitions_root,
    )
    return registry.to_dict(
        include_inactive=include_inactive,
        include_internal=include_internal,
        include_extra=include_extra,
        language=language,
    )


def get_definition_options(**kwargs: Any) -> Dict[str, Any]:
    return get_definitions_payload(**kwargs)


def get_create_definition_options(**kwargs: Any) -> Dict[str, Any]:
    return get_definitions_payload(**kwargs)


def get_definitions_summary(
    *,
    force_reload: bool = False,
    definitions_root: Optional[Any] = None,
) -> Dict[str, Any]:
    registry = get_definition_registry(
        force_reload=force_reload,
        definitions_root=definitions_root,
    )
    return registry.summary()


def clear_definition_registry_cache() -> Dict[str, Any]:
    before = _cache_info_to_dict(_get_definition_registry_cached.cache_info())
    _get_definition_registry_cached.cache_clear()
    after = _cache_info_to_dict(_get_definition_registry_cached.cache_info())

    return {
        "ok": True,
        "status": "cleared",
        "component": "library.definitions.registry",
        "before": before,
        "after": after,
    }


def clear_definition_caches() -> Dict[str, Any]:
    return clear_definition_registry_cache()


def clear_definitions_caches() -> Dict[str, Any]:
    return clear_definition_registry_cache()


def clear_cache() -> Dict[str, Any]:
    return clear_definition_registry_cache()


def _index_by_id(items: Sequence[Any]) -> Dict[str, Any]:
    return {
        _clean_string(getattr(item, "id", "")): item
        for item in items or ()
        if _clean_string(getattr(item, "id", ""))
    }


def _id_set(items: Sequence[Any]) -> set[str]:
    return {
        _clean_string(getattr(item, "id", ""))
        for item in items or ()
        if _clean_string(getattr(item, "id", ""))
    }


def _filter_active(items: Sequence[Any], *, include_inactive: bool = False) -> Tuple[Any, ...]:
    if include_inactive:
        return tuple(items or ())
    return tuple(item for item in items or () if getattr(item, "active", True))


def _normalize_optional_path(value: Optional[Any]) -> Optional[Path]:
    if value is None:
        return None
    if isinstance(value, Path):
        return value
    clean = _clean_string(value)
    if not clean:
        return None
    return Path(clean)


def _path_cache_value(value: Optional[Path]) -> Optional[str]:
    if value is None:
        return None

    try:
        return str(value.expanduser().resolve())
    except Exception:
        return str(value)


def _clean_string(value: Any, *, default: str = "") -> str:
    if value is None:
        return default
    clean = str(value).strip()
    return clean or default


def _as_bool(value: Any, *, default: bool = False) -> bool:
    if value is None:
        return default
    if isinstance(value, bool):
        return value
    if isinstance(value, (int, float)):
        return bool(value)
    if isinstance(value, str):
        clean = value.strip().lower()
        if clean in {"1", "true", "yes", "y", "on", "active", "enabled"}:
            return True
        if clean in {"0", "false", "no", "n", "off", "inactive", "disabled"}:
            return False
    return default


def _copy_mapping(value: Optional[Mapping[str, Any]]) -> Dict[str, Any]:
    if not isinstance(value, Mapping):
        return {}
    return dict(value)


def _drop_empty(payload: Mapping[str, Any]) -> Dict[str, Any]:
    result: Dict[str, Any] = {}

    for key, value in payload.items():
        if value is None:
            continue
        if value == "":
            continue
        if value == []:
            continue
        if value == {}:
            continue
        if value == ():
            continue
        result[key] = value

    return result


def _format_exception(exc: BaseException) -> str:
    return f"{exc.__class__.__name__}: {exc}"


def _cache_info_to_dict(info: Any) -> Dict[str, Any]:
    return {
        "hits": getattr(info, "hits", None),
        "misses": getattr(info, "misses", None),
        "maxsize": getattr(info, "maxsize", None),
        "currsize": getattr(info, "currsize", None),
    }