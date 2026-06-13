# services/vectoplan-library/src/library/definitions/__init__.py
"""
VECTOPLAN Library Definitions Package.

This package is the backend-owned definition layer for object kinds, family
profiles, variant profiles, variables, units, materials, document types and
profile bindings.

Design goals:
- no heavy work during import
- no filesystem scans during import
- no JSON loading during import
- lazy imports for all child modules
- robust fallback health while this package is still being built file by file
- cache-aware public accessors
- stable facade for config, routes, services, validators and create-flow code

Concrete implementation lives in:
- definition_models.py
- definition_registry.py
- definition_service.py
- data/*.json

Important:
The route service imports `src.library.definitions`, not the deeper
definition_service module directly. Therefore this __init__.py must expose the
public facade functions required by route services and later Create integration.
"""

from __future__ import annotations

import importlib
import inspect
import logging
from functools import lru_cache
from types import ModuleType
from typing import Any, Callable, Dict, List, Mapping, Optional, Sequence, Tuple


DEFINITIONS_COMPONENT_NAME = "library.definitions"
DEFINITIONS_COMPONENT_VERSION = "0.1.1"
DEFINITIONS_SCHEMA_VERSION = "1.0"
DEFINITIONS_DEFAULT_VERSION = "v1"

DEFINITIONS_STATUS_HEALTHY = "healthy"
DEFINITIONS_STATUS_DEGRADED = "degraded"
DEFINITIONS_STATUS_UNAVAILABLE = "unavailable"
DEFINITIONS_STATUS_BOOTSTRAP = "bootstrap"

DEFINITIONS_KNOWN_SUBMODULES: Tuple[str, ...] = (
    "definition_models",
    "definition_registry",
    "definition_service",
)

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

_DEFINITION_SERVICE_FACTORY_NAMES: Tuple[str, ...] = (
    "get_definition_service",
    "get_definitions_service",
    "create_definition_service",
    "create_definitions_service",
)

_DEFINITION_REGISTRY_FACTORY_NAMES: Tuple[str, ...] = (
    "get_definition_registry",
    "get_definitions_registry",
    "create_definition_registry",
    "create_definitions_registry",
)

_DEFINITIONS_HEALTH_FUNCTION_NAMES: Tuple[str, ...] = (
    "get_definitions_health",
    "get_definition_service_health",
    "get_definition_registry_health",
    "get_health",
)

_DEFINITIONS_PAYLOAD_FUNCTION_NAMES: Tuple[str, ...] = (
    "get_definitions_payload",
    "get_create_definitions_payload",
    "get_create_definition_options",
    "get_definition_options",
    "get_options_payload",
    "get_options",
)

_DEFINITIONS_SUMMARY_FUNCTION_NAMES: Tuple[str, ...] = (
    "get_definitions_summary",
    "get_definition_summary",
    "get_summary",
)

_DEFINITIONS_CLEAR_CACHE_FUNCTION_NAMES: Tuple[str, ...] = (
    "clear_definitions_caches",
    "clear_definition_caches",
    "clear_definition_cache",
    "clear_caches",
    "clear_cache",
)

_FAMILY_PROFILE_RESOLVER_NAMES: Tuple[str, ...] = (
    "resolve_family_profile_for_context",
    "resolve_family_profile",
    "get_family_profile_for_context",
    "find_family_profile",
)

_VARIANT_PROFILE_RESOLVER_NAMES: Tuple[str, ...] = (
    "resolve_variant_profile_for_context",
    "resolve_variant_profile",
    "get_variant_profile_for_context",
    "find_variant_profile",
)

_VARIANT_PROFILE_GETTER_NAMES: Tuple[str, ...] = (
    "get_variant_profile",
    "get_variant_profile_definition",
    "find_variant_profile_by_id",
)

_FAMILY_PROFILE_GETTER_NAMES: Tuple[str, ...] = (
    "get_family_profile",
    "get_family_profile_definition",
    "find_family_profile_by_id",
)

_VARIABLE_GETTER_NAMES: Tuple[str, ...] = (
    "get_variable",
    "get_variable_definition",
    "find_variable_by_key",
)

_UNIT_GETTER_NAMES: Tuple[str, ...] = (
    "get_unit",
    "get_unit_definition",
    "find_unit_by_id",
)

_MATERIAL_GETTER_NAMES: Tuple[str, ...] = (
    "get_material",
    "get_material_definition",
    "find_material_by_id",
)

_DOCUMENT_TYPE_GETTER_NAMES: Tuple[str, ...] = (
    "get_document_type",
    "get_document_type_definition",
    "find_document_type_by_id",
)

_EMPTY_VARIANT_VALUES_BUILDER_NAMES: Tuple[str, ...] = (
    "build_empty_variant_values",
    "get_empty_variant_values",
    "create_empty_variant_values",
)

_VARIANT_VALUES_VALIDATOR_NAMES: Tuple[str, ...] = (
    "validate_variant_values",
    "validate_variant",
    "validate_variant_payload",
)

_LAZY_EXPORTS: Mapping[str, Tuple[str, str]] = {
    # Models
    "DefinitionError": ("definition_models", "DefinitionError"),
    "DefinitionValidationError": ("definition_models", "DefinitionValidationError"),
    "DefinitionDatasetError": ("definition_models", "DefinitionDatasetError"),
    "DefinitionReferenceError": ("definition_models", "DefinitionReferenceError"),
    "ObjectKindDefinition": ("definition_models", "ObjectKindDefinition"),
    "FamilyProfileDefinition": ("definition_models", "FamilyProfileDefinition"),
    "VariantProfileDefinition": ("definition_models", "VariantProfileDefinition"),
    "VariantProfileSectionDefinition": ("definition_models", "VariantProfileSectionDefinition"),
    "VariableDefinition": ("definition_models", "VariableDefinition"),
    "UnitDefinition": ("definition_models", "UnitDefinition"),
    "MaterialDefinition": ("definition_models", "MaterialDefinition"),
    "DocumentTypeDefinition": ("definition_models", "DocumentTypeDefinition"),
    "ProfileBindingDefinition": ("definition_models", "ProfileBindingDefinition"),
    "DefinitionsRegistrySnapshot": ("definition_models", "DefinitionsRegistrySnapshot"),

    # Registry
    "DefinitionRegistry": ("definition_registry", "DefinitionRegistry"),
    "DefinitionRegistryOptions": ("definition_registry", "DefinitionRegistryOptions"),

    # Service
    "DefinitionService": ("definition_service", "DefinitionService"),
    "DefinitionServiceOptions": ("definition_service", "DefinitionServiceOptions"),
}

__all__ = [
    "DEFINITIONS_COMPONENT_NAME",
    "DEFINITIONS_COMPONENT_VERSION",
    "DEFINITIONS_SCHEMA_VERSION",
    "DEFINITIONS_DEFAULT_VERSION",
    "DEFINITIONS_DATASETS",
    "DEFINITIONS_KNOWN_SUBMODULES",
    "get_definitions_health",
    "get_definitions_summary",
    "get_definitions_payload",
    "get_create_definition_options",
    "get_definition_registry",
    "get_definition_service",
    "resolve_family_profile_for_context",
    "resolve_variant_profile_for_context",
    "get_variant_profile",
    "get_family_profile",
    "get_variable_definition",
    "get_unit_definition",
    "get_material_definition",
    "get_document_type_definition",
    "build_empty_variant_values",
    "validate_variant_values",
    "is_definitions_available",
    "require_definitions_available",
    "clear_definitions_caches",
]

_LOGGER = logging.getLogger(__name__)


def _format_exception(exc: BaseException) -> str:
    return f"{exc.__class__.__name__}: {exc}"


def _module_ref(module_name: str) -> str:
    clean_name = str(module_name or "").strip().strip(".")
    if not clean_name:
        raise ValueError("module_name must not be empty")
    return f"{__name__}.{clean_name}"


@lru_cache(maxsize=64)
def _safe_import_result(module_name: str) -> Dict[str, Any]:
    """
    Import a definitions submodule safely and cache the result.

    The cache intentionally stores both successful and failed imports. During
    development, call clear_definitions_caches() after adding missing files so
    that failed import results are discarded.
    """
    try:
        ref = _module_ref(module_name)
    except Exception as exc:
        return {
            "ok": False,
            "module": None,
            "module_name": module_name,
            "module_ref": None,
            "error": _format_exception(exc),
        }

    try:
        module = importlib.import_module(ref)
        return {
            "ok": True,
            "module": module,
            "module_name": module_name,
            "module_ref": ref,
            "error": None,
        }
    except Exception as exc:
        _LOGGER.debug("Could not import definitions submodule %s: %s", ref, exc)
        return {
            "ok": False,
            "module": None,
            "module_name": module_name,
            "module_ref": ref,
            "error": _format_exception(exc),
        }


def _safe_import_module(module_name: str, *, force_refresh: bool = False) -> Dict[str, Any]:
    if force_refresh:
        _safe_import_result.cache_clear()
    return _safe_import_result(module_name)


def _cache_info_payload() -> Dict[str, Any]:
    info = _safe_import_result.cache_info()
    return {
        "enabled": True,
        "maxsize": info.maxsize,
        "currsize": info.currsize,
        "hits": info.hits,
        "misses": info.misses,
    }


def _callable_accepts_kwargs(func: Callable[..., Any]) -> bool:
    try:
        signature = inspect.signature(func)
    except (TypeError, ValueError):
        return True

    for parameter in signature.parameters.values():
        if parameter.kind == inspect.Parameter.VAR_KEYWORD:
            return True

    return False


def _filter_supported_kwargs(func: Callable[..., Any], kwargs: Mapping[str, Any]) -> Dict[str, Any]:
    if not kwargs:
        return {}

    if _callable_accepts_kwargs(func):
        return dict(kwargs)

    try:
        signature = inspect.signature(func)
    except (TypeError, ValueError):
        return dict(kwargs)

    supported = set(signature.parameters.keys())
    return {key: value for key, value in kwargs.items() if key in supported}


def _invoke_callable(
    func: Callable[..., Any],
    *args: Any,
    **kwargs: Any,
) -> Dict[str, Any]:
    safe_kwargs = _filter_supported_kwargs(func, kwargs)

    try:
        return {
            "ok": True,
            "value": func(*args, **safe_kwargs),
            "error": None,
        }
    except TypeError as exc:
        if safe_kwargs:
            try:
                return {
                    "ok": True,
                    "value": func(*args),
                    "error": None,
                }
            except Exception as fallback_exc:
                return {
                    "ok": False,
                    "value": None,
                    "error": _format_exception(fallback_exc),
                    "primary_error": _format_exception(exc),
                }

        return {
            "ok": False,
            "value": None,
            "error": _format_exception(exc),
        }
    except Exception as exc:
        return {
            "ok": False,
            "value": None,
            "error": _format_exception(exc),
        }


def _call_first_available(
    module: ModuleType,
    function_names: Sequence[str],
    *args: Any,
    **kwargs: Any,
) -> Dict[str, Any]:
    missing: List[str] = []

    for function_name in function_names:
        candidate = getattr(module, function_name, None)
        if callable(candidate):
            result = _invoke_callable(candidate, *args, **kwargs)
            result["function"] = function_name
            return result
        missing.append(function_name)

    return {
        "ok": False,
        "value": None,
        "function": None,
        "missing": missing,
        "error": "No matching callable found",
    }


def _module_health_entry(module_name: str, *, force_refresh: bool = False) -> Dict[str, Any]:
    result = _safe_import_module(module_name, force_refresh=force_refresh)
    if result.get("ok"):
        return {
            "ok": True,
            "healthy": True,
            "status": DEFINITIONS_STATUS_HEALTHY,
            "module": result.get("module_ref"),
            "error": None,
        }

    return {
        "ok": False,
        "healthy": False,
        "status": DEFINITIONS_STATUS_UNAVAILABLE,
        "module": result.get("module_ref"),
        "error": result.get("error"),
    }


def _unavailable_payload(
    action: str,
    *,
    module_name: str = "definition_service",
    error: Optional[str] = None,
    extra: Optional[Mapping[str, Any]] = None,
) -> Dict[str, Any]:
    payload: Dict[str, Any] = {
        "ok": False,
        "healthy": False,
        "status": DEFINITIONS_STATUS_UNAVAILABLE,
        "component": DEFINITIONS_COMPONENT_NAME,
        "version": DEFINITIONS_COMPONENT_VERSION,
        "action": action,
        "module": module_name,
        "error": error or f"{module_name} is not available yet",
    }

    if extra:
        payload.update(dict(extra))

    return payload


def _get_service_module(*, force_refresh: bool = False) -> Dict[str, Any]:
    return _safe_import_module("definition_service", force_refresh=force_refresh)


def _get_registry_module(*, force_refresh: bool = False) -> Dict[str, Any]:
    return _safe_import_module("definition_registry", force_refresh=force_refresh)


def _call_definition_service(
    *,
    action: str,
    function_names: Sequence[str],
    args: Sequence[Any] = (),
    force_refresh: bool = False,
    **kwargs: Any,
) -> Dict[str, Any]:
    result = _get_service_module(force_refresh=force_refresh)
    if not result.get("ok") or not result.get("module"):
        return _unavailable_payload(
            action,
            error=result.get("error"),
        )

    call = _call_first_available(
        result["module"],
        function_names,
        *args,
        **kwargs,
    )

    if call.get("ok"):
        value = call.get("value")
        if isinstance(value, Mapping):
            return dict(value)
        return {
            "ok": True,
            "status": DEFINITIONS_STATUS_HEALTHY,
            "component": DEFINITIONS_COMPONENT_NAME,
            "action": action,
            "value": value,
        }

    return _unavailable_payload(
        action,
        error=call.get("error"),
        extra={
            "missing": call.get("missing"),
        },
    )


def get_definitions_health(*, force_refresh: bool = False) -> Dict[str, Any]:
    """
    Return health information for the definitions package.

    This function must remain safe during incremental build-out. If child files
    do not exist yet, the result is degraded/unavailable instead of raising an
    import error.
    """
    module_entries = {
        module_name: _module_health_entry(module_name, force_refresh=force_refresh)
        for module_name in DEFINITIONS_KNOWN_SUBMODULES
    }

    imported_count = sum(1 for entry in module_entries.values() if entry.get("ok"))
    missing_count = len(module_entries) - imported_count

    service_health: Optional[Any] = None
    service_result = _get_service_module(force_refresh=force_refresh)

    if service_result.get("ok") and service_result.get("module"):
        call = _call_first_available(
            service_result["module"],
            _DEFINITIONS_HEALTH_FUNCTION_NAMES,
            force_refresh=force_refresh,
        )
        if call.get("ok"):
            service_health = call.get("value")
        else:
            service_health = {
                "ok": False,
                "healthy": False,
                "status": DEFINITIONS_STATUS_DEGRADED,
                "error": call.get("error"),
                "missing": call.get("missing"),
            }

    imports_healthy = missing_count == 0
    service_healthy = True

    if isinstance(service_health, Mapping):
        service_healthy = bool(
            service_health.get("healthy", service_health.get("ok", True))
        )

    healthy = imports_healthy and service_healthy

    if healthy:
        status = DEFINITIONS_STATUS_HEALTHY
    elif imported_count == 0:
        status = DEFINITIONS_STATUS_BOOTSTRAP
    else:
        status = DEFINITIONS_STATUS_DEGRADED

    return {
        "ok": healthy,
        "healthy": healthy,
        "status": status,
        "component": DEFINITIONS_COMPONENT_NAME,
        "version": DEFINITIONS_COMPONENT_VERSION,
        "schema_version": DEFINITIONS_SCHEMA_VERSION,
        "default_definitions_version": DEFINITIONS_DEFAULT_VERSION,
        "package": __name__,
        "known_submodules": list(DEFINITIONS_KNOWN_SUBMODULES),
        "datasets": list(DEFINITIONS_DATASETS),
        "imports": module_entries,
        "imported_count": imported_count,
        "missing_count": missing_count,
        "service": service_health,
        "cache": _cache_info_payload(),
    }


def get_definition_service(*, force_refresh: bool = False) -> Any:
    """
    Return the concrete DefinitionService instance when available.

    During bootstrap this returns None instead of failing. Call
    require_definitions_available() if a hard failure is desired.
    """
    result = _get_service_module(force_refresh=force_refresh)
    if not result.get("ok") or not result.get("module"):
        return None

    module = result["module"]
    call = _call_first_available(
        module,
        _DEFINITION_SERVICE_FACTORY_NAMES,
        force_refresh=force_refresh,
    )

    if call.get("ok"):
        return call.get("value")

    return module


def get_definition_registry(*, force_reload: bool = False, force_refresh: bool = False) -> Any:
    """
    Return the concrete DefinitionRegistry instance when available.
    """
    result = _get_registry_module(force_refresh=force_refresh)
    if not result.get("ok") or not result.get("module"):
        return None

    module = result["module"]
    call = _call_first_available(
        module,
        _DEFINITION_REGISTRY_FACTORY_NAMES,
        force_reload=force_reload,
        force_refresh=force_refresh,
    )

    if call.get("ok"):
        return call.get("value")

    return module


def get_definitions_payload(
    *,
    include_inactive: bool = False,
    include_internal: bool = False,
    force_refresh: bool = False,
    force_reload: bool = False,
    **kwargs: Any,
) -> Dict[str, Any]:
    return _call_definition_service(
        action="get_definitions_payload",
        function_names=_DEFINITIONS_PAYLOAD_FUNCTION_NAMES,
        force_refresh=force_refresh,
        include_inactive=include_inactive,
        include_internal=include_internal,
        force_reload=force_reload,
        **kwargs,
    )


def get_create_definition_options(
    *,
    include_inactive: bool = False,
    include_internal: bool = False,
    force_refresh: bool = False,
    force_reload: bool = False,
    **kwargs: Any,
) -> Dict[str, Any]:
    return _call_definition_service(
        action="get_create_definition_options",
        function_names=_DEFINITIONS_PAYLOAD_FUNCTION_NAMES,
        force_refresh=force_refresh,
        include_inactive=include_inactive,
        include_internal=include_internal,
        force_reload=force_reload,
        **kwargs,
    )


def get_definitions_summary(
    *,
    force_refresh: bool = False,
    force_reload: bool = False,
    **kwargs: Any,
) -> Dict[str, Any]:
    return _call_definition_service(
        action="get_definitions_summary",
        function_names=_DEFINITIONS_SUMMARY_FUNCTION_NAMES,
        force_refresh=force_refresh,
        force_reload=force_reload,
        **kwargs,
    )


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
    """
    Resolve the matching family profile for a taxonomy/object context.
    """
    context = {
        "domain": domain,
        "category": category,
        "subcategory": subcategory,
        "object_kind": object_kind,
        "family_profile_id": family_profile_id,
    }

    result = _call_definition_service(
        action="resolve_family_profile_for_context",
        function_names=_FAMILY_PROFILE_RESOLVER_NAMES,
        force_refresh=force_refresh,
        domain=domain,
        category=category,
        subcategory=subcategory,
        object_kind=object_kind,
        family_profile_id=family_profile_id,
        force_reload=force_reload,
        **kwargs,
    )

    if not result.get("ok") and "context" not in result:
        result["context"] = context

    return result


def resolve_variant_profile_for_context(
    *,
    domain: Optional[str] = None,
    category: Optional[str] = None,
    subcategory: Optional[str] = None,
    object_kind: Optional[str] = None,
    family_profile_id: Optional[str] = None,
    variant_profile_id: Optional[str] = None,
    family_id: Optional[str] = None,
    package_id: Optional[str] = None,
    force_refresh: bool = False,
    force_reload: bool = False,
    **extra: Any,
) -> Dict[str, Any]:
    """
    Resolve the matching variant profile for a taxonomy/object/family context.

    This is the main facade function for the future "Variante hinzufügen"
    drawer. The frontend should not decide fields on its own; it should ask the
    backend which profile applies.
    """
    context = {
        "domain": domain,
        "category": category,
        "subcategory": subcategory,
        "object_kind": object_kind,
        "family_profile_id": family_profile_id,
        "variant_profile_id": variant_profile_id,
        "family_id": family_id,
        "package_id": package_id,
        **extra,
    }

    result = _call_definition_service(
        action="resolve_variant_profile_for_context",
        function_names=_VARIANT_PROFILE_RESOLVER_NAMES,
        force_refresh=force_refresh,
        domain=domain,
        category=category,
        subcategory=subcategory,
        object_kind=object_kind,
        family_profile_id=family_profile_id,
        variant_profile_id=variant_profile_id,
        family_id=family_id,
        package_id=package_id,
        force_reload=force_reload,
        **extra,
    )

    if not result.get("ok") and "context" not in result:
        result["context"] = context

    return result


def _get_definition_by_id(
    action: str,
    getter_names: Sequence[str],
    identifier: str,
    *,
    force_refresh: bool = False,
    force_reload: bool = False,
    **kwargs: Any,
) -> Dict[str, Any]:
    clean_identifier = str(identifier or "").strip()
    if not clean_identifier:
        return {
            "ok": False,
            "status": "invalid_request",
            "component": DEFINITIONS_COMPONENT_NAME,
            "action": action,
            "error": "identifier must not be empty",
        }

    return _call_definition_service(
        action=action,
        function_names=getter_names,
        args=(clean_identifier,),
        force_refresh=force_refresh,
        force_reload=force_reload,
        **kwargs,
    )


def get_variant_profile(
    profile_id: str,
    *,
    force_refresh: bool = False,
    force_reload: bool = False,
    **kwargs: Any,
) -> Dict[str, Any]:
    return _get_definition_by_id(
        "get_variant_profile",
        _VARIANT_PROFILE_GETTER_NAMES,
        profile_id,
        force_refresh=force_refresh,
        force_reload=force_reload,
        **kwargs,
    )


def get_family_profile(
    profile_id: str,
    *,
    force_refresh: bool = False,
    force_reload: bool = False,
    **kwargs: Any,
) -> Dict[str, Any]:
    return _get_definition_by_id(
        "get_family_profile",
        _FAMILY_PROFILE_GETTER_NAMES,
        profile_id,
        force_refresh=force_refresh,
        force_reload=force_reload,
        **kwargs,
    )


def get_variable_definition(
    variable_key: str,
    *,
    force_refresh: bool = False,
    force_reload: bool = False,
    **kwargs: Any,
) -> Dict[str, Any]:
    return _get_definition_by_id(
        "get_variable_definition",
        _VARIABLE_GETTER_NAMES,
        variable_key,
        force_refresh=force_refresh,
        force_reload=force_reload,
        **kwargs,
    )


def get_unit_definition(
    unit_id: str,
    *,
    force_refresh: bool = False,
    force_reload: bool = False,
    **kwargs: Any,
) -> Dict[str, Any]:
    return _get_definition_by_id(
        "get_unit_definition",
        _UNIT_GETTER_NAMES,
        unit_id,
        force_refresh=force_refresh,
        force_reload=force_reload,
        **kwargs,
    )


def get_material_definition(
    material_id: str,
    *,
    force_refresh: bool = False,
    force_reload: bool = False,
    **kwargs: Any,
) -> Dict[str, Any]:
    return _get_definition_by_id(
        "get_material_definition",
        _MATERIAL_GETTER_NAMES,
        material_id,
        force_refresh=force_refresh,
        force_reload=force_reload,
        **kwargs,
    )


def get_document_type_definition(
    document_type_id: str,
    *,
    force_refresh: bool = False,
    force_reload: bool = False,
    **kwargs: Any,
) -> Dict[str, Any]:
    return _get_definition_by_id(
        "get_document_type_definition",
        _DOCUMENT_TYPE_GETTER_NAMES,
        document_type_id,
        force_refresh=force_refresh,
        force_reload=force_reload,
        **kwargs,
    )


def build_empty_variant_values(
    *,
    variant_profile_id: str,
    force_refresh: bool = False,
    force_reload: bool = False,
    **kwargs: Any,
) -> Dict[str, Any]:
    """
    Build default/empty values for a new variant based on a variant profile.
    """
    clean_profile_id = str(variant_profile_id or "").strip()
    if not clean_profile_id:
        return {
            "ok": False,
            "status": "invalid_request",
            "component": DEFINITIONS_COMPONENT_NAME,
            "action": "build_empty_variant_values",
            "error": "variant_profile_id must not be empty",
        }

    return _call_definition_service(
        action="build_empty_variant_values",
        function_names=_EMPTY_VARIANT_VALUES_BUILDER_NAMES,
        force_refresh=force_refresh,
        variant_profile_id=clean_profile_id,
        force_reload=force_reload,
        **kwargs,
    )


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
    """
    Validate a variant values object against its backend-owned Variant Profile.
    """
    clean_profile_id = str(variant_profile_id or "").strip()
    if not clean_profile_id:
        return {
            "ok": False,
            "valid": False,
            "status": "invalid_request",
            "component": DEFINITIONS_COMPONENT_NAME,
            "action": "validate_variant_values",
            "errors": ["variant_profile_id must not be empty"],
            "warnings": [],
        }

    return _call_definition_service(
        action="validate_variant_values",
        function_names=_VARIANT_VALUES_VALIDATOR_NAMES,
        force_refresh=force_refresh,
        variant_profile_id=clean_profile_id,
        values=values if isinstance(values, Mapping) else {},
        documents=documents if isinstance(documents, Sequence) and not isinstance(documents, (str, bytes)) else [],
        manufacturer_reference=manufacturer_reference if isinstance(manufacturer_reference, Mapping) else {},
        force_reload=force_reload,
        **kwargs,
    )


def is_definitions_available(*, force_refresh: bool = False) -> bool:
    health = get_definitions_health(force_refresh=force_refresh)
    return bool(health.get("healthy") or health.get("ok"))


def require_definitions_available(*, force_refresh: bool = False) -> None:
    """
    Raise RuntimeError if the definitions package is not fully available.

    Use this only in code paths where definitions are mandatory. Import-time
    code should prefer get_definitions_health() to avoid hard failures.
    """
    health = get_definitions_health(force_refresh=force_refresh)
    if bool(health.get("healthy") or health.get("ok")):
        return

    raise RuntimeError(
        "VECTOPLAN library definitions are not available: "
        f"status={health.get('status')}, missing_count={health.get('missing_count')}"
    )


def _clear_module_cache_functions(module: ModuleType) -> List[Dict[str, Any]]:
    results: List[Dict[str, Any]] = []

    for function_name in _DEFINITIONS_CLEAR_CACHE_FUNCTION_NAMES:
        candidate = getattr(module, function_name, None)
        if not callable(candidate):
            continue

        call = _invoke_callable(candidate)
        results.append(
            {
                "function": function_name,
                "ok": bool(call.get("ok")),
                "error": call.get("error"),
            }
        )

    return results


def clear_definitions_caches(*, include_children: bool = True) -> Dict[str, Any]:
    """
    Clear lazy import caches and, when available, child module caches.

    This is intentionally safe to call even while child modules do not exist.
    """
    before = _cache_info_payload()
    child_results: Dict[str, Any] = {}

    if include_children:
        for module_name in DEFINITIONS_KNOWN_SUBMODULES:
            result = _safe_import_module(module_name)
            if result.get("ok") and result.get("module"):
                child_results[module_name] = _clear_module_cache_functions(result["module"])
            else:
                child_results[module_name] = [
                    {
                        "function": None,
                        "ok": False,
                        "error": result.get("error") or "module not available",
                    }
                ]

    _safe_import_result.cache_clear()
    after = _cache_info_payload()

    return {
        "ok": True,
        "status": "cleared",
        "component": DEFINITIONS_COMPONENT_NAME,
        "include_children": include_children,
        "before": before,
        "after": after,
        "children": child_results,
    }


def __getattr__(name: str) -> Any:
    """
    Lazy access for future public classes without importing child modules during
    package import.
    """
    target = _LAZY_EXPORTS.get(name)
    if not target:
        raise AttributeError(f"module {__name__!r} has no attribute {name!r}")

    module_name, attribute_name = target
    result = _safe_import_module(module_name)

    if not result.get("ok") or not result.get("module"):
        raise AttributeError(
            f"module {__name__!r} cannot provide {name!r}; "
            f"{module_name!r} is unavailable: {result.get('error')}"
        )

    module = result["module"]
    if not hasattr(module, attribute_name):
        raise AttributeError(
            f"module {result.get('module_ref')!r} has no attribute {attribute_name!r}"
        )

    return getattr(module, attribute_name)


def __dir__() -> List[str]:
    base = set(globals().keys())
    base.update(_LAZY_EXPORTS.keys())
    return sorted(base)