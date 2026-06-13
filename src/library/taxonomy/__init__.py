# services/vectoplan-library/src/library/taxonomy/__init__.py
"""
VECTOPLAN Library Taxonomy Package.

This package contains the backend-owned taxonomy layer for VPLIB:

- taxonomy_models.py
  Dependency-free model/value-object layer.

- taxonomy_registry.py
  File-backed JSON registry loader with cache, reload and diagnostics.

- taxonomy_validator.py
  Structural and semantic validation for registry, selections and source paths.

- taxonomy_service.py
  Central framework-free service layer for routes, create-flow, scanner and
  read-models.

Design rules:
- Importing this package must not load the taxonomy JSON file.
- Importing this package must not require Flask.
- Importing this package must not touch the filesystem.
- Runtime loading happens only through TaxonomyRegistry / TaxonomyService calls.
- Public exports are lazy-loaded to reduce circular import risk.

Canonical taxonomy file:
    services/vectoplan-library/src/library/taxonomy/data/taxonomy.v1.json

Canonical source path:
    src/library/source/{domain}/{category}/{subcategory}/{family_slug}

Canonical family_id:
    vp.{domain}.{category}.{subcategory}.{family_slug}

Canonical package_id:
    vplib.vp.{domain}.{category}.{subcategory}.{family_slug}
"""

from __future__ import annotations

import importlib
from types import ModuleType
from typing import Any, Dict, Iterable, Mapping, Tuple


__version__ = "0.1.0"
__component__ = "vectoplan-library-taxonomy"
__status__ = "active"


_MODELS_MODULE = "taxonomy_models"
_REGISTRY_MODULE = "taxonomy_registry"
_VALIDATOR_MODULE = "taxonomy_validator"
_SERVICE_MODULE = "taxonomy_service"


_EXPORTS: Dict[str, str] = {
    # taxonomy_models.py constants
    "DEFAULT_SCHEMA_VERSION": _MODELS_MODULE,
    "DEFAULT_TAXONOMY_VERSION": _MODELS_MODULE,
    "PACKAGE_ID_PREFIX": _MODELS_MODULE,
    "TAXONOMY_ID_PREFIX": _MODELS_MODULE,

    # taxonomy_models.py classes
    "TaxonomyCategory": _MODELS_MODULE,
    "TaxonomyConstraints": _MODELS_MODULE,
    "TaxonomyDefaults": _MODELS_MODULE,
    "TaxonomyDomain": _MODELS_MODULE,
    "TaxonomyIssue": _MODELS_MODULE,
    "TaxonomyIssueSeverity": _MODELS_MODULE,
    "TaxonomyLevel": _MODELS_MODULE,
    "TaxonomyModelError": _MODELS_MODULE,
    "TaxonomyNode": _MODELS_MODULE,
    "TaxonomyOption": _MODELS_MODULE,
    "TaxonomyRegistryModel": _MODELS_MODULE,
    "TaxonomyResolvedSelection": _MODELS_MODULE,
    "TaxonomySelection": _MODELS_MODULE,
    "TaxonomyStatus": _MODELS_MODULE,
    "TaxonomySubcategory": _MODELS_MODULE,
    "TaxonomyValidationResult": _MODELS_MODULE,

    # taxonomy_models.py helpers
    "as_mapping": _MODELS_MODULE,
    "as_sequence": _MODELS_MODULE,
    "coerce_slug_tuple": _MODELS_MODULE,
    "coerce_string_tuple": _MODELS_MODULE,
    "extract_extra": _MODELS_MODULE,
    "first_existing": _MODELS_MODULE,
    "is_valid_slug": _MODELS_MODULE,
    "make_json_safe": _MODELS_MODULE,
    "normalize_identifier_prefix": _MODELS_MODULE,
    "normalize_path_tuple": _MODELS_MODULE,
    "normalize_slug": _MODELS_MODULE,
    "safe_bool": _MODELS_MODULE,
    "safe_int": _MODELS_MODULE,
    "safe_str": _MODELS_MODULE,

    # taxonomy_registry.py constants
    "DEFAULT_TAXONOMY_DATA_DIRNAME": _REGISTRY_MODULE,
    "DEFAULT_TAXONOMY_FILENAME": _REGISTRY_MODULE,
    "ENV_TAXONOMY_FILE_KEYS": _REGISTRY_MODULE,
    "ENV_TAXONOMY_HASH_KEYS": _REGISTRY_MODULE,
    "ENV_TAXONOMY_STRICT_KEYS": _REGISTRY_MODULE,

    # taxonomy_registry.py classes
    "TaxonomyFileFingerprint": _REGISTRY_MODULE,
    "TaxonomyRegistry": _REGISTRY_MODULE,
    "TaxonomyRegistryError": _REGISTRY_MODULE,
    "TaxonomyRegistryLoadError": _REGISTRY_MODULE,
    "TaxonomyRegistryLoadResult": _REGISTRY_MODULE,
    "TaxonomyRegistryPathError": _REGISTRY_MODULE,

    # taxonomy_registry.py helpers
    "compute_file_sha256": _REGISTRY_MODULE,
    "default_taxonomy_file_path": _REGISTRY_MODULE,
    "get_default_taxonomy_registry": _REGISTRY_MODULE,
    "load_default_taxonomy_registry": _REGISTRY_MODULE,
    "load_default_taxonomy_result": _REGISTRY_MODULE,
    "load_taxonomy_registry_model_from_file": _REGISTRY_MODULE,
    "read_json_file": _REGISTRY_MODULE,
    "reset_default_taxonomy_registry": _REGISTRY_MODULE,
    "resolve_hash_default": _REGISTRY_MODULE,
    "resolve_strict_default": _REGISTRY_MODULE,
    "resolve_taxonomy_file_path": _REGISTRY_MODULE,
    "utc_now_iso": _REGISTRY_MODULE,
    "write_json_file_atomic": _REGISTRY_MODULE,

    # taxonomy_validator.py constants
    "CANONICAL_SOURCE_DEPTH": _VALIDATOR_MODULE,
    "KNOWN_OBJECT_KINDS": _VALIDATOR_MODULE,
    "KNOWN_VPLIB_MODULES": _VALIDATOR_MODULE,
    "LEGACY_SOURCE_DEPTH": _VALIDATOR_MODULE,
    "REQUIRED_NODE_FIELDS": _VALIDATOR_MODULE,
    "RESERVED_TOP_LEVEL_KEYS": _VALIDATOR_MODULE,

    # taxonomy_validator.py classes
    "TaxonomySourcePathValidation": _VALIDATOR_MODULE,
    "TaxonomyValidator": _VALIDATOR_MODULE,
    "TaxonomyValidatorConfig": _VALIDATOR_MODULE,
    "TaxonomyValidatorError": _VALIDATOR_MODULE,

    # taxonomy_validator.py helpers
    "assert_valid_taxonomy_registry": _VALIDATOR_MODULE,
    "is_reasonable_version_string": _VALIDATOR_MODULE,
    "normalize_source_path_parts": _VALIDATOR_MODULE,
    "validate_taxonomy_family_identifiers": _VALIDATOR_MODULE,
    "validate_taxonomy_registry_data": _VALIDATOR_MODULE,
    "validate_taxonomy_registry_model": _VALIDATOR_MODULE,
    "validate_taxonomy_selection": _VALIDATOR_MODULE,
    "validate_taxonomy_source_path": _VALIDATOR_MODULE,

    # taxonomy_service.py constants
    "DEFAULT_ALLOW_STALE_ON_ERROR": _SERVICE_MODULE,
    "DEFAULT_CACHE_MAX_ITEMS": _SERVICE_MODULE,
    "DEFAULT_CACHE_PAYLOADS": _SERVICE_MODULE,
    "DEFAULT_INCLUDE_INACTIVE": _SERVICE_MODULE,
    "TAXONOMY_REQUIRED_FIELDS": _SERVICE_MODULE,

    # taxonomy_service.py classes
    "TaxonomyBuildResult": _SERVICE_MODULE,
    "TaxonomyCounts": _SERVICE_MODULE,
    "TaxonomyPayloadCacheEntry": _SERVICE_MODULE,
    "TaxonomySelectionError": _SERVICE_MODULE,
    "TaxonomyService": _SERVICE_MODULE,
    "TaxonomyServiceConfig": _SERVICE_MODULE,
    "TaxonomyServiceError": _SERVICE_MODULE,
    "TaxonomyServiceUnavailableError": _SERVICE_MODULE,

    # taxonomy_service.py helpers
    "copy_payload": _SERVICE_MODULE,
    "get_default_taxonomy_service": _SERVICE_MODULE,
    "reset_default_taxonomy_service": _SERVICE_MODULE,
}


_MODULE_CACHE: Dict[str, ModuleType] = {}


__all__ = tuple(
    sorted(
        {
            "__version__",
            "__component__",
            "__status__",
            "get_taxonomy_package_info",
            "get_taxonomy_export_map",
            "preload_taxonomy_modules",
            "clear_taxonomy_import_cache",
            *_EXPORTS.keys(),
        }
    )
)


def __getattr__(name: str) -> Any:
    """
    Lazy-load public taxonomy exports.

    This keeps package import cheap and prevents route imports from loading the
    full taxonomy stack unless a concrete symbol is requested.
    """

    if name in {"__version__", "__component__", "__status__"}:
        return globals()[name]

    module_name = _EXPORTS.get(name)
    if not module_name:
        raise AttributeError(f"module '{__name__}' has no attribute '{name}'")

    module = _load_taxonomy_module(module_name)

    try:
        value = getattr(module, name)
    except AttributeError as exc:
        raise AttributeError(
            f"taxonomy export '{name}' is mapped to '{module_name}', "
            f"but the symbol does not exist in that module."
        ) from exc

    globals()[name] = value
    return value


def __dir__() -> Iterable[str]:
    return sorted(set(globals().keys()) | set(__all__))


def get_taxonomy_package_info() -> Dict[str, Any]:
    """
    Return static package metadata.

    This does not import submodules and does not load the taxonomy registry file.
    """

    return {
        "component": __component__,
        "version": __version__,
        "status": __status__,
        "package": __name__,
        "lazy_exports": True,
        "export_count": len(_EXPORTS),
        "modules": {
            "models": f"{__name__}.{_MODELS_MODULE}",
            "registry": f"{__name__}.{_REGISTRY_MODULE}",
            "validator": f"{__name__}.{_VALIDATOR_MODULE}",
            "service": f"{__name__}.{_SERVICE_MODULE}",
        },
        "canonical_source_path_pattern": "src/library/source/{domain}/{category}/{subcategory}/{family_slug}",
        "family_id_pattern": "vp.{domain}.{category}.{subcategory}.{family_slug}",
        "package_id_pattern": "vplib.vp.{domain}.{category}.{subcategory}.{family_slug}",
    }


def get_taxonomy_export_map() -> Dict[str, str]:
    """
    Return the public lazy-export map.

    Useful for tests and diagnostics.
    """

    return dict(_EXPORTS)


def preload_taxonomy_modules(*, raise_on_error: bool = False) -> Dict[str, Any]:
    """
    Import all taxonomy submodules without loading the taxonomy JSON registry.

    This is useful for startup checks and test diagnostics.

    Returns:
        {
          "ok": bool,
          "loaded": [...],
          "errors": {...}
        }
    """

    loaded = []
    errors: Dict[str, str] = {}

    for module_name in (
        _MODELS_MODULE,
        _REGISTRY_MODULE,
        _VALIDATOR_MODULE,
        _SERVICE_MODULE,
    ):
        try:
            _load_taxonomy_module(module_name)
            loaded.append(module_name)
        except Exception as exc:
            errors[module_name] = str(exc)
            if raise_on_error:
                raise

    return {
        "ok": not errors,
        "loaded": loaded,
        "errors": errors,
    }


def clear_taxonomy_import_cache() -> None:
    """
    Clear only this package's lazy import cache.

    This does not clear registry/service runtime caches. Those are managed by:
    - reset_default_taxonomy_registry()
    - reset_default_taxonomy_service()
    """

    _MODULE_CACHE.clear()

    for export_name in tuple(_EXPORTS.keys()):
        globals().pop(export_name, None)


def _load_taxonomy_module(module_name: str) -> ModuleType:
    if module_name in _MODULE_CACHE:
        return _MODULE_CACHE[module_name]

    qualified_name = f"{__name__}.{module_name}"

    try:
        module = importlib.import_module(qualified_name)
    except Exception as exc:
        raise ImportError(
            f"Could not import taxonomy module '{qualified_name}': {exc}"
        ) from exc

    _MODULE_CACHE[module_name] = module
    return module