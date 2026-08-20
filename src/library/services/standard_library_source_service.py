"""Read-through overlay for the built-in VPLIB standard library.

The database remains the runtime index. This module makes the checked-in
standard library authoritative for its own families, so an application update
cannot expose stale variants while an existing index is being synchronized.
"""

from __future__ import annotations

import copy
import json
import os
from functools import lru_cache
from pathlib import Path
from typing import Any, Iterable, Mapping


def _mapping(value: Any) -> dict[str, Any]:
    return dict(value) if isinstance(value, Mapping) else {}


def _list(value: Any) -> list[Any]:
    return list(value) if isinstance(value, (list, tuple)) else []


def _text(value: Any) -> str:
    return str(value or "").strip()


def _json_file(path: Path) -> dict[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8-sig"))
    except (OSError, ValueError, TypeError):
        return {}
    return _mapping(value)


def standard_library_source_root() -> Path:
    """Return the configured packages root without importing Flask config."""
    configured = (
        os.getenv("VECTOPLAN_LIBRARY_SOURCE_ROOT")
        or os.getenv("VPLIB_CREATE_SOURCE_ROOT")
        or ""
    ).strip()
    if configured:
        return Path(configured).expanduser().resolve()
    return (
        Path(__file__).resolve().parents[3]
        / "standard_library"
        / "v1"
        / "packages"
    ).resolve()


def _catalog_token(catalog_path: Path) -> str:
    catalog = _json_file(catalog_path)
    revision = _text(catalog.get("content_revision"))
    if revision:
        return revision
    try:
        stat = catalog_path.stat()
    except OSError:
        return "missing"
    return f"legacy:{stat.st_mtime_ns}:{stat.st_size}"


def _safe_family_root(packages_root: Path, source_path: str) -> Path | None:
    if not source_path:
        return None
    candidate = (packages_root / source_path).resolve()
    try:
        candidate.relative_to(packages_root)
    except ValueError:
        return None
    return candidate


def _variant_id(value: Mapping[str, Any]) -> str:
    return _text(value.get("variant_id") or value.get("variantId") or value.get("variant_key"))


@lru_cache(maxsize=8)
def _load_source_items(packages_root_text: str, catalog_token: str) -> tuple[dict[str, Any], ...]:
    del catalog_token  # part of the cache key; content is read from disk below
    packages_root = Path(packages_root_text).resolve()
    catalog = _json_file(packages_root.parent / "catalog.json")
    content_revision = _text(catalog.get("content_revision"))
    items: list[dict[str, Any]] = []

    for catalog_family in _list(catalog.get("families")):
        family = _mapping(catalog_family)
        family_root = _safe_family_root(packages_root, _text(family.get("source_path")))
        if family_root is None:
            continue

        manifest = _json_file(family_root / "vplib.manifest.json")
        variant_index = _json_file(family_root / "variants" / "index.json")
        if not manifest or not variant_index:
            continue

        variants: list[dict[str, Any]] = []
        for indexed_variant in _list(variant_index.get("variants")):
            index_payload = _mapping(indexed_variant)
            variant_id = _variant_id(index_payload)
            if not variant_id or variant_id in {".", ".."} or "/" in variant_id or "\\" in variant_id:
                continue
            document = _json_file(family_root / "variants" / f"{variant_id}.json")
            if not document:
                continue
            merged_variant = dict(index_payload)
            merged_variant.update(document)
            variants.append(merged_variant)

        if not variants:
            continue

        vplib_uid = _text(manifest.get("vplib_uid") or family.get("vplib_uid"))
        family_id = _text(manifest.get("family_id") or family.get("family_id"))
        package_id = _text(manifest.get("package_id"))
        default_variant_id = _text(manifest.get("default_variant_id")) or _variant_id(variants[0])
        name = _text(manifest.get("family_name") or family.get("name") or family_id)
        domain = _text(manifest.get("domain") or family.get("domain"))
        category = _text(manifest.get("category") or family.get("category"))
        subcategory = _text(manifest.get("subcategory") or family.get("subcategory"))
        object_kind = _text(manifest.get("object_kind")) or "catalog_object"
        taxonomy_path = "/".join(part for part in (domain, category, subcategory) if part)
        source_metadata = {
            "built_in": True,
            "standard_library": True,
            "standard_library_content_revision": content_revision,
        }
        payload = {
            "vplib_uid": vplib_uid,
            "family_id": family_id,
            "package_id": package_id,
            "variant_id": default_variant_id,
            "label": name,
            "name": name,
            "description": _text(manifest.get("description")),
            "object_kind": object_kind,
            "domain": domain,
            "category": category,
            "subcategory": subcategory,
            "taxonomy_path": taxonomy_path,
            "source": "standard-library-v1",
            "source_scope": "system",
            "placeable": True,
            "metadata": source_metadata,
        }
        items.append(
            {
                **payload,
                "default_variant_id": default_variant_id,
                "publication_status": "published",
                "status": "published",
                "enabled": True,
                "active": True,
                "visible": True,
                "is_deleted": False,
                "payload": payload,
                "variants": variants,
                "assets": [],
                "metadata": source_metadata,
            }
        )

    return tuple(items)


def get_standard_library_source_items() -> list[dict[str, Any]]:
    """Load current built-ins and refresh automatically after a rebuild."""
    root = standard_library_source_root()
    catalog_path = root.parent / "catalog.json"
    return [
        copy.deepcopy(item)
        for item in _load_source_items(str(root), _catalog_token(catalog_path))
    ]


def _identity_candidates(item: Mapping[str, Any]) -> tuple[str, ...]:
    payload = _mapping(item.get("payload"))
    candidates: list[str] = []
    for value in (
        item.get("vplib_uid"),
        item.get("family_id"),
        item.get("package_id"),
        payload.get("vplib_uid"),
        payload.get("family_id"),
        payload.get("package_id"),
    ):
        text = _text(value)
        if text and text not in candidates:
            candidates.append(text)
    return tuple(candidates)


def _merge_variants(indexed: Iterable[Any], source: Iterable[Any]) -> list[dict[str, Any]]:
    existing = {
        _variant_id(_mapping(variant)): _mapping(variant)
        for variant in indexed
        if _variant_id(_mapping(variant))
    }
    merged: list[dict[str, Any]] = []
    for source_variant in source:
        current = _mapping(source_variant)
        variant_id = _variant_id(current)
        payload = dict(existing.get(variant_id, {}))
        payload.update(current)  # checked-in definition values are authoritative
        merged.append(payload)
    return merged


def overlay_standard_library_source_items(indexed_items: Iterable[Mapping[str, Any]]) -> list[dict[str, Any]]:
    """Overlay stale DB rows and append built-ins not indexed yet."""
    result = [dict(item) for item in indexed_items or ()]
    lookup: dict[str, int] = {}
    for index, item in enumerate(result):
        for identity in _identity_candidates(item):
            lookup.setdefault(identity, index)

    for source_item in get_standard_library_source_items():
        target_index = next(
            (lookup[identity] for identity in _identity_candidates(source_item) if identity in lookup),
            None,
        )
        if target_index is None:
            target_index = len(result)
            result.append(source_item)
            for identity in _identity_candidates(source_item):
                lookup[identity] = target_index
            continue

        indexed = result[target_index]
        merged = dict(indexed)
        for key in (
            "vplib_uid", "family_id", "package_id", "variant_id", "default_variant_id",
            "label", "name", "description", "object_kind", "domain", "category",
            "subcategory", "taxonomy_path", "source", "source_scope", "placeable",
        ):
            if source_item.get(key) not in (None, ""):
                merged[key] = source_item[key]
        merged["variants"] = _merge_variants(
            _list(indexed.get("variants")),
            _list(source_item.get("variants")),
        )
        merged_metadata = _mapping(indexed.get("metadata"))
        merged_metadata.update(_mapping(source_item.get("metadata")))
        merged["metadata"] = merged_metadata
        merged_payload = _mapping(indexed.get("payload"))
        merged_payload.update(_mapping(source_item.get("payload")))
        merged["payload"] = merged_payload
        result[target_index] = merged

    return result


def clear_standard_library_source_cache() -> None:
    _load_source_items.cache_clear()


__all__ = [
    "clear_standard_library_source_cache",
    "get_standard_library_source_items",
    "overlay_standard_library_source_items",
    "standard_library_source_root",
]
