#!/usr/bin/env python3
"""Build the first VECTOPLAN standard VPLIB library with the real generator.

The script is intentionally deterministic: stable UUIDs, paths, timestamps and
variant IDs make the generated source tree reviewable and safe to rebuild.
"""

from __future__ import annotations

import argparse
import json
import os
import re
import sys
import unicodedata
import uuid
from collections import Counter
from pathlib import Path
from typing import Any, Iterable


SERVICE_ROOT = Path(__file__).resolve().parents[1]
SRC_ROOT = SERVICE_ROOT / "src"
OUTPUT_ROOT = SERVICE_ROOT / "standard_library" / "v1"
PACKAGES_ROOT = OUTPUT_ROOT / "packages"
CATALOG_PATH = OUTPUT_ROOT / "catalog.json"
CREATED_AT = "2026-08-11T00:00:00Z"
NAMESPACE = uuid.uuid5(uuid.NAMESPACE_URL, "https://vectoplan.com/library/standard/v1")

for candidate in (SERVICE_ROOT, SRC_ROOT):
    if str(candidate) not in sys.path:
        sys.path.insert(0, str(candidate))


def _slug(value: str) -> str:
    normalized = unicodedata.normalize("NFKD", value).encode("ascii", "ignore").decode("ascii")
    return re.sub(r"[^a-z0-9]+", "_", normalized.lower()).strip("_") or "variante"


def _variants(rows: Iterable[tuple[str, int, int, int, int]]) -> list[dict[str, Any]]:
    return [
        {
            "label": label,
            "width_mm": width,
            "height_mm": height,
            "depth_mm": depth,
            "thickness_mm": thickness,
        }
        for label, width, height, depth, thickness in rows
    ]


def wall_variants(thicknesses: Iterable[int], *, height: int = 3000) -> list[dict[str, Any]]:
    return _variants(
        (f"{value} mm", 1000, height, value, value)
        for value in thicknesses
    )


def layer_variants(thicknesses: Iterable[int], *, size: int = 1000) -> list[dict[str, Any]]:
    return _variants(
        (f"{value} mm", size, value, size, value)
        for value in thicknesses
    )


def square_variants(sizes: Iterable[int], *, height: int = 3000) -> list[dict[str, Any]]:
    return _variants(
        (f"{value} × {value} mm", value, height, value, value)
        for value in sizes
    )


def pipe_variants(diameters: Iterable[int], *, length: int = 1000) -> list[dict[str, Any]]:
    return _variants(
        (f"DN {diameter}", length, diameter, diameter, max(4, round(diameter * 0.08)))
        for diameter in diameters
    )


def section_variants(rows: Iterable[tuple[str, int, int]]) -> list[dict[str, Any]]:
    return _variants(
        (label, 1000, height, width, min(width, height))
        for label, width, height in rows
    )


def spec(
    domain: str,
    category: str,
    subcategory: str,
    slug: str,
    name: str,
    description: str,
    material_class: str,
    material_type: str,
    material_subtype: str,
    cut_pattern: str,
    surface_pattern: str,
    variants: list[dict[str, Any]],
    *,
    primitive_shape: str = "box",
    color: str = "#9CA3AF",
) -> dict[str, Any]:
    return {
        "domain": domain,
        "category": category,
        "subcategory": subcategory,
        "slug": slug,
        "name": name,
        "description": description,
        "material_class": material_class,
        "material_type": material_type,
        "material_subtype": material_subtype,
        "cut_pattern": cut_pattern,
        "surface_pattern": surface_pattern,
        "variants": variants,
        "primitive_shape": primitive_shape,
        "color": color,
    }


FAMILY_SPECS: list[dict[str, Any]] = [
    # Hochbau
    spec("hochbau", "waende", "mauerwerkswaende", "mauerwerkswand", "Mauerwerkswand", "Allgemeine Mauerwerkswand in üblichen Wandstärken.", "mauerwerk", "brick", "masonry_general", "masonry_general", "brick_running_bond", wall_variants([115, 175, 240, 300, 365, 425]), color="#B7794A"),
    spec("hochbau", "waende", "tragende_waende", "stahlbetonwand", "Stahlbetonwand", "Tragende Stahlbetonwand für Hochbaugrundrisse und Schnitte.", "stahlbeton", "reinforced_concrete", "cast_in_place", "concrete_reinforced", "concrete_plain", wall_variants([160, 180, 200, 240, 250, 300]), color="#A8ADB4"),
    spec("hochbau", "ausbau", "trockenbau", "trockenbauwand", "Trockenbauwand", "Leichte Metallständerwand mit Gipskartonbekleidung.", "sonstiges", "composite", "gypsum_board_partition", "gypsum_board", "line_horizontal", wall_variants([75, 100, 125, 150, 175]), color="#E8E2D0"),
    spec("hochbau", "ausbau", "wandbelaege", "mineralwolldaemmung", "Mineralwolldämmung", "Nichtbrennbare Dämmstofflage für Wand, Decke und Dach.", "sonstiges", "composite", "mineral_wool", "mineral_wool", "insulation_batt", wall_variants([40, 60, 80, 100, 120, 140, 160, 200, 240]), color="#D7C58A"),
    spec("hochbau", "fassade", "putzfassaden", "eps_fassadendaemmung", "EPS-Fassadendämmung", "Wärmedämmplatte aus expandiertem Polystyrol für WDVS.", "kunststoff", "plastic", "eps_insulation", "eps", "rigid_foam", wall_variants([60, 80, 100, 120, 140, 160, 180, 200, 240]), color="#F3F0CF"),
    spec("hochbau", "decken", "massivdecken", "stahlbetondecke", "Stahlbetondecke", "Massive Geschossdecke aus Stahlbeton.", "stahlbeton", "reinforced_concrete", "cast_in_place_slab", "concrete_reinforced", "concrete_plain", layer_variants([160, 180, 200, 220, 240, 250, 280, 300]), color="#A8ADB4"),
    spec("hochbau", "decken", "holzdecken", "holzbalkendecke", "Holzbalkendecke", "Vereinfachte Holzbalkendecke für frühe Planung und Mengenermittlung.", "holz", "wood", "timber_joist_slab", "wood_general", "timber_longitudinal", layer_variants([160, 180, 200, 220, 240, 280, 320]), color="#B98555"),
    spec("hochbau", "decken", "holzdecken", "brettsperrholzdecke", "Brettsperrholzdecke", "Massive CLT-Deckenplatte in gängigen Aufbauten.", "holz", "wood", "cross_laminated_timber", "cross_laminated_timber", "wood_general", layer_variants([80, 100, 120, 140, 160, 180, 200, 240]), color="#C49361"),
    spec("hochbau", "boeden", "estrich", "estrich", "Estrich", "Estrichschicht für schwimmende, beheizte und Verbundaufbauten.", "sonstiges", "composite", "screed", "screed", "line_horizontal", layer_variants([35, 40, 45, 50, 55, 60, 65, 70, 80]), color="#C8C3B8"),
    spec("hochbau", "boeden", "bodenbelaege", "keramikfliese", "Keramikfliese", "Keramischer Boden- oder Wandbelag mit mehreren Plattenstärken.", "sonstiges", "ceramic", "ceramic_tile", "ceramic_tile", "grid_fine", layer_variants([8, 10, 12, 15, 20, 25, 30]), color="#D7C0A5"),
    spec("hochbau", "daecher", "flachdaecher", "bitumenabdichtung", "Bitumenabdichtung", "Mehrlagig nutzbare Bitumenbahn für Flachdachabdichtungen.", "sonstiges", "composite", "bitumen_membrane", "bitumen_membrane", "waterproofing", layer_variants([4, 5, 6, 8, 10, 12]), color="#3F4145"),
    spec("hochbau", "daecher", "gruendach", "gruendachaufbau", "Gründachaufbau", "Vegetations- und Substrataufbau für extensive bis intensive Begrünung.", "sonstiges", "composite", "green_roof_system", "green_roof", "earth", layer_variants([80, 100, 120, 150, 200, 250, 300, 400]), color="#6F8F55"),
    spec("hochbau", "tragwerk", "stuetzen", "stahlbetonstuetze", "Stahlbetonstütze", "Quadratische Stahlbetonstütze in typischen Querschnitten.", "stahlbeton", "reinforced_concrete", "column", "concrete_reinforced", "concrete_plain", square_variants([200, 240, 250, 300, 350, 400, 450, 500]), color="#A8ADB4"),
    spec("hochbau", "tragwerk", "stuetzen", "stahlstuetze", "Stahlstütze", "Vereinfachte Stahlstütze für Vorplanung und Kollisionsprüfung.", "stahl", "steel", "structural_steel_column", "steel", "line_diagonal_45", square_variants([100, 120, 140, 160, 180, 200, 240, 300]), color="#75808A"),
    spec("hochbau", "tragwerk", "traeger", "stahlbetontraeger", "Stahlbetonträger", "Rechteckiger Stahlbetonträger mit mehreren Standardquerschnitten.", "stahlbeton", "reinforced_concrete", "beam", "concrete_reinforced", "concrete_plain", section_variants([("200 × 400 mm", 200, 400), ("240 × 500 mm", 240, 500), ("250 × 600 mm", 250, 600), ("300 × 600 mm", 300, 600), ("300 × 800 mm", 300, 800), ("400 × 800 mm", 400, 800)]), color="#A8ADB4"),
    spec("hochbau", "tragwerk", "fundamente", "streifenfundament", "Streifenfundament", "Durchlaufendes Stahlbetonfundament unter Wänden.", "stahlbeton", "reinforced_concrete", "strip_foundation", "concrete_reinforced", "concrete_plain", _variants([("400 × 300 mm", 1000, 300, 400, 300), ("500 × 300 mm", 1000, 300, 500, 300), ("600 × 350 mm", 1000, 350, 600, 350), ("800 × 400 mm", 1000, 400, 800, 400), ("1000 × 500 mm", 1000, 500, 1000, 500), ("1200 × 600 mm", 1000, 600, 1200, 600)]), color="#A8ADB4"),

    # Tiefbau
    spec("tiefbau", "strassen_wege", "asphalt", "asphaltdeckschicht", "Asphaltdeckschicht", "Deckschicht für Straßen und Verkehrsflächen.", "sonstiges", "asphalt", "wearing_course", "asphalt", "line_horizontal", layer_variants([25, 30, 35, 40, 45, 50]), color="#3E4145"),
    spec("tiefbau", "strassen_wege", "asphalt", "asphaltbinderschicht", "Asphaltbinderschicht", "Binderschicht zwischen Deck- und Tragschicht.", "sonstiges", "asphalt", "binder_course", "asphalt", "line_diagonal_45", layer_variants([40, 50, 60, 70, 80, 90, 100]), color="#46494E"),
    spec("tiefbau", "strassen_wege", "asphalt", "asphalttragschicht", "Asphalttragschicht", "Tragende Asphaltlage für unterschiedliche Belastungsklassen.", "sonstiges", "asphalt", "base_course", "asphalt", "grid_coarse", layer_variants([80, 100, 120, 140, 160, 180, 200, 220]), color="#51545A"),
    spec("tiefbau", "erdbau", "planum", "frostschutzschicht", "Frostschutzschicht", "Ungebundene frostunempfindliche Tragschicht.", "sonstiges", "natural_stone", "frost_protection_gravel", "gravel", "crushed_stone", layer_variants([200, 250, 300, 350, 400, 450, 500, 600]), color="#B6A88D"),
    spec("tiefbau", "strassen_wege", "fahrbahnen", "schottertragschicht", "Schottertragschicht", "Ungebundene Tragschicht aus gebrochenem Gestein.", "sonstiges", "natural_stone", "crushed_stone_base", "crushed_stone", "gravel", layer_variants([120, 150, 180, 200, 250, 300, 350, 400]), color="#9D9588"),
    spec("tiefbau", "strassen_wege", "pflaster", "rechteckpflaster", "Rechteckpflaster", "Beton- oder Natursteinpflaster für Wege und Plätze.", "beton", "concrete", "rectangular_paving", "paving_rectangular", "paving_herringbone", layer_variants([60, 80, 100, 120, 140]), color="#A89F94"),
    spec("tiefbau", "strassen_wege", "bordsteine", "bordstein", "Bordstein", "Vereinfachter Bordstein in gebräuchlichen Profilgrößen.", "beton", "concrete", "curb", "precast_concrete", "concrete_plain", _variants([("8 × 20 cm", 1000, 200, 80, 80), ("10 × 25 cm", 1000, 250, 100, 100), ("12 × 25 cm", 1000, 250, 120, 120), ("15 × 25 cm", 1000, 250, 150, 150), ("15 × 30 cm", 1000, 300, 150, 150), ("18 × 30 cm", 1000, 300, 180, 180)]), color="#B6B6B2"),
    spec("tiefbau", "strassen_wege", "rinnen", "entwaesserungsrinne", "Entwässerungsrinne", "Linienentwässerung für Verkehrs- und Freiflächen.", "beton", "concrete", "drainage_channel", "precast_concrete", "grid_fine", section_variants([("NW 100", 130, 150), ("NW 150", 180, 210), ("NW 200", 240, 280), ("NW 300", 350, 400), ("NW 400", 460, 520)]), color="#AEB2B4"),
    spec("tiefbau", "erdbau", "aufschuettung", "verdichtete_aufschuettung", "Verdichtete Aufschüttung", "Modellkörper für lagenweise verdichtete Erd- und Füllstoffe.", "sonstiges", "generic", "compacted_fill", "earth", "line_horizontal", layer_variants([200, 300, 400, 500, 750, 1000, 1500, 2000]), color="#A57D55"),
    spec("tiefbau", "erdbau", "bodenklassen", "bodenklasse", "Bodenklasse", "Generische Bodenvolumen für frühe Erdbau- und Massenermittlung.", "sonstiges", "generic", "soil", "earth", "sand", _variants([(f"Bodenklasse {value}", 1000, 1000, 1000, 1000) for value in range(1, 8)]), color="#9B7653"),
    spec("tiefbau", "leitungen", "abwasserleitungen", "kanalrohr", "Kanalrohr", "Abwasserrohr als vereinfachter Rohrkörper in gängigen Nennweiten.", "kunststoff", "plastic", "sewer_pipe", "solid", "line_diagonal_45", pipe_variants([100, 125, 150, 200, 250, 300, 400, 500, 600, 800]), primitive_shape="pipe", color="#A76A3F"),
    spec("tiefbau", "leitungen", "wasserleitungen", "wasserleitung", "Wasserleitung", "Druckrohr für Trink- und Betriebswasser.", "kunststoff", "plastic", "water_pressure_pipe", "solid", "line_horizontal", pipe_variants([25, 32, 40, 50, 63, 75, 90, 110, 160, 225]), primitive_shape="pipe", color="#3C82C4"),
    spec("tiefbau", "leitungen", "schutzrohre", "kabelschutzrohr", "Kabelschutzrohr", "Schutzrohr für Strom- und Datenkabel.", "kunststoff", "plastic", "cable_conduit", "solid", "line_vertical", pipe_variants([40, 50, 63, 75, 90, 110, 125, 160, 200]), primitive_shape="pipe", color="#D65C53"),
    spec("tiefbau", "schaechte", "kanalschaechte", "schachtring", "Schachtring", "Runder Fertigteil-Schachtring in Standardnennweiten und Bauhöhen.", "beton", "concrete", "manhole_ring", "precast_concrete", "concrete_plain", _variants([("DN 800 / H 500", 800, 500, 800, 100), ("DN 1000 / H 500", 1000, 500, 1000, 120), ("DN 1000 / H 1000", 1000, 1000, 1000, 120), ("DN 1200 / H 500", 1200, 500, 1200, 140), ("DN 1200 / H 1000", 1200, 1000, 1200, 140), ("DN 1500 / H 1000", 1500, 1000, 1500, 160)]), primitive_shape="cylinder", color="#AEB2B4"),
    spec("tiefbau", "bahninfrastruktur", "gleise", "gleisschotter", "Gleisschotter", "Schotterbett für vereinfachte Bahntrassenmodelle.", "sonstiges", "natural_stone", "rail_ballast", "rail_ballast", "crushed_stone", layer_variants([250, 300, 350, 400, 450, 500]), color="#8E877F"),
    spec("tiefbau", "bahninfrastruktur", "schwellen", "bahnschwelle", "Bahnschwelle", "Vereinfachte Beton- und Holzschwellen mit typischen Abmessungen.", "beton", "concrete", "railway_sleeper", "precast_concrete", "line_horizontal", _variants([("Beton 2400", 2400, 180, 280, 180), ("Beton 2500", 2500, 200, 300, 200), ("Beton 2600", 2600, 220, 320, 220), ("Holz 2500", 2500, 160, 260, 160), ("Holz 2700", 2700, 180, 280, 180)]), color="#9C9386"),

    # Ingenieurbau
    spec("ingenieurbau", "bruecken", "ueberbau", "brueckenplatte", "Brückenplatte", "Massive Stahlbetonplatte für Brückenüberbauten.", "stahlbeton", "reinforced_concrete", "bridge_deck", "concrete_reinforced", "concrete_plain", layer_variants([200, 250, 300, 350, 400, 450, 500, 600], size=2000), color="#A8ADB4"),
    spec("ingenieurbau", "bruecken", "widerlager", "brueckenwiderlager", "Brückenwiderlager", "Vereinfachter massiver Widerlagerkörper mit mehreren Wandstärken.", "stahlbeton", "reinforced_concrete", "bridge_abutment", "concrete_reinforced", "concrete_plain", wall_variants([500, 600, 800, 1000, 1200, 1500], height=5000), color="#A8ADB4"),
    spec("ingenieurbau", "bruecken", "pfeiler", "brueckenpfeiler", "Brückenpfeiler", "Massiver Brückenpfeiler in gestaffelten Querschnitten.", "stahlbeton", "reinforced_concrete", "bridge_pier", "concrete_reinforced", "concrete_plain", square_variants([500, 600, 800, 1000, 1200, 1500], height=6000), color="#A8ADB4"),
    spec("ingenieurbau", "stuetzbauwerke", "kopfbalken", "pfeilerkopfbalken", "Pfeilerkopfbalken", "Stahlbeton-Kopfbalken für Pfeiler und Pfahlreihen.", "stahlbeton", "reinforced_concrete", "pier_cap", "concrete_reinforced", "concrete_plain", section_variants([("600 × 800 mm", 600, 800), ("800 × 1000 mm", 800, 1000), ("1000 × 1200 mm", 1000, 1200), ("1200 × 1500 mm", 1200, 1500), ("1500 × 1800 mm", 1500, 1800)]), color="#A8ADB4"),
    spec("ingenieurbau", "bruecken", "kappen_randbalken", "brueckenkappe", "Brückenkappe / Randbalken", "Randbauteil für Brückenkappen und Gesimse.", "stahlbeton", "reinforced_concrete", "edge_beam", "concrete_reinforced", "concrete_plain", section_variants([("300 × 400 mm", 300, 400), ("400 × 500 mm", 400, 500), ("500 × 600 mm", 500, 600), ("600 × 800 mm", 600, 800), ("800 × 1000 mm", 800, 1000)]), color="#A8ADB4"),
    spec("ingenieurbau", "brueckentragwerk", "traeger", "spannbetontraeger", "Spannbetonträger", "Vereinfachter Spannbeton-Fertigteilträger für Variantenstudien.", "stahlbeton", "reinforced_concrete", "prestressed_girder", "precast_concrete", "concrete_plain", section_variants([("T 600", 400, 600), ("T 800", 500, 800), ("T 1000", 600, 1000), ("T 1200", 700, 1200), ("T 1500", 800, 1500), ("T 1800", 900, 1800)]), color="#A8ADB4"),
    spec("ingenieurbau", "brueckentragwerk", "traeger", "stahlbrueckentraeger", "Stahlbrückenträger", "Vereinfachter geschweißter Stahlträger für Brückenmodelle.", "stahl", "steel", "steel_bridge_girder", "steel", "line_diagonal_45", section_variants([("H 600", 300, 600), ("H 800", 350, 800), ("H 1000", 400, 1000), ("H 1200", 450, 1200), ("H 1500", 500, 1500), ("H 2000", 600, 2000)]), color="#65727D"),
    spec("ingenieurbau", "bruecken", "lager", "brueckenlager", "Brückenlager", "Vereinfachtes Elastomer- und Topflager in Standardabmessungen.", "sonstiges", "composite", "bridge_bearing", "cross_orthogonal", "solid", _variants([("200 × 250 × 50", 250, 50, 200, 50), ("300 × 400 × 70", 400, 70, 300, 70), ("400 × 500 × 90", 500, 90, 400, 90), ("500 × 600 × 110", 600, 110, 500, 110), ("600 × 700 × 140", 700, 140, 600, 140)]), color="#38424A"),
    spec("ingenieurbau", "bruecken", "fahrbahnuebergaenge", "fahrbahnuebergang", "Fahrbahnübergang", "Modularer Fahrbahnübergang für unterschiedliche Bewegungsbereiche.", "stahl", "steel", "expansion_joint", "steel", "grid_fine", _variants([("Bewegung 80 mm", 1000, 120, 350, 120), ("Bewegung 160 mm", 1000, 160, 450, 160), ("Bewegung 240 mm", 1000, 200, 550, 200), ("Bewegung 320 mm", 1000, 240, 650, 240), ("Bewegung 480 mm", 1000, 300, 800, 300)]), color="#555F67"),
    spec("ingenieurbau", "tunnel", "tunnelschalen", "tunnelschale", "Tunnelschale", "Stahlbeton-Tunnelschale als vereinfachtes Segmentbauteil.", "stahlbeton", "reinforced_concrete", "tunnel_lining", "concrete_reinforced", "concrete_plain", wall_variants([250, 300, 350, 400, 450, 500, 600, 800], height=5000), color="#A8ADB4"),
    spec("ingenieurbau", "spezialtiefbau", "schlitzwaende", "schlitzwand", "Schlitzwand", "Schlitzwandelement für Baugruben und unterirdische Bauwerke.", "stahlbeton", "reinforced_concrete", "diaphragm_wall", "concrete_reinforced", "concrete_plain", wall_variants([400, 500, 600, 800, 1000, 1200, 1500], height=10000), color="#9EA4AA"),
    spec("ingenieurbau", "stuetzbauwerke", "spundwaende", "spundwandprofil", "Spundwandprofil", "Vereinfachtes Stahlspundwandprofil in mehreren Profilgrößen.", "stahl", "steel", "sheet_pile", "steel", "line_vertical", section_variants([("Leicht 400", 120, 400), ("Leicht 500", 140, 500), ("Mittel 600", 160, 600), ("Mittel 700", 180, 700), ("Schwer 800", 220, 800), ("Schwer 900", 260, 900)]), color="#64717B"),
    spec("ingenieurbau", "stuetzbauwerke", "anker", "daueranker", "Daueranker", "Vereinfachter Boden- und Felsanker nach Zugkraftklassen.", "stahl", "steel", "ground_anchor", "steel", "line_horizontal", pipe_variants([32, 40, 50, 63, 75, 90, 110], length=6000), primitive_shape="cylinder", color="#5C6871"),
    spec("ingenieurbau", "spezialtiefbau", "pfahlwaende", "bohrpfahl", "Bohrpfahl", "Runder Stahlbeton-Bohrpfahl in typischen Durchmessern.", "stahlbeton", "reinforced_concrete", "bored_pile", "concrete_reinforced", "concrete_plain", _variants([(f"Ø {diameter} mm", diameter, 10000, diameter, diameter) for diameter in [300, 400, 500, 600, 800, 1000, 1200, 1500]]), primitive_shape="cylinder", color="#A8ADB4"),
    spec("ingenieurbau", "stuetzbauwerke", "gabionen", "gabione", "Gabione", "Steinkorb für Stütz- und Landschaftsbauwerke.", "sonstiges", "natural_stone", "gabion", "rubble_stone", "grid_coarse", _variants([("500 × 500 mm", 1000, 500, 500, 500), ("500 × 1000 mm", 1000, 1000, 500, 500), ("1000 × 500 mm", 1000, 500, 1000, 500), ("1000 × 1000 mm", 1000, 1000, 1000, 1000), ("1500 × 1000 mm", 1000, 1000, 1500, 1000), ("2000 × 1000 mm", 1000, 1000, 2000, 1000)]), color="#8E8170"),
    spec("ingenieurbau", "stuetzbauwerke", "stuetzwaende", "stahlbetonstuetzwand", "Stahlbetonstützwand", "Massive Stützwand für Geländesprünge und Verkehrsanlagen.", "stahlbeton", "reinforced_concrete", "retaining_wall", "concrete_reinforced", "concrete_plain", wall_variants([200, 250, 300, 350, 400, 500, 600, 800], height=4000), color="#A8ADB4"),
]


def _payload(family: dict[str, Any]) -> dict[str, Any]:
    raw_variants = family["variants"]
    variants: list[dict[str, Any]] = []
    used_ids: set[str] = set()
    for index, raw in enumerate(raw_variants):
        variant_id = "default" if index == 0 else _slug(raw["label"])
        if variant_id in used_ids:
            variant_id = f"{variant_id}_{index + 1}"
        used_ids.add(variant_id)
        values = {
            "variant.variant_id": variant_id,
            "variant.label": raw["label"],
            "dimensions.width_mm": raw["width_mm"],
            "dimensions.height_mm": raw["height_mm"],
            "dimensions.depth_mm": raw["depth_mm"],
            "dimensions.thickness_mm": raw["thickness_mm"],
            "dimensions.length_mm": raw["width_mm"],
            "technical.units": {
                "dimensions.width_mm": "mm",
                "dimensions.height_mm": "mm",
                "dimensions.depth_mm": "mm",
                "dimensions.thickness_mm": "mm",
                "dimensions.length_mm": "mm",
            },
            "material.type": family["material_type"],
            "material.subtype": family["material_subtype"],
            "material.color_hint": family["color"],
            "cad.cut_pattern_id": family["cut_pattern"],
            "cad.surface_pattern_id": family["surface_pattern"],
            "cad.pattern_scale": 1.0,
            "cad.pattern_rotation_deg": 0.0,
            "cad.pattern_foreground_color": "#202020",
            "cad.pattern_background_color": "#FFFFFF",
        }
        variants.append(
            {
                "variant_id": variant_id,
                "label": raw["label"],
                "is_default": index == 0,
                "kind": "standard" if index == 0 else "size_variant",
                "definition_values": values,
                "additional_field_keys": [],
            }
        )

    first = raw_variants[0]
    taxonomy_path = f"{family['domain']}/{family['category']}/{family['subcategory']}"
    vplib_uid = str(uuid.uuid5(NAMESPACE, f"{taxonomy_path}/{family['slug']}"))
    return {
        "vplib_uid": vplib_uid,
        "family_slug": family["slug"],
        "family_name": family["name"],
        "name": family["name"],
        "label": family["name"],
        "family_description": family["description"],
        "description": family["description"],
        "object_kind": "cell_block",
        "domain": family["domain"],
        "category": family["category"],
        "subcategory": family["subcategory"],
        "taxonomy_path": taxonomy_path,
        "family_profile_id": "simple_cell_block",
        "variant_profile_id": "simple_cell_block.v1",
        "default_variant_id": "default",
        "geometry_width": first["width_mm"] / 1000,
        "geometry_height": first["height_mm"] / 1000,
        "geometry_depth": first["depth_mm"] / 1000,
        "geometry_unit": "m",
        "primitive_shape": family["primitive_shape"],
        "material_class": family["material_class"],
        "material_classes": [family["material_class"]],
        "definition_variants": variants,
        "definition_variants_json": json.dumps(variants, ensure_ascii=False, sort_keys=True),
        "created_at": CREATED_AT,
        "client": {"source": "standard_library_v1_builder", "catalog_version": "1.0.0"},
    }


def _result_errors(result: Any) -> str:
    return "; ".join(
        str(issue.to_dict() if hasattr(issue, "to_dict") else issue)
        for issue in (getattr(result, "errors", None) or ())
    )


def build(*, check_only: bool = False) -> dict[str, Any]:
    os.environ["VPLIB_CREATE_WRITE_ENABLED"] = "false" if check_only else "true"
    os.environ["VECTOPLAN_LIBRARY_SOURCE_ROOT"] = str(PACKAGES_ROOT)
    os.environ["VPLIB_CREATE_SOURCE_ROOT"] = str(PACKAGES_ROOT)

    from library.services import library_create_service

    entries: list[dict[str, Any]] = []
    for family in FAMILY_SPECS:
        payload = _payload(family)
        result = library_create_service.build_package_plan(payload, include_documents=True) if check_only else library_create_service.save_package(payload, overwrite=True)
        if not result.ok:
            raise RuntimeError(f"{family['slug']}: {_result_errors(result)}")
        documents = result.data.get("documents") or {}
        pattern_document = documents.get("render/cad_patterns.json") or {}
        if not check_only:
            pattern_path = Path(str(result.data["target_dir"])) / "render" / "cad_patterns.json"
            pattern_document = json.loads(pattern_path.read_text(encoding="utf-8-sig"))
        entries.append(
            {
                "vplib_uid": payload["vplib_uid"],
                "family_id": f"vp.{family['domain']}.{family['category']}.{family['subcategory']}.{family['slug']}",
                "name": family["name"],
                "domain": family["domain"],
                "category": family["category"],
                "subcategory": family["subcategory"],
                "family_slug": family["slug"],
                "variant_count": len(payload["definition_variants"]),
                "cut_pattern_id": family["cut_pattern"],
                "surface_pattern_id": family["surface_pattern"],
                "source_path": f"{family['domain']}/{family['category']}/{family['subcategory']}/{family['slug']}",
                "embedded_pattern_count": len(pattern_document.get("patterns") or ()),
            }
        )

    domains = Counter(entry["domain"] for entry in entries)
    catalog = {
        "schema_version": "vectoplan.standard_library.catalog.v1",
        "catalog_version": "1.0.0",
        "created_at": CREATED_AT,
        "generator": "scripts/build_standard_library_v1.py",
        "source_root": "standard_library/v1/packages",
        "family_count": len(entries),
        "variant_count": sum(entry["variant_count"] for entry in entries),
        "domain_counts": dict(sorted(domains.items())),
        "families": sorted(entries, key=lambda item: (item["domain"], item["category"], item["subcategory"], item["family_slug"])),
    }
    if not check_only:
        OUTPUT_ROOT.mkdir(parents=True, exist_ok=True)
        CATALOG_PATH.write_text(json.dumps(catalog, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return catalog


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--check", action="store_true", help="Validate all package plans without writing packages.")
    args = parser.parse_args()
    catalog = build(check_only=args.check)
    mode = "validated" if args.check else "written"
    print(
        f"Standard library v1 {mode}: {catalog['family_count']} families, "
        f"{catalog['variant_count']} variants, {catalog['domain_counts']}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
