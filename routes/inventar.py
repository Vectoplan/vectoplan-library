# routes/inventar.py
from __future__ import annotations

from typing import Any

from flask import Blueprint, render_template, request


inventar_bp = Blueprint("inventar", __name__)


@inventar_bp.get("/user-inventar")
def user_inventar() -> Any:
    return render_template("inventar/user-inventar.html", **_inventory_context())


@inventar_bp.get("/creative-inventar")
def creative_inventar() -> Any:
    return render_template("inventar/creative-inventar.html", **_inventory_context())


def _inventory_context() -> dict[str, Any]:
    planning = request.args.get("workspace_mode") == "planning" or request.args.get("inventory_key") == "planning"
    return {
        "user_id": request.args.get("user_id", 1, type=int),
        "inventory_key": "planning" if planning else request.args.get("inventory_key", "default"),
        "world_edit_only": planning,
    }


__all__ = [
    "inventar_bp",
    "user_inventar",
    "creative_inventar",
]
