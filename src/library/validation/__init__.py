# services/vectoplan-library/src/library/validation/__init__.py
"""
Validation Package der VECTOPLAN Creative-Library-Schicht.

Dieses Package bündelt die fachliche Validierung für Pakete aus
`src/library/source`.

Aktuell enthalten:

- `library_package_validator.py`
  Validiert gelesene VPLIB-Pakete für die Verwendung als Creative-Library-
  Block oder Creative-Library-Objekt.

Wichtige Architekturgrenze:

- `/src/vplib/validators`
  prüft technische VPLIB-Konsistenz.

- `/src/library/validation`
  prüft, ob ein VPLIB-Paket als sichtbarer, stabil identifizierbarer,
  routenfähiger, taxonomisch korrekt eingeordneter und später
  DB-upsert-fähiger Library-Eintrag taugt.

Taxonomie-Regel:

    Backend-Taxonomie ist kanonisch für:
    - Domain/Reiter
    - Kategorie
    - Subkategorie
    - Source-Pfad
    - family_id
    - package_id
    - Creative-Library-Navigation

Diese Datei ist defensiv aufgebaut:

- keine Flask-Abhängigkeit
- keine Datenbank-Abhängigkeit
- kein Scan beim Import
- kein Dateisystem-Schreiben
- kein Taxonomie-JSON-Load beim Import
- Lazy-Reexports
- Health-Funktion für Startup und Routen

Version 0.2.0:

- Taxonomie-Validator-Symbole werden vollständig reexportiert.
- Source-Pfad-Helfer werden reexportiert.
- Health enthält Taxonomie-Health des Package-Validators.
- Import-Cache ist explizit leerbar.
- Lazy-Exports bleiben rückwärtskompatibel.
"""

from __future__ import annotations

import importlib
import traceback
from dataclasses import asdict, dataclass, field, is_dataclass
from datetime import datetime, timezone
from threading import RLock
from types import ModuleType
from typing import Any, Final, Iterable, Mapping


# ---------------------------------------------------------------------------
# Package metadata
# ---------------------------------------------------------------------------

VALIDATION_PACKAGE_VERSION: Final[str] = "0.2.0"
VALIDATION_PACKAGE_NAME: Final[str] = "library.validation"
VALIDATION_COMPONENT_NAME: Final[str] = "creative-library-validation"

VALIDATION_MODULES: Final[tuple[str, ...]] = (
    "library_package_validator",
)

REQUIRED_VALIDATION_MODULES: Final[tuple[str, ...]] = (
    "library_package_validator",
)


# ---------------------------------------------------------------------------
# Symbol registry
# ---------------------------------------------------------------------------

SYMBOL_TO_MODULE: Final[dict[str, str]] = {
    # -----------------------------------------------------------------------
    # library_package_validator.py constants
    # -----------------------------------------------------------------------
    "LIBRARY_PACKAGE_VALIDATOR_VERSION": "library_package_validator",
    "LIBRARY_PACKAGE_VALIDATOR_COMPONENT": "library_package_validator",
    "DEFAULT_VALIDATION_MODE": "library_package_validator",
    "DEFAULT_VALIDATION_STATUS": "library_package_validator",
    "DEFAULT_OBJECT_KIND_FALLBACK": "library_package_validator",
    "DEFAULT_VARIANT_ID_FALLBACK": "library_package_validator",
    "REQUIRED_TAXONOMY_FIELDS": "library_package_validator",
    "CANONICAL_SOURCE_DEPTH": "library_package_validator",
    "LEGACY_SOURCE_DEPTH": "library_package_validator",
    "STABLE_LIBRARY_ID_PATTERN": "library_package_validator",
    "RECOMMENDED_ID_PREFIXES": "library_package_validator",
    "VALID_ISSUE_LEVELS": "library_package_validator",
    "VALID_VALIDATION_STATUSES": "library_package_validator",
    "MIN_REQUIRED_DOCUMENT_KEYS": "library_package_validator",
    "RECOMMENDED_DOCUMENT_KEYS": "library_package_validator",
    "TECHNICAL_OBJECT_REQUIRED_DOCUMENTS": "library_package_validator",
    "VISIBLE_LIBRARY_RECOMMENDED_DOCUMENTS": "library_package_validator",
    "TECHNICAL_OBJECT_KINDS": "library_package_validator",

    # -----------------------------------------------------------------------
    # library_package_validator.py enums/classes
    # -----------------------------------------------------------------------
    "LibraryValidationIssueLevel": "library_package_validator",
    "LibraryPackageValidationStatus": "library_package_validator",
    "LibraryValidationIssue": "library_package_validator",
    "LibraryPackageValidatorOptions": "library_package_validator",
    "VplibValidationAdapterResult": "library_package_validator",
    "LibraryPackageValidationResult": "library_package_validator",

    # -----------------------------------------------------------------------
    # library_package_validator.py generic helpers
    # -----------------------------------------------------------------------
    "utc_now_iso": "library_package_validator",
    "exception_to_dict": "library_package_validator",
    "json_safe": "library_package_validator",
    "tuple_of_strings": "library_package_validator",
    "get_attr_or_key": "library_package_validator",
    "normalize_issue_level": "library_package_validator",
    "normalize_validation_status": "library_package_validator",
    "normalize_document_key": "library_package_validator",
    "has_document": "library_package_validator",
    "get_document": "library_package_validator",

    # -----------------------------------------------------------------------
    # library_package_validator.py extraction helpers
    # -----------------------------------------------------------------------
    "variant_id_from_any": "library_package_validator",
    "extract_variant_ids_from_documents": "library_package_validator",
    "extract_default_variant_id_from_documents": "library_package_validator",
    "extract_classification_from_documents": "library_package_validator",
    "extract_source_path_from_documents": "library_package_validator",
    "extract_family_slug_from_documents": "library_package_validator",
    "extract_object_kind_from_documents": "library_package_validator",
    "extract_label_from_documents": "library_package_validator",

    # -----------------------------------------------------------------------
    # library_package_validator.py identity/path/taxonomy helpers
    # -----------------------------------------------------------------------
    "is_stable_library_id": "library_package_validator",
    "has_recommended_id_prefix": "library_package_validator",
    "normalize_source_path_string": "library_package_validator",
    "normalize_source_path_parts": "library_package_validator",
    "infer_taxonomy_source_path_from_package_root": "library_package_validator",
    "taxonomy_issues_to_library_issues": "library_package_validator",

    # -----------------------------------------------------------------------
    # library_package_validator.py issue helpers
    # -----------------------------------------------------------------------
    "normalize_issues": "library_package_validator",
    "issue_from_exception": "library_package_validator",
    "demote_vplib_issues_for_non_strict_mode": "library_package_validator",

    # -----------------------------------------------------------------------
    # library_package_validator.py adapter
    # -----------------------------------------------------------------------
    "run_vplib_validation_adapter": "library_package_validator",

    # -----------------------------------------------------------------------
    # library_package_validator.py validation rules
    # -----------------------------------------------------------------------
    "validate_required_documents": "library_package_validator",
    "validate_recommended_documents": "library_package_validator",
    "validate_identity_rules": "library_package_validator",
    "validate_object_kind_rules": "library_package_validator",
    "validate_classification_rules": "library_package_validator",
    "validate_taxonomy_rules": "library_package_validator",
    "validate_variant_rules": "library_package_validator",
    "validate_visible_library_rules": "library_package_validator",
    "validate_module_rules": "library_package_validator",

    # -----------------------------------------------------------------------
    # library_package_validator.py main validation API
    # -----------------------------------------------------------------------
    "validate_library_documents": "library_package_validator",
    "validate_read_result": "library_package_validator",
    "validate_read_results": "library_package_validator",
    "validation_result_to_item_validation_summary": "library_package_validator",
    "validation_result_to_status": "library_package_validator",
    "build_validation_response": "library_package_validator",
    "build_many_validation_response": "library_package_validator",

    # -----------------------------------------------------------------------
    # library_package_validator.py health
    # -----------------------------------------------------------------------
    "get_import_status": "library_package_validator",
    "get_taxonomy_health": "library_package_validator",
    "get_library_package_validator_health": "library_package_validator",
    "assert_library_package_validator_ready": "library_package_validator",
}


# ---------------------------------------------------------------------------
# Internal import cache
# ---------------------------------------------------------------------------

_IMPORT_CACHE_LOCK = RLock()
_MODULE_CACHE: dict[str, ModuleType] = {}


# ---------------------------------------------------------------------------
# Dataclasses
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class ValidationModuleStatus:
    """Importstatus eines Validation-Submoduls."""

    name: str
    import_path: str
    loaded: bool
    status: str
    required: bool = False
    symbol_count: int = 0
    exported_symbols: tuple[str, ...] = field(default_factory=tuple)
    error: dict[str, Any] | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "import_path": self.import_path,
            "loaded": self.loaded,
            "status": self.status,
            "required": self.required,
            "symbol_count": self.symbol_count,
            "exported_symbols": list(self.exported_symbols),
            "error": json_safe(self.error),
        }


@dataclass(frozen=True)
class ValidationHealth:
    """Health-Modell für `library.validation`."""

    ok: bool
    healthy: bool
    package: str
    component: str
    version: str
    generated_at: str
    module_count: int
    loaded_module_count: int
    failed_module_count: int
    required_module_count: int
    loaded_required_module_count: int
    symbol_count: int
    modules: dict[str, dict[str, Any]]
    subhealth: dict[str, dict[str, Any]] = field(default_factory=dict)
    taxonomy: dict[str, Any] = field(default_factory=dict)
    warnings: tuple[str, ...] = field(default_factory=tuple)
    errors: tuple[str, ...] = field(default_factory=tuple)

    def to_dict(self) -> dict[str, Any]:
        return {
            "ok": self.ok,
            "healthy": self.healthy,
            "package": self.package,
            "component": self.component,
            "version": self.version,
            "generated_at": self.generated_at,
            "module_count": self.module_count,
            "loaded_module_count": self.loaded_module_count,
            "failed_module_count": self.failed_module_count,
            "required_module_count": self.required_module_count,
            "loaded_required_module_count": self.loaded_required_module_count,
            "symbol_count": self.symbol_count,
            "modules": json_safe(self.modules),
            "subhealth": json_safe(self.subhealth),
            "taxonomy": json_safe(self.taxonomy),
            "warnings": list(self.warnings),
            "errors": list(self.errors),
        }


# ---------------------------------------------------------------------------
# Generic helpers
# ---------------------------------------------------------------------------

def utc_now_iso() -> str:
    """UTC-Zeit im ISO-Format."""
    try:
        return datetime.now(timezone.utc).isoformat()
    except Exception:
        return datetime.utcnow().replace(tzinfo=timezone.utc).isoformat()


def exception_to_dict(
    exc: BaseException | None,
    *,
    include_traceback: bool = False,
) -> dict[str, Any] | None:
    """Serialisiert Exceptions JSON-kompatibel."""
    if exc is None:
        return None

    try:
        data: dict[str, Any] = {
            "type": exc.__class__.__name__,
            "message": str(exc),
        }

        if include_traceback:
            data["traceback"] = traceback.format_exception(
                type(exc),
                exc,
                exc.__traceback__,
            )

        return data

    except Exception as serialization_exc:
        return {
            "type": "ExceptionSerializationError",
            "message": str(serialization_exc),
            "original_type": str(type(exc)),
        }


def json_safe(value: Any) -> Any:
    """Defensiver JSON-Safe-Konverter."""
    try:
        if value is None:
            return None

        if isinstance(value, (str, int, float, bool)):
            return value

        if is_dataclass(value):
            return json_safe(asdict(value))

        if isinstance(value, Mapping):
            return {str(key): json_safe(item) for key, item in value.items()}

        if isinstance(value, (list, tuple, set)):
            return [json_safe(item) for item in value]

        if isinstance(value, ModuleType):
            return {
                "module": value.__name__,
                "file": getattr(value, "__file__", None),
            }

        to_dict = getattr(value, "to_dict", None)
        if callable(to_dict):
            try:
                return json_safe(to_dict())
            except TypeError:
                return json_safe(to_dict(flat=True))

        return str(value)

    except Exception as exc:
        return {
            "serialization_error": exception_to_dict(exc),
            "fallback_type": str(type(value)),
        }


def dataclass_to_dict_safe(value: Any) -> dict[str, Any]:
    """Defensive Dataclass-/Mapping-Serialisierung."""
    try:
        if hasattr(value, "to_dict") and callable(value.to_dict):
            raw = value.to_dict()
            return dict(raw) if isinstance(raw, Mapping) else {"value": json_safe(raw)}
    except Exception:
        pass

    try:
        if hasattr(value, "__dataclass_fields__"):
            return json_safe(asdict(value))
    except Exception:
        pass

    if isinstance(value, Mapping):
        return dict(json_safe(value))

    return {"value": str(value)}


def safe_tuple(value: Any) -> tuple[Any, ...]:
    """Normalisiert Werte defensiv zu tuple."""
    if value is None:
        return ()

    if isinstance(value, tuple):
        return value

    if isinstance(value, str):
        return (value,)

    if isinstance(value, Iterable):
        try:
            return tuple(value)
        except Exception:
            return ()

    return (value,)


def build_module_import_path(module_name: str) -> str:
    """Baut den vollständigen Importpfad eines Validation-Submoduls."""
    return f"{__name__}.{module_name}"


def clear_validation_import_cache() -> None:
    """Leert den lokalen Lazy-Import-Cache dieses Packages."""
    with _IMPORT_CACHE_LOCK:
        _MODULE_CACHE.clear()

    for symbol_name in tuple(SYMBOL_TO_MODULE.keys()):
        globals().pop(symbol_name, None)


def safe_import_module(
    module_name: str,
    *,
    include_traceback: bool = False,
    force_reload: bool = False,
) -> tuple[ModuleType | None, ValidationModuleStatus]:
    """
    Importiert ein Validation-Submodul defensiv.

    Rückgabe:
      (module, status)
    """

    import_path = build_module_import_path(module_name)
    required = module_name in REQUIRED_VALIDATION_MODULES

    try:
        with _IMPORT_CACHE_LOCK:
            if not force_reload and module_name in _MODULE_CACHE:
                module = _MODULE_CACHE[module_name]
            else:
                module = importlib.import_module(import_path)
                _MODULE_CACHE[module_name] = module

        exported_symbols = tuple(
            str(symbol)
            for symbol in safe_tuple(getattr(module, "__all__", ()))
        )

        return module, ValidationModuleStatus(
            name=module_name,
            import_path=import_path,
            loaded=True,
            status="loaded",
            required=required,
            symbol_count=len(exported_symbols),
            exported_symbols=exported_symbols,
            error=None,
        )

    except Exception as exc:
        return None, ValidationModuleStatus(
            name=module_name,
            import_path=import_path,
            loaded=False,
            status="error",
            required=required,
            symbol_count=0,
            exported_symbols=(),
            error=exception_to_dict(exc, include_traceback=include_traceback),
        )


def _status_is_healthy(payload: Mapping[str, Any]) -> bool:
    """Defensiver Health-Flag-Leser."""
    try:
        if "healthy" in payload:
            return bool(payload.get("healthy"))

        if "ok" in payload:
            return bool(payload.get("ok"))

        return False
    except Exception:
        return False


def _extract_taxonomy_health_from_subhealth(subhealth: Mapping[str, Any]) -> dict[str, Any]:
    """Extrahiert Taxonomie-Health aus Validator-Subhealth."""
    validator = subhealth.get("library_package_validator")
    if not isinstance(validator, Mapping):
        return {
            "available": None,
            "healthy": None,
            "status": "unknown",
        }

    taxonomy = validator.get("taxonomy")
    if isinstance(taxonomy, Mapping):
        return dict(json_safe(taxonomy))

    imports = validator.get("imports")
    if isinstance(imports, Mapping):
        taxonomy_import = imports.get("taxonomy")
        if isinstance(taxonomy_import, Mapping):
            return {
                "available": bool(taxonomy_import.get("ok")),
                "healthy": bool(taxonomy_import.get("ok")),
                "status": "import_only",
                "import": dict(json_safe(taxonomy_import)),
            }

    return {
        "available": None,
        "healthy": None,
        "status": "not_reported",
    }


# ---------------------------------------------------------------------------
# Health
# ---------------------------------------------------------------------------

def get_validation_module_status(
    *,
    include_traceback: bool = False,
    force_reload: bool = False,
) -> dict[str, dict[str, Any]]:
    """Liefert den Importstatus aller Validation-Submodule."""
    statuses: dict[str, dict[str, Any]] = {}

    for module_name in VALIDATION_MODULES:
        _, status = safe_import_module(
            module_name,
            include_traceback=include_traceback,
            force_reload=force_reload,
        )
        statuses[module_name] = status.to_dict()

    return statuses


def get_validation_subhealth(
    *,
    include_traceback: bool = False,
    force_reload: bool = False,
) -> dict[str, dict[str, Any]]:
    """Ruft optionale Health-Funktionen der Validation-Submodule auf."""
    subhealth: dict[str, dict[str, Any]] = {}

    health_functions = {
        "library_package_validator": "get_library_package_validator_health",
    }

    for module_name, function_name in health_functions.items():
        try:
            module, status = safe_import_module(
                module_name,
                include_traceback=include_traceback,
                force_reload=force_reload,
            )

            if module is None:
                subhealth[module_name] = {
                    "ok": False,
                    "healthy": False,
                    "status": "import_error",
                    "required": module_name in REQUIRED_VALIDATION_MODULES,
                    "error": status.error,
                }
                continue

            health_function = getattr(module, function_name, None)

            if not callable(health_function):
                subhealth[module_name] = {
                    "ok": False,
                    "healthy": False,
                    "status": "missing_health_function",
                    "required": module_name in REQUIRED_VALIDATION_MODULES,
                    "function": function_name,
                }
                continue

            try:
                health = health_function()
            except TypeError:
                health = health_function(include_traceback=include_traceback)

            health_payload = dataclass_to_dict_safe(health)
            health_payload.setdefault("required", module_name in REQUIRED_VALIDATION_MODULES)
            subhealth[module_name] = health_payload

        except Exception as exc:
            subhealth[module_name] = {
                "ok": False,
                "healthy": False,
                "status": "health_error",
                "required": module_name in REQUIRED_VALIDATION_MODULES,
                "error": exception_to_dict(exc, include_traceback=include_traceback),
            }

    return subhealth


def get_validation_health(
    *,
    include_traceback: bool = False,
    include_subhealth: bool = True,
    force_reload: bool = False,
) -> dict[str, Any]:
    """Liefert einen robusten Health-Status der Validation-Schicht."""

    module_statuses = get_validation_module_status(
        include_traceback=include_traceback,
        force_reload=force_reload,
    )

    loaded_modules = [
        name
        for name, status in module_statuses.items()
        if status.get("loaded") is True
    ]

    failed_modules = [
        name
        for name, status in module_statuses.items()
        if status.get("loaded") is not True
    ]

    loaded_required_modules = [
        name
        for name in REQUIRED_VALIDATION_MODULES
        if name in loaded_modules
    ]

    warnings: list[str] = []
    errors: list[str] = []

    for module_name in failed_modules:
        errors.append(f"validation module failed to import: {module_name}")

    missing_required = [
        name
        for name in REQUIRED_VALIDATION_MODULES
        if name not in loaded_required_modules
    ]

    for module_name in missing_required:
        errors.append(f"required validation module is not loaded: {module_name}")

    symbol_count = 0

    for status in module_statuses.values():
        try:
            symbol_count += int(status.get("symbol_count", 0))
        except Exception:
            continue

    subhealth: dict[str, dict[str, Any]] = {}

    if include_subhealth:
        subhealth = get_validation_subhealth(
            include_traceback=include_traceback,
            force_reload=force_reload,
        )

        for name, health in subhealth.items():
            if not _status_is_healthy(health):
                errors.append(f"validation subhealth failed: {name}")

    taxonomy = _extract_taxonomy_health_from_subhealth(subhealth)

    if taxonomy.get("healthy") is False:
        errors.append("taxonomy validation dependency is not healthy")

    healthy = len(errors) == 0

    health = ValidationHealth(
        ok=healthy,
        healthy=healthy,
        package=VALIDATION_PACKAGE_NAME,
        component=VALIDATION_COMPONENT_NAME,
        version=VALIDATION_PACKAGE_VERSION,
        generated_at=utc_now_iso(),
        module_count=len(VALIDATION_MODULES),
        loaded_module_count=len(loaded_modules),
        failed_module_count=len(failed_modules),
        required_module_count=len(REQUIRED_VALIDATION_MODULES),
        loaded_required_module_count=len(loaded_required_modules),
        symbol_count=symbol_count,
        modules=module_statuses,
        subhealth=subhealth,
        taxonomy=taxonomy,
        warnings=tuple(warnings),
        errors=tuple(errors),
    )

    return health.to_dict()


def is_validation_healthy() -> bool:
    """Boolescher Health-Check."""
    try:
        return bool(get_validation_health().get("healthy"))
    except Exception:
        return False


def assert_validation_ready() -> None:
    """Wirft RuntimeError, wenn die Validation-Schicht nicht bereit ist."""
    health = get_validation_health()

    if health.get("healthy"):
        return

    raise RuntimeError(
        f"library validation is not ready: errors={health.get('errors')}"
    )


# ---------------------------------------------------------------------------
# Lazy re-export API
# ---------------------------------------------------------------------------

def load_validation_symbol(symbol_name: str) -> Any:
    """Lädt ein bekanntes Validation-Symbol aus seinem Zielmodul."""
    module_name = SYMBOL_TO_MODULE.get(symbol_name)

    if not module_name:
        raise AttributeError(f"module {__name__!r} has no attribute {symbol_name!r}")

    module, status = safe_import_module(module_name)

    if module is None:
        raise ImportError(
            f"could not import validation module {module_name!r}: {status.error}"
        )

    try:
        value = getattr(module, symbol_name)
    except AttributeError as exc:
        raise AttributeError(
            f"validation symbol {symbol_name!r} not found in module {module.__name__!r}"
        ) from exc

    globals()[symbol_name] = value

    return value


def preload_validation_symbols(
    *,
    fail_fast: bool = False,
) -> dict[str, Any]:
    """
    Lädt alle bekannten Reexport-Symbole vor.

    Standard:
      fail_fast=False
    """

    loaded: dict[str, str] = {}
    errors: dict[str, dict[str, Any] | None] = {}

    for symbol_name in SYMBOL_TO_MODULE:
        try:
            value = load_validation_symbol(symbol_name)
            loaded[symbol_name] = f"{getattr(value, '__module__', '')}.{getattr(value, '__name__', symbol_name)}"
        except Exception as exc:
            errors[symbol_name] = exception_to_dict(exc)

            if fail_fast:
                raise

    return {
        "ok": not errors,
        "loaded": loaded,
        "errors": errors,
        "loaded_count": len(loaded),
        "error_count": len(errors),
    }


def __getattr__(name: str) -> Any:
    """Lazy-Reexport bekannter Validation-Symbole und Submodule."""
    if name in SYMBOL_TO_MODULE:
        return load_validation_symbol(name)

    if name in VALIDATION_MODULES:
        module, status = safe_import_module(name)
        if module is None:
            raise ImportError(
                f"could not import validation module {name!r}: {status.error}"
            )
        globals()[name] = module
        return module

    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")


def __dir__() -> list[str]:
    """Ergänzt Lazy-Reexport-Symbole in `dir(library.validation)`."""
    names = set(globals().keys())
    names.update(SYMBOL_TO_MODULE.keys())
    names.update(VALIDATION_MODULES)
    return sorted(names)


# ---------------------------------------------------------------------------
# Module access helpers
# ---------------------------------------------------------------------------

def get_validation_module(module_name: str) -> ModuleType | None:
    """Gibt ein Validation-Submodul zurück, falls es importierbar ist."""
    if module_name not in VALIDATION_MODULES:
        return None

    module, _ = safe_import_module(module_name)
    return module


def get_library_package_validator_module() -> ModuleType | None:
    return get_validation_module("library_package_validator")


# ---------------------------------------------------------------------------
# Convenience helpers
# ---------------------------------------------------------------------------

def validate_package_read_result(
    read_result: Any,
    *,
    options: Any = None,
) -> Any:
    """
    Convenience-Wrapper für frühe Service-/Route-Nutzung.

    Ruft intern `validate_read_result` aus `library_package_validator.py` auf.
    """

    validate_read_result = load_validation_symbol("validate_read_result")

    return validate_read_result(
        read_result,
        options=options,
    )


def validate_package_documents(
    documents: Mapping[str, Any] | None,
    *,
    package_root: Any = None,
    read_result: Any = None,
    options: Any = None,
) -> Any:
    """Convenience-Wrapper für direkte Dokumentvalidierung."""
    validate_library_documents = load_validation_symbol("validate_library_documents")

    return validate_library_documents(
        documents,
        package_root=package_root,
        read_result=read_result,
        options=options,
    )


def validate_taxonomy_for_documents(
    documents: Mapping[str, Any] | None,
    *,
    package_root: Any = None,
    options: Any = None,
) -> dict[str, Any]:
    """
    Convenience-Wrapper nur für Taxonomievalidierung.

    Gibt JSON-kompatibles Ergebnis zurück, damit Route-/Debug-Code nicht direkt
    mit internen Issue-Objekten umgehen muss.
    """

    validate_taxonomy_rules = load_validation_symbol("validate_taxonomy_rules")

    issues, metadata = validate_taxonomy_rules(
        documents or {},
        package_root=package_root,
        options=options,
    )

    issue_payloads = [
        issue.to_dict() if hasattr(issue, "to_dict") else json_safe(issue)
        for issue in issues
    ]

    valid = not any(
        isinstance(issue, Mapping) and issue.get("level") in {"error", "fatal"}
        for issue in issue_payloads
    )

    return {
        "ok": valid,
        "valid": valid,
        "issues": issue_payloads,
        "metadata": json_safe(metadata),
    }


def build_validation_payload(
    documents: Mapping[str, Any] | None,
    *,
    package_root: Any = None,
    read_result: Any = None,
    options: Any = None,
) -> dict[str, Any]:
    """Direkte JSON-kompatible Validierungsantwort."""
    result = validate_package_documents(
        documents,
        package_root=package_root,
        read_result=read_result,
        options=options,
    )

    build_validation_response = load_validation_symbol("build_validation_response")

    return build_validation_response(result)


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

__all__: Final[tuple[str, ...]] = (
    "VALIDATION_PACKAGE_VERSION",
    "VALIDATION_PACKAGE_NAME",
    "VALIDATION_COMPONENT_NAME",
    "VALIDATION_MODULES",
    "REQUIRED_VALIDATION_MODULES",
    "SYMBOL_TO_MODULE",
    "ValidationModuleStatus",
    "ValidationHealth",
    "utc_now_iso",
    "exception_to_dict",
    "json_safe",
    "dataclass_to_dict_safe",
    "safe_tuple",
    "build_module_import_path",
    "clear_validation_import_cache",
    "safe_import_module",
    "get_validation_module_status",
    "get_validation_subhealth",
    "get_validation_health",
    "is_validation_healthy",
    "assert_validation_ready",
    "load_validation_symbol",
    "preload_validation_symbols",
    "get_validation_module",
    "get_library_package_validator_module",
    "validate_package_read_result",
    "validate_package_documents",
    "validate_taxonomy_for_documents",
    "build_validation_payload",
    # Reexported validation symbols
    *tuple(SYMBOL_TO_MODULE.keys()),
)