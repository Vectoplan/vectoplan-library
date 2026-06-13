# IST-Zustand `services/vectoplan-library/src/vplib`

Stand: nach Analyse aller gelieferten Dateien  
Scope: ausschließlich `services/vectoplan-library/src/vplib`  
Zweck: technische Bestandsaufnahme, Architekturkarte und Arbeitsgrundlage, damit Entwickler nicht jede einzelne Datei erneut öffnen müssen.

---

## 1. Kurzfazit

`src/vplib` ist der interne Kern der VECTOPLAN-Library-Package-Engine. Der Code ist als eigenständiges Python-Package aufgebaut und bildet den kompletten Lebenszyklus eines modularen VPLIB-Packages ab:

```text
Raw Input / Dict
  ↓
CreateRequest
  ↓
PackageContext
  ↓
ObjectKindProfile
  ↓
ModulePlan / VariantSet / AssetPlan / PathPlan
  ↓
CreationPlan / PackagePlan
  ↓
DocumentBundle
  ↓
Validators
  ↓
Creators
  ↓
Directory Package / .vplib Archive
  ↓
Sources Scanner / Loader
  ↓
später: DB-Sync / Publication
```

Die zentrale Architekturregel lautet:

```text
models/*      modelliert strukturierte Daten.
domain/*      definiert kanonische Vokabulare und Regeln.
profiles/*    definiert object_kind-spezifische Package-Profile.
planning/*    erzeugt Pläne.
defaults/*    erzeugt JSON-Dokumentpayloads.
validators/*  prüft Pläne, Bundles und Dokumente.
creators/*    schreibt Dateien und Archive.
sources/*     scannt und lädt vorbereitete Packages.
vplib_id_service.py erzeugt und validiert die technische Package-ID.
```

Wichtig: Die meisten Schichten schreiben bewusst **nicht** ins Dateisystem. Tatsächliches Schreiben findet im Kern nur in `creators/*` und beim Laden vorbereiteter Source-Packages über `sources/source_loader.py` statt.

---

## 2. Zentrale Begriffe

### VPLIB

`VPLIB` steht für **VECTOPLAN Library Package**. Es existiert in zwei Formen:

```text
Directory Package:
src/library_catalog/hochbau/waende/ziegelwand/

Archive Package:
ziegelwand.vplib
```

Ein `.vplib` ist technisch ein ZIP-kompatibles Archiv mit stabilen POSIX-Pfaden.

### Package

Ein Package ist ein wiederverwendbares Library-Objekt mit Manifest, Modulen, Family-Daten, Varianten, Editor-Metadaten, Render-/Physical-/Materialdaten, Berechnungsdaten, optionaler Dynamic-Logik und Hersteller-Contract.

### Family

Die Family ist das semantische Objekt:

```text
Family: ziegelwand
```

Die Family enthält Identität, Klassifikation, Grundlogik, Editorverhalten und technische Basisdaten.

### Variant

Eine Variante ist keine neue Family. Sie enthält nur Overrides gegenüber Family oder Default-Struktur:

```text
Family:  ziegelwand
Variant: 24cm_tragend
Override:
  physical.wall_thickness_m = 0.24
  material.raw_density_kg_m3 = ...
```

### Product Overlay

Herstellerdaten werden perspektivisch nicht direkt in die neutrale Family geschrieben, sondern als Overlay gedacht:

```text
Family → Variant → Product Overlay
```

### `vplib_uid`

`vplib_uid` ist die unveränderliche technische Paket-ID.

Sie ist **nicht** dasselbe wie:

```text
package_id
family_id
family_slug
label
display_name
```

Diese Werte dürfen fachlich migrieren. `vplib_uid` darf das nicht.

---

## 3. Harte Architektur-Invarianten

Diese Regeln ziehen sich durch fast alle Dateien:

```text
1. VPLIB-Packages enthalten keine frei ausführbare Logik.
2. JSON-Dokumente sind deklarativ.
3. defaults/* erzeugt Dokumentpayloads, schreibt aber nichts.
4. planning/* erzeugt Pläne, schreibt aber nichts.
5. validators/* validiert, schreibt aber nichts.
6. models/* modelliert Daten, schreibt aber nichts.
7. creators/* schreibt Dateien und Archive.
8. sources/source_scanner.py scannt, schreibt aber nichts.
9. sources/source_loader.py lädt gescannte Packages in einen Library-Katalog und schreibt dabei.
10. vplib_uid entsteht im Manifest-/Bundle-/Create-Flow.
11. Scanner, Loader, Validatoren und Datenbank erzeugen keine neue vplib_uid.
12. Fehlende oder ungültige vplib_uid blockiert Validierung.
13. Der Grid-Footprint bleibt die Platzierungswahrheit.
14. Sichtbare Geometrie, GLB, Bounds und Physical-Daten dürfen den Grid-Footprint nicht widersprüchlich überschreiten.
15. Varianten dürfen keine Family-/Package-Identität überschreiben.
16. Manufacturer-Overlays dürfen nur freigegebene Felder überschreiben.
17. Adaptive Systeme sind deklarativ und require dynamic/*.json.
```

---

## 4. Gesamtordnerstruktur

```text
src/vplib/
  __init__.py
  vplib_id_service.py

  domain/
    __init__.py
    classification.py
    field_names.py
    module_names.py
    object_kinds.py
    package_paths.py
    placement_modes.py
    units.py

  profiles/
    __init__.py
    base_profiles.py
    cell_block_profile.py
    multi_cell_module_profile.py
    catalog_object_profile.py
    adaptive_system_profile.py
    profile_resolver.py

  models/
    asset_reference.py
    create_request.py
    module_plan.py
    package_context.py
    package_plan.py
    package_result.py
    validation_result.py
    variant_definition.py

  planning/
    __init__.py
    creation_planner.py
    module_planner.py
    variant_planner.py
    asset_planner.py
    path_planner.py

  defaults/
    __init__.py
    analysis_defaults.py
    calculation_defaults.py
    document_bundle.py
    dynamic_defaults.py
    editor_defaults.py
    family_defaults.py
    manifest_defaults.py
    manufacturer_defaults.py
    material_defaults.py
    module_defaults.py
    physical_defaults.py
    render_defaults.py
    variant_defaults.py

  validators/
    __init__.py
    schema_validator.py
    semantic_validator.py
    asset_validator.py
    package_validator.py

  creators/
    __init__.py
    file_writer.py
    package_creator.py
    archive_creator.py

  sources/
    __init__.py
    source_scanner.py
    source_loader.py
```

---

## 5. Zielstruktur eines VPLIB-Packages

Ein vollständiges Package kann diese Dateien enthalten:

```text
vplib.manifest.json
vplib.modules.json

family/
  identity.json
  classification.json
  lifecycle.json
  aliases.json
  metadata.json

variants/
  index.json
  default.json
  <variant_id>.json

editor/
  inventory.json
  placement.json
  targeting.json
  anchors.json
  sockets.json
  ports.json
  tools.json
  hotbar.json

render/
  render_variants.json
  bounds.json
  materials.json
  lod.json
  icons/
  previews/
  textures/
  models/
  assets/

physical/
  base.json
  dimensions.json
  collision.json
  occupancy.json
  layers.json
  mass.json
  bounds.json
  footprint.json

material/
  base.json
  performance.json
  surfaces.json
  layers.json
  finishes.json

calculation/
  variables.json
  formulas.json
  quantities.json
  measure_logic.json
  constraints.json
  units.json
  cost_factors.json

analysis/
  statics/
    profile.json
  routing/
    profile.json
  reinforcement/
    profile.json
  checks.json
  assumptions.json

dynamic/
  context_rules.json
  bindings.json
  generator.json
  parameters.json
  constraints.json
  rule_graph.json
  host_contract.json

manufacturer/
  contract.json
  override_slots.json
  product_fields.json
  product_categories.json
  branding.json
  assets.json

docs/
  ...

tests/
  ...
```

Nicht jedes Package enthält alle Dateien. Welche Dateien erwartet werden, ergibt sich aus:

```text
object_kind
  ↓
ObjectKindProfile
  ↓
ModulePlan
  ↓
PackagePlan
  ↓
DocumentBundle Options
```

---

## 6. Top-Level-API

### Datei

```text
src/vplib/__init__.py
```

### Rolle

Die Datei ist die öffentliche Fassade des VPLIB-Kerns. Sie bündelt stabile Einstiegspunkte aus:

```text
defaults
validators
creators
sources
vplib_id_service
```

### Typische Imports

```python
from vplib import create_vplib
from vplib import validate_vplib_documents
from vplib import scan_vplib_sources
from vplib import load_vplib_sources
from vplib import build_full_document_bundle

from vplib import generate_vplib_uid
from vplib import ensure_vplib_uid
from vplib import validate_vplib_uid
from vplib import ensure_mapping_vplib_uid
```

### Subpackages

```text
defaults     -> .defaults
validators   -> .validators
creators     -> .creators
sources      -> .sources
id_service   -> .vplib_id_service
```

Komfort-Aliase:

```text
ids
vplib_id_service
```

### Robustheitsmuster

`__init__.py` arbeitet mit:

```text
Lazy Imports
Symbol Registry
Health Check
Ready Assertion
Cache Clearing
defensiver Metadata-Serialisierung
```

Das Ziel ist: Ein defektes optionales Subpackage soll nicht sofort den Import von `vplib` zerstören.

---

## 7. VPLIB-ID-Service

### Datei

```text
src/vplib/vplib_id_service.py
```

### Rolle

Diese Datei ist die technische Identitätsquelle für VPLIB-Packages.

### Grundsatz

```text
vplib_uid ist die unveränderliche technische Paket-ID.
family_id, package_id, slug oder label sind semantische IDs und dürfen sich ändern.
```

### Erzeugung

`generate_vplib_uid()` erzeugt eine UUID-artige ID. Die ID sieht aus wie eine RFC-4122-kompatible UUID, ist lowercase und enthält keine direkt lesbaren Zeit-/Zufallsinformationen.

Intern fließen ein:

```text
Zeitstempel in Nanosekunden
UTC-Diagnosezeit
kryptografischer Zufall
prozesslokaler Counter
PID
Thread-ID
perf_counter_ns
Hashing über BLAKE2b
RFC-4122 Version-/Variant-Bits
```

### Wichtigste Funktionen

```text
generate_vplib_uid()
generate_unique_vplib_uid(existing_uids=...)
ensure_vplib_uid(value=None, existing_uids=None)

normalize_vplib_uid(value)
is_valid_vplib_uid(value)
validate_vplib_uid(value)
validate_vplib_uid_result(value)

get_vplib_uid_from_mapping(data)
require_vplib_uid_from_mapping(data)
ensure_mapping_vplib_uid(data, overwrite_invalid=False)
set_mapping_vplib_uid(data, uid, overwrite=False)
remove_mapping_vplib_uid(data)

compare_vplib_uids(left, right)
assert_same_vplib_uid(left, right)
build_vplib_uid_payload_fragment(uid=None)
```

### Unterstützte Felder

```text
vplib_uid
vplibUid
vplib_uid_v1
```

Nicht bewusst akzeptiert:

```text
id
package_id
family_id
```

Grund: Diese Felder haben andere fachliche Bedeutungen.

### Wichtiges Verhalten

```text
ensure_mapping_vplib_uid(...)
  - vorhandene gültige ID wird normalisiert und behalten
  - fehlende ID wird neu erzeugt
  - vorhandene ungültige ID schlägt standardmäßig fehl
  - ungültige ID wird nur ersetzt, wenn overwrite_invalid=True
```

### Architekturregel

```text
Nur der Create-/Manifest-/Bundle-Flow darf eine fehlende vplib_uid erzeugen.
Validatoren und Scanner erzeugen keine fehlende ID.
```

---

## 8. Domain-Schicht

```text
src/vplib/domain/
```

### Rolle

Die Domain-Schicht enthält kanonische Vokabulare, Taxonomien, Pfadregeln, Object-Kinds, Placement Modes, Module und Einheiten.

Sie ist bewusst leichtgewichtig und dependency-arm.

### `domain/__init__.py`

Lazy-Reexport für:

```text
classification
field_names
module_names
object_kinds
package_paths
placement_modes
units
```

Enthält:

```text
get_domain_health()
assert_domain_ready()
clear_domain_caches()
```

### `classification.py`

Definiert die VPLIB-Taxonomie:

```text
domain / tab -> category -> subcategory
```

Top-Level-Domains:

```text
hochbau
tiefbau
ingenieurbau
```

Beispiele:

```text
hochbau/waende/mauerwerk
tiefbau/leitungen/wasserleitung
ingenieurbau/bruecken/brueckenkappe
```

Aufgaben:

```text
Klassifikationspfade bauen
Aliase normalisieren
Umlaute und technische Keys normalisieren
classification payloads für family/classification.json erzeugen
```

### `field_names.py`

Definiert kanonische JSON-Feldnamen.

Beispielgruppen:

```text
system
identity
classification
object_kind
grid
variant
editor
placement
render
asset
physical
material
calculation
analysis
dynamic
manufacturer
validation
report
```

Regel:

```text
Aliase sind für Parsing/Migration erlaubt.
Serialisierung soll kanonische Feldnamen verwenden.
```

### `module_names.py`

Definiert logische Module:

```text
manifest
modules
family
variants
editor
render
physical
material
calculation
analysis
dynamic
manufacturer
docs
tests
```

Core-Module:

```text
manifest
modules
family
variants
editor
manufacturer
```

Enthält Regeln für:

```text
required/optional modules
Abhängigkeiten
Modulreihenfolge
Core-Validierung
Modulmanifest-Payload
```

### `object_kinds.py`

Definiert die vier kanonischen Objektarten:

```text
cell_block
multi_cell_module
catalog_object
adaptive_system
```

Objektarten:

```text
cell_block
  Raster-Bauteil, typischerweise 1x1x1.

multi_cell_module
  Zusammenhängendes Objekt mit mehreren Rasterzellen, aber eine semantische Instanz.

catalog_object
  Freies Objekt oder Ausstattung innerhalb eines Footprints.

adaptive_system
  Kontext-/hostabhängiges deklaratives System.
```

### `package_paths.py`

Definiert die physische Package-Struktur.

Aufgaben:

```text
package-relative Pfade normalisieren
absolute Pfade verbieten
Parent-Traversal verbieten
Modulordner kennen
required/optional/generated files liefern
Asset-Pfade prüfen
ausführbare Dateiendungen verbieten
```

Explizit problematische Endungen:

```text
.py
.sh
.js
.exe
.dll
.ps1
.rb
```

### `placement_modes.py`

Definiert Placement Modes:

```text
centered
bottom_aligned
top_aligned
surface_aligned
fill_block
```

Regel:

```text
Placement Mode beschreibt die Ausrichtung innerhalb des Grid-Footprints.
Der Grid-Footprint bleibt die Platzierungswahrheit.
```

### `units.py`

Definiert ein kontrolliertes Einheitensystem.

Beispiele:

```text
none
ratio
percent
count
m / cm / mm
m2 / cm2 / mm2
m3 / cm3 / mm3
kg / g / t
kg/m3
N / kN
Pa / kPa / MPa / GPa
W / kW
J / kJ / kWh
K / C
deg / rad
EUR / EUR/m2 / EUR/m3 / EUR/pcs
```

Keine Wechselkurslogik. Nur sichere, eindeutig definierte Konvertierungen.

---

## 9. Profile-Schicht

```text
src/vplib/profiles/
```

### Rolle

Profile definieren objektartabhängige Package-Regeln:

```text
Welche Module sind required?
Welche Module sind recommended?
Welche Module sind optional?
Welche Module sind ausgeschlossen?
Welche Dokumente sind Pflicht?
Welche Assets sind erlaubt/empfohlen/Pflicht?
Welche Defaults gelten?
Welche Validierungsregeln greifen?
```

Profile schreiben nichts. Sie sind Regel- und Planungsdaten.

### `profiles/__init__.py`

Lazy-Reexport für:

```text
base_profiles
cell_block_profile
multi_cell_module_profile
catalog_object_profile
adaptive_system_profile
profile_resolver
```

Health-, Status- und Cache-Funktionen sind vorhanden.

### `base_profiles.py`

Definiert die generische Profilbasis.

Zentrale Klassen:

```text
ObjectKindProfile
ProfileModuleRule
ProfileDocumentRule
ProfileAssetRule
ProfileValidationRule
ProfileDefaults
```

Core-Module werden immer abgesichert:

```text
manifest
modules
family
variants
editor
manufacturer
```

Gemeinsame Validierungsregeln:

```text
core_modules_present
required_files_present
no_executable_files
variant_overrides_only
```

`ObjectKindProfile.to_module_plan_entries()` wandelt Profilregeln in `ModulePlanEntry`-Objekte um.

### `cell_block_profile.py`

Profil für:

```text
object_kind = cell_block
```

Typische Fälle:

```text
wall block
slab block
road block
floor block
simple building component
```

Module:

```text
required:
  manifest
  modules
  family
  variants
  editor
  render
  physical
  manufacturer

recommended:
  material
  calculation

optional:
  analysis
  docs
  tests

excluded:
  dynamic
```

Defaults:

```text
recommended placement: fill_block
default grid: 1x1x1
fit_mode: fill_footprint
fallback_color: #9CA3AF
```

Regeln:

```text
cell_block sollte 1x1x1 nutzen.
sichtbare Bounds müssen in den Grid-Footprint passen.
Texture, Model oder fallback_color muss vorhanden sein.
Calculation bleibt deklarativ.
dynamic ist ausgeschlossen.
```

### `multi_cell_module_profile.py`

Profil für:

```text
object_kind = multi_cell_module
```

Typische Fälle:

```text
stair core
shaft
foundation module
technical block
multi-cell prefabricated component
```

Module:

```text
required:
  manifest
  modules
  family
  variants
  editor
  render
  physical
  manufacturer

recommended:
  material
  calculation

optional:
  analysis
  docs
  tests

excluded:
  dynamic
```

Zusätzliche Pflicht:

```text
physical/occupancy.json
```

Defaults:

```text
recommended placement: bottom_aligned
default grid: 2x1x2
```

Regeln:

```text
mindestens eine Grid-Dimension muss > 1 sein.
occupancy und collision sind required.
sichtbare Bounds müssen in den mehrzelligen Footprint passen.
bleibt eine semantische Family/Instance.
```

### `catalog_object_profile.py`

Profil für:

```text
object_kind = catalog_object
```

Typische Fälle:

```text
faucet
furniture
fixture
heat pump
cabinet
equipment object
```

Module:

```text
required:
  manifest
  modules
  family
  variants
  editor
  render
  physical
  manufacturer

recommended:
  material

optional:
  calculation
  analysis
  docs
  tests

excluded:
  dynamic
```

Zusätzliche Pflicht:

```text
render/bounds.json
physical/base.json
physical/dimensions.json
physical/collision.json
```

Defaults:

```text
recommended placement: centered
default grid: 1x1x1
```

Regeln:

```text
GLB empfohlen, aber nicht Pflicht.
Fallback-Rendering erlaubt.
render bounds required.
surface_aligned sollte Targeting oder Anchors definieren.
dynamic ist ausgeschlossen.
```

### `adaptive_system_profile.py`

Profil für:

```text
object_kind = adaptive_system
```

Typische Fälle:

```text
bridge cap
railing system
edge beam
pipe or routing system
host-bound adaptive technical system
```

Module:

```text
required:
  manifest
  modules
  family
  variants
  editor
  dynamic
  manufacturer

recommended:
  render
  physical
  material
  calculation

optional:
  analysis
  docs
  tests
```

Pflichtdokumente:

```text
dynamic/context_rules.json
dynamic/bindings.json
dynamic/generator.json
```

Defaults:

```text
recommended placement: surface_aligned
default grid: 1x1x1
declarative_only: true
```

Regeln:

```text
dynamic muss aktiv sein.
Generator muss deklarativ bleiben.
Keine ausführbaren Dateien.
Statische Modelle sind Preview/Prototyp, nicht semantische Wahrheit.
```

### `profile_resolver.py`

Löst `object_kind` auf Profil auf:

```text
cell_block          -> get_cell_block_profile()
multi_cell_module   -> get_multi_cell_module_profile()
catalog_object      -> get_catalog_object_profile()
adaptive_system     -> get_adaptive_system_profile()
```

Pipeline:

```text
object_kind
  ↓
resolve_profile(...)
  ↓
ObjectKindProfile
  ↓
ModulePlan / PackagePlan / Validators
```

---

## 10. Model-Schicht

```text
src/vplib/models/
```

### Rolle

Die Model-Schicht enthält strukturierte, normalisierende Datenmodelle. Sie schreibt nichts.

### `create_request.py`

Kanonischer Eingang für den Create-Flow.

Zentrale Klasse:

```text
CreateRequest
```

Untermodelle:

```text
IdentityRequest
ClassificationRequest
GridFootprintRequest
ModelBoundsRequest
AssetRequest
VisualRequest
PlacementRequest
VariantRequest
VariantsRequest
PhysicalRequest
MaterialRequest
CalculationRequest
DynamicRequest
ManufacturerRequest
CreateOptions
```

Enthält Validierungen für:

```text
family_id / package_id / slug
classification
object_kind
grid footprint
visual bounds gegen Footprint
placement_mode gegen object_kind
adaptive_system braucht dynamic context_rules oder generator metadata
```

### `asset_reference.py`

Deklaratives Asset-Modell.

Zentrale Klassen:

```text
AssetReference
AssetReferenceCollection
AssetSource
AssetTarget
AssetBounds3D
```

Asset-Rollen:

```text
icon
preview
texture
material_texture
glb_model
gltf_model
lod_model
documentation
test_fixture
other
```

Regeln:

```text
Model-Assets brauchen bounds_m.
Model-Assets müssen .glb oder .gltf sein.
AssetTarget muss unter dem angegebenen Modul liegen.
Externe URIs nur bei allow_external_uri.
Forbidden Extensions werden berücksichtigt.
```

### `module_plan.py`

Beschreibt aktive und inaktive Module.

Zentrale Klassen:

```text
ModulePlan
ModulePlanEntry
```

Ein Entry enthält:

```text
module_name
active
requirement
source
reason
required_files
optional_files
generated_files
directories
allowed_subdirectories
```

Requirement-Level:

```text
required
recommended
optional
excluded
```

Aktivierungsquellen:

```text
core
object_kind
profile
user_request
dependency
default
system
```

Regeln:

```text
required -> active=True
excluded -> active=False
Core-Module werden immer ergänzt
Dependencies werden aktiviert
required/optional/generated files kommen aus package_paths
```

### `package_context.py`

Immutable Laufzeitkontext für die Package-Erstellung.

Zentrale Klassen:

```text
PackageContext
PackageRootPaths
PackageIdentityContext
PackageClassificationContext
PackageLocationContext
PackageExecutionContext
```

Der Context enthält:

```text
request
roots
identity
classification
location
execution
object_kind
status
correlation_id
timestamps
metadata
```

Zielordner:

```text
source_root/<domain>/<category>/<family_slug>/
```

Beispiel:

```text
source/hochbau/waende/ziegelwand/
```

Subcategory bleibt in Klassifikationsdokumenten, nicht zwingend im Ordnerpfad.

### `package_plan.py`

Dateisystembezogener Bauplan.

Zentrale Klassen:

```text
PackagePlan
PlannedPath
PlannedDirectory
PlannedFile
PlannedAssetCopy
```

Enthält:

```text
context
module_plan
directories
files
asset_copies
archive_path
validation_required
metadata
```

Baut automatisch aus Context und ModulePlan:

```text
Package root
Modulordner
allowed subdirectories
required files
optional files
generated files
asset files
archive target
```

Wichtig:

```text
PackagePlan enthält keine Datei-Inhalte.
```

### `package_result.py`

Ergebnis-/Report-Modell nach Planung, Erstellung, Validierung oder Archivierung.

Zentrale Klassen:

```text
PackageResult
PackageResultItem
```

Status:

```text
pending
planned
created
validated
archived
skipped
failed
```

Item-Arten:

```text
directory
file
asset
archive
report
```

`success` wird aus Status, Items und ValidationResult abgeleitet.

### `validation_result.py`

Gemeinsame Issue-Sprache.

Zentrale Klassen:

```text
ValidationIssue
ValidationResult
```

Severity:

```text
info
warning
error
fatal
```

Regel:

```text
INFO/WARNING blockieren Erfolg nicht.
ERROR/FATAL blockieren Erfolg.
```

Scopes:

```text
request
context
module_plan
package_plan
package
path
file
json
module
variant
asset
placement
render
physical
material
calculation
analysis
dynamic
manufacturer
archive
system
```

### `variant_definition.py`

Fachliches Variantenmodell.

Zentrale Klassen:

```text
VariantOverride
VariantDefinition
VariantSet
```

Regel:

```text
Varianten enthalten nur Overrides.
Varianten sind keine neuen Families.
```

Forbidden Override Prefixes:

```text
schema_version
vplib_version
package_id
family_id
family_slug
family_name
classification
classification_path
domain
domain_id
domain_label
tab
tab_id
tab_label
category
category_id
category_label
subcategory
subcategory_id
subcategory_label
object_kind
active_modules
required_modules
optional_modules
module_versions
```

Allowed Override Prefixes:

```text
variant
editor
placement
targeting
anchors
sockets
ports
render
physical
material
calculation
analysis
dynamic
manufacturer
```

---

## 11. Planning-Schicht

```text
src/vplib/planning/
```

### Rolle

Planning erzeugt Pläne, schreibt aber nichts.

### `planning/__init__.py`

Lazy-Reexport für:

```text
creation_planner
module_planner
path_planner
variant_planner
asset_planner
```

Enthält Health-, Ready- und Cache-Funktionen.

### `creation_planner.py`

High-Level-Orchestrator.

Pipeline:

```text
raw request / dict
  ↓
CreateRequest
  ↓
PackageContext
  ↓
ObjectKindProfile
  ↓
ModulePlan
  ↓
PackagePlan
  ↓
CreationPlan
```

Hauptfunktion:

```text
plan_vplib_creation(...)
```

`CreationPlan` enthält:

```text
request
context
profile
module_plan
package_plan
validation_result
status
metadata
```

Wichtig: `creation_planner.py` enthält einfache Asset-Copy-Planung für explizite Request-Assets mit `target_path`. Die umfassendere Asset-Planung liegt in `asset_planner.py`.

### `module_planner.py`

Entscheidet aktive Module.

Inputs:

```text
CreateRequest
ObjectKindProfile
ModulePlanningOptions
```

Output:

```text
ModulePlanningResult
  module_plan
  decisions
```

Entscheidungsquellen:

```text
core
profile
request
request_features
options
dependency
system
```

Entscheidungsaktionen:

```text
activate
require
recommend
optional
exclude
```

Request-Feature-Inferenz:

```text
visual data       -> render
assets            -> render
physical values   -> physical
material values   -> material
calculation data  -> calculation
dynamic data      -> dynamic
manufacturer data -> manufacturer
```

### `variant_planner.py`

Plant Variantenstruktur.

Input:

```text
CreateRequest
ObjectKindProfile
VariantPlanningOptions
```

Output:

```text
VariantPlanningResult
  variant_set
  decisions
```

Regeln:

```text
keine Varianten -> default erzeugen
mehrere Varianten -> mode=multiple
allow_multiple_variants=False -> Fehler bei mehreren Varianten
Overrides standardmäßig strict
```

### `asset_planner.py`

Plant Asset-Referenzen und Copy-Ziele.

Input:

```text
CreateRequest.visual
CreateRequest.assets
PackageContext
ObjectKindProfile
```

Output:

```text
AssetPlanningResult
  AssetReferenceCollection
  PlannedAssetCopy[]
  AssetPlanningDecision[]
```

Zielstrategien:

```text
preserve_filename
canonical_role_path
keep_internal_path
```

Kanonische Zielordner:

```text
icon             -> render/icons
preview          -> render/previews
texture          -> render/textures
material_texture -> render/textures
glb_model        -> render/models
gltf_model       -> render/models
lod_model        -> render/models
documentation    -> docs/assets
test_fixture     -> tests/fixtures
other            -> render/assets
```

Regeln:

```text
Lokale Assets können als PlannedAssetCopy geplant werden.
Package-interne Referenzen bleiben intern.
Externe URIs nur bei allow_external_uri=True.
Model-Assets können declared bounds erfordern.
Profilregeln können required/recommended Assets melden.
```

### `path_planner.py`

Plant detaillierte Pfade.

Input:

```text
PackageContext
ModulePlan
optional VariantSet
optional AssetReferenceCollection
```

Output:

```text
PathPlanningResult
  PlannedPathRecord[]
```

Zwecke:

```text
package_root
module_directory
module_subdirectory
required_document
optional_document
generated_document
variant_document
asset_target
archive_target
```

Validierungen:

```text
relative Pfadsicherheit
Modulzugehörigkeit
Duplikate
Datei vs. Ordner
Pfad liegt innerhalb package_dir
Archivpfad darf außerhalb package_dir liegen
```

---

## 12. Defaults-Schicht

```text
src/vplib/defaults/
```

### Rolle

Defaults erzeugen JSON-kompatible Dokumentpayloads. Sie schreiben keine Dateien.

```text
CreateRequest / PackageContext / CreationPlan / Profile / ModulePlan
  ↓
defaults/*
  ↓
DocumentBundle
```

### `defaults/__init__.py`

Lazy-Reexport für alle Default-Module.

Enthält:

```text
get_defaults_health()
assert_defaults_ready()
clear_defaults_caches()
```

### `document_bundle.py`

Zentraler Bündler für Dokumente.

Rolle:

```text
Komponenten / Context / Request / CreationPlan
  ↓
DocumentBundle
  ↓
creators/file_writer.py
```

Wichtig:

```text
DocumentBundle stellt sicher, dass vplib.manifest.json eine gültige vplib_uid enthält.
Fehlende IDs werden im Bundle-/Manifest-Flow erzeugt.
Gültige vorhandene IDs bleiben erhalten.
Ungültige vorhandene IDs sollen nicht still ersetzt werden.
```

Zentrale Ausgaben:

```text
relative_path -> document payload
```

### `manifest_defaults.py`

Erzeugt:

```text
vplib.manifest.json
```

Enthält:

```text
vplib_uid
package_id
family_id
family_slug
family_name
object_kind
classification
version/lifecycle/source metadata
```

Manifest ist die technische Paketklammer.

### `module_defaults.py`

Erzeugt:

```text
vplib.modules.json
```

Beschreibt:

```text
active_modules
required_modules
recommended_modules
optional_modules
excluded_modules
module_versions
module files/directories
validation mode
profile_key
```

Core-Module werden immer required ergänzt.

### `family_defaults.py`

Erzeugt:

```text
family/identity.json
family/classification.json
family/lifecycle.json
family/aliases.json
family/metadata.json
```

Family ist die semantische Objektwahrheit.

### `variant_defaults.py`

Erzeugt:

```text
variants/index.json
variants/default.json
variants/<variant_id>.json
```

Regel:

```text
Variante = Overrides, keine neue Family.
```

### `editor_defaults.py`

Erzeugt:

```text
editor/inventory.json
editor/placement.json
editor/targeting.json
editor/anchors.json
editor/sockets.json
editor/ports.json
editor/tools.json
editor/hotbar.json
```

Kernregel:

```text
Grid-Footprint bleibt Platzierungswahrheit.
Sichtbare Geometrie liegt innerhalb dieses Footprints.
```

### `render_defaults.py`

Erzeugt:

```text
render/render_variants.json
render/bounds.json
render/materials.json
render/lod.json
```

Render beschreibt sichtbare Repräsentation, nicht fachliche Platzierungswahrheit.

Regeln:

```text
custom_glb braucht glb_ref oder model_ref.
Model-Refs brauchen bounds_m.
AssetRefs werden aus icon_ref, preview_ref, texture_ref, glb_ref/model_ref ergänzt.
```

### `physical_defaults.py`

Erzeugt:

```text
physical/base.json
physical/dimensions.json
physical/collision.json
physical/occupancy.json
physical/layers.json
physical/mass.json
physical/bounds.json
physical/footprint.json
```

Beschreibt reale Abmessungen, Kollision, Occupancy, Masse, Dichte, Layer und Footprint.

### `material_defaults.py`

Erzeugt:

```text
material/base.json
material/performance.json
material/surfaces.json
material/layers.json
material/finishes.json
```

Beschreibt neutrale Materialdaten, nicht Herstellerproduktdaten.

### `calculation_defaults.py`

Erzeugt:

```text
calculation/variables.json
calculation/formulas.json
calculation/quantities.json
calculation/measure_logic.json
calculation/constraints.json
calculation/units.json
calculation/cost_factors.json
```

Regel:

```text
Berechnungen sind deklarativ.
Keine ausführbaren Scripts.
Gefährliche Tokens werden blockiert.
```

### `analysis_defaults.py`

Erzeugt:

```text
analysis/statics/profile.json
analysis/routing/profile.json
analysis/reinforcement/profile.json
analysis/checks.json
analysis/assumptions.json
```

Führt keine Berechnungen aus, beschreibt nur Profile und Annahmen.

### `dynamic_defaults.py`

Erzeugt:

```text
dynamic/context_rules.json
dynamic/bindings.json
dynamic/generator.json
dynamic/parameters.json
dynamic/constraints.json
dynamic/rule_graph.json
dynamic/host_contract.json
```

Regel:

```text
declarative_only=true
keine Python-Dateien
keine freien Imports
keine externen Code-Referenzen
```

### `manufacturer_defaults.py`

Erzeugt:

```text
manufacturer/contract.json
manufacturer/override_slots.json
manufacturer/product_fields.json
manufacturer/product_categories.json
manufacturer/branding.json
manufacturer/assets.json
```

Regel:

```text
Hersteller dürfen nur erlaubte Felder überschreiben.
Family-/Package-Identität darf nicht verändert werden.
```

Forbidden Override Prefixes:

```text
schema_version
vplib_version
package_id
family_id
family_slug
family_name
object_kind
classification
domain/category/subcategory
active_modules
required_modules
optional_modules
module_versions
```

---

## 13. Validator-Schicht

```text
src/vplib/validators/
```

### Rolle

Validatoren prüfen vorhandene Datenstrukturen:

```text
documents mapping
DocumentBundle
CreationPlan
PackagePlan
AssetReferenceCollection
```

Sie schreiben keine Dateien und lesen keine echten Assets oder GLB-Geometrie.

### `validators/__init__.py`

Lazy-Reexport für:

```text
schema_validator
semantic_validator
asset_validator
package_validator
```

Komfortfunktionen:

```text
validate_vplib_creation_plan(...)
validate_vplib_documents(...)
validate_vplib_document_bundle(...)
validate_vplib_uid_only(...)
validate_vplib_schema_only(...)
validate_vplib_semantics_only(...)
validate_vplib_assets_only(...)
```

`validate_vplib_uid_only(...)` prüft gezielt nur die Package-ID-Konsistenz.

### `schema_validator.py`

Prüft strukturelle Ebene:

```text
JSON-Kompatibilität
schema_version
bekannte Pflichtfelder pro Dokumenttyp
package-relative Pfadsicherheit
grobe Modulzuordnung
Validatoren aus defaults/*
```

Registry-Mapping:

```text
vplib.manifest.json              -> manifest_defaults.validate_manifest_document
vplib.modules.json               -> module_defaults.validate_modules_document
family/identity.json             -> family_defaults.validate_family_identity_document
family/classification.json       -> family_defaults.validate_family_classification_document
variants/index.json              -> variant_defaults.validate_variant_index_document
variants/<variant_id>.json       -> variant_defaults.validate_variant_document
editor/inventory.json            -> editor_defaults.validate_inventory_document
editor/placement.json            -> editor_defaults.validate_placement_document
render/render_variants.json      -> render_defaults.validate_render_variants_document
render/bounds.json               -> render_defaults.validate_render_bounds_document
physical/base.json               -> physical_defaults.validate_physical_base_document
physical/dimensions.json         -> physical_defaults.validate_physical_dimensions_document
physical/collision.json          -> physical_defaults.validate_physical_collision_document
material/base.json               -> material_defaults.validate_material_base_document
material/performance.json        -> material_defaults.validate_material_performance_document
calculation/variables.json       -> calculation_defaults.validate_variables_document
calculation/formulas.json        -> calculation_defaults.validate_formulas_document
calculation/quantities.json      -> calculation_defaults.validate_quantities_document
calculation/measure_logic.json   -> calculation_defaults.validate_measure_logic_document
manufacturer/contract.json       -> manufacturer_defaults.validate_manufacturer_contract_document
manufacturer/override_slots.json -> manufacturer_defaults.validate_override_slots_document
analysis/...                     -> analysis_defaults validators
dynamic/...                      -> dynamic_defaults validators
```

### `semantic_validator.py`

Prüft dokumentübergreifende fachliche Konsistenz:

```text
Required Core-Dokumente
Manifest/Family/Editor-Identität
Klassifikation und object_kind
active_modules vs vorhandene Dokumente
Variantenindex vs Varianten-Dokumente
Placement/Grid-Footprint
Render-/Physical-Bounds
object_kind-Regeln
Material-/Physical-Konsistenz
Calculation-Referenzen
Manufacturer-Regeln
Dynamic-Regeln
Deklarative Sicherheit
```

Object-Kind-Regeln:

```text
cell_block/multi_cell_module/catalog_object dürfen dynamic nicht aktivieren.
adaptive_system muss dynamic aktivieren.
multi_cell_module muss >1 Zelle in mindestens einer Dimension belegen.
cell_block sollte 1x1x1 bleiben.
```

Sicherheitsprüfung:

```text
Keine ausführbaren Tokens in Expressions.
Keine ausführbaren Dateiendungen in Referenzen.
```

### `asset_validator.py`

Prüft deklarierte Asset-Metadaten:

```text
Rollen
Typen
Dateiendungen
Zielpfade
externe URLs
package-interne Referenzen
verbotene ausführbare Dateien
Model-Bounds
Bounds gegen Grid-Footprint
Profil-Asset-Regeln
Duplikate
```

Wichtig:

```text
keine Dateioperationen
keine GLB-Analyse
nur deklarierte Metadaten
```

### `package_validator.py`

Orchestriert die vollständige Package-Validierung.

Kombiniert:

```text
schema_validator
semantic_validator
asset_validator
PackagePlan-Konsistenz
Pfad-/Dokument-Konsistenz
Modul-/Dokument-Konsistenz
Archivpfadcheck
vplib_uid-Check
```

Zentrale Einstiege:

```text
validate_package_creation_plan(...)
validate_package_documents(...)
validate_package_document_bundle(...)
validate_package_plan_only(...)
validate_vplib_uid_consistency(...)
```

ID-Regeln:

```text
vplib.manifest.json muss vorhanden sein.
Manifest muss Mapping sein.
Manifest muss vplib_uid enthalten.
vplib_uid muss gültig sein.
Context/PackagePlan/Metadata-vplib_uid muss mit Manifest übereinstimmen.
Validator erzeugt keine fehlende vplib_uid.
```

---

## 14. Creator-Schicht

```text
src/vplib/creators/
```

### Rolle

Die Creator-Schicht führt Pläne und Bundles tatsächlich aus. Sie schreibt Dateien, kopiert Assets und erzeugt Archive.

### `creators/__init__.py`

Lazy-Reexport für:

```text
file_writer
package_creator
archive_creator
```

Typische Top-Level-Funktionen:

```text
create_vplib(...)
create_vplib_from_plan(...)
write_vplib_documents(...)
create_vplib_archive(...)
```

### `file_writer.py`

Zentraler sicherer Dateisystemadapter.

Aufgaben:

```text
JSON-Dateien schreiben
Textdateien schreiben
Binary-Dateien schreiben
Assets kopieren
DocumentBundle in Package schreiben
CopyRequests ausführen
dry_run unterstützen
atomare Writes unterstützen
fail / skip / overwrite behandeln
Backups unterstützen
```

Sicherheitsregeln:

```text
package-relative Zielpfade
keine absoluten Package-Pfade
kein Parent-Traversal
Zielpfade bleiben unter package_root
```

### `package_creator.py`

Orchestriert die Package-Erstellung.

Pipeline:

```text
CreateRequest / CreationPlan / DocumentBundle
  ↓
validate before write
  ↓
create directories
  ↓
write documents
  ↓
copy assets
  ↓
optional create archive
  ↓
optional validate after write
```

Wichtig:

```text
package_creator.py erzeugt vplib_uid nicht selbst neu.
Er liest sie aus Bundle, Plan oder Metadata und gibt sie im Result zurück.
```

### `archive_creator.py`

Erzeugt `.vplib` Archive.

Eigenschaften:

```text
ZIP-kompatibel
stabile POSIX-Pfade
Manifest-/Modules-Check
Parent-Traversal-Schutz
temporäre Dateien ausgeschlossen
dry_run
fail / skip / overwrite
atomare Archiv-Erstellung
```

---

## 15. Sources-Schicht

```text
src/vplib/sources/
```

### Rolle

Die Sources-Schicht verarbeitet vorbereitete VPLIB-Source-Packages:

```text
sources/
  wall_24/
    vplib.manifest.json
    vplib.modules.json
    family/identity.json
    variants/default.json
    editor/placement.json
    ...
```

### `sources/__init__.py`

Lazy-Reexport und Komfort-API:

```text
scan_vplib_sources(...)
load_vplib_sources(...)
load_vplib_scan_result(...)
source_candidate_to_bundle(...)
source_scan_result_to_bundles(...)
get_scanned_vplib_uids(...)
get_source_candidate_vplib_uid(...)
```

### `source_scanner.py`

Scannt Source-Verzeichnisse.

Aufgaben:

```text
Source-Root scannen
Package-Kandidaten erkennen
JSON-Dokumente laden
vplib_uid aus Manifest lesen
package-relative Pfade prüfen
optional Schema/Semantik/Asset validieren
doppelte vplib_uid erkennen
DocumentBundle-kompatible Mappings erzeugen
```

Wichtig:

```text
Scanner erzeugt keine vplib_uid.
Fehlende/ungültige vplib_uid macht Kandidaten invalid.
Doppelte vplib_uid im selben Scan erzeugt Fehler.
```

Scan-Modi:

```text
direct_children
recursive
single_package
```

### `source_loader.py`

Lädt gescannte Source-Packages in den Creative-Library-Katalog.

Pipeline:

```text
SourceScanner
  ↓
SourcePackageCandidate
  ↓
DocumentBundle
  ↓
library_catalog_root/<package_dir>/
  ↓
optional .vplib archive
```

Aufgaben:

```text
gültige Candidates laden
Documents über file_writer schreiben
Nicht-JSON-Assets kopieren
optional Archiv erzeugen
skip/fail/overwrite behandeln
dry_run unterstützen
vor/nach Write validieren
```

Wichtig:

```text
source_loader.py erzeugt keine vplib_uid.
Er übernimmt sie aus SourcePackageCandidate / Manifest / DocumentBundle.
```

---

## 16. End-to-End: Create-Flow

Ein typischer Create-Flow sieht so aus:

```text
1. Raw Input / Dict
   ↓
2. create_request_from_mapping(...)
   ↓
3. CreateRequest.normalized()
   ↓
4. create_package_context(...)
   ↓
5. resolve_profile(object_kind)
   ↓
6. build_module_plan(...) oder plan_modules_for_request(...)
   ↓
7. plan_variants_for_request(...)
   ↓
8. plan_assets_for_request(...)
   ↓
9. build_package_plan(...)
   ↓
10. plan_vplib_creation(...)
   ↓
11. build_document_bundle_from_creation_plan(...)
   ↓
12. validate_package_document_bundle(...)
   ↓
13. create_vplib_from_plan(...) / create_vplib_package_from_bundle(...)
   ↓
14. optional create_vplib_archive_from_package(...)
   ↓
15. PackageCreationResult / PackageResult
```

In Code-Nähe:

```python
request = create_request_from_mapping(payload)

plan = plan_vplib_creation(
    request=request,
    service_root=service_root,
)

bundle = build_document_bundle_from_creation_plan(plan)

validation = validate_vplib_document_bundle(
    bundle,
    profile=plan.profile,
)

result = create_vplib_from_plan(plan)
```

Die genaue öffentliche API kann je nach Route über `vplib.__init__.py` oder Subpackages genutzt werden.

---

## 17. End-to-End: Source-Import-Flow

Für vorbereitete Packages:

```text
1. Source root
   ↓
2. scan_vplib_sources(...)
   ↓
3. SourceScanResult
   ↓
4. SourcePackageCandidate[]
   ↓
5. validate_source_scan_uniqueness(...)
   ↓
6. source_scan_result_to_bundles(...)
   ↓
7. load_vplib_sources(...) oder load_vplib_scan_result(...)
   ↓
8. source_loader schreibt Documents und Assets in library_catalog_root
   ↓
9. optional .vplib Archiv
   ↓
10. später: DB-Sync
```

Wichtige Regel:

```text
Source-Packages ohne gültige vplib_uid werden nicht repariert.
Sie sind invalid.
```

---

## 18. End-to-End: Validierungsfluss

### Dokument-Mapping

```text
documents: dict[path, document]
  ↓
validate_vplib_documents(...)
  ↓
package_validator.validate_package_documents(...)
  ↓
document path checks
required document checks
vplib_uid checks
schema_validator
semantic_validator
asset_validator
  ↓
PackageValidationResult
  ↓
ValidationResult
```

### DocumentBundle

```text
DocumentBundle
  ↓
validate_vplib_document_bundle(...)
  ↓
bundle.to_documents()
  ↓
validate_package_documents(...)
```

### CreationPlan

```text
CreationPlan
  ↓
validate_vplib_creation_plan(...)
  ↓
build_document_bundle_from_creation_plan(...)
  ↓
validate_package_creation_plan(...)
```

---

## 19. ID-Fluss

### Erzeugung

```text
CreateRequest / Context / CreationPlan
  ↓
manifest_defaults.py / document_bundle.py
  ↓
ensure_mapping_vplib_uid(...)
  ↓
vplib.manifest.json enthält vplib_uid
```

### Validierung

```text
documents / bundle / creation plan
  ↓
package_validator.validate_vplib_uid_consistency(...)
  ↓
vplib_id_service.normalize_vplib_uid(...)
  ↓
gültig oder blockierender Fehler
```

### Source-Scan

```text
source_scanner.py
  ↓
liest vplib_uid aus vplib.manifest.json
  ↓
fehlend/ungültig = invalid
  ↓
doppelt im Scan = Fehler
```

### Loader

```text
source_loader.py
  ↓
übernimmt vplib_uid
  ↓
spiegelt sie in Target, ItemResult, Metadata, WriteResult, ArchiveResult
```

### DB-Sync später

```text
validiertes Package
  ↓
Scanner / Loader / DB Sync
  ↓
DB übernimmt vplib_uid
  ↓
DB erzeugt sie nicht
```

---

## 20. Object-Kind-abhängige Modulstruktur

### `cell_block`

```text
required:
  manifest
  modules
  family
  variants
  editor
  render
  physical
  manufacturer

recommended:
  material
  calculation

optional:
  analysis
  docs
  tests

excluded:
  dynamic
```

### `multi_cell_module`

```text
required:
  manifest
  modules
  family
  variants
  editor
  render
  physical
  manufacturer

recommended:
  material
  calculation

optional:
  analysis
  docs
  tests

excluded:
  dynamic
```

Sonderregel:

```text
physical/occupancy.json required
mindestens eine Grid-Dimension > 1
```

### `catalog_object`

```text
required:
  manifest
  modules
  family
  variants
  editor
  render
  physical
  manufacturer

recommended:
  material

optional:
  calculation
  analysis
  docs
  tests

excluded:
  dynamic
```

Sonderregel:

```text
render/bounds.json required
GLB recommended, fallback allowed
```

### `adaptive_system`

```text
required:
  manifest
  modules
  family
  variants
  editor
  dynamic
  manufacturer

recommended:
  render
  physical
  material
  calculation

optional:
  analysis
  docs
  tests
```

Sonderregel:

```text
dynamic/context_rules.json required
dynamic/bindings.json required
dynamic/generator.json required
generator.declarative_only must be true
```

---

## 21. Grid-Footprint-Regel

Der Grid-Footprint ist die Platzierungswahrheit.

Das betrifft:

```text
editor/placement.json
render/bounds.json
render/render_variants.json
physical/bounds.json
physical/dimensions.json
asset bounds
```

Grundregel:

```text
visible geometry <= grid footprint
physical bounds should not contradict grid footprint
model assets require declared bounds
```

Für `editor/placement.json` ist zentral:

```json
{
  "grid_footprint_is_placement_truth": true,
  "visual_model_must_remain_inside_footprint": true
}
```

Wenn diese Wahrheit verletzt wird, greifen Semantic- und Asset-Validatoren.

---

## 22. Variantenregel

Varianten dürfen:

```text
render
physical
material
calculation
analysis
dynamic
manufacturer
editor/placement-nahe Felder
```

überschreiben.

Varianten dürfen nicht:

```text
family_id
package_id
family_slug
family_name
classification
object_kind
active_modules
required_modules
module_versions
schema_version
```

überschreiben.

Grund:

```text
Eine Variante ist eine Ausprägung derselben Family.
Sie ist keine neue Family.
```

---

## 23. Manufacturer-Regel

Manufacturer-Daten sind als Contract/Overlay vorbereitet.

Zentrale Dateien:

```text
manufacturer/contract.json
manufacturer/override_slots.json
manufacturer/product_fields.json
manufacturer/product_categories.json
manufacturer/branding.json
manufacturer/assets.json
```

Regeln:

```text
manufacturer_allowed=false -> contract_mode muss disabled sein.
override_slots dürfen nur bei erlaubtem Manufacturer-Modus existieren.
override_slots müssen gegen allowed/forbidden prefixes passen.
required manufacturer product fields können geprüft werden.
```

---

## 24. Dynamic-Regel

Dynamic ist nur für `adaptive_system` required.

Für nicht-adaptive Object-Kinds gilt:

```text
cell_block
multi_cell_module
catalog_object
```

Dynamic ist dort ausgeschlossen bzw. semantisch fehlerhaft/warnend.

Für `adaptive_system` gilt:

```text
dynamic module required
context_rules required
bindings required
generator required
generator.declarative_only=true
keine ausführbaren Referenzen
```

---

## 25. Asset-Regel

Asset-Planung und Asset-Validierung sind getrennt.

```text
asset_planner.py
  plant AssetReferenceCollection und PlannedAssetCopy

asset_validator.py
  prüft deklarierte Asset-Metadaten
```

Keine der beiden Dateien kopiert echte Dateien. Kopieren passiert in:

```text
creators/file_writer.py
sources/source_loader.py
```

Wichtige Rollen:

```text
icon
preview
texture
material_texture
glb_model
gltf_model
lod_model
documentation
test_fixture
other
```

Wichtige Regeln:

```text
Modelle brauchen bounds_m.
Modelle müssen .glb/.gltf sein.
Zielmodul muss zur Rolle passen.
Verbotene Endungen sind blockierend.
Externe URIs sind standardmäßig nicht erlaubt.
```

---

## 26. Schreibverantwortung

### Schreibt nicht

```text
domain/*
profiles/*
models/*
planning/*
defaults/*
validators/*
sources/source_scanner.py
vplib_id_service.py
```

### Schreibt

```text
creators/file_writer.py
creators/package_creator.py
creators/archive_creator.py
sources/source_loader.py
```

### Schreibt was?

```text
file_writer.py
  JSON/Text/Binary-Dateien, Asset-Kopien

package_creator.py
  Package-Ordner, Dokumente, Assets, optional Archiv

archive_creator.py
  .vplib ZIP-kompatibles Archiv

source_loader.py
  geladene Source-Packages in library_catalog_root
```

---

## 27. Robustheitsmuster

Fast jedes Subpackage nutzt:

```text
Lazy Imports über __getattr__
Symbol Registry
Health-Funktion
Ready Assertion
Cache-Clear-Funktion
to_dict()-Serialisierung
defensive Normalisierung
Enum Parser mit Aliases
```

Vorteile:

```text
Subpackage kann isoliert getestet werden.
Defektes optionales Modul blockiert nicht sofort alles.
Admin-UI/Health-Endpoints können Modulstatus anzeigen.
CLI/Tests können assert_*_ready() nutzen.
```

---

## 28. Wichtige Überschneidungen und bewusste Doppelungen

### `PackagePlan` vs. `PathPlanningResult`

Beide planen Pfade, aber mit unterschiedlichem Fokus.

```text
PackagePlan
  Creator-naher Bauplan.
  Enthält Directories, Files, AssetCopies, ArchivePath.

PathPlanningResult
  Detaillierter Pfadrecord-Plan.
  Gut für Diagnose, Admin-UI, Validierung und Preview.
```

### `creation_planner.py` vs. Detailplaner

```text
creation_planner.py
  High-Level-Orchestrator.
  Baut Context, Profile, ModulePlan, PackagePlan.

module_planner.py
variant_planner.py
asset_planner.py
path_planner.py
  Spezialisierte Detailplanung.
```

Perspektivisch kann `creation_planner.py` stärker auf die spezialisierten Planner umgestellt werden, besonders für Assets und Varianten.

### `variant_defaults.py` vs. `variant_definition.py`

```text
variant_definition.py
  Fachliches Variantenmodell.

variant_defaults.py
  Erzeugt JSON-Dokumente für variants/*.json.
```

### `asset_reference.py` vs. `asset_planner.py` vs. `asset_validator.py`

```text
asset_reference.py
  Modelliert Asset-Metadaten.

asset_planner.py
  Plant Referenzen und Copy-Ziele.

asset_validator.py
  Validiert deklarierte Asset-Metadaten.
```

---

## 29. Empfohlene Developer-Einstiege

### Neues Package aus Payload erzeugen

Startpunkte:

```text
models/create_request.py
planning/creation_planner.py
defaults/document_bundle.py
validators/package_validator.py
creators/package_creator.py
```

### Neue Object-Kind hinzufügen

Mindestens prüfen/anpassen:

```text
domain/object_kinds.py
profiles/<new_object_kind>_profile.py
profiles/profile_resolver.py
domain/placement_modes.py
defaults/*
validators/semantic_validator.py
validators/asset_validator.py
planning/module_planner.py
```

### Neues Modul hinzufügen

Mindestens prüfen/anpassen:

```text
domain/module_names.py
domain/package_paths.py
defaults/<module>_defaults.py
defaults/__init__.py
profiles/base_profiles.py
profiles/<object_kind>_profile.py
validators/schema_validator.py
validators/semantic_validator.py
planning/module_planner.py
models/module_plan.py
```

### Neues Dokument hinzufügen

Mindestens prüfen/anpassen:

```text
domain/package_paths.py
defaults/<module>_defaults.py
defaults/document_bundle.py
validators/schema_validator.py
validators/semantic_validator.py
profiles/<object_kind>_profile.py
```

### Neue Asset-Rolle hinzufügen

Mindestens prüfen/anpassen:

```text
models/asset_reference.py
planning/asset_planner.py
validators/asset_validator.py
profiles/base_profiles.py
profiles/<object_kind>_profile.py
defaults/render_defaults.py oder passendes Modul
```

### Neue Hersteller-Overlay-Felder hinzufügen

Mindestens prüfen/anpassen:

```text
defaults/manufacturer_defaults.py
models/variant_definition.py
validators/semantic_validator.py
profiles/<object_kind>_profile.py
```

---

## 30. Bekannte technische Anschlussstellen

### DB-Sync

Außerhalb dieses Dokuments, aber relevant:

```text
validiertes Package
  ↓
source_scanner.py
  ↓
ScanResult
  ↓
DB Sync Service
  ↓
PostgreSQL
```

Die DB sollte verwenden:

```text
vplib_uid als stabile Business-/Technical-ID
revision_hash für Änderungen
package_id/family_id als semantische Felder
```

### Creative Library API

Die dateibasierte Creative-Library-API kann schrittweise auf validierte DB-Read-Models umgestellt werden. Der VPLIB-Kern liefert dafür:

```text
scanner
loader
validators
document bundle
package metadata
vplib_uid
```

---

## 31. Risiken / offene Architekturpunkte

Diese Punkte sind im IST-Zustand sichtbar und sollten bei Weiterentwicklung beachtet werden:

```text
1. creation_planner.py nutzt aktuell nur einfache Asset-Copy-Planung.
   asset_planner.py ist reicher und sollte perspektivisch stärker integriert werden.

2. PathPlanningResult und PackagePlan überschneiden sich.
   Das ist funktional okay, sollte aber bewusst bleiben.

3. Validatoren prüfen deklarierte Metadaten, nicht echte GLB-Geometrie.
   Für echte Geometrieprüfung braucht es später einen separaten Asset-/Model-Analyzer.

4. PackageContext trägt die vplib_uid nicht als primäres Pflichtfeld.
   Die technische ID liegt primär im Manifest/DocumentBundle und kann über Metadata/Plan verglichen werden.

5. SourceScanner repariert fehlende IDs nicht.
   Das ist korrekt, bedeutet aber: Backfill/Migration braucht eigene Reparaturlogik vor dem Scan oder gezielte Tools.

6. Manufacturer-Overlay ist vorbereitet, aber noch kein vollständiger Product-Overlay-Service.

7. Dynamic ist deklarativ modelliert, aber echte adaptive Runtime-Auflösung liegt außerhalb dieses Package-Kerns.

8. Validation kann streng sein; beim Einführen neuer Dokumente müssen Schema- und Semantic-Validatoren synchron gepflegt werden.
```

---

## 32. Kompakte mentale Architekturkarte

```text
                 ┌────────────────────┐
                 │  domain/*          │
                 │  Vokabular/Regeln  │
                 └─────────┬──────────┘
                           │
                 ┌─────────▼──────────┐
                 │  profiles/*        │
                 │  ObjectKindProfile │
                 └─────────┬──────────┘
                           │
┌──────────────┐  ┌────────▼─────────┐
│ raw payload  │─▶│ models/*         │
└──────────────┘  │ CreateRequest    │
                  │ Context/Plan/etc │
                  └────────┬─────────┘
                           │
                  ┌────────▼─────────┐
                  │ planning/*       │
                  │ Pläne erzeugen   │
                  └────────┬─────────┘
                           │
                  ┌────────▼─────────┐
                  │ defaults/*       │
                  │ Dokumente bauen  │
                  └────────┬─────────┘
                           │
                  ┌────────▼─────────┐
                  │ validators/*     │
                  │ Qualität sichern │
                  └────────┬─────────┘
                           │
                  ┌────────▼─────────┐
                  │ creators/*       │
                  │ Dateien schreiben│
                  └────────┬─────────┘
                           │
                  ┌────────▼─────────┐
                  │ sources/*        │
                  │ scannen/laden    │
                  └──────────────────┘
```

ID-Service läuft quer dazu:

```text
vplib_id_service.py
  ├─ generate_vplib_uid()
  ├─ ensure_mapping_vplib_uid()
  ├─ normalize_vplib_uid()
  └─ validate_vplib_uid()
```

---

## 33. Praktische Debug-Reihenfolge

Wenn ein Package nicht funktioniert:

```text
1. Ist vplib.manifest.json vorhanden?
2. Enthält Manifest eine gültige vplib_uid?
3. Ist vplib.modules.json vorhanden?
4. Sind Core-Module active + required?
5. Passt object_kind in Manifest, family/classification und editor/inventory?
6. Sind required Documents für aktive Module vorhanden?
7. Passt editor/placement.json Grid-Footprint?
8. Überschreiten render/physical/model bounds den Footprint?
9. Sind Varianten im Index und als Datei vorhanden?
10. Enthalten Varianten nur erlaubte Overrides?
11. Sind Assets role/type/extension/target-module-kompatibel?
12. Ist dynamic nur bei adaptive_system aktiv?
13. Sind calculation expressions deklarativ?
14. Sind Hersteller-Override-Slots erlaubt?
15. Stimmen PackagePlan-Dateien mit DocumentBundle-Dateien überein?
16. Ist archive_path .vplib, falls Archiv geplant ist?
```

Empfohlene Einstiegstests:

```python
from vplib import validate_vplib_documents
from vplib import validate_vplib_uid_only
from vplib import get_vplib_health

health = get_vplib_health()

uid_check = validate_vplib_uid_only(documents)

result = validate_vplib_documents(
    documents,
    mode="strict",
    validate_schema=True,
    validate_semantics=True,
    validate_assets=True,
    validate_vplib_uid=True,
)
```

---

## 34. Zusammenfassung in einem Satz

`src/vplib` ist eine modular aufgebaute, deklarative Package-Engine für VECTOPLAN-Library-Objekte: Sie normalisiert Requests, löst objektartabhängige Profile auf, plant Module/Varianten/Assets/Pfade, erzeugt JSON-Dokumente, validiert technische und fachliche Konsistenz inklusive stabiler `vplib_uid`, schreibt Packages/Archive über Creator und kann vorbereitete Source-Packages scannen und in einen Library-Katalog laden.
