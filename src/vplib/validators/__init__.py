# services/vectoplan-library/src/vplib/validators/__init__.py
"""
Public validators API for the VPLIB package engine.

Diese Datei bündelt die stabilen Validator-Bausteine für VPLIB:

- schema_validator
- semantic_validator
- asset_validator
- package_validator

Die Validator-Schicht schreibt keine Dateien. Sie validiert nur bereits erzeugte
Datenstrukturen wie:

- documents mapping
- DocumentBundle
- CreationPlan
- PackagePlan
- AssetReferenceCollection

Wichtig für die neue VPLIB-ID-Architektur:
- `vplib.manifest.json` muss eine gültige `vplib_uid` enthalten.
- Die Package-Validator-Schicht blockiert Packages ohne stabile ID.
- Diese Datei exportiert die neuen `vplib_uid`-Validator-Helfer lazy.
- Komfortfunktionen wie `validate_vplib_documents(...)` und
  `validate_vplib_document_bundle(...)` validieren `vplib_uid` standardmäßig mit.
- `validate_vplib_uid_only(...)` ist ein gezielter Einstieg, um nur die
  Package-ID-Konsistenz zu prüfen.
- Die Datenbank erzeugt später keine eigene fachliche Block-ID, sondern übernimmt
  nur die validierte `vplib_uid`.

Sie ist bewusst robust aufgebaut:
- Imports laufen lazy über __getattr__.
- Einzelne beschädigte Validator-Module blockieren nicht sofort das ganze Package.
- Diagnosefunktionen zeigen Importstatus und Fehler.
- Cache-Clear-Funktionen können alle Validator-Caches gesammelt leeren.
- Komfortfunktionen bieten stabile Einstiegspunkte für spätere Creator, Scanner
  und Routen.
- Komfort-Aliase wie `schema`, `semantic`, `asset` und `package` sind zusätzliche
  Modulzugriffe und brechen keine bestehende API.

Technische Namen, JSON-Keys und Variablen bleiben Englisch.
"""

from __future__ import annotations

import importlib
from dataclasses import dataclass
from functools import lru_cache
from types import ModuleType
from typing import Any, Final, Mapping


VALIDATORS_PACKAGE_VERSION: Final[str] = "vplib.validators.v1"
MANIFEST_VPLIB_UID_FIELD: Final[str] = "vplib_uid"


class ValidatorsImportError(ImportError):
    """Wird ausgelöst, wenn ein Validator-Modul oder Validator-Symbol nicht geladen werden kann."""


@dataclass(frozen=True, slots=True)
class ValidatorModuleStatus:
    """Importstatus eines Validator-Moduls."""

    module_key: str
    module_path: str
    loaded: bool
    error: str | None
    exported_symbols: tuple[str, ...]

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema_version": VALIDATORS_PACKAGE_VERSION,
            "module_key": self.module_key,
            "module_path": self.module_path,
            "loaded": self.loaded,
            "error": self.error,
            "exported_symbols": list(self.exported_symbols),
            "exported_symbol_count": len(self.exported_symbols),
        }


_RELATIVE_VALIDATOR_MODULES: Final[dict[str, str]] = {
    "schema_validator": ".schema_validator",
    "semantic_validator": ".semantic_validator",
    "asset_validator": ".asset_validator",
    "package_validator": ".package_validator",
}


_RELATIVE_VALIDATOR_MODULE_ALIASES: Final[dict[str, str]] = {
    "schema": "schema_validator",
    "schemas": "schema_validator",
    "semantic": "semantic_validator",
    "semantics": "semantic_validator",
    "asset": "asset_validator",
    "assets": "asset_validator",
    "package": "package_validator",
    "packages": "package_validator",
}


_SYMBOL_TO_MODULE: Final[dict[str, str]] = {
    # ---------------------------------------------------------------------
    # schema_validator.py
    # ---------------------------------------------------------------------
    "SCHEMA_VALIDATOR_SCHEMA_VERSION": "schema_validator",
    "SchemaValidationMode": "schema_validator",
    "SchemaValidationOptions": "schema_validator",
    "SchemaValidationReport": "schema_validator",
    "SchemaValidationResult": "schema_validator",
    "SchemaValidationScope": "schema_validator",
    "SchemaValidationStatus": "schema_validator",
    "SchemaValidationTarget": "schema_validator",
    "SchemaValidatorError": "schema_validator",
    "build_validation_result_from_reports": "schema_validator",
    "clear_schema_validator_caches": "schema_validator",
    "get_document_validator": "schema_validator",
    "get_document_validator_registry": "schema_validator",
    "validate_creation_plan_documents_schema": "schema_validator",
    "validate_document_bundle_schema": "schema_validator",
    "validate_document_schema": "schema_validator",
    "validate_documents_schema": "schema_validator",
    "validate_generic_document": "schema_validator",
    "validate_json_compatible_document": "schema_validator",
    "validate_package_path": "schema_validator",

    # ---------------------------------------------------------------------
    # semantic_validator.py
    # ---------------------------------------------------------------------
    "SEMANTIC_VALIDATOR_SCHEMA_VERSION": "semantic_validator",
    "SemanticIssue": "semantic_validator",
    "SemanticIssueCode": "semantic_validator",
    "SemanticIssueSeverity": "semantic_validator",
    "SemanticValidationMode": "semantic_validator",
    "SemanticValidationOptions": "semantic_validator",
    "SemanticValidationResult": "semantic_validator",
    "SemanticValidationStatus": "semantic_validator",
    "SemanticValidatorError": "semantic_validator",
    "build_validation_result_from_semantic_issues": "semantic_validator",
    "clear_semantic_validator_caches": "semantic_validator",
    "get_active_modules": "semantic_validator",
    "get_package_object_kind": "semantic_validator",
    "semantic_issue": "semantic_validator",
    "validate_calculation_references": "semantic_validator",
    "validate_classification_consistency": "semantic_validator",
    "validate_creation_plan_semantics": "semantic_validator",
    "validate_declarative_safety": "semantic_validator",
    "validate_document_bundle_semantics": "semantic_validator",
    "validate_documents_semantics": "semantic_validator",
    "validate_dynamic_rules": "semantic_validator",
    "validate_identity_consistency": "semantic_validator",
    "validate_manufacturer_rules": "semantic_validator",
    "validate_material_consistency": "semantic_validator",
    "validate_module_document_consistency": "semantic_validator",
    "validate_object_kind_rules": "semantic_validator",
    "validate_placement_consistency": "semantic_validator",
    "validate_render_physical_consistency": "semantic_validator",
    "validate_required_documents": "semantic_validator",
    "validate_variant_consistency": "semantic_validator",

    # ---------------------------------------------------------------------
    # asset_validator.py
    # ---------------------------------------------------------------------
    "ASSET_VALIDATOR_SCHEMA_VERSION": "asset_validator",
    "AssetBounds": "asset_validator",
    "AssetIssue": "asset_validator",
    "AssetIssueCode": "asset_validator",
    "AssetIssueSeverity": "asset_validator",
    "AssetReferenceKind": "asset_validator",
    "AssetSourceKind": "asset_validator",
    "AssetValidationMode": "asset_validator",
    "AssetValidationOptions": "asset_validator",
    "AssetValidationResult": "asset_validator",
    "AssetValidationStatus": "asset_validator",
    "AssetValidationTarget": "asset_validator",
    "AssetValidatorError": "asset_validator",
    "asset_issue": "asset_validator",
    "asset_target_from_asset_reference": "asset_validator",
    "asset_target_from_mapping_asset_ref": "asset_validator",
    "bounds_from_mapping": "asset_validator",
    "build_validation_result_from_asset_issues": "asset_validator",
    "clear_asset_validator_caches": "asset_validator",
    "extract_asset_targets_from_documents": "asset_validator",
    "extract_footprint_size_m": "asset_validator",
    "infer_asset_kind": "asset_validator",
    "infer_extension": "asset_validator",
    "infer_mime_type": "asset_validator",
    "infer_source_kind": "asset_validator",
    "infer_target_module_for_role": "asset_validator",
    "is_external_uri": "asset_validator",
    "is_package_internal_path": "asset_validator",
    "issue_for_target": "asset_validator",
    "validate_asset_collection": "asset_validator",
    "validate_asset_declared_size": "asset_validator",
    "validate_asset_declarative_safety": "asset_validator",
    "validate_asset_duplicates": "asset_validator",
    "validate_asset_extension": "asset_validator",
    "validate_asset_targets": "asset_validator",
    "validate_creation_plan_assets": "asset_validator",
    "validate_document_bundle_assets": "asset_validator",
    "validate_documents_assets": "asset_validator",
    "validate_package_asset_path": "asset_validator",
    "validate_profile_asset_rules": "asset_validator",
    "validate_single_asset_target": "asset_validator",

    # ---------------------------------------------------------------------
    # package_validator.py
    # ---------------------------------------------------------------------
    "CORE_REQUIRED_DOCUMENTS": "package_validator",
    "KNOWN_MODULE_ORDER": "package_validator",
    "MANIFEST_DOCUMENT_PATH": "package_validator",
    "MANIFEST_VPLIB_UID_FIELD": "package_validator",
    "MODULES_DOCUMENT_PATH": "package_validator",
    "PACKAGE_ARCHIVE_EXTENSION": "package_validator",
    "PACKAGE_VALIDATOR_SCHEMA_VERSION": "package_validator",
    "ROOT_REQUIRED_DOCUMENTS": "package_validator",
    "PackageIssue": "package_validator",
    "PackageIssueCode": "package_validator",
    "PackageIssueSeverity": "package_validator",
    "PackageValidationMode": "package_validator",
    "PackageValidationOptions": "package_validator",
    "PackageValidationPhase": "package_validator",
    "PackageValidationResult": "package_validator",
    "PackageValidationStatus": "package_validator",
    "PackageValidatorError": "package_validator",
    "build_documents_from_creation_plan_safe": "package_validator",
    "build_validation_result_from_package_result": "package_validator",
    "clear_package_validator_caches": "package_validator",
    "collect_expected_vplib_uid_candidates": "package_validator",
    "dedupe_issues": "package_validator",
    "extract_path_from_plan_item": "package_validator",
    "extract_planned_asset_target_paths": "package_validator",
    "extract_planned_directory_paths": "package_validator",
    "extract_planned_file_paths": "package_validator",
    "extract_raw_vplib_uid_from_any": "package_validator",
    "fallback_subvalidator_error_result": "package_validator",
    "find_duplicates": "package_validator",
    "get_creation_plan_object_kind": "package_validator",
    "get_creation_plan_package_id": "package_validator",
    "get_vplib_uid_from_bundle_safe": "package_validator",
    "get_vplib_uid_from_documents_safe": "package_validator",
    "get_vplib_uid_from_manifest_safe": "package_validator",
    "infer_module_from_path_safe": "package_validator",
    "normalize_creation_plan": "package_validator",
    "normalize_document_bundle": "package_validator",
    "normalize_document_mapping": "package_validator",
    "normalize_documents_mapping": "package_validator",
    "normalize_enum_key": "package_validator",
    "normalize_json_value": "package_validator",
    "normalize_metadata": "package_validator",
    "normalize_optional_module_name": "package_validator",
    "normalize_options": "package_validator",
    "normalize_package_path": "package_validator",
    "normalize_positive_float": "package_validator",
    "normalize_string_tuple": "package_validator",
    "normalize_sub_result": "package_validator",
    "normalize_validation_result": "package_validator",
    "normalize_vplib_uid_safe": "package_validator",
    "package_issue": "package_validator",
    "parse_issue_code_value": "package_validator",
    "parse_issue_severity_value": "package_validator",
    "parse_validation_mode_value": "package_validator",
    "parse_validation_phase_value": "package_validator",
    "parse_validation_status_value": "package_validator",
    "run_sub_validators": "package_validator",
    "sort_issues": "package_validator",
    "sub_result_is_valid": "package_validator",
    "sub_result_to_dict": "package_validator",
    "validate_archive_path_consistency": "package_validator",
    "validate_creation_plan_profile_consistency": "package_validator",
    "validate_document_path_consistency": "package_validator",
    "validate_package_creation_plan": "package_validator",
    "validate_package_document_bundle": "package_validator",
    "validate_package_documents": "package_validator",
    "validate_package_plan_consistency": "package_validator",
    "validate_package_plan_only": "package_validator",
    "validate_plan_context_consistency": "package_validator",
    "validate_plan_module_consistency": "package_validator",
    "validate_planned_documents_against_bundle": "package_validator",
    "validate_planned_path_duplicates": "package_validator",
    "validate_required_package_documents": "package_validator",
    "validate_vplib_uid_consistency": "package_validator",
}


_CLEAR_FUNCTION_BY_MODULE: Final[dict[str, str]] = {
    "schema_validator": "clear_schema_validator_caches",
    "semantic_validator": "clear_semantic_validator_caches",
    "asset_validator": "clear_asset_validator_caches",
    "package_validator": "clear_package_validator_caches",
}


def _canonical_module_key(module_key: str) -> str:
    """Normalisiert Validator-Modulkeys und Komfort-Aliase."""
    try:
        key = str(module_key).strip()
    except Exception as exc:
        raise ValidatorsImportError("Invalid VPLIB validator module key.") from exc

    if not key:
        raise ValidatorsImportError("Empty VPLIB validator module key.")

    return _RELATIVE_VALIDATOR_MODULE_ALIASES.get(key, key)


@lru_cache(maxsize=64)
def _load_validator_module(module_key: str) -> ModuleType:
    """Lädt ein Validator-Modul lazy über relative Imports."""
    canonical_key = _canonical_module_key(module_key)

    if canonical_key not in _RELATIVE_VALIDATOR_MODULES:
        raise ValidatorsImportError(f"Unknown VPLIB validator module {module_key!r}.")

    relative_path = _RELATIVE_VALIDATOR_MODULES[canonical_key]

    try:
        return importlib.import_module(relative_path, package=__name__)
    except Exception as exc:
        raise ValidatorsImportError(
            f"Could not import VPLIB validator module "
            f"{canonical_key!r} from {relative_path!r}: {exc}"
        ) from exc


def __getattr__(name: str) -> Any:
    """
    Lazy-Reexport für öffentliche Validator-Symbole.

    Beispiele:
        from vplib.validators import validate_package_creation_plan
        from vplib.validators import validate_vplib_uid_consistency
        from vplib.validators import validate_documents_schema
        from vplib.validators import validate_documents_semantics
        from vplib.validators import validate_documents_assets
    """
    canonical_module_name = _RELATIVE_VALIDATOR_MODULE_ALIASES.get(name, name)

    if canonical_module_name in _RELATIVE_VALIDATOR_MODULES:
        module = _load_validator_module(canonical_module_name)
        globals()[name] = module
        return module

    module_key = _SYMBOL_TO_MODULE.get(name)

    if not module_key:
        raise AttributeError(f"module {__name__!r} has no attribute {name!r}")

    module = _load_validator_module(module_key)

    try:
        value = getattr(module, name)
    except AttributeError as exc:
        raise ValidatorsImportError(
            f"Validator symbol {name!r} is mapped to module {module_key!r}, "
            f"but the module does not export it."
        ) from exc

    globals()[name] = value
    return value


def get_validator_module_keys(*, include_aliases: bool = False) -> tuple[str, ...]:
    """
    Gibt alle bekannten Validator-Modulkeys zurück.

    Args:
        include_aliases:
            Wenn True, werden Komfort-Aliase wie "schema" oder "package" ergänzt.
    """
    keys = list(_RELATIVE_VALIDATOR_MODULES.keys())

    if include_aliases:
        keys.extend(_RELATIVE_VALIDATOR_MODULE_ALIASES.keys())

    return tuple(keys)


def get_validator_module_alias_map() -> Mapping[str, str]:
    """Gibt die Alias-zu-Modul-Zuordnung zurück."""
    return dict(_RELATIVE_VALIDATOR_MODULE_ALIASES)


def get_validator_symbol_names() -> tuple[str, ...]:
    """Gibt alle lazy exportierten öffentlichen Symbolnamen zurück."""
    return tuple(sorted(_SYMBOL_TO_MODULE.keys()))


def get_validator_symbol_module_map() -> Mapping[str, str]:
    """Gibt die Symbol-zu-Modul-Zuordnung zurück."""
    return dict(_SYMBOL_TO_MODULE)


def is_validator_symbol(name: str) -> bool:
    """Gibt zurück, ob ein Symbol oder Modul-Alias über dieses Package exportiert wird."""
    try:
        key = str(name).strip()
    except Exception:
        return False

    if not key:
        return False

    return (
        key in _SYMBOL_TO_MODULE
        or key in _RELATIVE_VALIDATOR_MODULES
        or key in _RELATIVE_VALIDATOR_MODULE_ALIASES
    )


def load_all_validator_modules() -> tuple[ModuleType, ...]:
    """
    Lädt alle kanonischen Validator-Module.

    Nützlich für Tests, Startup-Diagnose oder strikte Entwicklungsprüfungen.
    Aliase werden nicht doppelt geladen.
    """
    modules: list[ModuleType] = []

    for module_key in get_validator_module_keys(include_aliases=False):
        modules.append(_load_validator_module(module_key))

    return tuple(modules)


def get_validator_module_statuses() -> tuple[ValidatorModuleStatus, ...]:
    """
    Gibt Importstatus für alle Validator-Module zurück.

    Diese Funktion wirft nicht, sondern sammelt Fehler in Statusobjekten.
    """
    statuses: list[ValidatorModuleStatus] = []

    for module_key, relative_path in _RELATIVE_VALIDATOR_MODULES.items():
        exported_symbols = tuple(
            sorted(
                symbol
                for symbol, mapped_module_key in _SYMBOL_TO_MODULE.items()
                if mapped_module_key == module_key
            )
        )

        try:
            _load_validator_module(module_key)
            statuses.append(
                ValidatorModuleStatus(
                    module_key=module_key,
                    module_path=relative_path,
                    loaded=True,
                    error=None,
                    exported_symbols=exported_symbols,
                )
            )
        except Exception as exc:
            statuses.append(
                ValidatorModuleStatus(
                    module_key=module_key,
                    module_path=relative_path,
                    loaded=False,
                    error=str(exc),
                    exported_symbols=exported_symbols,
                )
            )

    return tuple(statuses)


def get_validators_health() -> dict[str, Any]:
    """Gibt einen JSON-kompatiblen Health-Snapshot der Validator-Schicht zurück."""
    statuses = get_validator_module_statuses()

    try:
        healthy = all(status.loaded for status in statuses)
    except Exception:
        healthy = False

    return {
        "schema_version": VALIDATORS_PACKAGE_VERSION,
        "healthy": healthy,
        "module_count": len(statuses),
        "loaded_module_count": sum(1 for status in statuses if status.loaded),
        "symbol_count": len(_SYMBOL_TO_MODULE),
        "alias_count": len(_RELATIVE_VALIDATOR_MODULE_ALIASES),
        "aliases": get_validator_module_alias_map(),
        "modules": [status.to_dict() for status in statuses],
    }


def assert_validators_ready() -> None:
    """
    Prüft, ob alle Validator-Module ladbar sind.

    Raises:
        ValidatorsImportError: Wenn mindestens ein Modul nicht importiert werden kann.
    """
    statuses = get_validator_module_statuses()
    failed = [status for status in statuses if not status.loaded]

    if failed:
        details = "; ".join(
            f"{status.module_key}: {status.error}" for status in failed
        )
        raise ValidatorsImportError(f"VPLIB validators package is not ready: {details}")


def clear_validator_caches() -> None:
    """
    Leert alle bekannten Validator-Caches.

    Diese Funktion ist bewusst defensiv. Wenn ein einzelnes Modul fehlt oder
    eine Clear-Funktion nicht existiert, wird weitergemacht.
    """
    for module_key, function_name in _CLEAR_FUNCTION_BY_MODULE.items():
        try:
            module = _load_validator_module(module_key)
            function = getattr(module, function_name, None)

            if callable(function):
                function()
        except Exception:
            continue

    try:
        _load_validator_module.cache_clear()
    except Exception:
        pass


def validator_status_to_json(status: ValidatorModuleStatus) -> dict[str, Any]:
    """Serialisiert einen ValidatorModuleStatus JSON-kompatibel."""
    try:
        return status.to_dict()
    except Exception:
        return {
            "schema_version": VALIDATORS_PACKAGE_VERSION,
            "module_key": str(getattr(status, "module_key", "<unknown>")),
            "module_path": str(getattr(status, "module_path", "<unknown>")),
            "loaded": bool(getattr(status, "loaded", False)),
            "error": str(getattr(status, "error", None)),
            "exported_symbols": list(getattr(status, "exported_symbols", ()) or ()),
        }


def validator_statuses_to_json() -> list[dict[str, Any]]:
    """Serialisiert alle Validator-Modulstatuswerte JSON-kompatibel."""
    return [validator_status_to_json(status) for status in get_validator_module_statuses()]


def validate_vplib_creation_plan(
    creation_plan: Any,
    *,
    mode: str = "strict",
    validate_schema: bool = True,
    validate_semantics: bool = True,
    validate_assets: bool = True,
    validate_vplib_uid: bool = True,
    metadata: Mapping[str, Any] | None = None,
) -> Any:
    """
    Stabiler Komfort-Einstieg für die vollständige CreationPlan-Validierung.

    Dieser Wrapper delegiert an package_validator.validate_package_creation_plan.
    """
    module = _load_validator_module("package_validator")
    options_cls = getattr(module, "PackageValidationOptions")
    validator = getattr(module, "validate_package_creation_plan")

    return validator(
        creation_plan,
        options=options_cls(
            mode=mode,
            validate_schema=validate_schema,
            validate_semantics=validate_semantics,
            validate_assets=validate_assets,
            validate_vplib_uid=validate_vplib_uid,
        ),
        metadata=metadata,
    )


def validate_vplib_documents(
    documents: Mapping[str, Mapping[str, Any]],
    *,
    profile: Any | None = None,
    mode: str = "strict",
    validate_schema: bool = True,
    validate_semantics: bool = True,
    validate_assets: bool = True,
    validate_vplib_uid: bool = True,
    metadata: Mapping[str, Any] | None = None,
) -> Any:
    """
    Stabiler Komfort-Einstieg für die vollständige Dokument-Validierung.

    Dieser Wrapper delegiert an package_validator.validate_package_documents.
    """
    module = _load_validator_module("package_validator")
    options_cls = getattr(module, "PackageValidationOptions")
    validator = getattr(module, "validate_package_documents")

    return validator(
        documents,
        profile=profile,
        options=options_cls(
            mode=mode,
            validate_schema=validate_schema,
            validate_semantics=validate_semantics,
            validate_assets=validate_assets,
            validate_vplib_uid=validate_vplib_uid,
        ),
        metadata=metadata,
    )


def validate_vplib_document_bundle(
    bundle: Any,
    *,
    profile: Any | None = None,
    mode: str = "strict",
    validate_schema: bool = True,
    validate_semantics: bool = True,
    validate_assets: bool = True,
    validate_vplib_uid: bool = True,
    metadata: Mapping[str, Any] | None = None,
) -> Any:
    """
    Stabiler Komfort-Einstieg für die vollständige DocumentBundle-Validierung.

    Dieser Wrapper delegiert an package_validator.validate_package_document_bundle.
    """
    module = _load_validator_module("package_validator")
    options_cls = getattr(module, "PackageValidationOptions")
    validator = getattr(module, "validate_package_document_bundle")

    return validator(
        bundle,
        profile=profile,
        options=options_cls(
            mode=mode,
            validate_schema=validate_schema,
            validate_semantics=validate_semantics,
            validate_assets=validate_assets,
            validate_vplib_uid=validate_vplib_uid,
        ),
        metadata=metadata,
    )


def validate_vplib_uid_only(
    documents: Mapping[str, Mapping[str, Any]],
    *,
    context: Any | None = None,
    package_plan: Any | None = None,
    metadata: Mapping[str, Any] | None = None,
) -> Any:
    """
    Validiert nur die VPLIB-Package-ID-Konsistenz.

    Erwartet ein path -> document Mapping mit `vplib.manifest.json`.

    Diese Funktion ist nützlich für:
    - Scanner-Vorprüfung
    - Backfill-Checks
    - Create-Payload-Diagnose
    - Tests der neuen DB-Publish-Grundlage
    """
    module = _load_validator_module("package_validator")
    options_cls = getattr(module, "PackageValidationOptions")
    validator = getattr(module, "validate_package_documents")

    return validator(
        documents,
        context=context,
        package_plan=package_plan,
        options=options_cls(
            mode="strict",
            validate_schema=False,
            validate_semantics=False,
            validate_assets=False,
            validate_package_plan=False,
            validate_document_paths=False,
            validate_required_documents=False,
            validate_vplib_uid=True,
            validate_profile_consistency=False,
            validate_archive_path=False,
        ),
        metadata={
            "source": "validate_vplib_uid_only",
            **dict(metadata or {}),
        },
    )


def validate_vplib_schema_only(
    documents: Mapping[str, Mapping[str, Any]],
    *,
    mode: str = "strict",
    metadata: Mapping[str, Any] | None = None,
) -> Any:
    """Validiert nur die Schema-Ebene eines Dokument-Mappings."""
    module = _load_validator_module("schema_validator")
    options_cls = getattr(module, "SchemaValidationOptions")
    validator = getattr(module, "validate_documents_schema")

    return validator(
        documents,
        options=options_cls(mode=mode),
        metadata=metadata,
    )


def validate_vplib_semantics_only(
    documents: Mapping[str, Mapping[str, Any]],
    *,
    mode: str = "strict",
    metadata: Mapping[str, Any] | None = None,
) -> Any:
    """Validiert nur die semantische Ebene eines Dokument-Mappings."""
    module = _load_validator_module("semantic_validator")
    options_cls = getattr(module, "SemanticValidationOptions")
    validator = getattr(module, "validate_documents_semantics")

    return validator(
        documents,
        options=options_cls(mode=mode),
        metadata=metadata,
    )


def validate_vplib_assets_only(
    documents: Mapping[str, Mapping[str, Any]],
    *,
    profile: Any | None = None,
    mode: str = "strict",
    metadata: Mapping[str, Any] | None = None,
) -> Any:
    """Validiert nur die Asset-Ebene eines Dokument-Mappings."""
    module = _load_validator_module("asset_validator")
    options_cls = getattr(module, "AssetValidationOptions")
    validator = getattr(module, "validate_documents_assets")

    return validator(
        documents,
        profile=profile,
        options=options_cls(mode=mode),
        metadata=metadata,
    )


__version__ = VALIDATORS_PACKAGE_VERSION

__all__ = [
    "MANIFEST_VPLIB_UID_FIELD",
    "VALIDATORS_PACKAGE_VERSION",
    "ValidatorModuleStatus",
    "ValidatorsImportError",
    "__version__",
    "assert_validators_ready",
    "clear_validator_caches",
    "get_validator_module_alias_map",
    "get_validator_module_keys",
    "get_validator_module_statuses",
    "get_validator_symbol_module_map",
    "get_validator_symbol_names",
    "get_validators_health",
    "is_validator_symbol",
    "load_all_validator_modules",
    "validate_vplib_assets_only",
    "validate_vplib_creation_plan",
    "validate_vplib_document_bundle",
    "validate_vplib_documents",
    "validate_vplib_schema_only",
    "validate_vplib_semantics_only",
    "validate_vplib_uid_only",
    "validator_status_to_json",
    "validator_statuses_to_json",
    "schema_validator",
    "semantic_validator",
    "asset_validator",
    "package_validator",
    "schema",
    "schemas",
    "semantic",
    "semantics",
    "asset",
    "assets",
    "package",
    "packages",
    *_SYMBOL_TO_MODULE.keys(),
]