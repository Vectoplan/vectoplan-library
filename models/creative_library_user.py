# services/vectoplan-library/models/creative_library_user.py
"""
Database models for user-specific Creative Library state.

Diese Datei modelliert die User-Sicht auf die Creative Library:

- System-/Standard-Collections
- User-eigene Collections
- Zuordnung von Creative-Library-Items zu Collections
- User-Overrides auf Items, Varianten, Taxonomie oder Collection-Items
- User-Audit für add/remove/hide/restore/update/favorite/publish

Ziel:

    Published Creative Library
        -> system default collection
        -> user collection additions
        -> user overrides
        -> resolved creative inventory for user_id
        -> Editor / Creative-Inventar / User-Hotbar

Wichtige Architekturregeln:

- Diese Datei erzeugt keine Tabellen.
- Diese Datei führt keine Migration aus.
- Diese Datei führt kein db.create_all() aus.
- Diese Datei spricht keine Datenbankverbindung aktiv an.
- Diese Datei erzeugt keine VPLIB-UIDs.
- Diese Datei verändert keine CreativeLibraryItem/Variant-Daten direkt.
- User-Änderungen werden als Collection-Items, Overrides und Audit Events gespeichert.
- Die Standardbibliothek bleibt system-owned.
- owner_user_id=None bedeutet system-owned.
- owner_scope="system" bedeutet globale Standardbibliothek.
- owner_scope="user:<id>" bedeutet User-Erweiterung.
- Technische Namen, JSON-Keys und Variablen bleiben Englisch.

Phase 1:

- user_id darf weiterhin 1 sein.
- Ein User bekommt die System-Default-Collection plus eigene Änderungen.
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

CREATIVE_LIBRARY_USER_MODELS_SCHEMA_VERSION: Final[str] = "vectoplan_library.creative_library_user.models.v1"
DEFAULT_USER_ID: Final[int] = 1
DEFAULT_COLLECTION_KEY: Final[str] = "default"
DEFAULT_USER_COLLECTION_KEY: Final[str] = "user-default"

MAX_UID_LENGTH: Final[int] = 80
MAX_KEY_LENGTH: Final[int] = 255
MAX_SHORT_KEY_LENGTH: Final[int] = 160
MAX_LABEL_LENGTH: Final[int] = 255
MAX_STATUS_LENGTH: Final[int] = 40
MAX_SOURCE_SCOPE_LENGTH: Final[int] = 40
MAX_OWNER_SCOPE_LENGTH: Final[int] = 120
MAX_COLLECTION_KEY_LENGTH: Final[int] = 120
MAX_TARGET_TYPE_LENGTH: Final[int] = 120
MAX_ACTION_LENGTH: Final[int] = 80
MAX_VPLIB_UID_LENGTH: Final[int] = 80
MAX_FAMILY_ID_LENGTH: Final[int] = 255
MAX_PACKAGE_ID_LENGTH: Final[int] = 255
MAX_VARIANT_ID_LENGTH: Final[int] = 160
MAX_OBJECT_KIND_LENGTH: Final[int] = 80
MAX_TAXONOMY_PART_LENGTH: Final[int] = 120
MAX_TAXONOMY_PATH_LENGTH: Final[int] = 512
MAX_HASH_LENGTH: Final[int] = 128


# ---------------------------------------------------------------------------
# SQLAlchemy extension import
# ---------------------------------------------------------------------------

@lru_cache(maxsize=1)
def _load_db() -> Any:
    """
    Lädt die zentrale Flask-SQLAlchemy Extension defensiv.

    Erwarteter Service-Standard:

        services/vectoplan-library/extensions.py

    mit:

        db = SQLAlchemy()

    Diese Funktion ist bewusst tolerant gegenüber mehreren Import-Pfaden, weil
    der Service lokal, im Container, über Tests und über Flask-Migrate leicht
    unterschiedliche PYTHONPATH-Kontexte haben kann.
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

class CreativeLibraryUserSourceScope(str, enum.Enum):
    SYSTEM = "system"
    USER = "user"
    IMPORTED = "imported"
    GENERATED = "generated"

    @property
    def key(self) -> str:
        return str(self.value)


class CreativeLibraryUserStatus(str, enum.Enum):
    DRAFT = "draft"
    ACTIVE = "active"
    INACTIVE = "inactive"
    HIDDEN = "hidden"
    ARCHIVED = "archived"
    DELETED = "deleted"

    @property
    def key(self) -> str:
        return str(self.value)


class CreativeLibraryCollectionKind(str, enum.Enum):
    SYSTEM_DEFAULT = "system_default"
    USER_DEFAULT = "user_default"
    USER_CUSTOM = "user_custom"
    PROJECT = "project"
    FAVORITES = "favorites"
    GENERATED = "generated"
    IMPORTED = "imported"

    @property
    def key(self) -> str:
        return str(self.value)


class CreativeLibraryUserOverrideAction(str, enum.Enum):
    HIDE = "hide"
    RESTORE = "restore"
    RENAME = "rename"
    REORDER = "reorder"
    FAVORITE = "favorite"
    UNFAVORITE = "unfavorite"
    PIN = "pin"
    UNPIN = "unpin"
    REMOVE = "remove"
    ADD = "add"
    PATCH = "patch"
    DELETE = "delete"

    @property
    def key(self) -> str:
        return str(self.value)


class CreativeLibraryUserTargetType(str, enum.Enum):
    COLLECTION = "collection"
    COLLECTION_ITEM = "collection_item"
    CREATIVE_ITEM = "creative_item"
    CREATIVE_VARIANT = "creative_variant"
    TAXONOMY_NODE = "taxonomy_node"
    DEFINITION = "definition"
    FILE = "file"
    DRAFT = "draft"
    OTHER = "other"

    @property
    def key(self) -> str:
        return str(self.value)


class CreativeLibraryUserAuditEventType(str, enum.Enum):
    COLLECTION_CREATED = "collection_created"
    COLLECTION_UPDATED = "collection_updated"
    COLLECTION_DELETED = "collection_deleted"
    ITEM_ADDED = "item_added"
    ITEM_REMOVED = "item_removed"
    ITEM_HIDDEN = "item_hidden"
    ITEM_RESTORED = "item_restored"
    ITEM_REORDERED = "item_reordered"
    ITEM_FAVORITED = "item_favorited"
    ITEM_UNFAVORITED = "item_unfavorited"
    OVERRIDE_CREATED = "override_created"
    OVERRIDE_UPDATED = "override_updated"
    OVERRIDE_DELETED = "override_deleted"
    USER_LIBRARY_RESOLVED = "user_library_resolved"
    OTHER = "other"

    @property
    def key(self) -> str:
        return str(self.value)


# ---------------------------------------------------------------------------
# Generic helpers
# ---------------------------------------------------------------------------

def utc_now() -> datetime:
    """Timezone-aware UTC timestamp."""
    return datetime.now(timezone.utc)


def new_uid() -> str:
    """Stable lowercase UUID string for DB technical IDs."""
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
    """Normalisiert defensiv zu String."""
    try:
        if value is None:
            return fallback

        text = str(value).replace("\x00", "").strip()
        return text if text else fallback
    except Exception:
        return fallback


def normalize_optional_string(value: Any, *, max_length: int | None = None) -> str | None:
    """Normalisiert optionale Strings."""
    if value is None:
        return None

    try:
        text = str(value).replace("\x00", "").strip()
    except Exception:
        return None

    if not text:
        return None

    if max_length is not None and max_length > 0:
        text = text[:max_length]

    return text


def normalize_required_string(value: Any, *, field_name: str, max_length: int | None = None) -> str:
    """Normalisiert Pflicht-Strings."""
    text = normalize_optional_string(value, max_length=max_length)
    if not text:
        raise ValueError(f"{field_name} is required.")
    return text


def normalize_bool(value: Any, *, default: bool = False) -> bool:
    """Robuste Bool-Normalisierung."""
    if value is None:
        return default

    if isinstance(value, bool):
        return value

    text = clean_string(value).lower()

    if text in {"1", "true", "yes", "y", "ja", "on", "enabled", "active", "visible", "published", "selected"}:
        return True

    if text in {"0", "false", "no", "n", "nein", "off", "disabled", "inactive", "hidden", "deleted"}:
        return False

    return default


def normalize_optional_bool(value: Any) -> bool | None:
    """Normalisiert optionalen Boolean. Unbekannt bleibt None."""
    if value is None:
        return None

    if isinstance(value, bool):
        return value

    text = clean_string(value).lower()

    if text in {"1", "true", "yes", "y", "ja", "on", "enabled", "active", "visible", "published", "selected"}:
        return True

    if text in {"0", "false", "no", "n", "nein", "off", "disabled", "inactive", "hidden", "deleted"}:
        return False

    return None


def normalize_int(
    value: Any,
    *,
    default: int | None = 0,
    minimum: int | None = None,
    maximum: int | None = None,
) -> int | None:
    """Robuste Integer-Normalisierung."""
    if value is None and default is None:
        return None

    try:
        result = int(value)
    except Exception:
        if default is None:
            return None
        result = int(default)

    if minimum is not None:
        result = max(int(minimum), result)

    if maximum is not None:
        result = min(int(maximum), result)

    return result


def normalize_user_id(value: Any, *, default: int | None = DEFAULT_USER_ID) -> int | None:
    """Normalisiert User-ID. None bleibt None, wenn default=None."""
    return normalize_int(value, default=default, minimum=1)


def normalize_json_mapping(value: Mapping[str, Any] | None) -> dict[str, Any]:
    """Normalisiert JSON-Mapping defensiv."""
    if value is None:
        return {}

    if not isinstance(value, Mapping):
        return {"value": normalize_json_value(value)}

    result: dict[str, Any] = {}

    for key, child_value in value.items():
        try:
            result[str(key)] = normalize_json_value(child_value)
        except Exception:
            result[str(key)] = str(child_value)

    return result


def normalize_json_list(value: Iterable[Any] | None) -> list[Any]:
    """Normalisiert JSON-Listen defensiv."""
    if value is None:
        return []

    if isinstance(value, Mapping):
        return [normalize_json_mapping(value)]

    if isinstance(value, (str, bytes, bytearray)):
        return [normalize_json_value(value)]

    try:
        return [normalize_json_value(item) for item in value]
    except Exception:
        return [str(value)]


def normalize_json_value(value: Any) -> Any:
    """Normalisiert Werte JSON-kompatibel."""
    if value is None:
        return None

    if isinstance(value, (str, int, float, bool)):
        return value

    if isinstance(value, datetime):
        return value.isoformat()

    if isinstance(value, enum.Enum):
        return value.value

    if isinstance(value, Mapping):
        return normalize_json_mapping(value)

    if isinstance(value, (list, tuple, set)):
        return [normalize_json_value(item) for item in value]

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


def normalize_source_scope(value: Any, *, default: str = CreativeLibraryUserSourceScope.USER.value) -> str:
    """Normalisiert source_scope."""
    text = enum_value(value, default=default).strip().lower()

    aliases = {
        "core": CreativeLibraryUserSourceScope.SYSTEM.value,
        "default": CreativeLibraryUserSourceScope.SYSTEM.value,
        "global": CreativeLibraryUserSourceScope.SYSTEM.value,
        "system": CreativeLibraryUserSourceScope.SYSTEM.value,
        "user": CreativeLibraryUserSourceScope.USER.value,
        "custom": CreativeLibraryUserSourceScope.USER.value,
        "import": CreativeLibraryUserSourceScope.IMPORTED.value,
        "imported": CreativeLibraryUserSourceScope.IMPORTED.value,
        "generated": CreativeLibraryUserSourceScope.GENERATED.value,
        "generator": CreativeLibraryUserSourceScope.GENERATED.value,
    }

    return aliases.get(text, text if text else default)[:MAX_SOURCE_SCOPE_LENGTH]


def owner_scope_for(
    *,
    source_scope: Any = CreativeLibraryUserSourceScope.USER.value,
    owner_user_id: Any = DEFAULT_USER_ID,
) -> str:
    """
    Baut einen stabilen owner_scope.

    PostgreSQL behandelt NULL in UniqueConstraints nicht als gleich.
    Deshalb wird zusätzlich ein nicht-nullbarer owner_scope gespeichert.
    """

    scope = normalize_source_scope(source_scope)
    user_id = normalize_user_id(owner_user_id, default=None)

    if scope == CreativeLibraryUserSourceScope.SYSTEM.value and user_id is None:
        return CreativeLibraryUserSourceScope.SYSTEM.value

    if scope == CreativeLibraryUserSourceScope.USER.value:
        return f"user:{user_id or DEFAULT_USER_ID}"

    if user_id is not None:
        return f"{scope}:{user_id}"

    return scope or CreativeLibraryUserSourceScope.USER.value


def normalize_status(
    value: Any,
    *,
    default: str = CreativeLibraryUserStatus.ACTIVE.value,
    active: Any = None,
    visible: Any = None,
) -> str:
    """Normalisiert Status mit aktiv/visible-Fallback."""
    if value is not None:
        text = enum_value(value, default=default).strip().lower()
        return text[:MAX_STATUS_LENGTH] if text else default

    if active is not None and not normalize_bool(active, default=True):
        return CreativeLibraryUserStatus.INACTIVE.value

    if visible is not None and not normalize_bool(visible, default=True):
        return CreativeLibraryUserStatus.HIDDEN.value

    return default


@lru_cache(maxsize=4096)
def _cached_slugify(value: str, max_length: int = MAX_SHORT_KEY_LENGTH) -> str:
    """Cached slugify für Collection Keys."""
    replacements = {
        "ä": "ae",
        "ö": "oe",
        "ü": "ue",
        "ß": "ss",
        "Ä": "ae",
        "Ö": "oe",
        "Ü": "ue",
    }

    text = value

    for source, target in replacements.items():
        text = text.replace(source, target)

    text = text.strip().lower()
    text = text.replace("\\", "/")
    text = text.replace("/", "-")
    text = text.replace(".", "-")
    text = text.replace("_", "-")

    cleaned: list[str] = []
    previous_dash = False

    for char in text:
        if char.isalnum():
            cleaned.append(char)
            previous_dash = False
            continue

        if char == "-":
            if not previous_dash:
                cleaned.append("-")
                previous_dash = True
            continue

        if not previous_dash:
            cleaned.append("-")
            previous_dash = True

    result = "".join(cleaned).strip("-")
    return result[:max_length] if result else ""


def normalize_collection_key(value: Any, *, fallback: str = DEFAULT_USER_COLLECTION_KEY) -> str:
    """Normalisiert Collection-Key."""
    text = normalize_optional_string(value, max_length=MAX_COLLECTION_KEY_LENGTH)
    if not text:
        text = fallback

    slug = _cached_slugify(text, MAX_COLLECTION_KEY_LENGTH)
    return slug or fallback


def normalize_taxonomy_part(value: Any, *, max_length: int = MAX_TAXONOMY_PART_LENGTH) -> str | None:
    """Normalisiert Taxonomie-Part."""
    text = normalize_optional_string(value, max_length=max_length)
    if not text:
        return None

    slug = _cached_slugify(text, max_length)
    return slug or None


def taxonomy_path_for(
    *,
    domain: Any = None,
    category: Any = None,
    subcategory: Any = None,
) -> str | None:
    """Baut Taxonomiepfad aus Domain/Kategorie/Subkategorie."""
    parts = [
        normalize_taxonomy_part(domain),
        normalize_taxonomy_part(category),
        normalize_taxonomy_part(subcategory),
    ]

    cleaned = [part for part in parts if part]
    return "/".join(cleaned) if cleaned else None


def normalize_action(value: Any, *, default: str = CreativeLibraryUserOverrideAction.PATCH.value) -> str:
    """Normalisiert User-Action."""
    text = enum_value(value, default=default).strip().lower()
    aliases = {
        "remove_from_user_library": CreativeLibraryUserOverrideAction.REMOVE.value,
        "removed": CreativeLibraryUserOverrideAction.REMOVE.value,
        "unhide": CreativeLibraryUserOverrideAction.RESTORE.value,
        "show": CreativeLibraryUserOverrideAction.RESTORE.value,
        "rename": CreativeLibraryUserOverrideAction.RENAME.value,
        "sort": CreativeLibraryUserOverrideAction.REORDER.value,
    }

    return aliases.get(text, text or default)[:MAX_ACTION_LENGTH]


def normalize_target_type(value: Any, *, default: str = CreativeLibraryUserTargetType.OTHER.value) -> str:
    """Normalisiert Target-Type."""
    text = enum_value(value, default=default).strip().lower()

    aliases = {
        "item": CreativeLibraryUserTargetType.CREATIVE_ITEM.value,
        "family": CreativeLibraryUserTargetType.CREATIVE_ITEM.value,
        "vplib": CreativeLibraryUserTargetType.CREATIVE_ITEM.value,
        "variant": CreativeLibraryUserTargetType.CREATIVE_VARIANT.value,
        "collection_item": CreativeLibraryUserTargetType.COLLECTION_ITEM.value,
        "taxonomy": CreativeLibraryUserTargetType.TAXONOMY_NODE.value,
        "taxonomy_node": CreativeLibraryUserTargetType.TAXONOMY_NODE.value,
    }

    return aliases.get(text, text or default)[:MAX_TARGET_TYPE_LENGTH]


def extract_item_identity(payload: Mapping[str, Any] | None) -> dict[str, Any]:
    """
    Extrahiert Creative-Library-Identität aus einem Payload.

    Unterstützt bewusst unterschiedliche API-Feldnamen, weil Published API,
    DB-Models, Scanner und UI teilweise unterschiedliche Key-Konventionen haben.
    """

    data = normalize_json_mapping(payload)

    item_db_id = normalize_int(
        first_non_empty(
            data.get("item_db_id"),
            data.get("family_db_id"),
            data.get("creative_item_id"),
            data.get("creativeLibraryItemId"),
            data.get("id"),
        ),
        default=None,
        minimum=1,
    )

    variant_db_id = normalize_int(
        first_non_empty(
            data.get("variant_db_id"),
            data.get("creative_variant_id"),
            data.get("variantIdDb"),
        ),
        default=None,
        minimum=1,
    )

    domain = normalize_taxonomy_part(data.get("domain"))
    category = normalize_taxonomy_part(data.get("category"))
    subcategory = normalize_taxonomy_part(data.get("subcategory"))
    taxonomy_path = normalize_optional_string(data.get("taxonomy_path"), max_length=MAX_TAXONOMY_PATH_LENGTH) or taxonomy_path_for(
        domain=domain,
        category=category,
        subcategory=subcategory,
    )

    return {
        "item_db_id": item_db_id,
        "variant_db_id": variant_db_id,
        "vplib_uid": normalize_optional_string(data.get("vplib_uid") or data.get("vplibUid"), max_length=MAX_VPLIB_UID_LENGTH),
        "family_id": normalize_optional_string(data.get("family_id") or data.get("familyId"), max_length=MAX_FAMILY_ID_LENGTH),
        "package_id": normalize_optional_string(data.get("package_id") or data.get("packageId"), max_length=MAX_PACKAGE_ID_LENGTH),
        "variant_id": normalize_optional_string(data.get("variant_id") or data.get("variantId"), max_length=MAX_VARIANT_ID_LENGTH),
        "label": normalize_optional_string(data.get("label") or data.get("name") or data.get("family_name"), max_length=MAX_LABEL_LENGTH),
        "description": normalize_optional_string(data.get("description")),
        "object_kind": normalize_optional_string(data.get("object_kind") or data.get("objectKind"), max_length=MAX_OBJECT_KIND_LENGTH),
        "domain": domain,
        "category": category,
        "subcategory": subcategory,
        "taxonomy_path": taxonomy_path,
    }


def collection_item_key_for(
    *,
    item_db_id: Any = None,
    variant_db_id: Any = None,
    vplib_uid: Any = None,
    family_id: Any = None,
    package_id: Any = None,
    variant_id: Any = None,
) -> str:
    """Baut stabilen Collection-Item-Key."""
    item_id = normalize_int(item_db_id, default=None, minimum=1)
    variant_db = normalize_int(variant_db_id, default=None, minimum=1)
    uid = normalize_optional_string(vplib_uid, max_length=MAX_VPLIB_UID_LENGTH)
    family = normalize_optional_string(family_id, max_length=MAX_FAMILY_ID_LENGTH)
    package = normalize_optional_string(package_id, max_length=MAX_PACKAGE_ID_LENGTH)
    variant = normalize_optional_string(variant_id, max_length=MAX_VARIANT_ID_LENGTH)

    if uid:
        return f"vplib:{uid}:variant:{variant or 'default'}"[:MAX_KEY_LENGTH]

    if item_id:
        return f"item:{item_id}:variant_db:{variant_db or 0}:variant:{variant or 'default'}"[:MAX_KEY_LENGTH]

    if family:
        return f"family:{family}:variant:{variant or 'default'}"[:MAX_KEY_LENGTH]

    if package:
        return f"package:{package}:variant:{variant or 'default'}"[:MAX_KEY_LENGTH]

    return f"unknown:{stable_json_hash({'variant': variant})[:24]}"


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
    """Gemeinsame JSON-Helfer."""

    @staticmethod
    def json_mapping(value: Mapping[str, Any] | None) -> dict[str, Any]:
        return normalize_json_mapping(value)

    @staticmethod
    def json_list(value: Iterable[Any] | None) -> list[Any]:
        return normalize_json_list(value)


# ---------------------------------------------------------------------------
# Models
# ---------------------------------------------------------------------------

class CreativeLibraryCollection(TimestampMixin, JsonMixin, db.Model):
    """
    Eine Creative-Library-Collection.

    Beispiele:

    - system/default
    - user:1/user-default
    - user:1/favorites
    - user:1/projekt-bruecke-a
    """

    __tablename__ = "creative_library_collections"

    id = db.Column(db.BigInteger, primary_key=True, autoincrement=True)

    collection_uid = db.Column(db.String(MAX_UID_LENGTH), nullable=False, unique=True, index=True, default=new_uid)

    collection_key = db.Column(db.String(MAX_COLLECTION_KEY_LENGTH), nullable=False, index=True)
    collection_kind = db.Column(
        db.String(80),
        nullable=False,
        default=CreativeLibraryCollectionKind.USER_DEFAULT.value,
        index=True,
    )

    source_scope = db.Column(
        db.String(MAX_SOURCE_SCOPE_LENGTH),
        nullable=False,
        default=CreativeLibraryUserSourceScope.USER.value,
        index=True,
    )
    owner_user_id = db.Column(db.BigInteger, nullable=True, index=True)
    owner_scope = db.Column(
        db.String(MAX_OWNER_SCOPE_LENGTH),
        nullable=False,
        default=f"user:{DEFAULT_USER_ID}",
        index=True,
    )

    label = db.Column(db.String(MAX_LABEL_LENGTH), nullable=True)
    name = db.Column(db.String(MAX_LABEL_LENGTH), nullable=True)
    description = db.Column(db.Text, nullable=True)

    status = db.Column(
        db.String(MAX_STATUS_LENGTH),
        nullable=False,
        default=CreativeLibraryUserStatus.ACTIVE.value,
        index=True,
    )
    active = db.Column(db.Boolean, nullable=False, default=True, index=True)
    visible = db.Column(db.Boolean, nullable=False, default=True, index=True)
    locked = db.Column(db.Boolean, nullable=False, default=False)
    system_required = db.Column(db.Boolean, nullable=False, default=False)

    is_default = db.Column(db.Boolean, nullable=False, default=False, index=True)
    is_favorites = db.Column(db.Boolean, nullable=False, default=False, index=True)
    auto_include_system_default = db.Column(db.Boolean, nullable=False, default=False)
    item_count = db.Column(db.Integer, nullable=False, default=0)

    sort_order = db.Column(db.Integer, nullable=False, default=0, index=True)

    icon = db.Column(db.String(120), nullable=True)
    color = db.Column(db.String(40), nullable=True)

    settings = db.Column(db.JSON, nullable=False, default=dict)
    payload = db.Column(db.JSON, nullable=False, default=dict)
    meta = db.Column(db.JSON, nullable=False, default=dict)
    metadata_json = db.Column(db.JSON, nullable=False, default=dict)

    created_by_user_id = db.Column(db.BigInteger, nullable=True, index=True)
    updated_by_user_id = db.Column(db.BigInteger, nullable=True, index=True)
    deleted_by_user_id = db.Column(db.BigInteger, nullable=True, index=True)
    deleted_at = db.Column(db.DateTime(timezone=True), nullable=True)

    items = db.relationship(
        "CreativeLibraryCollectionItem",
        back_populates="collection",
        cascade="all, delete-orphan",
        foreign_keys="CreativeLibraryCollectionItem.collection_id",
        lazy="selectin",
    )

    __table_args__ = (
        db.UniqueConstraint("owner_scope", "collection_key", name="uq_creative_library_collection_owner_key"),
        db.Index("ix_creative_library_collections_owner_status", "owner_scope", "status", "active", "visible"),
        db.Index("ix_creative_library_collections_user_kind", "owner_user_id", "collection_kind"),
        db.Index("ix_creative_library_collections_default", "owner_scope", "is_default"),
    )

    def __repr__(self) -> str:
        return f"<CreativeLibraryCollection id={self.id!r} owner={self.owner_scope!r} key={self.collection_key!r}>"

    @classmethod
    def create_from_payload(
        cls,
        payload: Mapping[str, Any] | None,
        *,
        source_scope: Any = CreativeLibraryUserSourceScope.USER.value,
        owner_user_id: Any = DEFAULT_USER_ID,
        created_by_user_id: Any = None,
    ) -> "CreativeLibraryCollection":
        """Erstellt eine Collection aus Payload."""
        data = normalize_json_mapping(payload)

        normalized_source_scope = normalize_source_scope(source_scope)
        normalized_owner_user_id = normalize_user_id(owner_user_id, default=None)
        normalized_owner_scope = owner_scope_for(
            source_scope=normalized_source_scope,
            owner_user_id=normalized_owner_user_id,
        )

        collection_key = normalize_collection_key(
            first_non_empty(data.get("collection_key"), data.get("key"), data.get("slug")),
            fallback=DEFAULT_COLLECTION_KEY if normalized_source_scope == CreativeLibraryUserSourceScope.SYSTEM.value else DEFAULT_USER_COLLECTION_KEY,
        )

        kind = enum_value(
            data.get("collection_kind") or data.get("kind"),
            default=CreativeLibraryCollectionKind.SYSTEM_DEFAULT.value
            if normalized_source_scope == CreativeLibraryUserSourceScope.SYSTEM.value
            else CreativeLibraryCollectionKind.USER_DEFAULT.value,
        )

        label = normalize_optional_string(data.get("label") or data.get("name"), max_length=MAX_LABEL_LENGTH)

        return cls(
            collection_uid=normalize_optional_string(data.get("collection_uid") or data.get("uid"), max_length=MAX_UID_LENGTH) or new_uid(),
            collection_key=collection_key,
            collection_kind=kind,
            source_scope=normalized_source_scope,
            owner_user_id=normalized_owner_user_id,
            owner_scope=normalized_owner_scope,
            label=label,
            name=normalize_optional_string(data.get("name") or label, max_length=MAX_LABEL_LENGTH),
            description=normalize_optional_string(data.get("description")),
            status=normalize_status(data.get("status"), active=data.get("active"), visible=data.get("visible")),
            active=normalize_bool(data.get("active"), default=True),
            visible=normalize_bool(data.get("visible"), default=True),
            locked=normalize_bool(data.get("locked"), default=False),
            system_required=normalize_bool(data.get("system_required"), default=normalized_source_scope == CreativeLibraryUserSourceScope.SYSTEM.value),
            is_default=normalize_bool(data.get("is_default"), default=collection_key in {DEFAULT_COLLECTION_KEY, DEFAULT_USER_COLLECTION_KEY}),
            is_favorites=normalize_bool(data.get("is_favorites"), default=kind == CreativeLibraryCollectionKind.FAVORITES.value),
            auto_include_system_default=normalize_bool(
                data.get("auto_include_system_default"),
                default=normalized_source_scope == CreativeLibraryUserSourceScope.USER.value and collection_key == DEFAULT_USER_COLLECTION_KEY,
            ),
            item_count=normalize_int(data.get("item_count"), default=0, minimum=0) or 0,
            sort_order=normalize_int(data.get("sort_order"), default=0, minimum=0) or 0,
            icon=normalize_optional_string(data.get("icon"), max_length=120),
            color=normalize_optional_string(data.get("color"), max_length=40),
            settings=normalize_json_mapping(data.get("settings")),
            payload=data,
            meta=normalize_json_mapping(data.get("meta")),
            metadata_json=normalize_json_mapping(data.get("metadata")),
            created_by_user_id=normalize_user_id(created_by_user_id, default=None),
            updated_by_user_id=normalize_user_id(created_by_user_id, default=None),
        )

    def refresh_item_count(self) -> None:
        """Aktualisiert item_count aus geladenen Items, falls vorhanden."""
        try:
            self.item_count = len([item for item in getattr(self, "items", []) or [] if getattr(item, "active", False)])
            self.touch()
        except Exception:
            pass

    def mark_deleted(self, *, user_id: Any = None) -> None:
        """Soft-delete für Collection und ihre Collection-Items."""
        if self.locked or self.system_required:
            raise ValueError("Cannot delete a locked or system-required collection directly.")

        self.status = CreativeLibraryUserStatus.DELETED.value
        self.active = False
        self.visible = False
        self.deleted_at = utc_now()
        self.deleted_by_user_id = normalize_user_id(user_id, default=None)
        self.updated_by_user_id = normalize_user_id(user_id, default=self.updated_by_user_id)
        self.touch()

        for item in getattr(self, "items", []) or []:
            try:
                item.mark_deleted(user_id=user_id)
            except Exception:
                continue

    def restore(self, *, user_id: Any = None) -> None:
        """Stellt Collection wieder her."""
        self.status = CreativeLibraryUserStatus.ACTIVE.value
        self.active = True
        self.visible = True
        self.deleted_at = None
        self.deleted_by_user_id = None
        self.updated_by_user_id = normalize_user_id(user_id, default=self.updated_by_user_id)
        self.touch()

    def to_dict(self, *, include_items: bool = False) -> dict[str, Any]:
        result = {
            "id": self.id,
            "collection_db_id": self.id,
            "collection_uid": self.collection_uid,
            "collection_key": self.collection_key,
            "collection_kind": self.collection_kind,
            "source_scope": self.source_scope,
            "owner_user_id": self.owner_user_id,
            "owner_scope": self.owner_scope,
            "label": self.label,
            "name": self.name,
            "description": self.description,
            "status": self.status,
            "active": self.active,
            "visible": self.visible,
            "locked": self.locked,
            "system_required": self.system_required,
            "is_default": self.is_default,
            "is_favorites": self.is_favorites,
            "auto_include_system_default": self.auto_include_system_default,
            "item_count": self.item_count,
            "sort_order": self.sort_order,
            "icon": self.icon,
            "color": self.color,
            "settings": normalize_json_mapping(self.settings),
            "payload": normalize_json_mapping(self.payload),
            "meta": normalize_json_mapping(self.meta),
            "metadata": normalize_json_mapping(self.metadata_json),
            "created_by_user_id": self.created_by_user_id,
            "updated_by_user_id": self.updated_by_user_id,
            "deleted_by_user_id": self.deleted_by_user_id,
            "deleted_at": self.deleted_at.isoformat() if self.deleted_at else None,
            "created_at": self.created_at.isoformat() if self.created_at else None,
            "updated_at": self.updated_at.isoformat() if self.updated_at else None,
        }

        if include_items:
            items = list(getattr(self, "items", []) or [])
            items.sort(key=lambda item: (normalize_int(getattr(item, "sort_order", 0), default=0) or 0, getattr(item, "label", "") or ""))
            result["items"] = [item.to_dict(include_collection=False, include_item=False, include_variant=False) for item in items]

        return result


class CreativeLibraryCollectionItem(TimestampMixin, JsonMixin, db.Model):
    """
    Zuordnung eines Creative-Library-Items zu einer Collection.

    Ein CollectionItem kann aus der Systembibliothek stammen oder durch den User
    hinzugefügt worden sein. Es enthält bewusst Snapshots von wichtigen Feldern,
    damit resolved APIs schnell und stabil antworten können.
    """

    __tablename__ = "creative_library_collection_items"

    id = db.Column(db.BigInteger, primary_key=True, autoincrement=True)

    collection_item_uid = db.Column(db.String(MAX_UID_LENGTH), nullable=False, unique=True, index=True, default=new_uid)

    collection_id = db.Column(
        db.BigInteger,
        db.ForeignKey("creative_library_collections.id", ondelete="CASCADE"),
        nullable=True,
        index=True,
    )

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

    source_scope = db.Column(
        db.String(MAX_SOURCE_SCOPE_LENGTH),
        nullable=False,
        default=CreativeLibraryUserSourceScope.USER.value,
        index=True,
    )
    owner_user_id = db.Column(db.BigInteger, nullable=True, index=True)
    owner_scope = db.Column(
        db.String(MAX_OWNER_SCOPE_LENGTH),
        nullable=False,
        default=f"user:{DEFAULT_USER_ID}",
        index=True,
    )

    item_key = db.Column(db.String(MAX_KEY_LENGTH), nullable=False, index=True)

    vplib_uid = db.Column(db.String(MAX_VPLIB_UID_LENGTH), nullable=True, index=True)
    family_id = db.Column(db.String(MAX_FAMILY_ID_LENGTH), nullable=True, index=True)
    package_id = db.Column(db.String(MAX_PACKAGE_ID_LENGTH), nullable=True, index=True)
    variant_id = db.Column(db.String(MAX_VARIANT_ID_LENGTH), nullable=True, index=True)

    label = db.Column(db.String(MAX_LABEL_LENGTH), nullable=True)
    name = db.Column(db.String(MAX_LABEL_LENGTH), nullable=True)
    description = db.Column(db.Text, nullable=True)
    object_kind = db.Column(db.String(MAX_OBJECT_KIND_LENGTH), nullable=True, index=True)

    domain = db.Column(db.String(MAX_TAXONOMY_PART_LENGTH), nullable=True, index=True)
    category = db.Column(db.String(MAX_TAXONOMY_PART_LENGTH), nullable=True, index=True)
    subcategory = db.Column(db.String(MAX_TAXONOMY_PART_LENGTH), nullable=True, index=True)
    taxonomy_path = db.Column(db.String(MAX_TAXONOMY_PATH_LENGTH), nullable=True, index=True)

    status = db.Column(
        db.String(MAX_STATUS_LENGTH),
        nullable=False,
        default=CreativeLibraryUserStatus.ACTIVE.value,
        index=True,
    )
    active = db.Column(db.Boolean, nullable=False, default=True, index=True)
    visible = db.Column(db.Boolean, nullable=False, default=True, index=True)
    locked = db.Column(db.Boolean, nullable=False, default=False)

    pinned = db.Column(db.Boolean, nullable=False, default=False, index=True)
    favorite = db.Column(db.Boolean, nullable=False, default=False, index=True)
    is_standard = db.Column(db.Boolean, nullable=False, default=False, index=True)
    is_user_added = db.Column(db.Boolean, nullable=False, default=True, index=True)

    quantity = db.Column(db.Integer, nullable=False, default=1)
    sort_order = db.Column(db.Integer, nullable=False, default=0, index=True)

    icon = db.Column(db.JSON, nullable=False, default=dict)
    preview = db.Column(db.JSON, nullable=False, default=dict)
    assets = db.Column(db.JSON, nullable=False, default=list)
    variant = db.Column(db.JSON, nullable=False, default=dict)
    placement = db.Column(db.JSON, nullable=False, default=dict)

    added_at = db.Column(db.DateTime(timezone=True), nullable=True)
    removed_at = db.Column(db.DateTime(timezone=True), nullable=True)
    deleted_at = db.Column(db.DateTime(timezone=True), nullable=True)

    payload = db.Column(db.JSON, nullable=False, default=dict)
    meta = db.Column(db.JSON, nullable=False, default=dict)
    metadata_json = db.Column(db.JSON, nullable=False, default=dict)

    created_by_user_id = db.Column(db.BigInteger, nullable=True, index=True)
    updated_by_user_id = db.Column(db.BigInteger, nullable=True, index=True)
    deleted_by_user_id = db.Column(db.BigInteger, nullable=True, index=True)

    collection = db.relationship(
        "CreativeLibraryCollection",
        back_populates="items",
        foreign_keys=[collection_id],
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

    __table_args__ = (
        db.UniqueConstraint("collection_id", "item_key", name="uq_creative_library_collection_item_key"),
        db.Index("ix_creative_library_collection_items_collection_sort", "collection_id", "sort_order"),
        db.Index("ix_creative_library_collection_items_uid_variant", "vplib_uid", "variant_id"),
        db.Index("ix_creative_library_collection_items_taxonomy", "domain", "category", "subcategory"),
        db.Index("ix_creative_library_collection_items_owner_status", "owner_scope", "status", "active", "visible"),
        db.Index("ix_creative_library_collection_items_flags", "favorite", "pinned", "is_standard", "is_user_added"),
    )

    def __repr__(self) -> str:
        return f"<CreativeLibraryCollectionItem id={self.id!r} collection={self.collection_id!r} key={self.item_key!r}>"

    @classmethod
    def create_from_item_payload(
        cls,
        item_payload: Mapping[str, Any] | None,
        *,
        collection: CreativeLibraryCollection | None = None,
        source_scope: Any = CreativeLibraryUserSourceScope.USER.value,
        owner_user_id: Any = DEFAULT_USER_ID,
        created_by_user_id: Any = None,
        sort_order: Any = 0,
    ) -> "CreativeLibraryCollectionItem":
        """Erstellt ein CollectionItem aus einem Creative-Library/API-Payload."""
        data = normalize_json_mapping(item_payload)
        identity = extract_item_identity(data)

        normalized_source_scope = normalize_source_scope(source_scope)
        normalized_owner_user_id = normalize_user_id(owner_user_id, default=None)
        normalized_owner_scope = owner_scope_for(
            source_scope=normalized_source_scope,
            owner_user_id=normalized_owner_user_id,
        )

        item_key = collection_item_key_for(
            item_db_id=identity["item_db_id"],
            variant_db_id=identity["variant_db_id"],
            vplib_uid=identity["vplib_uid"],
            family_id=identity["family_id"],
            package_id=identity["package_id"],
            variant_id=identity["variant_id"],
        )

        is_standard_default = normalized_source_scope == CreativeLibraryUserSourceScope.SYSTEM.value

        return cls(
            collection=collection,
            collection_id=getattr(collection, "id", None),
            collection_item_uid=normalize_optional_string(data.get("collection_item_uid") or data.get("uid"), max_length=MAX_UID_LENGTH) or new_uid(),
            item_db_id=identity["item_db_id"],
            variant_db_id=identity["variant_db_id"],
            source_scope=normalized_source_scope,
            owner_user_id=normalized_owner_user_id,
            owner_scope=normalized_owner_scope,
            item_key=item_key,
            vplib_uid=identity["vplib_uid"],
            family_id=identity["family_id"],
            package_id=identity["package_id"],
            variant_id=identity["variant_id"],
            label=identity["label"],
            name=normalize_optional_string(data.get("name") or identity["label"], max_length=MAX_LABEL_LENGTH),
            description=identity["description"],
            object_kind=identity["object_kind"],
            domain=identity["domain"],
            category=identity["category"],
            subcategory=identity["subcategory"],
            taxonomy_path=identity["taxonomy_path"],
            status=normalize_status(data.get("status"), active=data.get("active"), visible=data.get("visible")),
            active=normalize_bool(data.get("active"), default=True),
            visible=normalize_bool(data.get("visible"), default=True),
            locked=normalize_bool(data.get("locked"), default=False),
            pinned=normalize_bool(data.get("pinned"), default=False),
            favorite=normalize_bool(data.get("favorite"), default=False),
            is_standard=normalize_bool(data.get("is_standard"), default=is_standard_default),
            is_user_added=normalize_bool(data.get("is_user_added"), default=not is_standard_default),
            quantity=normalize_int(data.get("quantity"), default=1, minimum=0) or 0,
            sort_order=normalize_int(first_non_empty(sort_order, data.get("sort_order")), default=0, minimum=0) or 0,
            icon=normalize_json_mapping(data.get("icon")),
            preview=normalize_json_mapping(data.get("preview")),
            assets=normalize_json_list(data.get("assets")),
            variant=normalize_json_mapping(data.get("variant")),
            placement=normalize_json_mapping(data.get("placement")),
            added_at=utc_now(),
            payload=data,
            meta=normalize_json_mapping(data.get("meta")),
            metadata_json=normalize_json_mapping(data.get("metadata")),
            created_by_user_id=normalize_user_id(created_by_user_id, default=None),
            updated_by_user_id=normalize_user_id(created_by_user_id, default=None),
        )

    def mark_deleted(self, *, user_id: Any = None) -> None:
        """Soft-delete für CollectionItem."""
        if self.locked and self.is_standard:
            raise ValueError("Cannot delete a locked standard collection item directly.")

        self.status = CreativeLibraryUserStatus.DELETED.value
        self.active = False
        self.visible = False
        self.removed_at = utc_now()
        self.deleted_at = self.removed_at
        self.deleted_by_user_id = normalize_user_id(user_id, default=None)
        self.updated_by_user_id = normalize_user_id(user_id, default=self.updated_by_user_id)
        self.touch()

    def hide(self, *, user_id: Any = None) -> None:
        """Blendet CollectionItem aus, ohne es komplett zu löschen."""
        self.status = CreativeLibraryUserStatus.HIDDEN.value
        self.visible = False
        self.updated_by_user_id = normalize_user_id(user_id, default=self.updated_by_user_id)
        self.touch()

    def restore(self, *, user_id: Any = None) -> None:
        """Stellt CollectionItem wieder her."""
        self.status = CreativeLibraryUserStatus.ACTIVE.value
        self.active = True
        self.visible = True
        self.removed_at = None
        self.deleted_at = None
        self.deleted_by_user_id = None
        self.updated_by_user_id = normalize_user_id(user_id, default=self.updated_by_user_id)
        self.touch()

    def set_favorite(self, value: Any = True, *, user_id: Any = None) -> None:
        self.favorite = normalize_bool(value, default=True)
        self.updated_by_user_id = normalize_user_id(user_id, default=self.updated_by_user_id)
        self.touch()

    def set_pinned(self, value: Any = True, *, user_id: Any = None) -> None:
        self.pinned = normalize_bool(value, default=True)
        self.updated_by_user_id = normalize_user_id(user_id, default=self.updated_by_user_id)
        self.touch()

    def to_dict(
        self,
        *,
        include_collection: bool = False,
        include_item: bool = False,
        include_variant: bool = False,
    ) -> dict[str, Any]:
        result = {
            "id": self.id,
            "collection_item_db_id": self.id,
            "collection_item_uid": self.collection_item_uid,
            "collection_id": self.collection_id,
            "item_db_id": self.item_db_id,
            "variant_db_id": self.variant_db_id,
            "source_scope": self.source_scope,
            "owner_user_id": self.owner_user_id,
            "owner_scope": self.owner_scope,
            "item_key": self.item_key,
            "vplib_uid": self.vplib_uid,
            "family_id": self.family_id,
            "package_id": self.package_id,
            "variant_id": self.variant_id,
            "label": self.label,
            "name": self.name,
            "description": self.description,
            "object_kind": self.object_kind,
            "domain": self.domain,
            "category": self.category,
            "subcategory": self.subcategory,
            "taxonomy_path": self.taxonomy_path,
            "status": self.status,
            "active": self.active,
            "visible": self.visible,
            "locked": self.locked,
            "pinned": self.pinned,
            "favorite": self.favorite,
            "is_standard": self.is_standard,
            "is_user_added": self.is_user_added,
            "quantity": self.quantity,
            "sort_order": self.sort_order,
            "icon": normalize_json_mapping(self.icon),
            "preview": normalize_json_mapping(self.preview),
            "assets": normalize_json_list(self.assets),
            "variant": normalize_json_mapping(self.variant),
            "placement": normalize_json_mapping(self.placement),
            "added_at": self.added_at.isoformat() if self.added_at else None,
            "removed_at": self.removed_at.isoformat() if self.removed_at else None,
            "deleted_at": self.deleted_at.isoformat() if self.deleted_at else None,
            "payload": normalize_json_mapping(self.payload),
            "meta": normalize_json_mapping(self.meta),
            "metadata": normalize_json_mapping(self.metadata_json),
            "created_by_user_id": self.created_by_user_id,
            "updated_by_user_id": self.updated_by_user_id,
            "deleted_by_user_id": self.deleted_by_user_id,
            "created_at": self.created_at.isoformat() if self.created_at else None,
            "updated_at": self.updated_at.isoformat() if self.updated_at else None,
        }

        if include_collection:
            result["collection"] = self.collection.to_dict(include_items=False) if self.collection is not None else None

        if include_item:
            result["item"] = self.item.to_dict() if self.item is not None and hasattr(self.item, "to_dict") else None

        if include_variant:
            result["variant_row"] = self.variant_row.to_dict() if self.variant_row is not None and hasattr(self.variant_row, "to_dict") else None

        return result


class CreativeLibraryUserOverride(TimestampMixin, JsonMixin, db.Model):
    """
    User-Override auf Creative Library Targets.

    Beispiele:

    - Standard-Item für User ausblenden.
    - Item für User umbenennen.
    - Item/Variant favorisieren.
    - System-Kategorie für User anders sortieren.
    - CollectionItem entfernen, ohne Systembibliothek zu verändern.
    """

    __tablename__ = "creative_library_user_overrides"

    id = db.Column(db.BigInteger, primary_key=True, autoincrement=True)

    override_uid = db.Column(db.String(MAX_UID_LENGTH), nullable=False, unique=True, index=True, default=new_uid)

    user_id = db.Column(db.BigInteger, nullable=False, default=DEFAULT_USER_ID, index=True)
    owner_scope = db.Column(db.String(MAX_OWNER_SCOPE_LENGTH), nullable=False, default=f"user:{DEFAULT_USER_ID}", index=True)

    target_type = db.Column(
        db.String(MAX_TARGET_TYPE_LENGTH),
        nullable=False,
        default=CreativeLibraryUserTargetType.OTHER.value,
        index=True,
    )
    target_db_id = db.Column(db.BigInteger, nullable=True, index=True)
    target_uid = db.Column(db.String(MAX_UID_LENGTH), nullable=True, index=True)
    target_key = db.Column(db.String(MAX_KEY_LENGTH), nullable=True, index=True)

    collection_id = db.Column(
        db.BigInteger,
        db.ForeignKey("creative_library_collections.id", ondelete="CASCADE"),
        nullable=True,
        index=True,
    )
    collection_item_id = db.Column(
        db.BigInteger,
        db.ForeignKey("creative_library_collection_items.id", ondelete="CASCADE"),
        nullable=True,
        index=True,
    )
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

    vplib_uid = db.Column(db.String(MAX_VPLIB_UID_LENGTH), nullable=True, index=True)
    family_id = db.Column(db.String(MAX_FAMILY_ID_LENGTH), nullable=True, index=True)
    package_id = db.Column(db.String(MAX_PACKAGE_ID_LENGTH), nullable=True, index=True)
    variant_id = db.Column(db.String(MAX_VARIANT_ID_LENGTH), nullable=True, index=True)

    taxonomy_path = db.Column(db.String(MAX_TAXONOMY_PATH_LENGTH), nullable=True, index=True)

    override_action = db.Column(
        db.String(MAX_ACTION_LENGTH),
        nullable=False,
        default=CreativeLibraryUserOverrideAction.PATCH.value,
        index=True,
    )
    status = db.Column(
        db.String(MAX_STATUS_LENGTH),
        nullable=False,
        default=CreativeLibraryUserStatus.ACTIVE.value,
        index=True,
    )
    active = db.Column(db.Boolean, nullable=False, default=True, index=True)

    visible_override = db.Column(db.Boolean, nullable=True)
    active_override = db.Column(db.Boolean, nullable=True)
    favorite_override = db.Column(db.Boolean, nullable=True)
    pinned_override = db.Column(db.Boolean, nullable=True)

    label_override = db.Column(db.String(MAX_LABEL_LENGTH), nullable=True)
    description_override = db.Column(db.Text, nullable=True)
    sort_order_override = db.Column(db.Integer, nullable=True)

    payload_patch = db.Column(db.JSON, nullable=False, default=dict)
    before_json = db.Column(db.JSON, nullable=False, default=dict)
    after_json = db.Column(db.JSON, nullable=False, default=dict)

    meta = db.Column(db.JSON, nullable=False, default=dict)
    metadata_json = db.Column(db.JSON, nullable=False, default=dict)

    created_by_user_id = db.Column(db.BigInteger, nullable=True, index=True)
    updated_by_user_id = db.Column(db.BigInteger, nullable=True, index=True)
    deleted_by_user_id = db.Column(db.BigInteger, nullable=True, index=True)
    deleted_at = db.Column(db.DateTime(timezone=True), nullable=True)

    collection = db.relationship("CreativeLibraryCollection", foreign_keys=[collection_id], lazy="joined")
    collection_item = db.relationship("CreativeLibraryCollectionItem", foreign_keys=[collection_item_id], lazy="joined")
    item = db.relationship("CreativeLibraryItem", foreign_keys=[item_db_id], lazy="joined")
    variant_row = db.relationship("CreativeLibraryVariant", foreign_keys=[variant_db_id], lazy="joined")

    __table_args__ = (
        db.UniqueConstraint("user_id", "target_type", "target_key", name="uq_creative_library_user_override_target"),
        db.Index("ix_creative_library_user_overrides_user_active", "user_id", "active", "status"),
        db.Index("ix_creative_library_user_overrides_action", "override_action", "status"),
        db.Index("ix_creative_library_user_overrides_uid_variant", "vplib_uid", "variant_id"),
        db.Index("ix_creative_library_user_overrides_taxonomy", "taxonomy_path"),
    )

    def __repr__(self) -> str:
        return f"<CreativeLibraryUserOverride user_id={self.user_id!r} target={self.target_type!r}:{self.target_key!r}>"

    @classmethod
    def create_from_payload(
        cls,
        payload: Mapping[str, Any] | None,
        *,
        user_id: Any = DEFAULT_USER_ID,
        collection: CreativeLibraryCollection | None = None,
        collection_item: CreativeLibraryCollectionItem | None = None,
        created_by_user_id: Any = None,
    ) -> "CreativeLibraryUserOverride":
        """Erstellt einen User-Override aus Payload."""
        data = normalize_json_mapping(payload)
        normalized_user_id = normalize_user_id(first_non_empty(data.get("user_id"), user_id), default=DEFAULT_USER_ID) or DEFAULT_USER_ID

        identity = extract_item_identity(data)

        if collection_item is not None:
            identity = merge_json(
                identity,
                {
                    "item_db_id": collection_item.item_db_id,
                    "variant_db_id": collection_item.variant_db_id,
                    "vplib_uid": collection_item.vplib_uid,
                    "family_id": collection_item.family_id,
                    "package_id": collection_item.package_id,
                    "variant_id": collection_item.variant_id,
                    "taxonomy_path": collection_item.taxonomy_path,
                },
            )

        target_type = normalize_target_type(first_non_empty(data.get("target_type"), data.get("targetType")))
        target_key = normalize_optional_string(data.get("target_key") or data.get("targetKey"), max_length=MAX_KEY_LENGTH)

        if not target_key:
            if target_type == CreativeLibraryUserTargetType.COLLECTION_ITEM.value and collection_item is not None:
                target_key = f"collection_item:{collection_item.collection_item_uid}"
            elif target_type == CreativeLibraryUserTargetType.COLLECTION.value and collection is not None:
                target_key = f"collection:{collection.collection_uid}"
            else:
                target_key = collection_item_key_for(
                    item_db_id=identity.get("item_db_id"),
                    variant_db_id=identity.get("variant_db_id"),
                    vplib_uid=identity.get("vplib_uid"),
                    family_id=identity.get("family_id"),
                    package_id=identity.get("package_id"),
                    variant_id=identity.get("variant_id"),
                )

        action = normalize_action(first_non_empty(data.get("override_action"), data.get("action")))

        return cls(
            override_uid=normalize_optional_string(data.get("override_uid") or data.get("uid"), max_length=MAX_UID_LENGTH) or new_uid(),
            user_id=normalized_user_id,
            owner_scope=f"user:{normalized_user_id}",
            target_type=target_type,
            target_db_id=normalize_int(data.get("target_db_id"), default=None, minimum=1),
            target_uid=normalize_optional_string(data.get("target_uid"), max_length=MAX_UID_LENGTH),
            target_key=target_key,
            collection=collection,
            collection_id=getattr(collection, "id", None),
            collection_item=collection_item,
            collection_item_id=getattr(collection_item, "id", None),
            item_db_id=identity.get("item_db_id"),
            variant_db_id=identity.get("variant_db_id"),
            vplib_uid=identity.get("vplib_uid"),
            family_id=identity.get("family_id"),
            package_id=identity.get("package_id"),
            variant_id=identity.get("variant_id"),
            taxonomy_path=identity.get("taxonomy_path") or normalize_optional_string(data.get("taxonomy_path"), max_length=MAX_TAXONOMY_PATH_LENGTH),
            override_action=action,
            status=normalize_status(data.get("status")),
            active=normalize_bool(data.get("active"), default=True),
            visible_override=normalize_optional_bool(data.get("visible_override") if "visible_override" in data else data.get("visible")),
            active_override=normalize_optional_bool(data.get("active_override")),
            favorite_override=normalize_optional_bool(data.get("favorite_override") if "favorite_override" in data else data.get("favorite")),
            pinned_override=normalize_optional_bool(data.get("pinned_override") if "pinned_override" in data else data.get("pinned")),
            label_override=normalize_optional_string(data.get("label_override") or data.get("label"), max_length=MAX_LABEL_LENGTH),
            description_override=normalize_optional_string(data.get("description_override") or data.get("description")),
            sort_order_override=normalize_int(data.get("sort_order_override") or data.get("sort_order"), default=None, minimum=0),
            payload_patch=normalize_json_mapping(data.get("payload_patch") or data.get("patch")),
            before_json=normalize_json_mapping(data.get("before")),
            after_json=normalize_json_mapping(data.get("after")),
            meta=normalize_json_mapping(data.get("meta")),
            metadata_json=normalize_json_mapping(data.get("metadata")),
            created_by_user_id=normalize_user_id(created_by_user_id, default=None),
            updated_by_user_id=normalize_user_id(created_by_user_id, default=None),
        )

    def mark_deleted(self, *, user_id: Any = None) -> None:
        """Soft-delete für Override."""
        self.status = CreativeLibraryUserStatus.DELETED.value
        self.active = False
        self.deleted_at = utc_now()
        self.deleted_by_user_id = normalize_user_id(user_id, default=None)
        self.updated_by_user_id = normalize_user_id(user_id, default=self.updated_by_user_id)
        self.touch()

    def restore(self, *, user_id: Any = None) -> None:
        """Stellt Override wieder her."""
        self.status = CreativeLibraryUserStatus.ACTIVE.value
        self.active = True
        self.deleted_at = None
        self.deleted_by_user_id = None
        self.updated_by_user_id = normalize_user_id(user_id, default=self.updated_by_user_id)
        self.touch()

    def to_dict(self, *, include_targets: bool = False) -> dict[str, Any]:
        result = {
            "id": self.id,
            "override_db_id": self.id,
            "override_uid": self.override_uid,
            "user_id": self.user_id,
            "owner_scope": self.owner_scope,
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
            "override_action": self.override_action,
            "status": self.status,
            "active": self.active,
            "visible_override": self.visible_override,
            "active_override": self.active_override,
            "favorite_override": self.favorite_override,
            "pinned_override": self.pinned_override,
            "label_override": self.label_override,
            "description_override": self.description_override,
            "sort_order_override": self.sort_order_override,
            "payload_patch": normalize_json_mapping(self.payload_patch),
            "before": normalize_json_mapping(self.before_json),
            "after": normalize_json_mapping(self.after_json),
            "meta": normalize_json_mapping(self.meta),
            "metadata": normalize_json_mapping(self.metadata_json),
            "created_by_user_id": self.created_by_user_id,
            "updated_by_user_id": self.updated_by_user_id,
            "deleted_by_user_id": self.deleted_by_user_id,
            "deleted_at": self.deleted_at.isoformat() if self.deleted_at else None,
            "created_at": self.created_at.isoformat() if self.created_at else None,
            "updated_at": self.updated_at.isoformat() if self.updated_at else None,
        }

        if include_targets:
            result["collection"] = self.collection.to_dict(include_items=False) if self.collection is not None else None
            result["collection_item"] = self.collection_item.to_dict(include_collection=False) if self.collection_item is not None else None
            result["item"] = self.item.to_dict() if self.item is not None and hasattr(self.item, "to_dict") else None
            result["variant_row"] = self.variant_row.to_dict() if self.variant_row is not None and hasattr(self.variant_row, "to_dict") else None

        return result


class CreativeLibraryUserAuditEvent(TimestampMixin, JsonMixin, db.Model):
    """Audit-Event für User-Creative-Library-Operationen."""

    __tablename__ = "creative_library_user_audit_events"

    id = db.Column(db.BigInteger, primary_key=True, autoincrement=True)

    event_uid = db.Column(db.String(MAX_UID_LENGTH), nullable=False, unique=True, index=True, default=new_uid)
    event_type = db.Column(db.String(120), nullable=False, index=True)

    user_id = db.Column(db.BigInteger, nullable=True, index=True)
    owner_scope = db.Column(db.String(MAX_OWNER_SCOPE_LENGTH), nullable=True, index=True)

    target_type = db.Column(db.String(MAX_TARGET_TYPE_LENGTH), nullable=True, index=True)
    target_db_id = db.Column(db.BigInteger, nullable=True, index=True)
    target_uid = db.Column(db.String(MAX_UID_LENGTH), nullable=True, index=True)
    target_key = db.Column(db.String(MAX_KEY_LENGTH), nullable=True, index=True)

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
    override_id = db.Column(
        db.BigInteger,
        db.ForeignKey("creative_library_user_overrides.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )

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

    collection = db.relationship("CreativeLibraryCollection", foreign_keys=[collection_id], lazy="joined")
    collection_item = db.relationship("CreativeLibraryCollectionItem", foreign_keys=[collection_item_id], lazy="joined")
    override = db.relationship("CreativeLibraryUserOverride", foreign_keys=[override_id], lazy="joined")
    item = db.relationship("CreativeLibraryItem", foreign_keys=[item_db_id], lazy="joined")
    variant_row = db.relationship("CreativeLibraryVariant", foreign_keys=[variant_db_id], lazy="joined")

    __table_args__ = (
        db.Index("ix_creative_library_user_audit_user_event", "user_id", "event_type", "created_at"),
        db.Index("ix_creative_library_user_audit_target", "target_type", "target_key", "created_at"),
        db.Index("ix_creative_library_user_audit_uid_variant", "vplib_uid", "variant_id", "created_at"),
        db.Index("ix_creative_library_user_audit_collection", "collection_id", "created_at"),
    )

    def __repr__(self) -> str:
        return f"<CreativeLibraryUserAuditEvent id={self.id!r} event_type={self.event_type!r} user_id={self.user_id!r}>"

    @classmethod
    def create_event(
        cls,
        *,
        event_type: Any,
        user_id: Any = None,
        collection: CreativeLibraryCollection | None = None,
        collection_item: CreativeLibraryCollectionItem | None = None,
        override: CreativeLibraryUserOverride | None = None,
        before: Mapping[str, Any] | None = None,
        after: Mapping[str, Any] | None = None,
        diff: Mapping[str, Any] | None = None,
        payload: Mapping[str, Any] | None = None,
        metadata: Mapping[str, Any] | None = None,
    ) -> "CreativeLibraryUserAuditEvent":
        """Erstellt Audit-Event aus bekannten Targets."""
        data = normalize_json_mapping(payload)
        normalized_user_id = normalize_user_id(
            first_non_empty(
                user_id,
                data.get("user_id"),
                getattr(override, "user_id", None),
                getattr(collection_item, "owner_user_id", None),
                getattr(collection, "owner_user_id", None),
            ),
            default=None,
        )

        target_type = normalize_target_type(
            first_non_empty(
                data.get("target_type"),
                getattr(override, "target_type", None),
                CreativeLibraryUserTargetType.COLLECTION_ITEM.value if collection_item is not None else None,
                CreativeLibraryUserTargetType.COLLECTION.value if collection is not None else None,
            )
        )

        target_key = normalize_optional_string(
            first_non_empty(
                data.get("target_key"),
                getattr(override, "target_key", None),
                getattr(collection_item, "item_key", None),
                getattr(collection, "collection_key", None),
            ),
            max_length=MAX_KEY_LENGTH,
        )

        return cls(
            event_uid=new_uid(),
            event_type=enum_value(event_type, default=CreativeLibraryUserAuditEventType.OTHER.value),
            user_id=normalized_user_id,
            owner_scope=f"user:{normalized_user_id}" if normalized_user_id else None,
            target_type=target_type,
            target_db_id=normalize_int(data.get("target_db_id"), default=None, minimum=1),
            target_uid=normalize_optional_string(
                first_non_empty(
                    data.get("target_uid"),
                    getattr(override, "target_uid", None),
                    getattr(collection_item, "collection_item_uid", None),
                    getattr(collection, "collection_uid", None),
                ),
                max_length=MAX_UID_LENGTH,
            ),
            target_key=target_key,
            collection=collection,
            collection_id=getattr(collection, "id", None),
            collection_item=collection_item,
            collection_item_id=getattr(collection_item, "id", None),
            override=override,
            override_id=getattr(override, "id", None),
            item_db_id=first_non_empty(getattr(collection_item, "item_db_id", None), getattr(override, "item_db_id", None), data.get("item_db_id")),
            variant_db_id=first_non_empty(getattr(collection_item, "variant_db_id", None), getattr(override, "variant_db_id", None), data.get("variant_db_id")),
            vplib_uid=first_non_empty(getattr(collection_item, "vplib_uid", None), getattr(override, "vplib_uid", None), data.get("vplib_uid")),
            family_id=first_non_empty(getattr(collection_item, "family_id", None), getattr(override, "family_id", None), data.get("family_id")),
            package_id=first_non_empty(getattr(collection_item, "package_id", None), getattr(override, "package_id", None), data.get("package_id")),
            variant_id=first_non_empty(getattr(collection_item, "variant_id", None), getattr(override, "variant_id", None), data.get("variant_id")),
            taxonomy_path=first_non_empty(getattr(collection_item, "taxonomy_path", None), getattr(override, "taxonomy_path", None), data.get("taxonomy_path")),
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
            "owner_scope": self.owner_scope,
            "target_type": self.target_type,
            "target_db_id": self.target_db_id,
            "target_uid": self.target_uid,
            "target_key": self.target_key,
            "collection_id": self.collection_id,
            "collection_item_id": self.collection_item_id,
            "override_id": self.override_id,
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
# Resolved payload helpers
# ---------------------------------------------------------------------------

def apply_user_override_to_item_payload(
    item_payload: Mapping[str, Any],
    override_payload: Mapping[str, Any] | None,
) -> dict[str, Any]:
    """
    Wendet einen User-Override auf ein serialisiertes CollectionItem/Item an.

    Diese Funktion ist model-unabhängig, damit Repository/Service sie später für
    resolved Creative Inventory verwenden können.
    """

    result = normalize_json_mapping(item_payload)
    override = normalize_json_mapping(override_payload)

    if not override or not normalize_bool(override.get("active"), default=True):
        return result

    action = normalize_action(first_non_empty(override.get("override_action"), override.get("action")))

    if action == CreativeLibraryUserOverrideAction.HIDE.value:
        result["visible"] = False
        result["hidden_by_override"] = True

    if action == CreativeLibraryUserOverrideAction.RESTORE.value:
        result["visible"] = True
        result["hidden_by_override"] = False

    if action == CreativeLibraryUserOverrideAction.FAVORITE.value:
        result["favorite"] = True

    if action == CreativeLibraryUserOverrideAction.UNFAVORITE.value:
        result["favorite"] = False

    if action == CreativeLibraryUserOverrideAction.PIN.value:
        result["pinned"] = True

    if action == CreativeLibraryUserOverrideAction.UNPIN.value:
        result["pinned"] = False

    if action in {CreativeLibraryUserOverrideAction.REMOVE.value, CreativeLibraryUserOverrideAction.DELETE.value}:
        result["active"] = False
        result["visible"] = False
        result["removed_by_override"] = True

    for source_key, target_key in (
        ("visible_override", "visible"),
        ("active_override", "active"),
        ("favorite_override", "favorite"),
        ("pinned_override", "pinned"),
        ("label_override", "label"),
        ("description_override", "description"),
        ("sort_order_override", "sort_order"),
    ):
        value = override.get(source_key)
        if value is not None:
            result[target_key] = value

    patch = normalize_json_mapping(override.get("payload_patch"))
    if patch:
        result["payload"] = merge_json(result.get("payload") if isinstance(result.get("payload"), Mapping) else None, patch)

    result["override"] = override
    return result


def build_resolved_collection_payload(
    *,
    collection: Mapping[str, Any],
    system_items: Iterable[Mapping[str, Any]] | None = None,
    user_items: Iterable[Mapping[str, Any]] | None = None,
    overrides: Iterable[Mapping[str, Any]] | None = None,
) -> dict[str, Any]:
    """
    Baut eine einfache resolved Collection aus System-Items, User-Items und Overrides.

    Diese Funktion führt keine DB-Queries aus. Repository/Service liefern später
    die bereits serialisierten Payloads.
    """

    result = normalize_json_mapping(collection)

    items_by_key: dict[str, dict[str, Any]] = {}

    for item in normalize_json_list(system_items):
        if not isinstance(item, Mapping):
            continue

        data = normalize_json_mapping(item)
        key = normalize_optional_string(data.get("item_key"), max_length=MAX_KEY_LENGTH)

        if not key:
            identity = extract_item_identity(data)
            key = collection_item_key_for(
                item_db_id=identity.get("item_db_id"),
                variant_db_id=identity.get("variant_db_id"),
                vplib_uid=identity.get("vplib_uid"),
                family_id=identity.get("family_id"),
                package_id=identity.get("package_id"),
                variant_id=identity.get("variant_id"),
            )

        data["item_key"] = key
        data.setdefault("is_standard", True)
        data.setdefault("is_user_added", False)
        items_by_key[key] = data

    for item in normalize_json_list(user_items):
        if not isinstance(item, Mapping):
            continue

        data = normalize_json_mapping(item)
        key = normalize_optional_string(data.get("item_key"), max_length=MAX_KEY_LENGTH)

        if not key:
            identity = extract_item_identity(data)
            key = collection_item_key_for(
                item_db_id=identity.get("item_db_id"),
                variant_db_id=identity.get("variant_db_id"),
                vplib_uid=identity.get("vplib_uid"),
                family_id=identity.get("family_id"),
                package_id=identity.get("package_id"),
                variant_id=identity.get("variant_id"),
            )

        data["item_key"] = key
        data.setdefault("is_user_added", True)
        items_by_key[key] = data

    for override in normalize_json_list(overrides):
        if not isinstance(override, Mapping):
            continue

        override_data = normalize_json_mapping(override)
        target_key = normalize_optional_string(override_data.get("target_key"), max_length=MAX_KEY_LENGTH)

        if not target_key:
            continue

        if target_key in items_by_key:
            items_by_key[target_key] = apply_user_override_to_item_payload(items_by_key[target_key], override_data)

    resolved_items = [
        item
        for item in items_by_key.values()
        if normalize_bool(item.get("active"), default=True)
    ]

    resolved_items.sort(
        key=lambda item: (
            normalize_int(item.get("sort_order"), default=0) or 0,
            clean_string(item.get("label") or item.get("name") or item.get("item_key")),
        )
    )

    result["items"] = resolved_items
    result["item_count"] = len(resolved_items)
    result["resolved_at"] = utc_now().isoformat()
    return result


# ---------------------------------------------------------------------------
# Public model helpers
# ---------------------------------------------------------------------------

def iter_creative_library_user_models() -> tuple[type[Any], ...]:
    """Gibt alle echten Modelklassen dieser Datei zurück."""
    return (
        CreativeLibraryCollection,
        CreativeLibraryCollectionItem,
        CreativeLibraryUserOverride,
        CreativeLibraryUserAuditEvent,
    )


def iter_models() -> tuple[type[Any], ...]:
    """Kompatibler Alias für models.__init__.py."""
    return iter_creative_library_user_models()


def get_models() -> tuple[type[Any], ...]:
    """Kompatibler Alias für Modelle-Discovery."""
    return iter_creative_library_user_models()


def get_creative_library_user_model_names() -> tuple[str, ...]:
    """Gibt alle Modelklassennamen zurück."""
    return tuple(model.__name__ for model in iter_creative_library_user_models())


def get_creative_library_user_table_names() -> tuple[str, ...]:
    """Gibt alle Tabellennamen zurück."""
    return tuple(str(getattr(model, "__tablename__", "")) for model in iter_creative_library_user_models())


def get_creative_library_user_models_health() -> dict[str, Any]:
    """JSON-kompatibler Health-Snapshot dieser Model-Datei."""
    model_names = get_creative_library_user_model_names()
    table_names = get_creative_library_user_table_names()

    try:
        metadata = getattr(db, "metadata", None)
        tables = getattr(metadata, "tables", None)

        if tables is None:
            metadata_table_names: tuple[str, ...] = tuple()
        else:
            metadata_table_names = tuple(sorted(str(name) for name in tables.keys()))

        missing_tables = [table_name for table_name in table_names if table_name not in metadata_table_names]
        healthy = len(model_names) > 0 and len(table_names) > 0 and not missing_tables

        return {
            "schema_version": CREATIVE_LIBRARY_USER_MODELS_SCHEMA_VERSION,
            "healthy": healthy,
            "ok": healthy,
            "model_count": len(model_names),
            "table_count": len(table_names),
            "model_names": list(model_names),
            "table_names": list(table_names),
            "metadata_table_count": len(metadata_table_names),
            "metadata_table_names": list(metadata_table_names),
            "missing_tables": missing_tables,
            "supports_collections": True,
            "supports_collection_items": True,
            "supports_user_overrides": True,
            "supports_user_audit_events": True,
            "supports_resolved_collection_helpers": True,
            "default_collection_key": DEFAULT_COLLECTION_KEY,
            "default_user_collection_key": DEFAULT_USER_COLLECTION_KEY,
        }
    except Exception as exc:
        return {
            "schema_version": CREATIVE_LIBRARY_USER_MODELS_SCHEMA_VERSION,
            "healthy": False,
            "ok": False,
            "model_count": len(model_names),
            "table_count": len(table_names),
            "model_names": list(model_names),
            "table_names": list(table_names),
            "error": f"{type(exc).__name__}: {exc}",
        }


def assert_creative_library_user_models_ready() -> None:
    """Wirft RuntimeError, wenn die User-Creative-Library-Models nicht bereit sind."""
    health = get_creative_library_user_models_health()

    if health.get("healthy"):
        return

    raise RuntimeError(f"Creative library user models are not ready: {health}")


def clear_creative_library_user_model_caches() -> dict[str, Any]:
    """Leert interne Caches dieser Datei."""
    cleared: list[str] = []

    for cached_func in (
        _load_db,
        _cached_slugify,
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


# ---------------------------------------------------------------------------
# Public exports
# ---------------------------------------------------------------------------

__all__ = [
    # Metadata / constants
    "CREATIVE_LIBRARY_USER_MODELS_SCHEMA_VERSION",
    "DEFAULT_USER_ID",
    "DEFAULT_COLLECTION_KEY",
    "DEFAULT_USER_COLLECTION_KEY",

    # Enums
    "CreativeLibraryUserSourceScope",
    "CreativeLibraryUserStatus",
    "CreativeLibraryCollectionKind",
    "CreativeLibraryUserOverrideAction",
    "CreativeLibraryUserTargetType",
    "CreativeLibraryUserAuditEventType",

    # Models
    "CreativeLibraryCollection",
    "CreativeLibraryCollectionItem",
    "CreativeLibraryUserOverride",
    "CreativeLibraryUserAuditEvent",

    # Helpers
    "utc_now",
    "new_uid",
    "enum_value",
    "first_non_empty",
    "clean_string",
    "normalize_optional_string",
    "normalize_required_string",
    "normalize_bool",
    "normalize_optional_bool",
    "normalize_int",
    "normalize_user_id",
    "normalize_json_mapping",
    "normalize_json_list",
    "normalize_json_value",
    "merge_json",
    "stable_json_hash",
    "normalize_source_scope",
    "owner_scope_for",
    "normalize_status",
    "normalize_collection_key",
    "normalize_taxonomy_part",
    "taxonomy_path_for",
    "normalize_action",
    "normalize_target_type",
    "extract_item_identity",
    "collection_item_key_for",
    "apply_user_override_to_item_payload",
    "build_resolved_collection_payload",

    # Model discovery / health
    "iter_creative_library_user_models",
    "iter_models",
    "get_models",
    "get_creative_library_user_model_names",
    "get_creative_library_user_table_names",
    "get_creative_library_user_models_health",
    "assert_creative_library_user_models_ready",
    "clear_creative_library_user_model_caches",
]