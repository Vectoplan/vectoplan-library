# services/vectoplan-library/models/user_inventory.py
"""
User inventory database models for vectoplan-library.

Diese Datei enthält die PostgreSQL-/SQLAlchemy-Modelle für das persistierte
User-Inventar.

Ziel:

    Editor / Viewport
        -> User hotbar overlay
        -> JS slot navigation
        -> Inventar-API
        -> UserInventoryService
        -> UserInventoryRepository
        -> PostgreSQL

Wichtig:

- Dieses Model ist bewusst getrennt von CreativeLibraryInventorySlot.
- CreativeLibraryInventorySlot beschreibt ein Library-/Default-Inventar.
- UserInventoryState und UserInventorySlot beschreiben den persistierten Zustand
  eines konkreten Users.
- Für Phase 1 wird user_id standardmäßig auf 1 gesetzt.
- Es gibt genau 9 Hotbar-Slots.
- Der aktuell ausgewählte Slot wird in UserInventoryState gespeichert.
- Der Inhalt der Slots wird in UserInventorySlot gespeichert.
- Creative-Library-Collections und CollectionItems werden nur referenziert.
- User-spezifische Bibliothekslogik liegt in creative_library_user.py.
- Published Creative-Library-Items bleiben in creative_library.py.
- Keine Route.
- Kein db.create_all().
- Keine aktive DB-Verbindung.
- Keine Migration.
- Keine Seed-Logik.

Technische Namen, JSON-Keys und Variablen bleiben Englisch.
"""

from __future__ import annotations

import enum
import hashlib
import json
import uuid
from datetime import datetime, timezone
from functools import lru_cache
from typing import Any, Final, Iterable, Mapping


# ---------------------------------------------------------------------------
# Metadata / constants
# ---------------------------------------------------------------------------

USER_INVENTORY_MODELS_SCHEMA_VERSION: Final[str] = "vectoplan_library.user_inventory.models.v2"

DEFAULT_USER_ID: Final[int] = 1
DEFAULT_INVENTORY_KEY: Final[str] = "default"
DEFAULT_SLOT_COUNT: Final[int] = 9
MIN_SLOT_INDEX: Final[int] = 1
MAX_SLOT_INDEX: Final[int] = 9

MAX_UID_LENGTH: Final[int] = 80
MAX_KEY_LENGTH: Final[int] = 255
MAX_LABEL_LENGTH: Final[int] = 255
MAX_STATUS_LENGTH: Final[int] = 40
MAX_SOURCE_LENGTH: Final[int] = 80
MAX_SCOPE_LENGTH: Final[int] = 80
MAX_MODE_LENGTH: Final[int] = 80
MAX_INVENTORY_KEY_LENGTH: Final[int] = 120
MAX_SLOT_KEY_LENGTH: Final[int] = 120
MAX_VPLIB_UID_LENGTH: Final[int] = 80
MAX_FAMILY_ID_LENGTH: Final[int] = 255
MAX_PACKAGE_ID_LENGTH: Final[int] = 255
MAX_VARIANT_ID_LENGTH: Final[int] = 160
MAX_OBJECT_KIND_LENGTH: Final[int] = 80
MAX_TAXONOMY_DOMAIN_LENGTH: Final[int] = 80
MAX_TAXONOMY_CATEGORY_LENGTH: Final[int] = 120
MAX_TAXONOMY_PATH_LENGTH: Final[int] = 512
MAX_HASH_LENGTH: Final[int] = 128
MAX_ACTION_LENGTH: Final[int] = 120
MAX_TARGET_TYPE_LENGTH: Final[int] = 120


# ---------------------------------------------------------------------------
# SQLAlchemy extension import
# ---------------------------------------------------------------------------

@lru_cache(maxsize=1)
def _load_db() -> Any:
    """
    Lädt die zentrale Flask-SQLAlchemy Extension.

    Erwarteter Service-Standard:

        services/vectoplan-library/extensions.py

    mit:

        db = SQLAlchemy()

    Diese Funktion ist tolerant gegenüber unterschiedlichen Import-Pfaden
    während Tests, App-Startup und Migrationen.
    """

    errors: list[str] = []

    for import_path in (
        "extensions",
        "src.extensions",
        "vectoplan_library.extensions",
    ):
        try:
            module = __import__(import_path, fromlist=["db"])
            db_obj = getattr(module, "db", None)

            if db_obj is not None:
                return db_obj

        except Exception as exc:
            errors.append(f"{import_path}: {type(exc).__name__}: {exc}")

    raise RuntimeError(
        "Could not import SQLAlchemy extension `db`. "
        "Expected `db = SQLAlchemy()` in services/vectoplan-library/extensions.py. "
        f"Import attempts: {'; '.join(errors)}"
    )


db = _load_db()


# ---------------------------------------------------------------------------
# Enums
# ---------------------------------------------------------------------------

class UserInventoryStatus(str, enum.Enum):
    ACTIVE = "active"
    INACTIVE = "inactive"
    EMPTY = "empty"
    LOCKED = "locked"
    DELETED = "deleted"

    @property
    def key(self) -> str:
        return str(self.value)


class UserInventoryContentType(str, enum.Enum):
    EMPTY = "empty"
    CREATIVE_ITEM = "creative_item"
    CREATIVE_VARIANT = "creative_variant"
    COLLECTION_ITEM = "collection_item"
    DRAFT = "draft"
    CUSTOM = "custom"

    @property
    def key(self) -> str:
        return str(self.value)


class UserInventorySource(str, enum.Enum):
    USER = "user"
    SYSTEM = "system"
    CREATIVE_LIBRARY = "creative_library"
    USER_LIBRARY = "user_library"
    COLLECTION = "collection"
    DRAFT = "draft"
    GENERATED = "generated"
    IMPORTED = "imported"

    @property
    def key(self) -> str:
        return str(self.value)


class UserInventoryMode(str, enum.Enum):
    CREATIVE = "creative"
    SURVIVAL = "survival"
    EDITOR = "editor"
    PREVIEW = "preview"

    @property
    def key(self) -> str:
        return str(self.value)


class UserInventoryAuditEventType(str, enum.Enum):
    STATE_CREATED = "state_created"
    STATE_UPDATED = "state_updated"
    STATE_LOADED = "state_loaded"
    STATE_SYNCED = "state_synced"
    SLOT_CREATED = "slot_created"
    SLOT_ASSIGNED = "slot_assigned"
    SLOT_CLEARED = "slot_cleared"
    SLOT_SELECTED = "slot_selected"
    SLOT_UPDATED = "slot_updated"
    SLOT_PINNED = "slot_pinned"
    SLOT_UNPINNED = "slot_unpinned"
    SLOT_LOCKED = "slot_locked"
    SLOT_UNLOCKED = "slot_unlocked"
    SLOT_DELETED = "slot_deleted"
    HOTBAR_REORDERED = "hotbar_reordered"
    OTHER = "other"

    @property
    def key(self) -> str:
        return str(self.value)


# ---------------------------------------------------------------------------
# Generic helpers
# ---------------------------------------------------------------------------

def utc_now() -> datetime:
    """Liefert eine timezone-aware UTC-Zeit."""
    return datetime.now(timezone.utc)


def new_uid() -> str:
    """Stable lowercase UUID string."""
    return str(uuid.uuid4()).lower()


def enum_value(value: Any, *, default: str = "") -> str:
    """Normalisiert Enum-/String-Werte zu DB-Strings."""
    if value is None:
        return default

    if hasattr(value, "value"):
        try:
            text = str(value.value).strip()
            return text or default
        except Exception:
            return default

    try:
        text = str(value).strip()
    except Exception:
        return default

    return text or default


def first_non_empty(*values: Any) -> Any:
    """Liefert den ersten nicht-leeren Wert."""
    for value in values:
        if value is None:
            continue

        if isinstance(value, str) and not value.strip():
            continue

        return value

    return None


def clean_string(value: Any, *, fallback: str = "") -> str:
    """Normalisiert einen beliebigen Wert defensiv zu String."""
    try:
        if value is None:
            return fallback

        cleaned = str(value).replace("\x00", "").strip()
        return cleaned if cleaned else fallback

    except Exception:
        return fallback


def clean_optional_string(value: Any, *, max_length: int | None = None) -> str | None:
    """Normalisiert optionalen String."""
    try:
        if value is None:
            return None

        cleaned = str(value).replace("\x00", "").strip()

        if not cleaned:
            return None

        if max_length is not None and max_length > 0:
            return cleaned[:max_length]

        return cleaned

    except Exception:
        return None


def clean_required_string(value: Any, *, fallback: str, max_length: int | None = None) -> str:
    """Normalisiert Pflicht-String mit Fallback."""
    cleaned = clean_optional_string(value, max_length=max_length)

    if cleaned is not None:
        return cleaned

    fallback_cleaned = clean_string(fallback, fallback="default")

    if max_length is not None and max_length > 0:
        return fallback_cleaned[:max_length]

    return fallback_cleaned


def normalize_optional_string(value: Any, *, max_length: int | None = None) -> str | None:
    """Alias für neue Model-Dateien."""
    return clean_optional_string(value, max_length=max_length)


def normalize_required_string(value: Any, *, field_name: str, max_length: int | None = None) -> str:
    """Normalisiert Pflicht-String ohne Fallback."""
    text = clean_optional_string(value, max_length=max_length)
    if not text:
        raise ValueError(f"{field_name} is required.")
    return text


def normalize_int(
    value: Any,
    *,
    default: int | None,
    minimum: int | None = None,
    maximum: int | None = None,
) -> int | None:
    """Normalisiert Integer mit optionalen Grenzen."""
    if value is None and default is None:
        return None

    try:
        normalized = int(value)
    except Exception:
        if default is None:
            return None
        normalized = int(default)

    if minimum is not None:
        normalized = max(int(minimum), normalized)

    if maximum is not None:
        normalized = min(int(maximum), normalized)

    return normalized


def normalize_slot_index(value: Any, *, default: int = MIN_SLOT_INDEX) -> int:
    """Normalisiert Slot-Indizes auf 1..9."""
    return normalize_int(
        value,
        default=default,
        minimum=MIN_SLOT_INDEX,
        maximum=MAX_SLOT_INDEX,
    ) or MIN_SLOT_INDEX


def normalize_slot_count(value: Any, *, default: int = DEFAULT_SLOT_COUNT) -> int:
    """Normalisiert Slot-Anzahl. Phase 1 bleibt fix auf 9."""
    return normalize_int(value, default=default, minimum=DEFAULT_SLOT_COUNT, maximum=DEFAULT_SLOT_COUNT) or DEFAULT_SLOT_COUNT


def normalize_user_id(value: Any, *, default: int = DEFAULT_USER_ID) -> int:
    """
    Normalisiert User-ID.

    Phase 1:
    - Standard: user_id=1
    - Es wird keine User-Tabelle vorausgesetzt.
    """

    return normalize_int(value, default=default, minimum=1) or DEFAULT_USER_ID


def normalize_bool(value: Any, *, default: bool = False) -> bool:
    """Normalisiert Bool-Werte aus Python-/JSON-/Form-ähnlichen Eingaben."""
    if isinstance(value, bool):
        return value

    if value is None:
        return default

    text = clean_string(value).lower()

    if text in {"1", "true", "yes", "y", "ja", "on", "enabled", "active", "selected", "visible", "locked", "pinned"}:
        return True

    if text in {"0", "false", "no", "n", "nein", "off", "disabled", "inactive", "hidden", "deleted", "empty"}:
        return False

    return default


def normalize_json_mapping(value: Any) -> dict[str, Any]:
    """Normalisiert Mapping-Werte JSON-kompatibel."""
    if value is None:
        return {}

    if isinstance(value, Mapping):
        result: dict[str, Any] = {}

        for key, child_value in value.items():
            try:
                result[str(key)] = normalize_json_value(child_value)
            except Exception:
                result[str(key)] = str(child_value)

        return result

    return {}


def normalize_json_list(value: Any) -> list[Any]:
    """Normalisiert Listenwerte JSON-kompatibel."""
    if value is None:
        return []

    if isinstance(value, Mapping):
        return [normalize_json_mapping(value)]

    if isinstance(value, list):
        return [normalize_json_value(item) for item in value]

    if isinstance(value, tuple):
        return [normalize_json_value(item) for item in value]

    if isinstance(value, set):
        return [normalize_json_value(item) for item in sorted(value, key=str)]

    if isinstance(value, (str, bytes, bytearray)):
        return [normalize_json_value(value)]

    try:
        return [normalize_json_value(item) for item in value]
    except Exception:
        return []


def normalize_json_value(value: Any) -> Any:
    """Normalisiert beliebige Werte JSON-kompatibel."""
    if value is None or isinstance(value, (str, int, float, bool)):
        return value

    if isinstance(value, datetime):
        return value.isoformat()

    if isinstance(value, enum.Enum):
        return value.value

    if isinstance(value, Mapping):
        return normalize_json_mapping(value)

    if isinstance(value, (list, tuple, set)):
        return normalize_json_list(value)

    if hasattr(value, "to_dict") and callable(value.to_dict):
        try:
            return normalize_json_value(value.to_dict())
        except Exception:
            return str(value)

    return str(value)


def merge_json(*values: Mapping[str, Any] | None) -> dict[str, Any]:
    """Mergt mehrere JSON-Mappings defensiv."""
    merged: dict[str, Any] = {}

    for value in values:
        merged.update(normalize_json_mapping(value))

    return merged


def stable_json_hash(value: Any) -> str:
    """Erzeugt einen stabilen SHA-256 Hash für JSON-kompatible Werte."""
    try:
        safe = normalize_json_value(value)
        raw = json.dumps(safe, sort_keys=True, ensure_ascii=False, separators=(",", ":"))
    except Exception:
        raw = str(value)

    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


@lru_cache(maxsize=512)
def slot_key_for_index(slot_index: Any) -> str:
    """Erzeugt stabilen Slot-Key für 1..9."""
    return f"user-slot-{normalize_slot_index(slot_index)}"


def taxonomy_path_for(
    *,
    domain: Any = None,
    category: Any = None,
    subcategory: Any = None,
) -> str | None:
    """Baut einen Taxonomie-Pfad aus Domain/Kategorie/Subkategorie."""
    parts = [
        clean_optional_string(domain, max_length=MAX_TAXONOMY_DOMAIN_LENGTH),
        clean_optional_string(category, max_length=MAX_TAXONOMY_CATEGORY_LENGTH),
        clean_optional_string(subcategory, max_length=MAX_TAXONOMY_CATEGORY_LENGTH),
    ]

    cleaned_parts = [part for part in parts if part]

    if not cleaned_parts:
        return None

    return "/".join(cleaned_parts)


def normalize_status(value: Any, *, default: str = UserInventoryStatus.ACTIVE.value) -> str:
    """Normalisiert Status."""
    return enum_value(value, default=default)[:MAX_STATUS_LENGTH]


def normalize_source(value: Any, *, default: str = UserInventorySource.USER.value) -> str:
    """Normalisiert source/content source."""
    text = enum_value(value, default=default).strip().lower()

    aliases = {
        "creative": UserInventorySource.CREATIVE_LIBRARY.value,
        "creative_library": UserInventorySource.CREATIVE_LIBRARY.value,
        "library": UserInventorySource.CREATIVE_LIBRARY.value,
        "user_library": UserInventorySource.USER_LIBRARY.value,
        "collection": UserInventorySource.COLLECTION.value,
        "draft": UserInventorySource.DRAFT.value,
        "generator": UserInventorySource.GENERATED.value,
        "generated": UserInventorySource.GENERATED.value,
        "import": UserInventorySource.IMPORTED.value,
        "imported": UserInventorySource.IMPORTED.value,
        "system": UserInventorySource.SYSTEM.value,
        "user": UserInventorySource.USER.value,
    }

    return aliases.get(text, text or default)[:MAX_SOURCE_LENGTH]


def normalize_mode(value: Any, *, default: str = UserInventoryMode.CREATIVE.value) -> str:
    """Normalisiert Inventar-Modus."""
    text = enum_value(value, default=default).strip().lower()

    aliases = {
        "create": UserInventoryMode.CREATIVE.value,
        "creative": UserInventoryMode.CREATIVE.value,
        "editor": UserInventoryMode.EDITOR.value,
        "edit": UserInventoryMode.EDITOR.value,
        "survival": UserInventoryMode.SURVIVAL.value,
        "preview": UserInventoryMode.PREVIEW.value,
    }

    return aliases.get(text, text or default)[:MAX_MODE_LENGTH]


def extract_inventory_item_identity(payload: Mapping[str, Any] | None) -> dict[str, Any]:
    """Extrahiert Item-/Variant-/Collection-Identität aus API-/DB-Payload."""
    data = normalize_json_mapping(payload)

    item_db_id = normalize_int(
        first_non_empty(
            data.get("item_db_id"),
            data.get("creative_item_id"),
            data.get("creativeLibraryItemId"),
            data.get("family_db_id"),
            data.get("id"),
        ),
        default=None,
        minimum=1,
    )

    variant_db_id = normalize_int(
        first_non_empty(
            data.get("variant_db_id"),
            data.get("creative_variant_id"),
            data.get("variantDbId"),
        ),
        default=None,
        minimum=1,
    )

    collection_id = normalize_int(
        first_non_empty(
            data.get("collection_id"),
            data.get("collection_db_id"),
            data.get("creative_library_collection_id"),
        ),
        default=None,
        minimum=1,
    )

    collection_item_id = normalize_int(
        first_non_empty(
            data.get("collection_item_id"),
            data.get("collection_item_db_id"),
            data.get("creative_library_collection_item_id"),
        ),
        default=None,
        minimum=1,
    )

    domain = clean_optional_string(data.get("domain"), max_length=MAX_TAXONOMY_DOMAIN_LENGTH)
    category = clean_optional_string(data.get("category"), max_length=MAX_TAXONOMY_CATEGORY_LENGTH)
    subcategory = clean_optional_string(data.get("subcategory"), max_length=MAX_TAXONOMY_CATEGORY_LENGTH)

    return {
        "item_db_id": item_db_id,
        "variant_db_id": variant_db_id,
        "collection_id": collection_id,
        "collection_item_id": collection_item_id,
        "collection_uid": clean_optional_string(data.get("collection_uid"), max_length=MAX_UID_LENGTH),
        "collection_key": clean_optional_string(data.get("collection_key"), max_length=MAX_INVENTORY_KEY_LENGTH),
        "collection_item_uid": clean_optional_string(data.get("collection_item_uid"), max_length=MAX_UID_LENGTH),
        "item_key": clean_optional_string(data.get("item_key"), max_length=MAX_KEY_LENGTH),
        "vplib_uid": clean_optional_string(data.get("vplib_uid") or data.get("vplibUid"), max_length=MAX_VPLIB_UID_LENGTH),
        "family_id": clean_optional_string(data.get("family_id") or data.get("familyId"), max_length=MAX_FAMILY_ID_LENGTH),
        "package_id": clean_optional_string(data.get("package_id") or data.get("packageId"), max_length=MAX_PACKAGE_ID_LENGTH),
        "variant_id": clean_optional_string(data.get("variant_id") or data.get("variantId"), max_length=MAX_VARIANT_ID_LENGTH),
        "label": clean_optional_string(data.get("label") or data.get("name") or data.get("family_name"), max_length=MAX_LABEL_LENGTH),
        "description": clean_optional_string(data.get("description")),
        "object_kind": clean_optional_string(data.get("object_kind") or data.get("objectKind"), max_length=MAX_OBJECT_KIND_LENGTH),
        "domain": domain,
        "category": category,
        "subcategory": subcategory,
        "taxonomy_path": clean_optional_string(data.get("taxonomy_path"), max_length=MAX_TAXONOMY_PATH_LENGTH)
        or taxonomy_path_for(domain=domain, category=category, subcategory=subcategory),
    }


def slot_payload_summary(slot: "UserInventorySlot | None") -> dict[str, Any]:
    """Kompakte Slot-Zusammenfassung für Audit/State."""
    if slot is None:
        return {}

    return {
        "slot_index": slot.slot_index,
        "slot_key": slot.slot_key,
        "content_type": slot.content_type,
        "item_db_id": slot.item_db_id,
        "variant_db_id": slot.variant_db_id,
        "collection_id": slot.collection_id,
        "collection_item_id": slot.collection_item_id,
        "collection_uid": slot.collection_uid,
        "collection_item_uid": slot.collection_item_uid,
        "item_key": slot.item_key,
        "vplib_uid": slot.vplib_uid,
        "family_id": slot.family_id,
        "package_id": slot.package_id,
        "variant_id": slot.variant_id,
        "label": slot.label,
        "object_kind": slot.object_kind,
        "taxonomy_path": slot.taxonomy_path,
        "quantity": slot.quantity,
        "empty": slot.empty,
        "selected": slot.selected,
        "active": slot.active,
    }


# ---------------------------------------------------------------------------
# Mixins
# ---------------------------------------------------------------------------

class TimestampMixin:
    """Gemeinsame created_at/updated_at-Felder."""

    created_at = db.Column(db.DateTime(timezone=True), nullable=False, default=utc_now)
    updated_at = db.Column(db.DateTime(timezone=True), nullable=False, default=utc_now, onupdate=utc_now)

    def touch(self) -> None:
        """Aktualisiert updated_at defensiv."""
        try:
            self.updated_at = utc_now()
        except Exception:
            pass


class JsonMixin:
    """Gemeinsame JSON-Normalisierung."""

    @staticmethod
    def json_mapping(value: Any) -> dict[str, Any]:
        return normalize_json_mapping(value)

    @staticmethod
    def json_list(value: Any) -> list[Any]:
        return normalize_json_list(value)


# ---------------------------------------------------------------------------
# Models
# ---------------------------------------------------------------------------

class UserInventoryState(TimestampMixin, JsonMixin, db.Model):
    """
    Persistierter Zustand eines User-Inventars.

    Diese Tabelle speichert nicht den Inhalt einzelner Slots, sondern den Zustand
    des Inventars:

    - welcher Slot aktiv ist
    - welcher Slot zuletzt ausgewählt wurde
    - welche Item-/Block-/Collection-Metadaten zuletzt selektiert waren

    Phase 1:
    - user_id default 1
    - inventory_key default "default"
    - active_slot_index 1..9
    """

    __tablename__ = "user_inventory_states"

    id = db.Column(db.BigInteger, primary_key=True, autoincrement=True)

    inventory_uid = db.Column(db.String(MAX_UID_LENGTH), nullable=False, unique=True, index=True, default=new_uid)

    user_id = db.Column(db.BigInteger, nullable=False, default=DEFAULT_USER_ID, index=True)
    inventory_key = db.Column(db.String(MAX_INVENTORY_KEY_LENGTH), nullable=False, default=DEFAULT_INVENTORY_KEY, index=True)

    active_slot_index = db.Column(db.Integer, nullable=False, default=MIN_SLOT_INDEX)
    last_selected_slot_index = db.Column(db.Integer, nullable=False, default=MIN_SLOT_INDEX)
    last_selected_slot_key = db.Column(db.String(MAX_SLOT_KEY_LENGTH), nullable=False, default=slot_key_for_index(MIN_SLOT_INDEX))

    # Optional resolved user library context.
    active_collection_id = db.Column(
        db.BigInteger,
        db.ForeignKey("creative_library_collections.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )
    active_collection_uid = db.Column(db.String(MAX_UID_LENGTH), nullable=True, index=True)
    active_collection_key = db.Column(db.String(MAX_INVENTORY_KEY_LENGTH), nullable=True, index=True)

    last_selected_collection_id = db.Column(
        db.BigInteger,
        db.ForeignKey("creative_library_collections.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )
    last_selected_collection_item_id = db.Column(
        db.BigInteger,
        db.ForeignKey("creative_library_collection_items.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )
    last_selected_collection_uid = db.Column(db.String(MAX_UID_LENGTH), nullable=True, index=True)
    last_selected_collection_item_uid = db.Column(db.String(MAX_UID_LENGTH), nullable=True, index=True)
    last_selected_item_key = db.Column(db.String(MAX_KEY_LENGTH), nullable=True, index=True)

    last_selected_item_db_id = db.Column(
        db.BigInteger,
        db.ForeignKey("creative_library_items.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )
    last_selected_variant_db_id = db.Column(
        db.BigInteger,
        db.ForeignKey("creative_library_variants.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )

    last_selected_vplib_uid = db.Column(db.String(MAX_VPLIB_UID_LENGTH), nullable=True, index=True)
    last_selected_family_id = db.Column(db.String(MAX_FAMILY_ID_LENGTH), nullable=True, index=True)
    last_selected_package_id = db.Column(db.String(MAX_PACKAGE_ID_LENGTH), nullable=True, index=True)
    last_selected_variant_id = db.Column(db.String(MAX_VARIANT_ID_LENGTH), nullable=True, index=True)
    last_selected_label = db.Column(db.String(MAX_LABEL_LENGTH), nullable=True)
    last_selected_object_kind = db.Column(db.String(MAX_OBJECT_KIND_LENGTH), nullable=True, index=True)

    last_selected_domain = db.Column(db.String(MAX_TAXONOMY_DOMAIN_LENGTH), nullable=True, index=True)
    last_selected_category = db.Column(db.String(MAX_TAXONOMY_CATEGORY_LENGTH), nullable=True, index=True)
    last_selected_subcategory = db.Column(db.String(MAX_TAXONOMY_CATEGORY_LENGTH), nullable=True, index=True)
    last_selected_taxonomy_path = db.Column(db.String(MAX_TAXONOMY_PATH_LENGTH), nullable=True)

    slot_count = db.Column(db.Integer, nullable=False, default=DEFAULT_SLOT_COUNT)
    source = db.Column(db.String(MAX_SOURCE_LENGTH), nullable=False, default=UserInventorySource.USER.value)
    scope = db.Column(db.String(MAX_SCOPE_LENGTH), nullable=False, default="editor")
    mode = db.Column(db.String(MAX_MODE_LENGTH), nullable=False, default=UserInventoryMode.CREATIVE.value)

    status = db.Column(db.String(MAX_STATUS_LENGTH), nullable=False, default=UserInventoryStatus.ACTIVE.value, index=True)
    active = db.Column(db.Boolean, nullable=False, default=True, index=True)
    locked = db.Column(db.Boolean, nullable=False, default=False)

    selected_at = db.Column(db.DateTime(timezone=True), nullable=True)
    last_loaded_at = db.Column(db.DateTime(timezone=True), nullable=True)
    last_synced_at = db.Column(db.DateTime(timezone=True), nullable=True)
    deleted_at = db.Column(db.DateTime(timezone=True), nullable=True)

    payload = db.Column(db.JSON, nullable=False, default=dict)
    settings = db.Column(db.JSON, nullable=False, default=dict)
    metadata_json = db.Column(db.JSON, nullable=False, default=dict)

    slots = db.relationship(
        "UserInventorySlot",
        back_populates="state",
        cascade="all, delete-orphan",
        lazy="selectin",
        passive_deletes=True,
    )

    active_collection = db.relationship(
        "CreativeLibraryCollection",
        foreign_keys=[active_collection_id],
        lazy="joined",
    )
    last_selected_collection = db.relationship(
        "CreativeLibraryCollection",
        foreign_keys=[last_selected_collection_id],
        lazy="joined",
    )
    last_selected_collection_item = db.relationship(
        "CreativeLibraryCollectionItem",
        foreign_keys=[last_selected_collection_item_id],
        lazy="joined",
    )
    last_selected_item = db.relationship(
        "CreativeLibraryItem",
        foreign_keys=[last_selected_item_db_id],
        lazy="joined",
    )
    last_selected_variant = db.relationship(
        "CreativeLibraryVariant",
        foreign_keys=[last_selected_variant_db_id],
        lazy="joined",
    )

    __table_args__ = (
        db.UniqueConstraint(
            "user_id",
            "inventory_key",
            name="uq_user_inventory_state_user_inventory",
        ),
        db.CheckConstraint(
            f"active_slot_index >= {MIN_SLOT_INDEX} AND active_slot_index <= {MAX_SLOT_INDEX}",
            name="ck_user_inventory_state_active_slot_range",
        ),
        db.CheckConstraint(
            f"last_selected_slot_index >= {MIN_SLOT_INDEX} AND last_selected_slot_index <= {MAX_SLOT_INDEX}",
            name="ck_user_inventory_state_last_slot_range",
        ),
        db.CheckConstraint(
            f"slot_count = {DEFAULT_SLOT_COUNT}",
            name="ck_user_inventory_state_slot_count",
        ),
        db.Index(
            "ix_user_inventory_state_selection",
            "user_id",
            "inventory_key",
            "active_slot_index",
        ),
        db.Index(
            "ix_user_inventory_state_last_item",
            "last_selected_vplib_uid",
            "last_selected_variant_id",
        ),
        db.Index(
            "ix_user_inventory_state_collection",
            "user_id",
            "active_collection_uid",
            "active_collection_key",
        ),
        db.Index(
            "ix_user_inventory_state_status",
            "user_id",
            "status",
            "active",
        ),
    )

    def __repr__(self) -> str:
        return (
            "<UserInventoryState "
            f"user_id={self.user_id!r} "
            f"inventory={self.inventory_key!r} "
            f"active_slot={self.active_slot_index!r}>"
        )

    @classmethod
    def create_default(
        cls,
        *,
        user_id: Any = DEFAULT_USER_ID,
        inventory_key: Any = DEFAULT_INVENTORY_KEY,
        active_slot_index: Any = MIN_SLOT_INDEX,
        metadata: Mapping[str, Any] | None = None,
        active_collection: Any = None,
    ) -> "UserInventoryState":
        """Erstellt einen Default-State ohne DB-Zugriff."""
        normalized_slot_index = normalize_slot_index(active_slot_index)

        collection_id = normalize_int(getattr(active_collection, "id", None), default=None, minimum=1)
        collection_uid = clean_optional_string(getattr(active_collection, "collection_uid", None), max_length=MAX_UID_LENGTH)
        collection_key = clean_optional_string(getattr(active_collection, "collection_key", None), max_length=MAX_INVENTORY_KEY_LENGTH)

        return cls(
            inventory_uid=new_uid(),
            user_id=normalize_user_id(user_id),
            inventory_key=clean_required_string(
                inventory_key,
                fallback=DEFAULT_INVENTORY_KEY,
                max_length=MAX_INVENTORY_KEY_LENGTH,
            ),
            active_slot_index=normalized_slot_index,
            last_selected_slot_index=normalized_slot_index,
            last_selected_slot_key=slot_key_for_index(normalized_slot_index),
            active_collection_id=collection_id,
            active_collection_uid=collection_uid,
            active_collection_key=collection_key,
            slot_count=DEFAULT_SLOT_COUNT,
            source=UserInventorySource.USER.value,
            scope="editor",
            mode=UserInventoryMode.CREATIVE.value,
            status=UserInventoryStatus.ACTIVE.value,
            active=True,
            locked=False,
            selected_at=utc_now(),
            payload={},
            settings={},
            metadata_json=normalize_json_mapping(metadata),
        )

    def select_slot(self, slot: "UserInventorySlot | None" = None, *, slot_index: Any | None = None) -> None:
        """
        Aktualisiert den aktiven und zuletzt ausgewählten Slot.

        Wenn ein Slot-Objekt übergeben wird, werden relevante Item-/Collection-Daten
        als Snapshot in den State übernommen.
        """

        selected_index = normalize_slot_index(
            slot.slot_index if slot is not None else slot_index,
            default=self.active_slot_index or MIN_SLOT_INDEX,
        )

        now = utc_now()

        self.active_slot_index = selected_index
        self.last_selected_slot_index = selected_index
        self.last_selected_slot_key = slot_key_for_index(selected_index)
        self.selected_at = now
        self.touch()

        if slot is None:
            return

        self.last_selected_collection_id = slot.collection_id
        self.last_selected_collection_item_id = slot.collection_item_id
        self.last_selected_collection_uid = slot.collection_uid
        self.last_selected_collection_item_uid = slot.collection_item_uid
        self.last_selected_item_key = slot.item_key

        self.last_selected_item_db_id = slot.item_db_id
        self.last_selected_variant_db_id = slot.variant_db_id
        self.last_selected_vplib_uid = slot.vplib_uid
        self.last_selected_family_id = slot.family_id
        self.last_selected_package_id = slot.package_id
        self.last_selected_variant_id = slot.variant_id
        self.last_selected_label = slot.label
        self.last_selected_object_kind = slot.object_kind
        self.last_selected_domain = slot.domain
        self.last_selected_category = slot.category
        self.last_selected_subcategory = slot.subcategory
        self.last_selected_taxonomy_path = slot.taxonomy_path

    def set_active_collection(self, collection: Any | None = None, *, collection_uid: Any = None, collection_key: Any = None) -> None:
        """Setzt aktive Creative-Library-Collection für resolved Inventar."""
        self.active_collection_id = normalize_int(getattr(collection, "id", None), default=None, minimum=1)
        self.active_collection_uid = clean_optional_string(
            first_non_empty(collection_uid, getattr(collection, "collection_uid", None)),
            max_length=MAX_UID_LENGTH,
        )
        self.active_collection_key = clean_optional_string(
            first_non_empty(collection_key, getattr(collection, "collection_key", None)),
            max_length=MAX_INVENTORY_KEY_LENGTH,
        )
        self.touch()

    def mark_loaded(self) -> None:
        """Markiert Inventar als geladen."""
        self.last_loaded_at = utc_now()
        self.touch()

    def mark_synced(self) -> None:
        """Markiert Inventar als synchronisiert."""
        self.last_synced_at = utc_now()
        self.touch()

    def mark_deleted(self) -> None:
        """Soft-delete für Inventory-State."""
        self.status = UserInventoryStatus.DELETED.value
        self.active = False
        self.deleted_at = utc_now()
        self.touch()

    def to_dict(self, *, include_slots: bool = False) -> dict[str, Any]:
        """Serialisiert den State API-freundlich."""
        data = {
            "id": self.id,
            "inventory_uid": self.inventory_uid,
            "user_id": self.user_id,
            "inventory_key": self.inventory_key,
            "active_slot_index": self.active_slot_index,
            "last_selected_slot_index": self.last_selected_slot_index,
            "last_selected_slot_key": self.last_selected_slot_key,
            "active_collection": {
                "collection_id": self.active_collection_id,
                "collection_uid": self.active_collection_uid,
                "collection_key": self.active_collection_key,
            },
            "last_selected": {
                "collection_id": self.last_selected_collection_id,
                "collection_item_id": self.last_selected_collection_item_id,
                "collection_uid": self.last_selected_collection_uid,
                "collection_item_uid": self.last_selected_collection_item_uid,
                "item_key": self.last_selected_item_key,
                "item_db_id": self.last_selected_item_db_id,
                "variant_db_id": self.last_selected_variant_db_id,
                "vplib_uid": self.last_selected_vplib_uid,
                "family_id": self.last_selected_family_id,
                "package_id": self.last_selected_package_id,
                "variant_id": self.last_selected_variant_id,
                "label": self.last_selected_label,
                "object_kind": self.last_selected_object_kind,
                "domain": self.last_selected_domain,
                "category": self.last_selected_category,
                "subcategory": self.last_selected_subcategory,
                "taxonomy_path": self.last_selected_taxonomy_path,
            },
            "slot_count": self.slot_count,
            "source": self.source,
            "scope": self.scope,
            "mode": self.mode,
            "status": self.status,
            "active": self.active,
            "locked": self.locked,
            "selected_at": self.selected_at.isoformat() if self.selected_at else None,
            "last_loaded_at": self.last_loaded_at.isoformat() if self.last_loaded_at else None,
            "last_synced_at": self.last_synced_at.isoformat() if self.last_synced_at else None,
            "deleted_at": self.deleted_at.isoformat() if self.deleted_at else None,
            "payload": normalize_json_mapping(self.payload),
            "settings": normalize_json_mapping(self.settings),
            "metadata": normalize_json_mapping(self.metadata_json),
            "created_at": self.created_at.isoformat() if self.created_at else None,
            "updated_at": self.updated_at.isoformat() if self.updated_at else None,
        }

        if include_slots:
            slots = list(getattr(self, "slots", []) or [])
            slots.sort(key=lambda item: normalize_slot_index(getattr(item, "slot_index", MIN_SLOT_INDEX)))
            data["slots"] = [slot.to_dict() for slot in slots]

        return data


class UserInventorySlot(TimestampMixin, JsonMixin, db.Model):
    """
    Persistierter Slot eines User-Inventars.

    Diese Tabelle speichert, was in welchem Slot eines konkreten Users liegt.

    Phase 1:
    - user_id default 1
    - inventory_key default "default"
    - slot_index 1..9
    """

    __tablename__ = "user_inventory_slots"

    id = db.Column(db.BigInteger, primary_key=True, autoincrement=True)

    slot_uid = db.Column(db.String(MAX_UID_LENGTH), nullable=False, unique=True, index=True, default=new_uid)

    state_id = db.Column(
        db.BigInteger,
        db.ForeignKey("user_inventory_states.id", ondelete="CASCADE"),
        nullable=True,
        index=True,
    )

    user_id = db.Column(db.BigInteger, nullable=False, default=DEFAULT_USER_ID, index=True)
    inventory_key = db.Column(db.String(MAX_INVENTORY_KEY_LENGTH), nullable=False, default=DEFAULT_INVENTORY_KEY, index=True)

    slot_index = db.Column(db.Integer, nullable=False)
    slot_key = db.Column(db.String(MAX_SLOT_KEY_LENGTH), nullable=False, index=True)

    content_type = db.Column(
        db.String(MAX_TARGET_TYPE_LENGTH),
        nullable=False,
        default=UserInventoryContentType.EMPTY.value,
        index=True,
    )

    collection_id = db.Column(
        db.BigInteger,
        db.ForeignKey("creative_library_collections.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )
    collection_item_id = db.Column(
        db.BigInteger,
        db.ForeignKey("creative_library_collection_items.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )
    collection_uid = db.Column(db.String(MAX_UID_LENGTH), nullable=True, index=True)
    collection_key = db.Column(db.String(MAX_INVENTORY_KEY_LENGTH), nullable=True, index=True)
    collection_item_uid = db.Column(db.String(MAX_UID_LENGTH), nullable=True, index=True)
    item_key = db.Column(db.String(MAX_KEY_LENGTH), nullable=True, index=True)

    item_db_id = db.Column(
        db.BigInteger,
        db.ForeignKey("creative_library_items.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )
    variant_db_id = db.Column(
        db.BigInteger,
        db.ForeignKey("creative_library_variants.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )

    source_draft_id = db.Column(
        db.BigInteger,
        db.ForeignKey("creative_library_drafts.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )
    source_draft_uid = db.Column(db.String(MAX_UID_LENGTH), nullable=True, index=True)

    vplib_uid = db.Column(db.String(MAX_VPLIB_UID_LENGTH), nullable=True, index=True)
    family_id = db.Column(db.String(MAX_FAMILY_ID_LENGTH), nullable=True, index=True)
    package_id = db.Column(db.String(MAX_PACKAGE_ID_LENGTH), nullable=True, index=True)
    variant_id = db.Column(db.String(MAX_VARIANT_ID_LENGTH), nullable=True, index=True)

    label = db.Column(db.String(MAX_LABEL_LENGTH), nullable=True)
    custom_label = db.Column(db.String(MAX_LABEL_LENGTH), nullable=True)
    description = db.Column(db.Text, nullable=True)
    object_kind = db.Column(db.String(MAX_OBJECT_KIND_LENGTH), nullable=True, index=True)

    domain = db.Column(db.String(MAX_TAXONOMY_DOMAIN_LENGTH), nullable=True, index=True)
    category = db.Column(db.String(MAX_TAXONOMY_CATEGORY_LENGTH), nullable=True, index=True)
    subcategory = db.Column(db.String(MAX_TAXONOMY_CATEGORY_LENGTH), nullable=True, index=True)
    taxonomy_path = db.Column(db.String(MAX_TAXONOMY_PATH_LENGTH), nullable=True)

    quantity = db.Column(db.Integer, nullable=False, default=0)
    empty = db.Column(db.Boolean, nullable=False, default=True, index=True)
    selected = db.Column(db.Boolean, nullable=False, default=False, index=True)
    active = db.Column(db.Boolean, nullable=False, default=True, index=True)
    locked = db.Column(db.Boolean, nullable=False, default=False)
    pinned = db.Column(db.Boolean, nullable=False, default=False)

    source = db.Column(db.String(MAX_SOURCE_LENGTH), nullable=False, default=UserInventorySource.USER.value)
    scope = db.Column(db.String(MAX_SCOPE_LENGTH), nullable=False, default="editor")
    mode = db.Column(db.String(MAX_MODE_LENGTH), nullable=False, default=UserInventoryMode.CREATIVE.value)
    status = db.Column(db.String(MAX_STATUS_LENGTH), nullable=False, default=UserInventoryStatus.EMPTY.value, index=True)

    sort_order = db.Column(db.Integer, nullable=False, default=0)

    icon = db.Column(db.JSON, nullable=False, default=dict)
    custom_icon = db.Column(db.JSON, nullable=False, default=dict)
    preview = db.Column(db.JSON, nullable=False, default=dict)
    custom_preview = db.Column(db.JSON, nullable=False, default=dict)
    assets = db.Column(db.JSON, nullable=False, default=list)
    variant = db.Column(db.JSON, nullable=False, default=dict)
    placement = db.Column(db.JSON, nullable=False, default=dict)

    selected_at = db.Column(db.DateTime(timezone=True), nullable=True)
    assigned_at = db.Column(db.DateTime(timezone=True), nullable=True)
    cleared_at = db.Column(db.DateTime(timezone=True), nullable=True)
    deleted_at = db.Column(db.DateTime(timezone=True), nullable=True)

    payload = db.Column(db.JSON, nullable=False, default=dict)
    meta = db.Column(db.JSON, nullable=False, default=dict)
    metadata_json = db.Column(db.JSON, nullable=False, default=dict)

    state = db.relationship(
        "UserInventoryState",
        back_populates="slots",
        lazy="joined",
    )

    collection = db.relationship(
        "CreativeLibraryCollection",
        foreign_keys=[collection_id],
        lazy="joined",
    )
    collection_item = db.relationship(
        "CreativeLibraryCollectionItem",
        foreign_keys=[collection_item_id],
        lazy="joined",
    )
    item = db.relationship(
        "CreativeLibraryItem",
        foreign_keys=[item_db_id],
        lazy="joined",
    )
    variant_row = db.relationship(
        "CreativeLibraryVariant",
        foreign_keys=[variant_db_id],
        lazy="joined",
    )
    source_draft = db.relationship(
        "CreativeLibraryDraft",
        foreign_keys=[source_draft_id],
        lazy="joined",
    )

    __table_args__ = (
        db.UniqueConstraint(
            "user_id",
            "inventory_key",
            "slot_index",
            name="uq_user_inventory_slot_user_inventory_index",
        ),
        db.UniqueConstraint(
            "user_id",
            "inventory_key",
            "slot_key",
            name="uq_user_inventory_slot_user_inventory_key",
        ),
        db.CheckConstraint(
            f"slot_index >= {MIN_SLOT_INDEX} AND slot_index <= {MAX_SLOT_INDEX}",
            name="ck_user_inventory_slot_index_range",
        ),
        db.CheckConstraint(
            "quantity >= 0",
            name="ck_user_inventory_slot_quantity_non_negative",
        ),
        db.Index(
            "ix_user_inventory_slot_lookup",
            "user_id",
            "inventory_key",
            "slot_index",
        ),
        db.Index(
            "ix_user_inventory_slot_selection",
            "user_id",
            "inventory_key",
            "selected",
        ),
        db.Index(
            "ix_user_inventory_slot_item_uid_variant",
            "vplib_uid",
            "variant_id",
        ),
        db.Index(
            "ix_user_inventory_slot_collection",
            "collection_uid",
            "collection_item_uid",
            "item_key",
        ),
        db.Index(
            "ix_user_inventory_slot_taxonomy",
            "domain",
            "category",
            "subcategory",
        ),
        db.Index(
            "ix_user_inventory_slot_content",
            "content_type",
            "status",
            "empty",
        ),
    )

    def __repr__(self) -> str:
        return (
            "<UserInventorySlot "
            f"user_id={self.user_id!r} "
            f"inventory={self.inventory_key!r} "
            f"slot={self.slot_index!r} "
            f"uid={self.vplib_uid!r}>"
        )

    @classmethod
    def create_empty(
        cls,
        *,
        user_id: Any = DEFAULT_USER_ID,
        inventory_key: Any = DEFAULT_INVENTORY_KEY,
        slot_index: Any,
        state: UserInventoryState | None = None,
        selected: bool = False,
        metadata: Mapping[str, Any] | None = None,
    ) -> "UserInventorySlot":
        """Erstellt einen leeren Slot ohne DB-Zugriff."""
        normalized_slot_index = normalize_slot_index(slot_index)
        resolved_user_id = normalize_user_id(user_id if user_id is not None else getattr(state, "user_id", DEFAULT_USER_ID))
        resolved_inventory_key = clean_required_string(
            inventory_key if inventory_key is not None else getattr(state, "inventory_key", DEFAULT_INVENTORY_KEY),
            fallback=DEFAULT_INVENTORY_KEY,
            max_length=MAX_INVENTORY_KEY_LENGTH,
        )

        return cls(
            slot_uid=new_uid(),
            state=state,
            state_id=getattr(state, "id", None),
            user_id=resolved_user_id,
            inventory_key=resolved_inventory_key,
            slot_index=normalized_slot_index,
            slot_key=slot_key_for_index(normalized_slot_index),
            content_type=UserInventoryContentType.EMPTY.value,
            quantity=0,
            empty=True,
            selected=bool(selected),
            active=True,
            locked=False,
            pinned=False,
            source=UserInventorySource.USER.value,
            scope="editor",
            mode=UserInventoryMode.CREATIVE.value,
            status=UserInventoryStatus.EMPTY.value,
            sort_order=normalized_slot_index,
            icon={},
            custom_icon={},
            preview={},
            custom_preview={},
            assets=[],
            variant={},
            placement={},
            selected_at=utc_now() if selected else None,
            payload={},
            meta={},
            metadata_json=normalize_json_mapping(metadata),
        )

    @classmethod
    def create_from_item_payload(
        cls,
        *,
        user_id: Any = DEFAULT_USER_ID,
        inventory_key: Any = DEFAULT_INVENTORY_KEY,
        slot_index: Any,
        item_payload: Mapping[str, Any],
        state: UserInventoryState | None = None,
        selected: bool = False,
        metadata: Mapping[str, Any] | None = None,
    ) -> "UserInventorySlot":
        """Erstellt einen gefüllten Slot aus einem API-/Library-Payload."""
        slot = cls.create_empty(
            user_id=user_id,
            inventory_key=inventory_key,
            slot_index=slot_index,
            state=state,
            selected=selected,
            metadata=metadata,
        )
        slot.assign_item(item_payload)
        return slot

    def assign_item(self, item_payload: Mapping[str, Any] | None) -> None:
        """
        Weist dem Slot Item-/Blockdaten zu.

        Erwartete Keys sind tolerant:
        - item_db_id oder id
        - variant_db_id
        - collection_id / collection_uid
        - collection_item_id / collection_item_uid
        - item_key
        - vplib_uid
        - family_id
        - package_id
        - variant_id
        - label/name
        - object_kind
        - domain/category/subcategory
        """

        payload = normalize_json_mapping(item_payload)
        identity = extract_inventory_item_identity(payload)

        self.collection_id = identity["collection_id"]
        self.collection_item_id = identity["collection_item_id"]
        self.collection_uid = identity["collection_uid"]
        self.collection_key = identity["collection_key"]
        self.collection_item_uid = identity["collection_item_uid"]
        self.item_key = identity["item_key"]

        self.item_db_id = identity["item_db_id"]
        self.variant_db_id = identity["variant_db_id"]

        self.vplib_uid = identity["vplib_uid"]
        self.family_id = identity["family_id"]
        self.package_id = identity["package_id"]
        self.variant_id = identity["variant_id"]

        self.label = identity["label"]
        self.custom_label = clean_optional_string(payload.get("custom_label"), max_length=MAX_LABEL_LENGTH)
        self.description = identity["description"]
        self.object_kind = identity["object_kind"]

        self.domain = identity["domain"]
        self.category = identity["category"]
        self.subcategory = identity["subcategory"]
        self.taxonomy_path = identity["taxonomy_path"]

        self.quantity = normalize_int(payload.get("quantity"), default=1, minimum=1) or 1
        self.empty = False
        self.active = normalize_bool(payload.get("active"), default=True)
        self.status = normalize_status(payload.get("status"), default=UserInventoryStatus.ACTIVE.value)
        self.content_type = enum_value(
            payload.get("content_type"),
            default=UserInventoryContentType.COLLECTION_ITEM.value if self.collection_item_id or self.collection_item_uid else UserInventoryContentType.CREATIVE_ITEM.value,
        )
        self.source = normalize_source(payload.get("source"), default=UserInventorySource.COLLECTION.value if self.collection_item_id or self.collection_item_uid else UserInventorySource.CREATIVE_LIBRARY.value)
        self.mode = normalize_mode(payload.get("mode"), default=UserInventoryMode.CREATIVE.value)

        self.assigned_at = utc_now()
        self.cleared_at = None
        self.deleted_at = None

        self.icon = normalize_json_mapping(payload.get("icon"))
        self.custom_icon = normalize_json_mapping(payload.get("custom_icon"))
        self.preview = normalize_json_mapping(payload.get("preview"))
        self.custom_preview = normalize_json_mapping(payload.get("custom_preview"))
        self.assets = normalize_json_list(payload.get("assets"))
        self.variant = normalize_json_mapping(payload.get("variant"))
        self.placement = normalize_json_mapping(payload.get("placement"))

        self.source_draft_id = normalize_int(payload.get("source_draft_id") or payload.get("draft_id"), default=None, minimum=1)
        self.source_draft_uid = clean_optional_string(payload.get("source_draft_uid") or payload.get("draft_uid"), max_length=MAX_UID_LENGTH)

        self.payload = payload
        self.meta = normalize_json_mapping(payload.get("meta"))
        self.metadata_json = normalize_json_mapping(payload.get("metadata", self.metadata_json))

        self.touch()

    def assign_collection_item(self, collection_item: Any, *, metadata: Mapping[str, Any] | None = None) -> None:
        """Weist dem Slot ein geladenes CreativeLibraryCollectionItem-Objekt zu."""
        payload = {}

        if collection_item is not None and hasattr(collection_item, "to_dict") and callable(collection_item.to_dict):
            try:
                payload = normalize_json_mapping(collection_item.to_dict())
            except Exception:
                payload = {}

        if not payload:
            payload = {
                "collection_item_id": getattr(collection_item, "id", None),
                "collection_item_uid": getattr(collection_item, "collection_item_uid", None),
                "collection_id": getattr(collection_item, "collection_id", None),
                "item_key": getattr(collection_item, "item_key", None),
                "item_db_id": getattr(collection_item, "item_db_id", None),
                "variant_db_id": getattr(collection_item, "variant_db_id", None),
                "vplib_uid": getattr(collection_item, "vplib_uid", None),
                "family_id": getattr(collection_item, "family_id", None),
                "package_id": getattr(collection_item, "package_id", None),
                "variant_id": getattr(collection_item, "variant_id", None),
                "label": getattr(collection_item, "label", None),
                "description": getattr(collection_item, "description", None),
                "object_kind": getattr(collection_item, "object_kind", None),
                "domain": getattr(collection_item, "domain", None),
                "category": getattr(collection_item, "category", None),
                "subcategory": getattr(collection_item, "subcategory", None),
                "taxonomy_path": getattr(collection_item, "taxonomy_path", None),
                "icon": getattr(collection_item, "icon", None),
                "preview": getattr(collection_item, "preview", None),
                "assets": getattr(collection_item, "assets", None),
                "variant": getattr(collection_item, "variant", None),
                "placement": getattr(collection_item, "placement", None),
                "metadata": metadata,
            }

        self.assign_item(payload)
        self.content_type = UserInventoryContentType.COLLECTION_ITEM.value
        self.source = UserInventorySource.COLLECTION.value
        self.metadata_json = merge_json(self.metadata_json, metadata)
        self.touch()

    def clear_item(self) -> None:
        """Leert den Slot, ohne User-/Slot-Identität zu entfernen."""
        if self.locked:
            raise ValueError("Cannot clear a locked inventory slot.")

        self.collection_id = None
        self.collection_item_id = None
        self.collection_uid = None
        self.collection_key = None
        self.collection_item_uid = None
        self.item_key = None

        self.item_db_id = None
        self.variant_db_id = None

        self.source_draft_id = None
        self.source_draft_uid = None

        self.vplib_uid = None
        self.family_id = None
        self.package_id = None
        self.variant_id = None

        self.label = None
        self.custom_label = None
        self.description = None
        self.object_kind = None

        self.domain = None
        self.category = None
        self.subcategory = None
        self.taxonomy_path = None

        self.quantity = 0
        self.empty = True
        self.status = UserInventoryStatus.EMPTY.value
        self.content_type = UserInventoryContentType.EMPTY.value
        self.assigned_at = None
        self.cleared_at = utc_now()

        self.icon = {}
        self.custom_icon = {}
        self.preview = {}
        self.custom_preview = {}
        self.assets = []
        self.variant = {}
        self.placement = {}

        self.payload = {}
        self.meta = {}

        self.touch()

    def mark_selected(self, *, selected: bool = True) -> None:
        """Markiert den Slot als ausgewählt oder nicht ausgewählt."""
        self.selected = bool(selected)

        if selected:
            self.selected_at = utc_now()

        self.touch()

    def set_pinned(self, value: Any = True) -> None:
        """Pinnt oder entpinnt Slot."""
        self.pinned = normalize_bool(value, default=True)
        self.touch()

    def set_locked(self, value: Any = True) -> None:
        """Sperrt oder entsperrt Slot."""
        self.locked = normalize_bool(value, default=True)
        self.status = UserInventoryStatus.LOCKED.value if self.locked else (UserInventoryStatus.EMPTY.value if self.empty else UserInventoryStatus.ACTIVE.value)
        self.touch()

    def mark_deleted(self) -> None:
        """Soft-delete für Slot."""
        if self.locked:
            raise ValueError("Cannot delete a locked inventory slot.")

        self.status = UserInventoryStatus.DELETED.value
        self.active = False
        self.empty = True
        self.selected = False
        self.deleted_at = utc_now()
        self.touch()

    def display_label(self) -> str | None:
        """Liefert User-Label-Fallback."""
        return self.custom_label or self.label

    def display_icon(self) -> dict[str, Any]:
        """Liefert User-Icon-Fallback."""
        custom_icon = normalize_json_mapping(self.custom_icon)
        if custom_icon:
            return custom_icon
        return normalize_json_mapping(self.icon)

    def display_preview(self) -> dict[str, Any]:
        """Liefert User-Preview-Fallback."""
        custom_preview = normalize_json_mapping(self.custom_preview)
        if custom_preview:
            return custom_preview
        return normalize_json_mapping(self.preview)

    def to_dict(self) -> dict[str, Any]:
        """Serialisiert den Slot API-freundlich."""
        return {
            "id": self.id,
            "slot_uid": self.slot_uid,
            "state_id": self.state_id,
            "user_id": self.user_id,
            "inventory_key": self.inventory_key,
            "slot_index": self.slot_index,
            "slot_key": self.slot_key or slot_key_for_index(self.slot_index),
            "content_type": self.content_type,
            "collection_id": self.collection_id,
            "collection_item_id": self.collection_item_id,
            "collection_uid": self.collection_uid,
            "collection_key": self.collection_key,
            "collection_item_uid": self.collection_item_uid,
            "item_key": self.item_key,
            "item_db_id": self.item_db_id,
            "variant_db_id": self.variant_db_id,
            "source_draft_id": self.source_draft_id,
            "source_draft_uid": self.source_draft_uid,
            "vplib_uid": self.vplib_uid,
            "family_id": self.family_id,
            "package_id": self.package_id,
            "variant_id": self.variant_id,
            "label": self.label,
            "custom_label": self.custom_label,
            "display_label": self.display_label(),
            "description": self.description,
            "object_kind": self.object_kind,
            "domain": self.domain,
            "category": self.category,
            "subcategory": self.subcategory,
            "taxonomy_path": self.taxonomy_path,
            "quantity": self.quantity,
            "empty": self.empty,
            "selected": self.selected,
            "active": self.active,
            "locked": self.locked,
            "pinned": self.pinned,
            "source": self.source,
            "scope": self.scope,
            "mode": self.mode,
            "status": self.status,
            "sort_order": self.sort_order,
            "icon": normalize_json_mapping(self.icon),
            "custom_icon": normalize_json_mapping(self.custom_icon),
            "display_icon": self.display_icon(),
            "preview": normalize_json_mapping(self.preview),
            "custom_preview": normalize_json_mapping(self.custom_preview),
            "display_preview": self.display_preview(),
            "assets": normalize_json_list(self.assets),
            "variant": normalize_json_mapping(self.variant),
            "placement": normalize_json_mapping(self.placement),
            "selected_at": self.selected_at.isoformat() if self.selected_at else None,
            "assigned_at": self.assigned_at.isoformat() if self.assigned_at else None,
            "cleared_at": self.cleared_at.isoformat() if self.cleared_at else None,
            "deleted_at": self.deleted_at.isoformat() if self.deleted_at else None,
            "payload": normalize_json_mapping(self.payload),
            "meta": normalize_json_mapping(self.meta),
            "metadata": normalize_json_mapping(self.metadata_json),
            "created_at": self.created_at.isoformat() if self.created_at else None,
            "updated_at": self.updated_at.isoformat() if self.updated_at else None,
        }


class UserInventoryAuditEvent(TimestampMixin, JsonMixin, db.Model):
    """Audit-Event für User-Inventar-Operationen."""

    __tablename__ = "user_inventory_audit_events"

    id = db.Column(db.BigInteger, primary_key=True, autoincrement=True)

    event_uid = db.Column(db.String(MAX_UID_LENGTH), nullable=False, unique=True, index=True, default=new_uid)
    event_type = db.Column(db.String(MAX_ACTION_LENGTH), nullable=False, index=True)

    user_id = db.Column(db.BigInteger, nullable=False, default=DEFAULT_USER_ID, index=True)
    inventory_key = db.Column(db.String(MAX_INVENTORY_KEY_LENGTH), nullable=False, default=DEFAULT_INVENTORY_KEY, index=True)

    state_id = db.Column(
        db.BigInteger,
        db.ForeignKey("user_inventory_states.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )
    slot_id = db.Column(
        db.BigInteger,
        db.ForeignKey("user_inventory_slots.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )
    slot_uid = db.Column(db.String(MAX_UID_LENGTH), nullable=True, index=True)
    slot_index = db.Column(db.Integer, nullable=True, index=True)

    target_type = db.Column(db.String(MAX_TARGET_TYPE_LENGTH), nullable=True, index=True)
    target_db_id = db.Column(db.BigInteger, nullable=True, index=True)
    target_uid = db.Column(db.String(MAX_UID_LENGTH), nullable=True, index=True)
    target_key = db.Column(db.String(MAX_KEY_LENGTH), nullable=True, index=True)

    collection_id = db.Column(db.BigInteger, nullable=True, index=True)
    collection_item_id = db.Column(db.BigInteger, nullable=True, index=True)
    item_db_id = db.Column(db.BigInteger, nullable=True, index=True)
    variant_db_id = db.Column(db.BigInteger, nullable=True, index=True)

    vplib_uid = db.Column(db.String(MAX_VPLIB_UID_LENGTH), nullable=True, index=True)
    family_id = db.Column(db.String(MAX_FAMILY_ID_LENGTH), nullable=True, index=True)
    package_id = db.Column(db.String(MAX_PACKAGE_ID_LENGTH), nullable=True, index=True)
    variant_id = db.Column(db.String(MAX_VARIANT_ID_LENGTH), nullable=True, index=True)
    taxonomy_path = db.Column(db.String(MAX_TAXONOMY_PATH_LENGTH), nullable=True, index=True)

    before_json = db.Column(db.JSON, nullable=False, default=dict)
    after_json = db.Column(db.JSON, nullable=False, default=dict)
    diff_json = db.Column(db.JSON, nullable=False, default=dict)

    payload = db.Column(db.JSON, nullable=False, default=dict)
    meta = db.Column(db.JSON, nullable=False, default=dict)
    metadata_json = db.Column(db.JSON, nullable=False, default=dict)

    state = db.relationship("UserInventoryState", foreign_keys=[state_id], lazy="joined")
    slot = db.relationship("UserInventorySlot", foreign_keys=[slot_id], lazy="joined")

    __table_args__ = (
        db.Index("ix_user_inventory_audit_user_event", "user_id", "event_type", "created_at"),
        db.Index("ix_user_inventory_audit_inventory_slot", "user_id", "inventory_key", "slot_index"),
        db.Index("ix_user_inventory_audit_target", "target_type", "target_key"),
        db.Index("ix_user_inventory_audit_uid_variant", "vplib_uid", "variant_id"),
    )

    def __repr__(self) -> str:
        return f"<UserInventoryAuditEvent id={self.id!r} user_id={self.user_id!r} event_type={self.event_type!r}>"

    @classmethod
    def create_event(
        cls,
        *,
        event_type: Any,
        user_id: Any = DEFAULT_USER_ID,
        inventory_key: Any = DEFAULT_INVENTORY_KEY,
        state: UserInventoryState | None = None,
        slot: UserInventorySlot | None = None,
        before: Mapping[str, Any] | None = None,
        after: Mapping[str, Any] | None = None,
        diff: Mapping[str, Any] | None = None,
        payload: Mapping[str, Any] | None = None,
        metadata: Mapping[str, Any] | None = None,
    ) -> "UserInventoryAuditEvent":
        """Erstellt ein Audit-Event ohne DB-Zugriff."""
        data = normalize_json_mapping(payload)

        normalized_user_id = normalize_user_id(
            first_non_empty(user_id, data.get("user_id"), getattr(slot, "user_id", None), getattr(state, "user_id", None)),
            default=DEFAULT_USER_ID,
        )
        normalized_inventory_key = clean_required_string(
            first_non_empty(inventory_key, data.get("inventory_key"), getattr(slot, "inventory_key", None), getattr(state, "inventory_key", None)),
            fallback=DEFAULT_INVENTORY_KEY,
            max_length=MAX_INVENTORY_KEY_LENGTH,
        )

        target_key = clean_optional_string(
            first_non_empty(
                data.get("target_key"),
                getattr(slot, "item_key", None),
                getattr(slot, "collection_item_uid", None),
                getattr(slot, "vplib_uid", None),
            ),
            max_length=MAX_KEY_LENGTH,
        )

        return cls(
            event_uid=new_uid(),
            event_type=enum_value(event_type, default=UserInventoryAuditEventType.OTHER.value),
            user_id=normalized_user_id,
            inventory_key=normalized_inventory_key,
            state=state,
            state_id=getattr(state, "id", None),
            slot=slot,
            slot_id=getattr(slot, "id", None),
            slot_uid=getattr(slot, "slot_uid", None),
            slot_index=getattr(slot, "slot_index", None),
            target_type=clean_optional_string(data.get("target_type") or getattr(slot, "content_type", None), max_length=MAX_TARGET_TYPE_LENGTH),
            target_db_id=normalize_int(data.get("target_db_id"), default=None, minimum=1),
            target_uid=clean_optional_string(data.get("target_uid"), max_length=MAX_UID_LENGTH),
            target_key=target_key,
            collection_id=getattr(slot, "collection_id", None),
            collection_item_id=getattr(slot, "collection_item_id", None),
            item_db_id=getattr(slot, "item_db_id", None),
            variant_db_id=getattr(slot, "variant_db_id", None),
            vplib_uid=getattr(slot, "vplib_uid", None),
            family_id=getattr(slot, "family_id", None),
            package_id=getattr(slot, "package_id", None),
            variant_id=getattr(slot, "variant_id", None),
            taxonomy_path=getattr(slot, "taxonomy_path", None),
            before_json=normalize_json_mapping(before),
            after_json=normalize_json_mapping(after),
            diff_json=normalize_json_mapping(diff),
            payload=data,
            meta=normalize_json_mapping(data.get("meta")),
            metadata_json=normalize_json_mapping(metadata),
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "event_uid": self.event_uid,
            "event_type": self.event_type,
            "user_id": self.user_id,
            "inventory_key": self.inventory_key,
            "state_id": self.state_id,
            "slot_id": self.slot_id,
            "slot_uid": self.slot_uid,
            "slot_index": self.slot_index,
            "target_type": self.target_type,
            "target_db_id": self.target_db_id,
            "target_uid": self.target_uid,
            "target_key": self.target_key,
            "collection_id": self.collection_id,
            "collection_item_id": self.collection_item_id,
            "item_db_id": self.item_db_id,
            "variant_db_id": self.variant_db_id,
            "vplib_uid": self.vplib_uid,
            "family_id": self.family_id,
            "package_id": self.package_id,
            "variant_id": self.variant_id,
            "taxonomy_path": self.taxonomy_path,
            "before": normalize_json_mapping(self.before_json),
            "after": normalize_json_mapping(self.after_json),
            "diff": normalize_json_mapping(self.diff_json),
            "payload": normalize_json_mapping(self.payload),
            "meta": normalize_json_mapping(self.meta),
            "metadata": normalize_json_mapping(self.metadata_json),
            "created_at": self.created_at.isoformat() if self.created_at else None,
            "updated_at": self.updated_at.isoformat() if self.updated_at else None,
        }


# ---------------------------------------------------------------------------
# Factory helpers
# ---------------------------------------------------------------------------

def build_default_inventory_slots(
    *,
    user_id: Any = DEFAULT_USER_ID,
    inventory_key: Any = DEFAULT_INVENTORY_KEY,
    state: UserInventoryState | None = None,
    selected_slot_index: Any = MIN_SLOT_INDEX,
    metadata: Mapping[str, Any] | None = None,
) -> list[UserInventorySlot]:
    """Erstellt 9 leere Hotbar-Slots ohne DB-Zugriff."""
    selected_index = normalize_slot_index(selected_slot_index)

    return [
        UserInventorySlot.create_empty(
            user_id=user_id,
            inventory_key=inventory_key,
            slot_index=index,
            state=state,
            selected=index == selected_index,
            metadata=metadata,
        )
        for index in range(MIN_SLOT_INDEX, MAX_SLOT_INDEX + 1)
    ]


def build_inventory_snapshot(
    *,
    state: UserInventoryState | None,
    slots: Iterable[UserInventorySlot] | None,
) -> dict[str, Any]:
    """Baut API-freundlichen Inventar-Snapshot ohne DB-Zugriff."""
    slot_list = list(slots or [])
    slot_list.sort(key=lambda item: normalize_slot_index(getattr(item, "slot_index", MIN_SLOT_INDEX)))

    return {
        "state": state.to_dict(include_slots=False) if state is not None else None,
        "slots": [slot.to_dict() for slot in slot_list],
        "slot_count": len(slot_list),
        "expected_slot_count": DEFAULT_SLOT_COUNT,
        "min_slot_index": MIN_SLOT_INDEX,
        "max_slot_index": MAX_SLOT_INDEX,
        "snapshot_hash": stable_json_hash(
            {
                "state": state.to_dict(include_slots=False) if state is not None else None,
                "slots": [slot_payload_summary(slot) for slot in slot_list],
            }
        ),
    }


# ---------------------------------------------------------------------------
# Public model helpers
# ---------------------------------------------------------------------------

def iter_user_inventory_models() -> tuple[type[Any], ...]:
    """Gibt alle echten User-Inventar-Modelklassen zurück."""
    return (
        UserInventoryState,
        UserInventorySlot,
        UserInventoryAuditEvent,
    )


def iter_models() -> tuple[type[Any], ...]:
    """Kompatibler Alias für models.__init__.py."""
    return iter_user_inventory_models()


def get_models() -> tuple[type[Any], ...]:
    """Kompatibler Alias für Modelle-Discovery."""
    return iter_user_inventory_models()


def get_user_inventory_model_names() -> tuple[str, ...]:
    """Gibt die Namen aller User-Inventar-Modelle zurück."""
    return tuple(model.__name__ for model in iter_user_inventory_models())


def get_user_inventory_table_names() -> tuple[str, ...]:
    """Gibt die Tabellennamen aller User-Inventar-Modelle zurück."""
    return tuple(
        str(getattr(model, "__tablename__", ""))
        for model in iter_user_inventory_models()
    )


def get_user_inventory_models_health() -> dict[str, Any]:
    """Gibt einen JSON-kompatiblen Health-Snapshot dieser Model-Datei zurück."""
    models = iter_user_inventory_models()
    table_names = get_user_inventory_table_names()

    try:
        metadata = getattr(db, "metadata", None)
        tables = getattr(metadata, "tables", None)

        if tables is None:
            metadata_table_names: tuple[str, ...] = tuple()
        else:
            metadata_table_names = tuple(sorted(str(name) for name in tables.keys()))

        missing_tables = [table_name for table_name in table_names if table_name not in metadata_table_names]
        healthy = len(models) > 0 and len(table_names) > 0 and not missing_tables

        return {
            "ok": healthy,
            "healthy": healthy,
            "schema_version": USER_INVENTORY_MODELS_SCHEMA_VERSION,
            "model_count": len(models),
            "model_names": [model.__name__ for model in models],
            "table_count": len(table_names),
            "tables": list(table_names),
            "metadata_table_count": len(metadata_table_names),
            "metadata_table_names": list(metadata_table_names),
            "missing_tables": missing_tables,
            "default_user_id": DEFAULT_USER_ID,
            "default_inventory_key": DEFAULT_INVENTORY_KEY,
            "default_slot_count": DEFAULT_SLOT_COUNT,
            "min_slot_index": MIN_SLOT_INDEX,
            "max_slot_index": MAX_SLOT_INDEX,
            "uses_sqlalchemy_extension": True,
            "supports_user_state": True,
            "supports_user_slots": True,
            "supports_selected_slot": True,
            "supports_slot_items": True,
            "supports_collection_links": True,
            "supports_collection_item_links": True,
            "supports_variant_links": True,
            "supports_draft_links": True,
            "supports_custom_label_icon": True,
            "supports_audit_events": True,
        }
    except Exception as exc:
        return {
            "ok": False,
            "healthy": False,
            "schema_version": USER_INVENTORY_MODELS_SCHEMA_VERSION,
            "model_count": len(models),
            "model_names": [model.__name__ for model in models],
            "table_count": len(table_names),
            "tables": list(table_names),
            "error": f"{type(exc).__name__}: {exc}",
        }


def assert_user_inventory_models_ready() -> None:
    """Wirft RuntimeError, wenn die User-Inventory-Models nicht bereit sind."""
    health = get_user_inventory_models_health()

    if health.get("healthy"):
        return

    raise RuntimeError(f"User inventory models are not ready: {health}")


def clear_user_inventory_models_cache() -> dict[str, Any]:
    """Leert lokale Caches dieser Datei."""
    cleared: list[str] = []

    for cached_func in (
        _load_db,
        slot_key_for_index,
    ):
        try:
            cached_func.cache_clear()
            cleared.append(getattr(cached_func, "__name__", str(cached_func)))
        except Exception:
            continue

    return {
        "ok": True,
        "cleared": cleared,
    }


__all__ = [
    "DEFAULT_INVENTORY_KEY",
    "DEFAULT_SLOT_COUNT",
    "DEFAULT_USER_ID",
    "MAX_SLOT_INDEX",
    "MIN_SLOT_INDEX",
    "USER_INVENTORY_MODELS_SCHEMA_VERSION",

    # Enums
    "UserInventoryAuditEventType",
    "UserInventoryContentType",
    "UserInventoryMode",
    "UserInventorySource",
    "UserInventoryStatus",

    # Models
    "UserInventoryAuditEvent",
    "UserInventorySlot",
    "UserInventoryState",

    # Helpers
    "assert_user_inventory_models_ready",
    "build_default_inventory_slots",
    "build_inventory_snapshot",
    "clean_optional_string",
    "clean_required_string",
    "clean_string",
    "clear_user_inventory_models_cache",
    "enum_value",
    "extract_inventory_item_identity",
    "first_non_empty",
    "get_models",
    "get_user_inventory_model_names",
    "get_user_inventory_models_health",
    "get_user_inventory_table_names",
    "iter_models",
    "iter_user_inventory_models",
    "merge_json",
    "new_uid",
    "normalize_bool",
    "normalize_int",
    "normalize_json_list",
    "normalize_json_mapping",
    "normalize_json_value",
    "normalize_mode",
    "normalize_optional_string",
    "normalize_required_string",
    "normalize_slot_count",
    "normalize_slot_index",
    "normalize_source",
    "normalize_status",
    "normalize_user_id",
    "slot_key_for_index",
    "slot_payload_summary",
    "stable_json_hash",
    "taxonomy_path_for",
    "utc_now",
]