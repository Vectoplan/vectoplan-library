# services/vectoplan-library/src/library/domain/__init__.py
"""
Domain Package der VECTOPLAN Creative-Library-Schicht.

Dieses Package bündelt die fachlichen Datenmodelle der `/src/library` Ebene.

Bisherige Kernmodelle:

- `library_item.py`
  Kompaktes Modell eines Blocks/Objekts für Listenansichten.

- `library_detail.py`
  Ausführliches Detailmodell eines Blocks/Objekts für Detailrouten.

- `scan_result.py`
  Scan-Ergebnisse, Kandidaten, Duplikate, Fehler und API-Response-Modelle.

Neue DB-/Publication-Modelle:

- `sync_result.py`
  Ergebnisstrukturen für Scan → DB-Sync → Sync-Report.

- `publication.py`
  Veröffentlichte DB-Lesemodelle für Blocks, Detail, Varianten und Tree.

- `inventory.py`
  Editor-/Creative-Library-Inventarzustand.

Diese Datei ist bewusst defensiv aufgebaut:

- keine Flask-Abhängigkeit
- keine Datenbank-Abhängigkeit
- kein Scan beim Import
- keine Dateisystem-Schreiboperation
- kein Taxonomie-JSON-Load beim Import
- robuste Health-Funktion
- Lazy-Reexports für spätere Imports
- Fehler in einzelnen Domain-Modulen brechen nicht sofort das gesamte Package
- Import-Cache ist explizit leerbar
- Submodule können einzeln abgefragt werden
- neue Domain-Dateien können inkrementell ergänzt werden

Taxonomie-Regel:

    Backend-Taxonomie ist kanonisch für:
    - Domain/Reiter
    - Kategorie
    - Subkategorie
    - Labels
    - taxonomy_path
    - classification_path
    - source_path
    - taxonomy_version

DB-/Publication-Regel:

    vplib_uid ist die stabile technische Package-ID.
    family_id und package_id bleiben semantische IDs.
    revision_hash beschreibt die Inhaltsrevision.
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

DOMAIN_PACKAGE_VERSION: Final[str] = "0.3.0"
DOMAIN_PACKAGE_NAME: Final[str] = "library.domain"
DOMAIN_COMPONENT_NAME: Final[str] = "creative-library-domain"

DOMAIN_MODULES: Final[tuple[str, ...]] = (
    "library_item",
    "library_detail",
    "scan_result",
    "sync_result",
    "publication",
    "inventory",
)

REQUIRED_DOMAIN_MODULES: Final[tuple[str, ...]] = (
    "library_item",
    "library_detail",
    "scan_result",
)

OPTIONAL_DOMAIN_MODULES: Final[tuple[str, ...]] = (
    "sync_result",
    "publication",
    "inventory",
)

DB_DOMAIN_MODULES: Final[tuple[str, ...]] = (
    "sync_result",
    "publication",
    "inventory",
)


# ---------------------------------------------------------------------------
# Symbol registry
# ---------------------------------------------------------------------------

SYMBOL_TO_MODULE: Final[dict[str, str]] = {
    # -----------------------------------------------------------------------
    # library_item.py constants
    # -----------------------------------------------------------------------
    "LIBRARY_ITEM_MODEL_VERSION": "library_item",
    "DEFAULT_VARIANT_ID": "library_item",
    "DEFAULT_OBJECT_KIND": "library_item",
    "DEFAULT_STATUS": "library_item",
    "UNKNOWN_LABEL": "library_item",
    "UNKNOWN_TAXONOMY_VALUE": "library_item",
    "VALID_OBJECT_KINDS": "library_item",
    "VALID_ITEM_STATUSES": "library_item",

    # -----------------------------------------------------------------------
    # library_item.py enums/classes
    # -----------------------------------------------------------------------
    "LibraryItemStatus": "library_item",
    "LibraryItemKind": "library_item",
    "LibraryItemValidationSummary": "library_item",
    "LibraryItemAssetRefs": "library_item",
    "LibraryItemClassification": "library_item",
    "LibraryItem": "library_item",

    # -----------------------------------------------------------------------
    # library_item.py generic helpers
    # -----------------------------------------------------------------------
    "safe_str": "library_item",
    "safe_int": "library_item",
    "safe_bool": "library_item",
    "safe_path_str": "library_item",
    "ensure_dict": "library_item",
    "ensure_list_of_strings": "library_item",
    "deep_get": "library_item",
    "first_non_empty": "library_item",
    "dataclass_to_dict_safe": "library_item",
    "json_safe": "library_item",

    # -----------------------------------------------------------------------
    # library_item.py normalization/taxonomy helpers
    # -----------------------------------------------------------------------
    "normalize_slug": "library_item",
    "normalize_taxonomy_slug": "library_item",
    "normalize_taxonomy_path": "library_item",
    "build_taxonomy_path": "library_item",
    "normalize_stable_id": "library_item",
    "normalize_object_kind": "library_item",
    "normalize_status": "library_item",
    "normalize_variant_id": "library_item",
    "humanize_identifier": "library_item",
    "normalize_item_taxonomy_payload": "library_item",

    # -----------------------------------------------------------------------
    # library_item.py collection helpers
    # -----------------------------------------------------------------------
    "extract_variant_ids": "library_item",
    "sort_library_items": "library_item",
    "index_library_items_by_id": "library_item",
    "filter_valid_library_items": "library_item",
    "library_items_to_summary_dicts": "library_item",
    "library_items_to_dicts": "library_item",

    # -----------------------------------------------------------------------
    # library_detail.py constants
    # -----------------------------------------------------------------------
    "LIBRARY_DETAIL_MODEL_VERSION": "library_detail",
    "LIBRARY_DETAIL_MODEL_COMPONENT": "library_detail",
    "MANIFEST_DOCUMENT_KEY": "library_detail",
    "MODULES_DOCUMENT_KEY": "library_detail",
    "FAMILY_PREFIX": "library_detail",
    "VARIANTS_PREFIX": "library_detail",
    "EDITOR_PREFIX": "library_detail",
    "RENDER_PREFIX": "library_detail",
    "PHYSICAL_PREFIX": "library_detail",
    "MATERIAL_PREFIX": "library_detail",
    "CALCULATION_PREFIX": "library_detail",
    "MANUFACTURER_PREFIX": "library_detail",
    "ANALYSIS_PREFIX": "library_detail",
    "DYNAMIC_PREFIX": "library_detail",
    "DOCS_PREFIX": "library_detail",
    "TESTS_PREFIX": "library_detail",
    "ASSETS_PREFIX": "library_detail",
    "KNOWN_DOCUMENT_GROUPS": "library_detail",
    "DETAIL_PROFILE_GROUPS": "library_detail",
    "DEFAULT_DETAIL_STATUS": "library_detail",
    "DEFAULT_VARIANT_ID_FALLBACK": "library_detail",
    "UNKNOWN_LIBRARY_ITEM_ID": "library_detail",
    "CANONICAL_SOURCE_DEPTH": "library_detail",
    "LEGACY_SOURCE_DEPTH": "library_detail",
    "TAXONOMY_DOCUMENT_KEY": "library_detail",

    # -----------------------------------------------------------------------
    # library_detail.py classes
    # -----------------------------------------------------------------------
    "LibraryDocumentEntry": "library_detail",
    "LibraryTaxonomyDetail": "library_detail",
    "LibraryVariantDetail": "library_detail",
    "LibraryModuleDetail": "library_detail",
    "LibrarySourceDetail": "library_detail",
    "LibraryItemDetail": "library_detail",

    # -----------------------------------------------------------------------
    # library_detail.py document helpers
    # -----------------------------------------------------------------------
    "document_group_for_key": "library_detail",
    "document_name_for_key": "library_detail",
    "normalize_document_key": "library_detail",
    "normalize_documents": "library_detail",
    "get_document": "library_detail",
    "get_document_dict": "library_detail",
    "group_documents": "library_detail",
    "extract_nested_document_group": "library_detail",
    "make_validation_summary": "library_detail",
    "item_to_summary_dict": "library_detail",
    "get_item_attr": "library_detail",
    "extract_package_id_from_documents": "library_detail",
    "extract_family_id_from_documents": "library_detail",

    # -----------------------------------------------------------------------
    # library_detail.py taxonomy/detail helpers
    # -----------------------------------------------------------------------
    "extract_taxonomy_from_documents": "library_detail",
    "build_classification_payload": "library_detail",
    "extract_variants_from_documents": "library_detail",
    "extract_modules_from_documents": "library_detail",
    "build_document_entries": "library_detail",
    "build_profile_groups": "library_detail",
    "build_family_payload": "library_detail",
    "build_package_payload": "library_detail",
    "build_detail_response": "library_detail",
    "build_not_found_detail_response": "library_detail",
    "build_error_detail_response": "library_detail",
    "get_library_detail_model_health": "library_detail",
    "assert_library_detail_model_ready": "library_detail",

    # -----------------------------------------------------------------------
    # scan_result.py constants
    # -----------------------------------------------------------------------
    "LIBRARY_SCAN_RESULT_MODEL_VERSION": "scan_result",
    "DEFAULT_SCAN_STATUS": "scan_result",
    "DEFAULT_SCAN_MODE": "scan_result",
    "DEFAULT_CANDIDATE_STATUS": "scan_result",
    "VALID_SCAN_STATUSES": "scan_result",
    "VALID_CANDIDATE_STATUSES": "scan_result",
    "TERMINAL_ERROR_STATUSES": "scan_result",

    # -----------------------------------------------------------------------
    # scan_result.py classes
    # -----------------------------------------------------------------------
    "LibraryScanStatus": "scan_result",
    "LibraryScanCandidateStatus": "scan_result",
    "LibraryScanMessage": "scan_result",
    "LibraryDuplicateId": "scan_result",
    "LibraryScanCandidate": "scan_result",
    "LibraryScanStats": "scan_result",
    "LibraryScanResult": "scan_result",

    # -----------------------------------------------------------------------
    # scan_result.py helpers/builders
    # -----------------------------------------------------------------------
    "monotonic_ms": "scan_result",
    "normalize_candidate_status": "scan_result",
    "normalize_scan_status": "scan_result",
    "derive_candidate_status": "scan_result",
    "calculate_duration_ms": "scan_result",
    "normalize_scan_messages": "scan_result",
    "normalize_scan_candidates": "scan_result",
    "normalize_duplicates": "scan_result",
    "derive_scan_status": "scan_result",
    "candidates_from_items": "scan_result",
    "detect_duplicate_items": "scan_result",
    "mark_duplicate_candidates": "scan_result",
    "build_scan_result_from_items": "scan_result",
    "build_scan_response": "scan_result",
    "build_blocks_response": "scan_result",
    "build_empty_scan_result": "scan_result",
    "build_error_scan_result": "scan_result",

    # -----------------------------------------------------------------------
    # sync_result.py constants
    # -----------------------------------------------------------------------
    "SYNC_RESULT_COMPONENT_NAME": "sync_result",
    "SYNC_RESULT_API_VERSION": "sync_result",
    "SYNC_RESULT_MODEL_VERSION": "sync_result",
    "DEFAULT_SYNC_MODE": "sync_result",
    "DEFAULT_SYNC_SOURCE": "sync_result",
    "DEFAULT_SYNC_TARGET": "sync_result",

    # -----------------------------------------------------------------------
    # sync_result.py enums/classes
    # -----------------------------------------------------------------------
    "LibrarySyncStatus": "sync_result",
    "LibrarySyncCandidateStatus": "sync_result",
    "LibrarySyncIssueSeverity": "sync_result",
    "LibrarySyncOperation": "sync_result",
    "LibrarySyncIssue": "sync_result",
    "LibrarySyncOperationResult": "sync_result",
    "LibrarySyncCandidateResult": "sync_result",
    "LibrarySyncStats": "sync_result",
    "LibrarySyncRunInfo": "sync_result",
    "LibrarySyncResult": "sync_result",

    # -----------------------------------------------------------------------
    # sync_result.py helpers/builders
    # -----------------------------------------------------------------------
    "normalize_sync_status": "sync_result",
    "normalize_sync_candidate_status": "sync_result",
    "normalize_sync_issue_severity": "sync_result",
    "normalize_sync_operation": "sync_result",
    "clear_sync_result_caches": "sync_result",
    "exception_to_issue": "sync_result",
    "build_sync_result_from_candidates": "sync_result",
    "build_empty_sync_result": "sync_result",
    "build_error_sync_result": "sync_result",
    "build_sync_response": "sync_result",
    "get_sync_result_health": "sync_result",
    "assert_sync_result_ready": "sync_result",

    # -----------------------------------------------------------------------
    # publication.py constants
    # -----------------------------------------------------------------------
    "PUBLICATION_COMPONENT_NAME": "publication",
    "PUBLICATION_API_VERSION": "publication",
    "PUBLICATION_MODEL_VERSION": "publication",
    "DEFAULT_PUBLICATION_STATUS": "publication",
    "DEFAULT_PUBLICATION_VISIBILITY": "publication",
    "DEFAULT_PUBLICATION_SOURCE": "publication",

    # -----------------------------------------------------------------------
    # publication.py enums/classes
    # -----------------------------------------------------------------------
    "LibraryPublicationStatus": "publication",
    "LibraryPublicationVisibility": "publication",
    "LibraryPublicationSource": "publication",
    "LibraryValidationStatus": "publication",
    "LibraryPublishedObjectKind": "publication",
    "PublishedAssetRef": "publication",
    "PublishedValidationSummary": "publication",
    "PublishedRevisionSummary": "publication",
    "PublishedVariantSummary": "publication",
    "PublishedFamilySummary": "publication",
    "PublishedFamilyDetail": "publication",
    "PublishedLibraryStats": "publication",
    "PublishedLibraryListResult": "publication",

    # -----------------------------------------------------------------------
    # publication.py helpers/builders
    # -----------------------------------------------------------------------
    "normalize_publication_status": "publication",
    "normalize_publication_visibility": "publication",
    "normalize_publication_source": "publication",
    "normalize_validation_status": "publication",
    "clear_publication_caches": "publication",
    "build_published_family_summary": "publication",
    "build_published_family_summaries": "publication",
    "build_published_detail_response": "publication",
    "build_published_list_response": "publication",
    "build_not_found_publication_response": "publication",
    "build_error_publication_response": "publication",
    "get_publication_health": "publication",
    "assert_publication_ready": "publication",

    # -----------------------------------------------------------------------
    # inventory.py constants
    # -----------------------------------------------------------------------
    "INVENTORY_COMPONENT_NAME": "inventory",
    "INVENTORY_API_VERSION": "inventory",
    "INVENTORY_MODEL_VERSION": "inventory",
    "DEFAULT_INVENTORY_SOURCE": "inventory",
    "DEFAULT_INVENTORY_SCOPE": "inventory",
    "DEFAULT_INVENTORY_STATUS": "inventory",
    "DEFAULT_INVENTORY_MODE": "inventory",

    # -----------------------------------------------------------------------
    # inventory.py enums/classes
    # -----------------------------------------------------------------------
    "InventorySlotStatus": "inventory",
    "InventorySource": "inventory",
    "InventoryScope": "inventory",
    "InventoryMode": "inventory",
    "InventoryObjectKind": "inventory",
    "InventoryAssetRole": "inventory",
    "InventoryAssetRef": "inventory",
    "InventoryPlacementInfo": "inventory",
    "InventoryVariantRef": "inventory",
    "InventorySlot": "inventory",
    "InventoryStats": "inventory",
    "InventoryState": "inventory",

    # -----------------------------------------------------------------------
    # inventory.py helpers/builders
    # -----------------------------------------------------------------------
    "normalize_slot_status": "inventory",
    "normalize_inventory_source": "inventory",
    "normalize_inventory_scope": "inventory",
    "normalize_inventory_mode": "inventory",
    "normalize_asset_role": "inventory",
    "clear_inventory_caches": "inventory",
    "sort_inventory_slots": "inventory",
    "build_inventory_slot": "inventory",
    "build_inventory_slots": "inventory",
    "build_inventory_state": "inventory",
    "build_inventory_response": "inventory",
    "build_empty_inventory_response": "inventory",
    "build_error_inventory_response": "inventory",
    "select_inventory_slot": "inventory",
    "get_inventory_health": "inventory",
    "assert_inventory_ready": "inventory",
}


# ---------------------------------------------------------------------------
# Symbol aliases
# ---------------------------------------------------------------------------

# Einige neue Module exportieren bewusst generische Namen wie
# `normalize_candidate_status`. Diese würden mit bestehenden scan_result-Symbolen
# kollidieren. Für saubere Domain-Reexports werden deshalb Aliasnamen angeboten.
SYMBOL_ALIASES: Final[dict[str, tuple[str, str]]] = {
    "normalize_sync_candidate_status": ("sync_result", "normalize_candidate_status"),
    "normalize_sync_issue_severity": ("sync_result", "normalize_issue_severity"),
}


# ---------------------------------------------------------------------------
# Internal import cache
# ---------------------------------------------------------------------------

_IMPORT_CACHE_LOCK = RLock()
_MODULE_CACHE: dict[str, ModuleType] = {}
_IMPORT_ERRORS: dict[str, dict[str, Any] | None] = {}


# ---------------------------------------------------------------------------
# Dataclasses
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class DomainModuleStatus:
    """Importstatus eines Domain-Submoduls."""

    name: str
    import_path: str
    loaded: bool
    status: str
    required: bool = False
    optional: bool = False
    db_module: bool = False
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
            "optional": self.optional,
            "db_module": self.db_module,
            "symbol_count": self.symbol_count,
            "exported_symbols": list(self.exported_symbols),
            "error": json_safe_local(self.error),
        }


@dataclass(frozen=True)
class DomainHealth:
    """Health-Modell für `library.domain`."""

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
    optional_module_count: int
    loaded_optional_module_count: int
    db_module_count: int
    loaded_db_module_count: int
    symbol_count: int
    modules: dict[str, dict[str, Any]]
    subhealth: dict[str, dict[str, Any]] = field(default_factory=dict)
    taxonomy: dict[str, Any] = field(default_factory=dict)
    db_domain: dict[str, Any] = field(default_factory=dict)
    capabilities: dict[str, Any] = field(default_factory=dict)
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
            "optional_module_count": self.optional_module_count,
            "loaded_optional_module_count": self.loaded_optional_module_count,
            "db_module_count": self.db_module_count,
            "loaded_db_module_count": self.loaded_db_module_count,
            "symbol_count": self.symbol_count,
            "modules": json_safe_local(self.modules),
            "subhealth": json_safe_local(self.subhealth),
            "taxonomy": json_safe_local(self.taxonomy),
            "db_domain": json_safe_local(self.db_domain),
            "capabilities": json_safe_local(self.capabilities),
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


def json_safe_local(value: Any) -> Any:
    """
    Lokaler JSON-Safe-Konverter.

    Absichtlich nicht als `json_safe` exportiert, weil `json_safe` als
    Lazy-Reexport aus `library_item.py` kommt.
    """
    try:
        if value is None:
            return None

        if isinstance(value, (str, int, float, bool)):
            return value

        if is_dataclass(value):
            return json_safe_local(asdict(value))

        if isinstance(value, Mapping):
            return {str(key): json_safe_local(item) for key, item in value.items()}

        if isinstance(value, (list, tuple, set)):
            return [json_safe_local(item) for item in value]

        if isinstance(value, ModuleType):
            return {
                "module": value.__name__,
                "file": getattr(value, "__file__", None),
            }

        to_dict = getattr(value, "to_dict", None)
        if callable(to_dict):
            try:
                return json_safe_local(to_dict())
            except TypeError:
                return json_safe_local(to_dict(flat=True))

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
            return dict(raw) if isinstance(raw, Mapping) else {"value": json_safe_local(raw)}
    except Exception:
        pass

    try:
        if is_dataclass(value):
            return json_safe_local(asdict(value))
    except Exception:
        pass

    if isinstance(value, Mapping):
        return dict(json_safe_local(value))

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
    """Baut den vollständigen Importpfad eines Domain-Submoduls."""
    return f"{__name__}.{module_name}"


def clear_domain_import_cache() -> dict[str, Any]:
    """
    Leert den lokalen Lazy-Import-Cache dieses Packages.

    Zusätzlich werden bereits gesetzte Lazy-Symbole aus globals() entfernt,
    damit spätere Zugriffe sauber neu aufgelöst werden.
    """

    with _IMPORT_CACHE_LOCK:
        cached_modules = sorted(_MODULE_CACHE.keys())
        cached_errors = sorted(_IMPORT_ERRORS.keys())

        _MODULE_CACHE.clear()
        _IMPORT_ERRORS.clear()

    for symbol_name in tuple(SYMBOL_TO_MODULE.keys()):
        globals().pop(symbol_name, None)

    for alias_name in tuple(SYMBOL_ALIASES.keys()):
        globals().pop(alias_name, None)

    for module_name in DOMAIN_MODULES:
        globals().pop(module_name, None)

    return {
        "ok": True,
        "cleared_module_cache": cached_modules,
        "cleared_import_errors": cached_errors,
    }


def clear_domain_runtime_caches() -> dict[str, Any]:
    """
    Ruft Cache-Clear-Funktionen importierter Domain-Submodule auf.

    Es werden keine neuen Module importiert.
    """

    clear_function_names = (
        "clear_cache",
        "clear_caches",
        "clear_domain_cache",
        "clear_domain_caches",
        "clear_sync_result_caches",
        "clear_publication_caches",
        "clear_inventory_caches",
    )

    cleared: list[dict[str, str]] = []
    failed: list[dict[str, str]] = []

    with _IMPORT_CACHE_LOCK:
        cached_modules = list(_MODULE_CACHE.items())

    for module_name, module in cached_modules:
        for function_name in clear_function_names:
            clear_function = getattr(module, function_name, None)

            if not callable(clear_function):
                continue

            try:
                clear_function()
                cleared.append(
                    {
                        "module": module_name,
                        "function": function_name,
                    }
                )
                break

            except Exception as exc:
                failed.append(
                    {
                        "module": module_name,
                        "function": function_name,
                        "error": str(exc),
                        "error_type": exc.__class__.__name__,
                    }
                )
                break

    return {
        "ok": not failed,
        "cleared": cleared,
        "failed": failed,
    }


def clear_domain_caches() -> dict[str, Any]:
    """Leert Runtime-Caches und Import-Caches der Domain-Fassade."""

    runtime_result = clear_domain_runtime_caches()
    import_result = clear_domain_import_cache()

    return {
        "ok": bool(runtime_result.get("ok")) and bool(import_result.get("ok")),
        "runtime": runtime_result,
        "imports": import_result,
    }


# Backwards-compatible alias
clear_domain_cache = clear_domain_caches


def safe_import_module(
    module_name: str,
    *,
    include_traceback: bool = False,
    force_reload: bool = False,
) -> tuple[ModuleType | None, DomainModuleStatus]:
    """
    Importiert ein Domain-Submodul defensiv.

    Rückgabe:
      (module, status)
    """

    import_path = build_module_import_path(module_name)
    required = module_name in REQUIRED_DOMAIN_MODULES
    optional = module_name in OPTIONAL_DOMAIN_MODULES
    db_module = module_name in DB_DOMAIN_MODULES

    try:
        with _IMPORT_CACHE_LOCK:
            if force_reload and module_name in _MODULE_CACHE:
                module = importlib.reload(_MODULE_CACHE[module_name])
                _MODULE_CACHE[module_name] = module
            elif not force_reload and module_name in _MODULE_CACHE:
                module = _MODULE_CACHE[module_name]
            else:
                module = importlib.import_module(import_path)
                _MODULE_CACHE[module_name] = module

            _IMPORT_ERRORS.pop(module_name, None)

        exported_symbols = tuple(
            str(symbol)
            for symbol in safe_tuple(getattr(module, "__all__", ()))
        )

        return module, DomainModuleStatus(
            name=module_name,
            import_path=import_path,
            loaded=True,
            status="loaded",
            required=required,
            optional=optional,
            db_module=db_module,
            symbol_count=len(exported_symbols),
            exported_symbols=exported_symbols,
            error=None,
        )

    except Exception as exc:
        error_payload = exception_to_dict(exc, include_traceback=include_traceback)

        with _IMPORT_CACHE_LOCK:
            _IMPORT_ERRORS[module_name] = error_payload
            _MODULE_CACHE.pop(module_name, None)

        return None, DomainModuleStatus(
            name=module_name,
            import_path=import_path,
            loaded=False,
            status="error",
            required=required,
            optional=optional,
            db_module=db_module,
            symbol_count=0,
            exported_symbols=(),
            error=error_payload,
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
    """Extrahiert Taxonomie-Capabilities aus Domain-Subhealth."""
    result: dict[str, Any] = {
        "supported": True,
        "item_model_version": None,
        "detail_model_version": None,
        "canonical_source_depth": None,
        "legacy_source_depth": None,
        "taxonomy_document_key": None,
        "library_item_taxonomy": {},
        "library_detail_taxonomy": {},
    }

    library_item = subhealth.get("library_item")
    if isinstance(library_item, Mapping):
        result["item_model_version"] = library_item.get("version")
        taxonomy = library_item.get("taxonomy")
        if isinstance(taxonomy, Mapping):
            result["library_item_taxonomy"] = dict(json_safe_local(taxonomy))

    library_detail = subhealth.get("library_detail")
    if isinstance(library_detail, Mapping):
        result["detail_model_version"] = library_detail.get("version")
        taxonomy = library_detail.get("taxonomy")
        if isinstance(taxonomy, Mapping):
            result["library_detail_taxonomy"] = dict(json_safe_local(taxonomy))
            result["canonical_source_depth"] = taxonomy.get("canonical_source_depth")
            result["legacy_source_depth"] = taxonomy.get("legacy_source_depth")
            result["taxonomy_document_key"] = taxonomy.get("taxonomy_document_key")

    return result


def _extract_db_domain_health_from_subhealth(subhealth: Mapping[str, Any]) -> dict[str, Any]:
    """Extrahiert DB-/Publication-/Inventory-Capabilities aus Subhealth."""
    sync_health = subhealth.get("sync_result")
    publication_health = subhealth.get("publication")
    inventory_health = subhealth.get("inventory")

    return {
        "supported": True,
        "sync_result": {
            "available": isinstance(sync_health, Mapping) and _status_is_healthy(sync_health),
            "api_version": sync_health.get("api_version") if isinstance(sync_health, Mapping) else None,
            "model_version": sync_health.get("model_version") if isinstance(sync_health, Mapping) else None,
        },
        "publication": {
            "available": isinstance(publication_health, Mapping) and _status_is_healthy(publication_health),
            "api_version": publication_health.get("api_version") if isinstance(publication_health, Mapping) else None,
            "model_version": publication_health.get("model_version") if isinstance(publication_health, Mapping) else None,
        },
        "inventory": {
            "available": isinstance(inventory_health, Mapping) and _status_is_healthy(inventory_health),
            "api_version": inventory_health.get("api_version") if isinstance(inventory_health, Mapping) else None,
            "model_version": inventory_health.get("model_version") if isinstance(inventory_health, Mapping) else None,
        },
    }


def _build_capabilities(
    *,
    taxonomy: Mapping[str, Any],
    db_domain: Mapping[str, Any],
) -> dict[str, Any]:
    """Baut eine kompakte Capability-Map für Admin-/Health-Routen."""
    return {
        "filesystem_scan_models": True,
        "taxonomy_models": bool(taxonomy.get("supported", False)),
        "db_sync_models": bool(db_domain.get("sync_result", {}).get("available", False)),
        "publication_models": bool(db_domain.get("publication", {}).get("available", False)),
        "inventory_models": bool(db_domain.get("inventory", {}).get("available", False)),
        "vplib_uid_ready": True,
        "published_read_path_ready": bool(db_domain.get("publication", {}).get("available", False)),
        "inventory_read_path_ready": bool(db_domain.get("inventory", {}).get("available", False)),
    }


# ---------------------------------------------------------------------------
# Health
# ---------------------------------------------------------------------------

def get_domain_module_status(
    *,
    include_traceback: bool = False,
    force_reload: bool = False,
    include_optional: bool = True,
) -> dict[str, dict[str, Any]]:
    """Liefert den Importstatus aller Domain-Submodule."""
    statuses: dict[str, dict[str, Any]] = {}

    module_names = DOMAIN_MODULES if include_optional else REQUIRED_DOMAIN_MODULES

    for module_name in module_names:
        _, status = safe_import_module(
            module_name,
            include_traceback=include_traceback,
            force_reload=force_reload,
        )
        statuses[module_name] = status.to_dict()

    return statuses


def get_domain_subhealth(
    *,
    include_traceback: bool = False,
    force_reload: bool = False,
    include_optional: bool = True,
) -> dict[str, dict[str, Any]]:
    """
    Ruft optionale Health-Funktionen der Domain-Submodule auf.

    Falls ein Submodul keine Health-Funktion hat, wird das nicht sofort als
    harter Fehler bewertet. Für `library_item.py` wird ein synthetischer
    Self-Test erzeugt.
    """

    subhealth: dict[str, dict[str, Any]] = {}

    health_functions: dict[str, str | None] = {
        "library_item": None,
        "library_detail": "get_library_detail_model_health",
        "scan_result": "get_scan_result_model_health",
        "sync_result": "get_sync_result_health",
        "publication": "get_publication_health",
        "inventory": "get_inventory_health",
    }

    module_names = DOMAIN_MODULES if include_optional else REQUIRED_DOMAIN_MODULES

    for module_name in module_names:
        function_name = health_functions.get(module_name)

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
                    "required": module_name in REQUIRED_DOMAIN_MODULES,
                    "optional": module_name in OPTIONAL_DOMAIN_MODULES,
                    "db_module": module_name in DB_DOMAIN_MODULES,
                    "error": status.error,
                }
                continue

            if function_name:
                health_function = getattr(module, function_name, None)

                if callable(health_function):
                    try:
                        health = health_function()
                    except TypeError:
                        health = health_function(include_traceback=include_traceback)

                    health_payload = dataclass_to_dict_safe(health)
                    health_payload.setdefault("required", module_name in REQUIRED_DOMAIN_MODULES)
                    health_payload.setdefault("optional", module_name in OPTIONAL_DOMAIN_MODULES)
                    health_payload.setdefault("db_module", module_name in DB_DOMAIN_MODULES)
                    subhealth[module_name] = health_payload
                    continue

            if module_name == "library_item":
                subhealth[module_name] = {
                    "ok": True,
                    "healthy": True,
                    "status": "loaded",
                    "required": True,
                    "optional": False,
                    "db_module": False,
                    "component": "library-item-model",
                    "version": getattr(module, "LIBRARY_ITEM_MODEL_VERSION", None),
                    "taxonomy": {
                        "supported": all(
                            hasattr(module, symbol)
                            for symbol in (
                                "LibraryItemClassification",
                                "normalize_item_taxonomy_payload",
                                "normalize_taxonomy_path",
                                "build_taxonomy_path",
                            )
                        ),
                        "model_has_taxonomy": hasattr(getattr(module, "LibraryItem", object), "__dataclass_fields__")
                        and "taxonomy" in getattr(getattr(module, "LibraryItem", object), "__dataclass_fields__", {}),
                    },
                }
                continue

            subhealth[module_name] = {
                "ok": True,
                "healthy": True,
                "status": "loaded_no_health_function",
                "required": module_name in REQUIRED_DOMAIN_MODULES,
                "optional": module_name in OPTIONAL_DOMAIN_MODULES,
                "db_module": module_name in DB_DOMAIN_MODULES,
                "module": module_name,
            }

        except Exception as exc:
            subhealth[module_name] = {
                "ok": False,
                "healthy": False,
                "status": "health_error",
                "required": module_name in REQUIRED_DOMAIN_MODULES,
                "optional": module_name in OPTIONAL_DOMAIN_MODULES,
                "db_module": module_name in DB_DOMAIN_MODULES,
                "error": exception_to_dict(exc, include_traceback=include_traceback),
            }

    return subhealth


def get_domain_health(
    *,
    include_traceback: bool = False,
    include_subhealth: bool = True,
    include_optional: bool = True,
    force_reload: bool = False,
    strict_optional: bool = False,
) -> dict[str, Any]:
    """
    Liefert einen robusten Health-Status der Domain-Schicht.

    include_optional:
        Wenn True, werden auch sync_result/publication/inventory geprüft.

    strict_optional:
        Wenn True, brechen Fehler in optionalen Modulen den Health-Status.
        Standard ist False, damit neue DB-Domainmodelle inkrementell eingeführt
        werden können.
    """

    module_statuses = get_domain_module_status(
        include_traceback=include_traceback,
        force_reload=force_reload,
        include_optional=include_optional,
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
        for name in REQUIRED_DOMAIN_MODULES
        if name in loaded_modules
    ]

    loaded_optional_modules = [
        name
        for name in OPTIONAL_DOMAIN_MODULES
        if name in loaded_modules
    ]

    loaded_db_modules = [
        name
        for name in DB_DOMAIN_MODULES
        if name in loaded_modules
    ]

    warnings: list[str] = []
    errors: list[str] = []

    for module_name in failed_modules:
        if module_name in REQUIRED_DOMAIN_MODULES:
            errors.append(f"required domain module failed to import: {module_name}")
        elif strict_optional:
            errors.append(f"optional domain module failed to import: {module_name}")
        else:
            warnings.append(f"optional domain module failed to import: {module_name}")

    missing_required = [
        name
        for name in REQUIRED_DOMAIN_MODULES
        if name not in loaded_required_modules
    ]

    for module_name in missing_required:
        errors.append(f"required domain module is not loaded: {module_name}")

    symbol_count = 0

    for status in module_statuses.values():
        try:
            symbol_count += int(status.get("symbol_count", 0))
        except Exception:
            continue

    subhealth: dict[str, dict[str, Any]] = {}

    if include_subhealth:
        subhealth = get_domain_subhealth(
            include_traceback=include_traceback,
            force_reload=force_reload,
            include_optional=include_optional,
        )

        for name, health in subhealth.items():
            if _status_is_healthy(health):
                continue

            if name in REQUIRED_DOMAIN_MODULES:
                errors.append(f"required domain subhealth failed: {name}")
            elif strict_optional:
                errors.append(f"optional domain subhealth failed: {name}")
            else:
                warnings.append(f"optional domain subhealth failed: {name}")

    taxonomy = _extract_taxonomy_health_from_subhealth(subhealth)
    db_domain = _extract_db_domain_health_from_subhealth(subhealth)
    capabilities = _build_capabilities(taxonomy=taxonomy, db_domain=db_domain)

    if taxonomy.get("library_item_taxonomy", {}).get("supported") is False:
        errors.append("library_item taxonomy support is not available")

    healthy = len(errors) == 0

    health = DomainHealth(
        ok=healthy,
        healthy=healthy,
        package=DOMAIN_PACKAGE_NAME,
        component=DOMAIN_COMPONENT_NAME,
        version=DOMAIN_PACKAGE_VERSION,
        generated_at=utc_now_iso(),
        module_count=len(module_statuses),
        loaded_module_count=len(loaded_modules),
        failed_module_count=len(failed_modules),
        required_module_count=len(REQUIRED_DOMAIN_MODULES),
        loaded_required_module_count=len(loaded_required_modules),
        optional_module_count=len(OPTIONAL_DOMAIN_MODULES),
        loaded_optional_module_count=len(loaded_optional_modules),
        db_module_count=len(DB_DOMAIN_MODULES),
        loaded_db_module_count=len(loaded_db_modules),
        symbol_count=symbol_count,
        modules=module_statuses,
        subhealth=subhealth,
        taxonomy=taxonomy,
        db_domain=db_domain,
        capabilities=capabilities,
        warnings=tuple(warnings),
        errors=tuple(errors),
    )

    return health.to_dict()


def is_domain_healthy(
    *,
    include_optional: bool = True,
    strict_optional: bool = False,
) -> bool:
    """Boolescher Health-Check."""
    try:
        return bool(
            get_domain_health(
                include_optional=include_optional,
                strict_optional=strict_optional,
            ).get("healthy")
        )
    except Exception:
        return False


def assert_domain_ready(
    *,
    include_optional: bool = True,
    strict_optional: bool = False,
) -> None:
    """Wirft RuntimeError, wenn die Domain-Schicht nicht bereit ist."""
    health = get_domain_health(
        include_optional=include_optional,
        strict_optional=strict_optional,
    )

    if health.get("healthy"):
        return

    raise RuntimeError(
        f"library domain is not ready: errors={health.get('errors')}"
    )


# ---------------------------------------------------------------------------
# Lazy re-export API
# ---------------------------------------------------------------------------

def load_domain_symbol(symbol_name: str) -> Any:
    """Lädt ein bekanntes Domain-Symbol aus seinem Zielmodul."""
    if symbol_name in SYMBOL_ALIASES:
        module_name, real_symbol_name = SYMBOL_ALIASES[symbol_name]
    else:
        module_name = SYMBOL_TO_MODULE.get(symbol_name)
        real_symbol_name = symbol_name

    if not module_name:
        raise AttributeError(f"module {__name__!r} has no attribute {symbol_name!r}")

    module, status = safe_import_module(module_name)

    if module is None:
        raise ImportError(
            f"could not import domain module {module_name!r}: {status.error}"
        )

    try:
        value = getattr(module, real_symbol_name)
    except AttributeError as exc:
        raise AttributeError(
            f"domain symbol {real_symbol_name!r} not found in module {module.__name__!r}"
        ) from exc

    globals()[symbol_name] = value

    return value


def preload_domain_symbols(
    *,
    fail_fast: bool = False,
    include_optional: bool = True,
) -> dict[str, Any]:
    """
    Lädt bekannte Reexport-Symbole vor.

    Standard:
      fail_fast=False
      include_optional=True
    """

    loaded: dict[str, str] = {}
    errors: dict[str, dict[str, Any] | None] = {}

    symbols = tuple(SYMBOL_TO_MODULE.keys()) + tuple(SYMBOL_ALIASES.keys())

    for symbol_name in symbols:
        module_name = SYMBOL_ALIASES.get(symbol_name, (SYMBOL_TO_MODULE.get(symbol_name), symbol_name))[0]

        if not include_optional and module_name in OPTIONAL_DOMAIN_MODULES:
            continue

        try:
            value = load_domain_symbol(symbol_name)
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
    """Lazy-Reexport bekannter Domain-Symbole und Submodule."""
    if name in SYMBOL_TO_MODULE or name in SYMBOL_ALIASES:
        return load_domain_symbol(name)

    if name in DOMAIN_MODULES:
        module, status = safe_import_module(name)
        if module is None:
            raise ImportError(
                f"could not import domain module {name!r}: {status.error}"
            )
        globals()[name] = module
        return module

    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")


def __dir__() -> list[str]:
    """Ergänzt Lazy-Reexport-Symbole in `dir(library.domain)`."""
    names = set(globals().keys())
    names.update(SYMBOL_TO_MODULE.keys())
    names.update(SYMBOL_ALIASES.keys())
    names.update(DOMAIN_MODULES)
    return sorted(names)


# ---------------------------------------------------------------------------
# Optional eager module handles
# ---------------------------------------------------------------------------

def get_domain_module(module_name: str) -> ModuleType | None:
    """Gibt ein Domain-Submodul zurück, falls es importierbar ist."""
    if module_name not in DOMAIN_MODULES:
        return None

    module, _ = safe_import_module(module_name)
    return module


def get_library_item_module() -> ModuleType | None:
    return get_domain_module("library_item")


def get_library_detail_module() -> ModuleType | None:
    return get_domain_module("library_detail")


def get_scan_result_module() -> ModuleType | None:
    return get_domain_module("scan_result")


def get_sync_result_module() -> ModuleType | None:
    return get_domain_module("sync_result")


def get_publication_module() -> ModuleType | None:
    return get_domain_module("publication")


def get_inventory_module() -> ModuleType | None:
    return get_domain_module("inventory")


# ---------------------------------------------------------------------------
# Convenience helpers
# ---------------------------------------------------------------------------

def build_library_item_from_documents(
    documents: Mapping[str, Any],
    **kwargs: Any,
) -> Any:
    """Convenience-Wrapper für `LibraryItem.from_documents`."""
    item_cls = load_domain_symbol("LibraryItem")

    if not hasattr(item_cls, "from_documents"):
        raise AttributeError("LibraryItem.from_documents is not available")

    return item_cls.from_documents(documents, **kwargs)


def build_library_detail_from_documents(
    documents: Mapping[str, Any],
    **kwargs: Any,
) -> Any:
    """Convenience-Wrapper für `LibraryItemDetail.from_documents`."""
    detail_cls = load_domain_symbol("LibraryItemDetail")

    if not hasattr(detail_cls, "from_documents"):
        raise AttributeError("LibraryItemDetail.from_documents is not available")

    return detail_cls.from_documents(documents, **kwargs)


def extract_domain_taxonomy_from_documents(
    documents: Mapping[str, Any],
    *,
    item: Any = None,
) -> dict[str, Any]:
    """Convenience-Wrapper für Taxonomieextraktion aus Detail-Domain."""
    extractor = load_domain_symbol("extract_taxonomy_from_documents")
    return extractor(documents, item=item)


def build_domain_classification_payload(
    documents: Mapping[str, Any],
    *,
    taxonomy: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    """Convenience-Wrapper für Klassifikationspayloads."""
    builder = load_domain_symbol("build_classification_payload")
    return builder(documents, taxonomy=taxonomy)


def build_domain_sync_response(
    result: Any,
    **kwargs: Any,
) -> dict[str, Any]:
    """Convenience-Wrapper für `sync_result.build_sync_response`."""
    builder = load_domain_symbol("build_sync_response")
    return builder(result, **kwargs)


def build_domain_published_list_response(
    items: Iterable[Any],
    **kwargs: Any,
) -> dict[str, Any]:
    """Convenience-Wrapper für `publication.build_published_list_response`."""
    builder = load_domain_symbol("build_published_list_response")
    return builder(items, **kwargs)


def build_domain_published_detail_response(
    detail: Any,
    **kwargs: Any,
) -> dict[str, Any]:
    """Convenience-Wrapper für `publication.build_published_detail_response`."""
    builder = load_domain_symbol("build_published_detail_response")
    return builder(detail, **kwargs)


def build_domain_inventory_response(
    state: Any,
    **kwargs: Any,
) -> dict[str, Any]:
    """Convenience-Wrapper für `inventory.build_inventory_response`."""
    builder = load_domain_symbol("build_inventory_response")
    return builder(state, **kwargs)


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

__all__: Final[tuple[str, ...]] = (
    "DOMAIN_PACKAGE_VERSION",
    "DOMAIN_PACKAGE_NAME",
    "DOMAIN_COMPONENT_NAME",
    "DOMAIN_MODULES",
    "REQUIRED_DOMAIN_MODULES",
    "OPTIONAL_DOMAIN_MODULES",
    "DB_DOMAIN_MODULES",
    "SYMBOL_TO_MODULE",
    "SYMBOL_ALIASES",

    "DomainModuleStatus",
    "DomainHealth",

    "utc_now_iso",
    "exception_to_dict",
    "json_safe_local",
    "dataclass_to_dict_safe",
    "safe_tuple",
    "build_module_import_path",

    "clear_domain_import_cache",
    "clear_domain_runtime_caches",
    "clear_domain_caches",
    "clear_domain_cache",

    "safe_import_module",
    "get_domain_module_status",
    "get_domain_subhealth",
    "get_domain_health",
    "is_domain_healthy",
    "assert_domain_ready",

    "load_domain_symbol",
    "preload_domain_symbols",

    "get_domain_module",
    "get_library_item_module",
    "get_library_detail_module",
    "get_scan_result_module",
    "get_sync_result_module",
    "get_publication_module",
    "get_inventory_module",

    "build_library_item_from_documents",
    "build_library_detail_from_documents",
    "extract_domain_taxonomy_from_documents",
    "build_domain_classification_payload",
    "build_domain_sync_response",
    "build_domain_published_list_response",
    "build_domain_published_detail_response",
    "build_domain_inventory_response",

    # Reexported domain symbols
    *tuple(SYMBOL_TO_MODULE.keys()),
    *tuple(SYMBOL_ALIASES.keys()),
)