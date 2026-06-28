# IST-Zustand – `services/vectoplan-library/src/library`

Stand: **2026-06-28**  
Letzte Aktualisierung: **2026-06-28**  
Scope: `services/vectoplan-library/src/library` plus relevante Außenkanten in `routes/`, `src/routes/`, `models/`, `migrations/`, PostgreSQL/Alembic und API-Testpfade.

Dieses Dokument beschreibt den aktuellen Aufbau der Library-Schicht so, dass ein Entwickler die Ordner, Dateien, Datenflüsse, Zuständigkeiten und Testreihenfolge nachvollziehen kann.

---

## Inhaltsverzeichnis

1. Kurzstatus
2. Grundidee und Systemgrenzen
3. Source-of-Truth-Modell
4. Gesamtarchitektur als Schichtenmodell
5. Ordner- und Filestruktur
6. Ordner `definitions/`
7. Ordner `taxonomy/`
8. Ordner `scanner/`
9. Ordner `validation/`
10. Ordner `domain/`
11. Ordner `read_models/`
12. Ordner `services/`
13. Ordner `repositories/`
14. Ordner `source/`
15. Wichtige Außenkanten außerhalb von `src/library`
16. Datenbankmodell und Tabellenfamilien
17. Hauptdatenflüsse
18. API-Routen und Verantwortlichkeiten
19. Create-, Draft-, Publish- und Sync-Zusammenhang
20. Files-/Upload-Schicht
21. User-Library, Collections und Inventory
22. Cache-, Health- und Diagnostics-Konzept
23. Teststrategie
24. Typische Fehlerbilder und Debug-Reihenfolge
25. Konventionen für neue Dateien und Erweiterungen
26. Offene Punkte / nächste Arbeit
27. Definition of Done

---

## 1. Kurzstatus

Die Library-Schicht ist nicht mehr nur ein dateibasierter Katalog. Sie besitzt jetzt mehrere gekoppelte, aber getrennte Pfade:

```text
1. Dateibasierter Source-Pfad
   src/library/source/*
   -> Scanner/Reader/Validator/Fingerprint
   -> Debug-/Preview-Responses

2. DB-Sync-Pfad
   src/library/source/* oder vorhandenes ScanResult
   -> LibraryDbSyncService
   -> CreativeLibraryService / CreativeLibraryRepository
   -> PostgreSQL

3. Published-Read-Pfad
   PostgreSQL
   -> CreativeLibraryRepository
   -> CreativeLibraryService / Read-Models
   -> API-Routen

4. Create-/Draft-Pfad
   /create Payload
   -> Create Route Service
   -> Create Service
   -> Draft Service oder .vplib Package/Source Package

5. Definition-/Taxonomie-Pfad
   JSON-Definitionen und DB-Definitionen
   -> Definition Catalog Service
   -> Create Options / Validation / Profile-Auflösung
```

Aktuell getestet und grundsätzlich funktionsfähig:

```text
✅ Container startet nach den Model-/FK-Fixes.
✅ Alembic-Migrationen laufen durch.
✅ SQLAlchemy-Modelle werden importiert.
✅ PostgreSQL ist erreichbar.
✅ Health-Routen funktionieren.
✅ /api/v1/vplib/library/scan?source=file funktioniert.
✅ /api/v1/vplib/definitions/health funktioniert.
✅ /api/v1/vplib/files/health funktioniert.
✅ /api/v1/vplib/taxonomy/health funktioniert.
✅ /api/v1/vplib/creative-library/health funktioniert.
✅ /api/v1/vplib/library/drafts/health funktioniert.
✅ /api/v1/vplib/library/health funktioniert.
```

Aktuell besonders wichtig:

```text
- GET /scan bleibt read-only.
- POST /sync ist der explizite DB-Write-Entry-Point.
- DB erzeugt keine vplib_uid.
- vplib_uid kommt aus dem Package/Manifest oder aus dem Create-Flow.
- Drafts sind Arbeitszustand, nicht Published State.
- Published Tables sind die produktive sichtbare Library.
- User Collections/Overrides sind getrennt vom Systemkatalog.
```

---

## 2. Grundidee und Systemgrenzen

### 2.1 Was ist `src/library`?

`src/library` ist die fachliche Creative-Library-Schicht. Sie liegt oberhalb des technischen VPLIB-Kerns.

```text
src/vplib
  technischer VPLIB-Kern
  - VPLIB UID Service
  - Package-/Manifest-Grundlogik
  - Creator/Defaults
  - Archiv-/Package-Mechanik
  - technische Validierung

src/library
  fachliche Creative-Library-Schicht
  - Taxonomie
  - Definitions/Profile
  - Source-Scan-Orchestrierung
  - fachliche Library-Validierung
  - Read-Models
  - DB-Sync
  - Published-DB-Reads
  - Draft Working State
  - User Collections/Overrides
  - File-/Upload-Metadaten
```

`src/library` beantwortet nicht nur die Frage „Kann dieses Package technisch gelesen werden?“, sondern:

```text
- Wo liegt es in der Taxonomie?
- Welche Object-Kind/Profile gelten?
- Ist es als Creative-Library-Block publishbar?
- Welche Varianten/Dokumente/Assets gehören dazu?
- Was ist der aktuelle veröffentlichte Stand?
- Welche User-Overlays existieren zusätzlich?
```

### 2.2 Was gehört bewusst nicht in `src/library`?

```text
- Keine Flask-Routen direkt in Domain-/Repository-/Service-Dateien.
- Keine Datenbankmigrationen in Services.
- Kein db.create_all().
- Keine Tabellenanlage durch Runtime-Code.
- Keine UI-Komponenten.
- Keine direkte Frontend-Logik.
- Keine automatische DB-Schreiboperation bei GET /scan.
```

### 2.3 Außenkanten

Wichtige Außenkanten liegen außerhalb von `src/library`:

```text
routes/
  Flask-Blueprints und HTTP-Adapter

src/routes/
  Blueprint-Registry / Import- und Registrierungslogik

models/
  SQLAlchemy-Modelle

migrations/
  Alembic-/Flask-Migrate-Versionen

PostgreSQL
  persistierter Published-/Draft-/Definitions-/File-/User-Zustand
```

---

## 3. Source-of-Truth-Modell

Die Schicht arbeitet mit mehreren bewusst getrennten Wahrheiten.

### 3.1 Source Packages

```text
services/vectoplan-library/src/library/source/
```

Das ist die menschlich lesbare Source-Struktur für VPLIB Directory Packages.

Eigenschaften:

```text
- versionierbar im Repository
- gut lesbar und reviewbar
- Quelle für /scan und /sync
- keine DB-Tabelle
- kein Runtime-Cache
```

Kanonisches Ziel-Layout:

```text
src/library/source/{domain}/{category}/{subcategory}/{family_slug}/
├── vplib.manifest.json
├── vplib.modules.json
├── family/
│   ├── identity.json
│   └── classification.json
├── variants/
│   ├── index.json
│   └── default.json
├── editor/
├── render/
├── physical/
├── material/
├── calculation/
├── manufacturer/
├── analysis/
├── dynamic/
├── docs/
├── tests/
└── assets/
```

### 3.2 Published DB State

Published State liegt in PostgreSQL und ist der produktive Lesezustand der Library.

Wichtige Tabellen:

```text
creative_library_items
creative_library_revisions
creative_library_variants
creative_library_assets
creative_library_documents
creative_library_scan_runs
creative_library_scan_issues
creative_library_inventory_slots
```

Eigenschaften:

```text
- produktiver API-Lesepfad
- wird durch POST /sync oder Publish geschrieben
- enthält current_revision_id und Zähler/Aggregate
- enthält Revisionen und Child Rows
- wird nicht durch GET /scan verändert
```

### 3.3 Draft State

Drafts sind Arbeitszustand für Generator/Edit/Publish.

Tabellen:

```text
creative_library_drafts
creative_library_draft_variants
creative_library_draft_assets
creative_library_draft_documents
creative_library_draft_validation_issues
creative_library_draft_audit_events
```

Eigenschaften:

```text
- nicht automatisch published
- darf unfertig/invalid sein
- kann später in Published Payload umgewandelt werden
- getrennt von System-Library und User Collections
```

### 3.4 Definitions State

Definitionen beschreiben fachliche Kataloge:

```text
variables
units
materials
document_types
object_kinds
family_profiles
variant_profiles
profile_bindings
```

Es gibt zwei Ebenen:

```text
1. JSON-Seeds unter src/library/definitions/data/*.json
2. Persistierte Definitionen in PostgreSQL über models/library_definitions.py
```

### 3.5 Taxonomy State

Taxonomie beschreibt:

```text
domain -> category -> subcategory
```

Sie existiert in:

```text
src/library/taxonomy/data/taxonomy.v1.json
models/library_taxonomy.py
```

Aktuell ist die Taxonomie Backend-kanonisch. Der Create-Wizard und der Scan sollen Taxonomie nicht hardcoden.

### 3.6 User State

User-spezifische Dinge liegen separat:

```text
creative_library_collections
creative_library_collection_items
creative_library_user_overrides
creative_library_user_audit_events
user_inventory_state
user_inventory_slots
```

Phase 1:

```text
user_id = 1
Hotbar Slots = 9
```

---

## 4. Gesamtarchitektur als Schichtenmodell

```text
HTTP / Flask
  routes/*.py
  src/routes/__init__.py
      ↓
Route Services / API-near Services
  src/services/library_route_service.py
  src/services/library_create_route_service.py
      ↓
Fachliche Library Services
  src/library/services/library_scan_service.py
  src/library/services/library_db_sync_service.py
  src/library/services/creative_library_service.py
  src/library/services/creative_library_draft_service.py
  src/library/services/creative_library_user_service.py
  src/library/services/library_definition_catalog_service.py
  src/library/services/library_file_service.py
  src/library/services/library_taxonomy_user_service.py
      ↓
Repositories
  src/library/repositories/*.py
      ↓
SQLAlchemy Models
  models/*.py
      ↓
PostgreSQL
```

### 4.1 Read-/Write-Trennung

```text
GET /api/v1/vplib/library/scan
  -> read-only
  -> liest source directory
  -> schreibt nicht DB

POST /api/v1/vplib/library/sync
  -> write
  -> scannt oder nimmt ScanResult entgegen
  -> schreibt Published DB

GET /api/v1/vplib/library/published
GET /api/v1/vplib/library/items
GET /api/v1/vplib/library/blocks
GET /api/v1/vplib/library/tree
  -> read
  -> liest Published DB
```

### 4.2 Warum diese Trennung wichtig ist

```text
- Scan kann beliebig oft ausgeführt werden, ohne DB-Zustand zu ändern.
- Sync ist explizit und nachvollziehbar.
- Tests können zuerst /scan prüfen und danach /sync.
- Published API ist stabil, auch wenn Source-Dateien temporär kaputt sind.
- Drafts können invalid sein, ohne produktive Library zu beschädigen.
```

---

## 5. Ordner- und Filestruktur

Aktuelle Zielstruktur von `src/library`:

```text
services/vectoplan-library/src/library/
│
├── __init__.py
│
├── definitions/
│   ├── __init__.py
│   ├── definition_models.py
│   ├── definition_registry.py
│   ├── definition_service.py
│   └── data/
│       ├── document_types.v1.json
│       ├── family_profiles.v1.json
│       ├── materials.v1.json
│       ├── object_kinds.v1.json
│       ├── profile_bindings.v1.json
│       ├── units.v1.json
│       ├── variables.v1.json
│       └── variant_profiles.v1.json
│
├── taxonomy/
│   ├── __init__.py
│   ├── taxonomy_models.py
│   ├── taxonomy_registry.py
│   ├── taxonomy_validator.py
│   ├── taxonomy_service.py
│   └── data/
│       └── taxonomy.v1.json
│
├── scanner/
│   ├── __init__.py
│   ├── package_discovery.py
│   ├── package_reader.py
│   └── package_fingerprint.py
│
├── validation/
│   ├── __init__.py
│   └── library_package_validator.py
│
├── domain/
│   ├── __init__.py
│   ├── library_item.py
│   ├── library_detail.py
│   ├── scan_result.py
│   ├── sync_result.py
│   ├── publication.py
│   └── inventory.py
│
├── read_models/
│   ├── __init__.py
│   ├── block_summary_builder.py
│   ├── block_detail_builder.py
│   ├── library_index_builder.py
│   ├── db_block_summary_builder.py
│   ├── db_block_detail_builder.py
│   ├── db_library_tree_builder.py
│   └── db_inventory_builder.py
│
├── services/
│   ├── __init__.py
│   ├── library_scan_service.py
│   ├── library_block_service.py
│   ├── library_create_service.py
│   ├── library_db_sync_service.py
│   ├── creative_library_service.py
│   ├── creative_library_draft_service.py
│   ├── creative_library_user_service.py
│   ├── library_definition_catalog_service.py
│   ├── library_definition_seed_service.py
│   ├── library_file_service.py
│   └── library_taxonomy_user_service.py
│
├── repositories/
│   ├── __init__.py
│   ├── creative_library_repository.py
│   ├── creative_library_draft_repository.py
│   ├── creative_library_user_repository.py
│   ├── library_definition_repository.py
│   ├── library_file_repository.py
│   ├── library_taxonomy_repository.py
│   └── sql/                         # legacy/compatibility, falls vorhanden
│       ├── __init__.py
│       └── creative_library_repository.py
│
└── source/
    └── {domain}/{category}/{subcategory}/{family_slug}/
```

Wichtig: In deinem Projekt können alte und neue Pfade parallel existieren. Die neue Richtung ist:

```text
src/library/repositories/creative_library_repository.py
src/library/services/creative_library_service.py
routes/library_routes.py
```

Ältere Dokumentation oder alte APIs können noch auf diese Pfade zeigen:

```text
src/library/repositories/sql/creative_library_repository.py
routes/api.py
library_published_service.py
```

Diese Legacy-Pfade sind nicht automatisch falsch; sie müssen aber sauber als Compatibility-Layer verstanden werden.

---

## 6. Ordner `definitions/`

### 6.1 Zweck

`definitions/` enthält fachliche Definitionen für Create, Validation und UI-Optionen.

Beispiele:

```text
- Welche Object-Kinds gibt es?
- Welche Family-Profile existieren?
- Welche Variant-Profile existieren?
- Welche Einheiten sind erlaubt?
- Welche Materialien sind bekannt?
- Welche Dokumenttypen gibt es?
- Welche Variablen sind technisch/fachlich bekannt?
- Welche Profile binden welche Variablen?
```

### 6.2 Dateien

#### `definition_models.py`

Dataclass-/Domain-Modelle für die Definitionsschicht.

Typische Konzepte:

```text
DefinitionDataset
DefinitionVariable
DefinitionUnit
DefinitionMaterial
DefinitionDocumentType
DefinitionObjectKind
DefinitionFamilyProfile
DefinitionVariantProfile
DefinitionProfileBinding
```

#### `definition_registry.py`

Lädt JSON-Dateien aus:

```text
src/library/definitions/data/*.json
```

Aufgaben:

```text
- JSON lesen
- Einträge normalisieren
- Lookup nach key/id bereitstellen
- Registry-Health liefern
```

Keine Aufgaben:

```text
- keine DB-Writes
- keine Flask-Routen
- keine UI-Logik
```

#### `definition_service.py`

Service über der Registry.

Aufgaben:

```text
- Create-Optionen erzeugen
- Profile auflösen
- Profile-Bindings auswerten
- Definitionen API-fähig serialisieren
```

### 6.3 Neue DB-backed Definition-Schicht

Zusätzlich existieren neue Dateien außerhalb von `definitions/`:

```text
models/library_definitions.py
src/library/repositories/library_definition_repository.py
src/library/services/library_definition_catalog_service.py
src/library/services/library_definition_seed_service.py
routes/library_definition_routes.py
```

Zusammenhang:

```text
JSON Seed Files
  -> library_definition_seed_service
  -> library_definition_repository
  -> PostgreSQL definition tables
  -> library_definition_catalog_service
  -> /api/v1/vplib/definitions/*
  -> /api/v1/vplib/create/options
```

### 6.4 Typische Routen

```text
GET  /api/v1/vplib/definitions/health
GET  /api/v1/vplib/definitions/catalog
GET  /api/v1/vplib/definitions/current
GET  /api/v1/vplib/definitions/create-options
GET  /api/v1/vplib/definitions/create-context
GET  /api/v1/vplib/definitions/datasets
POST /api/v1/vplib/definitions/seed/preview
POST /api/v1/vplib/definitions/seed
```

---

## 7. Ordner `taxonomy/`

### 7.1 Zweck

Taxonomie ist die kanonische Struktur für Library-Pfade und UI-Kategorien.

```text
domain -> category -> subcategory
```

Beispiel:

```text
hochbau -> bloecke -> basis
```

### 7.2 Dateien

#### `taxonomy_models.py`

Modelle für:

```text
TaxonomyNode
TaxonomyDomain
TaxonomyCategory
TaxonomySubcategory
TaxonomySelection
TaxonomyPath
TaxonomyValidationResult
```

#### `taxonomy_registry.py`

Lädt:

```text
src/library/taxonomy/data/taxonomy.v1.json
```

Aufgaben:

```text
- Registry aufbauen
- IDs normalisieren
- Parent/Child-Zusammenhänge liefern
- Lookup für domain/category/subcategory
```

#### `taxonomy_validator.py`

Validiert:

```text
- existiert domain?
- existiert category unter domain?
- existiert subcategory unter category?
- passt Source-Pfad zur Classification?
- ist Legacy-Pfad erlaubt?
- passt object_kind zur Taxonomie?
```

#### `taxonomy_service.py`

Fassade für Routen und Services:

```text
- get_create_options_payload
- validate_selection
- health
- clear_cache
- Taxonomie-Tree liefern
```

### 7.3 DB-backed Taxonomy-Schicht

Neue persistente Taxonomie-User-/Override-Schicht:

```text
models/library_taxonomy.py
src/library/repositories/library_taxonomy_repository.py
src/library/services/library_taxonomy_user_service.py
routes/taxonomy.py
```

Aufgaben:

```text
- System-Taxonomie lesen
- User-Taxonomie/Overrides verwalten
- Resolved Taxonomy erzeugen
- Audit Events schreiben
```

Typische Routen:

```text
GET /api/v1/vplib/taxonomy/health
GET /api/v1/vplib/taxonomy/routes
GET /api/v1/vplib/taxonomy/resolved
GET /api/v1/vplib/taxonomy/tree
GET /api/v1/vplib/taxonomy/nodes
GET /api/v1/vplib/taxonomy/create-options
```

---

## 8. Ordner `scanner/`

### 8.1 Zweck

`scanner/` liest die dateibasierte Source-Library.

Es schreibt nicht in die DB und verändert keine Source-Dateien.

Pipeline:

```text
source root
  -> package_discovery
  -> package_reader
  -> package_fingerprint
```

### 8.2 `package_discovery.py`

Findet VPLIB Directory Packages.

Aufgaben:

```text
- source root durchlaufen
- Kandidaten erkennen
- canonical layout erkennen
- legacy layout erkennen
- path classification ableiten
- PackageCandidate-ähnliche Objekte erzeugen
```

Canonical Layout:

```text
source/{domain}/{category}/{subcategory}/{family_slug}/
```

Legacy Layout kann noch vorkommen:

```text
source/{domain}/{category}/{family_slug}/
```

### 8.3 `package_reader.py`

Liest Dokumente eines Kandidaten.

Aufgaben:

```text
- JSON-Dateien lesen
- manifest finden
- identity/classification finden
- Module und Varianten lesen
- ReadResult erzeugen
```

Wichtige Dokumente:

```text
vplib.manifest.json
vplib.modules.json
family/identity.json
family/classification.json
editor/inventory.json
variants/index.json
variants/default.json
```

### 8.4 `package_fingerprint.py`

Erzeugt `revision_hash`.

Aufgaben:

```text
- gelesene Dokumente stabil serialisieren
- Inhaltsfingerprint erzeugen
- Revisionserkennung ermöglichen
```

Regel:

```text
Gleicher revision_hash = gleicher Inhaltsstand.
Geänderter revision_hash = neue Revision möglich.
```

---

## 9. Ordner `validation/`

### 9.1 Zweck

`validation/` prüft, ob ein gelesenes Package fachlich publishbar ist.

### 9.2 `library_package_validator.py`

Prüft typischerweise:

```text
- manifest vorhanden
- vplib_uid vorhanden
- family_id vorhanden
- package_id vorhanden
- classification vorhanden
- domain/category/subcategory gültig
- Varianten lesbar
- relevante Dokumente vorhanden
- object_kind bekannt
- Profile/Definitionen konsistent
```

### 9.3 Verhältnis zu Scanner

Scanner beantwortet:

```text
Kann ich das Package finden und lesen?
```

Validator beantwortet:

```text
Darf dieses Package in die Creative Library published werden?
```

### 9.4 Verhältnis zu DB-Sync

DB-Sync nutzt Validation-Ergebnis:

```text
valid + vplib_uid + revision_hash
  -> publishbar

invalid oder missing vplib_uid
  -> Issue speichern / Kandidat skippen
```

---

## 10. Ordner `domain/`

### 10.1 Zweck

`domain/` enthält API-nahe, fachliche Datenmodelle. Diese Modelle sollen möglichst unabhängig von Flask und SQLAlchemy bleiben.

### 10.2 `library_item.py`

Dateibasierte Summary-Modelle.

Typische Inhalte:

```text
LibraryItem
Classification
ValidationSummary
AssetRefs
```

Verwendung:

```text
- /scan source=file
- /blocks source=file
- filesystem debug path
```

### 10.3 `library_detail.py`

Dateibasierte Detailansicht.

Typische Inhalte:

```text
LibraryItemDetail
VariantDetail
ModuleDetail
DocumentEntry
```

### 10.4 `scan_result.py`

Domain für Scan-Ergebnisse.

Typische Inhalte:

```text
LibraryScanResult
LibraryScanCandidate
ScanStats
ScanMessage
DuplicateId
```

### 10.5 `sync_result.py`

Domain für DB-Sync-Ergebnisse.

Typische Inhalte:

```text
LibrarySyncResult
LibrarySyncCandidateResult
LibrarySyncIssue
LibrarySyncOperationResult
LibrarySyncStats
LibrarySyncRunInfo
```

Wichtig:

```text
- darf nicht rekursiv riesige ORM-/Scan-Objekte serialisieren
- sollte kompakte to_dict()-Methoden liefern
- ist API-Antwort-nah
```

### 10.6 `publication.py`

Domain für Published-DB-Readmodelle.

Typische Inhalte:

```text
PublishedFamilySummary
PublishedFamilyDetail
PublishedVariantSummary
PublishedAssetRef
PublishedRevisionSummary
PublishedValidationSummary
PublishedLibraryStats
PublishedLibraryListResult
```

### 10.7 `inventory.py`

Domain für Inventory-/Hotbar-Zustand.

Typische Inhalte:

```text
InventoryState
InventorySlot
InventoryVariantRef
InventoryAssetRef
InventoryPlacementInfo
InventoryStats
```

---

## 11. Ordner `read_models/`

### 11.1 Zweck

`read_models/` übersetzt interne Scan- oder DB-Daten in API-nahe Antwortformen.

Es gibt zwei Richtungen:

```text
1. Filesystem Read-Models
   ScanResult/ReadResults -> Blocks/Tree/Detail

2. DB Read-Models
   Published DB Rows -> Blocks/Tree/Detail/Inventory
```

### 11.2 Filesystem Builder

#### `block_summary_builder.py`

Baut Block-Summaries aus Scan-/Read-Ergebnissen.

#### `block_detail_builder.py`

Baut Detailansichten aus dateibasierten Dokumenten.

#### `library_index_builder.py`

Baut In-Memory-Index:

```text
items
items_by_id
tree
duplicate ids
stats
```

### 11.3 DB Builder

#### `db_block_summary_builder.py`

Baut DB-basierte Blocks-Liste.

Input:

```text
CreativeLibraryItem rows / repository payloads
```

Output:

```text
items[] mit id, label, family_id, vplib_uid, counts, taxonomy
```

#### `db_block_detail_builder.py`

Baut Detailansicht aus Published DB.

Input:

```text
item + current revision + variants + assets + documents
```

Output:

```text
summary
revision
variants
assets
documents
metadata
```

#### `db_library_tree_builder.py`

Baut Tree:

```text
root
└── domain
    └── category
        └── subcategory
            └── item refs
```

#### `db_inventory_builder.py`

Baut Inventory-Zustand aus:

```text
- echten inventory slot rows
- oder Fallback aus published families
```

---

## 12. Ordner `services/`

### 12.1 Zweck

`services/` orchestriert fachliche Abläufe. Services sprechen Repositories, Scanner, Validatoren und Read-Models an.

Services sind keine Flask-Routen und sollten keine Tabellen definieren.

### 12.2 `library_scan_service.py`

Orchestriert read-only Scan.

Pipeline:

```text
resolve source root
  -> taxonomy health/payload
  -> package discovery
  -> package reader
  -> package validation
  -> package fingerprint
  -> library items
  -> library index
  -> scan/tree/blocks response
```

Wichtige Public API:

```text
scan_library_source()
scan_library_source_no_cache()
get_library_scan_response()
get_library_blocks_response()
get_library_tree_response()
get_library_index()
get_library_sync_preview_response()
get_library_scan_service_health()
clear_library_scan_cache()
```

Garantien:

```text
- keine DB-Writes
- kein Schreiben in source
- Cache nur in-memory
- Optionen robust aus dict/dataclass/Namespace
```

### 12.3 `library_block_service.py`

Compatibility-/Filesystem-Debug-Service für:

```text
- blocks list
- block detail
- variants
- tree
```

Wird besonders für `source=file` oder legacy/debug genutzt.

### 12.4 `library_db_sync_service.py`

Persistenz-Entry-Point für Source/ScanResult -> DB.

Ablauf:

```text
sync_library_source()
  -> scan_library_source()
  -> extract candidates
  -> build publish payload per candidate
  -> CreativeLibraryService.publish_bundle()
     oder Repository-Fallback
  -> ScanRun/Issues/Stats
```

Wichtige Public API:

```text
sync_library_to_db()
sync_library_to_database_response()
sync_scan_result_to_db()
get_library_db_sync_service_health()
assert_library_db_sync_service_ready()
clear_library_db_sync_service_caches()
```

Regeln:

```text
- erzeugt keine vplib_uid
- repariert keine fehlende vplib_uid
- fehlende vplib_uid = Issue/Skip
- source scan + write nur bei POST /sync
```

### 12.5 `creative_library_service.py`

Published-DB-Service.

Aufgaben:

```text
- Published Library lesen
- Items lesen
- Revisions/Variants/Assets/Documents lesen
- Publish Bundle in DB schreiben
- ScanRuns/Issues verwalten
- Inventory Slots verwalten
```

Wichtige Public API:

```text
get_library()
list_items()
get_item()
get_item_by_vplib_uid()
list_revisions()
list_variants()
list_assets()
list_documents()
publish_bundle()
sync_package_payload()
start_scan_run()
finish_scan_run()
record_scan_issue()
list_scan_runs()
list_scan_issues()
list_inventory_slots()
set_inventory_slot()
clear_inventory_slot()
get_health()
```

### 12.6 `creative_library_draft_service.py`

Draft Working State.

Aufgaben:

```text
- Draft anlegen
- Draft lesen/aktualisieren
- Varianten/Assets/Dokumente am Draft verwalten
- Draft validieren
- Publish vorbereiten
- Publish-Service optional aufrufen
```

Routen:

```text
/api/v1/vplib/library/drafts/*
```

### 12.7 `creative_library_user_service.py`

User-spezifische Library-Schicht.

Aufgaben:

```text
- Collections
- Collection Items
- User Overrides
- Resolved Library pro User
- Inventory-nahe User-Sichten
```

Routen:

```text
/api/v1/vplib/creative-library/*
```

### 12.8 `library_definition_catalog_service.py`

DB-/Registry-backed Definitions-Service.

Aufgaben:

```text
- aktuellen Catalog liefern
- Definition nach key/id liefern
- Create Options liefern
- Create Context liefern
- Profile/Binding auflösen
- Health liefern
```

### 12.9 `library_definition_seed_service.py`

Seed-Service.

Aufgaben:

```text
- JSON-Dateien unter definitions/data lesen
- Validierung/Preview
- idempotent in DB schreiben
```

### 12.10 `library_file_service.py`

File-/Upload-Service.

Aufgaben:

```text
- Upload-Metadaten normalisieren
- Storage-Ziel bestimmen
- Datei-/Version-/Link-Datensätze verwalten
- Upload-Constraints liefern
```

### 12.11 `library_taxonomy_user_service.py`

Service über Taxonomy Repository.

Aufgaben:

```text
- resolved taxonomy
- nodes create/update/delete/restore/move/reorder
- overrides
- audit
```

### 12.12 `library_create_service.py`

Create-Service für neue Packages.

Aufgaben:

```text
- Create Options
- Create Context
- Draft Payload bauen
- Draft validieren
- Package Plan bauen
- .vplib Archive bauen
- Source Package speichern, wenn Write Mode aktiv
- Persistent Draft Payload bauen
- Publish Bundle aus Create Payload bauen
```

---

## 13. Ordner `repositories/`

### 13.1 Zweck

Repositories kapseln Datenbankzugriffe. Sie kennen SQLAlchemy-Models und Session, aber keine Flask-Routen und keine Scannerlogik.

### 13.2 Grundregeln

```text
- keine Flask-Imports
- keine Response-Objekte
- keine Source-Discovery
- kein db.create_all()
- keine Migration
- commit optional
- flush bei IDs, wenn commit=False
```

### 13.3 `creative_library_repository.py`

Repository für Published Creative Library.

Tabellen:

```text
creative_library_items
creative_library_revisions
creative_library_variants
creative_library_assets
creative_library_documents
creative_library_scan_runs
creative_library_scan_issues
creative_library_inventory_slots
```

Aufgaben:

```text
- Items upserten
- Revisions erzeugen/current setzen
- Varianten erzeugen/upserten
- Assets/Dokumente erzeugen
- ScanRuns starten/beenden
- Issues speichern
- Published payloads lesen
- Inventory Slots lesen/setzen
```

### 13.4 `creative_library_draft_repository.py`

Repository für Draft Working State.

Tabellen:

```text
creative_library_drafts
creative_library_draft_variants
creative_library_draft_assets
creative_library_draft_documents
creative_library_draft_validation_issues
creative_library_draft_audit_events
```

### 13.5 `creative_library_user_repository.py`

Repository für User Collections/Overrides.

Tabellen:

```text
creative_library_collections
creative_library_collection_items
creative_library_user_overrides
creative_library_user_audit_events
```

### 13.6 `library_definition_repository.py`

Repository für Definitions-Catalog.

Tabellen aus:

```text
models/library_definitions.py
```

### 13.7 `library_file_repository.py`

Repository für Uploads und Datei-Verknüpfungen.

Tabellen:

```text
library_files
library_file_versions
library_file_links
library_file_audit_events
```

### 13.8 `library_taxonomy_repository.py`

Repository für Taxonomie-Nodes, Overrides und Audit.

Tabellen:

```text
library_taxonomy_nodes
library_taxonomy_overrides
library_taxonomy_audit_events
```

---

## 14. Ordner `source/`

### 14.1 Zweck

`source/` enthält echte VPLIB Directory Packages.

Beispiel:

```text
src/library/source/hochbau/bloecke/basis/basic_stone_block/
```

### 14.2 Erwartete Kerndokumente

```text
vplib.manifest.json
vplib.modules.json
family/identity.json
family/classification.json
editor/inventory.json
variants/index.json
variants/default.json
```

### 14.3 Was wird daraus gelesen?

```text
vplib_uid
family_id
package_id
object_kind
domain/category/subcategory
variant_ids
revision_hash
metadata
documents
assets
```

### 14.4 Legacy-Pfade

Ältere Pakete können in Tiefe 3 liegen:

```text
source/hochbau/bloecke/basic_stone_block/
```

Wenn `family/classification.json` `subcategory=basis` enthält, kann der DB-Tree trotzdem korrekt einsortieren.

Ziel für neue Pakete:

```text
source/hochbau/bloecke/basis/basic_stone_block/
```

---

## 15. Wichtige Außenkanten außerhalb von `src/library`

### 15.1 `models/`

Wichtige Model-Dateien:

```text
models/creative_library.py
models/creative_library_drafts.py
models/creative_library_user.py
models/library_definitions.py
models/library_files.py
models/library_taxonomy.py
models/user_inventory.py
models/__init__.py
```

#### `models/creative_library.py`

Published Creative Library.

Wichtige Tabellen:

```text
CreativeLibraryItem
CreativeLibraryRevision
CreativeLibraryVariant
CreativeLibraryAsset
CreativeLibraryDocument
CreativeLibraryScanRun
CreativeLibraryScanIssue
CreativeLibraryInventorySlot
```

Wichtigster letzter Fix:

```text
Zyklische FKs zu Draft-Tabellen use_alter=True.
```

#### `models/creative_library_drafts.py`

Draft Working State.

Wichtigster letzter Fix:

```text
Optionale Rückverweise auf Published-Tabellen use_alter=True.
```

### 15.2 `routes/`

Wichtige Routen:

```text
routes/library_routes.py
routes/library_definition_routes.py
routes/taxonomy.py
routes/create.py
```

### 15.3 `src/routes/`

Blueprint Registry:

```text
src/routes/__init__.py
```

Aufgaben:

```text
- Blueprints lazy importieren
- Required/optional Blueprints unterscheiden
- Aliase wie bp/blueprint unterstützen
- Health/Registry-Info liefern
```

### 15.4 `src/services/`

Route-nahe Services außerhalb von `src/library`:

```text
src/services/library_route_service.py
src/services/library_create_route_service.py
src/services/library_create_variant_payload_service.py
```

Diese liegen außerhalb von `src/library`, weil sie HTTP-/Route-nahe Adapter sind.

---

## 16. Datenbankmodell und Tabellenfamilien

### 16.1 Published Library

```text
creative_library_items
  ein veröffentlichter Family-/Block-Kopf

creative_library_revisions
  versionierter Inhaltsstand eines Items

creative_library_variants
  Varianten einer Revision/eines Items

creative_library_assets
  Asset-Metadaten einer Revision/eines Items

creative_library_documents
  Dokumentzeilen einer Revision/eines Items

creative_library_scan_runs
  Sync-/Scan-Run-Protokoll

creative_library_scan_issues
  Fehler/Warnungen aus Scan/Sync

creative_library_inventory_slots
  einfache Hotbar-/Slot-Brücke
```

### 16.2 Draft Library

```text
creative_library_drafts
creative_library_draft_variants
creative_library_draft_assets
creative_library_draft_documents
creative_library_draft_validation_issues
creative_library_draft_audit_events
```

### 16.3 User Library

```text
creative_library_collections
creative_library_collection_items
creative_library_user_overrides
creative_library_user_audit_events
```

### 16.4 Definitions

```text
library_definition_datasets
library_definition_seed_runs
library_definition_variables
library_definition_units
library_definition_materials
library_definition_document_types
library_definition_object_kinds
library_definition_family_profiles
library_definition_variant_profiles
library_definition_profile_bindings
library_definition_overrides
```

### 16.5 Files

```text
library_files
library_file_versions
library_file_links
library_file_audit_events
```

### 16.6 Taxonomy

```text
library_taxonomy_nodes
library_taxonomy_overrides
library_taxonomy_audit_events
```

---

## 17. Hauptdatenflüsse

### 17.1 Dateibasierter Scan

```text
GET /api/v1/vplib/library/scan?source=file
  ↓
routes/library_routes.py
  ↓
src/services/library_route_service.py
  ↓
src/library/services/library_scan_service.py
  ↓
scanner/package_discovery.py
  ↓
scanner/package_reader.py
  ↓
validation/library_package_validator.py
  ↓
scanner/package_fingerprint.py
  ↓
read_models/library_index_builder.py
  ↓
JSON Response
```

Eigenschaften:

```text
- schreibt nicht DB
- eignet sich für Debug
- zeigt, ob Source-Pakete lesbar sind
```

### 17.2 DB-Sync aus Source

```text
POST /api/v1/vplib/library/sync
  ↓
routes/library_routes.py
  ↓
src/library/services/library_db_sync_service.py
  ↓
src/library/services/library_scan_service.py
  ↓
build publish payloads
  ↓
src/library/services/creative_library_service.py
  ↓
src/library/repositories/creative_library_repository.py
  ↓
models/creative_library.py
  ↓
PostgreSQL
```

Eigenschaften:

```text
- expliziter Write
- scannt oder nimmt ScanResult entgegen
- erzeugt ScanRun/Issues
- upsertet Items
- erzeugt Revisionen
- schreibt Varianten/Assets/Dokumente
```

### 17.3 Published Library Read

```text
GET /api/v1/vplib/library/published
GET /api/v1/vplib/library/items
GET /api/v1/vplib/library/blocks
GET /api/v1/vplib/library/tree
  ↓
routes/library_routes.py
  ↓
creative_library_service.py
  ↓
creative_library_repository.py
  ↓
PostgreSQL
  ↓
Read-Model / API Response
```

### 17.4 Create Flow

```text
POST /api/v1/vplib/create/draft
  ↓
routes/create.py
  ↓
src/services/library_create_route_service.py
  ↓
src/services/library_create_variant_payload_service.py
  ↓
src/library/services/library_create_service.py
  ↓
CreateResult / PackagePlan / Archive / PersistentDraftPayload
```

### 17.5 Draft Publish Prepare

```text
POST /api/v1/vplib/library/drafts/<draft_ref>/publish/prepare
  ↓
creative_library_draft_routes.py
  ↓
creative_library_draft_service.py
  ↓
build publish payload
  ↓
optional creative_library_service.publish_bundle()
```

---

## 18. API-Routen und Verantwortlichkeiten

### 18.1 Library Core

```text
GET  /api/v1/vplib/library/health
GET  /api/v1/vplib/library/routes
GET  /api/v1/vplib/library/selftest
GET  /api/v1/vplib/library/scan
POST /api/v1/vplib/library/sync
GET  /api/v1/vplib/library/blocks
GET  /api/v1/vplib/library/blocks/<block_id>
GET  /api/v1/vplib/library/blocks/<block_id>/variants
GET  /api/v1/vplib/library/tree
GET  /api/v1/vplib/library/published
GET  /api/v1/vplib/library/items
GET  /api/v1/vplib/library/items/<item_ref>
GET  /api/v1/vplib/library/scan-runs
GET  /api/v1/vplib/library/inventory/slots
```

### 18.2 Definitions

```text
GET  /api/v1/vplib/definitions/health
GET  /api/v1/vplib/definitions/routes
GET  /api/v1/vplib/definitions/catalog
GET  /api/v1/vplib/definitions/current
GET  /api/v1/vplib/definitions/create-options
GET  /api/v1/vplib/definitions/create-context
POST /api/v1/vplib/definitions/seed/preview
POST /api/v1/vplib/definitions/seed
```

### 18.3 Taxonomy

```text
GET /api/v1/vplib/taxonomy/health
GET /api/v1/vplib/taxonomy/routes
GET /api/v1/vplib/taxonomy/resolved
GET /api/v1/vplib/taxonomy/tree
GET /api/v1/vplib/taxonomy/nodes
GET /api/v1/vplib/taxonomy/create-options
```

### 18.4 Files

```text
GET  /api/v1/vplib/files/health
GET  /api/v1/vplib/files/routes
GET  /api/v1/vplib/files/constraints
GET  /api/v1/vplib/files
GET  /api/v1/vplib/files/links
GET  /api/v1/vplib/files/context
POST /api/v1/vplib/files/upload
```

### 18.5 Drafts

```text
GET  /api/v1/vplib/library/drafts/health
GET  /api/v1/vplib/library/drafts/routes
GET  /api/v1/vplib/library/drafts
POST /api/v1/vplib/library/drafts
GET  /api/v1/vplib/library/drafts/<draft_ref>
PATCH/PUT /api/v1/vplib/library/drafts/<draft_ref>
POST /api/v1/vplib/library/drafts/<draft_ref>/validate
POST /api/v1/vplib/library/drafts/<draft_ref>/publish/prepare
POST /api/v1/vplib/library/drafts/<draft_ref>/publish
```

### 18.6 Create

```text
GET  /api/v1/vplib/create/health
GET  /api/v1/vplib/create/options
GET  /api/v1/vplib/create/context
POST /api/v1/vplib/create/draft
POST /api/v1/vplib/create/validate
POST /api/v1/vplib/create/package-plan
POST /api/v1/vplib/create/download
POST /api/v1/vplib/create/save
```

### 18.7 User Creative Library

```text
GET  /api/v1/vplib/creative-library/health
GET  /api/v1/vplib/creative-library/routes
GET  /api/v1/vplib/creative-library/resolved
GET  /api/v1/vplib/creative-library/inventory
GET  /api/v1/vplib/creative-library/defaults
GET  /api/v1/vplib/creative-library/collections
POST /api/v1/vplib/creative-library/collections
```

---

## 19. Create-, Draft-, Publish- und Sync-Zusammenhang

### 19.1 Create ohne Persistenz

```text
/create Payload
  -> normalize_create_variant_payload
  -> build_draft
  -> validate
  -> package-plan
  -> download
```

Das erzeugt noch keinen Published DB State.

### 19.2 Create mit Source Save

```text
/create Payload
  -> build Package Documents
  -> save_package
  -> src/library/source/...
```

Danach ist ein expliziter Sync nötig:

```text
POST /api/v1/vplib/library/sync
```

### 19.3 Create mit Persistent Draft

```text
/create Payload
  -> build_persistent_draft_payload
  -> creative_library_draft_service.create_draft
  -> draft tables
```

### 19.4 Draft Publish

```text
Draft
  -> validate
  -> prepare publish payload
  -> publish_bundle
  -> published tables
```

### 19.5 Source Sync

```text
src/library/source Package
  -> scan
  -> build publish payload
  -> publish_bundle
  -> published tables
```

### 19.6 Warum beides existiert

```text
Create/Draft ist der Bearbeitungs- und Generatorpfad.
Source/Sync ist der repo- und filesystembasierte Publishingpfad.
Published DB ist der produktive Lesepfad.
```

---

## 20. Files-/Upload-Schicht

### 20.1 Zweck

Die File-Schicht verwaltet Uploads, Versionen und Links.

```text
LibraryFile
LibraryFileVersion
LibraryFileLink
LibraryFileAuditEvent
```

### 20.2 Warum getrennt von Creative Library?

Creative Library Items referenzieren fachliche Dokumente/Assets. Die File-Schicht verwaltet technische Upload-Metadaten.

```text
library_files
  technische Datei

creative_library_documents/assets
  fachliche Einbindung in Library Item/Revision/Variant
```

### 20.3 Große 3D-Modelle

Regel:

```text
Große 3D-Modelle nicht primär als bytea speichern.
Stattdessen Storage/Object-Store/Local Storage + Metadaten verwenden.
```

---

## 21. User-Library, Collections und Inventory

### 21.1 System Library vs User Library

```text
System Library
  Published Creative Library aus DB

User Library
  Collections, Overrides, User Inventory
```

### 21.2 Collections

```text
CreativeLibraryCollection
CreativeLibraryCollectionItem
```

Nutzung:

```text
- Favoriten
- eigene Gruppen
- projektspezifische Sammlungen
```

### 21.3 User Overrides

```text
CreativeLibraryUserOverride
```

Kann überschreiben:

```text
- Label
- Sichtbarkeit
- Sortierung
- Metadaten
- evtl. Default-Auswahl
```

### 21.4 Inventory

Phase 1:

```text
user_id = 1
slot_count = 9
```

Inventory ist bewusst getrennt von Published Library, damit User-Zustand nicht die System-Library verändert.

---

## 22. Cache-, Health- und Diagnostics-Konzept

### 22.1 Health-Routen

Health soll prüfen:

```text
- Importierbarkeit
- verfügbare Dependencies
- optionale Subhealth
- DB Session optional
- keine schweren Scans beim Import
```

Bereits getestet:

```text
/api/v1/vplib/library/health
/api/v1/vplib/definitions/health
/api/v1/vplib/files/health
/api/v1/vplib/taxonomy/health
/api/v1/vplib/creative-library/health
/api/v1/vplib/library/drafts/health
```

### 22.2 Cache Clear

Cache Clear soll nur Runtime-Caches leeren:

```text
- lazy import caches
- taxonomy caches
- scan caches
- definition catalog caches
```

Es soll keine DB-Daten löschen.

### 22.3 Lazy Imports

Viele Services verwenden lazy imports, damit:

```text
- Modulimport nicht sofort DB/Flask braucht
- Health kontrolliert Fehler anzeigen kann
- zirkuläre Imports reduziert werden
```

---

## 23. Teststrategie

### 23.1 Reihenfolge

1. Syntax/Import
2. Container Start
3. Migration/Alembic
4. Health-Routen
5. Source Scan
6. DB Sync
7. Published Reads
8. Detail/Variants/Documents
9. Draft/Create
10. User/Inventory

### 23.2 Minimaltests

```text
GET  /api/v1/vplib/library/health
GET  /api/v1/vplib/library/routes
GET  /api/v1/vplib/library/selftest
GET  /api/v1/vplib/library/scan?source=file
GET  /api/v1/vplib/library/blocks?source=file
GET  /api/v1/vplib/library/tree?source=file
POST /api/v1/vplib/library/sync
GET  /api/v1/vplib/library/published
GET  /api/v1/vplib/library/items
GET  /api/v1/vplib/library/blocks
GET  /api/v1/vplib/library/tree
```

### 23.3 Nach Sync testen

```text
GET /api/v1/vplib/library/published
GET /api/v1/vplib/library/items
GET /api/v1/vplib/library/blocks
GET /api/v1/vplib/library/tree
GET /api/v1/vplib/library/scan-runs
GET /api/v1/vplib/library/inventory/slots
```

### 23.4 Detailtests

```text
GET /api/v1/vplib/library/items/<item_ref>
GET /api/v1/vplib/library/items/<item_ref>/variants
GET /api/v1/vplib/library/items/<item_ref>/assets
GET /api/v1/vplib/library/items/<item_ref>/documents
GET /api/v1/vplib/library/vplib/<vplib_uid>
```

### 23.5 DB-Checks

```sql
select id, vplib_uid, family_id, package_id, current_revision_id,
       variant_count, asset_count, document_count, revision_count
from creative_library_items
order by id desc
limit 20;
```

```sql
select id, item_id, revision_id, vplib_uid, family_id,
       variant_id, label, is_default, status
from creative_library_variants
order by id;
```

---

## 24. Typische Fehlerbilder und Debug-Reihenfolge

### 24.1 Container unhealthy

Prüfen:

```text
- Model import error?
- Alembic migration error?
- Blueprint import error?
- DB connection error?
```

### 24.2 `relation does not exist` bei Migration

Wahrscheinliche Ursache:

```text
zyklische Foreign Keys
```

Fix:

```text
use_alter=True + fester Constraint-Name bei optionalen Rückverweisen
```

### 24.3 `name MAX_* is not defined`

Ursache:

```text
Model-Konstante fehlt.
```

Fix:

```text
Konstantenblock im Model ergänzen.
```

### 24.4 `/scan` geht, `/sync` nicht

Prüfen:

```text
- library_db_sync_service importierbar?
- creative_library_repository importierbar?
- fehlende vplib_uid?
- fehlender revision_hash?
- DB Session Rollback nach Fehler?
- SyncResult serialisiert zu große Objekte?
```

### 24.5 `/blocks` leer nach Sync

Prüfen:

```text
- creative_library_items enthält Rows?
- status/publication_status Filter?
- active/visible Flags?
- source=db oder source=file?
```

### 24.6 `/variants` leer, aber DB enthält Varianten

Wahrscheinlich:

```text
status != 'deleted' filtert NULL weg.
```

SQL-Regel:

```sql
status is null OR status != 'deleted'
```

### 24.7 `bigint = character varying`

Ursache:

```text
String-Identifier wurde gegen numeric id verglichen.
```

Fix:

```text
id nur vergleichen, wenn identifier numerisch ist.
```

---

## 25. Konventionen für neue Dateien und Erweiterungen

### 25.1 Neue Source Packages

Pfad:

```text
src/library/source/{domain}/{category}/{subcategory}/{family_slug}/
```

Pflicht:

```text
vplib.manifest.json mit vplib_uid
family/identity.json
family/classification.json
variants/index.json
mindestens eine Variant-Datei
```

### 25.2 Neue Definitionen

1. JSON unter `definitions/data/*.json` ergänzen.
2. Seed Preview testen.
3. Seed ausführen.
4. Create Options prüfen.

### 25.3 Neue Taxonomie

1. `taxonomy/data/taxonomy.v1.json` ergänzen.
2. Taxonomy Health testen.
3. Create Options prüfen.
4. Source Package in neue Taxonomie legen.
5. Scan und Sync testen.

### 25.4 Neue DB-Modelle

1. Model-Datei ergänzen.
2. `models/__init__.py` registrieren.
3. Importtest.
4. Migration erzeugen.
5. Migration prüfen.
6. Upgrade ausführen.

### 25.5 Neue Routen

1. Route-Datei erstellen.
2. Blueprint-Aliase exportieren:

```python
bp = your_blueprint
blueprint = your_blueprint
```

3. `src/routes/__init__.py` Registry ergänzen.
4. `/routes` und Health testen.

---

## 26. Offene Punkte / nächste Arbeit

### P0 – End-to-End Sync final testen

```text
POST /api/v1/vplib/library/sync
```

Erwartung:

```text
ok=true oder partial ohne Crash
kein Timeout
keine rekursive Serialisierung
ScanRun wird geschrieben
Items/Revisions/Variants/Documents werden geschrieben
```

### P0 – Wiederholter Sync idempotent

```text
Gleicher revision_hash darf keine neue Revision erzeugen.
```

### P1 – Published Detail und Child-Routen testen

```text
GET /api/v1/vplib/library/items/<item_ref>
GET /api/v1/vplib/library/items/<item_ref>/variants
GET /api/v1/vplib/library/items/<item_ref>/assets
GET /api/v1/vplib/library/items/<item_ref>/documents
```

### P1 – Definitions Seed testen

```text
POST /api/v1/vplib/definitions/seed/preview
POST /api/v1/vplib/definitions/seed
GET  /api/v1/vplib/definitions/catalog
```

### P1 – Draft Create/Validate testen

```text
POST /api/v1/vplib/library/drafts
POST /api/v1/vplib/library/drafts/<draft_ref>/validate
POST /api/v1/vplib/library/drafts/<draft_ref>/publish/prepare
```

### P2 – Source Layout vereinheitlichen

Legacy-Tiefe 3 auf kanonische Tiefe 4 migrieren.

### P2 – Startup-Warnungen bereinigen

Nicht blockierend, aber später säubern:

```text
- missing optional blueprints
- settings None warnings
- route root checks
```

---

## 27. Definition of Done

Der Abschnitt gilt als stabil, wenn:

```text
1. Container startet ohne unhealthy.
2. Alembic-Migrationen laufen durch.
3. /library/health ist ok.
4. /library/scan?source=file funktioniert.
5. /library/sync läuft ohne Timeout.
6. Wiederholter /sync erzeugt keine neue Revision bei gleichem revision_hash.
7. /library/published liefert DB-Daten.
8. /library/items liefert DB-Daten.
9. /library/blocks liefert DB-Daten.
10. /library/tree liefert DB-Daten.
11. Item Detail liefert current revision.
12. Variantenroute liefert gespeicherte Varianten.
13. Dokumentroute liefert gespeicherte Dokumente.
14. Inventory liefert sinnvolle Slots oder validen leeren Zustand.
15. Definitions Seed und Catalog funktionieren.
16. Create Options enthalten Taxonomie und Definitionen.
17. Draft Create/Validate/Prepare funktioniert.
18. Keine PostgreSQL-Session bleibt idle-in-transaction hängen.
19. Keine Route serialisiert rohe ORM- oder riesige ScanResult-Objekte rekursiv.
20. Source-of-Truth-Regeln sind eingehalten.
```

---

## Kurzfazit

`src/library` ist jetzt die zentrale fachliche Library-Schicht zwischen VPLIB-Core, Source-Dateien, PostgreSQL und API. Die wichtigsten Architekturentscheidungen sind:

```text
- source/ bleibt die lesbare Package-Quelle.
- /scan ist read-only.
- /sync ist der bewusste DB-Write-Pfad.
- Published DB ist der produktive Read-Pfad.
- Drafts sind Arbeitszustand.
- User Collections/Overrides sind getrennt vom Systemkatalog.
- Taxonomie und Definitionen sind Backend-kanonisch.
- vplib_uid wird nicht von der DB erzeugt.
```

Damit ist die Library-Schicht nicht mehr nur ein Datei-Katalog, sondern ein vollständiger Pipeline-Aufbau:

```text
Source Package
  -> Scan
  -> Validation
  -> Sync
  -> Published DB
  -> API Read Models
  -> Create/Draft/User-Erweiterungen
```
