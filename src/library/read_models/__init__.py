# services/vectoplan-library/src/library/read_models/__init__.py
"""
Read-Models Package der VECTOPLAN Creative-Library-Schicht.

Dieses Package bündelt API-taugliche Lesemodelle für zwei Lesepfade:

1. Dateibasierter Entwicklungs-/Debug-Pfad

    src/library/source
        → Scanner
        → Reader
        → Validation
        → Fingerprint
        → Read-Models
        → API

2. DB-basierter produktiver Published-Pfad

    creative_library Tabellen
        → Repository
        → Published-Service
        → DB-Read-Models
        → API

Bisherige dateibasierte Module:

- `block_summary_builder.py`
  Baut kompakte Block-/Objekt-Summaries für Listenansichten.

- `block_detail_builder.py`
  Baut ausführliche Detailansichten für einzelne Blöcke/Objekte.

- `library_index_builder.py`
  Baut einen in-memory Index mit Zugriff per ID, Tree-Struktur,
  Taxonomie-Navigation und Duplikaterkennung.

Neue DB-basierte Module:

- `db_block_summary_builder.py`
  Baut Blocklisten-/Summary-Antworten aus veröffentlichten DB-Daten.

- `db_block_detail_builder.py`
  Baut Detail- und Variantenantworten aus veröffentlichten DB-Daten.

- `db_library_tree_builder.py`
  Baut die Creative-Library-Tree-Struktur aus veröffentlichten DB-Daten.

- `db_inventory_builder.py`
  Baut den Editor-/Creative-Library-Inventarzustand aus DB-Daten.

Zielrouten:

    GET /api/v1/vplib/library/blocks
    GET /api/v1/vplib/library/blocks/<block_id>
    GET /api/v1/vplib/library/blocks/<block_id>/variants
    GET /api/v1/vplib/library/tree
    GET /api/v1/vplib/library/inventory

Diese Schicht ist bewusst getrennt von:

- Flask-Routes
- Scanner-Discovery
- Datei-Reader
- fachlicher Validierung
- Datenbankzugriff
- Persistenz nach `creative_library`

Read-Models erhalten fertige Pipeline-, Repository- oder Service-Ergebnisse und
bauen daraus stabile, JSON-kompatible Antworten.

Taxonomie-Regel:

    Backend-Taxonomie ist kanonisch für:
    - Domain/Reiter
    - Kategorie
    - Subkategorie
    - Labels
    - Source-Pfade
    - Tree-Sortierung
    - optionale leere Tree-Knoten

DB-/Publication-Regel:

    vplib_uid ist die stabile technische Package-ID.
    family_id und package_id bleiben semantische IDs.
    revision_hash beschreibt die Inhaltsrevision.

Version 0.3.0:

- DB-Read-Model-Builder werden optional reexportiert.
- Bestehende dateibasierte Reexports bleiben rückwärtskompatibel.
- DB-Builder-Health wird in Subhealth aufgenommen.
- Optionale DB-Builder brechen den Import nicht im Standardmodus.
- Namenskollisionen generischer Builder-Funktionen werden über Aliasnamen gelöst.
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

READ_MODELS_PACKAGE_VERSION: Final[str] = "0.3.0"
READ_MODELS_PACKAGE_NAME: Final[str] = "library.read_models"
READ_MODELS_COMPONENT_NAME: Final[str] = "creative-library-read-models"

READ_MODEL_MODULES: Final[tuple[str, ...]] = (
    "block_summary_builder",
    "block_detail_builder",
    "library_index_builder",
    "db_block_summary_builder",
    "db_block_detail_builder",
    "db_library_tree_builder",
    "db_inventory_builder",
)

REQUIRED_READ_MODEL_MODULES: Final[tuple[str, ...]] = (
    "block_summary_builder",
    "block_detail_builder",
    "library_index_builder",
)

OPTIONAL_READ_MODEL_MODULES: Final[tuple[str, ...]] = (
    "db_block_summary_builder",
    "db_block_detail_builder",
    "db_library_tree_builder",
    "db_inventory_builder",
)

DB_READ_MODEL_MODULES: Final[tuple[str, ...]] = (
    "db_block_summary_builder",
    "db_block_detail_builder",
    "db_library_tree_builder",
    "db_inventory_builder",
)


# ---------------------------------------------------------------------------
# Symbol registry
# ---------------------------------------------------------------------------

SYMBOL_TO_MODULE: Final[dict[str, str]] = {
    # -----------------------------------------------------------------------
    # block_summary_builder.py
    # -----------------------------------------------------------------------
    "BLOCK_SUMMARY_BUILDER_VERSION": "block_summary_builder",
    "BLOCK_SUMMARY_BUILDER_COMPONENT": "block_summary_builder",
    "DEFAULT_SUMMARY_STATUS": "block_summary_builder",
    "DEFAULT_SUMMARY_SORT": "block_summary_builder",
    "SUMMARY_STATUS_VALUES": "block_summary_builder",
    "SUMMARY_SORT_VALUES": "block_summary_builder",
    "UNKNOWN_TAXONOMY_KEY": "block_summary_builder",
    "BlockSummaryBuilderOptions": "block_summary_builder",
    "BlockSummaryBuildResult": "block_summary_builder",
    "clear_taxonomy_cache": "block_summary_builder",
    "taxonomy_available": "block_summary_builder",
    "normalize_taxonomy_key": "block_summary_builder",
    "load_taxonomy_payload": "block_summary_builder",
    "get_taxonomy_lookup": "block_summary_builder",
    "get_cached_taxonomy_version": "block_summary_builder",
    "build_taxonomy_lookup_from_payload": "block_summary_builder",
    "taxonomy_entry": "block_summary_builder",
    "taxonomy_label": "block_summary_builder",
    "normalize_taxonomy_path": "block_summary_builder",
    "extract_taxonomy_context": "block_summary_builder",
    "enrich_summary_with_taxonomy": "block_summary_builder",
    "normalize_summary_status": "block_summary_builder",
    "normalize_sort_mode": "block_summary_builder",
    "item_to_summary_dict": "block_summary_builder",
    "summary_item_is_valid": "block_summary_builder",
    "validation_summary_from_result": "block_summary_builder",
    "status_from_validation_result": "block_summary_builder",
    "extract_documents_from_any": "block_summary_builder",
    "extract_revision_hash": "block_summary_builder",
    "extract_source_path": "block_summary_builder",
    "extract_relative_package_root": "block_summary_builder",
    "extract_package_root": "block_summary_builder",
    "extract_scanned_at": "block_summary_builder",
    "extract_package_version": "block_summary_builder",
    "extract_schema_version": "block_summary_builder",
    "extract_created_at": "block_summary_builder",
    "extract_updated_at": "block_summary_builder",
    "extract_classification": "block_summary_builder",
    "extract_asset_refs": "block_summary_builder",
    "extract_variant_summary": "block_summary_builder",
    "extract_label_and_description": "block_summary_builder",
    "extract_tags": "block_summary_builder",
    "extract_enabled": "block_summary_builder",
    "build_library_item_from_parts": "block_summary_builder",
    "build_library_item_from_read_result": "block_summary_builder",
    "build_library_items_from_results": "block_summary_builder",
    "build_error_summary_item": "block_summary_builder",
    "coerce_summary_options": "block_summary_builder",
    "build_block_summary_result": "block_summary_builder",
    "build_block_summary_result_from_pipeline": "block_summary_builder",
    "build_blocks_response_from_items": "block_summary_builder",
    "build_blocks_response_from_pipeline": "block_summary_builder",
    "build_single_summary_dict": "block_summary_builder",
    "get_block_summary_builder_health": "block_summary_builder",
    "assert_block_summary_builder_ready": "block_summary_builder",

    # -----------------------------------------------------------------------
    # block_detail_builder.py
    # -----------------------------------------------------------------------
    "BLOCK_DETAIL_BUILDER_VERSION": "block_detail_builder",
    "BLOCK_DETAIL_BUILDER_COMPONENT": "block_detail_builder",
    "DEFAULT_DETAIL_STATUS": "block_detail_builder",
    "DETAIL_STATUS_VALUES": "block_detail_builder",
    "DEFAULT_DETAIL_DOCUMENT_GROUP_ORDER": "block_detail_builder",
    "BlockDetailBuilderOptions": "block_detail_builder",
    "BlockDetailBuildResult": "block_detail_builder",
    "get_taxonomy_health_payload": "block_detail_builder",
    "build_detail_taxonomy_payload": "block_detail_builder",
    "build_classification_payload": "block_detail_builder",
    "normalize_detail_status": "block_detail_builder",
    "safe_detail_to_dict": "block_detail_builder",
    "extract_source_root": "block_detail_builder",
    "extract_discovered_at": "block_detail_builder",
    "extract_document_groups": "block_detail_builder",
    "normalize_variant_payload": "block_detail_builder",
    "extract_variant_payloads": "block_detail_builder",
    "extract_module_payloads": "block_detail_builder",
    "extract_fingerprint_payload": "block_detail_builder",
    "extract_validation_payload": "block_detail_builder",
    "extract_package_payload": "block_detail_builder",
    "extract_family_payload": "block_detail_builder",
    "extract_profile_payloads": "block_detail_builder",
    "coerce_detail_options": "block_detail_builder",
    "build_library_item_detail_if_possible": "block_detail_builder",
    "build_detail_fallback_dict": "block_detail_builder",
    "build_block_detail_from_parts": "block_detail_builder",
    "build_block_detail_from_read_result": "block_detail_builder",
    "find_pipeline_entry_by_block_id": "block_detail_builder",
    "build_block_detail_result_by_id": "block_detail_builder",
    "build_block_detail_response_from_parts": "block_detail_builder",
    "build_block_detail_response_by_id": "block_detail_builder",
    "build_block_variants_response_from_parts": "block_detail_builder",
    "get_block_detail_builder_health": "block_detail_builder",
    "assert_block_detail_builder_ready": "block_detail_builder",

    # -----------------------------------------------------------------------
    # library_index_builder.py
    # -----------------------------------------------------------------------
    "LIBRARY_INDEX_BUILDER_VERSION": "library_index_builder",
    "LIBRARY_INDEX_BUILDER_COMPONENT": "library_index_builder",
    "DEFAULT_INDEX_STATUS": "library_index_builder",
    "DEFAULT_INDEX_SORT": "library_index_builder",
    "INDEX_STATUS_VALUES": "library_index_builder",
    "INDEX_SORT_VALUES": "library_index_builder",
    "TREE_ROOT_KEY": "library_index_builder",
    "UNKNOWN_TREE_KEY": "library_index_builder",
    "TREE_LEVEL_ROOT": "library_index_builder",
    "TREE_LEVEL_DOMAIN": "library_index_builder",
    "TREE_LEVEL_CATEGORY": "library_index_builder",
    "TREE_LEVEL_SUBCATEGORY": "library_index_builder",
    "LibraryTreeNode": "library_index_builder",
    "LibraryIndexBuilderOptions": "library_index_builder",
    "LibraryIndexStats": "library_index_builder",
    "LibraryIndex": "library_index_builder",
    "get_taxonomy_payload": "library_index_builder",
    "get_taxonomy_tree_payload": "library_index_builder",
    "get_taxonomy_version_from_payload": "library_index_builder",
    "deep_mapping_get": "library_index_builder",
    "build_taxonomy_lookup": "library_index_builder",
    "taxonomy_lookup_entry": "library_index_builder",
    "taxonomy_sort_order": "library_index_builder",
    "build_empty_taxonomy_tree": "library_index_builder",
    "normalize_index_status": "library_index_builder",
    "get_item_attr": "library_index_builder",
    "get_nested_item_attr": "library_index_builder",
    "first_item_value": "library_index_builder",
    "get_item_id": "library_index_builder",
    "get_item_family_id": "library_index_builder",
    "get_item_status": "library_index_builder",
    "get_item_enabled": "library_index_builder",
    "get_item_revision_hash": "library_index_builder",
    "get_item_label": "library_index_builder",
    "get_item_domain": "library_index_builder",
    "get_item_category": "library_index_builder",
    "get_item_subcategory": "library_index_builder",
    "get_item_taxonomy_version": "library_index_builder",
    "get_item_classification_path": "library_index_builder",
    "get_item_object_kind": "library_index_builder",
    "item_is_valid": "library_index_builder",
    "item_to_summary": "library_index_builder",
    "normalize_items": "library_index_builder",
    "sort_items_for_index": "library_index_builder",
    "make_duplicate_info": "library_index_builder",
    "duplicate_to_dict": "library_index_builder",
    "make_tree_node": "library_index_builder",
    "increment_tree_node": "library_index_builder",
    "build_tree_from_items": "library_index_builder",
    "sort_tree_dict": "library_index_builder",
    "build_library_index_from_items": "library_index_builder",
    "build_library_items_from_results_safe": "library_index_builder",
    "build_library_index_from_pipeline": "library_index_builder",
    "build_library_index_from_scan_result": "library_index_builder",
    "find_library_item_by_id": "library_index_builder",
    "index_items_from_any": "library_index_builder",
    "filter_index_items": "library_index_builder",
    "build_blocks_response_from_index": "library_index_builder",
    "build_tree_response_from_index": "library_index_builder",
    "build_index_response": "library_index_builder",
    "get_library_index_builder_health": "library_index_builder",
    "assert_library_index_builder_ready": "library_index_builder",

    # -----------------------------------------------------------------------
    # db_block_summary_builder.py
    # -----------------------------------------------------------------------
    "DB_BLOCK_SUMMARY_BUILDER_NAME": "db_block_summary_builder",
    "DB_BLOCK_SUMMARY_COMPONENT_NAME": "db_block_summary_builder",
    "DB_BLOCK_SUMMARY_API_VERSION": "db_block_summary_builder",
    "DB_BLOCK_SUMMARY_MODEL_VERSION": "db_block_summary_builder",
    "DbBlockSummaryStatus": "db_block_summary_builder",
    "DbBlockSummarySortField": "db_block_summary_builder",
    "DbBlockSummaryBuilderOptions": "db_block_summary_builder",
    "DbBlockSummarySourceBundle": "db_block_summary_builder",
    "DbBlockSummaryBuildResult": "db_block_summary_builder",
    "clear_db_block_summary_builder_caches": "db_block_summary_builder",
    "build_asset_refs": "db_block_summary_builder",
    "infer_validation_summary": "db_block_summary_builder",
    "build_summary_from_db_bundle": "db_block_summary_builder",
    "build_summary_from_db_row": "db_block_summary_builder",
    "build_summaries_from_db_rows": "db_block_summary_builder",
    "filter_summaries": "db_block_summary_builder",
    "summary_sort_key": "db_block_summary_builder",
    "sort_summaries": "db_block_summary_builder",
    "paginate_summaries": "db_block_summary_builder",
    "summary_to_dict": "db_block_summary_builder",
    "build_block_summary_result_from_summaries": "db_block_summary_builder",
    "build_block_summary_result_from_db_rows": "db_block_summary_builder",
    "build_blocks_response_from_summaries": "db_block_summary_builder",
    "build_blocks_response_from_db_rows": "db_block_summary_builder",
    "build_empty_blocks_response": "db_block_summary_builder",
    "build_error_blocks_response": "db_block_summary_builder",
    "get_db_block_summary_builder_health": "db_block_summary_builder",
    "assert_db_block_summary_builder_ready": "db_block_summary_builder",

    # -----------------------------------------------------------------------
    # db_block_detail_builder.py
    # -----------------------------------------------------------------------
    "DB_BLOCK_DETAIL_BUILDER_NAME": "db_block_detail_builder",
    "DB_BLOCK_DETAIL_COMPONENT_NAME": "db_block_detail_builder",
    "DB_BLOCK_DETAIL_API_VERSION": "db_block_detail_builder",
    "DB_BLOCK_DETAIL_MODEL_VERSION": "db_block_detail_builder",
    "DbBlockDetailStatus": "db_block_detail_builder",
    "DbDocumentGroup": "db_block_detail_builder",
    "DbBlockDetailBuilderOptions": "db_block_detail_builder",
    "DbBlockDetailSourceBundle": "db_block_detail_builder",
    "DbDocumentEntry": "db_block_detail_builder",
    "DbBlockDetailBuildResult": "db_block_detail_builder",
    "clear_db_block_detail_builder_caches": "db_block_detail_builder",
    "normalize_asset_refs": "db_block_detail_builder",
    "normalize_variant_refs": "db_block_detail_builder",
    "normalize_revision": "db_block_detail_builder",
    "build_validation_summary": "db_block_detail_builder",
    "normalize_documents": "db_block_detail_builder",
    "group_documents": "db_block_detail_builder",
    "extract_document_payload_by_path": "db_block_detail_builder",
    "build_detail_from_bundle": "db_block_detail_builder",
    "build_package_payload": "db_block_detail_builder",
    "build_family_payload": "db_block_detail_builder",
    "build_profile_payload": "db_block_detail_builder",
    "build_detail_result_from_db_payload": "db_block_detail_builder",
    "build_detail_response_from_db_payload": "db_block_detail_builder",
    "build_not_found_detail_response": "db_block_detail_builder",
    "build_error_detail_response": "db_block_detail_builder",
    "build_variants_response_from_db_payload": "db_block_detail_builder",
    "get_db_block_detail_builder_health": "db_block_detail_builder",
    "assert_db_block_detail_builder_ready": "db_block_detail_builder",

    # -----------------------------------------------------------------------
    # db_library_tree_builder.py
    # -----------------------------------------------------------------------
    "DB_LIBRARY_TREE_BUILDER_NAME": "db_library_tree_builder",
    "DB_LIBRARY_TREE_COMPONENT_NAME": "db_library_tree_builder",
    "DB_LIBRARY_TREE_API_VERSION": "db_library_tree_builder",
    "DB_LIBRARY_TREE_MODEL_VERSION": "db_library_tree_builder",
    "DbLibraryTreeStatus": "db_library_tree_builder",
    "DbLibraryTreeNodeType": "db_library_tree_builder",
    "DbLibraryTreeBuilderOptions": "db_library_tree_builder",
    "DbLibraryTreeNode": "db_library_tree_builder",
    "DbLibraryTreeBuildResult": "db_library_tree_builder",
    "clear_db_library_tree_builder_caches": "db_library_tree_builder",
    "build_summary": "db_library_tree_builder",
    "build_summaries": "db_library_tree_builder",
    "summary_item_id": "db_library_tree_builder",
    "summary_domain": "db_library_tree_builder",
    "summary_category": "db_library_tree_builder",
    "summary_subcategory": "db_library_tree_builder",
    "add_item_to_tree": "db_library_tree_builder",
    "prune_empty_nodes": "db_library_tree_builder",
    "build_tree_from_summaries": "db_library_tree_builder",
    "build_tree_from_db_rows": "db_library_tree_builder",
    "build_tree_stats": "db_library_tree_builder",
    "build_tree_result_from_summaries": "db_library_tree_builder",
    "build_tree_result_from_db_rows": "db_library_tree_builder",
    "build_tree_response_from_summaries": "db_library_tree_builder",
    "build_tree_response_from_db_rows": "db_library_tree_builder",
    "build_empty_tree_response": "db_library_tree_builder",
    "build_error_tree_response": "db_library_tree_builder",
    "get_db_library_tree_builder_health": "db_library_tree_builder",
    "assert_db_library_tree_builder_ready": "db_library_tree_builder",

    # -----------------------------------------------------------------------
    # db_inventory_builder.py
    # -----------------------------------------------------------------------
    "DB_INVENTORY_BUILDER_NAME": "db_inventory_builder",
    "DB_INVENTORY_COMPONENT_NAME": "db_inventory_builder",
    "DB_INVENTORY_API_VERSION": "db_inventory_builder",
    "DB_INVENTORY_MODEL_VERSION": "db_inventory_builder",
    "DbInventoryBuildStatus": "db_inventory_builder",
    "DbInventoryBuildSource": "db_inventory_builder",
    "DbInventoryBuilderOptions": "db_inventory_builder",
    "DbInventorySourceBundle": "db_inventory_builder",
    "DbInventoryBuildResult": "db_inventory_builder",
    "clear_db_inventory_builder_caches": "db_inventory_builder",
    "normalize_inventory_asset": "db_inventory_builder",
    "normalize_inventory_variant": "db_inventory_builder",
    "normalize_inventory_slot": "db_inventory_builder",
    "normalize_published_family": "db_inventory_builder",
    "family_key_candidates": "db_inventory_builder",
    "find_related_items": "db_inventory_builder",
    "find_default_variant": "db_inventory_builder",
    "build_slot_from_db_slot": "db_inventory_builder",
    "build_slot_from_published_family": "db_inventory_builder",
    "build_slots_from_db_slots": "db_inventory_builder",
    "build_slots_from_published_families": "db_inventory_builder",
    "build_empty_slots": "db_inventory_builder",
    "build_inventory_state_from_slots": "db_inventory_builder",
    "build_inventory_result_from_bundle": "db_inventory_builder",
    "build_inventory_result_from_sources": "db_inventory_builder",
    "slot_to_dict": "db_inventory_builder",
    "build_inventory_response_from_slots": "db_inventory_builder",
    "build_inventory_response_from_bundle": "db_inventory_builder",
    "build_inventory_response_from_sources": "db_inventory_builder",
    "build_empty_db_inventory_response": "db_inventory_builder",
    "build_error_db_inventory_response": "db_inventory_builder",
    "get_db_inventory_builder_health": "db_inventory_builder",
    "assert_db_inventory_builder_ready": "db_inventory_builder",
}


# ---------------------------------------------------------------------------
# Symbol aliases for colliding generic names
# ---------------------------------------------------------------------------

SYMBOL_ALIASES: Final[dict[str, tuple[str, str]]] = {
    # db_block_summary_builder.py
    "db_summary_build_options_from_query": ("db_block_summary_builder", "build_options_from_query"),
    "db_summary_build_filters_from_query": ("db_block_summary_builder", "build_filters_from_query"),
    "db_summary_normalize_sort_field": ("db_block_summary_builder", "normalize_sort_field"),
    "db_summary_normalize_sort_direction": ("db_block_summary_builder", "normalize_sort_direction"),
    "db_summary_build_single_summary_dict": ("db_block_summary_builder", "build_single_summary_dict"),

    # db_block_detail_builder.py
    "db_detail_build_options_from_query": ("db_block_detail_builder", "build_options_from_query"),
    "db_detail_normalize_document_path": ("db_block_detail_builder", "normalize_document_path"),
    "db_detail_document_group_for_path": ("db_block_detail_builder", "document_group_for_path"),

    # db_library_tree_builder.py
    "db_tree_build_options_from_query": ("db_library_tree_builder", "build_options_from_query"),
    "db_tree_build_filters_from_query": ("db_library_tree_builder", "build_filters_from_query"),
    "db_tree_make_tree_node": ("db_library_tree_builder", "make_tree_node"),
    "db_tree_summary_to_dict": ("db_library_tree_builder", "summary_to_dict"),

    # db_inventory_builder.py
    "db_inventory_build_options_from_query": ("db_inventory_builder", "build_options_from_query"),
    "db_inventory_build_filters_from_query": ("db_inventory_builder", "build_filters_from_query"),
    "db_inventory_normalize_source": ("db_inventory_builder", "normalize_source"),
    "db_inventory_normalize_scope": ("db_inventory_builder", "normalize_scope"),
    "db_inventory_normalize_mode": ("db_inventory_builder", "normalize_mode"),
    "db_inventory_build_response": ("db_inventory_builder", "build_inventory_response_from_bundle"),
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
class ReadModelModuleStatus:
    """Importstatus eines Read-Model-Submoduls."""

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
            "error": json_safe(self.error),
        }


@dataclass(frozen=True)
class ReadModelsHealth:
    """Health-Modell für `library.read_models`."""

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
    db_read_models: dict[str, Any] = field(default_factory=dict)
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
            "modules": json_safe(self.modules),
            "subhealth": json_safe(self.subhealth),
            "taxonomy": json_safe(self.taxonomy),
            "db_read_models": json_safe(self.db_read_models),
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

        to_summary_dict = getattr(value, "to_summary_dict", None)
        if callable(to_summary_dict):
            return json_safe(to_summary_dict())

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
    """Baut den vollständigen Importpfad eines Read-Model-Submoduls."""
    return f"{__name__}.{module_name}"


def clear_read_model_import_cache() -> dict[str, Any]:
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

    for module_name in READ_MODEL_MODULES:
        globals().pop(module_name, None)

    return {
        "ok": True,
        "cleared_module_cache": cached_modules,
        "cleared_import_errors": cached_errors,
    }


def clear_read_model_runtime_caches() -> dict[str, Any]:
    """
    Leert bekannte Laufzeit-Caches der Read-Model-Schicht.

    Es werden nur bereits importierte oder lazy verfügbare Clear-Funktionen
    aufgerufen. Fehler werden gesammelt, nicht verschluckt.
    """

    clear_function_names = (
        "clear_taxonomy_cache",
        "clear_db_block_summary_builder_caches",
        "clear_db_block_detail_builder_caches",
        "clear_db_library_tree_builder_caches",
        "clear_db_inventory_builder_caches",
    )

    cleared: dict[str, Any] = {
        "cleared": [],
        "errors": [],
    }

    for function_name in clear_function_names:
        try:
            clear_fn = load_read_model_symbol(function_name)
            if callable(clear_fn):
                result = clear_fn()
                cleared["cleared"].append(
                    {
                        "function": function_name,
                        "result": json_safe(result),
                    }
                )
        except Exception as exc:
            cleared["errors"].append(
                {
                    "function": function_name,
                    "error": exception_to_dict(exc),
                }
            )

    return {
        "ok": not cleared["errors"],
        **cleared,
    }


def clear_read_models_caches() -> dict[str, Any]:
    """Leert Import- und Runtime-Caches der Read-Model-Schicht."""

    runtime = clear_read_model_runtime_caches()
    imports = clear_read_model_import_cache()

    return {
        "ok": bool(runtime.get("ok")) and bool(imports.get("ok")),
        "runtime": runtime,
        "imports": imports,
    }


clear_read_models_cache = clear_read_models_caches


def safe_import_module(
    module_name: str,
    *,
    include_traceback: bool = False,
    force_reload: bool = False,
) -> tuple[ModuleType | None, ReadModelModuleStatus]:
    """
    Importiert ein Read-Model-Submodul defensiv.

    Rückgabe:
      (module, status)
    """

    import_path = build_module_import_path(module_name)
    required = module_name in REQUIRED_READ_MODEL_MODULES
    optional = module_name in OPTIONAL_READ_MODEL_MODULES
    db_module = module_name in DB_READ_MODEL_MODULES

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

        return module, ReadModelModuleStatus(
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
            _MODULE_CACHE.pop(module_name, None)
            _IMPORT_ERRORS[module_name] = error_payload

        return None, ReadModelModuleStatus(
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
    """Extrahiert Taxonomieinformationen aus Read-Model-Subhealth."""
    result: dict[str, Any] = {
        "available": None,
        "payload_ok": None,
        "taxonomy_version": None,
        "summary_cache_loaded_at": None,
        "builders": {},
    }

    for builder_name in ("block_summary_builder", "block_detail_builder", "library_index_builder"):
        health = subhealth.get(builder_name)
        if not isinstance(health, Mapping):
            continue

        taxonomy = health.get("taxonomy")
        if isinstance(taxonomy, Mapping):
            result["builders"][builder_name] = dict(json_safe(taxonomy))

            if result["available"] is None and taxonomy.get("available") is not None:
                result["available"] = taxonomy.get("available")

            if result["payload_ok"] is None and taxonomy.get("payload_ok") is not None:
                result["payload_ok"] = taxonomy.get("payload_ok")

            if not result["taxonomy_version"] and taxonomy.get("taxonomy_version"):
                result["taxonomy_version"] = taxonomy.get("taxonomy_version")

            if builder_name == "block_summary_builder":
                result["summary_cache_loaded_at"] = taxonomy.get("cache_loaded_at")

    return result


def _extract_db_read_model_health_from_subhealth(subhealth: Mapping[str, Any]) -> dict[str, Any]:
    """Extrahiert DB-Builder-Capabilities aus Subhealth."""
    builder_keys = (
        "db_block_summary_builder",
        "db_block_detail_builder",
        "db_library_tree_builder",
        "db_inventory_builder",
    )

    builders: dict[str, Any] = {}

    for key in builder_keys:
        health = subhealth.get(key)

        builders[key] = {
            "available": isinstance(health, Mapping) and _status_is_healthy(health),
            "api_version": health.get("api_version") if isinstance(health, Mapping) else None,
            "model_version": health.get("model_version") if isinstance(health, Mapping) else None,
            "status": health.get("status") if isinstance(health, Mapping) else None,
        }

    return {
        "supported": True,
        "builders": builders,
        "summary_ready": bool(builders["db_block_summary_builder"]["available"]),
        "detail_ready": bool(builders["db_block_detail_builder"]["available"]),
        "tree_ready": bool(builders["db_library_tree_builder"]["available"]),
        "inventory_ready": bool(builders["db_inventory_builder"]["available"]),
    }


def _build_capabilities(
    *,
    taxonomy: Mapping[str, Any],
    db_read_models: Mapping[str, Any],
) -> dict[str, Any]:
    """Kompakte Capability-Map für Health/Admin."""
    return {
        "filesystem_summary_builder": True,
        "filesystem_detail_builder": True,
        "filesystem_index_builder": True,
        "taxonomy_read_models": taxonomy.get("payload_ok") is not False,
        "db_summary_builder": bool(db_read_models.get("summary_ready")),
        "db_detail_builder": bool(db_read_models.get("detail_ready")),
        "db_tree_builder": bool(db_read_models.get("tree_ready")),
        "db_inventory_builder": bool(db_read_models.get("inventory_ready")),
        "published_blocks_response": bool(db_read_models.get("summary_ready")),
        "published_detail_response": bool(db_read_models.get("detail_ready")),
        "published_tree_response": bool(db_read_models.get("tree_ready")),
        "published_inventory_response": bool(db_read_models.get("inventory_ready")),
    }


# ---------------------------------------------------------------------------
# Health
# ---------------------------------------------------------------------------

def get_read_model_module_status(
    *,
    include_traceback: bool = False,
    force_reload: bool = False,
    include_optional: bool = True,
) -> dict[str, dict[str, Any]]:
    """Liefert den Importstatus aller Read-Model-Submodule."""
    statuses: dict[str, dict[str, Any]] = {}

    module_names = READ_MODEL_MODULES if include_optional else REQUIRED_READ_MODEL_MODULES

    for module_name in module_names:
        _, status = safe_import_module(
            module_name,
            include_traceback=include_traceback,
            force_reload=force_reload,
        )
        statuses[module_name] = status.to_dict()

    return statuses


def get_read_model_subhealth(
    *,
    include_traceback: bool = False,
    force_reload: bool = False,
    include_optional: bool = True,
) -> dict[str, dict[str, Any]]:
    """Ruft optionale Health-Funktionen der Read-Model-Submodule auf."""
    subhealth: dict[str, dict[str, Any]] = {}

    health_functions = {
        "block_summary_builder": "get_block_summary_builder_health",
        "block_detail_builder": "get_block_detail_builder_health",
        "library_index_builder": "get_library_index_builder_health",
        "db_block_summary_builder": "get_db_block_summary_builder_health",
        "db_block_detail_builder": "get_db_block_detail_builder_health",
        "db_library_tree_builder": "get_db_library_tree_builder_health",
        "db_inventory_builder": "get_db_inventory_builder_health",
    }

    module_names = READ_MODEL_MODULES if include_optional else REQUIRED_READ_MODEL_MODULES

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
                    "required": module_name in REQUIRED_READ_MODEL_MODULES,
                    "optional": module_name in OPTIONAL_READ_MODEL_MODULES,
                    "db_module": module_name in DB_READ_MODEL_MODULES,
                    "error": status.error,
                }
                continue

            if not function_name:
                subhealth[module_name] = {
                    "ok": True,
                    "healthy": True,
                    "status": "loaded_no_health_function",
                    "required": module_name in REQUIRED_READ_MODEL_MODULES,
                    "optional": module_name in OPTIONAL_READ_MODEL_MODULES,
                    "db_module": module_name in DB_READ_MODEL_MODULES,
                }
                continue

            health_function = getattr(module, function_name, None)

            if not callable(health_function):
                subhealth[module_name] = {
                    "ok": False,
                    "healthy": False,
                    "status": "missing_health_function",
                    "required": module_name in REQUIRED_READ_MODEL_MODULES,
                    "optional": module_name in OPTIONAL_READ_MODEL_MODULES,
                    "db_module": module_name in DB_READ_MODEL_MODULES,
                    "function": function_name,
                }
                continue

            try:
                health = health_function()
            except TypeError:
                health = health_function(include_traceback=include_traceback)

            health_payload = dataclass_to_dict_safe(health)
            health_payload.setdefault("required", module_name in REQUIRED_READ_MODEL_MODULES)
            health_payload.setdefault("optional", module_name in OPTIONAL_READ_MODEL_MODULES)
            health_payload.setdefault("db_module", module_name in DB_READ_MODEL_MODULES)
            subhealth[module_name] = health_payload

        except Exception as exc:
            subhealth[module_name] = {
                "ok": False,
                "healthy": False,
                "status": "health_error",
                "required": module_name in REQUIRED_READ_MODEL_MODULES,
                "optional": module_name in OPTIONAL_READ_MODEL_MODULES,
                "db_module": module_name in DB_READ_MODEL_MODULES,
                "error": exception_to_dict(exc, include_traceback=include_traceback),
            }

    return subhealth


def get_read_models_health(
    *,
    include_traceback: bool = False,
    include_subhealth: bool = True,
    include_optional: bool = True,
    force_reload: bool = False,
    strict_optional: bool = False,
) -> dict[str, Any]:
    """
    Liefert einen robusten Health-Status der Read-Models-Schicht.

    include_optional:
        Wenn True, werden auch DB-Builder geprüft.

    strict_optional:
        Wenn True, führen Fehler in DB-Buildern zu unhealthy.
        Standard ist False, damit der alte dateibasierte Pfad während der
        Migration weiter funktioniert.
    """

    module_statuses = get_read_model_module_status(
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
        for name in REQUIRED_READ_MODEL_MODULES
        if name in loaded_modules
    ]

    loaded_optional_modules = [
        name
        for name in OPTIONAL_READ_MODEL_MODULES
        if name in loaded_modules
    ]

    loaded_db_modules = [
        name
        for name in DB_READ_MODEL_MODULES
        if name in loaded_modules
    ]

    warnings: list[str] = []
    errors: list[str] = []

    for module_name in failed_modules:
        if module_name in REQUIRED_READ_MODEL_MODULES:
            errors.append(f"required read model module failed to import: {module_name}")
        elif strict_optional:
            errors.append(f"optional read model module failed to import: {module_name}")
        else:
            warnings.append(f"optional read model module failed to import: {module_name}")

    missing_required = [
        name
        for name in REQUIRED_READ_MODEL_MODULES
        if name not in loaded_required_modules
    ]

    for module_name in missing_required:
        errors.append(f"required read model module is not loaded: {module_name}")

    symbol_count = 0

    for status in module_statuses.values():
        try:
            symbol_count += int(status.get("symbol_count", 0))
        except Exception:
            continue

    subhealth: dict[str, dict[str, Any]] = {}

    if include_subhealth:
        subhealth = get_read_model_subhealth(
            include_traceback=include_traceback,
            force_reload=force_reload,
            include_optional=include_optional,
        )

        for name, health in subhealth.items():
            if _status_is_healthy(health):
                continue

            if name in REQUIRED_READ_MODEL_MODULES:
                errors.append(f"required read model subhealth failed: {name}")
            elif strict_optional:
                errors.append(f"optional read model subhealth failed: {name}")
            else:
                warnings.append(f"optional read model subhealth failed: {name}")

    taxonomy = _extract_taxonomy_health_from_subhealth(subhealth)
    db_read_models = _extract_db_read_model_health_from_subhealth(subhealth)
    capabilities = _build_capabilities(
        taxonomy=taxonomy,
        db_read_models=db_read_models,
    )

    if taxonomy.get("payload_ok") is False:
        warnings.append("read model taxonomy payload is unavailable or degraded")

    healthy = len(errors) == 0

    health = ReadModelsHealth(
        ok=healthy,
        healthy=healthy,
        package=READ_MODELS_PACKAGE_NAME,
        component=READ_MODELS_COMPONENT_NAME,
        version=READ_MODELS_PACKAGE_VERSION,
        generated_at=utc_now_iso(),
        module_count=len(module_statuses),
        loaded_module_count=len(loaded_modules),
        failed_module_count=len(failed_modules),
        required_module_count=len(REQUIRED_READ_MODEL_MODULES),
        loaded_required_module_count=len(loaded_required_modules),
        optional_module_count=len(OPTIONAL_READ_MODEL_MODULES),
        loaded_optional_module_count=len(loaded_optional_modules),
        db_module_count=len(DB_READ_MODEL_MODULES),
        loaded_db_module_count=len(loaded_db_modules),
        symbol_count=symbol_count,
        modules=module_statuses,
        subhealth=subhealth,
        taxonomy=taxonomy,
        db_read_models=db_read_models,
        capabilities=capabilities,
        warnings=tuple(warnings),
        errors=tuple(errors),
    )

    return health.to_dict()


def is_read_models_healthy(
    *,
    include_optional: bool = True,
    strict_optional: bool = False,
) -> bool:
    """Boolescher Health-Check."""
    try:
        return bool(
            get_read_models_health(
                include_optional=include_optional,
                strict_optional=strict_optional,
            ).get("healthy")
        )
    except Exception:
        return False


def assert_read_models_ready(
    *,
    include_optional: bool = True,
    strict_optional: bool = False,
) -> None:
    """Wirft RuntimeError, wenn die Read-Models-Schicht nicht bereit ist."""
    health = get_read_models_health(
        include_optional=include_optional,
        strict_optional=strict_optional,
    )

    if health.get("healthy"):
        return

    raise RuntimeError(
        f"library read models are not ready: errors={health.get('errors')}"
    )


# ---------------------------------------------------------------------------
# Lazy re-export API
# ---------------------------------------------------------------------------

def load_read_model_symbol(symbol_name: str) -> Any:
    """Lädt ein bekanntes Read-Model-Symbol aus seinem Zielmodul."""
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
            f"could not import read model module {module_name!r}: {status.error}"
        )

    try:
        value = getattr(module, real_symbol_name)
    except AttributeError as exc:
        raise AttributeError(
            f"read model symbol {real_symbol_name!r} not found in module {module.__name__!r}"
        ) from exc

    globals()[symbol_name] = value

    return value


def preload_read_model_symbols(
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

        if not include_optional and module_name in OPTIONAL_READ_MODEL_MODULES:
            continue

        try:
            value = load_read_model_symbol(symbol_name)
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
    """Lazy-Reexport bekannter Read-Model-Symbole und Submodule."""
    if name in SYMBOL_TO_MODULE or name in SYMBOL_ALIASES:
        return load_read_model_symbol(name)

    if name in READ_MODEL_MODULES:
        module, status = safe_import_module(name)
        if module is None:
            raise ImportError(
                f"could not import read model module {name!r}: {status.error}"
            )
        globals()[name] = module
        return module

    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")


def __dir__() -> list[str]:
    """Ergänzt Lazy-Reexport-Symbole in `dir(library.read_models)`."""
    names = set(globals().keys())
    names.update(SYMBOL_TO_MODULE.keys())
    names.update(SYMBOL_ALIASES.keys())
    names.update(READ_MODEL_MODULES)
    return sorted(names)


# ---------------------------------------------------------------------------
# Module access helpers
# ---------------------------------------------------------------------------

def get_read_model_module(module_name: str) -> ModuleType | None:
    """Gibt ein Read-Model-Submodul zurück, falls es importierbar ist."""
    if module_name not in READ_MODEL_MODULES:
        return None

    module, _ = safe_import_module(module_name)
    return module


def get_block_summary_builder_module() -> ModuleType | None:
    return get_read_model_module("block_summary_builder")


def get_block_detail_builder_module() -> ModuleType | None:
    return get_read_model_module("block_detail_builder")


def get_library_index_builder_module() -> ModuleType | None:
    return get_read_model_module("library_index_builder")


def get_db_block_summary_builder_module() -> ModuleType | None:
    return get_read_model_module("db_block_summary_builder")


def get_db_block_detail_builder_module() -> ModuleType | None:
    return get_read_model_module("db_block_detail_builder")


def get_db_library_tree_builder_module() -> ModuleType | None:
    return get_read_model_module("db_library_tree_builder")


def get_db_inventory_builder_module() -> ModuleType | None:
    return get_read_model_module("db_inventory_builder")


# ---------------------------------------------------------------------------
# Existing filesystem convenience helpers
# ---------------------------------------------------------------------------

def build_index_from_pipeline(
    *,
    read_results: Iterable[Any],
    validation_results: Iterable[Any] | None = None,
    fingerprint_results: Iterable[Any] | None = None,
    source_root: Any = None,
    options: Any = None,
) -> Any:
    """Convenience-Wrapper für Service-Schichten."""
    build_library_index_from_pipeline = load_read_model_symbol("build_library_index_from_pipeline")

    return build_library_index_from_pipeline(
        read_results=read_results,
        validation_results=validation_results,
        fingerprint_results=fingerprint_results,
        source_root=source_root,
        options=options,
    )


def build_index_from_items(
    items: Iterable[Any],
    *,
    source_root: Any = None,
    options: Any = None,
) -> Any:
    """Convenience-Wrapper für direkten Indexbau aus Items."""
    build_library_index_from_items = load_read_model_symbol("build_library_index_from_items")

    return build_library_index_from_items(
        items,
        source_root=source_root,
        options=options,
    )


def build_blocks_response(
    index: Any,
    *,
    domain: Any = None,
    category: Any = None,
    subcategory: Any = None,
    object_kind: Any = None,
    q: Any = None,
) -> dict[str, Any]:
    """Convenience-Wrapper für dateibasierte Blocklisten-Antworten."""
    build_blocks_response_from_index = load_read_model_symbol("build_blocks_response_from_index")

    return build_blocks_response_from_index(
        index,
        domain=domain,
        category=category,
        subcategory=subcategory,
        object_kind=object_kind,
        q=q,
    )


def build_tree_response(index: Any) -> dict[str, Any]:
    """Convenience-Wrapper für dateibasierte Tree-Antworten."""
    build_tree_response_from_index = load_read_model_symbol("build_tree_response_from_index")

    return build_tree_response_from_index(index)


def build_detail_response_by_id(
    block_id: Any,
    *,
    read_results: Iterable[Any],
    validation_results: Iterable[Any] | None = None,
    fingerprint_results: Iterable[Any] | None = None,
    items: Iterable[Any] | None = None,
    options: Any = None,
) -> dict[str, Any]:
    """Convenience-Wrapper für dateibasierte Detailantworten nach ID."""
    build_block_detail_response_by_id = load_read_model_symbol("build_block_detail_response_by_id")

    return build_block_detail_response_by_id(
        block_id,
        read_results=read_results,
        validation_results=validation_results,
        fingerprint_results=fingerprint_results,
        items=items,
        options=options,
    )


def build_variants_response_by_parts(
    *,
    read_result: Any = None,
    documents: Mapping[str, Any] | None = None,
    block_id: Any = None,
) -> dict[str, Any]:
    """Convenience-Wrapper für dateibasierte Variantenantworten."""
    build_block_variants_response_from_parts = load_read_model_symbol("build_block_variants_response_from_parts")

    return build_block_variants_response_from_parts(
        read_result=read_result,
        documents=documents,
        block_id=block_id,
    )


def build_summary_items_from_pipeline(
    *,
    read_results: Iterable[Any],
    validation_results: Iterable[Any] | None = None,
    fingerprint_results: Iterable[Any] | None = None,
    options: Any = None,
) -> list[Any]:
    """Convenience-Wrapper für Summary-Item-Erzeugung."""
    build_library_items_from_results = load_read_model_symbol("build_library_items_from_results")

    return build_library_items_from_results(
        read_results=read_results,
        validation_results=validation_results,
        fingerprint_results=fingerprint_results,
        options=options,
    )


def get_taxonomy_lookup_safe(*, force_reload: bool = False) -> dict[str, dict[str, Any]]:
    """Convenience-Wrapper für Taxonomie-Lookup aus Summary Builder."""
    get_taxonomy_lookup = load_read_model_symbol("get_taxonomy_lookup")

    return get_taxonomy_lookup(force_reload=force_reload)


def get_taxonomy_payload_safe(*, include_inactive: bool = False, force_reload: bool = False) -> dict[str, Any]:
    """Convenience-Wrapper für Taxonomie-Payload aus Index Builder."""
    get_taxonomy_payload = load_read_model_symbol("get_taxonomy_payload")

    return get_taxonomy_payload(
        include_inactive=include_inactive,
        force_reload=force_reload,
    )


# ---------------------------------------------------------------------------
# DB convenience helpers
# ---------------------------------------------------------------------------

def build_db_blocks_response_from_rows(
    rows: Iterable[Any],
    *,
    options: Any = None,
    filters: Mapping[str, Any] | None = None,
    metadata: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    """Convenience-Wrapper für DB-Blocks-Response aus Repository-Rows."""
    builder = load_read_model_symbol("build_blocks_response_from_db_rows")

    return builder(
        rows,
        options=options,
        filters=filters,
        metadata=metadata,
    )


def build_db_blocks_response_from_summaries(
    summaries: Iterable[Any],
    *,
    options: Any = None,
    filters: Mapping[str, Any] | None = None,
    metadata: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    """Convenience-Wrapper für DB-Blocks-Response aus PublishedFamilySummary."""
    builder = load_read_model_symbol("build_blocks_response_from_summaries")

    return builder(
        summaries,
        options=options,
        filters=filters,
        metadata=metadata,
    )


def build_db_block_detail_response(
    payload: Any,
    *,
    options: Any = None,
    identifier: Any = None,
) -> dict[str, Any]:
    """Convenience-Wrapper für DB-Detailresponse aus Repository-Payload."""
    builder = load_read_model_symbol("build_detail_response_from_db_payload")

    return builder(
        payload,
        options=options,
        identifier=identifier,
    )


def build_db_block_variants_response(
    payload: Any,
    *,
    options: Any = None,
    identifier: Any = None,
) -> dict[str, Any]:
    """Convenience-Wrapper für DB-Variantenresponse."""
    builder = load_read_model_symbol("build_variants_response_from_db_payload")

    return builder(
        payload,
        options=options,
        identifier=identifier,
    )


def build_db_tree_response_from_rows(
    rows: Iterable[Any],
    *,
    options: Any = None,
    filters: Mapping[str, Any] | None = None,
    metadata: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    """Convenience-Wrapper für DB-Tree-Response aus Repository-Rows."""
    builder = load_read_model_symbol("build_tree_response_from_db_rows")

    return builder(
        rows,
        options=options,
        filters=filters,
        metadata=metadata,
    )


def build_db_tree_response_from_summaries(
    summaries: Iterable[Any],
    *,
    options: Any = None,
    filters: Mapping[str, Any] | None = None,
    metadata: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    """Convenience-Wrapper für DB-Tree-Response aus PublishedFamilySummary."""
    builder = load_read_model_symbol("build_tree_response_from_summaries")

    return builder(
        summaries,
        options=options,
        filters=filters,
        metadata=metadata,
    )


def build_db_inventory_response_from_bundle(
    bundle: Any,
    *,
    options: Any = None,
    filters: Mapping[str, Any] | None = None,
    metadata: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    """Convenience-Wrapper für DB-Inventory-Response aus SourceBundle."""
    builder = load_read_model_symbol("build_inventory_response_from_bundle")

    return builder(
        bundle,
        options=options,
        filters=filters,
        metadata=metadata,
    )


def build_db_inventory_response_from_sources(
    *,
    db_slots: Iterable[Any] | None = None,
    published_families: Iterable[Any] | None = None,
    variants_by_family: Mapping[str, list[Any]] | None = None,
    assets_by_family: Mapping[str, list[Any]] | None = None,
    options: Any = None,
    filters: Mapping[str, Any] | None = None,
    metadata: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    """Convenience-Wrapper für DB-Inventory-Response aus getrennten Quellen."""
    builder = load_read_model_symbol("build_inventory_response_from_sources")

    return builder(
        db_slots=db_slots,
        published_families=published_families,
        variants_by_family=variants_by_family,
        assets_by_family=assets_by_family,
        options=options,
        filters=filters,
        metadata=metadata,
    )


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

__all__: Final[tuple[str, ...]] = (
    "READ_MODELS_PACKAGE_VERSION",
    "READ_MODELS_PACKAGE_NAME",
    "READ_MODELS_COMPONENT_NAME",
    "READ_MODEL_MODULES",
    "REQUIRED_READ_MODEL_MODULES",
    "OPTIONAL_READ_MODEL_MODULES",
    "DB_READ_MODEL_MODULES",
    "SYMBOL_TO_MODULE",
    "SYMBOL_ALIASES",

    "ReadModelModuleStatus",
    "ReadModelsHealth",

    "utc_now_iso",
    "exception_to_dict",
    "json_safe",
    "dataclass_to_dict_safe",
    "safe_tuple",
    "build_module_import_path",

    "clear_read_model_import_cache",
    "clear_read_model_runtime_caches",
    "clear_read_models_caches",
    "clear_read_models_cache",

    "safe_import_module",
    "get_read_model_module_status",
    "get_read_model_subhealth",
    "get_read_models_health",
    "is_read_models_healthy",
    "assert_read_models_ready",

    "load_read_model_symbol",
    "preload_read_model_symbols",

    "get_read_model_module",
    "get_block_summary_builder_module",
    "get_block_detail_builder_module",
    "get_library_index_builder_module",
    "get_db_block_summary_builder_module",
    "get_db_block_detail_builder_module",
    "get_db_library_tree_builder_module",
    "get_db_inventory_builder_module",

    # Existing filesystem convenience helpers
    "build_index_from_pipeline",
    "build_index_from_items",
    "build_blocks_response",
    "build_tree_response",
    "build_detail_response_by_id",
    "build_variants_response_by_parts",
    "build_summary_items_from_pipeline",
    "get_taxonomy_lookup_safe",
    "get_taxonomy_payload_safe",

    # DB convenience helpers
    "build_db_blocks_response_from_rows",
    "build_db_blocks_response_from_summaries",
    "build_db_block_detail_response",
    "build_db_block_variants_response",
    "build_db_tree_response_from_rows",
    "build_db_tree_response_from_summaries",
    "build_db_inventory_response_from_bundle",
    "build_db_inventory_response_from_sources",

    # Reexported read-model symbols
    *tuple(SYMBOL_TO_MODULE.keys()),
    *tuple(SYMBOL_ALIASES.keys()),
)