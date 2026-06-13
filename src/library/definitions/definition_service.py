# services/vectoplan-library/src/library/definitions/definition_service.py
"""
Service facade for VECTOPLAN Library Definitions.

This module is the public service layer above definition_registry.py.

Responsibilities:
- provide create-flow payloads for /api/v1/vplib/create/options
- expose stable lookup helpers for validators, scanners and read-models
- resolve family profiles and variant profiles from taxonomy/object context
- build UI-ready variant profile payloads for the future variant drawer
- validate variant values against variable definitions and profile rules
- provide robust health, summary and cache-clear APIs

Design constraints:
- no Flask dependency
- no filesystem access outside the registry
- no package scan execution
- safe to import while JSON files are still being created
- cached service instance

Important cache rule:
- lru_cache must receive only hashable arguments.
- DefinitionServiceOptions contains mutable metadata, so cached functions must
  use only options.cache_key(), never the options object itself.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from functools import lru_cache
from pathlib import Path
from typing import Any, Dict, List, Mapping, Optional, Sequence, Tuple

from .definition_models import (
    DEFINITION_DEFAULT_VERSION,
    DEFINITION_SCHEMA_VERSION,
    VariableDefinition,
    VariantProfileDefinition,
)
from .definition_registry import (
    DEFINITION_REGISTRY_VERSION,
    DefinitionRegistry,
    clear_definition_registry_cache,
    get_definition_registry,
)


DEFINITION_SERVICE_VERSION = "0.1.1"

_SERVICE_CACHE_KEY_LENGTH = 10

_LOGGER = logging.getLogger(__name__)


@dataclass(frozen=True)
class DefinitionServiceOptions:
    """
    Options for the definitions service facade.
    """

    definitions_root: Optional[Any] = None
    definitions_version: str = DEFINITION_DEFAULT_VERSION
    schema_version: str = DEFINITION_SCHEMA_VERSION
    include_inactive: bool = False
    include_internal: bool = False
    strict_references: bool = True
    allow_missing_datasets: bool = True
    allow_empty_datasets: bool = True
    use_config_fallback: bool = True
    language: str = "de"
    metadata: Dict[str, Any] = field(default_factory=dict)

    @classmethod
    def from_mapping(cls, data: Optional[Mapping[str, Any]]) -> "DefinitionServiceOptions":
        if not data:
            return cls()

        return cls(
            definitions_root=data.get("definitions_root") or data.get("root"),
            definitions_version=_clean_string(
                data.get("definitions_version") or data.get("version"),
                default=DEFINITION_DEFAULT_VERSION,
            ),
            schema_version=_clean_string(
                data.get("schema_version"),
                default=DEFINITION_SCHEMA_VERSION,
            ),
            include_inactive=_as_bool(data.get("include_inactive"), default=False),
            include_internal=_as_bool(data.get("include_internal"), default=False),
            strict_references=_as_bool(data.get("strict_references"), default=True),
            allow_missing_datasets=_as_bool(data.get("allow_missing_datasets"), default=True),
            allow_empty_datasets=_as_bool(data.get("allow_empty_datasets"), default=True),
            use_config_fallback=_as_bool(data.get("use_config_fallback"), default=True),
            language=_clean_string(data.get("language"), default="de"),
            metadata=_copy_mapping(data.get("metadata")),
        )

    def cache_key(self) -> Tuple[Any, ...]:
        """
        Return a stable, hashable cache key.

        `metadata` is intentionally excluded because it is diagnostic-only and
        does not change loaded definitions.
        """
        return (
            _root_cache_value(self.definitions_root),
            self.definitions_version,
            self.schema_version,
            bool(self.include_inactive),
            bool(self.include_internal),
            bool(self.strict_references),
            bool(self.allow_missing_datasets),
            bool(self.allow_empty_datasets),
            bool(self.use_config_fallback),
            self.language,
        )

    def to_dict(self) -> Dict[str, Any]:
        return {
            "definitions_root": str(self.definitions_root) if self.definitions_root else None,
            "definitions_version": self.definitions_version,
            "schema_version": self.schema_version,
            "include_inactive": self.include_inactive,
            "include_internal": self.include_internal,
            "strict_references": self.strict_references,
            "allow_missing_datasets": self.allow_missing_datasets,
            "allow_empty_datasets": self.allow_empty_datasets,
            "use_config_fallback": self.use_config_fallback,
            "language": self.language,
            "metadata": dict(self.metadata),
        }


class DefinitionService:
    """
    Service facade around DefinitionRegistry.

    The service deliberately returns dictionaries for most public methods because
    routes, validators and frontend option builders need JSON-ready payloads.
    """

    def __init__(self, options: Optional[DefinitionServiceOptions] = None) -> None:
        self.options = options or DefinitionServiceOptions()

    def get_registry(self, *, force_reload: bool = False) -> DefinitionRegistry:
        return get_definition_registry(
            definitions_root=self.options.definitions_root,
            definitions_version=self.options.definitions_version,
            force_reload=force_reload,
            strict_references=self.options.strict_references,
            allow_missing_datasets=self.options.allow_missing_datasets,
            allow_empty_datasets=self.options.allow_empty_datasets,
            use_config_fallback=self.options.use_config_fallback,
        )

    def health(self, *, force_reload: bool = False) -> Dict[str, Any]:
        try:
            registry = self.get_registry(force_reload=force_reload)
            registry_health = registry.health()

            healthy = bool(registry_health.get("healthy") or registry_health.get("ok"))

            return {
                "ok": healthy,
                "healthy": healthy,
                "status": "healthy" if healthy else "degraded",
                "component": "library.definitions.service",
                "version": DEFINITION_SERVICE_VERSION,
                "registry_version": DEFINITION_REGISTRY_VERSION,
                "definitions_version": self.options.definitions_version,
                "schema_version": self.options.schema_version,
                "options": self.options.to_dict(),
                "registry": registry_health,
            }
        except Exception as exc:
            _LOGGER.exception("Definitions service health failed")
            return {
                "ok": False,
                "healthy": False,
                "status": "unavailable",
                "component": "library.definitions.service",
                "version": DEFINITION_SERVICE_VERSION,
                "definitions_version": self.options.definitions_version,
                "schema_version": self.options.schema_version,
                "options": self.options.to_dict(),
                "error": _format_exception(exc),
            }

    def summary(self, *, force_reload: bool = False) -> Dict[str, Any]:
        try:
            registry = self.get_registry(force_reload=force_reload)
            payload = registry.summary()
            payload.update(
                {
                    "component": "library.definitions.service",
                    "service_version": DEFINITION_SERVICE_VERSION,
                    "options": self.options.to_dict(),
                }
            )
            return payload
        except Exception as exc:
            return {
                "ok": False,
                "healthy": False,
                "status": "unavailable",
                "component": "library.definitions.service",
                "service_version": DEFINITION_SERVICE_VERSION,
                "error": _format_exception(exc),
            }

    def payload(
        self,
        *,
        include_inactive: Optional[bool] = None,
        include_internal: Optional[bool] = None,
        include_extra: bool = True,
        force_reload: bool = False,
        language: Optional[str] = None,
    ) -> Dict[str, Any]:
        registry = self.get_registry(force_reload=force_reload)
        return registry.to_dict(
            include_inactive=self.options.include_inactive
            if include_inactive is None
            else include_inactive,
            include_internal=self.options.include_internal
            if include_internal is None
            else include_internal,
            include_extra=include_extra,
            language=language or self.options.language,
        )

    def create_options(
        self,
        *,
        include_inactive: Optional[bool] = None,
        include_internal: bool = False,
        force_reload: bool = False,
        language: Optional[str] = None,
    ) -> Dict[str, Any]:
        """
        UI-ready options payload for /create.

        This method intentionally includes both full definitions and compact
        option arrays so frontend code can start simple and later become more
        optimized without changing the route contract.
        """
        registry = self.get_registry(force_reload=force_reload)
        clean_include_inactive = (
            self.options.include_inactive
            if include_inactive is None
            else include_inactive
        )
        clean_language = language or self.options.language

        full_payload = registry.to_dict(
            include_inactive=clean_include_inactive,
            include_internal=include_internal,
            include_extra=True,
            language=clean_language,
        )

        return {
            "ok": full_payload.get("ok", True),
            "healthy": full_payload.get("healthy", True),
            "status": full_payload.get("status", "ok"),
            "component": "library.definitions.create_options",
            "definitions_version": full_payload.get("definitions_version"),
            "schema_version": full_payload.get("schema_version"),
            "counts": full_payload.get("counts", {}),
            "options": {
                "object_kinds": self._options_from_items(
                    registry.list_object_kinds(include_inactive=clean_include_inactive),
                    language=clean_language,
                ),
                "family_profiles": self._options_from_items(
                    registry.list_family_profiles(include_inactive=clean_include_inactive),
                    language=clean_language,
                ),
                "variant_profiles": self._options_from_items(
                    registry.list_variant_profiles(include_inactive=clean_include_inactive),
                    language=clean_language,
                ),
                "materials": self._options_from_items(
                    registry.list_materials(include_inactive=clean_include_inactive),
                    language=clean_language,
                ),
                "document_types": self._options_from_items(
                    registry.list_document_types(include_inactive=clean_include_inactive),
                    language=clean_language,
                ),
                "units": self._options_from_items(
                    registry.list_units(include_inactive=clean_include_inactive),
                    language=clean_language,
                ),
            },
            "definitions": {
                "object_kinds": full_payload.get("object_kinds", []),
                "family_profiles": full_payload.get("family_profiles", []),
                "variant_profiles": full_payload.get("variant_profiles", []),
                "variables": full_payload.get("variables", []),
                "units": full_payload.get("units", []),
                "materials": full_payload.get("materials", []),
                "document_types": full_payload.get("document_types", []),
                "profile_bindings": full_payload.get("profile_bindings", []),
            },
            "warnings": full_payload.get("warnings", []),
            "errors": full_payload.get("errors", []),
        }

    def resolve_family_profile_for_context(
        self,
        *,
        domain: Optional[str] = None,
        category: Optional[str] = None,
        subcategory: Optional[str] = None,
        object_kind: Optional[str] = None,
        family_profile_id: Optional[str] = None,
        force_reload: bool = False,
    ) -> Dict[str, Any]:
        registry = self.get_registry(force_reload=force_reload)
        return registry.resolve_family_profile_for_context(
            domain=domain,
            category=category,
            subcategory=subcategory,
            object_kind=object_kind,
            family_profile_id=family_profile_id,
        )

    def resolve_variant_profile_for_context(
        self,
        *,
        domain: Optional[str] = None,
        category: Optional[str] = None,
        subcategory: Optional[str] = None,
        object_kind: Optional[str] = None,
        family_profile_id: Optional[str] = None,
        variant_profile_id: Optional[str] = None,
        force_reload: bool = False,
        include_variables: bool = True,
        include_inactive: Optional[bool] = None,
        language: Optional[str] = None,
    ) -> Dict[str, Any]:
        registry = self.get_registry(force_reload=force_reload)
        result = registry.resolve_variant_profile_for_context(
            domain=domain,
            category=category,
            subcategory=subcategory,
            object_kind=object_kind,
            family_profile_id=family_profile_id,
            variant_profile_id=variant_profile_id,
        )

        if not result.get("ok"):
            return result

        resolved_variant_profile_id = _clean_string(result.get("variant_profile_id"))
        if not include_variables or not resolved_variant_profile_id:
            return result

        profile_payload = registry.build_variant_profile_payload(
            resolved_variant_profile_id,
            include_inactive=self.options.include_inactive
            if include_inactive is None
            else include_inactive,
            include_extra=True,
            language=language or self.options.language,
        )

        result["profile_payload"] = profile_payload
        result["variables"] = profile_payload.get("variables", {})
        return result

    def get_variant_profile(
        self,
        profile_id: str,
        *,
        include_variables: bool = True,
        include_inactive: Optional[bool] = None,
        force_reload: bool = False,
        language: Optional[str] = None,
    ) -> Dict[str, Any]:
        registry = self.get_registry(force_reload=force_reload)
        clean_profile_id = _clean_string(profile_id)

        if include_variables:
            return registry.build_variant_profile_payload(
                clean_profile_id,
                include_inactive=self.options.include_inactive
                if include_inactive is None
                else include_inactive,
                include_extra=True,
                language=language or self.options.language,
            )

        variant_profile = registry.get_variant_profile(clean_profile_id)
        if not variant_profile:
            return _not_found("variant_profile", clean_profile_id)

        return {
            "ok": True,
            "status": "ok",
            "variant_profile_id": variant_profile.id,
            "variant_profile": variant_profile.to_dict(
                include_inactive=True,
                include_extra=True,
                language=language or self.options.language,
            ),
        }

    def get_family_profile(
        self,
        profile_id: str,
        *,
        force_reload: bool = False,
        language: Optional[str] = None,
    ) -> Dict[str, Any]:
        registry = self.get_registry(force_reload=force_reload)
        family_profile = registry.get_family_profile(profile_id)

        if not family_profile:
            return _not_found("family_profile", profile_id)

        return {
            "ok": True,
            "status": "ok",
            "family_profile_id": family_profile.id,
            "family_profile": family_profile.to_dict(
                include_inactive=True,
                include_extra=True,
                language=language or self.options.language,
            ),
        }

    def get_variable(
        self,
        variable_key: str,
        *,
        force_reload: bool = False,
        language: Optional[str] = None,
    ) -> Dict[str, Any]:
        registry = self.get_registry(force_reload=force_reload)
        variable = registry.get_variable(variable_key)

        if not variable:
            return _not_found("variable", variable_key)

        return {
            "ok": True,
            "status": "ok",
            "variable_key": variable.key,
            "variable": variable.to_dict(
                include_inactive=True,
                include_extra=True,
                language=language or self.options.language,
            ),
        }

    def get_unit(
        self,
        unit_id: str,
        *,
        force_reload: bool = False,
        language: Optional[str] = None,
    ) -> Dict[str, Any]:
        registry = self.get_registry(force_reload=force_reload)
        unit = registry.get_unit(unit_id)

        if not unit:
            return _not_found("unit", unit_id)

        return {
            "ok": True,
            "status": "ok",
            "unit_id": unit.id,
            "unit": unit.to_dict(
                include_inactive=True,
                include_extra=True,
                language=language or self.options.language,
            ),
        }

    def get_material(
        self,
        material_id: str,
        *,
        force_reload: bool = False,
        language: Optional[str] = None,
    ) -> Dict[str, Any]:
        registry = self.get_registry(force_reload=force_reload)
        material = registry.get_material(material_id)

        if not material:
            return _not_found("material", material_id)

        return {
            "ok": True,
            "status": "ok",
            "material_id": material.id,
            "material": material.to_dict(
                include_inactive=True,
                include_extra=True,
                language=language or self.options.language,
            ),
        }

    def get_document_type(
        self,
        document_type_id: str,
        *,
        force_reload: bool = False,
        language: Optional[str] = None,
    ) -> Dict[str, Any]:
        registry = self.get_registry(force_reload=force_reload)
        document_type = registry.get_document_type(document_type_id)

        if not document_type:
            return _not_found("document_type", document_type_id)

        return {
            "ok": True,
            "status": "ok",
            "document_type_id": document_type.id,
            "document_type": document_type.to_dict(
                include_inactive=True,
                include_extra=True,
                language=language or self.options.language,
            ),
        }

    def validate_variant_values(
        self,
        *,
        variant_profile_id: str,
        values: Optional[Mapping[str, Any]] = None,
        documents: Optional[Sequence[Mapping[str, Any]]] = None,
        manufacturer_reference: Optional[Mapping[str, Any]] = None,
        force_reload: bool = False,
    ) -> Dict[str, Any]:
        """
        Validate a concrete variant values object against a variant profile.

        This is intentionally not a full package validator. It is the focused
        validator needed by the variant drawer, draft endpoint and create-flow.
        """
        registry = self.get_registry(force_reload=force_reload)
        clean_profile_id = _clean_string(variant_profile_id)

        variant_profile = registry.get_variant_profile(clean_profile_id)
        if not variant_profile:
            return {
                "ok": False,
                "valid": False,
                "status": "invalid",
                "variant_profile_id": clean_profile_id,
                "errors": [f"Unknown variant_profile_id: {clean_profile_id}"],
                "warnings": [],
            }

        values_dict = _copy_mapping(values)
        errors: List[str] = []
        warnings: List[str] = []

        allowed_fields = set(variant_profile.all_field_keys)
        required_fields = set(variant_profile.required_fields)

        for field_key in sorted(required_fields):
            if field_key not in values_dict or values_dict.get(field_key) in (None, ""):
                errors.append(f"Missing required variant field: {field_key}")

        for field_key in sorted(values_dict.keys()):
            if field_key not in allowed_fields:
                errors.append(
                    f"Field {field_key!r} is not allowed for variant profile "
                    f"{clean_profile_id!r}"
                )
                continue

            variable = registry.get_variable(field_key)
            if not variable:
                errors.append(f"Unknown variable definition: {field_key}")
                continue

            field_errors, field_warnings = self._validate_value_against_variable(
                field_key,
                values_dict.get(field_key),
                variable,
                registry=registry,
            )
            errors.extend(field_errors)
            warnings.extend(field_warnings)

        document_errors, document_warnings = self._validate_documents(
            documents or [],
            variant_profile=variant_profile,
            registry=registry,
        )
        errors.extend(document_errors)
        warnings.extend(document_warnings)

        manufacturer_errors, manufacturer_warnings = self._validate_manufacturer_reference(
            manufacturer_reference or {},
            variant_profile=variant_profile,
        )
        errors.extend(manufacturer_errors)
        warnings.extend(manufacturer_warnings)

        valid = not errors

        return {
            "ok": valid,
            "valid": valid,
            "status": "valid" if valid else "invalid",
            "variant_profile_id": clean_profile_id,
            "required_fields": sorted(required_fields),
            "allowed_fields": sorted(allowed_fields),
            "errors": errors,
            "warnings": warnings,
        }

    def build_empty_variant_values(
        self,
        *,
        variant_profile_id: str,
        force_reload: bool = False,
    ) -> Dict[str, Any]:
        """
        Build an empty/default values object for a new variant.
        """
        registry = self.get_registry(force_reload=force_reload)
        clean_profile_id = _clean_string(variant_profile_id)
        variant_profile = registry.get_variant_profile(clean_profile_id)

        if not variant_profile:
            return {
                "ok": False,
                "status": "not_found",
                "variant_profile_id": clean_profile_id,
                "error": f"Unknown variant_profile_id: {clean_profile_id}",
            }

        values: Dict[str, Any] = {}

        for field_key in variant_profile.all_field_keys:
            variable = registry.get_variable(field_key)
            if not variable:
                continue

            if field_key in variant_profile.default_values:
                values[field_key] = variant_profile.default_values[field_key]
            elif variable.default_value is not None:
                values[field_key] = variable.default_value
            else:
                values[field_key] = _empty_value_for_variable(variable)

        return {
            "ok": True,
            "status": "ok",
            "variant_profile_id": clean_profile_id,
            "values": values,
        }

    def _validate_value_against_variable(
        self,
        field_key: str,
        value: Any,
        variable: VariableDefinition,
        *,
        registry: DefinitionRegistry,
    ) -> Tuple[List[str], List[str]]:
        errors: List[str] = []
        warnings: List[str] = []

        if value in (None, ""):
            return errors, warnings

        value_type = variable.value_type

        if value_type in {"number", "money"}:
            if not _is_number(value):
                errors.append(f"Field {field_key!r} must be numeric")
        elif value_type == "integer":
            if not _is_integer(value):
                errors.append(f"Field {field_key!r} must be an integer")
        elif value_type == "boolean":
            if not isinstance(value, bool):
                errors.append(f"Field {field_key!r} must be boolean")
        elif value_type in {"string", "text", "url", "date"}:
            if not isinstance(value, str):
                errors.append(f"Field {field_key!r} must be text")
        elif value_type == "enum":
            allowed_values = _option_values(variable.options)
            if allowed_values and value not in allowed_values:
                errors.append(
                    f"Field {field_key!r} has invalid value {value!r}; "
                    f"allowed: {sorted(allowed_values)}"
                )
        elif value_type == "multi_enum":
            if not isinstance(value, list):
                errors.append(f"Field {field_key!r} must be a list")
            else:
                allowed_values = _option_values(variable.options)
                invalid_values = [
                    item for item in value
                    if allowed_values and item not in allowed_values
                ]
                if invalid_values:
                    errors.append(
                        f"Field {field_key!r} contains invalid values: {invalid_values}"
                    )
        elif value_type in {"array", "document_list"}:
            if not isinstance(value, list):
                errors.append(f"Field {field_key!r} must be a list")
        elif value_type == "object":
            if not isinstance(value, Mapping):
                errors.append(f"Field {field_key!r} must be an object")

        validation = variable.validation or {}
        if validation and _is_number(value):
            numeric_value = float(str(value).strip().replace(",", "."))

            minimum = validation.get("min")
            maximum = validation.get("max")

            if minimum is not None and numeric_value < float(minimum):
                errors.append(f"Field {field_key!r} must be >= {minimum}")
            if maximum is not None and numeric_value > float(maximum):
                errors.append(f"Field {field_key!r} must be <= {maximum}")

        if variable.unit:
            unit = registry.get_unit(variable.unit)
            if not unit:
                errors.append(
                    f"Field {field_key!r} references unknown unit {variable.unit!r}"
                )

        return errors, warnings

    def _validate_documents(
        self,
        documents: Sequence[Mapping[str, Any]],
        *,
        variant_profile: VariantProfileDefinition,
        registry: DefinitionRegistry,
    ) -> Tuple[List[str], List[str]]:
        errors: List[str] = []
        warnings: List[str] = []
        allowed_document_types = set(variant_profile.document_types)

        for index, document in enumerate(documents or []):
            if not isinstance(document, Mapping):
                errors.append(f"documents[{index}] must be an object")
                continue

            document_type_id = _clean_string(
                document.get("document_type")
                or document.get("type")
                or document.get("document_type_id")
            )

            if not document_type_id:
                errors.append(f"documents[{index}].document_type is required")
                continue

            if allowed_document_types and document_type_id not in allowed_document_types:
                errors.append(
                    f"Document type {document_type_id!r} is not allowed for "
                    f"variant profile {variant_profile.id!r}"
                )
                continue

            document_type = registry.get_document_type(document_type_id)
            if not document_type:
                errors.append(f"Unknown document type: {document_type_id}")

        return errors, warnings

    def _validate_manufacturer_reference(
        self,
        manufacturer_reference: Mapping[str, Any],
        *,
        variant_profile: VariantProfileDefinition,
    ) -> Tuple[List[str], List[str]]:
        errors: List[str] = []
        warnings: List[str] = []

        mode = _clean_string(variant_profile.manufacturer_mode, default="none")
        has_reference = bool(manufacturer_reference)

        if mode == "none" and has_reference:
            warnings.append(
                f"Variant profile {variant_profile.id!r} does not require manufacturer data; "
                "manufacturer_reference will be treated as optional metadata"
            )

        if mode in {"required", "product_required"}:
            manufacturer_name = _clean_string(
                manufacturer_reference.get("manufacturer_name")
                or manufacturer_reference.get("manufacturer")
                or manufacturer_reference.get("name")
            )
            product_designation = _clean_string(
                manufacturer_reference.get("product_designation")
                or manufacturer_reference.get("designation")
                or manufacturer_reference.get("product")
            )

            if not manufacturer_name:
                errors.append("manufacturer_reference.manufacturer_name is required")
            if not product_designation:
                errors.append("manufacturer_reference.product_designation is required")

        return errors, warnings

    def _options_from_items(
        self,
        items: Sequence[Any],
        *,
        language: str,
    ) -> List[Dict[str, Any]]:
        options: List[Dict[str, Any]] = []

        for item in sorted(
            items or (),
            key=lambda value: (
                getattr(value, "sort_order", 1000),
                getattr(value, "label", ""),
                getattr(value, "id", ""),
            ),
        ):
            to_option = getattr(item, "to_option", None)
            if callable(to_option):
                options.append(to_option(language=language))
            else:
                options.append(
                    {
                        "id": getattr(item, "id", ""),
                        "label": getattr(item, "label", getattr(item, "id", "")),
                    }
                )

        return options


def get_definition_service(
    *,
    definitions_root: Optional[Any] = None,
    definitions_version: str = DEFINITION_DEFAULT_VERSION,
    force_refresh: bool = False,
    **kwargs: Any,
) -> DefinitionService:
    """
    Cached service accessor.

    force_refresh=True clears both service and registry caches.
    """
    if force_refresh:
        clear_definition_service_cache()

    options = DefinitionServiceOptions(
        definitions_root=definitions_root,
        definitions_version=_clean_string(definitions_version, default=DEFINITION_DEFAULT_VERSION),
        schema_version=_clean_string(kwargs.get("schema_version"), default=DEFINITION_SCHEMA_VERSION),
        include_inactive=_as_bool(kwargs.get("include_inactive"), default=False),
        include_internal=_as_bool(kwargs.get("include_internal"), default=False),
        strict_references=_as_bool(kwargs.get("strict_references"), default=True),
        allow_missing_datasets=_as_bool(kwargs.get("allow_missing_datasets"), default=True),
        allow_empty_datasets=_as_bool(kwargs.get("allow_empty_datasets"), default=True),
        use_config_fallback=_as_bool(kwargs.get("use_config_fallback"), default=True),
        language=_clean_string(kwargs.get("language"), default="de"),
        metadata=_copy_mapping(kwargs.get("metadata")),
    )

    return _get_definition_service_cached(options.cache_key())


def get_definitions_service(**kwargs: Any) -> DefinitionService:
    return get_definition_service(**kwargs)


def create_definition_service(**kwargs: Any) -> DefinitionService:
    cleaned_kwargs = dict(kwargs)
    cleaned_kwargs["force_refresh"] = True
    return get_definition_service(**cleaned_kwargs)


def create_definitions_service(**kwargs: Any) -> DefinitionService:
    return create_definition_service(**kwargs)


@lru_cache(maxsize=16)
def _get_definition_service_cached(cache_key: Tuple[Any, ...]) -> DefinitionService:
    """
    Cached service builder.

    Only `cache_key` is accepted here. This avoids lru_cache receiving
    DefinitionServiceOptions, which contains mutable metadata and is therefore
    unsafe as a cached argument.
    """
    options = _options_from_cache_key(cache_key)
    return DefinitionService(options)


def _options_from_cache_key(cache_key: Tuple[Any, ...]) -> DefinitionServiceOptions:
    if not isinstance(cache_key, tuple) or len(cache_key) != _SERVICE_CACHE_KEY_LENGTH:
        raise ValueError(
            "Invalid definition service cache key. "
            f"Expected tuple length {_SERVICE_CACHE_KEY_LENGTH}, got {cache_key!r}"
        )

    (
        definitions_root,
        definitions_version,
        schema_version,
        include_inactive,
        include_internal,
        strict_references,
        allow_missing_datasets,
        allow_empty_datasets,
        use_config_fallback,
        language,
    ) = cache_key

    return DefinitionServiceOptions(
        definitions_root=definitions_root,
        definitions_version=_clean_string(definitions_version, default=DEFINITION_DEFAULT_VERSION),
        schema_version=_clean_string(schema_version, default=DEFINITION_SCHEMA_VERSION),
        include_inactive=bool(include_inactive),
        include_internal=bool(include_internal),
        strict_references=bool(strict_references),
        allow_missing_datasets=bool(allow_missing_datasets),
        allow_empty_datasets=bool(allow_empty_datasets),
        use_config_fallback=bool(use_config_fallback),
        language=_clean_string(language, default="de"),
        metadata={
            "from_cache_key": True,
        },
    )


def get_definitions_health(
    *,
    force_refresh: bool = False,
    force_reload: bool = False,
    **kwargs: Any,
) -> Dict[str, Any]:
    service = get_definition_service(force_refresh=force_refresh, **kwargs)
    return service.health(force_reload=force_reload)


def get_definition_service_health(**kwargs: Any) -> Dict[str, Any]:
    return get_definitions_health(**kwargs)


def get_health(**kwargs: Any) -> Dict[str, Any]:
    return get_definitions_health(**kwargs)


def get_definitions_summary(
    *,
    force_refresh: bool = False,
    force_reload: bool = False,
    **kwargs: Any,
) -> Dict[str, Any]:
    service = get_definition_service(force_refresh=force_refresh, **kwargs)
    return service.summary(force_reload=force_reload)


def get_definition_summary(**kwargs: Any) -> Dict[str, Any]:
    return get_definitions_summary(**kwargs)


def get_summary(**kwargs: Any) -> Dict[str, Any]:
    return get_definitions_summary(**kwargs)


def get_definitions_payload(
    *,
    include_inactive: bool = False,
    include_internal: bool = False,
    force_refresh: bool = False,
    force_reload: bool = False,
    **kwargs: Any,
) -> Dict[str, Any]:
    service = get_definition_service(force_refresh=force_refresh, **kwargs)
    return service.payload(
        include_inactive=include_inactive,
        include_internal=include_internal,
        force_reload=force_reload,
    )


def get_create_definitions_payload(**kwargs: Any) -> Dict[str, Any]:
    return get_create_definition_options(**kwargs)


def get_create_definition_options(
    *,
    include_inactive: bool = False,
    include_internal: bool = False,
    force_refresh: bool = False,
    force_reload: bool = False,
    **kwargs: Any,
) -> Dict[str, Any]:
    service = get_definition_service(force_refresh=force_refresh, **kwargs)
    return service.create_options(
        include_inactive=include_inactive,
        include_internal=include_internal,
        force_reload=force_reload,
    )


def get_definition_options(**kwargs: Any) -> Dict[str, Any]:
    return get_create_definition_options(**kwargs)


def get_options_payload(**kwargs: Any) -> Dict[str, Any]:
    return get_create_definition_options(**kwargs)


def get_options(**kwargs: Any) -> Dict[str, Any]:
    return get_create_definition_options(**kwargs)


def resolve_variant_profile_for_context(
    *,
    domain: Optional[str] = None,
    category: Optional[str] = None,
    subcategory: Optional[str] = None,
    object_kind: Optional[str] = None,
    family_profile_id: Optional[str] = None,
    variant_profile_id: Optional[str] = None,
    force_refresh: bool = False,
    force_reload: bool = False,
    **kwargs: Any,
) -> Dict[str, Any]:
    service = get_definition_service(force_refresh=force_refresh, **kwargs)
    return service.resolve_variant_profile_for_context(
        domain=domain,
        category=category,
        subcategory=subcategory,
        object_kind=object_kind,
        family_profile_id=family_profile_id,
        variant_profile_id=variant_profile_id,
        force_reload=force_reload,
    )


def resolve_variant_profile(**kwargs: Any) -> Dict[str, Any]:
    return resolve_variant_profile_for_context(**kwargs)


def get_variant_profile_for_context(**kwargs: Any) -> Dict[str, Any]:
    return resolve_variant_profile_for_context(**kwargs)


def find_variant_profile(**kwargs: Any) -> Dict[str, Any]:
    return resolve_variant_profile_for_context(**kwargs)


def resolve_family_profile_for_context(
    *,
    domain: Optional[str] = None,
    category: Optional[str] = None,
    subcategory: Optional[str] = None,
    object_kind: Optional[str] = None,
    family_profile_id: Optional[str] = None,
    force_refresh: bool = False,
    force_reload: bool = False,
    **kwargs: Any,
) -> Dict[str, Any]:
    service = get_definition_service(force_refresh=force_refresh, **kwargs)
    return service.resolve_family_profile_for_context(
        domain=domain,
        category=category,
        subcategory=subcategory,
        object_kind=object_kind,
        family_profile_id=family_profile_id,
        force_reload=force_reload,
    )


def get_variant_profile(
    profile_id: str,
    *,
    force_refresh: bool = False,
    force_reload: bool = False,
    **kwargs: Any,
) -> Dict[str, Any]:
    service = get_definition_service(force_refresh=force_refresh, **kwargs)
    return service.get_variant_profile(
        profile_id,
        force_reload=force_reload,
    )


def get_variant_profile_definition(profile_id: str, **kwargs: Any) -> Dict[str, Any]:
    return get_variant_profile(profile_id, **kwargs)


def find_variant_profile_by_id(profile_id: str, **kwargs: Any) -> Dict[str, Any]:
    return get_variant_profile(profile_id, **kwargs)


def get_family_profile(
    profile_id: str,
    *,
    force_refresh: bool = False,
    force_reload: bool = False,
    **kwargs: Any,
) -> Dict[str, Any]:
    service = get_definition_service(force_refresh=force_refresh, **kwargs)
    return service.get_family_profile(
        profile_id,
        force_reload=force_reload,
    )


def get_family_profile_definition(profile_id: str, **kwargs: Any) -> Dict[str, Any]:
    return get_family_profile(profile_id, **kwargs)


def find_family_profile_by_id(profile_id: str, **kwargs: Any) -> Dict[str, Any]:
    return get_family_profile(profile_id, **kwargs)


def get_variable(
    variable_key: str,
    *,
    force_refresh: bool = False,
    force_reload: bool = False,
    **kwargs: Any,
) -> Dict[str, Any]:
    service = get_definition_service(force_refresh=force_refresh, **kwargs)
    return service.get_variable(
        variable_key,
        force_reload=force_reload,
    )


def get_variable_definition(variable_key: str, **kwargs: Any) -> Dict[str, Any]:
    return get_variable(variable_key, **kwargs)


def find_variable_by_key(variable_key: str, **kwargs: Any) -> Dict[str, Any]:
    return get_variable(variable_key, **kwargs)


def get_unit(
    unit_id: str,
    *,
    force_refresh: bool = False,
    force_reload: bool = False,
    **kwargs: Any,
) -> Dict[str, Any]:
    service = get_definition_service(force_refresh=force_refresh, **kwargs)
    return service.get_unit(
        unit_id,
        force_reload=force_reload,
    )


def get_unit_definition(unit_id: str, **kwargs: Any) -> Dict[str, Any]:
    return get_unit(unit_id, **kwargs)


def find_unit_by_id(unit_id: str, **kwargs: Any) -> Dict[str, Any]:
    return get_unit(unit_id, **kwargs)


def get_material(
    material_id: str,
    *,
    force_refresh: bool = False,
    force_reload: bool = False,
    **kwargs: Any,
) -> Dict[str, Any]:
    service = get_definition_service(force_refresh=force_refresh, **kwargs)
    return service.get_material(
        material_id,
        force_reload=force_reload,
    )


def get_material_definition(material_id: str, **kwargs: Any) -> Dict[str, Any]:
    return get_material(material_id, **kwargs)


def find_material_by_id(material_id: str, **kwargs: Any) -> Dict[str, Any]:
    return get_material(material_id, **kwargs)


def get_document_type(
    document_type_id: str,
    *,
    force_refresh: bool = False,
    force_reload: bool = False,
    **kwargs: Any,
) -> Dict[str, Any]:
    service = get_definition_service(force_refresh=force_refresh, **kwargs)
    return service.get_document_type(
        document_type_id,
        force_reload=force_reload,
    )


def get_document_type_definition(document_type_id: str, **kwargs: Any) -> Dict[str, Any]:
    return get_document_type(document_type_id, **kwargs)


def find_document_type_by_id(document_type_id: str, **kwargs: Any) -> Dict[str, Any]:
    return get_document_type(document_type_id, **kwargs)


def validate_variant_values(
    *,
    variant_profile_id: str,
    values: Optional[Mapping[str, Any]] = None,
    documents: Optional[Sequence[Mapping[str, Any]]] = None,
    manufacturer_reference: Optional[Mapping[str, Any]] = None,
    force_refresh: bool = False,
    force_reload: bool = False,
    **kwargs: Any,
) -> Dict[str, Any]:
    service = get_definition_service(force_refresh=force_refresh, **kwargs)
    return service.validate_variant_values(
        variant_profile_id=variant_profile_id,
        values=values,
        documents=documents,
        manufacturer_reference=manufacturer_reference,
        force_reload=force_reload,
    )


def build_empty_variant_values(
    *,
    variant_profile_id: str,
    force_refresh: bool = False,
    force_reload: bool = False,
    **kwargs: Any,
) -> Dict[str, Any]:
    service = get_definition_service(force_refresh=force_refresh, **kwargs)
    return service.build_empty_variant_values(
        variant_profile_id=variant_profile_id,
        force_reload=force_reload,
    )


def clear_definition_service_cache() -> Dict[str, Any]:
    before = _cache_info_to_dict(_get_definition_service_cached.cache_info())
    _get_definition_service_cached.cache_clear()
    registry_result = clear_definition_registry_cache()
    after = _cache_info_to_dict(_get_definition_service_cached.cache_info())

    return {
        "ok": True,
        "status": "cleared",
        "component": "library.definitions.service",
        "before": before,
        "after": after,
        "registry": registry_result,
    }


def clear_definition_caches() -> Dict[str, Any]:
    return clear_definition_service_cache()


def clear_definitions_caches() -> Dict[str, Any]:
    return clear_definition_service_cache()


def clear_definition_cache() -> Dict[str, Any]:
    return clear_definition_service_cache()


def clear_caches() -> Dict[str, Any]:
    return clear_definition_service_cache()


def clear_cache() -> Dict[str, Any]:
    return clear_definition_service_cache()


def _not_found(kind: str, identifier: Any) -> Dict[str, Any]:
    clean_identifier = _clean_string(identifier)
    return {
        "ok": False,
        "status": "not_found",
        "kind": kind,
        "id": clean_identifier,
        "error": f"Unknown {kind}: {clean_identifier}",
    }


def _empty_value_for_variable(variable: VariableDefinition) -> Any:
    value_type = variable.value_type

    if value_type in {"number", "integer", "money"}:
        return None
    if value_type == "boolean":
        return False
    if value_type in {"array", "multi_enum", "document_list"}:
        return []
    if value_type == "object":
        return {}
    return ""


def _option_values(options: Sequence[Mapping[str, Any]]) -> set[Any]:
    values = set()

    for option in options or ():
        if not isinstance(option, Mapping):
            continue
        if "value" in option:
            values.add(option.get("value"))
        elif "id" in option:
            values.add(option.get("id"))

    return values


def _is_number(value: Any) -> bool:
    if isinstance(value, bool):
        return False
    if isinstance(value, (int, float)):
        return True
    if isinstance(value, str):
        clean = value.strip().replace(",", ".")
        if not clean:
            return False
        try:
            float(clean)
            return True
        except ValueError:
            return False
    return False


def _is_integer(value: Any) -> bool:
    if isinstance(value, bool):
        return False
    if isinstance(value, int):
        return True
    if isinstance(value, str):
        clean = value.strip()
        if not clean:
            return False
        try:
            int(clean)
            return True
        except ValueError:
            return False
    return False


def _root_cache_value(value: Optional[Any]) -> Optional[str]:
    if value is None:
        return None

    try:
        path = Path(str(value)).expanduser()
        return str(path.resolve())
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


def _format_exception(exc: BaseException) -> str:
    return f"{exc.__class__.__name__}: {exc}"


def _cache_info_to_dict(info: Any) -> Dict[str, Any]:
    return {
        "hits": getattr(info, "hits", None),
        "misses": getattr(info, "misses", None),
        "maxsize": getattr(info, "maxsize", None),
        "currsize": getattr(info, "currsize", None),
    }