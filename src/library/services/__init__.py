# services/vectoplan-library/src/library/services/__init__.py
"""
Services Package der VECTOPLAN Creative-Library-Schicht.

Dieses Package bündelt die backendseitigen Service-Orchestrierungen für:

1. den dateibasierten Creative-Library-Pfad
2. den einfachen VPLIB-Create-Flow
3. den DB-Sync-Pfad
4. den produktiven DB-basierten Published-Read-Pfad
5. den persistenten User-Inventar-/Hotbar-Pfad

Dateibasierte Services:

- `library_scan_service.py`
  Vollständige Scan-Pipeline:
    Discovery -> Reader -> Validation -> Fingerprint -> Items -> Index

- `library_block_service.py`
  Fachlicher Zugriff auf Blöcke/Objekte über den dateibasierten Scan-/Index-Pfad:
    Liste, Detail, Varianten, Tree

- `library_create_service.py`
  Einfacher Create-Flow:
    Draft -> Validate -> Package Plan -> VPLIB Archive -> optional Save

DB-Services:

- `library_db_sync_service.py`
  Persistiert Scan-/Pipeline-Ergebnisse in die creative_library Tabellen:
    Scan -> Validation -> Fingerprint -> DB Sync -> Published DB State

- `library_published_service.py`
  Produktiver DB-Lesepfad:
    creative_library Tabellen -> Repository -> Published-Service -> API

- `user_inventory_service.py`
  Persistenter User-Inventar-Pfad:
    User hotbar overlay -> Inventar-API -> Service -> Repository -> PostgreSQL

Zielrouten, die auf diese Services zugreifen:

    GET  /api/v1/vplib/library/health
    GET  /api/v1/vplib/library/scan
    POST /api/v1/vplib/library/sync
    GET  /api/v1/vplib/library/db/health
    GET  /api/v1/vplib/library/publication-status

    GET  /api/v1/vplib/library/blocks
    GET  /api/v1/vplib/library/blocks/<block_id>
    GET  /api/v1/vplib/library/blocks/<block_id>/variants
    GET  /api/v1/vplib/library/tree
    GET  /api/v1/vplib/library/inventory

    GET  /api/v1/vplib/create/health
    GET  /api/v1/vplib/create/options
    POST /api/v1/vplib/create/draft
    POST /api/v1/vplib/create/validate
    POST /api/v1/vplib/create/package-plan
    POST /api/v1/vplib/create/download
    POST /api/v1/vplib/create/save

    GET    /api/v1/vplib/inventar_user
    GET    /api/v1/vplib/inventar_user/state
    GET    /api/v1/vplib/inventar_user/slots
    PATCH  /api/v1/vplib/inventar_user/select-slot
    PUT    /api/v1/vplib/inventar_user/slots/<slot_index>
    PATCH  /api/v1/vplib/inventar_user/slots/<slot_index>
    DELETE /api/v1/vplib/inventar_user/slots/<slot_index>

Diese Services sind bewusst getrennt von:

- Flask-Routes
- Admin-Templates
- UI
- SQLAlchemy-Modellen
- direkten DB-Details
- Repository-Implementierungsdetails

Schreibverantwortung:

- Scanner, Reader, Validatoren und Read-Models schreiben nicht.
- Create-Service schreibt nur Source-Packages und nur mit Environment-Flag.
- DB-Sync-Service schreibt in die creative_library DB über das Repository.
- Published-Service liest nur aus der DB.
- User-Inventory-Service schreibt ausschließlich User-Inventar-State und User-Slots.

Taxonomie-Regel:

    Backend-Taxonomie ist kanonisch für:
    - Domain/Reiter
    - Kategorie
    - Subkategorie
    - Source-Pfade
    - Tree-Labels
    - Create-Optionen

DB-/Publication-Regel:

    vplib_uid ist die stabile technische Package-ID.
    family_id und package_id bleiben semantische IDs.
    revision_hash beschreibt die Inhaltsrevision.

User-Inventar-Regel:

    user_id ist in Phase 1 standardmäßig 1.
    inventory_key ist standardmäßig "default".
    Es gibt exakt 9 Hotbar-Slots.
    Die Slot-Auswahl wird persistent in PostgreSQL gespeichert.

Version 0.4.0:

- `user_inventory_service` ist als optionales DB-Service-Modul registriert.
- User-Inventar-Health, Cache-Clear und Convenience-Wrapper sind verfügbar.
- Alte dateibasierte Service-Reexports bleiben rückwärtskompatibel.
- Published-Inventory und User-Inventory werden bewusst nicht unter demselben
  Symbolnamen gemischt.
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

SERVICES_PACKAGE_VERSION: Final[str] = "0.4.0"
SERVICES_PACKAGE_NAME: Final[str] = "library.services"
SERVICES_COMPONENT_NAME: Final[str] = "creative-library-services"

SERVICE_MODULES: Final[tuple[str, ...]] = (
    "library_scan_service",
    "library_block_service",
    "library_create_service",
    "library_db_sync_service",
    "library_published_service",
    "user_inventory_service",
)

REQUIRED_SERVICE_MODULES: Final[tuple[str, ...]] = (
    "library_scan_service",
    "library_block_service",
)

OPTIONAL_SERVICE_MODULES: Final[tuple[str, ...]] = (
    "library_create_service",
    "library_db_sync_service",
    "library_published_service",
    "user_inventory_service",
)

DB_SERVICE_MODULES: Final[tuple[str, ...]] = (
    "library_db_sync_service",
    "library_published_service",
    "user_inventory_service",
)

USER_INVENTORY_SERVICE_MODULES: Final[tuple[str, ...]] = (
    "user_inventory_service",
)


# ---------------------------------------------------------------------------
# Symbol registry
# ---------------------------------------------------------------------------

SYMBOL_TO_MODULE: Final[dict[str, str]] = {
    # -----------------------------------------------------------------------
    # library_scan_service.py
    # -----------------------------------------------------------------------
    "LIBRARY_SCAN_SERVICE_VERSION": "library_scan_service",
    "LIBRARY_SCAN_SERVICE_COMPONENT": "library_scan_service",
    "DEFAULT_SCAN_SERVICE_STATUS": "library_scan_service",
    "SCAN_SERVICE_STATUS_VALUES": "library_scan_service",
    "DEFAULT_CACHE_KEY": "library_scan_service",
    "DEFAULT_CACHE_TTL_SECONDS": "library_scan_service",
    "MAX_CACHE_TTL_SECONDS": "library_scan_service",
    "SOURCE_ROOT_ENV_NAMES": "library_scan_service",
    "LibraryScanServiceOptions": "library_scan_service",
    "LibraryScanPipelineResult": "library_scan_service",
    "clear_library_scan_cache": "library_scan_service",
    "make_cache_key": "library_scan_service",
    "get_cached_scan_result": "library_scan_service",
    "set_cached_scan_result": "library_scan_service",
    "resolve_scan_source_root": "library_scan_service",
    "object_to_options_dict": "library_scan_service",
    "rebuild_options_object": "library_scan_service",
    "make_discovery_options": "library_scan_service",
    "make_reader_options": "library_scan_service",
    "make_fingerprint_options": "library_scan_service",
    "make_validation_options": "library_scan_service",
    "make_summary_options": "library_scan_service",
    "make_index_options": "library_scan_service",
    "discover_library_packages_safe": "library_scan_service",
    "read_package_candidates_safe": "library_scan_service",
    "validate_read_results_safe": "library_scan_service",
    "fingerprint_read_results_safe": "library_scan_service",
    "build_library_items_from_results_safe": "library_scan_service",
    "build_library_index_from_items_safe": "library_scan_service",
    "build_scan_result_from_items_safe": "library_scan_service",
    "build_error_scan_result_safe": "library_scan_service",
    "collect_pipeline_warnings": "library_scan_service",
    "collect_pipeline_errors": "library_scan_service",
    "derive_pipeline_status": "library_scan_service",
    "scan_library_source": "library_scan_service",
    "scan_library_source_no_cache": "library_scan_service",
    "get_library_scan_response": "library_scan_service",
    "get_library_blocks_response": "library_scan_service",
    "get_library_tree_response": "library_scan_service",
    "get_library_index": "library_scan_service",
    "get_library_scan_service_health": "library_scan_service",
    "assert_library_scan_service_ready": "library_scan_service",
    "get_taxonomy_service_safe": "library_scan_service",
    "get_taxonomy_payload_safe": "library_scan_service",
    "get_taxonomy_health_safe": "library_scan_service",
    "extract_taxonomy_version": "library_scan_service",

    # -----------------------------------------------------------------------
    # library_block_service.py
    # -----------------------------------------------------------------------
    "LIBRARY_BLOCK_SERVICE_VERSION": "library_block_service",
    "LIBRARY_BLOCK_SERVICE_COMPONENT": "library_block_service",
    "DEFAULT_BLOCK_SERVICE_STATUS": "library_block_service",
    "BLOCK_SERVICE_STATUS_VALUES": "library_block_service",
    "DEFAULT_BLOCK_LIST_LIMIT": "library_block_service",
    "MAX_BLOCK_LIST_LIMIT": "library_block_service",
    "DEFAULT_SCAN_CACHE_TTL_SECONDS": "library_block_service",
    "UNKNOWN_TAXONOMY_VALUE": "library_block_service",
    "LibraryBlockServiceOptions": "library_block_service",
    "LibraryBlockServiceResult": "library_block_service",
    "normalize_service_status": "library_block_service",
    "get_attr_or_key": "library_block_service",
    "deep_get": "library_block_service",
    "parse_limit": "library_block_service",
    "parse_offset": "library_block_service",
    "parse_force_refresh": "library_block_service",
    "get_item_id": "library_block_service",
    "get_item_status": "library_block_service",
    "get_item_taxonomy": "library_block_service",
    "item_to_summary": "library_block_service",
    "item_matches_id": "library_block_service",
    "item_matches_filter": "library_block_service",
    "get_index_items": "library_block_service",
    "find_library_item_by_id": "library_block_service",
    "extract_documents_from_read_result": "library_block_service",
    "read_result_matches_id": "library_block_service",
    "find_matching_read_result": "library_block_service",
    "normalize_variant_payloads": "library_block_service",
    "paginate_items": "library_block_service",
    "coerce_block_service_options": "library_block_service",
    "get_pipeline_read_results": "library_block_service",
    "get_pipeline_validation_results": "library_block_service",
    "get_pipeline_fingerprint_results": "library_block_service",
    "get_pipeline_items": "library_block_service",
    "get_pipeline_index": "library_block_service",
    "get_pipeline_taxonomy_version": "library_block_service",
    "scan_for_block_access": "library_block_service",
    "list_library_blocks": "library_block_service",
    "get_library_block_detail": "library_block_service",
    "get_library_block_variants": "library_block_service",
    "get_library_tree": "library_block_service",
    "scan_library_for_blocks": "library_block_service",
    "list_library_blocks_response": "library_block_service",
    "get_library_block_detail_response": "library_block_service",
    "get_library_block_variants_response": "library_block_service",
    "get_library_tree_response_from_block_service": "library_block_service",
    "scan_library_for_blocks_response": "library_block_service",
    "get_taxonomy_health_payload": "library_block_service",
    "get_library_block_service_health": "library_block_service",
    "assert_library_block_service_ready": "library_block_service",

    # -----------------------------------------------------------------------
    # library_create_service.py
    # -----------------------------------------------------------------------
    "LIBRARY_CREATE_SERVICE_VERSION": "library_create_service",
    "LIBRARY_CREATE_SERVICE_COMPONENT": "library_create_service",
    "DEFAULT_SCHEMA_VERSION": "library_create_service",
    "DEFAULT_PACKAGE_VERSION": "library_create_service",
    "ENV_SOURCE_ROOT_PRIMARY": "library_create_service",
    "ENV_SOURCE_ROOT_SECONDARY": "library_create_service",
    "ENV_WRITE_ENABLED": "library_create_service",
    "ENV_OVERWRITE_ENABLED": "library_create_service",
    "ENV_DEBUG": "library_create_service",
    "DEFAULT_OBJECT_KIND": "library_create_service",
    "DEFAULT_PRIMITIVE_SHAPE": "library_create_service",
    "DEFAULT_UNIT": "library_create_service",
    "REQUIRED_TAXONOMY_FIELDS": "library_create_service",
    "ALLOWED_OBJECT_KINDS": "library_create_service",
    "ALLOWED_PRIMITIVE_SHAPES": "library_create_service",
    "ALLOWED_UNITS": "library_create_service",
    "CreateIssue": "library_create_service",
    "CreateResult": "library_create_service",
    "NormalizedCreateDraft": "library_create_service",
    "CreateDraftNormalizationError": "library_create_service",
    "get_service_health": "library_create_service",
    "get_create_options": "library_create_service",
    "build_draft": "library_create_service",
    "validate_draft": "library_create_service",
    "build_package_plan": "library_create_service",
    "build_vplib_archive": "library_create_service",
    "save_package": "library_create_service",
    "build_package_documents": "library_create_service",
    "get_source_root": "library_create_service",
    "health": "library_create_service",
    "get_options": "library_create_service",
    "create_draft": "library_create_service",
    "package_plan": "library_create_service",

    # -----------------------------------------------------------------------
    # library_db_sync_service.py
    # -----------------------------------------------------------------------
    "LIBRARY_DB_SYNC_SERVICE_NAME": "library_db_sync_service",
    "LIBRARY_DB_SYNC_COMPONENT_NAME": "library_db_sync_service",
    "LIBRARY_DB_SYNC_API_VERSION": "library_db_sync_service",
    "LIBRARY_DB_SYNC_IMPLEMENTATION_STAGE": "library_db_sync_service",
    "ENV_SYNC_ENABLED": "library_db_sync_service",
    "ENV_SYNC_STRICT": "library_db_sync_service",
    "ENV_SYNC_AUTOCOMMIT": "library_db_sync_service",
    "ENV_SYNC_MARK_MISSING_DELETED": "library_db_sync_service",
    "ENV_SYNC_CONTINUE_ON_CANDIDATE_ERROR": "library_db_sync_service",
    "ENV_SYNC_INCLUDE_RAW_DOCUMENTS": "library_db_sync_service",
    "LibraryDbSyncServiceError": "library_db_sync_service",
    "LibraryDbSyncDisabledError": "library_db_sync_service",
    "LibraryDbSyncImportError": "library_db_sync_service",
    "LibraryDbSyncValidationError": "library_db_sync_service",
    "LibraryDbSyncCandidateError": "library_db_sync_service",
    "LibraryDbSyncServiceConfig": "library_db_sync_service",
    "LibraryDbSyncService": "library_db_sync_service",
    "create_library_db_sync_service": "library_db_sync_service",
    "get_library_db_sync_service": "library_db_sync_service",
    "sync_library_to_db": "library_db_sync_service",
    "sync_scan_result_to_db": "library_db_sync_service",
    "get_library_db_sync_service_health": "library_db_sync_service",
    "assert_library_db_sync_service_ready": "library_db_sync_service",
    "clear_library_db_sync_service_cache": "library_db_sync_service",
    "clear_library_db_sync_service_caches": "library_db_sync_service",
    "clear_db_sync_cache": "library_db_sync_service",
    "clear_db_sync_caches": "library_db_sync_service",
    "extract_pipeline_candidates": "library_db_sync_service",
    "build_family_upsert_payload": "library_db_sync_service",
    "build_revision_upsert_payload": "library_db_sync_service",
    "extract_variant_payloads": "library_db_sync_service",
    "extract_asset_payloads": "library_db_sync_service",
    "extract_document_payloads": "library_db_sync_service",
    "extract_issue_payloads": "library_db_sync_service",
    "build_sync_response": "library_db_sync_service",

    # -----------------------------------------------------------------------
    # library_published_service.py
    # -----------------------------------------------------------------------
    "LIBRARY_PUBLISHED_SERVICE_NAME": "library_published_service",
    "LIBRARY_PUBLISHED_COMPONENT_NAME": "library_published_service",
    "LIBRARY_PUBLISHED_API_VERSION": "library_published_service",
    "LIBRARY_PUBLISHED_IMPLEMENTATION_STAGE": "library_published_service",
    "ENV_PUBLISHED_READ_ENABLED": "library_published_service",
    "ENV_PUBLISHED_READ_STRICT": "library_published_service",
    "ENV_PUBLISHED_DEFAULT_LIMIT": "library_published_service",
    "ENV_PUBLISHED_MAX_LIMIT": "library_published_service",
    "ENV_PUBLISHED_INCLUDE_UNPUBLISHED": "library_published_service",
    "ENV_PUBLISHED_INCLUDE_DELETED": "library_published_service",
    "LibraryPublishedServiceError": "library_published_service",
    "LibraryPublishedServiceDisabledError": "library_published_service",
    "LibraryPublishedServiceImportError": "library_published_service",
    "LibraryPublishedNotFound": "library_published_service",
    "LibraryPublishedValidationError": "library_published_service",
    "LibraryPublishedServiceConfig": "library_published_service",
    "LibraryPublishedService": "library_published_service",
    "create_library_published_service": "library_published_service",
    "get_library_published_service": "library_published_service",
    "list_published_blocks": "library_published_service",
    "list_published_blocks_response": "library_published_service",
    "get_published_block_detail": "library_published_service",
    "get_published_block_detail_response": "library_published_service",
    "get_published_block_variants": "library_published_service",
    "get_published_block_variants_response": "library_published_service",
    "get_published_tree": "library_published_service",
    "get_published_tree_response": "library_published_service",
    "get_inventory_state": "library_published_service",
    "get_inventory_response": "library_published_service",
    "get_publication_status": "library_published_service",
    "get_library_published_service_health": "library_published_service",
    "assert_library_published_service_ready": "library_published_service",
    "clear_library_published_service_cache": "library_published_service",
    "clear_library_published_service_caches": "library_published_service",
    "clear_published_service_cache": "library_published_service",
    "clear_published_service_caches": "library_published_service",

    # -----------------------------------------------------------------------
    # user_inventory_service.py
    # -----------------------------------------------------------------------
    "USER_INVENTORY_SERVICE_VERSION": "user_inventory_service",
    "USER_INVENTORY_COMPONENT": "user_inventory_service",
    "DEFAULT_USER_ID": "user_inventory_service",
    "DEFAULT_INVENTORY_KEY": "user_inventory_service",
    "DEFAULT_SLOT_COUNT": "user_inventory_service",
    "MIN_SLOT_INDEX": "user_inventory_service",
    "MAX_SLOT_INDEX": "user_inventory_service",
    "STATUS_CACHE_CLEARED": "user_inventory_service",
    "STATUS_ERROR": "user_inventory_service",
    "STATUS_HEALTHY": "user_inventory_service",
    "STATUS_OK": "user_inventory_service",
    "STATUS_READY": "user_inventory_service",
    "STATUS_SELECTED": "user_inventory_service",
    "STATUS_SLOT_CLEARED": "user_inventory_service",
    "STATUS_SLOT_SET": "user_inventory_service",
    "UserInventoryServiceError": "user_inventory_service",
    "UserInventoryServiceValidationError": "user_inventory_service",
    "select_slot_response": "user_inventory_service",
    "set_slot_response": "user_inventory_service",
    "clear_slot_response": "user_inventory_service",
    "clear_cache_response": "user_inventory_service",
    "get_service_health_response": "user_inventory_service",
    "inventory_payload_from_snapshot": "user_inventory_service",
    "empty_slot_payload": "user_inventory_service",
    "extract_item_payload": "user_inventory_service",
    "normalize_payload": "user_inventory_service",
    "normalize_inventory_key": "user_inventory_service",
    "normalize_user_id": "user_inventory_service",
    "normalize_slot_index": "user_inventory_service",
    "slot_key_for_index": "user_inventory_service",
    "success_response": "user_inventory_service",
    "failure_response": "user_inventory_service",
}


# ---------------------------------------------------------------------------
# Symbol aliases for clearer names
# ---------------------------------------------------------------------------

SYMBOL_ALIASES: Final[dict[str, tuple[str, str]]] = {
    "db_sync_library_to_db": ("library_db_sync_service", "sync_library_to_db"),
    "db_sync_scan_result_to_db": ("library_db_sync_service", "sync_scan_result_to_db"),
    "db_sync_service_health": ("library_db_sync_service", "get_library_db_sync_service_health"),

    "published_blocks_response": ("library_published_service", "list_published_blocks_response"),
    "published_block_detail_response": ("library_published_service", "get_published_block_detail_response"),
    "published_block_variants_response": ("library_published_service", "get_published_block_variants_response"),
    "published_tree_response": ("library_published_service", "get_published_tree_response"),
    "published_inventory_response": ("library_published_service", "get_inventory_response"),
    "published_service_health": ("library_published_service", "get_library_published_service_health"),

    "user_inventory_get_inventory_response": ("user_inventory_service", "get_inventory_response"),
    "user_inventory_select_slot_response": ("user_inventory_service", "select_slot_response"),
    "user_inventory_set_slot_response": ("user_inventory_service", "set_slot_response"),
    "user_inventory_clear_slot_response": ("user_inventory_service", "clear_slot_response"),
    "user_inventory_clear_cache_response": ("user_inventory_service", "clear_cache_response"),
    "user_inventory_service_health": ("user_inventory_service", "get_service_health_response"),
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
class ServiceModuleStatus:
    """Importstatus eines Service-Submoduls."""

    name: str
    import_path: str
    loaded: bool
    status: str
    required: bool = False
    optional: bool = False
    db_service: bool = False
    user_inventory_service: bool = False
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
            "db_service": self.db_service,
            "user_inventory_service": self.user_inventory_service,
            "symbol_count": self.symbol_count,
            "exported_symbols": list(self.exported_symbols),
            "error": json_safe(self.error),
        }


@dataclass(frozen=True)
class ServicesHealth:
    """Health-Modell für `library.services`."""

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
    db_service_count: int
    loaded_db_service_count: int
    user_inventory_service_count: int
    loaded_user_inventory_service_count: int
    symbol_count: int
    modules: dict[str, dict[str, Any]]
    subhealth: dict[str, dict[str, Any]] = field(default_factory=dict)
    db_services: dict[str, Any] = field(default_factory=dict)
    user_inventory_services: dict[str, Any] = field(default_factory=dict)
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
            "db_service_count": self.db_service_count,
            "loaded_db_service_count": self.loaded_db_service_count,
            "user_inventory_service_count": self.user_inventory_service_count,
            "loaded_user_inventory_service_count": self.loaded_user_inventory_service_count,
            "symbol_count": self.symbol_count,
            "modules": json_safe(self.modules),
            "subhealth": json_safe(self.subhealth),
            "db_services": json_safe(self.db_services),
            "user_inventory_services": json_safe(self.user_inventory_services),
            "capabilities": json_safe(self.capabilities),
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


def payload_from_mapping_and_kwargs(
    payload: Mapping[str, Any] | None = None,
    kwargs: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    """Kombiniert optionales Payload-Mapping und Keyword-Argumente."""
    result: dict[str, Any] = {}

    if isinstance(payload, Mapping):
        result.update(dict(payload))

    if isinstance(kwargs, Mapping):
        result.update(dict(kwargs))

    return result


def build_module_import_path(module_name: str) -> str:
    """Baut den vollständigen Importpfad eines Service-Submoduls."""
    return f"{__name__}.{module_name}"


def clear_services_import_cache() -> dict[str, Any]:
    """Leert den lokalen Lazy-Import-Cache dieses Packages."""
    with _IMPORT_CACHE_LOCK:
        cached_modules = sorted(_MODULE_CACHE.keys())
        cached_errors = sorted(_IMPORT_ERRORS.keys())
        _MODULE_CACHE.clear()
        _IMPORT_ERRORS.clear()

    for symbol_name in tuple(SYMBOL_TO_MODULE.keys()):
        globals().pop(symbol_name, None)

    for alias_name in tuple(SYMBOL_ALIASES.keys()):
        globals().pop(alias_name, None)

    for module_name in SERVICE_MODULES:
        globals().pop(module_name, None)

    return {
        "ok": True,
        "cleared_module_cache": cached_modules,
        "cleared_import_errors": cached_errors,
    }


def clear_services_runtime_caches() -> dict[str, Any]:
    """
    Leert bekannte Runtime-Caches der Service-Schicht.

    Es werden nur lazy verfügbare Clear-Funktionen aufgerufen.
    Einzelne Fehler werden gesammelt.
    """

    clear_function_names = (
        "clear_library_scan_cache",
        "clear_library_db_sync_service_cache",
        "clear_library_published_service_cache",
        "user_inventory_clear_cache_response",
    )

    cleared: list[dict[str, Any]] = []
    errors: list[dict[str, Any]] = []

    for function_name in clear_function_names:
        try:
            clear_function = load_service_symbol(function_name)

            if callable(clear_function):
                result = clear_function()
                cleared.append(
                    {
                        "function": function_name,
                        "result": json_safe(result),
                    }
                )
        except Exception as exc:
            errors.append(
                {
                    "function": function_name,
                    "error": exception_to_dict(exc),
                }
            )

    return {
        "ok": not errors,
        "cleared": cleared,
        "errors": errors,
    }


def clear_services_caches() -> dict[str, Any]:
    """Leert Runtime- und Import-Caches der Services-Schicht."""

    runtime = clear_services_runtime_caches()
    imports = clear_services_import_cache()

    return {
        "ok": bool(runtime.get("ok")) and bool(imports.get("ok")),
        "runtime": runtime,
        "imports": imports,
    }


clear_services_cache = clear_services_caches


def safe_import_module(
    module_name: str,
    *,
    include_traceback: bool = False,
    force_reload: bool = False,
) -> tuple[ModuleType | None, ServiceModuleStatus]:
    """
    Importiert ein Service-Submodul defensiv.

    Rückgabe:
      (module, status)
    """

    import_path = build_module_import_path(module_name)
    required = module_name in REQUIRED_SERVICE_MODULES
    optional = module_name in OPTIONAL_SERVICE_MODULES
    db_service = module_name in DB_SERVICE_MODULES
    user_inventory_service = module_name in USER_INVENTORY_SERVICE_MODULES

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

        return module, ServiceModuleStatus(
            name=module_name,
            import_path=import_path,
            loaded=True,
            status="loaded",
            required=required,
            optional=optional,
            db_service=db_service,
            user_inventory_service=user_inventory_service,
            symbol_count=len(exported_symbols),
            exported_symbols=exported_symbols,
            error=None,
        )

    except Exception as exc:
        error_payload = exception_to_dict(exc, include_traceback=include_traceback)

        with _IMPORT_CACHE_LOCK:
            _MODULE_CACHE.pop(module_name, None)
            _IMPORT_ERRORS[module_name] = error_payload

        return None, ServiceModuleStatus(
            name=module_name,
            import_path=import_path,
            loaded=False,
            status="error",
            required=required,
            optional=optional,
            db_service=db_service,
            user_inventory_service=user_inventory_service,
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


def _extract_db_service_health_from_subhealth(subhealth: Mapping[str, Any]) -> dict[str, Any]:
    """Extrahiert DB-Service-Capabilities aus Subhealth."""
    sync_health = subhealth.get("library_db_sync_service")
    published_health = subhealth.get("library_published_service")
    user_inventory_health = subhealth.get("user_inventory_service")

    return {
        "supported": True,
        "sync": {
            "available": isinstance(sync_health, Mapping) and _status_is_healthy(sync_health),
            "api_version": sync_health.get("api_version") if isinstance(sync_health, Mapping) else None,
            "implementation_stage": sync_health.get("implementation_stage") if isinstance(sync_health, Mapping) else None,
            "status": sync_health.get("status") if isinstance(sync_health, Mapping) else None,
        },
        "published": {
            "available": isinstance(published_health, Mapping) and _status_is_healthy(published_health),
            "api_version": published_health.get("api_version") if isinstance(published_health, Mapping) else None,
            "implementation_stage": published_health.get("implementation_stage") if isinstance(published_health, Mapping) else None,
            "status": published_health.get("status") if isinstance(published_health, Mapping) else None,
        },
        "user_inventory": {
            "available": isinstance(user_inventory_health, Mapping) and _status_is_healthy(user_inventory_health),
            "version": user_inventory_health.get("version") if isinstance(user_inventory_health, Mapping) else None,
            "component": user_inventory_health.get("component") if isinstance(user_inventory_health, Mapping) else None,
            "status": user_inventory_health.get("status") if isinstance(user_inventory_health, Mapping) else None,
        },
    }


def _extract_user_inventory_service_health_from_subhealth(subhealth: Mapping[str, Any]) -> dict[str, Any]:
    """Extrahiert User-Inventar-Service-Capabilities aus Subhealth."""
    user_inventory_health = subhealth.get("user_inventory_service")

    if not isinstance(user_inventory_health, Mapping):
        return {
            "supported": True,
            "available": False,
            "status": "missing_subhealth",
            "health": {},
        }

    return {
        "supported": True,
        "available": _status_is_healthy(user_inventory_health),
        "status": user_inventory_health.get("status"),
        "version": user_inventory_health.get("version"),
        "component": user_inventory_health.get("component"),
        "health": json_safe(user_inventory_health),
    }


def _build_capabilities(db_services: Mapping[str, Any]) -> dict[str, Any]:
    """Baut Capability-Map für Health/Admin."""
    user_inventory_available = bool(db_services.get("user_inventory", {}).get("available", False))

    return {
        "filesystem_scan_service": True,
        "filesystem_block_service": True,
        "create_service": "library_create_service" in SERVICE_MODULES,
        "db_sync_service": bool(db_services.get("sync", {}).get("available", False)),
        "published_read_service": bool(db_services.get("published", {}).get("available", False)),
        "user_inventory_service": user_inventory_available,
        "sync_route_ready": bool(db_services.get("sync", {}).get("available", False)),
        "published_blocks_route_ready": bool(db_services.get("published", {}).get("available", False)),
        "published_detail_route_ready": bool(db_services.get("published", {}).get("available", False)),
        "published_tree_route_ready": bool(db_services.get("published", {}).get("available", False)),
        "inventory_route_ready": bool(db_services.get("published", {}).get("available", False)),
        "user_inventory_route_ready": user_inventory_available,
        "user_inventory_persistence_ready": user_inventory_available,
    }


# ---------------------------------------------------------------------------
# Health
# ---------------------------------------------------------------------------

def get_service_module_status(
    *,
    include_traceback: bool = False,
    force_reload: bool = False,
    include_optional: bool = True,
) -> dict[str, dict[str, Any]]:
    """Liefert den Importstatus aller Service-Submodule."""
    statuses: dict[str, dict[str, Any]] = {}

    module_names = SERVICE_MODULES if include_optional else REQUIRED_SERVICE_MODULES

    for module_name in module_names:
        _, status = safe_import_module(
            module_name,
            include_traceback=include_traceback,
            force_reload=force_reload,
        )
        statuses[module_name] = status.to_dict()

    return statuses


def get_service_subhealth(
    *,
    include_traceback: bool = False,
    force_reload: bool = False,
    include_optional: bool = True,
) -> dict[str, dict[str, Any]]:
    """Ruft optionale Health-Funktionen der Service-Submodule auf."""
    subhealth: dict[str, dict[str, Any]] = {}

    health_functions = {
        "library_scan_service": "get_library_scan_service_health",
        "library_block_service": "get_library_block_service_health",
        "library_create_service": "get_service_health",
        "library_db_sync_service": "get_library_db_sync_service_health",
        "library_published_service": "get_library_published_service_health",
        "user_inventory_service": "get_service_health_response",
    }

    module_names = SERVICE_MODULES if include_optional else REQUIRED_SERVICE_MODULES

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
                    "required": module_name in REQUIRED_SERVICE_MODULES,
                    "optional": module_name in OPTIONAL_SERVICE_MODULES,
                    "db_service": module_name in DB_SERVICE_MODULES,
                    "user_inventory_service": module_name in USER_INVENTORY_SERVICE_MODULES,
                    "error": status.error,
                }
                continue

            if not function_name:
                subhealth[module_name] = {
                    "ok": True,
                    "healthy": True,
                    "status": "loaded_no_health_function",
                    "required": module_name in REQUIRED_SERVICE_MODULES,
                    "optional": module_name in OPTIONAL_SERVICE_MODULES,
                    "db_service": module_name in DB_SERVICE_MODULES,
                    "user_inventory_service": module_name in USER_INVENTORY_SERVICE_MODULES,
                    "module": module_name,
                }
                continue

            health_function = getattr(module, function_name, None)

            if not callable(health_function):
                subhealth[module_name] = {
                    "ok": False,
                    "healthy": False,
                    "status": "missing_health_function",
                    "required": module_name in REQUIRED_SERVICE_MODULES,
                    "optional": module_name in OPTIONAL_SERVICE_MODULES,
                    "db_service": module_name in DB_SERVICE_MODULES,
                    "user_inventory_service": module_name in USER_INVENTORY_SERVICE_MODULES,
                    "function": function_name,
                }
                continue

            try:
                health = health_function()
            except TypeError:
                health = health_function(include_traceback=include_traceback)

            health_payload = dataclass_to_dict_safe(health)
            health_payload.setdefault("required", module_name in REQUIRED_SERVICE_MODULES)
            health_payload.setdefault("optional", module_name in OPTIONAL_SERVICE_MODULES)
            health_payload.setdefault("db_service", module_name in DB_SERVICE_MODULES)
            health_payload.setdefault("user_inventory_service", module_name in USER_INVENTORY_SERVICE_MODULES)
            subhealth[module_name] = health_payload

        except Exception as exc:
            subhealth[module_name] = {
                "ok": False,
                "healthy": False,
                "status": "health_error",
                "required": module_name in REQUIRED_SERVICE_MODULES,
                "optional": module_name in OPTIONAL_SERVICE_MODULES,
                "db_service": module_name in DB_SERVICE_MODULES,
                "user_inventory_service": module_name in USER_INVENTORY_SERVICE_MODULES,
                "error": exception_to_dict(exc, include_traceback=include_traceback),
            }

    return subhealth


def get_services_health(
    *,
    include_traceback: bool = False,
    include_subhealth: bool = True,
    include_optional: bool = True,
    force_reload: bool = False,
    strict_optional: bool = False,
) -> dict[str, Any]:
    """
    Liefert einen robusten Health-Status der Services-Schicht.

    Diese Funktion führt keinen Scan und keinen DB-Sync aus.

    include_optional:
        Wenn True, werden Create-, DB-Sync-, Published- und User-Inventory-Service geprüft.

    strict_optional:
        Wenn True, führen Fehler in optionalen Services zu unhealthy.
        Standard ist False, damit der alte dateibasierte Pfad während der
        Migration weiter funktioniert.
    """

    module_statuses = get_service_module_status(
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
        for name in REQUIRED_SERVICE_MODULES
        if name in loaded_modules
    ]

    loaded_optional_modules = [
        name
        for name in OPTIONAL_SERVICE_MODULES
        if name in loaded_modules
    ]

    loaded_db_services = [
        name
        for name in DB_SERVICE_MODULES
        if name in loaded_modules
    ]

    loaded_user_inventory_services = [
        name
        for name in USER_INVENTORY_SERVICE_MODULES
        if name in loaded_modules
    ]

    warnings: list[str] = []
    errors: list[str] = []

    for module_name in failed_modules:
        if module_name in REQUIRED_SERVICE_MODULES:
            errors.append(f"required service module failed to import: {module_name}")
        elif strict_optional:
            errors.append(f"optional service module failed to import: {module_name}")
        else:
            warnings.append(f"optional service module failed to import: {module_name}")

    missing_required = [
        name
        for name in REQUIRED_SERVICE_MODULES
        if name not in loaded_required_modules
    ]

    for module_name in missing_required:
        errors.append(f"required service module is not loaded: {module_name}")

    symbol_count = 0

    for status in module_statuses.values():
        try:
            symbol_count += int(status.get("symbol_count", 0))
        except Exception:
            continue

    subhealth: dict[str, dict[str, Any]] = {}

    if include_subhealth:
        subhealth = get_service_subhealth(
            include_traceback=include_traceback,
            force_reload=force_reload,
            include_optional=include_optional,
        )

        for name, health in subhealth.items():
            if _status_is_healthy(health):
                continue

            if name in REQUIRED_SERVICE_MODULES:
                errors.append(f"required service subhealth failed: {name}")
            elif strict_optional:
                errors.append(f"optional service subhealth failed: {name}")
            else:
                warnings.append(f"optional service subhealth failed: {name}")

    db_services = _extract_db_service_health_from_subhealth(subhealth)
    user_inventory_services = _extract_user_inventory_service_health_from_subhealth(subhealth)
    capabilities = _build_capabilities(db_services)

    healthy = len(errors) == 0

    health = ServicesHealth(
        ok=healthy,
        healthy=healthy,
        package=SERVICES_PACKAGE_NAME,
        component=SERVICES_COMPONENT_NAME,
        version=SERVICES_PACKAGE_VERSION,
        generated_at=utc_now_iso(),
        module_count=len(module_statuses),
        loaded_module_count=len(loaded_modules),
        failed_module_count=len(failed_modules),
        required_module_count=len(REQUIRED_SERVICE_MODULES),
        loaded_required_module_count=len(loaded_required_modules),
        optional_module_count=len(OPTIONAL_SERVICE_MODULES),
        loaded_optional_module_count=len(loaded_optional_modules),
        db_service_count=len(DB_SERVICE_MODULES),
        loaded_db_service_count=len(loaded_db_services),
        user_inventory_service_count=len(USER_INVENTORY_SERVICE_MODULES),
        loaded_user_inventory_service_count=len(loaded_user_inventory_services),
        symbol_count=symbol_count,
        modules=module_statuses,
        subhealth=subhealth,
        db_services=db_services,
        user_inventory_services=user_inventory_services,
        capabilities=capabilities,
        warnings=tuple(warnings),
        errors=tuple(errors),
    )

    return health.to_dict()


def is_services_healthy(
    *,
    include_optional: bool = True,
    strict_optional: bool = False,
) -> bool:
    """Boolescher Health-Check."""
    try:
        return bool(
            get_services_health(
                include_optional=include_optional,
                strict_optional=strict_optional,
            ).get("healthy")
        )
    except Exception:
        return False


def assert_services_ready(
    *,
    include_optional: bool = True,
    strict_optional: bool = False,
) -> None:
    """Wirft RuntimeError, wenn die Services-Schicht nicht bereit ist."""
    health = get_services_health(
        include_optional=include_optional,
        strict_optional=strict_optional,
    )

    if health.get("healthy"):
        return

    raise RuntimeError(
        f"library services are not ready: errors={health.get('errors')}"
    )


# ---------------------------------------------------------------------------
# Lazy re-export API
# ---------------------------------------------------------------------------

def load_service_symbol(symbol_name: str) -> Any:
    """Lädt ein bekanntes Service-Symbol aus seinem Zielmodul."""
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
            f"could not import service module {module_name!r}: {status.error}"
        )

    try:
        value = getattr(module, real_symbol_name)
    except AttributeError as exc:
        raise AttributeError(
            f"service symbol {real_symbol_name!r} not found in module {module.__name__!r}"
        ) from exc

    globals()[symbol_name] = value

    return value


def preload_service_symbols(
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

        if not include_optional and module_name in OPTIONAL_SERVICE_MODULES:
            continue

        try:
            value = load_service_symbol(symbol_name)
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
    """Lazy-Reexport bekannter Service-Symbole und Submodule."""
    if name in SYMBOL_TO_MODULE or name in SYMBOL_ALIASES:
        return load_service_symbol(name)

    if name in SERVICE_MODULES:
        module, status = safe_import_module(name)
        if module is None:
            raise ImportError(
                f"could not import service module {name!r}: {status.error}"
            )
        globals()[name] = module
        return module

    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")


def __dir__() -> list[str]:
    """Ergänzt Lazy-Reexport-Symbole in `dir(library.services)`."""
    names = set(globals().keys())
    names.update(SYMBOL_TO_MODULE.keys())
    names.update(SYMBOL_ALIASES.keys())
    names.update(SERVICE_MODULES)
    return sorted(names)


# ---------------------------------------------------------------------------
# Module access helpers
# ---------------------------------------------------------------------------

def get_service_module(module_name: str) -> ModuleType | None:
    """Gibt ein Service-Submodul zurück, falls es importierbar ist."""
    if module_name not in SERVICE_MODULES:
        return None

    module, _ = safe_import_module(module_name)
    return module


def get_library_scan_service_module() -> ModuleType | None:
    return get_service_module("library_scan_service")


def get_library_block_service_module() -> ModuleType | None:
    return get_service_module("library_block_service")


def get_library_create_service_module() -> ModuleType | None:
    return get_service_module("library_create_service")


def get_library_db_sync_service_module() -> ModuleType | None:
    return get_service_module("library_db_sync_service")


def get_library_published_service_module() -> ModuleType | None:
    return get_service_module("library_published_service")


def get_user_inventory_service_module() -> ModuleType | None:
    return get_service_module("user_inventory_service")


# ---------------------------------------------------------------------------
# Existing filesystem convenience helpers
# ---------------------------------------------------------------------------

def scan_source(
    *,
    source_root: Any = None,
    options: Any = None,
    force_refresh: bool = False,
) -> Any:
    """Convenience-Wrapper für vollständigen Source-Scan."""
    scan_library_source = load_service_symbol("scan_library_source")

    return scan_library_source(
        source_root=source_root,
        options=options,
        force_refresh=force_refresh,
    )


def scan_source_response(
    *,
    source_root: Any = None,
    options: Any = None,
    force_refresh: bool = False,
) -> dict[str, Any]:
    """Convenience-Wrapper für eine JSON-kompatible Scan-Antwort."""
    get_library_scan_response = load_service_symbol("get_library_scan_response")

    return get_library_scan_response(
        source_root=source_root,
        options=options,
        force_refresh=force_refresh,
    )


def list_blocks_response(
    *,
    source_root: Any = None,
    domain: Any = None,
    category: Any = None,
    subcategory: Any = None,
    object_kind: Any = None,
    q: Any = None,
    options: Any = None,
) -> dict[str, Any]:
    """Convenience-Wrapper für dateibasierte Blocklisten-Antworten."""
    list_library_blocks_response = load_service_symbol("list_library_blocks_response")

    return list_library_blocks_response(
        source_root=source_root,
        domain=domain,
        category=category,
        subcategory=subcategory,
        object_kind=object_kind,
        q=q,
        options=options,
    )


def block_detail_response(
    block_id: Any,
    *,
    source_root: Any = None,
    options: Any = None,
) -> dict[str, Any]:
    """Convenience-Wrapper für dateibasierte Blockdetails."""
    get_library_block_detail_response = load_service_symbol("get_library_block_detail_response")

    return get_library_block_detail_response(
        block_id,
        source_root=source_root,
        options=options,
    )


def block_variants_response(
    block_id: Any,
    *,
    source_root: Any = None,
    options: Any = None,
) -> dict[str, Any]:
    """Convenience-Wrapper für dateibasierte Blockvarianten."""
    get_library_block_variants_response = load_service_symbol("get_library_block_variants_response")

    return get_library_block_variants_response(
        block_id,
        source_root=source_root,
        options=options,
    )


def tree_response(
    *,
    source_root: Any = None,
    options: Any = None,
) -> dict[str, Any]:
    """Convenience-Wrapper für dateibasierten Tree."""
    get_library_tree_response_from_block_service = load_service_symbol(
        "get_library_tree_response_from_block_service"
    )

    return get_library_tree_response_from_block_service(
        source_root=source_root,
        options=options,
    )


# ---------------------------------------------------------------------------
# Create convenience helpers
# ---------------------------------------------------------------------------

def create_options_response() -> dict[str, Any]:
    """Convenience-Wrapper für Create-Optionen."""
    get_create_options = load_service_symbol("get_create_options")
    result = get_create_options()
    return dataclass_to_dict_safe(result)


def build_create_draft(payload: Any) -> Any:
    """Convenience-Wrapper für Create-Draft."""
    build_draft = load_service_symbol("build_draft")
    return build_draft(payload)


def validate_create_draft(payload: Any) -> Any:
    """Convenience-Wrapper für Create-Validierung."""
    validate_draft = load_service_symbol("validate_draft")
    return validate_draft(payload)


def build_create_package_plan(payload: Any, *, include_documents: bool = True) -> Any:
    """Convenience-Wrapper für Create-Package-Plan."""
    build_package_plan = load_service_symbol("build_package_plan")
    return build_package_plan(payload, include_documents=include_documents)


def build_create_archive(payload: Any) -> Any:
    """Convenience-Wrapper für .vplib-Archiv-Erzeugung."""
    build_vplib_archive = load_service_symbol("build_vplib_archive")
    return build_vplib_archive(payload)


def save_create_package(payload: Any, *, overwrite: bool | None = None) -> Any:
    """Convenience-Wrapper für optionales Package-Speichern."""
    save_package = load_service_symbol("save_package")
    return save_package(payload, overwrite=overwrite)


# ---------------------------------------------------------------------------
# DB sync convenience helpers
# ---------------------------------------------------------------------------

def sync_library_to_database(
    *,
    source_root: Any = None,
    force_refresh: bool = True,
    triggered_by: Any = None,
    publish_valid_only: bool | None = None,
    mark_missing_deleted: bool | None = None,
    include_raw_documents: bool | None = None,
    scan_options: Mapping[str, Any] | None = None,
) -> Any:
    """Convenience-Wrapper für Filesystem → DB Sync."""
    sync_library_to_db = load_service_symbol("sync_library_to_db")

    return sync_library_to_db(
        source_root=source_root,
        force_refresh=force_refresh,
        triggered_by=triggered_by,
        publish_valid_only=publish_valid_only,
        mark_missing_deleted=mark_missing_deleted,
        include_raw_documents=include_raw_documents,
        scan_options=scan_options,
    )


def sync_library_to_database_response(
    *,
    source_root: Any = None,
    force_refresh: bool = True,
    triggered_by: Any = None,
    publish_valid_only: bool | None = None,
    mark_missing_deleted: bool | None = None,
    include_raw_documents: bool | None = None,
    scan_options: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    """JSON-kompatible Response für Filesystem → DB Sync."""
    result = sync_library_to_database(
        source_root=source_root,
        force_refresh=force_refresh,
        triggered_by=triggered_by,
        publish_valid_only=publish_valid_only,
        mark_missing_deleted=mark_missing_deleted,
        include_raw_documents=include_raw_documents,
        scan_options=scan_options,
    )

    if hasattr(result, "to_dict") and callable(result.to_dict):
        return result.to_dict()

    return dataclass_to_dict_safe(result)


def sync_scan_result_to_database(
    scan_result: Any,
    **kwargs: Any,
) -> Any:
    """Convenience-Wrapper für vorhandenes ScanResult → DB Sync."""
    sync_scan_result_to_db = load_service_symbol("sync_scan_result_to_db")
    return sync_scan_result_to_db(scan_result, **kwargs)


def sync_scan_result_to_database_response(
    scan_result: Any,
    **kwargs: Any,
) -> dict[str, Any]:
    """JSON-kompatible Response für vorhandenes ScanResult → DB Sync."""
    result = sync_scan_result_to_database(scan_result, **kwargs)

    if hasattr(result, "to_dict") and callable(result.to_dict):
        return result.to_dict()

    return dataclass_to_dict_safe(result)


# ---------------------------------------------------------------------------
# Published DB read convenience helpers
# ---------------------------------------------------------------------------

def list_published_blocks_db_response(**kwargs: Any) -> dict[str, Any]:
    """Convenience-Wrapper für DB-basierte Blocks-Liste."""
    fn = load_service_symbol("list_published_blocks_response")
    return fn(**kwargs)


def published_block_detail_db_response(block_id: Any, **kwargs: Any) -> dict[str, Any]:
    """Convenience-Wrapper für DB-basierte Blockdetails."""
    fn = load_service_symbol("get_published_block_detail_response")
    return fn(block_id, **kwargs)


def published_block_variants_db_response(block_id: Any, **kwargs: Any) -> dict[str, Any]:
    """Convenience-Wrapper für DB-basierte Blockvarianten."""
    fn = load_service_symbol("get_published_block_variants_response")
    return fn(block_id, **kwargs)


def published_tree_db_response(**kwargs: Any) -> dict[str, Any]:
    """Convenience-Wrapper für DB-basierten Tree."""
    fn = load_service_symbol("get_published_tree_response")
    return fn(**kwargs)


def published_inventory_db_response(**kwargs: Any) -> dict[str, Any]:
    """Convenience-Wrapper für DB-basiertes Creative-/Published-Inventory."""
    fn = load_service_symbol("get_inventory_response")
    return fn(**kwargs)


def publication_status_response() -> dict[str, Any]:
    """Convenience-Wrapper für DB-Publication-Status."""
    fn = load_service_symbol("get_publication_status")
    return fn()


# ---------------------------------------------------------------------------
# User inventory convenience helpers
# ---------------------------------------------------------------------------

def user_inventory_state_response(
    payload: Mapping[str, Any] | None = None,
    **kwargs: Any,
) -> dict[str, Any]:
    """Convenience-Wrapper für persistenten User-Inventar-State."""
    fn = load_service_symbol("user_inventory_get_inventory_response")
    return fn(payload_from_mapping_and_kwargs(payload, kwargs))


def user_inventory_select_slot_response(
    payload: Mapping[str, Any] | None = None,
    **kwargs: Any,
) -> dict[str, Any]:
    """Convenience-Wrapper für persistente User-Slot-Auswahl."""
    fn = load_service_symbol("user_inventory_select_slot_response")
    return fn(payload_from_mapping_and_kwargs(payload, kwargs))


def user_inventory_set_slot_response(
    slot_index: Any,
    payload: Mapping[str, Any] | None = None,
    **kwargs: Any,
) -> dict[str, Any]:
    """Convenience-Wrapper zum Setzen eines User-Inventar-Slots."""
    fn = load_service_symbol("user_inventory_set_slot_response")
    return fn(slot_index, payload_from_mapping_and_kwargs(payload, kwargs))


def user_inventory_clear_slot_response(
    slot_index: Any,
    payload: Mapping[str, Any] | None = None,
    **kwargs: Any,
) -> dict[str, Any]:
    """Convenience-Wrapper zum Leeren eines User-Inventar-Slots."""
    fn = load_service_symbol("user_inventory_clear_slot_response")
    return fn(slot_index, payload_from_mapping_and_kwargs(payload, kwargs))


def user_inventory_health_response() -> dict[str, Any]:
    """Convenience-Wrapper für User-Inventar-Service-Health."""
    fn = load_service_symbol("user_inventory_service_health")
    return fn()


def user_inventory_clear_runtime_cache_response() -> dict[str, Any]:
    """Convenience-Wrapper für User-Inventar-Service-Cache-Clear."""
    fn = load_service_symbol("user_inventory_clear_cache_response")
    return fn()


# ---------------------------------------------------------------------------
# Cache convenience helper
# ---------------------------------------------------------------------------

def clear_scan_cache() -> None:
    """Convenience-Wrapper zum Leeren des Scan-Caches."""
    clear_library_scan_cache = load_service_symbol("clear_library_scan_cache")
    clear_library_scan_cache()


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

__all__: Final[tuple[str, ...]] = (
    "SERVICES_PACKAGE_VERSION",
    "SERVICES_PACKAGE_NAME",
    "SERVICES_COMPONENT_NAME",
    "SERVICE_MODULES",
    "REQUIRED_SERVICE_MODULES",
    "OPTIONAL_SERVICE_MODULES",
    "DB_SERVICE_MODULES",
    "USER_INVENTORY_SERVICE_MODULES",
    "SYMBOL_TO_MODULE",
    "SYMBOL_ALIASES",

    "ServiceModuleStatus",
    "ServicesHealth",

    "utc_now_iso",
    "exception_to_dict",
    "json_safe",
    "dataclass_to_dict_safe",
    "safe_tuple",
    "payload_from_mapping_and_kwargs",
    "build_module_import_path",

    "clear_services_import_cache",
    "clear_services_runtime_caches",
    "clear_services_caches",
    "clear_services_cache",

    "safe_import_module",
    "get_service_module_status",
    "get_service_subhealth",
    "get_services_health",
    "is_services_healthy",
    "assert_services_ready",

    "load_service_symbol",
    "preload_service_symbols",

    "get_service_module",
    "get_library_scan_service_module",
    "get_library_block_service_module",
    "get_library_create_service_module",
    "get_library_db_sync_service_module",
    "get_library_published_service_module",
    "get_user_inventory_service_module",

    # Existing filesystem convenience helpers
    "scan_source",
    "scan_source_response",
    "list_blocks_response",
    "block_detail_response",
    "block_variants_response",
    "tree_response",

    # Create convenience helpers
    "create_options_response",
    "build_create_draft",
    "validate_create_draft",
    "build_create_package_plan",
    "build_create_archive",
    "save_create_package",

    # DB sync convenience helpers
    "sync_library_to_database",
    "sync_library_to_database_response",
    "sync_scan_result_to_database",
    "sync_scan_result_to_database_response",

    # Published DB read convenience helpers
    "list_published_blocks_db_response",
    "published_block_detail_db_response",
    "published_block_variants_db_response",
    "published_tree_db_response",
    "published_inventory_db_response",
    "publication_status_response",

    # User inventory convenience helpers
    "user_inventory_state_response",
    "user_inventory_select_slot_response",
    "user_inventory_set_slot_response",
    "user_inventory_clear_slot_response",
    "user_inventory_health_response",
    "user_inventory_clear_runtime_cache_response",

    # Cache
    "clear_scan_cache",

    # Reexported service symbols
    *tuple(SYMBOL_TO_MODULE.keys()),
    *tuple(SYMBOL_ALIASES.keys()),
)