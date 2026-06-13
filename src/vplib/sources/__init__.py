# services/vectoplan-library/src/vplib/sources/__init__.py
"""
Public sources API for the VPLIB package engine.

Diese Datei bündelt die stabile Source-Schicht für VPLIB:

- source_scanner
- source_loader

Die Source-Schicht ist für vorbereitete Creative-Library-Objekte gedacht:

    sources/
      wall_24/
        vplib.manifest.json
        vplib.modules.json
        family/identity.json
        variants/default.json
        editor/placement.json
        ...

Typische Einstiegspunkte:
- scan_source_root(...)
- scan_source_package(...)
- load_source_root_to_library(...)
- load_source_candidate_to_library(...)
- result_to_document_bundles(...)

Wichtig für die neue VPLIB-ID-Architektur:
- `source_scanner.py` liest `vplib_uid` aus `vplib.manifest.json`.
- `vplib_uid` ist die technische, unveränderliche Package-ID.
- Der Scanner erzeugt keine neuen IDs.
- Fehlende/ungültige `vplib_uid` macht Kandidaten invalid.
- Doppelte `vplib_uid` im selben Scan werden als Fehler markiert.
- Diese Datei exportiert die neuen `vplib_uid`-Scanner-Hilfen lazy.
- `scan_vplib_sources(...)` validiert `vplib_uid` standardmäßig mit.

Sie ist bewusst robust aufgebaut:
- Imports laufen lazy über __getattr__.
- Einzelne beschädigte Source-Module blockieren nicht sofort das ganze Package.
- Diagnosefunktionen zeigen Importstatus und Fehler.
- Cache-Clear-Funktionen können alle Source-Caches gesammelt leeren.
- Komfort-Aliase wie `scanner`, `loader`, `scan` und `load` sind zusätzliche
  Modulzugriffe und brechen keine bestehende API.

Technische Namen, JSON-Keys und Variablen bleiben Englisch.
"""

from __future__ import annotations

import importlib
from dataclasses import dataclass
from functools import lru_cache
from types import ModuleType
from typing import Any, Final, Mapping


SOURCES_PACKAGE_VERSION: Final[str] = "vplib.sources.v1"
MANIFEST_VPLIB_UID_FIELD: Final[str] = "vplib_uid"


class SourcesImportError(ImportError):
    """Wird ausgelöst, wenn ein Source-Modul oder Source-Symbol nicht geladen werden kann."""


@dataclass(frozen=True, slots=True)
class SourceModuleStatus:
    """Importstatus eines Source-Moduls."""

    module_key: str
    module_path: str
    loaded: bool
    error: str | None
    exported_symbols: tuple[str, ...]

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema_version": SOURCES_PACKAGE_VERSION,
            "module_key": self.module_key,
            "module_path": self.module_path,
            "loaded": self.loaded,
            "error": self.error,
            "exported_symbols": list(self.exported_symbols),
            "exported_symbol_count": len(self.exported_symbols),
        }


_RELATIVE_SOURCE_MODULES: Final[dict[str, str]] = {
    "source_scanner": ".source_scanner",
    "source_loader": ".source_loader",
}


_RELATIVE_SOURCE_MODULE_ALIASES: Final[dict[str, str]] = {
    "scanner": "source_scanner",
    "scan": "source_scanner",
    "loader": "source_loader",
    "load": "source_loader",
}


_SYMBOL_TO_MODULE: Final[dict[str, str]] = {
    # ---------------------------------------------------------------------
    # source_scanner.py
    # ---------------------------------------------------------------------
    "ALLOWED_DOCUMENT_SUFFIXES": "source_scanner",
    "CORE_REQUIRED_DOCUMENTS": "source_scanner",
    "DEFAULT_ENCODING": "source_scanner",
    "DEFAULT_MAX_DEPTH": "source_scanner",
    "IGNORED_DIRECTORY_NAMES": "source_scanner",
    "IGNORED_FILE_NAMES": "source_scanner",
    "MANIFEST_DOCUMENT_PATH": "source_scanner",
    "MANIFEST_VPLIB_UID_FIELD": "source_scanner",
    "MODULES_DOCUMENT_PATH": "source_scanner",
    "ROOT_MARKER_DOCUMENTS": "source_scanner",
    "SOURCE_SCANNER_SCHEMA_VERSION": "source_scanner",
    "SourceCandidateStatus": "source_scanner",
    "SourceDocument": "source_scanner",
    "SourceIssue": "source_scanner",
    "SourceIssueCode": "source_scanner",
    "SourceIssueSeverity": "source_scanner",
    "SourcePackageCandidate": "source_scanner",
    "SourceScanMode": "source_scanner",
    "SourceScanOptions": "source_scanner",
    "SourceScanResult": "source_scanner",
    "SourceScanStatus": "source_scanner",
    "SourceScannerError": "source_scanner",
    "candidate_to_document_bundle": "source_scanner",
    "candidates_to_document_bundles": "source_scanner",
    "clear_source_scanner_caches": "source_scanner",
    "dedupe_issues": "source_scanner",
    "discover_source_candidate_dirs": "source_scanner",
    "discover_source_candidate_dirs_recursive": "source_scanner",
    "get_vplib_uid_from_documents_safe": "source_scanner",
    "get_vplib_uid_from_manifest_safe": "source_scanner",
    "infer_module_from_path_safe": "source_scanner",
    "is_source_candidate_dir": "source_scanner",
    "load_source_documents": "source_scanner",
    "normalize_absolute_path": "source_scanner",
    "normalize_document_mapping": "source_scanner",
    "normalize_enum_key": "source_scanner",
    "normalize_json_value": "source_scanner",
    "normalize_metadata": "source_scanner",
    "normalize_non_negative_int": "source_scanner",
    "normalize_optional_module_name": "source_scanner",
    "normalize_optional_validation_result": "source_scanner",
    "normalize_options": "source_scanner",
    "normalize_package_relative_path": "source_scanner",
    "normalize_source_file_relative_path": "source_scanner",
    "normalize_string_tuple": "source_scanner",
    "normalize_vplib_uid_safe": "source_scanner",
    "object_to_dict": "source_scanner",
    "parse_candidate_status_value": "source_scanner",
    "parse_issue_code_value": "source_scanner",
    "parse_issue_severity_value": "source_scanner",
    "parse_scan_mode_value": "source_scanner",
    "parse_scan_status_value": "source_scanner",
    "read_json_document": "source_scanner",
    "result_to_document_bundles": "source_scanner",
    "safe_relative_to": "source_scanner",
    "scan_source_package": "source_scanner",
    "scan_source_root": "source_scanner",
    "should_include_directory": "source_scanner",
    "should_include_file": "source_scanner",
    "sort_candidates": "source_scanner",
    "sort_documents": "source_scanner",
    "sort_issues": "source_scanner",
    "source_issue": "source_scanner",
    "validate_loaded_documents": "source_scanner",
    "validate_source_package_documents": "source_scanner",
    "validate_source_scan_uniqueness": "source_scanner",
    "validate_source_vplib_uid": "source_scanner",
    "validation_result_is_valid": "source_scanner",

    # ---------------------------------------------------------------------
    # source_loader.py
    # ---------------------------------------------------------------------
    "SOURCE_LOADER_SCHEMA_VERSION": "source_loader",
    "CandidateAssetFile": "source_loader",
    "SourceLoadAction": "source_loader",
    "SourceLoadItemResult": "source_loader",
    "SourceLoadOptions": "source_loader",
    "SourceLoadResult": "source_loader",
    "SourceLoadStatus": "source_loader",
    "SourceLoadTarget": "source_loader",
    "SourceLoadWriteMode": "source_loader",
    "SourceLoaderError": "source_loader",
    "any_result_dry_run": "source_loader",
    "any_result_failed": "source_loader",
    "build_load_target_for_candidate": "source_loader",
    "copy_candidate_assets": "source_loader",
    "create_candidate_archive": "source_loader",
    "determine_load_action": "source_loader",
    "discover_candidate_asset_files": "source_loader",
    "is_path_inside_root": "source_loader",
    "load_scan_result_to_library": "source_loader",
    "load_source_candidate_to_library": "source_loader",
    "load_source_root_to_library": "source_loader",
    "normalize_package_dir_name": "source_loader",
    "normalize_scan_result": "source_loader",
    "normalize_source_asset_relative_path": "source_loader",
    "normalize_source_candidate": "source_loader",
    "parse_load_action_value": "source_loader",
    "parse_load_status_value": "source_loader",
    "parse_write_mode_value": "source_loader",
    "render_package_dir_name": "source_loader",
    "should_copy_asset_file": "source_loader",
    "sort_item_results": "source_loader",
    "validate_candidate_after_write": "source_loader",
    "validate_candidate_before_write": "source_loader",
    "write_candidate_documents": "source_loader",
}


_CLEAR_FUNCTION_BY_MODULE: Final[dict[str, str]] = {
    "source_scanner": "clear_source_scanner_caches",
    "source_loader": "clear_source_loader_caches",
}


def _canonical_module_key(module_key: str) -> str:
    """Normalisiert Source-Modulkeys und Komfort-Aliase."""
    try:
        key = str(module_key).strip()
    except Exception as exc:
        raise SourcesImportError("Invalid VPLIB source module key.") from exc

    if not key:
        raise SourcesImportError("Empty VPLIB source module key.")

    return _RELATIVE_SOURCE_MODULE_ALIASES.get(key, key)


@lru_cache(maxsize=64)
def _load_source_module(module_key: str) -> ModuleType:
    """Lädt ein Source-Modul lazy über relative Imports."""
    canonical_key = _canonical_module_key(module_key)

    if canonical_key not in _RELATIVE_SOURCE_MODULES:
        raise SourcesImportError(f"Unknown VPLIB source module {module_key!r}.")

    relative_path = _RELATIVE_SOURCE_MODULES[canonical_key]

    try:
        return importlib.import_module(relative_path, package=__name__)
    except Exception as exc:
        raise SourcesImportError(
            f"Could not import VPLIB source module "
            f"{canonical_key!r} from {relative_path!r}: {exc}"
        ) from exc


def __getattr__(name: str) -> Any:
    """
    Lazy-Reexport für öffentliche Source-Symbole.

    Beispiele:
        from vplib.sources import scan_source_root
        from vplib.sources import get_vplib_uid_from_manifest_safe
        from vplib.sources import load_source_root_to_library
        from vplib.sources import result_to_document_bundles
    """
    canonical_module_name = _RELATIVE_SOURCE_MODULE_ALIASES.get(name, name)

    if canonical_module_name in _RELATIVE_SOURCE_MODULES:
        module = _load_source_module(canonical_module_name)
        globals()[name] = module
        return module

    module_key = _SYMBOL_TO_MODULE.get(name)

    if not module_key:
        raise AttributeError(f"module {__name__!r} has no attribute {name!r}")

    module = _load_source_module(module_key)

    try:
        value = getattr(module, name)
    except AttributeError as exc:
        raise SourcesImportError(
            f"Source symbol {name!r} is mapped to module {module_key!r}, "
            f"but the module does not export it."
        ) from exc

    globals()[name] = value
    return value


def get_source_module_keys(*, include_aliases: bool = False) -> tuple[str, ...]:
    """
    Gibt alle bekannten Source-Modulkeys zurück.

    Args:
        include_aliases:
            Wenn True, werden Komfort-Aliase wie "scanner" und "loader" ergänzt.
    """
    keys = list(_RELATIVE_SOURCE_MODULES.keys())

    if include_aliases:
        keys.extend(_RELATIVE_SOURCE_MODULE_ALIASES.keys())

    return tuple(keys)


def get_source_module_alias_map() -> Mapping[str, str]:
    """Gibt die Alias-zu-Modul-Zuordnung zurück."""
    return dict(_RELATIVE_SOURCE_MODULE_ALIASES)


def get_source_symbol_names() -> tuple[str, ...]:
    """Gibt alle lazy exportierten öffentlichen Symbolnamen zurück."""
    return tuple(sorted(_SYMBOL_TO_MODULE.keys()))


def get_source_symbol_module_map() -> Mapping[str, str]:
    """Gibt die Symbol-zu-Modul-Zuordnung zurück."""
    return dict(_SYMBOL_TO_MODULE)


def is_source_symbol(name: str) -> bool:
    """Gibt zurück, ob ein Symbol oder Modul-Alias über dieses Package exportiert wird."""
    try:
        key = str(name).strip()
    except Exception:
        return False

    if not key:
        return False

    return (
        key in _SYMBOL_TO_MODULE
        or key in _RELATIVE_SOURCE_MODULES
        or key in _RELATIVE_SOURCE_MODULE_ALIASES
    )


def load_all_source_modules() -> tuple[ModuleType, ...]:
    """
    Lädt alle kanonischen Source-Module.

    Nützlich für Tests, Startup-Diagnose oder strikte Entwicklungsprüfungen.
    Aliase werden nicht doppelt geladen.
    """
    modules: list[ModuleType] = []

    for module_key in get_source_module_keys(include_aliases=False):
        modules.append(_load_source_module(module_key))

    return tuple(modules)


def get_source_module_statuses() -> tuple[SourceModuleStatus, ...]:
    """
    Gibt Importstatus für alle Source-Module zurück.

    Diese Funktion wirft nicht, sondern sammelt Fehler in Statusobjekten.
    """
    statuses: list[SourceModuleStatus] = []

    for module_key, relative_path in _RELATIVE_SOURCE_MODULES.items():
        exported_symbols = tuple(
            sorted(
                symbol
                for symbol, mapped_module_key in _SYMBOL_TO_MODULE.items()
                if mapped_module_key == module_key
            )
        )

        try:
            _load_source_module(module_key)
            statuses.append(
                SourceModuleStatus(
                    module_key=module_key,
                    module_path=relative_path,
                    loaded=True,
                    error=None,
                    exported_symbols=exported_symbols,
                )
            )
        except Exception as exc:
            statuses.append(
                SourceModuleStatus(
                    module_key=module_key,
                    module_path=relative_path,
                    loaded=False,
                    error=str(exc),
                    exported_symbols=exported_symbols,
                )
            )

    return tuple(statuses)


def get_sources_health() -> dict[str, Any]:
    """Gibt einen JSON-kompatiblen Health-Snapshot der Source-Schicht zurück."""
    statuses = get_source_module_statuses()

    try:
        healthy = all(status.loaded for status in statuses)
    except Exception:
        healthy = False

    return {
        "schema_version": SOURCES_PACKAGE_VERSION,
        "healthy": healthy,
        "module_count": len(statuses),
        "loaded_module_count": sum(1 for status in statuses if status.loaded),
        "symbol_count": len(_SYMBOL_TO_MODULE),
        "alias_count": len(_RELATIVE_SOURCE_MODULE_ALIASES),
        "aliases": get_source_module_alias_map(),
        "modules": [status.to_dict() for status in statuses],
    }


def assert_sources_ready() -> None:
    """
    Prüft, ob alle Source-Module ladbar sind.

    Raises:
        SourcesImportError: Wenn mindestens ein Modul nicht importiert werden kann.
    """
    statuses = get_source_module_statuses()
    failed = [status for status in statuses if not status.loaded]

    if failed:
        details = "; ".join(
            f"{status.module_key}: {status.error}" for status in failed
        )
        raise SourcesImportError(f"VPLIB sources package is not ready: {details}")


def clear_source_caches() -> None:
    """
    Leert alle bekannten Source-Caches.

    Diese Funktion ist bewusst defensiv. Wenn ein einzelnes Modul fehlt oder
    eine Clear-Funktion nicht existiert, wird weitergemacht.
    """
    for module_key, function_name in _CLEAR_FUNCTION_BY_MODULE.items():
        try:
            module = _load_source_module(module_key)
            function = getattr(module, function_name, None)

            if callable(function):
                function()
        except Exception:
            continue

    try:
        _load_source_module.cache_clear()
    except Exception:
        pass


def source_status_to_json(status: SourceModuleStatus) -> dict[str, Any]:
    """Serialisiert einen SourceModuleStatus JSON-kompatibel."""
    try:
        return status.to_dict()
    except Exception:
        return {
            "schema_version": SOURCES_PACKAGE_VERSION,
            "module_key": str(getattr(status, "module_key", "<unknown>")),
            "module_path": str(getattr(status, "module_path", "<unknown>")),
            "loaded": bool(getattr(status, "loaded", False)),
            "error": str(getattr(status, "error", None)),
            "exported_symbols": list(getattr(status, "exported_symbols", ()) or ()),
        }


def source_statuses_to_json() -> list[dict[str, Any]]:
    """Serialisiert alle Source-Modulstatuswerte JSON-kompatibel."""
    return [source_status_to_json(status) for status in get_source_module_statuses()]


def scan_vplib_sources(
    source_root: str,
    *,
    scan_mode: str = "direct_children",
    validate_schema: bool = True,
    validate_semantics: bool = True,
    validate_assets: bool = True,
    require_vplib_uid: bool = True,
    skip_invalid_candidates: bool = False,
    strict: bool = True,
    metadata: Mapping[str, Any] | None = None,
) -> Any:
    """
    Kompakter stabiler Einstieg zum Scannen eines Source-Roots.

    Delegiert an source_scanner.scan_source_root.

    Args:
        require_vplib_uid:
            Standardmäßig True. Source-Packages ohne gültige `vplib_uid`
            werden dadurch invalid.
    """
    module = _load_source_module("source_scanner")
    options_cls = getattr(module, "SourceScanOptions")
    scanner = getattr(module, "scan_source_root")

    return scanner(
        source_root,
        options=options_cls(
            scan_mode=scan_mode,
            validate_schema=validate_schema,
            validate_semantics=validate_semantics,
            validate_assets=validate_assets,
            require_vplib_uid=require_vplib_uid,
            skip_invalid_candidates=skip_invalid_candidates,
            strict=strict,
        ),
        metadata=metadata,
    )


def load_vplib_sources(
    *,
    source_root: str,
    library_catalog_root: str,
    write_mode: str = "fail",
    dry_run: bool = False,
    create_archive: bool = False,
    skip_invalid_candidates: bool = True,
    strict: bool = True,
    metadata: Mapping[str, Any] | None = None,
) -> Any:
    """
    Kompakter stabiler Einstieg zum Laden eines Source-Roots in die Creative Library.

    Delegiert an source_loader.load_source_root_to_library.
    """
    module = _load_source_module("source_loader")
    options_cls = getattr(module, "SourceLoadOptions")
    loader = getattr(module, "load_source_root_to_library")

    return loader(
        source_root=source_root,
        library_catalog_root=library_catalog_root,
        options=options_cls(
            write_mode=write_mode,
            dry_run=dry_run,
            create_archive=create_archive,
            skip_invalid_candidates=skip_invalid_candidates,
            strict=strict,
        ),
        metadata=metadata,
    )


def load_vplib_scan_result(
    *,
    scan_result: Any,
    library_catalog_root: str,
    write_mode: str = "fail",
    dry_run: bool = False,
    create_archive: bool = False,
    skip_invalid_candidates: bool = True,
    strict: bool = True,
    metadata: Mapping[str, Any] | None = None,
) -> Any:
    """
    Kompakter stabiler Einstieg zum Laden eines vorhandenen Scan-Ergebnisses.

    Delegiert an source_loader.load_scan_result_to_library.
    """
    module = _load_source_module("source_loader")
    options_cls = getattr(module, "SourceLoadOptions")
    loader = getattr(module, "load_scan_result_to_library")

    return loader(
        scan_result=scan_result,
        library_catalog_root=library_catalog_root,
        options=options_cls(
            write_mode=write_mode,
            dry_run=dry_run,
            create_archive=create_archive,
            skip_invalid_candidates=skip_invalid_candidates,
            strict=strict,
        ),
        metadata=metadata,
    )


def source_candidate_to_bundle(candidate: Any) -> Any:
    """
    Kompakter Einstieg, um einen SourcePackageCandidate in ein DocumentBundle zu wandeln.
    """
    module = _load_source_module("source_scanner")
    converter = getattr(module, "candidate_to_document_bundle")
    return converter(candidate)


def source_scan_result_to_bundles(
    scan_result: Any,
    *,
    only_valid: bool = True,
) -> tuple[Any, ...]:
    """
    Kompakter Einstieg, um ein SourceScanResult in DocumentBundles zu wandeln.
    """
    module = _load_source_module("source_scanner")
    converter = getattr(module, "result_to_document_bundles")
    return converter(scan_result, only_valid=only_valid)


def get_scanned_vplib_uids(
    scan_result: Any,
    *,
    only_valid: bool = False,
) -> tuple[str, ...]:
    """
    Liest `vplib_uid`-Werte aus einem SourceScanResult-artigen Objekt.

    Args:
        only_valid:
            Wenn True, werden nur gültige Kandidaten berücksichtigt.
    """
    if scan_result is None:
        return tuple()

    try:
        normalized = scan_result.normalized() if hasattr(scan_result, "normalized") else scan_result
        candidates = tuple(getattr(normalized, "candidates", ()) or ())

        result: list[str] = []
        seen: set[str] = set()

        for candidate in candidates:
            try:
                normalized_candidate = candidate.normalized() if hasattr(candidate, "normalized") else candidate
                if only_valid and not bool(getattr(normalized_candidate, "valid", False)):
                    continue

                uid = clean_optional_string(getattr(normalized_candidate, MANIFEST_VPLIB_UID_FIELD, None))
                if not uid or uid in seen:
                    continue

                result.append(uid)
                seen.add(uid)
            except Exception:
                continue

        return tuple(result)
    except Exception:
        pass

    if isinstance(scan_result, Mapping):
        candidates = scan_result.get("candidates", ()) or ()
        result: list[str] = []
        seen: set[str] = set()

        for candidate in candidates:
            if not isinstance(candidate, Mapping):
                continue

            if only_valid and not bool(candidate.get("valid", False)):
                continue

            uid = clean_optional_string(candidate.get(MANIFEST_VPLIB_UID_FIELD))
            if not uid or uid in seen:
                continue

            result.append(uid)
            seen.add(uid)

        return tuple(result)

    return tuple()


def get_source_candidate_vplib_uid(candidate: Any) -> str | None:
    """Liest `vplib_uid` aus einem SourcePackageCandidate-artigen Objekt."""
    if candidate is None:
        return None

    try:
        normalized = candidate.normalized() if hasattr(candidate, "normalized") else candidate
        uid = clean_optional_string(getattr(normalized, MANIFEST_VPLIB_UID_FIELD, None))
        if uid:
            return uid
    except Exception:
        pass

    if isinstance(candidate, Mapping):
        return clean_optional_string(candidate.get(MANIFEST_VPLIB_UID_FIELD))

    return None


def clean_optional_string(value: Any) -> str | None:
    """Normalisiert optionalen String für leichte Wrapper-Helfer."""
    if value is None:
        return None

    try:
        cleaned = str(value).strip()
        return cleaned or None
    except Exception:
        return None


__version__ = SOURCES_PACKAGE_VERSION

__all__ = [
    "MANIFEST_VPLIB_UID_FIELD",
    "SOURCES_PACKAGE_VERSION",
    "SourceModuleStatus",
    "SourcesImportError",
    "__version__",
    "assert_sources_ready",
    "clean_optional_string",
    "clear_source_caches",
    "get_scanned_vplib_uids",
    "get_source_candidate_vplib_uid",
    "get_source_module_alias_map",
    "get_source_module_keys",
    "get_source_module_statuses",
    "get_source_symbol_module_map",
    "get_source_symbol_names",
    "get_sources_health",
    "is_source_symbol",
    "load_all_source_modules",
    "load_vplib_scan_result",
    "load_vplib_sources",
    "scan_vplib_sources",
    "source_candidate_to_bundle",
    "source_scan_result_to_bundles",
    "source_status_to_json",
    "source_statuses_to_json",
    "source_scanner",
    "source_loader",
    "scanner",
    "scan",
    "loader",
    "load",
    *_SYMBOL_TO_MODULE.keys(),
]