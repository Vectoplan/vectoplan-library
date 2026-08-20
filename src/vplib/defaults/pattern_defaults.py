"""CAD hatch/pattern defaults for generated VPLIB packages.

The catalog contains renderer-neutral vector primitives.  Generated packages
only embed the patterns selected by their variants, so packages remain small
and self-contained while the central catalog can continue to grow.
"""

from __future__ import annotations

import json
import re
from functools import lru_cache
from pathlib import Path
from typing import Any, Final, Iterable, Mapping


CAD_PATTERNS_DOCUMENT_SCHEMA_VERSION: Final[str] = "vplib.render.cad_patterns.v1"
HATCH_PATTERN_CATALOG_SCHEMA_VERSION: Final[str] = "1.0"
DEFAULT_CUT_PATTERN_ID: Final[str] = "solid"
DEFAULT_SURFACE_PATTERN_ID: Final[str] = "none"
DEFAULT_PATTERN_SCALE: Final[float] = 1.0
DEFAULT_PATTERN_ROTATION_DEG: Final[float] = 0.0
DEFAULT_FOREGROUND_COLOR: Final[str] = "#202020"
DEFAULT_BACKGROUND_COLOR: Final[str] = "#FFFFFF"

CUT_PATTERN_KEY: Final[str] = "cad.cut_pattern_id"
SURFACE_PATTERN_KEY: Final[str] = "cad.surface_pattern_id"
PATTERN_SCALE_KEY: Final[str] = "cad.pattern_scale"
PATTERN_ROTATION_KEY: Final[str] = "cad.pattern_rotation_deg"
PATTERN_FOREGROUND_KEY: Final[str] = "cad.pattern_foreground_color"
PATTERN_BACKGROUND_KEY: Final[str] = "cad.pattern_background_color"

CAD_PATTERN_VALUE_KEYS: Final[tuple[str, ...]] = (
    CUT_PATTERN_KEY,
    SURFACE_PATTERN_KEY,
    PATTERN_SCALE_KEY,
    PATTERN_ROTATION_KEY,
    PATTERN_FOREGROUND_KEY,
    PATTERN_BACKGROUND_KEY,
)

_SAFE_ID_RE = re.compile(r"^[a-z][a-z0-9_]*$")
_HEX_COLOR_RE = re.compile(r"^#[0-9A-Fa-f]{6}$")


class PatternDefaultsError(ValueError):
    """Raised when a pattern catalog or assignment is invalid."""


def get_hatch_pattern_catalog_path() -> Path:
    return (
        Path(__file__).resolve().parents[2]
        / "library"
        / "definitions"
        / "data"
        / "hatch_patterns.v1.json"
    )


@lru_cache(maxsize=1)
def load_hatch_pattern_catalog() -> dict[str, Any]:
    path = get_hatch_pattern_catalog_path()
    try:
        payload = json.loads(path.read_text(encoding="utf-8-sig"))
    except Exception as exc:
        raise PatternDefaultsError(f"Could not load hatch pattern catalog {path}: {exc}") from exc

    if not isinstance(payload, Mapping):
        raise PatternDefaultsError("Hatch pattern catalog must be a JSON object.")
    if str(payload.get("schema_version") or "") != HATCH_PATTERN_CATALOG_SCHEMA_VERSION:
        raise PatternDefaultsError("Unsupported hatch pattern catalog schema_version.")
    items = payload.get("items")
    if not isinstance(items, list) or not items:
        raise PatternDefaultsError("Hatch pattern catalog requires a non-empty items array.")

    normalized_items: list[dict[str, Any]] = []
    seen: set[str] = set()
    for raw in items:
        if not isinstance(raw, Mapping):
            raise PatternDefaultsError("Each hatch pattern must be an object.")
        pattern_id = str(raw.get("id") or "").strip().lower()
        if not _SAFE_ID_RE.fullmatch(pattern_id):
            raise PatternDefaultsError(f"Unsafe hatch pattern id {pattern_id!r}.")
        if pattern_id in seen:
            raise PatternDefaultsError(f"Duplicate hatch pattern id {pattern_id!r}.")
        if not isinstance(raw.get("definition"), Mapping):
            raise PatternDefaultsError(f"Hatch pattern {pattern_id!r} has no definition.")
        seen.add(pattern_id)
        normalized_items.append(_json_safe(dict(raw)))

    if {DEFAULT_CUT_PATTERN_ID, DEFAULT_SURFACE_PATTERN_ID} - seen:
        raise PatternDefaultsError("Catalog is missing required default patterns.")

    return {
        **_json_safe(dict(payload)),
        "items": sorted(normalized_items, key=lambda item: (int(item.get("sort_order") or 0), item["id"])),
    }


def get_hatch_pattern_options() -> list[dict[str, Any]]:
    """Return compact frontend options without losing category information."""
    catalog = load_hatch_pattern_catalog()
    return [
        {
            "id": item["id"],
            "value": item["id"],
            "label": str(item.get("label") or item["id"]),
            "description": str(item.get("description") or ""),
            "category": str(item.get("category") or "other"),
            "category_label": str(item.get("category_label") or "Weitere"),
            "kind": str(item.get("kind") or "material"),
            "enabled": bool(item.get("active", True)),
            "sort_order": int(item.get("sort_order") or 0),
            "tags": list(item.get("tags") or []),
        }
        for item in catalog["items"]
        if bool(item.get("active", True))
    ]


def build_cad_patterns_document(
    variants: Iterable[Any],
    *,
    default_variant_id: str = "default",
    include_defaults: bool = True,
) -> dict[str, Any]:
    """Build the self-contained ``render/cad_patterns.json`` document."""
    catalog = load_hatch_pattern_catalog()
    by_id = {str(item["id"]): item for item in catalog["items"]}
    assignments: list[dict[str, Any]] = []
    selected_ids: set[str] = set()

    for index, raw_variant in enumerate(tuple(variants or ())):
        variant = _variant_mapping(raw_variant)
        variant_id = str(
            variant.get("variant_id")
            or variant.get("variantId")
            or variant.get("id")
            or (default_variant_id if index == 0 else f"variant_{index + 1}")
        ).strip()
        values = _variant_values(variant)
        has_explicit_pattern = any(key in values for key in CAD_PATTERN_VALUE_KEYS)
        if not include_defaults and not has_explicit_pattern:
            continue

        cut_pattern_id = _pattern_id(values.get(CUT_PATTERN_KEY), DEFAULT_CUT_PATTERN_ID, by_id)
        surface_pattern_id = _pattern_id(values.get(SURFACE_PATTERN_KEY), DEFAULT_SURFACE_PATTERN_ID, by_id)
        scale = _bounded_float(values.get(PATTERN_SCALE_KEY), DEFAULT_PATTERN_SCALE, 0.01, 1000.0, PATTERN_SCALE_KEY)
        rotation_deg = _bounded_float(
            values.get(PATTERN_ROTATION_KEY),
            DEFAULT_PATTERN_ROTATION_DEG,
            -360.0,
            360.0,
            PATTERN_ROTATION_KEY,
        )
        foreground = _color(values.get(PATTERN_FOREGROUND_KEY), DEFAULT_FOREGROUND_COLOR)
        background = _color(values.get(PATTERN_BACKGROUND_KEY), DEFAULT_BACKGROUND_COLOR)

        selected_ids.update((cut_pattern_id, surface_pattern_id))
        common = {
            "scale": scale,
            "rotation_deg": rotation_deg,
            "foreground_color": foreground,
            "background_color": background,
        }
        assignments.append(
            {
                "variant_id": variant_id,
                "cut": {"pattern_id": cut_pattern_id, **common},
                "surface": {"pattern_id": surface_pattern_id, **common},
            }
        )

    if not assignments:
        assignments.append(
            {
                "variant_id": default_variant_id or "default",
                "cut": {
                    "pattern_id": DEFAULT_CUT_PATTERN_ID,
                    "scale": DEFAULT_PATTERN_SCALE,
                    "rotation_deg": DEFAULT_PATTERN_ROTATION_DEG,
                    "foreground_color": DEFAULT_FOREGROUND_COLOR,
                    "background_color": DEFAULT_BACKGROUND_COLOR,
                },
                "surface": {
                    "pattern_id": DEFAULT_SURFACE_PATTERN_ID,
                    "scale": DEFAULT_PATTERN_SCALE,
                    "rotation_deg": DEFAULT_PATTERN_ROTATION_DEG,
                    "foreground_color": DEFAULT_FOREGROUND_COLOR,
                    "background_color": DEFAULT_BACKGROUND_COLOR,
                },
            }
        )
        selected_ids.update((DEFAULT_CUT_PATTERN_ID, DEFAULT_SURFACE_PATTERN_ID))

    document = {
        "schema_version": CAD_PATTERNS_DOCUMENT_SCHEMA_VERSION,
        "catalog_version": str(catalog.get("catalog_version") or "1.0.0"),
        "units": str(catalog.get("unit") or "mm_paper"),
        "default_variant_id": default_variant_id or assignments[0]["variant_id"],
        "pattern_ids": sorted(selected_ids),
        "patterns": [_json_safe(by_id[pattern_id]) for pattern_id in sorted(selected_ids)],
        "assignments": assignments,
    }
    valid, messages = validate_cad_patterns_document(document)
    if not valid:
        raise PatternDefaultsError(" ".join(messages))
    return document


def cad_pattern_document_from_create_request(request: Any) -> dict[str, Any]:
    normalized = request.normalized() if hasattr(request, "normalized") else request
    variants_container = getattr(normalized, "variants", None)
    if variants_container is not None and hasattr(variants_container, "normalized"):
        variants_container = variants_container.normalized()
    variants = getattr(variants_container, "variants", None)
    default_variant_id = getattr(variants_container, "default_variant_id", "default")
    if variants is None and isinstance(normalized, Mapping):
        raw_container = normalized.get("variants") or {}
        variants = raw_container.get("variants") if isinstance(raw_container, Mapping) else raw_container
        default_variant_id = (
            raw_container.get("default_variant_id", "default")
            if isinstance(raw_container, Mapping)
            else normalized.get("default_variant_id", "default")
        )
    return build_cad_patterns_document(
        variants or (),
        default_variant_id=str(default_variant_id or "default"),
    )


def validate_cad_patterns_document(document: Mapping[str, Any]) -> tuple[bool, tuple[str, ...]]:
    messages: list[str] = []
    if not isinstance(document, Mapping):
        return False, ("render/cad_patterns.json must be an object.",)
    if document.get("schema_version") != CAD_PATTERNS_DOCUMENT_SCHEMA_VERSION:
        messages.append("Invalid CAD patterns schema_version.")
    pattern_ids = document.get("pattern_ids")
    patterns = document.get("patterns")
    assignments = document.get("assignments")
    if not isinstance(pattern_ids, list) or not pattern_ids:
        messages.append("pattern_ids must be a non-empty array.")
    if not isinstance(patterns, list) or not patterns:
        messages.append("patterns must be a non-empty array.")
    embedded_ids = {
        str(item.get("id")) for item in patterns or () if isinstance(item, Mapping) and item.get("id")
    }
    if isinstance(pattern_ids, list) and set(map(str, pattern_ids)) != embedded_ids:
        messages.append("pattern_ids must match embedded patterns.")
    if not isinstance(assignments, list) or not assignments:
        messages.append("assignments must be a non-empty array.")
    else:
        seen_variants: set[str] = set()
        for assignment in assignments:
            if not isinstance(assignment, Mapping):
                messages.append("Each pattern assignment must be an object.")
                continue
            variant_id = str(assignment.get("variant_id") or "")
            if not variant_id or variant_id in seen_variants:
                messages.append("Pattern assignment variant_id values must be non-empty and unique.")
            seen_variants.add(variant_id)
            for mode in ("cut", "surface"):
                style = assignment.get(mode)
                if not isinstance(style, Mapping) or str(style.get("pattern_id") or "") not in embedded_ids:
                    messages.append(f"Assignment {variant_id!r} has an invalid {mode} pattern reference.")
    return not messages, tuple(messages)


def _variant_mapping(value: Any) -> dict[str, Any]:
    if isinstance(value, Mapping):
        return dict(value)
    if hasattr(value, "to_dict") and callable(value.to_dict):
        raw = value.to_dict()
        if isinstance(raw, Mapping):
            return dict(raw)
    result: dict[str, Any] = {}
    for key in ("variant_id", "variantId", "id", "overrides", "definition_values", "definitionValues"):
        if hasattr(value, key):
            result[key] = getattr(value, key)
    return result


def _variant_values(variant: Mapping[str, Any]) -> dict[str, Any]:
    for key in ("definition_values", "definitionValues", "overrides"):
        value = variant.get(key)
        if isinstance(value, Mapping):
            return dict(value)
    return {}


def _pattern_id(value: Any, default: str, by_id: Mapping[str, Any]) -> str:
    pattern_id = str(value or default).strip().lower()
    if pattern_id not in by_id:
        raise PatternDefaultsError(f"Unknown hatch pattern id {pattern_id!r}.")
    return pattern_id


def _bounded_float(value: Any, default: float, minimum: float, maximum: float, field_name: str) -> float:
    try:
        number = float(default if value in (None, "") else value)
    except (TypeError, ValueError) as exc:
        raise PatternDefaultsError(f"{field_name} must be a number.") from exc
    if number < minimum or number > maximum:
        raise PatternDefaultsError(f"{field_name} must be between {minimum} and {maximum}.")
    return number


def _color(value: Any, default: str) -> str:
    color = str(value or default).strip()
    if not _HEX_COLOR_RE.fullmatch(color):
        raise PatternDefaultsError(f"Invalid pattern color {color!r}.")
    return color.upper()


def _json_safe(value: Any) -> Any:
    if value is None or isinstance(value, (str, int, float, bool)):
        return value
    if isinstance(value, Mapping):
        return {str(key): _json_safe(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [_json_safe(item) for item in value]
    return str(value)


__all__ = [
    "CAD_PATTERNS_DOCUMENT_SCHEMA_VERSION",
    "CAD_PATTERN_VALUE_KEYS",
    "CUT_PATTERN_KEY",
    "DEFAULT_CUT_PATTERN_ID",
    "DEFAULT_SURFACE_PATTERN_ID",
    "PATTERN_BACKGROUND_KEY",
    "PATTERN_FOREGROUND_KEY",
    "PATTERN_ROTATION_KEY",
    "PATTERN_SCALE_KEY",
    "PatternDefaultsError",
    "SURFACE_PATTERN_KEY",
    "build_cad_patterns_document",
    "cad_pattern_document_from_create_request",
    "get_hatch_pattern_catalog_path",
    "get_hatch_pattern_options",
    "load_hatch_pattern_catalog",
    "validate_cad_patterns_document",
]
