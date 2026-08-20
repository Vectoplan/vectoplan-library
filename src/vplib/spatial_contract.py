"""Normalize the generic spatial/connection contract used by VPLIB packages."""

from __future__ import annotations

import json
import math
import re
from collections.abc import Mapping
from typing import Any


SPATIAL_SCHEMA_VERSION = "vplib.spatial.v1"
ALLOWED_SPATIAL_MODES = {"contained", "asset_driven", "hybrid"}
ALLOWED_ZONE_SOURCES = {
    "manual_dimensions",
    "primary_model_bounds",
    "primary_model_hull",
    "primary_model_mesh",
}
ALLOWED_ZONE_SHAPES = {"box", "oriented_box", "convex_hull", "mesh_envelope"}
ALLOWED_CONNECTOR_ROLES = {"bidirectional", "support", "supported", "source", "target"}
MAX_CONNECTORS = 128
CLEARANCE_SIDES = ("left", "right", "front", "rear", "top", "bottom")


def _mapping(value: Any) -> dict[str, Any]:
    if isinstance(value, Mapping):
        return dict(value)
    if isinstance(value, str) and value.strip():
        try:
            decoded = json.loads(value)
        except (TypeError, ValueError, json.JSONDecodeError):
            return {}
        return dict(decoded) if isinstance(decoded, Mapping) else {}
    return {}


def _number(
    value: Any,
    default: float,
    *,
    minimum: float | None = None,
    maximum: float | None = None,
) -> float:
    try:
        parsed = float(str(value).strip().replace(",", "."))
    except (TypeError, ValueError):
        parsed = float(default)
    if minimum is not None:
        parsed = max(minimum, parsed)
    if maximum is not None:
        parsed = min(maximum, parsed)
    return parsed


def _integer(value: Any, default: int, *, minimum: int = 1, maximum: int = 1000) -> int:
    try:
        parsed = int(round(float(str(value).strip().replace(",", "."))))
    except (TypeError, ValueError):
        parsed = int(default)
    return max(minimum, min(maximum, parsed))


def _token(value: Any, default: str, allowed: set[str] | None = None) -> str:
    token = re.sub(r"[^a-z0-9_]+", "_", str(value or "").strip().lower()).strip("_")
    if not token or (allowed is not None and token not in allowed):
        return default
    return token


def _text(value: Any, default: str = "", *, maximum: int = 240) -> str:
    return str(value or default).replace("\x00", "").strip()[:maximum]


def _boolean(value: Any, default: bool = False) -> bool:
    if isinstance(value, bool):
        return value
    if value is None:
        return default
    return str(value).strip().lower() in {"1", "true", "yes", "on", "ja"}


def _vector(value: Any, *, default: tuple[float, float, float]) -> dict[str, float]:
    source = _mapping(value)
    return {
        "x": _number(source.get("x"), default[0]),
        "y": _number(source.get("y"), default[1]),
        "z": _number(source.get("z"), default[2]),
    }


def _normalize_connector(value: Any, index: int, *, unit: str) -> dict[str, Any] | None:
    source = _mapping(value)
    if not source:
        return None
    label = _text(source.get("label"), f"Anschluss {index + 1}", maximum=160)
    connector_id = _token(source.get("connector_id") or source.get("id") or label, f"connector_{index + 1}")
    compatible_raw = source.get("compatible_types") or source.get("compatibleTypes") or []
    if isinstance(compatible_raw, str):
        compatible_raw = compatible_raw.split(",")
    compatible_types = []
    if isinstance(compatible_raw, (list, tuple, set)):
        for item in compatible_raw:
            token = _token(item, "")
            if token and token not in compatible_types:
                compatible_types.append(token)

    position = _vector(source.get("position"), default=(0.0, 0.0, 0.0))
    position["unit"] = unit
    normal = _vector(source.get("normal") or source.get("direction"), default=(0.0, 1.0, 0.0))
    if normal["x"] == normal["y"] == normal["z"] == 0:
        normal["y"] = 1.0

    return {
        "connector_id": connector_id,
        "label": label,
        "interface_type": _token(source.get("interface_type") or source.get("type"), "generic"),
        "role": _token(source.get("role"), "bidirectional", ALLOWED_CONNECTOR_ROLES),
        "coordinate_space": "local",
        "position": position,
        "normal": normal,
        "snap_radius": _number(source.get("snap_radius"), 0.05, minimum=0.0),
        "compatible_types": compatible_types[:64],
    }


def normalize_spatial_contract(
    payload: Mapping[str, Any],
    *,
    dimensions: Mapping[str, Any],
    cells: Mapping[str, Any],
    unit: str,
) -> dict[str, Any]:
    """Return a safe, versioned contract while keeping flat create fields compatible."""
    raw = _mapping(
        payload.get("spatial_contract")
        or payload.get("spatialContract")
        or payload.get("spatial_contract_json")
        or payload.get("spatialContractJson")
    )
    zone = _mapping(raw.get("zone"))
    raw_dimensions = _mapping(zone.get("dimensions"))
    grid = _mapping(zone.get("grid"))
    raw_cells = _mapping(grid.get("cells"))
    model_transform = _mapping(raw.get("model_transform") or raw.get("modelTransform"))
    raw_scale = _mapping(model_transform.get("scale_in_blocks") or model_transform.get("scaleInBlocks"))

    mode = _token(raw.get("mode") or payload.get("spatial_mode"), "contained", ALLOWED_SPATIAL_MODES)
    source_default = "manual_dimensions" if mode == "contained" else "primary_model_bounds"
    zone_source = _token(
        zone.get("source") or payload.get("zone_source"), source_default, ALLOWED_ZONE_SOURCES
    )
    zone_shape = _token(
        zone.get("shape") or payload.get("zone_shape"), "box", ALLOWED_ZONE_SHAPES
    )
    safe_unit = _text(zone.get("unit") or raw_dimensions.get("unit") or unit, unit, maximum=12)
    legacy_margin = _number(zone.get("margin", payload.get("zone_margin")), 0.0, minimum=0.0)
    raw_clearance = _mapping(zone.get("clearance"))
    clearance: dict[str, dict[str, Any]] = {}
    for side in CLEARANCE_SIDES:
        side_value = _mapping(raw_clearance.get(side))
        enabled = _boolean(
            side_value.get("enabled", payload.get(f"clearance_{side}_enabled")),
            default=legacy_margin > 0.0,
        )
        distance = _number(
            side_value.get("distance", payload.get(f"clearance_{side}", legacy_margin)),
            legacy_margin if enabled else 0.0,
            minimum=0.0,
        )
        clearance[side] = {
            "enabled": enabled,
            "distance": distance if enabled else 0.0,
            "unit": safe_unit,
        }
    maximum_clearance = max(
        (item["distance"] for item in clearance.values() if item["enabled"]),
        default=0.0,
    )

    normalized_dimensions = {
        "width": _number(raw_dimensions.get("width"), _number(dimensions.get("width"), 1.0, minimum=0.0001), minimum=0.0001),
        "height": _number(raw_dimensions.get("height"), _number(dimensions.get("height"), 1.0, minimum=0.0001), minimum=0.0001),
        "depth": _number(raw_dimensions.get("depth"), _number(dimensions.get("depth"), 1.0, minimum=0.0001), minimum=0.0001),
        "unit": safe_unit,
    }
    normalized_cells = {
        "x": _integer(raw_cells.get("x"), _integer(cells.get("x"), 1)),
        "y": _integer(raw_cells.get("y"), _integer(cells.get("y"), 1)),
        "z": _integer(raw_cells.get("z"), _integer(cells.get("z"), 1)),
    }
    cell_size = {
        "x": normalized_dimensions["width"] / normalized_cells["x"],
        "y": normalized_dimensions["height"] / normalized_cells["y"],
        "z": normalized_dimensions["depth"] / normalized_cells["z"],
        "unit": safe_unit,
    }
    scale_in_blocks = {
        "x": _number(raw_scale.get("x", payload.get("model_scale_x")), 1.0, minimum=0.1, maximum=32.0),
        "y": _number(raw_scale.get("y", payload.get("model_scale_y")), 1.0, minimum=0.1, maximum=32.0),
        "z": _number(raw_scale.get("z", payload.get("model_scale_z")), 1.0, minimum=0.1, maximum=32.0),
    }
    uniform_scale = _boolean(
        model_transform.get("uniform", payload.get("model_scale_uniform")),
        default=True,
    )
    if uniform_scale:
        scale_in_blocks["y"] = scale_in_blocks["x"]
        scale_in_blocks["z"] = scale_in_blocks["x"]

    if mode in {"asset_driven", "hybrid"} and not raw_dimensions:
        normalized_cells = {
            "x": max(1, math.ceil(scale_in_blocks["x"])),
            "y": max(1, math.ceil(scale_in_blocks["y"])),
            "z": max(1, math.ceil(scale_in_blocks["z"])),
        }
        normalized_dimensions = {
            "width": cell_size["x"] * normalized_cells["x"],
            "height": cell_size["y"] * normalized_cells["y"],
            "depth": cell_size["z"] * normalized_cells["z"],
            "unit": safe_unit,
        }

    raw_connectors = raw.get("connectors") or payload.get("connection_points") or payload.get("connection_points_json") or []
    if isinstance(raw_connectors, str):
        try:
            raw_connectors = json.loads(raw_connectors)
        except (TypeError, ValueError, json.JSONDecodeError):
            raw_connectors = []
    connectors: list[dict[str, Any]] = []
    if isinstance(raw_connectors, list):
        for index, item in enumerate(raw_connectors[:MAX_CONNECTORS]):
            connector = _normalize_connector(item, index, unit=safe_unit)
            if connector is not None:
                connectors.append(connector)

    return {
        "schema_version": SPATIAL_SCHEMA_VERSION,
        "mode": mode,
        "primary_asset_role": "embedded_geometry" if mode == "contained" else "zone_driver",
        "model_transform": {
            "unit_basis": "editor_cell",
            "uniform": uniform_scale,
            "scale_in_blocks": scale_in_blocks,
            "block_reference": cell_size,
            "resulting_size": {
                "x": cell_size["x"] * scale_in_blocks["x"],
                "y": cell_size["y"] * scale_in_blocks["y"],
                "z": cell_size["z"] * scale_in_blocks["z"],
                "unit": safe_unit,
            },
        },
        "zone": {
            "source": zone_source,
            "shape": zone_shape,
            "auto_fit": mode != "contained" and zone_source != "manual_dimensions",
            "margin": maximum_clearance,
            "clearance": clearance,
            "unit": safe_unit,
            "dimensions": normalized_dimensions,
            "grid": {
                "occupancy": "rectangular_span",
                "cells": normalized_cells,
                "cell_size": cell_size,
            },
        },
        "connectors": connectors,
    }


__all__ = ["SPATIAL_SCHEMA_VERSION", "normalize_spatial_contract"]
