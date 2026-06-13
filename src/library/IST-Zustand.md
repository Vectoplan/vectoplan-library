# IST-Zustand – `services/vectoplan-library/src/library`

Stand: **2026-06-05**  
Letzte Aktualisierung: **2026-06-05 07:20 UTC**  
Scope: `services/vectoplan-library/src/library` plus relevante Außenkanten `routes/`, `models/creative_library.py`, `entrypoint.sh`, `docker-compose.yml`, PostgreSQL/Alembic, API-Tests und aktuelle Debug-Ergebnisse.

---

## 0. Kurzstatus

Die Library-Schicht ist inzwischen nicht mehr nur ein dateibasierter Katalog, sondern besitzt einen real getesteten DB-Sync- und DB-Read-Pfad.

### Aktuell nachgewiesen

```text
✅ PostgreSQL läuft.
✅ Alembic / Flask-Migrate funktioniert.
✅ Creative-Library-Tabellen existieren.
✅ Der erste Testblock wurde nach PostgreSQL synchronisiert.
✅ creative_library_items enthält 1 Family.
✅ creative_library_revisions enthält 1 Revision.
✅ creative_library_variants enthält 1 gespeicherte Variante.
✅ creative_library_assets enthält 1 Asset-Datensatz.
✅ creative_library_documents enthält 13 Dokumentzeilen.
✅ Aggregates/Pointers der Family wurden repariert:
   current_revision_id      = 1
   current_revision_hash    = 3e86f507...
   latest_revision_hash     = 3e86f507...
   published_revision_hash  = 3e86f507...
   revision_hash            = 3e86f507...
   variant_count            = 1
   asset_count              = 1
   document_count           = 13
   revision_count           = 1
✅ GET /api/v1/vplib/library/scan?force_refresh=true funktioniert.
✅ GET /api/v1/vplib/library/blocks?source=db&limit=20 funktioniert.
✅ GET /api/v1/vplib/library/tree?source=db funktioniert.
✅ routes/api.py ist syntaktisch gültig.
✅ library_scan_service.py ist syntaktisch gültig.
✅ library_db_sync_service.py ist syntaktisch gültig.
✅ creative_library_repository.py ist syntaktisch grundsätzlich importierbar.
```

### Aktuell offen

```text
⚠️ GET /blocks/<block_id>/variants?source=db antwortet technisch ok,
   liefert aber count = 0, obwohl variant_count = 1 und eine DB-Variante existiert.

⚠️ Ursache sehr wahrscheinlich:
   creative_library_repository.py / get_family_variants(...)
   beziehungsweise _filter_not_deleted(...), weil NULL-Statuswerte durch
   `status != 'deleted'` oder `publication_status != 'deleted'` weggefiltert
   werden können.

⚠️ GET /blocks/<block_id>?source=db wurde nach den letzten Repository-Fixes
   nicht vollständig mit Response-Payload dokumentiert. Frühere Fehler waren:
   - doppelte identifier/block_id Übergabe in routes/api.py
   - bigint-vs-varchar Fehler in get_family_by_identifier(...)
   Beide Fehler sind verstanden und durch Ziel-Patches adressiert.

⚠️ POST /sync muss nach allen letzten Fixes erneut final getestet werden:
   - keine Timeout-Response
   - keine rekursive SyncResult-Serialisierung
   - keine neue Revision bei gleichem revision_hash
```

### Wichtigster aktueller technischer Fokus

```text
services/vectoplan-library/src/library/repositories/sql/creative_library_repository.py

P0:
- get_family_by_identifier(...) darf String-Identifier nicht gegen bigint id vergleichen.
- _filter_not_deleted(...) muss NULL als "nicht gelöscht" behandeln.
- get_family_variants(...) muss die gespeicherte default-Variante zurückgeben.
```

---

## 1. Zweck dieses Dokuments

Dieses Dokument beschreibt den aktuellen Zustand der Library-Schicht von `vectoplan-library`.

Es ersetzt die bisherigen additiven IST-Notizen durch einen bereinigten Stand und dokumentiert:

```text
- aktuelle Architektur
- Ordnerstruktur
- Rolle jeder Datei und Schicht
- Source-of-Truth-Modell
- DB-Sync-Pfad
- Published-DB-Read-Pfad
- API-Routen
- reale Tests
- behobene Fehler
- offene Fehler
- nächste Arbeitsschritte
```

---

## 2. Grundverständnis

`src/library` ist die fachliche Creative-Library-Schicht oberhalb von `src/vplib`.

```text
src/vplib
  technischer VPLIB-Kern
  - Package-Modelle
  - Defaults
  - technische Validatoren
  - Creator
  - Source-Scanner
  - Loader
  - Archive
  - vplib_uid-Service

src/library
  fachliche Creative-Library-Schicht
  - Taxonomie
  - Definitions/Profile
  - Source-Scan-Orchestrierung
  - fachliche Validierung
  - Read-Models
  - DB-Sync
  - Published-DB-Read
  - Inventory
  - API-nahe Domain-Modelle
```

Aktuelle Implementierungsstufe:

```text
filesystem-taxonomy-db-sync-published-read-model
```

Bedeutung:

```text
1. src/library/source bleibt die dateibasierte Quelle für VPLIB-Directory-Packages.
2. Scanner/Reader/Validator/Fingerprint erzeugen dateibasierte Pipeline-Ergebnisse.
3. DB-Sync schreibt gültige Packages nach PostgreSQL.
4. Published-Service liest produktive Library-Daten aus PostgreSQL.
5. routes/api.py stellt die HTTP-Außenkante für Scan, Sync und DB-Reads bereit.
6. source=db ist der produktive Zielpfad.
7. source=filesystem bleibt Debug-/Vergleichspfad.
```

---

## 3. Source of Truth und Speicherorte

### 3.1 Dateibasierte Package-Quelle

```text
services/vectoplan-library/src/library/source/
```

Aktueller Testblock:

```text
services/vectoplan-library/src/library/source/hochbau/bloecke/basic_stone_block/
```

Wichtige Dateien im Testblock:

```text
vplib.manifest.json
vplib.modules.json
family/identity.json
family/classification.json
editor/inventory.json
variants/index.json
variants/default.json
editor/placement.json
manufacturer/contract.json
physical/base.json
physical/collision.json
physical/dimensions.json
render/render_variants.json
```

Aktuelle Test-IDs:

```text
vplib_uid      = 2cd32d24-0758-4663-be1b-63f39b9b44af
family_id      = vp.hochbau.bloecke.basic_stone_block
package_id     = vplib.vp.hochbau.bloecke.basic_stone_block
revision_hash  = 3e86f507dd7af84365bdb2f9bd242647401a6f8e8ee7416b3ce7f5a5f8c01010
```

### 3.2 Persistierter produktiver Zustand

```text
PostgreSQL Datenbank: vectoplan_library
```

Wichtige Tabellen:

```text
alembic_version
creative_library_items
creative_library_revisions
creative_library_variants
creative_library_assets
creative_library_documents
creative_library_scan_runs
creative_library_scan_issues
creative_library_inventory_slots
```

### 3.3 Runtime-/Output-Verzeichnis

```text
services/vectoplan-library/generated/
```

Bedeutung:

```text
- Output
- Cache
- Testartefakte
- Archive
- keine kanonische Quelle für Library-Blöcke
```

### 3.4 Migrationen

```text
services/vectoplan-library/migrations/
services/vectoplan-library/migrations/versions/
```

Aktueller Stand:

```text
✅ migrations/versions wird lokal sichtbar.
✅ Alembic-State ist konsistent.
✅ Tabellen existieren.
```

---

## 4. Architekturkarte

```text
services/vectoplan-library/src/library
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
│   └── library_published_service.py
│
├── repositories/
│   ├── __init__.py
│   └── sql/
│       ├── __init__.py
│       └── creative_library_repository.py
│
└── source/
    └── {domain}/{category}/{subcategory}/{family_slug}/
```

Relevante Außenkante:

```text
services/vectoplan-library/routes/
└── api.py

services/vectoplan-library/src/routes/
└── __init__.py

services/vectoplan-library/models/
└── creative_library.py

services/vectoplan-library/entrypoint.sh
services/vectoplan-library/docker-compose.yml
```

Wichtig: Im Container ist für die aktive API-Datei der Pfad sichtbar als:

```text
routes/api.py
```

Im Repo-Kontext wurde teils auch `src/routes/api.py` erwähnt. Für die getesteten Containerbefehle gilt:

```text
docker compose exec -T vectoplan-library python -m py_compile routes/api.py
```

---

## 5. Zentrale Architekturregeln

### 5.1 Read-/Write-Trennung

```text
GET /api/v1/vplib/library/scan
  liest/scant dateibasiert
  schreibt nicht in PostgreSQL

POST /api/v1/vplib/library/sync
  scannt dateibasiert
  schreibt über Repository nach PostgreSQL

GET /api/v1/vplib/library/blocks
GET /api/v1/vplib/library/blocks/<block_id>
GET /api/v1/vplib/library/blocks/<block_id>/variants
GET /api/v1/vplib/library/tree
GET /api/v1/vplib/library/inventory
  lesen standardmäßig aus DB
```

### 5.2 DB erzeugt keine `vplib_uid`

```text
vplib_uid entsteht im Create-Flow oder steht im Source-Package.
vplib_uid wird aus vplib.manifest.json gelesen.
Repository und DB-Sync übernehmen diese ID.
DB erzeugt sie nicht.
DB repariert sie nicht.
```

### 5.3 Revisionsregel

```text
revision_hash beschreibt den Inhaltsstand.
Neue Revision nur bei geändertem revision_hash.
Gleicher revision_hash = idempotenter Sync ohne neue Revision.
```

### 5.4 Scanner bleibt DB-frei

```text
Scanner:
  findet, liest und fingerprintet Packages

Validation:
  bewertet Packages fachlich

DB-Sync-Service:
  schreibt valide Ergebnisse über Repository in DB
```

### 5.5 Repository bleibt Scanner-frei

```text
Repository kennt SQLAlchemy und Models.
Repository kennt keine Scanner- oder Validatorlogik.
```

---

## 6. ID- und Pfadmodell

### 6.1 Kanonische Taxonomie

```text
domain      = oberster Reiter / Hauptdomäne
category    = Kategorie innerhalb der Domain
subcategory = Unterkategorie innerhalb der Kategorie
family_slug = Paket-/Family-Slug
```

Kanonischer Zielpfad:

```text
src/library/source/{domain}/{category}/{subcategory}/{family_slug}
```

Aktueller Testblock liegt noch im Legacy-Pfad:

```text
src/library/source/hochbau/bloecke/basic_stone_block
```

Im Inhalt steht aber:

```text
domain      = hochbau
category    = bloecke
subcategory = basis
```

Daher ordnet der DB-Tree den Block korrekt ein:

```text
root
└── hochbau
    └── bloecke
        └── basis
            └── vp.hochbau.bloecke.basic_stone_block
```

Für neue Pakete sollte die kanonische Tiefe 4 verwendet werden:

```text
src/library/source/hochbau/bloecke/basis/basic_stone_block
```

### 6.2 Aktuelle IDs

```text
vplib_uid
  stabile technische Package-UID
  Beispiel: 2cd32d24-0758-4663-be1b-63f39b9b44af

family_id
  semantische Family-ID
  Beispiel: vp.hochbau.bloecke.basic_stone_block

package_id
  semantische Package-ID
  Beispiel: vplib.vp.hochbau.bloecke.basic_stone_block

revision_hash
  Inhaltsfingerprint
  Beispiel: 3e86f507dd7af84365bdb2f9bd242647401a6f8e8ee7416b3ce7f5a5f8c01010

id / *_db_id
  interne technische DB-IDs
  Beispiel: creative_library_items.id = 1
```

---

## 7. Dateien und Ordner im Detail

## 7.1 `src/library/__init__.py`

Aufgabe:

```text
Root-Fassade der Library-Schicht.
```

Verantwortung:

```text
- Lazy Imports
- Health Checks
- Cache-Clear
- Root-Informationen
- Source-Root-Ermittlung
- Subpackage-Status
- DB-/Repository-/Published-Capabilities
```

Wichtige Konzepte:

```text
CORE_SUBPACKAGES
DB_SUBPACKAGES
OPTIONAL_SUBPACKAGES
CONTENT_DIRECTORIES
SUBPACKAGE_HEALTH_FUNCTIONS
```

Status:

```text
✅ grün
```

---

## 7.2 `definitions/`

Aufgabe:

```text
Backend-eigene Definitionen für Object-Kinds, Profile, Varianten,
Einheiten, Materialien, Dokumenttypen und spätere Product-Overlay-Fähigkeit.
```

### `definitions/__init__.py`

```text
Fassade für Definitions-Schicht.
Exportiert zentrale Models, Registry- und Service-Funktionen.
```

### `definition_models.py`

```text
Dataclass-/Domain-Modelle für:
- ObjectKinds
- FamilyProfiles
- VariantProfiles
- Units
- Materials
- Variables
- DocumentTypes
- ProfileBindings
```

### `definition_registry.py`

```text
Lädt JSON-Definitionsdaten aus definitions/data/.
Stellt Registry-Zugriffe bereit.
Soll keine API- oder DB-Logik enthalten.
```

### `definition_service.py`

```text
Service-Schicht über der Registry.
Gedacht für Create-Flow, UI-Optionen, Profile Resolver und Validierung.
```

### `definitions/data/*.json`

```text
document_types.v1.json
family_profiles.v1.json
materials.v1.json
object_kinds.v1.json
profile_bindings.v1.json
units.v1.json
variables.v1.json
variant_profiles.v1.json
```

Status:

```text
✅ grün
⚠️ Taxonomie/Profile-Abgleich später weiter schärfen.
```

---

## 7.3 `taxonomy/`

Aufgabe:

```text
Kanonische Backend-Taxonomie.
```

### `taxonomy/__init__.py`

```text
Fassade für Taxonomie.
Exportiert Registry, Service, Validator und Health.
```

### `taxonomy_models.py`

```text
Modelle für Domain, Category, Subcategory, TaxonomySelection,
TaxonomyPath und Create-Optionen.
```

### `taxonomy_registry.py`

```text
Lädt taxonomy.v1.json.
Stellt Lookup und Normalisierung für domain/category/subcategory bereit.
```

### `taxonomy_validator.py`

```text
Validiert Taxonomie-Auswahl, Source-Pfad-Tiefe,
object_kind-Regeln und Legacy-Pfadfälle.
```

### `taxonomy_service.py`

```text
Service-Fassade für Routen/Create-Flow:
- verfügbare Taxonomie liefern
- Auswahl validieren
- IDs und Source-Pfade ableiten
```

### `taxonomy/data/taxonomy.v1.json`

```text
Kanonische Taxonomie-Datenbasis.
Aktuell relevant:
domain = hochbau
category = bloecke
subcategory = basis
```

Status:

```text
✅ grün
⚠️ Legacy-Pfad des Testblocks bleibt Übergangsfall.
```

---

## 7.4 `scanner/`

Aufgabe:

```text
Dateibasierter Scan von src/library/source.
```

### `scanner/__init__.py`

```text
Fassade für Discovery, Reader und Fingerprint.
```

### `package_discovery.py`

```text
Findet VPLIB-Directory-Packages.
Erkennt canonical und legacy Source-Pfade.
Leitet Pfadklassifikation ab.
Schreibt nicht in DB.
```

### `package_reader.py`

```text
Liest JSON-Dokumente aus gefundenen Package-Kandidaten.
Prüft technische Lesbarkeit.
Soll vplib.manifest.json und Module lesen.
Schreibt nicht in DB.
```

### `package_fingerprint.py`

```text
Erzeugt revision_hash / Inhaltsfingerprint aus gelesenen Dokumenten.
Schreibt nicht in DB.
```

Status:

```text
✅ grün
⚠️ vollständige vplib_uid-Durchreichung weiterhin prüfen.
```

---

## 7.5 `validation/`

Aufgabe:

```text
Fachliche Creative-Library-Validierung gelesener Packages.
```

### `validation/__init__.py`

```text
Fassade für Validatoren und Health.
```

### `library_package_validator.py`

```text
Validiert Library-Tauglichkeit:
- Identity
- Classification
- Varianten
- sichtbare Summary-Daten
- Module
- optionale VPLIB-Core-Validation
```

Bereits behoben:

```text
✅ Dict/Options-Bruch wurde erkannt.
✅ Validator-Optionen müssen dict/dataclass/Namespace-kompatibel normalisiert werden.
```

Offen:

```text
⚠️ vplib_uid als publish-kritisches Pflichtfeld final erzwingen.
⚠️ subcategory bei require_taxonomy final hart prüfen.
⚠️ Legacy depth 3 nur noch kontrolliert erlauben.
```

---

## 7.6 `domain/`

Aufgabe:

```text
API-taugliche fachliche Datenmodelle.
```

### `domain/__init__.py`

```text
Fassade für Domain-Modelle.
Enthält Exporte und Health.
```

### `library_item.py`

```text
Altes dateibasiertes Summary-Modell:
- LibraryItem
- Classification
- ValidationSummary
- AssetRefs
Wird für filesystem Debug-Pfad genutzt.
```

### `library_detail.py`

```text
Altes dateibasiertes Detailmodell:
- LibraryItemDetail
- VariantDetail
- ModuleDetail
- DocumentEntry
Wird für filesystem Detailpfad genutzt.
```

### `scan_result.py`

```text
ScanResult-Domain:
- LibraryScanResult
- LibraryScanCandidate
- ScanStats
- Messages
- DuplicateId
```

### `sync_result.py`

```text
DB-Sync-Ergebnis-Domain:
- LibrarySyncResult
- LibrarySyncCandidateResult
- LibrarySyncIssue
- LibrarySyncOperationResult
- LibrarySyncStats
- LibrarySyncRunInfo
```

Bekannter Fix:

```text
✅ dataclasses.field-Kollision wurde durch dataclass_field-Alias gelöst.
```

### `publication.py`

```text
Published-Read-Domain:
- PublishedFamilySummary
- PublishedFamilyDetail
- PublishedVariantSummary
- PublishedAssetRef
- PublishedRevisionSummary
- PublishedValidationSummary
- PublishedLibraryStats
- PublishedLibraryListResult
```

Wird durch `library_published_service.py` und DB-Read-Routen genutzt.

### `inventory.py`

```text
Inventory-Domain:
- InventoryState
- InventorySlot
- InventoryVariantRef
- InventoryAssetRef
- InventoryPlacementInfo
- InventoryStats
```

Wird durch `/inventory` und Fallback aus Published Families genutzt.

Status:

```text
✅ neue Domain-Modelle grün
⚠️ alte filesystem Domain-Modelle sollten vplib_uid sauber durchreichen.
```

---

## 7.7 `read_models/`

Aufgabe:

```text
API-nahe Builder für dateibasierte und DB-basierte Antworten.
```

### `read_models/__init__.py`

```text
Fassade und Health für Read-Model-Builder.
```

### `block_summary_builder.py`

```text
Baut filesystem-basierte Block-Summaries aus Scan-/Read-Ergebnissen.
```

### `block_detail_builder.py`

```text
Baut filesystem-basierte Detailansichten.
```

### `library_index_builder.py`

```text
Baut In-Memory-Index und Tree für filesystem Debug-Pfad.
```

### `db_block_summary_builder.py`

```text
Baut DB-basierte PublishedFamilySummary/Blocks-Responses aus DB-Zeilen.
```

### `db_block_detail_builder.py`

```text
Baut DB-basierte Detail- und Variantenantworten aus Repository-Detailpayloads.
```

### `db_library_tree_builder.py`

```text
Baut Tree:
root -> domain -> category -> subcategory -> item_ids
```

Aktuell nachgewiesen:

```text
✅ /tree?source=db funktioniert.
✅ Block erscheint unter hochbau/bloecke/basis.
```

### `db_inventory_builder.py`

```text
Baut InventoryState aus:
- echten creative_library_inventory_slots
- oder Fallback aus Published Families
```

Status:

```text
✅ DB-Tree grün
✅ DB-Blocks-Liste grün
⚠️ DB-Detail/Variants abhängig von Repository-Lookup und Child-Filtern.
```

---

## 7.8 `services/`

Aufgabe:

```text
Orchestrierung zwischen Scanner, Validation, ReadModels, Repository und API.
```

### `services/__init__.py`

```text
Service-Fassade.
Exportiert filesystem Services, DB-Sync-Service und Published-Service.
```

Wichtige Wrapper:

```text
sync_library_to_database()
sync_library_to_database_response()
list_published_blocks_db_response()
published_block_detail_db_response()
published_block_variants_db_response()
published_tree_db_response()
published_inventory_db_response()
publication_status_response()
```

### `library_scan_service.py`

```text
Orchestriert dateibasierten Scan:
Discovery -> Reader -> Validation -> Fingerprint -> ReadModel.
```

Wichtiger Fix:

```text
✅ options werden dict/dataclass/Namespace-kompatibel normalisiert.
✅ Fehler `'dict' object has no attribute 'require_taxonomy'` wurde behoben.
✅ /scan?force_refresh=true funktioniert.
```

### `library_block_service.py`

```text
Filesystem Debug-Pfad:
- list blocks
- detail
- variants
- tree
```

Bleibt wichtig für Vergleich mit DB-Pfad.

### `library_create_service.py`

```text
Create-Flow für neue Source Packages:
- draft
- validate
- package-plan
- download
- save
```

Offen:

```text
⚠️ needs_sync=true nach save stärker sichtbar machen.
⚠️ optional save?sync=true später.
```

### `library_db_sync_service.py`

```text
Filesystem/PipelineResult -> PostgreSQL.
```

Aufgaben:

```text
- Scan auslösen
- Kandidaten extrahieren
- Manifest-Fallback
- vplib_uid extrahieren
- family_id/package_id/revision_hash extrahieren
- Family upserten
- Revision erzeugen oder überspringen
- Varianten/Assets/Dokumente speichern
- Issues speichern
- SyncResult bauen
```

Wichtige Fixes:

```text
✅ Manifest-Fallback ergänzt.
✅ Dokument-Fallback aus Package-Root ergänzt.
✅ rekursive to_dict/asdict-Serialisierung entschärft.
```

Status:

```text
✅ strukturell grün
⚠️ HTTP-/End-to-End-Sync nach letzten Repository-Fixes erneut final testen.
```

### `library_published_service.py`

```text
Produktiver DB-Read-Service.
Liest über CreativeLibraryRepository und baut Published-Domain-Antworten.
```

Wichtige Pfade:

```text
list_published_blocks_response()
get_published_block_detail_response()
get_published_block_variants_response()
get_published_tree_response()
get_inventory_response()
```

Aktueller Stand:

```text
✅ Blocks-Liste funktioniert.
✅ Tree funktioniert.
⚠️ Detail abhängig von Repository Identifier Lookup.
⚠️ Variants gibt derzeit count=0, obwohl DB variant_count=1 zeigt.
```

---

## 7.9 `repositories/`

### `repositories/__init__.py`

```text
Repository-Fassade.
Lazy Import.
Backend-Auswahl.
Health.
Cache-Clear.
```

### `repositories/sql/__init__.py`

```text
SQL-Repository-Fassade.
Löst Model- und Extension-Module.
Stellt Factory für CreativeLibraryRepository bereit.
```

### `repositories/sql/creative_library_repository.py`

```text
Zentrale SQLAlchemy-Zugriffsschicht.
```

Wichtige Aufgaben:

```text
- Session holen
- Model-Klassen tolerant finden
- ScanRuns speichern
- Issues speichern
- Families upserten
- Revisionen anlegen
- Varianten/Assets/Dokumente ersetzen
- Published Families listen
- Detaildaten laden
- Varianten/Assets/Dokumente laden
- Inventory Slots lesen
```

Wichtige aktuelle Fixes/Ziel-Fixes:

```text
1. get_family_by_identifier(...)
   darf String-Identifier nicht gegen bigint id vergleichen.

2. _filter_not_deleted(...)
   muss NULL-Werte als "nicht gelöscht" behandeln.

3. Idempotenter Sync darf keine aggressive Aggregate-Reparatur ausführen.

4. current_revision_* und Counts werden konservativ gesetzt
   oder gezielt per repair_family_aggregate_fields(...) repariert.
```

Status:

```text
⚠️ wichtigste aktuelle Datei
```

---

## 7.10 `source/`

Aufgabe:

```text
Content-Verzeichnis für echte VPLIB-Directory-Packages.
```

Kanonisches Layout:

```text
source/{domain}/{category}/{subcategory}/{family_slug}/
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

Aktueller Testblock ist noch Legacy-Tiefe 3:

```text
source/hochbau/bloecke/basic_stone_block/
```

---

## 7.11 `routes/api.py`

Aufgabe:

```text
HTTP-API für Library Scan, Sync und DB-Reads.
```

Wichtige Routen:

```text
GET  /api/v1/vplib/library/health
GET  /api/v1/vplib/library/db/health
GET  /api/v1/vplib/library/scan
POST /api/v1/vplib/library/sync
GET  /api/v1/vplib/library/sync-runs
GET  /api/v1/vplib/library/publication-status
GET  /api/v1/vplib/library/blocks
GET  /api/v1/vplib/library/blocks/<block_id>
GET  /api/v1/vplib/library/blocks/<block_id>/variants
GET  /api/v1/vplib/library/tree
GET  /api/v1/vplib/library/inventory
```

Wichtige Fixes:

```text
✅ /sync gibt nicht mehr rohes LibrarySyncResult zurück.
✅ sync_response_payload(...) kompakt eingeführt.
✅ json_safe(...) nutzt to_dict vor Dataclass-Fallback.
✅ Dataclass-Fallback ist shallow statt asdict-deep.
✅ Detail-/Variants-Route nutzt call_block_identifier_function(...)
   und verhindert doppelte identifier/block_id Übergabe.
✅ Tree-DB-Route übergibt keine inkompatiblen Filter mehr.
```

Status:

```text
✅ /blocks list grün
✅ /tree grün
⚠️ /detail und /variants abhängig vom Repository-Fix
```

---

## 7.12 `models/creative_library.py`

Aufgabe:

```text
SQLAlchemy-Modelle für Creative Library.
```

Tabellen:

```text
CreativeLibraryItem              -> creative_library_items
CreativeLibraryRevision          -> creative_library_revisions
CreativeLibraryVariant           -> creative_library_variants
CreativeLibraryAsset             -> creative_library_assets
CreativeLibraryDocument          -> creative_library_documents
CreativeLibraryScanRun           -> creative_library_scan_runs
CreativeLibraryScanIssue         -> creative_library_scan_issues
CreativeLibraryInventorySlot     -> creative_library_inventory_slots
```

Aliase:

```text
CreativeLibraryFamily = CreativeLibraryItem
CreativeLibraryFamilyRevision = CreativeLibraryRevision
```

Aktuell bewiesen:

```text
✅ Tabellen existieren.
✅ Daten wurden geschrieben.
✅ Alembic erkennt Schema.
```

---

## 8. Hauptdatenflüsse

### 8.1 Dateibasierter Scan

```text
GET /api/v1/vplib/library/scan?force_refresh=true
  ↓
routes/api.py
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
read_models
  ↓
JSON Response
```

Status:

```text
✅ funktioniert
```

### 8.2 DB-Sync

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
CreativeLibraryRepository
  ↓
PostgreSQL
  ↓
LibrarySyncResult / kompakte Sync-Response
```

Status:

```text
⚠️ strukturell funktioniert
⚠️ nach letzten Fixes erneut final testen
```

### 8.3 Blocks-Liste aus DB

```text
GET /api/v1/vplib/library/blocks?source=db&limit=20
  ↓
routes/api.py
  ↓
services.list_published_blocks_db_response()
  ↓
library_published_service.list_published_blocks_response()
  ↓
CreativeLibraryRepository.list_published_families()
  ↓
PublishedFamilySummary[]
  ↓
JSON
```

Status:

```text
✅ funktioniert
✅ count = 1
```

### 8.4 Block-Detail aus DB

```text
GET /api/v1/vplib/library/blocks/<block_id>?source=db
  ↓
routes/api.py
  ↓
services.published_block_detail_db_response()
  ↓
library_published_service.get_published_block_detail_response()
  ↓
CreativeLibraryRepository.get_published_family_detail()
  ↓
CreativeLibraryRepository.get_family_by_identifier()
  ↓
CreativeLibraryRepository.get_latest_revision()
  ↓
CreativeLibraryRepository.get_family_variants/assets/documents()
  ↓
JSON
```

Status:

```text
⚠️ frühere Fehler verstanden:
   - doppelte identifier/block_id Übergabe
   - bigint-vs-varchar in get_family_by_identifier()

⚠️ finaler Detail-Response nach Repository-Fix noch vollständig dokumentieren.
```

### 8.5 Varianten aus DB

```text
GET /api/v1/vplib/library/blocks/<block_id>/variants?source=db
  ↓
routes/api.py
  ↓
services.published_block_variants_db_response()
  ↓
library_published_service.get_published_block_variants_response()
  ↓
CreativeLibraryRepository.get_family_variants()
  ↓
JSON
```

Aktueller Test:

```json
{
  "ok": true,
  "status": "ok",
  "block_id": "vp.hochbau.bloecke.basic_stone_block",
  "identifier": "vp.hochbau.bloecke.basic_stone_block",
  "count": 0,
  "variants": [],
  "source": "database"
}
```

Bewertung:

```text
HTTP-Route und Published-Service laufen.
Fehler ist nicht mehr Transport/Route.
Daten sind aber fachlich unvollständig, weil eine Variante in DB existiert.
```

Wahrscheinliche Ursache:

```text
CreativeLibraryRepository._filter_not_deleted(...)
filtert Varianten mit NULL status/publication_status weg.
```

Ziel:

```text
count = 1
variants[0].variant_id = default
```

### 8.6 Tree aus DB

```text
GET /api/v1/vplib/library/tree?source=db
```

Aktueller Test:

```text
ok = true
count = 1
root/hochbau/bloecke/basis enthält item_id:
vp.hochbau.bloecke.basic_stone_block
```

Status:

```text
✅ funktioniert
```

### 8.7 Inventory aus DB

```text
GET /api/v1/vplib/library/inventory
```

Status:

```text
⚠️ Fallback vorbereitet
⚠️ nicht final mit aktuellem Stand dokumentiert
```

---

## 9. Reale Testhistorie und Fehlerchronik

### 9.1 PowerShell-Syntaxfehler

Problem:

```text
Bash-Syntax wie \ und <<'PY' wurde in PowerShell verwendet.
```

Fix:

```text
PowerShell Here-String:
@'
python code
'@ | docker compose exec -T vectoplan-library python
```

Status:

```text
✅ geklärt
```

### 9.2 `require_taxonomy` Fehler

Fehler:

```text
'dict' object has no attribute 'require_taxonomy'
```

Ursache:

```text
library_scan_service.py übernahm options als dict,
nutzte später aber options.require_taxonomy.
```

Fix:

```text
coerce_scan_service_options(...)
```

Status:

```text
✅ behoben
✅ /scan funktioniert
```

### 9.3 Validator-Options-Risiko

Problem:

```text
library_package_validator.py konnte ebenfalls dict/options unsauber behandeln.
```

Fix:

```text
coerce_validator_options(...)
```

Status:

```text
✅ stabilisiert
```

### 9.4 `/sync` Timeout durch rekursive Serialisierung

Problem:

```text
routes/api.py gab rohes LibrarySyncResult an json_response(...)
json_safe/asdict konnte große Strukturen rekursiv serialisieren.
```

Fix:

```text
sync_response_payload(...)
shallow dataclass serialization
to_dict vor dataclass fallback
```

Status:

```text
✅ Route stabilisiert
⚠️ Sync final erneut testen
```

### 9.5 Detail-/Variants-Routen Parameterfehler

Fehler 1:

```text
got multiple values for argument 'identifier'
```

Fehler 2:

```text
missing required positional argument: 'block_id'
```

Ursache:

```text
Unterschiedliche Service-Ebenen erwarten teils block_id, teils identifier.
```

Fix:

```text
call_block_identifier_function(...)
```

Status:

```text
✅ Route stabilisiert
```

### 9.6 Tree-Route Fehler

Fehler:

```text
Failed to build published library tree.
TypeError
```

Ursache:

```text
DB-Tree-Wrapper bekam inkompatible Filter.
```

Fix:

```text
DB-Tree-Aufruf ohne **filters
```

Status:

```text
✅ /tree?source=db funktioniert
```

### 9.7 Identifier-Lookup Fehler

Fehler:

```text
operator does not exist: bigint = character varying
```

Ursache:

```text
get_family_by_identifier() verglich:
creative_library_items.id = 'vp.hochbau.bloecke.basic_stone_block'
```

Fix:

```text
id nur prüfen, wenn identifier numerisch ist.
Nach SQLAlchemy/PostgreSQL Fehler rollback() vor Fallback-Queries.
```

Status:

```text
⚠️ muss im Repository dauerhaft enthalten sein
```

### 9.8 Varianten leer trotz DB-Variante

Fehlerbild:

```text
GET /blocks/<id>/variants?source=db
ok=true
count=0
variants=[]
```

Gleichzeitig:

```text
creative_library_items.variant_count = 1
creative_library_variants enthält 1 Variante
```

Wahrscheinliche Ursache:

```text
_filter_not_deleted() behandelt NULL nicht als "nicht gelöscht".
SQL `status != 'deleted'` schließt NULL-Zeilen aus.
```

Fix-Ziel:

```text
or_(column.is_(None), column != 'deleted')
or_(is_deleted.is_(None), is_deleted == False)
```

Status:

```text
⚠️ aktuell offen / zu prüfen
```

---

## 10. Aktueller API-Teststand

### 10.1 Funktioniert

```text
GET http://localhost:5001/api/v1/vplib/library/blocks?source=db&limit=20
```

Erwartung / Ist:

```text
ok = true
status = ok
count = 1
items[0].id = vp.hochbau.bloecke.basic_stone_block
variant_count = 1
asset_count = 1
document_count = 13
revision_count = 1
```

```text
GET http://localhost:5001/api/v1/vplib/library/tree?source=db
```

Erwartung / Ist:

```text
ok = true
count = 1
tree.children[0].id = hochbau
tree.children[0].children[0].id = hochbau/bloecke
subcategory basis enthält item_id vp.hochbau.bloecke.basic_stone_block
```

### 10.2 Teilweise funktioniert

```text
GET http://localhost:5001/api/v1/vplib/library/blocks/vp.hochbau.bloecke.basic_stone_block/variants?source=db
```

Ist:

```text
ok = true
status = ok
count = 0
variants = []
```

Bewertung:

```text
Transport/Route funktioniert.
Fachliches Ergebnis ist noch falsch, weil eine Variante existiert.
```

### 10.3 Noch zu dokumentieren

```text
GET http://localhost:5001/api/v1/vplib/library/blocks/vp.hochbau.bloecke.basic_stone_block?source=db
```

Status:

```text
Nach den letzten Fixes wurde kein vollständiger Response-Payload in den Logs dokumentiert.
Muss erneut getestet und in dieses Dokument übernommen werden.
```

### 10.4 Erneut testen

```text
POST http://localhost:5001/api/v1/vplib/library/sync
```

Status:

```text
Nach den Serialisierungs- und Repository-Fixes erneut vollständig testen.
```

---

## 11. Datenbankteststand

### 11.1 Family-Aggregate

Zuletzt erwarteter guter Zustand:

```sql
select
  id,
  vplib_uid,
  current_revision_id,
  current_revision_hash,
  latest_revision_hash,
  published_revision_hash,
  revision_hash,
  variant_count,
  asset_count,
  document_count,
  revision_count
from creative_library_items
order by id desc
limit 20;
```

Erwartung:

```text
id                       = 1
vplib_uid                = 2cd32d24-0758-4663-be1b-63f39b9b44af
current_revision_id      = 1
current_revision_hash    = 3e86f507...
latest_revision_hash     = 3e86f507...
published_revision_hash  = 3e86f507...
revision_hash            = 3e86f507...
variant_count            = 1
asset_count              = 1
document_count           = 13
revision_count           = 1
```

### 11.2 Variante

Zu prüfen:

```sql
select
  id,
  family_db_id,
  item_id,
  revision_id,
  revision_db_id,
  vplib_uid,
  family_id,
  revision_hash,
  variant_id,
  id_in_family,
  label,
  is_default,
  status,
  publication_status
from creative_library_variants
order by id;
```

Erwartung:

```text
variant_id      = default
id_in_family    = default
label           = Default Stone Block
is_default      = true
status/publication_status können NULL sein
```

Wenn `status` und `publication_status` NULL sind, muss `_filter_not_deleted()` NULL-kompatibel sein.

### 11.3 Dokumente

Zu prüfen:

```sql
select relative_path, document_type, module
from creative_library_documents
order by relative_path;
```

Erwartung:

```text
13 rows
```

---

## 12. Aktuelle Statusmatrix

| Bereich | Status | Detail |
|---|---:|---|
| Docker Compose Mount | grün | Migrationsdateien lokal sichtbar |
| Alembic / Flask-Migrate | grün | Tabellen existieren, DB konsistent |
| PostgreSQL | grün | Daten sind vorhanden |
| `models/creative_library.py` | grün | 8 Tabellen aktiv |
| `domain/sync_result.py` | grün | field-Kollision behoben |
| `library_scan_service.py` | grün | /scan funktioniert |
| `library_package_validator.py` | grün-gelb | Options normalisiert, Taxonomie-Strenge offen |
| `library_db_sync_service.py` | grün-gelb | Manifest-Fallback und kompakte Serialisierung, finaler Sync-Test offen |
| `library_published_service.py` | grün-gelb | Liste/Tree grün, Variants leer |
| `routes/api.py` | grün-gelb | Liste/Tree grün, Sync/Detail final testen |
| `creative_library_repository.py` | gelb | Identifier-/NULL-Filter-Fixes sind entscheidend |
| `/blocks?source=db` | grün | count=1 |
| `/tree?source=db` | grün | count=1 |
| `/blocks/<id>?source=db` | gelb | vollständiger Payload noch einmal testen |
| `/blocks/<id>/variants?source=db` | gelb | ok=true, aber count=0 |
| `/inventory` | gelb | Fallback vorbereitet, final testen |
| `/sync` | gelb | erneut final testen |
| Route/Startup-Warnungen | gelb | nicht blockierend |
| Legacy Source-Pfad | gelb | Testblock liegt in Tiefe 3 |

---

## 13. Priorisierte offene Punkte

### P0 – Varianten korrekt aus DB lesen

Datei:

```text
src/library/repositories/sql/creative_library_repository.py
```

Korrigieren/prüfen:

```text
_filter_not_deleted(...)
```

Soll:

```text
NULL status/publication_status nicht wegfiltern.
```

Ziel:

```text
GET /blocks/<id>/variants?source=db
→ count = 1
→ variants[0].variant_id = default
```

### P0 – Identifier-Lookup dauerhaft korrekt halten

Datei:

```text
src/library/repositories/sql/creative_library_repository.py
```

Korrigieren/prüfen:

```text
get_family_by_identifier(...)
```

Soll:

```text
String-Identifier nur mit Textfeldern vergleichen.
id bigint nur bei numerischem Identifier vergleichen.
Nach DB-Fehler rollback() ausführen.
```

### P1 – Detail-Response final prüfen

Route:

```text
GET /api/v1/vplib/library/blocks/vp.hochbau.bloecke.basic_stone_block?source=db
```

Erwartung:

```text
ok = true
summary/id/family_id/vplib_uid vorhanden
revision vorhanden
variants enthält default oder wenigstens count konsistent
documents enthält 13 Dokumente, wenn include_raw_documents=true
```

### P1 – Sync final erneut testen

Route:

```text
POST /api/v1/vplib/library/sync
```

Erwartung:

```text
ok = true
kein Timeout
keine neue Revision bei gleichem revision_hash
kein ExitCode=-1
keine idle-in-transaction Sessions
```

### P1 – Inventory testen

Route:

```text
GET /api/v1/vplib/library/inventory
```

Erwartung:

```text
ok = true
slots enthält mindestens einen Fallback-Slot aus Published Families
```

### P2 – Legacy-Pfad auf kanonischen Pfad migrieren

Aktuell:

```text
source/hochbau/bloecke/basic_stone_block
```

Ziel:

```text
source/hochbau/bloecke/basis/basic_stone_block
```

Danach:

```text
Scan/Synchronisation erneut ausführen.
classification_path und source_path sollten konsistent sein.
```

### P2 – Asset-Policy klären

Aktuell:

```text
asset_count = 1
role = material_refs
path war zeitweise strukturiert/leer
```

Zu entscheiden:

```text
A) material_refs nicht als Asset speichern
B) payload-only Asset erlauben
C) leere Mapping-Assets überspringen
```

### P2 – Startup-Warnungen bereinigen

Beobachtete Warnungen:

```text
Extension error [routes]: One or more required blueprints are missing.
Directory check failed for routes_root.
VPLIB settings check failed: 'NoneType' object has no attribute '__dict__'
Library settings check failed: 'NoneType' object has no attribute '__dict__'
```

Aktuell:

```text
nicht blockierend
```

---

## 14. Testbefehle

### 14.1 Syntax

```powershell
docker compose exec -T vectoplan-library python -m py_compile routes/api.py
docker compose exec -T vectoplan-library python -m py_compile src/library/services/library_scan_service.py
docker compose exec -T vectoplan-library python -m py_compile src/library/services/library_db_sync_service.py
docker compose exec -T vectoplan-library python -m py_compile src/library/repositories/sql/creative_library_repository.py
```

### 14.2 API-Tests

```text
http://localhost:5001/api/v1/vplib/library/blocks?source=db&limit=20
```

```text
http://localhost:5001/api/v1/vplib/library/tree?source=db
```

```text
http://localhost:5001/api/v1/vplib/library/blocks/vp.hochbau.bloecke.basic_stone_block?source=db
```

```text
http://localhost:5001/api/v1/vplib/library/blocks/vp.hochbau.bloecke.basic_stone_block/variants?source=db
```

```text
http://localhost:5001/api/v1/vplib/library/inventory
```

### 14.3 DB-Aggregate

```powershell
docker compose exec -T vectoplan-library-db psql -U vectoplan -d vectoplan_library -c "select id, vplib_uid, current_revision_id, current_revision_hash, latest_revision_hash, published_revision_hash, revision_hash, variant_count, asset_count, document_count, revision_count from creative_library_items order by id desc limit 20;"
```

### 14.4 Varianten direkt prüfen

```powershell
docker compose exec -T vectoplan-library-db psql -U vectoplan -d vectoplan_library -c "select id, family_db_id, item_id, revision_id, revision_db_id, vplib_uid, family_id, revision_hash, variant_id, id_in_family, label, is_default, status, publication_status from creative_library_variants order by id;"
```

### 14.5 DB-Session-Hänger prüfen

```powershell
docker compose exec -T vectoplan-library-db psql -U vectoplan -d vectoplan_library -c "select pid, state, wait_event_type, wait_event, now() - query_start as age, left(query, 300) as query from pg_stat_activity where datname = 'vectoplan_library' order by query_start;"
```

---

## 15. Definition of Done für den aktuellen Abschnitt

Der aktuelle DB-Read-/Sync-Abschnitt gilt als stabil, wenn:

```text
1. /scan funktioniert.
2. /blocks?source=db liefert count=1.
3. /tree?source=db liefert count=1 und korrekte Taxonomie.
4. /blocks/<id>?source=db liefert ok=true und vollständiges Detail.
5. /blocks/<id>/variants?source=db liefert count=1 und variant_id=default.
6. /inventory liefert sinnvollen Slot.
7. /sync läuft ohne Timeout.
8. Wiederholter /sync erzeugt keine neue Revision.
9. creative_library_items enthält korrekte current_revision_* Werte.
10. creative_library_items enthält korrekte Counts.
11. Keine PostgreSQL-Transaction bleibt idle-in-transaction hängen.
12. Keine Route serialisiert rohe ORM- oder große SyncResult-Objekte rekursiv.
```

---

## 16. Kurzfazit

Die Library-DB-Integration ist inzwischen real nutzbar für die wichtigsten Lesewege:

```text
✅ DB enthält den Block.
✅ Blocks-Liste funktioniert.
✅ Tree funktioniert.
✅ Scan funktioniert.
✅ DB-Aggregates sind grundsätzlich repariert.
```

Der verbleibende fachliche Fehler ist eng begrenzt:

```text
GET /blocks/<id>/variants?source=db
liefert technisch ok=true, aber fachlich count=0.
```

Der nächste konkrete Eingriff liegt nicht mehr in `routes/api.py`, sondern im Repository:

```text
services/vectoplan-library/src/library/repositories/sql/creative_library_repository.py
```

Genauer:

```text
- get_family_by_identifier(...)
- _filter_not_deleted(...)
- get_family_variants(...)
```

Ziel:

```text
Die gespeicherte default-Variante muss über den DB-Published-Pfad sichtbar werden.
```
