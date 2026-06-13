# services/vectoplan-library/src/vplib/creators/__init__.py
"""
Public creators API for the VPLIB package engine.

Diese Datei bündelt die stabile Creator-Schicht für VPLIB:

- file_writer
- package_creator
- archive_creator

Die Creator-Schicht ist die erste Schicht, die wirklich Dateien schreiben darf.

Typische Einstiegspunkte:
- create_vplib_package_from_request(...)
- create_vplib_package_from_plan(...)
- create_vplib_package_from_bundle(...)
- write_documents_to_package(...)
- create_vplib_archive_from_package(...)

Wichtig für die neue VPLIB-ID-Architektur:
- `vplib_uid` entsteht beim Erstellen des VPLIB-Manifests.
- `package_creator.py` liest diese ID aus dem finalen DocumentBundle.
- Diese Datei exportiert die neuen `vplib_uid`-Hilfsfunktionen lazy.
- Die kompakten Wrapper `create_vplib(...)`, `create_vplib_from_plan(...)`,
  `write_vplib_documents(...)` und `create_vplib_archive(...)` können optional
  eine vorhandene `vplib_uid` über metadata weiterreichen.
- Ungültige IDs werden hier nicht still ersetzt. Falls eine ungültige ID
  übergeben wird, soll sie später im Manifest-/Bundle-/Creator-Flow sichtbar
  fehlschlagen.

Sie ist bewusst robust aufgebaut:
- Imports laufen lazy über __getattr__.
- Einzelne beschädigte Creator-Module blockieren nicht sofort das ganze Package.
- Diagnosefunktionen zeigen Importstatus und Fehler.
- Cache-Clear-Funktionen können alle Creator-Caches gesammelt leeren.
- Komfort-Aliase wie `writer`, `package` und `archive` sind zusätzliche
  Modulzugriffe und brechen keine bestehende API.

Technische Namen, JSON-Keys und Variablen bleiben Englisch.
"""

from __future__ import annotations

import importlib
from dataclasses import dataclass
from functools import lru_cache
from types import ModuleType
from typing import Any, Final, Mapping


CREATORS_PACKAGE_VERSION: Final[str] = "vplib.creators.v1"
MANIFEST_VPLIB_UID_FIELD: Final[str] = "vplib_uid"


class CreatorsImportError(ImportError):
    """Wird ausgelöst, wenn ein Creator-Modul oder Creator-Symbol nicht geladen werden kann."""


@dataclass(frozen=True, slots=True)
class CreatorModuleStatus:
    """Importstatus eines Creator-Moduls."""

    module_key: str
    module_path: str
    loaded: bool
    error: str | None
    exported_symbols: tuple[str, ...]

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema_version": CREATORS_PACKAGE_VERSION,
            "module_key": self.module_key,
            "module_path": self.module_path,
            "loaded": self.loaded,
            "error": self.error,
            "exported_symbols": list(self.exported_symbols),
            "exported_symbol_count": len(self.exported_symbols),
        }


_RELATIVE_CREATOR_MODULES: Final[dict[str, str]] = {
    "file_writer": ".file_writer",
    "package_creator": ".package_creator",
    "archive_creator": ".archive_creator",
}


_RELATIVE_CREATOR_MODULE_ALIASES: Final[dict[str, str]] = {
    "writer": "file_writer",
    "files": "file_writer",
    "package": "package_creator",
    "packages": "package_creator",
    "archive": "archive_creator",
    "archives": "archive_creator",
}


_SYMBOL_TO_MODULE: Final[dict[str, str]] = {
    # ---------------------------------------------------------------------
    # file_writer.py
    # ---------------------------------------------------------------------
    "FILE_WRITER_SCHEMA_VERSION": "file_writer",
    "DEFAULT_BACKUP_SUFFIX": "file_writer",
    "DEFAULT_ENCODING": "file_writer",
    "DEFAULT_JSON_INDENT": "file_writer",
    "DEFAULT_TEMP_PREFIX": "file_writer",
    "FileContentKind": "file_writer",
    "FileCopyRequest": "file_writer",
    "FileWriteBatchResult": "file_writer",
    "FileWriteOptions": "file_writer",
    "FileWriteRequest": "file_writer",
    "FileWriteResult": "file_writer",
    "FileWriterError": "file_writer",
    "WriteMode": "file_writer",
    "WriteOperation": "file_writer",
    "WriteStatus": "file_writer",
    "atomic_copy_file": "file_writer",
    "atomic_write_bytes": "file_writer",
    "copy_file_request": "file_writer",
    "copy_package_plan_assets": "file_writer",
    "create_backup_file": "file_writer",
    "dedupe_paths": "file_writer",
    "ensure_package_directory": "file_writer",
    "evaluate_existing_target": "file_writer",
    "extract_asset_copies_from_package_plan": "file_writer",
    "extract_directory_paths_from_package_plan": "file_writer",
    "extract_relative_path": "file_writer",
    "failed_result": "file_writer",
    "file_copy_request_from_planned_asset_copy": "file_writer",
    "file_write_request_from_document": "file_writer",
    "is_path_inside_root": "file_writer",
    "normalize_absolute_path": "file_writer",
    "normalize_document_bundle": "file_writer",
    "normalize_document_mapping": "file_writer",
    "normalize_documents_mapping": "file_writer",
    "normalize_enum_key": "file_writer",
    "normalize_json_value": "file_writer",
    "normalize_local_source_path": "file_writer",
    "normalize_metadata": "file_writer",
    "normalize_non_negative_int": "file_writer",
    "normalize_options": "file_writer",
    "normalize_relative_directory_path": "file_writer",
    "normalize_relative_package_path": "file_writer",
    "normalize_result_relative_path": "file_writer",
    "operation_for_content_kind": "file_writer",
    "parse_content_kind_value": "file_writer",
    "parse_optional_write_mode_value": "file_writer",
    "parse_write_mode_value": "file_writer",
    "parse_write_operation_value": "file_writer",
    "parse_write_status_value": "file_writer",
    "resolve_package_target_path": "file_writer",
    "result_sort_key": "file_writer",
    "serialize_file_content": "file_writer",
    "write_copy_requests": "file_writer",
    "write_document_bundle_to_package": "file_writer",
    "write_documents_to_package": "file_writer",
    "write_file_request": "file_writer",
    "write_file_requests": "file_writer",
    "write_package_plan_directories": "file_writer",

    # ---------------------------------------------------------------------
    # package_creator.py
    # ---------------------------------------------------------------------
    "MANIFEST_DOCUMENT_PATH": "package_creator",
    "MANIFEST_VPLIB_UID_FIELD": "package_creator",
    "PACKAGE_CREATOR_SCHEMA_VERSION": "package_creator",
    "PackageCreationEvent": "package_creator",
    "PackageCreationOptions": "package_creator",
    "PackageCreationResult": "package_creator",
    "PackageCreationStage": "package_creator",
    "PackageCreationStatus": "package_creator",
    "PackageCreatorError": "package_creator",
    "build_document_bundle_for_plan": "package_creator",
    "copy_package_assets": "package_creator",
    "create_package_archive": "package_creator",
    "create_package_directories": "package_creator",
    "create_vplib_package_from_bundle": "package_creator",
    "create_vplib_package_from_plan": "package_creator",
    "create_vplib_package_from_request": "package_creator",
    "creation_event": "package_creator",
    "extract_raw_vplib_uid_from_any": "package_creator",
    "failed_creation_result": "package_creator",
    "get_family_id_safe": "package_creator",
    "get_family_slug_safe": "package_creator",
    "get_manifest_from_bundle_safe": "package_creator",
    "get_object_kind_safe": "package_creator",
    "get_package_id_safe": "package_creator",
    "get_package_root_from_plan": "package_creator",
    "get_package_root_from_plan_safe": "package_creator",
    "get_vplib_uid_from_bundle_safe": "package_creator",
    "get_vplib_uid_from_creation_plan_safe": "package_creator",
    "get_vplib_uid_from_manifest_safe": "package_creator",
    "get_vplib_uid_safe": "package_creator",
    "is_dry_run_result": "package_creator",
    "is_validation_valid": "package_creator",
    "is_write_result_failed": "package_creator",
    "normalize_absolute_path": "package_creator",
    "normalize_creation_plan": "package_creator",
    "normalize_document_bundle": "package_creator",
    "normalize_enum_key": "package_creator",
    "normalize_metadata": "package_creator",
    "normalize_metadata_value": "package_creator",
    "normalize_options": "package_creator",
    "normalize_optional_archive_result": "package_creator",
    "normalize_optional_creation_plan": "package_creator",
    "normalize_optional_document_bundle": "package_creator",
    "normalize_optional_validation_like": "package_creator",
    "normalize_optional_write_result": "package_creator",
    "normalize_vplib_uid_safe": "package_creator",
    "normalize_write_mode": "package_creator",
    "object_to_dict": "package_creator",
    "object_to_summary": "package_creator",
    "parse_creation_stage_value": "package_creator",
    "parse_creation_status_value": "package_creator",
    "result_summary": "package_creator",
    "status_from_archive_result": "package_creator",
    "status_from_write_result": "package_creator",
    "validate_package_after_write": "package_creator",
    "validate_package_before_write": "package_creator",
    "write_package_documents": "package_creator",

    # ---------------------------------------------------------------------
    # archive_creator.py
    # ---------------------------------------------------------------------
    "ARCHIVE_CREATOR_SCHEMA_VERSION": "archive_creator",
    "PACKAGE_ARCHIVE_EXTENSION": "archive_creator",
    "ArchiveCompression": "archive_creator",
    "ArchiveCreationOptions": "archive_creator",
    "ArchiveCreationResult": "archive_creator",
    "ArchiveCreationStatus": "archive_creator",
    "ArchiveCreatorError": "archive_creator",
    "ArchiveEntry": "archive_creator",
    "ArchiveEntryKind": "archive_creator",
    "ArchiveWriteMode": "archive_creator",
    "create_vplib_archive_from_package": "archive_creator",
    "dedupe_archive_entries": "archive_creator",
    "derive_archive_path": "archive_creator",
    "normalize_archive_path": "archive_creator",
    "normalize_archive_relative_path": "archive_creator",
    "normalize_compression_level": "archive_creator",
    "normalize_package_root": "archive_creator",
    "normalize_path_relative_to_root": "archive_creator",
    "parse_compression_value": "archive_creator",
    "parse_creation_status_value": "archive_creator",
    "parse_entry_kind_value": "archive_creator",
    "parse_write_mode_value": "archive_creator",
    "resolve_archive_path": "archive_creator",
    "scan_package_entries": "archive_creator",
    "should_include_name": "archive_creator",
    "sort_archive_entries": "archive_creator",
    "validate_archive_entries": "archive_creator",
    "validate_package_root_for_archive": "archive_creator",
    "write_archive_atomic": "archive_creator",
    "write_archive_file": "archive_creator",
}


_CLEAR_FUNCTION_BY_MODULE: Final[dict[str, str]] = {
    "file_writer": "clear_file_writer_caches",
    "package_creator": "clear_package_creator_caches",
    "archive_creator": "clear_archive_creator_caches",
}


def _canonical_module_key(module_key: str) -> str:
    """Normalisiert Creator-Modulkeys und Komfort-Aliase."""
    try:
        key = str(module_key).strip()
    except Exception as exc:
        raise CreatorsImportError("Invalid VPLIB creator module key.") from exc

    if not key:
        raise CreatorsImportError("Empty VPLIB creator module key.")

    return _RELATIVE_CREATOR_MODULE_ALIASES.get(key, key)


@lru_cache(maxsize=64)
def _load_creator_module(module_key: str) -> ModuleType:
    """Lädt ein Creator-Modul lazy über relative Imports."""
    canonical_key = _canonical_module_key(module_key)

    if canonical_key not in _RELATIVE_CREATOR_MODULES:
        raise CreatorsImportError(f"Unknown VPLIB creator module {module_key!r}.")

    relative_path = _RELATIVE_CREATOR_MODULES[canonical_key]

    try:
        return importlib.import_module(relative_path, package=__name__)
    except Exception as exc:
        raise CreatorsImportError(
            f"Could not import VPLIB creator module "
            f"{canonical_key!r} from {relative_path!r}: {exc}"
        ) from exc


def __getattr__(name: str) -> Any:
    """
    Lazy-Reexport für öffentliche Creator-Symbole.

    Beispiele:
        from vplib.creators import create_vplib_package_from_request
        from vplib.creators import get_vplib_uid_safe
        from vplib.creators import write_documents_to_package
        from vplib.creators import create_vplib_archive_from_package
    """
    canonical_module_name = _RELATIVE_CREATOR_MODULE_ALIASES.get(name, name)

    if canonical_module_name in _RELATIVE_CREATOR_MODULES:
        module = _load_creator_module(canonical_module_name)
        globals()[name] = module
        return module

    module_key = _SYMBOL_TO_MODULE.get(name)

    if not module_key:
        raise AttributeError(f"module {__name__!r} has no attribute {name!r}")

    module = _load_creator_module(module_key)

    try:
        value = getattr(module, name)
    except AttributeError as exc:
        raise CreatorsImportError(
            f"Creator symbol {name!r} is mapped to module {module_key!r}, "
            f"but the module does not export it."
        ) from exc

    globals()[name] = value
    return value


def get_creator_module_keys(*, include_aliases: bool = False) -> tuple[str, ...]:
    """
    Gibt alle bekannten Creator-Modulkeys zurück.

    Args:
        include_aliases:
            Wenn True, werden Komfort-Aliase wie "writer" oder "package" ergänzt.
    """
    keys = list(_RELATIVE_CREATOR_MODULES.keys())

    if include_aliases:
        keys.extend(_RELATIVE_CREATOR_MODULE_ALIASES.keys())

    return tuple(keys)


def get_creator_module_alias_map() -> Mapping[str, str]:
    """Gibt die Alias-zu-Modul-Zuordnung zurück."""
    return dict(_RELATIVE_CREATOR_MODULE_ALIASES)


def get_creator_symbol_names() -> tuple[str, ...]:
    """Gibt alle lazy exportierten öffentlichen Symbolnamen zurück."""
    return tuple(sorted(_SYMBOL_TO_MODULE.keys()))


def get_creator_symbol_module_map() -> Mapping[str, str]:
    """Gibt die Symbol-zu-Modul-Zuordnung zurück."""
    return dict(_SYMBOL_TO_MODULE)


def is_creator_symbol(name: str) -> bool:
    """Gibt zurück, ob ein Symbol oder Modul-Alias über dieses Package exportiert wird."""
    try:
        key = str(name).strip()
    except Exception:
        return False

    if not key:
        return False

    return (
        key in _SYMBOL_TO_MODULE
        or key in _RELATIVE_CREATOR_MODULES
        or key in _RELATIVE_CREATOR_MODULE_ALIASES
    )


def load_all_creator_modules() -> tuple[ModuleType, ...]:
    """
    Lädt alle kanonischen Creator-Module.

    Nützlich für Tests, Startup-Diagnose oder strikte Entwicklungsprüfungen.
    Aliase werden nicht doppelt geladen.
    """
    modules: list[ModuleType] = []

    for module_key in get_creator_module_keys(include_aliases=False):
        modules.append(_load_creator_module(module_key))

    return tuple(modules)


def get_creator_module_statuses() -> tuple[CreatorModuleStatus, ...]:
    """
    Gibt Importstatus für alle Creator-Module zurück.

    Diese Funktion wirft nicht, sondern sammelt Fehler in Statusobjekten.
    """
    statuses: list[CreatorModuleStatus] = []

    for module_key, relative_path in _RELATIVE_CREATOR_MODULES.items():
        exported_symbols = tuple(
            sorted(
                symbol
                for symbol, mapped_module_key in _SYMBOL_TO_MODULE.items()
                if mapped_module_key == module_key
            )
        )

        try:
            _load_creator_module(module_key)
            statuses.append(
                CreatorModuleStatus(
                    module_key=module_key,
                    module_path=relative_path,
                    loaded=True,
                    error=None,
                    exported_symbols=exported_symbols,
                )
            )
        except Exception as exc:
            statuses.append(
                CreatorModuleStatus(
                    module_key=module_key,
                    module_path=relative_path,
                    loaded=False,
                    error=str(exc),
                    exported_symbols=exported_symbols,
                )
            )

    return tuple(statuses)


def get_creators_health() -> dict[str, Any]:
    """Gibt einen JSON-kompatiblen Health-Snapshot der Creator-Schicht zurück."""
    statuses = get_creator_module_statuses()

    try:
        healthy = all(status.loaded for status in statuses)
    except Exception:
        healthy = False

    return {
        "schema_version": CREATORS_PACKAGE_VERSION,
        "healthy": healthy,
        "module_count": len(statuses),
        "loaded_module_count": sum(1 for status in statuses if status.loaded),
        "symbol_count": len(_SYMBOL_TO_MODULE),
        "alias_count": len(_RELATIVE_CREATOR_MODULE_ALIASES),
        "aliases": get_creator_module_alias_map(),
        "modules": [status.to_dict() for status in statuses],
    }


def assert_creators_ready() -> None:
    """
    Prüft, ob alle Creator-Module ladbar sind.

    Raises:
        CreatorsImportError: Wenn mindestens ein Modul nicht importiert werden kann.
    """
    statuses = get_creator_module_statuses()
    failed = [status for status in statuses if not status.loaded]

    if failed:
        details = "; ".join(
            f"{status.module_key}: {status.error}" for status in failed
        )
        raise CreatorsImportError(f"VPLIB creators package is not ready: {details}")


def clear_creator_caches() -> None:
    """
    Leert alle bekannten Creator-Caches.

    Diese Funktion ist bewusst defensiv. Wenn ein einzelnes Modul fehlt oder
    eine Clear-Funktion nicht existiert, wird weitergemacht.
    """
    for module_key, function_name in _CLEAR_FUNCTION_BY_MODULE.items():
        try:
            module = _load_creator_module(module_key)
            function = getattr(module, function_name, None)

            if callable(function):
                function()
        except Exception:
            continue

    try:
        _load_creator_module.cache_clear()
    except Exception:
        pass


def creator_status_to_json(status: CreatorModuleStatus) -> dict[str, Any]:
    """Serialisiert einen CreatorModuleStatus JSON-kompatibel."""
    try:
        return status.to_dict()
    except Exception:
        return {
            "schema_version": CREATORS_PACKAGE_VERSION,
            "module_key": str(getattr(status, "module_key", "<unknown>")),
            "module_path": str(getattr(status, "module_path", "<unknown>")),
            "loaded": bool(getattr(status, "loaded", False)),
            "error": str(getattr(status, "error", None)),
            "exported_symbols": list(getattr(status, "exported_symbols", ()) or ()),
        }


def creator_statuses_to_json() -> list[dict[str, Any]]:
    """Serialisiert alle Creator-Modulstatuswerte JSON-kompatibel."""
    return [creator_status_to_json(status) for status in get_creator_module_statuses()]


def create_vplib(
    request: Any,
    *,
    service_root: str,
    library_catalog_root: str | None = None,
    source_root: str | None = None,
    generated_root: str | None = None,
    archive_root: str | None = None,
    dry_run: bool = False,
    write_mode: str = "fail",
    create_archive: bool = False,
    vplib_uid: str | None = None,
    metadata: Mapping[str, Any] | None = None,
) -> Any:
    """
    Kompakter stabiler Einstieg für spätere Routen.

    Delegiert an package_creator.create_vplib_package_from_request.

    Args:
        vplib_uid:
            Optional vorhandene VPLIB-ID. Wird nicht hier validiert oder ersetzt,
            sondern über metadata in den Manifest-/Bundle-/Creator-Flow gegeben.
    """
    module = _load_creator_module("package_creator")
    options_cls = getattr(module, "PackageCreationOptions")
    creator = getattr(module, "create_vplib_package_from_request")

    return creator(
        request=request,
        service_root=service_root,
        library_catalog_root=library_catalog_root,
        source_root=source_root,
        generated_root=generated_root,
        archive_root=archive_root,
        options=options_cls(
            write_mode=write_mode,
            dry_run=dry_run,
            create_archive=create_archive,
        ),
        metadata=merge_metadata_with_vplib_uid(metadata, vplib_uid),
    )


def create_vplib_from_plan(
    creation_plan: Any,
    *,
    dry_run: bool = False,
    write_mode: str = "fail",
    create_archive: bool = False,
    vplib_uid: str | None = None,
    metadata: Mapping[str, Any] | None = None,
) -> Any:
    """
    Kompakter stabiler Einstieg für vorhandene CreationPlan-Objekte.

    Delegiert an package_creator.create_vplib_package_from_plan.

    Args:
        vplib_uid:
            Optional vorhandene VPLIB-ID. Wird über metadata weitergereicht.
    """
    module = _load_creator_module("package_creator")
    options_cls = getattr(module, "PackageCreationOptions")
    creator = getattr(module, "create_vplib_package_from_plan")

    return creator(
        creation_plan=creation_plan,
        options=options_cls(
            write_mode=write_mode,
            dry_run=dry_run,
            create_archive=create_archive,
        ),
        metadata=merge_metadata_with_vplib_uid(metadata, vplib_uid),
    )


def write_vplib_documents(
    *,
    package_root: str,
    documents: Mapping[str, Mapping[str, Any]],
    dry_run: bool = False,
    write_mode: str = "fail",
    vplib_uid: str | None = None,
    metadata: Mapping[str, Any] | None = None,
) -> Any:
    """
    Kompakter stabiler Einstieg zum Schreiben eines Dokument-Mappings.

    Delegiert an file_writer.write_documents_to_package.

    Hinweis:
        Diese Funktion validiert nicht selbst, ob `documents` ein Manifest mit
        `vplib_uid` enthält. Das muss im Bundle-/Manifest-Flow passieren.
        `vplib_uid` wird hier nur in metadata gespiegelt.
    """
    module = _load_creator_module("file_writer")
    options_cls = getattr(module, "FileWriteOptions")
    writer = getattr(module, "write_documents_to_package")

    return writer(
        package_root=package_root,
        documents=documents,
        options=options_cls(
            write_mode=write_mode,
            dry_run=dry_run,
        ),
        metadata=merge_metadata_with_vplib_uid(metadata, vplib_uid),
    )


def create_vplib_archive(
    *,
    package_root: str,
    archive_path: str | None = None,
    dry_run: bool = False,
    overwrite: bool = False,
    vplib_uid: str | None = None,
    metadata: Mapping[str, Any] | None = None,
) -> Any:
    """
    Kompakter stabiler Einstieg zum Erstellen eines .vplib-Archivs.

    Delegiert an archive_creator.create_vplib_archive_from_package.
    """
    module = _load_creator_module("archive_creator")
    creator = getattr(module, "create_vplib_archive_from_package")

    return creator(
        package_root=package_root,
        archive_path=archive_path,
        dry_run=dry_run,
        overwrite=overwrite,
        metadata=merge_metadata_with_vplib_uid(metadata, vplib_uid),
    )


def get_created_vplib_uid(result: Any) -> str | None:
    """
    Liest `vplib_uid` defensiv aus einem Creator-Ergebnis.

    Nützlich für Routen:
        result = create_vplib(...)
        uid = get_created_vplib_uid(result)
    """
    if result is None:
        return None

    try:
        uid = getattr(result, "vplib_uid", None)
        if uid:
            return str(uid)
    except Exception:
        pass

    try:
        if hasattr(result, "to_dict"):
            data = result.to_dict()
            uid = data.get(MANIFEST_VPLIB_UID_FIELD)
            if uid:
                return str(uid)

            metadata = data.get("metadata")
            if isinstance(metadata, Mapping):
                uid = metadata.get(MANIFEST_VPLIB_UID_FIELD)
                if uid:
                    return str(uid)
    except Exception:
        pass

    if isinstance(result, Mapping):
        try:
            uid = result.get(MANIFEST_VPLIB_UID_FIELD)
            if uid:
                return str(uid)

            metadata = result.get("metadata")
            if isinstance(metadata, Mapping):
                uid = metadata.get(MANIFEST_VPLIB_UID_FIELD)
                if uid:
                    return str(uid)
        except Exception:
            pass

    return None


def merge_metadata_with_vplib_uid(
    metadata: Mapping[str, Any] | None,
    vplib_uid: Any | None,
) -> dict[str, Any]:
    """
    Merged metadata mit optionaler `vplib_uid`.

    Wichtig:
    - Diese Funktion validiert die ID bewusst nicht.
    - Eine ungültige explizite ID soll später im Manifest-/Bundle-Flow
      sichtbar fehlschlagen.
    - Wenn metadata bereits eine `vplib_uid` enthält und zusätzlich ein
      anderer expliziter Wert übergeben wird, gewinnt der explizite Wert.
    """
    merged = normalize_metadata(metadata)

    if vplib_uid is not None:
        merged[MANIFEST_VPLIB_UID_FIELD] = vplib_uid

    return merged


def normalize_metadata(value: Mapping[str, Any] | None) -> dict[str, Any]:
    """Normalisiert Metadata defensiv JSON-kompatibel genug für Creator-Wrapper."""
    if value is None:
        return {}

    if not isinstance(value, Mapping):
        return {"value": str(value)}

    normalized: dict[str, Any] = {}

    for key, child_value in value.items():
        try:
            normalized[str(key)] = normalize_metadata_value(child_value)
        except Exception as exc:
            normalized[str(key)] = f"<metadata-normalization-error: {exc}>"

    return normalized


def normalize_metadata_value(value: Any) -> Any:
    """Normalisiert Metadata-Werte defensiv."""
    if value is None:
        return None

    if isinstance(value, (str, int, float, bool)):
        return value

    if isinstance(value, Mapping):
        return normalize_metadata(value)

    if isinstance(value, (list, tuple, set)):
        return [normalize_metadata_value(item) for item in value]

    return str(value)


__version__ = CREATORS_PACKAGE_VERSION

__all__ = [
    "CREATORS_PACKAGE_VERSION",
    "MANIFEST_VPLIB_UID_FIELD",
    "CreatorModuleStatus",
    "CreatorsImportError",
    "__version__",
    "assert_creators_ready",
    "clear_creator_caches",
    "create_vplib",
    "create_vplib_archive",
    "create_vplib_from_plan",
    "creator_status_to_json",
    "creator_statuses_to_json",
    "get_created_vplib_uid",
    "get_creator_module_alias_map",
    "get_creator_module_keys",
    "get_creator_module_statuses",
    "get_creator_symbol_module_map",
    "get_creator_symbol_names",
    "get_creators_health",
    "is_creator_symbol",
    "load_all_creator_modules",
    "merge_metadata_with_vplib_uid",
    "normalize_metadata",
    "normalize_metadata_value",
    "write_vplib_documents",
    "file_writer",
    "package_creator",
    "archive_creator",
    "writer",
    "files",
    "package",
    "packages",
    "archive",
    "archives",
    *_SYMBOL_TO_MODULE.keys(),
]