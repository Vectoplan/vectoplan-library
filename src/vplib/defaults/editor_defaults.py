# services/vectoplan-library/src/vplib/defaults/editor_defaults.py
"""
Editor defaults for the VPLIB package engine.

Diese Datei erzeugt robuste Default-Daten für:

    editor/inventory.json
    editor/placement.json
    optional: editor/targeting.json
    optional: editor/anchors.json
    optional: editor/sockets.json
    optional: editor/ports.json
    optional: editor/tools.json
    optional: editor/hotbar.json

Die Editor-Dokumente beschreiben, wie eine VPLIB-Family im Editor sichtbar,
auswählbar, platzierbar und später interaktiv adressierbar ist.

Wichtig:
Der Grid-Footprint bleibt die Platzierungswahrheit. Die sichtbare Geometrie
liegt nur innerhalb dieses Footprints.

Diese Datei schreibt keine Dateien. Sie erzeugt nur JSON-kompatible Payloads.

Technische Namen, JSON-Keys und Variablen bleiben Englisch.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from enum import Enum
from functools import lru_cache
from typing import Any, Final, Iterable, Mapping, Sequence


EDITOR_DEFAULTS_SCHEMA_VERSION: Final[str] = "vplib.editor_defaults.v1"
EDITOR_INVENTORY_DOCUMENT_SCHEMA_VERSION: Final[str] = "vplib.editor.inventory.v1"
EDITOR_PLACEMENT_DOCUMENT_SCHEMA_VERSION: Final[str] = "vplib.editor.placement.v1"
EDITOR_TARGETING_DOCUMENT_SCHEMA_VERSION: Final[str] = "vplib.editor.targeting.v1"
EDITOR_ANCHORS_DOCUMENT_SCHEMA_VERSION: Final[str] = "vplib.editor.anchors.v1"
EDITOR_SOCKETS_DOCUMENT_SCHEMA_VERSION: Final[str] = "vplib.editor.sockets.v1"
EDITOR_PORTS_DOCUMENT_SCHEMA_VERSION: Final[str] = "vplib.editor.ports.v1"
EDITOR_TOOLS_DOCUMENT_SCHEMA_VERSION: Final[str] = "vplib.editor.tools.v1"
EDITOR_HOTBAR_DOCUMENT_SCHEMA_VERSION: Final[str] = "vplib.editor.hotbar.v1"

DEFAULT_INVENTORY_GROUP: Final[str] = "creative_library"
DEFAULT_ROTATION_STEPS: Final[tuple[int, ...]] = (0, 90, 180, 270)
DEFAULT_ALLOWED_SURFACES: Final[tuple[str, ...]] = ("top", "side", "bottom")
DEFAULT_ALLOWED_HOSTS: Final[tuple[str, ...]] = ("grid",)
DEFAULT_TARGETING_RANGE_M: Final[float] = 8.0

SAFE_EDITOR_KEY_RE: Final[re.Pattern[str]] = re.compile(
    r"^[a-z0-9][a-z0-9._-]*[a-z0-9]$|^[a-z0-9]$"
)


class EditorDefaultsError(ValueError):
    """Wird ausgelöst, wenn Editor-Defaults ungültig erzeugt werden."""


class InventoryVisibility(str, Enum):
    """Sichtbarkeit im Editor-Inventar."""

    VISIBLE = "visible"
    HIDDEN = "hidden"
    INTERNAL = "internal"

    @property
    def key(self) -> str:
        return str(self.value)


class EditorSurface(str, Enum):
    """Erlaubte Platzierflächen."""

    TOP = "top"
    BOTTOM = "bottom"
    SIDE = "side"
    NORTH = "north"
    SOUTH = "south"
    EAST = "east"
    WEST = "west"
    FRONT = "front"
    BACK = "back"
    LEFT = "left"
    RIGHT = "right"
    ANY = "any"

    @property
    def key(self) -> str:
        return str(self.value)


class EditorHost(str, Enum):
    """Erlaubte Host-Arten."""

    GRID = "grid"
    BLOCK = "block"
    WALL = "wall"
    FLOOR = "floor"
    CEILING = "ceiling"
    SURFACE = "surface"
    SOCKET = "socket"
    ANCHOR = "anchor"
    ADAPTIVE_CONTEXT = "adaptive_context"
    ANY = "any"

    @property
    def key(self) -> str:
        return str(self.value)


class SnapMode(str, Enum):
    """Snap-Verhalten beim Platzieren."""

    GRID = "grid"
    SURFACE = "surface"
    ANCHOR = "anchor"
    SOCKET = "socket"
    FREE = "free"

    @property
    def key(self) -> str:
        return str(self.value)


class TargetingMode(str, Enum):
    """Targeting-Verhalten."""

    BLOCK_FACE = "block_face"
    SURFACE_RAYCAST = "surface_raycast"
    BOUNDS_RAYCAST = "bounds_raycast"
    ANCHOR_TARGETING = "anchor_targeting"
    SOCKET_TARGETING = "socket_targeting"
    ADAPTIVE_CONTEXT = "adaptive_context"

    @property
    def key(self) -> str:
        return str(self.value)


class AnchorKind(str, Enum):
    """Anchor-Art."""

    CENTER = "center"
    BOTTOM_CENTER = "bottom_center"
    TOP_CENTER = "top_center"
    SURFACE_CENTER = "surface_center"
    CORNER = "corner"
    CUSTOM = "custom"

    @property
    def key(self) -> str:
        return str(self.value)


class SocketKind(str, Enum):
    """Socket-Art."""

    ATTACHMENT = "attachment"
    CONNECTION = "connection"
    ROUTING = "routing"
    STRUCTURAL = "structural"
    CUSTOM = "custom"

    @property
    def key(self) -> str:
        return str(self.value)


class PortKind(str, Enum):
    """Port-Art."""

    INPUT = "input"
    OUTPUT = "output"
    BIDIRECTIONAL = "bidirectional"
    ROUTING = "routing"
    CUSTOM = "custom"

    @property
    def key(self) -> str:
        return str(self.value)


class EditorTool(str, Enum):
    """Editor-Werkzeuge."""

    PLACE = "place"
    REMOVE = "remove"
    MOVE = "move"
    ROTATE = "rotate"
    REPLACE = "replace"
    INSPECT = "inspect"
    VARIANT_SWITCH = "variant_switch"

    @property
    def key(self) -> str:
        return str(self.value)


@dataclass(frozen=True, slots=True)
class GridFootprintDefaults:
    """Grid-Footprint für editor/placement.json."""

    size_cells_x: int = 1
    size_cells_y: int = 1
    size_cells_z: int = 1
    cell_size_m: float = 1.0

    def normalized(self) -> "GridFootprintDefaults":
        return GridFootprintDefaults(
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

    def to_dict(self) -> dict[str, Any]:
        normalized = self.normalized()

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
            "size_m": {
                "x": normalized.size_m[0],
                "y": normalized.size_m[1],
                "z": normalized.size_m[2],
            },
        }


@dataclass(frozen=True, slots=True)
class EditorInventoryDefaults:
    """Defaults für editor/inventory.json."""

    family_id: str
    default_variant_id: str
    label: str
    short_label: str | None = None
    description: str = ""
    domain: str | None = None
    category: str | None = None
    subcategory: str | None = None
    object_kind: str | None = None
    inventory_group: str = DEFAULT_INVENTORY_GROUP
    visibility: str = InventoryVisibility.VISIBLE.value
    creative_library_visible: bool = True
    hotbar_eligible: bool = True
    icon_ref: str | None = None
    preview_ref: str | None = None
    sort_key: str | None = None
    search_text: str | None = None
    tags: tuple[str, ...] = field(default_factory=tuple)
    metadata: Mapping[str, Any] = field(default_factory=dict)

    def normalized(self) -> "EditorInventoryDefaults":
        family_id = clean_required_string(self.family_id, "family_id")
        default_variant_id = normalize_editor_key(self.default_variant_id, "default_variant_id")
        label = clean_required_string(self.label, "label")
        short_label = clean_optional_string(self.short_label) or label
        description = clean_optional_string(self.description) or ""
        domain = clean_optional_string(self.domain)
        category = clean_optional_string(self.category)
        subcategory = clean_optional_string(self.subcategory)
        object_kind = normalize_optional_object_kind(self.object_kind)
        inventory_group = normalize_editor_key(self.inventory_group or DEFAULT_INVENTORY_GROUP, "inventory_group")
        visibility = parse_inventory_visibility_value(self.visibility)
        creative_library_visible = bool(self.creative_library_visible)
        hotbar_eligible = bool(self.hotbar_eligible)
        icon_ref = clean_optional_string(self.icon_ref)
        preview_ref = clean_optional_string(self.preview_ref)
        sort_key = clean_optional_string(self.sort_key) or build_sort_key(domain, category, subcategory, label)
        search_text = clean_optional_string(self.search_text) or build_search_text(
            label=label,
            short_label=short_label,
            description=description,
            domain=domain,
            category=category,
            subcategory=subcategory,
            tags=self.tags,
        )
        tags = normalize_string_tuple(self.tags)
        metadata = normalize_metadata(self.metadata)

        if visibility != InventoryVisibility.VISIBLE.value:
            creative_library_visible = False

        return EditorInventoryDefaults(
            family_id=family_id,
            default_variant_id=default_variant_id,
            label=label,
            short_label=short_label,
            description=description,
            domain=domain,
            category=category,
            subcategory=subcategory,
            object_kind=object_kind,
            inventory_group=inventory_group,
            visibility=visibility,
            creative_library_visible=creative_library_visible,
            hotbar_eligible=hotbar_eligible,
            icon_ref=icon_ref,
            preview_ref=preview_ref,
            sort_key=sort_key,
            search_text=search_text,
            tags=tags,
            metadata=metadata,
        )

    def to_document(self) -> dict[str, Any]:
        """Erzeugt editor/inventory.json."""
        normalized = self.normalized()

        return {
            "schema_version": EDITOR_INVENTORY_DOCUMENT_SCHEMA_VERSION,
            "family_id": normalized.family_id,
            "default_variant_id": normalized.default_variant_id,
            "label": normalized.label,
            "short_label": normalized.short_label,
            "description": normalized.description,
            "domain": normalized.domain,
            "category": normalized.category,
            "subcategory": normalized.subcategory,
            "object_kind": normalized.object_kind,
            "inventory_group": normalized.inventory_group,
            "visibility": normalized.visibility,
            "creative_library_visible": normalized.creative_library_visible,
            "hotbar_eligible": normalized.hotbar_eligible,
            "icon_ref": normalized.icon_ref,
            "preview_ref": normalized.preview_ref,
            "sort_key": normalized.sort_key,
            "search_text": normalized.search_text,
            "tags": list(normalized.tags),
            "metadata": dict(normalized.metadata),
        }

    def to_dict(self) -> dict[str, Any]:
        return self.to_document()


@dataclass(frozen=True, slots=True)
class EditorPlacementDefaults:
    """Defaults für editor/placement.json."""

    object_kind: str
    placement_mode: str
    grid_footprint: GridFootprintDefaults = field(default_factory=GridFootprintDefaults)
    allowed_surfaces: tuple[str, ...] = DEFAULT_ALLOWED_SURFACES
    allowed_hosts: tuple[str, ...] = DEFAULT_ALLOWED_HOSTS
    rotation_allowed: bool = True
    rotation_steps: tuple[int, ...] = DEFAULT_ROTATION_STEPS
    snap_mode: str = SnapMode.GRID.value
    requires_support: bool | None = None
    requires_surface_normal: bool | None = None
    requires_support_surface: bool | None = None
    can_stack: bool = True
    can_attach: bool = False
    can_rotate: bool = True
    grid_footprint_is_placement_truth: bool = True
    visual_model_must_remain_inside_footprint: bool = True
    metadata: Mapping[str, Any] = field(default_factory=dict)

    def normalized(self) -> "EditorPlacementDefaults":
        object_kind = normalize_object_kind_value(self.object_kind)
        placement_mode = normalize_placement_mode_value(self.placement_mode)
        grid_footprint = self.grid_footprint.normalized()
        allowed_surfaces = normalize_surface_tuple(self.allowed_surfaces)
        allowed_hosts = normalize_host_tuple(self.allowed_hosts)
        rotation_allowed = bool(self.rotation_allowed)
        rotation_steps = normalize_rotation_steps(self.rotation_steps)
        snap_mode = parse_snap_mode_value(self.snap_mode)
        requires_support = None if self.requires_support is None else bool(self.requires_support)
        requires_surface_normal = infer_requires_surface_normal(placement_mode, self.requires_surface_normal)
        requires_support_surface = infer_requires_support_surface(placement_mode, self.requires_support_surface)
        can_stack = bool(self.can_stack)
        can_attach = bool(self.can_attach)
        can_rotate = bool(self.can_rotate and rotation_allowed)
        metadata = normalize_metadata(self.metadata)

        validate_placement_mode_for_object_kind_safe(
            placement_mode=placement_mode,
            object_kind=object_kind,
        )

        return EditorPlacementDefaults(
            object_kind=object_kind,
            placement_mode=placement_mode,
            grid_footprint=grid_footprint,
            allowed_surfaces=allowed_surfaces,
            allowed_hosts=allowed_hosts,
            rotation_allowed=rotation_allowed,
            rotation_steps=rotation_steps,
            snap_mode=snap_mode,
            requires_support=requires_support,
            requires_surface_normal=requires_surface_normal,
            requires_support_surface=requires_support_surface,
            can_stack=can_stack,
            can_attach=can_attach,
            can_rotate=can_rotate,
            grid_footprint_is_placement_truth=True,
            visual_model_must_remain_inside_footprint=True,
            metadata=metadata,
        )

    def to_document(self) -> dict[str, Any]:
        """Erzeugt editor/placement.json."""
        normalized = self.normalized()

        return {
            "schema_version": EDITOR_PLACEMENT_DOCUMENT_SCHEMA_VERSION,
            "object_kind": normalized.object_kind,
            "placement_mode": normalized.placement_mode,
            "grid_footprint": normalized.grid_footprint.to_dict(),
            "allowed_surfaces": list(normalized.allowed_surfaces),
            "allowed_hosts": list(normalized.allowed_hosts),
            "rotation_allowed": normalized.rotation_allowed,
            "rotation_steps": list(normalized.rotation_steps),
            "snap_mode": normalized.snap_mode,
            "requires_support": normalized.requires_support,
            "requires_surface_normal": normalized.requires_surface_normal,
            "requires_support_surface": normalized.requires_support_surface,
            "can_stack": normalized.can_stack,
            "can_attach": normalized.can_attach,
            "can_rotate": normalized.can_rotate,
            "grid_footprint_is_placement_truth": normalized.grid_footprint_is_placement_truth,
            "visual_model_must_remain_inside_footprint": normalized.visual_model_must_remain_inside_footprint,
            "metadata": dict(normalized.metadata),
        }

    def to_dict(self) -> dict[str, Any]:
        return self.to_document()


@dataclass(frozen=True, slots=True)
class EditorTargetingDefaults:
    """Defaults für editor/targeting.json."""

    targeting_modes: tuple[str, ...] = (TargetingMode.BLOCK_FACE.value,)
    max_range_m: float = DEFAULT_TARGETING_RANGE_M
    require_line_of_sight: bool = True
    prefer_surface_normal: bool = True
    allow_through_transparent: bool = False
    metadata: Mapping[str, Any] = field(default_factory=dict)

    def normalized(self) -> "EditorTargetingDefaults":
        return EditorTargetingDefaults(
            targeting_modes=normalize_targeting_mode_tuple(self.targeting_modes),
            max_range_m=normalize_positive_float(self.max_range_m, "max_range_m"),
            require_line_of_sight=bool(self.require_line_of_sight),
            prefer_surface_normal=bool(self.prefer_surface_normal),
            allow_through_transparent=bool(self.allow_through_transparent),
            metadata=normalize_metadata(self.metadata),
        )

    def to_document(self) -> dict[str, Any]:
        """Erzeugt editor/targeting.json."""
        normalized = self.normalized()

        return {
            "schema_version": EDITOR_TARGETING_DOCUMENT_SCHEMA_VERSION,
            "targeting_modes": list(normalized.targeting_modes),
            "max_range_m": normalized.max_range_m,
            "require_line_of_sight": normalized.require_line_of_sight,
            "prefer_surface_normal": normalized.prefer_surface_normal,
            "allow_through_transparent": normalized.allow_through_transparent,
            "metadata": dict(normalized.metadata),
        }

    def to_dict(self) -> dict[str, Any]:
        return self.to_document()


@dataclass(frozen=True, slots=True)
class EditorAnchorDefaults:
    """Ein Anchor für editor/anchors.json."""

    anchor_id: str
    anchor_kind: str = AnchorKind.CENTER.value
    label: str | None = None
    position: Mapping[str, float] = field(default_factory=lambda: {"x": 0.5, "y": 0.5, "z": 0.5})
    normal: Mapping[str, float] | None = None
    enabled: bool = True
    metadata: Mapping[str, Any] = field(default_factory=dict)

    def normalized(self) -> "EditorAnchorDefaults":
        anchor_id = normalize_editor_key(self.anchor_id, "anchor_id")
        anchor_kind = parse_anchor_kind_value(self.anchor_kind)
        label = clean_optional_string(self.label) or anchor_id
        position = normalize_vector3(self.position, "position")
        normal = normalize_optional_vector3(self.normal, "normal")
        enabled = bool(self.enabled)
        metadata = normalize_metadata(self.metadata)

        return EditorAnchorDefaults(
            anchor_id=anchor_id,
            anchor_kind=anchor_kind,
            label=label,
            position=position,
            normal=normal,
            enabled=enabled,
            metadata=metadata,
        )

    def to_dict(self) -> dict[str, Any]:
        normalized = self.normalized()

        return {
            "anchor_id": normalized.anchor_id,
            "anchor_kind": normalized.anchor_kind,
            "label": normalized.label,
            "position": dict(normalized.position),
            "normal": dict(normalized.normal) if normalized.normal else None,
            "enabled": normalized.enabled,
            "metadata": dict(normalized.metadata),
        }


@dataclass(frozen=True, slots=True)
class EditorAnchorsDefaults:
    """Defaults für editor/anchors.json."""

    anchors: tuple[EditorAnchorDefaults, ...] = field(default_factory=tuple)
    metadata: Mapping[str, Any] = field(default_factory=dict)

    def normalized(self) -> "EditorAnchorsDefaults":
        anchors = tuple(anchor.normalized() for anchor in self.anchors or ())

        if not anchors:
            anchors = (
                EditorAnchorDefaults(
                    anchor_id="center",
                    anchor_kind=AnchorKind.CENTER.value,
                    label="Center",
                ).normalized(),
            )

        assert_unique_ids(
            [anchor.anchor_id for anchor in anchors],
            field_name="anchor_id",
        )

        return EditorAnchorsDefaults(
            anchors=anchors,
            metadata=normalize_metadata(self.metadata),
        )

    def to_document(self) -> dict[str, Any]:
        """Erzeugt editor/anchors.json."""
        normalized = self.normalized()

        return {
            "schema_version": EDITOR_ANCHORS_DOCUMENT_SCHEMA_VERSION,
            "anchors": [anchor.to_dict() for anchor in normalized.anchors],
            "metadata": dict(normalized.metadata),
        }

    def to_dict(self) -> dict[str, Any]:
        return self.to_document()


@dataclass(frozen=True, slots=True)
class EditorSocketDefaults:
    """Ein Socket für editor/sockets.json."""

    socket_id: str
    socket_kind: str = SocketKind.ATTACHMENT.value
    label: str | None = None
    anchor_id: str | None = None
    accepted_object_kinds: tuple[str, ...] = field(default_factory=tuple)
    accepted_family_ids: tuple[str, ...] = field(default_factory=tuple)
    enabled: bool = True
    metadata: Mapping[str, Any] = field(default_factory=dict)

    def normalized(self) -> "EditorSocketDefaults":
        socket_id = normalize_editor_key(self.socket_id, "socket_id")
        socket_kind = parse_socket_kind_value(self.socket_kind)
        label = clean_optional_string(self.label) or socket_id
        anchor_id = normalize_optional_editor_key(self.anchor_id, "anchor_id")
        accepted_object_kinds = normalize_object_kind_tuple(self.accepted_object_kinds)
        accepted_family_ids = normalize_string_tuple(self.accepted_family_ids)
        enabled = bool(self.enabled)
        metadata = normalize_metadata(self.metadata)

        return EditorSocketDefaults(
            socket_id=socket_id,
            socket_kind=socket_kind,
            label=label,
            anchor_id=anchor_id,
            accepted_object_kinds=accepted_object_kinds,
            accepted_family_ids=accepted_family_ids,
            enabled=enabled,
            metadata=metadata,
        )

    def to_dict(self) -> dict[str, Any]:
        normalized = self.normalized()

        return {
            "socket_id": normalized.socket_id,
            "socket_kind": normalized.socket_kind,
            "label": normalized.label,
            "anchor_id": normalized.anchor_id,
            "accepted_object_kinds": list(normalized.accepted_object_kinds),
            "accepted_family_ids": list(normalized.accepted_family_ids),
            "enabled": normalized.enabled,
            "metadata": dict(normalized.metadata),
        }


@dataclass(frozen=True, slots=True)
class EditorSocketsDefaults:
    """Defaults für editor/sockets.json."""

    sockets: tuple[EditorSocketDefaults, ...] = field(default_factory=tuple)
    metadata: Mapping[str, Any] = field(default_factory=dict)

    def normalized(self) -> "EditorSocketsDefaults":
        sockets = tuple(socket.normalized() for socket in self.sockets or ())
        assert_unique_ids(
            [socket.socket_id for socket in sockets],
            field_name="socket_id",
        )

        return EditorSocketsDefaults(
            sockets=sockets,
            metadata=normalize_metadata(self.metadata),
        )

    def to_document(self) -> dict[str, Any]:
        """Erzeugt editor/sockets.json."""
        normalized = self.normalized()

        return {
            "schema_version": EDITOR_SOCKETS_DOCUMENT_SCHEMA_VERSION,
            "sockets": [socket.to_dict() for socket in normalized.sockets],
            "metadata": dict(normalized.metadata),
        }

    def to_dict(self) -> dict[str, Any]:
        return self.to_document()


@dataclass(frozen=True, slots=True)
class EditorPortDefaults:
    """Ein Port für editor/ports.json."""

    port_id: str
    port_kind: str = PortKind.BIDIRECTIONAL.value
    label: str | None = None
    socket_id: str | None = None
    unit: str | None = None
    data_type: str | None = None
    enabled: bool = True
    metadata: Mapping[str, Any] = field(default_factory=dict)

    def normalized(self) -> "EditorPortDefaults":
        port_id = normalize_editor_key(self.port_id, "port_id")
        port_kind = parse_port_kind_value(self.port_kind)
        label = clean_optional_string(self.label) or port_id
        socket_id = normalize_optional_editor_key(self.socket_id, "socket_id")
        unit = clean_optional_string(self.unit)
        data_type = clean_optional_string(self.data_type)
        enabled = bool(self.enabled)
        metadata = normalize_metadata(self.metadata)

        return EditorPortDefaults(
            port_id=port_id,
            port_kind=port_kind,
            label=label,
            socket_id=socket_id,
            unit=unit,
            data_type=data_type,
            enabled=enabled,
            metadata=metadata,
        )

    def to_dict(self) -> dict[str, Any]:
        normalized = self.normalized()

        return {
            "port_id": normalized.port_id,
            "port_kind": normalized.port_kind,
            "label": normalized.label,
            "socket_id": normalized.socket_id,
            "unit": normalized.unit,
            "data_type": normalized.data_type,
            "enabled": normalized.enabled,
            "metadata": dict(normalized.metadata),
        }


@dataclass(frozen=True, slots=True)
class EditorPortsDefaults:
    """Defaults für editor/ports.json."""

    ports: tuple[EditorPortDefaults, ...] = field(default_factory=tuple)
    metadata: Mapping[str, Any] = field(default_factory=dict)

    def normalized(self) -> "EditorPortsDefaults":
        ports = tuple(port.normalized() for port in self.ports or ())
        assert_unique_ids(
            [port.port_id for port in ports],
            field_name="port_id",
        )

        return EditorPortsDefaults(
            ports=ports,
            metadata=normalize_metadata(self.metadata),
        )

    def to_document(self) -> dict[str, Any]:
        """Erzeugt editor/ports.json."""
        normalized = self.normalized()

        return {
            "schema_version": EDITOR_PORTS_DOCUMENT_SCHEMA_VERSION,
            "ports": [port.to_dict() for port in normalized.ports],
            "metadata": dict(normalized.metadata),
        }

    def to_dict(self) -> dict[str, Any]:
        return self.to_document()


@dataclass(frozen=True, slots=True)
class EditorToolsDefaults:
    """Defaults für editor/tools.json."""

    enabled_tools: tuple[str, ...] = (
        EditorTool.PLACE.value,
        EditorTool.REMOVE.value,
        EditorTool.INSPECT.value,
        EditorTool.VARIANT_SWITCH.value,
    )
    metadata: Mapping[str, Any] = field(default_factory=dict)

    def normalized(self) -> "EditorToolsDefaults":
        return EditorToolsDefaults(
            enabled_tools=normalize_tool_tuple(self.enabled_tools),
            metadata=normalize_metadata(self.metadata),
        )

    def to_document(self) -> dict[str, Any]:
        """Erzeugt editor/tools.json."""
        normalized = self.normalized()

        return {
            "schema_version": EDITOR_TOOLS_DOCUMENT_SCHEMA_VERSION,
            "enabled_tools": list(normalized.enabled_tools),
            "metadata": dict(normalized.metadata),
        }

    def to_dict(self) -> dict[str, Any]:
        return self.to_document()


@dataclass(frozen=True, slots=True)
class EditorHotbarDefaults:
    """Defaults für editor/hotbar.json."""

    eligible: bool = True
    preferred_slot: int | None = None
    default_variant_id: str = "default"
    metadata: Mapping[str, Any] = field(default_factory=dict)

    def normalized(self) -> "EditorHotbarDefaults":
        preferred_slot = (
            normalize_non_negative_int(self.preferred_slot, "preferred_slot")
            if self.preferred_slot is not None
            else None
        )

        return EditorHotbarDefaults(
            eligible=bool(self.eligible),
            preferred_slot=preferred_slot,
            default_variant_id=normalize_editor_key(self.default_variant_id, "default_variant_id"),
            metadata=normalize_metadata(self.metadata),
        )

    def to_document(self) -> dict[str, Any]:
        """Erzeugt editor/hotbar.json."""
        normalized = self.normalized()

        return {
            "schema_version": EDITOR_HOTBAR_DOCUMENT_SCHEMA_VERSION,
            "eligible": normalized.eligible,
            "preferred_slot": normalized.preferred_slot,
            "default_variant_id": normalized.default_variant_id,
            "metadata": dict(normalized.metadata),
        }

    def to_dict(self) -> dict[str, Any]:
        return self.to_document()


@dataclass(frozen=True, slots=True)
class EditorDefaults:
    """Vollständige Defaults für alle editor/*.json-Dokumente."""

    inventory: EditorInventoryDefaults
    placement: EditorPlacementDefaults
    targeting: EditorTargetingDefaults = field(default_factory=EditorTargetingDefaults)
    anchors: EditorAnchorsDefaults = field(default_factory=EditorAnchorsDefaults)
    sockets: EditorSocketsDefaults = field(default_factory=EditorSocketsDefaults)
    ports: EditorPortsDefaults = field(default_factory=EditorPortsDefaults)
    tools: EditorToolsDefaults = field(default_factory=EditorToolsDefaults)
    hotbar: EditorHotbarDefaults = field(default_factory=EditorHotbarDefaults)

    def normalized(self) -> "EditorDefaults":
        inventory = self.inventory.normalized()
        placement = self.placement.normalized()
        targeting = self.targeting.normalized()
        anchors = self.anchors.normalized()
        sockets = self.sockets.normalized()
        ports = self.ports.normalized()
        tools = self.tools.normalized()
        hotbar = self.hotbar.normalized()

        return EditorDefaults(
            inventory=inventory,
            placement=placement,
            targeting=targeting,
            anchors=anchors,
            sockets=sockets,
            ports=ports,
            tools=tools,
            hotbar=hotbar,
        )

    def to_documents(self, *, include_optional: bool = True) -> dict[str, dict[str, Any]]:
        """Erzeugt alle Editor-Dokumente als Pfad -> Payload."""
        normalized = self.normalized()

        documents = {
            "editor/inventory.json": normalized.inventory.to_document(),
            "editor/placement.json": normalized.placement.to_document(),
        }

        if include_optional:
            documents["editor/targeting.json"] = normalized.targeting.to_document()
            documents["editor/anchors.json"] = normalized.anchors.to_document()
            documents["editor/sockets.json"] = normalized.sockets.to_document()
            documents["editor/ports.json"] = normalized.ports.to_document()
            documents["editor/tools.json"] = normalized.tools.to_document()
            documents["editor/hotbar.json"] = normalized.hotbar.to_document()

        return documents

    def to_dict(self) -> dict[str, Any]:
        normalized = self.normalized()

        return {
            "schema_version": EDITOR_DEFAULTS_SCHEMA_VERSION,
            "inventory": normalized.inventory.to_dict(),
            "placement": normalized.placement.to_dict(),
            "targeting": normalized.targeting.to_dict(),
            "anchors": normalized.anchors.to_dict(),
            "sockets": normalized.sockets.to_dict(),
            "ports": normalized.ports.to_dict(),
            "tools": normalized.tools.to_dict(),
            "hotbar": normalized.hotbar.to_dict(),
        }


def build_editor_defaults(
    *,
    family_id: str,
    default_variant_id: str,
    label: str,
    object_kind: str,
    placement_mode: str,
    grid_size_cells: Sequence[Any] = (1, 1, 1),
    cell_size_m: float = 1.0,
    short_label: str | None = None,
    description: str = "",
    domain: str | None = None,
    category: str | None = None,
    subcategory: str | None = None,
    icon_ref: str | None = None,
    preview_ref: str | None = None,
    allowed_surfaces: Iterable[Any] = DEFAULT_ALLOWED_SURFACES,
    allowed_hosts: Iterable[Any] = DEFAULT_ALLOWED_HOSTS,
    rotation_allowed: bool = True,
    rotation_steps: Iterable[Any] = DEFAULT_ROTATION_STEPS,
    snap_mode: str = SnapMode.GRID.value,
    metadata: Mapping[str, Any] | None = None,
) -> EditorDefaults:
    """Baut EditorDefaults aus expliziten Werten."""
    try:
        x, y, z = normalize_grid_size_cells(grid_size_cells)
        metadata_payload = dict(metadata or {})

        return EditorDefaults(
            inventory=EditorInventoryDefaults(
                family_id=family_id,
                default_variant_id=default_variant_id,
                label=label,
                short_label=short_label,
                description=description,
                domain=domain,
                category=category,
                subcategory=subcategory,
                object_kind=object_kind,
                icon_ref=icon_ref,
                preview_ref=preview_ref,
                tags=tuple(),
                metadata=metadata_payload,
            ),
            placement=EditorPlacementDefaults(
                object_kind=object_kind,
                placement_mode=placement_mode,
                grid_footprint=GridFootprintDefaults(
                    size_cells_x=x,
                    size_cells_y=y,
                    size_cells_z=z,
                    cell_size_m=cell_size_m,
                ),
                allowed_surfaces=tuple(allowed_surfaces or ()),
                allowed_hosts=tuple(allowed_hosts or ()),
                rotation_allowed=rotation_allowed,
                rotation_steps=tuple(rotation_steps or ()),
                snap_mode=snap_mode,
                metadata=metadata_payload,
            ),
            hotbar=EditorHotbarDefaults(
                eligible=True,
                default_variant_id=default_variant_id,
                metadata=metadata_payload,
            ),
        ).normalized()
    except EditorDefaultsError:
        raise
    except Exception as exc:
        raise EditorDefaultsError(f"Could not build editor defaults: {exc}") from exc


def editor_defaults_from_create_request(
    request: Any,
    *,
    metadata: Mapping[str, Any] | None = None,
) -> EditorDefaults:
    """Baut EditorDefaults aus einem CreateRequest-ähnlichen Objekt."""
    try:
        normalized_request = normalize_create_request(request)
        identity = normalized_request.identity.normalized()
        classification = normalized_request.classification.normalized()
        grid = normalized_request.grid.normalized()
        placement = normalized_request.placement.normalized(object_kind=normalized_request.object_kind)
        visual = normalized_request.visual.normalized()
        variants = normalized_request.variants.normalized()

        return build_editor_defaults(
            family_id=identity.family_id,
            default_variant_id=variants.default_variant_id,
            label=identity.display_name or identity.family_name,
            short_label=identity.short_name,
            description=identity.description,
            object_kind=normalized_request.object_kind,
            domain=classification.domain,
            category=classification.category,
            subcategory=classification.subcategory,
            placement_mode=placement.placement_mode,
            grid_size_cells=grid.size_cells,
            cell_size_m=grid.cell_size_m,
            icon_ref=visual.icon_ref,
            preview_ref=visual.preview_ref,
            allowed_surfaces=placement.allowed_surfaces or DEFAULT_ALLOWED_SURFACES,
            allowed_hosts=placement.allowed_hosts or DEFAULT_ALLOWED_HOSTS,
            rotation_allowed=placement.rotation_allowed,
            rotation_steps=placement.rotation_steps,
            snap_mode=placement.snap_mode,
            metadata={
                "source": "create_request",
                **dict(metadata or {}),
            },
        )
    except EditorDefaultsError:
        raise
    except Exception as exc:
        raise EditorDefaultsError(f"Could not build editor defaults from CreateRequest: {exc}") from exc


def editor_defaults_from_context(
    context: Any,
    *,
    label: str | None = None,
    default_variant_id: str = "default",
    placement_mode: str | None = None,
    metadata: Mapping[str, Any] | None = None,
) -> EditorDefaults:
    """Baut EditorDefaults aus einem PackageContext-ähnlichen Objekt."""
    try:
        normalized_context = context.normalized() if hasattr(context, "normalized") else context
        object_kind = normalized_context.object_kind

        resolved_placement_mode = placement_mode or get_default_placement_mode_for_object_kind_safe(object_kind)

        return build_editor_defaults(
            family_id=normalized_context.identity.family_id,
            default_variant_id=default_variant_id,
            label=label or normalized_context.identity.family_name,
            object_kind=object_kind,
            domain=normalized_context.classification.domain,
            category=normalized_context.classification.category,
            subcategory=normalized_context.classification.subcategory,
            placement_mode=resolved_placement_mode,
            metadata={
                "source": "package_context",
                "correlation_id": getattr(normalized_context, "correlation_id", None),
                **dict(metadata or {}),
            },
        )
    except EditorDefaultsError:
        raise
    except Exception as exc:
        raise EditorDefaultsError(f"Could not build editor defaults from PackageContext: {exc}") from exc


def editor_defaults_from_creation_plan(
    creation_plan: Any,
    *,
    metadata: Mapping[str, Any] | None = None,
) -> EditorDefaults:
    """Baut EditorDefaults aus einem CreationPlan-ähnlichen Objekt."""
    try:
        normalized_plan = creation_plan.normalized() if hasattr(creation_plan, "normalized") else creation_plan

        return editor_defaults_from_create_request(
            normalized_plan.request,
            metadata={
                "source": "creation_plan",
                "profile_key": getattr(normalized_plan.profile, "profile_key", None),
                **dict(metadata or {}),
            },
        )
    except EditorDefaultsError:
        raise
    except Exception as exc:
        raise EditorDefaultsError(f"Could not build editor defaults from CreationPlan: {exc}") from exc


def editor_documents_from_create_request(
    request: Any,
    *,
    include_optional: bool = True,
    metadata: Mapping[str, Any] | None = None,
) -> dict[str, dict[str, Any]]:
    """Baut alle editor/*.json-Dokumente aus CreateRequest."""
    return editor_defaults_from_create_request(
        request,
        metadata=metadata,
    ).to_documents(include_optional=include_optional)


def editor_documents_from_context(
    context: Any,
    *,
    include_optional: bool = True,
    metadata: Mapping[str, Any] | None = None,
) -> dict[str, dict[str, Any]]:
    """Baut alle editor/*.json-Dokumente aus PackageContext."""
    return editor_defaults_from_context(
        context,
        metadata=metadata,
    ).to_documents(include_optional=include_optional)


def editor_documents_from_creation_plan(
    creation_plan: Any,
    *,
    include_optional: bool = True,
    metadata: Mapping[str, Any] | None = None,
) -> dict[str, dict[str, Any]]:
    """Baut alle editor/*.json-Dokumente aus CreationPlan."""
    return editor_defaults_from_creation_plan(
        creation_plan,
        metadata=metadata,
    ).to_documents(include_optional=include_optional)


def validate_inventory_document(document: Mapping[str, Any]) -> tuple[bool, tuple[str, ...]]:
    """Validiert grob editor/inventory.json."""
    messages: list[str] = []

    try:
        if not isinstance(document, Mapping):
            return False, ("editor/inventory.json must be a mapping.",)

        required_fields = (
            "schema_version",
            "family_id",
            "default_variant_id",
            "label",
            "visibility",
            "creative_library_visible",
            "hotbar_eligible",
        )

        for field_name in required_fields:
            if field_name not in document:
                messages.append(f"Missing inventory field {field_name!r}.")

        if "visibility" in document:
            try:
                parse_inventory_visibility_value(document["visibility"])
            except Exception as exc:
                messages.append(str(exc))

    except Exception as exc:
        messages.append(f"Could not validate inventory document: {exc}")

    return len(messages) == 0, tuple(messages)


def validate_placement_document(document: Mapping[str, Any]) -> tuple[bool, tuple[str, ...]]:
    """Validiert grob editor/placement.json."""
    messages: list[str] = []

    try:
        if not isinstance(document, Mapping):
            return False, ("editor/placement.json must be a mapping.",)

        required_fields = (
            "schema_version",
            "object_kind",
            "placement_mode",
            "grid_footprint",
            "allowed_surfaces",
            "allowed_hosts",
            "rotation_allowed",
            "rotation_steps",
            "snap_mode",
            "grid_footprint_is_placement_truth",
            "visual_model_must_remain_inside_footprint",
        )

        for field_name in required_fields:
            if field_name not in document:
                messages.append(f"Missing placement field {field_name!r}.")

        if "object_kind" in document:
            try:
                normalize_object_kind_value(document["object_kind"])
            except Exception as exc:
                messages.append(str(exc))

        if "placement_mode" in document:
            try:
                normalize_placement_mode_value(document["placement_mode"])
            except Exception as exc:
                messages.append(str(exc))

        grid = document.get("grid_footprint")
        if isinstance(grid, Mapping):
            try:
                size_cells = grid.get("size_cells", {})
                GridFootprintDefaults(
                    size_cells_x=grid.get("size_cells_x", size_cells.get("x", 1)),
                    size_cells_y=grid.get("size_cells_y", size_cells.get("y", 1)),
                    size_cells_z=grid.get("size_cells_z", size_cells.get("z", 1)),
                    cell_size_m=grid.get("cell_size_m", 1.0),
                ).normalized()
            except Exception as exc:
                messages.append(str(exc))
        else:
            messages.append("placement grid_footprint must be an object.")

    except Exception as exc:
        messages.append(f"Could not validate placement document: {exc}")

    return len(messages) == 0, tuple(messages)


def assert_valid_inventory_document(document: Mapping[str, Any]) -> None:
    """Wirft EditorDefaultsError, wenn editor/inventory.json ungültig ist."""
    valid, messages = validate_inventory_document(document)

    if not valid:
        joined = " ".join(messages) if messages else "Invalid inventory document."
        raise EditorDefaultsError(joined)


def assert_valid_placement_document(document: Mapping[str, Any]) -> None:
    """Wirft EditorDefaultsError, wenn editor/placement.json ungültig ist."""
    valid, messages = validate_placement_document(document)

    if not valid:
        joined = " ".join(messages) if messages else "Invalid placement document."
        raise EditorDefaultsError(joined)


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

        raise EditorDefaultsError("CreateRequest value is required.")
    except EditorDefaultsError:
        raise
    except Exception as exc:
        raise EditorDefaultsError(f"Invalid CreateRequest: {exc}") from exc


def normalize_object_kind_value(value: Any) -> str:
    """Normalisiert object_kind."""
    try:
        from ..domain.object_kinds import ensure_object_kind_value

        return ensure_object_kind_value(value)
    except Exception as exc:
        raise EditorDefaultsError(f"Invalid object_kind {value!r}: {exc}") from exc


def normalize_optional_object_kind(value: Any) -> str | None:
    """Normalisiert optionale object_kind."""
    if value is None:
        return None

    return normalize_object_kind_value(value)


def normalize_object_kind_tuple(values: Iterable[Any]) -> tuple[str, ...]:
    """Normalisiert mehrere object_kind-Werte."""
    result: list[str] = []
    seen: set[str] = set()

    for value in values or ():
        normalized = normalize_object_kind_value(value)
        if normalized in seen:
            continue
        result.append(normalized)
        seen.add(normalized)

    return tuple(result)


def normalize_placement_mode_value(value: Any) -> str:
    """Normalisiert placement_mode."""
    try:
        from ..domain.placement_modes import ensure_placement_mode_value

        return ensure_placement_mode_value(value)
    except Exception as exc:
        raise EditorDefaultsError(f"Invalid placement_mode {value!r}: {exc}") from exc


def get_default_placement_mode_for_object_kind_safe(object_kind: Any) -> str:
    """Liest Default-Placement-Mode für object_kind."""
    try:
        from ..domain.placement_modes import get_default_placement_mode_for_object_kind

        return get_default_placement_mode_for_object_kind(object_kind).value
    except Exception:
        return "centered"


def validate_placement_mode_for_object_kind_safe(*, placement_mode: str, object_kind: str) -> None:
    """Validiert placement_mode gegen object_kind."""
    try:
        from ..domain.placement_modes import validate_placement_mode_for_object_kind

        valid, messages = validate_placement_mode_for_object_kind(
            placement_mode=placement_mode,
            object_kind=object_kind,
        )

        if not valid:
            raise EditorDefaultsError(" ".join(messages))
    except EditorDefaultsError:
        raise
    except Exception as exc:
        raise EditorDefaultsError(f"Could not validate placement mode: {exc}") from exc


def infer_requires_surface_normal(placement_mode: str, explicit_value: bool | None) -> bool:
    """Leitet requires_surface_normal aus placement_mode ab."""
    if explicit_value is not None:
        return bool(explicit_value)

    try:
        from ..domain.placement_modes import requires_surface_normal

        return bool(requires_surface_normal(placement_mode))
    except Exception:
        return placement_mode == "surface_aligned"


def infer_requires_support_surface(placement_mode: str, explicit_value: bool | None) -> bool:
    """Leitet requires_support_surface aus placement_mode ab."""
    if explicit_value is not None:
        return bool(explicit_value)

    try:
        from ..domain.placement_modes import requires_support_surface

        return bool(requires_support_surface(placement_mode))
    except Exception:
        return placement_mode in {"bottom_aligned", "top_aligned", "surface_aligned"}


def normalize_editor_key(value: Any, field_name: str) -> str:
    """Normalisiert technische Editor-Keys."""
    raw = clean_required_string(value, field_name)
    key = (
        raw.lower()
        .replace(" ", "_")
        .replace("-", "_")
        .replace("/", "_")
        .replace("\\", "_")
    )

    if not SAFE_EDITOR_KEY_RE.match(key):
        raise EditorDefaultsError(f"{field_name} contains unsafe characters: {value!r}.")

    return key


def normalize_optional_editor_key(value: Any, field_name: str) -> str | None:
    """Normalisiert optionale Editor-Keys."""
    if value is None:
        return None

    return normalize_editor_key(value, field_name)


@lru_cache(maxsize=128)
def parse_inventory_visibility_value(value: Any) -> str:
    """Parst InventoryVisibility."""
    try:
        if isinstance(value, InventoryVisibility):
            return value.value

        raw = normalize_enum_key(value)

        aliases = {
            "visible": InventoryVisibility.VISIBLE.value,
            "show": InventoryVisibility.VISIBLE.value,
            "shown": InventoryVisibility.VISIBLE.value,
            "hidden": InventoryVisibility.HIDDEN.value,
            "hide": InventoryVisibility.HIDDEN.value,
            "internal": InventoryVisibility.INTERNAL.value,
        }

        if raw in aliases:
            return aliases[raw]

        return InventoryVisibility(raw).value
    except Exception as exc:
        raise EditorDefaultsError(f"Invalid inventory visibility {value!r}.") from exc


@lru_cache(maxsize=128)
def parse_surface_value(value: Any) -> str:
    """Parst EditorSurface."""
    try:
        if isinstance(value, EditorSurface):
            return value.value

        raw = normalize_enum_key(value)
        return EditorSurface(raw).value
    except Exception as exc:
        raise EditorDefaultsError(f"Invalid editor surface {value!r}.") from exc


@lru_cache(maxsize=128)
def parse_host_value(value: Any) -> str:
    """Parst EditorHost."""
    try:
        if isinstance(value, EditorHost):
            return value.value

        raw = normalize_enum_key(value)
        return EditorHost(raw).value
    except Exception as exc:
        raise EditorDefaultsError(f"Invalid editor host {value!r}.") from exc


@lru_cache(maxsize=128)
def parse_snap_mode_value(value: Any) -> str:
    """Parst SnapMode."""
    try:
        if isinstance(value, SnapMode):
            return value.value

        raw = normalize_enum_key(value)
        return SnapMode(raw).value
    except Exception as exc:
        raise EditorDefaultsError(f"Invalid snap_mode {value!r}.") from exc


@lru_cache(maxsize=128)
def parse_targeting_mode_value(value: Any) -> str:
    """Parst TargetingMode."""
    try:
        if isinstance(value, TargetingMode):
            return value.value

        raw = normalize_enum_key(value)
        return TargetingMode(raw).value
    except Exception as exc:
        raise EditorDefaultsError(f"Invalid targeting mode {value!r}.") from exc


@lru_cache(maxsize=128)
def parse_anchor_kind_value(value: Any) -> str:
    """Parst AnchorKind."""
    try:
        if isinstance(value, AnchorKind):
            return value.value

        raw = normalize_enum_key(value)
        return AnchorKind(raw).value
    except Exception as exc:
        raise EditorDefaultsError(f"Invalid anchor kind {value!r}.") from exc


@lru_cache(maxsize=128)
def parse_socket_kind_value(value: Any) -> str:
    """Parst SocketKind."""
    try:
        if isinstance(value, SocketKind):
            return value.value

        raw = normalize_enum_key(value)
        return SocketKind(raw).value
    except Exception as exc:
        raise EditorDefaultsError(f"Invalid socket kind {value!r}.") from exc


@lru_cache(maxsize=128)
def parse_port_kind_value(value: Any) -> str:
    """Parst PortKind."""
    try:
        if isinstance(value, PortKind):
            return value.value

        raw = normalize_enum_key(value)
        return PortKind(raw).value
    except Exception as exc:
        raise EditorDefaultsError(f"Invalid port kind {value!r}.") from exc


@lru_cache(maxsize=128)
def parse_tool_value(value: Any) -> str:
    """Parst EditorTool."""
    try:
        if isinstance(value, EditorTool):
            return value.value

        raw = normalize_enum_key(value)
        return EditorTool(raw).value
    except Exception as exc:
        raise EditorDefaultsError(f"Invalid editor tool {value!r}.") from exc


def normalize_surface_tuple(values: Iterable[Any]) -> tuple[str, ...]:
    """Normalisiert Placement-Surfaces."""
    return dedupe_tuple(parse_surface_value(value) for value in values or ())


def normalize_host_tuple(values: Iterable[Any]) -> tuple[str, ...]:
    """Normalisiert Placement-Hosts."""
    return dedupe_tuple(parse_host_value(value) for value in values or ())


def normalize_targeting_mode_tuple(values: Iterable[Any]) -> tuple[str, ...]:
    """Normalisiert Targeting-Modes."""
    return dedupe_tuple(parse_targeting_mode_value(value) for value in values or ())


def normalize_tool_tuple(values: Iterable[Any]) -> tuple[str, ...]:
    """Normalisiert Editor-Tools."""
    return dedupe_tuple(parse_tool_value(value) for value in values or ())


def normalize_grid_size_cells(values: Sequence[Any]) -> tuple[int, int, int]:
    """Normalisiert Grid-Size-Cells."""
    if not isinstance(values, Sequence) or len(values) != 3:
        raise EditorDefaultsError("grid_size_cells must contain exactly three values.")

    return (
        normalize_positive_int(values[0], "size_cells_x"),
        normalize_positive_int(values[1], "size_cells_y"),
        normalize_positive_int(values[2], "size_cells_z"),
    )


def normalize_rotation_steps(values: Iterable[Any]) -> tuple[int, ...]:
    """Normalisiert Rotationsschritte."""
    result: list[int] = []
    seen: set[int] = set()

    for value in values or DEFAULT_ROTATION_STEPS:
        try:
            step = int(value)
        except Exception as exc:
            raise EditorDefaultsError(f"Invalid rotation step {value!r}.") from exc

        if step < 0 or step >= 360:
            raise EditorDefaultsError("Rotation steps must be in range 0 <= step < 360.")

        if step in seen:
            continue

        result.append(step)
        seen.add(step)

    if 0 not in seen:
        result.insert(0, 0)

    return tuple(sorted(result))


def normalize_vector3(value: Mapping[str, Any], field_name: str) -> dict[str, float]:
    """Normalisiert Vector3-Mapping."""
    if not isinstance(value, Mapping):
        raise EditorDefaultsError(f"{field_name} must be an object.")

    return {
        "x": normalize_float(value.get("x", 0.0), f"{field_name}.x"),
        "y": normalize_float(value.get("y", 0.0), f"{field_name}.y"),
        "z": normalize_float(value.get("z", 0.0), f"{field_name}.z"),
    }


def normalize_optional_vector3(value: Mapping[str, Any] | None, field_name: str) -> dict[str, float] | None:
    """Normalisiert optionales Vector3-Mapping."""
    if value is None:
        return None

    return normalize_vector3(value, field_name)


def assert_unique_ids(values: Iterable[str], field_name: str) -> None:
    """Prüft eindeutige IDs."""
    seen: set[str] = set()

    for value in values or ():
        if value in seen:
            raise EditorDefaultsError(f"Duplicate {field_name} {value!r}.")
        seen.add(value)


def build_sort_key(
    domain: str | None,
    category: str | None,
    subcategory: str | None,
    label: str,
) -> str:
    """Baut Sort-Key für Inventory."""
    parts = [
        clean_optional_string(domain) or "unknown",
        clean_optional_string(category) or "unknown",
        clean_optional_string(subcategory) or "unknown",
        clean_required_string(label, "label"),
    ]
    return "/".join(part.lower().replace(" ", "_") for part in parts)


def build_search_text(
    *,
    label: str,
    short_label: str | None,
    description: str,
    domain: str | None,
    category: str | None,
    subcategory: str | None,
    tags: Iterable[Any],
) -> str:
    """Baut einfachen Suchtext für Inventory."""
    parts = [
        label,
        short_label,
        description,
        domain,
        category,
        subcategory,
        *tuple(tags or ()),
    ]
    return " ".join(
        cleaned
        for cleaned in (clean_optional_string(part) for part in parts)
        if cleaned
    )


def dedupe_tuple(values: Iterable[str]) -> tuple[str, ...]:
    """Entfernt Duplikate, erhält Reihenfolge."""
    result: list[str] = []
    seen: set[str] = set()

    for value in values or ():
        if value in seen:
            continue
        result.append(value)
        seen.add(value)

    return tuple(result)


def normalize_string_tuple(values: Iterable[Any]) -> tuple[str, ...]:
    """Normalisiert Stringlisten."""
    result: list[str] = []
    seen: set[str] = set()

    for value in values or ():
        cleaned = clean_optional_string(value)
        if not cleaned or cleaned in seen:
            continue
        result.append(cleaned)
        seen.add(cleaned)

    return tuple(result)


def normalize_positive_int(value: Any, field_name: str) -> int:
    """Normalisiert positive Integer."""
    try:
        if isinstance(value, bool):
            raise EditorDefaultsError(f"{field_name} must be an integer.")

        number = int(value)
        if number < 1:
            raise EditorDefaultsError(f"{field_name} must be >= 1.")

        return number
    except EditorDefaultsError:
        raise
    except Exception as exc:
        raise EditorDefaultsError(f"{field_name} must be a positive integer.") from exc


def normalize_non_negative_int(value: Any, field_name: str) -> int:
    """Normalisiert nicht-negative Integer."""
    try:
        if isinstance(value, bool):
            raise EditorDefaultsError(f"{field_name} must be an integer.")

        number = int(value)
        if number < 0:
            raise EditorDefaultsError(f"{field_name} must be >= 0.")

        return number
    except EditorDefaultsError:
        raise
    except Exception as exc:
        raise EditorDefaultsError(f"{field_name} must be a non-negative integer.") from exc


def normalize_positive_float(value: Any, field_name: str) -> float:
    """Normalisiert positive Floats."""
    try:
        if isinstance(value, bool):
            raise EditorDefaultsError(f"{field_name} must be a number.")

        number = float(value)
        if number <= 0:
            raise EditorDefaultsError(f"{field_name} must be > 0.")

        return number
    except EditorDefaultsError:
        raise
    except Exception as exc:
        raise EditorDefaultsError(f"{field_name} must be a positive number.") from exc


def normalize_float(value: Any, field_name: str) -> float:
    """Normalisiert Floats."""
    try:
        if isinstance(value, bool):
            raise EditorDefaultsError(f"{field_name} must be a number.")

        return float(value)
    except Exception as exc:
        raise EditorDefaultsError(f"{field_name} must be a number.") from exc


def normalize_enum_key(value: Any) -> str:
    """Normalisiert Enum-ähnliche Werte."""
    try:
        raw = str(value).strip()

        if not raw:
            raise EditorDefaultsError("Enum value is required.")

        return (
            raw.lower()
            .replace(" ", "_")
            .replace("-", "_")
            .replace("/", "_")
            .replace("\\", "_")
        )
    except EditorDefaultsError:
        raise
    except Exception as exc:
        raise EditorDefaultsError(f"Invalid enum value {value!r}.") from exc


def normalize_metadata(value: Mapping[str, Any] | None) -> dict[str, Any]:
    """Normalisiert Metadata JSON-kompatibel."""
    if value is None:
        return {}

    if not isinstance(value, Mapping):
        raise EditorDefaultsError("metadata must be a mapping.")

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
            raise EditorDefaultsError(f"{field_name} is required.")

        return cleaned
    except EditorDefaultsError:
        raise
    except Exception as exc:
        raise EditorDefaultsError(f"{field_name} must be string-like.") from exc


def clean_optional_string(value: Any) -> str | None:
    """Normalisiert optionalen String."""
    if value is None:
        return None

    try:
        cleaned = str(value).strip()
        return cleaned or None
    except Exception:
        return None


def clear_editor_defaults_caches() -> None:
    """Leert interne Parser-Caches."""
    parse_inventory_visibility_value.cache_clear()
    parse_surface_value.cache_clear()
    parse_host_value.cache_clear()
    parse_snap_mode_value.cache_clear()
    parse_targeting_mode_value.cache_clear()
    parse_anchor_kind_value.cache_clear()
    parse_socket_kind_value.cache_clear()
    parse_port_kind_value.cache_clear()
    parse_tool_value.cache_clear()


__all__ = [
    "DEFAULT_ALLOWED_HOSTS",
    "DEFAULT_ALLOWED_SURFACES",
    "DEFAULT_INVENTORY_GROUP",
    "DEFAULT_ROTATION_STEPS",
    "DEFAULT_TARGETING_RANGE_M",
    "EDITOR_ANCHORS_DOCUMENT_SCHEMA_VERSION",
    "EDITOR_DEFAULTS_SCHEMA_VERSION",
    "EDITOR_HOTBAR_DOCUMENT_SCHEMA_VERSION",
    "EDITOR_INVENTORY_DOCUMENT_SCHEMA_VERSION",
    "EDITOR_PLACEMENT_DOCUMENT_SCHEMA_VERSION",
    "EDITOR_PORTS_DOCUMENT_SCHEMA_VERSION",
    "EDITOR_SOCKETS_DOCUMENT_SCHEMA_VERSION",
    "EDITOR_TARGETING_DOCUMENT_SCHEMA_VERSION",
    "EDITOR_TOOLS_DOCUMENT_SCHEMA_VERSION",
    "SAFE_EDITOR_KEY_RE",
    "AnchorKind",
    "EditorAnchorDefaults",
    "EditorAnchorsDefaults",
    "EditorDefaults",
    "EditorDefaultsError",
    "EditorHost",
    "EditorHotbarDefaults",
    "EditorInventoryDefaults",
    "EditorPlacementDefaults",
    "EditorPortDefaults",
    "EditorPortsDefaults",
    "EditorSocketDefaults",
    "EditorSocketsDefaults",
    "EditorSurface",
    "EditorTargetingDefaults",
    "EditorTool",
    "EditorToolsDefaults",
    "GridFootprintDefaults",
    "InventoryVisibility",
    "PortKind",
    "SnapMode",
    "SocketKind",
    "TargetingMode",
    "assert_unique_ids",
    "assert_valid_inventory_document",
    "assert_valid_placement_document",
    "build_editor_defaults",
    "build_search_text",
    "build_sort_key",
    "clean_optional_string",
    "clean_required_string",
    "clear_editor_defaults_caches",
    "dedupe_tuple",
    "editor_defaults_from_context",
    "editor_defaults_from_create_request",
    "editor_defaults_from_creation_plan",
    "editor_documents_from_context",
    "editor_documents_from_create_request",
    "editor_documents_from_creation_plan",
    "get_default_placement_mode_for_object_kind_safe",
    "infer_requires_support_surface",
    "infer_requires_surface_normal",
    "normalize_create_request",
    "normalize_editor_key",
    "normalize_enum_key",
    "normalize_float",
    "normalize_grid_size_cells",
    "normalize_host_tuple",
    "normalize_metadata",
    "normalize_metadata_value",
    "normalize_non_negative_int",
    "normalize_object_kind_tuple",
    "normalize_object_kind_value",
    "normalize_optional_editor_key",
    "normalize_optional_object_kind",
    "normalize_optional_vector3",
    "normalize_placement_mode_value",
    "normalize_positive_float",
    "normalize_positive_int",
    "normalize_rotation_steps",
    "normalize_string_tuple",
    "normalize_surface_tuple",
    "normalize_targeting_mode_tuple",
    "normalize_tool_tuple",
    "normalize_vector3",
    "parse_anchor_kind_value",
    "parse_host_value",
    "parse_inventory_visibility_value",
    "parse_port_kind_value",
    "parse_snap_mode_value",
    "parse_socket_kind_value",
    "parse_surface_value",
    "parse_targeting_mode_value",
    "parse_tool_value",
    "validate_inventory_document",
    "validate_placement_document",
    "validate_placement_mode_for_object_kind_safe",
]