# models/user_inventory.py
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
- Keine Route.
- Kein db.create_all().
- Keine aktive DB-Verbindung.
- Keine Migration.
- Keine Seed-Logik.

Technische Namen, JSON-Keys und Variablen bleiben Englisch.
"""

from __future__ import annotations

from datetime import datetime, timezone
from functools import lru_cache
from typing import Any, Final, Iterable, Mapping


USER_INVENTORY_MODELS_SCHEMA_VERSION: Final[str] = "vectoplan_library.user_inventory.models.v1"
DEFAULT_USER_ID: Final[int] = 1
DEFAULT_INVENTORY_KEY: Final[str] = "default"
DEFAULT_SLOT_COUNT: Final[int] = 9
MIN_SLOT_INDEX: Final[int] = 1
MAX_SLOT_INDEX: Final[int] = 9


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
# Generic helpers
# ---------------------------------------------------------------------------

def utc_now() -> datetime:
    """
    Liefert eine timezone-aware UTC-Zeit.
    """

    return datetime.now(timezone.utc)


def clean_string(value: Any, *, fallback: str = "") -> str:
    """
    Normalisiert einen beliebigen Wert defensiv zu String.
    """

    try:
        if value is None:
            return fallback

        cleaned = str(value).strip()
        return cleaned if cleaned else fallback

    except Exception:
        return fallback


def clean_optional_string(value: Any, *, max_length: int | None = None) -> str | None:
    """
    Normalisiert optionalen String.
    """

    try:
        if value is None:
            return None

        cleaned = str(value).strip()

        if not cleaned:
            return None

        if max_length is not None and max_length > 0:
            return cleaned[:max_length]

        return cleaned

    except Exception:
        return None


def clean_required_string(value: Any, *, fallback: str, max_length: int | None = None) -> str:
    """
    Normalisiert Pflicht-String mit Fallback.
    """

    cleaned = clean_optional_string(value, max_length=max_length)

    if cleaned is not None:
        return cleaned

    fallback_cleaned = clean_string(fallback, fallback="default")

    if max_length is not None and max_length > 0:
        return fallback_cleaned[:max_length]

    return fallback_cleaned


def normalize_int(
    value: Any,
    *,
    default: int,
    minimum: int | None = None,
    maximum: int | None = None,
) -> int:
    """
    Normalisiert Integer mit optionalen Grenzen.
    """

    try:
        normalized = int(value)
    except Exception:
        normalized = int(default)

    if minimum is not None:
        normalized = max(int(minimum), normalized)

    if maximum is not None:
        normalized = min(int(maximum), normalized)

    return normalized


def normalize_slot_index(value: Any, *, default: int = MIN_SLOT_INDEX) -> int:
    """
    Normalisiert Slot-Indizes auf 1..9.
    """

    return normalize_int(
        value,
        default=default,
        minimum=MIN_SLOT_INDEX,
        maximum=MAX_SLOT_INDEX,
    )


def normalize_user_id(value: Any, *, default: int = DEFAULT_USER_ID) -> int:
    """
    Normalisiert User-ID.

    Phase 1:
    - Standard: user_id=1
    - Es wird keine User-Tabelle vorausgesetzt.
    """

    return normalize_int(value, default=default, minimum=1)


def normalize_bool(value: Any, *, default: bool = False) -> bool:
    """
    Normalisiert Bool-Werte aus Python-/JSON-/Form-ähnlichen Eingaben.
    """

    if isinstance(value, bool):
        return value

    if value is None:
        return default

    text = clean_string(value).lower()

    if text in {"1", "true", "yes", "ja", "on", "enabled", "active", "selected"}:
        return True

    if text in {"0", "false", "no", "nein", "off", "disabled", "inactive"}:
        return False

    return default


def normalize_json_mapping(value: Any) -> dict[str, Any]:
    """
    Normalisiert Mapping-Werte JSON-kompatibel.
    """

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
    """
    Normalisiert Listenwerte JSON-kompatibel.
    """

    if value is None:
        return []

    if isinstance(value, list):
        return [normalize_json_value(item) for item in value]

    if isinstance(value, tuple):
        return [normalize_json_value(item) for item in value]

    if isinstance(value, set):
        return [normalize_json_value(item) for item in sorted(value, key=str)]

    return []


def normalize_json_value(value: Any) -> Any:
    """
    Normalisiert beliebige Werte JSON-kompatibel.
    """

    if value is None or isinstance(value, (str, int, float, bool)):
        return value

    if isinstance(value, datetime):
        return value.isoformat()

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


def slot_key_for_index(slot_index: Any) -> str:
    """
    Erzeugt stabilen Slot-Key für 1..9.
    """

    return f"user-slot-{normalize_slot_index(slot_index)}"


def taxonomy_path_for(
    *,
    domain: Any = None,
    category: Any = None,
    subcategory: Any = None,
) -> str | None:
    """
    Baut einen Taxonomie-Pfad aus Domain/Kategorie/Subkategorie.
    """

    parts = [
        clean_optional_string(domain, max_length=80),
        clean_optional_string(category, max_length=120),
        clean_optional_string(subcategory, max_length=120),
    ]

    cleaned_parts = [part for part in parts if part]

    if not cleaned_parts:
        return None

    return "/".join(cleaned_parts)


# ---------------------------------------------------------------------------
# Mixins
# ---------------------------------------------------------------------------

class TimestampMixin:
    """
    Gemeinsame created_at/updated_at-Felder.
    """

    created_at = db.Column(db.DateTime(timezone=True), nullable=False, default=utc_now)
    updated_at = db.Column(db.DateTime(timezone=True), nullable=False, default=utc_now, onupdate=utc_now)

    def touch(self) -> None:
        """
        Aktualisiert updated_at defensiv.
        """

        try:
            self.updated_at = utc_now()
        except Exception:
            pass


class JsonMixin:
    """
    Gemeinsame JSON-Normalisierung.
    """

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
    - welche Item-/Block-Metadaten zuletzt selektiert waren

    Phase 1:
    - user_id default 1
    - inventory_key default "default"
    - active_slot_index 1..9
    """

    __tablename__ = "user_inventory_states"

    id = db.Column(db.BigInteger, primary_key=True, autoincrement=True)

    user_id = db.Column(db.BigInteger, nullable=False, default=DEFAULT_USER_ID, index=True)
    inventory_key = db.Column(db.String(120), nullable=False, default=DEFAULT_INVENTORY_KEY, index=True)

    active_slot_index = db.Column(db.Integer, nullable=False, default=MIN_SLOT_INDEX)
    last_selected_slot_index = db.Column(db.Integer, nullable=False, default=MIN_SLOT_INDEX)
    last_selected_slot_key = db.Column(db.String(120), nullable=False, default=slot_key_for_index(MIN_SLOT_INDEX))

    last_selected_item_db_id = db.Column(
        db.BigInteger,
        db.ForeignKey("creative_library_items.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )
    last_selected_vplib_uid = db.Column(db.String(80), nullable=True, index=True)
    last_selected_family_id = db.Column(db.String(255), nullable=True, index=True)
    last_selected_package_id = db.Column(db.String(255), nullable=True, index=True)
    last_selected_variant_id = db.Column(db.String(160), nullable=True, index=True)
    last_selected_label = db.Column(db.String(255), nullable=True)
    last_selected_object_kind = db.Column(db.String(80), nullable=True, index=True)

    last_selected_domain = db.Column(db.String(80), nullable=True, index=True)
    last_selected_category = db.Column(db.String(120), nullable=True, index=True)
    last_selected_subcategory = db.Column(db.String(120), nullable=True, index=True)
    last_selected_taxonomy_path = db.Column(db.String(512), nullable=True)

    slot_count = db.Column(db.Integer, nullable=False, default=DEFAULT_SLOT_COUNT)
    source = db.Column(db.String(60), nullable=False, default="user")
    scope = db.Column(db.String(60), nullable=False, default="editor")
    mode = db.Column(db.String(60), nullable=False, default="creative")

    selected_at = db.Column(db.DateTime(timezone=True), nullable=True)
    last_loaded_at = db.Column(db.DateTime(timezone=True), nullable=True)
    last_synced_at = db.Column(db.DateTime(timezone=True), nullable=True)

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

    last_selected_item = db.relationship(
        "CreativeLibraryItem",
        foreign_keys=[last_selected_item_db_id],
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
    ) -> "UserInventoryState":
        """
        Erstellt einen Default-State ohne DB-Zugriff.
        """

        normalized_slot_index = normalize_slot_index(active_slot_index)

        return cls(
            user_id=normalize_user_id(user_id),
            inventory_key=clean_required_string(
                inventory_key,
                fallback=DEFAULT_INVENTORY_KEY,
                max_length=120,
            ),
            active_slot_index=normalized_slot_index,
            last_selected_slot_index=normalized_slot_index,
            last_selected_slot_key=slot_key_for_index(normalized_slot_index),
            slot_count=DEFAULT_SLOT_COUNT,
            source="user",
            scope="editor",
            mode="creative",
            selected_at=utc_now(),
            payload={},
            settings={},
            metadata_json=normalize_json_mapping(metadata),
        )

    def select_slot(self, slot: "UserInventorySlot | None" = None, *, slot_index: Any | None = None) -> None:
        """
        Aktualisiert den aktiven und zuletzt ausgewählten Slot.

        Wenn ein Slot-Objekt übergeben wird, werden relevante Item-Daten als Snapshot
        in den State übernommen.
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

        self.last_selected_item_db_id = slot.item_db_id
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

    def to_dict(self, *, include_slots: bool = False) -> dict[str, Any]:
        """
        Serialisiert den State API-freundlich.
        """

        data = {
            "id": self.id,
            "user_id": self.user_id,
            "inventory_key": self.inventory_key,
            "active_slot_index": self.active_slot_index,
            "last_selected_slot_index": self.last_selected_slot_index,
            "last_selected_slot_key": self.last_selected_slot_key,
            "last_selected": {
                "item_db_id": self.last_selected_item_db_id,
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
            "selected_at": self.selected_at.isoformat() if self.selected_at else None,
            "last_loaded_at": self.last_loaded_at.isoformat() if self.last_loaded_at else None,
            "last_synced_at": self.last_synced_at.isoformat() if self.last_synced_at else None,
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

    state_id = db.Column(
        db.BigInteger,
        db.ForeignKey("user_inventory_states.id", ondelete="CASCADE"),
        nullable=True,
        index=True,
    )

    user_id = db.Column(db.BigInteger, nullable=False, default=DEFAULT_USER_ID, index=True)
    inventory_key = db.Column(db.String(120), nullable=False, default=DEFAULT_INVENTORY_KEY, index=True)

    slot_index = db.Column(db.Integer, nullable=False)
    slot_key = db.Column(db.String(120), nullable=False, index=True)

    item_db_id = db.Column(
        db.BigInteger,
        db.ForeignKey("creative_library_items.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )

    vplib_uid = db.Column(db.String(80), nullable=True, index=True)
    family_id = db.Column(db.String(255), nullable=True, index=True)
    package_id = db.Column(db.String(255), nullable=True, index=True)
    variant_id = db.Column(db.String(160), nullable=True, index=True)

    label = db.Column(db.String(255), nullable=True)
    description = db.Column(db.Text, nullable=True)
    object_kind = db.Column(db.String(80), nullable=True, index=True)

    domain = db.Column(db.String(80), nullable=True, index=True)
    category = db.Column(db.String(120), nullable=True, index=True)
    subcategory = db.Column(db.String(120), nullable=True, index=True)
    taxonomy_path = db.Column(db.String(512), nullable=True)

    quantity = db.Column(db.Integer, nullable=False, default=0)
    empty = db.Column(db.Boolean, nullable=False, default=True, index=True)
    selected = db.Column(db.Boolean, nullable=False, default=False, index=True)
    active = db.Column(db.Boolean, nullable=False, default=True, index=True)
    locked = db.Column(db.Boolean, nullable=False, default=False)
    pinned = db.Column(db.Boolean, nullable=False, default=False)

    source = db.Column(db.String(60), nullable=False, default="user")
    scope = db.Column(db.String(60), nullable=False, default="editor")
    mode = db.Column(db.String(60), nullable=False, default="creative")

    sort_order = db.Column(db.Integer, nullable=False, default=0)

    icon = db.Column(db.JSON, nullable=False, default=dict)
    preview = db.Column(db.JSON, nullable=False, default=dict)
    assets = db.Column(db.JSON, nullable=False, default=list)
    variant = db.Column(db.JSON, nullable=False, default=dict)
    placement = db.Column(db.JSON, nullable=False, default=dict)

    selected_at = db.Column(db.DateTime(timezone=True), nullable=True)
    assigned_at = db.Column(db.DateTime(timezone=True), nullable=True)
    cleared_at = db.Column(db.DateTime(timezone=True), nullable=True)

    payload = db.Column(db.JSON, nullable=False, default=dict)
    meta = db.Column(db.JSON, nullable=False, default=dict)
    metadata_json = db.Column(db.JSON, nullable=False, default=dict)

    state = db.relationship(
        "UserInventoryState",
        back_populates="slots",
        lazy="joined",
    )

    item = db.relationship(
        "CreativeLibraryItem",
        foreign_keys=[item_db_id],
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
            "ix_user_inventory_slot_taxonomy",
            "domain",
            "category",
            "subcategory",
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
        """
        Erstellt einen leeren Slot ohne DB-Zugriff.
        """

        normalized_slot_index = normalize_slot_index(slot_index)

        return cls(
            state=state,
            state_id=getattr(state, "id", None),
            user_id=normalize_user_id(user_id if user_id is not None else getattr(state, "user_id", DEFAULT_USER_ID)),
            inventory_key=clean_required_string(
                inventory_key if inventory_key is not None else getattr(state, "inventory_key", DEFAULT_INVENTORY_KEY),
                fallback=DEFAULT_INVENTORY_KEY,
                max_length=120,
            ),
            slot_index=normalized_slot_index,
            slot_key=slot_key_for_index(normalized_slot_index),
            quantity=0,
            empty=True,
            selected=bool(selected),
            active=True,
            locked=False,
            pinned=False,
            source="user",
            scope="editor",
            mode="creative",
            sort_order=normalized_slot_index,
            icon={},
            preview={},
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
        """
        Erstellt einen gefüllten Slot aus einem API-/Library-Payload.
        """

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
        - vplib_uid
        - family_id
        - package_id
        - variant_id
        - label/name
        - object_kind
        - domain/category/subcategory
        """

        payload = normalize_json_mapping(item_payload)

        item_db_id = payload.get("item_db_id", payload.get("id"))
        self.item_db_id = normalize_int(item_db_id, default=0, minimum=0) or None

        self.vplib_uid = clean_optional_string(payload.get("vplib_uid"), max_length=80)
        self.family_id = clean_optional_string(payload.get("family_id"), max_length=255)
        self.package_id = clean_optional_string(payload.get("package_id"), max_length=255)
        self.variant_id = clean_optional_string(payload.get("variant_id"), max_length=160)

        self.label = clean_optional_string(payload.get("label", payload.get("name")), max_length=255)
        self.description = clean_optional_string(payload.get("description"))
        self.object_kind = clean_optional_string(payload.get("object_kind"), max_length=80)

        self.domain = clean_optional_string(payload.get("domain"), max_length=80)
        self.category = clean_optional_string(payload.get("category"), max_length=120)
        self.subcategory = clean_optional_string(payload.get("subcategory"), max_length=120)
        self.taxonomy_path = clean_optional_string(
            payload.get("taxonomy_path")
            or taxonomy_path_for(
                domain=self.domain,
                category=self.category,
                subcategory=self.subcategory,
            ),
            max_length=512,
        )

        self.quantity = normalize_int(payload.get("quantity"), default=1, minimum=1)
        self.empty = False
        self.assigned_at = utc_now()
        self.cleared_at = None

        self.icon = normalize_json_mapping(payload.get("icon"))
        self.preview = normalize_json_mapping(payload.get("preview"))
        self.assets = normalize_json_list(payload.get("assets"))
        self.variant = normalize_json_mapping(payload.get("variant"))
        self.placement = normalize_json_mapping(payload.get("placement"))

        self.payload = payload
        self.meta = normalize_json_mapping(payload.get("meta"))
        self.metadata_json = normalize_json_mapping(payload.get("metadata", self.metadata_json))

        self.touch()

    def clear_item(self) -> None:
        """
        Leert den Slot, ohne User-/Slot-Identität zu entfernen.
        """

        self.item_db_id = None

        self.vplib_uid = None
        self.family_id = None
        self.package_id = None
        self.variant_id = None

        self.label = None
        self.description = None
        self.object_kind = None

        self.domain = None
        self.category = None
        self.subcategory = None
        self.taxonomy_path = None

        self.quantity = 0
        self.empty = True
        self.assigned_at = None
        self.cleared_at = utc_now()

        self.icon = {}
        self.preview = {}
        self.assets = []
        self.variant = {}
        self.placement = {}

        self.payload = {}
        self.meta = {}

        self.touch()

    def mark_selected(self, *, selected: bool = True) -> None:
        """
        Markiert den Slot als ausgewählt oder nicht ausgewählt.
        """

        self.selected = bool(selected)

        if selected:
            self.selected_at = utc_now()

        self.touch()

    def to_dict(self) -> dict[str, Any]:
        """
        Serialisiert den Slot API-freundlich.
        """

        return {
            "id": self.id,
            "state_id": self.state_id,
            "user_id": self.user_id,
            "inventory_key": self.inventory_key,
            "slot_index": self.slot_index,
            "slot_key": self.slot_key or slot_key_for_index(self.slot_index),
            "item_db_id": self.item_db_id,
            "vplib_uid": self.vplib_uid,
            "family_id": self.family_id,
            "package_id": self.package_id,
            "variant_id": self.variant_id,
            "label": self.label,
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
            "sort_order": self.sort_order,
            "icon": normalize_json_mapping(self.icon),
            "preview": normalize_json_mapping(self.preview),
            "assets": normalize_json_list(self.assets),
            "variant": normalize_json_mapping(self.variant),
            "placement": normalize_json_mapping(self.placement),
            "selected_at": self.selected_at.isoformat() if self.selected_at else None,
            "assigned_at": self.assigned_at.isoformat() if self.assigned_at else None,
            "cleared_at": self.cleared_at.isoformat() if self.cleared_at else None,
            "payload": normalize_json_mapping(self.payload),
            "meta": normalize_json_mapping(self.meta),
            "metadata": normalize_json_mapping(self.metadata_json),
            "created_at": self.created_at.isoformat() if self.created_at else None,
            "updated_at": self.updated_at.isoformat() if self.updated_at else None,
        }


# ---------------------------------------------------------------------------
# Public model helpers
# ---------------------------------------------------------------------------

def iter_user_inventory_models() -> tuple[type[Any], ...]:
    """
    Gibt alle echten User-Inventar-Modelklassen zurück.
    """

    return (
        UserInventoryState,
        UserInventorySlot,
    )


def get_user_inventory_model_names() -> tuple[str, ...]:
    """
    Gibt die Namen aller User-Inventar-Modelle zurück.
    """

    return tuple(model.__name__ for model in iter_user_inventory_models())


def get_user_inventory_table_names() -> tuple[str, ...]:
    """
    Gibt die Tabellennamen aller User-Inventar-Modelle zurück.
    """

    return tuple(
        str(getattr(model, "__tablename__", ""))
        for model in iter_user_inventory_models()
    )


def get_user_inventory_models_health() -> dict[str, Any]:
    """
    Gibt einen JSON-kompatiblen Health-Snapshot dieser Model-Datei zurück.
    """

    models = iter_user_inventory_models()
    table_names = get_user_inventory_table_names()

    return {
        "ok": True,
        "healthy": True,
        "schema_version": USER_INVENTORY_MODELS_SCHEMA_VERSION,
        "model_count": len(models),
        "model_names": [model.__name__ for model in models],
        "table_count": len(table_names),
        "tables": list(table_names),
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
    }


__all__ = [
    "DEFAULT_INVENTORY_KEY",
    "DEFAULT_SLOT_COUNT",
    "DEFAULT_USER_ID",
    "MAX_SLOT_INDEX",
    "MIN_SLOT_INDEX",
    "USER_INVENTORY_MODELS_SCHEMA_VERSION",
    "UserInventorySlot",
    "UserInventoryState",
    "clean_optional_string",
    "clean_required_string",
    "clean_string",
    "get_user_inventory_model_names",
    "get_user_inventory_models_health",
    "get_user_inventory_table_names",
    "iter_user_inventory_models",
    "normalize_bool",
    "normalize_int",
    "normalize_json_list",
    "normalize_json_mapping",
    "normalize_json_value",
    "normalize_slot_index",
    "normalize_user_id",
    "slot_key_for_index",
    "taxonomy_path_for",
    "utc_now",
]