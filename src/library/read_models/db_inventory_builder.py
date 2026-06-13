# services/vectoplan-library/src/library/read_models/db_inventory_builder.py
"""
DB-Inventory-Builder für die VECTOPLAN Creative Library.

Diese Datei baut API-nahe Inventar-Responses aus DB-/Repository-Daten.

Zielpfad:

    creative_library Tabellen
        → repository
        → library_published_service
        → db_inventory_builder
        → GET /api/v1/vplib/library/inventory
        → Editor / Creative Mode / Hotbar / Admin UI

Wichtig:

- keine Flask-Abhängigkeit
- keine SQLAlchemy-Session
- keine Datenbankzugriffe
- keine Schreiboperationen
- kein Filesystem-Scan
- keine Scanner-/Reader-/Validator-Imports
- tolerant gegenüber SQLAlchemy-Objekten, Dicts, Dataclasses und Domainmodellen
- kompatibel mit editornahen Slot-/Inventory-Responses
- primär auf veröffentlichte DB-Daten ausgelegt
- kann echte DB-Slots verwenden oder aus published Families fallbacken

Primäre technische Identität:

    vplib_uid

Semantische Identitäten:

    family_id
    package_id
    variant_id

Ein Inventarslot ist keine Projektinstanz. Er ist eine editornahe Auswahl aus
einer veröffentlichten Family und optional einer konkreten Variante.
"""

from __future__ import annotations

import json
from dataclasses import asdict, dataclass, field, is_dataclass
from datetime import datetime, timezone
from enum import Enum
from functools import lru_cache
from pathlib import Path
from typing import Any, Dict, Iterable, List, Mapping, Optional, Sequence, Tuple


# ---------------------------------------------------------------------------
# Domain imports
# ---------------------------------------------------------------------------

try:
    from ..domain.inventory import (
        DEFAULT_INVENTORY_MODE,
        DEFAULT_INVENTORY_SCOPE,
        DEFAULT_INVENTORY_SOURCE,
        InventoryAssetRef,
        InventoryMode,
        InventoryObjectKind,
        InventoryPlacementInfo,
        InventoryScope,
        InventorySlot,
        InventorySlotStatus,
        InventorySource,
        InventoryState,
        InventoryStats,
        InventoryVariantRef,
        build_empty_inventory_response,
        build_error_inventory_response,
        build_inventory_response,
        build_inventory_slot,
        build_inventory_slots,
        build_inventory_state,
        sort_inventory_slots,
    )
except Exception as import_error:  # pragma: no cover - defensive fallback
    DEFAULT_INVENTORY_MODE = "creative"
    DEFAULT_INVENTORY_SCOPE = "editor"
    DEFAULT_INVENTORY_SOURCE = "database"

    InventoryAssetRef = None  # type: ignore
    InventoryMode = None  # type: ignore
    InventoryObjectKind = None  # type: ignore
    InventoryPlacementInfo = None  # type: ignore
    InventoryScope = None  # type: ignore
    InventorySlot = None  # type: ignore
    InventorySlotStatus = None  # type: ignore
    InventorySource = None  # type: ignore
    InventoryState = None  # type: ignore
    InventoryStats = None  # type: ignore
    InventoryVariantRef = None  # type: ignore
    build_empty_inventory_response = None  # type: ignore
    build_error_inventory_response = None  # type: ignore
    build_inventory_response = None  # type: ignore
    build_inventory_slot = None  # type: ignore
    build_inventory_slots = None  # type: ignore
    build_inventory_state = None  # type: ignore
    sort_inventory_slots = None  # type: ignore
    _INVENTORY_IMPORT_ERROR = import_error
else:
    _INVENTORY_IMPORT_ERROR = None


try:
    from ..domain.publication import (
        DEFAULT_PUBLICATION_SOURCE,
        PublishedAssetRef,
        PublishedFamilySummary,
        PublishedVariantSummary,
    )
except Exception as import_error:  # pragma: no cover - defensive fallback
    DEFAULT_PUBLICATION_SOURCE = "database"

    PublishedAssetRef = None  # type: ignore
    PublishedFamilySummary = None  # type: ignore
    PublishedVariantSummary = None  # type: ignore
    _PUBLICATION_IMPORT_ERROR = import_error
else:
    _PUBLICATION_IMPORT_ERROR = None


# ---------------------------------------------------------------------------
# Metadata
# ---------------------------------------------------------------------------

DB_INVENTORY_BUILDER_NAME = "db_inventory_builder"
DB_INVENTORY_COMPONENT_NAME = "creative_library_db_inventory_builder"
DB_INVENTORY_API_VERSION = "v1"
DB_INVENTORY_MODEL_VERSION = "db-inventory.v1"

__version__ = "0.1.0"


# ---------------------------------------------------------------------------
# Defaults
# ---------------------------------------------------------------------------

DEFAULT_SOURCE = DEFAULT_INVENTORY_SOURCE or "database"
DEFAULT_SCOPE = DEFAULT_INVENTORY_SCOPE or "editor"
DEFAULT_MODE = DEFAULT_INVENTORY_MODE or "creative"

DEFAULT_SLOT_LIMIT = 512
DEFAULT_FALLBACK_SLOT_LIMIT = 512

DEFAULT_INCLUDE_PAYLOAD = True
DEFAULT_INCLUDE_METADATA = True
DEFAULT_INCLUDE_ASSETS = True
DEFAULT_INCLUDE_INACTIVE = False
DEFAULT_FALLBACK_FROM_PUBLISHED_FAMILIES = True

DEFAULT_EMPTY_SLOT_COUNT = 0
DEFAULT_VARIANT_STRATEGY = "slot_variant_or_family_default"


# ---------------------------------------------------------------------------
# Enums
# ---------------------------------------------------------------------------


class DbInventoryBuildStatus(str, Enum):
    """Status eines Inventory-Builds."""

    OK = "ok"
    EMPTY = "empty"
    PARTIAL = "partial"
    ERROR = "error"

    @classmethod
    def values(cls) -> Tuple[str, ...]:
        return tuple(item.value for item in cls)


class DbInventoryBuildSource(str, Enum):
    """Quelle, aus der der Inventory-Builder Slots erzeugt hat."""

    DB_SLOTS = "db_slots"
    PUBLISHED_FAMILIES = "published_families"
    MIXED = "mixed"
    EMPTY = "empty"
    ERROR = "error"

    @classmethod
    def values(cls) -> Tuple[str, ...]:
        return tuple(item.value for item in cls)


# ---------------------------------------------------------------------------
# Normalization helpers with caches
# ---------------------------------------------------------------------------


@lru_cache(maxsize=1024)
def normalize_slug(value: Any) -> Optional[str]:
    if value is None:
        return None

    text = str(value).strip()

    if not text:
        return None

    return (
        text.lower()
        .replace(" ", "_")
        .replace("-", "_")
        .replace("/", "_")
    )


@lru_cache(maxsize=1024)
def normalize_string_cached(value: Any) -> Optional[str]:
    if value is None:
        return None

    text = str(value).strip()
    return text or None


@lru_cache(maxsize=256)
def normalize_source(value: Any) -> str:
    text = str(value or "").strip().lower().replace("-", "_").replace(" ", "_")

    aliases = {
        "db": "database",
        "sql": "database",
        "postgres": "database",
        "postgresql": "database",
        "published": "published_families",
        "families": "published_families",
        "fallback": "published_families",
        "slots": "db_slots",
        "inventory_slots": "db_slots",
    }

    if text in aliases:
        return aliases[text]

    return text or DEFAULT_SOURCE


@lru_cache(maxsize=256)
def normalize_scope(value: Any) -> str:
    text = str(value or "").strip().lower().replace("-", "_").replace(" ", "_")

    aliases = {
        "creative": "creative_library",
        "library": "creative_library",
        "creative_mode": "creative_library",
        "hot_bar": "hotbar",
        "tools": "toolbar",
        "tool_bar": "toolbar",
    }

    if text in aliases:
        return aliases[text]

    return text or DEFAULT_SCOPE


@lru_cache(maxsize=256)
def normalize_mode(value: Any) -> str:
    text = str(value or "").strip().lower().replace("-", "_").replace(" ", "_")

    aliases = {
        "creative_mode": "creative",
        "builder": "build",
        "building": "build",
        "placement": "place",
        "placing": "place",
        "readonly": "readonly",
        "read_only": "readonly",
    }

    if text in aliases:
        return aliases[text]

    return text or DEFAULT_MODE


def clear_db_inventory_builder_caches() -> Dict[str, Any]:
    """Leert alle lokalen Caches dieses Builders."""

    normalize_slug.cache_clear()
    normalize_string_cached.cache_clear()
    normalize_source.cache_clear()
    normalize_scope.cache_clear()
    normalize_mode.cache_clear()

    return {
        "ok": True,
        "cleared": [
            "normalize_slug",
            "normalize_string_cached",
            "normalize_source",
            "normalize_scope",
            "normalize_mode",
        ],
    }


# ---------------------------------------------------------------------------
# Generic helpers
# ---------------------------------------------------------------------------


def utcnow() -> datetime:
    """Timezone-aware UTC timestamp."""

    return datetime.now(timezone.utc)


def safe_isoformat(value: Any) -> Optional[str]:
    if value is None:
        return None

    if isinstance(value, datetime):
        return value.isoformat()

    text = str(value).strip()
    return text or None


def safe_int(value: Any, default: int = 0) -> int:
    try:
        if value is None:
            return default
        return int(value)
    except Exception:
        return default


def safe_bool(value: Any, default: bool = False) -> bool:
    if value is None:
        return default

    if isinstance(value, bool):
        return value

    text = str(value).strip().lower()

    if text in {"1", "true", "yes", "y", "on", "active", "enabled", "published", "visible"}:
        return True

    if text in {"0", "false", "no", "n", "off", "inactive", "disabled", "deleted", "hidden"}:
        return False

    return default


def normalize_string(value: Any) -> Optional[str]:
    return normalize_string_cached(value)


def normalize_vplib_uid(value: Any) -> Optional[str]:
    text = normalize_string(value)
    return text.lower() if text else None


def normalize_taxonomy_path(
    domain: Any = None,
    category: Any = None,
    subcategory: Any = None,
) -> Optional[str]:
    parts = [
        normalize_slug(domain),
        normalize_slug(category),
        normalize_slug(subcategory),
    ]

    clean = [part for part in parts if part]

    if not clean:
        return None

    return "/".join(clean)


def first_non_empty(*values: Any) -> Any:
    for value in values:
        if value is None:
            continue

        if isinstance(value, str) and not value.strip():
            continue

        return value

    return None


def json_safe(value: Any) -> Any:
    """Konvertiert typische Python-Objekte in JSON-kompatible Strukturen."""

    if value is None:
        return None

    if is_dataclass(value):
        return json_safe(asdict(value))

    if isinstance(value, Mapping):
        return {str(key): json_safe(item) for key, item in value.items()}

    if isinstance(value, (list, tuple, set)):
        return [json_safe(item) for item in value]

    if isinstance(value, datetime):
        return value.isoformat()

    if isinstance(value, Path):
        return str(value)

    if isinstance(value, Enum):
        return value.value

    try:
        json.dumps(value)
        return value
    except TypeError:
        return str(value)


def to_mapping(value: Any) -> Dict[str, Any]:
    """
    Konvertiert Mapping, Dataclass, SQLAlchemy-Objekt oder Fremdobjekt in Dict.
    """

    if value is None:
        return {}

    if isinstance(value, Mapping):
        return dict(value)

    if is_dataclass(value):
        return dict(asdict(value))

    if hasattr(value, "to_dict") and callable(value.to_dict):
        try:
            result = value.to_dict()
            if isinstance(result, Mapping):
                return dict(result)
        except TypeError:
            try:
                result = value.to_dict(flat=True)
                if isinstance(result, Mapping):
                    return dict(result)
            except Exception:
                pass
        except Exception:
            pass

    table = getattr(value.__class__, "__table__", None)
    columns = getattr(table, "columns", None)

    if columns is not None:
        result: Dict[str, Any] = {}

        try:
            for column in columns:
                name = column.name
                try:
                    result[name] = getattr(value, name)
                except Exception:
                    continue
            return result
        except Exception:
            pass

    result = {}

    for name in dir(value):
        if name.startswith("_"):
            continue

        try:
            item = getattr(value, name)
        except Exception:
            continue

        if callable(item):
            continue

        result[name] = item

    return result


def listify(value: Any) -> List[Any]:
    if value is None:
        return []

    if isinstance(value, list):
        return value

    if isinstance(value, tuple):
        return list(value)

    if isinstance(value, set):
        return list(value)

    return [value]


def truncate_list(values: Sequence[Any], limit: int) -> List[Any]:
    if limit <= 0:
        return []

    return list(values[:limit])


def bounded_limit(value: Any, *, default: int = DEFAULT_SLOT_LIMIT, max_limit: int = DEFAULT_SLOT_LIMIT) -> int:
    limit = safe_int(value, default)

    if limit <= 0:
        return default

    return min(limit, max_limit)


def object_id(value: Any) -> Any:
    data = to_mapping(value)

    return first_non_empty(
        data.get("id"),
        data.get("pk"),
        data.get("uuid"),
        data.get("slot_id"),
    )


# ---------------------------------------------------------------------------
# Dataclasses
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class DbInventoryBuilderOptions:
    """Optionen für DB-Inventory-Building."""

    include_inactive: bool = DEFAULT_INCLUDE_INACTIVE
    include_payload: bool = DEFAULT_INCLUDE_PAYLOAD
    include_metadata: bool = DEFAULT_INCLUDE_METADATA
    include_assets: bool = DEFAULT_INCLUDE_ASSETS

    fallback_from_published_families: bool = DEFAULT_FALLBACK_FROM_PUBLISHED_FAMILIES
    empty_slot_count: int = DEFAULT_EMPTY_SLOT_COUNT

    slot_limit: int = DEFAULT_SLOT_LIMIT
    fallback_slot_limit: int = DEFAULT_FALLBACK_SLOT_LIMIT

    scope: str = DEFAULT_SCOPE
    mode: str = DEFAULT_MODE
    source: str = DEFAULT_SOURCE

    default_variant_strategy: str = DEFAULT_VARIANT_STRATEGY

    def normalized(self) -> "DbInventoryBuilderOptions":
        return DbInventoryBuilderOptions(
            include_inactive=bool(self.include_inactive),
            include_payload=bool(self.include_payload),
            include_metadata=bool(self.include_metadata),
            include_assets=bool(self.include_assets),
            fallback_from_published_families=bool(self.fallback_from_published_families),
            empty_slot_count=max(0, safe_int(self.empty_slot_count, DEFAULT_EMPTY_SLOT_COUNT)),
            slot_limit=max(0, bounded_limit(self.slot_limit, default=DEFAULT_SLOT_LIMIT, max_limit=DEFAULT_SLOT_LIMIT)),
            fallback_slot_limit=max(0, bounded_limit(self.fallback_slot_limit, default=DEFAULT_FALLBACK_SLOT_LIMIT, max_limit=DEFAULT_FALLBACK_SLOT_LIMIT)),
            scope=normalize_scope(self.scope),
            mode=normalize_mode(self.mode),
            source=normalize_source(self.source),
            default_variant_strategy=normalize_string(self.default_variant_strategy) or DEFAULT_VARIANT_STRATEGY,
        )


@dataclass
class DbInventorySourceBundle:
    """
    Bündelt mögliche Quellen für einen Inventory-Build.

    db_slots:
        Echte persistierte Inventory-Slots.

    published_families:
        Fallback-Quelle. Aus published Families werden Slots erzeugt.

    variants_by_family:
        Optionale Map für Variant-Referenzen:
            vplib_uid/family_id → [variants]

    assets_by_family:
        Optionale Map für Asset-Referenzen:
            vplib_uid/family_id → [assets]
    """

    db_slots: List[Any] = field(default_factory=list)
    published_families: List[Any] = field(default_factory=list)
    variants_by_family: Dict[str, List[Any]] = field(default_factory=dict)
    assets_by_family: Dict[str, List[Any]] = field(default_factory=dict)
    metadata: Dict[str, Any] = field(default_factory=dict)

    @classmethod
    def from_any(cls, value: Any) -> "DbInventorySourceBundle":
        if isinstance(value, cls):
            return value

        data = to_mapping(value)

        return cls(
            db_slots=listify(
                first_non_empty(
                    data.get("db_slots"),
                    data.get("slots"),
                    data.get("inventory_slots"),
                    [],
                )
            ),
            published_families=listify(
                first_non_empty(
                    data.get("published_families"),
                    data.get("families"),
                    data.get("items"),
                    [],
                )
            ),
            variants_by_family={
                str(key): listify(item)
                for key, item in dict(data.get("variants_by_family") or {}).items()
            },
            assets_by_family={
                str(key): listify(item)
                for key, item in dict(data.get("assets_by_family") or {}).items()
            },
            metadata=dict(data.get("metadata") or data.get("meta") or {}),
        )


@dataclass
class DbInventoryBuildResult:
    """Ergebnis eines Inventory-Builds."""

    ok: bool = True
    status: str = DbInventoryBuildStatus.OK.value
    build_source: str = DbInventoryBuildSource.EMPTY.value
    state: Any = None
    slots: List[Any] = field(default_factory=list)
    stats: Dict[str, Any] = field(default_factory=dict)
    filters: Dict[str, Any] = field(default_factory=dict)
    source: str = DEFAULT_SOURCE
    generated_at: datetime = field(default_factory=utcnow)
    warnings: List[Dict[str, Any]] = field(default_factory=list)
    errors: List[Dict[str, Any]] = field(default_factory=list)
    metadata: Dict[str, Any] = field(default_factory=dict)

    def to_dict(
        self,
        *,
        include_payload: bool = DEFAULT_INCLUDE_PAYLOAD,
        include_metadata: bool = DEFAULT_INCLUDE_METADATA,
        include_assets: bool = DEFAULT_INCLUDE_ASSETS,
        slot_limit: int = DEFAULT_SLOT_LIMIT,
    ) -> Dict[str, Any]:
        if self.state is not None and hasattr(self.state, "to_dict") and callable(self.state.to_dict):
            try:
                payload = self.state.to_dict(
                    include_payload=include_payload,
                    include_metadata=include_metadata,
                    include_assets=include_assets,
                    slot_limit=slot_limit,
                )
            except TypeError:
                payload = self.state.to_dict()
        else:
            payload = {
                "ok": self.ok,
                "status": self.status,
                "slots": [
                    slot_to_dict(
                        slot,
                        include_payload=include_payload,
                        include_metadata=include_metadata,
                        include_assets=include_assets,
                    )
                    for slot in truncate_list(self.slots, slot_limit)
                ],
                "count": min(len(self.slots), slot_limit),
                "total_count": len(self.slots),
                "stats": json_safe(self.stats),
            }

        payload.setdefault("ok", self.ok)
        payload.setdefault("status", self.status)
        payload.setdefault("build_source", self.build_source)
        payload.setdefault("source", self.source)
        payload.setdefault("filters", json_safe(self.filters))
        payload.setdefault("warnings", json_safe(self.warnings))
        payload.setdefault("errors", json_safe(self.errors))
        payload.setdefault("generated_at", safe_isoformat(self.generated_at))

        if include_metadata:
            payload.setdefault("metadata", json_safe(self.metadata))

        return payload


# ---------------------------------------------------------------------------
# Domain normalizers
# ---------------------------------------------------------------------------


def _require_inventory_domain() -> None:
    if _INVENTORY_IMPORT_ERROR is not None:
        raise RuntimeError(
            "Inventory domain models are not available: "
            f"{_INVENTORY_IMPORT_ERROR.__class__.__name__}: {_INVENTORY_IMPORT_ERROR}"
        )


def _publication_available() -> bool:
    return _PUBLICATION_IMPORT_ERROR is None and PublishedFamilySummary is not None


def normalize_inventory_asset(asset: Any) -> Any:
    """Normalisiert Asset in InventoryAssetRef."""

    _require_inventory_domain()

    if InventoryAssetRef is not None and isinstance(asset, InventoryAssetRef):
        return asset

    return InventoryAssetRef.from_mapping(asset)  # type: ignore[union-attr]


def normalize_inventory_variant(variant: Any) -> Any:
    """Normalisiert Variante in InventoryVariantRef."""

    _require_inventory_domain()

    if variant is None:
        return None

    if InventoryVariantRef is not None and isinstance(variant, InventoryVariantRef):
        return variant

    return InventoryVariantRef.from_mapping(variant)  # type: ignore[union-attr]


def normalize_inventory_slot(slot: Any, *, fallback_slot_index: int = 0) -> Any:
    """Normalisiert DB-/Repository-Slot in InventorySlot."""

    _require_inventory_domain()

    if InventorySlot is not None and isinstance(slot, InventorySlot):
        return slot

    return InventorySlot.from_mapping(slot, fallback_slot_index=fallback_slot_index)  # type: ignore[union-attr]


def normalize_published_family(family: Any) -> Any:
    """Normalisiert Family in PublishedFamilySummary, wenn Publication-Domain verfügbar ist."""

    if not _publication_available():
        return family

    if PublishedFamilySummary is not None and isinstance(family, PublishedFamilySummary):
        return family

    return PublishedFamilySummary.from_mapping(family)  # type: ignore[union-attr]


def family_key_candidates(family: Any) -> List[str]:
    """Ermittelt mögliche Keys für Varianten-/Asset-Maps."""

    data = to_mapping(family)

    keys = [
        data.get("vplib_uid"),
        data.get("family_id"),
        data.get("package_id"),
        data.get("id"),
        data.get("slug"),
        getattr(family, "vplib_uid", None),
        getattr(family, "family_id", None),
        getattr(family, "package_id", None),
        getattr(family, "id", None),
    ]

    result: List[str] = []

    for key in keys:
        text = normalize_string(key)
        if text and text not in result:
            result.append(text)

    return result


def find_related_items(
    family: Any,
    mapping: Mapping[str, List[Any]],
) -> List[Any]:
    """Findet Varianten/Assets anhand möglicher Family-Keys."""

    for key in family_key_candidates(family):
        if key in mapping:
            return list(mapping[key])

        lower_key = key.lower()
        if lower_key in mapping:
            return list(mapping[lower_key])

    return []


def find_default_variant(variants: Iterable[Any], *, default_variant_id: Optional[str] = None) -> Any:
    """Findet Default-Variante."""

    variant_items = list(variants)

    if not variant_items:
        return None

    if default_variant_id:
        for variant in variant_items:
            data = to_mapping(variant)
            variant_id = first_non_empty(
                data.get("variant_id"),
                data.get("id_in_family"),
                data.get("id"),
                getattr(variant, "variant_id", None),
            )

            if normalize_string(variant_id) == normalize_string(default_variant_id):
                return variant

    for variant in variant_items:
        data = to_mapping(variant)
        is_default = first_non_empty(
            data.get("is_default"),
            data.get("default"),
            getattr(variant, "is_default", None),
        )

        if safe_bool(is_default, False):
            return variant

    return variant_items[0]


def find_asset_by_role(assets: Iterable[Any], roles: Sequence[str]) -> Any:
    """Findet erstes Asset mit passender Rolle."""

    role_set = {str(role).strip().lower() for role in roles if str(role).strip()}

    for asset in assets:
        asset_data = to_mapping(asset)
        role = str(
            first_non_empty(
                asset_data.get("role"),
                getattr(asset, "role", None),
                "",
            )
        ).strip().lower()

        if role in role_set:
            return asset

    return None


# ---------------------------------------------------------------------------
# Slot builders
# ---------------------------------------------------------------------------


def build_slot_from_db_slot(
    db_slot: Any,
    *,
    fallback_slot_index: int = 0,
) -> Any:
    """Baut InventorySlot aus persistiertem DB-Slot."""

    return normalize_inventory_slot(
        db_slot,
        fallback_slot_index=fallback_slot_index,
    )


def build_slot_from_published_family(
    family: Any,
    *,
    slot_index: int,
    variants: Optional[Iterable[Any]] = None,
    assets: Optional[Iterable[Any]] = None,
    options: Optional[DbInventoryBuilderOptions] = None,
) -> Any:
    """Baut InventorySlot aus PublishedFamilySummary/Fallback-Family."""

    _require_inventory_domain()

    options = (options or DbInventoryBuilderOptions()).normalized()

    summary = normalize_published_family(family)
    summary_data = to_mapping(summary)

    variant_items = list(variants or [])
    asset_items = list(assets or [])

    default_variant_id = first_non_empty(
        summary_data.get("default_variant_id"),
        getattr(summary, "default_variant_id", None),
    )

    selected_variant = find_default_variant(
        variant_items,
        default_variant_id=normalize_string(default_variant_id),
    )

    icon_asset = find_asset_by_role(asset_items, ("icon",))
    preview_asset = find_asset_by_role(asset_items, ("preview", "thumbnail"))

    icon = normalize_inventory_asset(icon_asset) if icon_asset is not None else None
    preview = normalize_inventory_asset(preview_asset) if preview_asset is not None else None

    inventory_assets = [
        normalize_inventory_asset(asset)
        for asset in asset_items
    ]

    variant_ref = normalize_inventory_variant(selected_variant) if selected_variant is not None else None

    placement_payload = first_non_empty(
        summary_data.get("placement"),
        summary_data.get("placement_payload"),
        to_mapping(summary_data.get("payload")).get("placement") if isinstance(summary_data.get("payload"), Mapping) else None,
        {},
    )

    placement = InventoryPlacementInfo.from_mapping(placement_payload)  # type: ignore[union-attr]

    return InventorySlot(  # type: ignore[operator]
        slot_index=slot_index,
        slot_id=f"slot_{slot_index}",
        status="active",
        source=options.source,
        scope=options.scope,
        mode=options.mode,

        vplib_uid=first_non_empty(summary_data.get("vplib_uid"), getattr(summary, "vplib_uid", None)),
        family_id=first_non_empty(summary_data.get("family_id"), getattr(summary, "family_id", None)),
        package_id=first_non_empty(summary_data.get("package_id"), getattr(summary, "package_id", None)),
        variant_id=first_non_empty(
            getattr(variant_ref, "variant_id", None) if variant_ref else None,
            default_variant_id,
        ),

        label=first_non_empty(summary_data.get("label"), summary_data.get("name"), getattr(summary, "label", None)),
        description=first_non_empty(summary_data.get("description"), getattr(summary, "description", None)),
        family_slug=first_non_empty(summary_data.get("family_slug"), summary_data.get("slug"), getattr(summary, "family_slug", None)),
        object_kind=first_non_empty(summary_data.get("object_kind"), getattr(summary, "object_kind", None)),

        domain=first_non_empty(summary_data.get("domain"), getattr(summary, "domain", None)),
        category=first_non_empty(summary_data.get("category"), getattr(summary, "category", None)),
        subcategory=first_non_empty(summary_data.get("subcategory"), getattr(summary, "subcategory", None)),
        taxonomy_path=first_non_empty(summary_data.get("taxonomy_path"), getattr(summary, "taxonomy_path", None)),

        enabled=safe_bool(first_non_empty(summary_data.get("enabled"), getattr(summary, "enabled", True)), True),
        visible=safe_bool(first_non_empty(summary_data.get("visible"), getattr(summary, "visible", True)), True),
        active=safe_bool(first_non_empty(summary_data.get("is_published"), getattr(summary, "is_published", True)), True),
        locked=False,
        pinned=False,
        selected=False,
        sort_order=slot_index,

        icon=icon,
        preview=preview,
        assets=inventory_assets,
        variant=variant_ref,
        placement=placement,

        revision_hash=first_non_empty(summary_data.get("revision_hash"), getattr(summary, "revision_hash", None)),
        publication_status=first_non_empty(summary_data.get("publication_status"), getattr(summary, "publication_status", None)),
        validation_status=first_non_empty(
            to_mapping(summary_data.get("validation")).get("status"),
            getattr(getattr(summary, "validation", None), "status", None),
        ),

        published_at=first_non_empty(summary_data.get("published_at"), getattr(summary, "published_at", None)),
        updated_at=first_non_empty(summary_data.get("updated_at"), getattr(summary, "updated_at", None)),

        payload={
            "source_family": json_safe(summary_data),
            "variant_strategy": options.default_variant_strategy,
        },
        metadata={
            "builder": DB_INVENTORY_BUILDER_NAME,
            "build_source": DbInventoryBuildSource.PUBLISHED_FAMILIES.value,
        },
    )


def build_slots_from_db_slots(
    db_slots: Iterable[Any],
    *,
    options: Optional[DbInventoryBuilderOptions] = None,
) -> List[Any]:
    """Baut InventorySlots aus echten DB-Slots."""

    options = (options or DbInventoryBuilderOptions()).normalized()

    slots: List[Any] = []

    for index, db_slot in enumerate(truncate_list(list(db_slots), options.slot_limit)):
        slot = build_slot_from_db_slot(
            db_slot,
            fallback_slot_index=index,
        )

        if not options.include_inactive:
            if not getattr(slot, "active", True):
                continue

            if getattr(slot, "status", None) in {"inactive", "hidden", "disabled", "deleted"}:
                continue

        slots.append(slot)

    if callable(sort_inventory_slots):
        return sort_inventory_slots(slots)  # type: ignore[misc]

    return sorted(
        slots,
        key=lambda item: (
            safe_int(getattr(item, "slot_index", 0), 0),
            safe_int(getattr(item, "sort_order", 0), 0),
            str(getattr(item, "label", "") or ""),
        ),
    )


def build_slots_from_published_families(
    families: Iterable[Any],
    *,
    variants_by_family: Optional[Mapping[str, List[Any]]] = None,
    assets_by_family: Optional[Mapping[str, List[Any]]] = None,
    options: Optional[DbInventoryBuilderOptions] = None,
) -> List[Any]:
    """Baut Fallback-InventorySlots aus Published Families."""

    options = (options or DbInventoryBuilderOptions()).normalized()

    variants_map = dict(variants_by_family or {})
    assets_map = dict(assets_by_family or {})

    slots: List[Any] = []

    for index, family in enumerate(truncate_list(list(families), options.fallback_slot_limit)):
        variants = find_related_items(family, variants_map)
        assets = find_related_items(family, assets_map)

        slot = build_slot_from_published_family(
            family,
            slot_index=index,
            variants=variants,
            assets=assets,
            options=options,
        )

        if not options.include_inactive:
            if not getattr(slot, "active", True):
                continue

            if getattr(slot, "status", None) in {"inactive", "hidden", "disabled", "deleted"}:
                continue

        slots.append(slot)

    if callable(sort_inventory_slots):
        return sort_inventory_slots(slots)  # type: ignore[misc]

    return sorted(
        slots,
        key=lambda item: (
            safe_int(getattr(item, "slot_index", 0), 0),
            safe_int(getattr(item, "sort_order", 0), 0),
            str(getattr(item, "label", "") or ""),
        ),
    )


def build_empty_slots(
    *,
    count: int,
    options: Optional[DbInventoryBuilderOptions] = None,
) -> List[Any]:
    """Baut leere Slots."""

    _require_inventory_domain()

    options = (options or DbInventoryBuilderOptions()).normalized()

    slots = []

    for index in range(max(0, count)):
        if hasattr(InventorySlot, "empty"):
            slots.append(InventorySlot.empty(index, scope=options.scope))  # type: ignore[union-attr]
        else:
            slots.append(
                InventorySlot(  # type: ignore[operator]
                    slot_index=index,
                    slot_id=f"slot_{index}",
                    status="empty",
                    scope=options.scope,
                    mode=options.mode,
                    source=options.source,
                    active=False,
                    enabled=False,
                    visible=True,
                    label=f"Slot {index}",
                )
            )

    return slots


# ---------------------------------------------------------------------------
# State builders
# ---------------------------------------------------------------------------


def build_inventory_state_from_slots(
    slots: Iterable[Any],
    *,
    options: Optional[DbInventoryBuilderOptions] = None,
    filters: Optional[Mapping[str, Any]] = None,
    metadata: Optional[Mapping[str, Any]] = None,
) -> Any:
    """Baut InventoryState aus Slots."""

    _require_inventory_domain()

    options = (options or DbInventoryBuilderOptions()).normalized()
    slot_items = list(slots)

    if InventoryState is not None and hasattr(InventoryState, "from_slots"):
        return InventoryState.from_slots(  # type: ignore[union-attr]
            slot_items,
            scope=options.scope,
            mode=options.mode,
            source=options.source,
            filters=dict(filters or {}),
            metadata={
                **dict(metadata or {}),
                "builder": DB_INVENTORY_BUILDER_NAME,
            },
        )

    return InventoryState(  # type: ignore[operator]
        ok=True,
        status="ok" if slot_items else "empty",
        scope=options.scope,
        mode=options.mode,
        source=options.source,
        slots=slot_items,
        stats=InventoryStats.from_slots(slot_items),  # type: ignore[union-attr]
        filters=dict(filters or {}),
        metadata={
            **dict(metadata or {}),
            "builder": DB_INVENTORY_BUILDER_NAME,
        },
    )


def build_inventory_result_from_bundle(
    bundle: DbInventorySourceBundle,
    *,
    options: Optional[DbInventoryBuilderOptions] = None,
    filters: Optional[Mapping[str, Any]] = None,
    metadata: Optional[Mapping[str, Any]] = None,
) -> DbInventoryBuildResult:
    """Baut DbInventoryBuildResult aus SourceBundle."""

    options = (options or DbInventoryBuilderOptions()).normalized()

    slots: List[Any] = []
    build_source = DbInventoryBuildSource.EMPTY.value
    warnings: List[Dict[str, Any]] = []

    if bundle.db_slots:
        slots = build_slots_from_db_slots(
            bundle.db_slots,
            options=options,
        )
        build_source = DbInventoryBuildSource.DB_SLOTS.value

    if not slots and options.fallback_from_published_families and bundle.published_families:
        slots = build_slots_from_published_families(
            bundle.published_families,
            variants_by_family=bundle.variants_by_family,
            assets_by_family=bundle.assets_by_family,
            options=options,
        )
        build_source = DbInventoryBuildSource.PUBLISHED_FAMILIES.value

        warnings.append(
            {
                "code": "inventory.fallback_from_published_families",
                "message": "No persisted inventory slots found; built inventory from published families.",
            }
        )

    if not slots and options.empty_slot_count > 0:
        slots = build_empty_slots(
            count=options.empty_slot_count,
            options=options,
        )
        build_source = DbInventoryBuildSource.EMPTY.value

    state = build_inventory_state_from_slots(
        slots,
        options=options,
        filters=filters,
        metadata={
            **dict(metadata or {}),
            **bundle.metadata,
            "build_source": build_source,
        },
    )

    status = DbInventoryBuildStatus.OK.value if slots else DbInventoryBuildStatus.EMPTY.value

    return DbInventoryBuildResult(
        ok=True,
        status=status,
        build_source=build_source,
        state=state,
        slots=slots,
        stats=state.stats.to_dict() if hasattr(state, "stats") and hasattr(state.stats, "to_dict") else {},
        filters=dict(filters or {}),
        source=options.source,
        warnings=warnings,
        metadata={
            **dict(metadata or {}),
            **bundle.metadata,
        },
    )


def build_inventory_result_from_sources(
    *,
    db_slots: Optional[Iterable[Any]] = None,
    published_families: Optional[Iterable[Any]] = None,
    variants_by_family: Optional[Mapping[str, List[Any]]] = None,
    assets_by_family: Optional[Mapping[str, List[Any]]] = None,
    options: Optional[DbInventoryBuilderOptions] = None,
    filters: Optional[Mapping[str, Any]] = None,
    metadata: Optional[Mapping[str, Any]] = None,
) -> DbInventoryBuildResult:
    """Baut Inventory-Result aus getrennten Quellen."""

    bundle = DbInventorySourceBundle(
        db_slots=list(db_slots or []),
        published_families=list(published_families or []),
        variants_by_family={
            str(key): list(value)
            for key, value in dict(variants_by_family or {}).items()
        },
        assets_by_family={
            str(key): list(value)
            for key, value in dict(assets_by_family or {}).items()
        },
        metadata=dict(metadata or {}),
    )

    return build_inventory_result_from_bundle(
        bundle,
        options=options,
        filters=filters,
        metadata=metadata,
    )


# ---------------------------------------------------------------------------
# Response builders
# ---------------------------------------------------------------------------


def slot_to_dict(
    slot: Any,
    *,
    include_payload: bool = DEFAULT_INCLUDE_PAYLOAD,
    include_metadata: bool = DEFAULT_INCLUDE_METADATA,
    include_assets: bool = DEFAULT_INCLUDE_ASSETS,
) -> Dict[str, Any]:
    """Serialisiert Slot robust."""

    if hasattr(slot, "to_dict") and callable(slot.to_dict):
        try:
            return slot.to_dict(
                include_payload=include_payload,
                include_metadata=include_metadata,
                include_assets=include_assets,
            )
        except TypeError:
            try:
                return slot.to_dict()
            except Exception:
                pass

    return json_safe(to_mapping(slot))


def build_inventory_response_from_slots(
    slots: Iterable[Any],
    *,
    options: Optional[DbInventoryBuilderOptions] = None,
    filters: Optional[Mapping[str, Any]] = None,
    metadata: Optional[Mapping[str, Any]] = None,
) -> Dict[str, Any]:
    """API-kompatible Inventory-Response aus Slots."""

    options = (options or DbInventoryBuilderOptions()).normalized()

    state = build_inventory_state_from_slots(
        slots,
        options=options,
        filters=filters,
        metadata=metadata,
    )

    if hasattr(state, "to_dict") and callable(state.to_dict):
        return state.to_dict(
            include_payload=options.include_payload,
            include_metadata=options.include_metadata,
            include_assets=options.include_assets,
            slot_limit=options.slot_limit,
        )

    return json_safe(to_mapping(state))


def build_inventory_response_from_bundle(
    bundle: DbInventorySourceBundle,
    *,
    options: Optional[DbInventoryBuilderOptions] = None,
    filters: Optional[Mapping[str, Any]] = None,
    metadata: Optional[Mapping[str, Any]] = None,
) -> Dict[str, Any]:
    """API-kompatible Inventory-Response aus SourceBundle."""

    options = (options or DbInventoryBuilderOptions()).normalized()

    result = build_inventory_result_from_bundle(
        bundle,
        options=options,
        filters=filters,
        metadata=metadata,
    )

    return result.to_dict(
        include_payload=options.include_payload,
        include_metadata=options.include_metadata,
        include_assets=options.include_assets,
        slot_limit=options.slot_limit,
    )


def build_inventory_response_from_sources(
    *,
    db_slots: Optional[Iterable[Any]] = None,
    published_families: Optional[Iterable[Any]] = None,
    variants_by_family: Optional[Mapping[str, List[Any]]] = None,
    assets_by_family: Optional[Mapping[str, List[Any]]] = None,
    options: Optional[DbInventoryBuilderOptions] = None,
    filters: Optional[Mapping[str, Any]] = None,
    metadata: Optional[Mapping[str, Any]] = None,
) -> Dict[str, Any]:
    """API-kompatible Inventory-Response aus getrennten Quellen."""

    result = build_inventory_result_from_sources(
        db_slots=db_slots,
        published_families=published_families,
        variants_by_family=variants_by_family,
        assets_by_family=assets_by_family,
        options=options,
        filters=filters,
        metadata=metadata,
    )

    options = (options or DbInventoryBuilderOptions()).normalized()

    return result.to_dict(
        include_payload=options.include_payload,
        include_metadata=options.include_metadata,
        include_assets=options.include_assets,
        slot_limit=options.slot_limit,
    )


def build_empty_db_inventory_response(
    *,
    options: Optional[DbInventoryBuilderOptions] = None,
    metadata: Optional[Mapping[str, Any]] = None,
) -> Dict[str, Any]:
    """Leere Inventory-Response."""

    options = (options or DbInventoryBuilderOptions()).normalized()

    if callable(build_empty_inventory_response):
        response = build_empty_inventory_response(
            slot_count=options.empty_slot_count,
            scope=options.scope,
            mode=options.mode,
            source=options.source,
        )
        response.setdefault("metadata", json_safe(dict(metadata or {})))
        return response

    slots = build_empty_slots(
        count=options.empty_slot_count,
        options=options,
    )

    return build_inventory_response_from_slots(
        slots,
        options=options,
        metadata=metadata,
    )


def build_error_db_inventory_response(
    error: Any,
    *,
    message: Optional[str] = None,
    options: Optional[DbInventoryBuilderOptions] = None,
) -> Dict[str, Any]:
    """Fehlerhafte Inventory-Response."""

    options = (options or DbInventoryBuilderOptions()).normalized()

    if callable(build_error_inventory_response):
        return build_error_inventory_response(
            error,
            message=message,
        )

    return {
        "ok": False,
        "status": DbInventoryBuildStatus.ERROR.value,
        "message": message or str(error),
        "error_type": error.__class__.__name__ if error is not None else None,
        "slots": [],
        "count": 0,
        "stats": {},
        "source": options.source,
        "generated_at": safe_isoformat(utcnow()),
    }


# ---------------------------------------------------------------------------
# Options builders
# ---------------------------------------------------------------------------


def build_options_from_query(
    query: Optional[Mapping[str, Any]] = None,
    *,
    defaults: Optional[DbInventoryBuilderOptions] = None,
) -> DbInventoryBuilderOptions:
    """
    Baut Builder-Optionen aus Query-/Request-Parametern.

    Diese Funktion importiert kein Flask. Übergib request.args als Mapping.
    """

    data = dict(query or {})
    defaults = defaults or DbInventoryBuilderOptions()

    return DbInventoryBuilderOptions(
        include_inactive=safe_bool(
            first_non_empty(data.get("include_inactive"), data.get("inactive")),
            defaults.include_inactive,
        ),
        include_payload=safe_bool(
            first_non_empty(data.get("include_payload"), data.get("payload")),
            defaults.include_payload,
        ),
        include_metadata=safe_bool(
            first_non_empty(data.get("include_metadata"), data.get("metadata")),
            defaults.include_metadata,
        ),
        include_assets=safe_bool(
            first_non_empty(data.get("include_assets"), data.get("assets")),
            defaults.include_assets,
        ),
        fallback_from_published_families=safe_bool(
            first_non_empty(data.get("fallback_from_published_families"), data.get("fallback")),
            defaults.fallback_from_published_families,
        ),
        empty_slot_count=safe_int(
            first_non_empty(data.get("empty_slot_count"), data.get("empty_slots")),
            defaults.empty_slot_count,
        ),
        slot_limit=safe_int(
            first_non_empty(data.get("slot_limit"), data.get("limit")),
            defaults.slot_limit,
        ),
        fallback_slot_limit=safe_int(
            first_non_empty(data.get("fallback_slot_limit"), data.get("family_limit")),
            defaults.fallback_slot_limit,
        ),
        scope=first_non_empty(data.get("scope"), defaults.scope),
        mode=first_non_empty(data.get("mode"), defaults.mode),
        source=first_non_empty(data.get("source"), defaults.source),
        default_variant_strategy=first_non_empty(
            data.get("default_variant_strategy"),
            defaults.default_variant_strategy,
        ),
    ).normalized()


def build_filters_from_query(query: Optional[Mapping[str, Any]] = None) -> Dict[str, Any]:
    """Extrahiert fachliche Inventory-Filter aus Query-Mapping."""

    data = dict(query or {})

    return {
        "domain": normalize_slug(data.get("domain")),
        "category": normalize_slug(data.get("category")),
        "subcategory": normalize_slug(data.get("subcategory")),
        "object_kind": normalize_string(data.get("object_kind")),
        "q": normalize_string(first_non_empty(data.get("q"), data.get("search"))),
        "include_inactive": safe_bool(data.get("include_inactive"), DEFAULT_INCLUDE_INACTIVE),
    }


# ---------------------------------------------------------------------------
# Health
# ---------------------------------------------------------------------------


def get_db_inventory_builder_health() -> Dict[str, Any]:
    """Leichter Health-Check für diesen Builder."""

    return {
        "ok": _INVENTORY_IMPORT_ERROR is None,
        "status": "ok" if _INVENTORY_IMPORT_ERROR is None else "error",
        "component": DB_INVENTORY_COMPONENT_NAME,
        "builder": DB_INVENTORY_BUILDER_NAME,
        "api_version": DB_INVENTORY_API_VERSION,
        "model_version": DB_INVENTORY_MODEL_VERSION,
        "version": __version__,
        "inventory_domain_available": _INVENTORY_IMPORT_ERROR is None,
        "inventory_domain_error": None
        if _INVENTORY_IMPORT_ERROR is None
        else {
            "type": _INVENTORY_IMPORT_ERROR.__class__.__name__,
            "message": str(_INVENTORY_IMPORT_ERROR),
        },
        "publication_domain_available": _PUBLICATION_IMPORT_ERROR is None,
        "publication_domain_error": None
        if _PUBLICATION_IMPORT_ERROR is None
        else {
            "type": _PUBLICATION_IMPORT_ERROR.__class__.__name__,
            "message": str(_PUBLICATION_IMPORT_ERROR),
        },
        "defaults": {
            "source": DEFAULT_SOURCE,
            "scope": DEFAULT_SCOPE,
            "mode": DEFAULT_MODE,
            "slot_limit": DEFAULT_SLOT_LIMIT,
            "fallback_slot_limit": DEFAULT_FALLBACK_SLOT_LIMIT,
            "include_payload": DEFAULT_INCLUDE_PAYLOAD,
            "include_metadata": DEFAULT_INCLUDE_METADATA,
            "include_assets": DEFAULT_INCLUDE_ASSETS,
            "include_inactive": DEFAULT_INCLUDE_INACTIVE,
            "fallback_from_published_families": DEFAULT_FALLBACK_FROM_PUBLISHED_FAMILIES,
            "empty_slot_count": DEFAULT_EMPTY_SLOT_COUNT,
            "variant_strategy": DEFAULT_VARIANT_STRATEGY,
        },
        "enums": {
            "build_status": list(DbInventoryBuildStatus.values()),
            "build_source": list(DbInventoryBuildSource.values()),
        },
        "cache": {
            "normalize_slug": normalize_slug.cache_info()._asdict(),
            "normalize_string_cached": normalize_string_cached.cache_info()._asdict(),
            "normalize_source": normalize_source.cache_info()._asdict(),
            "normalize_scope": normalize_scope.cache_info()._asdict(),
            "normalize_mode": normalize_mode.cache_info()._asdict(),
        },
    }


def assert_db_inventory_builder_ready() -> Dict[str, Any]:
    """Wirft RuntimeError, wenn der Builder nicht bereit ist."""

    health = get_db_inventory_builder_health()

    if not health.get("ok"):
        raise RuntimeError(
            "DB inventory builder is not ready: "
            f"{health.get('inventory_domain_error')}"
        )

    return health


# ---------------------------------------------------------------------------
# Public exports
# ---------------------------------------------------------------------------

__all__ = [
    # Metadata
    "DB_INVENTORY_BUILDER_NAME",
    "DB_INVENTORY_COMPONENT_NAME",
    "DB_INVENTORY_API_VERSION",
    "DB_INVENTORY_MODEL_VERSION",

    # Defaults
    "DEFAULT_SOURCE",
    "DEFAULT_SCOPE",
    "DEFAULT_MODE",
    "DEFAULT_SLOT_LIMIT",
    "DEFAULT_FALLBACK_SLOT_LIMIT",
    "DEFAULT_INCLUDE_PAYLOAD",
    "DEFAULT_INCLUDE_METADATA",
    "DEFAULT_INCLUDE_ASSETS",
    "DEFAULT_INCLUDE_INACTIVE",
    "DEFAULT_FALLBACK_FROM_PUBLISHED_FAMILIES",
    "DEFAULT_EMPTY_SLOT_COUNT",
    "DEFAULT_VARIANT_STRATEGY",

    # Enums
    "DbInventoryBuildStatus",
    "DbInventoryBuildSource",

    # Options/models
    "DbInventoryBuilderOptions",
    "DbInventorySourceBundle",
    "DbInventoryBuildResult",

    # Generic helpers
    "utcnow",
    "safe_isoformat",
    "safe_int",
    "safe_bool",
    "normalize_slug",
    "normalize_string",
    "normalize_vplib_uid",
    "normalize_taxonomy_path",
    "normalize_source",
    "normalize_scope",
    "normalize_mode",
    "first_non_empty",
    "json_safe",
    "to_mapping",
    "listify",
    "truncate_list",
    "bounded_limit",
    "object_id",
    "clear_db_inventory_builder_caches",

    # Domain normalizers
    "normalize_inventory_asset",
    "normalize_inventory_variant",
    "normalize_inventory_slot",
    "normalize_published_family",
    "family_key_candidates",
    "find_related_items",
    "find_default_variant",
    "find_asset_by_role",

    # Slot builders
    "build_slot_from_db_slot",
    "build_slot_from_published_family",
    "build_slots_from_db_slots",
    "build_slots_from_published_families",
    "build_empty_slots",

    # State builders
    "build_inventory_state_from_slots",
    "build_inventory_result_from_bundle",
    "build_inventory_result_from_sources",

    # Response builders
    "slot_to_dict",
    "build_inventory_response_from_slots",
    "build_inventory_response_from_bundle",
    "build_inventory_response_from_sources",
    "build_empty_db_inventory_response",
    "build_error_db_inventory_response",

    # Query helpers
    "build_options_from_query",
    "build_filters_from_query",

    # Health
    "get_db_inventory_builder_health",
    "assert_db_inventory_builder_ready",
]