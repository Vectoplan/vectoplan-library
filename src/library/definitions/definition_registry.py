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

import hashlib
import json
import logging
import threading
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


DEFINITION_REGISTRY_VERSION = "0.2.0"

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

STARTER_VARIANT_PROFILE_ID = "simple_cell_block.v1"
STARTER_FAMILY_PROFILE_ID = "simple_cell_block"
STARTER_OBJECT_KIND = "cell_block"
STARTER_REQUIRED_DEFAULT_FIELDS: Tuple[str, ...] = (
    "variant.variant_id",
    "variant.label",
    "dimensions.width_mm",
    "dimensions.height_mm",
    "dimensions.depth_mm",
)

DEFAULT_MAX_JSON_BYTES = 16 * 1024 * 1024
_CACHE_KEY_LENGTH = 13

_LOGGER = logging.getLogger(__name__)
_REGISTRY_BUILD_LOCK = threading.RLock()
_LAST_KNOWN_GOOD_LOCK = threading.RLock()
_LAST_KNOWN_GOOD: Dict[Tuple[Any, ...], "DefinitionRegistry"] = {}


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
    auto_reload_on_change: bool = True
    keep_last_known_good: bool = True
    validate_starter_profile: bool = True
    max_json_bytes: int = DEFAULT_MAX_JSON_BYTES
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
            auto_reload_on_change=_as_bool(data.get("auto_reload_on_change"), default=True),
            keep_last_known_good=_as_bool(data.get("keep_last_known_good"), default=True),
            validate_starter_profile=_as_bool(data.get("validate_starter_profile"), default=True),
            max_json_bytes=_as_int(
                data.get("max_json_bytes"),
                default=DEFAULT_MAX_JSON_BYTES,
                minimum=1024,
            ),
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
            bool(self.auto_reload_on_change),
            bool(self.keep_last_known_good),
            bool(self.validate_starter_profile),
            int(self.max_json_bytes),
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
            "auto_reload_on_change": self.auto_reload_on_change,
            "keep_last_known_good": self.keep_last_known_good,
            "validate_starter_profile": self.validate_starter_profile,
            "max_json_bytes": self.max_json_bytes,
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
    byte_size: Optional[int] = None
    modified_ns: Optional[int] = None
    sha256: Optional[str] = None
    source_kind: str = "single"
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
                "byte_size": self.byte_size,
                "modified_ns": self.modified_ns,
                "sha256": self.sha256,
                "source_kind": self.source_kind,
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
    source_signature: Optional[str] = None
    serving_last_known_good: bool = False
    fallback_reason: Optional[str] = None
    warnings: List[str] = field(default_factory=list)
    errors: List[str] = field(default_factory=list)

    @property
    def current_load_ok(self) -> bool:
        return not self.errors and self.snapshot.ok

    @property
    def ok(self) -> bool:
        return self.current_load_ok or self.serving_last_known_good

    @property
    def healthy(self) -> bool:
        return self.current_load_ok and not self.serving_last_known_good

    def to_dict(self) -> Dict[str, Any]:
        return {
            "ok": self.ok,
            "healthy": self.healthy,
            "status": (
                "healthy"
                if self.healthy
                else "degraded_last_known_good"
                if self.serving_last_known_good
                else "degraded"
            ),
            "data_root": str(self.data_root),
            "combined_file": str(self.combined_file) if self.combined_file else None,
            "source_signature": self.source_signature,
            "serving_last_known_good": self.serving_last_known_good,
            "fallback_reason": self.fallback_reason,
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

        (
            self._object_kinds_by_id,
            self._object_kind_aliases,
            object_kind_collisions,
        ) = _build_lookup_index(snapshot.object_kinds)
        (
            self._family_profiles_by_id,
            self._family_profile_aliases,
            family_profile_collisions,
        ) = _build_lookup_index(snapshot.family_profiles)
        (
            self._variant_profiles_by_id,
            self._variant_profile_aliases,
            variant_profile_collisions,
        ) = _build_lookup_index(snapshot.variant_profiles)
        (
            self._variables_by_key,
            self._variable_aliases,
            variable_collisions,
        ) = _build_lookup_index(snapshot.variables)
        (
            self._units_by_id,
            self._unit_aliases,
            unit_collisions,
        ) = _build_lookup_index(snapshot.units)
        (
            self._materials_by_id,
            self._material_aliases,
            material_collisions,
        ) = _build_lookup_index(snapshot.materials)
        (
            self._document_types_by_id,
            self._document_type_aliases,
            document_type_collisions,
        ) = _build_lookup_index(snapshot.document_types)
        (
            self._profile_bindings_by_id,
            self._profile_binding_aliases,
            profile_binding_collisions,
        ) = _build_lookup_index(snapshot.profile_bindings)

        self._lookup_warnings = tuple(
            object_kind_collisions
            + family_profile_collisions
            + variant_profile_collisions
            + variable_collisions
            + unit_collisions
            + material_collisions
            + document_type_collisions
            + profile_binding_collisions
        )
        self._starter_profile_status = _build_starter_profile_status(
            self._variant_profiles_by_id,
            self._variant_profile_aliases,
        )

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
    def available(self) -> bool:
        if not self._snapshot:
            return False
        if not self._options.validate_starter_profile:
            return True
        return bool(self._starter_profile_status.get("available"))

    @property
    def serving_last_known_good(self) -> bool:
        return bool(self._load_result and self._load_result.serving_last_known_good)

    @property
    def ok(self) -> bool:
        return self._snapshot.ok and self.available

    @property
    def healthy(self) -> bool:
        load_is_healthy = self._load_result.healthy if self._load_result else True
        return self._snapshot.healthy and self.available and load_is_healthy

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
                "starter_profile": dict(self._starter_profile_status),
                "lookup_warnings": list(self._lookup_warnings),
                "alias_counts": {
                    "object_kinds": len(self._object_kind_aliases),
                    "family_profiles": len(self._family_profile_aliases),
                    "variant_profiles": len(self._variant_profile_aliases),
                    "variables": len(self._variable_aliases),
                    "units": len(self._unit_aliases),
                    "materials": len(self._material_aliases),
                    "document_types": len(self._document_type_aliases),
                    "profile_bindings": len(self._profile_binding_aliases),
                },
            }

        return payload

    def summary(self) -> Dict[str, Any]:
        payload = self._snapshot.summary()
        payload.update(
            {
                "registry_version": DEFINITION_REGISTRY_VERSION,
                "data_root": str(self._data_root) if self._data_root else None,
                "available": self.available,
                "healthy": self.healthy,
                "serving_last_known_good": self.serving_last_known_good,
                "starter_profile": dict(self._starter_profile_status),
            }
        )
        return payload

    def health(self) -> Dict[str, Any]:
        load_result_payload = self._load_result.to_dict() if self._load_result else None
        warnings = list(self._snapshot.warnings) + list(self._lookup_warnings)
        errors = list(self._snapshot.errors)

        if self._options.validate_starter_profile and not self._starter_profile_status.get("ok"):
            errors.extend(self._starter_profile_status.get("errors") or ())

        status = (
            "healthy"
            if self.healthy
            else "degraded_last_known_good"
            if self.serving_last_known_good
            else "degraded"
            if self.available
            else "unavailable"
        )

        return {
            "ok": self.ok,
            "available": self.available,
            "healthy": self.healthy,
            "status": status,
            "component": "library.definitions.registry",
            "version": DEFINITION_REGISTRY_VERSION,
            "definitions_version": self._snapshot.definitions_version,
            "schema_version": self._snapshot.schema_version,
            "data_root": str(self._data_root) if self._data_root else None,
            "source_signature": self._load_result.source_signature if self._load_result else None,
            "serving_last_known_good": self.serving_last_known_good,
            "counts": self.counts(include_inactive=True),
            "starter_profile": dict(self._starter_profile_status),
            "lookup_warnings": list(self._lookup_warnings),
            "warnings": warnings,
            "errors": errors,
            "cache": get_definition_registry_cache_info(),
            "load_result": load_result_payload,
        }

    def get_object_kind(self, object_kind: str) -> Optional[ObjectKindDefinition]:
        return _lookup_definition(
            object_kind,
            canonical_index=self._object_kinds_by_id,
            alias_index=self._object_kind_aliases,
        )

    def get_family_profile(self, profile_id: str) -> Optional[FamilyProfileDefinition]:
        return _lookup_definition(
            profile_id,
            canonical_index=self._family_profiles_by_id,
            alias_index=self._family_profile_aliases,
        )

    def get_variant_profile(self, profile_id: str) -> Optional[VariantProfileDefinition]:
        return _lookup_definition(
            profile_id,
            canonical_index=self._variant_profiles_by_id,
            alias_index=self._variant_profile_aliases,
        )

    def get_variant_profile_canonical_id(self, profile_id: str) -> Optional[str]:
        profile = self.get_variant_profile(profile_id)
        return _definition_identifier(profile) if profile else None

    def has_variant_profile(self, profile_id: str, *, require_active: bool = True) -> bool:
        profile = self.get_variant_profile(profile_id)
        if not profile:
            return False
        return bool(getattr(profile, "active", True)) if require_active else True

    def lookup_variant_profile(self, profile_id: str) -> Dict[str, Any]:
        requested_id = _clean_string(profile_id)
        requested_key = _normalize_lookup_key(requested_id)
        profile = self.get_variant_profile(requested_id)

        if profile is None:
            return {
                "ok": False,
                "status": "not_found",
                "source": "registry",
                "requested_profile_id": requested_id,
                "canonical_profile_id": None,
                "matched_by": None,
                "error": (
                    f"Unknown variant_profile_id: {requested_id}"
                    if requested_id
                    else "variant_profile_id is required"
                ),
            }

        canonical_id = _definition_identifier(profile)
        canonical_key = _normalize_lookup_key(canonical_id)
        matched_by = "canonical_id" if requested_key == canonical_key else "alias"

        return {
            "ok": True,
            "status": "ok",
            "source": "registry",
            "requested_profile_id": requested_id,
            "canonical_profile_id": canonical_id,
            "matched_by": matched_by,
            "active": bool(getattr(profile, "active", True)),
            "profile": profile,
        }

    def get_variable(self, variable_key: str) -> Optional[VariableDefinition]:
        return _lookup_definition(
            variable_key,
            canonical_index=self._variables_by_key,
            alias_index=self._variable_aliases,
        )

    def get_unit(self, unit_id: str) -> Optional[UnitDefinition]:
        return _lookup_definition(
            unit_id,
            canonical_index=self._units_by_id,
            alias_index=self._unit_aliases,
        )

    def get_material(self, material_id: str) -> Optional[MaterialDefinition]:
        return _lookup_definition(
            material_id,
            canonical_index=self._materials_by_id,
            alias_index=self._material_aliases,
        )

    def get_document_type(self, document_type_id: str) -> Optional[DocumentTypeDefinition]:
        return _lookup_definition(
            document_type_id,
            canonical_index=self._document_types_by_id,
            alias_index=self._document_type_aliases,
        )

    def get_profile_binding(self, binding_id: str) -> Optional[ProfileBindingDefinition]:
        return _lookup_definition(
            binding_id,
            canonical_index=self._profile_bindings_by_id,
            alias_index=self._profile_binding_aliases,
        )

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
        lookup = self.lookup_variant_profile(variant_profile_id)
        if not lookup.get("ok"):
            return {
                **lookup,
                "variant_profile_id": _clean_string(variant_profile_id),
            }

        variant_profile = lookup["profile"]

        if not include_inactive and not bool(getattr(variant_profile, "active", True)):
            return {
                "ok": False,
                "status": "inactive",
                "source": "registry",
                "requested_profile_id": lookup.get("requested_profile_id"),
                "variant_profile_id": lookup.get("canonical_profile_id"),
                "canonical_profile_id": lookup.get("canonical_profile_id"),
                "matched_by": lookup.get("matched_by"),
                "error": (
                    f"Variant profile {lookup.get('canonical_profile_id')!r} "
                    "is inactive."
                ),
            }

        try:
            variables = self.get_variables_for_variant_profile(
                lookup["canonical_profile_id"],
                include_inactive=include_inactive,
            )
            profile_payload = variant_profile.to_dict(
                include_extra=include_extra,
                include_inactive=include_inactive,
                language=language,
            )
            variable_payloads = {
                variable.key: variable.to_dict(
                    include_extra=include_extra,
                    include_inactive=include_inactive,
                    language=language,
                )
                for variable in variables
            }
        except Exception as exc:
            _LOGGER.exception(
                "Could not serialize variant profile %s",
                lookup.get("canonical_profile_id"),
            )
            return {
                "ok": False,
                "status": "serialization_error",
                "source": "registry",
                "requested_profile_id": lookup.get("requested_profile_id"),
                "variant_profile_id": lookup.get("canonical_profile_id"),
                "canonical_profile_id": lookup.get("canonical_profile_id"),
                "matched_by": lookup.get("matched_by"),
                "error": _format_exception(exc),
            }

        return {
            "ok": True,
            "status": "ok",
            "source": "registry",
            "requested_profile_id": lookup.get("requested_profile_id"),
            "variant_profile_id": lookup.get("canonical_profile_id"),
            "canonical_profile_id": lookup.get("canonical_profile_id"),
            "matched_by": lookup.get("matched_by"),
            "serving_last_known_good": self.serving_last_known_good,
            "variant_profile": profile_payload,
            "variables": variable_payloads,
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
    auto_reload_on_change: bool = True,
    keep_last_known_good: bool = True,
    validate_starter_profile: bool = True,
    max_json_bytes: int = DEFAULT_MAX_JSON_BYTES,
) -> DefinitionRegistry:
    """
    Return the cached definitions registry.

    Cache behavior:
    - The configuration is represented only by a hashable tuple.
    - With ``auto_reload_on_change=True`` the selected definition files contribute
      a stat-based source signature. A changed file therefore receives a new cache
      entry without requiring a process restart.
    - ``force_reload=True`` clears only the active LRU entries. The last-known-good
      snapshot remains available as a safety net unless explicitly cleared.
    """
    if force_reload:
        clear_definition_registry_cache(clear_last_known_good=False)

    options = DefinitionRegistryOptions(
        definitions_root=_normalize_optional_path(definitions_root),
        definitions_version=_clean_string(definitions_version, default=DEFINITION_DEFAULT_VERSION),
        schema_version=DEFINITION_SCHEMA_VERSION,
        strict_references=bool(strict_references),
        allow_missing_datasets=bool(allow_missing_datasets),
        allow_empty_datasets=bool(allow_empty_datasets),
        use_config_fallback=bool(use_config_fallback),
        auto_reload_on_change=bool(auto_reload_on_change),
        keep_last_known_good=bool(keep_last_known_good),
        validate_starter_profile=bool(validate_starter_profile),
        max_json_bytes=_as_int(
            max_json_bytes,
            default=DEFAULT_MAX_JSON_BYTES,
            minimum=1024,
        ),
    )

    options_cache_key = options.cache_key()
    source_signature = (
        calculate_definitions_source_signature(options)
        if options.auto_reload_on_change
        else "auto-reload-disabled"
    )

    return _get_definition_registry_cached(options_cache_key, source_signature)


def get_definitions_registry(**kwargs: Any) -> DefinitionRegistry:
    return get_definition_registry(**kwargs)


def create_definition_registry(**kwargs: Any) -> DefinitionRegistry:
    cleaned_kwargs = dict(kwargs)
    cleaned_kwargs["force_reload"] = True
    return get_definition_registry(**cleaned_kwargs)


def create_definitions_registry(**kwargs: Any) -> DefinitionRegistry:
    return create_definition_registry(**kwargs)


@lru_cache(maxsize=32)
def _get_definition_registry_cached(
    cache_key: Tuple[Any, ...],
    source_signature: str,
) -> DefinitionRegistry:
    """
    Build and cache one immutable registry generation.

    ``source_signature`` is intentionally a separate hashable argument. The LRU
    cache can therefore retain a small number of previous generations while a
    changed JSON file automatically triggers a new build.
    """
    options = _options_from_cache_key(cache_key)

    with _REGISTRY_BUILD_LOCK:
        try:
            load_result = load_registry(
                options,
                source_signature=source_signature,
            )
            candidate = DefinitionRegistry(
                load_result.snapshot,
                options=options,
                data_root=load_result.data_root,
                load_result=load_result,
            )
        except Exception as exc:
            _LOGGER.exception("Unexpected definitions registry build failure")
            candidate = _build_unavailable_registry(
                options,
                source_signature=source_signature,
                error=_format_exception(exc),
            )

        if candidate.healthy:
            _store_last_known_good(cache_key, candidate)
            return candidate

        if options.keep_last_known_good:
            fallback = _get_last_known_good(cache_key)
            if fallback is not None:
                return _build_last_known_good_registry(
                    fallback,
                    failed_candidate=candidate,
                    options=options,
                    source_signature=source_signature,
                )

        return candidate


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
        auto_reload_on_change,
        keep_last_known_good,
        validate_starter_profile,
        max_json_bytes,
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
        auto_reload_on_change=bool(auto_reload_on_change),
        keep_last_known_good=bool(keep_last_known_good),
        validate_starter_profile=bool(validate_starter_profile),
        max_json_bytes=_as_int(
            max_json_bytes,
            default=DEFAULT_MAX_JSON_BYTES,
            minimum=1024,
        ),
        source_label=_clean_string(source_label, default="definitions"),
        metadata={
            "from_cache_key": True,
        },
    )


def _store_last_known_good(
    cache_key: Tuple[Any, ...],
    registry: DefinitionRegistry,
) -> None:
    if not registry.healthy:
        return

    with _LAST_KNOWN_GOOD_LOCK:
        _LAST_KNOWN_GOOD[cache_key] = registry


def _get_last_known_good(
    cache_key: Tuple[Any, ...],
) -> Optional[DefinitionRegistry]:
    with _LAST_KNOWN_GOOD_LOCK:
        return _LAST_KNOWN_GOOD.get(cache_key)


def _build_last_known_good_registry(
    fallback: DefinitionRegistry,
    *,
    failed_candidate: DefinitionRegistry,
    options: DefinitionRegistryOptions,
    source_signature: str,
) -> DefinitionRegistry:
    failed_result = failed_candidate.load_result
    fallback_reason = "The current definitions generation is invalid."

    if failed_result:
        if failed_result.errors:
            fallback_reason = "; ".join(failed_result.errors)
        elif not failed_candidate.available:
            fallback_reason = (
                f"Required starter profile {STARTER_VARIANT_PROFILE_ID!r} "
                "is unavailable in the current definitions generation."
            )

    load_result = RegistryLoadResult(
        snapshot=fallback.snapshot,
        options=options,
        data_root=(
            failed_result.data_root
            if failed_result is not None
            else fallback.data_root
            or Path(__file__).resolve().parent / "data"
        ),
        dataset_results=(
            dict(failed_result.dataset_results)
            if failed_result is not None
            else {}
        ),
        combined_file=failed_result.combined_file if failed_result else None,
        source_signature=source_signature,
        serving_last_known_good=True,
        fallback_reason=fallback_reason,
        warnings=_deduplicate_strings(
            list(failed_result.warnings if failed_result else ())
            + [
                "Serving the last-known-good definitions snapshot because the "
                "current source generation could not be published."
            ]
        ),
        errors=list(failed_result.errors if failed_result else (fallback_reason,)),
    )

    _LOGGER.error(
        "Definitions registry reload failed; serving last-known-good snapshot. %s",
        fallback_reason,
    )

    return DefinitionRegistry(
        fallback.snapshot,
        options=options,
        data_root=fallback.data_root,
        load_result=load_result,
    )


def _build_unavailable_registry(
    options: DefinitionRegistryOptions,
    *,
    source_signature: str,
    error: str,
) -> DefinitionRegistry:
    try:
        data_root = resolve_definitions_data_root(options)
    except Exception:
        data_root = Path(__file__).resolve().parent / "data"

    loaded_at = datetime.now(timezone.utc).isoformat()
    errors = [error]
    snapshot = build_registry_snapshot(
        definitions_version=options.definitions_version,
        schema_version=options.schema_version,
        source=str(data_root),
        loaded_at=loaded_at,
        object_kinds=(),
        family_profiles=(),
        variant_profiles=(),
        variables=(),
        units=(),
        materials=(),
        document_types=(),
        profile_bindings=(),
        warnings=(),
        errors=errors,
        metadata={
            **options.metadata,
            "registry_version": DEFINITION_REGISTRY_VERSION,
            "source_signature": source_signature,
            "unavailable": True,
        },
    )
    load_result = RegistryLoadResult(
        snapshot=snapshot,
        options=options,
        data_root=data_root,
        source_signature=source_signature,
        warnings=[],
        errors=errors,
    )
    return DefinitionRegistry(
        snapshot,
        options=options,
        data_root=data_root,
        load_result=load_result,
    )


def load_registry(
    options: Optional[DefinitionRegistryOptions] = None,
    *,
    source_signature: Optional[str] = None,
) -> RegistryLoadResult:
    """
    Load, parse and cross-validate all definition datasets.

    The function never mutates a previously published registry generation. A
    complete candidate snapshot is built first and later swapped into the cache
    only when it is healthy. This makes concurrent reads deterministic.
    """
    options = options or DefinitionRegistryOptions()
    warnings: List[str] = []
    errors: List[str] = []

    try:
        data_root = resolve_definitions_data_root(options)
    except Exception as exc:
        data_root = Path(__file__).resolve().parent / "data"
        errors.append(
            "Could not resolve definitions data root: "
            f"{_format_exception(exc)}"
        )

    loaded_at = datetime.now(timezone.utc).isoformat()
    effective_source_signature = source_signature or calculate_definitions_source_signature(
        options,
        data_root=data_root,
    )

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
            combined_data, file_metadata = _load_json_file_with_metadata(
                combined_file,
                max_bytes=options.max_json_bytes,
            )
            _validate_combined_dataset_envelope(
                combined_data,
                path=combined_file,
                options=options,
            )

            for dataset_name in DEFINITIONS_DATASETS:
                dataset_result, parsed_items = _parse_dataset_from_combined_file(
                    dataset_name,
                    combined_data,
                    combined_file,
                    options=options,
                    file_metadata=file_metadata,
                )
                dataset_results[dataset_name] = dataset_result
                parsed_datasets[dataset_name] = parsed_items

                if dataset_result.warning:
                    warnings.append(dataset_result.warning)
                if dataset_result.error:
                    errors.append(dataset_result.error)
        except Exception as exc:
            error = (
                f"Could not load combined definitions file {combined_file}: "
                f"{_format_exception(exc)}"
            )
            errors.append(error)
            _LOGGER.exception(error)

            file_metadata = _safe_file_metadata(combined_file)
            for dataset_name in DEFINITIONS_DATASETS:
                dataset_results[dataset_name] = DatasetLoadResult(
                    dataset_name=dataset_name,
                    path=combined_file,
                    found=combined_file.exists(),
                    ok=False,
                    byte_size=file_metadata.get("byte_size"),
                    modified_ns=file_metadata.get("modified_ns"),
                    sha256=file_metadata.get("sha256"),
                    source_kind="combined",
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

    alias_warnings, alias_errors = validate_lookup_aliases_from_items(
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
    warnings.extend(alias_warnings)
    errors.extend(alias_errors)

    if options.validate_starter_profile:
        starter_warnings, starter_errors = validate_creator_starter_profile(
            parsed_datasets["variant_profiles"],
            strict=options.strict_references,
        )
        warnings.extend(starter_warnings)
        errors.extend(starter_errors)

    warnings = _deduplicate_strings(warnings)
    errors = _deduplicate_strings(errors)

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
            "source_signature": effective_source_signature,
            "starter_variant_profile_id": STARTER_VARIANT_PROFILE_ID,
        },
    )

    return RegistryLoadResult(
        snapshot=snapshot,
        options=options,
        data_root=data_root,
        dataset_results=dataset_results,
        combined_file=combined_file,
        source_signature=effective_source_signature,
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


def calculate_definitions_source_signature(
    options: Optional[DefinitionRegistryOptions] = None,
    *,
    data_root: Optional[Path] = None,
) -> str:
    """
    Return a deterministic stat-based signature for the selected source files.

    File content is not read here. The loader calculates SHA-256 hashes while
    parsing; the inexpensive signature only decides whether the LRU cache needs a
    new generation.
    """
    options = options or DefinitionRegistryOptions()

    try:
        root = data_root or resolve_definitions_data_root(options)
    except Exception as exc:
        return _hash_text(
            f"unresolved-root|{options.cache_key()!r}|{_format_exception(exc)}"
        )

    parts: List[str] = [
        f"root={_path_cache_value(root)}",
        f"definitions_version={options.definitions_version}",
        f"schema_version={options.schema_version}",
    ]

    combined_file = _find_combined_dataset_file(
        root,
        definitions_version=options.definitions_version,
    )

    paths: List[Path]
    if combined_file:
        paths = [combined_file]
        parts.append("source_kind=combined")
    else:
        paths = [
            _dataset_file_path(
                root,
                dataset_name,
                options.definitions_version,
            )
            for dataset_name in DEFINITIONS_DATASETS
        ]
        parts.append("source_kind=single")

    for path in paths:
        parts.append(_file_stat_signature_part(path))

    return _hash_text("\n".join(parts))


def _file_stat_signature_part(path: Path) -> str:
    normalized = _path_cache_value(path)

    try:
        stat = path.stat()
    except FileNotFoundError:
        return f"{normalized}|missing"
    except OSError as exc:
        return f"{normalized}|stat-error={exc.__class__.__name__}:{exc}"

    return (
        f"{normalized}|file={path.is_file()}|size={stat.st_size}|"
        f"mtime_ns={stat.st_mtime_ns}|inode={getattr(stat, 'st_ino', 0)}"
    )


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
            source_kind="single",
            warning=message if options.allow_missing_datasets else None,
            error=None if options.allow_missing_datasets else message,
        )
        return result, tuple()

    if not path.is_file():
        error = f"Definitions dataset path is not a file: {path}"
        return (
            DatasetLoadResult(
                dataset_name=dataset_name,
                path=path,
                found=True,
                ok=False,
                source_kind="single",
                error=error,
            ),
            tuple(),
        )

    try:
        raw_data, file_metadata = _load_json_file_with_metadata(
            path,
            max_bytes=options.max_json_bytes,
        )
        _validate_single_dataset_envelope(
            dataset_name,
            raw_data,
            path=path,
            options=options,
        )
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
            byte_size=file_metadata.get("byte_size"),
            modified_ns=file_metadata.get("modified_ns"),
            sha256=file_metadata.get("sha256"),
            source_kind="single",
        )
        return result, parsed_items
    except Exception as exc:
        error = (
            f"Could not load definitions dataset {dataset_name!r} from {path}: "
            f"{_format_exception(exc)}"
        )
        _LOGGER.exception(error)
        file_metadata = _safe_file_metadata(path)

        result = DatasetLoadResult(
            dataset_name=dataset_name,
            path=path,
            found=True,
            ok=False,
            item_count=0,
            byte_size=file_metadata.get("byte_size"),
            modified_ns=file_metadata.get("modified_ns"),
            sha256=file_metadata.get("sha256"),
            source_kind="single",
            error=error,
        )
        return result, tuple()


def _parse_dataset_from_combined_file(
    dataset_name: str,
    combined_data: Mapping[str, Any],
    path: Path,
    *,
    options: DefinitionRegistryOptions,
    file_metadata: Optional[Mapping[str, Any]] = None,
) -> Tuple[DatasetLoadResult, Tuple[Any, ...]]:
    metadata = dict(file_metadata or {})

    if not isinstance(combined_data, Mapping):
        error = f"Combined definitions file must contain a JSON object: {path}"
        return (
            DatasetLoadResult(
                dataset_name=dataset_name,
                path=path,
                found=True,
                ok=False,
                byte_size=metadata.get("byte_size"),
                modified_ns=metadata.get("modified_ns"),
                sha256=metadata.get("sha256"),
                source_kind="combined",
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
                byte_size=metadata.get("byte_size"),
                modified_ns=metadata.get("modified_ns"),
                sha256=metadata.get("sha256"),
                source_kind="combined",
                warning=message if options.allow_missing_datasets else None,
                error=None if options.allow_missing_datasets else message,
            ),
            tuple(),
        )

    try:
        raw_dataset = combined_data.get(dataset_name)
        _validate_combined_dataset_section(
            dataset_name,
            raw_dataset,
            path=path,
            options=options,
        )
        parsed_items = parse_dataset_items(
            dataset_name,
            raw_dataset,
            allow_empty=options.allow_empty_datasets,
        )

        return (
            DatasetLoadResult(
                dataset_name=dataset_name,
                path=path,
                found=True,
                ok=True,
                item_count=len(parsed_items),
                byte_size=metadata.get("byte_size"),
                modified_ns=metadata.get("modified_ns"),
                sha256=metadata.get("sha256"),
                source_kind="combined",
            ),
            parsed_items,
        )
    except Exception as exc:
        error = (
            f"Could not parse dataset {dataset_name!r} in combined file {path}: "
            f"{_format_exception(exc)}"
        )
        _LOGGER.exception(error)
        return (
            DatasetLoadResult(
                dataset_name=dataset_name,
                path=path,
                found=True,
                ok=False,
                byte_size=metadata.get("byte_size"),
                modified_ns=metadata.get("modified_ns"),
                sha256=metadata.get("sha256"),
                source_kind="combined",
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
    data, _metadata = _load_json_file_with_metadata(
        path,
        max_bytes=DEFAULT_MAX_JSON_BYTES,
    )
    return data


def _load_json_file_with_metadata(
    path: Path,
    *,
    max_bytes: int,
) -> Tuple[Any, Dict[str, Any]]:
    """
    Load one UTF-8 JSON file with duplicate-key detection and size limits.
    """
    if not path.exists():
        raise DefinitionDatasetError(f"JSON file does not exist: {path}")

    if not path.is_file():
        raise DefinitionDatasetError(f"JSON path is not a regular file: {path}")

    try:
        stat_before = path.stat()
    except OSError as exc:
        raise DefinitionDatasetError(
            f"Could not stat JSON file {path}: {_format_exception(exc)}"
        ) from exc

    effective_max_bytes = _as_int(
        max_bytes,
        default=DEFAULT_MAX_JSON_BYTES,
        minimum=1024,
    )
    if stat_before.st_size > effective_max_bytes:
        raise DefinitionDatasetError(
            f"JSON file {path} is too large: {stat_before.st_size} bytes; "
            f"limit is {effective_max_bytes} bytes"
        )

    try:
        raw_bytes = path.read_bytes()
    except OSError as exc:
        raise DefinitionDatasetError(
            f"Could not read JSON file {path}: {_format_exception(exc)}"
        ) from exc

    if len(raw_bytes) > effective_max_bytes:
        raise DefinitionDatasetError(
            f"JSON file {path} exceeded the configured limit while reading: "
            f"{len(raw_bytes)} bytes; limit is {effective_max_bytes} bytes"
        )

    if not raw_bytes:
        raise DefinitionDatasetError(f"JSON file is empty: {path}")

    try:
        text = raw_bytes.decode("utf-8-sig")
    except UnicodeDecodeError as exc:
        raise DefinitionDatasetError(
            f"JSON file {path} is not valid UTF-8: {exc}"
        ) from exc

    try:
        data = json.loads(
            text,
            object_pairs_hook=_reject_duplicate_json_keys,
        )
    except json.JSONDecodeError as exc:
        raise DefinitionDatasetError(
            f"Invalid JSON in {path}: line {exc.lineno}, column {exc.colno}: "
            f"{exc.msg}"
        ) from exc

    try:
        stat_after = path.stat()
    except OSError:
        stat_after = stat_before

    if (
        stat_before.st_size != stat_after.st_size
        or stat_before.st_mtime_ns != stat_after.st_mtime_ns
    ):
        raise DefinitionDatasetError(
            f"JSON file changed while it was being read: {path}"
        )

    metadata = {
        "byte_size": len(raw_bytes),
        "modified_ns": stat_after.st_mtime_ns,
        "sha256": hashlib.sha256(raw_bytes).hexdigest(),
    }
    return data, metadata


def _reject_duplicate_json_keys(
    pairs: Sequence[Tuple[str, Any]],
) -> Dict[str, Any]:
    result: Dict[str, Any] = {}

    for key, value in pairs:
        if key in result:
            raise DefinitionDatasetError(
                f"Duplicate JSON object key detected: {key!r}"
            )
        result[key] = value

    return result


def _safe_file_metadata(path: Path) -> Dict[str, Any]:
    metadata: Dict[str, Any] = {}

    try:
        stat = path.stat()
        metadata["byte_size"] = stat.st_size
        metadata["modified_ns"] = stat.st_mtime_ns
    except OSError:
        return metadata

    try:
        if path.is_file() and stat.st_size <= DEFAULT_MAX_JSON_BYTES:
            metadata["sha256"] = hashlib.sha256(path.read_bytes()).hexdigest()
    except OSError:
        pass

    return metadata


def _validate_single_dataset_envelope(
    dataset_name: str,
    raw_data: Any,
    *,
    path: Path,
    options: DefinitionRegistryOptions,
) -> None:
    if not isinstance(raw_data, Mapping):
        raise DefinitionDatasetError(
            f"Definitions dataset {dataset_name!r} must contain a JSON object: {path}"
        )

    declared_dataset = _clean_string(raw_data.get("dataset"))
    if declared_dataset and declared_dataset != dataset_name:
        raise DefinitionDatasetError(
            f"Definitions dataset mismatch in {path}: expected {dataset_name!r}, "
            f"got {declared_dataset!r}"
        )

    _validate_dataset_versions(
        raw_data,
        path=path,
        options=options,
    )

    items = raw_data.get("items")
    if items is None:
        raise DefinitionDatasetError(
            f"Definitions dataset {dataset_name!r} has no 'items' array: {path}"
        )
    if not isinstance(items, list):
        raise DefinitionDatasetError(
            f"Definitions dataset {dataset_name!r}.items must be an array: {path}"
        )
    if not items and not options.allow_empty_datasets:
        raise DefinitionDatasetError(
            f"Definitions dataset {dataset_name!r} must not be empty: {path}"
        )


def _validate_combined_dataset_envelope(
    raw_data: Any,
    *,
    path: Path,
    options: DefinitionRegistryOptions,
) -> None:
    if not isinstance(raw_data, Mapping):
        raise DefinitionDatasetError(
            f"Combined definitions file must contain a JSON object: {path}"
        )

    _validate_dataset_versions(
        raw_data,
        path=path,
        options=options,
        allow_missing=True,
    )


def _validate_combined_dataset_section(
    dataset_name: str,
    raw_dataset: Any,
    *,
    path: Path,
    options: DefinitionRegistryOptions,
) -> None:
    if isinstance(raw_dataset, list):
        if not raw_dataset and not options.allow_empty_datasets:
            raise DefinitionDatasetError(
                f"Combined dataset section {dataset_name!r} must not be empty: {path}"
            )
        return

    if not isinstance(raw_dataset, Mapping):
        raise DefinitionDatasetError(
            f"Combined dataset section {dataset_name!r} must be an object or array: "
            f"{path}"
        )

    declared_dataset = _clean_string(raw_dataset.get("dataset"))
    if declared_dataset and declared_dataset != dataset_name:
        raise DefinitionDatasetError(
            f"Combined dataset section mismatch in {path}: expected "
            f"{dataset_name!r}, got {declared_dataset!r}"
        )

    _validate_dataset_versions(
        raw_dataset,
        path=path,
        options=options,
        allow_missing=True,
    )


def _validate_dataset_versions(
    raw_data: Mapping[str, Any],
    *,
    path: Path,
    options: DefinitionRegistryOptions,
    allow_missing: bool = False,
) -> None:
    declared_schema = _clean_string(raw_data.get("schema_version"))
    declared_definitions = _clean_string(raw_data.get("definitions_version"))

    if declared_schema:
        if declared_schema != options.schema_version:
            raise DefinitionDatasetError(
                f"Schema version mismatch in {path}: expected "
                f"{options.schema_version!r}, got {declared_schema!r}"
            )
    elif not allow_missing:
        raise DefinitionDatasetError(
            f"Missing schema_version in definitions dataset: {path}"
        )

    if declared_definitions:
        if declared_definitions != options.definitions_version:
            raise DefinitionDatasetError(
                f"Definitions version mismatch in {path}: expected "
                f"{options.definitions_version!r}, got {declared_definitions!r}"
            )
    elif not allow_missing:
        raise DefinitionDatasetError(
            f"Missing definitions_version in definitions dataset: {path}"
        )


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


def validate_lookup_aliases_from_items(
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

    datasets: Tuple[Tuple[str, Sequence[Any]], ...] = (
        ("object_kinds", object_kinds),
        ("family_profiles", family_profiles),
        ("variant_profiles", variant_profiles),
        ("variables", variables),
        ("units", units),
        ("materials", materials),
        ("document_types", document_types),
        ("profile_bindings", profile_bindings),
    )

    for dataset_name, items in datasets:
        _canonical, _aliases, collisions = _build_lookup_index(items)

        for collision in collisions:
            message = f"{dataset_name}: {collision}"
            if strict:
                errors.append(message)
            else:
                warnings.append(message)

    return _deduplicate_strings(warnings), _deduplicate_strings(errors)


def validate_creator_starter_profile(
    variant_profiles: Sequence[VariantProfileDefinition],
    *,
    strict: bool = True,
) -> Tuple[List[str], List[str]]:
    """
    Validate the minimum profile required by the first downloadable cell block.
    """
    warnings: List[str] = []
    errors: List[str] = []

    canonical_index, alias_index, collisions = _build_lookup_index(variant_profiles)
    profile = _lookup_definition(
        STARTER_VARIANT_PROFILE_ID,
        canonical_index=canonical_index,
        alias_index=alias_index,
    )

    def issue(message: str, *, fatal: bool = True) -> None:
        if fatal and strict:
            errors.append(message)
        else:
            warnings.append(message)

    if collisions:
        for collision in collisions:
            issue(
                f"Starter profile lookup is ambiguous: {collision}",
                fatal=True,
            )

    if profile is None:
        issue(
            f"Required creator starter variant profile "
            f"{STARTER_VARIANT_PROFILE_ID!r} was not loaded.",
            fatal=True,
        )
        return _deduplicate_strings(warnings), _deduplicate_strings(errors)

    if not bool(getattr(profile, "active", True)):
        issue(
            f"Creator starter profile {STARTER_VARIANT_PROFILE_ID!r} is inactive.",
            fatal=True,
        )

    family_profiles = set(
        _clean_string(value)
        for value in _definition_sequence(profile, "family_profiles")
        if _clean_string(value)
    )
    if STARTER_FAMILY_PROFILE_ID not in family_profiles:
        issue(
            f"Creator starter profile {STARTER_VARIANT_PROFILE_ID!r} must allow "
            f"family profile {STARTER_FAMILY_PROFILE_ID!r}.",
            fatal=True,
        )

    object_kinds = set(
        _clean_string(value)
        for value in _definition_sequence(profile, "object_kinds")
        if _clean_string(value)
    )
    if STARTER_OBJECT_KIND not in object_kinds:
        issue(
            f"Creator starter profile {STARTER_VARIANT_PROFILE_ID!r} must allow "
            f"object kind {STARTER_OBJECT_KIND!r}.",
            fatal=True,
        )

    required_fields = set(
        _clean_string(value)
        for value in _definition_sequence(profile, "required_fields")
        if _clean_string(value)
    )
    all_fields = set(
        _clean_string(value)
        for value in (
            getattr(profile, "all_field_keys", None)
            or _definition_sequence(profile, "all_fields")
            or _definition_sequence(profile, "fields")
        )
        if _clean_string(value)
    )
    default_values = _definition_mapping(profile, "default_values")

    for field_key in STARTER_REQUIRED_DEFAULT_FIELDS:
        if field_key not in required_fields:
            issue(
                f"Creator starter profile {STARTER_VARIANT_PROFILE_ID!r} must list "
                f"{field_key!r} as required.",
                fatal=True,
            )

        if all_fields and field_key not in all_fields:
            issue(
                f"Creator starter profile {STARTER_VARIANT_PROFILE_ID!r} references "
                f"required field {field_key!r} outside its sections.",
                fatal=True,
            )

        if field_key not in default_values:
            issue(
                f"Creator starter profile {STARTER_VARIANT_PROFILE_ID!r} requires "
                f"a default value for {field_key!r}.",
                fatal=True,
            )

    for dimension_key in (
        "dimensions.width_mm",
        "dimensions.height_mm",
        "dimensions.depth_mm",
    ):
        value = default_values.get(dimension_key)
        if not isinstance(value, (int, float)) or isinstance(value, bool) or value <= 0:
            issue(
                f"Creator starter profile default {dimension_key!r} must be a "
                "positive number.",
                fatal=True,
            )

    variant_id = _clean_string(default_values.get("variant.variant_id"))
    if not variant_id:
        issue(
            "Creator starter profile must define a non-empty default "
            "'variant.variant_id'.",
            fatal=True,
        )

    variant_label = _clean_string(default_values.get("variant.label"))
    if not variant_label:
        issue(
            "Creator starter profile must define a non-empty default "
            "'variant.label'.",
            fatal=True,
        )

    return _deduplicate_strings(warnings), _deduplicate_strings(errors)


def _build_starter_profile_status(
    canonical_index: Mapping[str, Any],
    alias_index: Mapping[str, str],
) -> Dict[str, Any]:
    profile = _lookup_definition(
        STARTER_VARIANT_PROFILE_ID,
        canonical_index=canonical_index,
        alias_index=alias_index,
    )

    if profile is None:
        return {
            "ok": False,
            "available": False,
            "profile_id": STARTER_VARIANT_PROFILE_ID,
            "errors": [
                f"Required starter profile {STARTER_VARIANT_PROFILE_ID!r} "
                "is unavailable."
            ],
        }

    warnings, errors = validate_creator_starter_profile(
        (profile,),
        strict=True,
    )
    canonical_id = _definition_identifier(profile)

    return {
        "ok": not errors,
        "available": True,
        "active": bool(getattr(profile, "active", True)),
        "profile_id": canonical_id,
        "requested_profile_id": STARTER_VARIANT_PROFILE_ID,
        "family_profile_id": STARTER_FAMILY_PROFILE_ID,
        "object_kind": STARTER_OBJECT_KIND,
        "warnings": warnings,
        "errors": errors,
    }


def _build_lookup_index(
    items: Sequence[Any],
) -> Tuple[Dict[str, Any], Dict[str, str], List[str]]:
    canonical_index: Dict[str, Any] = {}
    alias_index: Dict[str, str] = {}
    collisions: List[str] = []

    for item in items or ():
        canonical_id = _definition_identifier(item)
        lookup_key = _normalize_lookup_key(canonical_id)
        if not lookup_key:
            continue

        existing = canonical_index.get(lookup_key)
        if existing is not None and existing is not item:
            collisions.append(
                f"duplicate canonical definition id {canonical_id!r}"
            )
            continue

        canonical_index[lookup_key] = item

    for item in items or ():
        canonical_id = _definition_identifier(item)
        canonical_key = _normalize_lookup_key(canonical_id)
        if not canonical_key or canonical_index.get(canonical_key) is not item:
            continue

        for alias in _definition_aliases(item):
            alias_key = _normalize_lookup_key(alias)
            if not alias_key or alias_key == canonical_key:
                continue

            canonical_owner = canonical_index.get(alias_key)
            if canonical_owner is not None and canonical_owner is not item:
                collisions.append(
                    f"alias {alias!r} of {canonical_id!r} collides with canonical "
                    f"id {_definition_identifier(canonical_owner)!r}"
                )
                continue

            existing_canonical_key = alias_index.get(alias_key)
            if existing_canonical_key and existing_canonical_key != canonical_key:
                existing_item = canonical_index.get(existing_canonical_key)
                collisions.append(
                    f"alias {alias!r} of {canonical_id!r} collides with alias of "
                    f"{_definition_identifier(existing_item)!r}"
                )
                continue

            alias_index[alias_key] = canonical_key

    return canonical_index, alias_index, _deduplicate_strings(collisions)


def _lookup_definition(
    lookup_value: Any,
    *,
    canonical_index: Mapping[str, Any],
    alias_index: Mapping[str, str],
) -> Optional[Any]:
    lookup_key = _normalize_lookup_key(lookup_value)
    if not lookup_key:
        return None

    item = canonical_index.get(lookup_key)
    if item is not None:
        return item

    canonical_key = alias_index.get(lookup_key)
    if not canonical_key:
        return None

    return canonical_index.get(canonical_key)


def _definition_identifier(item: Any) -> str:
    if item is None:
        return ""

    direct = getattr(item, "id", None)
    if direct is None:
        direct = getattr(item, "key", None)

    if direct is not None:
        return _clean_string(direct)

    payload = _definition_to_mapping(item)
    return _clean_string(payload.get("id") or payload.get("key"))


def _definition_aliases(item: Any) -> Tuple[str, ...]:
    aliases = getattr(item, "aliases", None)

    if aliases is None:
        payload = _definition_to_mapping(item)
        aliases = payload.get("aliases")

    if isinstance(aliases, str):
        aliases = (aliases,)

    if not isinstance(aliases, Sequence) or isinstance(aliases, (bytes, bytearray)):
        return tuple()

    result: List[str] = []
    seen = set()

    for alias in aliases:
        clean = _clean_string(alias)
        normalized = _normalize_lookup_key(clean)
        if not normalized or normalized in seen:
            continue
        seen.add(normalized)
        result.append(clean)

    return tuple(result)


def _definition_sequence(item: Any, field_name: str) -> Tuple[Any, ...]:
    value = getattr(item, field_name, None)

    if value is None:
        value = _definition_to_mapping(item).get(field_name)

    if value is None:
        return tuple()
    if isinstance(value, str):
        return (value,)
    if isinstance(value, Sequence) and not isinstance(value, (bytes, bytearray)):
        return tuple(value)
    return tuple()


def _definition_mapping(item: Any, field_name: str) -> Dict[str, Any]:
    value = getattr(item, field_name, None)

    if not isinstance(value, Mapping):
        value = _definition_to_mapping(item).get(field_name)

    return dict(value) if isinstance(value, Mapping) else {}


def _definition_to_mapping(item: Any) -> Dict[str, Any]:
    if isinstance(item, Mapping):
        return dict(item)

    to_dict = getattr(item, "to_dict", None)
    if callable(to_dict):
        attempts = (
            {"include_extra": True, "include_inactive": True},
            {"include_extra": True},
            {},
        )
        for kwargs in attempts:
            try:
                payload = to_dict(**kwargs)
            except TypeError:
                continue
            except Exception:
                break

            if isinstance(payload, Mapping):
                return dict(payload)

    raw_dict = getattr(item, "__dict__", None)
    if isinstance(raw_dict, Mapping):
        return dict(raw_dict)

    return {}


def _normalize_lookup_key(value: Any) -> str:
    return _clean_string(value).casefold()


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


def get_definition_registry_cache_info() -> Dict[str, Any]:
    lru_info = _cache_info_to_dict(_get_definition_registry_cached.cache_info())
    with _LAST_KNOWN_GOOD_LOCK:
        last_known_good_count = len(_LAST_KNOWN_GOOD)

    return {
        "lru": lru_info,
        "last_known_good_count": last_known_good_count,
    }


def clear_definition_registry_cache(
    *,
    clear_last_known_good: bool = False,
) -> Dict[str, Any]:
    with _REGISTRY_BUILD_LOCK:
        before = get_definition_registry_cache_info()
        _get_definition_registry_cached.cache_clear()

        cleared_last_known_good = 0
        if clear_last_known_good:
            with _LAST_KNOWN_GOOD_LOCK:
                cleared_last_known_good = len(_LAST_KNOWN_GOOD)
                _LAST_KNOWN_GOOD.clear()

        after = get_definition_registry_cache_info()

    return {
        "ok": True,
        "status": "cleared",
        "component": "library.definitions.registry",
        "clear_last_known_good": clear_last_known_good,
        "cleared_last_known_good": cleared_last_known_good,
        "before": before,
        "after": after,
    }


def clear_last_known_good_definition_registry_cache() -> Dict[str, Any]:
    with _LAST_KNOWN_GOOD_LOCK:
        before = len(_LAST_KNOWN_GOOD)
        _LAST_KNOWN_GOOD.clear()

    return {
        "ok": True,
        "status": "cleared",
        "component": "library.definitions.registry.last_known_good",
        "before": before,
        "after": 0,
    }


def clear_definition_caches(
    *,
    clear_last_known_good: bool = False,
) -> Dict[str, Any]:
    return clear_definition_registry_cache(
        clear_last_known_good=clear_last_known_good,
    )


def clear_definitions_caches(
    *,
    clear_last_known_good: bool = False,
) -> Dict[str, Any]:
    return clear_definition_registry_cache(
        clear_last_known_good=clear_last_known_good,
    )


def clear_cache(
    *,
    clear_last_known_good: bool = False,
) -> Dict[str, Any]:
    return clear_definition_registry_cache(
        clear_last_known_good=clear_last_known_good,
    )


def _id_set(items: Sequence[Any]) -> set[str]:
    return {
        _definition_identifier(item)
        for item in items or ()
        if _definition_identifier(item)
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


def _as_int(
    value: Any,
    *,
    default: int,
    minimum: Optional[int] = None,
    maximum: Optional[int] = None,
) -> int:
    try:
        parsed = int(value)
    except (TypeError, ValueError):
        parsed = int(default)

    if minimum is not None and parsed < minimum:
        parsed = minimum
    if maximum is not None and parsed > maximum:
        parsed = maximum

    return parsed


def _deduplicate_strings(values: Iterable[Any]) -> List[str]:
    result: List[str] = []
    seen = set()

    for value in values or ():
        clean = _clean_string(value)
        if not clean or clean in seen:
            continue
        seen.add(clean)
        result.append(clean)

    return result


def _hash_text(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


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