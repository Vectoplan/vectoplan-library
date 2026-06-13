
<!-- services/vectoplan-library/README.md -->

# VECTOPLAN Library

Der `vectoplan-library`-Service ist die **kanonische Bibliotheks- und Paketwelt** von VECTOPLAN.

Er verwaltet **wiederverwendbare Blöcke, Modelle, Bauteilfamilien, Varianten, technische Profile, Berechnungsgrundlagen, Renderdaten und spätere Herstellerfähigkeit** für die gesamte Plattform.

Der Service ist damit **nicht nur ein Asset-Katalog**, sondern die strukturierte Fachquelle für alles, was im Editor auswählbar, platzierbar, technisch beschreibbar und später produktfähig sein soll.

---

## Kurzfassung

VECTOPLAN ist eine Plattform für strukturierte Gebäudeerstellung, Bearbeitung und spätere technische sowie kaufmännische Auswertung.

Innerhalb dieser Plattform gilt:

- der **Core** besitzt Projekte, Instanzen und Revisionen
- die **Library** besitzt Familien, Varianten, technische Paketdefinitionen und Kataloglogik
- der **Editor** ist die builder-orientierte Arbeitsoberfläche
- der **Converter** erzeugt Austausch- und Runtime-Artefakte

Für `vectoplan-library` bedeutet das:

> Der Service ist die kanonische Heimat der wiederverwendbaren Objekt-, Bauteil- und Modellwelt von VECTOPLAN.

---

## Was VECTOPLAN als Gesamtplattform ist

VECTOPLAN ist **nicht BIM-first** und **nicht IFC-zentriert**.

Die Plattform verfolgt bewusst ein eigenes Modell:

- ein eigenes semantisches Authoring-Modell
- ein builder-orientierter 3D-Editor
- eine getrennte Objekt- und Bauteilbibliothek
- separate Import-/Export- und Runtime-Pfade
- spätere Ableitung von 2D, Mengen, Kosten und Austauschformaten

Das eigentliche Produkt ist nicht nur der Viewer und auch nicht nur der Export.

**Das Produkt ist das Zusammenspiel aus kanonischem Modell, Editor, Library und klar getrennten Servicegrenzen.**

---

## Die Rolle von `vectoplan-library`

`vectoplan-library` ist ein **eigener fachlicher Service** und nicht bloß eine Datenablage für Vorschauobjekte.

Er verwaltet perspektivisch:

- Reiter wie **Hochbau**, **Tiefbau** und **Ingenieurbau**
- Kategorien und Unterkategorien
- wiederverwendbare **Families**
- auswählbare **Variants**
- Editor- und Platzierungsprofile
- physische und technische Profile
- Berechnungsprofile
- Material- und Leistungsprofile
- adaptive und dynamische Modelle
- Render- und Preview-Daten
- Herstellerverträge für spätere Produktanbindung
- Scan- und Validierungslogik für Library-Pakete
- veröffentlichte Library-Einträge in der Datenbank
- Read-Modelle für Creative Library, Inventar und spätere Clients

Kurz:

**Die Library besitzt die wiederverwendbare Bau- und Objektlogik, nicht die Projekte.**

---

## Was der Service aktuell leisten soll

Die aktuelle Zielrichtung des Services ist:

1. eine **feste Paketstruktur** für Library-Elemente definieren
2. Reiter, Kategorien und Families unter `/src/library_catalog/` organisieren
3. strukturierte Family-/Variant-Pakete validieren
4. nur gültige Pakete in die Datenbank übernehmen
5. daraus die Creative Library und Inventar-Daten bereitstellen
6. später Herstellerprodukte als Overlay andocken können

---

## Was der Service bewusst nicht ist

`vectoplan-library` ist **nicht**:

- nicht der Owner des kanonischen Projektmodells
- nicht der Editor
- nicht die Projekt-Revisionslogik
- nicht der Runtime-Chunk-Service
- nicht der IFC-Import-/Export-Kern
- nicht der finale Kosten- oder LV-Service
- nicht der Ort für frei ausführbaren Paketcode

Besonders wichtig:

**Packages dürfen keine `.py`-Dateien oder andere frei ausführbaren Nutzercode-Dateien enthalten.**  
Die Library arbeitet mit **deklarativen, scannerfähigen und validierbaren Datenstrukturen**.

---

## Die wichtigste Modellentscheidung: Family statt Einzelobjekt

Ein Library-Element ist im Regelfall **eine Familie**, nicht jede einzelne Ausprägung als separates Objekt.

### Beispiel

Nicht so:

- `ziegelwand_11_5`
- `ziegelwand_17_5`
- `ziegelwand_24`

Sondern so:

- `ziegelwand`
  - `11_5cm_nicht_tragend`
  - `17_5cm_tragend`
  - `24cm_tragend`

Warum das wichtig ist:

- Im Editor bleibt es dieselbe Wandfamilie.
- Unterschiede wie Dicke, Tragfähigkeit oder Kennwerte sind Varianten.
- Formeln und Kernlogik bleiben gleich.
- Später kann der Nutzer pro Instanz die Variante wechseln.
- Herstellerprodukte können später an Family oder Variant andocken.

Kurz:

**Family = semantisches Objekt. Variant = konkrete Ausprägung.**

---

## Das Paketformat: VPLIB

Der Service arbeitet im Zielbild mit einem eigenen Paketformat:

**VPLIB = VECTOPLAN Library Package**

Dieses Format existiert in zwei Formen:

### 1. Directory Package

Das ist die Autorenform im Repository.

Beispiel:

```text
src/library_catalog/hochbau/waende/ziegelwand/
````

### 2. Archive Package

Das ist dieselbe Struktur als Datei, z. B.

```text
ziegelwand.vplib
```

Das bedeutet:

* im Service und in Git wird mit Ordnerpaketen gearbeitet
* später kann daraus ein eigenes Austausch-/Importformat werden

---

## Die Grundstruktur unter `/src`

Die Library-Pakete sollen unter einem festen Wurzelpfad liegen:

```text id="w30n2w"
src/
  library_catalog/
    _schemas/
    _taxonomy/
    _shared/
    _examples/
    hochbau/
    tiefbau/
    ingenieurbau/
```

### Bedeutung

* `_schemas/`
  formale JSON-Schemata für VPLIB-Dateien

* `_taxonomy/`
  definierte Domains, Kategorien, Unterkategorien, Klassen, Materialtypen, Einheiten

* `_shared/`
  gemeinsame, wiederverwendbare Profile und Referenzbausteine

* `_examples/`
  Referenzpakete und Beispieldaten

* `hochbau/`, `tiefbau/`, `ingenieurbau/`
  eigentliche fachliche Inhaltsräume

---

## Reiter, Kategorien und Family-Pakete

Die sichtbare Library-Hierarchie ist im Zielbild:

* **Domain / Reiter**
* **Kategorie**
* **Family**
* **Variant**

Beispiel:

```text id="nfmx7w"
src/library_catalog/
  hochbau/
    waende/
      ziegelwand/
      betonwand/
    decken/
      massivdecke/
    daecher/
      satteldach/
    moebel/
      schulbank/
    technik/
      wasserhahn/

  tiefbau/
    leitungen/
      wasserleitung/
    schaechte/
      revisionsschacht/

  ingenieurbau/
    bruecken/
      brueckenkappe/
      brueckenpfeiler/
    tragwerk/
      brueckenlager/
```

---

## Welche Objektklassen die Library unterstützen muss

Die Library soll nicht nur einfache Blockbausteine kennen.

Sie muss mindestens diese Klassen tragen:

### `cell_block`

Raster- oder blockartige Bauteile

Beispiele:

* Wandblock
* Deckenelement
* Straßenblock

### `multi_cell_module`

Mehrzellige Module

Beispiele:

* Treppenkern
* Schacht
* Fundamentmodul

### `catalog_object`

Freie oder eher objektartige Modelle

Beispiele:

* Wasserhahn
* Möbel
* Wärmepumpe
* Armatur

### `adaptive_system`

Kontextabhängige, adaptive Modelle

Beispiele:

* Brückenkappe
* Randbalken
* adaptive Sonderformen auf vorhandenen Tragstrukturen

---

## Standardstruktur eines Family Packages

Ein Family Package besteht nicht aus einer großen Einzeldatei, sondern aus klar getrennten Modulen.

Empfohlene Struktur:

```text id="6ri5mo"
ziegelwand/
  vplib.manifest.json
  vplib.modules.json

  family/
    identity.json
    classification.json

  variants/
    index.json
    default.json
    11_5cm_nicht_tragend.json
    17_5cm_tragend.json
    24cm_tragend.json

  editor/
    inventory.json
    placement.json
    targeting.json
    anchors.json

  render/
    icon.svg
    preview.webp
    mesh.glb
    render_variants.json

  physical/
    base.json
    dimensions.json
    layers.json
    collision.json
    occupancy.json

  material/
    base.json
    performance.json

  calculation/
    variables.json
    formulas.json
    quantities.json
    constraints.json
    measure_logic.json

  analysis/
    statics/
      profile.json
    energy/
      profile.json
    acoustics/
      profile.json
    routing/
      profile.json
    reinforcement/
      profile.json

  dynamic/
    context_rules.json
    bindings.json
    generator.json

  manufacturer/
    contract.json
    override_slots.json

  docs/
    notes.md

  tests/
    cases.json
```

Nicht jede Datei ist in der ersten Stufe für jedes Objekt verpflichtend, aber die Grundstruktur soll klar und stabil sein.

---

## Pflichtmodule und optionale Module

Damit die Struktur für Wände, adaptive Brückenelemente und leichte 3D-Objekte gleichermaßen funktioniert, gibt es eine **Modulsteuerung**.

### Immer Pflicht

* `vplib.manifest.json`
* `vplib.modules.json`
* `family/identity.json`
* `variants/index.json`
* `variants/default.json`
* `editor/inventory.json`
* `editor/placement.json`
* `manufacturer/contract.json`

### Pflicht für technische Bauteile

* `physical/base.json`
* `calculation/variables.json`
* `calculation/formulas.json`
* `calculation/quantities.json`
* `calculation/measure_logic.json`

### Pflicht für 3D-Objekte

* Renderprofil
* Collision-/Boundingdaten

### Pflicht für adaptive Systeme

* `dynamic/context_rules.json`
* `dynamic/bindings.json`
* `dynamic/generator.json`

---

## Varianten als Overrides

Varianten sollen nicht das ganze Objekt neu beschreiben.

Stattdessen gilt:

* die **Family** definiert Kernlogik, Kernvariablen und Grundstruktur
* die **Variant** überschreibt nur Abweichungen

Beispiel `ziegelwand`:

Die Family definiert:

* Editorverhalten
* Platzierungslogik
* Materialfamilie
* Berechnungsgrundlagen
* Maßlogik

Die Variante überschreibt dann z. B.:

* reale Dicke
* Tragfähigkeit
* U-Wert
* Rohdichte
* zulässige Einsatzart

Dadurch bleibt das System konsistent.

---

## Editormaß und Realmaß

Ein zentrales Problem ist die Übersetzung von Editorabstraktion in Bauwirklichkeit.

Beispiel:

* Im Editor wirkt ein Element wie `1m x 1m x 1m`
* In der Realität ist es z. B. `1,00m x 1,00m x 0,24m`

Oder:

* Drei Editor-Blöcke ergeben real nicht 3,00m, sondern z. B. 2,77m

Darum braucht die Library eine eigene Maßlogik-Schicht.

Empfohlene Datei:

* `calculation/measure_logic.json`

Darin werden formal beschrieben:

* Zelllogik
* reale Abmessungen
* Stapelregeln
* Zuschlagsregeln
* Mauermaß- und Schichtlogik
* variantenspezifische Umrechnung

Gerade für Wände, Decken, Leitungen und Tragsysteme ist das essenziell.

---

## Berechnung als deklarative Struktur

Die Library soll technisch sehr tief werden können, aber ohne frei ausführbaren Code.

Deshalb gilt:

* keine `.py`-Dateien in Library-Paketen
* keine Shellskripte
* keine frei hochladbaren Formelauswertungen in Codeform

Stattdessen wird Berechnung deklarativ beschrieben, z. B. über:

* `variables.json`
* `formulas.json`
* `quantities.json`
* `constraints.json`
* `measure_logic.json`

Der Service und spätere Fachservices werten diese Daten aus.

---

## Feste Kernvariablen, aber offen für Erweiterungen

Die Library soll stark erweiterbar sein, aber nicht beliebig werden.

Darum wird zwischen zwei Variablenarten unterschieden.

### Core Variables

Systemweit standardisierte Variablen, z. B.

* Identität
* Editor-Footprint
* reale Maße
* Materialklasse
* Wärmeleitfähigkeit
* Rohdichte
* Druckfestigkeit
* Tragfähigkeit
* Routingfähigkeit
* Grundkostenfaktoren

### Extension Variables

Objektspezifische Erweiterungen, z. B.

* `extensions.bridge.*`
* `extensions.wall_masonry.*`
* `extensions.manufacturer_ready.*`

Damit kann das Format wachsen, ohne seine Struktur zu verlieren.

---

## Adaptive und dynamische Modelle

Die Library muss auch kontextabhängige Modelle beschreiben können.

Beispiel:

* Brückenkappe

Eine Brückenkappe ist kein bloßes Mesh, sondern leitet sich aus Kontext ab, z. B.:

* Unterbau
* Tragkonstruktion
* Breite
* Lagerung
* Randbedingungen

Dafür gibt es eigene Dateien:

* `dynamic/context_rules.json`
* `dynamic/bindings.json`
* `dynamic/generator.json`

Diese Dateien beschreiben:

* auf welchen Kontexten das Objekt erlaubt ist
* welche Daten aus dem Kontext gelesen werden
* wie daraus Modellparameter und Regeln entstehen

Wichtig:

**Auch adaptive Modelle bleiben deklarativ beschrieben.**

---

## Leichte 3D-Objekte

Nicht jedes Library-Element ist ein tief technisches Bauteil.

Die Library muss auch leichtere 3D-Objekte verwalten können, z. B.:

* Wasserhähne
* Möbel
* Ausstattung
* einfache Katalogobjekte

Für solche Objekte gilt dieselbe Package-Familie, aber mit weniger aktiven Modulen.

Typisch aktiv sind dort:

* Family
* Variants
* Editor
* Render
* Bounding-/Collisiondaten
* optional Herstellervertrag

Nicht alles braucht Statik, Energie oder Akustik.

---

## Herstellerfähigkeit

Herstellerdaten werden später separat in der Datenbank gepflegt.
Trotzdem muss die Library-Struktur von Anfang an dafür vorbereitet sein.

Dafür dienen insbesondere:

### `manufacturer/contract.json`

Beschreibt:

* ob Herstellerprodukte für dieses Family Package zulässig sind
* ob Produkte family- oder variantenspezifisch angebunden werden
* welche Variablen später überschreibbar sind
* welche Werte Hersteller liefern müssen

### `manufacturer/override_slots.json`

Beschreibt:

* welche Variablen Hersteller überschreiben dürfen
* welche Einheiten und Wertebereiche gelten
* welche Felder verpflichtend sind

Wichtig:

**Der Hersteller überschreibt später keine Family-Definition, sondern liefert ein Overlay auf definierte Variablen.**

---

## Scanner und Validierung

Die Library darf nicht blind alles aus `/src` übernehmen.

Der Scanner muss mindestens prüfen:

1. Struktur
   Liegt das Paket am richtigen Ort?

2. Pflichtdateien
   Sind alle nötigen Dateien vorhanden?

3. JSON-Schemata
   Stimmen Felder, Typen und Werte?

4. Cross-File-Konsistenz
   Passen Family, Modules, Variants und Profile zueinander?

5. Logik
   Sind Maße, Varianten, Regeln und Referenzen plausibel?

6. Assets
   Existieren referenzierte Render- und Preview-Dateien?

### Wichtige Regel

Nur **gültige** Packages werden veröffentlicht.
Ungültige Packages:

* werden protokolliert
* erscheinen nicht in der produktiven Library
* ersetzen keinen gültigen Altstand

---

## Datenbankrolle des Services

Die Datenbank ist nicht nur Cache des Dateisystems.

Sie ist die **veröffentlichte, validierte Library-Wahrheit**.

Dort werden perspektivisch gespeichert:

* Families
* Family-Revisions
* Varianten
* resolved Varianten
* Scanläufe
* Scanfehler
* Veröffentlichungsstatus
* spätere Herstelleroverlays
* Inventarzustände

---

## Verhältnis zur Creative Library

Die Creative Library im Frontend soll nicht direkt aus `/src` lesen.

Der Pfad lautet:

**`/src` → Scanner → Validierung → Datenbank → API → Frontend**

Das ist wichtig, damit:

* nur gültige Packages sichtbar werden
* Varianten sauber aufgelöst werden
* Suche und Filter funktionieren
* Herstellerfähigkeit später integrierbar bleibt

---

## Verhältnis zum Editor

Der Editor liest die Library für:

* Reiter
* Kategorien
* Unterkategorien
* Creative-Grid-Inhalte
* Inventar
* Family-/Variantenauswahl
* Placement-Metadaten
* Preview-Darstellung

Der Editor speichert die Library nicht selbst als Primärquelle.

---

## Inventarzustand

`vectoplan-library` soll perspektivisch eine Route liefern, die den Inventarzustand maschinenlesbar ausgibt.

Ein Slot soll später mindestens enthalten:

* Slotindex
* `family_id`
* `variant_id`
* Label
* Domain
* Kategorie
* Anzeigeinformationen
* Zeitstempel

So kann der spätere Editor diese Daten direkt verwenden.

---

## Aktueller Frontend-Stand des Services

Der Service hat aktuell bereits eine sichtbare Admin-Oberfläche unter `/admin`.

Diese Oberfläche ist serverseitig mit Jinja aufgebaut und besteht im Wesentlichen aus:

* `overview`
* `settings`
* `export-import`

### Besonders relevant ist aktuell

* eine builderartige Overview
* eine Creative Library mit Reitern
* Unterkategorien unter der Hauptnavigation
* aktuelles Inventar unten
* reduzierte Toolbar rechts
* Theme-Umschaltung
* Live Search
* vorbereitete Drawer-Logik
* feste, editorartige Overlay-Struktur

Die aktuelle Oberfläche ist damit bereits deutlich mehr als eine Platzhalterseite, aber noch nicht die finale fachliche Library.

---

## Aktuell relevante Service-Struktur

```text id="j2knnf"
vectoplan-library/
  AI.md
  README.md
  IST-Zustand.md
  Dockerfile
  entrypoint.sh
  requirements.txt
  wsgi.py
  app.py
  config.py
  extensions.py

  routes/
    __init__.py
    admin.py
    health.py

  templates/
    library_admin/
      main.html
      partials/
        _header.html
      screens/
        _overview.html
        _settings.html
        _export_import.html

  static/
    library_admin/
      css/
        main.css
        layout.css
        overview.css
      js/
        main.js

  src/
    library_catalog/
      ...
```

---

## Was als Nächstes sinnvoll ist

Die nächste sinnvolle Ausbaustufe des Services ist:

1. eine formale **VPLIB-Spezifikation**
2. Referenzpakete unter `src/library_catalog/`
3. Scanner- und Validierungslogik
4. persistente Veröffentlichung in die Datenbank
5. Read-APIs statt Mock-Daten
6. Inventar-APIs
7. später Herstellerverträge und Overlays

---

## Quick Start

### Lokaler Start

Im Serviceverzeichnis:

```bash
python -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
python wsgi.py
```

Danach ist die Oberfläche typischerweise unter `/admin` erreichbar.

### Docker / Compose

Vom Repository-Root aus:

```bash
docker compose up -d --build
```

Danach ist der Service über den konfigurierten Port erreichbar.

---

## Wichtige Merksätze

* Die Library besitzt **Families und Variants**, nicht Projekte.
* Packages enthalten **deklarative Daten**, keinen ausführbaren Code.
* Herstellerdaten kommen später als **Overlay**, nicht als Primärpaket.
* Adaptive Modelle sind eine eigene Klasse, keine Sonderfälle im Mesh.
* Die Creative Library soll aus der **Datenbank**, nicht direkt aus dem Dateisystem lesen.
* Das eigentliche Ziel ist eine **kanonische, validierte Bibliothekswelt für den Editor und spätere Fachauswertungen**.

---

## Verhältnis zu `AI.md`

Dieses `README.md` ist die **entwicklerfreundliche Projektübersicht** des Services.

Es erklärt vor allem:

* wofür `vectoplan-library` da ist
* wie der Service grob zu verstehen ist
* welche Kernideen gelten
* wie man die Struktur schnell einordnet

Die `AI.md` ist dagegen das **präzisere Architektur- und Verantwortungsdokument**.

Faustregel:

* `README.md` = Einstieg, Überblick, Orientierung
* `AI.md` = Architekturvertrag, Zielbild, Invarianten

---

## Kurzfassung

`vectoplan-library` ist der kanonische Bibliotheksservice von VECTOPLAN.

Er verwaltet:

* wiederverwendbare Family-/Variant-Pakete
* technische und editorbezogene Profile
* Render- und Preview-Daten
* adaptive Modelllogik
* Scan- und Validierungslogik
* spätere Herstellerfähigkeit
* Read-Modelle für Creative Library und Inventar

Er besitzt nicht das Projekt, sondern die wiederverwendbare Objekt- und Bauteilwelt.

**Nicht der Katalog allein ist das Ziel, sondern eine streng strukturierte, validierte und später produktfähige Library für den gesamten VECTOPLAN-Stack.**

```
```