<!-- services/vectoplan-server/IST-Zustand_Gesamtprojekt_2026-06-28.md -->

# IST-Zustand – Gesamtprojekt VECTOPLAN Server / VPLIB / Creative Library

Stand: **2026-06-28**  
Zeitzone/Arbeitskontext: **Europe/Berlin**  
Arbeitskontext lokal: `services/vectoplan-server`  
Schwerpunkt-Service: `services/vectoplan-library`  
Dokumenttyp: technischer Gesamt-IST-Stand für Projektstruktur, Services, Container, Datenbank, Migration, Backend-Routen, Library-/VPLIB-Schichten, Create-Flow, Drafts, Files, Taxonomie, User-Inventar, UI-Schichten, Datenflüsse, Tests und nächste Arbeitsschritte.

---

## 0. Kurzfazit

Das Gesamtprojekt ist inzwischen über den kritischen Start-/Migrationspunkt hinweg.

Der wichtigste Fortschritt:

```text
✅ vectoplan-library startet im Container.
✅ PostgreSQL für vectoplan-library ist erreichbar.
✅ Flask-SQLAlchemy sieht 39 Modelklassen / 39 Tabellen.
✅ Alembic erzeugt eine Initialmigration.
✅ flask db upgrade wurde erfolgreich ausgeführt.
✅ Gunicorn startet.
✅ Health- und erste API-Routen liefern HTTP 200.
✅ Source-/Scan-Pfad funktioniert.
✅ Die neuen Creative-Library-/Definition-/Taxonomie-/File-/Draft-/User-Modelle sind im Schema sichtbar.
```

Der aktuelle Stand ist damit nicht mehr „Import-/Migration kaputt“, sondern **Integrationstest und Stabilisierung der fachlichen Pfade**:

```text
1. Scan lesen.
2. Sync in DB ausführen.
3. Published DB Reads prüfen.
4. Definitions/Taxonomy seed/catalog prüfen.
5. Draft/Create-Flow testen.
6. Files- und User-Inventar-Pfade testen.
7. UI-Flows browserseitig verbinden.
```

---

## 1. Gesamtbild des Projekts

Das Projekt besteht aus mehreren Services, die zusammen die VECTOPLAN-Plattform bilden.

Aus Sicht des aktuellen Arbeitsstands ist `vectoplan-library` der zentrale Service für:

```text
- VPLIB Package-Logik
- Creative Library
- Source Scan
- DB-Sync
- Published Library API
- Definitions
- Taxonomie
- Upload-/File-Metadaten
- Draft-/Create-Flow
- Creative-Library User Collections/Overrides
- User Inventory / Hotbar
- Inventar- und Create-UI
```

Daneben existieren im Compose-/Projektkontext weitere Services:

```text
- vectoplan-library
- vectoplan-library-db
- vectoplan-chunk
- vectoplan-chunk-init
- vectoplan-app
- vectoplan-editor
- geoserver
- geoserver-orchestrator
- geoserver-orchestrator-db-init
- openlayer
- db-postgis-init
```

Die geospatial/editorbezogenen Services sind für das spätere Gesamtprodukt wichtig, wurden in diesem Abschnitt aber nicht tief inhaltlich überarbeitet. Die aktuelle Arbeit konzentriert sich auf die Library-/VPLIB-/Inventar-Schicht, weil diese die Basis für Editor-Auswahl, Blöcke, Objekte, Create-Flow und Persistenz liefert.

---

## 2. Aktuell nachgewiesener Betriebszustand

### 2.1 Container-/Runtime-Start

Der Library-Service startet mit:

```text
Service: vectoplan-library
Startmodus: gunicorn
Bind: 0.0.0.0:5000
Gunicorn App: wsgi:app
Gunicorn Workers: 2
Gunicorn Threads: 2
Gunicorn Timeout: 120
```

Wichtige konfigurierte Pfade im Container:

```text
VPLIB Route Prefix:              /api/v1/vplib
VPLIB Source Root:               /opt/vectoplan/services/vectoplan-library/sources
VPLIB Library Catalog Root:      /opt/vectoplan/services/vectoplan-library/creative_library
VPLIB Generated Root:            /opt/vectoplan/services/vectoplan-library/generated/vplib
VPLIB Test Output Root:          /opt/vectoplan/services/vectoplan-library/generated/vplib_test

Creative Library Route Prefix:   /api/v1/vplib/library
Creative Library Package Root:   /opt/vectoplan/services/vectoplan-library/src/library
Creative Library Source Root:    /opt/vectoplan/services/vectoplan-library/src/library/source
Creative Library Creative Root:  /opt/vectoplan/services/vectoplan-library/creative_library
Creative Library Generated Root: /opt/vectoplan/services/vectoplan-library/generated/library
Creative Library Cache Root:     /opt/vectoplan/services/vectoplan-library/generated/library_cache
```

### 2.2 Datenbank-/Migration-Status

Aktuell bewiesen:

```text
✅ PostgreSQL ist bereit.
✅ Datenbank: vectoplan_library
✅ Datenbank-URI ist gesetzt.
✅ DB Auto Init ist aktiv.
✅ DB Auto Migrate ist aktiv.
✅ DB Auto Upgrade ist aktiv.
✅ SQLAlchemy-Modelle sind in db.metadata sichtbar.
✅ 39 Modelklassen / 39 Tabellen sind sichtbar.
✅ Initialmigration wurde erzeugt.
✅ flask db upgrade wurde erfolgreich ausgeführt.
✅ Datenbank-Bootstrap abgeschlossen.
```

Die zuletzt erzeugte Migration im Log:

```text
b8249cb008a4_auto_creative_library_migration_2026_06_.py
```

### 2.3 Prestart-Status

Prestart meldet unter anderem OK für:

```text
app
wsgi
extensions
flask_sqlalchemy
flask_migrate
sqlalchemy
alembic
psycopg
models
models.creative_library
routes
routes.vplib_routes
routes.library_routes
routes.create
services.vplib_route_service
services.library_route_service
services.library_create_route_service
vplib
vplib.vplib_id_service
vplib.validators
vplib.creators
vplib.sources
library
library.domain
library.scanner
library.validation
library.read_models
library.services
library.services.library_scan_service
library.services.library_block_service
library.services.library_create_service
library.services.library_db_sync_service
library.services.library_published_service
library.repositories
library.repositories.sql
config.vplib_settings
config.library_settings
```

Das bedeutet: Der harte Import- und Migrationsblocker ist überwunden.

---

## 3. Aktuell getestete HTTP-Routen

Die folgenden Routen wurden manuell getestet und liefen mit HTTP 200:

```text
GET /api/v1/vplib/library/health
GET /api/v1/vplib/library/scan?source=file
GET /api/v1/vplib/definitions/health
GET /api/v1/vplib/files/health
GET /api/v1/vplib/taxonomy/health
GET /api/v1/vplib/creative-library/health
GET /api/v1/vplib/library/drafts/health
```

Interpretation:

```text
✅ Library-Routen sind erreichbar.
✅ Scan-Route ist erreichbar.
✅ Definitions-Routen sind erreichbar.
✅ Files-Routen sind erreichbar.
✅ Taxonomie-Routen sind erreichbar.
✅ Creative-Library-User-Routen sind erreichbar.
✅ Draft-Routen sind erreichbar.
```

Noch nicht aus diesen Tests bewiesen:

```text
⚠️ POST /api/v1/vplib/library/sync schreibt erfolgreich in DB.
⚠️ Published DB Reads liefern nicht-leere Daten nach Sync.
⚠️ Draft erstellen/validieren/publish vorbereiten funktioniert Ende-zu-Ende.
⚠️ File Uploads funktionieren Ende-zu-Ende.
⚠️ User Inventory schreibt Slot-/State-Daten korrekt.
⚠️ Create Save → Source → Sync → Published DB Read funktioniert komplett.
```

---

## 4. Bekannte nicht-blockierende Warnungen

Im Startlog treten weiterhin Warnungen auf:

```text
WARNING Extension error [routes]: One or more required blueprints are missing.
WARNING Directory check failed for routes_root.
WARNING VPLIB settings check failed: 'NoneType' object has no attribute '__dict__'
WARNING Library settings check failed: 'NoneType' object has no attribute '__dict__'
```

Bewertung:

```text
Status: nicht-blockierend
Begründung:
- App initialisiert erfolgreich.
- Gunicorn startet.
- Health-/API-Routen antworten mit HTTP 200.
- Prestart meldet zentrale Route- und Service-Imports als OK.
```

Diese Warnungen sollten später bereinigt werden, sind aber aktuell nicht P0.

---

## 5. Projekt-Topologie

### 5.1 Grobe Repository-Struktur

```text
vectoplan-website/
└── services/
    └── vectoplan-server/
        ├── docker-compose.yml
        ├── services/
        │   ├── vectoplan-library/
        │   ├── vectoplan-chunk/
        │   ├── vectoplan-editor/
        │   └── ...
        └── ...
```

### 5.2 Compose-/Runtime-Services

```text
vectoplan-server
│
├── vectoplan-library
│   ├── Flask/Gunicorn Service
│   ├── VPLIB API
│   ├── Creative Library API
│   ├── Create API/UI
│   ├── Draft API
│   ├── File API
│   ├── Taxonomy API
│   ├── User/Creative Library API
│   └── Inventar UI/API
│
├── vectoplan-library-db
│   └── PostgreSQL für vectoplan-library
│
├── vectoplan-chunk
│   └── Chunk-/Spatial-/Tile-/Datenservice
│
├── vectoplan-chunk-init
│   └── Initialisierungsjob für Chunk-Service
│
├── vectoplan-app
│   └── übergeordnete App-/Frontend-Komponente
│
├── vectoplan-editor
│   └── Editor-/Viewport-Komponente
│
├── geoserver
│   └── GeoServer
│
├── geoserver-orchestrator
│   └── Orchestrierung für GeoServer
│
├── geoserver-orchestrator-db-init
│   └── DB-Init-Job für GeoServer-Orchestrator
│
├── openlayer
│   └── OpenLayers-/Karten-/Viewer-Komponente
│
└── db-postgis-init
    └── PostGIS-/DB-Initialisierung
```

---

## 6. Zentrale Architekturregeln

### 6.1 Source of Truth

```text
src/library/source/
  Menschenlesbare, versionierbare Quelle für VPLIB-Directory-Packages.

PostgreSQL vectoplan_library
  Persistenter Published-State für produktive Library-Reads.

Draft-Tabellen
  Generator-/Bearbeitungs-Zwischenstände.

User Inventory Tabellen
  Runtime-/Editor-/Hotbar-Zustand pro User.

generated/
  Cache, Output, Testartefakte, Archive.
  Keine fachliche Source of Truth.
```

### 6.2 Read-/Write-Trennung

```text
GET /api/v1/vplib/library/scan
  read-only
  scannt Source
  schreibt nicht in PostgreSQL

POST /api/v1/vplib/library/sync
  write
  scannt oder verarbeitet ScanResult
  schreibt in PostgreSQL

GET /api/v1/vplib/library/published
GET /api/v1/vplib/library/items
GET /api/v1/vplib/library/blocks
GET /api/v1/vplib/library/tree
  DB-backed Published Reads

GET/POST/PATCH/PUT/DELETE Inventar-/Draft-/Files-/Create-Routen
  schreiben nur dort, wo die Route explizit als Write-Pfad ausgelegt ist
```

### 6.3 `vplib_uid`-Regel

```text
vplib_uid wird NICHT von der DB erzeugt.

vplib_uid entsteht:
- im VPLIB/Create-/Manifest-/Bundle-Flow
- oder ist bereits im Source-Package vorhanden

DB-Sync:
- übernimmt vplib_uid
- validiert/normalisiert sie
- nutzt sie als Upsert-Schlüssel

DB:
- generiert keine vplib_uid
- repariert keine fehlende vplib_uid
```

### 6.4 Revisionsregel

```text
revision_hash = Inhaltsfingerprint

Wenn revision_hash gleich bleibt:
  kein neuer Published-Revision-Datensatz nötig

Wenn revision_hash sich ändert:
  neue Revision
  neue Varianten-/Asset-/Dokument-Snapshots
  Family current_revision_* aktualisieren
```

### 6.5 Schichtentrennung

```text
routes/
  HTTP-Adapter
  keine Business-Logik
  keine direkten Queries

src/services/
  HTTP-nahe Service-Adapter
  Payload-Normalisierung
  keine direkte DB-Fachlogik

src/library/services/
  fachliche Orchestrierung
  Scan, Sync, Published Reads, Drafts, Files, User-Inventory

src/library/repositories/
  DB-Zugriff
  SQLAlchemy-Session
  Queries / Writes

models/
  SQLAlchemy-Tabellen
  keine Migrationen
  kein db.create_all()
```

---

## 7. `services/vectoplan-library` im Detail

### 7.1 Root-Struktur

```text
services/vectoplan-library/
├── Dockerfile
├── entrypoint.sh
├── requirements.txt
├── app.py
├── wsgi.py
├── config.py
├── extensions.py
├── IST-Zustand.md
├── models/
├── migrations/
├── routes/
├── src/
├── templates/
├── static/
├── generated/
├── sources/
└── creative_library/
```

### 7.2 Root-Dateien

#### `Dockerfile`

```text
Aufgabe:
- Runtime-Image bauen
- Python-Umgebung bereitstellen
- Systemabhängigkeiten installieren
- Anforderungen aus requirements.txt installieren
- Service-Code einbinden
- entrypoint.sh als Startpunkt verwenden
```

#### `entrypoint.sh`

```text
Aufgabe:
- Containerstart orchestrieren
- PostgreSQL-Erreichbarkeit abwarten
- Migrationsumgebung vorbereiten
- automatische Migration erzeugen, falls nötig
- flask db upgrade ausführen
- Prestart-Checks ausführen
- Gunicorn starten
```

#### `app.py`

```text
Aufgabe:
- Flask-App erzeugen
- Config laden
- db/migrate initialisieren
- Models importieren
- Blueprints registrieren
- Startup Hooks ausführen
- Health-Routen bereitstellen
```

#### `wsgi.py`

```text
Aufgabe:
- WSGI Entry für Gunicorn
- stellt app bereit
```

#### `extensions.py`

```text
Aufgabe:
- zentrale Flask-Extensions
- db = SQLAlchemy()
- migrate = Migrate()
- Extension-/DB-/Route-Status verwalten
```

#### `config.py`

```text
Aufgabe:
- Environment-/Runtime-Konfiguration
- DB-URI
- Route-Prefix
- Source-/Generated-/Cache-Pfade
- Migrations-/Bootstrap-Flags
```

---

## 8. `models/` – SQLAlchemy-Schicht

Aktuelle Model-Registry sieht 39 Tabellen.

```text
models/
├── __init__.py
├── creative_library.py
├── creative_library_drafts.py
├── creative_library_user.py
├── library_definitions.py
├── library_files.py
├── library_taxonomy.py
└── user_inventory.py
```

### 8.1 `models/__init__.py`

```text
Aufgabe:
- zentrale Model-Registry
- import_all_models()
- get_models_health()
- Lazy-Exports
- Alembic-Metadaten sichtbar machen
```

Wichtig:

```text
Alembic sieht Tabellen nur, wenn models.import_all_models() alle Modelmodule lädt.
```

### 8.2 Creative Library Published Models

Datei:

```text
models/creative_library.py
```

Tabellen:

```text
creative_library_items
creative_library_scan_runs
creative_library_revisions
creative_library_variants
creative_library_assets
creative_library_documents
creative_library_scan_issues
creative_library_inventory_slots
```

Rolle:

```text
Published Creative Library.
Das ist der persistente, produktive DB-Zustand für veröffentlichte Families/Items.
```

Besonders wichtig:

```text
CreativeLibraryItem
  Published Family/Item

CreativeLibraryRevision
  versionierter Inhaltsstand

CreativeLibraryVariant
  konkrete Variant einer Revision

CreativeLibraryAsset
  Preview/Mesh/Texture/File-Verweis

CreativeLibraryDocument
  persistierte JSON-/Dokumentrepräsentation

CreativeLibraryScanRun
  DB-Sync-/Scan-Ausführung

CreativeLibraryScanIssue
  Issues/Warnings/Errors aus Scan/Sync

CreativeLibraryInventorySlot
  Legacy/System-Inventar-Slot
```

### 8.3 Creative Library Draft Models

Datei:

```text
models/creative_library_drafts.py
```

Tabellen:

```text
creative_library_drafts
creative_library_draft_variants
creative_library_draft_assets
creative_library_draft_documents
creative_library_draft_validation_issues
creative_library_draft_audit_events
```

Rolle:

```text
Arbeits-/Generator-Zwischenschicht.
Drafts sind nicht Published Truth.
Sie dienen zum Erstellen, Bearbeiten, Validieren und späteren Publizieren.
```

Datenfluss:

```text
Create UI / Generator
  -> Draft
  -> DraftVariant / DraftAsset / DraftDocument
  -> ValidationIssue
  -> Publish Prepare
  -> CreativeLibraryRevision
```

### 8.4 Creative Library User Models

Datei:

```text
models/creative_library_user.py
```

Tabellen:

```text
creative_library_collections
creative_library_collection_items
creative_library_user_overrides
creative_library_user_audit_events
```

Rolle:

```text
User-spezifische Sicht auf die Published Creative Library.
Collections, Favoriten, Overrides und Audit.
```

### 8.5 Definition Models

Datei:

```text
models/library_definitions.py
```

Tabellen:

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

Rolle:

```text
Persistente Definitionen für:
- Object Kinds
- Profiles
- Variables
- Units
- Materials
- Document Types
- Bindings
- Overrides
```

### 8.6 File Models

Datei:

```text
models/library_files.py
```

Tabellen:

```text
library_files
library_file_versions
library_file_links
library_file_audit_events
```

Rolle:

```text
Upload-/File-Metadaten für:
- 3D-Modelle
- Dokumente
- Texturen
- Previews
- Assets
- Versionen
- Verlinkungen zu Drafts/Families/Variants/Documents
```

### 8.7 Taxonomy Models

Datei:

```text
models/library_taxonomy.py
```

Tabellen:

```text
library_taxonomy_nodes
library_taxonomy_overrides
library_taxonomy_audit_events
```

Rolle:

```text
Persistente Taxonomie und user-/systembezogene Overrides.
```

### 8.8 User Inventory Models

Datei:

```text
models/user_inventory.py
```

Tabellen:

```text
user_inventory_states
user_inventory_slots
user_inventory_audit_events
```

Rolle:

```text
Editor-/Runtime-Hotbar pro User.

Phase 1:
- user_id default 1
- 9 Slots
- inventory_key default
```

---

## 9. `routes/` und `src/routes/` – HTTP-Außenkante

Im Projekt existieren historisch und aktuell mehrere Route-Orte. Der aktive Importkontext lädt Routen zuverlässig.

Wichtige Blueprints laut Startlog:

```text
vplib
vplib_library_api
library_bp
taxonomy
library_definition_routes
library_files
creative_library_user
creative_library_drafts
vplib_create
inventar
inventar_user
```

### 9.1 Route-Gruppen

```text
VPLIB Core:
  /api/v1/vplib/...

Library:
  /api/v1/vplib/library/...

Definitions:
  /api/v1/vplib/definitions/...

Files:
  /api/v1/vplib/files/...

Taxonomy:
  /api/v1/vplib/taxonomy/...

Creative Library User:
  /api/v1/vplib/creative-library/...

Drafts:
  /api/v1/vplib/library/drafts/...

Create:
  /api/v1/vplib/create/...
  /create

Inventar:
  /user-inventar
  /creative-inventar
  /api/v1/vplib/inventar_user/...
```

### 9.2 `routes/library_routes.py`

Rolle:

```text
HTTP-Adapter für Library-API.
```

Wichtige Routen:

```text
GET  /api/v1/vplib/library/health
GET  /api/v1/vplib/library/routes
GET  /api/v1/vplib/library/selftest
GET  /api/v1/vplib/library/scan
POST /api/v1/vplib/library/sync
GET  /api/v1/vplib/library/blocks
GET  /api/v1/vplib/library/tree
GET  /api/v1/vplib/library/published
GET  /api/v1/vplib/library/items
GET  /api/v1/vplib/library/items/<item_ref>
GET  /api/v1/vplib/library/vplib/<vplib_uid>
GET  /api/v1/vplib/library/scan-runs
GET  /api/v1/vplib/library/inventory/slots
```

Zentrale Regel:

```text
GET /scan schreibt nicht.
POST /sync schreibt.
```

### 9.3 `routes/library_definition_routes.py`

Rolle:

```text
Definition Catalog API.
```

Wichtige Routen:

```text
GET  /api/v1/vplib/definitions/health
GET  /api/v1/vplib/definitions/routes
GET  /api/v1/vplib/definitions/catalog
GET  /api/v1/vplib/definitions/current
GET  /api/v1/vplib/definitions/create-options
GET  /api/v1/vplib/definitions/create-context
GET  /api/v1/vplib/definitions/datasets
POST /api/v1/vplib/definitions/seed/preview
POST /api/v1/vplib/definitions/seed
```

### 9.4 `routes/library_files.py`

Rolle:

```text
File-/Upload-/Asset-Metadaten API.
```

Wichtige Routen:

```text
GET /api/v1/vplib/files/health
GET /api/v1/vplib/files/routes
GET /api/v1/vplib/files/constraints
GET /api/v1/vplib/files
GET /api/v1/vplib/files/links
GET /api/v1/vplib/files/context
```

### 9.5 `routes/taxonomy.py`

Rolle:

```text
Taxonomie API.
```

Wichtige Routen:

```text
GET /api/v1/vplib/taxonomy/health
GET /api/v1/vplib/taxonomy/routes
GET /api/v1/vplib/taxonomy/resolved
GET /api/v1/vplib/taxonomy/tree
GET /api/v1/vplib/taxonomy/nodes
GET /api/v1/vplib/taxonomy/create-options
```

### 9.6 `routes/creative_library_user_routes.py`

Rolle:

```text
User Collections / User Overrides / Creative-Library-User-Sicht.
```

Wichtige Routen:

```text
GET  /api/v1/vplib/creative-library/health
GET  /api/v1/vplib/creative-library/routes
GET  /api/v1/vplib/creative-library/resolved
GET  /api/v1/vplib/creative-library/inventory
GET  /api/v1/vplib/creative-library/defaults
GET  /api/v1/vplib/creative-library/collections
POST /api/v1/vplib/creative-library/collections
```

### 9.7 `routes/creative_library_draft_routes.py`

Rolle:

```text
Draft API.
```

Wichtige Routen:

```text
GET  /api/v1/vplib/library/drafts/health
GET  /api/v1/vplib/library/drafts/routes
GET  /api/v1/vplib/library/drafts
POST /api/v1/vplib/library/drafts
GET  /api/v1/vplib/library/drafts/<draft_ref>
POST /api/v1/vplib/library/drafts/<draft_ref>/validate
POST /api/v1/vplib/library/drafts/<draft_ref>/publish/prepare
```

### 9.8 `routes/create.py`

Rolle:

```text
Create Flow API und Create UI Einstieg.
```

Wichtige Routen:

```text
GET  /create
GET  /api/v1/vplib/create/health
GET  /api/v1/vplib/create/options
GET  /api/v1/vplib/create/context
POST /api/v1/vplib/create/draft
POST /api/v1/vplib/create/validate
POST /api/v1/vplib/create/package-plan
POST /api/v1/vplib/create/download
POST /api/v1/vplib/create/save
```

### 9.9 `routes/inventar.py`

Rolle:

```text
HTML-Routen für Inventar-UIs.
```

Routen:

```text
GET /user-inventar
GET /creative-inventar
```

### 9.10 `routes/inventar_user.py`

Rolle:

```text
Persistente User-Hotbar API.
```

Wichtige Routen:

```text
GET    /api/v1/vplib/inventar_user/health
GET    /api/v1/vplib/inventar_user
GET    /api/v1/vplib/inventar_user/state
GET    /api/v1/vplib/inventar_user/slots
PATCH  /api/v1/vplib/inventar_user/select-slot
POST   /api/v1/vplib/inventar_user/select-slot
PUT    /api/v1/vplib/inventar_user/slots/<slot_index>
PATCH  /api/v1/vplib/inventar_user/slots/<slot_index>
DELETE /api/v1/vplib/inventar_user/slots/<slot_index>
POST   /api/v1/vplib/inventar_user/cache/clear
```

---

## 10. `src/vplib` – technischer VPLIB-Kern

Rolle:

```text
Technische Package-/Manifest-/Creator-/Validator-Schicht.
```

Zuständigkeit:

```text
- vplib_uid-Service
- technische VPLIB-Validierung
- Package-Erzeugung
- Archive/Download
- Source Loader
- Default-Strukturen
- technische Manifest-/Modulregeln
```

Beziehung zu `src/library`:

```text
src/vplib
  technischer Kern

src/library
  fachliche Creative-Library-Schicht auf VPLIB-Basis
```

Wichtiger Grundsatz:

```text
src/library darf VPLIB nutzen,
aber src/vplib sollte nicht von Creative-Library-DB-/UI-Schichten abhängig sein.
```

---

## 11. `src/library` – fachliche Creative-Library-Schicht

Für `src/library` existiert zusätzlich eine separate Detaildokumentation. Im Gesamtprojekt ist diese Schicht der fachliche Kern der aktuellen Arbeit.

### 11.1 Struktur

```text
src/library/
├── __init__.py
├── source/
├── definitions/
├── taxonomy/
├── scanner/
├── validation/
├── domain/
├── read_models/
├── services/
└── repositories/
```

### 11.2 `source/`

Rolle:

```text
Menschenlesbare VPLIB Directory Packages.
```

Kanonisches Ziel-Layout:

```text
src/library/source/{domain}/{category}/{subcategory}/{family_slug}/
├── vplib.manifest.json
├── vplib.modules.json
├── family/
├── variants/
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

### 11.3 `definitions/`

Rolle:

```text
Backend-Definitionskatalog.
```

Inhalt:

```text
- document_types
- family_profiles
- materials
- object_kinds
- profile_bindings
- units
- variables
- variant_profiles
```

Datenquelle:

```text
src/library/definitions/data/*.json
```

Persistenz:

```text
models/library_definitions.py
```

Service/API:

```text
src/library/services/library_definition_catalog_service.py
src/library/services/library_definition_seed_service.py
routes/library_definition_routes.py
```

### 11.4 `taxonomy/`

Rolle:

```text
Kanonische Backend-Taxonomie.
```

Inhalt:

```text
- domain
- category
- subcategory
- object_kind bindings
- create-options
- validation helpers
```

Datenquelle:

```text
src/library/taxonomy/data/taxonomy.v1.json
```

Persistenz:

```text
models/library_taxonomy.py
```

Service/API:

```text
src/library/services/library_taxonomy_user_service.py
routes/taxonomy.py
```

### 11.5 `scanner/`

Rolle:

```text
Dateibasierter Source-Scan.
```

Bausteine:

```text
package_discovery.py
  findet Package-Kandidaten

package_reader.py
  liest JSON-Dokumente

package_fingerprint.py
  erzeugt revision_hash
```

Regel:

```text
Scanner schreibt nicht in DB.
```

### 11.6 `validation/`

Rolle:

```text
Fachliche Prüfung gelesener Packages.
```

Prüft:

```text
- Manifest
- Identity
- Classification
- Varianten
- Dokumentstruktur
- Module
- Taxonomie
- optionale VPLIB-Core-Regeln
```

### 11.7 `domain/`

Rolle:

```text
Dataclasses / Response-Domain-Modelle.
```

Wichtige Dateien:

```text
library_item.py
library_detail.py
scan_result.py
sync_result.py
publication.py
inventory.py
```

### 11.8 `read_models/`

Rolle:

```text
API-nahe Builder.
```

Zwei Pfade:

```text
Filesystem Debug Path:
- block_summary_builder.py
- block_detail_builder.py
- library_index_builder.py

DB Published Path:
- db_block_summary_builder.py
- db_block_detail_builder.py
- db_library_tree_builder.py
- db_inventory_builder.py
```

### 11.9 `services/`

Rolle:

```text
Fachliche Orchestrierung.
```

Wichtige Services:

```text
library_scan_service.py
  Source -> ScanResult

library_block_service.py
  Filesystem Debug Reads

library_create_service.py
  Create Draft / Validate / Package Plan / Save / Download

library_db_sync_service.py
  Source/ScanResult -> PostgreSQL

creative_library_service.py
  Published Creative Library Service über neues Repository

library_file_service.py
  Upload/File-Metadaten

creative_library_draft_service.py
  Draft CRUD/Validation/Publish Prepare

creative_library_user_service.py
  Collections/Overrides/User Sicht

library_definition_catalog_service.py
  Definitionskatalog lesen

library_definition_seed_service.py
  Definitionsdaten aus JSON in DB seeden

library_taxonomy_user_service.py
  Taxonomie + User Overrides
```

### 11.10 `repositories/`

Rolle:

```text
DB-Zugriff.
```

Wichtige Repositories:

```text
creative_library_repository.py
creative_library_draft_repository.py
creative_library_user_repository.py
library_definition_repository.py
library_file_repository.py
library_taxonomy_repository.py
user_inventory_repository.py
```

---

## 12. `src/services` – HTTP-nahe Services

Rolle:

```text
Adapter zwischen Routen und Fachservices.
Keine Flask-Abhängigkeit, aber HTTP-nahe Payload-Normalisierung.
```

Wichtige Dateien:

```text
library_route_service.py
  Legacy/File-Scan Route Adapter

library_create_route_service.py
  Create-Routen-Service

library_create_variant_payload_service.py
  Create-Payload-Normalisierung

vplib_route_service.py
  VPLIB-Core-Routen-Service
```

---

## 13. `templates/` – UI-Schicht

### 13.1 Struktur

```text
templates/
├── library_admin/
│   ├── create.html
│   └── create/
│       ├── _context_json.html
│       ├── _wizard_nav.html
│       ├── _stepper.html
│       ├── _preview.html
│       ├── _theme_toggle.html
│       ├── sections/
│       └── variants/
└── inventar/
    ├── user-inventar.html
    └── creative-inventar.html
```

### 13.2 Create UI

Rolle:

```text
Wizard für neue VPLIB-/Creative-Library-Elemente.
```

Kann genutzt werden:

```text
direkt:
  GET /create

eingebettet:
  GET /creative-inventar
  iframe -> /create
```

### 13.3 User-Inventar UI

Rolle:

```text
Transparente 9-Slot-Hotbar.
```

Ziel:

```text
Später über Editor/Viewport legen.
Nur Hotbar sichtbar.
Slot-Auswahl per Klick/Mausrad/Tastatur.
Persistenz über inventar_user API.
```

### 13.4 Creative-Inventar UI

Rolle:

```text
Creative Library Browser.
```

Elemente:

```text
- Taxonomie-Reiter
- Kategorien
- Subkategorien
- Creative Cards
- Button "Neues Element hinzufügen"
- Create iframe
- User-Hotbar Integration
```

---

## 14. `static/` – Frontend Assets

### 14.1 Inventar JavaScript

```text
static/js/inventar/
├── taxonomy-navigation.js
├── create-embed.js
└── user-inventory.js
```

#### `taxonomy-navigation.js`

```text
- lädt /api/v1/vplib/taxonomy/create-options
- rendert Domain-Reiter
- rendert Kategorien/Subkategorien
- setzt data-selected-domain/category/subcategory
- dispatcht taxonomy selection events
```

#### `create-embed.js`

```text
- öffnet/schließt Create iframe
- setzt data-create-embed-active
- blendet Creative Grid/Hotbar im Create-Modus aus
- lazy lädt /create
```

#### `user-inventory.js`

```text
- lädt /api/v1/vplib/inventar_user
- normalisiert 9 Slots
- verwaltet active_slot_index
- reagiert auf Mausrad
- reagiert auf Tastatur 1..9
- speichert Auswahl per PATCH /select-slot
- kann Slots setzen/löschen
```

### 14.2 Create JavaScript

```text
static/library_admin/js/
├── create.js
├── create_wizard.js
├── create_definitions.js
├── create_variant_utils.js
├── create_variant_state.js
├── create_variant_profiles.js
├── create_variant_summary.js
├── create_variant_field_renderer.js
├── create_variant_validation.js
├── create_variant_drawer.js
├── create_variant_table.js
└── create_variant_optional_fields.js
```

Rolle:

```text
Create Wizard, Variantenverwaltung, dynamische Felder, Profile, Validierung und Package-Plan.
```

### 14.3 CSS

```text
static/css/inventar/inventar.css
static/library_admin/css/create/*.css
```

Rolle:

```text
- Inventar Overlay
- Creative-Inventar Layout
- Taxonomie-Reiter
- Create Embed Panel
- Create Wizard Layout
- Varianten UI
- Responsive Verhalten
```

---

## 15. Hauptdatenflüsse

### 15.1 Source Scan

```text
GET /api/v1/vplib/library/scan?source=file
  ↓
routes/library_routes.py
  ↓
services/library_route_service.py
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
read_models/*
  ↓
JSON Response
```

Eigenschaft:

```text
read-only
keine DB-Writes
```

### 15.2 DB Sync

```text
POST /api/v1/vplib/library/sync
  ↓
routes/library_routes.py
  ↓
src/library/services/library_db_sync_service.py
  ↓
library_scan_service.scan_library_source()
  ↓
build_publish_payload_from_candidate()
  ↓
creative_library_service / creative_library_repository
  ↓
PostgreSQL
  ↓
SyncResult JSON
```

Eigenschaft:

```text
expliziter DB-Write
```

### 15.3 Published Library Read

```text
GET /api/v1/vplib/library/published
GET /api/v1/vplib/library/items
GET /api/v1/vplib/library/blocks
GET /api/v1/vplib/library/tree
  ↓
routes/library_routes.py
  ↓
creative_library_service
  ↓
creative_library_repository
  ↓
PostgreSQL
  ↓
Published JSON
```

### 15.4 Definitions Seed / Catalog

```text
definitions/data/*.json
  ↓
library_definition_seed_service
  ↓
library_definition_repository
  ↓
library_definition_* Tabellen
  ↓
library_definition_catalog_service
  ↓
GET /api/v1/vplib/definitions/catalog
```

### 15.5 Taxonomy

```text
taxonomy/data/taxonomy.v1.json
  ↓
taxonomy registry/service
  ↓
optional DB taxonomy nodes/overrides
  ↓
GET /api/v1/vplib/taxonomy/create-options
  ↓
Creative-Inventar Navigation
```

### 15.6 Create Flow

```text
GET /create
  ↓
Create UI
  ↓
GET /api/v1/vplib/create/options
  ↓
POST /api/v1/vplib/create/draft
  ↓
POST /api/v1/vplib/create/validate
  ↓
POST /api/v1/vplib/create/package-plan
  ↓
POST /api/v1/vplib/create/save
  ↓
Source Package / Draft / später Sync
```

### 15.7 Draft Flow

```text
POST /api/v1/vplib/library/drafts
  ↓
creative_library_draft_service
  ↓
creative_library_draft_repository
  ↓
creative_library_drafts + child tables
  ↓
validate
  ↓
publish/prepare
  ↓
Published Payload
```

### 15.8 File Flow

```text
Upload / File Metadata
  ↓
library_file_service
  ↓
library_file_repository
  ↓
library_files
  ↓
library_file_versions
  ↓
library_file_links
  ↓
Assets/Documents/Drafts/Variants referenzieren File IDs
```

### 15.9 User Inventory Flow

```text
GET /user-inventar
  ↓
user-inventory.js
  ↓
GET /api/v1/vplib/inventar_user
  ↓
user_inventory_service
  ↓
user_inventory_repository
  ↓
user_inventory_states + user_inventory_slots
  ↓
Hotbar UI
```

Slot-Auswahl:

```text
Mausrad / Taste 1..9 / Klick
  ↓
PATCH /api/v1/vplib/inventar_user/select-slot
  ↓
active_slot_index speichern
  ↓
selected Slot aktualisieren
```

### 15.10 Creative Card in User Slot

Zielpfad:

```text
Creative Card auswählen
  ↓
aktiver Slot wird bestimmt
  ↓
PUT /api/v1/vplib/inventar_user/slots/<slot_index>
  ↓
UserInventorySlot speichert vplib_uid/family_id/variant_id
  ↓
Hotbar zeigt Item
  ↓
Editor nutzt aktiven Slot
```

---

## 16. Datenbanktabellen nach Bereich

### 16.1 Published Creative Library

```text
creative_library_items
creative_library_scan_runs
creative_library_revisions
creative_library_variants
creative_library_assets
creative_library_documents
creative_library_scan_issues
creative_library_inventory_slots
```

### 16.2 Drafts

```text
creative_library_drafts
creative_library_draft_variants
creative_library_draft_assets
creative_library_draft_documents
creative_library_draft_validation_issues
creative_library_draft_audit_events
```

### 16.3 Creative Library User Layer

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

### 16.7 User Inventory

```text
user_inventory_states
user_inventory_slots
user_inventory_audit_events
```

---

## 17. Testplan ab aktuellem Stand

### 17.1 Bereits getestete Basis

```text
GET /api/v1/vplib/library/health
GET /api/v1/vplib/library/scan?source=file
GET /api/v1/vplib/definitions/health
GET /api/v1/vplib/files/health
GET /api/v1/vplib/taxonomy/health
GET /api/v1/vplib/creative-library/health
GET /api/v1/vplib/library/drafts/health
```

### 17.2 Nächste Library-Tests

```text
GET  /api/v1/vplib/library/routes
GET  /api/v1/vplib/library/selftest
GET  /api/v1/vplib/library/blocks?source=file
GET  /api/v1/vplib/library/tree?source=file
POST /api/v1/vplib/library/sync
GET  /api/v1/vplib/library/published
GET  /api/v1/vplib/library/items
GET  /api/v1/vplib/library/blocks
GET  /api/v1/vplib/library/tree
GET  /api/v1/vplib/library/scan-runs
GET  /api/v1/vplib/library/inventory/slots
```

### 17.3 Nächste Definitions-Tests

```text
GET  /api/v1/vplib/definitions/routes
GET  /api/v1/vplib/definitions/catalog
GET  /api/v1/vplib/definitions/current
GET  /api/v1/vplib/definitions/create-options
GET  /api/v1/vplib/definitions/create-context
GET  /api/v1/vplib/definitions/datasets
POST /api/v1/vplib/definitions/seed/preview
POST /api/v1/vplib/definitions/seed
```

### 17.4 Nächste Taxonomy-Tests

```text
GET /api/v1/vplib/taxonomy/routes
GET /api/v1/vplib/taxonomy/resolved
GET /api/v1/vplib/taxonomy/tree
GET /api/v1/vplib/taxonomy/nodes
GET /api/v1/vplib/taxonomy/create-options
```

### 17.5 Nächste Files-Tests

```text
GET /api/v1/vplib/files/routes
GET /api/v1/vplib/files/constraints
GET /api/v1/vplib/files
GET /api/v1/vplib/files/links
GET /api/v1/vplib/files/context
```

### 17.6 Nächste Draft-Tests

```text
GET  /api/v1/vplib/library/drafts/routes
GET  /api/v1/vplib/library/drafts
POST /api/v1/vplib/library/drafts
GET  /api/v1/vplib/library/drafts/<draft_ref>
POST /api/v1/vplib/library/drafts/<draft_ref>/validate
POST /api/v1/vplib/library/drafts/<draft_ref>/publish/prepare
```

Minimaler Draft-Testbody:

```json
{
  "label": "Test Draft",
  "family_id": "test.family",
  "package_id": "test.package",
  "object_kind": "test",
  "domain": "test",
  "category": "test",
  "subcategory": "test"
}
```

### 17.7 Nächste Create-Tests

```text
GET  /api/v1/vplib/create/health
GET  /api/v1/vplib/create/options
GET  /api/v1/vplib/create/context
POST /api/v1/vplib/create/draft
POST /api/v1/vplib/create/validate
POST /api/v1/vplib/create/package-plan
POST /api/v1/vplib/create/download
```

`save` erst bewusst testen:

```text
POST /api/v1/vplib/create/save
```

### 17.8 Nächste Creative-Library-User-Tests

```text
GET  /api/v1/vplib/creative-library/routes
GET  /api/v1/vplib/creative-library/resolved
GET  /api/v1/vplib/creative-library/inventory
GET  /api/v1/vplib/creative-library/defaults
GET  /api/v1/vplib/creative-library/collections
POST /api/v1/vplib/creative-library/collections
```

### 17.9 Nächste User-Inventar-Tests

```text
GET    /api/v1/vplib/inventar_user/health
GET    /api/v1/vplib/inventar_user
GET    /api/v1/vplib/inventar_user/state
GET    /api/v1/vplib/inventar_user/slots
PATCH  /api/v1/vplib/inventar_user/select-slot
PUT    /api/v1/vplib/inventar_user/slots/1
DELETE /api/v1/vplib/inventar_user/slots/1
```

---

## 18. Statusmatrix

| Bereich | Status | Bedeutung |
|---|---:|---|
| Docker Compose Library Stack | grün | Library-Service startet |
| vectoplan-library-db | grün | PostgreSQL erreichbar |
| Flask App Factory | grün | App initialisiert |
| Gunicorn | grün | Worker starten |
| Flask-SQLAlchemy | grün | Models sichtbar |
| Flask-Migrate/Alembic | grün | Migration erzeugt und Upgrade erfolgreich |
| Model-Registry | grün | 39 Tabellen sichtbar |
| Creative Library Models | grün | Published Tabellen vorhanden |
| Draft Models | grün | Draft Tabellen vorhanden |
| Definition Models | grün | Definition Tabellen vorhanden |
| File Models | grün | File Tabellen vorhanden |
| Taxonomy Models | grün | Taxonomy Tabellen vorhanden |
| User Inventory Models | grün | Tabellen in Migration sichtbar |
| Route-Registry | grün-gelb | Blueprints registriert, Warnung bleibt |
| Settings-Health | gelb | NoneType-Warnung, nicht blockierend |
| Source Scan | grün | `/scan?source=file` 200 |
| Library Health | grün | `/library/health` 200 |
| Definitions Health | grün | `/definitions/health` 200 |
| Files Health | grün | `/files/health` 200 |
| Taxonomy Health | grün | `/taxonomy/health` 200 |
| Creative Library User Health | grün | `/creative-library/health` 200 |
| Drafts Health | grün | `/library/drafts/health` 200 |
| DB Sync | gelb | als nächstes testen |
| Published Reads | gelb | nach Sync testen |
| Create Flow | gelb | Options/Draft/Validate testen |
| Draft CRUD | gelb | nach Health testen |
| File Upload | gelb | nach Constraints testen |
| User Inventory API | gelb | Health/State/Slots testen |
| UI Browser Tests | gelb | /user-inventar, /creative-inventar, /create testen |
| Editor Integration | offen | spätere Verbindung mit Hotbar |

---

## 19. Risiken und offene Punkte

### P0 – DB-Sync testen

```text
POST /api/v1/vplib/library/sync
```

Erwartung:

```text
ok=true
kein Timeout
keine rekursive Serialisierung
ScanRun wird angelegt
gültige Packages werden publiziert
Wiederholung erzeugt keine unnötigen Revisionen
```

### P0 – Published Reads nach Sync

```text
GET /api/v1/vplib/library/published
GET /api/v1/vplib/library/items
GET /api/v1/vplib/library/blocks
GET /api/v1/vplib/library/tree
```

Erwartung:

```text
200
ok=true
bei vorhandenen Source-Packages: nicht leer
```

### P0 – Route-Warnung auflösen

Warnung:

```text
One or more required blueprints are missing.
```

Vorgehen:

```text
- erwartete Required-Blueprint-Liste prüfen
- tatsächlich registrierte Blueprints vergleichen
- veraltete Required-Namen entfernen oder Alias ergänzen
```

### P1 – Settings-Warnungen bereinigen

Warnungen:

```text
VPLIB settings check failed: 'NoneType' object has no attribute '__dict__'
Library settings check failed: 'NoneType' object has no attribute '__dict__'
```

Vorgehen:

```text
- Health-/Settings-Funktionen null-safe machen
- None als "unavailable/partial" statt Exception behandeln
```

### P1 – User Inventory End-to-End

```text
GET /api/v1/vplib/inventar_user
PATCH /api/v1/vplib/inventar_user/select-slot
Reload /user-inventar
```

Erwartung:

```text
9 Slots
active_slot_index persistiert
selected Slot konsistent
```

### P1 – Create/Draft End-to-End

```text
/create
POST /api/v1/vplib/create/draft
POST /api/v1/vplib/create/validate
POST /api/v1/vplib/create/package-plan
POST /api/v1/vplib/create/save
POST /api/v1/vplib/library/sync
GET /api/v1/vplib/library/items
```

### P2 – UI-Integration

```text
/creative-inventar
  Taxonomie laden
  Create iframe öffnen
  Create iframe schließen
  Cards filtern

/user-inventar
  transparent
  Mausrad
  Tastatur 1..9
  Persistenz
```

### P2 – Editor-Kopplung

Später:

```text
active_slot_index
  -> Editor Tool Selection
  -> Placement Mode
  -> Object Placement
```

---

## 20. Debug- und Prüfkommandos

### 20.1 Python Syntax

```powershell
docker compose exec -T vectoplan-library python -m py_compile models/__init__.py
docker compose exec -T vectoplan-library python -m py_compile models/creative_library.py
docker compose exec -T vectoplan-library python -m py_compile models/creative_library_drafts.py
docker compose exec -T vectoplan-library python -m py_compile models/creative_library_user.py
docker compose exec -T vectoplan-library python -m py_compile models/library_definitions.py
docker compose exec -T vectoplan-library python -m py_compile models/library_files.py
docker compose exec -T vectoplan-library python -m py_compile models/library_taxonomy.py
docker compose exec -T vectoplan-library python -m py_compile models/user_inventory.py
```

```powershell
docker compose exec -T vectoplan-library python -m py_compile routes/library_routes.py
docker compose exec -T vectoplan-library python -m py_compile routes/library_definition_routes.py
docker compose exec -T vectoplan-library python -m py_compile routes/taxonomy.py
docker compose exec -T vectoplan-library python -m py_compile routes/create.py
```

```powershell
docker compose exec -T vectoplan-library python -m py_compile src/library/services/library_scan_service.py
docker compose exec -T vectoplan-library python -m py_compile src/library/services/library_db_sync_service.py
docker compose exec -T vectoplan-library python -m py_compile src/library/services/creative_library_service.py
docker compose exec -T vectoplan-library python -m py_compile src/library/services/creative_library_draft_service.py
docker compose exec -T vectoplan-library python -m py_compile src/library/services/creative_library_user_service.py
docker compose exec -T vectoplan-library python -m py_compile src/library/services/library_file_service.py
```

### 20.2 DB Tabellen prüfen

```powershell
docker compose exec -T vectoplan-library-db psql -U vectoplan -d vectoplan_library -c "select table_name from information_schema.tables where table_schema='public' order by table_name;"
```

### 20.3 Alembic Version prüfen

```powershell
docker compose exec -T vectoplan-library-db psql -U vectoplan -d vectoplan_library -c "select * from alembic_version;"
```

### 20.4 Health prüfen

```powershell
Invoke-RestMethod -Uri "http://localhost:5001/api/v1/vplib/library/health" | ConvertTo-Json -Depth 20
Invoke-RestMethod -Uri "http://localhost:5001/api/v1/vplib/definitions/health" | ConvertTo-Json -Depth 20
Invoke-RestMethod -Uri "http://localhost:5001/api/v1/vplib/files/health" | ConvertTo-Json -Depth 20
Invoke-RestMethod -Uri "http://localhost:5001/api/v1/vplib/taxonomy/health" | ConvertTo-Json -Depth 20
Invoke-RestMethod -Uri "http://localhost:5001/api/v1/vplib/creative-library/health" | ConvertTo-Json -Depth 20
Invoke-RestMethod -Uri "http://localhost:5001/api/v1/vplib/library/drafts/health" | ConvertTo-Json -Depth 20
```

### 20.5 Sync testen

```powershell
Invoke-RestMethod `
  -Method Post `
  -Uri "http://localhost:5001/api/v1/vplib/library/sync" `
  -ContentType "application/json" `
  -Body '{"scan":true,"force_refresh":true,"publish_valid_only":true}' |
  ConvertTo-Json -Depth 30
```

### 20.6 Published Reads testen

```powershell
Invoke-RestMethod -Uri "http://localhost:5001/api/v1/vplib/library/published" | ConvertTo-Json -Depth 30
Invoke-RestMethod -Uri "http://localhost:5001/api/v1/vplib/library/items" | ConvertTo-Json -Depth 30
Invoke-RestMethod -Uri "http://localhost:5001/api/v1/vplib/library/blocks" | ConvertTo-Json -Depth 30
Invoke-RestMethod -Uri "http://localhost:5001/api/v1/vplib/library/tree" | ConvertTo-Json -Depth 30
```

### 20.7 Draft testen

```powershell
Invoke-RestMethod `
  -Method Post `
  -Uri "http://localhost:5001/api/v1/vplib/library/drafts" `
  -ContentType "application/json" `
  -Body '{"label":"Test Draft","family_id":"test.family","package_id":"test.package","object_kind":"test","domain":"test","category":"test","subcategory":"test"}' |
  ConvertTo-Json -Depth 30
```

### 20.8 User Inventory testen

```powershell
Invoke-RestMethod -Uri "http://localhost:5001/api/v1/vplib/inventar_user/health" | ConvertTo-Json -Depth 30
Invoke-RestMethod -Uri "http://localhost:5001/api/v1/vplib/inventar_user?user_id=1&inventory_key=default" | ConvertTo-Json -Depth 40
```

```powershell
Invoke-RestMethod `
  -Method Patch `
  -Uri "http://localhost:5001/api/v1/vplib/inventar_user/select-slot" `
  -ContentType "application/json" `
  -Body '{"user_id":1,"inventory_key":"default","slot_index":3}' |
  ConvertTo-Json -Depth 40
```

---

## 21. Definition of Done – aktueller Gesamtabschnitt

Der aktuelle Gesamtabschnitt gilt als stabil, wenn:

```text
1. Container starten ohne Error.
2. Gunicorn läuft.
3. /health/live und /health/ready liefern 200.
4. SQLAlchemy sieht alle erwarteten Tabellen.
5. Alembic-Version ist gesetzt.
6. Alle Health-Routen liefern 200.
7. /library/routes und /library/selftest liefern 200.
8. /library/scan?source=file liefert 200.
9. POST /library/sync liefert ok=true.
10. Wiederholter POST /library/sync erzeugt keine unnötigen Revisionen.
11. /library/published und /library/items liefern konsistente DB-Daten.
12. /definitions/catalog liefert einen sinnvollen Katalog.
13. /taxonomy/create-options liefert UI-taugliche Taxonomie.
14. /files/constraints und /files/context liefern sinnvolle Antworten.
15. /library/drafts kann Draft erstellen und lesen.
16. /create/options funktioniert.
17. /creative-library/collections funktioniert.
18. /inventar_user liefert 9 Slots.
19. Slot-Auswahl persistiert.
20. /user-inventar zeigt transparente Hotbar.
21. /creative-inventar lädt Taxonomie und kann /create einbetten.
22. Keine P0-Startup-Warnung bleibt offen.
```

---

## 22. Nächste sinnvolle Reihenfolge

```text
1. /api/v1/vplib/library/routes testen
2. /api/v1/vplib/library/selftest testen
3. POST /api/v1/vplib/library/sync testen
4. Published DB Reads testen
5. Definitions catalog/seed testen
6. Taxonomy tree/create-options testen
7. Files constraints/context testen
8. Draft CRUD testen
9. Create options/draft/validate/package-plan testen
10. User Inventory health/state/slots/select testen
11. Browser: /user-inventar testen
12. Browser: /creative-inventar testen
13. Create iframe im Creative-Inventar testen
14. Creative Card → User Hotbar integrieren
15. Editor-Kopplung planen
```

---

## 23. Kurzfazit für Weiterarbeit

Der Stand ist deutlich besser als vor den Model-/Migration-Fixes.

Aktuell:

```text
Stabil:
- Containerstart
- DB-Bootstrap
- Migration
- Model-Import
- Blueprint-Registrierung
- zentrale Health-Routen
- Scan-Read-Pfad

Als nächstes wirklich beweisen:
- Sync schreibt valide Daten in DB
- Published Reads liefern DB-Daten
- Draft/Create funktionieren E2E
- User Inventory persistiert Slotzustand
- UI verbindet Creative Library, Create und Hotbar
```

Der nächste technische Schwerpunkt ist damit nicht mehr „Startfehler beheben“, sondern:

```text
API-Testmatrix vollständig abarbeiten
→ dann fachliche E2E-Flows stabilisieren
→ dann UI-Verbindung mit Editor vorbereiten
```
