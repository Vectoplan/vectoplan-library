<!-- services/vectoplan-library/IST-Zustand.md -->

# Haupt-IST-Zustand – `services/vectoplan-library`

Stand: **2026-06-05**  
Zeitzone/Arbeitskontext: Europe/Berlin  
Service: `services/vectoplan-library`  
Dokumenttyp: technischer Haupt-IST-Stand mit Architektur-, Ordnerstruktur-, Datei-, Runtime-, Datenbank-, Migration-, VPLIB-, Creative-Library-, Create-Flow-, Repository-, DB-Sync-, Published-Read-, API-, Frontend- und Testübersicht.

---

## 0. Kurzstatus am 2026-06-05

Der `vectoplan-library` Service ist inzwischen nicht mehr nur ein dateibasierter VPLIB-/Creative-Library-Service. Er besitzt jetzt zusätzlich eine reale PostgreSQL-Persistenz, eine Repository-Schicht, einen DB-Sync-Pfad, einen Published-Read-Service und DB-basierte API-Routen.

### Aktuell bewiesen

```text
✅ PostgreSQL läuft.
✅ Flask-SQLAlchemy ist angebunden.
✅ Flask-Migrate/Alembic funktioniert im Container.
✅ Migrationsdateien sind im Development-Mount lokal sichtbar.
✅ Creative-Library-Tabellen existieren.
✅ Repository-Import funktioniert.
✅ SQLAlchemy-Session funktioniert.
✅ library_db_sync_service importiert.
✅ library_published_service importiert.
✅ Dataclass-field-Kollisionen wurden behoben.
✅ Manifest-/Dokument-Fallback im DB-Sync-Service funktioniert.
✅ vplib_uid wird aus vplib.manifest.json erkannt.
✅ Der Testblock wurde erfolgreich in PostgreSQL synchronisiert.
✅ creative_library_items enthält den Testblock.
✅ creative_library_revisions enthält eine Revision.
✅ creative_library_variants enthält eine Variante.
✅ creative_library_assets enthält einen Asset-Datensatz.
✅ creative_library_documents enthält 13 Dokumentzeilen.
✅ GET /api/v1/vplib/library/blocks?source=db&limit=20 funktioniert.
✅ GET /api/v1/vplib/library/tree?source=db funktioniert.
✅ GET /api/v1/vplib/library/blocks/<block_id>/variants?source=db antwortet technisch ok.
```

### Aktuell gelb / offen

```text
⚠️ GET /blocks/<block_id>?source=db muss nach dem letzten Repository-Fix final mit vollständigem JSON geprüft werden.
⚠️ GET /blocks/<block_id>/variants?source=db liefert aktuell ok=true, aber count=0, obwohl variant_count=1 und eine DB-Variante existiert.
⚠️ Wahrscheinlicher Grund: Repository-Child-Filterung in get_family_variants(...) / _filter_not_deleted(...)
   oder FK-/UID-Filterung gegen falsches Feld.
⚠️ POST /sync muss nach den letzten Routing-/Repository-Korrekturen erneut gemessen werden.
⚠️ Der Testblock liegt noch im Legacy-Pfad mit Tiefe 3:
   src/library/source/hochbau/bloecke/basic_stone_block
   Klassifikation enthält aber subcategory=basis.
```

### Aktuell rot

```text
❌ Varianten-Read ist fachlich noch nicht korrekt:
   /variants?source=db gibt count=0 zurück, obwohl die DB und die Listenroute variant_count=1 zeigen.
```

---

## 1. Zweck dieses Dokuments

Dieses Dokument ist der übergeordnete Haupt-IST-Zustand für den kompletten Service `services/vectoplan-library`.

Es beschreibt:

```text
- Zielbild und fachliche Architektur
- Service-Root-Struktur
- Docker-/Compose-/Runtime-Verhalten
- PostgreSQL-/Migration-/Alembic-Stand
- VPLIB-Core
- Creative-Library-Dateisystempfad
- Backend-Taxonomie
- Backend-Definitionsschicht
- Create-Flow und Frontend-Struktur
- Repository-Schicht
- DB-Sync-Service
- Published-Read-Service
- DB-Read-Model-Builder
- API-Routen
- Templates, Static JS und CSS
- relevante Datenbanktabellen
- aktuelle Testresultate
- offene Fehler
- nächste technische Schritte
```

Dieses Dokument ersetzt alte widersprüchliche Teilstände. Insbesondere sind ältere Aussagen wie „Migration offen“, „DB-Read E2E offen“, „Tree offen“ oder „Blocks aus DB offen“ nicht mehr pauschal korrekt. Der aktuelle Stand unterscheidet zwischen bereits getesteten DB-Reads und noch offenen Detail-/Varianten-Korrekturen.

---

## 2. Zielbild des Systems

Der `vectoplan-library` Microservice verwaltet VECTOPLAN Library-Bausteine, Familien, Varianten, Assets, Dokumente, technische Profile und perspektivisch Hersteller-/Product-Overlays.

Der fachliche Zielpfad ist:

```text
VPLIB Source Package
  ↓
Scanner
  ↓
Library Validation
  ↓
Fingerprint / revision_hash
  ↓
DB Sync
  ↓
PostgreSQL
  ↓
Published Read Models
  ↓
API
  ↓
Creative Library / Editor / Inventory / Admin UI
```

Wichtige fachliche Regel:

```text
Die Datei-/Package-Welt bleibt menschenlesbar und versionierbar.
Die PostgreSQL-Welt ist der persistente, veröffentlichte Read-/Runtime-Zustand.
```

---

## 3. Zentrale Architekturregeln

### 3.1 Source of Truth

```text
src/library/source/
  ist die dateibasierte Quelle für VPLIB-Directory-Packages.

PostgreSQL
  ist der persistente Published-State und die Grundlage für produktive DB-Reads.

generated/
  ist Runtime-/Output-/Cache-Bereich und keine fachliche Source of Truth.
```

### 3.2 Read-/Write-Trennung

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

?source=filesystem
  bleibt Debug-/Vergleichspfad
```

### 3.3 ID-Regeln

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

id / *_db_id
  technische DB-IDs
  nicht als fachlich stabile ID verwenden
```

### 3.4 Revisionsregel

```text
Gleicher revision_hash:
  keine neue Revision
  idempotenter Sync

Geänderter revision_hash:
  neue Revision
  Children wie Varianten/Assets/Dokumente werden für diese Revision ersetzt
```

---

## 4. Aktueller Testblock

Aktueller Block:

```text
family_id:    vp.hochbau.bloecke.basic_stone_block
package_id:   vplib.vp.hochbau.bloecke.basic_stone_block
vplib_uid:    2cd32d24-0758-4663-be1b-63f39b9b44af
label:        Basic Stone Block
object_kind:  cell_block
domain:       hochbau
category:     bloecke
subcategory:  basis
variant_id:   default
```

Aktueller Dateipfad:

```text
services/vectoplan-library/src/library/source/hochbau/bloecke/basic_stone_block
```

Bewertung:

```text
Dieser Pfad ist Legacy-/Übergangsform mit Tiefe 3.
Kanonisch wäre:
services/vectoplan-library/src/library/source/hochbau/bloecke/basis/basic_stone_block
```

Gespeicherte Dokumente:

```text
vplib.manifest.json
vplib.modules.json
family/identity.json
family/classification.json
editor/inventory.json
editor/placement.json
variants/index.json
variants/default.json
manufacturer/contract.json
physical/base.json
physical/collision.json
physical/dimensions.json
render/render_variants.json
```

---

## 5. Gesamtstruktur im Repository

```text
.
├── docker-compose.yml
├── services/
│   ├── vectoplan-editor/
│   ├── vectoplan-library/
│   └── vectoplan-chunk/
└── ...
```

### 5.1 `vectoplan-editor`

```text
Zweck:
  Editor-/Frontend-Service.

Bezug zur Library:
  konsumiert später Published Library, Inventory und Blockdetails.
```

### 5.2 `vectoplan-library`

```text
Zweck:
  VPLIB-Core
  Creative Library
  Create Flow
  DB-Sync
  Published DB Read
  API für Editor/Admin/UI
```

### 5.3 `vectoplan-chunk`

```text
Zweck:
  Chunk-/World-Service.
  Hat eigene PostgreSQL-Datenbank.
```

---

## 6. Root `docker-compose.yml`

### 6.1 Relevante Services

```text
vectoplan-editor
vectoplan-library-db
vectoplan-library
vectoplan-chunk-db
vectoplan-chunk
```

### 6.2 `vectoplan-library-db`

```text
Image:          postgres:16-alpine
Database:       vectoplan_library
User:           vectoplan
Password:       vectoplan
Internal Port:  5432
Public Port:    ${VECTOPLAN_LIBRARY_POSTGRES_PUBLIC_PORT:-5432}
Volume:         vectoplan-library-postgres-data
Network:        vectoplan-net
Healthcheck:    pg_isready
```

### 6.3 `vectoplan-library`

```text
Build Context:  ./services/vectoplan-library
Dockerfile:     Dockerfile
Target:         runtime
Public Port:    ${VECTOPLAN_LIBRARY_PUBLIC_PORT:-5001}:5000
Depends on:     vectoplan-library-db service_healthy
Healthcheck:    /health/ready
Network:        vectoplan-net
```

### 6.4 DB-Environment

Die Library bekommt mehrere kompatible DB-URI-Aliase:

```text
SQLALCHEMY_DATABASE_URI
VECTOPLAN_LIBRARY_DATABASE_URI
VECTOPLAN_LIBRARY_DATABASE_URL
VPLIB_DATABASE_URL
DATABASE_URL
```

Zielwert:

```text
postgresql+psycopg://vectoplan:vectoplan@vectoplan-library-db:5432/vectoplan_library
```

### 6.5 Development-Mount

Wichtig für Migrationen und lokalen Dateistand:

```text
./services/vectoplan-library:/opt/vectoplan/services/vectoplan-library
```

Dadurch werden automatisch erzeugte Migrationen und geänderte Python-Dateien im Container sichtbar.

---

## 7. Service-Root `services/vectoplan-library`

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
│   └── creative_library.py
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
│   ├── services/
│   ├── vplib/
│   └── library/
├── templates/
│   └── library_admin/
├── static/
│   └── library_admin/
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

## 8. Root-Dateien im Detail

### 8.1 `Dockerfile`

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

Zusammenhang:
  Ohne PostgreSQL-Client kann entrypoint.sh keinen DB-Wait/Healthcheck gegen Postgres durchführen.
```

### 8.2 `entrypoint.sh`

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

Wichtig:
  Im Development darf Auto-Migrate aktiv sein.
  Für produktivere Umgebungen sollte Auto-Migrate reduziert werden.
```

### 8.3 `requirements.txt`

```text
Aufgabe:
  Python-Abhängigkeiten.

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

### 8.4 `app.py`

```text
Aufgabe:
  Flask-App-Factory.

Macht:
  - Config laden
  - extensions.db initialisieren
  - migrations initialisieren
  - Models importieren
  - Blueprints registrieren
  - Startup-Hooks ausführen
  - Health-Routen bereitstellen
```

### 8.5 `wsgi.py`

```text
Aufgabe:
  WSGI-Entry für Gunicorn und Flask CLI.

Wichtig:
  FLASK_APP=wsgi:app nutzt diese Datei.
```

### 8.6 `config.py`

```text
Aufgabe:
  Konfiguration für Flask, DB, Pfade, Runtime, Library Source Roots, Generated Roots und Environment.

Wichtige Werte:
  SQLALCHEMY_DATABASE_URI
  VECTOPLAN_LIBRARY_SOURCE_ROOT
  VPLIB_SOURCE_ROOT
  Runtime-/Generated-Verzeichnisse
```

### 8.7 `extensions.py`

```text
Aufgabe:
  Zentrale Flask-Extensions.

Enthält:
  db = SQLAlchemy()
  migrate = Migrate()

Zusätzlich:
  Extension-Health
  DB-Initialisierung
  interne Extension-Registry
```

### 8.8 `IST-Zustand.md`

```text
Aufgabe:
  dieses Dokument.

Soll:
  Gesamtarchitektur, Ist-Stand, offene Fehler und nächste Schritte beschreiben.
```

---

## 9. Migration und Alembic

### 9.1 Struktur

```text
migrations/
├── README
├── alembic.ini
├── env.py
├── script.py.mako
└── versions/
    └── <revision>_*.py
```

### 9.2 Aktueller Stand

```text
✅ Flask-Migrate funktioniert.
✅ Alembic-State-Mismatch wurde verstanden.
✅ Migrations/versions ist im Dev-Mount sichtbar.
✅ Tabellen existieren in PostgreSQL.
✅ No changes in schema detected wurde bereits gesehen.
```

### 9.3 Wichtige Regel

```text
Migrationen nicht dauerhaft nur im Container belassen.
Migrationen müssen im Repo sichtbar und versioniert sein.
```

### 9.4 Dev-Reset bei Alembic-State-Mismatch

Wenn die DB auf eine nicht mehr vorhandene Migration zeigt:

```text
Can't locate revision identified by ...
```

dann im Development:

```sql
DROP SCHEMA public CASCADE;
CREATE SCHEMA public;
```

Danach:

```bash
flask db migrate
flask db upgrade
```

---

## 10. `models/`

```text
models/
├── __init__.py
└── creative_library.py
```

### 10.1 `models/__init__.py`

```text
Aufgabe:
  zentrale Model-Registry und Alembic-Importpunkt.

Macht:
  - import_all_models()
  - iter_model_classes()
  - get_model_class_names()
  - get_model_table_names()
  - get_models_metadata_snapshot()
  - get_models_health()
  - assert_models_ready()

Zusammenhang:
  Alembic braucht importierte Models, damit db.metadata alle Tabellen kennt.
```

### 10.2 `models/creative_library.py`

```text
Aufgabe:
  SQLAlchemy-Modelle für Creative Library.

Aktuelle fachliche Tabellen:
  - creative_library_items
  - creative_library_scan_runs
  - creative_library_revisions
  - creative_library_variants
  - creative_library_assets
  - creative_library_documents
  - creative_library_scan_issues
  - creative_library_inventory_slots

Wichtige Aliase:
  CreativeLibraryFamily = CreativeLibraryItem
  CreativeLibraryFamilyRevision = CreativeLibraryRevision
```

---

## 11. Datenbanktabellen

### 11.1 `creative_library_items`

```text
Fachlich:
  veröffentlichter Library-Eintrag / Family.

Wichtige Felder:
  id
  vplib_uid
  package_id
  family_id
  family_slug
  slug
  label
  name
  description
  domain
  category
  subcategory
  classification_path
  taxonomy_path
  object_kind
  source_root
  source_path
  package_root
  current_revision_id
  current_revision_hash
  latest_revision_hash
  published_revision_hash
  revision_hash
  default_variant_id
  variant_count
  asset_count
  document_count
  revision_count
  status
  publication_status
  enabled
  visible
  is_deleted
  first_seen_at
  last_seen_at
  scanned_at
  published_at
  deleted_at
  summary_payload
  payload
  meta
  metadata_json
  created_at
  updated_at

Aktueller Teststand:
  enthält Basic Stone Block.
```

### 11.2 `creative_library_revisions`

```text
Fachlich:
  versionierter Stand einer Family.

Wichtige Felder:
  id
  family_db_id
  item_id
  scan_run_id
  scan_run_db_id
  vplib_uid
  family_id
  package_id
  revision_id
  revision_hash
  previous_revision_hash
  package_version
  schema_version
  source_root
  source_path
  source_mtime_ns
  source_size_bytes
  validation_status
  status
  publication_status
  published_at
  manifest_json
  modules_json
  identity_json
  classification_json
  resolved_package_json
  document_paths_json
  summary_payload
  detail_payload
  raw_documents
  documents
  validation_payload
  payload
  meta
  metadata_json
  created_at
  updated_at

Aktueller Teststand:
  enthält eine Revision für Basic Stone Block.
```

### 11.3 `creative_library_variants`

```text
Fachlich:
  Varianten einer Revision.

Wichtige Felder:
  id
  family_db_id
  item_id
  revision_id
  revision_db_id
  vplib_uid
  family_id
  revision_hash
  variant_id
  id_in_family
  slug
  label
  name
  description
  is_default
  enabled
  visible
  family_profile_id
  variant_profile_id
  definition_values_json
  additional_field_keys_json
  summary_json
  resolved_payload
  payload
  meta
  metadata_json
  status
  publication_status
  sort_order
  created_at
  updated_at

Aktueller Teststand:
  DB enthält eine Variante `default`.
  API /variants liefert aktuell noch count=0.
```

### 11.4 `creative_library_assets`

```text
Fachlich:
  Asset-/Preview-/Mesh-/Texture-/Dokumentverweise einer Revision.

Wichtige Felder:
  id
  family_db_id
  item_id
  revision_id
  revision_db_id
  vplib_uid
  family_id
  revision_hash
  role
  asset_kind
  asset_type
  asset_path
  path
  relative_path
  uri
  label
  asset_hash
  checksum
  mime_type
  size_bytes
  exists
  payload
  meta
  metadata_json
  created_at
  updated_at

Aktueller Teststand:
  ein Asset-Datensatz vorhanden.
  Asset-Policy noch fachlich zu klären.
```

### 11.5 `creative_library_documents`

```text
Fachlich:
  persistierte Package-Dokumente je Revision.

Wichtige Felder:
  id
  family_db_id
  item_id
  revision_id
  revision_db_id
  vplib_uid
  family_id
  revision_hash
  relative_path
  path
  document_type
  module
  checksum
  document
  payload
  meta
  metadata_json
  created_at
  updated_at

Aktueller Teststand:
  13 Dokumente gespeichert.
```

### 11.6 `creative_library_scan_runs`

```text
Fachlich:
  Protokoll eines Scan-/Sync-Laufs.

Wichtige Felder:
  id
  scan_uid
  source_root
  mode
  triggered_by
  started_at
  finished_at
  duration_ms
  status
  total_count
  scanned_count
  valid_count
  invalid_count
  created_count
  inserted_count
  updated_count
  unchanged_count
  published_count
  skipped_count
  deleted_count
  duplicate_count
  warning_count
  error_count
  summary_json
  details
  payload
  meta
  metadata_json
  created_at
  updated_at
```

### 11.7 `creative_library_scan_issues`

```text
Fachlich:
  Issues, Warnings und Errors aus Scan, Validation oder DB-Sync.

Wichtige Felder:
  id
  scan_run_id
  scan_run_db_id
  family_db_id
  revision_id
  revision_db_id
  severity
  level
  code
  message
  path
  field
  scope
  source_path
  relative_path
  vplib_uid
  package_id
  family_id
  revision_hash
  context_json
  payload
  meta
  metadata_json
  created_at
  updated_at
```

### 11.8 `creative_library_inventory_slots`

```text
Fachlich:
  vorbereitete Editor-/Creative-Library-Inventarslots.

Wichtige Felder:
  id
  inventory_key
  slot_index
  slot_id
  family_db_id
  item_id
  vplib_uid
  family_id
  package_id
  variant_id
  label
  description
  family_slug
  object_kind
  domain
  category
  subcategory
  taxonomy_path
  status
  source
  scope
  mode
  enabled
  visible
  active
  locked
  pinned
  selected
  sort_order
  icon
  preview
  assets
  variant
  placement
  revision_hash
  publication_status
  validation_status
  selected_at
  published_at
  payload
  meta
  metadata_json
  created_at
  updated_at

Aktueller Teststand:
  echte InventorySlots noch nicht produktiv genutzt.
  Inventory-Fallback aus Published Families vorbereitet.
```

---

## 12. `src/vplib`

```text
src/vplib/
├── __init__.py
├── vplib_id_service.py
├── defaults/
├── validators/
├── creators/
└── sources/
```

### 12.1 Aufgabe

```text
Technischer VPLIB-Core.

Macht:
  - Default-Dokumente bereitstellen
  - technische Package-Strukturen erzeugen
  - VPLIB-Dokumente validieren
  - VPLIB-Archive / Directory Packages erzeugen
  - Source-Pfade verwalten
  - stabile vplib_uid erzeugen und normalisieren
```

### 12.2 Verhältnis zu `src/library`

```text
src/vplib:
  technische Package-Engine

src/library:
  fachliche Creative-Library-Schicht
  Scan, Taxonomie, Publication, DB-Sync, Inventory
```

---

## 13. `src/library`

```text
src/library/
├── __init__.py
├── IST-Zustand.md
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

### 13.1 `src/library/__init__.py`

```text
Aufgabe:
  Root-Fassade der Library-Schicht.

Macht:
  - Lazy Imports
  - Health
  - Package Info
  - Subpackage Status
  - Content Directory Status
  - Cache Clear
  - Repository-/DB-Capabilities anzeigen

Wichtige Begriffe:
  CORE_SUBPACKAGES
  DB_SUBPACKAGES
  OPTIONAL_SUBPACKAGES
  CONTENT_DIRECTORIES
```

### 13.2 `src/library/source/`

```text
Aufgabe:
  echte VPLIB-Directory-Packages.

Kanonisch:
  source/{domain}/{category}/{subcategory}/{family_slug}

Aktueller Testblock:
  source/hochbau/bloecke/basic_stone_block
  Legacy-Tiefe 3.
```

---

## 14. `src/library/definitions`

```text
definitions/
├── __init__.py
├── definition_models.py
├── definition_registry.py
├── definition_service.py
└── data/
    ├── document_types.v1.json
    ├── family_profiles.v1.json
    ├── materials.v1.json
    ├── object_kinds.v1.json
    ├── profile_bindings.v1.json
    ├── units.v1.json
    ├── variables.v1.json
    └── variant_profiles.v1.json
```

### 14.1 `definition_models.py`

```text
Aufgabe:
  Dataclasses/Modelle für Definitionsdaten.

Beschreibt:
  ObjectKinds
  FamilyProfiles
  VariantProfiles
  Variables
  Units
  Materials
  DocumentTypes
  ProfileBindings
```

### 14.2 `definition_registry.py`

```text
Aufgabe:
  Laden, Cachen und Auflösen der JSON-Definitionsdaten.

Macht:
  - data/*.json laden
  - Validierung/Normalisierung
  - Lookup nach Profilen/Objektarten
```

### 14.3 `definition_service.py`

```text
Aufgabe:
  Service-Fassade für Routes und Create-Flow.

Macht:
  - Options-Payloads für Frontend
  - Profilauflösung
  - leere Variant-Values
  - Variant-Validation
```

### 14.4 `data/*.json`

```text
document_types.v1.json:
  bekannte Dokumenttypen.

family_profiles.v1.json:
  Family-Profildefinitionen.

materials.v1.json:
  Materialien.

object_kinds.v1.json:
  verfügbare Objektarten.

profile_bindings.v1.json:
  Zuordnung Taxonomie/ObjectKind → Profile.

units.v1.json:
  Einheiten.

variables.v1.json:
  technische Variablen.

variant_profiles.v1.json:
  Variant-Profile und Felder.
```

---

## 15. `src/library/taxonomy`

```text
taxonomy/
├── __init__.py
├── taxonomy_models.py
├── taxonomy_registry.py
├── taxonomy_validator.py
├── taxonomy_service.py
└── data/
    └── taxonomy.v1.json
```

### 15.1 `taxonomy_models.py`

```text
Aufgabe:
  Taxonomie-Domainmodelle.

Beschreibt:
  Domain
  Category
  Subcategory
  TaxonomySelection
  SourcePath-Information
  Create-Optionen
```

### 15.2 `taxonomy_registry.py`

```text
Aufgabe:
  Lädt und cached taxonomy.v1.json.

Macht:
  - Slug-Lookups
  - Domain-/Kategorie-/Subkategorie-Auflösung
  - Tree-Aufbereitung
```

### 15.3 `taxonomy_validator.py`

```text
Aufgabe:
  Validiert Taxonomieauswahlen.

Prüft:
  - existiert Domain?
  - existiert Category?
  - existiert Subcategory?
  - ist ObjectKind erlaubt?
  - ist Legacy-Pfad erlaubt?
```

### 15.4 `taxonomy_service.py`

```text
Aufgabe:
  Service-Fassade für API/Create/Scanner.

Macht:
  - Optionen liefern
  - Selection auflösen
  - Source-Pfad bauen
  - family_id/package_id bauen
```

### 15.5 `data/taxonomy.v1.json`

```text
Aufgabe:
  Backend-Source-of-Truth für Taxonomie.

Aktueller relevanter Pfad:
  hochbau / bloecke / basis
```

---

## 16. `src/library/scanner`

```text
scanner/
├── __init__.py
├── package_discovery.py
├── package_reader.py
└── package_fingerprint.py
```

### 16.1 `package_discovery.py`

```text
Aufgabe:
  findet VPLIB-Directory-Packages in src/library/source.

Macht:
  - source root traversieren
  - canonical/legacy Pfade erkennen
  - Kandidaten erzeugen
  - Pfadklassifikation ableiten
```

### 16.2 `package_reader.py`

```text
Aufgabe:
  liest Package-Dateien.

Macht:
  - JSON-Dokumente lesen
  - manifest/modules/family/variants/editor/render/physical etc. einsammeln
  - ReadResult bauen

Offen:
  vplib_uid muss dauerhaft und explizit in ReadResult/Metadata sichtbar sein.
```

### 16.3 `package_fingerprint.py`

```text
Aufgabe:
  erzeugt revision_hash.

Macht:
  - relevante Dokumente normalisieren
  - Hash bilden
  - FingerprintResult erzeugen
```

---

## 17. `src/library/validation`

```text
validation/
├── __init__.py
└── library_package_validator.py
```

### 17.1 `library_package_validator.py`

```text
Aufgabe:
  fachliche Creative-Library-Validierung.

Prüft:
  - Manifest/Identity vorhanden
  - family_id/package_id plausibel
  - Classification vorhanden
  - Varianten vorhanden
  - default variant vorhanden
  - Dokumentstruktur plausibel
  - optional VPLIB-Core-Validierung

Bereits gefixt:
  options-Dict wird in Options-Objekt normalisiert.
  require_taxonomy/require_classification Bruch wurde adressiert.

Offen:
  vplib_uid als publish-kritisches Pflichtfeld.
  subcategory-Strenge finalisieren.
  validation/__init__.py Symbole harmonisieren.
```

### 17.2 `validation/__init__.py`

```text
Aufgabe:
  Fassade für Validation.

Offen:
  Exporte und Health-Funktionen müssen vollständig mit library_package_validator.py übereinstimmen.
```

---

## 18. `src/library/domain`

```text
domain/
├── __init__.py
├── library_item.py
├── library_detail.py
├── scan_result.py
├── sync_result.py
├── publication.py
└── inventory.py
```

### 18.1 `library_item.py`

```text
Aufgabe:
  altes dateibasiertes Summary-Modell.

Enthält:
  LibraryItem
  LibraryItemValidationSummary
  LibraryItemAssetRefs
  LibraryItemClassification

Offen:
  vplib_uid explizit durchziehen.
```

### 18.2 `library_detail.py`

```text
Aufgabe:
  altes dateibasiertes Detailmodell.

Enthält:
  LibraryItemDetail
  LibraryDocumentEntry
  LibraryTaxonomyDetail
  LibraryVariantDetail
  LibraryModuleDetail
  LibrarySourceDetail

Offen:
  vplib_uid/revision_hash explizit durchziehen.
```

### 18.3 `scan_result.py`

```text
Aufgabe:
  ScanResult-Domain für dateibasierte Scan-Pipeline.

Enthält:
  LibraryScanResult
  LibraryScanCandidate
  LibraryScanStats
  LibraryScanMessage
  LibraryDuplicateId

Offen:
  Kandidaten sollen vplib_uid/family_id/package_id/revision_hash sicher tragen.
```

### 18.4 `sync_result.py`

```text
Aufgabe:
  DB-Sync-Ergebnis-Domain.

Enthält:
  LibrarySyncResult
  LibrarySyncRunInfo
  LibrarySyncCandidateResult
  LibrarySyncStats
  LibrarySyncIssue
  LibrarySyncOperationResult

Bereits gefixt:
  dataclasses.field-Kollision durch dataclass_field.
```

### 18.5 `publication.py`

```text
Aufgabe:
  Published-DB-Read-Domain.

Enthält:
  PublishedFamilySummary
  PublishedFamilyDetail
  PublishedRevisionSummary
  PublishedVariantSummary
  PublishedAssetRef
  PublishedValidationSummary
  PublishedLibraryStats
  PublishedLibraryListResult

Wird genutzt von:
  library_published_service
  DB-Read-API
```

### 18.6 `inventory.py`

```text
Aufgabe:
  Inventory-Domain.

Enthält:
  InventoryState
  InventorySlot
  InventoryStats
  InventoryAssetRef
  InventoryVariantRef
  InventoryPlacementInfo

Wird genutzt von:
  library_published_service.get_inventory_response()
```

### 18.7 `domain/__init__.py`

```text
Aufgabe:
  Fassade für alte und neue Domainmodelle.

Macht:
  - Lazy Import
  - Health
  - Re-Exports
  - Cache Clear
```

---

## 19. `src/library/read_models`

```text
read_models/
├── __init__.py
├── block_summary_builder.py
├── block_detail_builder.py
├── library_index_builder.py
├── db_block_summary_builder.py
├── db_block_detail_builder.py
├── db_library_tree_builder.py
└── db_inventory_builder.py
```

### 19.1 `block_summary_builder.py`

```text
Aufgabe:
  dateibasierte ReadResults → LibraryItem Summary.

Wird genutzt im Filesystem-Pfad.
```

### 19.2 `block_detail_builder.py`

```text
Aufgabe:
  dateibasierte ReadResults → Detail-/Variantenantwort.
```

### 19.3 `library_index_builder.py`

```text
Aufgabe:
  baut In-Memory-Index und Tree für Filesystem-Read.

Offen:
  by_vplib_uid ergänzen.
```

### 19.4 `db_block_summary_builder.py`

```text
Aufgabe:
  DB-Family-/Revision-/Asset-Daten → PublishedFamilySummary / Blocks-Response.

Status:
  strukturell vorhanden.
  In aktueller API läuft Blocks-Liste über Published-Service und Domainmodelle.
```

### 19.5 `db_block_detail_builder.py`

```text
Aufgabe:
  Repository-Detailpayload → PublishedFamilyDetail / Detail-/Variantenantwort.

Status:
  strukturell vorhanden.
```

### 19.6 `db_library_tree_builder.py`

```text
Aufgabe:
  PublishedFamilySummary-Liste → Tree:
  root → domain → category → subcategory → item_ids.

Aktueller Stand:
  /tree?source=db funktioniert.
```

### 19.7 `db_inventory_builder.py`

```text
Aufgabe:
  DB-InventorySlots oder PublishedFamilies → InventoryState.

Status:
  Fallback vorbereitet, echte DB-Slots noch nicht produktiv getestet.
```

### 19.8 `read_models/__init__.py`

```text
Aufgabe:
  Fassade für Filesystem- und DB-Read-Model-Builder.

Macht:
  - Lazy Imports
  - Re-Exports
  - Health
  - Convenience-Wrapper
```

---

## 20. `src/library/repositories`

```text
repositories/
├── __init__.py
└── sql/
    ├── __init__.py
    └── creative_library_repository.py
```

### 20.1 `repositories/__init__.py`

```text
Aufgabe:
  Repository-Root-Fassade.

Macht:
  - Backend-Auswahl
  - SQL-Backend auflösen
  - Health
  - Cache-Clear
  - keine DB-Verbindung beim Import
```

### 20.2 `repositories/sql/__init__.py`

```text
Aufgabe:
  SQL-Fassade.

Macht:
  - creative_library_repository Modul lazy importieren
  - Repository-Factories bereitstellen
  - SQLAlchemy db object finden
  - Models finden
  - Health
```

### 20.3 `repositories/sql/creative_library_repository.py`

```text
Aufgabe:
  konkrete SQLAlchemy-Zugriffsschicht.

Schreibmethoden:
  create_scan_run
  finish_scan_run
  fail_scan_run
  add_issue
  add_issues
  upsert_family
  create_revision
  upsert_revision_if_changed
  replace_variants
  replace_assets
  replace_documents
  mark_missing_families_deleted

Lesemethoden:
  get_family_by_vplib_uid
  get_family_by_family_id
  get_family_by_identifier
  get_latest_revision
  list_published_families
  count_published_families
  get_published_family_detail
  get_family_variants
  get_family_assets
  get_family_documents
  list_inventory_slots

Aktuelle wichtige Fixes:
  - idempotenter Sync ohne aggressive Aggregate-Reparatur.
  - current_revision_* wird nur bei neuer Revision gesetzt.
  - Counts werden nach Replace direkt gesetzt.
  - explizite repair_family_aggregate_fields(...) Methode.
  - get_family_by_identifier darf String-Identifier nicht gegen bigint id vergleichen.
  - _filter_not_deleted muss NULL-Statuswerte als nicht gelöscht behandeln.

Aktuell noch offen:
  - Variantenroute liefert count=0, obwohl Variante existiert.
  - get_family_variants / _filter_query_for_family_or_uid / _filter_not_deleted final prüfen.
```

---

## 21. `src/library/services`

```text
services/
├── __init__.py
├── library_scan_service.py
├── library_block_service.py
├── library_create_service.py
├── library_db_sync_service.py
└── library_published_service.py
```

### 21.1 `library_scan_service.py`

```text
Aufgabe:
  dateibasierte Scan-Orchestrierung.

Pipeline:
  package_discovery
  package_reader
  library_package_validator
  package_fingerprint
  block_summary_builder
  library_index_builder

Wichtige Fixes:
  options-Dict wird in ServiceOptions normalisiert.
  require_taxonomy-Fehler wurde dadurch behoben.

API-Bezug:
  GET /api/v1/vplib/library/scan
```

### 21.2 `library_block_service.py`

```text
Aufgabe:
  alter Filesystem-/Debug-Read-Service.

Bietet:
  list blocks
  detail
  variants
  tree

API-Bezug:
  ?source=filesystem
```

### 21.3 `library_create_service.py`

```text
Aufgabe:
  Create-Flow für neue Source Packages.

Bietet:
  Draft
  Validate
  Package Plan
  Download .vplib
  Save Directory Package

Offen:
  Save soll needs_sync=true, vplib_uid, source_path, family_id, package_id zurückgeben.
```

### 21.4 `library_db_sync_service.py`

```text
Aufgabe:
  Filesystem-Scan → PostgreSQL.

Macht:
  - Scan ausführen
  - Kandidaten extrahieren
  - Manifest-Fallback aus Dateisystem nutzen
  - vplib_uid/family_id/package_id/revision_hash bestimmen
  - Repository-Operationen ausführen
  - SyncResult zurückgeben

Wichtige Fixes:
  - Manifest-Fallback ergänzt
  - Dokument-Fallback ergänzt
  - SyncResult-Serialisierung entschärft
  - kein rekursives asdict auf große Pipeline-Objekte
```

### 21.5 `library_published_service.py`

```text
Aufgabe:
  PostgreSQL → Published API-Daten.

Bietet:
  list_published_blocks_response
  get_published_block_detail_response
  get_published_block_variants_response
  get_published_tree_response
  get_inventory_response

Aktueller Stand:
  /blocks?source=db funktioniert
  /tree?source=db funktioniert
  /variants?source=db antwortet ok, aber count=0
  Detail muss nach letztem Repository-Fix final mit Payload geprüft werden
```

### 21.6 `services/__init__.py`

```text
Aufgabe:
  Service-Fassade.

Macht:
  - Lazy Import alter und neuer Services
  - Health
  - Cache Clear
  - Convenience-Funktionen für Routes

Wichtige Wrapper:
  sync_library_to_database_response
  list_published_blocks_db_response
  published_block_detail_db_response
  published_block_variants_db_response
  published_tree_db_response
  published_inventory_db_response
  publication_status_response
```

---

## 22. `src/routes`

```text
src/routes/
├── __init__.py
├── api.py
├── vplib_routes.py
├── library_routes.py
├── create.py
├── library_definition_routes.py
└── taxonomy.py
```

### 22.1 `routes/__init__.py`

```text
Aufgabe:
  zentrale Blueprint-Registry.

Macht:
  - Blueprints importieren
  - required/optional trennen
  - api_bp registrieren
  - library_routes registrieren
  - route health

Aktuelle Warnung:
  "One or more required blueprints are missing"
  ist bisher nicht blockierend, sollte aber bereinigt werden.
```

### 22.2 `routes/api.py`

```text
Aufgabe:
  neue API-Kante für DB-Sync und Published Reads.

Routen:
  GET  /api/v1/vplib/library/health
  GET  /api/v1/vplib/library/db/health
  GET  /api/v1/vplib/library/scan
  POST /api/v1/vplib/library/sync
  GET  /api/v1/vplib/library/sync-runs
  GET  /api/v1/vplib/library/sync-runs/<run_id>
  GET  /api/v1/vplib/library/publication-status
  GET  /api/v1/vplib/library/blocks
  GET  /api/v1/vplib/library/blocks/<block_id>
  GET  /api/v1/vplib/library/blocks/<block_id>/variants
  GET  /api/v1/vplib/library/tree
  GET  /api/v1/vplib/library/inventory

Wichtige Fixes:
  - /sync serialisiert kein rohes SyncResult mehr.
  - json_safe nutzt to_dict vor Dataclass.
  - Dataclass-Fallback ist shallow.
  - Detail/Variants nutzen call_block_identifier_function.
  - DB-Tree-Route übergibt keine inkompatiblen Filter mehr.

Aktueller Stand:
  Blocks-Liste grün.
  Tree grün.
  Detail nach letztem Fix final prüfen.
  Variants fachlich noch gelb, weil count=0.
```

### 22.3 `routes/vplib_routes.py`

```text
Aufgabe:
  VPLIB-Core API.

Bietet:
  Health
  Test
  Create/Dry-Run für technische VPLIB-Funktionalität
```

### 22.4 `routes/library_routes.py`

```text
Aufgabe:
  ältere Creative-Library-Routen.

Bedeutung:
  Filesystem-/Legacy-/Debug-Pfad.
  Muss mit routes/api.py hinsichtlich URL-Regeln beobachtet werden.
```

### 22.5 `routes/create.py`

```text
Aufgabe:
  Create UI und Create API.

Bietet:
  /create
  /api/v1/vplib/create/*
```

### 22.6 `routes/library_definition_routes.py`

```text
Aufgabe:
  Definitions API.

Bietet:
  object kinds
  family profiles
  variant profiles
  variables
  units
  materials
  validation
```

### 22.7 `routes/taxonomy.py`

```text
Aufgabe:
  Taxonomie API.

Bietet:
  Taxonomieoptionen, Tree, Auswahlvalidierung.
```

---

## 23. `src/services`

```text
src/services/
├── vplib_route_service.py
├── library_route_service.py
├── library_create_route_service.py
├── library_definition_route_service.py
└── library_create_variant_payload_service.py
```

### 23.1 `vplib_route_service.py`

```text
Aufgabe:
  Service-Schicht für VPLIB-Core-Routen.
```

### 23.2 `library_route_service.py`

```text
Aufgabe:
  ältere HTTP-Service-Schicht für Creative-Library-Filesystem-Routen.

Status:
  bleibt Debug-/Legacy-Pfad.
```

### 23.3 `library_create_route_service.py`

```text
Aufgabe:
  HTTP-Service für Create-Flow.

Macht:
  Draft
  Validate
  Package Plan
  Download
  Save
```

### 23.4 `library_definition_route_service.py`

```text
Aufgabe:
  HTTP-Service für Definitionsdaten.
```

### 23.5 `library_create_variant_payload_service.py`

```text
Aufgabe:
  Normalisierung und Validierung definition-managed Variant Payloads.

Bedeutung:
  Bindeglied zwischen Frontend Variant Drawer und Backend-Definitionsschema.
```

---

## 24. Templates

```text
templates/
└── library_admin/
    ├── create.html
    └── create/
        ├── _context_json.html
        ├── _wizard_nav.html
        ├── _stepper.html
        ├── _preview.html
        ├── _theme_toggle.html
        ├── sections/
        │   ├── _identity.html
        │   ├── _taxonomy.html
        │   ├── _object_variants.html
        │   ├── _geometry.html
        │   ├── _technical.html
        │   └── _actions.html
        └── variants/
            ├── _variant_workspace.html
            ├── _variant_table.html
            ├── _variant_drawer_shell.html
            ├── _variant_drawer_footer.html
            └── _variant_empty_state.html
```

### 24.1 Aufgaben

```text
create.html:
  Hauptseite des Create Wizards.

_context_json.html:
  initiale Backend-Kontextdaten als JSON.

_wizard_nav.html:
  Navigation des Wizards.

_stepper.html:
  Schrittanzeige.

_preview.html:
  rechte Vorschau.

_theme_toggle.html:
  UI Theme Toggle.

sections/_identity.html:
  Basisdaten.

sections/_taxonomy.html:
  Taxonomie-Auswahl.

sections/_object_variants.html:
  Variantenbereich.

sections/_geometry.html:
  Geometrie.

sections/_technical.html:
  technische Angaben.

sections/_actions.html:
  Aktionen: Draft/Validate/Plan/Download/Save.

variants/_variant_workspace.html:
  Arbeitsbereich für Varianten.

variants/_variant_table.html:
  Übersichtstabelle.

variants/_variant_drawer_shell.html:
  Drawer für Variantenbearbeitung.

variants/_variant_drawer_footer.html:
  Aktionen im Drawer.

variants/_variant_empty_state.html:
  Empty State.
```

---

## 25. Static JavaScript

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

### 25.1 Aufgaben

```text
create.js:
  Haupt-Orchestrator.
  Sammelt Payload.
  Ruft Backend-Actions.

create_wizard.js:
  Wizard-Schritte und Navigation.

create_definitions.js:
  Bridge zu Backend-Definitionsdaten.

create_variant_utils.js:
  Hilfsfunktionen für Varianten.

create_variant_state.js:
  Browser-State für Varianten.

create_variant_profiles.js:
  Auflösung von Family-/Variant-Profilen.

create_variant_summary.js:
  Kurzwerte und Summary.

create_variant_field_renderer.js:
  rendert Felder aus Backend-Definitionen.

create_variant_validation.js:
  lokale und Backend-Validierung.

create_variant_drawer.js:
  Drawer-Interaktion.

create_variant_table.js:
  Variantenliste.

create_variant_optional_fields.js:
  optionale Backend-Variablen und additional_field_keys.
```

---

## 26. Static CSS

```text
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

### 26.1 Aufgaben

```text
tokens.css:
  Design Tokens.

base.css:
  Basislayout.

layout.css:
  Grid/Layout.

cards.css:
  Cards.

forms.css:
  Formulare.

tables.css:
  Tabellen.

preview.css:
  Vorschau.

actions.css:
  Aktionsbuttons.

wizard.css:
  Stepper/Wizard.

definitions.css:
  Definitions-/Profile UI.

variant-workspace.css:
  Variantenarbeitsbereich.

variant-table.css:
  Variantentabelle.

variant-drawer.css:
  Drawer.

variant-fields.css:
  Profilfelder.

variant-optional-fields.css:
  optionale Felder.

variant-validation.css:
  Validierungszustände.

themes.css:
  Themes.

responsive.css:
  responsive Verhalten.
```

---

## 27. Generated und Runtime-Verzeichnisse

```text
generated/
├── vplib/
├── archives/
├── vplib_test/
├── library/
└── library_cache/
```

### 27.1 Bedeutung

```text
generated/vplib:
  erzeugte VPLIB-Arbeitsdaten.

generated/archives:
  .vplib Downloads/Archive.

generated/vplib_test:
  Testausgaben.

generated/library:
  Library-Ausgaben.

generated/library_cache:
  optionaler Cache.
```

### 27.2 Regel

```text
generated/ ist nicht fachliche Quelle.
generated/ nicht als Source-of-Truth behandeln.
```

---

## 28. API-Status und Testresultate

### 28.1 Funktionierende Routen

#### Blocks-Liste

```text
GET http://localhost:5001/api/v1/vplib/library/blocks?source=db&limit=20
```

Status:

```text
✅ ok=true
✅ count=1
✅ source=database
✅ Basic Stone Block sichtbar
```

#### Tree

```text
GET http://localhost:5001/api/v1/vplib/library/tree?source=db
```

Status:

```text
✅ ok=true
✅ root/hochbau/bloecke/basis sichtbar
✅ item_ids enthält vp.hochbau.bloecke.basic_stone_block
✅ count=1
```

#### Varianten

```text
GET http://localhost:5001/api/v1/vplib/library/blocks/vp.hochbau.bloecke.basic_stone_block/variants?source=db
```

Status:

```text
⚠️ technisch ok=true
⚠️ fachlich noch falsch: count=0, variants=[]
```

Erwartung:

```text
count=1
variant_id=default
```

#### Detail

```text
GET http://localhost:5001/api/v1/vplib/library/blocks/vp.hochbau.bloecke.basic_stone_block?source=db
```

Status:

```text
⚠️ vom Nutzer als "schaut gut aus" eingeordnet, aber vollständige JSON-Antwort wurde nicht übermittelt.
⚠️ final nach Repository-Fix mit vollständigem Payload dokumentieren.
```

### 28.2 Frühere Fehler und aktueller Status

#### Fehler: PowerShell Bash-Syntax

```text
Ursache:
  \ und <<'PY' aus Bash wurden in PowerShell verwendet.

Status:
  behoben durch PowerShell Here-Strings @' ... '@.
```

#### Fehler: `dict` hat kein `require_taxonomy`

```text
Ursache:
  options wurde als dict weitergereicht, aber Code erwartete Attributzugriff.

Fix:
  Validator und Scan-Service normalisieren Options.

Status:
  behoben.
```

#### Fehler: `/sync` Timeout durch rekursive Serialisierung

```text
Ursache:
  routes/api.py gab rohes SyncResult zurück.
  json_safe nutzte rekursives dataclasses.asdict.

Fix:
  sync_response_payload(...)
  to_dict vor dataclass
  shallow dataclass fallback

Status:
  behoben/verbessert; /sync nach letzten Repository-Fixes erneut testen.
```

#### Fehler: Detail/Variants doppelte Parameter

```text
Ursache:
  Route übergab block_id und identifier gleichzeitig.

Fix:
  call_block_identifier_function(...)

Status:
  behoben.
```

#### Fehler: String-Identifier gegen bigint id

```text
Ursache:
  get_family_by_identifier verglich:
  creative_library_items.id = 'vp.hochbau.bloecke.basic_stone_block'

Fix:
  id nur bei numerischem Identifier prüfen.
  nach SQLAlchemy/psycopg Fehler rollback durchführen.

Status:
  sollte behoben sein; Detail final prüfen.
```

#### Fehler: Variants count=0

```text
Ursache wahrscheinlich:
  _filter_not_deleted filtert NULL-Werte weg
  oder _filter_query_for_family_or_uid nutzt nicht passende Family-/Revision-Felder.

Aktueller Status:
  offen.
```

---

## 29. Aktueller Datenfluss: DB-Read

### 29.1 Blocks-Liste

```text
GET /api/v1/vplib/library/blocks?source=db
  ↓
routes/api.py
  ↓
services.list_published_blocks_db_response()
  ↓
library_published_service.list_published_blocks_response()
  ↓
repository.list_published_families()
  ↓
PublishedFamilySummary[]
  ↓
JSON
```

### 29.2 Detail

```text
GET /api/v1/vplib/library/blocks/<block_id>?source=db
  ↓
routes/api.py
  ↓
services.published_block_detail_db_response()
  ↓
library_published_service.get_published_block_detail_response()
  ↓
repository.get_published_family_detail()
  ↓
repository.get_family_by_identifier()
  ↓
repository.get_latest_revision()
  ↓
repository.get_family_variants()
  ↓
repository.get_family_assets()
  ↓
repository.get_family_documents()
```

### 29.3 Varianten

```text
GET /api/v1/vplib/library/blocks/<block_id>/variants?source=db
  ↓
routes/api.py
  ↓
services.published_block_variants_db_response()
  ↓
library_published_service.get_published_block_variants_response()
  ↓
repository.get_family_variants()
  ↓
PublishedVariantSummary[]
```

Aktueller Bruch:

```text
repository.get_family_variants() findet keine Zeilen,
obwohl creative_library_variants eine default-Variante enthält.
```

### 29.4 Tree

```text
GET /api/v1/vplib/library/tree?source=db
  ↓
routes/api.py
  ↓
services.published_tree_db_response()
  ↓
library_published_service.get_published_tree_response()
  ↓
list_published_blocks()
  ↓
build_published_tree_from_summaries()
```

Status:

```text
grün.
```

---

## 30. Aktueller Datenfluss: DB-Sync

```text
POST /api/v1/vplib/library/sync
  ↓
routes/api.py
  ↓
services.sync_library_to_database_response()
  ↓
library_db_sync_service.sync_library_to_db()
  ↓
library_scan_service.scan_library_source()
  ↓
package_discovery
  ↓
package_reader
  ↓
library_package_validator
  ↓
package_fingerprint
  ↓
extract_pipeline_candidates()
  ↓
Repository:
  upsert_family
  upsert_revision_if_changed
  replace_variants
  replace_assets
  replace_documents
  add_issues
  finish_scan_run
  ↓
LibrarySyncResult
  ↓
sync_response_payload()
  ↓
JSON
```

Aktueller Status:

```text
Historisch erfolgreich.
Nach den letzten Detail-/Repository-Fixes erneut final testen.
```

---

## 31. Aktuelle PowerShell-Testbefehle

### 31.1 Syntax prüfen

```powershell
docker compose exec -T vectoplan-library python -m py_compile routes/api.py
docker compose exec -T vectoplan-library python -m py_compile src/library/repositories/sql/creative_library_repository.py
docker compose exec -T vectoplan-library python -m py_compile src/library/services/library_published_service.py
docker compose exec -T vectoplan-library python -m py_compile src/library/services/library_db_sync_service.py
```

### 31.2 DB prüfen

```powershell
docker compose exec -T vectoplan-library-db psql -U vectoplan -d vectoplan_library -c "select id, vplib_uid, family_id, package_id, current_revision_id, current_revision_hash, latest_revision_hash, published_revision_hash, revision_hash, variant_count, asset_count, document_count, revision_count from creative_library_items order by id desc limit 20;"
```

```powershell
docker compose exec -T vectoplan-library-db psql -U vectoplan -d vectoplan_library -c "select id, vplib_uid, family_id, revision_id, revision_db_id, variant_id, label, is_default, status, publication_status from creative_library_variants order by id;"
```

### 31.3 API testen

```powershell
Invoke-RestMethod `
  -Uri "http://localhost:5001/api/v1/vplib/library/blocks?source=db&limit=20" |
  ConvertTo-Json -Depth 30
```

```powershell
Invoke-RestMethod `
  -Uri "http://localhost:5001/api/v1/vplib/library/tree?source=db" |
  ConvertTo-Json -Depth 30
```

```powershell
Invoke-RestMethod `
  -Uri "http://localhost:5001/api/v1/vplib/library/blocks/vp.hochbau.bloecke.basic_stone_block?source=db" |
  ConvertTo-Json -Depth 50
```

```powershell
Invoke-RestMethod `
  -Uri "http://localhost:5001/api/v1/vplib/library/blocks/vp.hochbau.bloecke.basic_stone_block/variants?source=db" |
  ConvertTo-Json -Depth 50
```

### 31.4 Direkter Repository-Test

```powershell
@'
from app import create_app
import traceback

app = create_app("development")

with app.app_context():
    from library.repositories.sql.creative_library_repository import get_creative_library_repository

    repo = get_creative_library_repository()
    identifier = "vp.hochbau.bloecke.basic_stone_block"

    try:
        family = repo.get_family_by_identifier(identifier)
        print("family =", family)
        print("family_id =", getattr(family, "family_id", None))
        print("vplib_uid =", getattr(family, "vplib_uid", None))

        variants = repo.get_family_variants(identifier, include_unpublished=True)
        print("variants include_unpublished=True =", len(variants))
        for v in variants:
            print("variant", getattr(v, "variant_id", None), getattr(v, "label", None))

        variants = repo.get_family_variants(identifier, include_unpublished=False)
        print("variants include_unpublished=False =", len(variants))
        for v in variants:
            print("variant", getattr(v, "variant_id", None), getattr(v, "label", None))

    except BaseException as exc:
        print("EXCEPTION", type(exc).__name__, str(exc))
        traceback.print_exc()
'@ | docker compose exec -T vectoplan-library python
```

---

## 32. Offene P0/P1/P2-Aufgaben

### P0 – Varianten-Read reparieren

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

### P0 – Detail final dokumentieren

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

### P1 – POST /sync erneut final testen

```text
POST /api/v1/vplib/library/sync
```

Prüfen:

```text
keine Timeouts
keine offene idle-in-transaction Session
keine neue Revision bei gleichem revision_hash
SyncResult kompakt
```

### P1 – Asset-Policy klären

Aktueller Datenstand enthält einen Asset-Datensatz aus `material_refs`.

Entscheidung:

```text
A) Leere Mapping-Assets überspringen.
B) Structured Assets ohne path als payload-only speichern.
C) material_refs nicht als Asset behandeln.
```

Empfehlung:

```text
Kurzfristig leere `{}`-Assets überspringen.
```

### P1 – Legacy-Pfad migrieren

Aktuell:

```text
source/hochbau/bloecke/basic_stone_block
```

Ziel:

```text
source/hochbau/bloecke/basis/basic_stone_block
```

### P2 – Startup-Warnungen bereinigen

Aktuelle Warnungen:

```text
Extension error [routes]: One or more required blueprints are missing.
Directory check failed for routes_root.
VPLIB settings check failed: 'NoneType' object has no attribute '__dict__'
Library settings check failed: 'NoneType' object has no attribute '__dict__'
```

### P2 – `vplib_uid` überall durchziehen

Dateien:

```text
scanner/package_reader.py
validation/library_package_validator.py
domain/library_item.py
domain/library_detail.py
domain/scan_result.py
read_models/block_summary_builder.py
read_models/block_detail_builder.py
read_models/library_index_builder.py
services/library_scan_service.py
```

### P2 – Create-Flow Save → Sync verbessern

```text
POST /create/save
  soll needs_sync=true liefern

Optional:
  POST /create/save?sync=true
```

### P3 – Admin-Sync-UI

Offen:

```text
DB-Status anzeigen
Sync starten
SyncRuns anzeigen
SyncRun-Details anzeigen
```

---

## 33. Statusmatrix

| Bereich | Status | Bemerkung |
|---|---:|---|
| Docker Compose | grün | Library-DB und Service laufen |
| PostgreSQL | grün | Tabellen und Testdaten vorhanden |
| Flask-SQLAlchemy | grün | Session funktioniert |
| Flask-Migrate/Alembic | grün | Init/Migrate/Upgrade funktioniert |
| VPLIB-Core | grün | technische Package-Schicht vorhanden |
| Backend-Taxonomie | grün | hochbau/bloecke/basis sichtbar |
| Definitionsschicht | grün | Definitionsdaten vorhanden |
| Source Scanner | grün | Scan funktioniert |
| Library Validation | grün-gelb | Options-Fix erledigt, UID-Strenge offen |
| Fingerprint | grün | revision_hash vorhanden |
| DB-Sync-Service | grün-gelb | historisch erfolgreich, final neu testen |
| Repository | gelb | Details/Variants noch teilweise offen |
| Published-Service | grün-gelb | Blocks/Tree grün, Variants gelb |
| Blocks-Liste DB | grün | count=1 |
| Tree DB | grün | root/hochbau/bloecke/basis |
| Detail DB | gelb | final mit Payload prüfen |
| Variants DB | rot-gelb | ok=true, aber count=0 |
| Inventory DB | gelb | Fallback vorbereitet, final testen |
| routes/api.py | grün-gelb | Sync/Read-Pfade stabilisiert |
| routes/__init__.py | gelb | Startup-Warnungen |
| Create UI | grün-gelb | E2E mit Save/Sync offen |
| Static JS/CSS | grün-gelb | Variant Runtime vorhanden, E2E offen |

---

## 34. Definition of Done für aktuellen Abschnitt

Der DB-Read-/Sync-Abschnitt gilt als abgeschlossen, wenn:

```text
1. GET /blocks?source=db liefert Basic Stone Block.
2. GET /tree?source=db liefert root/hochbau/bloecke/basis mit item_id.
3. GET /blocks/<id>?source=db liefert Detail mit Summary, Revision, Varianten, Assets, Dokumenten.
4. GET /blocks/<id>/variants?source=db liefert count=1 und variant_id=default.
5. GET /inventory liefert sinnvolles Fallback-Inventar oder echte Slots.
6. POST /sync läuft ohne Timeout.
7. POST /sync erzeugt bei gleichem revision_hash keine neue Revision.
8. DB enthält keine offene idle-in-transaction Session nach API-Aufrufen.
9. creative_library_items Pointer und Counts stimmen.
10. Legacy-Pfad-Status ist bewusst dokumentiert oder migriert.
```

---

## 35. Nächste empfohlene Reihenfolge

### Schritt 1

Repository-Varianten-Fix finalisieren:

```text
src/library/repositories/sql/creative_library_repository.py
```

Funktionen:

```text
get_family_variants()
_filter_not_deleted()
_filter_query_for_family_or_uid()
```

### Schritt 2

Direkten Repository-Test ausführen:

```text
repo.get_family_by_identifier(...)
repo.get_family_variants(..., include_unpublished=True)
repo.get_family_variants(..., include_unpublished=False)
```

### Schritt 3

API-Variantenroute erneut prüfen:

```text
GET /api/v1/vplib/library/blocks/vp.hochbau.bloecke.basic_stone_block/variants?source=db
```

### Schritt 4

Detailroute mit vollständigem JSON sichern:

```text
GET /api/v1/vplib/library/blocks/vp.hochbau.bloecke.basic_stone_block?source=db
```

### Schritt 5

POST /sync erneut messen:

```text
POST /api/v1/vplib/library/sync
```

### Schritt 6

Create → Save → Scan → Sync → DB Read E2E durchführen.

---

## 36. Kurzfazit

`vectoplan-library` ist inzwischen auf einem klaren Zwischenstand:

```text
VPLIB-Core:
  grün

Dateibasierte Creative Library:
  grün

Create Flow:
  grün-gelb

PostgreSQL und Migration:
  grün

Repository/DB-Sync:
  grün-gelb

Published DB Reads:
  Blocks und Tree grün,
  Detail final prüfen,
  Variants fachlich noch falsch mit count=0

Nächster harter Fix:
  creative_library_repository.py
  insbesondere get_family_variants / _filter_not_deleted / _filter_query_for_family_or_uid
```

Der Service hat damit die grundlegende Zielarchitektur erreicht:

```text
Source Package
  ↓
Scan
  ↓
Validation
  ↓
Fingerprint
  ↓
DB Sync
  ↓
PostgreSQL
  ↓
Published Read API
```

Der offene Rest ist keine neue Architekturfrage mehr, sondern gezielte Stabilisierung und End-to-End-Verifikation der DB-Read-Details.
