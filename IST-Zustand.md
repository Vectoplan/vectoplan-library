<!-- services/vectoplan-library/IST-Zustand.md -->

# Haupt-IST-Zustand – `services/vectoplan-library`

Stand: **2026-06-26**  
Zeitzone/Arbeitskontext: Europe/Berlin  
Service: `services/vectoplan-library`  
Dokumenttyp: technischer Haupt-IST-Stand mit Architektur-, Ordnerstruktur-, Datei-, Runtime-, Datenbank-, Migration-, VPLIB-, Creative-Library-, Create-Flow-, Taxonomie-, Inventar-, User-Hotbar-, API-, UI- und Testübersicht.

---

## 0. Kurzstatus am 2026-06-26

Der `vectoplan-library` Service ist inzwischen auf dem Weg von einem reinen Library-/Create-/DB-Read-Service zu einer zusammenhängenden UI-Schicht für Editor, Creative Library, Create Flow und User-Inventar.

Aktuell existieren drei UI-Schwerpunkte:

```text
1. Creative-Inventar
   - /creative-inventar
   - obere Taxonomie-Reiter
   - Kategorien/Subkategorien aus Backend-Taxonomie
   - Creative Library Cards
   - eingebetteter Create-Flow über /create

2. User-Inventar
   - /user-inventar
   - transparente 9-Slot-Hotbar
   - Overlay-tauglich für späteren Editor
   - Mausrad-/Keyboard-Navigation geplant und per JS vorbereitet
   - Persistenz über neue User-Inventar-API vorbereitet

3. Create-Flow
   - /create
   - bleibt eigenständige Create-Seite
   - wird zusätzlich im Creative-Inventar als iframe eingebettet
   - soll perspektivisch neue VPLIB-Packages erzeugen, speichern und danach in Library/DB sichtbar machen
```

Der Fokus hat sich damit erweitert:

```text
Vorher:
  Source Package → Scan → DB Sync → Published API

Jetzt zusätzlich:
  Published API + Taxonomie + Create + Inventar → zusammenhängende UI
```

---

## 1. Aktuell bewiesen

```text
✅ PostgreSQL läuft.
✅ Flask-SQLAlchemy ist angebunden.
✅ Flask-Migrate/Alembic funktioniert im Container.
✅ Creative-Library-Tabellen existieren.
✅ Repository-Import funktioniert.
✅ SQLAlchemy-Session funktioniert.
✅ library_db_sync_service importiert.
✅ library_published_service importiert.
✅ vplib_uid wird aus vplib.manifest.json erkannt.
✅ Testblock wurde erfolgreich in PostgreSQL synchronisiert.
✅ creative_library_items enthält den Testblock.
✅ creative_library_revisions enthält eine Revision.
✅ creative_library_variants enthält eine Variante.
✅ creative_library_assets enthält einen Asset-Datensatz.
✅ creative_library_documents enthält 13 Dokumentzeilen.
✅ GET /api/v1/vplib/library/blocks?source=db&limit=20 funktioniert.
✅ GET /api/v1/vplib/library/tree?source=db funktioniert.
✅ GET /api/v1/vplib/library/blocks/<block_id>/variants?source=db antwortet technisch ok.
✅ /api/v1/vplib/taxonomy/create-options liefert die Backend-Taxonomie für UI-Navigation.
✅ /create existiert als eigenständige Create-Frontend-Route.
✅ /user-inventar und /creative-inventar existieren als HTML-Routen.
✅ Creative-Inventar lädt Taxonomie-Reiter aus Backend-Route statt hart codierter Taxonomie.
✅ Creative-Inventar kann /create im Hauptbereich einbetten.
✅ User-Inventar-Template wurde zu einem transparenten Overlay umgebaut.
✅ Neue User-Inventar-Datenmodelle wurden fachlich entworfen/generiert.
✅ Neue User-Inventar-Repository-/Service-/Route-/JS-Schicht wurde entworfen/generiert.
```

---

## 2. Aktuell gelb / offen

```text
⚠️ Neue User-Inventar-Modelle müssen migriert werden:
   user_inventory_states
   user_inventory_slots

⚠️ Danach muss flask db migrate / flask db upgrade laufen.

⚠️ Die neu generierten Dateien müssen im Container py_compile-geprüft werden.

⚠️ /api/v1/vplib/inventar_user muss nach Blueprint-Registrierung und Migration getestet werden.

⚠️ /user-inventar muss im Browser getestet werden:
   - transparentes Overlay
   - Mausrad-Navigation
   - aktive Slot-Markierung
   - Persistenz nach Reload

⚠️ Creative-Inventar Create-Embed funktioniert konzeptionell, muss aber mit finalem CSS/JS nach Hard Reload visuell geprüft werden.

⚠️ GET /blocks/<block_id>?source=db muss final mit vollständigem JSON geprüft werden.

⚠️ GET /blocks/<block_id>/variants?source=db liefert aktuell ok=true, aber count=0,
   obwohl variant_count=1 und eine DB-Variante existiert.

⚠️ POST /sync muss nach den letzten Routing-/Repository-Korrekturen erneut gemessen werden.

⚠️ Der Testblock liegt noch im Legacy-Pfad mit Tiefe 3:
   src/library/source/hochbau/bloecke/basic_stone_block
   Klassifikation enthält aber subcategory=basis.
```

---

## 3. Aktuell rot

```text
❌ Varianten-Read ist fachlich noch nicht korrekt:
   /variants?source=db gibt count=0 zurück, obwohl die DB und die Listenroute variant_count=1 zeigen.
```

---

## 4. Zielbild: alles in eine UI bringen

Das Ziel ist eine Minecraft-/Hytale-ähnliche Editor-Experience für VECTOPLAN:

```text
Editor Viewport
  ↓
transparente User-Hotbar unten
  ↓
Creative Library / Inventar öffnen
  ↓
Taxonomie-Reiter:
  Alle | Hochbau | Tiefbau | Ingenieurbau | World Edit
  ↓
Kategorie / Subkategorie auswählen
  ↓
Block / Modul / Objekt / adaptives System wählen
  ↓
in User-Inventar-Slot legen
  ↓
im Editor platzieren
```

Parallel dazu:

```text
Creative Library
  ↓
"Neues Element hinzufügen"
  ↓
Create Flow wird eingebettet
  ↓
VPLIB Package anlegen
  ↓
Save
  ↓
Scan / Sync
  ↓
Published DB Read
  ↓
neues Element erscheint in Creative Library
```

Ziel ist also keine getrennte Admin-/Create-/Inventory-Welt mehr, sondern eine zusammenhängende UI:

```text
Create Flow
  erstellt neue Families/Variants

Creative Library
  durchsucht und filtert veröffentlichte Families/Variants

User-Inventar
  speichert die aktuelle Hotbar eines Users

Editor
  nutzt den aktuell ausgewählten Slot als aktives Werkzeug/Objekt
```

---

## 5. Architekturregeln

### 5.1 Source of Truth

```text
src/library/source/
  bleibt die menschenlesbare, versionierbare Quelle für VPLIB-Directory-Packages.

PostgreSQL
  ist der persistente Published-State und die Grundlage für produktive DB-Reads.

User-Inventar-Tabellen
  speichern den aktuellen Runtime-/Editor-Zustand pro User.

generated/
  bleibt Runtime-/Output-/Cache-Bereich und ist keine fachliche Source of Truth.
```

### 5.2 Read-/Write-Trennung

```text
GET /api/v1/vplib/library/scan
  liest/scant dateibasiert
  schreibt nicht in PostgreSQL

POST /api/v1/vplib/library/sync
  scannt dateibasiert
  schreibt über Repository nach PostgreSQL

GET /api/v1/vplib/library/blocks?source=db
GET /api/v1/vplib/library/tree?source=db
GET /api/v1/vplib/library/inventory
  lesen produktiv aus PostgreSQL

GET/PATCH/PUT/DELETE /api/v1/vplib/inventar_user/*
  lesen/schreiben User-Inventar-Zustand

?source=filesystem
  bleibt Debug-/Vergleichspfad
```

### 5.3 Route-Schichten

```text
routes/*
  HTTP-Adapter.
  Keine Business-Logik.
  Keine direkten SQLAlchemy-Queries.
  Keine Mockdaten.

library/services/*
  Ablauf-/Business-Logik.
  Validierung, Normalisierung, Response-Payloads.

library/repositories/*
  DB-Zugriff.
  SQLAlchemy-Session.
  Queries und Schreiboperationen.

models/*
  SQLAlchemy-Tabellen.
  Keine Migrationen.
  Kein db.create_all().
```

### 5.4 ID-Regeln

```text
vplib_uid
  stabile technische Package-ID
  wird nicht von der DB erzeugt
  wird im Manifest gespeichert
  ist Upsert-Schlüssel im DB-Sync

family_id
  semantische Family-ID
  Beispiel: vp.hochbau.bloecke.basic_stone_block

package_id
  semantische Package-ID
  Beispiel: vplib.vp.hochbau.bloecke.basic_stone_block

revision_hash
  Inhaltsfingerprint
  bestimmt, ob eine neue Revision entsteht

user_id
  Phase 1: default 1
  später echter Editor-/Account-/Session-Kontext

slot_index
  User-Hotbar-Slot 1..9
```

---

## 6. Gesamtstruktur im Repository

```text
.
├── docker-compose.yml
├── services/
│   ├── vectoplan-editor/
│   ├── vectoplan-library/
│   └── vectoplan-chunk/
└── ...
```

### 6.1 `services/vectoplan-library`

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
│   ├── __init__.py
│   ├── creative_library.py
│   └── user_inventory.py
├── migrations/
│   ├── README
│   ├── alembic.ini
│   ├── env.py
│   ├── script.py.mako
│   └── versions/
│       └── *.py
├── src/
│   ├── __init__.py
│   ├── bootstrap/
│   ├── config/
│   ├── routes/
│   │   ├── __init__.py
│   │   ├── api.py
│   │   ├── vplib_routes.py
│   │   ├── library_routes.py
│   │   ├── create.py
│   │   ├── library_definition_routes.py
│   │   ├── taxonomy.py
│   │   ├── inventar.py
│   │   └── inventar_user.py
│   ├── services/
│   ├── vplib/
│   └── library/
│       ├── __init__.py
│       ├── source/
│       ├── definitions/
│       ├── taxonomy/
│       ├── scanner/
│       ├── validation/
│       ├── domain/
│       ├── read_models/
│       ├── services/
│       │   ├── __init__.py
│       │   ├── library_scan_service.py
│       │   ├── library_block_service.py
│       │   ├── library_create_service.py
│       │   ├── library_db_sync_service.py
│       │   ├── library_published_service.py
│       │   └── user_inventory_service.py
│       └── repositories/
│           ├── __init__.py
│           ├── user_inventory_repository.py
│           └── sql/
│               ├── __init__.py
│               └── creative_library_repository.py
├── templates/
│   ├── library_admin/
│   │   ├── create.html
│   │   └── create/
│   │       └── ...
│   └── inventar/
│       ├── user-inventar.html
│       └── creative-inventar.html
├── static/
│   ├── library_admin/
│   │   ├── css/
│   │   └── js/
│   ├── css/
│   │   └── inventar/
│   │       └── inventar.css
│   └── js/
│       └── inventar/
│           ├── taxonomy-navigation.js
│           ├── create-embed.js
│           └── user-inventory.js
├── generated/
│   ├── vplib/
│   ├── archives/
│   ├── vplib_test/
│   ├── library/
│   └── library_cache/
├── sources/
└── creative_library/
```

---

## 7. Root-Dateien im Detail

### 7.1 `Dockerfile`

```text
Aufgabe:
  Baut das Runtime-Image des Library-Service.

Macht:
  - Python Runtime bereitstellen
  - Systempakete installieren
  - PostgreSQL-Client/pg_isready verfügbar machen
  - requirements.txt installieren
  - App-Code kopieren
  - entrypoint.sh als Startpunkt nutzen
```

### 7.2 `entrypoint.sh`

```text
Aufgabe:
  Containerstart orchestrieren.

Macht:
  - Runtime-Verzeichnisse vorbereiten
  - Strukturprüfungen ausführen
  - auf PostgreSQL warten
  - Flask-Migrate initialisieren, wenn nötig
  - Migrationen ausführen
  - Prestart-Checks starten
  - Gunicorn/wsgi:app starten
```

### 7.3 `requirements.txt`

```text
Wichtige Pakete:
  - Flask
  - Flask-SQLAlchemy
  - Flask-Migrate
  - SQLAlchemy
  - Alembic
  - psycopg[binary]
  - gunicorn
  - pytest
```

### 7.4 `app.py`

```text
Aufgabe:
  Flask-App-Factory.

Macht:
  - Config laden
  - extensions.db initialisieren
  - migrations initialisieren
  - models.import_all_models()
  - Blueprints registrieren
  - Startup-Hooks ausführen
  - Health-Routen bereitstellen
```

### 7.5 `extensions.py`

```text
Enthält:
  db = SQLAlchemy()
  migrate = Migrate()

Zusätzlich:
  Extension-Health
  DB-Initialisierung
  interne Extension-Registry
```

---

## 8. Datenbank und Migration

### 8.1 Vorhandene Creative-Library-Tabellen

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

### 8.2 Neue User-Inventar-Tabellen

Neu geplant/generiert:

```text
user_inventory_states
user_inventory_slots
```

#### `user_inventory_states`

```text
Fachlich:
  persistierter Zustand eines User-Inventars.

Speichert:
  - user_id
  - inventory_key
  - active_slot_index
  - last_selected_slot_index
  - last_selected_slot_key
  - last_selected_item_db_id
  - last_selected_vplib_uid
  - last_selected_family_id
  - last_selected_package_id
  - last_selected_variant_id
  - last_selected_label
  - last_selected_object_kind
  - last_selected_domain
  - last_selected_category
  - last_selected_subcategory
  - last_selected_taxonomy_path
  - slot_count
  - selected_at
  - last_loaded_at
  - last_synced_at
  - payload
  - settings
  - metadata_json
```

Eindeutigkeit:

```text
unique(user_id, inventory_key)
```

#### `user_inventory_slots`

```text
Fachlich:
  persistierter Inhalt eines einzelnen Hotbar-Slots.

Speichert:
  - user_id
  - inventory_key
  - slot_index
  - slot_key
  - item_db_id
  - vplib_uid
  - family_id
  - package_id
  - variant_id
  - label
  - description
  - object_kind
  - domain
  - category
  - subcategory
  - taxonomy_path
  - quantity
  - empty
  - selected
  - active
  - locked
  - pinned
  - icon
  - preview
  - assets
  - variant
  - placement
  - payload
  - meta
  - metadata_json
```

Eindeutigkeit:

```text
unique(user_id, inventory_key, slot_index)
unique(user_id, inventory_key, slot_key)
```

### 8.3 Migration erforderlich

Nach Einfügen der neuen Dateien:

```powershell
docker compose exec -T vectoplan-library flask db migrate -m "add user inventory tables"
docker compose exec -T vectoplan-library flask db upgrade
```

Danach prüfen:

```powershell
docker compose exec -T vectoplan-library-db psql -U vectoplan -d vectoplan_library -c "\dt"
```

Erwartung:

```text
user_inventory_states
user_inventory_slots
```

---

## 9. `models/`

```text
models/
├── __init__.py
├── creative_library.py
└── user_inventory.py
```

### 9.1 `models/__init__.py`

```text
Aufgabe:
  zentrale Model-Registry und Alembic-Importpunkt.

Aktueller Stand:
  - creative_library registriert
  - user_inventory registriert
  - Lazy Imports über __getattr__
  - import_all_models() lädt beide Model-Module
  - get_models_health() zeigt Creative- und User-Inventar-Fähigkeit
```

Wichtig:

```text
Alembic sieht neue Tabellen nur, wenn:
  - models/user_inventory.py existiert
  - models/__init__.py user_inventory registriert
  - app.py import_all_models() aufruft
```

### 9.2 `models/creative_library.py`

```text
Aufgabe:
  SQLAlchemy-Modelle für Creative Library.

Tabellen:
  - creative_library_items
  - creative_library_scan_runs
  - creative_library_revisions
  - creative_library_variants
  - creative_library_assets
  - creative_library_documents
  - creative_library_scan_issues
  - creative_library_inventory_slots
```

### 9.3 `models/user_inventory.py`

```text
Aufgabe:
  SQLAlchemy-Modelle für persistiertes User-Inventar.

Modelle:
  - UserInventoryState
  - UserInventorySlot

Phase 1:
  - DEFAULT_USER_ID = 1
  - DEFAULT_INVENTORY_KEY = "default"
  - DEFAULT_SLOT_COUNT = 9
  - MIN_SLOT_INDEX = 1
  - MAX_SLOT_INDEX = 9
```

---

## 10. `src/routes`

```text
src/routes/
├── __init__.py
├── api.py
├── vplib_routes.py
├── library_routes.py
├── create.py
├── library_definition_routes.py
├── taxonomy.py
├── inventar.py
└── inventar_user.py
```

### 10.1 `routes/__init__.py`

```text
Aufgabe:
  zentrale Blueprint-Registry.

Aktueller Stand:
  Required:
    - routes.vplib_routes:vplib_bp
    - routes.library_routes:library_bp
    - routes.taxonomy:taxonomy_bp

  Optional:
    - routes.api:api_bp
    - routes.library_definition_routes:library_definition_bp
    - routes.create:create_bp
    - routes.inventar:inventar_bp
    - routes.inventar_user:inventar_user_bp
```

Wichtig:

```text
routes.admin wurde bewusst nicht weiterverwendet.
Inventar HTML liegt in routes.inventar.
User-Inventar API liegt in routes.inventar_user.
```

### 10.2 `routes/inventar.py`

```text
Aufgabe:
  minimaler HTML-Adapter.

Routen:
  GET /user-inventar
  GET /creative-inventar

Regel:
  Keine Mockdaten.
  Keine DB-Logik.
  Nur Template rendern.
```

### 10.3 `routes/inventar_user.py`

```text
Aufgabe:
  User-Inventar API.

Blueprint:
  inventar_user_bp

Prefix:
  /api/v1/vplib/inventar_user

Routen:
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

### 10.4 `routes/create.py`

```text
Aufgabe:
  Create UI und Create API.

Bietet:
  GET  /create
  GET  /api/v1/vplib/create/health
  GET  /api/v1/vplib/create/options
  POST /api/v1/vplib/create/draft
  POST /api/v1/vplib/create/validate
  POST /api/v1/vplib/create/package-plan
  POST /api/v1/vplib/create/download
  POST /api/v1/vplib/create/save
```

### 10.5 `routes/taxonomy.py`

```text
Aufgabe:
  Taxonomie API.

Wichtig für UI:
  GET /api/v1/vplib/taxonomy/create-options

Diese Route ist die Grundlage für:
  - Creative-Inventar Reiter
  - Kategorien
  - Subkategorien
  - später Create-/Filter-Vorbelegung
```

---

## 11. `src/library/repositories`

```text
repositories/
├── __init__.py
├── user_inventory_repository.py
└── sql/
    ├── __init__.py
    └── creative_library_repository.py
```

### 11.1 `repositories/sql/creative_library_repository.py`

```text
Aufgabe:
  konkrete SQLAlchemy-Zugriffsschicht für Creative Library.

Wichtige Lesemethoden:
  - get_family_by_vplib_uid
  - get_family_by_family_id
  - get_family_by_identifier
  - get_latest_revision
  - list_published_families
  - get_published_family_detail
  - get_family_variants
  - get_family_assets
  - get_family_documents
  - list_inventory_slots

Aktuell offen:
  - get_family_variants liefert für API fachlich count=0
```

### 11.2 `repositories/user_inventory_repository.py`

```text
Aufgabe:
  konkrete SQLAlchemy-Zugriffsschicht für User-Inventar.

Methoden:
  - get_state
  - get_slot
  - list_slots
  - ensure_default_inventory
  - select_slot
  - set_slot_item
  - clear_slot
  - get_snapshot
  - get_health

Regel:
  Repository kennt DB und Models.
  Repository kennt keine Flask-Route.
```

---

## 12. `src/library/services`

```text
services/
├── __init__.py
├── library_scan_service.py
├── library_block_service.py
├── library_create_service.py
├── library_db_sync_service.py
├── library_published_service.py
└── user_inventory_service.py
```

### 12.1 `library_scan_service.py`

```text
Aufgabe:
  dateibasierte Scan-Orchestrierung.
```

### 12.2 `library_db_sync_service.py`

```text
Aufgabe:
  Filesystem-Scan → PostgreSQL.

Status:
  historisch erfolgreich.
  nach letzten Fixes erneut final testen.
```

### 12.3 `library_published_service.py`

```text
Aufgabe:
  PostgreSQL → Published API-Daten.

Bietet:
  - list_published_blocks_response
  - get_published_block_detail_response
  - get_published_block_variants_response
  - get_published_tree_response
  - get_inventory_response

Aktueller Stand:
  - /blocks?source=db funktioniert
  - /tree?source=db funktioniert
  - /variants?source=db antwortet ok, aber count=0
```

### 12.4 `user_inventory_service.py`

```text
Aufgabe:
  fachliche Service-Logik für persistiertes User-Inventar.

Methoden:
  - get_inventory_response
  - select_slot_response
  - set_slot_response
  - clear_slot_response
  - clear_cache_response
  - get_service_health_response

Phase 1:
  - user_id default 1
  - inventory_key default "default"
  - exakt 9 Slots
```

Hinweis:

```text
Beim Einfügen prüfen:
  __all__ darf keinen nicht definierten Namen STATUS_CLEARED enthalten.
  Richtig ist STATUS_SLOT_CLEARED.
```

---

## 13. Templates

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

### 13.1 `templates/inventar/user-inventar.html`

```text
Aufgabe:
  transparente User-Hotbar als Overlay.

Aktueller Stand:
  - alter Textblock entfernt
  - keine Stage
  - keine große Arbeitsfläche
  - 9 Slots als HTML-Grundstruktur
  - data-user-id default 1
  - data-inventory-key default default
  - data-user-inventory-api-url
  - data-user-inventory-select-url
  - user-inventory.js eingebunden
```

Ziel:

```text
/user-inventar soll später über Editor/Viewport gelegt werden können.
Nur die Slots sind sichtbar und interaktiv.
Alles andere ist transparent.
```

### 13.2 `templates/inventar/creative-inventar.html`

```text
Aufgabe:
  Creative Library UI.

Aktueller Stand:
  - obere Taxonomie-Reiter bleiben sichtbar
  - Reiter werden per taxonomy-navigation.js aus Backend geladen
  - Kategorien/Subkategorien werden per Backend-Taxonomie gerendert
  - "Neues Element hinzufügen" / "Creative Library anzeigen" sitzt oben auf Reiter-Ebene
  - /create wird als iframe eingebettet
  - störender Create-Panel-Header wurde entfernt
  - User-Hotbar wird beim Create-Embed ausgeblendet
  - iframe füllt den verfügbaren Bereich
```

Wichtig:

```text
Der Create-Flow bleibt technisch /create.
Im Creative-Inventar wird er nur eingebettet.
```

### 13.3 `templates/library_admin/create.html`

```text
Aufgabe:
  Hauptseite des Create Wizards.

Wird verwendet:
  - direkt unter /create
  - eingebettet in /creative-inventar
```

---

## 14. Static JavaScript

```text
static/js/inventar/
├── taxonomy-navigation.js
├── create-embed.js
└── user-inventory.js

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

### 14.1 `static/js/inventar/taxonomy-navigation.js`

```text
Aufgabe:
  Taxonomie-Navigation für Creative-Inventar.

Macht:
  - lädt /api/v1/vplib/taxonomy/create-options
  - cached Ergebnis im sessionStorage
  - rendert Reiter:
    Alle, Hochbau, Tiefbau, Ingenieurbau, World Edit
  - rendert Kategorien je Domain
  - rendert Subkategorien je Kategorie
  - schreibt data-selected-domain/category/subcategory auf Root
  - dispatcht vectoplan:taxonomy-selection-change
```

### 14.2 `static/js/inventar/create-embed.js`

```text
Aufgabe:
  Einbettung des Create-Flows in Creative-Inventar.

Macht:
  - Button öffnen/schließen
  - iframe lazy laden
  - Kategorie/Subkategorie/Creative-Library ausblenden
  - User-Hotbar ausblenden
  - Root-State data-create-embed-active setzen
  - Buttonlabel wechseln:
    Neues Element hinzufügen
    Creative Library anzeigen
```

### 14.3 `static/js/inventar/user-inventory.js`

```text
Aufgabe:
  User-Hotbar Interaktion und Persistenz.

Macht:
  - lädt /api/v1/vplib/inventar_user
  - cached lokalen Zustand im localStorage
  - reagiert auf Mausrad
  - reagiert auf Tastatur 1..9, Pfeile, Home/End
  - setzt aktiven Slot visuell
  - speichert Auswahl über PATCH /select-slot
  - kann Slot-Inhalt setzen/löschen
  - dispatcht Events:
    vectoplan:user-inventory-ready
    vectoplan:user-inventory-load
    vectoplan:user-inventory-selection-change
    vectoplan:user-inventory-save
    vectoplan:user-inventory-error
```

---

## 15. Static CSS

```text
static/css/inventar/
└── inventar.css

static/library_admin/css/create/
├── tokens.css
├── base.css
├── layout.css
├── cards.css
├── forms.css
├── tables.css
├── preview.css
├── actions.css
├── wizard.css
├── definitions.css
├── variant-workspace.css
├── variant-table.css
├── variant-drawer.css
├── variant-fields.css
├── variant-optional-fields.css
├── variant-validation.css
├── themes.css
└── responsive.css
```

### 15.1 `static/css/inventar/inventar.css`

```text
Aufgabe:
  gemeinsames Inventar-CSS für:
    /user-inventar
    /creative-inventar

Enthält:
  - Grundwerte / Tokens
  - User-Inventar Overlay
  - User-Hotbar
  - Creative-Inventar Layout
  - Taxonomie-Reiter
  - Kategorie/Subkategorie-Filter
  - Create-Embed-Panel
  - Creative Cards
  - Rechte Tools
  - Responsive Regeln
```

Wichtige neue Regeln:

```text
.vp-user-inventar-overlay-page
  transparent, kein Seitenhintergrund

.vp-user-inventory-root
  fixed overlay, pointer-events none

.vp-user-hotbar--overlay
  nur Hotbar sichtbar, unten mittig, keine äußere Panel-Fläche

.vp-user-slot--active / [aria-selected=true]
  aktive Slot-Markierung

.vp-creative-layout[data-create-embed-active=true]
  Hotbar weg, Hauptbereich gewinnt Platz

.vp-create-embed-frame
  width: 100%
  height: 100%
```

---

## 16. Aktuelle UI-Datenflüsse

### 16.1 Creative-Inventar Taxonomie

```text
GET /creative-inventar
  ↓
templates/inventar/creative-inventar.html
  ↓
static/js/inventar/taxonomy-navigation.js
  ↓
GET /api/v1/vplib/taxonomy/create-options
  ↓
Reiter/Kategorien/Subkategorien rendern
  ↓
Root-Datasets aktualisieren
```

### 16.2 Creative-Inventar Create-Embed

```text
User klickt "Neues Element hinzufügen"
  ↓
static/js/inventar/create-embed.js
  ↓
data-create-embed-active=true
  ↓
Kategorie/Subkategorie/Grid/Hotbar ausblenden
  ↓
iframe src="/create"
  ↓
Create UI wird im Creative-Inventar angezeigt
```

### 16.3 User-Inventar Slot-Auswahl

```text
GET /user-inventar
  ↓
templates/inventar/user-inventar.html
  ↓
static/js/inventar/user-inventory.js
  ↓
GET /api/v1/vplib/inventar_user?user_id=1&inventory_key=default
  ↓
9 Slots laden/normalisieren
  ↓
Mausrad / Tastatur / Klick
  ↓
active_slot_index ändern
  ↓
PATCH /api/v1/vplib/inventar_user/select-slot
  ↓
UserInventoryState.active_slot_index speichern
  ↓
UserInventorySlot.selected synchronisieren
```

### 16.4 Späterer Ziel-Datenfluss: Creative Item in User-Inventar

```text
Creative-Library Card auswählen
  ↓
Item-Payload:
  vplib_uid
  family_id
  variant_id
  label
  object_kind
  domain/category/subcategory
  ↓
PUT /api/v1/vplib/inventar_user/slots/<slot_index>
  ↓
UserInventorySlot wird gesetzt
  ↓
Hotbar zeigt Item
  ↓
Editor verwendet aktiven Slot für Platzierung
```

---

## 17. API-Status

### 17.1 Funktionierende/etablierte Routen

```text
GET /api/v1/vplib/library/blocks?source=db&limit=20
  Status: grün

GET /api/v1/vplib/library/tree?source=db
  Status: grün

GET /api/v1/vplib/taxonomy/create-options
  Status: grün für UI-Navigation

GET /create
  Status: grün-gelb, UI vorhanden, E2E Save/Sync offen
```

### 17.2 Offene DB-Read-Route

```text
GET /api/v1/vplib/library/blocks/<block_id>/variants?source=db
  Status: rot-gelb
  Problem: count=0 trotz vorhandener default-Variante
```

### 17.3 Neue User-Inventar-API

```text
GET /api/v1/vplib/inventar_user/health
GET /api/v1/vplib/inventar_user
GET /api/v1/vplib/inventar_user/state
GET /api/v1/vplib/inventar_user/slots
PATCH /api/v1/vplib/inventar_user/select-slot
PUT /api/v1/vplib/inventar_user/slots/<slot_index>
PATCH /api/v1/vplib/inventar_user/slots/<slot_index>
DELETE /api/v1/vplib/inventar_user/slots/<slot_index>
POST /api/v1/vplib/inventar_user/cache/clear
```

Status:

```text
generiert/geplant.
Muss nach Migration und Service-Neustart getestet werden.
```

---

## 18. Testbefehle

### 18.1 Syntax prüfen

```powershell
docker compose exec -T vectoplan-library python -m py_compile models/user_inventory.py
docker compose exec -T vectoplan-library python -m py_compile models/__init__.py
docker compose exec -T vectoplan-library python -m py_compile src/library/repositories/user_inventory_repository.py
docker compose exec -T vectoplan-library python -m py_compile src/library/services/user_inventory_service.py
docker compose exec -T vectoplan-library python -m py_compile routes/inventar_user.py
docker compose exec -T vectoplan-library python -m py_compile routes/__init__.py
```

Zusätzlich bestehende kritische Dateien:

```powershell
docker compose exec -T vectoplan-library python -m py_compile routes/api.py
docker compose exec -T vectoplan-library python -m py_compile src/library/repositories/sql/creative_library_repository.py
docker compose exec -T vectoplan-library python -m py_compile src/library/services/library_published_service.py
docker compose exec -T vectoplan-library python -m py_compile src/library/services/library_db_sync_service.py
```

### 18.2 Migration erzeugen

```powershell
docker compose exec -T vectoplan-library flask db migrate -m "add user inventory tables"
docker compose exec -T vectoplan-library flask db upgrade
```

### 18.3 Neue Tabellen prüfen

```powershell
docker compose exec -T vectoplan-library-db psql -U vectoplan -d vectoplan_library -c "select table_name from information_schema.tables where table_schema='public' order by table_name;"
```

Erwartung:

```text
user_inventory_states
user_inventory_slots
```

### 18.4 User-Inventar API testen

```powershell
Invoke-RestMethod `
  -Uri "http://localhost:5001/api/v1/vplib/inventar_user/health" |
  ConvertTo-Json -Depth 30
```

```powershell
Invoke-RestMethod `
  -Uri "http://localhost:5001/api/v1/vplib/inventar_user?user_id=1&inventory_key=default" |
  ConvertTo-Json -Depth 40
```

```powershell
Invoke-RestMethod `
  -Method Patch `
  -Uri "http://localhost:5001/api/v1/vplib/inventar_user/select-slot" `
  -ContentType "application/json" `
  -Body '{"user_id":1,"inventory_key":"default","slot_index":3}' |
  ConvertTo-Json -Depth 40
```

Danach DB prüfen:

```powershell
docker compose exec -T vectoplan-library-db psql -U vectoplan -d vectoplan_library -c "select user_id, inventory_key, active_slot_index, last_selected_slot_index from user_inventory_states;"
```

```powershell
docker compose exec -T vectoplan-library-db psql -U vectoplan -d vectoplan_library -c "select user_id, inventory_key, slot_index, selected, empty, vplib_uid, family_id, variant_id from user_inventory_slots order by slot_index;"
```

### 18.5 Browser-Test

```text
/user-inventar
  - nur Hotbar sichtbar
  - Hintergrund transparent
  - keine Texte
  - Mausrad wechselt Slot
  - Slot-Auswahl bleibt nach Reload erhalten, wenn API/Migration funktioniert

/creative-inventar
  - Reiter aus Taxonomie sichtbar
  - Button rechts oben auf Reiter-Ebene
  - Klick zeigt /create iframe
  - Hotbar verschwindet im Create-Modus
  - iframe nutzt 100% des Bereichs
```

---

## 19. Statusmatrix

| Bereich | Status | Bemerkung |
|---|---:|---|
| Docker Compose | grün | Library-DB und Service laufen |
| PostgreSQL | grün | Creative-Library-Tabellen vorhanden |
| Flask-SQLAlchemy | grün | Session funktioniert |
| Flask-Migrate/Alembic | grün | Init/Migrate/Upgrade funktioniert |
| Creative-Library Models | grün | bestehende Tabellen vorhanden |
| User-Inventar Models | gelb | Datei generiert, Migration offen |
| User-Inventar Repository | gelb | Datei generiert, py_compile/API-Test offen |
| User-Inventar Service | gelb | Datei generiert, py_compile/API-Test offen |
| User-Inventar Route | gelb | Datei generiert, Blueprint-Test offen |
| User-Inventar JS | gelb | Datei generiert, Browser/API-Test offen |
| User-Inventar Overlay Template | grün-gelb | HTML/CSS erstellt, Browser-Test offen |
| Creative-Inventar Template | grün-gelb | Taxonomie + Create Embed erstellt |
| Creative-Inventar JS | grün-gelb | taxonomy-navigation/create-embed erstellt |
| Create iframe Einbindung | grün-gelb | visuell testen |
| Backend-Taxonomie | grün | create-options wird genutzt |
| Create UI | grün-gelb | /create vorhanden, Save/Sync E2E offen |
| Blocks-Liste DB | grün | count=1 |
| Tree DB | grün | root/hochbau/bloecke/basis |
| Detail DB | gelb | final mit Payload prüfen |
| Variants DB | rot-gelb | ok=true, aber count=0 |
| DB-Sync-Service | grün-gelb | historisch erfolgreich, erneut testen |
| Route Registry | grün-gelb | inventar_user ergänzt, Startup prüfen |
| Gesamte UI-Zusammenführung | gelb | Architektur steht, E2E noch offen |

---

## 20. Offene Aufgaben

### P0 – Neue User-Inventar-Dateien wirklich einfügen

```text
models/user_inventory.py
models/__init__.py
src/library/repositories/user_inventory_repository.py
src/library/services/user_inventory_service.py
routes/inventar_user.py
routes/__init__.py
templates/inventar/user-inventar.html
static/css/inventar/inventar.css
static/js/inventar/user-inventory.js
```

### P0 – Syntax prüfen

```text
python -m py_compile für alle neuen/geänderten Python-Dateien.
```

### P0 – Migration ausführen

```text
flask db migrate -m "add user inventory tables"
flask db upgrade
```

### P0 – User-Inventar API testen

```text
GET /api/v1/vplib/inventar_user/health
GET /api/v1/vplib/inventar_user
PATCH /api/v1/vplib/inventar_user/select-slot
```

### P0 – User-Inventar Browser testen

```text
/user-inventar
  Mausrad
  Tastatur 1..9
  aktive Markierung
  Reload-Persistenz
```

### P1 – Creative-Inventar Create Embed final visuell prüfen

```text
/creative-inventar
  Button auf Reiter-Ebene
  keine störenden Texte
  iframe 100% im verfügbaren Bereich
  User-Hotbar im Create-Modus ausgeblendet
```

### P1 – Creative Library Cards filtern

Aktuell vorbereitet, aber noch nicht final umgesetzt:

```text
data-domain
data-category
data-subcategory
```

Nächster Schritt:

```text
taxonomy-navigation.js oder eigenes filter-js erweitert Cards nach Auswahl.
```

### P1 – Creative Item in User-Inventar legen

Nächster Integrationsschritt:

```text
Creative Card auswählen
  ↓
PUT /api/v1/vplib/inventar_user/slots/<active_slot>
  ↓
Hotbar zeigt Item
```

### P1 – Varianten-Read reparieren

Datei:

```text
src/library/repositories/sql/creative_library_repository.py
```

Verdächtige Funktionen:

```text
get_family_variants()
_filter_not_deleted()
_filter_query_for_family_or_uid()
```

Erwartung:

```text
/variants?source=db
  ok=true
  count=1
  variants[0].variant_id=default
```

### P1 – Detail final dokumentieren

```text
GET /blocks/vp.hochbau.bloecke.basic_stone_block?source=db
```

Vollständige JSON-Antwort erfassen und prüfen:

```text
summary
revision
variants
assets
documents
raw_documents optional
validation
```

### P2 – Create → Save → Sync → DB Read E2E

```text
/create
  ↓
Save
  ↓
Scan/Sync
  ↓
DB Read
  ↓
Creative Library anzeigen
```

### P2 – Legacy-Pfad migrieren

Aktuell:

```text
source/hochbau/bloecke/basic_stone_block
```

Ziel:

```text
source/hochbau/bloecke/basis/basic_stone_block
```

---

## 21. Definition of Done für UI-Zusammenführung

Der aktuelle UI-Zusammenführungsabschnitt gilt als abgeschlossen, wenn:

```text
1. /user-inventar zeigt nur die transparente Hotbar.
2. /user-inventar hat keine Texte, keine Stage und keine äußere Fläche.
3. Mausrad wechselt Slot 1..9 zyklisch.
4. Slotwechsel wird in user_inventory_states gespeichert.
5. user_inventory_slots enthält exakt 9 Slots für user_id=1/default.
6. Reload zeigt den zuletzt ausgewählten Slot.
7. /creative-inventar lädt Taxonomie aus Backend.
8. Kategorien/Subkategorien bleiben auswählbar.
9. Create-Button sitzt auf Reiter-Ebene.
10. Create-iframe ersetzt Kategorien/Subkategorien/Grid im Hauptbereich.
11. User-Hotbar ist im Create-Modus ausgeblendet.
12. /create funktioniert weiterhin direkt.
13. Ein Creative-Library-Item kann später in einen User-Slot geschrieben werden.
14. Migrationen liegen lokal im Repo.
15. Alle neuen Python-Dateien bestehen py_compile.
16. Keine Startup-Warnung wegen fehlender inventar_user-Route.
```

---

## 22. Kurzfazit

`services/vectoplan-library` hat jetzt eine deutlich klarere Richtung:

```text
VPLIB-Core:
  grün

Dateibasierte Creative Library:
  grün

PostgreSQL / Migration:
  grün für bestehende Tabellen
  gelb für neue User-Inventar-Tabellen bis Migration ausgeführt ist

Published DB Reads:
  Blocks und Tree grün
  Detail final prüfen
  Variants fachlich noch falsch mit count=0

Create Flow:
  grün-gelb
  direkt unter /create vorhanden
  in Creative-Inventar eingebettet

Creative-Inventar:
  grün-gelb
  Taxonomie-Navigation aus Backend
  Create Embed vorhanden

User-Inventar:
  gelb
  Overlay-UI erstellt
  persistente DB-/API-Schicht generiert
  Migration und Tests offen
```

Der aktuelle harte nächste Schritt ist:

```text
1. Dateien einfügen.
2. py_compile ausführen.
3. Migration erzeugen.
4. /api/v1/vplib/inventar_user testen.
5. /user-inventar im Browser testen.
6. Danach Creative Card → User-Hotbar Slot integrieren.
```

Der offene Rest ist damit keine neue Architekturfrage mehr, sondern gezielte Stabilisierung und End-to-End-Verifikation der UI- und DB-Integration.
