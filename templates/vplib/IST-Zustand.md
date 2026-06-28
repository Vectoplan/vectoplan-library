# IST-Zustand · `services/vectoplan-library/templates/vplib`

Stand: 2026-06-27  
Scope: Template-Struktur unter `services/vectoplan-library/templates/vplib` plus direkt abhängige statische Create-Runtimes.

---

## 1. Zielbild

Der Create-Wizard ist in kleine, wartbare Template- und Runtime-Bausteine getrennt. Die sichtbare UI bleibt schwarz, kompakt und editorartig. Die Templates liefern HTML, Datenattribute und JSON-Kontext. JavaScript-Runtimes übernehmen Navigation, Payload-Aufbau, Preview-Sync, Upload-Metadaten und Varianten-State.

Grundregeln im aktuellen Stand:

- Templates liegen unter `services/vectoplan-library/templates/vplib`.
- Statische Create-JS-Dateien liegen weiterhin unter `services/vectoplan-library/static/library_admin/js`.
- Zentrales CSS liegt unter `services/vectoplan-library/static/css/vplib/create.css`.
- Step 3 heißt sichtbar **Variablen**, nutzt technisch aber weiter den Backend-Vertrag `object` / `object-variants`.
- Browser erzeugt keine `.vplib`-Pakete.
- Uploads sind aktuell nur lokale Metadaten. Echte Datei-Bytes müssen später backendseitig ergänzt werden.
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

services/vectoplan-library/static/library_admin/js/
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

Erwartete oder noch nachzuziehende Variant-Runtimes, falls im Projekt vorhanden:

```text
services/vectoplan-library/static/library_admin/js/
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
- importiert `vplib/create/_macros.html`
- lädt Kontext, Stepper, Sections, Preview und Footer-Navigation
- lädt Create-JS-Runtimes in definierter Reihenfolge
- hält `enctype="multipart/form-data"` für spätere Uploads bereit
- nutzt neue Templatepfade unter `vplib/create/...`

Wichtig:

- `create.html` ist nur UI-Orchestrierung.
- Payload- und Package-Erzeugung liegen nicht in diesem Template.
- Backend-Routen bleiben über `/api/v1/vplib/create/*` angebunden.

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
- globale Window-Objekte wie `VectoplanCreateContext`, `VectoplanCreateUploadConfig`

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
- Unterlagen / technische Hinweise nur wenn sinnvoll

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
- 3D-Dateien werden aktuell nur lokal als Metadaten vorbereitet.

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
- Save bleibt Backend-gesteuert
- Buttons stehen vertikal
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

Action-Runtime.

Aufgaben:

- Draft
- Validate
- Package Plan
- Download
- Save
- Resultanzeige
- Action-Locks

Wichtig:

- nutzt Payload-Runtime
- Download nur Backend-Blob
- keine Browser-Package-Erzeugung

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

1. `create.py` darf aktuell nur HTTP-Adapter bleiben, nicht echter `.vplib`-Generator.
2. Echte Upload-Bytes sind noch nicht implementiert, da `_request_payload()` keine `request.files` verarbeitet.
3. Wenn alte Templates noch `library_admin/create.html` rendern, muss backendseitig auf `vplib/create.html` umgestellt werden.
4. Weitere Variant-Runtimes sollten noch konsolidiert werden:
   - Summary
   - Field Renderer
   - Optional Fields
   - Validation
   - Drawer
   - Table
   - Definitions Runtime
5. Preview bleibt bis zur echten 3D-Integration bewusst roter Dev-Platzhalter.
6. Upload-UI für technische Dokumente und `document_list`-Variablen ist konzeptionell vorbereitet, aber backendseitig offen.
7. Step 4 besitzt aktuell einen optionalen 3D-Modell-Strip. Falls Upload dort später wieder entfernt wird, müssen `geometry_model_files` und `geometry_model_uploads_json` entweder vollständig entfernt oder als hidden-only Vertrag behalten werden.

---

## 11. Wartungsregeln

Bei Änderungen an Templates:

- Pfadkommentar in der ersten Zeile beibehalten.
- Keine langen `render_field(...)` / `render_select(...)` Macro-Aufrufe in neuen Section-Templates.
- Sichtbare Sprache in Step 3 bleibt „Variablen“.
- Technische Objektlogik darf existieren, soll aber nicht sichtbar als „Objekt“ dominieren.
- Backend-Feldnamen nicht ohne Backend-Abgleich ändern.
- Uploads nicht als echte Dateiübertragung ausgeben, solange Backend-Dateiverarbeitung fehlt.
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
