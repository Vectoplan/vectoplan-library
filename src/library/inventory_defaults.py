"""Initial planning loadout and the shared inventory write policy."""
from typing import Any, Mapping

PLANNING_INVENTORY_KEY = "planning"
PLANNING_TOOLS = (
    ("selection", "Auswahl", "⌗"),
    ("room", "Linienbrush", "L"),
    ("storey", "Geschosse", "G"),
    ("roof", "Dach", "⌂"),
    ("tentacle", "Straße / Pfad", "∿"),
    ("parcel", "Grundstück", "⌖"),
    ("parcel-grid", "Grundstücksraster", "⋕"),
    ("stair", "Treppe", "▥"),
    ("ruler-laser", "Messen", "↔"),
)
READY_WORLD_EDIT_TOOLS = frozenset(tool[0] for tool in PLANNING_TOOLS) | {
    "paint", "sculpt", "copy-transform", "cut-transform",
}


def planning_default_item(slot_index: int) -> dict[str, Any]:
    tool, label, icon = PLANNING_TOOLS[slot_index - 1]
    return {
        "vplib_uid": f"vectoplan.world-edit.{tool}",
        "family_id": f"world-edit.{tool}", "package_id": "vectoplan.world-edit",
        "variant_id": tool, "label": label, "object_kind": "world_edit_tool",
        "world_edit_tool": tool, "domain": "world-edit", "category": "basic-tools",
        "quantity": 1, "source": "system", "scope": "editor", "mode": "creative",
        "icon": {"text": icon, "color": "#315fc4"},
        "placement": {"kind": "editor-tool", "tool": "world-edit", "toolId": tool,
                      "world_edit_tool": tool},
        "metadata": {"builtin": True, "ready": True, "world_edit_tool": tool},
    }


def is_world_edit_item(item: Mapping[str, Any]) -> bool:
    for source in (item, item.get("placement"), item.get("metadata")):
        if isinstance(source, Mapping):
            tool = source.get("world_edit_tool") or source.get("worldEditTool") or source.get("toolId")
            if tool in READY_WORLD_EDIT_TOOLS:
                return True
    family = str(item.get("family_id") or item.get("familyId") or "")
    return family.startswith("world-edit.") and family.removeprefix("world-edit.") in READY_WORLD_EDIT_TOOLS
