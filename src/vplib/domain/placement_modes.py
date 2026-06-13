# services/vectoplan-library/src/vplib/domain/placement_modes.py
"""
Canonical VPLIB placement-mode definitions.

Placement modes describe how the visible representation of a Library element
is positioned inside its occupied grid footprint.

Important invariant:
The grid footprint remains the placement truth. A placement mode only describes
how the visible model, texture, fallback shape or GLB is aligned within that
footprint.

Canonical values:
- centered
- bottom_aligned
- top_aligned
- surface_aligned
- fill_block
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from functools import lru_cache
from typing import Any, Final, Iterable, Mapping, Sequence


PLACEMENT_MODE_SCHEMA_VERSION: Final[str] = "vplib.placement_modes.v1"


class PlacementModeError(ValueError):
    """Raised when a placement-mode value cannot be normalized or validated."""


class VplibPlacementMode(str, Enum):
    """
    Canonical placement-mode enum for VPLIB packages.

    Keep these values stable. They may appear in:
    - editor/placement.json
    - render/render_variants.json
    - variants/default.json
    - variants/<variant>.json
    - scanner reports
    - future database rows
    - API responses
    """

    CENTERED = "centered"
    BOTTOM_ALIGNED = "bottom_aligned"
    TOP_ALIGNED = "top_aligned"
    SURFACE_ALIGNED = "surface_aligned"
    FILL_BLOCK = "fill_block"

    @property
    def key(self) -> str:
        """Return the canonical string key."""
        return str(self.value)

    @property
    def is_surface_dependent(self) -> bool:
        """Return whether the mode depends on the placement face or host surface."""
        return self is VplibPlacementMode.SURFACE_ALIGNED

    @property
    def fills_grid_footprint(self) -> bool:
        """Return whether the visible representation is intended to fill the footprint."""
        return self is VplibPlacementMode.FILL_BLOCK

    @property
    def is_vertical_alignment(self) -> bool:
        """Return whether the mode primarily describes vertical alignment."""
        return self in {
            VplibPlacementMode.BOTTOM_ALIGNED,
            VplibPlacementMode.TOP_ALIGNED,
        }

    @property
    def requires_support_surface(self) -> bool:
        """Return whether this mode usually requires a meaningful host/support surface."""
        return self in {
            VplibPlacementMode.BOTTOM_ALIGNED,
            VplibPlacementMode.TOP_ALIGNED,
            VplibPlacementMode.SURFACE_ALIGNED,
        }


@dataclass(frozen=True, slots=True)
class PlacementModeDefinition:
    """
    Metadata for one canonical VPLIB placement mode.

    The mode describes visual/model alignment inside the occupied grid footprint.
    It does not decide project ownership, persistence or final validity.
    """

    mode: VplibPlacementMode
    label_de: str
    label_en: str
    short_description_de: str
    long_description_de: str
    examples_de: tuple[str, ...]
    typical_object_kinds: tuple[str, ...]
    allowed_object_kinds: tuple[str, ...]
    recommended_for: tuple[str, ...]
    not_recommended_for: tuple[str, ...]
    requires_grid_footprint: bool
    requires_surface_normal: bool
    requires_support_surface: bool
    allows_glb: bool
    allows_texture: bool
    allows_fallback_color: bool
    default_anchor: str
    default_pivot: str
    notes_de: tuple[str, ...]


_ALL_OBJECT_KIND_KEYS: Final[tuple[str, ...]] = (
    "cell_block",
    "multi_cell_module",
    "catalog_object",
    "adaptive_system",
)

_GRID_OBJECT_KIND_KEYS: Final[tuple[str, ...]] = (
    "cell_block",
    "multi_cell_module",
    "catalog_object",
)

_PLACEMENT_MODE_DEFINITIONS: Final[dict[VplibPlacementMode, PlacementModeDefinition]] = {
    VplibPlacementMode.CENTERED: PlacementModeDefinition(
        mode=VplibPlacementMode.CENTERED,
        label_de="Mittig im Block",
        label_en="Centered",
        short_description_de=(
            "Das sichtbare Modell sitzt zentriert im belegten Rasterraum."
        ),
        long_description_de=(
            "Der sichtbare Körper, das GLB-Modell oder die Fallback-Geometrie wird "
            "innerhalb des belegten Grid-Footprints mittig ausgerichtet. Diese "
            "Ausrichtung ist neutral und eignet sich für viele einfache Blöcke, "
            "Möbel, technische Objekte oder generische Platzhaltermodelle."
        ),
        examples_de=(
            "neutraler Block",
            "Möbelstück im Raster",
            "technisches Gerät",
            "Preview-Geometrie",
        ),
        typical_object_kinds=(
            "cell_block",
            "multi_cell_module",
            "catalog_object",
            "adaptive_system",
        ),
        allowed_object_kinds=_ALL_OBJECT_KIND_KEYS,
        recommended_for=(
            "neutrale Objekte",
            "symmetrische Objekte",
            "einfache GLB-Modelle",
            "Objekte ohne klare Boden- oder Wandbindung",
        ),
        not_recommended_for=(
            "Bodenmöbel mit klarer Standfläche",
            "Deckenobjekte",
            "Wandaufsätze",
            "Objekte, die exakt ein Bauteilvolumen ausfüllen sollen",
        ),
        requires_grid_footprint=True,
        requires_surface_normal=False,
        requires_support_surface=False,
        allows_glb=True,
        allows_texture=True,
        allows_fallback_color=True,
        default_anchor="center",
        default_pivot="center",
        notes_de=(
            "Der Raster-Footprint bleibt die Platzierungswahrheit.",
            "Zentrierung ist der sicherste Default, wenn keine bessere Fachbindung bekannt ist.",
            "Das sichtbare Modell darf den belegten Rasterraum nicht überschreiten.",
        ),
    ),
    VplibPlacementMode.BOTTOM_ALIGNED: PlacementModeDefinition(
        mode=VplibPlacementMode.BOTTOM_ALIGNED,
        label_de="Bodenaufliegend",
        label_en="Bottom aligned",
        short_description_de=(
            "Das sichtbare Modell liegt unten im belegten Rasterraum auf."
        ),
        long_description_de=(
            "Der sichtbare Körper wird innerhalb des belegten Grid-Footprints nach "
            "unten ausgerichtet. Das ist sinnvoll für Objekte, die im Editor auf dem "
            "Boden, einer Decke, einem Fundament oder einer anderen tragenden Fläche "
            "stehen sollen."
        ),
        examples_de=(
            "Möbel",
            "Wärmepumpe",
            "Schaltschrank",
            "Maschine",
            "Bodenobjekt",
        ),
        typical_object_kinds=(
            "multi_cell_module",
            "catalog_object",
        ),
        allowed_object_kinds=_GRID_OBJECT_KIND_KEYS,
        recommended_for=(
            "Möbel",
            "Geräte",
            "stehende Technikobjekte",
            "mehrzellige Module mit Grundfläche",
        ),
        not_recommended_for=(
            "Deckenobjekte",
            "wandhängende Objekte",
            "vollvolumige Rasterblöcke",
            "adaptive hostabhängige Systeme ohne festen Bodenbezug",
        ),
        requires_grid_footprint=True,
        requires_surface_normal=False,
        requires_support_surface=True,
        allows_glb=True,
        allows_texture=True,
        allows_fallback_color=True,
        default_anchor="bottom_center",
        default_pivot="bottom_center",
        notes_de=(
            "Geeignet für Objekte, die sichtbar auf einer unteren Fläche stehen.",
            "Die untere Modellkante sollte mit der unteren Grenze des belegten Rasterraums übereinstimmen.",
            "Für reine Blockvolumen ist fill_block meist präziser.",
        ),
    ),
    VplibPlacementMode.TOP_ALIGNED: PlacementModeDefinition(
        mode=VplibPlacementMode.TOP_ALIGNED,
        label_de="Oben / deckenbündig",
        label_en="Top aligned",
        short_description_de=(
            "Das sichtbare Modell liegt oben im belegten Rasterraum an."
        ),
        long_description_de=(
            "Der sichtbare Körper wird innerhalb des belegten Grid-Footprints nach "
            "oben ausgerichtet. Das ist sinnvoll für Deckenobjekte, Unterzüge, "
            "abgehängte Elemente oder Leitungen, die an der oberen Grenze ihres "
            "Platzierungsraums liegen sollen."
        ),
        examples_de=(
            "Deckenobjekt",
            "Unterzug",
            "Deckenleuchte",
            "Rohr unter Decke",
            "abgehängtes Bauteil",
        ),
        typical_object_kinds=(
            "cell_block",
            "catalog_object",
        ),
        allowed_object_kinds=_GRID_OBJECT_KIND_KEYS,
        recommended_for=(
            "Deckenobjekte",
            "Unterzüge",
            "oben anschließende Leitungen",
            "hängende technische Objekte",
        ),
        not_recommended_for=(
            "Bodenmöbel",
            "freie neutrale Objekte",
            "vollvolumige Rasterblöcke",
            "Objekte ohne oberen Bezug",
        ),
        requires_grid_footprint=True,
        requires_surface_normal=False,
        requires_support_surface=True,
        allows_glb=True,
        allows_texture=True,
        allows_fallback_color=True,
        default_anchor="top_center",
        default_pivot="top_center",
        notes_de=(
            "Geeignet für Objekte mit klarer Decken- oder Oberkantenbindung.",
            "Die obere Modellkante sollte mit der oberen Grenze des belegten Rasterraums übereinstimmen.",
            "Für flexible Host-Bindungen ist surface_aligned oft besser.",
        ),
    ),
    VplibPlacementMode.SURFACE_ALIGNED: PlacementModeDefinition(
        mode=VplibPlacementMode.SURFACE_ALIGNED,
        label_de="An Platzierfläche ausrichten",
        label_en="Surface aligned",
        short_description_de=(
            "Das sichtbare Modell wird automatisch an die Fläche gelegt, auf der es platziert wird."
        ),
        long_description_de=(
            "Der sichtbare Körper wird anhand der getroffenen Platzierfläche und ihrer "
            "Normalen ausgerichtet. Das ist besonders wichtig für Wandobjekte, "
            "Deckenobjekte, Rohre, Armaturen, Leitungen oder adaptive Systeme, die "
            "nicht einfach nur mittig in einer Rasterzelle sitzen sollen."
        ),
        examples_de=(
            "Wasserhahn an Wand/Objekt",
            "Rohr an Wand oder Decke",
            "Wandobjekt",
            "Deckenobjekt",
            "hostgebundenes adaptives Element",
        ),
        typical_object_kinds=(
            "catalog_object",
            "adaptive_system",
        ),
        allowed_object_kinds=(
            "cell_block",
            "multi_cell_module",
            "catalog_object",
            "adaptive_system",
        ),
        recommended_for=(
            "Wandobjekte",
            "Deckenobjekte",
            "Rohre",
            "Armaturen",
            "hostabhängige adaptive Systeme",
        ),
        not_recommended_for=(
            "einfache Vollblöcke",
            "symmetrische neutrale Objekte",
            "Objekte ohne Host- oder Flächenbezug",
        ),
        requires_grid_footprint=True,
        requires_surface_normal=True,
        requires_support_surface=True,
        allows_glb=True,
        allows_texture=True,
        allows_fallback_color=True,
        default_anchor="surface_center",
        default_pivot="surface_contact",
        notes_de=(
            "Benötigt im Editor eine Ziel-/Flächennormale.",
            "Die endgültige fachliche Validierung bleibt später beim Core oder zuständigen Fachservice.",
            "Für adaptive Systeme ist diese Ausrichtung oft der fachlich beste Startpunkt.",
        ),
    ),
    VplibPlacementMode.FILL_BLOCK: PlacementModeDefinition(
        mode=VplibPlacementMode.FILL_BLOCK,
        label_de="Block vollständig ausfüllen",
        label_en="Fill block",
        short_description_de=(
            "Das sichtbare Modell füllt den belegten Rasterraum vollständig."
        ),
        long_description_de=(
            "Der sichtbare Körper soll den gesamten belegten Grid-Footprint ausfüllen. "
            "Das ist sinnvoll für echte Block- oder Bauteilvolumen wie Wandblöcke, "
            "Deckenelemente, Straßenblöcke oder andere Volumenkörper, deren sichtbare "
            "Darstellung der belegten Rasterfläche entspricht."
        ),
        examples_de=(
            "Wandblock",
            "Deckenelement",
            "Straßenblock",
            "Bodenblock",
            "volumetrisches Bauteil",
        ),
        typical_object_kinds=(
            "cell_block",
            "multi_cell_module",
        ),
        allowed_object_kinds=(
            "cell_block",
            "multi_cell_module",
        ),
        recommended_for=(
            "echte Blockvolumen",
            "Bauteile mit voller Zellausfüllung",
            "einfache Rasterbauteile",
            "volumetrische Module",
        ),
        not_recommended_for=(
            "kleine GLB-Objekte",
            "Möbel",
            "Armaturen",
            "Wandobjekte",
            "Deckenobjekte",
            "adaptive Systeme mit Host-Kontext",
        ),
        requires_grid_footprint=True,
        requires_surface_normal=False,
        requires_support_surface=False,
        allows_glb=True,
        allows_texture=True,
        allows_fallback_color=True,
        default_anchor="bounds",
        default_pivot="center",
        notes_de=(
            "Geeignet für echte Bauteilvolumen.",
            "Wenn ein GLB verwendet wird, muss es den Footprint plausibel ausfüllen und darf ihn nicht überschreiten.",
            "Für Möbel oder Armaturen ist centered, bottom_aligned oder surface_aligned meist passender.",
        ),
    ),
}


_ALIAS_MAP: Final[dict[str, VplibPlacementMode]] = {
    # Canonical values
    "centered": VplibPlacementMode.CENTERED,
    "bottom_aligned": VplibPlacementMode.BOTTOM_ALIGNED,
    "top_aligned": VplibPlacementMode.TOP_ALIGNED,
    "surface_aligned": VplibPlacementMode.SURFACE_ALIGNED,
    "fill_block": VplibPlacementMode.FILL_BLOCK,
    # English aliases
    "center": VplibPlacementMode.CENTERED,
    "centre": VplibPlacementMode.CENTERED,
    "middle": VplibPlacementMode.CENTERED,
    "middle_aligned": VplibPlacementMode.CENTERED,
    "inside_center": VplibPlacementMode.CENTERED,
    "bottom": VplibPlacementMode.BOTTOM_ALIGNED,
    "floor": VplibPlacementMode.BOTTOM_ALIGNED,
    "floor_aligned": VplibPlacementMode.BOTTOM_ALIGNED,
    "on_floor": VplibPlacementMode.BOTTOM_ALIGNED,
    "grounded": VplibPlacementMode.BOTTOM_ALIGNED,
    "ground_aligned": VplibPlacementMode.BOTTOM_ALIGNED,
    "top": VplibPlacementMode.TOP_ALIGNED,
    "ceiling": VplibPlacementMode.TOP_ALIGNED,
    "ceiling_aligned": VplibPlacementMode.TOP_ALIGNED,
    "top_flush": VplibPlacementMode.TOP_ALIGNED,
    "surface": VplibPlacementMode.SURFACE_ALIGNED,
    "face": VplibPlacementMode.SURFACE_ALIGNED,
    "face_aligned": VplibPlacementMode.SURFACE_ALIGNED,
    "host_aligned": VplibPlacementMode.SURFACE_ALIGNED,
    "attach_to_surface": VplibPlacementMode.SURFACE_ALIGNED,
    "fill": VplibPlacementMode.FILL_BLOCK,
    "full": VplibPlacementMode.FILL_BLOCK,
    "full_block": VplibPlacementMode.FILL_BLOCK,
    "fill_footprint": VplibPlacementMode.FILL_BLOCK,
    "fill_grid": VplibPlacementMode.FILL_BLOCK,
    "block_fill": VplibPlacementMode.FILL_BLOCK,
    # German aliases
    "mittig": VplibPlacementMode.CENTERED,
    "zentriert": VplibPlacementMode.CENTERED,
    "zentriert_im_block": VplibPlacementMode.CENTERED,
    "mitte": VplibPlacementMode.CENTERED,
    "boden": VplibPlacementMode.BOTTOM_ALIGNED,
    "bodenaufliegend": VplibPlacementMode.BOTTOM_ALIGNED,
    "boden_aufliegend": VplibPlacementMode.BOTTOM_ALIGNED,
    "unten": VplibPlacementMode.BOTTOM_ALIGNED,
    "unten_ausgerichtet": VplibPlacementMode.BOTTOM_ALIGNED,
    "auf_boden": VplibPlacementMode.BOTTOM_ALIGNED,
    "oben": VplibPlacementMode.TOP_ALIGNED,
    "deckenbuendig": VplibPlacementMode.TOP_ALIGNED,
    "deckenbündig": VplibPlacementMode.TOP_ALIGNED,
    "oben_ausgerichtet": VplibPlacementMode.TOP_ALIGNED,
    "an_decke": VplibPlacementMode.TOP_ALIGNED,
    "platzierflaeche": VplibPlacementMode.SURFACE_ALIGNED,
    "platzierfläche": VplibPlacementMode.SURFACE_ALIGNED,
    "an_platzierflaeche": VplibPlacementMode.SURFACE_ALIGNED,
    "an_platzierfläche": VplibPlacementMode.SURFACE_ALIGNED,
    "an_flaeche": VplibPlacementMode.SURFACE_ALIGNED,
    "an_fläche": VplibPlacementMode.SURFACE_ALIGNED,
    "flaechenbuendig": VplibPlacementMode.SURFACE_ALIGNED,
    "flächenbündig": VplibPlacementMode.SURFACE_ALIGNED,
    "block_vollstaendig": VplibPlacementMode.FILL_BLOCK,
    "block_vollständig": VplibPlacementMode.FILL_BLOCK,
    "vollstaendig_ausfuellen": VplibPlacementMode.FILL_BLOCK,
    "vollständig_ausfüllen": VplibPlacementMode.FILL_BLOCK,
    "vollblock": VplibPlacementMode.FILL_BLOCK,
    "block_fuellen": VplibPlacementMode.FILL_BLOCK,
    "block_füllen": VplibPlacementMode.FILL_BLOCK,
}


def _normalize_key(value: Any) -> str:
    """
    Normalize arbitrary input into a comparable placement-mode key.

    Raises:
        PlacementModeError: If the value cannot be converted into a usable key.
    """
    try:
        if isinstance(value, VplibPlacementMode):
            return value.value

        if value is None:
            raise PlacementModeError("Placement mode is required, got None.")

        raw = str(value).strip()
        if not raw:
            raise PlacementModeError("Placement mode is required, got an empty value.")

        return (
            raw.lower()
            .replace(" ", "_")
            .replace(".", "_")
            .replace("/", "_")
            .replace("\\", "_")
            .replace("-", "_")
        )
    except PlacementModeError:
        raise
    except Exception as exc:
        raise PlacementModeError(f"Could not normalize placement mode {value!r}.") from exc


@lru_cache(maxsize=256)
def parse_placement_mode(value: Any) -> VplibPlacementMode:
    """
    Parse a placement-mode input into a canonical VplibPlacementMode.

    Accepts canonical values and a controlled set of aliases. The result is
    cached because this function will be called frequently by planners,
    validators and scanners.

    Raises:
        PlacementModeError: If the value is unknown.
    """
    key = _normalize_key(value)

    try:
        return VplibPlacementMode(key)
    except ValueError:
        pass

    try:
        return _ALIAS_MAP[key]
    except KeyError as exc:
        allowed = ", ".join(get_placement_mode_values())
        raise PlacementModeError(
            f"Unknown placement mode {value!r}. Allowed values: {allowed}."
        ) from exc


def try_parse_placement_mode(
    value: Any,
    default: VplibPlacementMode | None = None,
) -> VplibPlacementMode | None:
    """
    Safe placement-mode parser.

    Returns default instead of raising PlacementModeError. This is useful for
    non-fatal scan/report paths.
    """
    try:
        return parse_placement_mode(value)
    except PlacementModeError:
        return default
    except Exception:
        return default


def is_valid_placement_mode(value: Any) -> bool:
    """Return True if value can be parsed as a canonical placement mode."""
    try:
        parse_placement_mode(value)
        return True
    except Exception:
        return False


@lru_cache(maxsize=1)
def get_placement_mode_values() -> tuple[str, ...]:
    """Return all canonical placement-mode string values."""
    return tuple(mode.value for mode in VplibPlacementMode)


@lru_cache(maxsize=1)
def get_placement_mode_aliases() -> Mapping[str, str]:
    """Return a read-only-style mapping of supported aliases to canonical values."""
    return {alias: mode.value for alias, mode in _ALIAS_MAP.items()}


@lru_cache(maxsize=1)
def get_placement_mode_definitions() -> Mapping[VplibPlacementMode, PlacementModeDefinition]:
    """Return all canonical placement-mode definitions."""
    return dict(_PLACEMENT_MODE_DEFINITIONS)


@lru_cache(maxsize=32)
def get_placement_mode_definition(value: Any) -> PlacementModeDefinition:
    """
    Return the placement-mode definition for a value.

    Raises:
        PlacementModeError: If the value is unknown or the definition is missing.
    """
    mode = parse_placement_mode(value)

    try:
        return _PLACEMENT_MODE_DEFINITIONS[mode]
    except KeyError as exc:
        raise PlacementModeError(f"Missing placement-mode definition for {mode.value!r}.") from exc


def ensure_placement_mode(value: Any) -> VplibPlacementMode:
    """
    Strict parser for call sites that require a valid placement mode.

    This is an explicit alias around parse_placement_mode to make intent clear
    in planners and validators.
    """
    return parse_placement_mode(value)


def ensure_placement_mode_value(value: Any) -> str:
    """Return the canonical string value for a placement-mode input."""
    return ensure_placement_mode(value).value


def filter_valid_placement_modes(values: Iterable[Any]) -> tuple[VplibPlacementMode, ...]:
    """
    Parse many values and return only valid placement modes.

    Invalid entries are ignored. Duplicates are removed while preserving order.
    """
    result: list[VplibPlacementMode] = []
    seen: set[VplibPlacementMode] = set()

    for value in values:
        mode = try_parse_placement_mode(value)
        if mode is None or mode in seen:
            continue
        result.append(mode)
        seen.add(mode)

    return tuple(result)


def _normalize_object_kind_value(value: Any) -> str:
    """
    Normalize an object-kind value without requiring object_kinds.py at runtime.

    This avoids a hard dependency for basic placement-mode operations. If
    object_kinds.py is available, its parser is used first.
    """
    try:
        from .object_kinds import ensure_object_kind_value

        return ensure_object_kind_value(value)
    except Exception:
        try:
            raw = str(value).strip()
            if not raw:
                return ""
            return (
                raw.lower()
                .replace(" ", "_")
                .replace(".", "_")
                .replace("/", "_")
                .replace("\\", "_")
                .replace("-", "_")
            )
        except Exception:
            return ""


def is_placement_mode_allowed_for_object_kind(
    placement_mode: Any,
    object_kind: Any,
) -> bool:
    """
    Return whether a placement mode is allowed for an object kind.

    This is a broad compatibility check. More detailed host, surface, anchor and
    collision checks belong in later placement and validation modules.
    """
    try:
        definition = get_placement_mode_definition(placement_mode)
        kind_value = _normalize_object_kind_value(object_kind)
        return kind_value in definition.allowed_object_kinds
    except Exception:
        return False


def is_placement_mode_typical_for_object_kind(
    placement_mode: Any,
    object_kind: Any,
) -> bool:
    """
    Return whether a placement mode is typical/recommended for an object kind.
    """
    try:
        definition = get_placement_mode_definition(placement_mode)
        kind_value = _normalize_object_kind_value(object_kind)
        return kind_value in definition.typical_object_kinds
    except Exception:
        return False


def get_allowed_placement_modes_for_object_kind(object_kind: Any) -> tuple[VplibPlacementMode, ...]:
    """
    Return all placement modes allowed for the given object kind.
    """
    kind_value = _normalize_object_kind_value(object_kind)
    if not kind_value:
        return tuple()

    result: list[VplibPlacementMode] = []
    for mode, definition in _PLACEMENT_MODE_DEFINITIONS.items():
        if kind_value in definition.allowed_object_kinds:
            result.append(mode)

    return tuple(result)


def get_typical_placement_modes_for_object_kind(object_kind: Any) -> tuple[VplibPlacementMode, ...]:
    """
    Return typical/recommended placement modes for the given object kind.
    """
    kind_value = _normalize_object_kind_value(object_kind)
    if not kind_value:
        return tuple()

    result: list[VplibPlacementMode] = []
    for mode, definition in _PLACEMENT_MODE_DEFINITIONS.items():
        if kind_value in definition.typical_object_kinds:
            result.append(mode)

    return tuple(result)


def get_default_placement_mode_for_object_kind(object_kind: Any) -> VplibPlacementMode:
    """
    Return a safe default placement mode for an object kind.

    Defaults are intentionally conservative:
    - cell_block: fill_block
    - multi_cell_module: centered
    - catalog_object: centered
    - adaptive_system: surface_aligned
    """
    kind_value = _normalize_object_kind_value(object_kind)

    if kind_value == "cell_block":
        return VplibPlacementMode.FILL_BLOCK

    if kind_value == "multi_cell_module":
        return VplibPlacementMode.CENTERED

    if kind_value == "catalog_object":
        return VplibPlacementMode.CENTERED

    if kind_value == "adaptive_system":
        return VplibPlacementMode.SURFACE_ALIGNED

    return VplibPlacementMode.CENTERED


def requires_surface_normal(value: Any) -> bool:
    """Return whether the placement mode requires a surface normal."""
    return get_placement_mode_definition(value).requires_surface_normal


def requires_support_surface(value: Any) -> bool:
    """Return whether the placement mode usually requires a support/host surface."""
    return get_placement_mode_definition(value).requires_support_surface


def requires_grid_footprint(value: Any) -> bool:
    """Return whether the placement mode requires a grid footprint."""
    return get_placement_mode_definition(value).requires_grid_footprint


def placement_mode_allows_glb(value: Any) -> bool:
    """Return whether the placement mode allows GLB-backed rendering."""
    return get_placement_mode_definition(value).allows_glb


def placement_mode_allows_texture(value: Any) -> bool:
    """Return whether the placement mode allows texture-backed rendering."""
    return get_placement_mode_definition(value).allows_texture


def placement_mode_allows_fallback_color(value: Any) -> bool:
    """Return whether the placement mode allows fallback-color rendering."""
    return get_placement_mode_definition(value).allows_fallback_color


def get_default_anchor(value: Any) -> str:
    """Return the default anchor key for a placement mode."""
    return get_placement_mode_definition(value).default_anchor


def get_default_pivot(value: Any) -> str:
    """Return the default pivot key for a placement mode."""
    return get_placement_mode_definition(value).default_pivot


def validate_placement_mode_for_object_kind(
    placement_mode: Any,
    object_kind: Any,
) -> tuple[bool, tuple[str, ...]]:
    """
    Validate whether a placement mode is compatible with an object kind.

    Returns:
        Tuple of (is_valid, messages).
    """
    messages: list[str] = []

    try:
        mode_definition = get_placement_mode_definition(placement_mode)
    except PlacementModeError as exc:
        return False, (str(exc),)

    kind_value = _normalize_object_kind_value(object_kind)
    if not kind_value:
        return False, ("Object kind is required for placement-mode validation.",)

    if kind_value not in mode_definition.allowed_object_kinds:
        messages.append(
            f"Placement mode {mode_definition.mode.value!r} is not allowed for "
            f"object kind {kind_value!r}."
        )

    if kind_value not in mode_definition.typical_object_kinds:
        messages.append(
            f"Placement mode {mode_definition.mode.value!r} is allowed but not typical "
            f"for object kind {kind_value!r}."
        )

    return len(messages) == 0, tuple(messages)


def assert_valid_placement_mode_for_object_kind(
    placement_mode: Any,
    object_kind: Any,
) -> None:
    """
    Raise PlacementModeError if a placement mode is not valid for an object kind.
    """
    is_valid, messages = validate_placement_mode_for_object_kind(
        placement_mode=placement_mode,
        object_kind=object_kind,
    )
    if not is_valid:
        joined = " ".join(messages) if messages else "Invalid placement mode."
        raise PlacementModeError(joined)


def placement_mode_to_json(value: Any) -> dict[str, Any]:
    """
    Serialize one placement-mode definition into a JSON-compatible dictionary.
    """
    definition = get_placement_mode_definition(value)

    return {
        "schema_version": PLACEMENT_MODE_SCHEMA_VERSION,
        "mode": definition.mode.value,
        "label_de": definition.label_de,
        "label_en": definition.label_en,
        "short_description_de": definition.short_description_de,
        "long_description_de": definition.long_description_de,
        "examples_de": list(definition.examples_de),
        "typical_object_kinds": list(definition.typical_object_kinds),
        "allowed_object_kinds": list(definition.allowed_object_kinds),
        "recommended_for": list(definition.recommended_for),
        "not_recommended_for": list(definition.not_recommended_for),
        "requires_grid_footprint": definition.requires_grid_footprint,
        "requires_surface_normal": definition.requires_surface_normal,
        "requires_support_surface": definition.requires_support_surface,
        "allows_glb": definition.allows_glb,
        "allows_texture": definition.allows_texture,
        "allows_fallback_color": definition.allows_fallback_color,
        "default_anchor": definition.default_anchor,
        "default_pivot": definition.default_pivot,
        "notes_de": list(definition.notes_de),
    }


def all_placement_modes_to_json() -> list[dict[str, Any]]:
    """Serialize all placement-mode definitions into JSON-compatible dictionaries."""
    return [placement_mode_to_json(mode) for mode in VplibPlacementMode]


def build_editor_placement_defaults(
    object_kind: Any,
    placement_mode: Any | None = None,
) -> dict[str, Any]:
    """
    Build a safe default payload for editor/placement.json.

    This function is intentionally small and generic. Later document builders can
    enrich this with grid footprint, rotation, snapping, anchors and targeting.
    """
    mode = (
        get_default_placement_mode_for_object_kind(object_kind)
        if placement_mode is None
        else parse_placement_mode(placement_mode)
    )

    definition = get_placement_mode_definition(mode)

    return {
        "placement_mode": mode.value,
        "anchor": definition.default_anchor,
        "pivot": definition.default_pivot,
        "requires_surface_normal": definition.requires_surface_normal,
        "requires_support_surface": definition.requires_support_surface,
        "grid_footprint_is_placement_truth": True,
        "visual_model_must_remain_inside_footprint": True,
    }


def clear_placement_mode_caches() -> None:
    """
    Clear internal lru_cache state.

    Useful for tests and long-running developer sessions.
    """
    parse_placement_mode.cache_clear()
    get_placement_mode_values.cache_clear()
    get_placement_mode_aliases.cache_clear()
    get_placement_mode_definitions.cache_clear()
    get_placement_mode_definition.cache_clear()


__all__ = [
    "PLACEMENT_MODE_SCHEMA_VERSION",
    "PlacementModeDefinition",
    "PlacementModeError",
    "VplibPlacementMode",
    "all_placement_modes_to_json",
    "assert_valid_placement_mode_for_object_kind",
    "build_editor_placement_defaults",
    "clear_placement_mode_caches",
    "ensure_placement_mode",
    "ensure_placement_mode_value",
    "filter_valid_placement_modes",
    "get_allowed_placement_modes_for_object_kind",
    "get_default_anchor",
    "get_default_pivot",
    "get_default_placement_mode_for_object_kind",
    "get_placement_mode_aliases",
    "get_placement_mode_definition",
    "get_placement_mode_definitions",
    "get_placement_mode_values",
    "get_typical_placement_modes_for_object_kind",
    "is_placement_mode_allowed_for_object_kind",
    "is_placement_mode_typical_for_object_kind",
    "is_valid_placement_mode",
    "parse_placement_mode",
    "placement_mode_allows_fallback_color",
    "placement_mode_allows_glb",
    "placement_mode_allows_texture",
    "placement_mode_to_json",
    "requires_grid_footprint",
    "requires_support_surface",
    "requires_surface_normal",
    "try_parse_placement_mode",
    "validate_placement_mode_for_object_kind",
]