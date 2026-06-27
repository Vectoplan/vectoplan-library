# routes/inventar.py
from __future__ import annotations

from typing import Any

from flask import Blueprint, render_template


inventar_bp = Blueprint("inventar", __name__)


@inventar_bp.get("/user-inventar")
def user_inventar() -> Any:
    return render_template("inventar/user-inventar.html")


@inventar_bp.get("/creative-inventar")
def creative_inventar() -> Any:
    return render_template("inventar/creative-inventar.html")


__all__ = [
    "inventar_bp",
    "user_inventar",
    "creative_inventar",
]