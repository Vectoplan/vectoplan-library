# services/vectoplan-library/src/library/domain/inventory.py
"""
Domain-Modelle für den Creative-Library-Inventarzustand.

Diese Datei beschreibt die API-/Service-taugliche Inventarstruktur für:

    creative_library Tabellen
        → library_published_service / inventory builder
        → GET /api/v1/vplib/library/inventory
        → Editor / Creative Mode / Hotbar / Admin UI

Wichtig:

- keine Flask-Abhängigkeit
- keine SQLAlchemy-Abhängigkeit
- keine Repository-Imports
- keine Scanner-Imports
- keine Schreiboperationen
- robust serialisierbar
- tolerant gegenüber Dicts, Dataclasses, SQLAlchemy-Objekten und Fremdobjekten
- geeignet für Editor-State, Admin-UI, API-Responses und Tests

Primäre technische Identität:

    vplib_uid

Semantische Identitäten:

    family_id
    package_id
    variant_id

Ein Inventory Slot ist nicht die Family selbst, sondern eine editornahe Auswahl:

    slot_index
    → family / variant
    → Anzeigeinformationen
    → Placement-/Tool-Metadaten
    → optional Zustand wie locked, active, pinned

Die konkrete Platzierung im Projekt gehört weiterhin nicht der Library.
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
# Metadata
# ---------------------------------------------------------------------------

INVENTORY_COMPONENT_NAME = "creative_library_inventory"
INVENTORY_API_VERSION = "v1"
INVENTORY_MODEL_VERSION = "inventory.v1"

__version__ = "0.1.0"


# ---------------------------------------------------------------------------
# Defaults
# ---------------------------------------------------------------------------

DEFAULT_INVENTORY_SOURCE = "database"
DEFAULT_INVENTORY_SCOPE = "editor"
DEFAULT_INVENTORY_STATUS = "active"
DEFAULT_INVENTORY_MODE = "creative"
DEFAULT_SLOT_LIMIT = 512
DEFAULT_METADATA_LIMIT = 1000


# ---------------------------------------------------------------------------
# Enums
# ---------------------------------------------------------------------------


class InventorySlotStatus(str, Enum):
    """Status eines Inventarslots."""

    UNKNOWN = "unknown"
    ACTIVE = "active"
    INACTIVE = "inactive"
    EMPTY = "empty"
    HIDDEN = "hidden"
    DISABLED = "disabled"
    LOCKED = "locked"
    DELETED = "deleted"
    ERROR = "error"

    @classmethod
    def values(cls) -> Tuple[str, ...]:
        return tuple(item.value for item in cls)


class InventorySource(str, Enum):
    """Quelle des Inventarzustands."""

    UNKNOWN = "unknown"
    DATABASE = "database"
    FILESYSTEM = "filesystem"
    DEFAULTS = "defaults"
    USER = "user"
    ADMIN = "admin"
    SYNC = "sync"
    API = "api"

    @classmethod
    def values(cls) -> Tuple[str, ...]:
        return tuple(item.value for item in cls)


class InventoryScope(str, Enum):
    """Scope, für den das Inventar gedacht ist."""

    UNKNOWN = "unknown"
    EDITOR = "editor"
    ADMIN = "admin"
    CREATIVE_LIBRARY = "creative_library"
    HOTBAR = "hotbar"
    TOOLBAR = "toolbar"
    PROJECT = "project"
    USER = "user"
    GLOBAL = "global"

    @classmethod
    def values(cls) -> Tuple[str, ...]:
        return tuple(item.value for item in cls)


class InventoryMode(str, Enum):
    """Editor-/UI-Modus des Inventars."""

    UNKNOWN = "unknown"
    CREATIVE = "creative"
    BUILD = "build"
    PLACE = "place"
    INSPECT = "inspect"
    ADMIN = "admin"
    READONLY = "readonly"

    @classmethod
    def values(cls) -> Tuple[str, ...]:
        return tuple(item.value for item in cls)


class InventoryObjectKind(str, Enum):
    """Bekannte technische Object-Kinds im Inventory."""

    CELL_BLOCK = "cell_block"
    MULTI_CELL_MODULE = "multi_cell_module"
    CATALOG_OBJECT = "catalog_object"
    ADAPTIVE_SYSTEM = "adaptive_system"
    UNKNOWN = "unknown"

    @classmethod
    def values(cls) -> Tuple[str, ...]:
        return tuple(item.value for item in cls)


class InventoryAssetRole(str, Enum):
    """Asset-Rollen für Inventar-Darstellung."""

    ICON = "icon"
    PREVIEW = "preview"
    THUMBNAIL = "thumbnail"
    MODEL = "model"
    TEXTURE = "texture"
    OTHER = "other"

    @classmethod
    def values(cls) -> Tuple[str, ...]:
        return tuple(item.value for item in cls)


# ---------------------------------------------------------------------------
# Normalization helpers with caches
# ---------------------------------------------------------------------------


@lru_cache(maxsize=256)
def normalize_slot_status(value: Any) -> str:
    text = str(value or "").strip().lower().replace("-", "_").replace(" ", "_")

    aliases = {
        "enabled": InventorySlotStatus.ACTIVE.value,
        "visible": InventorySlotStatus.ACTIVE.value,
        "show": InventorySlotStatus.ACTIVE.value,
        "shown": InventorySlotStatus.ACTIVE.value,
        "available": InventorySlotStatus.ACTIVE.value,
        "off": InventorySlotStatus.INACTIVE.value,
        "disabled": InventorySlotStatus.DISABLED.value,
        "hide": InventorySlotStatus.HIDDEN.value,
        "invisible": InventorySlotStatus.HIDDEN.value,
        "removed": InventorySlotStatus.DELETED.value,
        "soft_deleted": InventorySlotStatus.DELETED.value,
        "fail": InventorySlotStatus.ERROR.value,
        "failed": InventorySlotStatus.ERROR.value,
    }

    if text in aliases:
        return aliases[text]

    if text in InventorySlotStatus.values():
        return text

    return InventorySlotStatus.UNKNOWN.value


@lru_cache(maxsize=256)
def normalize_inventory_source(value: Any) -> str:
    text = str(value or "").strip().lower().replace("-", "_").replace(" ", "_")

    aliases = {
        "db": InventorySource.DATABASE.value,
        "sql": InventorySource.DATABASE.value,
        "postgres": InventorySource.DATABASE.value,
        "postgresql": InventorySource.DATABASE.value,
        "fs": InventorySource.FILESYSTEM.value,
        "file": InventorySource.FILESYSTEM.value,
        "files": InventorySource.FILESYSTEM.value,
        "default": InventorySource.DEFAULTS.value,
        "system": InventorySource.DEFAULTS.value,
        "sync_run": InventorySource.SYNC.value,
    }

    if text in aliases:
        return aliases[text]

    if text in InventorySource.values():
        return text

    return InventorySource.UNKNOWN.value


@lru_cache(maxsize=256)
def normalize_inventory_scope(value: Any) -> str:
    text = str(value or "").strip().lower().replace("-", "_").replace(" ", "_")

    aliases = {
        "creative": InventoryScope.CREATIVE_LIBRARY.value,
        "library": InventoryScope.CREATIVE_LIBRARY.value,
        "creative": InventoryScope.CREATIVE_LIBRARY.value,
        "creative_mode": InventoryScope.CREATIVE_LIBRARY.value,
        "hot_bar": InventoryScope.HOTBAR.value,
        "tools": InventoryScope.TOOLBAR.value,
        "tool_bar": InventoryScope.TOOLBAR.value,
        "project_inventory": InventoryScope.PROJECT.value,
    }

    if text in aliases:
        return aliases[text]

    if text in InventoryScope.values():
        return text

    return InventoryScope.UNKNOWN.value


@lru_cache(maxsize=256)
def normalize_inventory_mode(value: Any) -> str:
    text = str(value or "").strip().lower().replace("-", "_").replace(" ", "_")

    aliases = {
        "creative_mode": InventoryMode.CREATIVE.value,
        "builder": InventoryMode.BUILD.value,
        "building": InventoryMode.BUILD.value,
        "placement": InventoryMode.PLACE.value,
        "placing": InventoryMode.PLACE.value,
        "readonly": InventoryMode.READONLY.value,
        "read_only": InventoryMode.READONLY.value,
    }

    if text in aliases:
        return aliases[text]

    if text in InventoryMode.values():
        return text

    return InventoryMode.UNKNOWN.value


@lru_cache(maxsize=256)
def normalize_object_kind(value: Any) -> str:
    text = str(value or "").strip().lower().replace("-", "_").replace(" ", "_")

    aliases = {
        "block": InventoryObjectKind.CELL_BLOCK.value,
        "cell": InventoryObjectKind.CELL_BLOCK.value,
        "cellblock": InventoryObjectKind.CELL_BLOCK.value,
        "multi_cell": InventoryObjectKind.MULTI_CELL_MODULE.value,
        "module": InventoryObjectKind.MULTI_CELL_MODULE.value,
        "object": InventoryObjectKind.CATALOG_OBJECT.value,
        "catalog": InventoryObjectKind.CATALOG_OBJECT.value,
        "catalogue_object": InventoryObjectKind.CATALOG_OBJECT.value,
        "adaptive": InventoryObjectKind.ADAPTIVE_SYSTEM.value,
        "system": InventoryObjectKind.ADAPTIVE_SYSTEM.value,
    }

    if text in aliases:
        return aliases[text]

    if text in InventoryObjectKind.values():
        return text

    return InventoryObjectKind.UNKNOWN.value


@lru_cache(maxsize=256)
def normalize_asset_role(value: Any) -> str:
    text = str(value or "").strip().lower().replace("-", "_").replace(" ", "_")

    aliases = {
        "image": InventoryAssetRole.PREVIEW.value,
        "thumb": InventoryAssetRole.THUMBNAIL.value,
        "thumbnail": InventoryAssetRole.THUMBNAIL.value,
        "glb": InventoryAssetRole.MODEL.value,
        "gltf": InventoryAssetRole.MODEL.value,
        "mesh": InventoryAssetRole.MODEL.value,
        "model_3d": InventoryAssetRole.MODEL.value,
        "material_texture": InventoryAssetRole.TEXTURE.value,
    }

    if text in aliases:
        return aliases[text]

    if text in InventoryAssetRole.values():
        return text

    return InventoryAssetRole.OTHER.value


def clear_inventory_caches() -> Dict[str, Any]:
    """Leert alle lokalen Normalisierungs-Caches dieser Datei."""

    normalize_slot_status.cache_clear()
    normalize_inventory_source.cache_clear()
    normalize_inventory_scope.cache_clear()
    normalize_inventory_mode.cache_clear()
    normalize_object_kind.cache_clear()
    normalize_asset_role.cache_clear()

    return {
        "ok": True,
        "cleared": [
            "normalize_slot_status",
            "normalize_inventory_source",
            "normalize_inventory_scope",
            "normalize_inventory_mode",
            "normalize_object_kind",
            "normalize_asset_role",
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

    if text in {"1", "true", "yes", "y", "on", "enabled", "active", "visible"}:
        return True

    if text in {"0", "false", "no", "n", "off", "disabled", "inactive", "hidden"}:
        return False

    return default


def normalize_string(value: Any) -> Optional[str]:
    if value is None:
        return None

    text = str(value).strip()
    return text or None


def normalize_slug(value: Any) -> Optional[str]:
    text = normalize_string(value)

    if not text:
        return None

    return (
        text.strip()
        .lower()
        .replace(" ", "_")
        .replace("-", "_")
        .replace("/", "_")
    )


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

    Diese Funktion ist defensiv und wirft nicht bei einzelnen kaputten
    Attributen.
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


def truncate_list(values: Sequence[Any], limit: int) -> List[Any]:
    if limit <= 0:
        return []

    return list(values[:limit])


def sort_inventory_slots(slots: Iterable["InventorySlot"]) -> List["InventorySlot"]:
    """Sortiert Slots stabil nach slot_index, sort_order und Label."""

    return sorted(
        list(slots),
        key=lambda item: (
            safe_int(item.slot_index, 0),
            safe_int(item.sort_order, 0),
            str(item.label or item.family_id or item.vplib_uid or ""),
        ),
    )


# ---------------------------------------------------------------------------
# Domain models
# ---------------------------------------------------------------------------


@dataclass
class InventoryAssetRef:
    """Asset-Referenz für Inventar-UI, z. B. Icon oder Preview."""

    role: str = InventoryAssetRole.OTHER.value
    path: Optional[str] = None
    relative_path: Optional[str] = None
    uri: Optional[str] = None
    label: Optional[str] = None
    mime_type: Optional[str] = None
    asset_type: Optional[str] = None
    checksum: Optional[str] = None
    size_bytes: Optional[int] = None
    payload: Dict[str, Any] = field(default_factory=dict)
    metadata: Dict[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        self.role = normalize_asset_role(self.role)
        self.path = normalize_string(self.path)
        self.relative_path = normalize_string(self.relative_path)
        self.uri = normalize_string(self.uri)
        self.label = normalize_string(self.label)
        self.mime_type = normalize_string(self.mime_type)
        self.asset_type = normalize_string(self.asset_type)
        self.checksum = normalize_string(self.checksum)
        self.size_bytes = safe_int(self.size_bytes, 0) if self.size_bytes is not None else None

    @classmethod
    def from_mapping(cls, value: Any) -> "InventoryAssetRef":
        data = to_mapping(value)

        return cls(
            role=data.get("role") or data.get("asset_role") or InventoryAssetRole.OTHER.value,
            path=data.get("path"),
            relative_path=data.get("relative_path"),
            uri=data.get("uri") or data.get("url"),
            label=data.get("label") or data.get("name"),
            mime_type=data.get("mime_type"),
            asset_type=data.get("asset_type") or data.get("type"),
            checksum=data.get("checksum") or data.get("sha256"),
            size_bytes=data.get("size_bytes"),
            payload=dict(data.get("payload") or {}),
            metadata=dict(data.get("metadata") or data.get("meta") or {}),
        )

    def to_dict(self) -> Dict[str, Any]:
        return {
            "role": self.role,
            "path": self.path,
            "relative_path": self.relative_path,
            "uri": self.uri,
            "label": self.label,
            "mime_type": self.mime_type,
            "asset_type": self.asset_type,
            "type": self.asset_type,
            "checksum": self.checksum,
            "size_bytes": self.size_bytes,
            "payload": json_safe(self.payload),
            "metadata": json_safe(self.metadata),
        }


@dataclass
class InventoryPlacementInfo:
    """Editornahe Placement-Informationen eines Inventareintrags."""

    placement_mode: Optional[str] = None
    tool: Optional[str] = None
    tool_mode: Optional[str] = None
    target: Optional[str] = None
    target_mode: Optional[str] = None
    grid_footprint: Dict[str, Any] = field(default_factory=dict)
    footprint: Dict[str, Any] = field(default_factory=dict)
    anchors: Dict[str, Any] = field(default_factory=dict)
    sockets: Dict[str, Any] = field(default_factory=dict)
    constraints: Dict[str, Any] = field(default_factory=dict)
    payload: Dict[str, Any] = field(default_factory=dict)

    @classmethod
    def from_mapping(cls, value: Any) -> "InventoryPlacementInfo":
        data = to_mapping(value)

        return cls(
            placement_mode=data.get("placement_mode") or data.get("mode"),
            tool=data.get("tool"),
            tool_mode=data.get("tool_mode"),
            target=data.get("target"),
            target_mode=data.get("target_mode"),
            grid_footprint=dict(data.get("grid_footprint") or data.get("grid") or {}),
            footprint=dict(data.get("footprint") or {}),
            anchors=dict(data.get("anchors") or {}),
            sockets=dict(data.get("sockets") or {}),
            constraints=dict(data.get("constraints") or {}),
            payload=dict(data.get("payload") or {}),
        )

    def to_dict(self) -> Dict[str, Any]:
        return {
            "placement_mode": self.placement_mode,
            "tool": self.tool,
            "tool_mode": self.tool_mode,
            "target": self.target,
            "target_mode": self.target_mode,
            "grid_footprint": json_safe(self.grid_footprint),
            "footprint": json_safe(self.footprint),
            "anchors": json_safe(self.anchors),
            "sockets": json_safe(self.sockets),
            "constraints": json_safe(self.constraints),
            "payload": json_safe(self.payload),
        }


@dataclass
class InventoryVariantRef:
    """Leichte Referenz auf eine Family-Variante im Inventory."""

    variant_id: Optional[str] = None
    label: Optional[str] = None
    description: Optional[str] = None
    is_default: bool = False
    enabled: bool = True
    visible: bool = True
    payload: Dict[str, Any] = field(default_factory=dict)
    resolved_payload: Dict[str, Any] = field(default_factory=dict)
    metadata: Dict[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        self.variant_id = normalize_string(self.variant_id)
        self.label = normalize_string(first_non_empty(self.label, self.variant_id))
        self.description = normalize_string(self.description)
        self.is_default = safe_bool(self.is_default, False)
        self.enabled = safe_bool(self.enabled, True)
        self.visible = safe_bool(self.visible, True)

    @classmethod
    def from_mapping(cls, value: Any) -> "InventoryVariantRef":
        data = to_mapping(value)
        variant_id = first_non_empty(data.get("variant_id"), data.get("id_in_family"), data.get("id"))

        return cls(
            variant_id=variant_id,
            label=data.get("label") or data.get("name") or variant_id,
            description=data.get("description"),
            is_default=data.get("is_default", data.get("default", False)),
            enabled=data.get("enabled", True),
            visible=data.get("visible", True),
            payload=dict(data.get("payload") or {}),
            resolved_payload=dict(data.get("resolved_payload") or data.get("resolved") or {}),
            metadata=dict(data.get("metadata") or data.get("meta") or {}),
        )

    def to_dict(self) -> Dict[str, Any]:
        return {
            "variant_id": self.variant_id,
            "label": self.label,
            "description": self.description,
            "is_default": self.is_default,
            "enabled": self.enabled,
            "visible": self.visible,
            "payload": json_safe(self.payload),
            "resolved_payload": json_safe(self.resolved_payload),
            "metadata": json_safe(self.metadata),
        }


@dataclass
class InventorySlot:
    """
    Einzelner Inventarslot für Editor / Creative Library / Hotbar.

    Der Slot referenziert eine veröffentlichte Family und optional eine konkrete
    Variante. Der Slot besitzt keine Projektinstanz.
    """

    slot_index: int = 0
    slot_id: Optional[str] = None
    status: str = InventorySlotStatus.ACTIVE.value
    source: str = InventorySource.DATABASE.value
    scope: str = InventoryScope.EDITOR.value
    mode: str = InventoryMode.CREATIVE.value

    vplib_uid: Optional[str] = None
    family_id: Optional[str] = None
    package_id: Optional[str] = None
    variant_id: Optional[str] = None

    label: Optional[str] = None
    description: Optional[str] = None
    family_slug: Optional[str] = None
    object_kind: str = InventoryObjectKind.UNKNOWN.value

    domain: Optional[str] = None
    category: Optional[str] = None
    subcategory: Optional[str] = None
    taxonomy_path: Optional[str] = None

    enabled: bool = True
    visible: bool = True
    active: bool = True
    locked: bool = False
    pinned: bool = False
    selected: bool = False
    sort_order: int = 0

    icon: Optional[InventoryAssetRef] = None
    preview: Optional[InventoryAssetRef] = None
    assets: List[InventoryAssetRef] = field(default_factory=list)
    variant: Optional[InventoryVariantRef] = None
    placement: InventoryPlacementInfo = field(default_factory=InventoryPlacementInfo)

    revision_hash: Optional[str] = None
    publication_status: Optional[str] = None
    validation_status: Optional[str] = None

    created_at: Optional[datetime] = None
    updated_at: Optional[datetime] = None
    published_at: Optional[datetime] = None
    selected_at: Optional[datetime] = None

    payload: Dict[str, Any] = field(default_factory=dict)
    metadata: Dict[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        self.slot_index = safe_int(self.slot_index, 0)
        self.slot_id = normalize_string(self.slot_id) or f"slot_{self.slot_index}"
        self.status = normalize_slot_status(self.status)
        self.source = normalize_inventory_source(self.source)
        self.scope = normalize_inventory_scope(self.scope)
        self.mode = normalize_inventory_mode(self.mode)

        self.vplib_uid = normalize_vplib_uid(self.vplib_uid)
        self.family_id = normalize_string(self.family_id)
        self.package_id = normalize_string(self.package_id)
        self.variant_id = normalize_string(self.variant_id)

        self.label = normalize_string(first_non_empty(self.label, self.family_id, self.vplib_uid))
        self.description = normalize_string(self.description)
        self.family_slug = normalize_slug(self.family_slug)
        self.object_kind = normalize_object_kind(self.object_kind)

        self.domain = normalize_slug(self.domain)
        self.category = normalize_slug(self.category)
        self.subcategory = normalize_slug(self.subcategory)
        self.taxonomy_path = self.taxonomy_path or normalize_taxonomy_path(
            self.domain,
            self.category,
            self.subcategory,
        )

        self.enabled = safe_bool(self.enabled, True)
        self.visible = safe_bool(self.visible, True)
        self.active = safe_bool(self.active, True)
        self.locked = safe_bool(self.locked, False)
        self.pinned = safe_bool(self.pinned, False)
        self.selected = safe_bool(self.selected, False)
        self.sort_order = safe_int(self.sort_order, self.slot_index)

        if self.icon is not None and not isinstance(self.icon, InventoryAssetRef):
            self.icon = InventoryAssetRef.from_mapping(self.icon)

        if self.preview is not None and not isinstance(self.preview, InventoryAssetRef):
            self.preview = InventoryAssetRef.from_mapping(self.preview)

        self.assets = [
            item if isinstance(item, InventoryAssetRef) else InventoryAssetRef.from_mapping(item)
            for item in self.assets
        ]

        if self.variant is not None and not isinstance(self.variant, InventoryVariantRef):
            self.variant = InventoryVariantRef.from_mapping(self.variant)

        if not isinstance(self.placement, InventoryPlacementInfo):
            self.placement = InventoryPlacementInfo.from_mapping(self.placement)

        if self.variant_id is None and self.variant is not None:
            self.variant_id = self.variant.variant_id

        self.revision_hash = normalize_string(self.revision_hash)
        self.publication_status = normalize_string(self.publication_status)
        self.validation_status = normalize_string(self.validation_status)

        if self.status in {
            InventorySlotStatus.INACTIVE.value,
            InventorySlotStatus.HIDDEN.value,
            InventorySlotStatus.DISABLED.value,
            InventorySlotStatus.DELETED.value,
        }:
            self.active = False

    @property
    def id(self) -> str:
        return self.slot_id or f"slot_{self.slot_index}"

    @property
    def is_empty(self) -> bool:
        return not any([self.vplib_uid, self.family_id, self.package_id])

    @property
    def is_usable(self) -> bool:
        return (
            not self.is_empty
            and self.status == InventorySlotStatus.ACTIVE.value
            and self.enabled
            and self.visible
            and self.active
        )

    @classmethod
    def from_mapping(cls, value: Any, *, fallback_slot_index: Optional[int] = None) -> "InventorySlot":
        data = to_mapping(value)

        payload = dict(data.get("payload") or {})
        metadata = dict(data.get("metadata") or data.get("meta") or {})

        icon_payload = first_non_empty(
            data.get("icon"),
            data.get("icon_asset"),
            metadata.get("icon") if isinstance(metadata, Mapping) else None,
            None,
        )

        preview_payload = first_non_empty(
            data.get("preview"),
            data.get("preview_asset"),
            metadata.get("preview") if isinstance(metadata, Mapping) else None,
            None,
        )

        raw_assets = data.get("assets") or metadata.get("assets") or []
        assets = [InventoryAssetRef.from_mapping(item) for item in raw_assets]

        if icon_payload is None:
            for asset in assets:
                if asset.role == InventoryAssetRole.ICON.value:
                    icon_payload = asset
                    break

        if preview_payload is None:
            for asset in assets:
                if asset.role in {InventoryAssetRole.PREVIEW.value, InventoryAssetRole.THUMBNAIL.value}:
                    preview_payload = asset
                    break

        variant_payload = first_non_empty(
            data.get("variant"),
            data.get("variant_ref"),
            data.get("selected_variant"),
            None,
        )

        placement_payload = first_non_empty(
            data.get("placement"),
            data.get("placement_payload"),
            payload.get("placement") if isinstance(payload, Mapping) else None,
            {},
        )

        slot_index = first_non_empty(
            data.get("slot_index"),
            data.get("index"),
            data.get("position"),
            fallback_slot_index,
            0,
        )

        domain = first_non_empty(data.get("domain"), data.get("domain_id"))
        category = first_non_empty(data.get("category"), data.get("category_id"))
        subcategory = first_non_empty(data.get("subcategory"), data.get("subcategory_id"))

        variant_id = first_non_empty(
            data.get("variant_id"),
            data.get("selected_variant_id"),
            to_mapping(variant_payload).get("variant_id") if variant_payload else None,
        )

        return cls(
            slot_index=safe_int(slot_index, 0),
            slot_id=data.get("slot_id") or data.get("id"),
            status=first_non_empty(data.get("status"), DEFAULT_INVENTORY_STATUS),
            source=first_non_empty(data.get("source"), DEFAULT_INVENTORY_SOURCE),
            scope=first_non_empty(data.get("scope"), DEFAULT_INVENTORY_SCOPE),
            mode=first_non_empty(data.get("mode"), DEFAULT_INVENTORY_MODE),

            vplib_uid=data.get("vplib_uid"),
            family_id=data.get("family_id"),
            package_id=data.get("package_id"),
            variant_id=variant_id,

            label=first_non_empty(data.get("label"), data.get("name")),
            description=data.get("description"),
            family_slug=first_non_empty(data.get("family_slug"), data.get("slug")),
            object_kind=data.get("object_kind"),

            domain=domain,
            category=category,
            subcategory=subcategory,
            taxonomy_path=first_non_empty(data.get("taxonomy_path"), data.get("classification_path")),

            enabled=data.get("enabled", True),
            visible=data.get("visible", True),
            active=data.get("active", True),
            locked=data.get("locked", False),
            pinned=data.get("pinned", False),
            selected=data.get("selected", False),
            sort_order=data.get("sort_order", slot_index),

            icon=InventoryAssetRef.from_mapping(icon_payload) if icon_payload else None,
            preview=InventoryAssetRef.from_mapping(preview_payload) if preview_payload else None,
            assets=assets,
            variant=InventoryVariantRef.from_mapping(variant_payload) if variant_payload else None,
            placement=InventoryPlacementInfo.from_mapping(placement_payload),

            revision_hash=data.get("revision_hash"),
            publication_status=first_non_empty(data.get("publication_status"), data.get("published_status")),
            validation_status=data.get("validation_status"),

            created_at=data.get("created_at"),
            updated_at=data.get("updated_at"),
            published_at=data.get("published_at"),
            selected_at=data.get("selected_at"),

            payload=payload,
            metadata=metadata,
        )

    @classmethod
    def empty(cls, slot_index: int, *, scope: str = DEFAULT_INVENTORY_SCOPE) -> "InventorySlot":
        return cls(
            slot_index=slot_index,
            slot_id=f"slot_{slot_index}",
            status=InventorySlotStatus.EMPTY.value,
            scope=scope,
            active=False,
            enabled=False,
            visible=True,
            label=f"Slot {slot_index}",
        )

    def to_dict(
        self,
        *,
        include_payload: bool = True,
        include_metadata: bool = True,
        include_assets: bool = True,
    ) -> Dict[str, Any]:
        return {
            "id": self.id,
            "slot_id": self.slot_id,
            "slot_index": self.slot_index,
            "status": self.status,
            "source": self.source,
            "scope": self.scope,
            "mode": self.mode,

            "vplib_uid": self.vplib_uid,
            "family_id": self.family_id,
            "package_id": self.package_id,
            "variant_id": self.variant_id,

            "label": self.label,
            "description": self.description,
            "family_slug": self.family_slug,
            "object_kind": self.object_kind,

            "domain": self.domain,
            "category": self.category,
            "subcategory": self.subcategory,
            "taxonomy_path": self.taxonomy_path,

            "enabled": self.enabled,
            "visible": self.visible,
            "active": self.active,
            "locked": self.locked,
            "pinned": self.pinned,
            "selected": self.selected,
            "sort_order": self.sort_order,
            "is_empty": self.is_empty,
            "is_usable": self.is_usable,

            "icon": self.icon.to_dict() if self.icon else None,
            "preview": self.preview.to_dict() if self.preview else None,
            "assets": [
                asset.to_dict()
                for asset in self.assets
            ] if include_assets else [],

            "variant": self.variant.to_dict() if self.variant else None,
            "placement": self.placement.to_dict(),

            "revision_hash": self.revision_hash,
            "publication_status": self.publication_status,
            "validation_status": self.validation_status,

            "created_at": safe_isoformat(self.created_at),
            "updated_at": safe_isoformat(self.updated_at),
            "published_at": safe_isoformat(self.published_at),
            "selected_at": safe_isoformat(self.selected_at),

            "payload": json_safe(self.payload) if include_payload else {},
            "metadata": json_safe(self.metadata) if include_metadata else {},
        }


@dataclass
class InventoryStats:
    """Aggregierte Zähler eines Inventarzustands."""

    total_slots: int = 0
    active_slots: int = 0
    empty_slots: int = 0
    hidden_slots: int = 0
    locked_slots: int = 0
    pinned_slots: int = 0
    selected_slots: int = 0
    usable_slots: int = 0
    family_count: int = 0
    variant_count: int = 0
    domain_count: int = 0
    category_count: int = 0
    subcategory_count: int = 0

    def __post_init__(self) -> None:
        for field_name in self.__dataclass_fields__:
            setattr(self, field_name, safe_int(getattr(self, field_name), 0))

    @classmethod
    def from_slots(cls, slots: Iterable[InventorySlot]) -> "InventoryStats":
        items = [
            item if isinstance(item, InventorySlot) else InventorySlot.from_mapping(item)
            for item in slots
        ]

        families = {item.vplib_uid or item.family_id for item in items if item.vplib_uid or item.family_id}
        variants = {
            (item.vplib_uid or item.family_id, item.variant_id)
            for item in items
            if (item.vplib_uid or item.family_id) and item.variant_id
        }
        domains = {item.domain for item in items if item.domain}
        categories = {(item.domain, item.category) for item in items if item.domain and item.category}
        subcategories = {
            (item.domain, item.category, item.subcategory)
            for item in items
            if item.domain and item.category and item.subcategory
        }

        return cls(
            total_slots=len(items),
            active_slots=sum(1 for item in items if item.active),
            empty_slots=sum(1 for item in items if item.is_empty),
            hidden_slots=sum(1 for item in items if not item.visible or item.status == InventorySlotStatus.HIDDEN.value),
            locked_slots=sum(1 for item in items if item.locked),
            pinned_slots=sum(1 for item in items if item.pinned),
            selected_slots=sum(1 for item in items if item.selected),
            usable_slots=sum(1 for item in items if item.is_usable),
            family_count=len(families),
            variant_count=len(variants),
            domain_count=len(domains),
            category_count=len(categories),
            subcategory_count=len(subcategories),
        )

    @classmethod
    def from_mapping(cls, value: Any) -> "InventoryStats":
        data = to_mapping(value)

        return cls(
            total_slots=data.get("total_slots", data.get("total", 0)),
            active_slots=data.get("active_slots", data.get("active", 0)),
            empty_slots=data.get("empty_slots", data.get("empty", 0)),
            hidden_slots=data.get("hidden_slots", data.get("hidden", 0)),
            locked_slots=data.get("locked_slots", data.get("locked", 0)),
            pinned_slots=data.get("pinned_slots", data.get("pinned", 0)),
            selected_slots=data.get("selected_slots", data.get("selected", 0)),
            usable_slots=data.get("usable_slots", data.get("usable", 0)),
            family_count=data.get("family_count", data.get("families", 0)),
            variant_count=data.get("variant_count", data.get("variants", 0)),
            domain_count=data.get("domain_count", data.get("domains", 0)),
            category_count=data.get("category_count", data.get("categories", 0)),
            subcategory_count=data.get("subcategory_count", data.get("subcategories", 0)),
        )

    def to_dict(self) -> Dict[str, int]:
        return {
            "total_slots": self.total_slots,
            "active_slots": self.active_slots,
            "empty_slots": self.empty_slots,
            "hidden_slots": self.hidden_slots,
            "locked_slots": self.locked_slots,
            "pinned_slots": self.pinned_slots,
            "selected_slots": self.selected_slots,
            "usable_slots": self.usable_slots,
            "family_count": self.family_count,
            "variant_count": self.variant_count,
            "domain_count": self.domain_count,
            "category_count": self.category_count,
            "subcategory_count": self.subcategory_count,
        }


@dataclass
class InventoryState:
    """
    Gesamter Inventarzustand für Editor/Admin/API.

    Primäre API-Antwort für:

        GET /api/v1/vplib/library/inventory
    """

    ok: bool = True
    status: str = "ok"
    scope: str = InventoryScope.EDITOR.value
    mode: str = InventoryMode.CREATIVE.value
    source: str = InventorySource.DATABASE.value
    slots: List[InventorySlot] = field(default_factory=list)
    stats: InventoryStats = field(default_factory=InventoryStats)
    active_slot_index: Optional[int] = None
    selected_slot_index: Optional[int] = None
    default_variant_strategy: str = "use_slot_variant_or_family_default"
    filters: Dict[str, Any] = field(default_factory=dict)
    generated_at: datetime = field(default_factory=utcnow)
    updated_at: Optional[datetime] = None
    metadata: Dict[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        self.scope = normalize_inventory_scope(self.scope)
        self.mode = normalize_inventory_mode(self.mode)
        self.source = normalize_inventory_source(self.source)

        self.slots = sort_inventory_slots(
            item if isinstance(item, InventorySlot) else InventorySlot.from_mapping(item, fallback_slot_index=index)
            for index, item in enumerate(self.slots)
        )

        if not isinstance(self.stats, InventoryStats):
            self.stats = InventoryStats.from_mapping(self.stats)

        if self.stats.total_slots == 0 and self.slots:
            self.stats = InventoryStats.from_slots(self.slots)

        if self.selected_slot_index is None:
            selected = next((slot.slot_index for slot in self.slots if slot.selected), None)
            self.selected_slot_index = selected

        if self.active_slot_index is None:
            active = next((slot.slot_index for slot in self.slots if slot.is_usable), None)
            self.active_slot_index = active

    @classmethod
    def from_mapping(cls, value: Any) -> "InventoryState":
        data = to_mapping(value)

        return cls(
            ok=safe_bool(data.get("ok"), True),
            status=data.get("status") or "ok",
            scope=data.get("scope") or DEFAULT_INVENTORY_SCOPE,
            mode=data.get("mode") or DEFAULT_INVENTORY_MODE,
            source=data.get("source") or DEFAULT_INVENTORY_SOURCE,
            slots=[
                InventorySlot.from_mapping(item, fallback_slot_index=index)
                for index, item in enumerate(data.get("slots", []) or data.get("items", []) or [])
            ],
            stats=InventoryStats.from_mapping(data.get("stats") or {}),
            active_slot_index=data.get("active_slot_index"),
            selected_slot_index=data.get("selected_slot_index"),
            default_variant_strategy=data.get("default_variant_strategy") or "use_slot_variant_or_family_default",
            filters=dict(data.get("filters") or {}),
            generated_at=data.get("generated_at") or utcnow(),
            updated_at=data.get("updated_at"),
            metadata=dict(data.get("metadata") or data.get("meta") or {}),
        )

    @classmethod
    def from_slots(
        cls,
        slots: Iterable[Any],
        *,
        scope: str = DEFAULT_INVENTORY_SCOPE,
        mode: str = DEFAULT_INVENTORY_MODE,
        source: str = DEFAULT_INVENTORY_SOURCE,
        filters: Optional[Mapping[str, Any]] = None,
        metadata: Optional[Mapping[str, Any]] = None,
    ) -> "InventoryState":
        slot_items = [
            item if isinstance(item, InventorySlot) else InventorySlot.from_mapping(item, fallback_slot_index=index)
            for index, item in enumerate(slots)
        ]

        return cls(
            ok=True,
            status="ok",
            scope=scope,
            mode=mode,
            source=source,
            slots=slot_items,
            stats=InventoryStats.from_slots(slot_items),
            filters=dict(filters or {}),
            metadata=dict(metadata or {}),
        )

    @classmethod
    def empty(
        cls,
        *,
        slot_count: int = 0,
        scope: str = DEFAULT_INVENTORY_SCOPE,
        mode: str = DEFAULT_INVENTORY_MODE,
        source: str = DEFAULT_INVENTORY_SOURCE,
    ) -> "InventoryState":
        slots = [
            InventorySlot.empty(index, scope=scope)
            for index in range(max(0, safe_int(slot_count, 0)))
        ]

        return cls(
            ok=True,
            status="empty",
            scope=scope,
            mode=mode,
            source=source,
            slots=slots,
            stats=InventoryStats.from_slots(slots),
        )

    def to_dict(
        self,
        *,
        include_payload: bool = True,
        include_metadata: bool = True,
        include_assets: bool = True,
        slot_limit: int = DEFAULT_SLOT_LIMIT,
    ) -> Dict[str, Any]:
        slots = truncate_list(self.slots, slot_limit)

        return {
            "ok": self.ok,
            "status": self.status,
            "scope": self.scope,
            "mode": self.mode,
            "source": self.source,
            "count": len(slots),
            "total_count": len(self.slots),
            "slots": [
                slot.to_dict(
                    include_payload=include_payload,
                    include_metadata=include_metadata,
                    include_assets=include_assets,
                )
                for slot in slots
            ],
            "slots_truncated": len(self.slots) > slot_limit,
            "stats": self.stats.to_dict(),
            "active_slot_index": self.active_slot_index,
            "selected_slot_index": self.selected_slot_index,
            "default_variant_strategy": self.default_variant_strategy,
            "filters": json_safe(self.filters),
            "generated_at": safe_isoformat(self.generated_at),
            "updated_at": safe_isoformat(self.updated_at),
            "metadata": json_safe(self.metadata) if include_metadata else {},
        }


# ---------------------------------------------------------------------------
# Builders / response helpers
# ---------------------------------------------------------------------------


def build_inventory_slot(value: Any, *, fallback_slot_index: Optional[int] = None) -> InventorySlot:
    return (
        value
        if isinstance(value, InventorySlot)
        else InventorySlot.from_mapping(value, fallback_slot_index=fallback_slot_index)
    )


def build_inventory_slots(values: Iterable[Any]) -> List[InventorySlot]:
    return sort_inventory_slots(
        build_inventory_slot(value, fallback_slot_index=index)
        for index, value in enumerate(values)
    )


def build_inventory_state(
    slots: Iterable[Any],
    *,
    scope: str = DEFAULT_INVENTORY_SCOPE,
    mode: str = DEFAULT_INVENTORY_MODE,
    source: str = DEFAULT_INVENTORY_SOURCE,
    filters: Optional[Mapping[str, Any]] = None,
    metadata: Optional[Mapping[str, Any]] = None,
) -> InventoryState:
    return InventoryState.from_slots(
        slots,
        scope=scope,
        mode=mode,
        source=source,
        filters=filters,
        metadata=metadata,
    )


def build_inventory_response(
    state: Any,
    *,
    include_payload: bool = True,
    include_metadata: bool = True,
    include_assets: bool = True,
) -> Dict[str, Any]:
    inventory_state = state if isinstance(state, InventoryState) else InventoryState.from_mapping(state)

    return inventory_state.to_dict(
        include_payload=include_payload,
        include_metadata=include_metadata,
        include_assets=include_assets,
    )


def build_empty_inventory_response(
    *,
    slot_count: int = 0,
    scope: str = DEFAULT_INVENTORY_SCOPE,
    mode: str = DEFAULT_INVENTORY_MODE,
    source: str = DEFAULT_INVENTORY_SOURCE,
) -> Dict[str, Any]:
    return InventoryState.empty(
        slot_count=slot_count,
        scope=scope,
        mode=mode,
        source=source,
    ).to_dict()


def build_error_inventory_response(
    error: Any,
    *,
    message: Optional[str] = None,
) -> Dict[str, Any]:
    return {
        "ok": False,
        "status": "error",
        "message": message or str(error),
        "error_type": error.__class__.__name__ if error is not None else None,
        "slots": [],
        "count": 0,
        "stats": InventoryStats().to_dict(),
        "generated_at": safe_isoformat(utcnow()),
    }


def select_inventory_slot(
    state: InventoryState,
    slot_index: int,
    *,
    clear_previous: bool = True,
) -> InventoryState:
    """
    Markiert einen Slot als ausgewählt.

    Diese Funktion verändert nur das in-memory Domain-Modell. Persistenz gehört
    später in Repository/Service.
    """

    target_index = safe_int(slot_index, 0)

    for slot in state.slots:
        if clear_previous:
            slot.selected = False

        if slot.slot_index == target_index:
            slot.selected = True
            slot.selected_at = utcnow()
            state.selected_slot_index = target_index

    state.updated_at = utcnow()
    state.stats = InventoryStats.from_slots(state.slots)
    return state


# ---------------------------------------------------------------------------
# Health
# ---------------------------------------------------------------------------


def get_inventory_health() -> Dict[str, Any]:
    """Leichter Health-Check für die Inventory-Domain-Datei."""

    return {
        "ok": True,
        "status": "ok",
        "component": INVENTORY_COMPONENT_NAME,
        "api_version": INVENTORY_API_VERSION,
        "model_version": INVENTORY_MODEL_VERSION,
        "version": __version__,
        "enums": {
            "slot_status": list(InventorySlotStatus.values()),
            "source": list(InventorySource.values()),
            "scope": list(InventoryScope.values()),
            "mode": list(InventoryMode.values()),
            "object_kind": list(InventoryObjectKind.values()),
            "asset_role": list(InventoryAssetRole.values()),
        },
        "cache": {
            "normalize_slot_status": normalize_slot_status.cache_info()._asdict(),
            "normalize_inventory_source": normalize_inventory_source.cache_info()._asdict(),
            "normalize_inventory_scope": normalize_inventory_scope.cache_info()._asdict(),
            "normalize_inventory_mode": normalize_inventory_mode.cache_info()._asdict(),
            "normalize_object_kind": normalize_object_kind.cache_info()._asdict(),
            "normalize_asset_role": normalize_asset_role.cache_info()._asdict(),
        },
    }


def assert_inventory_ready() -> Dict[str, Any]:
    health = get_inventory_health()

    if not health.get("ok"):
        raise RuntimeError("Inventory domain models are not ready.")

    return health


# ---------------------------------------------------------------------------
# Public exports
# ---------------------------------------------------------------------------

__all__ = [
    # Metadata
    "INVENTORY_COMPONENT_NAME",
    "INVENTORY_API_VERSION",
    "INVENTORY_MODEL_VERSION",
    "DEFAULT_INVENTORY_SOURCE",
    "DEFAULT_INVENTORY_SCOPE",
    "DEFAULT_INVENTORY_STATUS",
    "DEFAULT_INVENTORY_MODE",

    # Enums
    "InventorySlotStatus",
    "InventorySource",
    "InventoryScope",
    "InventoryMode",
    "InventoryObjectKind",
    "InventoryAssetRole",

    # Helpers
    "utcnow",
    "safe_isoformat",
    "safe_int",
    "safe_bool",
    "normalize_string",
    "normalize_slug",
    "normalize_vplib_uid",
    "normalize_taxonomy_path",
    "normalize_slot_status",
    "normalize_inventory_source",
    "normalize_inventory_scope",
    "normalize_inventory_mode",
    "normalize_object_kind",
    "normalize_asset_role",
    "clear_inventory_caches",
    "json_safe",
    "to_mapping",
    "first_non_empty",
    "sort_inventory_slots",

    # Models
    "InventoryAssetRef",
    "InventoryPlacementInfo",
    "InventoryVariantRef",
    "InventorySlot",
    "InventoryStats",
    "InventoryState",

    # Builders
    "build_inventory_slot",
    "build_inventory_slots",
    "build_inventory_state",
    "build_inventory_response",
    "build_empty_inventory_response",
    "build_error_inventory_response",
    "select_inventory_slot",

    # Health
    "get_inventory_health",
    "assert_inventory_ready",
]