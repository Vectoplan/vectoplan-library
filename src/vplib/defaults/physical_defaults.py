# services/vectoplan-library/src/vplib/defaults/physical_defaults.py
"""
Physical defaults for the VPLIB package engine.

Diese Datei erzeugt robuste Default-Daten für:

    physical/base.json
    physical/dimensions.json
    physical/collision.json
    optional: physical/occupancy.json
    optional: physical/layers.json
    optional: physical/mass.json
    optional: physical/bounds.json
    optional: physical/footprint.json

Physical-Daten beschreiben reale Abmessungen, Kollision, Belegung,
Masse, Dichte, Layer und einfache technische Basiseigenschaften.

Wichtig:
Der Grid-Footprint bleibt die Platzierungswahrheit. Physical-Daten dürfen diese
Wahrheit präzisieren, aber nicht widersprechen.

Diese Datei schreibt keine Dateien. Sie erzeugt nur JSON-kompatible Payloads.

Technische Namen, JSON-Keys und Variablen bleiben Englisch.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from functools import lru_cache
from typing import Any, Final, Iterable, Mapping, Sequence


PHYSICAL_DEFAULTS_SCHEMA_VERSION: Final[str] = "vplib.physical_defaults.v1"
PHYSICAL_BASE_DOCUMENT_SCHEMA_VERSION: Final[str] = "vplib.physical.base.v1"
PHYSICAL_DIMENSIONS_DOCUMENT_SCHEMA_VERSION: Final[str] = "vplib.physical.dimensions.v1"
PHYSICAL_COLLISION_DOCUMENT_SCHEMA_VERSION: Final[str] = "vplib.physical.collision.v1"
PHYSICAL_OCCUPANCY_DOCUMENT_SCHEMA_VERSION: Final[str] = "vplib.physical.occupancy.v1"
PHYSICAL_LAYERS_DOCUMENT_SCHEMA_VERSION: Final[str] = "vplib.physical.layers.v1"
PHYSICAL_MASS_DOCUMENT_SCHEMA_VERSION: Final[str] = "vplib.physical.mass.v1"
PHYSICAL_BOUNDS_DOCUMENT_SCHEMA_VERSION: Final[str] = "vplib.physical.bounds.v1"
PHYSICAL_FOOTPRINT_DOCUMENT_SCHEMA_VERSION: Final[str] = "vplib.physical.footprint.v1"

DEFAULT_CELL_SIZE_M: Final[float] = 1.0
DEFAULT_GRID_SIZE_CELLS: Final[tuple[int, int, int]] = (1, 1, 1)
DEFAULT_DENSITY_KG_M3: Final[float] = 0.0
MAX_EXPLICIT_OCCUPANCY_CELLS: Final[int] = 512


class PhysicalDefaultsError(ValueError):
    """Wird ausgelöst, wenn Physical-Defaults ungültig erzeugt werden."""


class PhysicalShape(str, Enum):
    """Physische Grundform."""

    BOX = "box"
    CUSTOM_BOUNDS = "custom_bounds"
    MESH_BOUNDS = "mesh_bounds"
    NONE = "none"

    @property
    def key(self) -> str:
        return str(self.value)


class PhysicalRole(str, Enum):
    """Fachliche physische Rolle."""

    GENERIC = "generic"
    WALL = "wall"
    SLAB = "slab"
    FLOOR = "floor"
    ROOF = "roof"
    FOUNDATION = "foundation"
    EQUIPMENT = "equipment"
    FURNITURE = "furniture"
    STRUCTURAL = "structural"
    INFRASTRUCTURE = "infrastructure"
    ADAPTIVE = "adaptive"

    @property
    def key(self) -> str:
        return str(self.value)


class CollisionMode(str, Enum):
    """Kollisionsmodus."""

    SOLID = "solid"
    BOUNDS = "bounds"
    TRIGGER = "trigger"
    NONE = "none"

    @property
    def key(self) -> str:
        return str(self.value)


class OccupancyMode(str, Enum):
    """Occupancy-Modus."""

    FOOTPRINT_BOX = "footprint_box"
    EXPLICIT_CELLS = "explicit_cells"
    BOUNDS = "bounds"
    NONE = "none"

    @property
    def key(self) -> str:
        return str(self.value)


class MassSource(str, Enum):
    """Quelle der Massenberechnung."""

    EXPLICIT = "explicit"
    COMPUTED_FROM_DENSITY = "computed_from_density"
    UNKNOWN = "unknown"

    @property
    def key(self) -> str:
        return str(self.value)


class LayerKind(str, Enum):
    """Layer-Art."""

    STRUCTURAL = "structural"
    FINISH = "finish"
    INSULATION = "insulation"
    AIR_GAP = "air_gap"
    MEMBRANE = "membrane"
    CORE = "core"
    OTHER = "other"

    @property
    def key(self) -> str:
        return str(self.value)


@dataclass(frozen=True, slots=True)
class Vector3Defaults:
    """3D-Vektor."""

    x: float
    y: float
    z: float

    def normalized(self) -> "Vector3Defaults":
        return Vector3Defaults(
            x=normalize_float(self.x, "x"),
            y=normalize_float(self.y, "y"),
            z=normalize_float(self.z, "z"),
        )

    def to_dict(self) -> dict[str, Any]:
        normalized = self.normalized()
        return {"x": normalized.x, "y": normalized.y, "z": normalized.z}


@dataclass(frozen=True, slots=True)
class GridSizeDefaults:
    """Rastergröße und Zellgröße."""

    size_cells_x: int = 1
    size_cells_y: int = 1
    size_cells_z: int = 1
    cell_size_m: float = DEFAULT_CELL_SIZE_M

    def normalized(self) -> "GridSizeDefaults":
        return GridSizeDefaults(
            size_cells_x=normalize_positive_int(self.size_cells_x, "size_cells_x"),
            size_cells_y=normalize_positive_int(self.size_cells_y, "size_cells_y"),
            size_cells_z=normalize_positive_int(self.size_cells_z, "size_cells_z"),
            cell_size_m=normalize_positive_float(self.cell_size_m, "cell_size_m"),
        )

    @property
    def size_cells(self) -> tuple[int, int, int]:
        normalized = self.normalized()
        return (
            normalized.size_cells_x,
            normalized.size_cells_y,
            normalized.size_cells_z,
        )

    @property
    def size_m(self) -> tuple[float, float, float]:
        normalized = self.normalized()
        return (
            normalized.size_cells_x * normalized.cell_size_m,
            normalized.size_cells_y * normalized.cell_size_m,
            normalized.size_cells_z * normalized.cell_size_m,
        )

    @property
    def cell_count(self) -> int:
        normalized = self.normalized()
        return normalized.size_cells_x * normalized.size_cells_y * normalized.size_cells_z

    def to_dict(self) -> dict[str, Any]:
        normalized = self.normalized()
        size_m = normalized.size_m

        return {
            "size_cells": {
                "x": normalized.size_cells_x,
                "y": normalized.size_cells_y,
                "z": normalized.size_cells_z,
            },
            "size_cells_x": normalized.size_cells_x,
            "size_cells_y": normalized.size_cells_y,
            "size_cells_z": normalized.size_cells_z,
            "cell_size_m": normalized.cell_size_m,
            "cell_count": normalized.cell_count,
            "size_m": {
                "x": size_m[0],
                "y": size_m[1],
                "z": size_m[2],
            },
        }


@dataclass(frozen=True, slots=True)
class PhysicalBoundsDefaults:
    """Physische Bounds in Metern."""

    width_m: float
    height_m: float
    depth_m: float
    offset_m: Vector3Defaults = field(default_factory=lambda: Vector3Defaults(0.0, 0.0, 0.0))
    origin_m: Vector3Defaults = field(default_factory=lambda: Vector3Defaults(0.0, 0.0, 0.0))
    must_fit_grid_footprint: bool = True
    metadata: Mapping[str, Any] = field(default_factory=dict)

    def normalized(self) -> "PhysicalBoundsDefaults":
        return PhysicalBoundsDefaults(
            width_m=normalize_positive_float(self.width_m, "width_m"),
            height_m=normalize_positive_float(self.height_m, "height_m"),
            depth_m=normalize_positive_float(self.depth_m, "depth_m"),
            offset_m=self.offset_m.normalized(),
            origin_m=self.origin_m.normalized(),
            must_fit_grid_footprint=bool(self.must_fit_grid_footprint),
            metadata=normalize_metadata(self.metadata),
        )

    @property
    def size_m(self) -> tuple[float, float, float]:
        normalized = self.normalized()
        return (normalized.width_m, normalized.height_m, normalized.depth_m)

    @property
    def volume_m3(self) -> float:
        normalized = self.normalized()
        return normalized.width_m * normalized.height_m * normalized.depth_m

    def fits_inside(self, grid: GridSizeDefaults) -> bool:
        normalized = self.normalized()
        max_width, max_height, max_depth = grid.size_m

        return (
            normalized.width_m <= max_width
            and normalized.height_m <= max_height
            and normalized.depth_m <= max_depth
        )

    def to_document(self) -> dict[str, Any]:
        """Erzeugt physical/bounds.json."""
        normalized = self.normalized()

        return {
            "schema_version": PHYSICAL_BOUNDS_DOCUMENT_SCHEMA_VERSION,
            "width_m": normalized.width_m,
            "height_m": normalized.height_m,
            "depth_m": normalized.depth_m,
            "size_m": {
                "x": normalized.width_m,
                "y": normalized.height_m,
                "z": normalized.depth_m,
            },
            "offset_m": normalized.offset_m.to_dict(),
            "origin_m": normalized.origin_m.to_dict(),
            "volume_m3": normalized.volume_m3,
            "must_fit_grid_footprint": normalized.must_fit_grid_footprint,
            "metadata": dict(normalized.metadata),
        }

    def to_dict(self) -> dict[str, Any]:
        return self.to_document()


@dataclass(frozen=True, slots=True)
class PhysicalBaseDefaults:
    """Defaults für physical/base.json."""

    object_kind: str
    physical_role: str = PhysicalRole.GENERIC.value
    physical_shape: str = PhysicalShape.BOX.value
    load_bearing: bool | None = None
    fire_class: str | None = None
    has_collision: bool = True
    has_occupancy: bool = True
    has_mass: bool = False
    has_layers: bool = False
    metadata: Mapping[str, Any] = field(default_factory=dict)

    def normalized(self) -> "PhysicalBaseDefaults":
        return PhysicalBaseDefaults(
            object_kind=normalize_object_kind_value(self.object_kind),
            physical_role=parse_physical_role_value(self.physical_role),
            physical_shape=parse_physical_shape_value(self.physical_shape),
            load_bearing=None if self.load_bearing is None else bool(self.load_bearing),
            fire_class=clean_optional_string(self.fire_class),
            has_collision=bool(self.has_collision),
            has_occupancy=bool(self.has_occupancy),
            has_mass=bool(self.has_mass),
            has_layers=bool(self.has_layers),
            metadata=normalize_metadata(self.metadata),
        )

    def to_document(self) -> dict[str, Any]:
        """Erzeugt physical/base.json."""
        normalized = self.normalized()

        return {
            "schema_version": PHYSICAL_BASE_DOCUMENT_SCHEMA_VERSION,
            "object_kind": normalized.object_kind,
            "physical_role": normalized.physical_role,
            "physical_shape": normalized.physical_shape,
            "load_bearing": normalized.load_bearing,
            "fire_class": normalized.fire_class,
            "has_collision": normalized.has_collision,
            "has_occupancy": normalized.has_occupancy,
            "has_mass": normalized.has_mass,
            "has_layers": normalized.has_layers,
            "metadata": dict(normalized.metadata),
        }

    def to_dict(self) -> dict[str, Any]:
        return self.to_document()


@dataclass(frozen=True, slots=True)
class PhysicalDimensionsDefaults:
    """Defaults für physical/dimensions.json."""

    grid: GridSizeDefaults = field(default_factory=GridSizeDefaults)
    bounds: PhysicalBoundsDefaults | None = None
    real_width_m: float | None = None
    real_height_m: float | None = None
    real_depth_m: float | None = None
    wall_thickness_m: float | None = None
    metadata: Mapping[str, Any] = field(default_factory=dict)

    def normalized(self) -> "PhysicalDimensionsDefaults":
        grid = self.grid.normalized()
        bounds = self.bounds.normalized() if self.bounds is not None else physical_bounds_from_grid(grid)

        real_width_m = normalize_optional_positive_float(self.real_width_m, "real_width_m") or bounds.width_m
        real_height_m = normalize_optional_positive_float(self.real_height_m, "real_height_m") or bounds.height_m
        real_depth_m = normalize_optional_positive_float(self.real_depth_m, "real_depth_m") or bounds.depth_m
        wall_thickness_m = normalize_optional_positive_float(self.wall_thickness_m, "wall_thickness_m")

        if bounds.must_fit_grid_footprint and not bounds.fits_inside(grid):
            raise PhysicalDefaultsError("Physical bounds must not exceed the grid footprint.")

        return PhysicalDimensionsDefaults(
            grid=grid,
            bounds=bounds,
            real_width_m=real_width_m,
            real_height_m=real_height_m,
            real_depth_m=real_depth_m,
            wall_thickness_m=wall_thickness_m,
            metadata=normalize_metadata(self.metadata),
        )

    @property
    def volume_m3(self) -> float:
        normalized = self.normalized()
        return normalized.real_width_m * normalized.real_height_m * normalized.real_depth_m

    def to_document(self) -> dict[str, Any]:
        """Erzeugt physical/dimensions.json."""
        normalized = self.normalized()

        return {
            "schema_version": PHYSICAL_DIMENSIONS_DOCUMENT_SCHEMA_VERSION,
            "grid": normalized.grid.to_dict(),
            "bounds": normalized.bounds.to_document() if normalized.bounds else None,
            "real_dimensions": {
                "width_m": normalized.real_width_m,
                "height_m": normalized.real_height_m,
                "depth_m": normalized.real_depth_m,
            },
            "real_width_m": normalized.real_width_m,
            "real_height_m": normalized.real_height_m,
            "real_depth_m": normalized.real_depth_m,
            "wall_thickness_m": normalized.wall_thickness_m,
            "volume_m3": normalized.volume_m3,
            "metadata": dict(normalized.metadata),
        }

    def to_dict(self) -> dict[str, Any]:
        return self.to_document()


@dataclass(frozen=True, slots=True)
class PhysicalCollisionDefaults:
    """Defaults für physical/collision.json."""

    enabled: bool = True
    collision_mode: str = CollisionMode.SOLID.value
    shape: str = PhysicalShape.BOX.value
    bounds: PhysicalBoundsDefaults | None = None
    collision_group: str = "default"
    can_block_placement: bool = True
    can_be_selected: bool = True
    metadata: Mapping[str, Any] = field(default_factory=dict)

    def normalized(self) -> "PhysicalCollisionDefaults":
        enabled = bool(self.enabled)
        collision_mode = parse_collision_mode_value(self.collision_mode)
        shape = parse_physical_shape_value(self.shape)

        if collision_mode == CollisionMode.NONE.value:
            enabled = False

        return PhysicalCollisionDefaults(
            enabled=enabled,
            collision_mode=collision_mode,
            shape=shape,
            bounds=self.bounds.normalized() if self.bounds is not None else None,
            collision_group=normalize_simple_key(self.collision_group, "collision_group"),
            can_block_placement=bool(self.can_block_placement) and enabled,
            can_be_selected=bool(self.can_be_selected),
            metadata=normalize_metadata(self.metadata),
        )

    def to_document(self) -> dict[str, Any]:
        """Erzeugt physical/collision.json."""
        normalized = self.normalized()

        return {
            "schema_version": PHYSICAL_COLLISION_DOCUMENT_SCHEMA_VERSION,
            "enabled": normalized.enabled,
            "collision_mode": normalized.collision_mode,
            "shape": normalized.shape,
            "bounds": normalized.bounds.to_document() if normalized.bounds else None,
            "collision_group": normalized.collision_group,
            "can_block_placement": normalized.can_block_placement,
            "can_be_selected": normalized.can_be_selected,
            "metadata": dict(normalized.metadata),
        }

    def to_dict(self) -> dict[str, Any]:
        return self.to_document()


@dataclass(frozen=True, slots=True)
class OccupancyCellDefaults:
    """Eine belegte Rasterzelle."""

    x: int
    y: int
    z: int

    def normalized(self) -> "OccupancyCellDefaults":
        return OccupancyCellDefaults(
            x=normalize_non_negative_int(self.x, "x"),
            y=normalize_non_negative_int(self.y, "y"),
            z=normalize_non_negative_int(self.z, "z"),
        )

    def to_dict(self) -> dict[str, int]:
        normalized = self.normalized()
        return {"x": normalized.x, "y": normalized.y, "z": normalized.z}


@dataclass(frozen=True, slots=True)
class PhysicalOccupancyDefaults:
    """Defaults für physical/occupancy.json."""

    occupancy_mode: str = OccupancyMode.FOOTPRINT_BOX.value
    grid: GridSizeDefaults = field(default_factory=GridSizeDefaults)
    occupied_cells: tuple[OccupancyCellDefaults, ...] = field(default_factory=tuple)
    anchor_cell: OccupancyCellDefaults = field(default_factory=lambda: OccupancyCellDefaults(0, 0, 0))
    metadata: Mapping[str, Any] = field(default_factory=dict)

    def normalized(self) -> "PhysicalOccupancyDefaults":
        occupancy_mode = parse_occupancy_mode_value(self.occupancy_mode)
        grid = self.grid.normalized()
        anchor_cell = self.anchor_cell.normalized()
        metadata = normalize_metadata(self.metadata)

        occupied_cells = tuple(cell.normalized() for cell in self.occupied_cells or ())
        if not occupied_cells and occupancy_mode == OccupancyMode.EXPLICIT_CELLS.value:
            occupied_cells = build_occupied_cells_for_grid(grid)

        if grid.cell_count <= MAX_EXPLICIT_OCCUPANCY_CELLS and occupancy_mode == OccupancyMode.FOOTPRINT_BOX.value:
            occupied_cells = build_occupied_cells_for_grid(grid)

        for cell in occupied_cells:
            assert_cell_inside_grid(cell, grid)

        assert_cell_inside_grid(anchor_cell, grid)

        return PhysicalOccupancyDefaults(
            occupancy_mode=occupancy_mode,
            grid=grid,
            occupied_cells=occupied_cells,
            anchor_cell=anchor_cell,
            metadata=metadata,
        )

    def to_document(self) -> dict[str, Any]:
        """Erzeugt physical/occupancy.json."""
        normalized = self.normalized()

        return {
            "schema_version": PHYSICAL_OCCUPANCY_DOCUMENT_SCHEMA_VERSION,
            "occupancy_mode": normalized.occupancy_mode,
            "grid": normalized.grid.to_dict(),
            "cell_count": normalized.grid.cell_count,
            "explicit_cell_count": len(normalized.occupied_cells),
            "occupied_cells": [cell.to_dict() for cell in normalized.occupied_cells],
            "anchor_cell": normalized.anchor_cell.to_dict(),
            "metadata": dict(normalized.metadata),
        }

    def to_dict(self) -> dict[str, Any]:
        return self.to_document()


@dataclass(frozen=True, slots=True)
class PhysicalLayerDefaults:
    """Ein physischer Layer."""

    layer_id: str
    label: str | None = None
    layer_kind: str = LayerKind.OTHER.value
    thickness_m: float | None = None
    material_id: str | None = None
    density_kg_m3: float | None = None
    sort_order: int = 100
    metadata: Mapping[str, Any] = field(default_factory=dict)

    def normalized(self) -> "PhysicalLayerDefaults":
        layer_id = normalize_simple_key(self.layer_id, "layer_id")
        label = clean_optional_string(self.label) or layer_id
        layer_kind = parse_layer_kind_value(self.layer_kind)
        thickness_m = normalize_optional_positive_float(self.thickness_m, "thickness_m")
        material_id = clean_optional_string(self.material_id)
        density_kg_m3 = normalize_optional_non_negative_float(self.density_kg_m3, "density_kg_m3")
        sort_order = normalize_int(self.sort_order, "sort_order")
        metadata = normalize_metadata(self.metadata)

        return PhysicalLayerDefaults(
            layer_id=layer_id,
            label=label,
            layer_kind=layer_kind,
            thickness_m=thickness_m,
            material_id=material_id,
            density_kg_m3=density_kg_m3,
            sort_order=sort_order,
            metadata=metadata,
        )

    def to_dict(self) -> dict[str, Any]:
        normalized = self.normalized()

        return {
            "layer_id": normalized.layer_id,
            "label": normalized.label,
            "layer_kind": normalized.layer_kind,
            "thickness_m": normalized.thickness_m,
            "material_id": normalized.material_id,
            "density_kg_m3": normalized.density_kg_m3,
            "sort_order": normalized.sort_order,
            "metadata": dict(normalized.metadata),
        }


@dataclass(frozen=True, slots=True)
class PhysicalLayersDefaults:
    """Defaults für physical/layers.json."""

    layers: tuple[PhysicalLayerDefaults, ...] = field(default_factory=tuple)
    total_thickness_m: float | None = None
    metadata: Mapping[str, Any] = field(default_factory=dict)

    def normalized(self) -> "PhysicalLayersDefaults":
        layers = tuple(layer.normalized() for layer in self.layers or ())
        assert_unique_values([layer.layer_id for layer in layers], "layer_id")

        total_thickness_m = normalize_optional_positive_float(self.total_thickness_m, "total_thickness_m")
        if total_thickness_m is None:
            layer_thicknesses = [layer.thickness_m for layer in layers if layer.thickness_m is not None]
            total_thickness_m = sum(layer_thicknesses) if layer_thicknesses else None

        return PhysicalLayersDefaults(
            layers=tuple(sorted(layers, key=lambda layer: (layer.sort_order, layer.layer_id))),
            total_thickness_m=total_thickness_m,
            metadata=normalize_metadata(self.metadata),
        )

    def to_document(self) -> dict[str, Any]:
        """Erzeugt physical/layers.json."""
        normalized = self.normalized()

        return {
            "schema_version": PHYSICAL_LAYERS_DOCUMENT_SCHEMA_VERSION,
            "total_thickness_m": normalized.total_thickness_m,
            "layers": [layer.to_dict() for layer in normalized.layers],
            "metadata": dict(normalized.metadata),
        }

    def to_dict(self) -> dict[str, Any]:
        return self.to_document()


@dataclass(frozen=True, slots=True)
class PhysicalMassDefaults:
    """Defaults für physical/mass.json."""

    mass_kg: float | None = None
    volume_m3: float | None = None
    density_kg_m3: float | None = None
    raw_density_kg_m3: float | None = None
    mass_source: str = MassSource.UNKNOWN.value
    center_of_mass_m: Vector3Defaults | None = None
    metadata: Mapping[str, Any] = field(default_factory=dict)

    def normalized(self) -> "PhysicalMassDefaults":
        mass_kg = normalize_optional_non_negative_float(self.mass_kg, "mass_kg")
        volume_m3 = normalize_optional_positive_float(self.volume_m3, "volume_m3")
        density_kg_m3 = normalize_optional_non_negative_float(self.density_kg_m3, "density_kg_m3")
        raw_density_kg_m3 = normalize_optional_non_negative_float(self.raw_density_kg_m3, "raw_density_kg_m3")
        mass_source = parse_mass_source_value(self.mass_source)
        center_of_mass_m = self.center_of_mass_m.normalized() if self.center_of_mass_m is not None else None
        metadata = normalize_metadata(self.metadata)

        if mass_kg is None and volume_m3 is not None and density_kg_m3 is not None:
            mass_kg = volume_m3 * density_kg_m3
            mass_source = MassSource.COMPUTED_FROM_DENSITY.value

        if mass_kg is not None and mass_source == MassSource.UNKNOWN.value:
            mass_source = MassSource.EXPLICIT.value

        return PhysicalMassDefaults(
            mass_kg=mass_kg,
            volume_m3=volume_m3,
            density_kg_m3=density_kg_m3,
            raw_density_kg_m3=raw_density_kg_m3,
            mass_source=mass_source,
            center_of_mass_m=center_of_mass_m,
            metadata=metadata,
        )

    def to_document(self) -> dict[str, Any]:
        """Erzeugt physical/mass.json."""
        normalized = self.normalized()

        return {
            "schema_version": PHYSICAL_MASS_DOCUMENT_SCHEMA_VERSION,
            "mass_kg": normalized.mass_kg,
            "volume_m3": normalized.volume_m3,
            "density_kg_m3": normalized.density_kg_m3,
            "raw_density_kg_m3": normalized.raw_density_kg_m3,
            "mass_source": normalized.mass_source,
            "center_of_mass_m": normalized.center_of_mass_m.to_dict() if normalized.center_of_mass_m else None,
            "metadata": dict(normalized.metadata),
        }

    def to_dict(self) -> dict[str, Any]:
        return self.to_document()


@dataclass(frozen=True, slots=True)
class PhysicalFootprintDefaults:
    """Defaults für physical/footprint.json."""

    grid: GridSizeDefaults = field(default_factory=GridSizeDefaults)
    footprint_area_m2: float | None = None
    footprint_volume_m3: float | None = None
    metadata: Mapping[str, Any] = field(default_factory=dict)

    def normalized(self) -> "PhysicalFootprintDefaults":
        grid = self.grid.normalized()
        size_x, size_y, size_z = grid.size_m

        footprint_area_m2 = normalize_optional_positive_float(self.footprint_area_m2, "footprint_area_m2")
        footprint_volume_m3 = normalize_optional_positive_float(self.footprint_volume_m3, "footprint_volume_m3")

        if footprint_area_m2 is None:
            footprint_area_m2 = size_x * size_z

        if footprint_volume_m3 is None:
            footprint_volume_m3 = size_x * size_y * size_z

        return PhysicalFootprintDefaults(
            grid=grid,
            footprint_area_m2=footprint_area_m2,
            footprint_volume_m3=footprint_volume_m3,
            metadata=normalize_metadata(self.metadata),
        )

    def to_document(self) -> dict[str, Any]:
        """Erzeugt physical/footprint.json."""
        normalized = self.normalized()

        return {
            "schema_version": PHYSICAL_FOOTPRINT_DOCUMENT_SCHEMA_VERSION,
            "grid": normalized.grid.to_dict(),
            "footprint_area_m2": normalized.footprint_area_m2,
            "footprint_volume_m3": normalized.footprint_volume_m3,
            "metadata": dict(normalized.metadata),
        }

    def to_dict(self) -> dict[str, Any]:
        return self.to_document()


@dataclass(frozen=True, slots=True)
class PhysicalDefaults:
    """Vollständige Defaults für alle physical/*.json-Dokumente."""

    base: PhysicalBaseDefaults
    dimensions: PhysicalDimensionsDefaults
    collision: PhysicalCollisionDefaults
    occupancy: PhysicalOccupancyDefaults = field(default_factory=PhysicalOccupancyDefaults)
    layers: PhysicalLayersDefaults = field(default_factory=PhysicalLayersDefaults)
    mass: PhysicalMassDefaults = field(default_factory=PhysicalMassDefaults)
    footprint: PhysicalFootprintDefaults = field(default_factory=PhysicalFootprintDefaults)

    def normalized(self) -> "PhysicalDefaults":
        dimensions = self.dimensions.normalized()
        base = self.base.normalized()
        collision = PhysicalCollisionDefaults(
            enabled=self.collision.enabled,
            collision_mode=self.collision.collision_mode,
            shape=self.collision.shape,
            bounds=self.collision.bounds or dimensions.bounds,
            collision_group=self.collision.collision_group,
            can_block_placement=self.collision.can_block_placement,
            can_be_selected=self.collision.can_be_selected,
            metadata=self.collision.metadata,
        ).normalized()

        occupancy = PhysicalOccupancyDefaults(
            occupancy_mode=self.occupancy.occupancy_mode,
            grid=self.occupancy.grid if self.occupancy.grid else dimensions.grid,
            occupied_cells=self.occupancy.occupied_cells,
            anchor_cell=self.occupancy.anchor_cell,
            metadata=self.occupancy.metadata,
        ).normalized()

        mass = PhysicalMassDefaults(
            mass_kg=self.mass.mass_kg,
            volume_m3=self.mass.volume_m3 or dimensions.volume_m3,
            density_kg_m3=self.mass.density_kg_m3,
            raw_density_kg_m3=self.mass.raw_density_kg_m3,
            mass_source=self.mass.mass_source,
            center_of_mass_m=self.mass.center_of_mass_m,
            metadata=self.mass.metadata,
        ).normalized()

        return PhysicalDefaults(
            base=PhysicalBaseDefaults(
                object_kind=base.object_kind,
                physical_role=base.physical_role,
                physical_shape=base.physical_shape,
                load_bearing=base.load_bearing,
                fire_class=base.fire_class,
                has_collision=collision.enabled,
                has_occupancy=occupancy.occupancy_mode != OccupancyMode.NONE.value,
                has_mass=mass.mass_kg is not None,
                has_layers=bool(self.layers.layers),
                metadata=base.metadata,
            ).normalized(),
            dimensions=dimensions,
            collision=collision,
            occupancy=occupancy,
            layers=self.layers.normalized(),
            mass=mass,
            footprint=PhysicalFootprintDefaults(
                grid=dimensions.grid,
                metadata=self.footprint.metadata,
            ).normalized(),
        )

    def to_documents(self, *, include_optional: bool = True) -> dict[str, dict[str, Any]]:
        """Erzeugt alle Physical-Dokumente als Pfad -> Payload."""
        normalized = self.normalized()

        documents = {
            "physical/base.json": normalized.base.to_document(),
            "physical/dimensions.json": normalized.dimensions.to_document(),
            "physical/collision.json": normalized.collision.to_document(),
        }

        if include_optional:
            documents["physical/occupancy.json"] = normalized.occupancy.to_document()
            documents["physical/layers.json"] = normalized.layers.to_document()
            documents["physical/mass.json"] = normalized.mass.to_document()
            if normalized.dimensions.bounds is not None:
                documents["physical/bounds.json"] = normalized.dimensions.bounds.to_document()
            documents["physical/footprint.json"] = normalized.footprint.to_document()

        return documents

    def to_dict(self) -> dict[str, Any]:
        normalized = self.normalized()

        return {
            "schema_version": PHYSICAL_DEFAULTS_SCHEMA_VERSION,
            "base": normalized.base.to_dict(),
            "dimensions": normalized.dimensions.to_dict(),
            "collision": normalized.collision.to_dict(),
            "occupancy": normalized.occupancy.to_dict(),
            "layers": normalized.layers.to_dict(),
            "mass": normalized.mass.to_dict(),
            "footprint": normalized.footprint.to_dict(),
        }


def build_physical_defaults(
    *,
    object_kind: str,
    grid_size_cells: Sequence[Any] = DEFAULT_GRID_SIZE_CELLS,
    cell_size_m: float = DEFAULT_CELL_SIZE_M,
    physical_role: str = PhysicalRole.GENERIC.value,
    physical_shape: str = PhysicalShape.BOX.value,
    real_width_m: float | None = None,
    real_height_m: float | None = None,
    real_depth_m: float | None = None,
    wall_thickness_m: float | None = None,
    volume_m3: float | None = None,
    mass_kg: float | None = None,
    density_kg_m3: float | None = None,
    raw_density_kg_m3: float | None = None,
    load_bearing: bool | None = None,
    fire_class: str | None = None,
    collision_mode: str = CollisionMode.SOLID.value,
    metadata: Mapping[str, Any] | None = None,
) -> PhysicalDefaults:
    """Baut PhysicalDefaults aus expliziten Werten."""
    try:
        size_x, size_y, size_z = normalize_grid_size_cells(grid_size_cells)
        grid = GridSizeDefaults(
            size_cells_x=size_x,
            size_cells_y=size_y,
            size_cells_z=size_z,
            cell_size_m=cell_size_m,
        ).normalized()

        bounds = PhysicalBoundsDefaults(
            width_m=real_width_m or grid.size_m[0],
            height_m=real_height_m or grid.size_m[1],
            depth_m=real_depth_m or grid.size_m[2],
        ).normalized()

        dimensions = PhysicalDimensionsDefaults(
            grid=grid,
            bounds=bounds,
            real_width_m=real_width_m,
            real_height_m=real_height_m,
            real_depth_m=real_depth_m,
            wall_thickness_m=wall_thickness_m,
            metadata=dict(metadata or {}),
        ).normalized()

        mass = PhysicalMassDefaults(
            mass_kg=mass_kg,
            volume_m3=volume_m3 or dimensions.volume_m3,
            density_kg_m3=density_kg_m3,
            raw_density_kg_m3=raw_density_kg_m3,
            metadata=dict(metadata or {}),
        ).normalized()

        return PhysicalDefaults(
            base=PhysicalBaseDefaults(
                object_kind=object_kind,
                physical_role=physical_role,
                physical_shape=physical_shape,
                load_bearing=load_bearing,
                fire_class=fire_class,
                metadata=dict(metadata or {}),
            ),
            dimensions=dimensions,
            collision=PhysicalCollisionDefaults(
                enabled=collision_mode != CollisionMode.NONE.value,
                collision_mode=collision_mode,
                shape=physical_shape,
                bounds=bounds,
                metadata=dict(metadata or {}),
            ),
            occupancy=PhysicalOccupancyDefaults(
                occupancy_mode=OccupancyMode.FOOTPRINT_BOX.value,
                grid=grid,
                metadata=dict(metadata or {}),
            ),
            layers=PhysicalLayersDefaults(metadata=dict(metadata or {})),
            mass=mass,
            footprint=PhysicalFootprintDefaults(
                grid=grid,
                footprint_volume_m3=volume_m3,
                metadata=dict(metadata or {}),
            ),
        ).normalized()
    except PhysicalDefaultsError:
        raise
    except Exception as exc:
        raise PhysicalDefaultsError(f"Could not build physical defaults: {exc}") from exc


def physical_defaults_from_create_request(
    request: Any,
    *,
    metadata: Mapping[str, Any] | None = None,
) -> PhysicalDefaults:
    """Baut PhysicalDefaults aus einem CreateRequest-ähnlichen Objekt."""
    try:
        normalized_request = normalize_create_request(request)
        grid = normalized_request.grid.normalized()
        physical = normalized_request.physical.normalized()

        return build_physical_defaults(
            object_kind=normalized_request.object_kind,
            grid_size_cells=grid.size_cells,
            cell_size_m=grid.cell_size_m,
            physical_role=infer_physical_role_from_request(normalized_request),
            real_width_m=physical.real_width_m,
            real_height_m=physical.real_height_m,
            real_depth_m=physical.real_depth_m,
            wall_thickness_m=physical.wall_thickness_m,
            volume_m3=physical.volume_m3,
            mass_kg=physical.mass_kg,
            density_kg_m3=physical.density_kg_m3,
            raw_density_kg_m3=physical.raw_density_kg_m3,
            load_bearing=physical.load_bearing,
            fire_class=physical.fire_class,
            metadata={
                "source": "create_request",
                "object_kind": normalized_request.object_kind,
                **dict(metadata or {}),
            },
        )
    except PhysicalDefaultsError:
        raise
    except Exception as exc:
        raise PhysicalDefaultsError(f"Could not build physical defaults from CreateRequest: {exc}") from exc


def physical_defaults_from_context(
    context: Any,
    *,
    metadata: Mapping[str, Any] | None = None,
) -> PhysicalDefaults:
    """Baut PhysicalDefaults aus einem PackageContext-ähnlichen Objekt."""
    try:
        normalized_context = context.normalized() if hasattr(context, "normalized") else context

        return build_physical_defaults(
            object_kind=normalized_context.object_kind,
            physical_role=infer_physical_role_from_object_kind(normalized_context.object_kind),
            metadata={
                "source": "package_context",
                "correlation_id": getattr(normalized_context, "correlation_id", None),
                **dict(metadata or {}),
            },
        )
    except PhysicalDefaultsError:
        raise
    except Exception as exc:
        raise PhysicalDefaultsError(f"Could not build physical defaults from PackageContext: {exc}") from exc


def physical_defaults_from_creation_plan(
    creation_plan: Any,
    *,
    metadata: Mapping[str, Any] | None = None,
) -> PhysicalDefaults:
    """Baut PhysicalDefaults aus einem CreationPlan-ähnlichen Objekt."""
    try:
        normalized_plan = creation_plan.normalized() if hasattr(creation_plan, "normalized") else creation_plan

        return physical_defaults_from_create_request(
            normalized_plan.request,
            metadata={
                "source": "creation_plan",
                "profile_key": getattr(normalized_plan.profile, "profile_key", None),
                **dict(metadata or {}),
            },
        )
    except PhysicalDefaultsError:
        raise
    except Exception as exc:
        raise PhysicalDefaultsError(f"Could not build physical defaults from CreationPlan: {exc}") from exc


def physical_documents_from_create_request(
    request: Any,
    *,
    include_optional: bool = True,
    metadata: Mapping[str, Any] | None = None,
) -> dict[str, dict[str, Any]]:
    """Baut alle physical/*.json-Dokumente aus CreateRequest."""
    return physical_defaults_from_create_request(
        request,
        metadata=metadata,
    ).to_documents(include_optional=include_optional)


def physical_documents_from_context(
    context: Any,
    *,
    include_optional: bool = True,
    metadata: Mapping[str, Any] | None = None,
) -> dict[str, dict[str, Any]]:
    """Baut alle physical/*.json-Dokumente aus PackageContext."""
    return physical_defaults_from_context(
        context,
        metadata=metadata,
    ).to_documents(include_optional=include_optional)


def physical_documents_from_creation_plan(
    creation_plan: Any,
    *,
    include_optional: bool = True,
    metadata: Mapping[str, Any] | None = None,
) -> dict[str, dict[str, Any]]:
    """Baut alle physical/*.json-Dokumente aus CreationPlan."""
    return physical_defaults_from_creation_plan(
        creation_plan,
        metadata=metadata,
    ).to_documents(include_optional=include_optional)


def validate_physical_base_document(document: Mapping[str, Any]) -> tuple[bool, tuple[str, ...]]:
    """Validiert grob physical/base.json."""
    messages: list[str] = []

    try:
        if not isinstance(document, Mapping):
            return False, ("physical/base.json must be a mapping.",)

        required_fields = (
            "schema_version",
            "object_kind",
            "physical_role",
            "physical_shape",
            "has_collision",
            "has_occupancy",
        )

        for field_name in required_fields:
            if field_name not in document:
                messages.append(f"Missing physical base field {field_name!r}.")

        if "object_kind" in document:
            try:
                normalize_object_kind_value(document["object_kind"])
            except Exception as exc:
                messages.append(str(exc))

    except Exception as exc:
        messages.append(f"Could not validate physical base document: {exc}")

    return len(messages) == 0, tuple(messages)


def validate_physical_dimensions_document(document: Mapping[str, Any]) -> tuple[bool, tuple[str, ...]]:
    """Validiert grob physical/dimensions.json."""
    messages: list[str] = []

    try:
        if not isinstance(document, Mapping):
            return False, ("physical/dimensions.json must be a mapping.",)

        required_fields = (
            "schema_version",
            "grid",
            "real_dimensions",
            "real_width_m",
            "real_height_m",
            "real_depth_m",
            "volume_m3",
        )

        for field_name in required_fields:
            if field_name not in document:
                messages.append(f"Missing physical dimensions field {field_name!r}.")

        for field_name in ("real_width_m", "real_height_m", "real_depth_m", "volume_m3"):
            if field_name in document:
                try:
                    normalize_positive_float(document[field_name], field_name)
                except Exception as exc:
                    messages.append(str(exc))

    except Exception as exc:
        messages.append(f"Could not validate physical dimensions document: {exc}")

    return len(messages) == 0, tuple(messages)


def validate_physical_collision_document(document: Mapping[str, Any]) -> tuple[bool, tuple[str, ...]]:
    """Validiert grob physical/collision.json."""
    messages: list[str] = []

    try:
        if not isinstance(document, Mapping):
            return False, ("physical/collision.json must be a mapping.",)

        required_fields = (
            "schema_version",
            "enabled",
            "collision_mode",
            "shape",
            "can_block_placement",
            "can_be_selected",
        )

        for field_name in required_fields:
            if field_name not in document:
                messages.append(f"Missing physical collision field {field_name!r}.")

        if "collision_mode" in document:
            try:
                parse_collision_mode_value(document["collision_mode"])
            except Exception as exc:
                messages.append(str(exc))

    except Exception as exc:
        messages.append(f"Could not validate physical collision document: {exc}")

    return len(messages) == 0, tuple(messages)


def assert_valid_physical_base_document(document: Mapping[str, Any]) -> None:
    """Wirft PhysicalDefaultsError, wenn physical/base.json ungültig ist."""
    valid, messages = validate_physical_base_document(document)
    if not valid:
        raise PhysicalDefaultsError(" ".join(messages) if messages else "Invalid physical base document.")


def assert_valid_physical_dimensions_document(document: Mapping[str, Any]) -> None:
    """Wirft PhysicalDefaultsError, wenn physical/dimensions.json ungültig ist."""
    valid, messages = validate_physical_dimensions_document(document)
    if not valid:
        raise PhysicalDefaultsError(" ".join(messages) if messages else "Invalid physical dimensions document.")


def assert_valid_physical_collision_document(document: Mapping[str, Any]) -> None:
    """Wirft PhysicalDefaultsError, wenn physical/collision.json ungültig ist."""
    valid, messages = validate_physical_collision_document(document)
    if not valid:
        raise PhysicalDefaultsError(" ".join(messages) if messages else "Invalid physical collision document.")


def physical_bounds_from_grid(grid: GridSizeDefaults) -> PhysicalBoundsDefaults:
    """Erzeugt Bounds aus Grid-Größe."""
    normalized = grid.normalized()
    width_m, height_m, depth_m = normalized.size_m

    return PhysicalBoundsDefaults(
        width_m=width_m,
        height_m=height_m,
        depth_m=depth_m,
        must_fit_grid_footprint=True,
    ).normalized()


def build_occupied_cells_for_grid(grid: GridSizeDefaults) -> tuple[OccupancyCellDefaults, ...]:
    """Erzeugt explizite belegte Zellen für kleine Footprints."""
    normalized = grid.normalized()

    if normalized.cell_count > MAX_EXPLICIT_OCCUPANCY_CELLS:
        return tuple()

    return tuple(
        OccupancyCellDefaults(x=x, y=y, z=z).normalized()
        for x in range(normalized.size_cells_x)
        for y in range(normalized.size_cells_y)
        for z in range(normalized.size_cells_z)
    )


def assert_cell_inside_grid(cell: OccupancyCellDefaults, grid: GridSizeDefaults) -> None:
    """Prüft, ob eine Zelle innerhalb des Grids liegt."""
    normalized_cell = cell.normalized()
    normalized_grid = grid.normalized()

    if (
        normalized_cell.x >= normalized_grid.size_cells_x
        or normalized_cell.y >= normalized_grid.size_cells_y
        or normalized_cell.z >= normalized_grid.size_cells_z
    ):
        raise PhysicalDefaultsError(
            f"Occupancy cell {normalized_cell.to_dict()!r} is outside grid {normalized_grid.size_cells!r}."
        )


def infer_physical_role_from_request(request: Any) -> str:
    """Leitet physical_role aus Request-Daten ab."""
    try:
        classification = request.classification.normalized()
        category = classification.category
        subcategory = classification.subcategory

        if category == "waende" or "wand" in subcategory:
            return PhysicalRole.WALL.value
        if category == "decken":
            return PhysicalRole.SLAB.value
        if category == "boeden":
            return PhysicalRole.FLOOR.value
        if category == "daecher":
            return PhysicalRole.ROOF.value
        if category == "fundamente":
            return PhysicalRole.FOUNDATION.value
        if category in {"tragwerk", "bruecken"}:
            return PhysicalRole.STRUCTURAL.value
        if category in {"leitungen", "schaechte", "strassen", "kanaele"}:
            return PhysicalRole.INFRASTRUCTURE.value
        if category in {"technik"}:
            return PhysicalRole.EQUIPMENT.value
        if category in {"moebel"}:
            return PhysicalRole.FURNITURE.value

        return infer_physical_role_from_object_kind(request.object_kind)
    except Exception:
        return PhysicalRole.GENERIC.value


def infer_physical_role_from_object_kind(object_kind: Any) -> str:
    """Leitet physical_role aus object_kind ab."""
    try:
        object_kind_value = normalize_object_kind_value(object_kind)
    except Exception:
        return PhysicalRole.GENERIC.value

    if object_kind_value == "adaptive_system":
        return PhysicalRole.ADAPTIVE.value

    if object_kind_value == "catalog_object":
        return PhysicalRole.EQUIPMENT.value

    return PhysicalRole.GENERIC.value


def normalize_create_request(value: Any) -> Any:
    """Normalisiert CreateRequest-ähnliche Werte."""
    try:
        from ..models.create_request import CreateRequest, create_request_from_mapping

        if isinstance(value, CreateRequest):
            return value.normalized()

        if isinstance(value, Mapping):
            return create_request_from_mapping(value).normalized()

        if hasattr(value, "normalized") and callable(value.normalized):
            return value.normalized()

        raise PhysicalDefaultsError("CreateRequest value is required.")
    except PhysicalDefaultsError:
        raise
    except Exception as exc:
        raise PhysicalDefaultsError(f"Invalid CreateRequest: {exc}") from exc


def normalize_object_kind_value(value: Any) -> str:
    """Normalisiert object_kind."""
    try:
        from ..domain.object_kinds import ensure_object_kind_value

        return ensure_object_kind_value(value)
    except Exception as exc:
        raise PhysicalDefaultsError(f"Invalid object_kind {value!r}: {exc}") from exc


@lru_cache(maxsize=128)
def parse_physical_shape_value(value: Any) -> str:
    """Parst PhysicalShape."""
    try:
        if isinstance(value, PhysicalShape):
            return value.value

        raw = normalize_enum_key(value)

        aliases = {
            "box": PhysicalShape.BOX.value,
            "cube": PhysicalShape.BOX.value,
            "cuboid": PhysicalShape.BOX.value,
            "custom": PhysicalShape.CUSTOM_BOUNDS.value,
            "custom_bounds": PhysicalShape.CUSTOM_BOUNDS.value,
            "mesh": PhysicalShape.MESH_BOUNDS.value,
            "mesh_bounds": PhysicalShape.MESH_BOUNDS.value,
            "none": PhysicalShape.NONE.value,
        }

        if raw in aliases:
            return aliases[raw]

        return PhysicalShape(raw).value
    except Exception as exc:
        raise PhysicalDefaultsError(f"Invalid physical shape {value!r}.") from exc


@lru_cache(maxsize=128)
def parse_physical_role_value(value: Any) -> str:
    """Parst PhysicalRole."""
    try:
        if isinstance(value, PhysicalRole):
            return value.value

        raw = normalize_enum_key(value)
        return PhysicalRole(raw).value
    except Exception as exc:
        raise PhysicalDefaultsError(f"Invalid physical role {value!r}.") from exc


@lru_cache(maxsize=128)
def parse_collision_mode_value(value: Any) -> str:
    """Parst CollisionMode."""
    try:
        if isinstance(value, CollisionMode):
            return value.value

        raw = normalize_enum_key(value)

        aliases = {
            "solid": CollisionMode.SOLID.value,
            "bounds": CollisionMode.BOUNDS.value,
            "trigger": CollisionMode.TRIGGER.value,
            "none": CollisionMode.NONE.value,
            "off": CollisionMode.NONE.value,
            "disabled": CollisionMode.NONE.value,
        }

        if raw in aliases:
            return aliases[raw]

        return CollisionMode(raw).value
    except Exception as exc:
        raise PhysicalDefaultsError(f"Invalid collision mode {value!r}.") from exc


@lru_cache(maxsize=128)
def parse_occupancy_mode_value(value: Any) -> str:
    """Parst OccupancyMode."""
    try:
        if isinstance(value, OccupancyMode):
            return value.value

        raw = normalize_enum_key(value)

        aliases = {
            "footprint": OccupancyMode.FOOTPRINT_BOX.value,
            "footprint_box": OccupancyMode.FOOTPRINT_BOX.value,
            "cells": OccupancyMode.EXPLICIT_CELLS.value,
            "explicit_cells": OccupancyMode.EXPLICIT_CELLS.value,
            "bounds": OccupancyMode.BOUNDS.value,
            "none": OccupancyMode.NONE.value,
        }

        if raw in aliases:
            return aliases[raw]

        return OccupancyMode(raw).value
    except Exception as exc:
        raise PhysicalDefaultsError(f"Invalid occupancy mode {value!r}.") from exc


@lru_cache(maxsize=128)
def parse_mass_source_value(value: Any) -> str:
    """Parst MassSource."""
    try:
        if isinstance(value, MassSource):
            return value.value

        raw = normalize_enum_key(value)

        aliases = {
            "explicit": MassSource.EXPLICIT.value,
            "computed": MassSource.COMPUTED_FROM_DENSITY.value,
            "computed_from_density": MassSource.COMPUTED_FROM_DENSITY.value,
            "density": MassSource.COMPUTED_FROM_DENSITY.value,
            "unknown": MassSource.UNKNOWN.value,
        }

        if raw in aliases:
            return aliases[raw]

        return MassSource(raw).value
    except Exception as exc:
        raise PhysicalDefaultsError(f"Invalid mass source {value!r}.") from exc


@lru_cache(maxsize=128)
def parse_layer_kind_value(value: Any) -> str:
    """Parst LayerKind."""
    try:
        if isinstance(value, LayerKind):
            return value.value

        raw = normalize_enum_key(value)
        return LayerKind(raw).value
    except Exception as exc:
        raise PhysicalDefaultsError(f"Invalid layer kind {value!r}.") from exc


def normalize_grid_size_cells(values: Sequence[Any]) -> tuple[int, int, int]:
    """Normalisiert Grid-Size-Cells."""
    if not isinstance(values, Sequence) or len(values) != 3:
        raise PhysicalDefaultsError("grid_size_cells must contain exactly three values.")

    return (
        normalize_positive_int(values[0], "size_cells_x"),
        normalize_positive_int(values[1], "size_cells_y"),
        normalize_positive_int(values[2], "size_cells_z"),
    )


def normalize_simple_key(value: Any, field_name: str) -> str:
    """Normalisiert einfache technische Keys."""
    raw = clean_required_string(value, field_name)
    return raw.lower().replace(" ", "_").replace("-", "_").replace("/", "_").replace("\\", "_")


def assert_unique_values(values: Iterable[str], field_name: str) -> None:
    """Prüft eindeutige Werte."""
    seen: set[str] = set()

    for value in values or ():
        if value in seen:
            raise PhysicalDefaultsError(f"Duplicate {field_name} {value!r}.")
        seen.add(value)


def normalize_enum_key(value: Any) -> str:
    """Normalisiert Enum-ähnliche Werte."""
    try:
        raw = str(value).strip()

        if not raw:
            raise PhysicalDefaultsError("Enum value is required.")

        return (
            raw.lower()
            .replace(" ", "_")
            .replace("-", "_")
            .replace("/", "_")
            .replace("\\", "_")
        )
    except PhysicalDefaultsError:
        raise
    except Exception as exc:
        raise PhysicalDefaultsError(f"Invalid enum value {value!r}.") from exc


def normalize_float(value: Any, field_name: str) -> float:
    """Normalisiert Float."""
    try:
        if isinstance(value, bool):
            raise PhysicalDefaultsError(f"{field_name} must be a number.")
        return float(value)
    except PhysicalDefaultsError:
        raise
    except Exception as exc:
        raise PhysicalDefaultsError(f"{field_name} must be a number.") from exc


def normalize_positive_float(value: Any, field_name: str) -> float:
    """Normalisiert positive Float-Werte."""
    number = normalize_float(value, field_name)
    if number <= 0:
        raise PhysicalDefaultsError(f"{field_name} must be > 0.")
    return number


def normalize_non_negative_float(value: Any, field_name: str) -> float:
    """Normalisiert nicht-negative Float-Werte."""
    number = normalize_float(value, field_name)
    if number < 0:
        raise PhysicalDefaultsError(f"{field_name} must be >= 0.")
    return number


def normalize_optional_positive_float(value: Any, field_name: str) -> float | None:
    """Normalisiert optionale positive Float-Werte."""
    if value is None:
        return None
    return normalize_positive_float(value, field_name)


def normalize_optional_non_negative_float(value: Any, field_name: str) -> float | None:
    """Normalisiert optionale nicht-negative Float-Werte."""
    if value is None:
        return None
    return normalize_non_negative_float(value, field_name)


def normalize_positive_int(value: Any, field_name: str) -> int:
    """Normalisiert positive Integer."""
    try:
        if isinstance(value, bool):
            raise PhysicalDefaultsError(f"{field_name} must be an integer.")
        number = int(value)
        if number < 1:
            raise PhysicalDefaultsError(f"{field_name} must be >= 1.")
        return number
    except PhysicalDefaultsError:
        raise
    except Exception as exc:
        raise PhysicalDefaultsError(f"{field_name} must be a positive integer.") from exc


def normalize_non_negative_int(value: Any, field_name: str) -> int:
    """Normalisiert nicht-negative Integer."""
    try:
        if isinstance(value, bool):
            raise PhysicalDefaultsError(f"{field_name} must be an integer.")
        number = int(value)
        if number < 0:
            raise PhysicalDefaultsError(f"{field_name} must be >= 0.")
        return number
    except PhysicalDefaultsError:
        raise
    except Exception as exc:
        raise PhysicalDefaultsError(f"{field_name} must be a non-negative integer.") from exc


def normalize_int(value: Any, field_name: str) -> int:
    """Normalisiert Integer."""
    try:
        if isinstance(value, bool):
            raise PhysicalDefaultsError(f"{field_name} must be an integer.")
        return int(value)
    except Exception as exc:
        raise PhysicalDefaultsError(f"{field_name} must be an integer.") from exc


def normalize_metadata(value: Mapping[str, Any] | None) -> dict[str, Any]:
    """Normalisiert Metadata JSON-kompatibel."""
    if value is None:
        return {}

    if not isinstance(value, Mapping):
        raise PhysicalDefaultsError("metadata must be a mapping.")

    return {
        str(key): normalize_metadata_value(child_value)
        for key, child_value in value.items()
    }


def normalize_metadata_value(value: Any) -> Any:
    """Normalisiert Metadata-Werte JSON-kompatibel."""
    if value is None:
        return None

    if isinstance(value, (str, int, float, bool)):
        return value

    if isinstance(value, Mapping):
        return normalize_metadata(value)

    if isinstance(value, (list, tuple, set)):
        return [normalize_metadata_value(item) for item in value]

    return str(value)


def clean_required_string(value: Any, field_name: str) -> str:
    """Normalisiert Pflicht-String."""
    try:
        cleaned = str(value).strip()
        if not cleaned:
            raise PhysicalDefaultsError(f"{field_name} is required.")
        return cleaned
    except PhysicalDefaultsError:
        raise
    except Exception as exc:
        raise PhysicalDefaultsError(f"{field_name} must be string-like.") from exc


def clean_optional_string(value: Any) -> str | None:
    """Normalisiert optionalen String."""
    if value is None:
        return None

    try:
        cleaned = str(value).strip()
        return cleaned or None
    except Exception:
        return None


def clear_physical_defaults_caches() -> None:
    """Leert interne Parser-Caches."""
    parse_physical_shape_value.cache_clear()
    parse_physical_role_value.cache_clear()
    parse_collision_mode_value.cache_clear()
    parse_occupancy_mode_value.cache_clear()
    parse_mass_source_value.cache_clear()
    parse_layer_kind_value.cache_clear()


__all__ = [
    "DEFAULT_CELL_SIZE_M",
    "DEFAULT_DENSITY_KG_M3",
    "DEFAULT_GRID_SIZE_CELLS",
    "MAX_EXPLICIT_OCCUPANCY_CELLS",
    "PHYSICAL_BASE_DOCUMENT_SCHEMA_VERSION",
    "PHYSICAL_BOUNDS_DOCUMENT_SCHEMA_VERSION",
    "PHYSICAL_COLLISION_DOCUMENT_SCHEMA_VERSION",
    "PHYSICAL_DEFAULTS_SCHEMA_VERSION",
    "PHYSICAL_DIMENSIONS_DOCUMENT_SCHEMA_VERSION",
    "PHYSICAL_FOOTPRINT_DOCUMENT_SCHEMA_VERSION",
    "PHYSICAL_LAYERS_DOCUMENT_SCHEMA_VERSION",
    "PHYSICAL_MASS_DOCUMENT_SCHEMA_VERSION",
    "PHYSICAL_OCCUPANCY_DOCUMENT_SCHEMA_VERSION",
    "CollisionMode",
    "GridSizeDefaults",
    "LayerKind",
    "MassSource",
    "OccupancyCellDefaults",
    "OccupancyMode",
    "PhysicalBaseDefaults",
    "PhysicalBoundsDefaults",
    "PhysicalCollisionDefaults",
    "PhysicalDefaults",
    "PhysicalDefaultsError",
    "PhysicalDimensionsDefaults",
    "PhysicalFootprintDefaults",
    "PhysicalLayerDefaults",
    "PhysicalLayersDefaults",
    "PhysicalMassDefaults",
    "PhysicalOccupancyDefaults",
    "PhysicalRole",
    "PhysicalShape",
    "Vector3Defaults",
    "assert_cell_inside_grid",
    "assert_unique_values",
    "assert_valid_physical_base_document",
    "assert_valid_physical_collision_document",
    "assert_valid_physical_dimensions_document",
    "build_occupied_cells_for_grid",
    "build_physical_defaults",
    "clean_optional_string",
    "clean_required_string",
    "clear_physical_defaults_caches",
    "infer_physical_role_from_object_kind",
    "infer_physical_role_from_request",
    "normalize_create_request",
    "normalize_enum_key",
    "normalize_float",
    "normalize_grid_size_cells",
    "normalize_int",
    "normalize_metadata",
    "normalize_metadata_value",
    "normalize_non_negative_float",
    "normalize_non_negative_int",
    "normalize_object_kind_value",
    "normalize_optional_non_negative_float",
    "normalize_optional_positive_float",
    "normalize_positive_float",
    "normalize_positive_int",
    "normalize_simple_key",
    "parse_collision_mode_value",
    "parse_layer_kind_value",
    "parse_mass_source_value",
    "parse_occupancy_mode_value",
    "parse_physical_role_value",
    "parse_physical_shape_value",
    "physical_bounds_from_grid",
    "physical_defaults_from_context",
    "physical_defaults_from_create_request",
    "physical_defaults_from_creation_plan",
    "physical_documents_from_context",
    "physical_documents_from_create_request",
    "physical_documents_from_creation_plan",
    "validate_physical_base_document",
    "validate_physical_collision_document",
    "validate_physical_dimensions_document",
]