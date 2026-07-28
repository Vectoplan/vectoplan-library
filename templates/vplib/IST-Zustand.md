# IST-Zustand · `services/vectoplan-library/templates/vplib`

Stand: **2026-07-10**  
Letzte Aktualisierung: **2026-07-10**  
Scope: Template-Struktur unter `services/vectoplan-library/templates/vplib` plus direkt abhängige statische Create-Runtimes, Create-/Definitions-API-Verträge und die verifizierten Browser-Abläufe für Download und Source-Save.

---

## 1. Zielbild

Der Create-Wizard ist in kleine, wartbare Template- und Runtime-Bausteine getrennt. Die sichtbare UI bleibt schwarz, kompakt und editorartig. Die Templates liefern HTML, Datenattribute und JSON-Kontext. JavaScript-Runtimes übernehmen Navigation, Payload-Aufbau, Preview-Sync, Upload-Metadaten und Varianten-State.

Grundregeln im aktuellen Stand:

- Templates liegen unter `services/vectoplan-library/templates/vplib`.
- Kanonische statische Create-JS-Dateien liegen unter `services/vectoplan-library/static/js/vplib/create`.
- Zentrales CSS liegt unter `services/vectoplan-library/static/css/vplib/create.css`.
- Step 3 heißt sichtbar **Variablen**, nutzt technisch aber weiter den Backend-Vertrag `object` / `object-variants`.
- Browser erzeugt keine `.vplib`-Pakete.
- Die Create-Runtime sammelt Uploads weiterhin primär als Metadaten. Der Kontext kann einen Backend-Uploadpfad ausweisen, die direkte Verarbeitung von `request.files` im Create-Save-/Download-Payload ist jedoch noch nicht vollständig als End-to-End-Flow verifiziert.
- Preview rechts ist bewusst ein roter Entwicklungsplatzhalter.
- Sichtbare HTML-Felder in Sections sind direkt geschrieben, nicht über lange Macro-Aufrufe.

---

## 2. Ordnerstruktur

```text
services/vectoplan-library/templates/vplib/
├── IST-Zustand.md
├── create.html
└── create/
    ├── _context_json.html
    ├── _macros.html
    ├── _preview_placeholder.html
    ├── _stepper.html
    ├── _wizard_nav.html
    ├── sections/
    │   ├── _actions.html
    │   ├── _geometry.html
    │   ├── _identity.html
    │   ├── _taxonomy.html
    │   ├── _technical.html
    │   └── _variables.html
    └── variants/
        ├── _variant_drawer_empty_state.html
        ├── _variant_drawer_shell.html
        ├── _variant_table.html
        └── _variant_workspace.html
```

Externe, aber direkt gekoppelte Dateien:

```text
services/vectoplan-library/static/css/vplib/
└── create.css

services/vectoplan-library/static/js/vplib/create/
├── create.js
├── create_actions.js
├── create_core.js
├── create_dynamic_rows_legacy.js
├── create_payload.js
├── create_preview.js
├── create_theme.js
├── create_uploads.js
├── create_variant_profiles.js
├── create_variant_state.js
└── create_variant_utils.js
```

Zusätzliche Variant-Runtimes, die im aktuellen Haupttemplate explizit geladen werden:

```text
services/vectoplan-library/static/js/vplib/create/
├── create_definitions.js
├── create_variant_drawer.js
├── create_variant_field_renderer.js
├── create_variant_optional_fields.js
├── create_variant_summary.js
├── create_variant_table.js
└── create_variant_validation.js
```

---

## 3. Top-Level-Template

### `create.html`

Einstiegspunkt für den Wizard.

Aufgaben:

- definiert Shell, Form, Workspace und Preview-Spalte
- bindet zentrales CSS `css/vplib/create.css`
- trägt Template-Version `1.0.0` und Asset-Version `20260710.3`
- importiert `vplib/create/_macros.html`
- lädt Kontext, Stepper, Sections, Preview und Footer-Navigation
- lädt 19 Create-JS-Runtimes in definierter Reihenfolge über `static/js/vplib/create`
- hält `enctype="multipart/form-data"` für Upload-Kompatibilität bereit
- registriert bereits im `<head>` eine frühe Shell-Action-Bridge vor allen defer-Skripten
- stellt Script-Load-Diagnosen über DOM-Attribute und `window.vpCreateGetScriptLoadState()` bereit
- nutzt neue Templatepfade unter `vplib/create/...`

Wichtig:

- `create.html` ist nur UI-Orchestrierung.
- Payload- und Package-Erzeugung liegen nicht in diesem Template.
- Backend-Routen bleiben über `/api/v1/vplib/create/*` angebunden.
- `_actions.html` wird ausdrücklich `with context` innerhalb des Formulars eingebunden.
- `_context_json.html` wird nach dem Formular gerendert und initialisiert die globalen Runtime-Kontexte vor Ausführung der defer-Skripte.

---

## 4. Gemeinsame Partials

### `create/_context_json.html`

Liefert JSON-Kontext für Frontend-Runtimes.

Enthält:

- Wizard-Step-Konfiguration
- Step 3 sichtbar als `Variablen`
- API-Routen
- Definitions-Kontext
- Upload-Konfiguration
- globale Window-Objekte wie `VectoplanCreateContext`, `VectoplanCreateDefinitions`, `VectoplanCreateDefinitionCatalogs`, `VectoplanCreateDefinitionMaps`, `VectoplanCreateDefinitionsOptions`, `VectoplanCreateUploadConfig`, `VectoplanCreateRoutes` und `VectoplanCreatePayloadContract`

Relevante Upload-Metadatenfelder:

- `geometry_model_uploads_json`
- `technical_document_uploads_json`
- `variant_document_uploads_json`

### `create/_stepper.html`

Rendert den oberen Stepper.

Aktuelle Step-Logik:

```text
1 Grunddaten     → identity
2 Taxonomie      → taxonomy
3 Variablen      → object / object-variants
4 Geometrie      → geometry
5 Technik        → technical
6 Erzeugen       → actions
```

Wichtig:

- Step 3 bleibt technisch `object`, wird aber sichtbar als `Variablen` geführt.
- Stepper setzt Data-Attribute für Wizard-Runtime und CSS-State.
- Keine Business-Logik im Template.

### `create/_wizard_nav.html`

Footer-Navigation für Zurück/Weiter.

Aufgaben:

- zeigt aktuellen Schritt
- stellt Zurück/Weiter-Buttons
- wird durch `create_wizard.js` gesteuert
- darf keine eigene Sprunglogik enthalten

### `create/_preview_placeholder.html`

Rechte Preview-Fläche.

Aktueller Zustand:

- roter leerer Dev-Platzhalter
- keine sichtbaren Statuskopien
- keine Metriken
- keine Preview-Texte
- alte Hooks bleiben erhalten

### `create/_macros.html`

Legacy-kompatible Makro-Sammlung.

Aktuelle Rolle:

- bleibt für Kompatibilität verfügbar
- neue Sections sollen sichtbare Felder bevorzugt direkt als HTML schreiben
- keine neuen langen positional Macro-Aufrufe in Sections

---

## 5. Section-Partials

### `create/sections/_identity.html`

Step 1: Grunddaten.

Felder:

- `family_name`
- `family_description`

Aufgaben:

- sichtbarer Name und Beschreibung
- Slug-/ID-Vorschau
- einfache Validierung
- Event-Sync für `identity-ready`, `identity-changed`, `identity-validity-changed`

Layout-Ziel:

- ohne Scrollen auf normalen Desktop-Höhen
- sehr kompakt

### `create/sections/_taxonomy.html`

Step 2: Taxonomie.

Felder:

- `domain`
- `category`
- `subcategory`

Aufgaben:

- Taxonomie-Auswahl
- abhängige Filterung
- Pfad-Sync
- Defaults: `hochbau`, `bloecke`, `basis`

Layout-Ziel:

- ohne Scrollen auf normalen Desktop-Höhen
- direkte HTML-Felder, keine langen Macro-Aufrufe

### `create/sections/_variables.html`

Step 3: Variablen.

Sichtbar:

- Variablen
- Variablen-Varianten
- Unterlagen ausschließlich innerhalb der jeweiligen Variablen-Variante

Der frühere globale Unterlagen-Block in Step 3 ist entfernt. Damit gibt es dort
keine losgelöste Dateiauswahl ohne Variantenbezug mehr.

Technisch bleibt erhalten:

- `data-create-section="object-variants"`
- `data-vp-create-section="object-variants"`
- `data-vp-create-section-alias="variables"`
- hidden `object_kind`
- hidden `family_profile_id`
- hidden `variant_profile_id`
- `definition_variants_json`
- `default_variant_id`
- `variants[...]`

Wichtig:

- sichtbares Wort „Objekt“ vermeiden
- Backend-Vertrag nicht brechen
- Variant-Workspace ist der fachliche Editor

### `create/sections/_geometry.html`

Step 4: Geometrie.

Felder:

- sichtbare Typ-Auswahl ohne `name`
- hidden/synchronisiertes `object_kind`
- `primitive_shape`
- `geometry_unit`
- `geometry_width`
- `geometry_height`
- `geometry_depth`
- `editor_cells_x`
- `editor_cells_y`
- `editor_cells_z`
- optional `geometry_model_files`
- `geometry_model_uploads_json`
- optional `texture_files`
- `texture_uploads_json`

Aktueller Layout-Stand:

- oben eine dreispaltige, saubere Auswahlzeile:
  - Typ
  - Form
  - Einheit
- darunter kompakter 3D-Modell-Strip
- danach „Sichtbare Größe“
- danach „Editor-Raster“
- Upload ist optisch eigenständig und nicht mehr in „Sichtbare Größe“ verschachtelt

Objektart-Verhalten:

```text
Raster-Bauteil      → editor_cells_x/y/z gesperrt auf 1
Mehrblock-Modul     → editor_cells_x/y/z frei editierbar
Katalogelement      → editor_cells_x/y/z frei editierbar
Adaptives System    → editor_cells_x/y/z gesperrt auf 1
```

Wichtig:

- Die sichtbare Typ-Auswahl schreibt nicht direkt `name="object_kind"`, damit kein doppeltes FormData entsteht.
- Das JS synchronisiert den Wert in das bestehende hidden field `object_kind`.
- Bei Typänderung wird Profilauflösung erneut angefragt.
- 3D-Dateien und Texturen werden als echte Binärdaten übertragen und unter
  `assets/models/` beziehungsweise `assets/textures/` in `.vplib` eingebettet.

### `create/sections/_technical.html`

Step 5: Technik.

Felder:

- `material_class`
- `variables[i][key]`
- `variables[i][value]`
- `variables[i][unit]`
- `variables[i][description]`
- `technical_document_files`
- `technical_document_uploads_json`

Aufgaben:

- technische Kennwerte
- Materialklasse
- optionale technische Unterlagen als lokale Metadaten
- Legacy-Variablenzeilen bleiben kompatibel

### `create/sections/_actions.html`

Step 6: Erzeugen.

Aktionen:

- `draft`
- `validate`
- `package-plan`
- `download`
- `save`

Backend-Routen:

```text
/api/v1/vplib/create/draft
/api/v1/vplib/create/validate
/api/v1/vplib/create/package-plan
/api/v1/vplib/create/download
/api/v1/vplib/create/save
```

Wichtig:

- keine Browser-VPLIB-Erzeugung
- Download kommt als Backend-Blob
- Save bleibt Backend-gesteuert und schreibt aktuell zunächst nur in den Source-Bereich
- Save synchronisiert im aktuellen Stand noch nicht automatisch in die Published-DB
- sieben Actions stehen vertikal: Draft, Validate, Package-Plan, Download, Persistent Draft, Publish-Prepare und Save
- jeder Button besitzt `data-create-action`, `data-vp-action-button`, eine normalisierte Route und einen direkten `onclick`-Fallback
- Result-Anzeige nur sichtbar, wenn es ein verwertbares Ergebnis gibt

---

## 6. Variant-Partials

### `create/variants/_variant_workspace.html`

Container für Variantenliste und Drawer.

Aufgaben:

- hält Hidden-Felder:
  - `definition_variants_json`
  - `definition_variants_state_version`
  - `definition_variants_default_variant_id`
  - `default_variant_id`
- bindet Table und Drawer
- setzt Runtime-Hooks für `VectoplanCreateVariantWorkspace`

### `create/variants/_variant_table.html`

Kompakte Variantenliste.

Aufgaben:

- Anzeige vorhandener Varianten
- Bearbeiten-Button
- Default/Fix-Status
- Hidden-Row-Felder für Legacy- und Payload-Kompatibilität
- scrollbarer Body bei vielen Varianten

### `create/variants/_variant_drawer_shell.html`

Editor-Shell für Varianten.

Aufgaben:

- Variante anlegen oder bearbeiten
- Definition-managed Felder aufnehmen
- optionale Felder verwalten
- `document_list`-Felder mit späterem Upload-UI vorbereiten
- Profil- und State-Hooks bereitstellen

Sichtbare Sprache:

- „Variable“
- „Variablen“
- kein sichtbares „Objekt“

### `create/variants/_variant_drawer_empty_state.html`

Fallback, wenn Definitionsdaten oder Profile fehlen.

Aufgaben:

- kompakter leerer Zustand
- Retry-/Diagnose-Hooks
- kein harter UI-Abbruch

---

## 7. Statische Runtimes

### `create_core.js`

Zentrale Basis.

Aufgaben:

- Selektoren
- Klassen
- State
- Context
- Logging
- Locks
- Events
- DOM-Helfer
- JSON-Helfer
- API-Route-Defaults

### `create_theme.js`

Theme-Schicht.

Aufgaben:

- dark/light/system API
- Black-/Dark-First Default
- stabile Theme-Hooks
- lokale Speicherung
- `black` wird als `dark` normalisiert

### `create_wizard.js`

Wizard-Navigation.

Aufgaben:

- Weiter
- Zurück
- Stepper-Klick
- Submit-Fallback
- aktives Panel
- Stepper-Status
- Footer-Status

Regeln:

- vorwärts nur ein Schritt
- rückwärts frei
- keine Sprünge 2 → 4
- keine automatische Profilnavigation
- Overlay/Drawer blockiert Keyboard-Navigation

### `create_preview.js`

Preview- und Kontext-Sync.

Aufgaben:

- Taxonomie-Pfad
- Geometrie-Summaries
- Objektart-/Rasterregeln
- Variant-Workspace-Kontext
- rechte Preview bewusst leer halten

Wichtig:

- keine Navigation
- keine VPLIB-Erzeugung
- keine echten Dateioperationen

### `create_dynamic_rows_legacy.js`

Legacy-Brücke.

Aufgaben:

- alte Varianten- und Kennwert-Zeilen weiter lauffähig halten
- neue definition-managed Variantenanlage an Drawer/State delegieren
- keine Kollision mit neuer Variant-Runtime

### `create_uploads.js`

Upload-Metadatenadapter.

Aufgaben:

- lokale File-Metadaten sammeln
- Hidden JSON-Felder schreiben
- Dateilisten rendern
- keine Dateiübertragung
- keine Objekt-URLs
- keine Datei-Inhalte lesen

Fix-Stand:

- Event-Schleife mit Payload-Runtime unterbunden
- `syncAll()` läuft standardmäßig still
- Upload-Events nur bei echter Nutzeränderung oder explizitem Event-Wunsch

### `create_payload.js`

Payload-Runtime.

Aufgaben:

- FormData einsammeln
- Variant-State in `definition_variants_json` spiegeln
- Upload-Metadaten in Payload einhängen
- Defaultwerte normalisieren
- Profil-IDs synchronisieren
- Backend-kompatiblen Payload erzeugen

Fix-Stand:

- Upload-Reentrancy mit `create_uploads.js` unterbunden
- Upload-Events lösen keinen erneuten Upload-Runtime-syncAll aus
- `payload-uploads-synced` nur bei geänderter Signatur

### `create_actions.js`

Action-Runtime. Aktuelle Version: **0.9.0**.

Aufgaben:

- Draft
- Validate
- Package Plan
- Download
- Save
- Resultanzeige
- Action-Locks
- delegierter Capture-Listener
- direkte Button-Fallback-Listener
- automatische Nachbindung dynamisch ersetzter Buttons
- MutationObserver und Binding-Diagnosen
- Event-Deduplizierung über `__vpCreateActionsHandled`
- verzögertes Widerrufen von Download-Object-URLs

Wichtig:

- nutzt Payload-Runtime
- Download nur Backend-Blob
- keine Browser-Package-Erzeugung
- Download führt vor dem Blob-Request automatisch Validate und Package-Plan als Preflight aus
- Save zeigt eine Bestätigung, prüft das Write-Flag und sendet anschließend `POST /api/v1/vplib/create/save`

### `create_variant_utils.js`

Hilfsschicht für Varianten.

Aufgaben:

- DOM-Helfer
- Event-Helfer
- JSON
- Slugs / IDs
- Definitions-Mapping
- Variant-Normalisierung
- Werttyp-Normalisierung
- `document`, `documents`, `document_list`

### `create_variant_state.js`

Browser-Wahrheit für Varianten.

Aufgaben:

- `state.variants`
- `definition_variants_json`
- Default Variant ID
- Variant Count
- Events für Table, Drawer, Payload und Validation

Wichtig:

- DOM ist nicht fachliche Wahrheit
- Tabellenzeilen sind Anzeige-/Kompatibilitätsspiegel
- Sync läuft still und idempotent

### `create_variant_profiles.js`

Profile-/Definitions-Schicht.

Aufgaben:

- lokale Definitionsdaten lesen
- Backend-Definitions-APIs kapseln
- Family Profile resolve
- Variant Profile resolve
- Empty Variant Values resolve
- Profil-IDs in Workspace, Drawer und Hidden-Felder schreiben
- VariantState-Kontext ohne native Events aktualisieren

Backend-Routen:

```text
/api/v1/vplib/definitions/options
/api/v1/vplib/definitions/payload
/api/v1/vplib/definitions/resolve-family-profile
/api/v1/vplib/definitions/resolve-variant-profile
/api/v1/vplib/definitions/variant-profiles/<profile_id>
/api/v1/vplib/definitions/empty-variant-values/<profile_id>
```

---

## 8. Layout- und Scroll-Regeln

Der Wizard verwendet eine feste Desktop-Shell:

```text
shell
├── stepper
└── form
    ├── workspace
    │   ├── main/steps
    │   └── aside/preview
    └── wizard_nav
```

Wichtige CSS-Regel:

- `body` und große Shell-Eltern dürfen Desktop-seitig `overflow: hidden` nutzen.
- Scroll muss innerhalb der aktiven Step-Body-Fläche stattfinden.
- Daher brauchen alle Eltern in der Kette `min-height: 0`.
- Scrollbare Targets:
  - `.vplib-create-step__body`
  - `.vp-create-variant-table__body`
  - `.vp-create-variant-drawer__sections`
  - optionale Listen im Drawer

Aktuelle Problemklasse, die vermieden werden muss:

```text
Parent overflow:hidden + Child ohne belastbare Höhe
→ Inhalt wird abgeschnitten
→ keine sichtbare Scrollleiste
```

---

## 9. Backend-Verträge

### Create API

```text
/api/v1/vplib/create/health
/api/v1/vplib/create/options
/api/v1/vplib/create/draft
/api/v1/vplib/create/validate
/api/v1/vplib/create/package-plan
/api/v1/vplib/create/download
/api/v1/vplib/create/save
```

### Definitions API

```text
/api/v1/vplib/definitions/options
/api/v1/vplib/definitions/payload
/api/v1/vplib/definitions/resolve-family-profile
/api/v1/vplib/definitions/resolve-variant-profile
/api/v1/vplib/definitions/variant-profiles/<profile_id>
/api/v1/vplib/definitions/empty-variant-values/<profile_id>
```

### Stable Payload Fields

Identity:

```text
family_name
family_description
```

Taxonomy:

```text
domain
category
subcategory
```

Variables / Variants:

```text
object_kind
family_profile_id
variant_profile_id
definition_variants_json
default_variant_id
variants[...]
```

Geometry:

```text
primitive_shape
geometry_width
geometry_height
geometry_depth
geometry_unit
editor_cells_x
editor_cells_y
editor_cells_z
geometry_model_uploads_json
```

Technical:

```text
material_class
variables[i][key]
variables[i][value]
variables[i][unit]
variables[i][description]
technical_document_uploads_json
```

---

## 10. Aktuelle offene Punkte

1. `create.py` bleibt HTTP-Adapter; Package-Erzeugung, Download und Source-Save werden an Route-/Create-Services delegiert.
2. Echte `request.files` werden validiert, gehasht und den Package-Assets beziehungsweise Varianten-Dokumenten zugeordnet.
3. Der aktuelle Create-Endpunkt rendert `vplib/create.html`; alte `library_admin/create.html`-Referenzen gelten nur noch als Legacy-/Migrationshinweis.
4. Die folgenden Variant-Runtimes werden inzwischen explizit geladen und müssen als zusammenhängender Runtime-Vertrag gepflegt werden:
   - Summary
   - Field Renderer
   - Optional Fields
   - Validation
   - Drawer
   - Table
   - Definitions Runtime
5. Preview bleibt bis zur echten 3D-Integration bewusst roter Dev-Platzhalter.
6. Varianten-Unterlagen werden im Variant-Drawer erfasst und als echte Dateien im Package gespeichert; der globale Unterlagen-Block in Step 3 existiert nicht mehr.
7. Step 4 besitzt getrennte Uploads für 3D-Modelle und Texturen. Die Feldnamen und Asset-Zielpfade sind ein stabiler Vertrag.
8. `POST /api/v1/vplib/create/save` schreibt standardmäßig in den Source-Bereich und fordert anschließend automatisch den Library-Sync an.
9. Der Save-Response enthält das Sync-Ergebnis; bei erfolgreichem DB-Sync steht das neue oder aktualisierte Package unmittelbar im veröffentlichten Read-Model bereit.
10. Die drei Action-Bindungsebenen sind absichtlich redundant; Änderungen müssen den gemeinsamen Event-Marker respektieren, damit keine Aktion doppelt läuft.

---

## 11. Wartungsregeln

Bei Änderungen an Templates:

- Pfadkommentar in der ersten Zeile beibehalten.
- Keine langen `render_field(...)` / `render_select(...)` Macro-Aufrufe in neuen Section-Templates.
- Sichtbare Sprache in Step 3 bleibt „Variablen“.
- Technische Objektlogik darf existieren, soll aber nicht sichtbar als „Objekt“ dominieren.
- Backend-Feldnamen nicht ohne Backend-Abgleich ändern.
- Upload-Feldnamen, erlaubte Endungen und Package-Zielpfade immer gemeinsam in UI, Route und Create-Service pflegen.
- Scroll-Fixes bevorzugt zentral in `static/css/vplib/create.css` lösen.
- JS-Runtimes defensiv schreiben und Reentrancy vermeiden.
- Event-Namen stabil halten.
- FormData-Duplikate vermeiden, besonders bei `object_kind`.

---

## 12. Kurzdiagnose aktueller Aufbau

Der Template-Stand ist sauber modularisiert. Die Hauptarbeit liegt nun nicht mehr in HTML-Fragmente zerlegen, sondern in der Stabilisierung der Runtime-Kopplung:

- Stepper/Wizard
- Payload
- Upload-Metadaten
- Variant-State
- Variant-Profile
- Scroll- und Layoutkette
- spätere Backend-Dateiverarbeitung

Die kritischsten Verträge sind `object_kind`, `definition_variants_json`, `default_variant_id` und die Create-/Definitions-API-Routen.

---

## 13. Verifizierter Stand vom 10. Juli 2026

Die Create-Oberfläche wurde im Browser und zusätzlich in isolierten Runtime-Simulationen geprüft. Der aktuelle Stand unterscheidet klar zwischen geladenem UI-Kontext, physischem Button-Klick, Backend-Package-Erzeugung und Published-DB-Synchronisation.

### 13.1 Verifiziert funktionierende Bereiche

```text
GET /create
  -> Template rendert vollständig
  -> CSS wird geladen
  -> alle 19 Create-Runtimes werden geladen
  -> Context-Bootstrap wird ausgeführt
  -> Definitionen werden aufgelöst

Download-Button
  -> physischer HTML-Klick
  -> VectoplanCreateActions.runAction("download")
  -> POST /create/validate
  -> POST /create/package-plan
  -> POST /create/download
  -> Blob wird als .vplib ausgelöst

Save-Button
  -> physischer HTML-Klick
  -> Write-Flag prüfen
  -> Bestätigung anzeigen
  -> POST /create/save
  -> Source-Package wird geschrieben
```

### 13.2 Im Runtime-Log beobachtete erfolgreiche Requests

```text
GET  /api/v1/vplib/definitions/options
GET  /api/v1/vplib/definitions/resolve-family-profile
GET  /api/v1/vplib/definitions/resolve-variant-profile
GET  /api/v1/vplib/definitions/empty-variant-values/simple_cell_block.v1
GET  /api/v1/vplib/definitions/variant-profiles/simple_cell_block.v1?resolved=1

POST /api/v1/vplib/create/validate
POST /api/v1/vplib/create/package-plan
POST /api/v1/vplib/create/download
POST /api/v1/vplib/create/drafts
POST /api/v1/vplib/create/save
```

Die genannten Requests antworteten im beobachteten Test mit HTTP 200.

### 13.3 Noch nicht automatisch gekoppelt

```text
POST /api/v1/vplib/create/save
  -> Source-Save
  -> kein automatischer DB-Sync

POST /api/v1/vplib/library/sync
  -> muss derzeit separat als POST ausgeführt werden
  -> schreibt Published State nach PostgreSQL
```

Ein Aufruf von `/api/v1/vplib/library/sync` durch direktes Öffnen im Browser verwendet GET und erhält deshalb korrekt HTTP 405. Das ist kein fehlender Endpunkt, sondern eine falsche HTTP-Methode.

---

## 14. Kanonische aktuelle Struktur

Die aktuelle produktive Struktur lautet:

```text
services/vectoplan-library/templates/vplib/
├── create.html
└── create/
    ├── _context_json.html
    ├── _macros.html
    ├── _preview_placeholder.html
    ├── _stepper.html
    ├── _wizard_nav.html
    ├── sections/
    │   ├── _actions.html
    │   ├── _geometry.html
    │   ├── _identity.html
    │   ├── _taxonomy.html
    │   ├── _technical.html
    │   └── _variables.html
    └── variants/
        ├── _variant_drawer_empty_state.html
        ├── _variant_drawer_shell.html
        ├── _variant_table.html
        └── _variant_workspace.html

services/vectoplan-library/static/css/vplib/
└── create.css

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
└── create.js
```

`static/library_admin/js` ist für diesen Wizard nicht mehr der kanonische Pfad.

---

## 15. `create.html` im aktuellen Stand

### 15.1 Versionsvertrag

```text
Template-Version: 1.0.0
Asset-Version:    20260710.3
CSS-Modus:        single-file
Theme:            dark / black
Variant Runtime:  definition-managed
```

Die Asset-Version wird als Query-Parameter an alle JavaScript-URLs angehängt. Dadurch lassen sich veraltete Browser-, Reverse-Proxy- oder Service-Worker-Caches gezielt umgehen.

### 15.2 Früher Shell-Bootstrap

Noch im `<head>` setzt das Template:

```text
data-theme="dark"
data-vp-create-theme="dark"
data-vp-create-shell="wizard"
data-vp-create-style="black"
data-vp-create-template-root="vplib"
data-vp-create-template-version="1.0.0"
data-vp-create-css-mode="single-file"
data-vp-create-variant-runtime="definition-managed"
```

Zusätzlich wird erkannt, ob die Seite in einem Frame eingebettet ist. Das Ergebnis wird als `data-vp-create-embedded` am Root abgelegt.

### 15.3 Frühe Shell-Action-Bridge

Das Haupttemplate registriert vor allen defer-Skripten:

```text
window.VectoplanCreateShellActionBridge
```

Eigenschaften:

```text
- Capture-Listener auf Dokumentebene
- erkennt ausschließlich Buttons innerhalb des Create-Formulars
- wartet maximal 12 Sekunden auf die Actions-Runtime
- ruft die öffentliche Runtime-API auf
- markiert das Event gegen Doppelverarbeitung
- führt selbst keine Payload-, Fetch- oder Download-Logik aus
- protokolliert Click-, Wait-, Duplicate- und Error-Zähler
```

### 15.4 Formular- und Partial-Reihenfolge

```text
create shell
  -> form
     -> stepper
     -> identity
     -> taxonomy
     -> variables/object-variants
     -> geometry
     -> technical
     -> actions with context
     -> preview
     -> wizard navigation
  -> context JSON partial
  -> script loader bootstrap
  -> 19 defer scripts
```

`_actions.html` liegt innerhalb des Formulars. `_context_json.html` liegt nach dem Formular, aber vor den defer-Runtimes.

### 15.5 Step-3-Fallback

Das Haupttemplate unterstützt:

```jinja
{% include [
  "vplib/create/sections/_variables.html",
  "vplib/create/sections/_object_variants.html"
] ignore missing with context %}
```

Damit bleibt ein älterer Partialname als Fallback möglich, ohne den sichtbaren Schritt „Variablen“ wieder umzubenennen.

---

## 16. Action-Bindungsarchitektur

Die Action-Buttons besitzen inzwischen drei bewusst getrennte Bindungsebenen.

### 16.1 Ebene 1: Shell-Bridge in `create.html`

```text
Global: VectoplanCreateShellActionBridge
Wartezeit: 12.000 ms
Listener: document capture
```

Diese Ebene existiert bereits, bevor `create_actions.js` geladen wurde.

### 16.2 Ebene 2: Template-Bridge in `_actions.html`

```text
Global:  VectoplanCreateActionsTemplateBridge
Handler: window.vpRunCreateAction
Wartezeit: 10.000 ms
```

Jeder Button enthält zusätzlich:

```html
onclick="return window.vpRunCreateAction ? window.vpRunCreateAction(event, this) : false;"
```

Die Template-Bridge sucht bevorzugt:

```text
window.VectoplanCreateActions.runAction(action, form, button)
```

und verwendet als Kompatibilitätsfallback:

```text
window.VectoplanCreate.runAction(action)
```

### 16.3 Ebene 3: Runtime-Bindung in `create_actions.js`

Aktuelle Version:

```text
0.9.0
```

Die Runtime besitzt:

```text
- delegierten Dokument-Listener
- direkte Listener pro Button
- zentrale Binding Registry
- Binding-Verifikation
- MutationObserver
- Nachbindung dynamisch eingefügter oder ersetzter Buttons
- Reparatur veralteter Binding-Marker
- Action-Lock
- Pending-Schutz
- Diagnosezustand in getState()
```

### 16.4 Gemeinsamer Deduplizierungsvertrag

Alle drei Ebenen verwenden denselben Event-Schlüssel:

```text
__vpCreateActionsHandled
```

Regel:

```text
Das erste zuständige Binding markiert das Event.
Jede weitere Ebene erkennt die Markierung und startet keine zweite Aktion.
```

Diese Redundanz ist absichtlich vorhanden. Sie schützt gegen:

```text
- stale core.bindOnce()-Marker
- DOM-Ersatz nach Initialisierung
- verspätete defer-Runtime
- teilweise geladene Scripts
- Browser-/Proxy-Cache mit gemischten Versionen
```

### 16.5 Historisches Fehlerbild

Vor der Template-Bridge galt:

```text
VectoplanCreateActions.runAction("download") funktioniert direkt,
aber physischer Button-Klick startet keinen Request.
```

Ursache war nicht der Backendpfad, sondern eine fehlerhaft gemeldete Listener-Bindung. `bindingDone=true` konnte gesetzt sein, obwohl der eigentliche Callback durch einen alten Core-Bindeschlüssel nicht erneut ausgeführt wurde.

Der aktuelle Stand setzt `bindingDone` erst nach verifizierter Registrierung und verlässt sich nicht mehr ausschließlich auf `core.bindOnce()`.

---

## 17. `_actions.html` im aktuellen Stand

### 17.1 Version und Aufgabe

```text
Template-Version: 1.0.0
Komponente:       create.actions
```

Das Partial stellt UI und Bindungshooks bereit. Payload-Aufbau, HTTP-Requests, Blob-Prüfung und Statusauswertung bleiben in `create_actions.js`.

### 17.2 Verfügbare Actions

```text
draft
validate
package-plan
download
persist-draft
publish-prepare
save
```

### 17.3 Routen

```text
draft           -> /api/v1/vplib/create/draft
validate        -> /api/v1/vplib/create/validate
package-plan    -> /api/v1/vplib/create/package-plan
download        -> /api/v1/vplib/create/download
persist-draft   -> /api/v1/vplib/create/drafts
publish-prepare -> /api/v1/vplib/create/publish-bundle
save            -> /api/v1/vplib/create/save
```

### 17.4 Save-Button

Der Save-Button trägt:

```text
data-create-requires-write="true"
data-create-action="save"
data-vp-action-kind="save"
```

Er ist deaktiviert, wenn der Templatekontext keinen aktiven Schreibmodus meldet.

Der Buttontext „In Library speichern“ bedeutet im derzeitigen Backendvertrag:

```text
Package in src/library/source speichern
```

Er bedeutet noch nicht automatisch:

```text
Package in PostgreSQL Published State synchronisieren
```

### 17.5 Action-Konfigurationsblock

Das Partial rendert einen eigenen `application/json`-Block mit:

```text
apiPrefix
writeEnabled
healthOk
definitionsReady
generatorContextReady
payloadContractReady
htmlBridge
sourceRoot
routes
actions
events
```

Damit kann die Runtime ihre Umgebung prüfen, ohne Jinja-Werte aus sichtbarem HTML erraten zu müssen.

---

## 18. `_context_json.html` im aktuellen Stand

### 18.1 Version

```text
Template-Version: 1.0.0
Schema:           create_context_template.v1
```

### 18.2 Neun stabile JSON-Script-Blöcke

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

### 18.3 Öffentliche Globals

Nach dem Bootstrap existieren:

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

### 18.4 Routen-Normalisierung

Der Bootstrap akzeptiert bei Backendantworten nicht nur Strings, sondern defensiv auch Route-Deskriptoren mit Feldern wie:

```text
url
href
path
endpoint
route
```

Das Ergebnis wird immer als sicherer lokaler URL-String normalisiert.

Explizit verhindert wird:

```text
/[object Object]
```

Externe oder offensichtlich unsichere URL-Kandidaten werden nicht als Create-Route übernommen.

### 18.5 Create-Route-Defaults

```text
index
health
routes
selftest
options
context
create_context
definitions_current
draft
persistent_draft
validate
package_plan
publish_bundle
download
save
cache_clear
```

### 18.6 Definitions-Route-Defaults

```text
index
health
summary
options
payload
variant_profiles
variant_profile_base
resolve_family_profile
resolve_variant_profile
empty_variant_values
empty_variant_values_base
validate_variant
cache_clear
selftest
```

### 18.7 Dataset-spezifische Maps

Definitionen werden getrennt indiziert:

```text
objectKindsById
familyProfilesById
variantProfilesById
variablesByKey
unitsById
materialsById
documentTypesById
profileBindingsById
```

Jeder Dataset-Typ besitzt eigene Schlüsselfelder. Dadurch werden Fremdschlüssel oder gleichnamige Felder eines anderen Definitionstyps nicht als falscher Primärschlüssel verwendet.

### 18.8 Deduplizierung

Definitionen können gleichzeitig aus folgenden Quellen stammen:

```text
Generator Context
Create Options
Definition Catalog
Definition Options
DB-backed Definition Service
JSON-/Registry-Fallback
```

Der Context-Bootstrap dedupliziert semantisch pro Dataset. DB-backed beziehungsweise bereits normalisierte Records erhalten Vorrang vor schwächeren Fallbackformen.

---

## 19. Startervertrag

Der Create-Kontext stellt einen stabilen Minimalvertrag bereit:

```text
object_kind:        cell_block
family_profile_id:  simple_cell_block
variant_profile_id: simple_cell_block.v1
default_variant_id: default
```

### 19.1 Zweck

Der Startervertrag verhindert, dass ein leerer oder nur teilweise verfügbarer Definitionskontext die komplette Create-Runtime unbrauchbar macht.

### 19.2 Auflösung

Im verifizierten Browserablauf wurden erfolgreich aufgerufen:

```text
resolve-family-profile
resolve-variant-profile
variant-profiles/simple_cell_block.v1?resolved=1
empty-variant-values/simple_cell_block.v1
```

### 19.3 IDs im Kontext

Der Bootstrap führt sowohl snake_case als auch camelCase:

```text
object_kind / objectKind
family_profile_id / familyProfileId
variant_profile_id / variantProfileId
default_variant_id / defaultVariantId
vplib_uid / vplibUid
context_uid / contextUid
```

### 19.4 Regel

Die Template-Schicht erzeugt keine eigenständige fachliche Profilentscheidung. Sie übernimmt Backendwerte und verwendet den Startervertrag nur als defensiven Fallback.

---

## 20. Script-Reihenfolge und Abhängigkeiten

Die Reihenfolge in `create.html` ist verbindlich:

```text
1.  create_core.js
2.  create_theme.js
3.  create_wizard.js
4.  create_preview.js
5.  create_dynamic_rows_legacy.js
6.  create_uploads.js
7.  create_definitions.js
8.  create_variant_utils.js
9.  create_variant_state.js
10. create_variant_profiles.js
11. create_variant_summary.js
12. create_variant_field_renderer.js
13. create_variant_optional_fields.js
14. create_variant_validation.js
15. create_variant_drawer.js
16. create_variant_table.js
17. create_payload.js
18. create_actions.js
19. create.js
```

### 20.1 Begründung

```text
Core zuerst
  -> gemeinsame State-/DOM-/Event-Grundlage

Definitions vor Profilauflösung
  -> lokale und Backend-Kataloge verfügbar

Variant Utils/State vor Profile/Renderer/Drawer/Table
  -> zentrale Variant-Wahrheit vorhanden

Payload nach allen Feld-/Variant-Runtimes
  -> vollständiger Formularzustand serialisierbar

Actions nach Payload
  -> Actions können stabil prepareActionPayload() verwenden

create.js zuletzt
  -> Orchestrator sieht alle Teilruntimes
```

### 20.2 Script-Load-Diagnose

Jedes Script besitzt:

```text
data-vp-create-script
data-vp-create-script-file
data-vp-create-script-base
data-vp-create-script-version
data-vp-create-template-version
onload
onerror
```

Der Loader schreibt Root-Attribute wie:

```text
data-vp-create-script-loaded-<key>="true"
data-vp-create-script-loaded-count
data-vp-create-script-error
data-vp-create-script-error-count
data-vp-create-script-error-last
```

Wenn `create_actions.js` geladen ist, wird die Shell-Bridge aktiv benachrichtigt.

---

## 21. `create_actions.js` – vollständiger Action-Vertrag

### 21.1 Version und Timeouts

```text
Version:                       0.9.0
Boot Retry:                    40 ms
Request Timeout:               60 s
Preflight Timeout:             45 s
Download Timeout:              120 s
Action Lock:                   120 s
Download URL Revoke Delay:     60 s
Mutation Rebind Delay:         40 ms
```

### 21.2 Action-Lock

Nur eine Action darf gleichzeitig laufen.

Schutzebenen:

```text
localState.pending
activeActionPromise
activeActionKey
Core Lock create-actions-run
Fallback Lock ohne Core
Button busy/disabled state
```

### 21.3 Payload-Vorbereitung

Vor jedem Request:

```text
Runtime Readiness prüfen
Form auflösen
Feldfehler leeren
Payload-Runtime aufrufen
Variant-State integrieren
Upload-Metadaten integrieren
Action-Metadaten ergänzen
Payload-Summary erzeugen
```

### 21.4 Direkte Actions

```text
draft           -> postJson("draft")
validate        -> postJson("validate")
package-plan    -> postJson("package-plan")
persist-draft   -> postJson("persist-draft")
publish-prepare -> postJson("publish-prepare")
```

### 21.5 Save

```text
writeEnabled prüfen
  -> deaktiviert: clientseitig blockieren
  -> aktiviert: Bestätigung anzeigen
     -> POST /create/save
```

Der Bestätigungstext weist ausdrücklich darauf hin, dass lokale Upload-Dateien im Payload als Metadaten vorkommen und Datei-Bytes über den Backend-Uploadpfad separat verarbeitet werden.

### 21.6 Download

Download ist ein dreistufiger Workflow:

```text
POST /create/validate
  -> nur bei Erfolg weiter

POST /create/package-plan
  -> nur bei Erfolg weiter

POST /create/download
  -> Blob lesen
  -> Content-Type prüfen
  -> Mindestgröße prüfen
  -> ZIP-Signatur/Archiv plausibilisieren
  -> Browserdownload auslösen
```

---

## 22. Download-Vertrag

### 22.1 Erfolgsantwort

Die Runtime erzeugt clientseitig ein Ergebnis mit:

```text
ok=true
ready=true
status=download_started
route=download
filename
size_bytes
content_type
archive_validation
preflight
_http_status
_request_id
headers
```

### 22.2 Was `download_started` bedeutet

`download_started` bedeutet:

```text
- Backendantwort war erfolgreich.
- Blob wurde gelesen.
- Archivprüfung war erfolgreich.
- Ein Browser-Download wurde ausgelöst.
```

Es bedeutet nicht, dass die Browseroberfläche den endgültigen Speicherort des Nutzers kennt.

### 22.3 Object-URL-Lebensdauer

Die Object-URL wird nicht mehr unmittelbar nach `0 ms` widerrufen. Die aktuelle Verzögerung beträgt 60 Sekunden. Damit haben Browser ausreichend Zeit, die Downloadquelle zu übernehmen.

### 22.4 Kein Source-Save

Der Downloadpfad schreibt kein Package nach `src/library/source`.

```text
Download = in-memory .vplib Archiv
Save     = Directory Package im Source-Root
```

---

## 23. Save-, Sync- und Published-Grenze

### 23.1 Aktueller Save

```text
POST /api/v1/vplib/create/save
  -> Package-Dokumente bauen
  -> Directory Package schreiben
  -> HTTP 200 bei Erfolg
```

### 23.2 Aktueller Sync

```text
POST /api/v1/vplib/library/sync
  -> Source scannen
  -> validieren und fingerprinten
  -> Published Rows in PostgreSQL schreiben
```

### 23.3 Published Read

```text
GET /api/v1/vplib/library/items
  -> liest published_db
  -> zeigt nur bereits synchronisierte Published Items
```

### 23.4 Konsequenz für die UI

Die sichtbare Save-Erfolgsmeldung darf derzeit nur behaupten:

```text
Source-Package wurde gespeichert.
```

Sie darf nicht ohne zusätzliche Backendbestätigung behaupten:

```text
Item wurde in PostgreSQL veröffentlicht.
```

### 23.5 Geplante, aber noch nicht umgesetzte Zielkopplung

```text
Save
  -> einzelnes Package scannen
  -> einzelnes Package synchronisieren
  -> Published Item verifizieren
```

Diese Automatisierung gehört in eine Backend-Orchestrierung. Das Frontend soll dafür nicht zwei voneinander unabhängige Requests verketten.

### 23.6 Manueller Recovery-Pfad

Bis zur Automatisierung:

```text
POST /api/v1/vplib/library/sync
```

Danach:

```text
GET /api/v1/vplib/library/items
```

---

## 24. Upload-Vertrag

### 24.1 Formularfelder

```text
geometry_model_files
technical_document_files
variant_document_files
```

Metadatenfelder:

```text
geometry_model_uploads_json
technical_document_uploads_json
variant_document_uploads_json
```

### 24.2 Frontend-Verhalten

`create_uploads.js`:

```text
- liest Dateiname, Größe, MIME-Type und Feldzuordnung
- schreibt JSON-Metadaten
- rendert lokale Listen
- liest keine Datei-Inhalte
- erzeugt keine Object-URLs
- überträgt nicht eigenständig
```

### 24.3 Context-Verhalten

Der Kontext kann Uploads als backend-enabled ausweisen und stellt File-Service-Routen bereit. Das bedeutet, dass eine Backend-Infrastruktur vorgesehen ist. Es bestätigt noch nicht automatisch, dass jede Create-Action die nativen File-Bytes aus `request.files` vollständig in das erzeugte Package integriert.

### 24.4 Wartungsregel

UI, Context und Backend müssen bei Änderungen gemeinsam geprüft werden:

```text
accept-Attribute
max size
allowed extensions
blocked extensions
MIME types
multiple flag
metadata field
purpose
File-Service route
Create-Payload integration
Package document/asset mapping
```

---

## 25. Öffentliche Events

### 25.1 Context

```text
vectoplan:create:context-ready
vectoplan:create:definitions-ready
vectoplan:create:definitions-unavailable
vectoplan:create:uploads-ready
```

### 25.2 Actions Template

```text
vectoplan:create:actions-template-ready
vectoplan:create:actions-template-state-changed
vectoplan:create:actions-result-changed
vectoplan:create:actions-result-copied
vectoplan:create:actions-result-cleared
```

### 25.3 Actions Runtime

```text
vectoplan:create:action-start
vectoplan:create:action-complete
vectoplan:create:action-error
```

### 25.4 Varianten und Wizard

Die bestehenden Variant-, Wizard-, Upload- und Preview-Events bleiben Teil des Runtime-Vertrags. Neue Events dürfen nicht bestehende Eventnamen still ersetzen.

---

## 26. Wichtige DOM-Diagnoseattribute

### 26.1 Shell

```text
data-vp-create-shell-ready
data-vp-create-template-version
data-vp-create-css-mode
data-vp-create-embedded
data-vp-create-script-loader-ready
```

### 26.2 Context

```text
data-vp-create-context-json-ready
data-vp-create-context-version
data-vp-create-definitions-ready
data-vp-create-definitions-ok
data-vp-create-definition-object-kind-count
data-vp-create-definition-family-profile-count
data-vp-create-definition-variant-profile-count
data-vp-create-definition-variable-count
data-vp-create-upload-ready
data-vp-create-upload-backend-enabled
data-vp-create-route-download
data-vp-create-starter-object-kind
data-vp-create-starter-family-profile-id
data-vp-create-starter-variant-profile-id
```

### 26.3 Actions

```text
data-vp-create-actions-ready
data-vp-create-actions-version
data-vp-create-actions-binding-done
data-vp-create-actions-asset-loaded
data-vp-actions-html-bridge-ready
data-vp-actions-html-bridge-pending
```

Diese Attribute sind Diagnosehilfen. Die fachliche Wahrheit bleibt in den Runtime-States und Backendantworten.

---

## 27. Browser-Cache und gemischte Versionen

### 27.1 Aktuelle Schutzmaßnahme

Alle 19 JavaScript-Dateien erhalten:

```text
?v=20260710.3
```

### 27.2 Warum das wichtig ist

Das behobene Click-Binding-Problem konnte durch gemischte Zustände verschärft werden:

```text
neues Template
+ alte create_actions.js
+ alter Core-State
+ 304 Cache
```

### 27.3 Deployment-Regel

Bei Änderungen an einer gekoppelten Runtimegruppe:

```text
create.html Asset-Version erhöhen
Service neu bauen/starten
Browserseite mit Cache-Bypass neu laden
Script-Load-State prüfen
```

### 27.4 Kein willkürliches Versionieren

Die Query-Version soll bei einem zusammengehörigen Release einmal erhöht werden. Einzelne Dateien sollen nicht ohne Not unterschiedliche Query-Versionen erhalten.

---

## 28. Debug-Reihenfolge für Action-Probleme

### 28.1 Grundzustand

```javascript
({
  actions: window.VectoplanCreateActions?.getState?.(),
  payload: window.VectoplanCreatePayload?.getState?.(),
  core: window.VectoplanCreateCore?.snapshot?.(),
  shellBridge: window.VectoplanCreateShellActionBridge?.getState?.(),
  templateBridge: window.VectoplanCreateActionsTemplateBridge?.getState?.(),
  scripts: window.vpCreateGetScriptLoadState?.()
})
```

### 28.2 Direkter Runtime-Test

```javascript
await window.VectoplanCreateActions.runAction("download")
```

Interpretation:

```text
funktioniert
  -> Payload und Backendpfad sind grundsätzlich intakt
  -> Problem liegt wahrscheinlich im DOM-Clickpfad

funktioniert nicht
  -> Payload, Runtime Readiness, Route oder Backendantwort prüfen
```

### 28.3 Physischer Programmatic-Click

```javascript
const button = document.querySelector('[data-create-action="download"]');
const before = window.VectoplanCreateActions.getState().actionCount;
button.click();
await new Promise(resolve => setTimeout(resolve, 1000));
({
  before,
  after: window.VectoplanCreateActions.getState().actionCount,
  pointerEvents: getComputedStyle(button).pointerEvents
});
```

### 28.4 Network-Reihenfolge

Beim Download erwartet:

```text
POST validate
POST package-plan
POST download
```

Beim Save erwartet:

```text
POST save
```

Nicht automatisch erwartet:

```text
POST library/sync
```

### 28.5 Häufige Fehlerbilder

```text
Kein POST sichtbar
  -> Click-Binding/Overlay/disabled/pointer-events prüfen

GET /library/sync -> 405
  -> Route wurde im Browser geöffnet; POST erforderlich

/items leer nach Save
  -> Published DB wurde noch nicht synchronisiert

/[object Object]
  -> alte Context-Version oder nicht normalisierte Route

Doppelte Requests
  -> gemeinsamer Event-Marker oder mehrere inkompatible Bridges prüfen
```

---

## 29. Testmatrix

### 29.1 Template-Tests

```text
- Jinja parse
- Rendering mit leerem Kontext
- Rendering mit vollständigem Starterkontext
- Actions Partial innerhalb des Formulars
- Context Partial vorhanden
- neun JSON-Blöcke valide
- alle 19 Script-Tags vorhanden
- korrekte Script-Reihenfolge
- Asset-Version an jeder JS-URL
```

### 29.2 Context-Tests

```text
- Route als String
- Route als {url: ...}
- Route als {href: ...}
- Route als {path: ...}
- ungültige/externe Route
- kein /[object Object]
- leere Definitionsdaten
- doppelte Definitionsrecords
- Fremdschlüsselfelder im falschen Dataset
- simple_cell_block Startervertrag
- snake_case/camelCase Globals
```

### 29.3 Action-Binding-Tests

```text
- Core-Bindeschlüssel bereits gesetzt
- delegierter Listener aktiv
- nur direkter Listener aktiv
- nur Template-Bridge aktiv
- nur Shell-Bridge aktiv
- alle Ebenen gleichzeitig
- dynamisch eingefügter Button
- Button durch DOM-Ersatz neu erstellt
- pending/disabled Button
- dasselbe Event wird nur einmal ausgeführt
```

### 29.4 Download-Tests

```text
- Validate erfolgreich
- Validate fehlgeschlagen
- Package-Plan erfolgreich
- Package-Plan fehlgeschlagen
- JSON-Fehlerantwort statt Blob
- HTML-Fehlerantwort statt Blob
- zu kleiner Blob
- falscher MIME-Type
- gültige ZIP-Signatur
- Dateiname aus Content-Disposition
- Object-URL verzögert widerrufen
```

### 29.5 Save-Tests

```text
- Write-Flag false
- Nutzer bricht Bestätigung ab
- Source-Save erfolgreich
- Ziel existiert
- Backendfehler
- Upload-Metadaten vorhanden
- Response klar als Source-Save interpretieren
- kein falscher Published-Erfolg
```

---

## 30. Aktuelle offene Punkte und Prioritäten

### P0 – Save-Erfolg semantisch präzisieren

Die UI muss unterscheiden:

```text
source_saved
published_synced
published_verified
```

Solange der Backendvertrag nur Source-Save liefert, darf der Status nicht „vollständig veröffentlicht“ suggerieren.

### P0 – Automatische Save→Sync-Orchestrierung

Geplantes Ziel:

```text
POST /create/save
  -> Source atomar schreiben
  -> genau dieses Package scannen
  -> genau diesen Kandidaten synchronisieren
  -> Published Read verifizieren
```

Die Umsetzung gehört in Backend-Services, nicht in das Template.

### P1 – Upload-Bytes End-to-End

Zu prüfen:

```text
request.files
File-Service
Package-Asset-Plan
Document Links
Source-Save
Download-Archiv
Published Assets/Documents
```

### P1 – Preview

Der rote Placeholder ist bewusst stabil, aber keine produktive Vorschau. Eine spätere 3D-Integration benötigt einen separaten Viewer-Vertrag und darf Payload-/Action-Runtimes nicht übernehmen.

### P1 – Runtime-Größen und Kopplung

Einige Runtimes und Context-Payloads sind groß. Zu prüfen:

```text
Definitionen nicht mehrfach serialisieren
Context nur einmal normalisieren
Runtime-Debugdaten begrenzen
Lazy Detail-Fetch statt kompletter Kataloge
```

### P2 – Bridge-Konsolidierung

Die drei Bindungsebenen bleiben vorerst als Robustheitsschutz. Eine spätere Reduzierung ist erst vertretbar, wenn Browser-, DOM-Ersatz- und Cache-Regressionstests dauerhaft grün sind.

---

## 31. Definition of Done für `templates/vplib`

Der Template-/Runtime-Bereich gilt als stabil, wenn:

```text
1. GET /create rendert ohne Jinja-Fehler.
2. Das Haupttemplate lädt ausschließlich kanonische static/js/vplib/create-Pfade.
3. Alle 19 Scripts werden in definierter Reihenfolge geladen.
4. Context-Bootstrap setzt alle dokumentierten Globals.
5. Keine Route wird zu /[object Object].
6. Starterprofil cell_block/simple_cell_block/simple_cell_block.v1 wird aufgelöst.
7. Wizard-Schritte 1 bis 6 funktionieren.
8. Step 3 bleibt sichtbar „Variablen“.
9. Variant-State ist die Browser-Wahrheit.
10. Physische Action-Buttons starten genau eine Action.
11. Dynamisch ersetzte Buttons werden erneut gebunden.
12. Download führt Validate, Package-Plan und Blob-Download aus.
13. Download-Archiv wird vor dem Browserstart plausibilisiert.
14. Save wird bei deaktiviertem Write-Flag blockiert.
15. Save-Ergebnis unterscheidet Source und Published State.
16. Upload-Metadaten verursachen keine Event-Reentrancy.
17. Script-/Binding-Fehler sind über Diagnostics sichtbar.
18. Browser-Cache kann über Asset-Version sicher invalidiert werden.
19. Keine Template-Bridge baut Payloads oder führt eigene Fetch-Logik aus.
20. Backend bleibt alleinige Quelle für Package-Erzeugung und Persistenz.
```

---

## 32. Aktualisierte Kurzdiagnose

Der Template-Bereich ist inzwischen nicht nur modularisiert, sondern gegen die kritischste Browserfehlerklasse gehärtet:

```text
korrekte Runtime vorhanden
+ direkter API-Aufruf funktioniert
+ physischer Button war trotzdem wirkungslos
```

Die aktuelle Architektur löst dies durch:

```text
frühe Shell-Bridge
+ direkte Template-Bridge
+ gehärtete Actions-Runtime
+ gemeinsamer Deduplizierungsmarker
+ MutationObserver
+ Script-Versionierung
+ Route-Normalisierung
```

Der Downloadpfad ist damit End-to-End funktionsfähig. Der Source-Save ist ebenfalls funktionsfähig. Die nächste fachliche Grenze liegt nicht mehr im Template, sondern in der noch fehlenden automatischen Kopplung von Source-Save und Published-DB-Sync.

