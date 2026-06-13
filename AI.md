
<!-- services/vectoplan-library/AI.md -->

# AI.md – VECTOPLAN Library

## Status dieser Fassung

Diese Fassung beschreibt den **beabsichtigten Zielstand** des Services `vectoplan-library` innerhalb der VECTOPLAN-Plattform.

Wichtig:

Diese Datei ist **kein Code-Audit** und **keine reine Bestandsaufnahme**, sondern ein **Architektur-, Verantwortungs- und Produktdokument** für den Library-Service.

Sie erklärt:

- was VECTOPLAN als Gesamtplattform ist
- welche Kernservices es gibt
- warum der Library-Service ein eigener Microservice ist
- welche fachliche Wahrheit der Library-Service besitzt
- was der Service bewusst **nicht** tun soll
- wie die Library intern gedacht werden soll
- wie die Paketstruktur für Blöcke/Modelle funktioniert
- wie Family, Variant und spätere Hersteller-Overlays zusammenhängen
- wie Scanner, Datenbank, Creative Library, Inventar und spätere Herstellerintegration zusammenspielen

Diese Datei dient als:

- Einstiegsdokument für Entwickler
- Architekturvertrag für `vectoplan-library`
- Referenz für Service-Grenzen und Datenbesitz
- Grundlage für Scanner-, Datenbank-, API- und UI-Entwicklung
- Leitlinie für spätere Erweiterungen wie Herstellerportal, Produkt-Matching und technische Auswertung

---

## 1. Was VECTOPLAN als Gesamtplattform ist

VECTOPLAN ist eine Plattform zur **strukturierten Gebäudeerstellung, Bearbeitung und späteren technischen und kaufmännischen Auswertung**.

Das System ist nicht als klassisches BIM-first-System gedacht.  
Es ist auch nicht als IFC-zentrierter Viewer oder Dateikonverter gedacht.

Die Grundidee lautet:

> Gebäude, Bauteile, technische Systeme und Objekte sollen sich in einer builder-orientierten 3D-Umgebung intuitiv bearbeiten lassen, gleichzeitig aber so strukturiert beschrieben sein, dass daraus belastbare technische Daten, Varianten, Mengen, Kosten, 2D-Pläne, Austauschformate und spätere Produktauswertungen entstehen können.

Daraus folgen einige harte Architekturentscheidungen:

- VECTOPLAN ist **nicht BIM-first**
- IFC ist **nicht** das kanonische Kernformat
- GLB ist **nicht** die semantische Wahrheit
- das kanonische Modell ist ein **eigenes semantisches VECTOPLAN-Authoring-Modell**
- der Editor ist die **primäre Eingabeoberfläche**
- Austauschformate sind **abgeleitete Adapterformate**
- Runtime-Artefakte sind **Darstellungsformen**, nicht die fachliche Primärwahrheit

Kurz:

**VECTOPLAN ist eine Authoring-Plattform mit eigenem Datenmodell, builder-zentriertem 3D-Editor und klar getrennten Fachservices.**

---

## 2. Executive Summary

VECTOPLAN besteht im Zielbild aus mehreren klar getrennten Services.

Die erste Zielarchitektur umfasst mindestens diese Kernbausteine:

1. `vectoplan-core-service`
2. `vectoplan-library`
3. `vectoplan-editor`
4. `vectoplan-converter-service`

Später kommen voraussichtlich weitere Services dazu, z. B.:

5. `vectoplan-realtime-service`
6. `vectoplan-drawing-service`
7. `vectoplan-quantity-cost-service`

Der wichtigste Merksatz für die Gesamtplattform lautet:

**Der Core besitzt das kanonische Projektmodell. Die Library besitzt die kanonische Objekt- und Bauteilwelt. Der Editor ist die Arbeitsoberfläche. Der Converter erzeugt Austausch- und Runtime-Artefakte.**

Für `vectoplan-library` bedeutet das:

**Der Library-Service ist der Owner der wiederverwendbaren Bauteil-, Block-, Modell-, Varianten- und Paketdefinitionen von VECTOPLAN.**

---

## 3. Die Rolle von `vectoplan-library` im Gesamtsystem

`vectoplan-library` ist **nicht nur ein Katalogservice für Icons und Vorschauen**.

Er ist die fachliche Heimat der **wiederverwendbaren Objekt- und Bauteilwelt** von VECTOPLAN.

Dazu gehören perspektivisch:

- Reiter wie Hochbau, Tiefbau, Ingenieurbau
- Kategorien und Unterkategorien
- semantische Familien von Blöcken und Modellen
- Varianten innerhalb einer Familie
- technische Profile
- Berechnungsprofile
- Materialprofile
- Platzierungs- und Editorregeln
- Render- und Vorschaudaten
- adaptive/dynamische Modellregeln
- Herstellerverträge für spätere Produktanbindung
- Scans und Validierung von Paketstrukturen
- Veröffentlichung gültiger Library-Einträge in die Datenbank
- Auslieferung dieser Einträge an Creative Library, Inventar und spätere Clients

Kurz:

**`vectoplan-library` besitzt nicht das Projekt, sondern die wiederverwendbare Bau- und Objektlogik, auf die Projekte und Editor später aufbauen.**

---

## 4. Warum die Library ein eigener Microservice ist

Die Library muss eigenständig sein, weil sie andere Aufgaben hat als der Core.

### Der Core besitzt

- Projekte
- Ebenen
- Grids
- Instanzen
- Revisionen
- Rechte
- projektbezogene Commands und Zustände

### Die Library besitzt

- Familien von Bauteilen, Blöcken und Modellen
- Variantenlogik
- technische Paketdefinitionen
- Material- und Leistungsprofile
- Kategorien
- Unterkategorien
- Herstellerverträge
- Render-/Preview-Daten
- Scan- und Validierungslogik für Library-Pakete

Würde man beides vermischen, entstünden sofort Probleme:

- Projektzustand und Bibliothekswahrheit würden ineinanderlaufen
- Bibliotheksänderungen würden Projektpersistenz verunreinigen
- Hersteller- und Produktlogik würde im Projektkern landen
- Editor und Library könnten nicht sauber unabhängig wachsen

Darum gilt dauerhaft:

**`vectoplan-library` ist der Owner der Library-Welt, nicht der Projekte.**

---

## 5. Was `vectoplan-library` fachlich ist

`vectoplan-library` ist am treffendsten so zu verstehen:

**Ein kanonischer Bibliotheksservice für VECTOPLAN-Familien, Varianten, technische Paketdefinitionen, Validierung, Veröffentlichung und spätere Produktfähigkeit.**

Genauer:

1. Ein Service für **wiederverwendbare Library-Familien**
2. Ein Service für **technische Profile und Regeln**
3. Ein Service für **strukturierte Family-/Variant-Pakete**
4. Ein Service für **Scan, Validierung und Veröffentlichung**
5. Ein Service für **Creative-Library-Read-Modelle**
6. Ein Service für **Inventar-Integrationszustände**
7. Ein Service, der später **herstellerfähige Produktverträge** bereitstellt

---

## 6. Was `vectoplan-library` ausdrücklich nicht ist

Der Service ist wichtig, aber bewusst begrenzt.

Er ist **nicht**:

1. nicht der Owner des kanonischen Projektmodells
2. nicht der Owner von Instanzen im Projekt
3. nicht der primäre Persistenzort für Projekt-Revisionslogik
4. nicht der Editor selbst
5. nicht der IFC-Import-/Export-Kern
6. nicht die Runtime-Chunking-Pipeline
7. nicht der Ort für vollständige Hersteller-Preislogik in der ersten Stufe
8. nicht der Ort für finale Mengen-/Kostenrechnung des Projekts
9. nicht der Ort für freie, ausführbare Nutzerlogik oder beliebige Skripte in Paketen

Besonders wichtig:

**`vectoplan-library` besitzt Familien und Varianten – nicht deren konkrete Platzierung im Projekt.**

---

## 7. Die Grundidee der Library: Family statt Einzelobjekt

Der wichtigste Library-Grundsatz lautet:

**Ein Library-Element ist in der Regel eine Familie, nicht jede einzelne Ausprägung als eigenes unabhängiges Objekt.**

Beispiel:

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
- Unterschiede wie Dicke oder Tragfähigkeit sind Varianten.
- Formeln und Kernstruktur bleiben gleich.
- Nur Variablenwerte ändern sich.
- Später kann der Nutzer in einer CAD-/Inspector-artigen Oberfläche pro Instanz die Variante wechseln.

Kurz:

**Die Library organisiert Familien mit Varianten, nicht tausende künstlich duplizierte Einzelobjekte.**

---

## 8. Das zentrale Format: VPLIB

Die Library soll ein eigenes standardisiertes Paketformat verwenden.

Empfohlener Name:

**VPLIB = VECTOPLAN Library Package**

Dieses Format existiert in zwei Erscheinungsformen:

### 8.1 Directory Package

Das ist die Autorenform im Repository, z. B.

```text
src/library_catalog/hochbau/waende/ziegelwand/
````

### 8.2 Archive Package

Das ist die gepackte Form desselben Inhalts, z. B.

```text
ziegelwand.vplib
```

Die Directory-Form ist für Entwicklung, Git und Scanner ideal.
Die `.vplib`-Datei ist später für Austausch, Import und Paketierung sinnvoll.

---

## 9. Die Grundstruktur unter `/src`

Der Library-Service soll eine feste Inhaltsstruktur unter `/src` besitzen.

Empfohlene Wurzel:

```text
src/library_catalog/
```

Darunter:

```text
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
  erlaubte Domains, Kategorien, Unterkategorien, Klassen, Einheiten, Materialtypen

* `_shared/`
  wiederverwendbare gemeinsame Profile und Definitionen

* `_examples/`
  Referenzpakete als Vorlage für Entwickler

* `hochbau/`, `tiefbau/`, `ingenieurbau/`
  eigentliche Inhaltsdomänen

---

## 10. Reiter, Kategorien und Familien

Die sichtbare Creative Library im Editor und in der Admin-Oberfläche soll später aus der kanonischen Struktur der Library abgeleitet werden.

Die oberste Hierarchie lautet:

* Domain / Reiter
* Kategorie
* Familie
* Variante

Beispiel:

```text
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

Das ist wichtig für:

* Scanner
* Datenbankmodell
* API-Routen
* Creative-Library-UI
* spätere Herstellerzuordnung

---

## 11. Welche Objektarten die Library unterstützen muss

Die Library darf nicht nur einfache 1x1x1-Blöcke kennen.

Sie muss mindestens vier Objektklassen abdecken.

### 11.1 `cell_block`

Raster- oder blockartige Bauteile
Beispiele:

* Wandblock
* Deckenelement
* Straßenblock

### 11.2 `multi_cell_module`

Mehrzellige Module
Beispiele:

* Treppenkern
* Schacht
* Fundamentmodul

### 11.3 `catalog_object`

Freie oder eher objektartige Modelle
Beispiele:

* Wasserhahn
* Möbel
* Wärmepumpe
* Armatur

### 11.4 `adaptive_system`

Kontextabhängige, adaptive Objekte
Beispiele:

* Brückenkappe
* Randbalken
* adaptive Geländersysteme
* kontextgebundene Sonderformen

Diese Klassen müssen im Format explizit erkennbar sein.

---

## 12. Die Standardstruktur eines Family Packages

Ein Family Package soll nicht aus einer einzigen großen JSON-Datei bestehen, sondern aus klar getrennten Modulen.

Empfohlene Struktur:

```text
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

Nicht jede Datei ist für jedes Objekt aktiv, aber die Grundstruktur soll klar sein.

---

## 13. Pflicht- und Optionsmodule

Damit dieselbe Formatfamilie sowohl für Wände als auch für Wasserhähne oder adaptive Brückenelemente funktioniert, braucht das System eine Modulsteuerung.

### Immer Pflicht

* `vplib.manifest.json`
* `vplib.modules.json`
* `family/identity.json`
* `variants/index.json`
* `variants/default.json`
* `editor/inventory.json`
* `editor/placement.json`
* `manufacturer/contract.json`

### Zusätzlich Pflicht für technische Bauteile

* `physical/base.json`
* `calculation/variables.json`
* `calculation/formulas.json`
* `calculation/quantities.json`
* `calculation/measure_logic.json`

### Zusätzlich Pflicht für 3D-Objekte

* Renderdaten
* Collision-/Boundingdaten

### Zusätzlich Pflicht für adaptive Modelle

* `dynamic/context_rules.json`
* `dynamic/bindings.json`
* `dynamic/generator.json`

---

## 14. Die wichtigste Trennung: Family, Variant, Product Overlay

Das ist einer der wichtigsten Punkte im gesamten Service.

### 14.1 Family

Die Familie beschreibt das semantische Objekt selbst.
Beispiel:

* `ziegelwand`
* `wasserhahn`
* `brueckenlager`
* `brueckenkappe`

### 14.2 Variant

Die Variante beschreibt eine Ausprägung derselben Familie.
Beispiel:

* `24cm_tragend`
* `17_5cm_tragend`
* `11_5cm_nicht_tragend`

### 14.3 Product Overlay

Später beschreibt ein Herstellerprodukt eine produktbezogene Ausprägung, die auf Family und optional Variant aufsitzt.

Beispiel:

* Family: `ziegelwand`
* Variant: `24cm_tragend`
* Produkt: `Schlagmann Produkt X`

Wichtig:

**Herstellerdaten gehören nicht als Primärwahrheit in das Family Package.**
Sie werden später als Datenbank-Overlay gespeichert.

---

## 15. Varianten sollen nur Overrides definieren

Eine Variante soll nicht das ganze Objekt neu beschreiben.

Stattdessen gilt:

* Family definiert Basisstruktur, Regeln und Kernvariablen
* Variant überschreibt nur Abweichungen

Beispiel Wandfamilie:

Die Family definiert:

* Editorverhalten
* Platzierungslogik
* Materialfamilie
* Formeln
* Berechnungsmodule

Die Variant überschreibt z. B. nur:

* reale Dicke
* Tragfähigkeit
* U-Wert
* Rohdichte
* Druckfestigkeit
* zulässige Einsatzart

Dadurch bleibt das System konsistent und sehr viel besser wartbar.

---

## 16. Editormaß und Realmaß

Ein besonders wichtiger Bereich ist die Trennung zwischen Authoring-Darstellung und Bauwirklichkeit.

Beispiel:

* Im Editor kann ein Element wie `1m x 1m x 1m` erscheinen.
* In der Realität ist es vielleicht `1,00m x 1,00m x 0,24m`.

Oder:

* Drei gestapelte Editorblöcke entsprechen nicht einfach 3,00m, sondern z. B. 2,77m.

Darum braucht die Library eine eigene Schicht für Maßlogik.

Empfohlene Datei:

* `calculation/measure_logic.json`

Darin wird formal beschrieben:

* Zelllogik
* reale Abmessungen
* Stapelregeln
* Zuschlagsregeln
* Mauermaß- oder Schichtlogik
* material- oder variantenspezifische Umrechnungen

Gerade für Wände, Decken, Tragsysteme oder Leitungen ist das zentral.

---

## 17. Feste Kernvariablen, aber unbegrenzt erweiterbar

Die Library soll stark erweitert werden können, aber nicht chaotisch werden.

Darum braucht sie zwei Variablenebenen.

### 17.1 Core Variables

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

Diese Variablen sollen überall dieselben Namen tragen.

### 17.2 Extension Variables

Objektspezifische Erweiterungen, z. B.

* `extensions.bridge.*`
* `extensions.wall_masonry.*`
* `extensions.manufacturer_ready.*`

Damit bleibt das Format offen, ohne beliebig zu werden.

---

## 18. Berechnung als deklarative Schicht

Die Berechnungslogik der Library soll **nicht** aus frei ausführbarem Code bestehen.

Darum gilt:

* keine `.py`-Dateien im Package
* keine freien Skripte
* keine beliebigen dynamischen Evaluationsdateien

Stattdessen wird die Berechnung deklarativ beschrieben, etwa über:

* `variables.json`
* `formulas.json`
* `quantities.json`
* `constraints.json`
* `measure_logic.json`

Der Library-Service oder spätere Fachservices werten diese Strukturen aus.

Das ist sicherer, wartbarer und besser prüfbar.

---

## 19. Adaptive und dynamische Modelle

Die Library muss auch kontextabhängige Systeme unterstützen.

Beispiel:

* Brückenkappe

Diese ist nicht einfach ein statisches Mesh, sondern ergibt sich aus:

* Unterbau
* Tragkonstruktion
* Breite
* Lagerung
* Randbedingungen

Darum braucht die Library für adaptive Modelle eigene Dateien:

* `dynamic/context_rules.json`
* `dynamic/bindings.json`
* `dynamic/generator.json`

Diese Dateien beschreiben:

* auf welchen Kontexten das Objekt erlaubt ist
* welche Daten aus dem Kontext gelesen werden
* wie daraus Modellparameter abgeleitet werden

Wichtig:

**Adaptive Modelle bleiben deklarativ beschrieben.**
Auch hier soll kein frei ausführbarer Code im Package liegen.

---

## 20. Leichte 3D-Objekte mit geringer technischer Tiefe

Die Library soll nicht nur tiefe technische Bauteile verwalten, sondern auch leichtere 3D-Objekte wie:

* Wasserhähne
* Möbel
* Ausstattung
* einfache Katalogobjekte

Dafür gilt dieselbe Familienlogik, aber mit weniger aktiven Modulen.

Beispiel Wasserhahn:

* Family
* Varianten
* Editorprofil
* Renderprofil
* Bounding-/Collisionprofil
* optional Herstellervertrag

Nicht jedes Objekt braucht:

* Statik
* Energie
* Schallschutz
* Routing
* Bewehrung

Darum ist `vplib.modules.json` so wichtig.

---

## 21. Herstellerfähigkeit im Format

Herstellerdaten werden später separat in der Datenbank gepflegt.
Trotzdem muss die Library-Struktur diese Produktfähigkeit bereits vorbereiten.

Dazu dient insbesondere:

### `manufacturer/contract.json`

Diese Datei beschreibt:

* ob Herstellerprodukte für dieses Family Package zulässig sind
* ob Family- oder Variant-bezogene Produkte möglich sind
* welche Variablen später überschreibbar sind
* welche davon Pflichtfelder für Hersteller sind
* welche Produktkategorien kompatibel sind

### `manufacturer/override_slots.json`

Diese Datei beschreibt:

* welche Variablen Hersteller überschreiben dürfen
* welche Grenzen und Einheiten gelten
* welche Validierungsregeln greifen

Wichtig:

**Der Hersteller ändert später keine Family-Definition, sondern liefert ein Overlay auf definierte Variablen.**

---

## 22. Scanner und Validierung

`vectoplan-library` soll nicht einfach Dateien lesen und blind veröffentlichen.

Der Service braucht eine strenge Scan- und Validierungskette.

### Der Scanner muss prüfen:

1. Struktur
   Ist der Ordnerpfad korrekt?

2. Pflichtdateien
   Sind alle benötigten Dateien vorhanden?

3. JSON-Schemata
   Stimmen Felder, Typen und Wertebereiche?

4. Cross-File-Konsistenz
   Passen Manifest, Module, Varianten und Profile zueinander?

5. Logik
   Sind Maße, Regeln, Varianten und Abhängigkeiten plausibel?

6. Assets
   Existieren referenzierte Render- und Vorschauartefakte?

### Wichtige Regel

Nur **gültige** Pakete werden veröffentlicht.
Ungültige Pakete:

* werden protokolliert
* erscheinen nicht in der produktiven Library
* ersetzen keinen gültigen Altstand

---

## 23. Datenbankrolle des Library-Service

Die Datenbank dient nicht einfach als Cache des Dateisystems.

Sie wird zur **veröffentlichten Library-Wahrheit**.

Der Datenbankstand enthält perspektivisch:

* Families
* Family-Revisions
* Varianten
* resolved Varianten
* Scanläufe
* Scanfehler
* Veröffentlichungsstatus
* spätere Herstelleroverlays
* Inventarzustände

Wichtig:

Die Datenbank speichert nicht nur Rohdateien, sondern **normalisierte und validierte Library-Zustände**.

---

## 24. Verhältnis zur Creative Library im Frontend

Die Creative Library im Frontend oder Editor soll **nicht** direkt aus `/src` lesen.

Der Pfad lautet immer:

**`/src` → Scanner → Validierung → Datenbank → API → Frontend**

Das ist wichtig, damit:

* nur gültige Packages sichtbar werden
* Family- und Variantendaten normalisiert werden
* Suche und Filter funktionieren
* Freigabezustände sauber bleiben
* Herstellerfähigkeit später integrierbar ist

---

## 25. Inventarzustand für den späteren Editor

`vectoplan-library` soll eine Route bereitstellen, die den aktuellen Inventarzustand maschinenlesbar ausgibt.

Das ist wichtig für die spätere Editor-Integration.

Ein Inventarslot sollte perspektivisch mindestens enthalten:

* Slotindex
* `family_id`
* `variant_id`
* Label
* Domain
* Kategorie
* Anzeigeinformationen
* Zeitstempel

Dadurch kann der Editor später:

* aktive Slots laden
* Creative-Mode-Elemente verwenden
* Variantenzustände verstehen
* Slotwechsel und Toollogik sauber synchronisieren

---

## 26. Verhältnis zum Core

`vectoplan-library` liefert wiederverwendbare Definitionen, aber keine Projektwahrheit.

Der Core speichert später z. B. bei einer Projektinstanz:

* `family_id`
* `variant_id`
* projektbezogene Overrides
* bestätigte Verwendung

Die Library speichert dagegen:

* die Family selbst
* die Varianten
* technische Grundprofile
* Renderprofile
* Vertragsfähigkeit für Hersteller

Wichtig:

**Der Core verwendet Library-Definitionen, besitzt sie aber nicht als Primärquelle.**

---

## 27. Verhältnis zum Editor

Der Editor verwendet `vectoplan-library` für:

* Reiter
* Kategorien
* Unterkategorien
* Creative-Grid-Inhalte
* Inventar
* Family-/Variantenauswahl
* Placement-Metadaten
* Preview-Darstellung

Wichtig:

Der Editor besitzt die Library nicht selbst.
Er liest veröffentlichte Daten aus dem Library-Service.

---

## 28. Verhältnis zum Converter

Der Converter kann Library-Daten später brauchen für:

* Export-Mappings
* Render-Prototypen
* Austauschformate
* Artefakt-Erzeugung

Aber:

**`vectoplan-library` bleibt Owner der Library-Semantik.**
Der Converter verwendet diese Daten nur für Ableitungen.

---

## 29. Einheitliche Python-/Flask-Service-Struktur

Auch `vectoplan-library` soll dieselbe Grundstruktur wie die restlichen VECTOPLAN-Services verwenden.

Empfohlene Service-Struktur:

```text
vectoplan-library/
  AI.md
  README.md
  Dockerfile
  entrypoint.sh
  requirements.txt
  wsgi.py
  app.py
  config.py
  extensions.py

  bootstrap/
    __init__.py
    startup.py
    health.py

  routes/
    __init__.py
    health.py
    admin.py
    api.py
    scanner.py
    inventory.py
    manufacturers.py

  domain/
    __init__.py
    entities/
    value_objects/
    enums/

  services/
    __init__.py
    scanner/
    validation/
    publication/
    inventory/
    read_models/

  repositories/
    __init__.py
    sql/
    storage/

  models/
    __init__.py
    ...

  schemas/
    __init__.py
    requests/
    responses/

  clients/
    __init__.py
    core_client.py
    editor_client.py
    converter_client.py

  tasks/
    __init__.py
    jobs.py

  utils/
    __init__.py
    logging.py
    ids.py
    time.py

  src/
    library_catalog/
      _schemas/
      _taxonomy/
      _shared/
      _examples/
      hochbau/
      tiefbau/
      ingenieurbau/

  templates/
    library_admin/
      ...

  static/
    library_admin/
      ...
```

---

## 30. Was `vectoplan-library` als Service konkret leisten soll

Die Kernaufgaben des Services sind:

### 30.1 Library-Format definieren und tragen

* VPLIB-Spezifikation
* Family-/Variant-Struktur
* Modulaktivierung
* Schema-Versionen

### 30.2 Paketstrukturen in `/src` verwalten

* Scannerpfade
* Taxonomie
* Beispiele
* Shared-Definitionen

### 30.3 Scan und Validierung

* Family Packages erkennen
* Varianten auflösen
* Schema prüfen
* Plausibilität prüfen
* Fehler protokollieren

### 30.4 Veröffentlichung in die Datenbank

* gültige Pakete veröffentlichen
* alte gültige Revisionen nicht zerstören
* Revisionierung und Nachvollziehbarkeit sichern

### 30.5 Read-APIs für Frontend und Editor

* Reiter
* Kategorien
* Unterkategorien
* Families
* Varianten
* Detailansichten
* Suche und Filter

### 30.6 Inventar-APIs

* Slotzustände
* aktive Family-/Variantenauswahl
* Übergabe an spätere Editorkontexte

### 30.7 Herstellerfähigkeit vorbereiten

* Contracts
* Override-Slots
* später Produktoverlays ermöglichen

### 30.8 Adaptive Modelle vorbereiten

* Kontextregeln
* Bindungen
* Generatorparameter

---

## 31. Was `vectoplan-library` bewusst noch nicht vollständig leisten soll

In der frühen Ausbaustufe sollte der Service noch nicht alles vollständig umsetzen.

Noch nicht Kernziel der ersten Stufen sind:

* vollständige Hersteller-Preisportale
* Produkt-Matching-Engine
* echte Kostenoptimierung
* vollständige Statik-Solver
* vollständige Energie-Solver
* vollständige Schallschutz-Solver
* vollständige Bewehrungsplanung

Diese Dinge sollen vorbereitet werden, aber die erste Priorität ist:

**saubere Struktur vor voller Fachsimulation**

---

## 32. Empfohlene Entwicklungsreihenfolge

Eine sinnvolle Reihenfolge für den Service ist:

### Phase 1 – Format und Struktur

* VPLIB-Spezifikation
* Family-/Variant-Modell
* Taxonomie
* Pflicht- und Optionsmodule
* JSON-Schemata

### Phase 2 – Referenzpakete

* mindestens vier Family Packages als Referenz
* Wandfamilie
* 3D-Objekt
* Tiefbauobjekt
* adaptives Modell

### Phase 3 – Scanner und Validierung

* Strukturprüfung
* Schema-Prüfung
* Cross-File-Prüfung
* Logik-Prüfung

### Phase 4 – Datenbank und Veröffentlichung

* Family-Revisionsmodell
* Variantenmodell
* veröffentlichte Datensicht

### Phase 5 – Read-APIs

* Creative-Library-Daten
* Details
* Varianten
* Suche / Filter

### Phase 6 – Inventarzustand

* Slotstruktur
* Family-/Variant-Zustand
* spätere Editor-Schnittstelle

### Phase 7 – Herstellerverträge

* Contract- und Override-Logik
* vorbereitete Andockfähigkeit

### Phase 8 – Herstellerportal

* Auswahlwizard
* Variablenpflege
* Gebietsauswahl
* spätere Produktdaten

### Phase 9 – Adaptive Engine

* Kontextregeln
* Generatorlogik
* Bindungen

### Phase 10 – tiefe Fachmodule

* Statik
* Energie
* Akustik
* Routing
* Bewehrung

---

## 33. Prägnantes Gesamtbild

Der belastbare Gesamtbefund für `vectoplan-library` lautet:

**`vectoplan-library` ist der kanonische Bibliotheksservice von VECTOPLAN. Er verwaltet wiederverwendbare Family-/Variant-Pakete für Blöcke, Modelle und adaptive Systeme, validiert deren strukturierte VPLIB-Definitionen, veröffentlicht gültige Einträge in die Datenbank und liefert sie an Creative Library, Inventar, Editor und spätere Produkt- und Herstellerlogik aus.**

Besonders wichtig ist:

* Die Library besitzt die Family-/Variant-Welt.
* Projekte gehören nicht der Library.
* Herstellerdaten werden später als Overlays geführt, nicht als Primärdefinition.
* Es gibt feste Kernvariablen.
* Das Format ist stark strukturiert, aber modular erweiterbar.
* Packages enthalten deklarative Daten, keinen ausführbaren Code.
* Adaptive Modelle sind eine eigene Klasse, keine Sonderhacks.

---

## 34. Kurzfassung für Reviewer

* `vectoplan-library` ist der Owner der wiederverwendbaren Objekt- und Bauteilwelt von VECTOPLAN.
* Die Library arbeitet mit einem eigenen Paketformat `VPLIB`.
* VPLIB organisiert **Families**, **Variants** und später **Product Overlays**.
* Ein Element wie `ziegelwand` ist eine Familie; `24cm_tragend` ist eine Variante.
* Die Library verwaltet technische Profile, Editorprofile, Berechnungsprofile, optionale Analyseprofile und adaptive Regeln.
* Das Format ist deklarativ und erlaubt keine `.py`- oder sonstigen ausführbaren Paketdateien.
* Scanner und Validierung prüfen die Ordnerstruktur unter `src/library_catalog/`.
* Nur gültige Pakete werden in die Datenbank veröffentlicht.
* Die Creative Library liest später aus der Datenbank, nicht direkt aus dem Dateisystem.
* Der Editor verwendet Family- und Variantendaten, besitzt sie aber nicht selbst.
* Herstellerdaten werden später separat in der Datenbank als Overlays gespeichert.

---

## 35. Nächster sinnvoller Schritt

Der nächste sinnvolle Schritt nach dieser Datei ist:

1. eine formale **`VPLIB-SPEC.md`** anzulegen
2. darin die Paketstruktur, Pflichtdateien, Objektklassen und Core-Variablen exakt festzuschreiben
3. anschließend erste Referenzpakete unter `src/library_catalog/` anzulegen
4. danach Scanner- und Validierungslogik darauf aufzubauen

```

Als nächste Datei empfehle ich: `services/vectoplan-library/VPLIB-SPEC.md`  
Dort sollten wir die Family-/Variant-Struktur jetzt formal und exakt definieren.
```
