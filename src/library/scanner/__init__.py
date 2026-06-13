# services/vectoplan-library/src/library/scanner/__init__.py
"""
Scanner Package der VECTOPLAN Creative-Library-Schicht.

Dieses Package bündelt die dateibasierten Scanner-Bausteine für
`src/library/source`.

Enthaltene Module:

- `package_discovery.py`
  Findet VPLIB-Package-Kandidaten anhand von Manifest-Dateien und erkennt
  kanonische Taxonomie-Pfade:
      {domain}/{category}/{subcategory}/{family_slug}

- `package_reader.py`
  Liest JSON-Dokumente aus gefundenen Package-Roots und reicht
  Taxonomie-/Discovery-Metadaten an Validator und Read-Models weiter.

- `package_fingerprint.py`
  Erzeugt stabile `revision_hash`-Fingerprints für spätere DB-Upserts.

Diese Scanner-Schicht ist bewusst getrennt von:

- Flask-Routes
- Datenbank
- Persistenz nach `creative_library`
- fachlicher Library-Validierung
- UI-/Admin-Logik

Der Scanner darf lesen und analysieren, aber nicht automatisch schreiben.

Taxonomie-Regel:

    Backend-Taxonomie ist kanonisch für Source-Pfade, Domain/Reiter,
    Kategorie und Subkategorie. Scanner-Module validieren nur soweit nötig,
    um Kandidaten und ReadResults mit ausreichend Kontext weiterzureichen.

Version 0.2.0:

- Reexport-Registry enthält Taxonomie-/Source-Pfad-Symbole aus Discovery und Reader.
- Health zeigt Taxonomie-bezogene Scanner-Fähigkeiten an.
- Import-Cache ist explizit leerbar.
- Package-Import bleibt seiteneffektfrei:
    kein Scan
    kein Dateilesen
    kein Taxonomie-JSON-Load
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

SCANNER_PACKAGE_VERSION: Final[str] = "0.2.0"
SCANNER_PACKAGE_NAME: Final[str] = "library.scanner"
SCANNER_COMPONENT_NAME: Final[str] = "creative-library-scanner"

SCANNER_MODULES: Final[tuple[str, ...]] = (
    "package_discovery",
    "package_reader",
    "package_fingerprint",
)

REQUIRED_SCANNER_MODULES: Final[tuple[str, ...]] = (
    "package_discovery",
    "package_reader",
    "package_fingerprint",
)


# ---------------------------------------------------------------------------
# Symbol registry
# ---------------------------------------------------------------------------

SYMBOL_TO_MODULE: Final[dict[str, str]] = {
    # -----------------------------------------------------------------------
    # package_discovery.py
    # -----------------------------------------------------------------------
    "PACKAGE_DISCOVERY_VERSION": "package_discovery",
    "PACKAGE_DISCOVERY_COMPONENT": "package_discovery",
    "DEFAULT_DISCOVERY_MODE": "package_discovery",
    "DEFAULT_DISCOVERY_STATUS": "package_discovery",
    "PACKAGE_MARKER_REASON_MANIFEST": "package_discovery",
    "PACKAGE_MARKER_REASON_SKIPPED_IGNORED_DIR": "package_discovery",
    "PACKAGE_MARKER_REASON_SKIPPED_MAX_DEPTH": "package_discovery",
    "PACKAGE_MARKER_REASON_SKIPPED_SYMLINK": "package_discovery",
    "PACKAGE_MARKER_REASON_SKIPPED_NOT_DIRECTORY": "package_discovery",
    "PACKAGE_MARKER_REASON_SKIPPED_OUTSIDE_SOURCE_ROOT": "package_discovery",
    "PACKAGE_MARKER_REASON_SKIPPED_SYMLINK_LOOP": "package_discovery",
    "PACKAGE_MARKER_REASON_SKIPPED_LEGACY": "package_discovery",
    "VALID_DISCOVERY_STATUSES": "package_discovery",
    "VALID_DISCOVERY_CANDIDATE_STATUSES": "package_discovery",
    "DEFAULT_ALLOWED_MANIFEST_FILENAMES_FALLBACK": "package_discovery",
    "DEFAULT_IGNORED_DIRECTORY_NAMES_FALLBACK": "package_discovery",
    "DEFAULT_SCAN_FOLLOW_SYMLINKS_FALLBACK": "package_discovery",
    "DEFAULT_SCAN_MAX_DEPTH_FALLBACK": "package_discovery",
    "DEFAULT_SCAN_RECURSIVE_FALLBACK": "package_discovery",
    "DEFAULT_INCLUDE_LEGACY_SOURCE_LAYOUT_FALLBACK": "package_discovery",
    "DEFAULT_VALIDATE_TAXONOMY_PATH_FALLBACK": "package_discovery",
    "DEFAULT_READ_MINIMAL_METADATA_FALLBACK": "package_discovery",
    "MAX_SCAN_DEPTH_HARD_LIMIT": "package_discovery",
    "CANONICAL_SOURCE_DEPTH": "package_discovery",
    "LEGACY_SOURCE_DEPTH": "package_discovery",
    "SOURCE_LAYOUT_CANONICAL": "package_discovery",
    "SOURCE_LAYOUT_LEGACY": "package_discovery",
    "SOURCE_LAYOUT_UNKNOWN": "package_discovery",
    "SOURCE_ROOT_ENV_NAMES": "package_discovery",
    "PackageDiscoveryOptions": "package_discovery",
    "PackageDiscoveryMessage": "package_discovery",
    "PackageDiscoveryCandidate": "package_discovery",
    "PackageDiscoveryResult": "package_discovery",
    "taxonomy_available": "package_discovery",
    "normalize_taxonomy_part": "package_discovery",
    "normalize_source_path_parts": "package_discovery",
    "normalize_source_path_string": "package_discovery",
    "infer_source_layout": "package_discovery",
    "taxonomy_from_relative_path": "package_discovery",
    "read_json_object": "package_discovery",
    "read_minimal_package_metadata": "package_discovery",
    "build_taxonomy_discovery_metadata": "package_discovery",
    "normalize_manifest_filenames": "package_discovery",
    "normalize_ignored_directory_names": "package_discovery",
    "normalize_discovery_status": "package_discovery",
    "normalize_candidate_status": "package_discovery",
    "normalize_source_layout": "package_discovery",
    "directory_name_is_ignored": "package_discovery",
    "find_manifest_file": "package_discovery",
    "coerce_discovery_options": "package_discovery",
    "make_scan_candidate": "package_discovery",
    "should_skip_directory": "package_discovery",
    "make_skipped_candidate": "package_discovery",
    "iter_child_directories": "package_discovery",
    "discover_package_candidates": "package_discovery",
    "discover_library_packages": "package_discovery",
    "discover_package_roots": "package_discovery",
    "discover_manifest_paths": "package_discovery",
    "get_package_discovery_health": "package_discovery",
    "assert_package_discovery_ready": "package_discovery",

    # -----------------------------------------------------------------------
    # package_reader.py
    # -----------------------------------------------------------------------
    "PACKAGE_READER_VERSION": "package_reader",
    "PACKAGE_READER_COMPONENT": "package_reader",
    "DEFAULT_READER_STATUS": "package_reader",
    "DEFAULT_TEXT_ENCODING": "package_reader",
    "DEFAULT_MAX_JSON_FILE_SIZE_BYTES": "package_reader",
    "MAX_JSON_FILE_SIZE_BYTES_HARD_LIMIT": "package_reader",
    "DEFAULT_READ_ALL_JSON_DOCUMENTS": "package_reader",
    "DEFAULT_INCLUDE_OPTIONAL_SUMMARY_FILES": "package_reader",
    "DEFAULT_FAIL_ON_JSON_ERROR": "package_reader",
    "DEFAULT_FAIL_ON_MISSING_REQUIRED": "package_reader",
    "JSON_SUFFIX": "package_reader",
    "TAXONOMY_REQUIRED_READER_FILES": "package_reader",
    "PackageReaderOptions": "package_reader",
    "PackageReadMessage": "package_reader",
    "PackageDocument": "package_reader",
    "PackageReadResult": "package_reader",
    "normalize_document_key": "package_reader",
    "normalize_documents": "package_reader",
    "normalize_reader_status": "package_reader",
    "normalize_candidate_id": "package_reader",
    "normalize_taxonomy_slug": "package_reader",
    "infer_source_layout": "package_reader",
    "taxonomy_from_relative_path": "package_reader",
    "extract_classification_from_documents": "package_reader",
    "extract_family_slug_from_documents": "package_reader",
    "build_reader_taxonomy_metadata": "package_reader",
    "normalize_required_files": "package_reader",
    "normalize_optional_files": "package_reader",
    "normalize_ignored_file_suffixes": "package_reader",
    "document_key_to_path": "package_reader",
    "path_to_document_key": "package_reader",
    "is_ignored_file": "package_reader",
    "is_ignored_directory": "package_reader",
    "extract_label_from_documents": "package_reader",
    "extract_object_kind_from_documents": "package_reader",
    "coerce_reader_options": "package_reader",
    "make_scan_candidate": "package_reader",
    "iter_json_files": "package_reader",
    "collect_document_keys_to_read": "package_reader",
    "read_json_document": "package_reader",
    "read_package_root": "package_reader",
    "discovery_candidate_to_metadata": "package_reader",
    "read_discovery_candidate": "package_reader",
    "read_package_candidates": "package_reader",
    "read_package_path": "package_reader",
    "read_result_to_document_mapping": "package_reader",
    "read_results_to_scan_candidates": "package_reader",
    "build_read_response": "package_reader",
    "build_read_many_response": "package_reader",
    "get_package_reader_health": "package_reader",
    "assert_package_reader_ready": "package_reader",

    # -----------------------------------------------------------------------
    # package_fingerprint.py
    # -----------------------------------------------------------------------
    "PACKAGE_FINGERPRINT_VERSION": "package_fingerprint",
    "PACKAGE_FINGERPRINT_COMPONENT": "package_fingerprint",
    "DEFAULT_HASH_ALGORITHM": "package_fingerprint",
    "FINGERPRINT_SCHEMA_VERSION": "package_fingerprint",
    "PackageFingerprintOptions": "package_fingerprint",
    "FingerprintedFile": "package_fingerprint",
    "PackageFingerprintResult": "package_fingerprint",
    "stable_json_dumps": "package_fingerprint",
    "hash_bytes": "package_fingerprint",
    "hash_text": "package_fingerprint",
    "hash_loaded_documents": "package_fingerprint",
    "fingerprint_package_root": "package_fingerprint",
    "fingerprint_read_result": "package_fingerprint",
    "fingerprint_documents_only": "package_fingerprint",
    "attach_fingerprint_to_read_result_dict": "package_fingerprint",
    "get_package_fingerprint_health": "package_fingerprint",
    "assert_package_fingerprint_ready": "package_fingerprint",
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
class ScannerModuleStatus:
    """Importstatus eines Scanner-Submoduls."""

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
class ScannerHealth:
    """Health-Modell für `library.scanner`."""

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
    taxonomy_capabilities: dict[str, Any] = field(default_factory=dict)
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
            "taxonomy_capabilities": json_safe(self.taxonomy_capabilities),
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
    """Baut den vollständigen Importpfad eines Scanner-Submoduls."""
    return f"{__name__}.{module_name}"


def clear_scanner_import_cache() -> None:
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
) -> tuple[ModuleType | None, ScannerModuleStatus]:
    """
    Importiert ein Scanner-Submodul defensiv.

    Rückgabe:
      (module, status)
    """

    import_path = build_module_import_path(module_name)
    required = module_name in REQUIRED_SCANNER_MODULES

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

        return module, ScannerModuleStatus(
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
        return None, ScannerModuleStatus(
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
    """Sammelt Taxonomiehinweise aus Discovery-/Reader-Health."""
    result: dict[str, Any] = {
        "discovery_taxonomy_available": None,
        "reader_taxonomy_import_ok": None,
        "canonical_source_depth": None,
        "legacy_source_depth": None,
        "source_layouts": {
            "canonical": "canonical",
            "legacy": "legacy",
            "unknown": "unknown",
        },
    }

    discovery = subhealth.get("package_discovery")
    if isinstance(discovery, Mapping):
        taxonomy = discovery.get("taxonomy")
        if isinstance(taxonomy, Mapping):
            result["discovery_taxonomy_available"] = taxonomy.get("available")
        if discovery.get("canonical_source_depth") is not None:
            result["canonical_source_depth"] = discovery.get("canonical_source_depth")
        if discovery.get("legacy_source_depth") is not None:
            result["legacy_source_depth"] = discovery.get("legacy_source_depth")

    reader = subhealth.get("package_reader")
    if isinstance(reader, Mapping):
        imports = reader.get("imports")
        if isinstance(imports, Mapping):
            taxonomy_import = imports.get("taxonomy")
            if isinstance(taxonomy_import, Mapping):
                result["reader_taxonomy_import_ok"] = taxonomy_import.get("ok")
        if reader.get("canonical_source_depth") is not None:
            result["canonical_source_depth"] = reader.get("canonical_source_depth")
        if reader.get("legacy_source_depth") is not None:
            result["legacy_source_depth"] = reader.get("legacy_source_depth")

    return result


# ---------------------------------------------------------------------------
# Health
# ---------------------------------------------------------------------------

def get_scanner_module_status(
    *,
    include_traceback: bool = False,
    force_reload: bool = False,
) -> dict[str, dict[str, Any]]:
    """Liefert den Importstatus aller Scanner-Submodule."""
    statuses: dict[str, dict[str, Any]] = {}

    for module_name in SCANNER_MODULES:
        _, status = safe_import_module(
            module_name,
            include_traceback=include_traceback,
            force_reload=force_reload,
        )
        statuses[module_name] = status.to_dict()

    return statuses


def get_scanner_subhealth(
    *,
    include_traceback: bool = False,
    force_reload: bool = False,
) -> dict[str, dict[str, Any]]:
    """Ruft optionale Health-Funktionen der Scanner-Submodule auf."""
    subhealth: dict[str, dict[str, Any]] = {}

    health_functions = {
        "package_discovery": "get_package_discovery_health",
        "package_reader": "get_package_reader_health",
        "package_fingerprint": "get_package_fingerprint_health",
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
                    "required": module_name in REQUIRED_SCANNER_MODULES,
                    "error": status.error,
                }
                continue

            health_function = getattr(module, function_name, None)

            if not callable(health_function):
                subhealth[module_name] = {
                    "ok": False,
                    "healthy": False,
                    "status": "missing_health_function",
                    "required": module_name in REQUIRED_SCANNER_MODULES,
                    "function": function_name,
                }
                continue

            try:
                health = health_function()
            except TypeError:
                health = health_function(include_traceback=include_traceback)

            health_payload = dataclass_to_dict_safe(health)
            health_payload.setdefault("required", module_name in REQUIRED_SCANNER_MODULES)
            subhealth[module_name] = health_payload

        except Exception as exc:
            subhealth[module_name] = {
                "ok": False,
                "healthy": False,
                "status": "health_error",
                "required": module_name in REQUIRED_SCANNER_MODULES,
                "error": exception_to_dict(exc, include_traceback=include_traceback),
            }

    return subhealth


def get_scanner_health(
    *,
    include_traceback: bool = False,
    include_subhealth: bool = True,
    force_reload: bool = False,
) -> dict[str, Any]:
    """Liefert einen robusten Health-Status der Scanner-Schicht."""

    module_statuses = get_scanner_module_status(
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
        for name in REQUIRED_SCANNER_MODULES
        if name in loaded_modules
    ]

    warnings: list[str] = []
    errors: list[str] = []

    for module_name in failed_modules:
        errors.append(f"scanner module failed to import: {module_name}")

    missing_required = [
        name
        for name in REQUIRED_SCANNER_MODULES
        if name not in loaded_required_modules
    ]

    for module_name in missing_required:
        errors.append(f"required scanner module is not loaded: {module_name}")

    symbol_count = 0

    for status in module_statuses.values():
        try:
            symbol_count += int(status.get("symbol_count", 0))
        except Exception:
            continue

    subhealth: dict[str, dict[str, Any]] = {}

    if include_subhealth:
        subhealth = get_scanner_subhealth(
            include_traceback=include_traceback,
            force_reload=force_reload,
        )

        for name, health in subhealth.items():
            if not _status_is_healthy(health):
                errors.append(f"scanner subhealth failed: {name}")

    taxonomy_capabilities = _extract_taxonomy_health_from_subhealth(subhealth)

    healthy = len(errors) == 0

    health = ScannerHealth(
        ok=healthy,
        healthy=healthy,
        package=SCANNER_PACKAGE_NAME,
        component=SCANNER_COMPONENT_NAME,
        version=SCANNER_PACKAGE_VERSION,
        generated_at=utc_now_iso(),
        module_count=len(SCANNER_MODULES),
        loaded_module_count=len(loaded_modules),
        failed_module_count=len(failed_modules),
        required_module_count=len(REQUIRED_SCANNER_MODULES),
        loaded_required_module_count=len(loaded_required_modules),
        symbol_count=symbol_count,
        modules=module_statuses,
        subhealth=subhealth,
        taxonomy_capabilities=taxonomy_capabilities,
        warnings=tuple(warnings),
        errors=tuple(errors),
    )

    return health.to_dict()


def is_scanner_healthy() -> bool:
    """Boolescher Health-Check."""
    try:
        return bool(get_scanner_health().get("healthy"))
    except Exception:
        return False


def assert_scanner_ready() -> None:
    """Wirft RuntimeError, wenn die Scanner-Schicht nicht bereit ist."""
    health = get_scanner_health()

    if health.get("healthy"):
        return

    raise RuntimeError(
        f"library scanner is not ready: errors={health.get('errors')}"
    )


# ---------------------------------------------------------------------------
# Lazy re-export API
# ---------------------------------------------------------------------------

def load_scanner_symbol(symbol_name: str) -> Any:
    """Lädt ein bekanntes Scanner-Symbol aus seinem Zielmodul."""
    module_name = SYMBOL_TO_MODULE.get(symbol_name)

    if not module_name:
        raise AttributeError(f"module {__name__!r} has no attribute {symbol_name!r}")

    module, status = safe_import_module(module_name)

    if module is None:
        raise ImportError(
            f"could not import scanner module {module_name!r}: {status.error}"
        )

    try:
        value = getattr(module, symbol_name)
    except AttributeError as exc:
        raise AttributeError(
            f"scanner symbol {symbol_name!r} not found in module {module.__name__!r}"
        ) from exc

    globals()[symbol_name] = value

    return value


def preload_scanner_symbols(
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
            value = load_scanner_symbol(symbol_name)
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
    """Lazy-Reexport bekannter Scanner-Symbole und Submodule."""
    if name in SYMBOL_TO_MODULE:
        return load_scanner_symbol(name)

    if name in SCANNER_MODULES:
        module, status = safe_import_module(name)
        if module is None:
            raise ImportError(
                f"could not import scanner module {name!r}: {status.error}"
            )
        globals()[name] = module
        return module

    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")


def __dir__() -> list[str]:
    """Ergänzt Lazy-Reexport-Symbole in `dir(library.scanner)`."""
    names = set(globals().keys())
    names.update(SYMBOL_TO_MODULE.keys())
    names.update(SCANNER_MODULES)
    return sorted(names)


# ---------------------------------------------------------------------------
# Module access helpers
# ---------------------------------------------------------------------------

def get_scanner_module(module_name: str) -> ModuleType | None:
    """Gibt ein Scanner-Submodul zurück, falls es importierbar ist."""
    if module_name not in SCANNER_MODULES:
        return None

    module, _ = safe_import_module(module_name)
    return module


def get_package_discovery_module() -> ModuleType | None:
    return get_scanner_module("package_discovery")


def get_package_reader_module() -> ModuleType | None:
    return get_scanner_module("package_reader")


def get_package_fingerprint_module() -> ModuleType | None:
    return get_scanner_module("package_fingerprint")


# ---------------------------------------------------------------------------
# Convenience pipeline helpers
# ---------------------------------------------------------------------------

def discover_and_read_packages(
    *,
    source_root: Any = None,
    discovery_options: Any = None,
    reader_options: Any = None,
) -> dict[str, Any]:
    """
    Kleine Convenience-Pipeline für frühe Tests.

    Führt aus:
      discovery -> reader

    Keine fachliche Validierung.
    Kein Fingerprint.
    Kein Schreiben.
    """

    try:
        discover = load_scanner_symbol("discover_library_packages")
        read_candidates = load_scanner_symbol("read_package_candidates")

        discovery_result = discover(
            source_root=source_root,
            options=discovery_options,
        )

        candidates = getattr(discovery_result, "candidates", ())

        read_results = read_candidates(
            candidates,
            options=reader_options,
        )

        ok_count = sum(1 for result in read_results if getattr(result, "ok", False))
        error_count = sum(1 for result in read_results if getattr(result, "status", None) == "error")

        return {
            "ok": error_count == 0,
            "status": "ok" if error_count == 0 else "partial" if ok_count > 0 else "error",
            "discovery": (
                discovery_result.to_dict()
                if hasattr(discovery_result, "to_dict")
                else dataclass_to_dict_safe(discovery_result)
            ),
            "read": [
                result.to_dict(include_documents=False)
                if hasattr(result, "to_dict")
                else dataclass_to_dict_safe(result)
                for result in read_results
            ],
            "count": len(read_results),
            "ok_count": ok_count,
            "error_count": error_count,
            "taxonomy": {
                "canonical_source_depth": 4,
                "legacy_source_depth": 3,
                "source_path_pattern": "{domain}/{category}/{subcategory}/{family_slug}",
            },
        }

    except Exception as exc:
        return {
            "ok": False,
            "status": "error",
            "error": exception_to_dict(exc),
        }


def discover_read_and_fingerprint_packages(
    *,
    source_root: Any = None,
    discovery_options: Any = None,
    reader_options: Any = None,
    fingerprint_options: Any = None,
) -> dict[str, Any]:
    """
    Convenience-Pipeline für frühe Tests.

    Führt aus:
      discovery -> reader -> fingerprint

    Keine fachliche Validierung.
    Kein Schreiben.
    """

    try:
        discover = load_scanner_symbol("discover_library_packages")
        read_candidates = load_scanner_symbol("read_package_candidates")
        fingerprint_read = load_scanner_symbol("fingerprint_read_result")

        discovery_result = discover(
            source_root=source_root,
            options=discovery_options,
        )

        candidates = getattr(discovery_result, "candidates", ())
        read_results = read_candidates(
            candidates,
            options=reader_options,
        )

        fingerprint_results = [
            fingerprint_read(
                read_result,
                options=fingerprint_options,
            )
            for read_result in read_results
        ]

        ok_count = sum(1 for result in fingerprint_results if getattr(result, "ok", False))
        error_count = sum(1 for result in fingerprint_results if getattr(result, "status", None) == "error")

        return {
            "ok": error_count == 0,
            "status": "ok" if error_count == 0 else "partial" if ok_count > 0 else "error",
            "discovery": (
                discovery_result.to_dict()
                if hasattr(discovery_result, "to_dict")
                else dataclass_to_dict_safe(discovery_result)
            ),
            "items": [
                {
                    "read": (
                        read_result.to_dict(include_documents=False)
                        if hasattr(read_result, "to_dict")
                        else dataclass_to_dict_safe(read_result)
                    ),
                    "fingerprint": (
                        fingerprint_result.to_dict(include_files=False)
                        if hasattr(fingerprint_result, "to_dict")
                        else dataclass_to_dict_safe(fingerprint_result)
                    ),
                }
                for read_result, fingerprint_result in zip(read_results, fingerprint_results)
            ],
            "count": len(read_results),
            "ok_count": ok_count,
            "error_count": error_count,
            "taxonomy": {
                "canonical_source_depth": 4,
                "legacy_source_depth": 3,
                "source_path_pattern": "{domain}/{category}/{subcategory}/{family_slug}",
            },
        }

    except Exception as exc:
        return {
            "ok": False,
            "status": "error",
            "error": exception_to_dict(exc),
        }


def discover_read_fingerprint_documents(
    *,
    source_root: Any = None,
    discovery_options: Any = None,
    reader_options: Any = None,
    fingerprint_options: Any = None,
) -> dict[str, Any]:
    """Alias mit expliziterem Namen für Tests und Debug-Tools."""
    return discover_read_and_fingerprint_packages(
        source_root=source_root,
        discovery_options=discovery_options,
        reader_options=reader_options,
        fingerprint_options=fingerprint_options,
    )


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

__all__: Final[tuple[str, ...]] = (
    "SCANNER_PACKAGE_VERSION",
    "SCANNER_PACKAGE_NAME",
    "SCANNER_COMPONENT_NAME",
    "SCANNER_MODULES",
    "REQUIRED_SCANNER_MODULES",
    "SYMBOL_TO_MODULE",
    "ScannerModuleStatus",
    "ScannerHealth",
    "utc_now_iso",
    "exception_to_dict",
    "json_safe",
    "dataclass_to_dict_safe",
    "safe_tuple",
    "build_module_import_path",
    "clear_scanner_import_cache",
    "safe_import_module",
    "get_scanner_module_status",
    "get_scanner_subhealth",
    "get_scanner_health",
    "is_scanner_healthy",
    "assert_scanner_ready",
    "load_scanner_symbol",
    "preload_scanner_symbols",
    "get_scanner_module",
    "get_package_discovery_module",
    "get_package_reader_module",
    "get_package_fingerprint_module",
    "discover_and_read_packages",
    "discover_read_and_fingerprint_packages",
    "discover_read_fingerprint_documents",
    # Reexported scanner symbols
    *tuple(SYMBOL_TO_MODULE.keys()),
)