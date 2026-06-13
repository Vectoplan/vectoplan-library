# services/vectoplan-library/src/vplib/domain/classification.py
"""
Canonical VPLIB classification taxonomy.

This file defines the stable classification path for VPLIB library elements:

    domain / tab  ->  category  ->  subcategory

Visible high-level tabs:
- Hochbau
- Tiefbau
- Ingenieurbau

Stable technical values:
- hochbau
- tiefbau
- ingenieurbau

This file is intentionally independent from Flask, routes, database, services,
creators and validators. It is used by defaults, planners, validators, scanners
and API read models.

Important:
- _humanize_key() is defined before _build_subcategory_definitions().
- self_test is included as a controlled diagnostic subcategory.
- All public parser functions are cached.
- All returned payloads are JSON-compatible.

Technical names, JSON keys and variables remain English.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from enum import Enum
from functools import lru_cache
from typing import Any, Final, Iterable, Mapping


CLASSIFICATION_SCHEMA_VERSION: Final[str] = "vplib.classification.v1"

SAFE_CLASSIFICATION_KEY_RE: Final[re.Pattern[str]] = re.compile(
    r"^[a-z0-9][a-z0-9_]*[a-z0-9]$|^[a-z0-9]$"
)


class ClassificationError(ValueError):
    """Raised when domain, category or subcategory is invalid."""


class VplibDomain(str, Enum):
    """Canonical top-level library tabs."""

    HOCHBAU = "hochbau"
    TIEFBAU = "tiefbau"
    INGENIEURBAU = "ingenieurbau"

    @property
    def key(self) -> str:
        return str(self.value)


@dataclass(frozen=True, slots=True)
class DomainDefinition:
    """Definition of a top-level library tab."""

    domain: VplibDomain
    label: str
    description: str
    stable_order: int
    category_keys: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class CategoryDefinition:
    """Definition of a category inside a domain."""

    domain: VplibDomain
    key: str
    label: str
    description: str
    stable_order: int
    subcategory_keys: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class SubcategoryDefinition:
    """Definition of a subcategory inside a category."""

    domain: VplibDomain
    category_key: str
    key: str
    label: str
    description: str
    stable_order: int


@dataclass(frozen=True, slots=True)
class ClassificationPath:
    """Normalized classification path."""

    domain: VplibDomain
    category: str
    subcategory: str

    @property
    def path(self) -> str:
        """Returns the canonical path domain/category/subcategory."""
        return f"{self.domain.value}/{self.category}/{self.subcategory}"

    def to_dict(self) -> dict[str, Any]:
        """Returns a JSON-compatible classification payload."""
        domain_definition = get_domain_definition(self.domain)
        category_definition = get_category_definition(self.domain, self.category)
        subcategory_definition = get_subcategory_definition(
            self.domain,
            self.category,
            self.subcategory,
        )

        return {
            "schema_version": CLASSIFICATION_SCHEMA_VERSION,
            "domain": self.domain.value,
            "domain_label": domain_definition.label,
            "tab": self.domain.value,
            "tab_label": domain_definition.label,
            "category": category_definition.key,
            "category_label": category_definition.label,
            "subcategory": subcategory_definition.key,
            "subcategory_label": subcategory_definition.label,
            "classification_path": self.path,
        }


def _humanize_key(value: Any) -> str:
    """
    Builds a readable label from a stable technical key.

    This function must be defined before _build_subcategory_definitions(),
    because that function is executed during module import.
    """
    try:
        text = str(value).strip()
    except Exception:
        return ""

    if not text:
        return ""

    explicit_labels = {
        "waende": "Wände",
        "daecher": "Dächer",
        "boeden": "Böden",
        "oeffnungen": "Öffnungen",
        "moebel": "Möbel",
        "schaechte": "Schächte",
        "kanaele": "Kanäle",
        "bruecken": "Brücken",
        "gruendung": "Gründung",
        "stuetzbauwerke": "Stützbauwerke",
        "entwaesserung": "Entwässerung",
        "aussenanlagen": "Außenanlagen",
        "sanitaer": "Sanitär",
        "lueftung": "Lüftung",
        "kueche": "Küche",
        "geraet": "Gerät",
        "traeger": "Träger",
        "stuetze": "Stütze",
        "gelander": "Geländer",
        "brueckenkappe": "Brückenkappe",
        "brueckenpfeiler": "Brückenpfeiler",
        "brueckengelaender": "Brückengeländer",
        "ueberbau": "Überbau",
        "tuer": "Tür",
        "boeschung": "Böschung",
        "boeschungssicherung": "Böschungssicherung",
        "verfuellung": "Verfüllung",
        "daemmung": "Dämmung",
        "oberflaeche": "Oberfläche",
        "abhangdecke": "Abhangdecke",
        "tunnelausruestung": "Tunnelausrüstung",
        "self_test": "Self Test",
    }

    normalized = (
        text.lower()
        .replace(" ", "_")
        .replace("-", "_")
        .replace("/", "_")
        .replace("\\", "_")
        .replace(".", "_")
    )

    if normalized in explicit_labels:
        return explicit_labels[normalized]

    return " ".join(part.capitalize() for part in normalized.split("_") if part)


def _normalize_key(value: Any) -> str:
    """Normalizes a technical classification key."""
    try:
        if value is None:
            raise ClassificationError("Classification key is required, got None.")

        raw = str(value).strip()
        if not raw:
            raise ClassificationError("Classification key is required, got an empty value.")

        key = (
            raw.lower()
            .replace(" ", "_")
            .replace("-", "_")
            .replace("/", "_")
            .replace("\\", "_")
            .replace(".", "_")
            .replace("ä", "ae")
            .replace("ö", "oe")
            .replace("ü", "ue")
            .replace("ß", "ss")
        )

        return _KEY_ALIAS_MAP.get(key, key)
    except ClassificationError:
        raise
    except Exception as exc:
        raise ClassificationError(f"Could not normalize classification key {value!r}.") from exc


_DOMAIN_DEFINITIONS: Final[dict[VplibDomain, DomainDefinition]] = {
    VplibDomain.HOCHBAU: DomainDefinition(
        domain=VplibDomain.HOCHBAU,
        label="Hochbau",
        description="Buildings, building elements, interiors, equipment and building-related technical objects.",
        stable_order=10,
        category_keys=(
            "waende",
            "decken",
            "daecher",
            "boeden",
            "fundamente",
            "treppen",
            "oeffnungen",
            "ausbau",
            "moebel",
            "technik",
            "tragwerk",
        ),
    ),
    VplibDomain.TIEFBAU: DomainDefinition(
        domain=VplibDomain.TIEFBAU,
        label="Tiefbau",
        description="Civil groundworks, infrastructure, pipes, shafts, roads and site-related objects.",
        stable_order=20,
        category_keys=(
            "leitungen",
            "schaechte",
            "strassen",
            "wege",
            "kanaele",
            "erdarbeiten",
            "fundamente",
            "entwaesserung",
            "versorgung",
            "aussenanlagen",
        ),
    ),
    VplibDomain.INGENIEURBAU: DomainDefinition(
        domain=VplibDomain.INGENIEURBAU,
        label="Ingenieurbau",
        description="Engineering structures, bridges, structural systems and infrastructure structures.",
        stable_order=30,
        category_keys=(
            "bruecken",
            "tragwerk",
            "lager",
            "gruendung",
            "stuetzbauwerke",
            "tunnel",
            "wasserbau",
            "bewehrung",
            "sondersysteme",
        ),
    ),
}


_CATEGORY_DEFINITIONS: Final[dict[tuple[VplibDomain, str], CategoryDefinition]] = {
    # Hochbau
    (VplibDomain.HOCHBAU, "waende"): CategoryDefinition(
        domain=VplibDomain.HOCHBAU,
        key="waende",
        label="Wände",
        description="Wall systems and wall-like building components.",
        stable_order=10,
        subcategory_keys=(
            "mauerwerk",
            "trockenbau",
            "betonwand",
            "holzbauwand",
            "innenwand",
            "aussenwand",
            "tragende_wand",
            "nichttragende_wand",
            "vorsatzschale",
            "wandzubehoer",
            "self_test",
        ),
    ),
    (VplibDomain.HOCHBAU, "decken"): CategoryDefinition(
        domain=VplibDomain.HOCHBAU,
        key="decken",
        label="Decken",
        description="Ceilings, slabs and horizontal structural layers.",
        stable_order=20,
        subcategory_keys=(
            "massivdecke",
            "holzdecke",
            "fertigdecke",
            "abhangdecke",
            "unterzug",
            "deckenbekleidung",
            "deckenobjekt",
        ),
    ),
    (VplibDomain.HOCHBAU, "daecher"): CategoryDefinition(
        domain=VplibDomain.HOCHBAU,
        key="daecher",
        label="Dächer",
        description="Roof structures, roof surfaces and roof components.",
        stable_order=30,
        subcategory_keys=(
            "satteldach",
            "flachdach",
            "walmdach",
            "pultdach",
            "dachaufbau",
            "dachdeckung",
            "dachzubehoer",
        ),
    ),
    (VplibDomain.HOCHBAU, "boeden"): CategoryDefinition(
        domain=VplibDomain.HOCHBAU,
        key="boeden",
        label="Böden",
        description="Floors, floor layers and floor finishes.",
        stable_order=40,
        subcategory_keys=(
            "bodenplatte",
            "estrich",
            "bodenbelag",
            "daemmung",
            "sockel",
        ),
    ),
    (VplibDomain.HOCHBAU, "fundamente"): CategoryDefinition(
        domain=VplibDomain.HOCHBAU,
        key="fundamente",
        label="Fundamente",
        description="Building foundations and foundation-like components.",
        stable_order=50,
        subcategory_keys=(
            "streifenfundament",
            "einzelfundament",
            "plattenfundament",
            "fundamentmodul",
            "sockelfundament",
        ),
    ),
    (VplibDomain.HOCHBAU, "treppen"): CategoryDefinition(
        domain=VplibDomain.HOCHBAU,
        key="treppen",
        label="Treppen",
        description="Stairs, landings and vertical circulation modules.",
        stable_order=60,
        subcategory_keys=(
            "treppenlauf",
            "podest",
            "treppenkern",
            "gelander",
            "handlauf",
        ),
    ),
    (VplibDomain.HOCHBAU, "oeffnungen"): CategoryDefinition(
        domain=VplibDomain.HOCHBAU,
        key="oeffnungen",
        label="Öffnungen",
        description="Windows, doors and opening-related components.",
        stable_order=70,
        subcategory_keys=(
            "fenster",
            "tuer",
            "tor",
            "durchbruch",
            "lichtband",
            "oeffnungszubehoer",
        ),
    ),
    (VplibDomain.HOCHBAU, "ausbau"): CategoryDefinition(
        domain=VplibDomain.HOCHBAU,
        key="ausbau",
        label="Ausbau",
        description="Interior finishing and fit-out objects.",
        stable_order=80,
        subcategory_keys=(
            "bekleidung",
            "verkleidung",
            "daemmung",
            "oberflaeche",
            "innenausbau",
        ),
    ),
    (VplibDomain.HOCHBAU, "moebel"): CategoryDefinition(
        domain=VplibDomain.HOCHBAU,
        key="moebel",
        label="Möbel",
        description="Furniture and furnishing objects.",
        stable_order=90,
        subcategory_keys=(
            "tisch",
            "stuhl",
            "schrank",
            "bett",
            "kueche",
            "sanitaermoebel",
            "sonstiges_moebel",
        ),
    ),
    (VplibDomain.HOCHBAU, "technik"): CategoryDefinition(
        domain=VplibDomain.HOCHBAU,
        key="technik",
        label="Technik",
        description="Building services, fixtures, devices and technical equipment.",
        stable_order=100,
        subcategory_keys=(
            "sanitaer",
            "heizung",
            "lueftung",
            "elektro",
            "armatur",
            "geraet",
            "leitung",
            "schaltschrank",
        ),
    ),
    (VplibDomain.HOCHBAU, "tragwerk"): CategoryDefinition(
        domain=VplibDomain.HOCHBAU,
        key="tragwerk",
        label="Tragwerk",
        description="Structural members and load-bearing systems.",
        stable_order=110,
        subcategory_keys=(
            "stuetze",
            "traeger",
            "riegel",
            "aussteifung",
            "verband",
            "tragwerksmodul",
        ),
    ),

    # Tiefbau
    (VplibDomain.TIEFBAU, "leitungen"): CategoryDefinition(
        domain=VplibDomain.TIEFBAU,
        key="leitungen",
        label="Leitungen",
        description="Pipes, ducts and underground line systems.",
        stable_order=10,
        subcategory_keys=(
            "wasserleitung",
            "abwasserleitung",
            "stromleitung",
            "datenleitung",
            "gasleitung",
            "fernwaermeleitung",
            "schutzrohr",
        ),
    ),
    (VplibDomain.TIEFBAU, "schaechte"): CategoryDefinition(
        domain=VplibDomain.TIEFBAU,
        key="schaechte",
        label="Schächte",
        description="Shafts, manholes and inspection structures.",
        stable_order=20,
        subcategory_keys=(
            "revisionsschacht",
            "kontrollschacht",
            "pumpenschacht",
            "kabelschacht",
            "schachtabdeckung",
        ),
    ),
    (VplibDomain.TIEFBAU, "strassen"): CategoryDefinition(
        domain=VplibDomain.TIEFBAU,
        key="strassen",
        label="Straßen",
        description="Road bodies, surfaces and road construction elements.",
        stable_order=30,
        subcategory_keys=(
            "fahrbahn",
            "bordstein",
            "rinne",
            "asphalt",
            "pflaster",
            "markierung",
        ),
    ),
    (VplibDomain.TIEFBAU, "wege"): CategoryDefinition(
        domain=VplibDomain.TIEFBAU,
        key="wege",
        label="Wege",
        description="Paths, pedestrian areas and paved outdoor surfaces.",
        stable_order=40,
        subcategory_keys=(
            "gehweg",
            "radweg",
            "pflasterweg",
            "kiesweg",
            "plattenweg",
        ),
    ),
    (VplibDomain.TIEFBAU, "kanaele"): CategoryDefinition(
        domain=VplibDomain.TIEFBAU,
        key="kanaele",
        label="Kanäle",
        description="Sewer and channel systems.",
        stable_order=50,
        subcategory_keys=(
            "regenwasserkanal",
            "schmutzwasserkanal",
            "mischwasserkanal",
            "kanalbauteil",
        ),
    ),
    (VplibDomain.TIEFBAU, "erdarbeiten"): CategoryDefinition(
        domain=VplibDomain.TIEFBAU,
        key="erdarbeiten",
        label="Erdarbeiten",
        description="Earthwork and ground preparation components.",
        stable_order=60,
        subcategory_keys=(
            "aushub",
            "verfuellung",
            "boeschung",
            "planum",
            "baugrube",
        ),
    ),
    (VplibDomain.TIEFBAU, "fundamente"): CategoryDefinition(
        domain=VplibDomain.TIEFBAU,
        key="fundamente",
        label="Fundamente",
        description="Civil engineering foundation elements.",
        stable_order=70,
        subcategory_keys=(
            "punktfundament",
            "streifenfundament",
            "plattenfundament",
            "pfahl",
            "anker",
        ),
    ),
    (VplibDomain.TIEFBAU, "entwaesserung"): CategoryDefinition(
        domain=VplibDomain.TIEFBAU,
        key="entwaesserung",
        label="Entwässerung",
        description="Drainage and water management systems.",
        stable_order=80,
        subcategory_keys=(
            "drainage",
            "ablauf",
            "rigole",
            "mulde",
            "sickeranlage",
        ),
    ),
    (VplibDomain.TIEFBAU, "versorgung"): CategoryDefinition(
        domain=VplibDomain.TIEFBAU,
        key="versorgung",
        label="Versorgung",
        description="Supply infrastructure and utility components.",
        stable_order=90,
        subcategory_keys=(
            "strom",
            "wasser",
            "gas",
            "telekommunikation",
            "fernwaerme",
        ),
    ),
    (VplibDomain.TIEFBAU, "aussenanlagen"): CategoryDefinition(
        domain=VplibDomain.TIEFBAU,
        key="aussenanlagen",
        label="Außenanlagen",
        description="Outdoor site elements and landscaping components.",
        stable_order=100,
        subcategory_keys=(
            "zaun",
            "mauer",
            "tor",
            "bepflanzung",
            "ausstattung",
        ),
    ),

    # Ingenieurbau
    (VplibDomain.INGENIEURBAU, "bruecken"): CategoryDefinition(
        domain=VplibDomain.INGENIEURBAU,
        key="bruecken",
        label="Brücken",
        description="Bridge structures and bridge components.",
        stable_order=10,
        subcategory_keys=(
            "brueckenkappe",
            "brueckenpfeiler",
            "widerlager",
            "ueberbau",
            "fahrbahnplatte",
            "brueckengelaender",
        ),
    ),
    (VplibDomain.INGENIEURBAU, "tragwerk"): CategoryDefinition(
        domain=VplibDomain.INGENIEURBAU,
        key="tragwerk",
        label="Tragwerk",
        description="Engineering structural systems and load-bearing elements.",
        stable_order=20,
        subcategory_keys=(
            "traeger",
            "stuetze",
            "fachwerk",
            "rahmen",
            "verband",
            "platte",
        ),
    ),
    (VplibDomain.INGENIEURBAU, "lager"): CategoryDefinition(
        domain=VplibDomain.INGENIEURBAU,
        key="lager",
        label="Lager",
        description="Bearings and support devices.",
        stable_order=30,
        subcategory_keys=(
            "brueckenlager",
            "elastomerlager",
            "gleitlager",
            "festlager",
            "bewegliches_lager",
        ),
    ),
    (VplibDomain.INGENIEURBAU, "gruendung"): CategoryDefinition(
        domain=VplibDomain.INGENIEURBAU,
        key="gruendung",
        label="Gründung",
        description="Foundation systems for engineering structures.",
        stable_order=40,
        subcategory_keys=(
            "pfahlgruendung",
            "flachgruendung",
            "tiefgruendung",
            "anker",
            "baugrundverbesserung",
        ),
    ),
    (VplibDomain.INGENIEURBAU, "stuetzbauwerke"): CategoryDefinition(
        domain=VplibDomain.INGENIEURBAU,
        key="stuetzbauwerke",
        label="Stützbauwerke",
        description="Retaining structures and support walls.",
        stable_order=50,
        subcategory_keys=(
            "stuetzwand",
            "winkelstuetzwand",
            "gabione",
            "spundwand",
            "boeschungssicherung",
        ),
    ),
    (VplibDomain.INGENIEURBAU, "tunnel"): CategoryDefinition(
        domain=VplibDomain.INGENIEURBAU,
        key="tunnel",
        label="Tunnel",
        description="Tunnel components and underground engineering structures.",
        stable_order=60,
        subcategory_keys=(
            "tunnelschale",
            "portal",
            "innenausbau",
            "tunnelausruestung",
            "entwaesserung",
        ),
    ),
    (VplibDomain.INGENIEURBAU, "wasserbau"): CategoryDefinition(
        domain=VplibDomain.INGENIEURBAU,
        key="wasserbau",
        label="Wasserbau",
        description="Hydraulic engineering structures.",
        stable_order=70,
        subcategory_keys=(
            "uferwand",
            "wehr",
            "schleuse",
            "durchlass",
            "spundwand",
        ),
    ),
    (VplibDomain.INGENIEURBAU, "bewehrung"): CategoryDefinition(
        domain=VplibDomain.INGENIEURBAU,
        key="bewehrung",
        label="Bewehrung",
        description="Reinforcement systems and reinforcement components.",
        stable_order=80,
        subcategory_keys=(
            "stabstahl",
            "matte",
            "korb",
            "spannglied",
            "anschlussbewehrung",
        ),
    ),
    (VplibDomain.INGENIEURBAU, "sondersysteme"): CategoryDefinition(
        domain=VplibDomain.INGENIEURBAU,
        key="sondersysteme",
        label="Sondersysteme",
        description="Special adaptive and engineering systems.",
        stable_order=90,
        subcategory_keys=(
            "adaptives_system",
            "sensorik",
            "monitoring",
            "sonderbauteil",
        ),
    ),
}


_DOMAIN_ALIAS_MAP: Final[dict[str, VplibDomain]] = {
    "hochbau": VplibDomain.HOCHBAU,
    "building": VplibDomain.HOCHBAU,
    "building_construction": VplibDomain.HOCHBAU,
    "architecture": VplibDomain.HOCHBAU,
    "tab_hochbau": VplibDomain.HOCHBAU,
    "tiefbau": VplibDomain.TIEFBAU,
    "civil": VplibDomain.TIEFBAU,
    "civil_engineering": VplibDomain.TIEFBAU,
    "infrastructure": VplibDomain.TIEFBAU,
    "tab_tiefbau": VplibDomain.TIEFBAU,
    "ingenieurbau": VplibDomain.INGENIEURBAU,
    "engineering": VplibDomain.INGENIEURBAU,
    "structural_engineering": VplibDomain.INGENIEURBAU,
    "engineered_structures": VplibDomain.INGENIEURBAU,
    "tab_ingenieurbau": VplibDomain.INGENIEURBAU,
}


_KEY_ALIAS_MAP: Final[dict[str, str]] = {
    "wände": "waende",
    "waende": "waende",
    "walls": "waende",
    "wall": "waende",
    "decken": "decken",
    "ceiling": "decken",
    "ceilings": "decken",
    "slabs": "decken",
    "dächer": "daecher",
    "daecher": "daecher",
    "roof": "daecher",
    "roofs": "daecher",
    "böden": "boeden",
    "boeden": "boeden",
    "floor": "boeden",
    "floors": "boeden",
    "öffnungen": "oeffnungen",
    "oeffnungen": "oeffnungen",
    "openings": "oeffnungen",
    "möbel": "moebel",
    "moebel": "moebel",
    "furniture": "moebel",
    "technik": "technik",
    "services": "technik",
    "equipment": "technik",
    "tragwerk": "tragwerk",
    "structure": "tragwerk",
    "structural": "tragwerk",
    "leitungen": "leitungen",
    "pipes": "leitungen",
    "lines": "leitungen",
    "schächte": "schaechte",
    "schaechte": "schaechte",
    "shafts": "schaechte",
    "strassen": "strassen",
    "straßen": "strassen",
    "roads": "strassen",
    "kanäle": "kanaele",
    "kanaele": "kanaele",
    "channels": "kanaele",
    "brücken": "bruecken",
    "bruecken": "bruecken",
    "bridges": "bruecken",
    "gründung": "gruendung",
    "gruendung": "gruendung",
    "foundation": "gruendung",
    "foundations": "fundamente",
    "stützbauwerke": "stuetzbauwerke",
    "stuetzbauwerke": "stuetzbauwerke",
    "retaining_structures": "stuetzbauwerke",
    "selftest": "self_test",
    "self_test": "self_test",
    "test": "self_test",
}


def _build_subcategory_definitions() -> dict[tuple[VplibDomain, str, str], SubcategoryDefinition]:
    definitions: dict[tuple[VplibDomain, str, str], SubcategoryDefinition] = {}

    for (domain, category_key), category_definition in _CATEGORY_DEFINITIONS.items():
        for index, subcategory_key in enumerate(category_definition.subcategory_keys, start=1):
            label = _humanize_key(subcategory_key)
            definitions[(domain, category_key, subcategory_key)] = SubcategoryDefinition(
                domain=domain,
                category_key=category_key,
                key=subcategory_key,
                label=label,
                description=f"{category_definition.label} / {label}.",
                stable_order=index * 10,
            )

    return definitions


_SUBCATEGORY_DEFINITIONS: Final[
    dict[tuple[VplibDomain, str, str], SubcategoryDefinition]
] = _build_subcategory_definitions()


@lru_cache(maxsize=128)
def parse_domain(value: Any) -> VplibDomain:
    """
    Parses a domain/tab value to a canonical VplibDomain value.

    Raises:
        ClassificationError: if the domain is unknown.
    """
    if isinstance(value, VplibDomain):
        return value

    key = _normalize_key(value)

    try:
        return VplibDomain(key)
    except ValueError:
        pass

    try:
        return _DOMAIN_ALIAS_MAP[key]
    except KeyError as exc:
        allowed = ", ".join(get_domain_values())
        raise ClassificationError(
            f"Unknown VPLIB domain {value!r}. Allowed values: {allowed}."
        ) from exc


def try_parse_domain(value: Any, default: VplibDomain | None = None) -> VplibDomain | None:
    """Safe domain parser variant."""
    try:
        return parse_domain(value)
    except ClassificationError:
        return default
    except Exception:
        return default


def is_valid_domain(value: Any) -> bool:
    """Returns whether a domain value is valid."""
    try:
        parse_domain(value)
        return True
    except Exception:
        return False


@lru_cache(maxsize=1)
def get_domain_values() -> tuple[str, ...]:
    """Returns all canonical domain values."""
    return tuple(domain.value for domain in get_all_domains())


@lru_cache(maxsize=1)
def get_all_domains() -> tuple[VplibDomain, ...]:
    """Returns all domains in stable order."""
    return tuple(
        definition.domain
        for definition in sorted(
            _DOMAIN_DEFINITIONS.values(),
            key=lambda definition: definition.stable_order,
        )
    )


@lru_cache(maxsize=1)
def get_domain_definitions() -> Mapping[VplibDomain, DomainDefinition]:
    """Returns all domain definitions."""
    return dict(_DOMAIN_DEFINITIONS)


@lru_cache(maxsize=32)
def get_domain_definition(domain: Any) -> DomainDefinition:
    """Returns the definition of a domain."""
    parsed_domain = parse_domain(domain)

    try:
        return _DOMAIN_DEFINITIONS[parsed_domain]
    except KeyError as exc:
        raise ClassificationError(
            f"Missing domain definition for {parsed_domain.value!r}."
        ) from exc


@lru_cache(maxsize=128)
def parse_category(domain: Any, category: Any) -> str:
    """
    Parses a category inside a domain.

    Raises:
        ClassificationError: if the category does not exist in this domain.
    """
    parsed_domain = parse_domain(domain)
    category_key = _normalize_key(category)

    domain_definition = get_domain_definition(parsed_domain)
    if category_key not in domain_definition.category_keys:
        allowed = ", ".join(domain_definition.category_keys)
        raise ClassificationError(
            f"Unknown category {category!r} for domain {parsed_domain.value!r}. "
            f"Allowed values: {allowed}."
        )

    return category_key


def try_parse_category(
    domain: Any,
    category: Any,
    default: str | None = None,
) -> str | None:
    """Safe category parser variant."""
    try:
        return parse_category(domain, category)
    except ClassificationError:
        return default
    except Exception:
        return default


@lru_cache(maxsize=256)
def parse_subcategory(domain: Any, category: Any, subcategory: Any) -> str:
    """
    Parses a subcategory inside a category.

    Raises:
        ClassificationError: if the subcategory does not exist in this category.
    """
    parsed_domain = parse_domain(domain)
    category_key = parse_category(parsed_domain, category)
    subcategory_key = _normalize_key(subcategory)

    category_definition = get_category_definition(parsed_domain, category_key)

    if subcategory_key not in category_definition.subcategory_keys:
        allowed = ", ".join(category_definition.subcategory_keys)
        raise ClassificationError(
            f"Unknown subcategory {subcategory!r} for "
            f"{parsed_domain.value!r}/{category_key!r}. Allowed values: {allowed}."
        )

    return subcategory_key


def try_parse_subcategory(
    domain: Any,
    category: Any,
    subcategory: Any,
    default: str | None = None,
) -> str | None:
    """Safe subcategory parser variant."""
    try:
        return parse_subcategory(domain, category, subcategory)
    except ClassificationError:
        return default
    except Exception:
        return default


@lru_cache(maxsize=128)
def get_category_definition(domain: Any, category: Any) -> CategoryDefinition:
    """Returns the category definition."""
    parsed_domain = parse_domain(domain)
    category_key = parse_category(parsed_domain, category)

    try:
        return _CATEGORY_DEFINITIONS[(parsed_domain, category_key)]
    except KeyError as exc:
        raise ClassificationError(
            f"Missing category definition for {parsed_domain.value!r}/{category_key!r}."
        ) from exc


@lru_cache(maxsize=256)
def get_subcategory_definition(
    domain: Any,
    category: Any,
    subcategory: Any,
) -> SubcategoryDefinition:
    """Returns the subcategory definition."""
    parsed_domain = parse_domain(domain)
    category_key = parse_category(parsed_domain, category)
    subcategory_key = parse_subcategory(parsed_domain, category_key, subcategory)

    try:
        return _SUBCATEGORY_DEFINITIONS[(parsed_domain, category_key, subcategory_key)]
    except KeyError as exc:
        raise ClassificationError(
            f"Missing subcategory definition for "
            f"{parsed_domain.value!r}/{category_key!r}/{subcategory_key!r}."
        ) from exc


def get_categories_for_domain(domain: Any) -> tuple[CategoryDefinition, ...]:
    """Returns all categories of a domain in stable order."""
    parsed_domain = parse_domain(domain)
    domain_definition = get_domain_definition(parsed_domain)

    categories = [
        get_category_definition(parsed_domain, category_key)
        for category_key in domain_definition.category_keys
    ]

    return tuple(sorted(categories, key=lambda category: category.stable_order))


def get_subcategories_for_category(
    domain: Any,
    category: Any,
) -> tuple[SubcategoryDefinition, ...]:
    """Returns all subcategories of a category in stable order."""
    parsed_domain = parse_domain(domain)
    category_key = parse_category(parsed_domain, category)
    category_definition = get_category_definition(parsed_domain, category_key)

    subcategories = [
        get_subcategory_definition(parsed_domain, category_key, subcategory_key)
        for subcategory_key in category_definition.subcategory_keys
    ]

    return tuple(sorted(subcategories, key=lambda subcategory: subcategory.stable_order))


def build_classification_path(
    *,
    domain: Any,
    category: Any,
    subcategory: Any,
) -> ClassificationPath:
    """Creates a validated classification path."""
    parsed_domain = parse_domain(domain)
    category_key = parse_category(parsed_domain, category)
    subcategory_key = parse_subcategory(parsed_domain, category_key, subcategory)

    return ClassificationPath(
        domain=parsed_domain,
        category=category_key,
        subcategory=subcategory_key,
    )


def parse_classification_path(value: Any) -> ClassificationPath:
    """
    Parses a string in the format domain/category/subcategory.

    Raises:
        ClassificationError: if the path is invalid.
    """
    try:
        raw = str(value).strip().replace("\\", "/")
        parts = [part for part in raw.split("/") if part]

        if len(parts) != 3:
            raise ClassificationError(
                "Classification path must have exactly three parts: domain/category/subcategory."
            )

        return build_classification_path(
            domain=parts[0],
            category=parts[1],
            subcategory=parts[2],
        )
    except ClassificationError:
        raise
    except Exception as exc:
        raise ClassificationError(f"Could not parse classification path {value!r}.") from exc


def try_parse_classification_path(
    value: Any,
    default: ClassificationPath | None = None,
) -> ClassificationPath | None:
    """Safe parser variant for classification paths."""
    try:
        return parse_classification_path(value)
    except ClassificationError:
        return default
    except Exception:
        return default


def is_valid_classification(
    *,
    domain: Any,
    category: Any,
    subcategory: Any,
) -> bool:
    """Returns whether a classification path is valid."""
    try:
        build_classification_path(
            domain=domain,
            category=category,
            subcategory=subcategory,
        )
        return True
    except Exception:
        return False


def validate_classification(
    *,
    domain: Any,
    category: Any,
    subcategory: Any,
) -> tuple[bool, tuple[str, ...]]:
    """Validates a classification path."""
    try:
        build_classification_path(
            domain=domain,
            category=category,
            subcategory=subcategory,
        )
        return True, tuple()
    except ClassificationError as exc:
        return False, (str(exc),)
    except Exception as exc:
        return False, (f"Could not validate classification: {exc}",)


def assert_valid_classification(
    *,
    domain: Any,
    category: Any,
    subcategory: Any,
) -> None:
    """Raises ClassificationError if the classification path is invalid."""
    is_valid, messages = validate_classification(
        domain=domain,
        category=category,
        subcategory=subcategory,
    )

    if not is_valid:
        joined = " ".join(messages) if messages else "Invalid classification."
        raise ClassificationError(joined)


def normalize_classification_key(value: Any) -> str:
    """Normalizes a technical classification key and checks it roughly."""
    key = _normalize_key(value)

    if not SAFE_CLASSIFICATION_KEY_RE.match(key):
        raise ClassificationError(f"Unsafe classification key {value!r}.")

    return key


def domain_definition_to_json(definition: DomainDefinition) -> dict[str, Any]:
    """Serializes a domain definition JSON-compatibly."""
    return {
        "schema_version": CLASSIFICATION_SCHEMA_VERSION,
        "domain": definition.domain.value,
        "label": definition.label,
        "description": definition.description,
        "stable_order": definition.stable_order,
        "category_keys": list(definition.category_keys),
    }


def category_definition_to_json(definition: CategoryDefinition) -> dict[str, Any]:
    """Serializes a category definition JSON-compatibly."""
    return {
        "schema_version": CLASSIFICATION_SCHEMA_VERSION,
        "domain": definition.domain.value,
        "key": definition.key,
        "label": definition.label,
        "description": definition.description,
        "stable_order": definition.stable_order,
        "subcategory_keys": list(definition.subcategory_keys),
    }


def subcategory_definition_to_json(definition: SubcategoryDefinition) -> dict[str, Any]:
    """Serializes a subcategory definition JSON-compatibly."""
    return {
        "schema_version": CLASSIFICATION_SCHEMA_VERSION,
        "domain": definition.domain.value,
        "category": definition.category_key,
        "key": definition.key,
        "label": definition.label,
        "description": definition.description,
        "stable_order": definition.stable_order,
    }


def all_domains_to_json() -> list[dict[str, Any]]:
    """Serializes all domains JSON-compatibly."""
    return [
        domain_definition_to_json(get_domain_definition(domain))
        for domain in get_all_domains()
    ]


def all_categories_to_json() -> list[dict[str, Any]]:
    """Serializes all categories JSON-compatibly."""
    result: list[dict[str, Any]] = []

    for domain in get_all_domains():
        for category in get_categories_for_domain(domain):
            result.append(category_definition_to_json(category))

    return result


def all_subcategories_to_json() -> list[dict[str, Any]]:
    """Serializes all subcategories JSON-compatibly."""
    result: list[dict[str, Any]] = []

    for domain in get_all_domains():
        for category in get_categories_for_domain(domain):
            for subcategory in get_subcategories_for_category(domain, category.key):
                result.append(subcategory_definition_to_json(subcategory))

    return result


def taxonomy_to_json() -> dict[str, Any]:
    """Returns the full taxonomy JSON-compatibly."""
    return {
        "schema_version": CLASSIFICATION_SCHEMA_VERSION,
        "domains": all_domains_to_json(),
        "categories": all_categories_to_json(),
        "subcategories": all_subcategories_to_json(),
    }


def build_classification_payload(
    *,
    domain: Any,
    category: Any,
    subcategory: Any,
) -> dict[str, Any]:
    """Creates the canonical payload for family/classification.json."""
    return build_classification_path(
        domain=domain,
        category=category,
        subcategory=subcategory,
    ).to_dict()


def clear_classification_caches() -> None:
    """Clears internal parser caches."""
    parse_domain.cache_clear()
    get_domain_values.cache_clear()
    get_all_domains.cache_clear()
    get_domain_definitions.cache_clear()
    get_domain_definition.cache_clear()
    parse_category.cache_clear()
    parse_subcategory.cache_clear()
    get_category_definition.cache_clear()
    get_subcategory_definition.cache_clear()


__all__ = [
    "CLASSIFICATION_SCHEMA_VERSION",
    "SAFE_CLASSIFICATION_KEY_RE",
    "CategoryDefinition",
    "ClassificationError",
    "ClassificationPath",
    "DomainDefinition",
    "SubcategoryDefinition",
    "VplibDomain",
    "all_categories_to_json",
    "all_domains_to_json",
    "all_subcategories_to_json",
    "assert_valid_classification",
    "build_classification_path",
    "build_classification_payload",
    "category_definition_to_json",
    "clear_classification_caches",
    "domain_definition_to_json",
    "get_all_domains",
    "get_categories_for_domain",
    "get_category_definition",
    "get_domain_definition",
    "get_domain_definitions",
    "get_domain_values",
    "get_subcategories_for_category",
    "get_subcategory_definition",
    "is_valid_classification",
    "is_valid_domain",
    "normalize_classification_key",
    "parse_category",
    "parse_classification_path",
    "parse_domain",
    "parse_subcategory",
    "subcategory_definition_to_json",
    "taxonomy_to_json",
    "try_parse_category",
    "try_parse_classification_path",
    "try_parse_domain",
    "try_parse_subcategory",
    "validate_classification",
]