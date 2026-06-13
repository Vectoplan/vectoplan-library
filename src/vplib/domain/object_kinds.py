# services/vectoplan-library/src/vplib/domain/object_kinds.py
"""
Canonical VPLIB object-kind definitions.

This module is intentionally dependency-light and safe to import early.
It defines the stable object-kind vocabulary used by the VPLIB creation,
planning, validation, scanner and later API layers.

Object kinds describe what kind of reusable Library element a VPLIB package
represents. They are not UI labels and they are not database model names.

Canonical values:
- cell_block
- multi_cell_module
- catalog_object
- adaptive_system
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from functools import lru_cache
from typing import Any, Final, Iterable, Mapping, Sequence


OBJECT_KIND_SCHEMA_VERSION: Final[str] = "vplib.object_kinds.v1"


class ObjectKindError(ValueError):
    """Raised when an object-kind value cannot be normalized or validated."""


class VplibObjectKind(str, Enum):
    """
    Canonical object-kind enum for VPLIB packages.

    Keep these values stable. They may appear in:
    - vplib.manifest.json
    - vplib.modules.json
    - family/classification.json
    - editor/inventory.json
    - scanner reports
    - future database rows
    - API responses
    """

    CELL_BLOCK = "cell_block"
    MULTI_CELL_MODULE = "multi_cell_module"
    CATALOG_OBJECT = "catalog_object"
    ADAPTIVE_SYSTEM = "adaptive_system"

    @property
    def key(self) -> str:
        """Return the canonical string key."""
        return str(self.value)

    @property
    def is_grid_based(self) -> bool:
        """Return whether this object kind has a fixed grid footprint."""
        return self in {
            VplibObjectKind.CELL_BLOCK,
            VplibObjectKind.MULTI_CELL_MODULE,
            VplibObjectKind.CATALOG_OBJECT,
        }

    @property
    def is_adaptive(self) -> bool:
        """Return whether this object kind requires adaptive/dynamic modules."""
        return self is VplibObjectKind.ADAPTIVE_SYSTEM

    @property
    def allows_variants(self) -> bool:
        """All current object kinds support variants."""
        return True

    @property
    def default_variant_id(self) -> str:
        """Return the default variant id used for new packages."""
        return "default"


@dataclass(frozen=True, slots=True)
class ObjectKindDefinition:
    """
    Metadata for one canonical VPLIB object kind.

    This metadata is intentionally stored here because object-kind decisions are
    foundational for creation planning. Later files such as module planners and
    validators can consume this without duplicating business rules.
    """

    kind: VplibObjectKind
    label_de: str
    label_en: str
    short_description_de: str
    long_description_de: str
    examples_de: tuple[str, ...]
    typical_placement_modes: tuple[str, ...]
    required_module_keys: tuple[str, ...]
    optional_module_keys: tuple[str, ...]
    recommended_module_keys: tuple[str, ...]
    supports_glb: bool
    supports_texture: bool
    supports_fallback_color: bool
    supports_multi_cell_footprint: bool
    requires_dynamic_modules: bool
    requires_grid_footprint: bool
    requires_bounds_check: bool
    allows_manufacturer_overlay: bool
    default_grid_footprint: tuple[int, int, int]
    min_grid_footprint: tuple[int, int, int]
    notes_de: tuple[str, ...]


# Module-key strings are kept as plain strings here to avoid a hard dependency
# on domain/module_names.py before that file exists.
_COMMON_REQUIRED_MODULE_KEYS: Final[tuple[str, ...]] = (
    "manifest",
    "modules",
    "family",
    "variants",
    "editor",
    "manufacturer",
)

_COMMON_OPTIONAL_MODULE_KEYS: Final[tuple[str, ...]] = (
    "render",
    "physical",
    "material",
    "calculation",
    "analysis",
    "dynamic",
    "docs",
    "tests",
)

_OBJECT_KIND_DEFINITIONS: Final[dict[VplibObjectKind, ObjectKindDefinition]] = {
    VplibObjectKind.CELL_BLOCK: ObjectKindDefinition(
        kind=VplibObjectKind.CELL_BLOCK,
        label_de="Raster-Bauteil",
        label_en="Cell Block",
        short_description_de=(
            "Für Bauteile, die als einzelner Block oder Rasterbaustein funktionieren."
        ),
        long_description_de=(
            "Ein Raster-Bauteil ist ein Library-Element, dessen Platzierungswahrheit "
            "direkt an eine Rasterzelle oder einen einfachen Raster-Footprint gebunden "
            "ist. Es eignet sich für Wandblöcke, Deckenelemente, Straßenblöcke oder "
            "andere Bauteile, die im Editor blockartig gesetzt werden können, aber "
            "trotzdem semantische Maße, Materialien, Varianten und Berechnungsprofile "
            "besitzen dürfen."
        ),
        examples_de=(
            "Wandblock",
            "Deckenelement",
            "Straßenblock",
            "Bodenblock",
            "einfacher Infrastrukturblock",
        ),
        typical_placement_modes=(
            "fill_block",
            "centered",
            "bottom_aligned",
            "top_aligned",
        ),
        required_module_keys=(
            *_COMMON_REQUIRED_MODULE_KEYS,
            "render",
            "physical",
        ),
        optional_module_keys=(
            "material",
            "calculation",
            "analysis",
            "docs",
            "tests",
        ),
        recommended_module_keys=(
            "material",
            "calculation",
        ),
        supports_glb=True,
        supports_texture=True,
        supports_fallback_color=True,
        supports_multi_cell_footprint=False,
        requires_dynamic_modules=False,
        requires_grid_footprint=True,
        requires_bounds_check=True,
        allows_manufacturer_overlay=True,
        default_grid_footprint=(1, 1, 1),
        min_grid_footprint=(1, 1, 1),
        notes_de=(
            "Der sichtbare Körper darf den belegten Rasterraum nicht überschreiten.",
            "Wenn keine Textur gesetzt ist, muss eine Fallback-Farbe vorhanden sein.",
            "Varianten sollen nur Abweichungen wie Dicke, Material oder Kennwerte überschreiben.",
        ),
    ),
    VplibObjectKind.MULTI_CELL_MODULE: ObjectKindDefinition(
        kind=VplibObjectKind.MULTI_CELL_MODULE,
        label_de="Mehrblock-Modul",
        label_en="Multi-Cell Module",
        short_description_de=(
            "Für größere Bauteile, die mehrere Blöcke oder Rasterzellen belegen."
        ),
        long_description_de=(
            "Ein Mehrblock-Modul ist ein zusammenhängendes Library-Element mit einem "
            "mehrzelligen Footprint. Es bleibt fachlich eine einzige Family/Instance, "
            "auch wenn es mehrere Rasterzellen belegt. Es eignet sich für Treppenkerne, "
            "Schächte, Fundamentmodule oder technische Anlagen mit definierter räumlicher "
            "Ausdehnung."
        ),
        examples_de=(
            "Treppenkern",
            "Schacht",
            "Fundamentmodul",
            "Technikblock",
            "mehrzelliges Fertigteil",
        ),
        typical_placement_modes=(
            "centered",
            "bottom_aligned",
            "fill_block",
        ),
        required_module_keys=(
            *_COMMON_REQUIRED_MODULE_KEYS,
            "render",
            "physical",
        ),
        optional_module_keys=(
            "material",
            "calculation",
            "analysis",
            "docs",
            "tests",
        ),
        recommended_module_keys=(
            "material",
            "calculation",
        ),
        supports_glb=True,
        supports_texture=True,
        supports_fallback_color=True,
        supports_multi_cell_footprint=True,
        requires_dynamic_modules=False,
        requires_grid_footprint=True,
        requires_bounds_check=True,
        allows_manufacturer_overlay=True,
        default_grid_footprint=(2, 1, 2),
        min_grid_footprint=(1, 1, 1),
        notes_de=(
            "Mindestens eine Footprint-Dimension sollte größer als 1 sein.",
            "Occupancy- und Collision-Daten sind für diese Objektart besonders wichtig.",
            "Das sichtbare Modell darf nicht größer sein als der gesamte belegte Rasterraum.",
        ),
    ),
    VplibObjectKind.CATALOG_OBJECT: ObjectKindDefinition(
        kind=VplibObjectKind.CATALOG_OBJECT,
        label_de="Katalogobjekt",
        label_en="Catalog Object",
        short_description_de=(
            "Für freie Objekte, Ausstattung oder technische Geräte innerhalb eines Rasterraums."
        ),
        long_description_de=(
            "Ein Katalogobjekt ist ein eher objektartiges Library-Element wie Möbel, "
            "Armatur, Wasserhahn, Wärmepumpe oder Ausstattung. Es kann ein GLB-Modell "
            "oder einfache Renderdaten besitzen. Auch hier bleibt der Raster-Footprint "
            "die Platzierungswahrheit; das sichtbare Modell wird innerhalb dieses "
            "Footprints ausgerichtet."
        ),
        examples_de=(
            "Wasserhahn",
            "Möbel",
            "Armatur",
            "Wärmepumpe",
            "Schaltschrank",
        ),
        typical_placement_modes=(
            "centered",
            "bottom_aligned",
            "top_aligned",
            "surface_aligned",
        ),
        required_module_keys=(
            *_COMMON_REQUIRED_MODULE_KEYS,
            "render",
            "physical",
        ),
        optional_module_keys=(
            "material",
            "calculation",
            "analysis",
            "docs",
            "tests",
        ),
        recommended_module_keys=(
            "physical",
        ),
        supports_glb=True,
        supports_texture=True,
        supports_fallback_color=True,
        supports_multi_cell_footprint=True,
        requires_dynamic_modules=False,
        requires_grid_footprint=True,
        requires_bounds_check=True,
        allows_manufacturer_overlay=True,
        default_grid_footprint=(1, 1, 1),
        min_grid_footprint=(1, 1, 1),
        notes_de=(
            "Katalogobjekte dürfen frei aussehen, müssen aber in ihrem Raster-Footprint bleiben.",
            "surface_aligned ist besonders für Wand-, Decken- oder Anschlussobjekte geeignet.",
            "Technische Tiefe ist optional; nicht jedes Katalogobjekt braucht Statik oder Energieprofile.",
        ),
    ),
    VplibObjectKind.ADAPTIVE_SYSTEM: ObjectKindDefinition(
        kind=VplibObjectKind.ADAPTIVE_SYSTEM,
        label_de="Adaptives System",
        label_en="Adaptive System",
        short_description_de=(
            "Für Elemente, die sich später an einen Kontext, Host oder eine Situation anpassen."
        ),
        long_description_de=(
            "Ein adaptives System beschreibt ein Library-Element, dessen endgültige Form, "
            "Parameter oder Platzierung aus Kontextdaten abgeleitet werden. Beispiele sind "
            "Brückenkappen, Geländer, Randbalken, Leitungssysteme oder andere hostgebundene "
            "Systeme. Adaptive Systeme bleiben deklarativ beschrieben und dürfen keinen "
            "frei ausführbaren Code im Package enthalten."
        ),
        examples_de=(
            "Brückenkappe",
            "Geländer",
            "Randbalken",
            "Leitungssystem",
            "adaptives Tragsystem",
        ),
        typical_placement_modes=(
            "surface_aligned",
            "centered",
        ),
        required_module_keys=(
            *_COMMON_REQUIRED_MODULE_KEYS,
            "dynamic",
        ),
        optional_module_keys=(
            "render",
            "physical",
            "material",
            "calculation",
            "analysis",
            "docs",
            "tests",
        ),
        recommended_module_keys=(
            "render",
            "physical",
            "calculation",
        ),
        supports_glb=True,
        supports_texture=True,
        supports_fallback_color=True,
        supports_multi_cell_footprint=True,
        requires_dynamic_modules=True,
        requires_grid_footprint=False,
        requires_bounds_check=True,
        allows_manufacturer_overlay=True,
        default_grid_footprint=(1, 1, 1),
        min_grid_footprint=(1, 1, 1),
        notes_de=(
            "dynamic/context_rules.json, dynamic/bindings.json und dynamic/generator.json sind Pflicht.",
            "Die adaptive Logik muss deklarativ bleiben.",
            "Ein statisches Preview-Modell ist erlaubt, aber nicht die fachliche Wahrheit des Systems.",
        ),
    ),
}


_ALIAS_MAP: Final[dict[str, VplibObjectKind]] = {
    # Canonical values
    "cell_block": VplibObjectKind.CELL_BLOCK,
    "multi_cell_module": VplibObjectKind.MULTI_CELL_MODULE,
    "catalog_object": VplibObjectKind.CATALOG_OBJECT,
    "adaptive_system": VplibObjectKind.ADAPTIVE_SYSTEM,
    # Common English aliases
    "cellblock": VplibObjectKind.CELL_BLOCK,
    "block": VplibObjectKind.CELL_BLOCK,
    "grid_block": VplibObjectKind.CELL_BLOCK,
    "grid-cell": VplibObjectKind.CELL_BLOCK,
    "grid_cell": VplibObjectKind.CELL_BLOCK,
    "raster_block": VplibObjectKind.CELL_BLOCK,
    "multi_block": VplibObjectKind.MULTI_CELL_MODULE,
    "multiblock": VplibObjectKind.MULTI_CELL_MODULE,
    "multi-cell": VplibObjectKind.MULTI_CELL_MODULE,
    "multi_cell": VplibObjectKind.MULTI_CELL_MODULE,
    "module": VplibObjectKind.MULTI_CELL_MODULE,
    "catalog": VplibObjectKind.CATALOG_OBJECT,
    "object": VplibObjectKind.CATALOG_OBJECT,
    "catalogue_object": VplibObjectKind.CATALOG_OBJECT,
    "free_object": VplibObjectKind.CATALOG_OBJECT,
    "asset": VplibObjectKind.CATALOG_OBJECT,
    "adaptive": VplibObjectKind.ADAPTIVE_SYSTEM,
    "dynamic": VplibObjectKind.ADAPTIVE_SYSTEM,
    "adaptive_model": VplibObjectKind.ADAPTIVE_SYSTEM,
    "dynamic_system": VplibObjectKind.ADAPTIVE_SYSTEM,
    "hosted_system": VplibObjectKind.ADAPTIVE_SYSTEM,
    # German aliases
    "raster-bauteil": VplibObjectKind.CELL_BLOCK,
    "raster_bauteil": VplibObjectKind.CELL_BLOCK,
    "rasterbauteil": VplibObjectKind.CELL_BLOCK,
    "rasterblock": VplibObjectKind.CELL_BLOCK,
    "blockbauteil": VplibObjectKind.CELL_BLOCK,
    "mehrblock-modul": VplibObjectKind.MULTI_CELL_MODULE,
    "mehrblock_modul": VplibObjectKind.MULTI_CELL_MODULE,
    "mehrblockmodul": VplibObjectKind.MULTI_CELL_MODULE,
    "mehrfachblock": VplibObjectKind.MULTI_CELL_MODULE,
    "mehrzellenmodul": VplibObjectKind.MULTI_CELL_MODULE,
    "katalogobjekt": VplibObjectKind.CATALOG_OBJECT,
    "katalog-objekt": VplibObjectKind.CATALOG_OBJECT,
    "freies_objekt": VplibObjectKind.CATALOG_OBJECT,
    "ausstattung": VplibObjectKind.CATALOG_OBJECT,
    "adaptives_system": VplibObjectKind.ADAPTIVE_SYSTEM,
    "adaptiv": VplibObjectKind.ADAPTIVE_SYSTEM,
    "dynamisches_system": VplibObjectKind.ADAPTIVE_SYSTEM,
}


def _normalize_key(value: Any) -> str:
    """
    Normalize arbitrary input into a comparable object-kind key.

    Raises:
        ObjectKindError: If the value cannot be converted into a usable key.
    """
    try:
        if isinstance(value, VplibObjectKind):
            return value.value

        if value is None:
            raise ObjectKindError("Object kind is required, got None.")

        raw = str(value).strip()
        if not raw:
            raise ObjectKindError("Object kind is required, got an empty value.")

        return (
            raw.lower()
            .replace(" ", "_")
            .replace(".", "_")
            .replace("/", "_")
            .replace("\\", "_")
        )
    except ObjectKindError:
        raise
    except Exception as exc:
        raise ObjectKindError(f"Could not normalize object kind {value!r}.") from exc


@lru_cache(maxsize=256)
def parse_object_kind(value: Any) -> VplibObjectKind:
    """
    Parse an object-kind input into a canonical VplibObjectKind.

    Accepts canonical values and a controlled set of aliases. The result is
    cached because this function will be called frequently by planners,
    validators and scanners.

    Raises:
        ObjectKindError: If the value is unknown.
    """
    key = _normalize_key(value)

    try:
        return VplibObjectKind(key)
    except ValueError:
        pass

    try:
        return _ALIAS_MAP[key]
    except KeyError as exc:
        allowed = ", ".join(get_object_kind_values())
        raise ObjectKindError(
            f"Unknown object kind {value!r}. Allowed values: {allowed}."
        ) from exc


def try_parse_object_kind(value: Any, default: VplibObjectKind | None = None) -> VplibObjectKind | None:
    """
    Safe object-kind parser.

    Returns default instead of raising ObjectKindError. This is useful for
    non-fatal scan/report paths.
    """
    try:
        return parse_object_kind(value)
    except ObjectKindError:
        return default
    except Exception:
        return default


def is_valid_object_kind(value: Any) -> bool:
    """Return True if value can be parsed as a canonical object kind."""
    try:
        parse_object_kind(value)
        return True
    except Exception:
        return False


@lru_cache(maxsize=1)
def get_object_kind_values() -> tuple[str, ...]:
    """Return all canonical object-kind string values."""
    return tuple(kind.value for kind in VplibObjectKind)


@lru_cache(maxsize=1)
def get_object_kind_aliases() -> Mapping[str, str]:
    """Return a read-only-style mapping of supported aliases to canonical values."""
    return {alias: kind.value for alias, kind in _ALIAS_MAP.items()}


@lru_cache(maxsize=1)
def get_object_kind_definitions() -> Mapping[VplibObjectKind, ObjectKindDefinition]:
    """Return all canonical object-kind definitions."""
    return dict(_OBJECT_KIND_DEFINITIONS)


@lru_cache(maxsize=32)
def get_object_kind_definition(value: Any) -> ObjectKindDefinition:
    """
    Return the object-kind definition for a value.

    Raises:
        ObjectKindError: If the value is unknown or the definition is missing.
    """
    kind = parse_object_kind(value)

    try:
        return _OBJECT_KIND_DEFINITIONS[kind]
    except KeyError as exc:
        raise ObjectKindError(f"Missing object-kind definition for {kind.value!r}.") from exc


def get_required_module_keys(value: Any) -> tuple[str, ...]:
    """Return required module keys for the given object kind."""
    return get_object_kind_definition(value).required_module_keys


def get_optional_module_keys(value: Any) -> tuple[str, ...]:
    """Return optional module keys for the given object kind."""
    return get_object_kind_definition(value).optional_module_keys


def get_recommended_module_keys(value: Any) -> tuple[str, ...]:
    """Return recommended module keys for the given object kind."""
    return get_object_kind_definition(value).recommended_module_keys


def supports_glb(value: Any) -> bool:
    """Return whether the object kind supports GLB render assets."""
    return get_object_kind_definition(value).supports_glb


def supports_texture(value: Any) -> bool:
    """Return whether the object kind supports texture assets."""
    return get_object_kind_definition(value).supports_texture


def supports_fallback_color(value: Any) -> bool:
    """Return whether the object kind supports fallback color rendering."""
    return get_object_kind_definition(value).supports_fallback_color


def supports_multi_cell_footprint(value: Any) -> bool:
    """Return whether the object kind may occupy multiple grid cells."""
    return get_object_kind_definition(value).supports_multi_cell_footprint


def requires_dynamic_modules(value: Any) -> bool:
    """Return whether the object kind requires dynamic module files."""
    return get_object_kind_definition(value).requires_dynamic_modules


def requires_grid_footprint(value: Any) -> bool:
    """Return whether the object kind requires a grid footprint."""
    return get_object_kind_definition(value).requires_grid_footprint


def requires_bounds_check(value: Any) -> bool:
    """Return whether the object kind requires visual/model bounds validation."""
    return get_object_kind_definition(value).requires_bounds_check


def allows_manufacturer_overlay(value: Any) -> bool:
    """Return whether the object kind allows manufacturer product overlays."""
    return get_object_kind_definition(value).allows_manufacturer_overlay


def get_default_grid_footprint(value: Any) -> tuple[int, int, int]:
    """Return default grid footprint as (x, y, z)."""
    return get_object_kind_definition(value).default_grid_footprint


def get_min_grid_footprint(value: Any) -> tuple[int, int, int]:
    """Return minimum grid footprint as (x, y, z)."""
    return get_object_kind_definition(value).min_grid_footprint


def object_kind_to_json(value: Any) -> dict[str, Any]:
    """
    Serialize one object-kind definition into a JSON-compatible dictionary.
    """
    definition = get_object_kind_definition(value)

    return {
        "schema_version": OBJECT_KIND_SCHEMA_VERSION,
        "kind": definition.kind.value,
        "label_de": definition.label_de,
        "label_en": definition.label_en,
        "short_description_de": definition.short_description_de,
        "long_description_de": definition.long_description_de,
        "examples_de": list(definition.examples_de),
        "typical_placement_modes": list(definition.typical_placement_modes),
        "required_module_keys": list(definition.required_module_keys),
        "optional_module_keys": list(definition.optional_module_keys),
        "recommended_module_keys": list(definition.recommended_module_keys),
        "supports_glb": definition.supports_glb,
        "supports_texture": definition.supports_texture,
        "supports_fallback_color": definition.supports_fallback_color,
        "supports_multi_cell_footprint": definition.supports_multi_cell_footprint,
        "requires_dynamic_modules": definition.requires_dynamic_modules,
        "requires_grid_footprint": definition.requires_grid_footprint,
        "requires_bounds_check": definition.requires_bounds_check,
        "allows_manufacturer_overlay": definition.allows_manufacturer_overlay,
        "default_grid_footprint": list(definition.default_grid_footprint),
        "min_grid_footprint": list(definition.min_grid_footprint),
        "notes_de": list(definition.notes_de),
    }


def all_object_kinds_to_json() -> list[dict[str, Any]]:
    """Serialize all object-kind definitions into JSON-compatible dictionaries."""
    return [object_kind_to_json(kind) for kind in VplibObjectKind]


def ensure_object_kind(value: Any) -> VplibObjectKind:
    """
    Strict parser for call sites that require a valid object kind.

    This is an explicit alias around parse_object_kind to make intent clear in
    planners and validators.
    """
    return parse_object_kind(value)


def ensure_object_kind_value(value: Any) -> str:
    """Return the canonical string value for an object-kind input."""
    return ensure_object_kind(value).value


def filter_valid_object_kinds(values: Iterable[Any]) -> tuple[VplibObjectKind, ...]:
    """
    Parse many values and return only valid object kinds.

    Invalid entries are ignored. Duplicates are removed while preserving order.
    """
    result: list[VplibObjectKind] = []
    seen: set[VplibObjectKind] = set()

    for value in values:
        kind = try_parse_object_kind(value)
        if kind is None or kind in seen:
            continue
        result.append(kind)
        seen.add(kind)

    return tuple(result)


def validate_grid_footprint_for_object_kind(
    object_kind: Any,
    footprint: Sequence[int] | None,
) -> tuple[bool, tuple[str, ...]]:
    """
    Validate whether a grid footprint is plausible for the given object kind.

    This function performs only object-kind-level checks. More detailed bounds,
    physical and occupancy validation belongs in later validator modules.

    Args:
        object_kind: Object-kind value or alias.
        footprint: Sequence of three positive integers: (x, y, z).

    Returns:
        Tuple of (is_valid, messages).
    """
    messages: list[str] = []

    try:
        definition = get_object_kind_definition(object_kind)
    except ObjectKindError as exc:
        return False, (str(exc),)

    if not definition.requires_grid_footprint and footprint is None:
        return True, tuple(messages)

    if footprint is None:
        return False, ("Grid footprint is required for this object kind.",)

    try:
        if len(footprint) != 3:
            return False, ("Grid footprint must contain exactly three dimensions: x, y, z.",)

        x, y, z = (int(footprint[0]), int(footprint[1]), int(footprint[2]))
    except Exception:
        return False, ("Grid footprint must be a sequence of three integers.",)

    if x < 1 or y < 1 or z < 1:
        return False, ("Grid footprint dimensions must be positive integers.",)

    min_x, min_y, min_z = definition.min_grid_footprint
    if x < min_x or y < min_y or z < min_z:
        messages.append(
            f"Grid footprint {(x, y, z)!r} is smaller than minimum "
            f"{definition.min_grid_footprint!r} for {definition.kind.value!r}."
        )

    if definition.kind is VplibObjectKind.CELL_BLOCK and (x, y, z) != (1, 1, 1):
        messages.append(
            "cell_block is intended for simple raster elements. "
            "Use multi_cell_module if the object should occupy multiple cells."
        )

    if definition.kind is VplibObjectKind.MULTI_CELL_MODULE and max(x, y, z) <= 1:
        messages.append(
            "multi_cell_module should occupy more than one cell in at least one dimension."
        )

    return len(messages) == 0, tuple(messages)


def assert_valid_grid_footprint_for_object_kind(
    object_kind: Any,
    footprint: Sequence[int] | None,
) -> None:
    """
    Raise ObjectKindError if the footprint is invalid for the object kind.
    """
    is_valid, messages = validate_grid_footprint_for_object_kind(object_kind, footprint)
    if not is_valid:
        joined = " ".join(messages) if messages else "Invalid grid footprint."
        raise ObjectKindError(joined)


def clear_object_kind_caches() -> None:
    """
    Clear internal lru_cache state.

    Useful for tests and long-running developer sessions.
    """
    parse_object_kind.cache_clear()
    get_object_kind_values.cache_clear()
    get_object_kind_aliases.cache_clear()
    get_object_kind_definitions.cache_clear()
    get_object_kind_definition.cache_clear()


__all__ = [
    "OBJECT_KIND_SCHEMA_VERSION",
    "ObjectKindDefinition",
    "ObjectKindError",
    "VplibObjectKind",
    "all_object_kinds_to_json",
    "allows_manufacturer_overlay",
    "assert_valid_grid_footprint_for_object_kind",
    "clear_object_kind_caches",
    "ensure_object_kind",
    "ensure_object_kind_value",
    "filter_valid_object_kinds",
    "get_default_grid_footprint",
    "get_min_grid_footprint",
    "get_object_kind_aliases",
    "get_object_kind_definition",
    "get_object_kind_definitions",
    "get_object_kind_values",
    "get_optional_module_keys",
    "get_recommended_module_keys",
    "get_required_module_keys",
    "is_valid_object_kind",
    "object_kind_to_json",
    "parse_object_kind",
    "requires_bounds_check",
    "requires_dynamic_modules",
    "requires_grid_footprint",
    "supports_fallback_color",
    "supports_glb",
    "supports_multi_cell_footprint",
    "supports_texture",
    "try_parse_object_kind",
    "validate_grid_footprint_for_object_kind",
]