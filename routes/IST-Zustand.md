# IST-Zustand – `services/vectoplan-library/routes`

Stand: **2026-06-28**  
Zielpfad im Projekt: `services/vectoplan-library/routes/IST-Zustand.md`  
Dokumenttyp: technischer IST-Stand für die komplette Flask-Routenschicht.

---

## 0. Kurzfazit

Der Ordner `routes/` ist die HTTP-Außenkante des `vectoplan-library` Service.  
Er verbindet Browser, Editor, Create UI, Creative Library, Taxonomie, Definition Catalog, File Uploads, Drafts und User-Inventar mit den Service- und Repository-Schichten.

Die wichtigste Regel bleibt:

```text
routes/*
  = HTTP-Adapter
  = Request lesen
  = Service aufrufen
  = Response serialisieren
  ≠ Business-Logik
  ≠ direkte SQLAlchemy-Queries
  ≠ db.create_all()
  ≠ Scanner-/Generator-/Repository-Implementierung
```

Aktuell enthält der Ordner **12 geprüfte Python-Dateien** mit insgesamt **230 erkannten Route-Decorators**.  
Die zentrale Registry ist `routes/__init__.py`; sie registriert Required- und Optional-Blueprints defensiv und speichert Metadaten in `app.extensions["vectoplan_library"]`.

---

## 1. Zielbild der Routenschicht

```text
HTTP / Browser / Editor / Frontend
  ↓
services/vectoplan-library/routes/*
  ↓
src/services/* oder src/library/services/*
  ↓
src/library/repositories/*
  ↓
models/*
  ↓
PostgreSQL / Source-Dateien / Storage
```

Die Routen sind bewusst nicht die fachliche Hauptlogik.  
Sie sind Adapter zwischen Flask und den fachlichen Services.

### 1.1 Zentrale Verantwortlichkeiten

```text
routes/__init__.py
  registriert Blueprints

routes/vplib_routes.py
  VPLIB Core: Health, Test, Create, Dry-Run

routes/library_routes.py
  kanonische Creative-Library API: Scan, Sync, Published Reads

routes/api.py
  ältere/kompatible Library API mit vollständigen Pfaden

routes/taxonomy.py
  Taxonomie API: legacy canonical + DB-backed User Taxonomy

routes/library_definition_routes.py
  Definition Catalog API

routes/library_files.py
  Upload/File/Version/Link API

routes/creative_library_user_routes.py
  User-spezifische Creative-Library Collections/Overrides

routes/creative_library_draft_routes.py
  Persistent Drafts / Generator-Arbeitsstände

routes/create.py
  Create UI + Create API + optional persistente Drafts

routes/inventar.py
  HTML-Seiten /user-inventar und /creative-inventar

routes/inventar_user.py
  persistierte User-Hotbar API
```

---

## 2. Ordnerstruktur

```text
services/vectoplan-library/routes/
├── __init__.py
├── api.py
├── vplib_routes.py
├── library_routes.py
├── taxonomy.py
├── library_definition_routes.py
├── library_files.py
├── creative_library_user_routes.py
├── creative_library_draft_routes.py
├── create.py
├── inventar.py
├── inventar_user.py
└── IST-Zustand.md
```

---

## 3. Architekturregeln

### 3.1 Keine Fachlogik in Routes

Routen dürfen:

```text
✅ Query-Parameter lesen
✅ JSON/Form/Multipart lesen
✅ bool/int/string defensiv normalisieren
✅ Service-Funktionen aufrufen
✅ Fehler in API-sichere JSON-Payloads mappen
✅ Blueprints bereitstellen
✅ Route-Maps/Health/Selftests liefern
```

Routen sollen nicht:

```text
❌ SQLAlchemy direkt abfragen
❌ db.session direkt verwenden
❌ Alembic/Migrationen ausführen
❌ Source-Dateien direkt schreiben
❌ Scanner direkt implementieren
❌ Generatorlogik direkt implementieren
❌ Published Items direkt aus User-Routen verändern
❌ Mockdaten als produktive Antworten liefern
```

### 3.2 Read-/Write-Trennung

```text
GET /api/v1/vplib/library/scan
  read-only; dateibasierter Scan; kein DB-Write

POST /api/v1/vplib/library/sync
  expliziter DB-Write; Source/ScanResult -> PostgreSQL

GET /api/v1/vplib/library/items
GET /api/v1/vplib/library/published
GET /api/v1/vplib/library/blocks
GET /api/v1/vplib/library/tree
  DB-backed Published Reads

POST/PATCH/PUT/DELETE /api/v1/vplib/library/drafts/*
  Draft Working State Writes

POST/PATCH/DELETE /api/v1/vplib/creative-library/*
  User Collections / Overrides / Audit Writes

POST/PATCH/DELETE /api/v1/vplib/taxonomy/nodes/*
  User Taxonomy Writes oder Overrides

PUT/PATCH/DELETE /api/v1/vplib/inventar_user/slots/*
  User-Hotbar Writes
```

---

## 4. Blueprint-Matrix

| Datei | Blueprint | Prefix | Aufgabe | Delegiert an | Statusklasse |
|---|---|---|---|---|---|
| routes/__init__.py | - | - | Zentrale Blueprint-Registry, lädt Required/Optional Blueprints defensiv und speichert Registrierungsmetadaten in app.extensions. | keine Business-Services | Startup/Registry |
| routes/vplib_routes.py | vplib_bp | /api/v1/vplib | VPLIB-Kern: Health, Self-Test, Package-Create und Dry-Run. | services.vplib_route_service | Read + Create-Compute |
| routes/library_routes.py | library_bp | /api/v1/vplib/library | Kanonische Creative-Library-API: Scan, Sync, Published Reads, Items, Scan-Runs, Inventory-Slots. | services.library_route_service, library_db_sync_service, creative_library_service | Read + DB Sync |
| routes/api.py | api_bp | (vollständige Pfade im Decorator) | Ältere/kompatible API-Bündelung für Library Scan/Sync/DB Reads mit flexiblen Service-Signaturen. | library.services, library.repositories | Compatibility/Transitional |
| routes/taxonomy.py | taxonomy_bp | /api/v1/vplib/taxonomy | Taxonomie-HTTP-Schicht: Legacy/canonical taxonomy plus DB-backed User-Nodes und Overrides. | taxonomy_route_service, library_taxonomy_user_service | Read + User Writes |
| routes/library_definition_routes.py | library_definition_bp | /api/v1/vplib/definitions | Definition Catalog API: Variables, Units, Materials, Profiles, Bindings, Create Context, Upload Constraints, Seed. | library_definition_catalog_service, library_definition_seed_service | Read + Seed/Admin Writes |
| routes/library_files.py | file_bp | /api/v1/vplib/files | Upload-/Datei-API: Files, Versions, Links, Context-Files, Constraints, Audit. | library_file_service | File/DB Writes |
| routes/creative_library_user_routes.py | creative_library_user_bp | /api/v1/vplib/creative-library | User-spezifische Creative-Library-Sicht: Collections, Items, Overrides, Audit, resolved Inventory. | creative_library_user_service | User DB Writes |
| routes/creative_library_draft_routes.py | creative_library_drafts_bp | /api/v1/vplib/library/drafts | Persistent Draft API: Draft CRUD, Variants, Assets, Documents, Upload, Validation, Publish-Prepare/Publish, Audit. | creative_library_draft_service | Draft DB Writes |
| routes/create.py | create_bp | /create + /api/v1/vplib/create | Create-Frontend und Create API; verbindet Legacy Create-Service, Definition Catalog und optional persistente Drafts. | library_create_route_service, library_definition_catalog_service, creative_library_draft_service | Compute + optional DB/Source Writes |
| routes/inventar.py | inventar_bp | (keiner) | HTML-Routen für /user-inventar und /creative-inventar. | keine; render_template | HTML Read |
| routes/inventar_user.py | inventar_user_bp | /api/v1/vplib/inventar_user | Persistierte User-Hotbar API: State, Slots, Slot-Auswahl, Slot setzen/leeren. | user_inventory_service | User DB Writes |

---

## 5. Zentrale Registry: `routes/__init__.py`

### 5.1 Aufgabe

`routes/__init__.py` ist der zentrale Startpunkt für die Registrierung aller Blueprints.

Ablauf:

```text
app.py / create_app()
  ↓
from routes import register_blueprints
  ↓
register_blueprints(app)
  ↓
get_blueprint_specs()
  ↓
for each BlueprintSpec:
    import module
    find blueprint attribute
    register blueprint if not already registered
  ↓
store registry metadata in app.extensions["vectoplan_library"]
```

### 5.2 Required Blueprints

```text
routes.vplib_routes:vplib_bp
routes.library_routes:library_bp
routes.taxonomy:taxonomy_bp
```

Diese drei Blueprints sind hart erforderlich. Wenn einer davon nicht importiert oder nicht registriert werden kann, soll der App-Start scheitern.

### 5.3 Optional Blueprints

```text
routes.api:api_bp
routes.library_definition_routes:library_definition_bp
routes.library_files:file_bp
routes.creative_library_user_routes:creative_library_user_bp
routes.creative_library_draft_routes:creative_library_drafts_bp
routes.create:create_bp
routes.inventar:inventar_bp
routes.inventar_user:inventar_user_bp
```

Optionale Blueprints dürfen fehlen, ohne den Start sofort zu stoppen. Die Registry protokolliert dann Warnungen und Registrierungsfehler.

### 5.4 Registry-Daten

Die Registry schreibt unter anderem:

```text
app.extensions["vectoplan_library"]["route_module"]
app.extensions["vectoplan_library"]["routes_component"]
app.extensions["vectoplan_library"]["schema_version"]
app.extensions["vectoplan_library"]["blueprint_specs"]
app.extensions["vectoplan_library"]["blueprint_resolution_results"]
app.extensions["vectoplan_library"]["blueprint_registration_results"]
app.extensions["vectoplan_library"]["registered_blueprint_names_list"]
app.extensions["vectoplan_library"]["app_blueprint_names"]
app.extensions["vectoplan_library"]["route_count"]
app.extensions["vectoplan_library"]["routing_initialized"]
app.extensions["vectoplan_library"]["routing_initialized_at"]
```

Diese Daten sind für Startup-Diagnose und Healthchecks wichtig.

---

## 6. Datei-für-Datei-IST-Zustand

### routes/__init__.py

**Routen laut aktueller Datei:** 0

- Zentrale Registry des gesamten Flask-Routings.
- Definiert Required-Blueprints und Optional-Blueprints.
- Lädt Route-Module defensiv per importlib.
- Akzeptiert Alias-Attribute wie bp/blueprint.
- Registriert Blueprints genau einmal.
- Speichert Registrierungsergebnisse in app.extensions['vectoplan_library'].
- Enthält keine Business-Logik, keine DB-Queries und keine HTML-Erzeugung.

### routes/vplib_routes.py

**Routen laut aktueller Datei:** 4

- HTTP-Adapter für den VPLIB-Kern.
- Stellt /api/v1/vplib/health, /test, /create und /create/dry-run bereit.
- Nutzt services.vplib_route_service für Create/Self-Test.
- Lädt Settings bevorzugt aus src.config.vplib_settings.
- Antwortet immer JSON und kapselt Exceptions.

### routes/library_routes.py

**Routen laut aktueller Datei:** 26

- Kanonische aktuelle Library-API.
- GET /scan bleibt read-only.
- POST /sync ist der explizite DB-write Entry-Point.
- DB-backed Reads laufen über CreativeLibraryService.
- Source/ScanResult -> DB läuft über LibraryDbSyncService.
- Legacy dateibasierte Reads bleiben per ?source=file verfügbar.
- Published Library ist von Drafts und User-Overlays getrennt.

### routes/api.py

**Routen laut aktueller Datei:** 12

- Kompatibilitäts-/Transitions-API mit vollständigen Pfaden im Decorator.
- Enthält ebenfalls /api/v1/vplib/library/* Endpoints.
- Kann parallel zu routes/library_routes.py existieren, sollte aber langfristig bereinigt oder klar als Legacy markiert werden.
- Nutzt flexible Service-Aufrufe, um alte und neue Signaturen zu unterstützen.
- Komprimiert Sync-Ergebnisse, damit keine großen Domain-/ORM-Objekte blind serialisiert werden.

### routes/taxonomy.py

**Routen laut aktueller Datei:** 34

- Thin route layer für backend-owned Taxonomy.
- Delegiert Legacy/canonical Taxonomy Reads an TaxonomyRouteService.
- Delegiert User-Nodes, Overrides und Audit an LibraryTaxonomyUserService.
- Create-Inventar und Create-Flow sollen Taxonomie über diese API konsumieren.
- System-Taxonomie wird nicht pro User kopiert; User-Änderungen sind Nodes oder Overrides.

### routes/library_definition_routes.py

**Routen laut aktueller Datei:** 32

- Definition Catalog HTTP-Schicht.
- Liefert Current Catalog, Datasets, Variables, Units, Materials, Document Types, Object Kinds, Profiles und Bindings.
- Liefert Create Context und Upload Constraints für Create UI, Variant Drawer und Files.
- Seed-Preview/Validate ist read-only; Seed-Run schreibt in Definitionstabellen.
- Legacy Definition-Route-Service bleibt als Fallback für ältere Endpunkte erhalten.

### routes/library_files.py

**Routen laut aktueller Datei:** 20

- Generische Datei-/Upload-HTTP-Schicht.
- Unterstützt Multipart-Uploads, Versionen, Soft-Delete, File Links, Primary Links, Context-Files und Audit.
- Speicherlogik bleibt im File-Service.
- DB-Logik bleibt im File-Repository.
- Große GLB/GLTF-Dateien sollten über Storage-Metadaten statt primär BYTEA laufen.

### routes/creative_library_user_routes.py

**Routen laut aktueller Datei:** 39

- User-spezifische Sicht auf die Creative Library.
- Liefert resolved Creative Library und Creative Inventory für user_id.
- Verwaltet Collections, Collection Items, Favorites, Pins, Rename/Reorder und User Overrides.
- Schreibt nicht in Published Items selbst, sondern in User-Collections/Overrides/Audit.

### routes/creative_library_draft_routes.py

**Routen laut aktueller Datei:** 30

- Persistent Draft HTTP-Schicht.
- Drafts sind Generator-/Edit-Zwischenstände.
- Unterstützt Draft CRUD, Varianten, Assets, Documents, File-Upload als Document, Validation Issues, Publish Prepare und optional Publish.
- Published Creative Library bleibt getrennt und wird erst über Publish-/Sync-Service berührt.

### routes/create.py

**Routen laut aktueller Datei:** 21

- Create-Frontend und Create-API in einer Datei.
- GET /create rendert die Create-Seite oder eine Fallback-Seite.
- API unter /api/v1/vplib/create/*.
- Legacy Create-Service bleibt zuständig für Draft-Normalisierung, Validate, Package Plan, Download und Save.
- Definition Catalog liefert Create Context und Optionen.
- Persistente Drafts sind opt-in über persist/save_draft/db/persistent.

### routes/inventar.py

**Routen laut aktueller Datei:** 2

- Minimaler HTML-Adapter.
- Rendert /user-inventar und /creative-inventar.
- Keine DB-Logik, keine Mockdaten, keine Service-Schicht.

### routes/inventar_user.py

**Routen laut aktueller Datei:** 10

- HTTP-Adapter für persistiertes User-Inventar.
- Phase 1: user_id=1, inventory_key=default, exakt 9 Slots.
- Delegiert an user_inventory_service.
- Persistiert Slot-Auswahl, Setzen und Leeren.
- Keine SQLAlchemy-Queries und keine Model-Logik in der Route.


---

## 7. Datenflüsse

### 7.1 App-Start / Blueprint-Registrierung

```text
wsgi:app
  ↓
create_app()
  ↓
models.import_all_models()
  ↓
Flask-Migrate/Alembic sieht db.metadata.tables
  ↓
routes.register_blueprints(app)
  ↓
Required Blueprints:
  - vplib_bp
  - library_bp
  - taxonomy_bp
  ↓
Optional Blueprints:
  - api_bp
  - definitions
  - files
  - creative-library user
  - drafts
  - create
  - inventar
  - inventar_user
  ↓
Gunicorn startet
```

### 7.2 Library Scan

```text
GET /api/v1/vplib/library/scan?source=file
  ↓
routes/library_routes.py
  ↓
services.library_route_service
  ↓
library_scan_service
  ↓
src/library/source/
  ↓
JSON Response
```

Eigenschaft:

```text
writes_database = False
```

### 7.3 Library DB Sync

```text
POST /api/v1/vplib/library/sync
  ↓
routes/library_routes.py
  ↓
library.services.library_db_sync_service
  ↓
library_scan_service
  ↓
creative_library_service
  ↓
creative_library_repository
  ↓
PostgreSQL:
  creative_library_items
  creative_library_revisions
  creative_library_variants
  creative_library_assets
  creative_library_documents
  creative_library_scan_runs
  creative_library_scan_issues
```

Eigenschaft:

```text
writes_database = True
```

### 7.4 Published Reads

```text
GET /api/v1/vplib/library/items
GET /api/v1/vplib/library/published
GET /api/v1/vplib/library/blocks
GET /api/v1/vplib/library/tree
  ↓
routes/library_routes.py
  ↓
creative_library_service
  ↓
creative_library_repository
  ↓
PostgreSQL Published State
```

### 7.5 Definition Catalog

```text
GET /api/v1/vplib/definitions/current
GET /api/v1/vplib/definitions/create-context
GET /api/v1/vplib/definitions/upload-constraints
  ↓
routes/library_definition_routes.py
  ↓
library_definition_catalog_service
  ↓
library_definition_repository
  ↓
PostgreSQL Definition Tables
```

Seed-Flow:

```text
definitions/data/*.json
  ↓
POST /api/v1/vplib/definitions/seed/run
  ↓
library_definition_seed_service
  ↓
library_definition_repository
  ↓
PostgreSQL Definition Tables
```

### 7.6 Taxonomie

```text
GET /api/v1/vplib/taxonomy/create-options
  ↓
routes/taxonomy.py
  ↓
legacy taxonomy_route_service
  ↓
canonical backend taxonomy
```

User-resolved Flow:

```text
GET /api/v1/vplib/taxonomy/resolved?user_id=1
  ↓
routes/taxonomy.py
  ↓
library_taxonomy_user_service
  ↓
library_taxonomy_repository
  ↓
library_taxonomy_nodes
  library_taxonomy_overrides
```

### 7.7 Files / Uploads

```text
POST /api/v1/vplib/files
  ↓
routes/library_files.py
  ↓
library_file_service
  ↓
library_file_repository
  ↓
library_files
library_file_versions
library_file_links
library_file_audit_events
  ↓
storage_backend:
  local | postgres_bytea | object_storage | external_uri
```

### 7.8 Drafts

```text
POST /api/v1/vplib/library/drafts
  ↓
routes/creative_library_draft_routes.py
  ↓
creative_library_draft_service
  ↓
creative_library_draft_repository
  ↓
creative_library_drafts
creative_library_draft_variants
creative_library_draft_assets
creative_library_draft_documents
creative_library_draft_validation_issues
creative_library_draft_audit_events
```

Publish-Prepare:

```text
POST /api/v1/vplib/library/drafts/<draft_ref>/publish/prepare
  ↓
build publish payload
  ↓
kein direkter Published-Write zwingend
```

Publish:

```text
POST /api/v1/vplib/library/drafts/<draft_ref>/publish
  ↓
optional publish adapter
  ↓
Published Creative Library
```

### 7.9 Create Flow

```text
GET /create
  ↓
routes/create.py
  ↓
render_template("vplib/create.html")
  oder fallback HTML
```

API:

```text
POST /api/v1/vplib/create/draft
  ↓
legacy library_create_route_service
  ↓
optional persist=true
  ↓
creative_library_draft_service
```

### 7.10 User-Inventar

```text
GET /user-inventar
  ↓
routes/inventar.py
  ↓
templates/inventar/user-inventar.html
  ↓
static/js/inventar/user-inventory.js
  ↓
GET /api/v1/vplib/inventar_user
  ↓
routes/inventar_user.py
  ↓
user_inventory_service
  ↓
user_inventory_repository
  ↓
user_inventory_states
user_inventory_slots
```

Slot-Auswahl:

```text
PATCH /api/v1/vplib/inventar_user/select-slot
  ↓
active_slot_index speichern
  ↓
selected Slot aktualisieren
```

---

## 8. Routenklassifikation

| Klasse | Anzahl | Bedeutung |
|---|---|---|
| read | 114 | Nur lesend/diagnostisch. |
| write | 91 | Schreibt User-/Draft-/File-/Taxonomie-/Collection-Zustand. |
| db-write | 3 | Schreibt in PostgreSQL oder synchronisiert persistenten Published-State. |
| cache/admin | 9 | Ändert Cache oder lädt Registry neu. |
| compute/validate | 10 | Erzeugt/validiert Payloads oder Downloads; persistent abhängig vom Service. |
| read/validate | 2 | Validiert/previewt ohne geplanten DB-Write. |
| source-write optional | 1 | Kann Dateien in Source schreiben, wenn Service/Settings das erlauben. |

---

## 9. Health-, Routes- und Selftest-Endpunkte

| Methode | Route | Funktion | Datei |
|---|---|---|---|
| GET | /api/v1/vplib/health | vplib_health_route | routes/vplib_routes.py |
| GET | /api/v1/vplib/library/health | library_health | routes/library_routes.py |
| GET | /api/v1/vplib/library/routes | library_routes | routes/library_routes.py |
| GET | /api/v1/vplib/library/selftest | library_selftest | routes/library_routes.py |
| GET | /api/v1/vplib/library/health | library_health_route | routes/api.py |
| GET | /api/v1/vplib/library/db/health | library_db_health_route | routes/api.py |
| GET | /api/v1/vplib/taxonomy/health | taxonomy_health | routes/taxonomy.py |
| GET | /api/v1/vplib/taxonomy/routes | taxonomy_routes_map | routes/taxonomy.py |
| GET | /api/v1/vplib/taxonomy/selftest | taxonomy_selftest | routes/taxonomy.py |
| GET | /api/v1/vplib/definitions/routes | library_definition_routes_map | routes/library_definition_routes.py |
| GET | /api/v1/vplib/definitions/health | library_definition_health | routes/library_definition_routes.py |
| GET | /api/v1/vplib/definitions/selftest | library_definition_selftest | routes/library_definition_routes.py |
| GET | /api/v1/vplib/files/routes | library_files_routes_map | routes/library_files.py |
| GET | /api/v1/vplib/files/health | library_files_health | routes/library_files.py |
| GET | /api/v1/vplib/files/selftest | library_files_selftest | routes/library_files.py |
| GET | /api/v1/vplib/creative-library/health | creative_library_user_health | routes/creative_library_user_routes.py |
| GET | /api/v1/vplib/creative-library/routes | creative_library_user_routes_map | routes/creative_library_user_routes.py |
| GET | /api/v1/vplib/creative-library/selftest | creative_library_user_selftest | routes/creative_library_user_routes.py |
| GET | /api/v1/vplib/library/drafts/health | creative_library_drafts_health | routes/creative_library_draft_routes.py |
| GET | /api/v1/vplib/library/drafts/routes | creative_library_drafts_routes_map | routes/creative_library_draft_routes.py |
| GET | /api/v1/vplib/library/drafts/selftest | creative_library_drafts_selftest | routes/creative_library_draft_routes.py |
| GET | /api/v1/vplib/create/health | create_health | routes/create.py |
| GET | /api/v1/vplib/create/routes | create_routes_map | routes/create.py |
| GET | /api/v1/vplib/create/selftest | create_selftest | routes/create.py |
| GET | /api/v1/vplib/inventar_user/health | inventar_user_health | routes/inventar_user.py |

---

## 10. Vollständiger Route-Katalog nach Datei

### routes/vplib_routes.py


| Methode | Route | Funktion | Klasse |
|---|---|---|---|
| GET | /api/v1/vplib/test | vplib_test_route | read |
| GET | /api/v1/vplib/health | vplib_health_route | read |
| POST | /create | vplib_create_route | write |
| POST | /api/v1/vplib/create/dry-run | vplib_create_dry_run_route | write |



### routes/library_routes.py


| Methode | Route | Funktion | Klasse |
|---|---|---|---|
| GET | /api/v1/vplib/library/health | library_health | read |
| GET | /api/v1/vplib/library/routes | library_routes | read |
| GET | /api/v1/vplib/library/selftest | library_selftest | read |
| GET | /api/v1/vplib/library/scan | library_scan | read |
| POST | /api/v1/vplib/library/sync | library_sync | db-write |
| GET | /api/v1/vplib/library/blocks | library_blocks | read |
| GET | /api/v1/vplib/library/tree | library_tree | read |
| GET | /api/v1/vplib/library/blocks/<path:block_id>/variants | library_block_variants | read |
| GET | /api/v1/vplib/library/blocks/<path:block_id> | library_block_detail | read |
| GET | /api/v1/vplib/library/published | library_published | read |
| GET | /api/v1/vplib/library/items | library_items | read |
| GET | /api/v1/vplib/library/vplib/<path:vplib_uid> | library_item_by_vplib_uid | read |
| GET | /api/v1/vplib/library/items/<path:item_ref>/variants | library_item_variants | read |
| GET | /api/v1/vplib/library/items/<path:item_ref>/revisions | library_item_revisions | read |
| GET | /api/v1/vplib/library/items/<path:item_ref>/assets | library_item_assets | read |
| GET | /api/v1/vplib/library/items/<path:item_ref>/documents | library_item_documents | read |
| GET | /api/v1/vplib/library/items/<path:item_ref> | library_item_detail | read |
| GET | /api/v1/vplib/library/scan-runs | library_scan_runs | read |
| POST | /api/v1/vplib/library/scan-runs | library_scan_run_start | write |
| POST | /api/v1/vplib/library/scan-runs/<path:scan_run_ref>/finish | library_scan_run_finish | write |
| GET | /api/v1/vplib/library/scan-runs/<path:scan_run_ref>/issues | library_scan_run_issues | read |
| POST | /api/v1/vplib/library/scan-runs/<path:scan_run_ref>/issues | library_scan_run_issue_add | write |
| GET | /api/v1/vplib/library/inventory/slots | library_inventory_slots | read |
| POST | /api/v1/vplib/library/inventory/slots/<int:slot_index> | library_inventory_slot_set | write |
| DELETE | /api/v1/vplib/library/inventory/slots/<int:slot_index> | library_inventory_slot_clear | write |
| POST | /api/v1/vplib/library/cache/clear | library_cache_clear | cache/admin |



### routes/api.py


| Methode | Route | Funktion | Klasse |
|---|---|---|---|
| GET | /api/v1/vplib/library/health | library_health_route | read |
| GET | /api/v1/vplib/library/db/health | library_db_health_route | read |
| GET | /api/v1/vplib/library/scan | library_scan_route | read |
| POST | /api/v1/vplib/library/sync | library_sync_route | db-write |
| GET | /api/v1/vplib/library/sync-runs | library_sync_runs_route | read |
| GET | /api/v1/vplib/library/sync-runs/<path:run_id> | library_sync_run_detail_route | read |
| GET | /api/v1/vplib/library/publication-status | library_publication_status_route | read |
| GET | /api/v1/vplib/library/blocks | library_blocks_route | read |
| GET | /api/v1/vplib/library/blocks/<path:block_id>/variants | library_block_variants_route | read |
| GET | /api/v1/vplib/library/blocks/<path:block_id> | library_block_detail_route | read |
| GET | /api/v1/vplib/library/tree | library_tree_route | read |
| GET | /api/v1/vplib/library/inventory | library_inventory_route | read |



### routes/taxonomy.py


| Methode | Route | Funktion | Klasse |
|---|---|---|---|
| GET | /api/v1/vplib/taxonomy/health | taxonomy_health | read |
| GET | /api/v1/vplib/taxonomy/routes | taxonomy_routes_map | read |
| GET | /api/v1/vplib/taxonomy/selftest | taxonomy_selftest | read |
| GET | /api/v1/vplib/taxonomy | taxonomy_root | read |
| GET | /api/v1/vplib/taxonomy/resolved | taxonomy_resolved | read |
| GET | /api/v1/vplib/taxonomy/options | taxonomy_options | read |
| GET | /api/v1/vplib/taxonomy/create-options | taxonomy_create_options | read |
| GET | /api/v1/vplib/taxonomy/tree | taxonomy_tree | read |
| GET | /api/v1/vplib/taxonomy/lookup | taxonomy_lookup | read |
| GET | /api/v1/vplib/taxonomy/nodes | taxonomy_nodes_list | read |
| POST | /api/v1/vplib/taxonomy/nodes | taxonomy_nodes_create | write |
| GET | /api/v1/vplib/taxonomy/nodes/<path:node_ref> | taxonomy_nodes_get | read |
| PATCH | /api/v1/vplib/taxonomy/nodes/<path:node_ref> | taxonomy_nodes_patch | write |
| DELETE | /api/v1/vplib/taxonomy/nodes/<path:node_ref> | taxonomy_nodes_delete | write |
| POST | /api/v1/vplib/taxonomy/nodes/<path:node_ref>/restore | taxonomy_nodes_restore | write |
| POST | /api/v1/vplib/taxonomy/nodes/<path:node_ref>/hide | taxonomy_nodes_hide | write |
| POST | /api/v1/vplib/taxonomy/nodes/<path:node_ref>/rename | taxonomy_nodes_rename | write |
| POST | /api/v1/vplib/taxonomy/nodes/<path:node_ref>/reorder | taxonomy_nodes_reorder | write |
| POST | /api/v1/vplib/taxonomy/nodes/<path:node_ref>/move | taxonomy_nodes_move | write |
| GET | /api/v1/vplib/taxonomy/overrides | taxonomy_overrides_list | read |
| POST | /api/v1/vplib/taxonomy/overrides | taxonomy_overrides_create | write |
| DELETE | /api/v1/vplib/taxonomy/overrides/<path:override_ref> | taxonomy_overrides_delete | write |
| DELETE | /api/v1/vplib/taxonomy/overrides | taxonomy_overrides_delete_by_node | write |
| GET | /api/v1/vplib/taxonomy/audit | taxonomy_audit_list | read |
| POST | /api/v1/vplib/taxonomy/domains | taxonomy_create_domain | write |
| POST | /api/v1/vplib/taxonomy/categories | taxonomy_create_category | write |
| POST | /api/v1/vplib/taxonomy/subcategories | taxonomy_create_subcategory | write |
| POST | /api/v1/vplib/taxonomy/validate | taxonomy_validate | compute/validate |
| POST | /api/v1/vplib/taxonomy/resolve | taxonomy_resolve | write |
| POST | /api/v1/vplib/taxonomy/build-reference | taxonomy_build_reference | write |
| POST | /api/v1/vplib/taxonomy/build-classification | taxonomy_build_classification | write |
| POST | /api/v1/vplib/taxonomy/validate-source-path | taxonomy_validate_source_path | compute/validate |
| POST | /api/v1/vplib/taxonomy/cache/clear | taxonomy_cache_clear | cache/admin |
| POST | /api/v1/vplib/taxonomy/reload | taxonomy_reload | cache/admin |



### routes/library_definition_routes.py


| Methode | Route | Funktion | Klasse |
|---|---|---|---|
| GET | /api/v1/vplib/definitions | library_definition_routes_index | read |
| GET | /api/v1/vplib/definitions/routes | library_definition_routes_map | read |
| GET | /api/v1/vplib/definitions/health | library_definition_health | read |
| GET | /api/v1/vplib/definitions/selftest | library_definition_selftest | read |
| GET | /api/v1/vplib/definitions/current | library_definition_current | read |
| GET | /api/v1/vplib/definitions/summary | library_definition_summary | read |
| GET | /api/v1/vplib/definitions/options | library_definition_options | read |
| GET | /api/v1/vplib/definitions/payload | library_definition_payload | read |
| GET | /api/v1/vplib/definitions/datasets | library_definition_datasets | read |
| GET | /api/v1/vplib/definitions/datasets/<path:dataset_key> | library_definition_dataset | read |
| GET | /api/v1/vplib/definitions/variables | library_definition_variables | read |
| GET | /api/v1/vplib/definitions/units | library_definition_units | read |
| GET | /api/v1/vplib/definitions/materials | library_definition_materials | read |
| GET | /api/v1/vplib/definitions/document-types | library_definition_document_types | read |
| GET | /api/v1/vplib/definitions/object-kinds | library_definition_object_kinds | read |
| GET | /api/v1/vplib/definitions/family-profiles | library_definition_family_profiles | read |
| GET | /api/v1/vplib/definitions/family-profiles/<path:profile_id> | library_definition_family_profile | read |
| GET | /api/v1/vplib/definitions/variant-profiles | library_definition_variant_profiles | read |
| GET | /api/v1/vplib/definitions/variant-profiles/<path:profile_id>/resolved | library_definition_variant_profile_resolved | read |
| GET | /api/v1/vplib/definitions/variant-profiles/<path:profile_id> | library_definition_variant_profile | read |
| GET | /api/v1/vplib/definitions/profile-bindings | library_definition_profile_bindings | read |
| GET/POST | /api/v1/vplib/definitions/create-context | library_definition_create_context | write |
| GET/POST | /api/v1/vplib/definitions/upload-constraints | library_definition_upload_constraints | write |
| GET/POST | /api/v1/vplib/definitions/seed/preview | library_definition_seed_preview | read/validate |
| GET/POST | /api/v1/vplib/definitions/seed/validate | library_definition_seed_validate | read/validate |
| POST | /api/v1/vplib/definitions/seed/run | library_definition_seed_run | db-write |
| GET/POST | /api/v1/vplib/definitions/resolve-family-profile | library_definition_resolve_family_profile | write |
| GET/POST | /api/v1/vplib/definitions/resolve-variant-profile | library_definition_resolve_variant_profile | write |
| GET/POST | /api/v1/vplib/definitions/empty-variant-values | library_definition_empty_variant_values_from_query_or_payload | write |
| GET/POST | /api/v1/vplib/definitions/empty-variant-values/<path:profile_id> | library_definition_empty_variant_values | write |
| POST | /api/v1/vplib/definitions/validate-variant | library_definition_validate_variant | compute/validate |
| POST | /api/v1/vplib/definitions/cache/clear | library_definition_cache_clear | cache/admin |



### routes/library_files.py


| Methode | Route | Funktion | Klasse |
|---|---|---|---|
| GET | /api/v1/vplib/files | library_files_index | read |
| GET | /api/v1/vplib/files/routes | library_files_routes_map | read |
| GET | /api/v1/vplib/files/health | library_files_health | read |
| GET | /api/v1/vplib/files/selftest | library_files_selftest | read |
| POST | /api/v1/vplib/files/cache/clear | library_files_cache_clear | cache/admin |
| POST | /api/v1/vplib/files | library_files_upload | write |
| GET | /api/v1/vplib/files/<path:file_ref> | library_files_get | read |
| PATCH | /api/v1/vplib/files/<path:file_ref> | library_files_patch | write |
| DELETE | /api/v1/vplib/files/<path:file_ref> | library_files_delete | write |
| GET | /api/v1/vplib/files/<path:file_ref>/versions | library_files_versions | read |
| POST | /api/v1/vplib/files/<path:file_ref>/versions | library_files_replace_version | write |
| DELETE | /api/v1/vplib/files/versions/<path:version_ref> | library_files_delete_version | write |
| GET | /api/v1/vplib/files/links | library_files_links_list | read |
| POST | /api/v1/vplib/files/<path:file_ref>/links | library_files_link_existing | write |
| GET | /api/v1/vplib/files/links/<path:link_ref> | library_files_link_get | read |
| DELETE | /api/v1/vplib/files/links/<path:link_ref> | library_files_link_delete | write |
| POST | /api/v1/vplib/files/links/<path:link_ref>/primary | library_files_link_primary | write |
| GET | /api/v1/vplib/files/context | library_files_context_files | read |
| GET/POST | /api/v1/vplib/files/upload-constraints | library_files_upload_constraints | write |
| GET | /api/v1/vplib/files/audit | library_files_audit_list | read |



### routes/creative_library_user_routes.py


| Methode | Route | Funktion | Klasse |
|---|---|---|---|
| GET | /api/v1/vplib/creative-library/health | creative_library_user_health | read |
| GET | /api/v1/vplib/creative-library/routes | creative_library_user_routes_map | read |
| GET | /api/v1/vplib/creative-library/selftest | creative_library_user_selftest | read |
| POST | /api/v1/vplib/creative-library/cache/clear | creative_library_user_cache_clear | cache/admin |
| GET | /api/v1/vplib/creative-library | creative_library_user_root | read |
| GET | /api/v1/vplib/creative-library/resolved | creative_library_user_resolved | read |
| GET | /api/v1/vplib/creative-library/inventory | creative_library_user_inventory | read |
| POST | /api/v1/vplib/creative-library/ensure-defaults | creative_library_user_ensure_defaults | write |
| GET | /api/v1/vplib/creative-library/collections | creative_library_user_collections_list | read |
| POST | /api/v1/vplib/creative-library/collections | creative_library_user_collections_create | write |
| GET | /api/v1/vplib/creative-library/collections/<path:collection_ref> | creative_library_user_collections_get | read |
| PATCH | /api/v1/vplib/creative-library/collections/<path:collection_ref> | creative_library_user_collections_patch | write |
| DELETE | /api/v1/vplib/creative-library/collections/<path:collection_ref> | creative_library_user_collections_delete | write |
| POST | /api/v1/vplib/creative-library/collections/<path:collection_ref>/restore | creative_library_user_collections_restore | write |
| GET | /api/v1/vplib/creative-library/collections/<path:collection_ref>/items | creative_library_user_collection_items_list | read |
| POST | /api/v1/vplib/creative-library/collections/<path:collection_ref>/items | creative_library_user_collection_items_add | write |
| GET | /api/v1/vplib/creative-library/items | creative_library_user_items_list | read |
| POST | /api/v1/vplib/creative-library/items | creative_library_user_items_add | write |
| DELETE | /api/v1/vplib/creative-library/items | creative_library_user_items_remove_by_payload | write |
| POST | /api/v1/vplib/creative-library/items/hide | creative_library_user_items_hide_by_identity | write |
| POST | /api/v1/vplib/creative-library/items/restore | creative_library_user_items_restore_by_identity | write |
| POST | /api/v1/vplib/creative-library/items/favorite | creative_library_user_items_favorite_by_identity | write |
| POST | /api/v1/vplib/creative-library/items/unfavorite | creative_library_user_items_unfavorite_by_identity | write |
| POST | /api/v1/vplib/creative-library/items/pin | creative_library_user_items_pin_by_identity | write |
| POST | /api/v1/vplib/creative-library/items/unpin | creative_library_user_items_unpin_by_identity | write |
| POST | /api/v1/vplib/creative-library/items/rename | creative_library_user_items_rename_by_identity | write |
| POST | /api/v1/vplib/creative-library/items/reorder | creative_library_user_items_reorder_by_identity | write |
| PATCH | /api/v1/vplib/creative-library/items/<path:collection_item_ref> | creative_library_user_items_patch | write |
| DELETE | /api/v1/vplib/creative-library/items/<path:collection_item_ref> | creative_library_user_items_delete | write |
| POST | /api/v1/vplib/creative-library/items/<path:collection_item_ref>/pin | creative_library_user_items_pin | write |
| POST | /api/v1/vplib/creative-library/items/<path:collection_item_ref>/unpin | creative_library_user_items_unpin | write |
| POST | /api/v1/vplib/creative-library/items/<path:collection_item_ref>/favorite | creative_library_user_items_favorite | write |
| POST | /api/v1/vplib/creative-library/items/<path:collection_item_ref>/unfavorite | creative_library_user_items_unfavorite | write |
| POST | /api/v1/vplib/creative-library/items/<path:collection_item_ref>/reorder | creative_library_user_items_reorder | write |
| GET | /api/v1/vplib/creative-library/overrides | creative_library_user_overrides_list | read |
| POST | /api/v1/vplib/creative-library/overrides | creative_library_user_overrides_create | write |
| DELETE | /api/v1/vplib/creative-library/overrides/<path:override_ref> | creative_library_user_overrides_delete | write |
| DELETE | /api/v1/vplib/creative-library/overrides | creative_library_user_overrides_delete_by_target | write |
| GET | /api/v1/vplib/creative-library/audit | creative_library_user_audit_list | read |



### routes/creative_library_draft_routes.py


| Methode | Route | Funktion | Klasse |
|---|---|---|---|
| GET | /api/v1/vplib/library/drafts/health | creative_library_drafts_health | read |
| GET | /api/v1/vplib/library/drafts/routes | creative_library_drafts_routes_map | read |
| GET | /api/v1/vplib/library/drafts/selftest | creative_library_drafts_selftest | read |
| POST | /api/v1/vplib/library/drafts/cache/clear | creative_library_drafts_cache_clear | cache/admin |
| GET | /api/v1/vplib/library/drafts | creative_library_drafts_list | read |
| POST | /api/v1/vplib/library/drafts | creative_library_drafts_create | write |
| GET | /api/v1/vplib/library/drafts/<string:draft_ref> | creative_library_drafts_get | read |
| PATCH | /api/v1/vplib/library/drafts/<string:draft_ref> | creative_library_drafts_patch | write |
| DELETE | /api/v1/vplib/library/drafts/<string:draft_ref> | creative_library_drafts_delete | write |
| POST | /api/v1/vplib/library/drafts/<string:draft_ref>/discard | creative_library_drafts_discard | write |
| POST | /api/v1/vplib/library/drafts/<string:draft_ref>/validate | creative_library_drafts_validate | compute/validate |
| GET | /api/v1/vplib/library/drafts/<string:draft_ref>/validation-issues | creative_library_drafts_validation_issues_list | read |
| POST | /api/v1/vplib/library/drafts/<string:draft_ref>/validation-issues | creative_library_drafts_validation_issues_set | write |
| POST | /api/v1/vplib/library/drafts/<string:draft_ref>/publish/prepare | creative_library_drafts_publish_prepare | compute/validate |
| POST | /api/v1/vplib/library/drafts/<string:draft_ref>/publish | creative_library_drafts_publish | write |
| GET | /api/v1/vplib/library/drafts/<string:draft_ref>/variants | creative_library_drafts_variants_list | read |
| POST | /api/v1/vplib/library/drafts/<string:draft_ref>/variants | creative_library_drafts_variants_add | write |
| PATCH | /api/v1/vplib/library/drafts/variants/<string:variant_ref> | creative_library_drafts_variants_patch | write |
| DELETE | /api/v1/vplib/library/drafts/variants/<string:variant_ref> | creative_library_drafts_variants_delete | write |
| GET | /api/v1/vplib/library/drafts/<string:draft_ref>/assets | creative_library_drafts_assets_list | read |
| POST | /api/v1/vplib/library/drafts/<string:draft_ref>/assets | creative_library_drafts_assets_add | write |
| PATCH | /api/v1/vplib/library/drafts/assets/<string:asset_ref> | creative_library_drafts_assets_patch | write |
| DELETE | /api/v1/vplib/library/drafts/assets/<string:asset_ref> | creative_library_drafts_assets_delete | write |
| GET | /api/v1/vplib/library/drafts/<string:draft_ref>/documents | creative_library_drafts_documents_list | read |
| POST | /api/v1/vplib/library/drafts/<string:draft_ref>/documents | creative_library_drafts_documents_add | write |
| POST | /api/v1/vplib/library/drafts/<string:draft_ref>/documents/upload | creative_library_drafts_documents_upload | write |
| PATCH | /api/v1/vplib/library/drafts/documents/<string:document_ref> | creative_library_drafts_documents_patch | write |
| DELETE | /api/v1/vplib/library/drafts/documents/<string:document_ref> | creative_library_drafts_documents_delete | write |
| GET | /api/v1/vplib/library/drafts/<string:draft_ref>/audit | creative_library_drafts_audit_for_draft | read |
| GET | /api/v1/vplib/library/drafts/audit | creative_library_drafts_audit_list | read |



### routes/create.py


| Methode | Route | Funktion | Klasse |
|---|---|---|---|
| GET | /create | create_page | read |
| GET | /api/v1/vplib/create/health | create_health | read |
| GET | /api/v1/vplib/create/routes | create_routes_map | read |
| GET | /api/v1/vplib/create/selftest | create_selftest | read |
| GET | /api/v1/vplib/create/ | create_index | read |
| GET | /api/v1/vplib/create | create_index | read |
| GET | /api/v1/vplib/create/options | create_options | read |
| GET/POST | /api/v1/vplib/create/create-context | create_context | write |
| GET/POST | /api/v1/vplib/create/context | create_context | write |
| GET | /api/v1/vplib/create/definitions/current | create_definitions_current | read |
| POST | /api/v1/vplib/create/draft | create_draft | write |
| POST | /api/v1/vplib/create/drafts | create_persistent_draft | write |
| GET | /api/v1/vplib/create/drafts/<path:draft_ref> | create_persistent_draft_get | read |
| PATCH | /api/v1/vplib/create/drafts/<path:draft_ref> | create_persistent_draft_patch | write |
| POST | /api/v1/vplib/create/drafts/<path:draft_ref>/validate | create_persistent_draft_validate | compute/validate |
| POST | /api/v1/vplib/create/drafts/<path:draft_ref>/publish/prepare | create_persistent_draft_publish_prepare | compute/validate |
| POST | /api/v1/vplib/create/validate | create_validate | compute/validate |
| POST | /api/v1/vplib/create/package-plan | create_package_plan | compute/validate |
| POST | /api/v1/vplib/create/save | create_save | source-write optional |
| POST | /api/v1/vplib/create/download | create_download | compute/validate |
| POST | /api/v1/vplib/create/cache/clear | create_cache_clear | cache/admin |



### routes/inventar.py


| Methode | Route | Funktion | Klasse |
|---|---|---|---|
| GET | /user-inventar | user_inventar | read |
| GET | /creative-inventar | creative_inventar | read |



### routes/inventar_user.py


| Methode | Route | Funktion | Klasse |
|---|---|---|---|
| GET | /api/v1/vplib/inventar_user/health | inventar_user_health | read |
| GET | /api/v1/vplib/inventar_user | inventar_user_index | read |
| GET | /api/v1/vplib/inventar_user/state | inventar_user_state | read |
| GET | /api/v1/vplib/inventar_user/slots | inventar_user_slots | read |
| POST | /api/v1/vplib/inventar_user/select-slot | inventar_user_select_slot | write |
| PATCH | /api/v1/vplib/inventar_user/select-slot | inventar_user_select_slot | write |
| PUT | /api/v1/vplib/inventar_user/slots/<int:slot_index> | inventar_user_set_slot | write |
| PATCH | /api/v1/vplib/inventar_user/slots/<int:slot_index> | inventar_user_set_slot | write |
| DELETE | /api/v1/vplib/inventar_user/slots/<int:slot_index> | inventar_user_clear_slot | write |
| POST | /api/v1/vplib/inventar_user/cache/clear | inventar_user_cache_clear | cache/admin |



---

## 11. Überlappende Routen / Übergangsrisiken

### 11.1 `routes/library_routes.py` und `routes/api.py`

Aktuell existieren zwei Dateien, die Routen im Namespace `/api/v1/vplib/library/*` bereitstellen:

```text
routes/library_routes.py
  aktueller kanonischer Blueprint mit url_prefix /api/v1/vplib/library

routes/api.py
  älterer/kompatibler API-Blueprint mit vollständigen Pfaden im Decorator
```

Das ist während der Migration tolerierbar, sollte aber bewusst behandelt werden.

Empfehlung:

```text
P0:
  library_routes.py als kanonische Library API behandeln.

P1:
  api.py entweder:
    - als Legacy-Kompatibilität behalten und eindeutig dokumentieren
    - oder schrittweise deaktivieren/aus Registry entfernen
    - oder nur für zusätzliche nicht-duplizierte Endpunkte verwenden

Prüfbefehl:
  GET /api/v1/vplib/library/routes
  plus Flask url_map prüfen:
  docker compose exec -T vectoplan-library python - <<'PY'
  from app import create_app
  app = create_app()
  for rule in sorted(app.url_map.iter_rules(), key=lambda r: str(r)):
      if "/api/v1/vplib/library" in str(rule):
          print(rule, rule.endpoint, sorted(rule.methods))
  PY
```

### 11.2 Erkannte exakte Doppeldekoratoren

| Methode | Route | Vorkommen |
|---|---|---|
| GET | /api/v1/vplib/library/blocks | routes/library_routes.py:library_blocks, routes/api.py:library_blocks_route |
| GET | /api/v1/vplib/library/blocks/<path:block_id> | routes/library_routes.py:library_block_detail, routes/api.py:library_block_detail_route |
| GET | /api/v1/vplib/library/blocks/<path:block_id>/variants | routes/library_routes.py:library_block_variants, routes/api.py:library_block_variants_route |
| GET | /api/v1/vplib/library/health | routes/library_routes.py:library_health, routes/api.py:library_health_route |
| GET | /api/v1/vplib/library/scan | routes/library_routes.py:library_scan, routes/api.py:library_scan_route |
| GET | /api/v1/vplib/library/tree | routes/library_routes.py:library_tree, routes/api.py:library_tree_route |
| POST | /api/v1/vplib/library/sync | routes/library_routes.py:library_sync, routes/api.py:library_sync_route |

---

## 12. Testplan

### 12.1 Smoke-Test-Matrix

| Testgruppe | Route | Erwartung |
|---|---|---|
| Basis Health | GET /api/v1/vplib/health | VPLIB Core lädt Settings und VPLIB Health. |
| Library Health | GET /api/v1/vplib/library/health | Library Route, DB Sync und Published Service sichtbar. |
| Library Route Map | GET /api/v1/vplib/library/routes | Kanonische Library-Route-Metadaten sichtbar. |
| Filesystem Scan | GET /api/v1/vplib/library/scan?source=file | Read-only Scan; schreibt nicht in DB. |
| DB Sync | POST /api/v1/vplib/library/sync | Source/ScanResult -> DB. Nach Erfolg Published Reads prüfen. |
| Published Items | GET /api/v1/vplib/library/items | DB-backed Published Library. |
| Definitions | GET /api/v1/vplib/definitions/current | Definition Catalog resolved. |
| Definition Seed Preview | GET\|POST /api/v1/vplib/definitions/seed/preview | Read-only Seed-Preview. |
| Files Health | GET /api/v1/vplib/files/health | File-Service/Repository erreichbar. |
| Taxonomy Create Options | GET /api/v1/vplib/taxonomy/create-options | Taxonomie für UI/Create. |
| Resolved Taxonomy | GET /api/v1/vplib/taxonomy/resolved?user_id=1 | DB-backed User-Taxonomy. |
| Create Options | GET /api/v1/vplib/create/options | Create UI Optionen + Definitionen. |
| Drafts | GET /api/v1/vplib/library/drafts | Persistente Draft-Liste. |
| Creative User | GET /api/v1/vplib/creative-library/resolved?user_id=1 | Resolved Creative Library für User. |
| User Hotbar | GET /api/v1/vplib/inventar_user?user_id=1&inventory_key=default | Persistiertes User-Inventar mit 9 Slots. |
| HTML User Inventar | GET /user-inventar | Hotbar-Overlay Template. |
| HTML Creative Inventar | GET /creative-inventar | Creative Library UI mit Create Embed. |

### 12.2 Nicht-destruktive Testreihenfolge

```text
1. GET /api/v1/vplib/health
2. GET /api/v1/vplib/library/health
3. GET /api/v1/vplib/library/routes
4. GET /api/v1/vplib/library/scan?source=file
5. GET /api/v1/vplib/definitions/health
6. GET /api/v1/vplib/definitions/current
7. GET /api/v1/vplib/taxonomy/health
8. GET /api/v1/vplib/taxonomy/create-options
9. GET /api/v1/vplib/files/health
10. GET /api/v1/vplib/create/health
11. GET /api/v1/vplib/library/drafts/health
12. GET /api/v1/vplib/creative-library/health
13. GET /api/v1/vplib/inventar_user/health
14. GET /user-inventar
15. GET /creative-inventar
```

### 12.3 Persistente Testreihenfolge

```text
1. POST /api/v1/vplib/library/sync
2. GET  /api/v1/vplib/library/items
3. GET  /api/v1/vplib/library/published
4. GET  /api/v1/vplib/library/scan-runs
5. GET  /api/v1/vplib/creative-library/resolved?user_id=1
6. GET  /api/v1/vplib/inventar_user?user_id=1&inventory_key=default
7. PATCH /api/v1/vplib/inventar_user/select-slot
8. GET  /api/v1/vplib/inventar_user/state
```

### 12.4 Create-/Draft-Testreihenfolge

```text
1. GET  /api/v1/vplib/create/options
2. GET  /api/v1/vplib/create/context
3. POST /api/v1/vplib/create/draft
4. POST /api/v1/vplib/create/draft?persist=true
5. GET  /api/v1/vplib/library/drafts
6. GET  /api/v1/vplib/library/drafts/<draft_ref>
7. POST /api/v1/vplib/library/drafts/<draft_ref>/validate
8. POST /api/v1/vplib/library/drafts/<draft_ref>/publish/prepare
```

### 12.5 Files-Testreihenfolge

```text
1. GET /api/v1/vplib/files/health
2. GET /api/v1/vplib/files/routes
3. GET /api/v1/vplib/files
4. GET /api/v1/vplib/files/links
5. GET /api/v1/vplib/files/context
6. POST multipart /api/v1/vplib/files
7. GET /api/v1/vplib/files/<file_ref>
8. GET /api/v1/vplib/files/<file_ref>/versions
```

---

## 13. Debugging und typische Fehlerbilder

### 13.1 Blueprint fehlt

Symptom:

```text
One or more required blueprints are missing
```

Prüfen:

```text
routes/__init__.py:
  get_blueprint_specs()
  resolve_all_blueprint_specs()
  get_blueprint_registry_snapshot(app)
```

Häufige Ursachen:

```text
- falscher Blueprint-Attributname
- Importfehler in Route-Datei
- Service-Import wird schon beim Route-Import hart ausgeführt
- Blueprint wurde als None erzeugt
```

### 13.2 Service unavailable

Symptom:

```json
{
  "ok": false,
  "status": "unavailable",
  "error": {
    "code": "..._service_unavailable"
  }
}
```

Prüfen:

```text
- import path in lazy loader
- Service-Datei existiert im Container
- __init__.py des Package exportiert Service falls benötigt
- py_compile der Service-Datei
- Models importierbar, falls Service Repository instanziiert
```

### 13.3 DB-Modelle nicht sichtbar

Symptom:

```text
models=False
tables=0
flask db migrate bricht ab
```

Prüfen:

```text
python -c "import models; print(models.get_models_health())"
```

Routen sind dann meist nicht ursächlich. Fehler liegt in `models/*` oder deren Importpfad.

### 13.4 Route funktioniert, aber liefert leere Daten

Mögliche Ursachen:

```text
- DB noch nicht synchronisiert
- POST /api/v1/vplib/library/sync wurde noch nicht ausgeführt
- Definition Catalog noch nicht geseedet
- Taxonomie-Nodes noch nicht aus DB resolved
- User-Collections/Defaults wurden noch nicht angelegt
- user_id/inventory_key falsch
```

### 13.5 501 / not_implemented

Mögliche Ursachen:

```text
- Route existiert
- Service ist importierbar
- aber erwartete Methode existiert im Service oder Repository noch nicht
```

Dann Service/Repository patchen, nicht Route.

---

## 14. Offene Punkte / Risiken

### P0 – Kanonische Library-API festlegen

`routes/library_routes.py` sollte als kanonischer Pfad gelten.  
`routes/api.py` ist historisch/kompatibel und kann Doppelpunkte im URL-Space erzeugen.

Empfehlung:

```text
Kurzfristig:
  beide Health/Route-Maps testen

Mittelfristig:
  api.py in Registry optional lassen oder gezielt entfernen,
  sobald library_routes.py alle notwendigen Endpunkte stabil abdeckt.
```

### P0 – Route-Map automatisch prüfen

Für jede Route-Datei:

```text
GET /.../routes
GET /.../health
GET /.../selftest
```

sollte konsistent funktionieren.

### P1 – POST-/PATCH-/DELETE-Routen mit Minimaldaten testen

Wichtigste Write-Routen:

```text
POST /api/v1/vplib/library/sync
POST /api/v1/vplib/definitions/seed/run
POST /api/v1/vplib/files
POST /api/v1/vplib/library/drafts
POST /api/v1/vplib/creative-library/ensure-defaults
PATCH /api/v1/vplib/inventar_user/select-slot
PUT /api/v1/vplib/inventar_user/slots/<slot_index>
```

### P1 – Frontend-Verknüpfung final testen

```text
/user-inventar
  -> inventar_user API
  -> user_inventory_states/user_inventory_slots

/creative-inventar
  -> taxonomy/create-options
  -> creative-library/resolved
  -> create embed
```

### P2 – Route-Dateien vereinheitlichen

Aktuell gibt es unterschiedliche Response-Helfer und Status-Mapping-Stile.  
Langfristig wäre ein gemeinsames `routes/_http.py` oder `src/services/http_response_service.py` sinnvoll.

---

## 15. Definition of Done für `routes/`

Der IST-Stand der Routenschicht gilt als stabil, wenn:

```text
1. register_blueprints(app) registriert alle Required Blueprints ohne Warnung.
2. Optional Blueprints werden geladen oder sauber als optional unavailable gemeldet.
3. /api/v1/vplib/health funktioniert.
4. /api/v1/vplib/library/health funktioniert.
5. /api/v1/vplib/library/scan?source=file schreibt nicht in DB.
6. POST /api/v1/vplib/library/sync schreibt erfolgreich in DB.
7. /api/v1/vplib/library/items liefert DB-backed Published State.
8. /api/v1/vplib/definitions/current liefert Definition Catalog.
9. /api/v1/vplib/taxonomy/create-options liefert UI-Taxonomie.
10. /api/v1/vplib/files/health funktioniert.
11. /api/v1/vplib/library/drafts/health funktioniert.
12. /api/v1/vplib/creative-library/resolved?user_id=1 funktioniert.
13. /api/v1/vplib/inventar_user liefert 9 Slots.
14. /user-inventar rendert nur die Hotbar-UI.
15. /creative-inventar rendert Creative Library UI und Create Embed.
16. Keine Route-Datei enthält direkte SQLAlchemy-Queries.
17. Keine Route-Datei führt Migrationen oder db.create_all() aus.
18. Doppelte Library-Routen sind bewusst dokumentiert oder bereinigt.
```

---

## 16. Kurzfazit

`routes/` ist inzwischen eine breite, aber klar schichtbare HTTP-Außenkante:

```text
VPLIB Core
  /api/v1/vplib/*

Published Creative Library
  /api/v1/vplib/library/*

Definitions
  /api/v1/vplib/definitions/*

Taxonomy
  /api/v1/vplib/taxonomy/*

Files
  /api/v1/vplib/files/*

Create
  /create
  /api/v1/vplib/create/*

Drafts
  /api/v1/vplib/library/drafts/*

User Creative Library
  /api/v1/vplib/creative-library/*

User Hotbar
  /user-inventar
  /api/v1/vplib/inventar_user/*

Creative Inventory UI
  /creative-inventar
```

Der wichtigste technische Punkt bleibt die Trennung:

```text
GET /scan = read-only
POST /sync = persistenter DB-Sync
routes/* = HTTP-Adapter
services/* = Fachlogik
repositories/* = DB-Zugriff
models/* = Tabellen
```

Nächster sinnvoller IST-Stand nach `routes/`:

```text
src/library/services/IST-Zustand.md
```
