# IST-Zustand · `services/vectoplan-library/static/js/vplib/create`

Stand: **2026-07-10**  
Letzte Aktualisierung: **2026-07-10**  
Scope: vollständiger Browser-Runtime-Ordner `services/vectoplan-library/static/js/vplib/create` plus unmittelbar erforderliche Template-, Context- und Backend-Verträge.  
Zweck: technische Bestandsaufnahme, Laufzeitkarte, Fehlerdiagnose und Arbeitsgrundlage, damit die Create-Runtime nicht erneut aus verstreuten JavaScript-, Template- und Route-Dateien rekonstruiert werden muss.

---

## Inhaltsverzeichnis

1. Kurzstatus
2. Systemgrenzen und Verantwortlichkeiten
3. Ordnerstruktur
4. Kanonische Script-Reihenfolge
5. Initialisierungs- und Laufzeitmodell
6. Context- und Template-Abhängigkeiten
7. `create_core.js`
8. `create_theme.js`
9. `create_wizard.js`
10. `create_preview.js`
11. `create_dynamic_rows_legacy.js`
12. `create_uploads.js`
13. `create_definitions.js`
14. `create_variant_utils.js`
15. `create_variant_state.js`
16. `create_variant_profiles.js`
17. `create_variant_summary.js`
18. `create_variant_field_renderer.js`
19. `create_variant_optional_fields.js`
20. `create_variant_validation.js`
21. `create_variant_drawer.js`
22. `create_variant_table.js`
23. `create_payload.js`
24. `create_actions.js`
25. `create.js`
26. Action-Bridges und Klick-Deduplizierung
27. Download-End-to-End-Flow
28. Save-, Source- und Published-Sync-Grenze
29. Backend-Routen
30. Stabiler Payload-Vertrag
31. Variant- und Profilvertrag
32. Upload-Vertrag
33. Event-System
34. DOM-Attribute und Selektoren
35. Runtime-State und Diagnostik
36. Fehlerbehandlung
37. Browser-Cache und Deployment
38. Verifizierter Runtime-Stand
39. Bekannte Risiken und offene Punkte
40. Wartungsregeln
41. Teststrategie
42. Priorisierte weitere Arbeit
43. Definition of Done
44. Praktische Debug-Reihenfolge
45. Kurzfazit

---

## 1. Kurzstatus

Der Ordner enthält die browserseitige Create-Runtime des VPLIB-Wizards. Die frühere große Ein-Datei-Logik wurde in kleine Module zerlegt.

```text
Template-Context
  ↓
create_core.js
  ↓
Theme / Wizard / Preview / Legacy / Uploads
  ↓
Definitions / Variant Utils / Variant State / Variant Profiles
  ↓
Summary / Renderer / Optional Fields / Validation / Drawer / Table
  ↓
create_payload.js
  ↓
create_actions.js
  ↓
create.js
```

Der aktuell bestätigte Funktionsstand:

```text
✅ Create-Seite rendert.
✅ Context-JSON wird defensiv geparst.
✅ Definition Options werden geladen.
✅ simple_cell_block wird als Starterprofil aufgelöst.
✅ Variant Profile simple_cell_block.v1 wird aufgelöst.
✅ Empty Variant Values werden geladen.
✅ Draft funktioniert.
✅ Validate funktioniert.
✅ Package-Plan funktioniert.
✅ .vplib-Download funktioniert.
✅ Source-Save funktioniert.
✅ physischer Download-Button ist über mehrere Ebenen abgesichert.
✅ Download-Aktion startet trotz stale bindOnce-Markern genau einmal.
✅ Download-Blob wird als Browser-Download ausgelöst.
✅ Objekt-URL wird nicht sofort widerrufen.
⚠️ Save schreibt derzeit nur in den Source-Bereich.
⚠️ Save synchronisiert derzeit nicht automatisch in die Published-DB.
⚠️ GET /library/items bleibt bis zu einem POST /library/sync leer.
⚠️ Upload-Felder transportieren derzeit nur Metadaten, keine Datei-Bytes.
```

Die drei zuletzt direkt verifizierten Runtime-Versionen:

```text
create_variant_profiles.js  0.8.0
create_payload.js           0.7.0
create_actions.js           0.9.0
```

Für andere Runtime-Dateien ist die Integration aktuell, ihre internen Versionsnummern müssen bei der nächsten Einzeldatei-Überarbeitung erneut direkt geprüft werden. Eine alte Versionsnummer in einer Datei ist nicht automatisch ein Funktionsfehler, sollte aber nicht als verbindlicher Gesamtstand interpretiert werden.

---

## 2. Systemgrenzen und Verantwortlichkeiten

### 2.1 Was der Browser tut

```text
- Wizard anzeigen und navigieren
- Formulardaten lesen
- Taxonomieauswahl spiegeln
- Variant-State verwalten
- Profile über Definitions-APIs auflösen
- Variant-Felder rendern
- Payload normalisieren
- Backend-Aktionen auslösen
- Backend-Ergebnisse anzeigen
- Download-Blob im Browser speichern
- Upload-Metadaten lokal erfassen
- Diagnosezustände bereitstellen
```

### 2.2 Was der Browser nicht tut

```text
- keine VPLIB-Dokumente fachlich erzeugen
- kein Directory Package schreiben
- kein ZIP/.vplib selbst bauen
- keine PostgreSQL-Transaktion
- keinen Published-State selbst erzeugen
- keine Datenbankmigration
- keine vollständige Source-Synchronisation
- keine Datei-Bytes aus Uploads dauerhaft speichern
- keine Python-/Backend-Validierung ersetzen
```

### 2.3 Verbindliche Architekturregel

```text
Browser = Eingabe, State, Darstellung, Requests
Backend = Normalisierung, Planung, Validierung, Package-Erzeugung, Save, Sync
PostgreSQL = Published State
```

### 2.4 Schichtgrenzen

```text
create_core.js
  technische Browserbasis

create_variant_*.js / create_definitions.js
  definitions- und variantenspezifische UI-/State-Schicht

create_payload.js
  Browser-Payload-Adapter

create_actions.js
  HTTP- und Action-Orchestrierung

create.js
  öffentliche Gesamtfassade
```

---

## 3. Ordnerstruktur

```text
services/vectoplan-library/static/js/vplib/create/
├── create_core.js
├── create_theme.js
├── create_wizard.js
├── create_preview.js
├── create_dynamic_rows_legacy.js
├── create_uploads.js
├── create_definitions.js
├── create_variant_utils.js
├── create_variant_state.js
├── create_variant_profiles.js
├── create_variant_summary.js
├── create_variant_field_renderer.js
├── create_variant_optional_fields.js
├── create_variant_validation.js
├── create_variant_drawer.js
├── create_variant_table.js
├── create_payload.js
├── create_actions.js
├── create.js
└── IST-Zustand.md
```

Die neu zu erstellende Datei dieses Dokuments gehört direkt in diesen Ordner:

```text
services/vectoplan-library/static/js/vplib/create/IST-Zustand.md
```

Direkt gekoppelte Dateien außerhalb des Ordners:

```text
services/vectoplan-library/templates/vplib/create.html
services/vectoplan-library/templates/vplib/create/_context_json.html
services/vectoplan-library/templates/vplib/create/sections/_actions.html
services/vectoplan-library/templates/vplib/create/variants/*
services/vectoplan-library/static/css/vplib/create.css
services/vectoplan-library/routes/create.py
services/vectoplan-library/routes/library_definition_routes.py
services/vectoplan-library/routes/library_routes.py
services/vectoplan-library/src/services/library_create_route_service.py
services/vectoplan-library/src/library/services/library_create_service.py
services/vectoplan-library/src/library/services/library_db_sync_service.py
```

---

## 4. Kanonische Script-Reihenfolge

Die Runtime-Dateien müssen mit `defer` und stabiler Reihenfolge geladen werden.

Empfohlene kanonische Reihenfolge:

```text
01 create_core.js
02 create_theme.js
03 create_wizard.js
04 create_preview.js
05 create_dynamic_rows_legacy.js
06 create_uploads.js
07 create_definitions.js
08 create_variant_utils.js
09 create_variant_state.js
10 create_variant_profiles.js
11 create_variant_summary.js
12 create_variant_field_renderer.js
13 create_variant_optional_fields.js
14 create_variant_validation.js
15 create_variant_drawer.js
16 create_variant_table.js
17 create_payload.js
18 create_actions.js
19 create.js
```

Harte Reihenfolgeregeln:

```text
create_core.js vor allen Runtime-Modulen
create_variant_utils.js vor definitionsabhängigen Variant-Modulen
create_variant_state.js vor Drawer/Table/Payload
create_definitions.js vor oder spätestens gemeinsam mit create_variant_profiles.js
create_variant_profiles.js vor Renderer/Drawer
create_payload.js nach Variant- und Upload-Runtimes
create_actions.js nach create_payload.js
create.js immer zuletzt
```

Warum `create.js` zuletzt geladen wird:

```text
- Es ist Orchestrator, nicht Basis.
- Es darf nur vorhandene Module verbinden.
- Es darf keine fehlende Fachruntime nachimplementieren.
- Es stellt die öffentliche Gesamt-API erst bereit, wenn Teilmodule sichtbar sind.
```

Die Template-URLs verwenden eine Asset-Version, aktuell:

```text
?v=20260710.3
```

Diese Version ist ein Cache-Buster und keine semantische Runtime-Version.

---

## 5. Initialisierungs- und Laufzeitmodell

### 5.1 Grundmuster

Die Runtime-Dateien verwenden überwiegend IIFEs:

```text
(function () {
  "use strict";
  ...
})();
```

Ziele:

```text
- keine unkontrollierten globalen Variablen
- genau ein öffentliches Window-Objekt je Runtime
- defensive Wiederverwendung bei doppeltem Laden
- getState() für Diagnose
- initialize() oder automatischer Boot
```

### 5.2 Boot-Retry

Mehrere Module warten defensiv auf ihre Abhängigkeiten.

Typisches Muster:

```text
BOOT_RETRY_MS       ungefähr 40 ms
BOOT_MAX_ATTEMPTS   ungefähr 80 bis 100
```

Das ist notwendig, weil:

```text
- defer-Skripte nacheinander ausgeführt werden
- Context-Globals aus Inline-Skripten kommen
- DOM-Partials bereits vorhanden sein müssen
- einzelne optionale Runtimes später bereit sein können
```

### 5.3 Idempotenz

Jede Runtime soll wiederholte Initialisierung tolerieren.

```text
initialize()
initialize()
refresh()
DOM Mutation
Template-Teil wird ersetzt
```

dürfen nicht zu Folgendem führen:

```text
- doppelte HTTP-Requests
- doppelte Button-Aktionen
- doppelte Events
- doppelte Tabellenzeilen
- mehrere MutationObserver für dieselbe Aufgabe
- mehrere globale State-Instanzen
```

### 5.4 Ready-Attribute

Der Root `<html>` wird für Diagnose mit `data-vp-*`-Attributen versehen.

Beispiele:

```text
data-vp-create-context-json-ready
data-vp-create-context-version
data-vp-create-definitions-ready
data-vp-create-definitions-ok
data-vp-create-variant-runtime-ready
data-vp-create-upload-ready
data-vp-create-template-version
data-vp-create-style
```

Variant Profiles ergänzt unter anderem:

```text
data-vp-create-variant-profiles-ready
data-vp-create-variant-profiles-initialized
data-vp-create-variant-profiles-status
data-vp-create-variant-profiles-operational
```

---

## 6. Context- und Template-Abhängigkeiten

Die Runtime hängt von `_context_json.html` ab. Diese Datei liegt nicht im Static-Ordner, ist aber die wichtigste Dateneingangsschicht.

### 6.1 Öffentliche Context-Globals

```text
window.VectoplanCreateContext
window.VectoplanGeneratorContext
window.VectoplanCreateDefinitions
window.VectoplanCreateDefinitionCatalogs
window.VectoplanCreateDefinitionMaps
window.VectoplanCreateDefinitionsOptions
window.VectoplanCreateUploadConfig
window.VectoplanCreateRoutes
window.VectoplanCreatePayloadContract
```

### 6.2 JSON-Script-Blöcke

Der Context-Bootstrap liest neun stabile JSON-Blöcke:

```text
vp-create-context-json
vp-generator-context-json
vp-create-options-json
vp-create-definitions-json
vp-create-health-json
vp-create-upload-json
vp-create-payload-contract-json
vp-create-ui-state-json
vp-create-wizard-json
```

### 6.3 Routen-Normalisierung

Der Context muss Routen als Strings liefern.

Akzeptierte eingehende Formen können sein:

```text
"/api/v1/..."
{ "url": "/api/v1/..." }
{ "href": "/api/v1/..." }
{ "path": "/api/v1/..." }
{ "endpoint": "/api/v1/..." }
```

Die Runtime darf niemals Folgendes erzeugen:

```text
/[object Object]
```

### 6.4 Template-Bridges

`create.html` stellt eine frühe Shell-Bridge bereit.

`sections/_actions.html` stellt eine direkte Action-Bridge bereit.

`create_actions.js` stellt die vollständige Runtime-Bindung bereit.

Diese drei Ebenen teilen einen Event-Marker, damit ein physischer Klick trotz mehrerer Fallbacks genau eine Aktion startet.

---

## 7. `create_core.js`

### 7.1 Rolle

`create_core.js` ist die technische Basis aller Create-Runtimes.

Öffentliches Global:

```text
window.VectoplanCreateCore
```

### 7.2 Verantwortlichkeiten

```text
- zentrale Selektoren
- zentrale CSS-Klassen
- Runtime-State
- Context-Zugriff
- Logging
- Event-Helfer
- DOM-Helfer
- JSON-Helfer
- Zeitstempel
- Lock-Verwaltung
- Route-Auflösung
- bindOnce-Kompatibilität
- gemeinsame Fehlertoleranz
```

### 7.3 State

Typische Core-State-Bereiche:

```text
initialized
modules
bindings
locks
context
routes
lastError
diagnostics
```

### 7.4 Locking

Actions verwenden einen benannten Lock:

```text
create-actions-run
```

Der Core soll Lock-Anfragen zentral verwalten, darf aber nicht die Action selbst ausführen.

### 7.5 `bindOnce`-Risiko

Historisch konnte ein stale Eintrag in `state.bindings` bewirken:

```text
bindOnce(key, callback)
  -> false
  -> callback wird nicht ausgeführt
```

Dadurch meldete `create_actions.js` früher `bindingDone=true`, obwohl kein Click-Listener existierte.

Der Actions-Fix 0.9.0 verlässt sich deshalb nicht mehr ausschließlich auf diesen Core-Marker.

### 7.6 Wartungsregel

`create_core.js` darf keine Variant-, Payload- oder Backend-Fachlogik aufnehmen.

---

## 8. `create_theme.js`

Öffentliches Global:

```text
window.VectoplanCreateTheme
```

### 8.1 Rolle

```text
- Theme normalisieren
- Theme auf Root-Element anwenden
- Storage-Key verwalten
- Theme-Events auslösen
- alte Theme-Keys berücksichtigen
```

### 8.2 Unterstützte API-Werte

```text
dark
light
system
black als Alias/Fallback für dark
```

### 8.3 Aktueller UI-Vertrag

Der Context erzwingt aktuell den schwarzen/dunklen Create-Stil:

```text
forced = dark
allowed = ["dark"]
```

Die Runtime kann aus Kompatibilitätsgründen weiterhin Theme-Methoden anbieten. Der produktive Create-Wizard soll im aktuellen Stand jedoch nicht unkontrolliert zwischen inkompatiblen Styles wechseln.

### 8.4 Storage-Keys

```text
vectoplan.create.wizard.theme
vectoplan.create.theme
```

---

## 9. `create_wizard.js`

Öffentliches Global:

```text
window.VectoplanCreateWizard
```

### 9.1 Rolle

```text
- aktuellen Schritt verwalten
- Zurück/Weiter
- Stepper-Klicks
- aktives Panel
- Stepper-Status
- Footer-Status
- Keyboard-Navigation
- Overlay-/Drawer-Blockierung
```

### 9.2 Schritte

```text
1 identity          Grunddaten
2 taxonomy          Taxonomie
3 variables         Variablen
4 geometry          Geometrie
5 technical         Technik
6 actions           Erzeugen
```

Technische Aliase für Schritt 3:

```text
object
object-variants
variables
```

### 9.3 Navigationsregeln

```text
- vorwärts maximal einen Schritt
- rückwärts frei
- kein unkontrollierter Sprung 2 -> 4
- aktive Overlays/Drawer blockieren Keyboard-Navigation
- keine automatische Navigation durch Profilauflösung
- keine Backend-Aktion durch normalen Stepper-Klick
```

### 9.4 State-Wahrheit

Der Wizard-State liegt in der Runtime. CSS-Klassen und DOM-Attribute sind Darstellungsspiegel.

---

## 10. `create_preview.js`

Öffentliches Global:

```text
window.VectoplanCreatePreview
```

### 10.1 Rolle

```text
- Taxonomie-Pfad spiegeln
- Identitätszusammenfassung aktualisieren
- Geometrie-Summaries aktualisieren
- Objektart-/Rasterregeln anwenden
- Variant-Workspace-Kontext aktualisieren
- Preview-Hooks pflegen
```

### 10.2 Aktueller Preview-Stand

Die rechte Fläche ist weiterhin ein Entwicklungsplatzhalter.

```text
- bewusst minimal
- keine fachliche 3D-Wahrheit
- keine Package-Erzeugung
- keine GLB-Analyse
- keine Navigation
```

### 10.3 Geometrieregeln

```text
cell_block
  editor_cells_x/y/z typischerweise 1

multi_cell_module
  mindestens eine Dimension kann > 1 sein

catalog_object
  frei innerhalb des Footprints

adaptive_system
  Runtime-/Host-Kontext später entscheidend
```

---

## 11. `create_dynamic_rows_legacy.js`

Öffentliches Global:

```text
window.VectoplanCreateDynamicRowsLegacy
```

### 11.1 Zweck

Compatibility-Layer für ältere dynamische Zeilen.

```text
- Legacy-Variantenzeilen lesbar halten
- alte technische Kennwertzeilen erhalten
- neue Variant-Anlage an Drawer/State delegieren
- alte DOM-Strukturen in Payload-Fallbacks einbeziehen
```

### 11.2 Nicht-Ziel

```text
- keine zweite Variant-Wahrheit
- keine parallele Profilauflösung
- keine eigene Backend-Validierung
- keine neue UI-Fachlogik
```

### 11.3 Migrationsregel

Neue Funktionalität gehört in:

```text
create_variant_state.js
create_variant_drawer.js
create_variant_table.js
create_payload.js
```

Legacy Rows bleiben nur als Fallback und Migrationsbrücke.

---

## 12. `create_uploads.js`

Öffentliches Global:

```text
window.VectoplanCreateUploads
```

### 12.1 Rolle

```text
- lokale File-Objekte aus Input-Feldern beobachten
- sichere Metadaten erzeugen
- Upload-Listen darstellen
- Hidden-JSON-Felder synchronisieren
- Constraints aus Context berücksichtigen
- Upload-Events auslösen
```

### 12.2 Unterstützte Bereiche

```text
geometry_model
technical_documents
variant_documents
```

### 12.3 Hidden-Felder

```text
geometry_model_uploads_json
technical_document_uploads_json
variant_document_uploads_json
```

### 12.4 Harte Grenze

Die Runtime speichert keine Datei-Bytes.

Sie darf typischerweise erfassen:

```text
name
size
mime type
extension
lastModified
purpose
field key
valid/errors
```

Sie darf nicht vortäuschen:

```text
backend_stored=true
```

solange keine echte Upload-Route die Datei persistiert hat.

### 12.5 Reentrancy-Fix

Uploads und Payload dürfen keine Event-Schleife bilden.

```text
create_uploads.syncAll()
  -> Hidden-Felder
  -> Payload-Sync
  -> kein erneutes natives input/change
  -> kein erneutes create_uploads.syncAll()
```

`syncAll()` soll intern standardmäßig still ausgeführt werden.

---

## 13. `create_definitions.js`

Öffentliches Global:

```text
window.VectoplanCreateDefinitionsRuntime
```

### 13.1 Rolle

```text
- Definitionsdaten aus Context lesen
- Definition Options vom Backend laden
- Datenformen normalisieren
- Kataloge deduplizieren
- Lookup-Strukturen bereitstellen
- readiness/status signalisieren
- Variant Profiles unterstützen
```

### 13.2 Eingangsquellen

```text
window.VectoplanCreateDefinitions
window.VectoplanCreateDefinitionCatalogs
window.VectoplanCreateDefinitionMaps
window.VectoplanCreateDefinitionsOptions
/api/v1/vplib/definitions/options
/api/v1/vplib/definitions/payload
```

### 13.3 Katalogtypen

```text
object_kinds
family_profiles
variant_profiles
variables
units
materials
document_types
profile_bindings
```

### 13.4 Deduplizierung

Definitionen müssen dataset-spezifisch dedupliziert werden.

Beispiele:

```text
variant_profiles nach profile_id/id/key
variables nach key/variable_key
units nach id/key
materials nach id/key
```

Es ist unzulässig, einen generischen Index zu verwenden, der IDs verschiedener Datasets vermischt.

### 13.5 DB-Vorrang

Bei semantischen Duplikaten soll die kanonische DB-/Backend-Definition Vorrang vor statischen Fallbacks haben.

---

## 14. `create_variant_utils.js`

Öffentliches Global:

```text
window.VectoplanCreateVariantUtils
```

### 14.1 Rolle

```text
- DOM-Helfer
- CSS-Escape
- Events
- JSON
- Slug-/ID-Normalisierung
- Definitions-Mapping
- Variant-Normalisierung
- Werttyp-Normalisierung
- sichere Array-/Mapping-Konvertierung
```

### 14.2 Werttypen

Unterstützte und zu normalisierende Typen umfassen:

```text
string
text
number
integer
boolean
enum/select
unit value
document
documents
document_list
```

### 14.3 Regel

Diese Datei darf keine Variant-State-Instanz besitzen. Sie liefert reine Hilfsfunktionen.

---

## 15. `create_variant_state.js`

Öffentliches Global:

```text
window.VectoplanCreateVariantState
```

### 15.1 Rolle

Der Variant-State ist die browserseitige fachliche Wahrheit für Varianten.

```text
state.variants
state.defaultVariantId
state.profileContext
state.version
state.lastChange
```

### 15.2 Spiegel

Folgende Elemente sind nur Spiegel:

```text
definition_variants_json
Tabellenzeilen
Drawer-Felder
Legacy variants[...]-Inputs
Summary-Ausgaben
```

### 15.3 Regeln

```text
- Variant IDs eindeutig
- genau eine Default-Variante
- default_variant_id muss existieren
- systemverwaltete variant.variant_id konsistent
- Hidden JSON idempotent
- DOM-Re-Render verändert State nicht unkontrolliert
```

### 15.4 Events

State-Änderungen informieren mindestens:

```text
Table
Drawer
Payload
Validation
Summary
```

---

## 16. `create_variant_profiles.js`

Öffentliches Global:

```text
window.VectoplanCreateVariantProfiles
```

Direkt verifizierte Version:

```text
0.8.0
```

### 16.1 Startervertrag

```text
object_kind          cell_block
family_profile_id    simple_cell_block
variant_profile_id   simple_cell_block.v1
```

Pflicht-Default-Keys:

```text
variant.variant_id
variant.label
dimensions.width_mm
dimensions.height_mm
dimensions.depth_mm
```

### 16.2 Backend-Routen

```text
GET /api/v1/vplib/definitions/resolve-family-profile
GET /api/v1/vplib/definitions/resolve-variant-profile
GET /api/v1/vplib/definitions/variant-profiles/<profile_id>?resolved=1
GET /api/v1/vplib/definitions/empty-variant-values/<profile_id>
```

### 16.3 Query-Kompatibilität

Die Runtime übermittelt snake_case und camelCase:

```text
object_kind / objectKind
family_profile_id / familyProfileId
variant_profile_id / variantProfileId
```

### 16.4 Timeout und Cache

```text
Request Timeout      15000 ms
Request Cache TTL    30000 ms
```

### 16.5 DOM-Kontext

Profile werden aus folgenden Bereichen abgeleitet:

```text
domain
category
subcategory
object_kind
family_profile_id
variant_profile_id
```

und in Workspace, Drawer, Table sowie Hidden-Felder gespiegelt.

### 16.6 Operational State

Die Runtime unterscheidet:

```text
initialized
ready
operational
status
last error
resolved profile
request cache
```

### 16.7 Fallback-Regel

Wenn Context-Daten vollständig sind, soll eine unnötige Backend-Anfrage vermieden werden. Wenn Daten fehlen oder unsicher sind, erfolgt Backend-Auflösung.

---

## 17. `create_variant_summary.js`

Öffentliches Global:

```text
window.VectoplanCreateVariantSummary
```

### 17.1 Rolle

```text
- lesbare Variant-Zusammenfassung
- Variant Count
- Default-Status
- Profilstatus
- Validierungsstatus
- optionale Feldanzahl
- Tabellen-/Drawer-Hinweise
```

### 17.2 Regel

Summary berechnet keine fachliche Wahrheit neu. Sie liest State und Validation.

---

## 18. `create_variant_field_renderer.js`

Öffentliches Global:

```text
window.VectoplanCreateVariantFieldRenderer
```

### 18.1 Rolle

```text
- definitionsverwaltete Felder rendern
- Input-Typ aus Definition ableiten
- Label, Hilfe, Unit und Constraints darstellen
- Werte aus Variant-State setzen
- Systemfelder sperren
- optionale Dokumentfelder vorbereiten
```

### 18.2 Systemverwaltetes Feld

```text
variant.variant_id
```

darf nicht wie ein frei überschreibbares normales Feld behandelt werden.

### 18.3 Renderer-Grenze

Der Renderer:

```text
- schreibt DOM
- liest Definitionen
- delegiert Werte an State/Drawer
```

Er:

```text
- validiert nicht final
- sendet keine HTTP-Aktion
- baut kein Package
```

---

## 19. `create_variant_optional_fields.js`

Öffentliches Global:

```text
window.VectoplanCreateVariantOptionalFields
```

### 19.1 Rolle

```text
- verfügbare optionale Definition-Felder ermitteln
- bereits aktive optionale Felder markieren
- Feld hinzufügen/entfernen
- additional_field_keys pflegen
- Drawer neu rendern
```

### 19.2 Regeln

```text
- Pflichtfelder nicht entfernbar
- Systemfelder nicht optional
- keine doppelten Feldkeys
- Feldentfernung muss State und Payload synchronisieren
- unbekannte Legacy-Keys nicht still zerstören
```

---

## 20. `create_variant_validation.js`

Öffentliches Global:

```text
window.VectoplanCreateVariantValidation
```

### 20.1 Rolle

```text
- clientseitige Sofortvalidierung
- required fields
- Datentypen
- min/max
- enum
- Unit
- Default-Variante
- Variant-ID-Eindeutigkeit
- Profilkonsistenz
- Fehler an Drawer/Table spiegeln
```

### 20.2 Grenze

Clientvalidierung verbessert UX, ersetzt aber nicht:

```text
POST /api/v1/vplib/create/validate
```

Backendvalidierung bleibt verbindlich.

### 20.3 Status

Eine Variante kann mindestens sein:

```text
valid
invalid
incomplete
unknown
```

---

## 21. `create_variant_drawer.js`

Öffentliches Global:

```text
window.VectoplanCreateVariantDrawer
```

### 21.1 Rolle

```text
- Variante erstellen
- Variante bearbeiten
- Profile anwenden
- Felder rendern
- optionale Felder verwalten
- Dokumentmetadaten aufnehmen
- Entwurf verwerfen
- Änderungen in Variant-State übernehmen
```

### 21.2 Drawer-State

Der Drawer besitzt einen temporären Bearbeitungszustand. Erst „Übernehmen/Speichern“ darf den zentralen Variant-State ändern.

### 21.3 Overlay-Regeln

```text
- Fokus im Drawer halten
- Escape kontrolliert behandeln
- Wizard-Keyboard-Navigation blockieren
- mehrfaches Öffnen idempotent
- beim Re-Render keine Listener vervielfachen
```

---

## 22. `create_variant_table.js`

Öffentliches Global:

```text
window.VectoplanCreateVariantTable
```

### 22.1 Rolle

```text
- Variant-State als Liste rendern
- Default markieren
- Validierungsstatus anzeigen
- Bearbeiten auslösen
- Legacy-Hidden-Inputs spiegeln
- viele Varianten scrollbar darstellen
```

### 22.2 Regel

Die Tabelle ist kein State-Store.

```text
State -> Table
```

nicht:

```text
Table DOM -> fachliche Wahrheit
```

---

## 23. `create_payload.js`

Öffentliches Global:

```text
window.VectoplanCreatePayload
```

Direkt verifizierte Version:

```text
0.7.0
```

### 23.1 Rolle

```text
- Formular finden
- FormData robust einlesen
- Scalar Fields normalisieren
- JSON Fields parsen
- Variant-State in Payload spiegeln
- Upload-Metadaten übernehmen
- Profile und Taxonomie normalisieren
- Defaultwerte ergänzen
- Payload-Contract prüfen
- Payload Summary erzeugen
```

### 23.2 Öffentliche Kern-API

```text
initialize()
collectPayload(form, options)
syncVariantRuntimeToForm(form)
syncUploadsRuntimeToForm(form)
getDefinitionVariants(form)
getDefinitionVariantsJson(form)
getUploadMetadata(form)
normalizeDefinitionVariant(...)
ensureDefinitionVariantHiddenFields(form)
ensureUploadHiddenFields(form)
getState()
```

### 23.3 Zentrale Felder

```text
vplib_uid
family_name
family_description
domain
category
subcategory
taxonomy_path
object_kind
family_profile_id
variant_profile_id
definition_variants_json
default_variant_id
primitive_shape
geometry_unit
geometry_width
geometry_height
geometry_depth
editor_cells_x
editor_cells_y
editor_cells_z
material_class
geometry_model_uploads_json
technical_document_uploads_json
variant_document_uploads_json
```

### 23.4 Variant-Quelle

Priorität:

```text
1. window.VectoplanCreateVariantState
2. definition_variants_json
3. Legacy variants[...] DOM-Felder
4. Starter-Default
```

### 23.5 System-Keys

Folgende Keys werden besonders geschützt:

```text
variant.variant_id
variant.variantId
variant.id
variant_id
variantId
id
```

### 23.6 Upload-Reentrancy

State enthält Diagnosewerte wie:

```text
uploadSyncCount
skippedUploadSyncCount
suppressedUploadEventCount
uploadSyncActive
lastUploadSync
uploadFileCount
uploadErrorCount
```

### 23.7 Payload-Contract

Der Context kann liefern:

```text
required_fields
duplicate_formdata_guards
```

Mindestens geschützt:

```text
object_kind
family_profile_id
variant_profile_id
definition_variants_json
default_variant_id
```

### 23.8 Keine Browser-Package-Erzeugung

`collectPayload()` erzeugt ein Request-Objekt, kein Package.

---

## 24. `create_actions.js`

Öffentliches Global:

```text
window.VectoplanCreateActions
```

Direkt verifizierte Version:

```text
0.9.0
```

### 24.1 Aktionen

```text
draft
validate
package-plan
download
save
persist-draft
publish-prepare
```

Aliasformen werden normalisiert:

```text
package_plan
persist_draft
persistent-draft
persistent_draft
publish_prepare
publish-bundle
publish_bundle
```

### 24.2 Routen

```text
draft             /draft
validate          /validate
package-plan      /package-plan
download          /download
save              /save
persist-draft     /drafts
publish-prepare   /publish-bundle
```

Der effektive Prefix kommt aus dem Context, Standard:

```text
/api/v1/vplib/create
```

### 24.3 Timeouts

Aktueller gehärteter Bereich:

```text
normaler Request       ungefähr 60000 ms
Preflight              ungefähr 45000 ms
Download               ungefähr 120000 ms
Action Lock            bis ungefähr 120000 ms
```

### 24.4 Download-Prüfung

Akzeptierte Archive-MIME-Typen umfassen:

```text
application/zip
application/x-zip-compressed
application/octet-stream
application/vnd.vectoplan.vplib
application/vnd.vectoplan-library
```

Minimale Archivgröße:

```text
64 Bytes
```

Zusätzlich wird geprüft:

```text
- HTTP Status
- Content-Type
- Content-Disposition
- Blob-Größe
- Fehlerpayload statt Blob
- Dateiname
```

### 24.5 Binding-Fix 0.9.0

Der zentrale Fix:

```text
bindingDone wird erst true,
wenn reale Listener registriert wurden.
```

Die Runtime besitzt:

```text
- eigene globale Binding-Registry
- delegierten document capture listener
- direkten Button-Fallback
- Event-Marker gegen Doppelstart
- Listener-Replacement bei Reload
- MutationObserver
- Binding-Verifikation
- Binding-Reparatur
- Click-Diagnostik
```

Öffentliche Diagnose-/Reparaturmethoden:

```text
bindControls()
repairBindings()
verifyBindings()
diagnoseBindings()
bindDirectActionButtons()
triggerBrowserDownload()
getState()
```

### 24.6 Physischer Klick

Ein echter Button-Klick soll unabhängig funktionieren von:

```text
- stale Core bindOnce key
- verspätetem Runtime-Load
- nachträglich ersetztem Button
- delegiertem Listener-Ausfall
- direktem Listener-Ausfall
```

### 24.7 Doppelstartschutz

Ein gemeinsamer Marker am Event verhindert:

```text
Shell Bridge
+ Template Bridge
+ delegated Actions listener
+ direct Actions listener
= vier Starts
```

Erwartung:

```text
ein physischer Klick = genau eine Action
```

### 24.8 Download-URL

Die Object URL wird nicht sofort widerrufen.

Aktueller Cleanup:

```text
ungefähr 60000 ms verzögert
```

Das verhindert Browser, die den Blob nach dem synthetischen Anchor-Klick noch benötigen.

### 24.9 Save-Status

Die Runtime zeigt die Antwort von `/create/save`.

Sie darf aktuell nicht behaupten, der Eintrag sei Published, wenn die Antwort nur Source-Save bestätigt.

---

## 25. `create.js`

Öffentliches Global:

```text
window.VectoplanCreate
```

Zuletzt direkt inspizierte interne Version:

```text
0.6.0
```

Die Integrationsdatei muss bei einer nächsten Einzeldatei-Aktualisierung erneut auf den aktuellen Gesamtvertrag angehoben werden.

### 25.1 Rolle

```text
- Teilmodule initialisieren
- öffentliche Gesamt-API bereitstellen
- State-Snapshots zusammenführen
- Refresh delegieren
- Wizard-Funktionen delegieren
- Theme delegieren
- Payload delegieren
- Actions delegieren
- Variant-/Upload-Sync delegieren
```

### 25.2 Öffentliche API

```text
getState()
collectPayload()
runAction(action)
goToStep(step)
nextStep()
prevStep()
previousStep()
setTheme(theme)
cycleTheme()
updatePreview()
refresh()
syncVariants()
syncUploads()
getDefinitionVariants()
getDefinitionVariantsJson()
getUploadMetadata()
```

### 25.3 Regel

`create.js` darf keine große Fachlogik zurückholen.

Wenn ein Teilmodul fehlt:

```text
- Status partial/unavailable melden
- nicht still dieselbe Fachlogik duplizieren
- getState() diagnostisch halten
```

---

## 26. Action-Bridges und Klick-Deduplizierung

### 26.1 Warum mehrere Bridges existieren

Der Download-Button reagierte trotz erfolgreicher direkter API-Aufrufe zeitweise nicht auf physische Klicks.

Diagnose:

```text
window.VectoplanCreateActions.runAction("download")
  -> funktioniert

physischer Button-Klick
  -> kein POST
```

Damit war Backend/Payload/Download funktionsfähig und die Störung lag in der DOM-Bindung.

### 26.2 Drei Schutzebenen

```text
1. create.html Shell Bridge
2. _actions.html direkte Template Bridge
3. create_actions.js vollständige Runtime-Bindung
```

### 26.3 Shell Bridge

Wird früh im `<head>` registriert.

```text
- document capture listener
- läuft vor defer-Runtimes
- wartet auf VectoplanCreateActions
- kann VectoplanCreate als Fallback nutzen
```

### 26.4 Template Bridge

Liegt direkt bei den Buttons.

```text
- kennt data-create-action
- ruft runAction(action, form, button)
- wartet begrenzt auf Runtime
- zeigt Runtime-Fehler im Statusbereich
```

### 26.5 Actions Runtime

Übernimmt nach vollständigem Laden.

```text
- delegierter Listener
- direkter Listener
- MutationObserver
- Verifikation und Repair
```

### 26.6 Gemeinsamer Marker

Alle Ebenen müssen denselben semantischen Marker respektieren.

```text
bereits behandelt
  -> keine zweite Ausführung
```

### 26.7 Abnahmekriterium

```text
Button.click()
  -> exakt ein Workflow
  -> exakt ein Download
```

---

## 27. Download-End-to-End-Flow

Aktueller Download-Ablauf:

```text
Nutzer klickt Download
  ↓
Action Bridge / Actions Runtime
  ↓
Payload collectPayload()
  ↓
POST /api/v1/vplib/create/validate
  ↓
POST /api/v1/vplib/create/package-plan
  ↓
POST /api/v1/vplib/create/download
  ↓
Backend erzeugt .vplib
  ↓
Blob Response
  ↓
Content-/Größenprüfung
  ↓
Object URL
  ↓
temporärer <a download>
  ↓
click()
  ↓
verzögerter revokeObjectURL()
```

Warum Validate und Package-Plan vor Download:

```text
- frühe verständliche Fehler
- Download-Route nicht mit offensichtlich invalidem Payload belasten
- Dateiname und Plan diagnostisch sichtbar
- stabile UX
```

Fehlerfälle:

```text
- JSON-Fehlerantwort statt Blob
- Content-Type falsch
- Blob zu klein
- Content-Disposition fehlt
- Request Timeout
- Abort
- Payload invalid
- Package-Plan fehlerhaft
```

---

## 28. Save-, Source- und Published-Sync-Grenze

### 28.1 Aktueller Save

```text
POST /api/v1/vplib/create/save
```

führt derzeit aus:

```text
Payload
  -> Backend Create Service
  -> Directory Package
  -> src/library/source/...
```

### 28.2 Was Save nicht automatisch tut

```text
- keinen POST /api/v1/vplib/library/sync
- keinen automatischen Published-DB-Write
- keine Read-after-write-Verifikation unter /library/items
```

### 28.3 Aktueller Published-Sync

```text
POST /api/v1/vplib/library/sync
```

führt aus:

```text
Source Scan
  -> Validation
  -> Fingerprint
  -> Candidate Sync
  -> PostgreSQL Published State
```

### 28.4 Sichtbare Folge

Nach einem erfolgreichen Source-Save kann Folgendes korrekt sein:

```json
{
  "item_count": 0,
  "items": []
}
```

unter:

```text
GET /api/v1/vplib/library/items
```

solange noch kein erfolgreicher POST-Sync gelaufen ist.

### 28.5 Kein Browser-Auto-Sync

Der Browser soll die automatische Synchronisation langfristig nicht selbst durch einen zweiten HTTP-Aufruf implementieren.

Zielarchitektur:

```text
POST /create/save
  -> Backend Save-and-Sync-Orchestrierung
  -> Source schreiben
  -> einzelnes Package scannen
  -> einzelnes Package synchronisieren
  -> Published verifizieren
  -> ein gemeinsames Ergebnis
```

Diese Orchestrierung ist derzeit noch nicht umgesetzt.

### 28.6 UI-Regel bis dahin

```text
Source gespeichert
```

ist nicht gleich:

```text
in Published Library sichtbar
```

---

## 29. Backend-Routen

### 29.1 Create

```text
GET  /api/v1/vplib/create/health
GET  /api/v1/vplib/create/routes
GET  /api/v1/vplib/create/selftest
GET  /api/v1/vplib/create/options
GET  /api/v1/vplib/create/context
GET  /api/v1/vplib/create/create-context

POST /api/v1/vplib/create/draft
POST /api/v1/vplib/create/drafts
POST /api/v1/vplib/create/validate
POST /api/v1/vplib/create/package-plan
POST /api/v1/vplib/create/publish-bundle
POST /api/v1/vplib/create/download
POST /api/v1/vplib/create/save
POST /api/v1/vplib/create/cache/clear
```

### 29.2 Definitions

```text
GET /api/v1/vplib/definitions/options
GET /api/v1/vplib/definitions/payload
GET /api/v1/vplib/definitions/resolve-family-profile
GET /api/v1/vplib/definitions/resolve-variant-profile
GET /api/v1/vplib/definitions/variant-profiles/<profile_id>
GET /api/v1/vplib/definitions/empty-variant-values/<profile_id>
POST /api/v1/vplib/definitions/validate-variant
```

### 29.3 Library

```text
GET  /api/v1/vplib/library/health
GET  /api/v1/vplib/library/scan
POST /api/v1/vplib/library/sync
GET  /api/v1/vplib/library/items
GET  /api/v1/vplib/library/vplib/<vplib_uid>
GET  /api/v1/vplib/library/blocks
GET  /api/v1/vplib/library/tree
```

### 29.4 Methoden sind verbindlich

```text
GET /library/sync
  -> 405 korrekt

POST /library/sync
  -> richtige Methode
```

---

## 30. Stabiler Payload-Vertrag

### 30.1 Identität

```text
vplib_uid
family_name
family_description
```

### 30.2 Taxonomie

```text
domain
category
subcategory
taxonomy_path
```

### 30.3 Profil

```text
object_kind
family_profile_id
variant_profile_id
```

### 30.4 Varianten

```text
definition_variants_json
default_variant_id
variants[...]
additional_field_keys
```

### 30.5 Geometrie

```text
primitive_shape
geometry_unit
geometry_width
geometry_height
geometry_depth
editor_cells_x
editor_cells_y
editor_cells_z
```

### 30.6 Technik

```text
material_class
variables[i][key]
variables[i][value]
variables[i][unit]
variables[i][description]
```

### 30.7 Upload-Metadaten

```text
geometry_model_uploads_json
technical_document_uploads_json
variant_document_uploads_json
```

### 30.8 Duplicate Guards

Folgende Felder dürfen nicht mehrfach widersprüchlich in FormData landen:

```text
object_kind
family_profile_id
variant_profile_id
definition_variants_json
default_variant_id
```

---

## 31. Variant- und Profilvertrag

### 31.1 Starter

```text
object_kind = cell_block
family_profile_id = simple_cell_block
variant_profile_id = simple_cell_block.v1
default_variant_id = default
```

### 31.2 Starterwerte

```text
variant.variant_id
variant.label
dimensions.width_mm
dimensions.height_mm
dimensions.depth_mm
```

### 31.3 ID-Regeln

```text
Variant ID stabil
Default ID existiert
Systemfeld variant.variant_id stimmt
keine doppelte Variant ID
```

### 31.4 Profilauflösung

Kontext:

```text
domain
category
subcategory
object_kind
family_profile_id
variant_profile_id
```

Antworten können mehrere Formen haben. Die Runtime muss tolerant normalisieren, aber darf keine fachlich falsche Definition aus einem anderen Dataset übernehmen.

### 31.5 Backend ist kanonisch

Lokale Context-Daten sind Boot-/Fallback-Daten. Bei Abweichungen hat die kanonische Backend-Auflösung Vorrang.

---

## 32. Upload-Vertrag

### 32.1 Metadaten-only

Aktuell:

```text
File Input
  -> Browser File Metadata
  -> Hidden JSON
  -> Create Payload
```

Nicht aktuell:

```text
File Input
  -> multipart upload
  -> LibraryFile
  -> FileVersion
  -> persistent link
```

### 32.2 Felder

```text
geometry_model_files
technical_document_files
variant_document_files
```

werden browserseitig beobachtet, aber der JSON-Create-Request enthält primär Metadaten.

### 32.3 Sicherheitsregel

Eine UI darf nicht „hochgeladen“ oder `backend_stored=true` anzeigen, solange der Backend-Upload nicht bestätigt ist.

---

## 33. Event-System

Wichtige Events:

```text
vectoplan:create:context-ready
vectoplan:create:definitions-ready
vectoplan:create:definitions-unavailable
vectoplan:create:variant-profile-resolved
vectoplan:create:variant-state-ready
vectoplan:create:theme-ready
vectoplan:create:uploads-ready
vectoplan:create:upload-changed
vectoplan:create:upload-cleared
vectoplan:create:geometry-upload-changed
vectoplan:create:technical-upload-changed
vectoplan:create:variables-upload-changed
```

Zusätzlich existieren modulinterne Events für:

```text
wizard step changed
identity changed
taxonomy changed
geometry changed
variant changed
variant default changed
drawer opened/closed
validation changed
payload collected
action started
action completed
action failed
download started
```

Event-Regeln:

```text
- Eventnamen stabil halten
- Detail JSON-safe
- keine großen File-/ORM-Objekte
- keine zyklischen Payloads
- stille interne Synchronisierung nicht unnötig eventen
- Event-Schleifen vermeiden
```

---

## 34. DOM-Attribute und Selektoren

### 34.1 Form

```text
[data-vp-create-form]
[data-create-form="true"]
#vp-create-form
```

### 34.2 Action

```text
[data-create-action]
[data-vp-actions-root="true"]
[data-create-actions-card="true"]
[data-vp-actions-result]
```

### 34.3 Variant Workspace

```text
[data-vp-variant-workspace-root="true"]
[data-vp-variant-workspace="true"]
```

### 34.4 Drawer

```text
[data-vp-variant-drawer-root="true"]
[data-vp-variant-drawer="true"]
```

### 34.5 Table

```text
[data-vp-variant-table-root="true"]
[data-vp-variant-table="true"]
```

### 34.6 Profilfelder

```text
[name="object_kind"]
[name="family_profile_id"]
[name="variant_profile_id"]
[name="default_variant_id"]
[name="definition_variants_json"]
```

### 34.7 Taxonomie

```text
[name="domain"]
[name="category"]
[name="subcategory"]
[data-vp-taxonomy-domain]
[data-vp-taxonomy-category]
[data-vp-taxonomy-subcategory]
```

### 34.8 Wartungsregel

Bei Template-Änderungen zuerst bestehende Datenattribute erweitern, nicht unkoordiniert ersetzen.

---

## 35. Runtime-State und Diagnostik

### 35.1 Einheitliches Muster

Jede Runtime soll mindestens bieten:

```text
version
initialized
status
lastError
getState()
```

### 35.2 Actions-Diagnose

```javascript
window.VectoplanCreateActions.getState()
window.VectoplanCreateActions.diagnoseBindings()
window.VectoplanCreateActions.verifyBindings()
```

Wichtige Felder:

```text
bindingDone
pending
currentAction
lastAction
lastResult
lastError
lastHttpStatus
actionCount
downloadCount
lastClick
binding diagnostics
download diagnostics
```

### 35.3 Payload-Diagnose

```javascript
window.VectoplanCreatePayload.getState()
```

Wichtige Felder:

```text
collectCount
syncCount
uploadSyncCount
runtimeVariantCount
fallbackVariantCount
uploadFileCount
uploadErrorCount
lastPayloadSummary
lastValidation
lastError
```

### 35.4 Profiles-Diagnose

```javascript
window.VectoplanCreateVariantProfiles.getState()
```

Wichtige Bereiche:

```text
operational
context
resolved family profile
resolved variant profile
request cache
last request
last error
```

### 35.5 Gesamtstatus

```javascript
window.VectoplanCreate.getState()
```

soll Teilmodule zusammenfassen, nicht deren State überschreiben.

---

## 36. Fehlerbehandlung

### 36.1 Grundmuster

Fast jede DOM-, JSON- und Runtime-Grenze wird mit `try/catch` abgesichert.

Ziel:

```text
- optionale Runtime fehlt -> partial statt kompletter Seitenabbruch
- defektes DOM-Element -> andere Aktionen bleiben nutzbar
- ungültiges JSON -> Fallback + Diagnose
- Netzwerkfehler -> verständliche Resultanzeige
```

### 36.2 Nicht verschlucken

Defensive Fehlerbehandlung darf nicht bedeuten:

```text
catch (error) { /* immer ignorieren */ }
```

bei kritischen Vorgängen.

Kritisch:

```text
Payload
Validate
Package Plan
Download
Save
Profile Resolution
Variant Commit
```

### 36.3 HTTP-Fehler

Zu unterscheiden:

```text
400 Payload
404 Definition/Profile
409 Konflikt
422 Validierung
500 interner Fehler
503 Service/DB nicht verfügbar
405 falsche Methode
Timeout/Abort
```

### 36.4 Teilstatus Save

```text
Source gespeichert
DB nicht synchronisiert
```

ist ein Teilzustand und darf nicht als vollständig Published dargestellt werden.

---

## 37. Browser-Cache und Deployment

### 37.1 Problem

Logs zeigten wiederholt:

```text
304 Not Modified
```

Das ist normal, kann aber nach einem Runtime-Fix dazu führen, dass ein alter Browser-/Proxy-Stand weiterverwendet wird.

### 37.2 Cache-Buster

Alle Create-Skripte sollen dieselbe Asset-Version tragen:

```text
?v=20260710.3
```

Bei einer produktiven Runtime-Änderung:

```text
- Asset-Version erhöhen
- Service neu bauen/starten
- Browser Hard Reload
- DevTools Disable Cache für Test
```

### 37.3 Diagnose

Im Network-Tab prüfen:

```text
Request URL
Status
Response Size
Initiator
geladene Query-Version
```

### 37.4 Doppelter Runtime-Code

Es darf nicht gleichzeitig geladen werden:

```text
static/library_admin/js/create_actions.js
und
static/js/vplib/create/create_actions.js
```

Der kanonische Pfad ist:

```text
static/js/vplib/create/
```

---

## 38. Verifizierter Runtime-Stand

Am 10. Juli 2026 wurden im echten Service-Log bestätigt:

```text
GET /create                                                  200
GET /definitions/options                                     200
GET /definitions/resolve-family-profile                      200
GET /definitions/resolve-variant-profile                     200
GET /definitions/empty-variant-values/simple_cell_block.v1   200
GET /definitions/variant-profiles/simple_cell_block.v1       200
POST /create/validate                                        200
POST /create/package-plan                                    200
POST /create/download                                        200
POST /create/drafts                                          200
POST /create/save                                            200
```

Zusätzlich isoliert verifiziert:

```text
- stale Core bindOnce blockiert Actions nicht mehr
- physischer Click startet genau eine Action
- delegierter Listener funktioniert
- direkter Fallback funktioniert
- beide gemeinsam erzeugen keinen Doppelstart
- Download-Anchor wird geklickt
- Object URL wird nicht sofort widerrufen
- 60000-ms-Cleanup wird geplant
```

Nicht bestätigt als automatische Kette:

```text
POST /create/save
  -> POST /library/sync
```

Diese Kette existiert derzeit nicht.

---

## 39. Bekannte Risiken und offene Punkte

### P0

```text
1. Save synchronisiert nicht automatisch in Published DB.
2. UI muss Source-Save und Published-Erfolg klar unterscheiden.
3. create.js-Version/Vertrag erneut direkt gegen alle neuen Runtimes prüfen.
4. Vollständiger Browser-E2E-Test nach jedem Template-/Action-Update.
```

### P1

```text
5. Echte Datei-Bytes für Uploads implementieren.
6. Definitions-Requests reduzieren und Cache-Nutzung prüfen.
7. Mehrere nahezu gleiche Profilauflösungen deduplizieren.
8. Context- und Runtime-Versionen vereinheitlichen.
9. Event-Katalog verbindlich zentral dokumentieren.
10. Variant-Drawer/Renderer/Validation gemeinsam E2E testen.
```

### P2

```text
11. Preview durch echte 3D-/Geometrieansicht ersetzen.
12. Legacy Dynamic Rows weiter abbauen.
13. Theme-API und erzwungenen Dark-Context konsolidieren.
14. große Definitions-/Ready-Responses verkleinern.
```

---

## 40. Wartungsregeln

```text
1. Erste Dateizeile behält den exakten Pfadkommentar.
2. Eine Runtime besitzt genau ein primäres Window-Global.
3. getState() bleibt JSON-safe.
4. Initialisierung bleibt idempotent.
5. create.js bleibt Orchestrator.
6. Payload-Erzeugung bleibt in create_payload.js.
7. HTTP-Actions bleiben in create_actions.js.
8. Variant-State bleibt in create_variant_state.js.
9. Definitionsauflösung bleibt in Definitions/Profile-Runtimes.
10. Templates enthalten keine große Fachlogik.
11. Browser erzeugt kein VPLIB-Package.
12. Browser behauptet keinen DB-Sync ohne Backend-Bestätigung.
13. Upload-Metadaten werden nicht als persistierte Datei ausgegeben.
14. Event-Schleifen werden vermieden.
15. Listener werden bei Reload/Mutation sauber ersetzt.
16. physischer Button-Klick muss testbar bleiben.
17. Cache-Buster nach Runtime-Änderungen erhöhen.
18. snake_case und camelCase nur an definierten Kompatibilitätsgrenzen führen.
19. unbekannte Backend-Felder nicht still löschen.
20. Systemfelder nicht frei editierbar machen.
```

---

## 41. Teststrategie

### 41.1 Syntax

```text
node --check create_core.js
...
node --check create.js
```

### 41.2 Statische Prüfung

```text
- erster Pfadkommentar korrekt
- genau ein GLOBAL_NAME
- keine alten static/library_admin-Pfadkommentare
- keine doppelte Funktionsdefinition
- bekannte Runtime-Version
- öffentliche API vorhanden
```

### 41.3 Context-Test

```text
- neun JSON-Blöcke parsebar
- alle Routen Strings
- kein [object Object]
- Starterprofile vorhanden
- Window-Globals gesetzt
```

### 41.4 Variant-Test

```text
- simple_cell_block resolve
- simple_cell_block.v1 resolve
- Empty Values
- Default-Variante
- optionale Felder
- Drawer Edit
- Table Update
- definition_variants_json
```

### 41.5 Payload-Test

```text
- keine FormData-Duplikate
- vplib_uid
- Taxonomie
- Profile
- Varianten
- Default ID
- Geometrie
- Technik
- Upload-Metadaten
```

### 41.6 Action-Test

```text
- Draft
- Validate
- Package Plan
- Download
- Persist Draft
- Save
- Publish Prepare
```

### 41.7 Klicktest

```text
- Shell Bridge allein
- Template Bridge allein
- delegated Listener allein
- direct Listener allein
- alle gemeinsam
- dynamisch ersetzter Button
- stale bindOnce
```

Erwartung immer:

```text
actionCount += 1
```

### 41.8 Backend-E2E

```text
POST /create/save
GET  /library/scan?source=file
POST /library/sync
GET  /library/items
GET  /library/vplib/<vplib_uid>
```

---

## 42. Priorisierte weitere Arbeit

### Schritt 1

```text
create.js
```

gegen den aktuellen Runtime-Vertrag prüfen und auf den neuen Stand bringen.

### Schritt 2

Backend-Auto-Sync planen und implementieren:

```text
save -> single package scan -> single candidate sync -> published verify
```

### Schritt 3

`create_actions.js` anschließend auf den neuen kombinierten Save-Status anpassen.

### Schritt 4

Upload-Bytes mit File-Service verbinden.

### Schritt 5

Variant-Drawer bis Backend-Roundtrip testen:

```text
öffnen
optionales Feld hinzufügen
Wert setzen
speichern
Payload prüfen
Backend speichern
erneut laden
```

### Schritt 6

Preview-/3D-Runtime separat planen, ohne Payload- oder Action-Schicht aufzublähen.

---

## 43. Definition of Done

Der Runtime-Ordner gilt als stabil, wenn:

```text
1. Alle 19 Skripte syntaktisch gültig sind.
2. Alle Skripte nur aus static/js/vplib/create geladen werden.
3. Context-JSON ohne Fehler bootet.
4. Alle effektiven Routen Strings sind.
5. simple_cell_block zuverlässig aufgelöst wird.
6. simple_cell_block.v1 zuverlässig aufgelöst wird.
7. Variant-State und Hidden JSON übereinstimmen.
8. Payload keine kritischen Duplikate enthält.
9. Upload-Sync keine Event-Schleife erzeugt.
10. Wizard-Navigation stabil ist.
11. physischer Action-Klick genau einmal startet.
12. direkter API-Aufruf ebenfalls funktioniert.
13. Validate funktioniert.
14. Package-Plan funktioniert.
15. Download ein valides .vplib liefert.
16. Object URL ausreichend spät widerrufen wird.
17. Source-Save funktioniert.
18. Save-UI den tatsächlichen Persistenzstatus korrekt benennt.
19. Backend-Auto-Sync nach Implementierung verifiziert wird.
20. GET /library/items das gespeicherte Item danach sofort zeigt.
21. getState()-Antworten JSON-safe bleiben.
22. Runtime-Reinitialisierung keine Listener vervielfacht.
23. dynamisch ersetzte Buttons nachgebunden werden.
24. Browser-Cache eindeutig auf aktuelle Assets zeigt.
25. keine Browser-Package-Erzeugung eingeführt wird.
```

---

## 44. Praktische Debug-Reihenfolge

### 44.1 Context

```javascript
({
  context: window.VectoplanCreateContext,
  routes: window.VectoplanCreateRoutes,
  definitions: window.VectoplanCreateDefinitions,
  payloadContract: window.VectoplanCreatePayloadContract
})
```

### 44.2 Module

```javascript
({
  core: !!window.VectoplanCreateCore,
  wizard: !!window.VectoplanCreateWizard,
  uploads: !!window.VectoplanCreateUploads,
  definitions: !!window.VectoplanCreateDefinitionsRuntime,
  variantState: !!window.VectoplanCreateVariantState,
  profiles: !!window.VectoplanCreateVariantProfiles,
  payload: !!window.VectoplanCreatePayload,
  actions: !!window.VectoplanCreateActions,
  create: !!window.VectoplanCreate
})
```

### 44.3 Actions

```javascript
window.VectoplanCreateActions.diagnoseBindings()
window.VectoplanCreateActions.getState()
```

### 44.4 Payload

```javascript
window.VectoplanCreatePayload.collectPayload()
window.VectoplanCreatePayload.getState()
```

### 44.5 Profiles

```javascript
window.VectoplanCreateVariantProfiles.getState()
```

### 44.6 Download direkt

```javascript
await window.VectoplanCreateActions.runAction("download")
```

### 44.7 Save direkt

```javascript
await window.VectoplanCreateActions.runAction("save")
```

Danach beachten:

```text
Save-Erfolg derzeit = Source-Save
Published-Sichtbarkeit erst nach POST /library/sync
```

### 44.8 Binding-Repair

```javascript
window.VectoplanCreateActions.repairBindings()
window.VectoplanCreateActions.verifyBindings()
```

---

## 45. Kurzfazit

`static/js/vplib/create` ist eine modularisierte Browser-Orchestrierung für den VPLIB-Create-Wizard. Der Ordner verwaltet UI-State, Profile, Varianten, Payloads, Upload-Metadaten und Backend-Actions, baut aber selbst keine VPLIB-Packages und schreibt nicht in PostgreSQL. Der Downloadpfad ist inzwischen gegen fehlerhafte Button-Bindungen, doppelte Listener und zu frühes Object-URL-Cleanup gehärtet. Der verbleibende wichtigste Systembruch liegt nicht mehr in der Klick- oder Download-Runtime, sondern zwischen erfolgreichem Source-Save und dem noch separat auszuführenden Published-DB-Sync.
