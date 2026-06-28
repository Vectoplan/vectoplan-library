# services/vectoplan-library/src/library/services/__init__.py
from __future__ import annotations

"""
Service-Fassade der VECTOPLAN Creative-Library-Schicht.

Diese Datei ist bewusst import-sicher:

- keine Flask-Route
- keine SQLAlchemy-Query
- keine Migration
- kein db.create_all()
- keine Dateisystem-Schreiboperation beim Import
- keine eager Imports von Service-Modulen
- keine Symbolsuche über hasattr(), weil hasattr() PEP-562 __getattr__ triggert
- kein Fallback-Scan aus __getattr__
- keine Endlosrekursion bei teilweise importierten Service-Modulen

Wichtiger Fix:
Die vorherige Version konnte beim App-Import hängen, weil __getattr__ ein Symbol
auflösen wollte, dann alle Module scannte und dabei wieder __getattr__ auslöste.
Diese Version löst nur explizit registrierte Symbole auf und liest Symbole direkt
aus module.__dict__, ohne hasattr()/getattr()-Fallback-Scan.
"""

import importlib
import sys
import traceback
from dataclasses import asdict, dataclass, field, fields, is_dataclass
from datetime import datetime, timezone
from threading import RLock
from types import ModuleType
from typing import Any, Final, Iterable, Mapping


# ---------------------------------------------------------------------------
# Package metadata
# ---------------------------------------------------------------------------

SERVICES_PACKAGE_VERSION: Final[str] = "0.5.1"
SERVICES_PACKAGE_NAME: Final[str] = "library.services"
SERVICES_COMPONENT_NAME: Final[str] = "creative-library-services"


# ---------------------------------------------------------------------------
# Service module registry
# ---------------------------------------------------------------------------

SERVICE_MODULES: Final[tuple[str, ...]] = (
    "library_scan_service",
    "library_block_service",
    "library_create_service",
    "library_db_sync_service",
    "library_published_service",
    "creative_library_service",
    "creative_library_user_service",
    "creative_library_draft_service",
    "user_inventory_service",
    "library_definition_catalog_service",
    "library_definition_seed_service",
    "library_file_service",
    "library_taxonomy_user_service",
    "library_generator_context_service",
    "library_generator_diagnostics_service",
    "library_generator_workflow_service",
)

REQUIRED_SERVICE_MODULES: Final[tuple[str, ...]] = (
    "library_scan_service",
    "library_block_service",
)

OPTIONAL_SERVICE_MODULES: Final[tuple[str, ...]] = tuple(
    name for name in SERVICE_MODULES if name not in REQUIRED_SERVICE_MODULES
)

DB_SERVICE_MODULES: Final[tuple[str, ...]] = (
    "library_db_sync_service",
    "library_published_service",
    "creative_library_service",
    "creative_library_user_service",
    "creative_library_draft_service",
    "library_definition_catalog_service",
    "library_definition_seed_service",
    "library_file_service",
    "library_taxonomy_user_service",
    "user_inventory_service",
)

GENERATOR_SERVICE_MODULES: Final[tuple[str, ...]] = (
    "library_generator_context_service",
    "library_generator_diagnostics_service",
    "library_generator_workflow_service",
)

DEFINITION_SERVICE_MODULES: Final[tuple[str, ...]] = (
    "library_definition_catalog_service",
    "library_definition_seed_service",
)

FILE_SERVICE_MODULES: Final[tuple[str, ...]] = (
    "library_file_service",
)

TAXONOMY_SERVICE_MODULES: Final[tuple[str, ...]] = (
    "library_taxonomy_user_service",
)

DRAFT_SERVICE_MODULES: Final[tuple[str, ...]] = (
    "creative_library_draft_service",
)

USER_SERVICE_MODULES: Final[tuple[str, ...]] = (
    "creative_library_user_service",
    "user_inventory_service",
)

USER_INVENTORY_SERVICE_MODULES: Final[tuple[str, ...]] = (
    "user_inventory_service",
)


# ---------------------------------------------------------------------------
# Symbol registry
# ---------------------------------------------------------------------------

SYMBOL_TO_MODULE: dict[str, str] = {}


def _register(module_name: str, *symbols: str) -> None:
    for symbol in symbols:
        SYMBOL_TO_MODULE[str(symbol)] = str(module_name)


_register(
    "library_scan_service",
    "LIBRARY_SCAN_SERVICE_VERSION",
    "LIBRARY_SCAN_SERVICE_COMPONENT",
    "LibraryScanServiceOptions",
    "LibraryScanPipelineResult",
    "scan_library_source",
    "scan_library_source_no_cache",
    "get_library_scan_response",
    "get_library_blocks_response",
    "get_library_tree_response",
    "get_library_index",
    "get_library_scan_service_health",
    "assert_library_scan_service_ready",
    "clear_library_scan_cache",
    "get_taxonomy_service_safe",
    "get_taxonomy_payload_safe",
    "get_taxonomy_health_safe",
    "extract_taxonomy_version",
)

_register(
    "library_block_service",
    "LIBRARY_BLOCK_SERVICE_VERSION",
    "LIBRARY_BLOCK_SERVICE_COMPONENT",
    "LibraryBlockServiceOptions",
    "LibraryBlockServiceResult",
    "list_library_blocks",
    "get_library_block_detail",
    "get_library_block_variants",
    "get_library_tree",
    "scan_library_for_blocks",
    "list_library_blocks_response",
    "get_library_block_detail_response",
    "get_library_block_variants_response",
    "get_library_tree_response_from_block_service",
    "scan_library_for_blocks_response",
    "get_library_block_service_health",
    "assert_library_block_service_ready",
)

_register(
    "library_create_service",
    "LIBRARY_CREATE_SERVICE_VERSION",
    "LIBRARY_CREATE_SERVICE_COMPONENT",
    "CreateIssue",
    "CreateResult",
    "NormalizedCreateDraft",
    "CreateDraftNormalizationError",
    "get_service_health",
    "get_create_options",
    "get_create_context",
    "build_draft",
    "validate_draft",
    "build_package_plan",
    "build_vplib_archive",
    "save_package",
    "build_package_documents",
    "build_persistent_draft_payload",
    "build_publish_bundle_from_create_payload",
    "get_source_root",
    "health",
    "get_options",
    "create_draft",
    "package_plan",
)

_register(
    "library_db_sync_service",
    "LIBRARY_DB_SYNC_SERVICE_NAME",
    "LIBRARY_DB_SYNC_COMPONENT_NAME",
    "LIBRARY_DB_SYNC_API_VERSION",
    "LibraryDbSyncServiceError",
    "LibraryDbSyncDisabledError",
    "LibraryDbSyncImportError",
    "LibraryDbSyncValidationError",
    "LibraryDbSyncCandidateError",
    "LibraryDbSyncServiceConfig",
    "LibraryDbSyncService",
    "create_library_db_sync_service",
    "get_library_db_sync_service",
    "sync_library_to_db",
    "sync_scan_result_to_db",
    "get_library_db_sync_service_health",
    "assert_library_db_sync_service_ready",
    "clear_library_db_sync_service_cache",
    "clear_library_db_sync_service_caches",
    "clear_db_sync_cache",
    "clear_db_sync_caches",
    "build_sync_response",
)

_register(
    "library_published_service",
    "LIBRARY_PUBLISHED_SERVICE_NAME",
    "LIBRARY_PUBLISHED_COMPONENT_NAME",
    "LIBRARY_PUBLISHED_API_VERSION",
    "LibraryPublishedServiceError",
    "LibraryPublishedServiceDisabledError",
    "LibraryPublishedServiceImportError",
    "LibraryPublishedNotFound",
    "LibraryPublishedValidationError",
    "LibraryPublishedServiceConfig",
    "LibraryPublishedService",
    "create_library_published_service",
    "get_library_published_service",
    "list_published_blocks",
    "list_published_blocks_response",
    "get_published_block_detail",
    "get_published_block_detail_response",
    "get_published_block_variants",
    "get_published_block_variants_response",
    "get_published_tree",
    "get_published_tree_response",
    "get_inventory_state",
    "get_inventory_response",
    "get_publication_status",
    "get_library_published_service_health",
    "assert_library_published_service_ready",
    "clear_library_published_service_cache",
    "clear_library_published_service_caches",
    "clear_published_service_cache",
    "clear_published_service_caches",
)

_register(
    "creative_library_service",
    "CREATIVE_LIBRARY_SERVICE_VERSION",
    "CreativeLibraryService",
    "CreativeLibraryServiceError",
    "CreativeLibraryServiceImportError",
    "CreativeLibraryServiceValidationError",
    "CreativeLibraryServiceNotFoundError",
    "CreativeLibraryServiceConflictError",
    "CreativeLibraryServiceResult",
    "LibraryQuery",
    "PublishOptions",
    "create_creative_library_service",
    "get_creative_library_service",
    "get_creative_library_service_health",
    "clear_creative_library_service_caches",
)

_register(
    "creative_library_user_service",
    "CREATIVE_LIBRARY_USER_SERVICE_VERSION",
    "CreativeLibraryUserService",
    "CreativeLibraryUserServiceError",
    "CreativeLibraryUserServiceImportError",
    "CreativeLibraryUserServiceValidationError",
    "CreativeLibraryUserServiceNotFoundError",
    "CreativeLibraryUserServiceConflictError",
    "ResolvedCreativeLibraryQuery",
    "CreativeLibraryCollectionInput",
    "CreativeLibraryItemInput",
    "CreativeLibraryUserServiceResult",
    "create_creative_library_user_service",
    "get_creative_library_user_service",
    "get_creative_library_user_service_health",
    "clear_creative_library_user_service_caches",
)

_register(
    "creative_library_draft_service",
    "CREATIVE_LIBRARY_DRAFT_SERVICE_VERSION",
    "CreativeLibraryDraftService",
    "CreativeLibraryDraftServiceError",
    "CreativeLibraryDraftServiceImportError",
    "CreativeLibraryDraftServiceValidationError",
    "CreativeLibraryDraftServiceNotFoundError",
    "CreativeLibraryDraftServiceConflictError",
    "CreativeLibraryDraftPublishNotAvailableError",
    "DraftInput",
    "DraftValidationIssueInput",
    "DraftServiceResult",
    "create_creative_library_draft_service",
    "get_creative_library_draft_service",
    "get_creative_library_draft_service_health",
    "clear_creative_library_draft_service_caches",
)

_register(
    "library_definition_catalog_service",
    "LIBRARY_DEFINITION_CATALOG_SERVICE_VERSION",
    "LibraryDefinitionCatalogService",
    "LibraryDefinitionCatalogServiceError",
    "LibraryDefinitionCatalogImportError",
    "LibraryDefinitionCatalogNotFoundError",
    "LibraryDefinitionCreateContextError",
    "CreateContextQuery",
    "ServiceHealth",
    "create_library_definition_catalog_service",
    "get_library_definition_catalog_service",
    "get_library_definition_catalog_service_health",
    "clear_library_definition_catalog_service_caches",
)

_register(
    "library_definition_seed_service",
    "LIBRARY_DEFINITION_SEED_SERVICE_VERSION",
    "LibraryDefinitionSeedService",
    "LibraryDefinitionSeedServiceError",
    "LibraryDefinitionSeedImportError",
    "LibraryDefinitionSeedFileNotFoundError",
    "LibraryDefinitionSeedPayloadError",
    "DefinitionSeedOptions",
    "DefinitionSeedDatasetResult",
    "DefinitionSeedResult",
    "create_library_definition_seed_service",
    "get_library_definition_seed_service",
    "get_library_definition_seed_service_health",
    "clear_library_definition_seed_service_caches",
)

_register(
    "library_file_service",
    "LIBRARY_FILE_SERVICE_VERSION",
    "LibraryFileService",
    "LibraryFileServiceError",
    "LibraryFileServiceImportError",
    "LibraryFileValidationError",
    "LibraryFileStorageError",
    "LibraryFileUnsupportedStorageError",
    "UploadValidationResult",
    "StoredUpload",
    "UploadRequest",
    "FileLinkInput",
    "LibraryFileServiceResult",
    "create_library_file_service",
    "get_library_file_service",
    "get_library_file_service_health",
    "clear_library_file_service_caches",
)

_register(
    "library_taxonomy_user_service",
    "LIBRARY_TAXONOMY_USER_SERVICE_VERSION",
    "LibraryTaxonomyUserService",
    "LibraryTaxonomyUserServiceError",
    "LibraryTaxonomyUserServiceImportError",
    "LibraryTaxonomyUserServiceValidationError",
    "LibraryTaxonomyUserServiceNotFoundError",
    "LibraryTaxonomyUserServiceConflictError",
    "TaxonomyContextQuery",
    "TaxonomyNodeInput",
    "TaxonomyActionInput",
    "TaxonomyOverrideInput",
    "TaxonomyServiceResult",
    "create_library_taxonomy_user_service",
    "get_library_taxonomy_user_service",
    "get_library_taxonomy_user_service_health",
    "clear_library_taxonomy_user_service_caches",
)

_register(
    "user_inventory_service",
    "USER_INVENTORY_SERVICE_VERSION",
    "USER_INVENTORY_COMPONENT",
    "DEFAULT_USER_ID",
    "DEFAULT_INVENTORY_KEY",
    "DEFAULT_SLOT_COUNT",
    "MIN_SLOT_INDEX",
    "MAX_SLOT_INDEX",
    "UserInventoryServiceError",
    "UserInventoryServiceValidationError",
    "get_inventory_response",
    "select_slot_response",
    "set_slot_response",
    "clear_slot_response",
    "clear_cache_response",
    "get_service_health_response",
    "inventory_payload_from_snapshot",
    "empty_slot_payload",
    "extract_item_payload",
    "normalize_payload",
    "normalize_inventory_key",
    "normalize_user_id",
    "normalize_slot_index",
    "slot_key_for_index",
    "success_response",
    "failure_response",
)

_register(
    "library_generator_context_service",
    "LIBRARY_GENERATOR_CONTEXT_SERVICE_COMPONENT",
    "LIBRARY_GENERATOR_CONTEXT_SERVICE_SCHEMA_VERSION",
    "DEFAULT_SERVICE_CACHE_TTL_SECONDS",
    "DEFAULT_SERVICE_CACHE_MAX_ENTRIES",
    "LibraryGeneratorContextRequest",
    "DependencyResolution",
    "ServiceCallResult",
    "LibraryGeneratorContextService",
    "get_library_generator_context_service",
    "get_generator_context",
    "get_generator_context_payload",
    "get_generator_frontend_context",
    "get_generator_create_options",
    "get_generator_diagnostics",
    "get_library_generator_context_service_health",
    "assert_library_generator_context_service_ready",
    "clear_library_generator_context_service_caches",
)

_register(
    "library_generator_diagnostics_service",
    "LIBRARY_GENERATOR_DIAGNOSTICS_SERVICE_COMPONENT",
    "LIBRARY_GENERATOR_DIAGNOSTICS_SERVICE_SCHEMA_VERSION",
    "DEFAULT_DIAGNOSTICS_CACHE_TTL_SECONDS",
    "DEFAULT_DIAGNOSTICS_CACHE_MAX_ENTRIES",
    "REQUIRED_ROUTE_KEYS",
    "REQUIRED_PAYLOAD_CONTRACT_SECTIONS",
    "DEFAULT_CHECK_ORDER",
    "OPTIONAL_CHECK_ORDER",
    "DiagnosticCheckStatus",
    "LibraryGeneratorDiagnosticsRequest",
    "DiagnosticCheckResult",
    "GeneratorDiagnosticsReport",
    "DiagnosticCheckSpec",
    "LibraryGeneratorDiagnosticsService",
    "get_library_generator_diagnostics_service",
    "run_generator_diagnostics",
    "get_generator_diagnostics_payload",
    "get_library_generator_diagnostics_service_health",
    "assert_library_generator_diagnostics_service_ready",
    "clear_library_generator_diagnostics_service_caches",
)

_register(
    "library_generator_workflow_service",
    "LIBRARY_GENERATOR_WORKFLOW_SERVICE_COMPONENT",
    "LIBRARY_GENERATOR_WORKFLOW_SERVICE_SCHEMA_VERSION",
    "DEFAULT_WORKFLOW_CACHE_TTL_SECONDS",
    "DEFAULT_WORKFLOW_CACHE_MAX_ENTRIES",
    "WORKFLOW_ACTION_CONTEXT",
    "WORKFLOW_ACTION_OPTIONS",
    "WORKFLOW_ACTION_DRAFT",
    "WORKFLOW_ACTION_VALIDATE",
    "WORKFLOW_ACTION_PACKAGE_PLAN",
    "WORKFLOW_ACTION_DOWNLOAD",
    "WORKFLOW_ACTION_SAVE",
    "WORKFLOW_ACTION_PERSIST_DRAFT",
    "WORKFLOW_ACTION_PUBLISH_PREPARE",
    "WORKFLOW_ACTION_PUBLISH",
    "WORKFLOW_ACTION_SYNC",
    "SUPPORTED_WORKFLOW_ACTIONS",
    "WRITE_ACTIONS",
    "GeneratorWorkflowStatus",
    "GeneratorWorkflowMode",
    "LibraryGeneratorWorkflowRequest",
    "GeneratorWorkflowStep",
    "GeneratorWorkflowResult",
    "normalize_workflow_action",
    "normalize_workflow_mode",
    "LibraryGeneratorWorkflowService",
    "get_library_generator_workflow_service",
    "run_generator_workflow",
    "run_generator_workflow_payload",
    "create_generator_draft_payload",
    "validate_generator_payload",
    "build_generator_package_plan",
    "prepare_generator_download",
    "save_generator_source_package",
    "create_generator_persistent_draft",
    "prepare_generator_publish",
    "get_library_generator_workflow_service_health",
    "assert_library_generator_workflow_service_ready",
    "clear_library_generator_workflow_service_caches",
)


SYMBOL_ALIASES: dict[str, tuple[str, str]] = {
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

    "generator_context_service": ("library_generator_context_service", "get_library_generator_context_service"),
    "generator_context_service_health": ("library_generator_context_service", "get_library_generator_context_service_health"),
    "generator_context_payload": ("library_generator_context_service", "get_generator_context_payload"),
    "generator_frontend_context": ("library_generator_context_service", "get_generator_frontend_context"),
    "generator_create_options": ("library_generator_context_service", "get_generator_create_options"),

    "generator_diagnostics_service": ("library_generator_diagnostics_service", "get_library_generator_diagnostics_service"),
    "generator_diagnostics_service_health": ("library_generator_diagnostics_service", "get_library_generator_diagnostics_service_health"),
    "generator_diagnostics_payload": ("library_generator_diagnostics_service", "get_generator_diagnostics_payload"),

    "generator_workflow_service": ("library_generator_workflow_service", "get_library_generator_workflow_service"),
    "generator_workflow_service_health": ("library_generator_workflow_service", "get_library_generator_workflow_service_health"),
    "generator_workflow_payload": ("library_generator_workflow_service", "run_generator_workflow_payload"),
    "generator_draft_payload": ("library_generator_workflow_service", "create_generator_draft_payload"),
    "generator_validate_payload": ("library_generator_workflow_service", "validate_generator_payload"),
    "generator_package_plan": ("library_generator_workflow_service", "build_generator_package_plan"),
    "generator_download": ("library_generator_workflow_service", "prepare_generator_download"),
    "generator_source_save": ("library_generator_workflow_service", "save_generator_source_package"),
    "generator_persistent_draft": ("library_generator_workflow_service", "create_generator_persistent_draft"),
    "generator_publish_prepare": ("library_generator_workflow_service", "prepare_generator_publish"),
}


# ---------------------------------------------------------------------------
# Runtime import state
# ---------------------------------------------------------------------------

_IMPORT_CACHE_LOCK = RLock()
_MODULE_CACHE: dict[str, ModuleType] = {}
_IMPORT_ERRORS: dict[str, dict[str, Any] | None] = {}
_IMPORT_IN_PROGRESS: set[str] = set()
_SYMBOL_RESOLUTION_STACK: set[str] = set()

_MISSING = object()


# ---------------------------------------------------------------------------
# Dataclasses
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class ServiceModuleStatus:
    name: str
    import_path: str
    loaded: bool
    status: str
    required: bool = False
    optional: bool = True
    error: dict[str, Any] | None = None
    exports_count: int = 0
    loaded_at: str | None = None
    partial: bool = False

    @property
    def ok(self) -> bool:
        return self.loaded or (self.optional and not self.required)

    def to_dict(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "import_path": self.import_path,
            "loaded": self.loaded,
            "ok": self.ok,
            "status": self.status,
            "required": self.required,
            "optional": self.optional,
            "partial": self.partial,
            "error": json_safe(self.error),
            "exports_count": self.exports_count,
            "loaded_at": self.loaded_at,
        }


@dataclass(frozen=True)
class ServicesHealth:
    ok: bool
    healthy: bool
    status: str
    component: str = SERVICES_COMPONENT_NAME
    package: str = SERVICES_PACKAGE_NAME
    version: str = SERVICES_PACKAGE_VERSION
    checked_at: str = field(default_factory=lambda: utc_now_iso())
    modules: tuple[ServiceModuleStatus, ...] = ()
    required_ok: bool = True
    optional_ok: bool = True
    route_ready: bool = True
    generator_ready: bool = False
    errors: tuple[dict[str, Any], ...] = ()
    warnings: tuple[dict[str, Any], ...] = ()
    metadata: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "ok": self.ok,
            "healthy": self.healthy,
            "status": self.status,
            "component": self.component,
            "package": self.package,
            "version": self.version,
            "checked_at": self.checked_at,
            "required_ok": self.required_ok,
            "optional_ok": self.optional_ok,
            "route_ready": self.route_ready,
            "generator_ready": self.generator_ready,
            "modules": [item.to_dict() for item in self.modules],
            "errors": json_safe(self.errors),
            "warnings": json_safe(self.warnings),
            "metadata": json_safe(self.metadata),
        }


# ---------------------------------------------------------------------------
# Generic helpers
# ---------------------------------------------------------------------------

def utc_now_iso() -> str:
    try:
        return datetime.now(timezone.utc).replace(microsecond=0).isoformat()
    except Exception:
        return datetime.utcnow().replace(tzinfo=timezone.utc).isoformat()


def exception_to_dict(
    exc: BaseException | None,
    *,
    include_traceback: bool = False,
) -> dict[str, Any] | None:
    if exc is None:
        return None

    try:
        payload: dict[str, Any] = {
            "type": exc.__class__.__name__,
            "message": str(exc),
        }

        if include_traceback:
            payload["traceback"] = traceback.format_exception(
                type(exc),
                exc,
                exc.__traceback__,
            )

        return payload
    except Exception as serialization_exc:
        return {
            "type": "ExceptionSerializationError",
            "message": str(serialization_exc),
            "original_type": str(type(exc)),
        }


def dataclass_to_dict_safe(value: Any) -> dict[str, Any]:
    if not is_dataclass(value) or isinstance(value, type):
        return {}

    result: dict[str, Any] = {}

    try:
        for field_info in fields(value):
            try:
                result[field_info.name] = json_safe(getattr(value, field_info.name))
            except Exception as exc:
                result[field_info.name] = {
                    "serialization_error": exception_to_dict(exc),
                }
        return result
    except Exception:
        try:
            return json_safe(asdict(value))
        except Exception:
            return {}


def json_safe(value: Any) -> Any:
    try:
        if value is None:
            return None

        if isinstance(value, (str, int, float, bool)):
            return value

        if isinstance(value, bytes):
            return {
                "type": "bytes",
                "length": len(value),
            }

        if is_dataclass(value) and not isinstance(value, type):
            return dataclass_to_dict_safe(value)

        if isinstance(value, Mapping):
            return {str(key): json_safe(item) for key, item in value.items()}

        if isinstance(value, (list, tuple, set, frozenset)):
            return [json_safe(item) for item in value]

        to_dict = getattr(value, "to_dict", None)
        if callable(to_dict):
            try:
                return json_safe(to_dict())
            except TypeError:
                return json_safe(to_dict(flat=True))
            except Exception:
                return str(value)

        isoformat = getattr(value, "isoformat", None)
        if callable(isoformat):
            try:
                return isoformat()
            except Exception:
                return str(value)

        return str(value)
    except Exception as exc:
        return {
            "serialization_error": exception_to_dict(exc),
            "fallback_type": str(type(value)),
        }


def safe_tuple(value: Any) -> tuple[str, ...]:
    if value is None:
        return ()

    if isinstance(value, str):
        text = value.strip()
        return (text,) if text else ()

    try:
        return tuple(str(item).strip() for item in value if str(item).strip())
    except Exception:
        text = str(value).strip()
        return (text,) if text else ()


def payload_from_mapping_and_kwargs(
    payload: Mapping[str, Any] | None = None,
    kwargs: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    data = dict(payload or {})
    data.update({key: value for key, value in dict(kwargs or {}).items() if value is not None})
    return data


def _service_package_base() -> str:
    if __name__.endswith(".services"):
        return __name__
    return "library.services"


def build_module_import_path(module_name: str) -> str:
    name = str(module_name or "").strip()

    if "." in name:
        return name

    return f"{_service_package_base()}.{name}"


def _dedupe(values: Iterable[str]) -> tuple[str, ...]:
    seen: set[str] = set()
    output: list[str] = []

    for value in values:
        text = str(value or "").strip()
        if not text or text in seen:
            continue
        seen.add(text)
        output.append(text)

    return tuple(output)


def _absolute_import_candidates(module_name: str) -> tuple[str, ...]:
    name = str(module_name or "").strip()

    if not name:
        return ()

    if "." in name:
        return (name,)

    base = _service_package_base()

    return _dedupe(
        (
            f"{base}.{name}",
            f"library.services.{name}",
            f"src.library.services.{name}",
            f"vectoplan_library.library.services.{name}",
            f"vectoplan_library.src.library.services.{name}",
        )
    )


def _service_exports_count(module: ModuleType | None) -> int:
    if module is None:
        return 0

    try:
        explicit = module.__dict__.get("__all__")
        if explicit:
            return len(tuple(explicit))
    except Exception:
        pass

    try:
        return len([name for name in module.__dict__ if not str(name).startswith("_")])
    except Exception:
        return 0


def _read_module_symbol(module: ModuleType | None, symbol_name: str) -> Any:
    """Liest ein Symbol ohne hasattr()/getattr(), damit __getattr__ nicht feuert."""
    if module is None:
        return _MISSING

    try:
        namespace = module.__dict__
    except Exception:
        return _MISSING

    if symbol_name in namespace:
        return namespace[symbol_name]

    return _MISSING


def _module_has_symbol(module: ModuleType, symbol_name: str) -> bool:
    """Import-sichere Symbolprüfung ohne hasattr()."""
    return _read_module_symbol(module, symbol_name) is not _MISSING


def _module_from_sys_modules(candidates: Iterable[str]) -> ModuleType | None:
    for import_path in candidates:
        module = sys.modules.get(import_path)
        if isinstance(module, ModuleType):
            return module
    return None


# ---------------------------------------------------------------------------
# Import handling
# ---------------------------------------------------------------------------

def clear_services_import_cache() -> dict[str, Any]:
    with _IMPORT_CACHE_LOCK:
        cached_modules = sorted(_MODULE_CACHE.keys())
        cached_errors = sorted(_IMPORT_ERRORS.keys())
        in_progress = sorted(_IMPORT_IN_PROGRESS)
        resolving_symbols = sorted(_SYMBOL_RESOLUTION_STACK)

        _MODULE_CACHE.clear()
        _IMPORT_ERRORS.clear()
        _IMPORT_IN_PROGRESS.clear()
        _SYMBOL_RESOLUTION_STACK.clear()

    return {
        "ok": True,
        "status": "cache_cleared",
        "component": SERVICES_COMPONENT_NAME,
        "cleared_at": utc_now_iso(),
        "cached_modules": cached_modules,
        "cached_errors": cached_errors,
        "in_progress": in_progress,
        "resolving_symbols": resolving_symbols,
    }


def safe_import_module(
    module_name: str,
    *,
    required: bool = False,
    force_reload: bool = False,
) -> ModuleType | None:
    normalized_name = str(module_name or "").strip()

    if not normalized_name:
        if required:
            raise ImportError("Empty service module name.")
        return None

    candidates = _absolute_import_candidates(normalized_name)

    with _IMPORT_CACHE_LOCK:
        if not force_reload and normalized_name in _MODULE_CACHE:
            return _MODULE_CACHE[normalized_name]

        if normalized_name in _IMPORT_IN_PROGRESS:
            partial_module = _module_from_sys_modules(candidates)
            if partial_module is not None:
                return partial_module

            if required:
                raise ImportError(f"Recursive import prevented for service module {normalized_name!r}.")

            return None

        _IMPORT_IN_PROGRESS.add(normalized_name)

    errors: list[dict[str, Any]] = []

    try:
        for import_path in candidates:
            try:
                if force_reload:
                    existing = sys.modules.get(import_path)
                    module = importlib.reload(existing) if isinstance(existing, ModuleType) else importlib.import_module(import_path)
                else:
                    module = importlib.import_module(import_path)

                with _IMPORT_CACHE_LOCK:
                    _MODULE_CACHE[normalized_name] = module
                    _IMPORT_ERRORS[normalized_name] = None

                return module

            except Exception as exc:
                errors.append(
                    {
                        "import_path": import_path,
                        "error": exception_to_dict(exc),
                    }
                )

        error_payload = {
            "module_name": normalized_name,
            "errors": errors,
            "checked_at": utc_now_iso(),
        }

        with _IMPORT_CACHE_LOCK:
            _MODULE_CACHE.pop(normalized_name, None)
            _IMPORT_ERRORS[normalized_name] = error_payload

        if required:
            raise ImportError(f"Could not import service module {normalized_name!r}: {error_payload}")

        return None

    finally:
        with _IMPORT_CACHE_LOCK:
            _IMPORT_IN_PROGRESS.discard(normalized_name)


def get_service_module(module_name: str, *, required: bool = False) -> ModuleType | None:
    return safe_import_module(module_name, required=required)


def get_service_module_status(
    module_name: str,
    *,
    required: bool | None = None,
    force_reload: bool = False,
) -> ServiceModuleStatus:
    name = str(module_name or "").strip()
    required_flag = name in REQUIRED_SERVICE_MODULES if required is None else bool(required)

    module = safe_import_module(
        name,
        required=False,
        force_reload=force_reload,
    )

    partial = False
    if module is not None:
        partial = name in _IMPORT_IN_PROGRESS
        return ServiceModuleStatus(
            name=name,
            import_path=getattr(module, "__name__", build_module_import_path(name)),
            loaded=True,
            status="partial" if partial else "loaded",
            required=required_flag,
            optional=not required_flag,
            error=None,
            exports_count=_service_exports_count(module),
            loaded_at=utc_now_iso(),
            partial=partial,
        )

    error = _IMPORT_ERRORS.get(name)

    return ServiceModuleStatus(
        name=name,
        import_path=build_module_import_path(name),
        loaded=False,
        status="error" if required_flag else "optional_unavailable",
        required=required_flag,
        optional=not required_flag,
        error=json_safe(error),
        exports_count=0,
        loaded_at=None,
        partial=False,
    )


def get_library_scan_service_module() -> ModuleType | None:
    return get_service_module("library_scan_service", required=True)


def get_library_block_service_module() -> ModuleType | None:
    return get_service_module("library_block_service", required=True)


def get_library_create_service_module() -> ModuleType | None:
    return get_service_module("library_create_service")


def get_library_db_sync_service_module() -> ModuleType | None:
    return get_service_module("library_db_sync_service")


def get_library_published_service_module() -> ModuleType | None:
    return get_service_module("library_published_service")


def get_creative_library_service_module() -> ModuleType | None:
    return get_service_module("creative_library_service")


def get_creative_library_user_service_module() -> ModuleType | None:
    return get_service_module("creative_library_user_service")


def get_creative_library_draft_service_module() -> ModuleType | None:
    return get_service_module("creative_library_draft_service")


def get_library_definition_catalog_service_module() -> ModuleType | None:
    return get_service_module("library_definition_catalog_service")


def get_library_definition_seed_service_module() -> ModuleType | None:
    return get_service_module("library_definition_seed_service")


def get_library_file_service_module() -> ModuleType | None:
    return get_service_module("library_file_service")


def get_library_taxonomy_user_service_module() -> ModuleType | None:
    return get_service_module("library_taxonomy_user_service")


def get_user_inventory_service_module() -> ModuleType | None:
    return get_service_module("user_inventory_service")


def get_library_generator_context_service_module() -> ModuleType | None:
    return get_service_module("library_generator_context_service")


def get_library_generator_diagnostics_service_module() -> ModuleType | None:
    return get_service_module("library_generator_diagnostics_service")


def get_library_generator_workflow_service_module() -> ModuleType | None:
    return get_service_module("library_generator_workflow_service")


# ---------------------------------------------------------------------------
# Symbol loading
# ---------------------------------------------------------------------------

def find_service_symbol(symbol_name: str) -> tuple[str, Any] | None:
    """
    Explizite, sichere Symbolsuche.

    Diese Funktion ist absichtlich NICHT der Fallback von __getattr__.
    Sie scannt nur module.__dict__ und löst kein Modul-__getattr__ aus.
    """

    name = str(symbol_name or "").strip()
    if not name:
        return None

    for module_name in SERVICE_MODULES:
        module = safe_import_module(module_name, required=False)
        symbol = _read_module_symbol(module, name)
        if symbol is not _MISSING:
            return module_name, symbol

    return None


def load_service_symbol(
    symbol_name: str,
    *,
    allow_scan: bool = False,
) -> Any:
    name = str(symbol_name or "").strip()

    if not name:
        raise AttributeError("Empty service symbol name.")

    with _IMPORT_CACHE_LOCK:
        if name in _SYMBOL_RESOLUTION_STACK:
            raise AttributeError(f"Recursive service symbol resolution prevented for {name!r}.")
        _SYMBOL_RESOLUTION_STACK.add(name)

    try:
        alias = SYMBOL_ALIASES.get(name)
        if alias is not None:
            module_name, real_symbol_name = alias
            module = safe_import_module(module_name, required=True)
            symbol = _read_module_symbol(module, real_symbol_name)
            if symbol is _MISSING:
                raise AttributeError(
                    f"Service alias {name!r} could not resolve {module_name}.{real_symbol_name}."
                )
            return symbol

        module_name = SYMBOL_TO_MODULE.get(name)
        if module_name:
            module = safe_import_module(module_name, required=True)
            symbol = _read_module_symbol(module, name)
            if symbol is _MISSING:
                raise AttributeError(
                    f"Service symbol {name!r} is not currently available in module {module_name!r}."
                )
            return symbol

        if allow_scan:
            found = find_service_symbol(name)
            if found is not None:
                _found_module_name, found_symbol = found
                return found_symbol

        raise AttributeError(f"Service symbol {name!r} is not registered.")

    finally:
        with _IMPORT_CACHE_LOCK:
            _SYMBOL_RESOLUTION_STACK.discard(name)


def preload_service_symbols(
    symbols: Iterable[str] | None = None,
    *,
    strict: bool = False,
) -> dict[str, Any]:
    requested = tuple(symbols or ())
    loaded: dict[str, str] = {}
    errors: dict[str, Any] = {}

    for symbol in requested:
        symbol_text = str(symbol)
        try:
            resolved = load_service_symbol(symbol_text, allow_scan=False)
            loaded[symbol_text] = getattr(resolved, "__name__", type(resolved).__name__)
        except Exception as exc:
            errors[symbol_text] = exception_to_dict(exc)
            if strict:
                raise

    return {
        "ok": not errors,
        "loaded": loaded,
        "errors": errors,
    }


def __getattr__(name: str) -> Any:
    """
    PEP-562 Lazy-Reexport.

    Wichtig:
    - nur registrierte Symbole
    - kein Fallback-Scan
    - kein hasattr()
    - keine rekursive Modulauflösung
    """

    try:
        return load_service_symbol(name, allow_scan=False)
    except AttributeError as exc:
        raise AttributeError(f"module {__name__!r} has no attribute {name!r}") from exc


# ---------------------------------------------------------------------------
# Health
# ---------------------------------------------------------------------------

def get_service_subhealth(module_name: str) -> dict[str, Any]:
    module = safe_import_module(module_name, required=False)
    if module is None:
        return {
            "ok": False,
            "healthy": False,
            "status": "unavailable",
            "module": module_name,
            "error": json_safe(_IMPORT_ERRORS.get(module_name)),
        }

    candidates = (
        "get_health",
        "health",
        "get_service_health",
        "get_service_health_response",
        f"get_{module_name}_health",
        f"get_{module_name}_service_health",
        f"get_{module_name}_service_health_response",
    )

    for candidate in candidates:
        method = _read_module_symbol(module, candidate)
        if method is _MISSING or not callable(method):
            continue

        try:
            result = method()
            if hasattr(result, "to_dict") and callable(result.to_dict):
                result = result.to_dict()

            if isinstance(result, Mapping):
                payload = dict(result)
            else:
                payload = {"value": json_safe(result)}

            payload.setdefault("ok", bool(payload.get("healthy", payload.get("ok", True))))
            payload.setdefault("healthy", bool(payload.get("ok", payload.get("healthy", True))))
            payload.setdefault("module", module_name)
            payload.setdefault("method", candidate)
            return json_safe(payload)

        except Exception as exc:
            return {
                "ok": False,
                "healthy": False,
                "status": "error",
                "module": module_name,
                "method": candidate,
                "error": exception_to_dict(exc),
            }

    return {
        "ok": True,
        "healthy": True,
        "status": "loaded_no_health_method",
        "module": module_name,
        "exports_count": _service_exports_count(module),
    }


def get_services_health(
    *,
    include_optional: bool = True,
    include_subhealth: bool = False,
    force_reload: bool = False,
) -> ServicesHealth:
    module_names = SERVICE_MODULES if include_optional else REQUIRED_SERVICE_MODULES
    statuses: list[ServiceModuleStatus] = []
    errors: list[dict[str, Any]] = []
    warnings: list[dict[str, Any]] = []
    subhealth: dict[str, Any] = {}

    for module_name in module_names:
        status = get_service_module_status(
            module_name,
            force_reload=force_reload,
        )
        statuses.append(status)

        if status.required and not status.loaded:
            errors.append(
                {
                    "code": "required_service_unavailable",
                    "module": module_name,
                    "error": status.error,
                }
            )
        elif not status.loaded:
            warnings.append(
                {
                    "code": "optional_service_unavailable",
                    "module": module_name,
                    "error": status.error,
                }
            )

        if include_subhealth and status.loaded and not status.partial:
            subhealth[module_name] = get_service_subhealth(module_name)

    required_ok = all(item.loaded for item in statuses if item.required)
    optional_ok = all(item.loaded for item in statuses if not item.required)

    generator_statuses = [item for item in statuses if item.name in GENERATOR_SERVICE_MODULES]
    generator_ready = bool(generator_statuses) and all(item.loaded for item in generator_statuses)

    ok = required_ok
    status_text = "healthy" if ok and optional_ok else "partial" if ok else "error"

    return ServicesHealth(
        ok=ok,
        healthy=ok,
        status=status_text,
        modules=tuple(statuses),
        required_ok=required_ok,
        optional_ok=optional_ok,
        route_ready=required_ok,
        generator_ready=generator_ready,
        errors=tuple(errors),
        warnings=tuple(warnings),
        metadata={
            "service_modules": list(SERVICE_MODULES),
            "required_service_modules": list(REQUIRED_SERVICE_MODULES),
            "optional_service_modules": list(OPTIONAL_SERVICE_MODULES),
            "db_service_modules": list(DB_SERVICE_MODULES),
            "generator_service_modules": list(GENERATOR_SERVICE_MODULES),
            "subhealth": subhealth,
            "import_in_progress": sorted(_IMPORT_IN_PROGRESS),
            "symbol_resolution_stack": sorted(_SYMBOL_RESOLUTION_STACK),
        },
    )


def is_services_healthy() -> bool:
    return get_services_health(include_optional=False, include_subhealth=False).ok


def assert_services_ready(
    *,
    include_optional: bool = False,
    include_generator: bool = False,
) -> bool:
    health = get_services_health(include_optional=include_optional, include_subhealth=False)

    if not health.required_ok:
        raise RuntimeError(f"Required services are not ready: {health.to_dict()}")

    if include_optional and not health.optional_ok:
        raise RuntimeError(f"Optional services are not ready: {health.to_dict()}")

    if include_generator:
        missing = [
            module_name
            for module_name in GENERATOR_SERVICE_MODULES
            if not get_service_module_status(module_name).loaded
        ]
        if missing:
            raise RuntimeError(f"Generator services are not ready: {missing}")

    return True


# ---------------------------------------------------------------------------
# Runtime cache clearing
# ---------------------------------------------------------------------------

def clear_services_runtime_caches() -> dict[str, Any]:
    clear_candidates = (
        "clear_cache",
        "clear_caches",
        "clear_service_cache",
        "clear_service_caches",
        "clear_runtime_cache",
        "clear_runtime_caches",
        "clear_library_scan_cache",
        "clear_library_db_sync_service_cache",
        "clear_library_db_sync_service_caches",
        "clear_library_published_service_cache",
        "clear_library_published_service_caches",
        "clear_creative_library_service_caches",
        "clear_creative_library_user_service_caches",
        "clear_creative_library_draft_service_caches",
        "clear_library_definition_catalog_service_caches",
        "clear_library_definition_seed_service_caches",
        "clear_library_file_service_caches",
        "clear_library_taxonomy_user_service_caches",
        "clear_library_generator_context_service_caches",
        "clear_library_generator_diagnostics_service_caches",
        "clear_library_generator_workflow_service_caches",
        "clear_cache_response",
    )

    cleared: dict[str, Any] = {}
    errors: dict[str, Any] = {}

    with _IMPORT_CACHE_LOCK:
        loaded_modules = dict(_MODULE_CACHE)

    for module_name, module in loaded_modules.items():
        module_cleared: list[Any] = []

        for candidate in clear_candidates:
            method = _read_module_symbol(module, candidate)
            if method is _MISSING or not callable(method):
                continue

            try:
                module_cleared.append(
                    {
                        "method": candidate,
                        "result": json_safe(method()),
                    }
                )
            except Exception as exc:
                errors.setdefault(module_name, []).append(
                    {
                        "method": candidate,
                        "error": exception_to_dict(exc),
                    }
                )

        if module_cleared:
            cleared[module_name] = module_cleared

    return {
        "ok": not errors,
        "status": "cache_cleared" if not errors else "partial",
        "cleared_at": utc_now_iso(),
        "cleared": cleared,
        "errors": errors,
    }


def clear_services_caches() -> dict[str, Any]:
    runtime_result = clear_services_runtime_caches()
    import_result = clear_services_import_cache()

    return {
        "ok": bool(import_result.get("ok")) and bool(runtime_result.get("ok")),
        "status": "cache_cleared",
        "runtime_caches": runtime_result,
        "import_cache": import_result,
    }


def clear_services_cache() -> dict[str, Any]:
    return clear_services_caches()


# ---------------------------------------------------------------------------
# Internal call helpers
# ---------------------------------------------------------------------------

def _call_symbol(symbol_name: str, *args: Any, **kwargs: Any) -> Any:
    function = load_service_symbol(symbol_name, allow_scan=False)
    if not callable(function):
        raise TypeError(f"Service symbol {symbol_name!r} is not callable.")
    return function(*args, **kwargs)


def _to_response_payload(result: Any) -> dict[str, Any]:
    if hasattr(result, "to_dict") and callable(result.to_dict):
        return json_safe(result.to_dict())

    if isinstance(result, Mapping):
        return json_safe(dict(result))

    return {"ok": True, "value": json_safe(result)}


# ---------------------------------------------------------------------------
# Filesystem / source convenience helpers
# ---------------------------------------------------------------------------

def scan_source(**kwargs: Any) -> Any:
    return _call_symbol("scan_library_source", **kwargs)


def scan_source_response(**kwargs: Any) -> dict[str, Any]:
    return _to_response_payload(_call_symbol("get_library_scan_response", **kwargs))


def list_blocks_response(**kwargs: Any) -> dict[str, Any]:
    return _to_response_payload(_call_symbol("list_library_blocks_response", **kwargs))


def block_detail_response(block_id: Any, **kwargs: Any) -> dict[str, Any]:
    return _to_response_payload(_call_symbol("get_library_block_detail_response", block_id, **kwargs))


def block_variants_response(block_id: Any, **kwargs: Any) -> dict[str, Any]:
    return _to_response_payload(_call_symbol("get_library_block_variants_response", block_id, **kwargs))


def tree_response(**kwargs: Any) -> dict[str, Any]:
    return _to_response_payload(_call_symbol("get_library_tree_response_from_block_service", **kwargs))


# ---------------------------------------------------------------------------
# Create convenience helpers
# ---------------------------------------------------------------------------

def create_options_response(**kwargs: Any) -> dict[str, Any]:
    return _to_response_payload(_call_symbol("get_create_options", **kwargs))


def create_context_response(
    payload: Mapping[str, Any] | None = None,
    **kwargs: Any,
) -> dict[str, Any]:
    return _to_response_payload(_call_symbol("get_create_context", payload_from_mapping_and_kwargs(payload, kwargs)))


def build_create_draft(payload: Mapping[str, Any] | None = None, **kwargs: Any) -> dict[str, Any]:
    return _to_response_payload(_call_symbol("build_draft", payload_from_mapping_and_kwargs(payload, kwargs)))


def validate_create_draft(payload: Mapping[str, Any] | None = None, **kwargs: Any) -> dict[str, Any]:
    return _to_response_payload(_call_symbol("validate_draft", payload_from_mapping_and_kwargs(payload, kwargs)))


def build_create_package_plan(payload: Mapping[str, Any] | None = None, **kwargs: Any) -> dict[str, Any]:
    return _to_response_payload(_call_symbol("build_package_plan", payload_from_mapping_and_kwargs(payload, kwargs)))


def build_create_archive(payload: Mapping[str, Any] | None = None, **kwargs: Any) -> Any:
    return _call_symbol("build_vplib_archive", payload_from_mapping_and_kwargs(payload, kwargs))


def save_create_package(payload: Mapping[str, Any] | None = None, **kwargs: Any) -> dict[str, Any]:
    return _to_response_payload(_call_symbol("save_package", payload_from_mapping_and_kwargs(payload, kwargs)))


# ---------------------------------------------------------------------------
# DB sync convenience helpers
# ---------------------------------------------------------------------------

def sync_library_to_database(**kwargs: Any) -> Any:
    return _call_symbol("sync_library_to_db", **kwargs)


def sync_library_to_database_response(**kwargs: Any) -> dict[str, Any]:
    return _to_response_payload(sync_library_to_database(**kwargs))


def sync_scan_result_to_database(scan_result: Any, **kwargs: Any) -> Any:
    return _call_symbol("sync_scan_result_to_db", scan_result, **kwargs)


def sync_scan_result_to_database_response(scan_result: Any, **kwargs: Any) -> dict[str, Any]:
    return _to_response_payload(sync_scan_result_to_database(scan_result, **kwargs))


# ---------------------------------------------------------------------------
# Published DB read convenience helpers
# ---------------------------------------------------------------------------

def list_published_blocks_db_response(**kwargs: Any) -> dict[str, Any]:
    return _to_response_payload(_call_symbol("list_published_blocks_response", **kwargs))


def published_block_detail_db_response(block_id: Any, **kwargs: Any) -> dict[str, Any]:
    return _to_response_payload(_call_symbol("get_published_block_detail_response", block_id, **kwargs))


def published_block_variants_db_response(block_id: Any, **kwargs: Any) -> dict[str, Any]:
    return _to_response_payload(_call_symbol("get_published_block_variants_response", block_id, **kwargs))


def published_tree_db_response(**kwargs: Any) -> dict[str, Any]:
    return _to_response_payload(_call_symbol("get_published_tree_response", **kwargs))


def published_inventory_db_response(**kwargs: Any) -> dict[str, Any]:
    return _to_response_payload(_call_symbol("get_inventory_response", **kwargs))


def publication_status_response() -> dict[str, Any]:
    return _to_response_payload(_call_symbol("get_publication_status"))


# ---------------------------------------------------------------------------
# User inventory convenience helpers
# ---------------------------------------------------------------------------

def user_inventory_state_response(
    payload: Mapping[str, Any] | None = None,
    **kwargs: Any,
) -> dict[str, Any]:
    return _to_response_payload(
        _call_symbol("user_inventory_get_inventory_response", payload_from_mapping_and_kwargs(payload, kwargs))
    )


def user_inventory_select_slot_response(
    payload: Mapping[str, Any] | None = None,
    **kwargs: Any,
) -> dict[str, Any]:
    return _to_response_payload(
        _call_symbol("user_inventory_select_slot_response", payload_from_mapping_and_kwargs(payload, kwargs))
    )


def user_inventory_set_slot_response(
    slot_index: Any,
    payload: Mapping[str, Any] | None = None,
    **kwargs: Any,
) -> dict[str, Any]:
    return _to_response_payload(
        _call_symbol("user_inventory_set_slot_response", slot_index, payload_from_mapping_and_kwargs(payload, kwargs))
    )


def user_inventory_clear_slot_response(
    slot_index: Any,
    payload: Mapping[str, Any] | None = None,
    **kwargs: Any,
) -> dict[str, Any]:
    return _to_response_payload(
        _call_symbol("user_inventory_clear_slot_response", slot_index, payload_from_mapping_and_kwargs(payload, kwargs))
    )


def user_inventory_health_response() -> dict[str, Any]:
    return _to_response_payload(_call_symbol("user_inventory_service_health"))


def user_inventory_clear_runtime_cache_response() -> dict[str, Any]:
    return _to_response_payload(_call_symbol("user_inventory_clear_cache_response"))


# ---------------------------------------------------------------------------
# Generator context convenience helpers
# ---------------------------------------------------------------------------

def generator_context_response(
    payload: Mapping[str, Any] | None = None,
    **kwargs: Any,
) -> dict[str, Any]:
    return _to_response_payload(
        _call_symbol("get_generator_context_payload", payload_from_mapping_and_kwargs(payload, kwargs))
    )


def generator_frontend_context_response(
    payload: Mapping[str, Any] | None = None,
    **kwargs: Any,
) -> dict[str, Any]:
    return _to_response_payload(
        _call_symbol("get_generator_frontend_context", payload_from_mapping_and_kwargs(payload, kwargs))
    )


def generator_create_options_response(
    payload: Mapping[str, Any] | None = None,
    **kwargs: Any,
) -> dict[str, Any]:
    return _to_response_payload(
        _call_symbol("get_generator_create_options", payload_from_mapping_and_kwargs(payload, kwargs))
    )


def generator_context_health_response() -> dict[str, Any]:
    return _to_response_payload(_call_symbol("get_library_generator_context_service_health"))


# ---------------------------------------------------------------------------
# Generator diagnostics convenience helpers
# ---------------------------------------------------------------------------

def generator_diagnostics_response(
    payload: Mapping[str, Any] | None = None,
    **kwargs: Any,
) -> dict[str, Any]:
    return _to_response_payload(
        _call_symbol("get_generator_diagnostics_payload", payload_from_mapping_and_kwargs(payload, kwargs))
    )


def generator_diagnostics_health_response() -> dict[str, Any]:
    return _to_response_payload(_call_symbol("get_library_generator_diagnostics_service_health"))


# ---------------------------------------------------------------------------
# Generator workflow convenience helpers
# ---------------------------------------------------------------------------

def generator_workflow_response(
    payload: Mapping[str, Any] | None = None,
    **kwargs: Any,
) -> dict[str, Any]:
    return _to_response_payload(
        _call_symbol("run_generator_workflow_payload", payload_from_mapping_and_kwargs(payload, kwargs))
    )


def generator_draft_response(
    payload: Mapping[str, Any] | None = None,
    **kwargs: Any,
) -> dict[str, Any]:
    return _to_response_payload(
        _call_symbol("create_generator_draft_payload", payload_from_mapping_and_kwargs(payload, kwargs))
    )


def generator_validate_response(
    payload: Mapping[str, Any] | None = None,
    **kwargs: Any,
) -> dict[str, Any]:
    return _to_response_payload(
        _call_symbol("validate_generator_payload", payload_from_mapping_and_kwargs(payload, kwargs))
    )


def generator_package_plan_response(
    payload: Mapping[str, Any] | None = None,
    **kwargs: Any,
) -> dict[str, Any]:
    return _to_response_payload(
        _call_symbol("build_generator_package_plan", payload_from_mapping_and_kwargs(payload, kwargs))
    )


def generator_download_response(
    payload: Mapping[str, Any] | None = None,
    **kwargs: Any,
) -> dict[str, Any]:
    return _to_response_payload(
        _call_symbol("prepare_generator_download", payload_from_mapping_and_kwargs(payload, kwargs))
    )


def generator_save_source_response(
    payload: Mapping[str, Any] | None = None,
    **kwargs: Any,
) -> dict[str, Any]:
    return _to_response_payload(
        _call_symbol("save_generator_source_package", payload_from_mapping_and_kwargs(payload, kwargs))
    )


def generator_persistent_draft_response(
    payload: Mapping[str, Any] | None = None,
    **kwargs: Any,
) -> dict[str, Any]:
    return _to_response_payload(
        _call_symbol("create_generator_persistent_draft", payload_from_mapping_and_kwargs(payload, kwargs))
    )


def generator_publish_prepare_response(
    draft_ref: Any = None,
    payload: Mapping[str, Any] | None = None,
    **kwargs: Any,
) -> dict[str, Any]:
    return _to_response_payload(
        _call_symbol(
            "prepare_generator_publish",
            draft_ref=draft_ref,
            payload=payload_from_mapping_and_kwargs(payload, kwargs),
        )
    )


def generator_workflow_health_response() -> dict[str, Any]:
    return _to_response_payload(_call_symbol("get_library_generator_workflow_service_health"))


# ---------------------------------------------------------------------------
# Cache convenience helper
# ---------------------------------------------------------------------------

def clear_scan_cache() -> None:
    clear_library_scan_cache = load_service_symbol("clear_library_scan_cache", allow_scan=False)
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
    "GENERATOR_SERVICE_MODULES",
    "DEFINITION_SERVICE_MODULES",
    "FILE_SERVICE_MODULES",
    "TAXONOMY_SERVICE_MODULES",
    "DRAFT_SERVICE_MODULES",
    "USER_SERVICE_MODULES",
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
    "get_service_module",
    "get_service_module_status",
    "get_service_subhealth",
    "get_services_health",
    "is_services_healthy",
    "assert_services_ready",

    "load_service_symbol",
    "find_service_symbol",
    "preload_service_symbols",

    "get_library_scan_service_module",
    "get_library_block_service_module",
    "get_library_create_service_module",
    "get_library_db_sync_service_module",
    "get_library_published_service_module",
    "get_creative_library_service_module",
    "get_creative_library_user_service_module",
    "get_creative_library_draft_service_module",
    "get_library_definition_catalog_service_module",
    "get_library_definition_seed_service_module",
    "get_library_file_service_module",
    "get_library_taxonomy_user_service_module",
    "get_user_inventory_service_module",
    "get_library_generator_context_service_module",
    "get_library_generator_diagnostics_service_module",
    "get_library_generator_workflow_service_module",

    "scan_source",
    "scan_source_response",
    "list_blocks_response",
    "block_detail_response",
    "block_variants_response",
    "tree_response",

    "create_options_response",
    "create_context_response",
    "build_create_draft",
    "validate_create_draft",
    "build_create_package_plan",
    "build_create_archive",
    "save_create_package",

    "sync_library_to_database",
    "sync_library_to_database_response",
    "sync_scan_result_to_database",
    "sync_scan_result_to_database_response",

    "list_published_blocks_db_response",
    "published_block_detail_db_response",
    "published_block_variants_db_response",
    "published_tree_db_response",
    "published_inventory_db_response",
    "publication_status_response",

    "user_inventory_state_response",
    "user_inventory_select_slot_response",
    "user_inventory_set_slot_response",
    "user_inventory_clear_slot_response",
    "user_inventory_health_response",
    "user_inventory_clear_runtime_cache_response",

    "generator_context_response",
    "generator_frontend_context_response",
    "generator_create_options_response",
    "generator_context_health_response",

    "generator_diagnostics_response",
    "generator_diagnostics_health_response",

    "generator_workflow_response",
    "generator_draft_response",
    "generator_validate_response",
    "generator_package_plan_response",
    "generator_download_response",
    "generator_save_source_response",
    "generator_persistent_draft_response",
    "generator_publish_prepare_response",
    "generator_workflow_health_response",

    "clear_scan_cache",
)