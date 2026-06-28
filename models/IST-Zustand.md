<!-- services/vectoplan-library/models/IST-Zustand.md -->

# IST-Zustand – `services/vectoplan-library/models`

Stand: **2026-06-28**  
Arbeitskontext: `services/vectoplan-library`  
Scope: ausschließlich der Ordner `models/` plus direkte Außenkanten zu `extensions.py`, `app.py`, Flask-Migrate/Alembic, Repositories, Services und API-Routen.

---

## 0. Kurzstatus

Der Ordner `models/` ist die zentrale SQLAlchemy-Schema-Schicht des `vectoplan-library`-Service. Er enthält keine Business-Logik, keine Routen, keine Scanner, keine Repository-Queries und keine Migrationen. Er deklariert ausschließlich Tabellen, Beziehungen, Normalisierungshelfer, `to_dict()`-Serialisierung und Diagnose-/Importfunktionen.

Aktueller Modellumfang:

- **7 fachliche Model-Module** plus zentrale Registry `models/__init__.py`
- **39 SQLAlchemy-Modelklassen**
- **39 deklarierte Tabellen**
- **42 Enum-Klassen**
- Published Creative Library, Drafts, User Collections, User Hotbar, Definitions, Taxonomy und Files sind getrennte Model-Module.
- `models.import_all_models()` ist der zentrale Alembic-/App-Startup-Einstieg.
- Die Datenbank erzeugt keine fachliche `vplib_uid`; sie übernimmt sie aus Manifest/Create/Package-Flows.

Aktueller Containerstatus aus den letzten Tests:

- App startet mit `models=True` und sichtbaren SQLAlchemy-Tabellen.
- Initialmigration wurde erzeugt und erfolgreich angewendet.
- Prestart meldet zentrale Model- und Service-Imports als OK.
- Health-/Scan-/Definition-/File-/Taxonomy-/Creative-/Draft-Routen antworten mit HTTP 200.

---

## 1. Zweck des Ordners `models/`

`models/` beschreibt den persistenten Datenvertrag des Library-Service. Alles, was langfristig in PostgreSQL gespeichert werden soll, hat hier eine SQLAlchemy-Repräsentation.

Nicht in `models/` enthalten:

- keine Scanner-Ausführung
- keine File-System-Schreiblogik
- keine Seed-Ausführung
- keine HTTP-Route
- keine Repository-Query-Orchestrierung
- keine Service-Validierung
- kein `db.create_all()`
- keine Alembic-Migrationsdateien

Enthalten:

- Tabellenstruktur
- Foreign Keys
- Unique Constraints
- Indexe
- Check Constraints
- Beziehungen für ORM-Loads
- Enum-Werte für Status/Typen/Actions
- sichere Payload-/JSON-Normalisierung
- Factory-Methoden wie `create_from_payload(...)`
- `to_dict()` für API-nahe Serialisierung
- Import-/Health-Funktionen für Alembic und Prestart

---

## 2. Ordnerstruktur

```text
services/vectoplan-library/models/
├── __init__.py
├── creative_library.py
├── creative_library_drafts.py
├── creative_library_user.py
├── user_inventory.py
├── library_definitions.py
├── library_taxonomy.py
└── library_files.py
```

### 2.1 Modulrollen

| Datei | Rolle | Modelle | Enums |
|---|---|---|---|
| `__init__.py` | Zentrale Model-Registry, Lazy-Exports, Alembic-Importpunkt, Health-/Diagnose-Fassade. | 0 | 0 |
| `creative_library.py` | Published Creative Library: veröffentlichte Families/Items, Revisions, Variants, Assets, Documents, ScanRuns, Issues und Default-Inventory-Slots. | 8 | 5 |
| `creative_library_drafts.py` | Draft-/Generator-Zwischenschicht für neue oder bestehende VPLIB-Packages vor Veröffentlichung. | 6 | 9 |
| `creative_library_user.py` | User-spezifische Sicht auf die Creative Library: Collections, CollectionItems, Overrides und User-Audit. | 4 | 6 |
| `user_inventory.py` | Persistierter Editor-/Hotbar-Zustand pro User: State, 9 Slots und Audit. | 3 | 5 |
| `library_definitions.py` | DB-seitiger Definitionskatalog für Variablen, Einheiten, Materialien, Dokumenttypen, ObjectKinds und Profile. | 11 | 5 |
| `library_taxonomy.py` | DB-seitige Taxonomie für Domains/Reiter, Kategorien, Subkategorien, User-Nodes, Overrides und Audit. | 3 | 5 |
| `library_files.py` | Generische Datei-/Upload-Metadaten, Versionen, Kontext-Links und Audit. | 4 | 7 |

---

## 3. Architekturregeln

### 3.1 Model-Schicht ist deklarativ

Die Dateien in `models/` definieren das Schema. Sie führen keine migrationsrelevanten Aktionen selbst aus. Tabellen entstehen nur über Flask-Migrate/Alembic.

Erlaubt:

- `db.Model`-Klassen
- `db.Column(...)`
- `db.ForeignKey(...)`
- `db.relationship(...)`
- `__table_args__` mit Constraints und Indexen
- reine Normalisierungsfunktionen
- objektinterne Statusmethoden wie `mark_deleted()`

Nicht erlaubt:

- direkte DB-Abfragen
- `db.session.query(...)`
- Scanner-/Filesystem-Operationen
- Flask-Request-/Response-Logik
- `db.create_all()`
- automatische Daten-Seeds

### 3.2 App-Startup und Alembic

Die zentrale Kette ist:

```text
wsgi:app
  ↓
app.create_app()
  ↓
extensions.db.init_app(app)
  ↓
models.import_all_models()
  ↓
alle Modelmodule werden importiert
  ↓
SQLAlchemy db.metadata.tables enthält alle Tabellen
  ↓
flask db migrate / flask db upgrade
```

### 3.3 ID-Regeln

- `id` ist immer technische DB-Primary-Key-Identität.
- `*_uid` ist meist eine technische stabile UUID innerhalb einer Tabelle.
- `vplib_uid` ist die stabile technische Package-ID des VPLIB-Pakets.
- `family_id`, `package_id`, `variant_id` sind semantische IDs.
- `revision_hash` ist der Inhaltsfingerprint und entscheidet, ob eine neue Revision entsteht.
- `owner_scope` ist eine nicht-nullbare Eindeutigkeitsstütze, weil PostgreSQL `NULL` in Unique Constraints nicht als gleich behandelt.
- Phase 1 nutzt `user_id=1` als Default, ohne eine User-Tabelle vorauszusetzen.

### 3.4 Published, Draft, User und Runtime sind getrennt

```text
creative_library.py
  published canonical state

creative_library_drafts.py
  generator/create/edit working state

creative_library_user.py
  user-specific library view: collections and overrides

user_inventory.py
  editor/runtime hotbar state for one user

library_definitions.py
  reusable definition catalog

library_taxonomy.py
  taxonomy tree and user taxonomy overrides

library_files.py
  generic file metadata and file-context links
```

---

## 4. Tabellenmatrix

| Modul | Modelklasse | Tabelle | Spalten | FKs | Relationships |
|---|---|---|---|---|---|
| `creative_library.py` | `CreativeLibraryItem` | `creative_library_items` | 60 | 1 | 6 |
| `creative_library.py` | `CreativeLibraryScanRun` | `creative_library_scan_runs` | 31 | 0 | 2 |
| `creative_library.py` | `CreativeLibraryRevision` | `creative_library_revisions` | 45 | 4 | 6 |
| `creative_library.py` | `CreativeLibraryVariant` | `creative_library_variants` | 37 | 4 | 5 |
| `creative_library.py` | `CreativeLibraryAsset` | `creative_library_assets` | 35 | 6 | 6 |
| `creative_library.py` | `CreativeLibraryDocument` | `creative_library_documents` | 23 | 6 | 6 |
| `creative_library.py` | `CreativeLibraryScanIssue` | `creative_library_scan_issues` | 25 | 3 | 3 |
| `creative_library.py` | `CreativeLibraryInventorySlot` | `creative_library_inventory_slots` | 45 | 2 | 2 |
| `creative_library_drafts.py` | `CreativeLibraryDraft` | `creative_library_drafts` | 54 | 3 | 8 |
| `creative_library_drafts.py` | `CreativeLibraryDraftVariant` | `creative_library_draft_variants` | 28 | 2 | 4 |
| `creative_library_drafts.py` | `CreativeLibraryDraftAsset` | `creative_library_draft_assets` | 32 | 4 | 4 |
| `creative_library_drafts.py` | `CreativeLibraryDraftDocument` | `creative_library_draft_documents` | 24 | 2 | 2 |
| `creative_library_drafts.py` | `CreativeLibraryDraftValidationIssue` | `creative_library_draft_validation_issues` | 18 | 2 | 2 |
| `creative_library_drafts.py` | `CreativeLibraryDraftAuditEvent` | `creative_library_draft_audit_events` | 14 | 1 | 1 |
| `creative_library_user.py` | `CreativeLibraryCollection` | `creative_library_collections` | 30 | 0 | 1 |
| `creative_library_user.py` | `CreativeLibraryCollectionItem` | `creative_library_collection_items` | 45 | 3 | 3 |
| `creative_library_user.py` | `CreativeLibraryUserOverride` | `creative_library_user_overrides` | 36 | 4 | 4 |
| `creative_library_user.py` | `CreativeLibraryUserAuditEvent` | `creative_library_user_audit_events` | 25 | 5 | 5 |
| `user_inventory.py` | `UserInventoryState` | `user_inventory_states` | 41 | 5 | 6 |
| `user_inventory.py` | `UserInventorySlot` | `user_inventory_slots` | 55 | 6 | 6 |
| `user_inventory.py` | `UserInventoryAuditEvent` | `user_inventory_audit_events` | 28 | 2 | 2 |
| `library_definitions.py` | `LibraryDefinitionDataset` | `library_definition_datasets` | 17 | 0 | 0 |
| `library_definitions.py` | `LibraryDefinitionSeedRun` | `library_definition_seed_runs` | 25 | 0 | 0 |
| `library_definitions.py` | `LibraryDefinitionVariable` | `library_definition_variables` | 15 | 1 | 1 |
| `library_definitions.py` | `LibraryDefinitionUnit` | `library_definition_units` | 7 | 1 | 1 |
| `library_definitions.py` | `LibraryDefinitionMaterial` | `library_definition_materials` | 9 | 1 | 1 |
| `library_definitions.py` | `LibraryDefinitionDocumentType` | `library_definition_document_types` | 12 | 1 | 1 |
| `library_definitions.py` | `LibraryDefinitionObjectKind` | `library_definition_object_kinds` | 9 | 1 | 1 |
| `library_definitions.py` | `LibraryDefinitionFamilyProfile` | `library_definition_family_profiles` | 13 | 1 | 1 |
| `library_definitions.py` | `LibraryDefinitionVariantProfile` | `library_definition_variant_profiles` | 15 | 1 | 1 |
| `library_definitions.py` | `LibraryDefinitionProfileBinding` | `library_definition_profile_bindings` | 15 | 1 | 1 |
| `library_definitions.py` | `LibraryDefinitionOverride` | `library_definition_overrides` | 25 | 0 | 0 |
| `library_taxonomy.py` | `LibraryTaxonomyNode` | `library_taxonomy_nodes` | 41 | 1 | 3 |
| `library_taxonomy.py` | `LibraryTaxonomyOverride` | `library_taxonomy_overrides` | 31 | 1 | 1 |
| `library_taxonomy.py` | `LibraryTaxonomyAuditEvent` | `library_taxonomy_audit_events` | 17 | 2 | 2 |
| `library_files.py` | `LibraryFile` | `library_files` | 33 | 1 | 3 |
| `library_files.py` | `LibraryFileVersion` | `library_file_versions` | 21 | 1 | 2 |
| `library_files.py` | `LibraryFileLink` | `library_file_links` | 32 | 2 | 2 |
| `library_files.py` | `LibraryFileAuditEvent` | `library_file_audit_events` | 22 | 3 | 3 |

---

## 5. Zentrale Import-Registry: `models/__init__.py`

`models/__init__.py` ist kein fachliches Datenmodell, sondern die Registry und Fassade für alle Modelmodule.

Aufgaben:

- kennt alle kanonischen Modelmodule
- kennt Komfort-Aliase für Modulgruppen
- mappt öffentliche Symbole auf ihr Modul
- lädt Modelmodule lazy über `__getattr__`
- lädt alle Module explizit für App-Startup und Alembic
- liefert Model-/Table-/Health-Snapshots
- prüft über `assert_models_ready()` harte Importbereitschaft

Kanonische Module:

- `creative_library`
- `library_definitions`
- `library_files`
- `library_taxonomy`
- `creative_library_user`
- `creative_library_drafts`
- `user_inventory`

Wichtige Funktionen:

- `load_model_module()`
- `load_all_model_modules()`
- `import_all_models()`
- `iter_model_classes()`
- `get_model_class_names()`
- `get_model_table_names()`
- `get_model_module_statuses()`
- `get_models_metadata_snapshot()`
- `get_models_health()`
- `assert_models_ready()`

Wichtig: Alembic sieht neue Tabellen nur, wenn das jeweilige Model-Modul in dieser Registry steht und `import_all_models()` durch App-Startup/Migration ausgeführt wird.

---

## 6. Datei: `creative_library.py` – Published Creative Library

Diese Datei enthält den veröffentlichten, produktiven Creative-Library-State. Sie ist der Kern des DB-backed Published-Pfads.

Hauptdatenfluss:

```text
src/library/source/*
  ↓ scan/validation/fingerprint
library_db_sync_service
  ↓
creative_library.py Tabellen
  ↓
creative_library_service / published reads
  ↓
/api/v1/vplib/library/items, /published, /blocks, /tree
```

### 6.1 `CreativeLibraryItem` → `creative_library_items`

Kanonisches veröffentlichtes Creative-Library-Item; fachlich eine Family.

- **identity**: `vplib_uid`, `family_slug`, `slug`, `label`, `name`, `package_root`, `source_hash`, `current_revision_hash`, `latest_revision_hash`, `published_revision_hash`, `revision_hash`
- **ownership**: `source_scope`, `owner_scope`
- **classification**: `domain`, `category`, `subcategory`, `classification_path`, `taxonomy_path`, `object_kind`
- **lifecycle**: `status`, `publication_status`, `enabled`, `visible`, `is_deleted`, `locked`, `published_at`, `deleted_at`
- **counts**: `variant_count`, `asset_count`, `document_count`, `revision_count`
- **timestamps**: `first_seen_at`, `last_seen_at`, `scanned_at`, `last_edited_at`, `last_generated_at`
- **payloads**: `generator_editable`, `summary_payload`, `payload`, `generator_payload`, `definition_payload`, `file_refs_json`, `meta`, `metadata_json`
- **foreign_keys**: `id`, `owner_user_id`, `created_by_user_id`, `updated_by_user_id`, `package_id`, `family_id`, `family_profile_id`, `variant_profile_id`, `current_revision_id`, `default_variant_id`
- **other**: `description`, `definition_version`, `source_root`, `source_path`, `editable`, `system_required`
- **Foreign Keys**:
  - `current_revision_id` → `creative_library_revisions.id`; `use_alter=True`
- **Relationships**: `revisions`, `current_revision`, `variants`, `assets`, `documents`, `inventory_slots`
- **Indexe**: 7
- **wichtige Methoden**: `create_from_manifest`, `update_from_manifest`, `mark_seen`, `mark_invalid`, `mark_deleted`, `set_current_revision`, `mark_generator_updated`, `to_dict`

### 6.2 `CreativeLibraryScanRun` → `creative_library_scan_runs`

Protokoll eines Scan-/Sync-/Publication-Laufs.

- **identity**: `scan_uid`
- **ownership**: `source_scope`, `owner_scope`
- **lifecycle**: `mode`, `status`, `valid_count`, `invalid_count`, `published_count`, `deleted_count`
- **counts**: `total_count`, `scanned_count`, `created_count`, `inserted_count`, `updated_count`, `unchanged_count`, `skipped_count`, `duplicate_count`, `warning_count`, `error_count`
- **timestamps**: `started_at`, `finished_at`
- **payloads**: `summary_json`, `details`, `payload`, `meta`, `metadata_json`
- **foreign_keys**: `id`, `owner_user_id`
- **other**: `source_root`, `triggered_by`, `duration_ms`
- **Relationships**: `revisions`, `issues`
- **Indexe**: 3
- **wichtige Methoden**: `start`, `finish`, `apply_counts`, `to_dict`

### 6.3 `CreativeLibraryRevision` → `creative_library_revisions`

Versionierter veröffentlichter Inhaltsstand einer Family.

- **identity**: `source_draft_uid`, `vplib_uid`, `revision_hash`, `previous_revision_hash`, `package_version`, `resolved_package_json`
- **ownership**: `source_scope`, `owner_scope`
- **classification**: `classification_json`
- **lifecycle**: `validation_status`, `status`, `publication_status`, `published_at`, `validation_payload`
- **payloads**: `manifest_json`, `modules_json`, `identity_json`, `document_paths_json`, `summary_payload`, `detail_payload`, `raw_documents`, `documents`, `generator_payload`, `file_refs_json`, `payload`, `meta`, `metadata_json`
- **foreign_keys**: `id`, `family_db_id`, `item_id`, `scan_run_id`, `scan_run_db_id`, `source_draft_id`, `owner_user_id`, `family_id`, `package_id`, `revision_id`, `created_by_user_id`, `published_by_user_id`
- **other**: `schema_version`, `definitions_version`, `source_root`, `source_path`, `source_mtime_ns`, `source_size_bytes`
- **Foreign Keys**:
  - `family_db_id` → `creative_library_items.id`
  - `item_id` → `creative_library_items.id`
  - `scan_run_id` → `creative_library_scan_runs.id`
  - `source_draft_id` → `creative_library_drafts.id`; `use_alter=True`
- **Relationships**: `family`, `item`, `scan_run`, `variants`, `assets`, `document_rows`
- **Unique Constraints**: 1
- **Indexe**: 5
- **wichtige Methoden**: `create_from_documents`, `to_dict`

### 6.4 `CreativeLibraryVariant` → `creative_library_variants`

Veröffentlichte Varianten einer Revision/Family.

- **identity**: `source_draft_variant_uid`, `vplib_uid`, `revision_hash`, `id_in_family`, `slug`, `label`, `name`, `additional_field_keys_json`
- **lifecycle**: `enabled`, `visible`, `validation_payload`, `status`, `publication_status`
- **counts**: `sort_order`
- **payloads**: `definition_values_json`, `summary_json`, `resolved_payload`, `generator_payload`, `file_refs_json`, `payload`, `meta`, `metadata_json`
- **foreign_keys**: `id`, `family_db_id`, `item_id`, `revision_id`, `revision_db_id`, `source_draft_variant_id`, `family_id`, `package_id`, `variant_id`, `family_profile_id`, `variant_profile_id`, `created_by_user_id`, `updated_by_user_id`
- **other**: `description`, `is_default`
- **Foreign Keys**:
  - `family_db_id` → `creative_library_items.id`
  - `item_id` → `creative_library_items.id`
  - `revision_id` → `creative_library_revisions.id`
  - `source_draft_variant_id` → `creative_library_draft_variants.id`; `use_alter=True`
- **Relationships**: `family`, `item`, `revision`, `assets`, `documents`
- **Unique Constraints**: 1
- **Indexe**: 4
- **wichtige Methoden**: `create_from_payload`, `to_dict`

### 6.5 `CreativeLibraryAsset` → `creative_library_assets`

Veröffentlichte Asset-Referenzen, optional mit LibraryFile-Verknüpfung.

- **identity**: `vplib_uid`, `revision_hash`, `field_key`, `label`, `asset_hash`
- **classification**: `asset_kind`, `document_type`
- **counts**: `sort_order`
- **payloads**: `bounds_json`, `transform_json`, `payload`, `meta`, `metadata_json`
- **foreign_keys**: `id`, `family_db_id`, `item_id`, `revision_id`, `revision_db_id`, `variant_db_id`, `variant_id`, `library_file_id`, `library_file_version_id`, `family_id`, `package_id`
- **other**: `role`, `asset_type`, `asset_path`, `path`, `relative_path`, `uri`, `checksum`, `mime_type`, `size_bytes`, `exists`, `is_primary`
- **Foreign Keys**:
  - `family_db_id` → `creative_library_items.id`
  - `item_id` → `creative_library_items.id`
  - `revision_id` → `creative_library_revisions.id`
  - `variant_db_id` → `creative_library_variants.id`
  - `library_file_id` → `library_files.id`
  - `library_file_version_id` → `library_file_versions.id`
- **Relationships**: `family`, `item`, `revision`, `variant`, `library_file`, `library_file_version`
- **Indexe**: 5
- **wichtige Methoden**: `create_from_payload`, `to_dict`

### 6.6 `CreativeLibraryDocument` → `creative_library_documents`

Veröffentlichte Dokument-/JSON-Dateien und Module einer Revision.

- **identity**: `vplib_uid`, `revision_hash`, `field_key`
- **classification**: `document_type`
- **payloads**: `payload`, `meta`, `metadata_json`
- **foreign_keys**: `id`, `family_db_id`, `item_id`, `revision_id`, `revision_db_id`, `variant_db_id`, `variant_id`, `library_file_id`, `library_file_version_id`, `family_id`, `package_id`
- **other**: `relative_path`, `path`, `module`, `checksum`, `document`
- **Foreign Keys**:
  - `family_db_id` → `creative_library_items.id`
  - `item_id` → `creative_library_items.id`
  - `revision_id` → `creative_library_revisions.id`
  - `variant_db_id` → `creative_library_variants.id`
  - `library_file_id` → `library_files.id`
  - `library_file_version_id` → `library_file_versions.id`
- **Relationships**: `family`, `item`, `revision`, `variant`, `library_file`, `library_file_version`
- **Unique Constraints**: 1
- **Indexe**: 4
- **wichtige Methoden**: `create_from_payload`, `to_dict`

### 6.7 `CreativeLibraryScanIssue` → `creative_library_scan_issues`

Scan-/Sync-/Validation-Issues pro Lauf/Family/Revision.

- **identity**: `vplib_uid`, `revision_hash`
- **ownership**: `scope`
- **lifecycle**: `active`
- **payloads**: `context_json`, `payload`, `meta`, `metadata_json`
- **foreign_keys**: `id`, `scan_run_id`, `scan_run_db_id`, `family_db_id`, `revision_id`, `revision_db_id`, `package_id`, `family_id`
- **other**: `severity`, `level`, `code`, `message`, `path`, `field`, `source_path`, `relative_path`, `resolved`
- **Foreign Keys**:
  - `scan_run_id` → `creative_library_scan_runs.id`
  - `family_db_id` → `creative_library_items.id`
  - `revision_id` → `creative_library_revisions.id`
- **Relationships**: `scan_run`, `family`, `revision`
- **Indexe**: 3
- **wichtige Methoden**: `from_issue_payload`, `mark_resolved`, `to_dict`

### 6.8 `CreativeLibraryInventorySlot` → `creative_library_inventory_slots`

System-/Library-Default-Slot-Snapshot, nicht User-Hotbar.

- **identity**: `inventory_key`, `vplib_uid`, `label`, `family_slug`, `revision_hash`
- **ownership**: `source_scope`, `owner_scope`, `scope`
- **classification**: `object_kind`, `domain`, `category`, `subcategory`, `taxonomy_path`
- **lifecycle**: `status`, `mode`, `enabled`, `visible`, `active`, `locked`, `pinned`, `selected`, `publication_status`, `validation_status`, `selected_at`, `published_at`
- **counts**: `slot_index`, `sort_order`
- **payloads**: `assets`, `variant`, `placement`, `payload`, `meta`, `metadata_json`
- **foreign_keys**: `id`, `slot_id`, `owner_user_id`, `family_db_id`, `item_id`, `family_id`, `package_id`, `variant_id`
- **other**: `description`, `source`, `icon`, `preview`
- **Foreign Keys**:
  - `family_db_id` → `creative_library_items.id`
  - `item_id` → `creative_library_items.id`
- **Relationships**: `family`, `item`
- **Unique Constraints**: 1
- **Indexe**: 4
- **wichtige Methoden**: `create_for_item`, `to_dict`

Besonderheiten:

- `CreativeLibraryItem` ist fachlich die Family und besitzt den stabilen Schlüssel `vplib_uid`.
- `CreativeLibraryFamily = CreativeLibraryItem` bleibt als Alias für ältere Repository-/Service-Namen erhalten.
- `CreativeLibraryRevision` speichert den versionierten Inhaltsstand; `vplib_uid + revision_hash` ist eindeutig.
- `current_revision_id` ist ein zyklischer Pointer und deshalb mit `use_alter=True` modelliert.
- `source_draft_id` und `source_draft_variant_id` sind optionale Rückverweise auf Draft-Tabellen und ebenfalls per `use_alter=True` entkoppelt.
- Assets und Documents können optional auf `library_files` / `library_file_versions` zeigen.
- `CreativeLibraryInventorySlot` ist ein Library-/Default-Inventar-Snapshot, nicht der User-Hotbar-State.

---

## 7. Datei: `creative_library_drafts.py` – Draft-/Generator-Zwischenschicht

Diese Datei modelliert Arbeitsstände aus Create UI, Generator, Import oder Bearbeiten bestehender VPLIBs. Drafts sind nicht die veröffentlichte Wahrheit; sie sind vorbereitende, validierbare und verwerfbare Zustände.

Datenfluss:

```text
/api/v1/vplib/create/* oder /api/v1/vplib/library/drafts/*
  ↓
CreativeLibraryDraft
  ↓
DraftVariant / DraftAsset / DraftDocument
  ↓ validate
DraftValidationIssue
  ↓ publish
CreativeLibraryRevision / CreativeLibraryVariant / CreativeLibraryAsset / CreativeLibraryDocument
```

### 7.1 `CreativeLibraryDraft` → `creative_library_drafts`

Haupt-Draft für Create/Edit/Import/Generator-Arbeitsstand.

- **identity**: `draft_uid`, `draft_key`, `vplib_uid`, `family_slug`, `label`, `name`, `family_payload`
- **ownership**: `source_scope`, `owner_scope`
- **classification**: `object_kind`, `domain`, `category`, `subcategory`, `taxonomy_path`, `classification_payload`
- **lifecycle**: `draft_mode`, `status`, `stage`, `active`, `locked`, `validation_payload`, `validated_at`, `published_at`, `deleted_at`
- **counts**: `variant_count`, `asset_count`, `document_count`, `issue_count`, `warning_count`, `error_count`
- **timestamps**: `discarded_at`
- **payloads**: `manifest_payload`, `modules_payload`, `generator_payload`, `publish_payload`, `payload`, `meta`, `metadata_json`
- **foreign_keys**: `id`, `owner_user_id`, `target_item_id`, `base_revision_id`, `published_revision_id`, `package_id`, `family_id`, `family_profile_id`, `variant_profile_id`, `created_by_user_id`, `updated_by_user_id`, `validated_by_user_id`, `published_by_user_id`, `discarded_by_user_id`, `deleted_by_user_id`
- **other**: `description`
- **Foreign Keys**:
  - `target_item_id` → `creative_library_items.id`; `use_alter=True`
  - `base_revision_id` → `creative_library_revisions.id`; `use_alter=True`
  - `published_revision_id` → `creative_library_revisions.id`; `use_alter=True`
- **Relationships**: `target_item`, `base_revision`, `published_revision`, `variants`, `assets`, `documents`, `validation_issues`, `audit_events`
- **Unique Constraints**: 1
- **Indexe**: 5
- **wichtige Methoden**: `create_from_payload`, `refresh_counts`, `mark_valid`, `mark_invalid`, `mark_ready_to_publish`, `mark_published`, `discard`, `mark_deleted`, `to_dict`

### 7.2 `CreativeLibraryDraftVariant` → `creative_library_draft_variants`

Varianten-Arbeitsstände innerhalb eines Drafts.

- **identity**: `draft_variant_uid`, `slug`, `label`, `name`, `additional_field_keys_json`
- **lifecycle**: `active`, `visible`, `status`, `validation_payload`, `deleted_at`
- **counts**: `sort_order`
- **payloads**: `definition_values_json`, `summary_json`, `resolved_payload`, `payload`, `meta`, `metadata_json`
- **foreign_keys**: `id`, `draft_id`, `source_variant_id`, `variant_id`, `family_profile_id`, `variant_profile_id`, `created_by_user_id`, `updated_by_user_id`, `deleted_by_user_id`
- **other**: `description`, `is_default`
- **Foreign Keys**:
  - `draft_id` → `creative_library_drafts.id`
  - `source_variant_id` → `creative_library_variants.id`; `use_alter=True`
- **Relationships**: `draft`, `source_variant`, `assets`, `documents`
- **Unique Constraints**: 1
- **Indexe**: 2
- **wichtige Methoden**: `create_from_payload`, `mark_deleted`, `to_dict`

### 7.3 `CreativeLibraryDraftAsset` → `creative_library_draft_assets`

Asset-Arbeitsstände innerhalb eines Drafts.

- **identity**: `draft_asset_uid`, `field_key`, `label`
- **classification**: `asset_kind`, `document_type`
- **lifecycle**: `status`, `active`, `visible`, `deleted_at`
- **counts**: `sort_order`
- **payloads**: `bounds_json`, `transform_json`, `payload`, `meta`, `metadata_json`
- **foreign_keys**: `id`, `draft_id`, `draft_variant_id`, `library_file_id`, `library_file_version_id`, `created_by_user_id`, `updated_by_user_id`, `deleted_by_user_id`
- **other**: `role`, `description`, `relative_path`, `storage_path`, `uri`, `mime_type`, `size_bytes`, `sha256`, `is_primary`
- **Foreign Keys**:
  - `draft_id` → `creative_library_drafts.id`
  - `draft_variant_id` → `creative_library_draft_variants.id`
  - `library_file_id` → `library_files.id`
  - `library_file_version_id` → `library_file_versions.id`
- **Relationships**: `draft`, `draft_variant`, `library_file`, `library_file_version`
- **Indexe**: 4
- **wichtige Methoden**: `create_from_payload`, `mark_deleted`, `to_dict`

### 7.4 `CreativeLibraryDraftDocument` → `creative_library_draft_documents`

Dokument-Arbeitsstände innerhalb eines Drafts.

- **identity**: `draft_document_uid`
- **classification**: `document_type`
- **lifecycle**: `active`, `visible`, `status`, `deleted_at`
- **counts**: `sort_order`
- **payloads**: `document_json`, `payload`, `meta`, `metadata_json`
- **foreign_keys**: `id`, `draft_id`, `draft_variant_id`, `created_by_user_id`, `updated_by_user_id`, `deleted_by_user_id`
- **other**: `relative_path`, `module`, `document_kind`, `checksum`, `generated`, `dirty`, `required`
- **Foreign Keys**:
  - `draft_id` → `creative_library_drafts.id`
  - `draft_variant_id` → `creative_library_draft_variants.id`
- **Relationships**: `draft`, `draft_variant`
- **Unique Constraints**: 1
- **Indexe**: 3
- **wichtige Methoden**: `create_from_payload`, `update_document`, `mark_clean`, `mark_deleted`, `to_dict`

### 7.5 `CreativeLibraryDraftValidationIssue` → `creative_library_draft_validation_issues`

Validierungsprobleme eines Drafts oder einer Draft-Variante.

- **identity**: `issue_uid`
- **ownership**: `scope`
- **lifecycle**: `active`
- **counts**: `sort_order`
- **payloads**: `context_json`, `payload`, `meta`, `metadata_json`
- **foreign_keys**: `id`, `draft_id`, `draft_variant_id`
- **other**: `severity`, `code`, `message`, `field`, `path`, `relative_path`, `resolved`
- **Foreign Keys**:
  - `draft_id` → `creative_library_drafts.id`
  - `draft_variant_id` → `creative_library_draft_variants.id`
- **Relationships**: `draft`, `draft_variant`
- **Indexe**: 3
- **wichtige Methoden**: `create_from_payload`, `mark_resolved`, `to_dict`

### 7.6 `CreativeLibraryDraftAuditEvent` → `creative_library_draft_audit_events`

Audit-Protokoll für Draft-Aktionen.

- **identity**: `event_uid`, `target_uid`
- **payloads**: `before_json`, `after_json`, `diff_json`, `payload`, `meta`, `metadata_json`
- **foreign_keys**: `id`, `draft_id`, `user_id`, `target_db_id`
- **other**: `event_type`, `target_type`
- **Foreign Keys**:
  - `draft_id` → `creative_library_drafts.id`
- **Relationships**: `draft`
- **Indexe**: 3
- **wichtige Methoden**: `create_event`, `to_dict`

Besonderheiten:

- `target_item_id`, `base_revision_id`, `published_revision_id` zeigen optional auf Published-Tabellen und sind mit `use_alter=True` modelliert.
- `source_variant_id` in `CreativeLibraryDraftVariant` zeigt optional auf Published Variants und ist ebenfalls mit `use_alter=True` modelliert.
- Die Child-FKs `draft_id → creative_library_drafts.id` bleiben normale FKs, damit Alembic die Draft-Child-Tabellen korrekt sortieren kann.
- Drafts dürfen eine `vplib_uid` zwischenspeichern, erzeugen aber nicht eigenmächtig finale VPLIB-IDs.
- Publish-Logik liegt im Service/Repository, nicht im Model.

---

## 8. Datei: `creative_library_user.py` – User-spezifische Creative-Library-Sicht

Diese Datei modelliert, wie ein User die published Creative Library sieht und verändert, ohne die system-owned Published Items direkt umzuschreiben.

Datenfluss:

```text
Published Creative Library
  ↓
System Default Collection
  ↓
User Collections + User Overrides
  ↓
resolved creative inventory for user_id
  ↓
Creative-Inventar / Editor / User-Hotbar
```

### 8.1 `CreativeLibraryCollection` → `creative_library_collections`

System- oder User-Collection für Creative-Library-Items.

- **identity**: `collection_uid`, `collection_key`, `label`, `name`
- **ownership**: `source_scope`, `owner_scope`
- **lifecycle**: `status`, `active`, `visible`, `locked`, `is_favorites`, `deleted_at`
- **counts**: `item_count`, `sort_order`
- **payloads**: `settings`, `payload`, `meta`, `metadata_json`
- **foreign_keys**: `id`, `owner_user_id`, `created_by_user_id`, `updated_by_user_id`, `deleted_by_user_id`
- **other**: `collection_kind`, `description`, `system_required`, `is_default`, `auto_include_system_default`, `icon`, `color`
- **Relationships**: `items`
- **Unique Constraints**: 1
- **Indexe**: 3
- **wichtige Methoden**: `create_from_payload`, `refresh_item_count`, `mark_deleted`, `restore`, `to_dict`

### 8.2 `CreativeLibraryCollectionItem` → `creative_library_collection_items`

Zuordnung/Snapshot eines Creative Items in einer Collection.

- **identity**: `collection_item_uid`, `item_key`, `vplib_uid`, `label`, `name`
- **ownership**: `source_scope`, `owner_scope`
- **classification**: `object_kind`, `domain`, `category`, `subcategory`, `taxonomy_path`
- **lifecycle**: `status`, `active`, `visible`, `locked`, `pinned`, `favorite`, `deleted_at`
- **counts**: `quantity`, `sort_order`
- **timestamps**: `added_at`, `removed_at`
- **payloads**: `assets`, `variant`, `placement`, `payload`, `meta`, `metadata_json`
- **foreign_keys**: `id`, `collection_id`, `item_db_id`, `variant_db_id`, `owner_user_id`, `family_id`, `package_id`, `variant_id`, `created_by_user_id`, `updated_by_user_id`, `deleted_by_user_id`
- **other**: `description`, `is_standard`, `is_user_added`, `icon`, `preview`
- **Foreign Keys**:
  - `collection_id` → `creative_library_collections.id`
  - `item_db_id` → `creative_library_items.id`
  - `variant_db_id` → `creative_library_variants.id`
- **Relationships**: `collection`, `item`, `variant_row`
- **Unique Constraints**: 1
- **Indexe**: 5
- **wichtige Methoden**: `create_from_item_payload`, `mark_deleted`, `hide`, `restore`, `set_favorite`, `set_pinned`, `to_dict`

### 8.3 `CreativeLibraryUserOverride` → `creative_library_user_overrides`

User-Overrides auf Items, Variants, Collections, Taxonomy oder Definitions.

- **identity**: `override_uid`, `target_uid`, `target_key`, `vplib_uid`, `label_override`
- **ownership**: `owner_scope`
- **classification**: `taxonomy_path`
- **lifecycle**: `status`, `active`, `visible_override`, `active_override`, `favorite_override`, `pinned_override`, `deleted_at`
- **payloads**: `payload_patch`, `before_json`, `after_json`, `meta`, `metadata_json`
- **foreign_keys**: `id`, `user_id`, `target_db_id`, `collection_id`, `collection_item_id`, `item_db_id`, `variant_db_id`, `family_id`, `package_id`, `variant_id`, `created_by_user_id`, `updated_by_user_id`, `deleted_by_user_id`
- **other**: `target_type`, `override_action`, `description_override`, `sort_order_override`
- **Foreign Keys**:
  - `collection_id` → `creative_library_collections.id`
  - `collection_item_id` → `creative_library_collection_items.id`
  - `item_db_id` → `creative_library_items.id`
  - `variant_db_id` → `creative_library_variants.id`
- **Relationships**: `collection`, `collection_item`, `item`, `variant_row`
- **Unique Constraints**: 1
- **Indexe**: 4
- **wichtige Methoden**: `create_from_payload`, `mark_deleted`, `restore`, `to_dict`

### 8.4 `CreativeLibraryUserAuditEvent` → `creative_library_user_audit_events`

Audit-Protokoll für User-Library-Aktionen.

- **identity**: `event_uid`, `target_uid`, `target_key`, `vplib_uid`
- **ownership**: `owner_scope`
- **classification**: `taxonomy_path`
- **payloads**: `before_json`, `after_json`, `diff_json`, `payload`, `meta`, `metadata_json`
- **foreign_keys**: `id`, `user_id`, `target_db_id`, `collection_id`, `collection_item_id`, `override_id`, `item_db_id`, `variant_db_id`, `family_id`, `package_id`, `variant_id`
- **other**: `event_type`, `target_type`
- **Foreign Keys**:
  - `collection_id` → `creative_library_collections.id`
  - `collection_item_id` → `creative_library_collection_items.id`
  - `override_id` → `creative_library_user_overrides.id`
  - `item_db_id` → `creative_library_items.id`
  - `variant_db_id` → `creative_library_variants.id`
- **Relationships**: `collection`, `collection_item`, `override`, `item`, `variant_row`
- **Indexe**: 4
- **wichtige Methoden**: `create_event`, `to_dict`

Besonderheiten:

- Systembibliothek bleibt `owner_scope='system'`.
- User-Erweiterungen liegen in `owner_scope='user:<id>'`.
- CollectionItems enthalten Snapshots wichtiger Item-/Variant-/Taxonomie-Felder.
- Overrides beschreiben Aktionen wie hide, restore, rename, reorder, favorite, pin, patch oder delete.
- AuditEvents protokollieren User-Aktionen für spätere Nachvollziehbarkeit.

---

## 9. Datei: `user_inventory.py` – Persistierte User-Hotbar

Diese Datei ist bewusst getrennt von `CreativeLibraryInventorySlot`. Sie beschreibt den tatsächlichen Runtime-/Editor-Zustand eines Users: welcher Slot aktiv ist und was in den 9 Hotbar-Slots liegt.

Datenfluss:

```text
Editor / Viewport
  ↓
User hotbar overlay
  ↓
static/js/inventar/user-inventory.js
  ↓
/api/v1/vplib/inventar_user/*
  ↓
UserInventoryService
  ↓
UserInventoryRepository
  ↓
user_inventory_states + user_inventory_slots
```

### 9.1 `UserInventoryState` → `user_inventory_states`

Persistierter User-Hotbar-Zustand mit aktivem Slot.

- **identity**: `inventory_uid`, `inventory_key`, `last_selected_slot_key`, `active_collection_uid`, `active_collection_key`, `last_selected_collection_uid`, `last_selected_collection_item_uid`, `last_selected_item_key`, `last_selected_vplib_uid`, `last_selected_label`
- **ownership**: `scope`
- **classification**: `last_selected_object_kind`, `last_selected_domain`, `last_selected_category`, `last_selected_subcategory`, `last_selected_taxonomy_path`
- **lifecycle**: `active_slot_index`, `last_selected_slot_index`, `mode`, `status`, `active`, `locked`, `selected_at`, `deleted_at`
- **counts**: `slot_count`
- **timestamps**: `last_loaded_at`, `last_synced_at`
- **payloads**: `payload`, `settings`, `metadata_json`
- **foreign_keys**: `id`, `user_id`, `active_collection_id`, `last_selected_collection_id`, `last_selected_collection_item_id`, `last_selected_item_db_id`, `last_selected_variant_db_id`, `last_selected_family_id`, `last_selected_package_id`, `last_selected_variant_id`
- **other**: `source`
- **Foreign Keys**:
  - `active_collection_id` → `creative_library_collections.id`
  - `last_selected_collection_id` → `creative_library_collections.id`
  - `last_selected_collection_item_id` → `creative_library_collection_items.id`
  - `last_selected_item_db_id` → `creative_library_items.id`
  - `last_selected_variant_db_id` → `creative_library_variants.id`
- **Relationships**: `slots`, `active_collection`, `last_selected_collection`, `last_selected_collection_item`, `last_selected_item`, `last_selected_variant`
- **Unique Constraints**: 1
- **Check Constraints**: 3
- **Indexe**: 4
- **wichtige Methoden**: `create_default`, `select_slot`, `set_active_collection`, `mark_loaded`, `mark_synced`, `mark_deleted`, `to_dict`

### 9.2 `UserInventorySlot` → `user_inventory_slots`

Persistierter Inhalt eines Slots der 9er-Hotbar.

- **identity**: `slot_uid`, `inventory_key`, `slot_key`, `collection_uid`, `collection_key`, `collection_item_uid`, `item_key`, `source_draft_uid`, `vplib_uid`, `label`, `custom_label`
- **ownership**: `scope`
- **classification**: `object_kind`, `domain`, `category`, `subcategory`, `taxonomy_path`
- **lifecycle**: `empty`, `selected`, `active`, `locked`, `pinned`, `mode`, `status`, `selected_at`, `deleted_at`
- **counts**: `slot_index`, `quantity`, `sort_order`
- **timestamps**: `assigned_at`, `cleared_at`
- **payloads**: `assets`, `variant`, `placement`, `payload`, `meta`, `metadata_json`
- **foreign_keys**: `id`, `state_id`, `user_id`, `collection_id`, `collection_item_id`, `item_db_id`, `variant_db_id`, `source_draft_id`, `family_id`, `package_id`, `variant_id`
- **other**: `content_type`, `description`, `source`, `icon`, `custom_icon`, `preview`, `custom_preview`
- **Foreign Keys**:
  - `state_id` → `user_inventory_states.id`
  - `collection_id` → `creative_library_collections.id`
  - `collection_item_id` → `creative_library_collection_items.id`
  - `item_db_id` → `creative_library_items.id`
  - `variant_db_id` → `creative_library_variants.id`
  - `source_draft_id` → `creative_library_drafts.id`
- **Relationships**: `state`, `collection`, `collection_item`, `item`, `variant_row`, `source_draft`
- **Unique Constraints**: 2
- **Check Constraints**: 2
- **Indexe**: 6
- **wichtige Methoden**: `create_empty`, `create_from_item_payload`, `assign_item`, `assign_collection_item`, `clear_item`, `mark_selected`, `set_pinned`, `set_locked`, `mark_deleted`, `display_label`, `display_icon`, `display_preview`, `to_dict`

### 9.3 `UserInventoryAuditEvent` → `user_inventory_audit_events`

Audit-Protokoll für Hotbar-/Slot-Aktionen.

- **identity**: `event_uid`, `inventory_key`, `slot_uid`, `target_uid`, `target_key`, `vplib_uid`
- **classification**: `taxonomy_path`
- **counts**: `slot_index`
- **payloads**: `before_json`, `after_json`, `diff_json`, `payload`, `meta`, `metadata_json`
- **foreign_keys**: `id`, `user_id`, `state_id`, `slot_id`, `target_db_id`, `collection_id`, `collection_item_id`, `item_db_id`, `variant_db_id`, `family_id`, `package_id`, `variant_id`
- **other**: `event_type`, `target_type`
- **Foreign Keys**:
  - `state_id` → `user_inventory_states.id`
  - `slot_id` → `user_inventory_slots.id`
- **Relationships**: `state`, `slot`
- **Indexe**: 4
- **wichtige Methoden**: `create_event`, `to_dict`

Besonderheiten:

- Phase 1: `user_id=1`, `inventory_key='default'`, exakt 9 Slots.
- `UserInventoryState` speichert Auswahlzustand und Last-Selected-Snapshot.
- `UserInventorySlot` speichert Slotinhalt und verweist optional auf Collection, CollectionItem, Published Item, Variant oder Draft.
- `selected` wird slotweise gespiegelt, aber der kanonische aktive Slot liegt im State.
- `UserInventoryAuditEvent` protokolliert Slot-Auswahl, Slot-Assignment, Clear, Pin, Lock usw.

---

## 10. Datei: `library_definitions.py` – Definition Catalog

Diese Datei modelliert den DB-seitigen Definitionskatalog. Die JSON-Dateien aus `src/library/definitions/data/*.json` können in diese Tabellen gesynct werden.

Datenfluss:

```text
src/library/definitions/data/*.json
  ↓
LibraryDefinitionSeedService
  ↓
library_definition_* Tabellen
  ↓
LibraryDefinitionCatalogService
  ↓
/api/v1/vplib/definitions/*
  ↓
Create UI / Variant Drawer / Upload Rules / Generator
```

### 10.1 `LibraryDefinitionDataset` → `library_definition_datasets`

Metadaten eines Definitions-Datasets.

- **identity**: `dataset_uid`, `dataset_key`, `label`
- **lifecycle**: `active`, `status`
- **counts**: `item_count`
- **timestamps**: `seeded_at`, `last_synced_at`
- **payloads**: `payload`, `meta`, `metadata_json`
- **foreign_keys**: `id`
- **other**: `schema_version`, `definitions_version`, `description`, `source_file_path`, `checksum`
- **Indexe**: 2
- **wichtige Methoden**: `create_from_payload`, `update_from_payload`, `mark_deprecated`, `to_dict`

### 10.2 `LibraryDefinitionSeedRun` → `library_definition_seed_runs`

Protokoll eines Definition-Seed-/Sync-Laufs.

- **identity**: `run_uid`, `source_label`
- **lifecycle**: `status`
- **counts**: `dataset_count`, `item_count`, `inserted_count`, `updated_count`, `unchanged_count`, `deprecated_count`, `skipped_count`, `warning_count`, `error_count`
- **timestamps**: `started_at`, `finished_at`
- **payloads**: `summary_json`, `errors_json`, `payload`, `meta`, `metadata_json`
- **foreign_keys**: `id`
- **other**: `source_root`, `triggered_by`, `schema_version`, `definitions_version`, `duration_ms`
- **Indexe**: 2
- **wichtige Methoden**: `start`, `apply_counts`, `finish`, `to_dict`

### 10.3 `LibraryDefinitionVariable` → `library_definition_variables`

Variable/Felddefinitionen für UI, Generator und Validierung.

- **identity**: `variable_key`, `group_key`
- **classification**: `document_type`
- **lifecycle**: `validation_json`
- **payloads**: `options_json`, `applies_to_json`
- **foreign_keys**: `dataset_id`, `unit_id`
- **other**: `value_type`, `widget`, `required_default`, `default_value`, `quantity_kind`, `references_dataset`, `stored_in`
- **Foreign Keys**:
  - `dataset_id` → `library_definition_datasets.id`
- **Relationships**: `dataset`
- **Unique Constraints**: 1
- **Indexe**: 3
- **wichtige Methoden**: `create_from_item`, `update_from_item`, `applies_to_profile`, `to_dict`

### 10.4 `LibraryDefinitionUnit` → `library_definition_units`

Einheiten und Umrechnungsmetadaten.

- **foreign_keys**: `dataset_id`, `unit_id`
- **other**: `symbol`, `quantity_kind`, `base_unit`, `conversion_factor_to_base`, `precision`
- **Foreign Keys**:
  - `dataset_id` → `library_definition_datasets.id`
- **Relationships**: `dataset`
- **Unique Constraints**: 1
- **Indexe**: 2
- **wichtige Methoden**: `create_from_item`, `update_from_item`, `to_dict`

### 10.5 `LibraryDefinitionMaterial` → `library_definition_materials`

Materialdefinitionen und technische Eigenschaften.

- **identity**: `compatible_family_profiles_json`
- **classification**: `compatible_variant_profiles_json`
- **payloads**: `default_values_json`, `properties_json`
- **foreign_keys**: `dataset_id`, `material_id`, `parent_material_id`
- **other**: `technical_depth`, `supports_product_overlay`
- **Foreign Keys**:
  - `dataset_id` → `library_definition_datasets.id`
- **Relationships**: `dataset`
- **Unique Constraints**: 1
- **Indexe**: 3
- **wichtige Methoden**: `create_from_item`, `update_from_item`, `compatible_with_variant_profile`, `to_dict`

### 10.6 `LibraryDefinitionDocumentType` → `library_definition_document_types`

Dokument-/Uploadtypen und Dateiregeln.

- **classification**: `required_for_profiles_json`
- **payloads**: `allowed_mime_types_json`, `allowed_extensions_json`
- **foreign_keys**: `dataset_id`, `document_type_id`
- **other**: `max_size_mb`, `multiple`, `upload_group`, `can_be_preview_asset`, `can_be_render_asset`, `runtime_artifact`, `future_overlay_ready`
- **Foreign Keys**:
  - `dataset_id` → `library_definition_datasets.id`
- **Relationships**: `dataset`
- **Unique Constraints**: 1
- **Indexe**: 3
- **wichtige Methoden**: `create_from_item`, `update_from_item`, `allows_extension`, `allows_mime_type`, `to_dict`

### 10.7 `LibraryDefinitionObjectKind` → `library_definition_object_kinds`

ObjectKind-Definitionen als fachliche Objekttypen.

- **identity**: `allowed_family_profiles_json`
- **payloads**: `default_modules_json`, `geometry_rules_json`, `preview_behavior_json`
- **foreign_keys**: `dataset_id`, `object_kind_id`, `default_family_profile_id`, `default_variant_profile_id`
- **other**: `technical_truth`
- **Foreign Keys**:
  - `dataset_id` → `library_definition_datasets.id`
- **Relationships**: `dataset`
- **Unique Constraints**: 1
- **Indexe**: 2
- **wichtige Methoden**: `create_from_item`, `update_from_item`, `to_dict`

### 10.8 `LibraryDefinitionFamilyProfile` → `library_definition_family_profiles`

Family-Profile für Package-/Generator-Struktur.

- **classification**: `object_kinds_json`, `taxonomy_domains_json`, `taxonomy_categories_json`, `taxonomy_subcategories_json`, `allowed_variant_profiles_json`
- **payloads**: `required_modules_json`, `optional_modules_json`, `default_modules_json`, `supports_product_like_variants`
- **foreign_keys**: `dataset_id`, `family_profile_id`, `default_variant_profile_id`
- **other**: `future_overlay_ready`
- **Foreign Keys**:
  - `dataset_id` → `library_definition_datasets.id`
- **Relationships**: `dataset`
- **Unique Constraints**: 1
- **Indexe**: 2
- **wichtige Methoden**: `create_from_item`, `update_from_item`, `allows_variant_profile`, `to_dict`

### 10.9 `LibraryDefinitionVariantProfile` → `library_definition_variant_profiles`

Variant-Profile für Variantenfelder und UI-Modi.

- **identity**: `family_profiles_json`
- **classification**: `object_kinds_json`, `document_types_json`
- **lifecycle**: `manufacturer_mode`, `preview_mode`
- **payloads**: `sections_json`, `required_fields_json`, `optional_fields_json`, `summary_fields_json`, `default_values_json`, `drawer_size`, `supports_product_like_variants`
- **foreign_keys**: `dataset_id`, `variant_profile_id`
- **other**: `future_overlay_ready`
- **Foreign Keys**:
  - `dataset_id` → `library_definition_datasets.id`
- **Relationships**: `dataset`
- **Unique Constraints**: 1
- **Indexe**: 2
- **wichtige Methoden**: `create_from_item`, `update_from_item`, `field_keys`, `has_field`, `to_dict`

### 10.10 `LibraryDefinitionProfileBinding` → `library_definition_profile_bindings`

Bindings zwischen Taxonomie/ObjectKind und Profilen.

- **classification**: `domain`, `category`, `subcategory`, `taxonomy_path`, `object_kind`
- **payloads**: `match_json`, `supports_product_like_variants`
- **foreign_keys**: `dataset_id`, `binding_id`, `family_profile_id`, `variant_profile_id`
- **other**: `priority`, `supports_legacy_source_layout`, `fallback_binding`, `alias_binding`
- **Foreign Keys**:
  - `dataset_id` → `library_definition_datasets.id`
- **Relationships**: `dataset`
- **Unique Constraints**: 1
- **Indexe**: 4
- **wichtige Methoden**: `create_from_item`, `update_from_item`, `matches_context`, `to_dict`

### 10.11 `LibraryDefinitionOverride` → `library_definition_overrides`

User-/System-Overrides auf Definitionen.

- **identity**: `override_uid`, `dataset_key`, `target_definition_uid`, `target_key`, `label_override`
- **ownership**: `owner_scope`
- **lifecycle**: `status`, `active`, `visible_override`, `active_override`, `deleted_at`
- **payloads**: `payload_patch`, `value_override_json`, `before_json`, `after_json`, `meta`, `metadata_json`
- **foreign_keys**: `id`, `user_id`, `created_by_user_id`, `updated_by_user_id`
- **other**: `target_type`, `override_action`, `description_override`, `sort_order_override`
- **Unique Constraints**: 1
- **Indexe**: 2
- **wichtige Methoden**: `create_from_payload`, `mark_deleted`, `to_dict`

Besonderheiten:

- Systemdefinitionen werden nicht überschrieben, sondern durch user-scoped Definitionen oder Overrides ergänzt.
- `LibraryDefinitionDataset` speichert Dataset-Metadaten und Checksums.
- `LibraryDefinitionSeedRun` protokolliert Seed-/Sync-Läufe.
- Konkrete Definitionstabellen teilen sich gemeinsame Felder über `DefinitionRecordMixin`.
- `owner_scope + definition_key` ist pro Definitionstyp eindeutig.
- Dataset-Keys: `variables`, `units`, `materials`, `document_types`, `object_kinds`, `family_profiles`, `variant_profiles`, `profile_bindings`.

---

## 11. Datei: `library_taxonomy.py` – Taxonomy DB

Diese Datei modelliert die Backend-Taxonomie für Creative Inventory, Create Flow und Generator.

Datenfluss:

```text
src/library/taxonomy/data/taxonomy.v1.json
  ↓ seed/sync
LibraryTaxonomyNode system-owned
  ↓
User Nodes + Overrides
  ↓
resolved taxonomy for user_id
  ↓
/api/v1/vplib/taxonomy/*
  ↓
Creative-Inventar / Create Flow
```

### 11.1 `LibraryTaxonomyNode` → `library_taxonomy_nodes`

Taxonomie-Knoten für Domain, Category, Subcategory.

- **identity**: `node_uid`, `base_node_uid`, `node_key`, `slug`, `label`, `name`
- **ownership**: `source_scope`, `owner_scope`
- **classification**: `domain`, `category`, `subcategory`, `taxonomy_path`, `parent_taxonomy_path`
- **lifecycle**: `status`, `active`, `visible`, `locked`, `deleted_at`
- **counts**: `sort_order`
- **payloads**: `tags_json`, `aliases_json`, `i18n_json`, `ui_json`, `payload`, `meta`, `metadata_json`
- **foreign_keys**: `id`, `parent_node_id`, `owner_user_id`, `created_by_user_id`, `updated_by_user_id`, `deleted_by_user_id`
- **other**: `node_type`, `node_depth`, `description`, `icon`, `color`, `selectable`, `allow_children`, `is_leaf`, `system_required`
- **Foreign Keys**:
  - `parent_node_id` → `library_taxonomy_nodes.id`
- **Relationships**: `parent`, `children`, `overrides`
- **Unique Constraints**: 1
- **Indexe**: 5
- **wichtige Methoden**: `create_from_payload`, `update_from_payload`, `is_system_owned`, `is_user_owned`, `mark_deleted`, `restore`, `to_dict`

### 11.2 `LibraryTaxonomyOverride` → `library_taxonomy_overrides`

User-Overrides auf System-Taxonomie-Knoten.

- **identity**: `override_uid`, `target_node_uid`, `target_node_key`, `label_override`, `parent_node_uid_override`
- **ownership**: `owner_scope`
- **classification**: `target_taxonomy_path`, `parent_taxonomy_path_override`
- **lifecycle**: `status`, `active`, `visible_override`, `active_override`, `deleted_at`
- **payloads**: `payload_patch`, `before_json`, `after_json`, `meta`, `metadata_json`
- **foreign_keys**: `id`, `user_id`, `target_node_id`, `created_by_user_id`, `updated_by_user_id`, `deleted_by_user_id`
- **other**: `target_node_type`, `override_action`, `selectable_override`, `description_override`, `icon_override`, `color_override`, `sort_order_override`
- **Foreign Keys**:
  - `target_node_id` → `library_taxonomy_nodes.id`
- **Relationships**: `target_node`
- **Unique Constraints**: 1
- **Indexe**: 3
- **wichtige Methoden**: `create_from_payload`, `mark_deleted`, `restore`, `to_dict`

### 11.3 `LibraryTaxonomyAuditEvent` → `library_taxonomy_audit_events`

Audit-Protokoll für Taxonomie-Aktionen.

- **identity**: `event_uid`, `node_uid`, `override_uid`
- **ownership**: `owner_scope`
- **classification**: `taxonomy_path`
- **payloads**: `before_json`, `after_json`, `diff_json`, `payload`, `meta`, `metadata_json`
- **foreign_keys**: `id`, `user_id`, `node_id`, `override_id`
- **other**: `event_type`, `node_type`
- **Foreign Keys**:
  - `node_id` → `library_taxonomy_nodes.id`
  - `override_id` → `library_taxonomy_overrides.id`
- **Relationships**: `node`, `override`
- **Indexe**: 3
- **wichtige Methoden**: `create_event`, `to_dict`

Besonderheiten:

- Node-Typen sind `domain`, `category`, `subcategory`.
- `taxonomy_path` ist der kanonische Pfad, maximal drei Ebenen tief.
- System-Nodes liegen unter `owner_scope='system'`.
- User-Erweiterungen liegen unter `owner_scope='user:<id>'`.
- Overrides erlauben hide/restore/rename/reorder/move/patch/delete ohne System-Nodes direkt zu verändern.

---

## 12. Datei: `library_files.py` – Upload-/File-Metadaten

Diese Datei modelliert Dateien unabhängig davon, ob sie zu einem Published Item, Draft, Definition, Taxonomy Node oder User Inventory Slot gehören.

Datenfluss:

```text
Upload / Generator / Import
  ↓
LibraryFileService
  ↓
LibraryFile
  ↓
LibraryFileVersion
  ↓
LibraryFileLink
  ↓
context: creative_item | creative_variant | draft | definition | taxonomy_node | user_inventory_slot | ...
```

### 12.1 `LibraryFile` → `library_files`

Logische Datei über mehrere Versionen.

- **identity**: `file_uid`, `original_filename`, `safe_filename`
- **ownership**: `source_scope`, `owner_scope`
- **classification**: `document_type`, `asset_kind`
- **lifecycle**: `status`, `active`, `visible`, `locked`, `deleted_at`
- **counts**: `version_count`
- **timestamps**: `uploaded_at`, `replaced_at`, `last_accessed_at`
- **payloads**: `payload`, `meta`, `metadata_json`
- **foreign_keys**: `id`, `owner_user_id`, `current_version_id`, `created_by_user_id`, `updated_by_user_id`, `deleted_by_user_id`
- **other**: `extension`, `mime_type`, `size_bytes`, `sha256`, `storage_backend`, `storage_path`, `external_uri`, `quarantine_reason`
- **Foreign Keys**:
  - `current_version_id` → `library_file_versions.id`; `use_alter=True`
- **Relationships**: `versions`, `current_version`, `links`
- **Indexe**: 5
- **wichtige Methoden**: `create_from_payload`, `set_current_version`, `mark_deleted`, `mark_quarantined`, `restore`, `touch_accessed`, `to_dict`

### 12.2 `LibraryFileVersion` → `library_file_versions`

Konkrete Version einer LibraryFile.

- **identity**: `version_uid`, `original_filename`, `safe_filename`
- **lifecycle**: `status`, `active`
- **payloads**: `payload`, `meta`, `metadata_json`
- **foreign_keys**: `id`, `file_id`, `uploaded_by_user_id`
- **other**: `version_index`, `extension`, `mime_type`, `size_bytes`, `sha256`, `storage_backend`, `storage_path`, `external_uri`, `binary_data`, `content_encoding`
- **Foreign Keys**:
  - `file_id` → `library_files.id`
- **Relationships**: `file`, `links`
- **Unique Constraints**: 1
- **Indexe**: 3
- **wichtige Methoden**: `create_from_payload`, `mark_replaced`, `mark_deleted`, `to_dict`

### 12.3 `LibraryFileLink` → `library_file_links`

Kontext-Link zwischen Datei und Item/Variant/Draft/Definition/etc.

- **identity**: `link_uid`, `context_uid`, `vplib_uid`, `revision_hash`, `field_key`, `label`
- **ownership**: `owner_scope`
- **classification**: `document_type`
- **lifecycle**: `status`, `active`, `deleted_at`
- **counts**: `sort_order`
- **timestamps**: `assigned_at`
- **payloads**: `payload`, `meta`, `metadata_json`
- **foreign_keys**: `id`, `file_id`, `file_version_id`, `user_id`, `context_db_id`, `context_id`, `family_id`, `package_id`, `variant_id`, `created_by_user_id`, `updated_by_user_id`, `deleted_by_user_id`
- **other**: `context_type`, `role`, `description`, `is_primary`
- **Foreign Keys**:
  - `file_id` → `library_files.id`
  - `file_version_id` → `library_file_versions.id`
- **Relationships**: `file`, `file_version`
- **Indexe**: 5
- **wichtige Methoden**: `create_from_payload`, `mark_deleted`, `restore`, `to_dict`

### 12.4 `LibraryFileAuditEvent` → `library_file_audit_events`

Audit-Protokoll für Upload-/Link-/Version-Aktionen.

- **identity**: `event_uid`, `file_uid`, `version_uid`, `link_uid`, `vplib_uid`
- **ownership**: `owner_scope`
- **payloads**: `before_json`, `after_json`, `diff_json`, `payload`, `meta`, `metadata_json`
- **foreign_keys**: `id`, `user_id`, `file_id`, `file_version_id`, `link_id`, `context_id`, `family_id`, `variant_id`
- **other**: `event_type`, `context_type`
- **Foreign Keys**:
  - `file_id` → `library_files.id`
  - `file_version_id` → `library_file_versions.id`
  - `link_id` → `library_file_links.id`
- **Relationships**: `file`, `file_version`, `link`
- **Indexe**: 3
- **wichtige Methoden**: `create_event`, `to_dict`

Besonderheiten:

- `LibraryFile` ist die logische Datei über mehrere Versionen.
- `LibraryFileVersion` ist die konkrete Datei-/Storage-Version.
- `LibraryFile.current_version_id` ist ein zyklischer Pointer auf `library_file_versions` und mit `use_alter=True` modelliert.
- Große Dateien wie GLB/GLTF sollen standardmäßig nicht als BYTEA gespeichert werden, sondern über `storage_path`, Object Storage oder externe URI referenziert werden.
- `LibraryFileLink` verbindet Dateien mit beliebigen Kontexten über `context_type`, `context_id`, `context_uid`, `field_key`, `role` usw.
- Gefährliche Upload-Endungen sind als Konstanten blockierbar; die tatsächliche Sicherheitsprüfung gehört aber in den File-Service.

---

## 13. Cross-Module-Foreign-Key-Graph

Die Modelschicht ist bewusst in mehrere Module getrennt, aber die Tabellen referenzieren sich teilweise gegenseitig.

### `creative_library_assets`
- `family_db_id` → `creative_library_items`
- `item_id` → `creative_library_items`
- `revision_id` → `creative_library_revisions`
- `variant_db_id` → `creative_library_variants`
- `library_file_id` → `library_files`
- `library_file_version_id` → `library_file_versions`

### `creative_library_collection_items`
- `collection_id` → `creative_library_collections`
- `item_db_id` → `creative_library_items`
- `variant_db_id` → `creative_library_variants`

### `creative_library_documents`
- `family_db_id` → `creative_library_items`
- `item_id` → `creative_library_items`
- `revision_id` → `creative_library_revisions`
- `variant_db_id` → `creative_library_variants`
- `library_file_id` → `library_files`
- `library_file_version_id` → `library_file_versions`

### `creative_library_draft_assets`
- `draft_id` → `creative_library_drafts`
- `draft_variant_id` → `creative_library_draft_variants`
- `library_file_id` → `library_files`
- `library_file_version_id` → `library_file_versions`

### `creative_library_draft_audit_events`
- `draft_id` → `creative_library_drafts`

### `creative_library_draft_documents`
- `draft_id` → `creative_library_drafts`
- `draft_variant_id` → `creative_library_draft_variants`

### `creative_library_draft_validation_issues`
- `draft_id` → `creative_library_drafts`
- `draft_variant_id` → `creative_library_draft_variants`

### `creative_library_draft_variants`
- `draft_id` → `creative_library_drafts`
- `source_variant_id` → `creative_library_variants` (`use_alter=True`)

### `creative_library_drafts`
- `target_item_id` → `creative_library_items` (`use_alter=True`)
- `base_revision_id` → `creative_library_revisions` (`use_alter=True`)
- `published_revision_id` → `creative_library_revisions` (`use_alter=True`)

### `creative_library_inventory_slots`
- `family_db_id` → `creative_library_items`
- `item_id` → `creative_library_items`

### `creative_library_items`
- `current_revision_id` → `creative_library_revisions` (`use_alter=True`)

### `creative_library_revisions`
- `family_db_id` → `creative_library_items`
- `item_id` → `creative_library_items`
- `scan_run_id` → `creative_library_scan_runs`
- `source_draft_id` → `creative_library_drafts` (`use_alter=True`)

### `creative_library_scan_issues`
- `scan_run_id` → `creative_library_scan_runs`
- `family_db_id` → `creative_library_items`
- `revision_id` → `creative_library_revisions`

### `creative_library_user_audit_events`
- `collection_id` → `creative_library_collections`
- `collection_item_id` → `creative_library_collection_items`
- `override_id` → `creative_library_user_overrides`
- `item_db_id` → `creative_library_items`
- `variant_db_id` → `creative_library_variants`

### `creative_library_user_overrides`
- `collection_id` → `creative_library_collections`
- `collection_item_id` → `creative_library_collection_items`
- `item_db_id` → `creative_library_items`
- `variant_db_id` → `creative_library_variants`

### `creative_library_variants`
- `family_db_id` → `creative_library_items`
- `item_id` → `creative_library_items`
- `revision_id` → `creative_library_revisions`
- `source_draft_variant_id` → `creative_library_draft_variants` (`use_alter=True`)

### `library_definition_document_types`
- `dataset_id` → `library_definition_datasets`

### `library_definition_family_profiles`
- `dataset_id` → `library_definition_datasets`

### `library_definition_materials`
- `dataset_id` → `library_definition_datasets`

### `library_definition_object_kinds`
- `dataset_id` → `library_definition_datasets`

### `library_definition_profile_bindings`
- `dataset_id` → `library_definition_datasets`

### `library_definition_units`
- `dataset_id` → `library_definition_datasets`

### `library_definition_variables`
- `dataset_id` → `library_definition_datasets`

### `library_definition_variant_profiles`
- `dataset_id` → `library_definition_datasets`

### `library_file_audit_events`
- `file_id` → `library_files`
- `file_version_id` → `library_file_versions`
- `link_id` → `library_file_links`

### `library_file_links`
- `file_id` → `library_files`
- `file_version_id` → `library_file_versions`

### `library_file_versions`
- `file_id` → `library_files`

### `library_files`
- `current_version_id` → `library_file_versions` (`use_alter=True`)

### `library_taxonomy_audit_events`
- `node_id` → `library_taxonomy_nodes`
- `override_id` → `library_taxonomy_overrides`

### `library_taxonomy_nodes`
- `parent_node_id` → `library_taxonomy_nodes`

### `library_taxonomy_overrides`
- `target_node_id` → `library_taxonomy_nodes`

### `user_inventory_audit_events`
- `state_id` → `user_inventory_states`
- `slot_id` → `user_inventory_slots`

### `user_inventory_slots`
- `state_id` → `user_inventory_states`
- `collection_id` → `creative_library_collections`
- `collection_item_id` → `creative_library_collection_items`
- `item_db_id` → `creative_library_items`
- `variant_db_id` → `creative_library_variants`
- `source_draft_id` → `creative_library_drafts`

### `user_inventory_states`
- `active_collection_id` → `creative_library_collections`
- `last_selected_collection_id` → `creative_library_collections`
- `last_selected_collection_item_id` → `creative_library_collection_items`
- `last_selected_item_db_id` → `creative_library_items`
- `last_selected_variant_db_id` → `creative_library_variants`

### 13.1 Bekannte zyklische FKs

Zyklische Foreign Keys werden nicht entfernt, sondern mit `use_alter=True` und stabilen Constraint-Namen so modelliert, dass Alembic die Tabellen zuerst erzeugen und die betroffenen Constraints anschließend per `ALTER TABLE` anlegen kann.

Aktuelle zyklische/optional entkoppelte FKs:

- `creative_library_items.current_revision_id` → `creative_library_revisions.id`
- `creative_library_revisions.source_draft_id` → `creative_library_drafts.id`
- `creative_library_variants.source_draft_variant_id` → `creative_library_draft_variants.id`
- `creative_library_drafts.target_item_id` → `creative_library_items.id`
- `creative_library_drafts.base_revision_id` → `creative_library_revisions.id`
- `creative_library_drafts.published_revision_id` → `creative_library_revisions.id`
- `creative_library_draft_variants.source_variant_id` → `creative_library_variants.id`
- `library_files.current_version_id` → `library_file_versions.id`

Wichtig: Normale Parent-Child-FKs wie `creative_library_draft_variants.draft_id → creative_library_drafts.id` bleiben ohne `use_alter=True`, damit die Tabellenreihenfolge weiterhin eindeutig sortierbar bleibt.

---

## 14. Status-/Scope-Konzept

Fast alle Modelmodule verwenden ähnliche Konzepte:

### 14.1 `source_scope`

Beschreibt, woher ein Datensatz fachlich stammt:

- `system`: globale, system-owned Daten
- `user`: user-owned Daten
- `imported`: importierte Daten
- `generated`: Generator-/Create-Flow-Daten
- `external`: nur bei Dateien für externe URI-Quellen

### 14.2 `owner_user_id` und `owner_scope`

`owner_user_id` darf `NULL` sein. Für eindeutige Constraints wird zusätzlich `owner_scope` gespeichert:

```text
system-owned: owner_user_id = NULL, owner_scope = 'system'
user-owned:   owner_user_id = 1,    owner_scope = 'user:1'
```

### 14.3 Soft Delete

Die meisten Tabellen löschen fachlich weich:

- `status='deleted'`
- `active=False`
- `visible=False` oder `enabled=False`
- `deleted_at` gesetzt
- optionale `deleted_by_user_id`

Physische Deletes sollten in Services/Repositories nur bewusst erfolgen.

---

## 15. Hauptdatenflüsse über die Models

### 15.1 Source Package → Published DB

```text
src/library/source/<domain>/<category>/<subcategory>/<family_slug>/
  ↓
scanner / reader / validator / fingerprint
  ↓
library_db_sync_service
  ↓
CreativeLibraryScanRun
  ↓
CreativeLibraryItem
  ↓
CreativeLibraryRevision
  ↓
CreativeLibraryVariant / CreativeLibraryAsset / CreativeLibraryDocument
  ↓
Published API
```

### 15.2 Create UI → Draft → Published

```text
/create oder /api/v1/vplib/library/drafts
  ↓
CreativeLibraryDraft
  ↓
CreativeLibraryDraftVariant
CreativeLibraryDraftAsset
CreativeLibraryDraftDocument
  ↓
CreativeLibraryDraftValidationIssue
  ↓
Draft ready_to_publish
  ↓
CreativeLibraryRevision + Children
```

### 15.3 Published Library → User Collection

```text
CreativeLibraryItem / CreativeLibraryVariant
  ↓
CreativeLibraryCollectionItem
  ↓
CreativeLibraryCollection
  ↓
CreativeLibraryUserOverride
  ↓
resolved user creative library
```

### 15.4 User Collection → Editor Hotbar

```text
CreativeLibraryCollectionItem
  ↓
PUT /api/v1/vplib/inventar_user/slots/<slot_index>
  ↓
UserInventorySlot
  ↓
UserInventoryState.select_slot(...)
  ↓
Editor nutzt aktiven Slot
```

### 15.5 Definitions → Create UI

```text
definitions/data/*.json
  ↓
LibraryDefinitionDataset
LibraryDefinitionVariable / Unit / Material / DocumentType / ObjectKind / Profile / Binding
  ↓
Definition Catalog Service
  ↓
Create UI / Variant Drawer / Upload Regeln
```

### 15.6 Files → Kontext-Links

```text
Upload / Generator
  ↓
LibraryFile
  ↓
LibraryFileVersion
  ↓
LibraryFileLink
  ↓
creative_item / creative_variant / creative_draft / definition / taxonomy_node / user_inventory_slot
```

---

## 16. Migrations- und Startverhalten

### 16.1 Was beim Start passieren muss

```text
1. extensions.db wird erzeugt.
2. Flask app initialisiert extensions.db.
3. models.import_all_models() importiert alle Modelmodule.
4. SQLAlchemy db.metadata enthält alle Tabellen.
5. Alembic autogenerate erkennt neue Tabellen/Constraints/Indexe.
6. flask db upgrade erzeugt/aktualisiert PostgreSQL-Struktur.
```

### 16.2 Typische harte Fehler und Bedeutung

| Fehler | Bedeutung | Fix-Richtung |
|---|---|---|
| `NameError` beim Modelimport | Modul kann nicht importiert werden; Alembic sieht keine Tabellen | fehlende Konstante/Import/Typ korrigieren |
| `SQLAlchemy model classes: 0` | `import_all_models()` lädt keine Models | `models/__init__.py` Registry prüfen |
| `metadata tables: 0` | db.Model Registry wurde nicht gefüllt | db-Extension-/Import-Reihenfolge prüfen |
| `UndefinedTable` bei Migration | FK-Zyklus oder falsche Reihenfolge | optionale zyklische FKs mit `use_alter=True` |
| `relation already exists` | DB/Migration-State inkonsistent | Alembic-Version und Reset-Strategie prüfen |
| `operator does not exist: bigint = character varying` | Repository vergleicht String-ID gegen BigInteger | nicht im Model fixen; Repository Lookup korrigieren |

### 16.3 Aktueller Stand

- Die Modelmodule sind importierbar.
- Alle 39 Tabellen sind in `db.metadata` sichtbar.
- Die letzte Initialmigration wurde erfolgreich ausgeführt.
- Die vorherigen FK-Zyklen zwischen Published und Draft wurden durch `use_alter=True` entschärft.

---

## 17. Was gehört wohin?

| Aufgabe | Richtiger Ort | Nicht in |
|---|---|---|
| Spalte/Tabelle/Index/Constraint definieren | `models/*.py` | Service/Route |
| Alle Models für Alembic registrieren | `models/__init__.py` | einzelne Route |
| DB-Abfrage schreiben | `src/library/repositories/*` | `models/*.py` |
| Business-Flow orchestrieren | `src/library/services/*` | `models/*.py` |
| HTTP Request/Response | `routes/*.py` oder `src/routes/*.py` | `models/*.py` |
| Daten aus JSON seeden | Seed-Service | `models/*.py` |
| VPLIB UID erzeugen | VPLIB/Create/Manifest Flow | DB-Model |
| Dateien speichern | File-Service / Storage Adapter | `library_files.py` Model |
| Migration erzeugen | Alembic/Flask-Migrate | Model-Datei selbst |

---

## 18. Test- und Diagnosebefehle

### 18.1 Syntax

```powershell
docker compose exec -T vectoplan-library python -m py_compile models/__init__.py
docker compose exec -T vectoplan-library python -m py_compile models/creative_library.py
docker compose exec -T vectoplan-library python -m py_compile models/creative_library_drafts.py
docker compose exec -T vectoplan-library python -m py_compile models/creative_library_user.py
docker compose exec -T vectoplan-library python -m py_compile models/user_inventory.py
docker compose exec -T vectoplan-library python -m py_compile models/library_definitions.py
docker compose exec -T vectoplan-library python -m py_compile models/library_taxonomy.py
docker compose exec -T vectoplan-library python -m py_compile models/library_files.py
```

### 18.2 Modelimport

```powershell
docker compose exec -T vectoplan-library python -c "import models; print(models.get_models_health())"
docker compose exec -T vectoplan-library python -c "from models import import_all_models; print(len(import_all_models()))"
docker compose exec -T vectoplan-library python -c "from models import get_model_table_names; print(get_model_table_names())"
```

### 18.3 DB-Tabellen prüfen

```powershell
docker compose exec -T vectoplan-library-db psql -U vectoplan -d vectoplan_library -c "select table_name from information_schema.tables where table_schema = 'public' order by table_name;"
```

### 18.4 Alembic Status

```powershell
docker compose exec -T vectoplan-library flask db current
docker compose exec -T vectoplan-library flask db history
docker compose exec -T vectoplan-library flask db migrate -m "check models diff"
```

Wenn `flask db migrate` eine leere Migration erzeugt, obwohl Modeländerungen erwartet werden, zuerst `models.import_all_models()` und `db.metadata.tables` prüfen.

---

## 19. Offene Prüfungen / nächste Schritte

P0:

- Nach jeder Modeländerung `py_compile` ausführen.
- `models.get_models_health()` prüfen.
- `flask db migrate` nur dann ausführen, wenn die Modeländerung fachlich gewollt ist.
- Neue Migrationsdatei prüfen, bevor sie committed wird.
- Zyklische FKs nur gezielt mit `use_alter=True` markieren; normale Parent-Child-FKs nicht unnötig auslagern.

P1:

- Constraints/Indexes auf tatsächliche Query-Pfade abstimmen.
- `MAX_VPLIB_UID_LENGTH` langfristig über alle Module angleichen.
- `owner_scope` und `source_scope` in Services konsistent setzen.
- Tests für `import_all_models(strict=True)` ergänzen.
- Tests für `get_models_health()` ergänzen.
- Alembic-Autogenerate in CI oder Prestart-Diagnose prüfen.

P2:

- Gemeinsame Helper ggf. später aus den Modeldateien in ein internes Model-Utils-Modul auslagern, falls Duplikation stört.
- Model-Dokumentation mit echten DB-Dumps und ERD ergänzen.
- Optional Diagramm für FK-Graph generieren.

---

## 20. Definition of Done für `/models`

Der Ordner `/models` gilt als stabil, wenn:

1. alle Modeldateien syntaktisch gültig sind
2. `import models` funktioniert
3. `models.import_all_models(strict=True)` funktioniert
4. `models.get_models_health()['healthy'] == True`
5. `db.metadata.tables` alle erwarteten 39 Tabellen enthält
6. `flask db migrate` keine unerwarteten Änderungen erzeugt
7. `flask db upgrade` erfolgreich läuft
8. Published-/Draft-/User-/Definitions-/Taxonomy-/Files-Tabellen sichtbar sind
9. zyklische FKs nur an den bekannten optionalen Rückverweisen hängen
10. keine Modeldatei aktive DB-Verbindungen, Scanner, Seed-Logik oder Routen enthält
11. `vplib_uid` nur übernommen und nicht durch die DB erfunden wird
12. `UserInventoryState/UserInventorySlot` exakt den User-Hotbar-Zustand speichern und keine Library-Items erzeugen

---

## 21. Kurzfazit

`services/vectoplan-library/models` ist inzwischen nicht mehr nur ein kleines Creative-Library-Model, sondern die vollständige Persistenzbasis für:

- Published Creative Library
- Scan-/Sync-Historie
- Revisions und Varianten
- Assets und Documents
- Draft-/Create-/Generator-Arbeitsstände
- User Collections und User Overrides
- User-Hotbar und Editor-Auswahl
- Definition Catalog
- Taxonomie
- generische Upload-/File-Metadaten

Der wichtigste Architekturpunkt bleibt: Die Modelschicht beschreibt den persistenten Vertrag, aber sie führt ihn nicht aus. Ausführung liegt in Repositories, Services, Routes, Alembic und den jeweiligen Runtime-Flows.
