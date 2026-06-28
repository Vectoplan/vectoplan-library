# services/vectoplan-library/src/library/repositories/creative_library_user_repository.py
"""
Repository for VECTOPLAN Creative Library User Overlay.

Diese Datei kapselt alle DB-Zugriffe auf:

- creative_library_collections
- creative_library_collection_items
- creative_library_user_overrides
- creative_library_user_audit_events

Ziel:

    System Creative Library
        + User Collections
        + User Added Items
        + User Hidden/Removed Items
        + User Overrides
        -> user-resolved Creative Library / Creative Inventory

Architekturregeln:

- Repository enthält keine Flask-Routes.
- Repository enthält keine UI-Logik.
- Repository enthält keine Generator-Publish-Logik.
- Repository erzeugt keine Tabellen.
- Repository führt keine Migration aus.
- Repository führt kein db.create_all() aus.
- Repository öffnet keine aktive DB-Verbindung beim Import.
- DB-Zugriffe laufen nur in expliziten Methoden.
- Standardbibliothek wird nicht pro User kopiert.
- User-Änderungen sind User Collections, Collection Items oder Overrides.
- Technische Namen, JSON-Keys und Variablen bleiben Englisch.

Phase 1:

- user_id darf weiterhin 1 sein.
- owner_user_id=None bedeutet System Collection.
- owner_user_id=1 bedeutet User Collection.
- owner_scope="system" oder "user:1".
"""

from __future__ import annotations

import importlib
from dataclasses import dataclass, field
from functools import lru_cache
from types import ModuleType
from typing import Any, Final, Iterable, Mapping, Sequence


# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

CREATIVE_LIBRARY_USER_REPOSITORY_VERSION: Final[str] = "vectoplan_library.repository.creative_library_user.v1"

DEFAULT_USER_ID: Final[int] = 1

SOURCE_SCOPE_SYSTEM: Final[str] = "system"
SOURCE_SCOPE_USER: Final[str] = "user"
SOURCE_SCOPE_IMPORTED: Final[str] = "imported"
SOURCE_SCOPE_GENERATED: Final[str] = "generated"

STATUS_ACTIVE: Final[str] = "active"
STATUS_INACTIVE: Final[str] = "inactive"
STATUS_HIDDEN: Final[str] = "hidden"
STATUS_DELETED: Final[str] = "deleted"
STATUS_ARCHIVED: Final[str] = "archived"

COLLECTION_KIND_DEFAULT: Final[str] = "default"
COLLECTION_KIND_USER: Final[str] = "user"
COLLECTION_KIND_PROJECT: Final[str] = "project"
COLLECTION_KIND_FAVORITES: Final[str] = "favorites"
COLLECTION_KIND_RECENT: Final[str] = "recent"
COLLECTION_KIND_SYSTEM: Final[str] = "system"

TARGET_TYPE_ITEM: Final[str] = "item"
TARGET_TYPE_VARIANT: Final[str] = "variant"
TARGET_TYPE_COLLECTION: Final[str] = "collection"
TARGET_TYPE_COLLECTION_ITEM: Final[str] = "collection_item"
TARGET_TYPE_TAXONOMY_NODE: Final[str] = "taxonomy_node"
TARGET_TYPE_DEFINITION: Final[str] = "definition"
TARGET_TYPE_DRAFT: Final[str] = "draft"

ACTION_ADD: Final[str] = "add"
ACTION_REMOVE: Final[str] = "remove"
ACTION_HIDE: Final[str] = "hide"
ACTION_RESTORE: Final[str] = "restore"
ACTION_RENAME: Final[str] = "rename"
ACTION_REORDER: Final[str] = "reorder"
ACTION_FAVORITE: Final[str] = "favorite"
ACTION_UNFAVORITE: Final[str] = "unfavorite"
ACTION_PIN: Final[str] = "pin"
ACTION_UNPIN: Final[str] = "unpin"
ACTION_PATCH: Final[str] = "patch"
ACTION_REMOVE_FROM_USER_LIBRARY: Final[str] = "remove_from_user_library"

DEFAULT_SYSTEM_COLLECTION_KEY: Final[str] = "default"
DEFAULT_USER_COLLECTION_KEY: Final[str] = "user-default"
DEFAULT_FAVORITES_COLLECTION_KEY: Final[str] = "favorites"

DEFAULT_LIMIT: Final[int] = 500
MAX_LIMIT: Final[int] = 5000


# ---------------------------------------------------------------------------
# Exceptions
# ---------------------------------------------------------------------------

class CreativeLibraryUserRepositoryError(RuntimeError):
    """Base error for CreativeLibraryUserRepository."""


class CreativeLibraryUserRepositoryImportError(CreativeLibraryUserRepositoryError):
    """Raised when db/model imports fail."""


class CreativeLibraryCollectionNotFoundError(CreativeLibraryUserRepositoryError):
    """Raised when a collection cannot be found."""


class CreativeLibraryCollectionItemNotFoundError(CreativeLibraryUserRepositoryError):
    """Raised when a collection item cannot be found."""


class CreativeLibraryUserOverrideNotFoundError(CreativeLibraryUserRepositoryError):
    """Raised when an override cannot be found."""


class CreativeLibraryUserConflictError(CreativeLibraryUserRepositoryError):
    """Raised when an operation conflicts with ownership or state."""


# ---------------------------------------------------------------------------
# Lazy imports
# ---------------------------------------------------------------------------

@lru_cache(maxsize=1)
def _load_db() -> Any:
    """Loads the central Flask-SQLAlchemy extension defensively."""
    errors: list[str] = []

    for module_name in (
        "extensions",
        "src.extensions",
        "vectoplan_library.extensions",
    ):
        try:
            module = importlib.import_module(module_name)
            db_obj = getattr(module, "db", None)
            if db_obj is not None:
                return db_obj
            errors.append(f"{module_name}: db missing")
        except Exception as exc:
            errors.append(f"{module_name}: {type(exc).__name__}: {exc}")

    raise CreativeLibraryUserRepositoryImportError(
        "Could not import SQLAlchemy extension `db`. "
        + " | ".join(errors)
    )


@lru_cache(maxsize=1)
def _load_user_models_module() -> ModuleType:
    """Loads models.creative_library_user defensively."""
    errors: list[str] = []

    for module_name in (
        "models.creative_library_user",
        "src.models.creative_library_user",
        "vectoplan_library.models.creative_library_user",
    ):
        try:
            return importlib.import_module(module_name)
        except Exception as exc:
            errors.append(f"{module_name}: {type(exc).__name__}: {exc}")

    raise CreativeLibraryUserRepositoryImportError(
        "Could not import creative_library_user models. "
        + " | ".join(errors)
    )


def _db() -> Any:
    """Short alias for lazy db access."""
    return _load_db()


def _models() -> ModuleType:
    """Short alias for lazy model access."""
    return _load_user_models_module()


# ---------------------------------------------------------------------------
# Generic helpers
# ---------------------------------------------------------------------------

def clean_string(value: Any, *, fallback: str = "") -> str:
    """Converts value to safe stripped string."""
    try:
        if value is None:
            return fallback

        text = str(value).replace("\x00", "").strip()
        return text if text else fallback
    except Exception:
        return fallback


def optional_string(value: Any, *, max_length: int | None = None) -> str | None:
    """Normalizes optional string values."""
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


def normalize_int(
    value: Any,
    *,
    default: int | None = 0,
    minimum: int | None = None,
    maximum: int | None = None,
) -> int | None:
    """Normalizes integer values."""
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
    """Normalizes user_id."""
    return normalize_int(value, default=default, minimum=1)


def normalize_bool(value: Any, *, default: bool = False) -> bool:
    """Normalizes boolean-like values."""
    if isinstance(value, bool):
        return value

    if value is None:
        return default

    text = clean_string(value).lower()

    if text in {"1", "true", "yes", "y", "ja", "on", "enabled", "active", "visible", "favorite", "pinned"}:
        return True

    if text in {"0", "false", "no", "n", "nein", "off", "disabled", "inactive", "hidden", "deleted"}:
        return False

    return default


def normalize_json_mapping(value: Mapping[str, Any] | None) -> dict[str, Any]:
    """Normalizes mapping values."""
    if value is None:
        return {}

    if not isinstance(value, Mapping):
        return {"value": normalize_json_value(value)}

    result: dict[str, Any] = {}

    for key, child_value in value.items():
        result[str(key)] = normalize_json_value(child_value)

    return result


def normalize_json_list(value: Iterable[Any] | None) -> list[Any]:
    """Normalizes list-like values."""
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
    """Normalizes arbitrary values for JSON payloads."""
    if value is None or isinstance(value, (str, int, float, bool)):
        return value

    if isinstance(value, Mapping):
        return normalize_json_mapping(value)

    if isinstance(value, (list, tuple, set)):
        return [normalize_json_value(item) for item in value]

    if hasattr(value, "isoformat") and callable(value.isoformat):
        try:
            return value.isoformat()
        except Exception:
            return str(value)

    if hasattr(value, "to_dict") and callable(value.to_dict):
        try:
            return normalize_json_value(value.to_dict())
        except Exception:
            return str(value)

    return str(value)


def enum_value(value: Any, *, default: str = "") -> str:
    """Normalizes enum/string values."""
    if value is None:
        return default

    if hasattr(value, "value"):
        try:
            text = str(value.value).strip()
            return text or default
        except Exception:
            return default

    return clean_string(value, fallback=default)


def owner_scope_for(*, source_scope: Any = SOURCE_SCOPE_USER, owner_user_id: Any = DEFAULT_USER_ID) -> str:
    """Builds stable owner_scope."""
    helper = getattr(_models(), "owner_scope_for", None)

    if callable(helper):
        try:
            return str(helper(source_scope=source_scope, owner_user_id=owner_user_id))
        except Exception:
            pass

    scope = clean_string(source_scope, fallback=SOURCE_SCOPE_USER).lower()
    user_id = normalize_user_id(owner_user_id, default=None)

    if scope == SOURCE_SCOPE_SYSTEM and user_id is None:
        return SOURCE_SCOPE_SYSTEM

    if scope == SOURCE_SCOPE_USER:
        return f"user:{user_id or DEFAULT_USER_ID}"

    if user_id is not None:
        return f"{scope}:{user_id}"

    return scope


def to_dict_or_payload(value: Any, **kwargs: Any) -> dict[str, Any]:
    """Serializes model objects defensively."""
    if value is None:
        return {}

    if hasattr(value, "to_dict") and callable(value.to_dict):
        try:
            return normalize_json_mapping(value.to_dict(**kwargs))
        except TypeError:
            try:
                return normalize_json_mapping(value.to_dict())
            except Exception:
                pass
        except Exception:
            pass

    if isinstance(value, Mapping):
        return normalize_json_mapping(value)

    result: dict[str, Any] = {}

    for field_name in (
        "id",
        "collection_uid",
        "collection_item_uid",
        "override_uid",
        "event_uid",
        "collection_key",
        "collection_kind",
        "label",
        "name",
        "description",
        "source_scope",
        "owner_user_id",
        "owner_scope",
        "user_id",
        "target_type",
        "target_id",
        "target_uid",
        "item_db_id",
        "variant_db_id",
        "vplib_uid",
        "family_id",
        "package_id",
        "variant_id",
        "status",
        "active",
        "visible",
        "pinned",
        "favorite",
        "sort_order",
        "created_at",
        "updated_at",
    ):
        try:
            if hasattr(value, field_name):
                result[field_name] = normalize_json_value(getattr(value, field_name))
        except Exception:
            continue

    return result


def _new_model_with_attrs(model_class: type[Any], attrs: Mapping[str, Any]) -> Any:
    """Creates SQLAlchemy model instance and sets only available attributes."""
    obj = model_class()

    for key, value in attrs.items():
        try:
            if hasattr(obj, key):
                setattr(obj, key, value)
        except Exception:
            continue

    return obj


def _dedupe_preserve_order(values: Iterable[Any]) -> tuple[Any, ...]:
    """Dedupe helper preserving order."""
    result: list[Any] = []
    seen: set[str] = set()

    for value in values or ():
        key = repr(value)
        if key in seen:
            continue
        seen.add(key)
        result.append(value)

    return tuple(result)


def extract_item_identity(payload: Mapping[str, Any] | Any) -> dict[str, Any]:
    """Extracts a stable item/variant identity from payload or model object."""
    if isinstance(payload, Mapping):
        data = normalize_json_mapping(payload)
        getter = data.get
    else:
        data = {}
        getter = lambda key, default=None: getattr(payload, key, default)

    return {
        "target_type": optional_string(getter("target_type")) or TARGET_TYPE_ITEM,
        "target_id": normalize_int(getter("target_id"), default=None, minimum=1),
        "target_uid": optional_string(getter("target_uid")),
        "item_db_id": normalize_int(getter("item_db_id"), default=None, minimum=1),
        "variant_db_id": normalize_int(getter("variant_db_id"), default=None, minimum=1),
        "vplib_uid": optional_string(getter("vplib_uid")),
        "family_id": optional_string(getter("family_id")),
        "package_id": optional_string(getter("package_id")),
        "variant_id": optional_string(getter("variant_id")),
        "draft_id": normalize_int(getter("draft_id"), default=None, minimum=1),
        "draft_uid": optional_string(getter("draft_uid")),
    }


def item_identity_key(identity: Mapping[str, Any]) -> str:
    """Builds a stable key for an item identity."""
    data = normalize_json_mapping(identity)

    for field_name in (
        "target_uid",
        "vplib_uid",
        "variant_id",
        "family_id",
        "package_id",
        "draft_uid",
    ):
        value = optional_string(data.get(field_name))
        if value:
            return f"{field_name}:{value}"

    for field_name in ("target_id", "item_db_id", "variant_db_id", "draft_id"):
        value = normalize_int(data.get(field_name), default=None, minimum=1)
        if value is not None:
            return f"{field_name}:{value}"

    return repr(sorted(data.items()))


def target_key_from_payload(payload: Mapping[str, Any] | Any) -> str:
    """Builds target key for overrides."""
    return item_identity_key(extract_item_identity(payload))


# ---------------------------------------------------------------------------
# Dataclasses
# ---------------------------------------------------------------------------

@dataclass(slots=True)
class CollectionQuery:
    """Structured collection query."""

    user_id: int | None = None
    owner_user_id: int | None = None
    owner_scope: str | None = None
    source_scope: str | None = None
    collection_uid: str | None = None
    collection_key: str | None = None
    collection_kind: str | None = None
    active_only: bool = True
    visible_only: bool = False
    include_deleted: bool = False
    include_system: bool = True
    include_user: bool = True
    limit: int = DEFAULT_LIMIT
    offset: int = 0

    @classmethod
    def from_payload(cls, payload: Mapping[str, Any] | None = None, **kwargs: Any) -> "CollectionQuery":
        data = normalize_json_mapping(payload)
        data.update({key: value for key, value in kwargs.items() if value is not None})

        return cls(
            user_id=normalize_user_id(data.get("user_id"), default=None),
            owner_user_id=normalize_user_id(data.get("owner_user_id"), default=None),
            owner_scope=optional_string(data.get("owner_scope")),
            source_scope=optional_string(data.get("source_scope")),
            collection_uid=optional_string(data.get("collection_uid")),
            collection_key=optional_string(data.get("collection_key")),
            collection_kind=optional_string(data.get("collection_kind")),
            active_only=normalize_bool(data.get("active_only"), default=True),
            visible_only=normalize_bool(data.get("visible_only"), default=False),
            include_deleted=normalize_bool(data.get("include_deleted"), default=False),
            include_system=normalize_bool(data.get("include_system"), default=True),
            include_user=normalize_bool(data.get("include_user"), default=True),
            limit=normalize_int(data.get("limit"), default=DEFAULT_LIMIT, minimum=1, maximum=MAX_LIMIT) or DEFAULT_LIMIT,
            offset=normalize_int(data.get("offset"), default=0, minimum=0) or 0,
        )

    def resolved_owner_scopes(self) -> tuple[str, ...]:
        if self.owner_scope:
            return (self.owner_scope,)

        scopes: list[str] = []

        if self.include_system:
            scopes.append(SOURCE_SCOPE_SYSTEM)

        user_id = self.owner_user_id or self.user_id
        if self.include_user and user_id is not None:
            scopes.append(f"user:{user_id}")

        return tuple(_dedupe_preserve_order(scopes))


@dataclass(slots=True)
class CollectionItemQuery:
    """Structured collection item query."""

    user_id: int | None = None
    collection_id: int | None = None
    collection_uid: str | None = None
    collection_key: str | None = None
    collection_item_uid: str | None = None
    item_db_id: int | None = None
    variant_db_id: int | None = None
    vplib_uid: str | None = None
    family_id: str | None = None
    package_id: str | None = None
    variant_id: str | None = None
    target_type: str | None = None
    target_uid: str | None = None
    active_only: bool = True
    visible_only: bool = False
    pinned_only: bool = False
    favorite_only: bool = False
    include_deleted: bool = False
    limit: int = DEFAULT_LIMIT
    offset: int = 0

    @classmethod
    def from_payload(cls, payload: Mapping[str, Any] | None = None, **kwargs: Any) -> "CollectionItemQuery":
        data = normalize_json_mapping(payload)
        data.update({key: value for key, value in kwargs.items() if value is not None})

        return cls(
            user_id=normalize_user_id(data.get("user_id"), default=None),
            collection_id=normalize_int(data.get("collection_id"), default=None, minimum=1),
            collection_uid=optional_string(data.get("collection_uid")),
            collection_key=optional_string(data.get("collection_key")),
            collection_item_uid=optional_string(data.get("collection_item_uid")),
            item_db_id=normalize_int(data.get("item_db_id"), default=None, minimum=1),
            variant_db_id=normalize_int(data.get("variant_db_id"), default=None, minimum=1),
            vplib_uid=optional_string(data.get("vplib_uid")),
            family_id=optional_string(data.get("family_id")),
            package_id=optional_string(data.get("package_id")),
            variant_id=optional_string(data.get("variant_id")),
            target_type=optional_string(data.get("target_type")),
            target_uid=optional_string(data.get("target_uid")),
            active_only=normalize_bool(data.get("active_only"), default=True),
            visible_only=normalize_bool(data.get("visible_only"), default=False),
            pinned_only=normalize_bool(data.get("pinned_only"), default=False),
            favorite_only=normalize_bool(data.get("favorite_only"), default=False),
            include_deleted=normalize_bool(data.get("include_deleted"), default=False),
            limit=normalize_int(data.get("limit"), default=DEFAULT_LIMIT, minimum=1, maximum=MAX_LIMIT) or DEFAULT_LIMIT,
            offset=normalize_int(data.get("offset"), default=0, minimum=0) or 0,
        )


@dataclass(slots=True)
class UserOverrideQuery:
    """Structured user override query."""

    user_id: int = DEFAULT_USER_ID
    target_type: str | None = None
    target_id: int | None = None
    target_uid: str | None = None
    action: str | None = None
    active_only: bool = True
    include_deleted: bool = False
    limit: int = DEFAULT_LIMIT
    offset: int = 0

    @classmethod
    def from_payload(cls, payload: Mapping[str, Any] | None = None, **kwargs: Any) -> "UserOverrideQuery":
        data = normalize_json_mapping(payload)
        data.update({key: value for key, value in kwargs.items() if value is not None})

        return cls(
            user_id=normalize_user_id(data.get("user_id"), default=DEFAULT_USER_ID) or DEFAULT_USER_ID,
            target_type=optional_string(data.get("target_type")),
            target_id=normalize_int(data.get("target_id"), default=None, minimum=1),
            target_uid=optional_string(data.get("target_uid")),
            action=optional_string(data.get("action") or data.get("override_action")),
            active_only=normalize_bool(data.get("active_only"), default=True),
            include_deleted=normalize_bool(data.get("include_deleted"), default=False),
            limit=normalize_int(data.get("limit"), default=DEFAULT_LIMIT, minimum=1, maximum=MAX_LIMIT) or DEFAULT_LIMIT,
            offset=normalize_int(data.get("offset"), default=0, minimum=0) or 0,
        )


@dataclass(slots=True)
class CreativeLibraryUserWriteResult:
    """JSON-compatible write result."""

    ok: bool
    action: str
    collection_uid: str | None = None
    collection_item_uid: str | None = None
    override_uid: str | None = None
    event_uid: str | None = None
    collection_id: int | None = None
    collection_item_id: int | None = None
    override_id: int | None = None
    event_id: int | None = None
    created: bool = False
    updated: bool = False
    deleted: bool = False
    payload: dict[str, Any] = field(default_factory=dict)
    errors: list[str] = field(default_factory=list)

    def add_error(self, message: Any) -> None:
        self.ok = False
        self.errors.append(str(message))

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema_version": CREATIVE_LIBRARY_USER_REPOSITORY_VERSION,
            "ok": self.ok,
            "action": self.action,
            "collection_uid": self.collection_uid,
            "collection_item_uid": self.collection_item_uid,
            "override_uid": self.override_uid,
            "event_uid": self.event_uid,
            "collection_id": self.collection_id,
            "collection_item_id": self.collection_item_id,
            "override_id": self.override_id,
            "event_id": self.event_id,
            "created": self.created,
            "updated": self.updated,
            "deleted": self.deleted,
            "payload": normalize_json_mapping(self.payload),
            "errors": list(self.errors),
        }


# ---------------------------------------------------------------------------
# Repository
# ---------------------------------------------------------------------------

class CreativeLibraryUserRepository:
    """
    SQLAlchemy repository for Creative Library user overlay.

    Args:
        session:
            Optional SQLAlchemy session. If omitted, db.session is used lazily.

    Commit strategy:
        - Methods accept commit=False by default.
        - With commit=False, repository flushes where IDs are needed but leaves
          transaction ownership to the caller/service.
        - With commit=True, repository commits and rolls back on error.
    """

    def __init__(self, session: Any | None = None) -> None:
        self._session = session

    # ------------------------------------------------------------------
    # Session / model access
    # ------------------------------------------------------------------

    @property
    def session(self) -> Any:
        if self._session is not None:
            return self._session
        return _db().session

    @property
    def models(self) -> ModuleType:
        return _models()

    def flush(self) -> None:
        self.session.flush()

    def commit(self) -> None:
        self.session.commit()

    def rollback(self) -> None:
        self.session.rollback()

    def _finish_write(self, *, commit: bool) -> None:
        if commit:
            self.session.commit()
        else:
            self.session.flush()

    # ------------------------------------------------------------------
    # Collection reads
    # ------------------------------------------------------------------

    def get_collection_by_id(
        self,
        collection_id: Any,
        *,
        include_deleted: bool = False,
        for_update: bool = False,
    ) -> Any | None:
        """Returns collection by DB id."""
        normalized_id = normalize_int(collection_id, default=None, minimum=1)
        if normalized_id is None:
            return None

        model = self.models.CreativeLibraryCollection
        query = self.session.query(model).filter(model.id == normalized_id)

        if not include_deleted and hasattr(model, "status"):
            query = query.filter(model.status != STATUS_DELETED)

        if for_update:
            query = self._with_for_update(query)

        return query.one_or_none()

    def get_collection_by_uid(
        self,
        collection_uid: Any,
        *,
        include_deleted: bool = False,
        for_update: bool = False,
    ) -> Any | None:
        """Returns collection by collection_uid."""
        uid = optional_string(collection_uid)
        if not uid:
            return None

        model = self.models.CreativeLibraryCollection
        query = self.session.query(model).filter(model.collection_uid == uid)

        if not include_deleted and hasattr(model, "status"):
            query = query.filter(model.status != STATUS_DELETED)

        if for_update:
            query = self._with_for_update(query)

        return query.one_or_none()

    def get_collection_by_key(
        self,
        collection_key: Any,
        *,
        user_id: Any = None,
        source_scope: Any = None,
        include_deleted: bool = False,
        for_update: bool = False,
    ) -> Any | None:
        """Returns collection by key and optional owner/scope."""
        key = optional_string(collection_key)
        if not key:
            return None

        model = self.models.CreativeLibraryCollection
        query = self.session.query(model).filter(model.collection_key == key)

        if source_scope and hasattr(model, "source_scope"):
            query = query.filter(model.source_scope == source_scope)

        normalized_user_id = normalize_user_id(user_id, default=None)
        if normalized_user_id is not None and hasattr(model, "owner_scope"):
            query = query.filter(model.owner_scope.in_((SOURCE_SCOPE_SYSTEM, f"user:{normalized_user_id}")))

        if not include_deleted and hasattr(model, "status"):
            query = query.filter(model.status != STATUS_DELETED)

        query = self._apply_collection_sort(query, model)

        if for_update:
            query = self._with_for_update(query)

        values = query.all()

        if not values:
            return None

        if normalized_user_id is not None:
            user_scope = f"user:{normalized_user_id}"
            for collection in values:
                if getattr(collection, "owner_scope", None) == user_scope:
                    return collection

        for collection in values:
            if getattr(collection, "owner_scope", None) == SOURCE_SCOPE_SYSTEM:
                return collection

        return values[0]

    def get_collection(
        self,
        collection_ref: Any,
        *,
        include_deleted: bool = False,
        for_update: bool = False,
    ) -> Any | None:
        """Returns collection by id, uid or key."""
        text = clean_string(collection_ref)

        if text.isdigit():
            return self.get_collection_by_id(text, include_deleted=include_deleted, for_update=for_update)

        collection = self.get_collection_by_uid(text, include_deleted=include_deleted, for_update=for_update)
        if collection is not None:
            return collection

        return self.get_collection_by_key(text, include_deleted=include_deleted, for_update=for_update)

    def require_collection(
        self,
        collection_ref: Any,
        *,
        include_deleted: bool = False,
        for_update: bool = False,
    ) -> Any:
        """Returns collection or raises."""
        collection = self.get_collection(collection_ref, include_deleted=include_deleted, for_update=for_update)

        if collection is None:
            raise CreativeLibraryCollectionNotFoundError(f"Creative Library collection {collection_ref!r} was not found.")

        return collection

    def list_collections(
        self,
        *,
        query: CollectionQuery | Mapping[str, Any] | None = None,
        as_dict: bool = False,
    ) -> list[Any]:
        """Lists collections."""
        collection_query = query if isinstance(query, CollectionQuery) else CollectionQuery.from_payload(query)
        model = self.models.CreativeLibraryCollection
        db_query = self.session.query(model)

        owner_scopes = collection_query.resolved_owner_scopes()
        if owner_scopes and hasattr(model, "owner_scope"):
            db_query = db_query.filter(model.owner_scope.in_(owner_scopes))

        for field_name in ("source_scope", "collection_uid", "collection_key", "collection_kind"):
            value = getattr(collection_query, field_name)
            if value is not None and hasattr(model, field_name):
                db_query = db_query.filter(getattr(model, field_name) == value)

        if collection_query.owner_user_id is not None and hasattr(model, "owner_user_id"):
            db_query = db_query.filter(model.owner_user_id == collection_query.owner_user_id)

        if collection_query.active_only and hasattr(model, "active"):
            db_query = db_query.filter(model.active.is_(True))

        if collection_query.visible_only and hasattr(model, "visible"):
            db_query = db_query.filter(model.visible.is_(True))

        if not collection_query.include_deleted and hasattr(model, "status"):
            db_query = db_query.filter(model.status != STATUS_DELETED)

        db_query = self._apply_collection_sort(db_query, model)

        if collection_query.offset:
            db_query = db_query.offset(collection_query.offset)

        if collection_query.limit:
            db_query = db_query.limit(collection_query.limit)

        values = db_query.all()

        if as_dict:
            return [to_dict_or_payload(value) for value in values]

        return values

    def list_collection_payloads(self, *, query: CollectionQuery | Mapping[str, Any] | None = None) -> list[dict[str, Any]]:
        """Lists collections as dicts."""
        return self.list_collections(query=query, as_dict=True)

    # ------------------------------------------------------------------
    # Collection writes
    # ------------------------------------------------------------------

    def create_collection(
        self,
        payload: Mapping[str, Any],
        *,
        owner_user_id: Any = DEFAULT_USER_ID,
        source_scope: Any = SOURCE_SCOPE_USER,
        created_by_user_id: Any = None,
        commit: bool = False,
        audit: bool = True,
    ) -> Any:
        """Creates a collection."""
        data = normalize_json_mapping(payload)

        try:
            creator = getattr(self.models.CreativeLibraryCollection, "create_from_payload", None)

            if callable(creator):
                collection = creator(
                    data,
                    owner_user_id=owner_user_id,
                    source_scope=source_scope,
                    created_by_user_id=created_by_user_id,
                )
            else:
                collection = _new_model_with_attrs(
                    self.models.CreativeLibraryCollection,
                    self._fallback_collection_attrs(
                        data,
                        owner_user_id=owner_user_id,
                        source_scope=source_scope,
                    ),
                )

            self.session.add(collection)
            self.session.flush()

            if audit:
                self.create_audit_event(
                    event_type="collection_created",
                    user_id=created_by_user_id or owner_user_id,
                    collection=collection,
                    after=to_dict_or_payload(collection),
                    commit=False,
                )

            self._finish_write(commit=commit)
            return collection

        except Exception:
            if commit:
                self.rollback()
            raise

    def update_collection(
        self,
        collection_ref: Any,
        payload: Mapping[str, Any],
        *,
        user_id: Any = None,
        commit: bool = False,
        audit: bool = True,
    ) -> Any:
        """Updates mutable collection fields."""
        data = normalize_json_mapping(payload)

        try:
            collection = self.require_collection(collection_ref, include_deleted=True, for_update=True)

            if getattr(collection, "owner_scope", None) == SOURCE_SCOPE_SYSTEM:
                raise CreativeLibraryUserConflictError("System collections should not be modified directly.")

            before = to_dict_or_payload(collection)

            updater = getattr(collection, "update_from_payload", None)
            if callable(updater):
                updater(data, updated_by_user_id=user_id)
            else:
                self._fallback_update_collection(collection, data, user_id=user_id)

            after = to_dict_or_payload(collection)

            if audit:
                self.create_audit_event(
                    event_type="collection_updated",
                    user_id=user_id or getattr(collection, "owner_user_id", None),
                    collection=collection,
                    before=before,
                    after=after,
                    commit=False,
                )

            self._finish_write(commit=commit)
            return collection

        except Exception:
            if commit:
                self.rollback()
            raise

    def soft_delete_collection(
        self,
        collection_ref: Any,
        *,
        user_id: Any = None,
        commit: bool = False,
        audit: bool = True,
    ) -> bool:
        """Soft-deletes a user collection."""
        try:
            collection = self.require_collection(collection_ref, include_deleted=True, for_update=True)

            if getattr(collection, "owner_scope", None) == SOURCE_SCOPE_SYSTEM:
                raise CreativeLibraryUserConflictError("System collections should not be deleted directly.")

            before = to_dict_or_payload(collection)

            if hasattr(collection, "mark_deleted") and callable(collection.mark_deleted):
                collection.mark_deleted(user_id=user_id)
            else:
                collection.status = STATUS_DELETED
                if hasattr(collection, "active"):
                    collection.active = False
                if hasattr(collection, "visible"):
                    collection.visible = False

            after = to_dict_or_payload(collection)

            if audit:
                self.create_audit_event(
                    event_type="collection_deleted",
                    user_id=user_id or getattr(collection, "owner_user_id", None),
                    collection=collection,
                    before=before,
                    after=after,
                    commit=False,
                )

            self._finish_write(commit=commit)
            return True

        except Exception:
            if commit:
                self.rollback()
            raise

    def restore_collection(
        self,
        collection_ref: Any,
        *,
        user_id: Any = None,
        commit: bool = False,
        audit: bool = True,
    ) -> Any:
        """Restores a user collection."""
        try:
            collection = self.require_collection(collection_ref, include_deleted=True, for_update=True)

            if getattr(collection, "owner_scope", None) == SOURCE_SCOPE_SYSTEM:
                raise CreativeLibraryUserConflictError("System collections should not be restored directly.")

            before = to_dict_or_payload(collection)

            if hasattr(collection, "restore") and callable(collection.restore):
                collection.restore(user_id=user_id)
            else:
                collection.status = STATUS_ACTIVE
                if hasattr(collection, "active"):
                    collection.active = True
                if hasattr(collection, "visible"):
                    collection.visible = True

            after = to_dict_or_payload(collection)

            if audit:
                self.create_audit_event(
                    event_type="collection_restored",
                    user_id=user_id or getattr(collection, "owner_user_id", None),
                    collection=collection,
                    before=before,
                    after=after,
                    commit=False,
                )

            self._finish_write(commit=commit)
            return collection

        except Exception:
            if commit:
                self.rollback()
            raise

    def get_or_create_user_collection(
        self,
        *,
        user_id: Any = DEFAULT_USER_ID,
        collection_key: Any = DEFAULT_USER_COLLECTION_KEY,
        label: Any = "Meine Bibliothek",
        collection_kind: Any = COLLECTION_KIND_USER,
        commit: bool = False,
    ) -> tuple[Any, bool]:
        """Gets or creates a user collection."""
        normalized_user_id = normalize_user_id(user_id, default=DEFAULT_USER_ID) or DEFAULT_USER_ID
        key = clean_string(collection_key, fallback=DEFAULT_USER_COLLECTION_KEY)

        existing = self.get_collection_by_key(
            key,
            user_id=normalized_user_id,
            source_scope=SOURCE_SCOPE_USER,
            include_deleted=False,
        )

        if existing is not None:
            return existing, False

        collection = self.create_collection(
            {
                "collection_key": key,
                "collection_kind": collection_kind,
                "label": label,
                "active": True,
                "visible": True,
            },
            owner_user_id=normalized_user_id,
            source_scope=SOURCE_SCOPE_USER,
            created_by_user_id=normalized_user_id,
            commit=commit,
            audit=True,
        )
        return collection, True

    # ------------------------------------------------------------------
    # Collection item reads
    # ------------------------------------------------------------------

    def get_collection_item_by_id(
        self,
        collection_item_id: Any,
        *,
        include_deleted: bool = False,
        for_update: bool = False,
    ) -> Any | None:
        """Returns collection item by DB id."""
        normalized_id = normalize_int(collection_item_id, default=None, minimum=1)
        if normalized_id is None:
            return None

        model = self.models.CreativeLibraryCollectionItem
        query = self.session.query(model).filter(model.id == normalized_id)

        if not include_deleted and hasattr(model, "status"):
            query = query.filter(model.status != STATUS_DELETED)

        if for_update:
            query = self._with_for_update(query)

        return query.one_or_none()

    def get_collection_item_by_uid(
        self,
        collection_item_uid: Any,
        *,
        include_deleted: bool = False,
        for_update: bool = False,
    ) -> Any | None:
        """Returns collection item by uid."""
        uid = optional_string(collection_item_uid)
        if not uid:
            return None

        model = self.models.CreativeLibraryCollectionItem
        query = self.session.query(model)

        uid_columns = ("collection_item_uid", "item_uid")
        found_column = False
        for column_name in uid_columns:
            if hasattr(model, column_name):
                query = query.filter(getattr(model, column_name) == uid)
                found_column = True
                break

        if not found_column:
            return None

        if not include_deleted and hasattr(model, "status"):
            query = query.filter(model.status != STATUS_DELETED)

        if for_update:
            query = self._with_for_update(query)

        return query.one_or_none()

    def get_collection_item(
        self,
        collection_item_ref: Any,
        *,
        include_deleted: bool = False,
        for_update: bool = False,
    ) -> Any | None:
        """Returns collection item by id or uid."""
        text = clean_string(collection_item_ref)

        if text.isdigit():
            return self.get_collection_item_by_id(text, include_deleted=include_deleted, for_update=for_update)

        return self.get_collection_item_by_uid(text, include_deleted=include_deleted, for_update=for_update)

    def require_collection_item(
        self,
        collection_item_ref: Any,
        *,
        include_deleted: bool = False,
        for_update: bool = False,
    ) -> Any:
        """Returns collection item or raises."""
        item = self.get_collection_item(collection_item_ref, include_deleted=include_deleted, for_update=for_update)

        if item is None:
            raise CreativeLibraryCollectionItemNotFoundError(f"Creative Library collection item {collection_item_ref!r} was not found.")

        return item

    def list_collection_items(
        self,
        *,
        query: CollectionItemQuery | Mapping[str, Any] | None = None,
        as_dict: bool = False,
        include_collection: bool = False,
    ) -> list[Any]:
        """Lists collection items."""
        item_query = query if isinstance(query, CollectionItemQuery) else CollectionItemQuery.from_payload(query)
        model = self.models.CreativeLibraryCollectionItem
        db_query = self.session.query(model)

        collection_id = item_query.collection_id

        if collection_id is None and item_query.collection_uid:
            collection = self.get_collection_by_uid(item_query.collection_uid)
            collection_id = getattr(collection, "id", None) if collection is not None else None
            if collection_id is None:
                return []

        if collection_id is None and item_query.collection_key:
            collection = self.get_collection_by_key(item_query.collection_key, user_id=item_query.user_id)
            collection_id = getattr(collection, "id", None) if collection is not None else None
            if collection_id is None:
                return []

        if collection_id is not None and hasattr(model, "collection_id"):
            db_query = db_query.filter(model.collection_id == collection_id)

        for field_name in (
            "collection_item_uid",
            "item_db_id",
            "variant_db_id",
            "vplib_uid",
            "family_id",
            "package_id",
            "variant_id",
            "target_type",
            "target_uid",
        ):
            value = getattr(item_query, field_name)
            if value is not None and hasattr(model, field_name):
                db_query = db_query.filter(getattr(model, field_name) == value)

        if item_query.user_id is not None and hasattr(model, "user_id"):
            db_query = db_query.filter(model.user_id == item_query.user_id)

        if item_query.active_only and hasattr(model, "active"):
            db_query = db_query.filter(model.active.is_(True))

        if item_query.visible_only and hasattr(model, "visible"):
            db_query = db_query.filter(model.visible.is_(True))

        if item_query.pinned_only and hasattr(model, "pinned"):
            db_query = db_query.filter(model.pinned.is_(True))

        if item_query.favorite_only and hasattr(model, "favorite"):
            db_query = db_query.filter(model.favorite.is_(True))

        if not item_query.include_deleted and hasattr(model, "status"):
            db_query = db_query.filter(model.status != STATUS_DELETED)

        db_query = self._apply_collection_item_sort(db_query, model)

        if item_query.offset:
            db_query = db_query.offset(item_query.offset)

        if item_query.limit:
            db_query = db_query.limit(item_query.limit)

        values = db_query.all()

        if as_dict:
            result: list[dict[str, Any]] = []
            for value in values:
                if hasattr(value, "to_dict"):
                    try:
                        result.append(value.to_dict(include_collection=include_collection))
                        continue
                    except TypeError:
                        pass
                    except Exception:
                        pass
                result.append(to_dict_or_payload(value))
            return result

        return values

    def list_collection_item_payloads(
        self,
        *,
        query: CollectionItemQuery | Mapping[str, Any] | None = None,
        include_collection: bool = False,
    ) -> list[dict[str, Any]]:
        """Lists collection items as dicts."""
        return self.list_collection_items(query=query, as_dict=True, include_collection=include_collection)

    def find_collection_item(
        self,
        *,
        collection_ref: Any,
        identity: Mapping[str, Any],
        include_deleted: bool = False,
        for_update: bool = False,
    ) -> Any | None:
        """Finds an item in a collection by identity fields."""
        collection = self.require_collection(collection_ref)
        model = self.models.CreativeLibraryCollectionItem

        base_query = self.session.query(model).filter(model.collection_id == collection.id)

        if not include_deleted and hasattr(model, "status"):
            base_query = base_query.filter(model.status != STATUS_DELETED)

        candidates = []

        for field_name in ("target_uid", "vplib_uid", "variant_id", "family_id", "package_id"):
            value = optional_string(identity.get(field_name))
            if value and hasattr(model, field_name):
                candidates.append((field_name, value))

        for field_name in ("target_id", "item_db_id", "variant_db_id", "draft_id"):
            value = normalize_int(identity.get(field_name), default=None, minimum=1)
            if value is not None and hasattr(model, field_name):
                candidates.append((field_name, value))

        for field_name, value in candidates:
            query = base_query.filter(getattr(model, field_name) == value)
            if for_update:
                query = self._with_for_update(query)

            item = query.first()
            if item is not None:
                return item

        return None

    # ------------------------------------------------------------------
    # Collection item writes
    # ------------------------------------------------------------------

    def add_item_to_collection(
        self,
        collection_ref: Any,
        item_payload: Mapping[str, Any],
        *,
        user_id: Any = DEFAULT_USER_ID,
        added_by_user_id: Any = None,
        commit: bool = False,
        audit: bool = True,
    ) -> tuple[Any, bool]:
        """
        Adds item to a collection.

        Returns:
            (collection_item, created)
        """
        data = normalize_json_mapping(item_payload)
        normalized_user_id = normalize_user_id(user_id, default=DEFAULT_USER_ID) or DEFAULT_USER_ID

        try:
            collection = self.require_collection(collection_ref, include_deleted=False, for_update=True)
            identity = extract_item_identity(data)

            existing = self.find_collection_item(
                collection_ref=getattr(collection, "id", None),
                identity=identity,
                include_deleted=True,
                for_update=True,
            )

            created = existing is None

            if existing is not None:
                before = to_dict_or_payload(existing)
                self._restore_or_update_collection_item(existing, data, user_id=normalized_user_id)
                item = existing
                after = to_dict_or_payload(item)

                if audit:
                    self.create_audit_event(
                        event_type="collection_item_restored" if before.get("status") == STATUS_DELETED else "collection_item_updated",
                        user_id=added_by_user_id or normalized_user_id,
                        collection=collection,
                        collection_item=item,
                        before=before,
                        after=after,
                        commit=False,
                    )
            else:
                creator = getattr(self.models.CreativeLibraryCollectionItem, "create_from_payload", None)

                if callable(creator):
                    item = creator(
                        data,
                        collection=collection,
                        user_id=normalized_user_id,
                        added_by_user_id=added_by_user_id or normalized_user_id,
                    )
                else:
                    item = _new_model_with_attrs(
                        self.models.CreativeLibraryCollectionItem,
                        self._fallback_collection_item_attrs(
                            data,
                            collection=collection,
                            user_id=normalized_user_id,
                            added_by_user_id=added_by_user_id or normalized_user_id,
                        ),
                    )

                self.session.add(item)
                self.session.flush()

                if audit:
                    self.create_audit_event(
                        event_type="collection_item_added",
                        user_id=added_by_user_id or normalized_user_id,
                        collection=collection,
                        collection_item=item,
                        after=to_dict_or_payload(item),
                        commit=False,
                    )

            self._finish_write(commit=commit)
            return item, created

        except Exception:
            if commit:
                self.rollback()
            raise

    def remove_item_from_collection(
        self,
        collection_item_ref: Any = None,
        *,
        collection_ref: Any = None,
        identity: Mapping[str, Any] | None = None,
        user_id: Any = DEFAULT_USER_ID,
        commit: bool = False,
        audit: bool = True,
    ) -> bool:
        """Soft-removes item from collection."""
        try:
            if collection_item_ref is not None:
                item = self.require_collection_item(collection_item_ref, include_deleted=True, for_update=True)
            else:
                if collection_ref is None or identity is None:
                    raise ValueError("collection_item_ref or collection_ref + identity is required.")

                item = self.find_collection_item(
                    collection_ref=collection_ref,
                    identity=identity,
                    include_deleted=True,
                    for_update=True,
                )
                if item is None:
                    return False

            before = to_dict_or_payload(item)

            if hasattr(item, "mark_deleted") and callable(item.mark_deleted):
                item.mark_deleted(user_id=user_id)
            else:
                if hasattr(item, "status"):
                    item.status = STATUS_DELETED
                if hasattr(item, "active"):
                    item.active = False
                if hasattr(item, "visible"):
                    item.visible = False

            after = to_dict_or_payload(item)

            if audit:
                self.create_audit_event(
                    event_type="collection_item_removed",
                    user_id=user_id,
                    collection=getattr(item, "collection", None),
                    collection_item=item,
                    before=before,
                    after=after,
                    commit=False,
                )

            self._finish_write(commit=commit)
            return True

        except Exception:
            if commit:
                self.rollback()
            raise

    def update_collection_item(
        self,
        collection_item_ref: Any,
        payload: Mapping[str, Any],
        *,
        user_id: Any = DEFAULT_USER_ID,
        commit: bool = False,
        audit: bool = True,
    ) -> Any:
        """Updates mutable collection item fields."""
        data = normalize_json_mapping(payload)

        try:
            item = self.require_collection_item(collection_item_ref, include_deleted=True, for_update=True)
            before = to_dict_or_payload(item)

            for field_name in ("visible", "active", "pinned", "favorite", "locked"):
                if field_name in data and hasattr(item, field_name):
                    setattr(item, field_name, normalize_bool(data.get(field_name), default=getattr(item, field_name)))

            for field_name in ("sort_order",):
                if field_name in data and hasattr(item, field_name):
                    setattr(item, field_name, normalize_int(data.get(field_name), default=getattr(item, field_name, 0), minimum=0) or 0)

            for field_name in ("custom_label", "custom_icon", "custom_preview_url", "status", "role", "note"):
                if field_name in data and hasattr(item, field_name):
                    setattr(item, field_name, optional_string(data.get(field_name)))

            if "payload" in data and hasattr(item, "payload"):
                item.payload = normalize_json_mapping(data.get("payload"))

            if "meta" in data and hasattr(item, "meta"):
                item.meta = normalize_json_mapping(data.get("meta"))

            if ("metadata" in data or "metadata_json" in data) and hasattr(item, "metadata_json"):
                item.metadata_json = normalize_json_mapping(data.get("metadata") or data.get("metadata_json"))

            if hasattr(item, "updated_by_user_id"):
                item.updated_by_user_id = normalize_user_id(user_id, default=None)

            if hasattr(item, "touch") and callable(item.touch):
                item.touch()

            after = to_dict_or_payload(item)

            if audit:
                self.create_audit_event(
                    event_type="collection_item_updated",
                    user_id=user_id,
                    collection=getattr(item, "collection", None),
                    collection_item=item,
                    before=before,
                    after=after,
                    commit=False,
                )

            self._finish_write(commit=commit)
            return item

        except Exception:
            if commit:
                self.rollback()
            raise

    def set_collection_item_pinned(
        self,
        collection_item_ref: Any,
        *,
        pinned: bool = True,
        user_id: Any = DEFAULT_USER_ID,
        commit: bool = False,
    ) -> Any:
        """Sets pinned flag."""
        return self.update_collection_item(
            collection_item_ref,
            {"pinned": pinned},
            user_id=user_id,
            commit=commit,
            audit=True,
        )

    def set_collection_item_visible(
        self,
        collection_item_ref: Any,
        *,
        visible: bool = True,
        user_id: Any = DEFAULT_USER_ID,
        commit: bool = False,
    ) -> Any:
        """Sets visible flag."""
        return self.update_collection_item(
            collection_item_ref,
            {"visible": visible},
            user_id=user_id,
            commit=commit,
            audit=True,
        )

    def reorder_collection_item(
        self,
        collection_item_ref: Any,
        *,
        sort_order: Any,
        user_id: Any = DEFAULT_USER_ID,
        commit: bool = False,
    ) -> Any:
        """Sets sort_order."""
        return self.update_collection_item(
            collection_item_ref,
            {"sort_order": sort_order},
            user_id=user_id,
            commit=commit,
            audit=True,
        )

    # ------------------------------------------------------------------
    # Overrides
    # ------------------------------------------------------------------

    def get_override_by_id(
        self,
        override_id: Any,
        *,
        include_deleted: bool = False,
        for_update: bool = False,
    ) -> Any | None:
        """Returns override by DB id."""
        normalized_id = normalize_int(override_id, default=None, minimum=1)
        if normalized_id is None:
            return None

        model = self.models.CreativeLibraryUserOverride
        query = self.session.query(model).filter(model.id == normalized_id)

        if not include_deleted and hasattr(model, "status"):
            query = query.filter(model.status != STATUS_DELETED)

        if for_update:
            query = self._with_for_update(query)

        return query.one_or_none()

    def get_override_by_uid(
        self,
        override_uid: Any,
        *,
        include_deleted: bool = False,
        for_update: bool = False,
    ) -> Any | None:
        """Returns override by uid."""
        uid = optional_string(override_uid)
        if not uid:
            return None

        model = self.models.CreativeLibraryUserOverride
        query = self.session.query(model)

        uid_columns = ("override_uid", "user_override_uid")
        found_column = False
        for column_name in uid_columns:
            if hasattr(model, column_name):
                query = query.filter(getattr(model, column_name) == uid)
                found_column = True
                break

        if not found_column:
            return None

        if not include_deleted and hasattr(model, "status"):
            query = query.filter(model.status != STATUS_DELETED)

        if for_update:
            query = self._with_for_update(query)

        return query.one_or_none()

    def get_override(
        self,
        override_ref: Any,
        *,
        include_deleted: bool = False,
        for_update: bool = False,
    ) -> Any | None:
        """Returns override by id or uid."""
        text = clean_string(override_ref)

        if text.isdigit():
            return self.get_override_by_id(text, include_deleted=include_deleted, for_update=for_update)

        return self.get_override_by_uid(text, include_deleted=include_deleted, for_update=for_update)

    def require_override(
        self,
        override_ref: Any,
        *,
        include_deleted: bool = False,
        for_update: bool = False,
    ) -> Any:
        """Returns override or raises."""
        override = self.get_override(override_ref, include_deleted=include_deleted, for_update=for_update)

        if override is None:
            raise CreativeLibraryUserOverrideNotFoundError(f"Creative Library user override {override_ref!r} was not found.")

        return override

    def get_override_for_target(
        self,
        *,
        user_id: Any,
        target_type: Any,
        target_uid: Any = None,
        target_id: Any = None,
        active_only: bool = True,
        include_deleted: bool = False,
        for_update: bool = False,
    ) -> Any | None:
        """Returns one override for user/target."""
        model = self.models.CreativeLibraryUserOverride
        normalized_user_id = normalize_user_id(user_id, default=DEFAULT_USER_ID) or DEFAULT_USER_ID

        query = self.session.query(model).filter(model.user_id == normalized_user_id)

        if hasattr(model, "target_type"):
            query = query.filter(model.target_type == clean_string(target_type, fallback=TARGET_TYPE_ITEM))

        normalized_target_uid = optional_string(target_uid)
        normalized_target_id = normalize_int(target_id, default=None, minimum=1)

        if normalized_target_uid and hasattr(model, "target_uid"):
            query = query.filter(model.target_uid == normalized_target_uid)
        elif normalized_target_id is not None and hasattr(model, "target_id"):
            query = query.filter(model.target_id == normalized_target_id)
        else:
            return None

        if active_only and hasattr(model, "active"):
            query = query.filter(model.active.is_(True))

        if not include_deleted and hasattr(model, "status"):
            query = query.filter(model.status != STATUS_DELETED)

        if for_update:
            query = self._with_for_update(query)

        return query.one_or_none()

    def list_overrides(
        self,
        *,
        query: UserOverrideQuery | Mapping[str, Any] | None = None,
        as_dict: bool = False,
    ) -> list[Any]:
        """Lists user overrides."""
        override_query = query if isinstance(query, UserOverrideQuery) else UserOverrideQuery.from_payload(query)
        model = self.models.CreativeLibraryUserOverride

        db_query = self.session.query(model).filter(model.user_id == override_query.user_id)

        for field_name in ("target_type", "target_id", "target_uid"):
            value = getattr(override_query, field_name)
            if value is not None and hasattr(model, field_name):
                db_query = db_query.filter(getattr(model, field_name) == value)

        if override_query.action:
            if hasattr(model, "override_action"):
                db_query = db_query.filter(model.override_action == override_query.action)
            elif hasattr(model, "action"):
                db_query = db_query.filter(model.action == override_query.action)

        if override_query.active_only and hasattr(model, "active"):
            db_query = db_query.filter(model.active.is_(True))

        if not override_query.include_deleted and hasattr(model, "status"):
            db_query = db_query.filter(model.status != STATUS_DELETED)

        db_query = db_query.order_by(model.id.asc())

        if override_query.offset:
            db_query = db_query.offset(override_query.offset)

        if override_query.limit:
            db_query = db_query.limit(override_query.limit)

        values = db_query.all()

        if as_dict:
            return [to_dict_or_payload(value) for value in values]

        return values

    def list_override_payloads(self, *, query: UserOverrideQuery | Mapping[str, Any] | None = None) -> list[dict[str, Any]]:
        """Lists overrides as dicts."""
        return self.list_overrides(query=query, as_dict=True)

    def upsert_override(
        self,
        payload: Mapping[str, Any],
        *,
        user_id: Any = DEFAULT_USER_ID,
        created_by_user_id: Any = None,
        updated_by_user_id: Any = None,
        commit: bool = False,
        audit: bool = True,
    ) -> tuple[Any, bool]:
        """
        Creates or updates a user override.

        Returns:
            (override, created)
        """
        data = normalize_json_mapping(payload)
        normalized_user_id = normalize_user_id(user_id or data.get("user_id"), default=DEFAULT_USER_ID) or DEFAULT_USER_ID
        target_type = clean_string(data.get("target_type"), fallback=TARGET_TYPE_ITEM)
        target_uid = optional_string(data.get("target_uid"))
        target_id = normalize_int(data.get("target_id"), default=None, minimum=1)

        if target_uid is None and target_id is None:
            identity = extract_item_identity(data)
            target_uid = optional_string(identity.get("target_uid") or identity.get("vplib_uid") or identity.get("variant_id") or identity.get("family_id"))
            target_id = normalize_int(identity.get("target_id") or identity.get("item_db_id") or identity.get("variant_db_id"), default=None, minimum=1)

        if target_uid is None and target_id is None:
            raise ValueError("target_uid or target_id is required for user override.")

        try:
            override = self.get_override_for_target(
                user_id=normalized_user_id,
                target_type=target_type,
                target_uid=target_uid,
                target_id=target_id,
                active_only=False,
                include_deleted=True,
                for_update=True,
            )
            created = override is None

            if created:
                creator = getattr(self.models.CreativeLibraryUserOverride, "create_from_payload", None)

                if callable(creator):
                    override = creator(
                        {
                            **data,
                            "user_id": normalized_user_id,
                            "target_type": target_type,
                            "target_uid": target_uid,
                            "target_id": target_id,
                        },
                        user_id=normalized_user_id,
                        created_by_user_id=created_by_user_id,
                    )
                else:
                    override = _new_model_with_attrs(
                        self.models.CreativeLibraryUserOverride,
                        self._fallback_override_attrs(
                            {
                                **data,
                                "user_id": normalized_user_id,
                                "target_type": target_type,
                                "target_uid": target_uid,
                                "target_id": target_id,
                            }
                        ),
                    )

                self.session.add(override)
            else:
                before = to_dict_or_payload(override)
                self._fallback_update_override(override, data, user_id=updated_by_user_id or normalized_user_id)

            self.session.flush()

            if audit:
                self.create_audit_event(
                    event_type="override_created" if created else "override_updated",
                    user_id=normalized_user_id,
                    override=override,
                    after=to_dict_or_payload(override),
                    commit=False,
                )

            self._finish_write(commit=commit)
            return override, created

        except Exception:
            if commit:
                self.rollback()
            raise

    def soft_delete_override(
        self,
        override_ref: Any = None,
        *,
        user_id: Any = DEFAULT_USER_ID,
        target_type: Any = None,
        target_uid: Any = None,
        target_id: Any = None,
        commit: bool = False,
        audit: bool = True,
    ) -> bool:
        """Soft-deletes user override by ref or target."""
        try:
            if override_ref is not None:
                override = self.require_override(override_ref, include_deleted=True, for_update=True)
            else:
                override = self.get_override_for_target(
                    user_id=user_id,
                    target_type=target_type or TARGET_TYPE_ITEM,
                    target_uid=target_uid,
                    target_id=target_id,
                    active_only=False,
                    include_deleted=True,
                    for_update=True,
                )
                if override is None:
                    return False

            before = to_dict_or_payload(override)

            if hasattr(override, "mark_deleted") and callable(override.mark_deleted):
                override.mark_deleted(user_id=user_id)
            else:
                if hasattr(override, "status"):
                    override.status = STATUS_DELETED
                if hasattr(override, "active"):
                    override.active = False

            after = to_dict_or_payload(override)

            if audit:
                self.create_audit_event(
                    event_type="override_deleted",
                    user_id=user_id,
                    override=override,
                    before=before,
                    after=after,
                    commit=False,
                )

            self._finish_write(commit=commit)
            return True

        except Exception:
            if commit:
                self.rollback()
            raise

    # ------------------------------------------------------------------
    # Override convenience actions
    # ------------------------------------------------------------------

    def hide_item_for_user(
        self,
        identity_payload: Mapping[str, Any],
        *,
        user_id: Any = DEFAULT_USER_ID,
        commit: bool = False,
    ) -> Any:
        """Creates hide override for item/variant."""
        identity = extract_item_identity(identity_payload)
        override, _created = self.upsert_override(
            {
                **identity,
                "user_id": user_id,
                "target_type": identity.get("target_type") or TARGET_TYPE_ITEM,
                "target_uid": identity.get("target_uid") or identity.get("vplib_uid") or identity.get("variant_id"),
                "target_id": identity.get("target_id") or identity.get("item_db_id") or identity.get("variant_db_id"),
                "override_action": ACTION_HIDE,
                "visible_override": False,
                "active": True,
            },
            user_id=user_id,
            created_by_user_id=user_id,
            updated_by_user_id=user_id,
            commit=commit,
            audit=True,
        )
        return override

    def restore_item_for_user(
        self,
        identity_payload: Mapping[str, Any],
        *,
        user_id: Any = DEFAULT_USER_ID,
        commit: bool = False,
    ) -> Any:
        """Creates restore override for item/variant."""
        identity = extract_item_identity(identity_payload)
        override, _created = self.upsert_override(
            {
                **identity,
                "user_id": user_id,
                "target_type": identity.get("target_type") or TARGET_TYPE_ITEM,
                "target_uid": identity.get("target_uid") or identity.get("vplib_uid") or identity.get("variant_id"),
                "target_id": identity.get("target_id") or identity.get("item_db_id") or identity.get("variant_db_id"),
                "override_action": ACTION_RESTORE,
                "visible_override": True,
                "active_override": True,
                "active": True,
            },
            user_id=user_id,
            created_by_user_id=user_id,
            updated_by_user_id=user_id,
            commit=commit,
            audit=True,
        )
        return override

    def favorite_item_for_user(
        self,
        identity_payload: Mapping[str, Any],
        *,
        favorite: bool = True,
        user_id: Any = DEFAULT_USER_ID,
        commit: bool = False,
    ) -> Any:
        """Creates favorite/unfavorite override."""
        identity = extract_item_identity(identity_payload)
        override, _created = self.upsert_override(
            {
                **identity,
                "user_id": user_id,
                "target_type": identity.get("target_type") or TARGET_TYPE_ITEM,
                "target_uid": identity.get("target_uid") or identity.get("vplib_uid") or identity.get("variant_id"),
                "target_id": identity.get("target_id") or identity.get("item_db_id") or identity.get("variant_db_id"),
                "override_action": ACTION_FAVORITE if favorite else ACTION_UNFAVORITE,
                "favorite_override": favorite,
                "active": True,
            },
            user_id=user_id,
            created_by_user_id=user_id,
            updated_by_user_id=user_id,
            commit=commit,
            audit=True,
        )
        return override

    def rename_item_for_user(
        self,
        identity_payload: Mapping[str, Any],
        *,
        label: Any,
        user_id: Any = DEFAULT_USER_ID,
        commit: bool = False,
    ) -> Any:
        """Creates rename override."""
        identity = extract_item_identity(identity_payload)
        override, _created = self.upsert_override(
            {
                **identity,
                "user_id": user_id,
                "target_type": identity.get("target_type") or TARGET_TYPE_ITEM,
                "target_uid": identity.get("target_uid") or identity.get("vplib_uid") or identity.get("variant_id"),
                "target_id": identity.get("target_id") or identity.get("item_db_id") or identity.get("variant_db_id"),
                "override_action": ACTION_RENAME,
                "label_override": label,
                "active": True,
            },
            user_id=user_id,
            created_by_user_id=user_id,
            updated_by_user_id=user_id,
            commit=commit,
            audit=True,
        )
        return override

    # ------------------------------------------------------------------
    # Resolved payload helpers
    # ------------------------------------------------------------------

    def get_resolved_collection_payload(
        self,
        collection_ref: Any,
        *,
        user_id: Any = DEFAULT_USER_ID,
        include_hidden: bool = False,
        include_deleted: bool = False,
    ) -> dict[str, Any]:
        """Builds resolved collection payload."""
        collection = self.require_collection(collection_ref, include_deleted=include_deleted)
        normalized_user_id = normalize_user_id(user_id, default=DEFAULT_USER_ID) or DEFAULT_USER_ID

        items = self.list_collection_item_payloads(
            query=CollectionItemQuery(
                user_id=None,
                collection_id=getattr(collection, "id", None),
                active_only=not include_deleted,
                visible_only=False,
                include_deleted=include_deleted,
                limit=MAX_LIMIT,
            ),
            include_collection=False,
        )

        overrides = self.list_override_payloads(
            query=UserOverrideQuery(
                user_id=normalized_user_id,
                active_only=True,
                include_deleted=include_deleted,
                limit=MAX_LIMIT,
            )
        )

        resolved_items = self.apply_overrides_to_items(
            items,
            overrides,
            include_hidden=include_hidden,
            include_deleted=include_deleted,
        )

        helper = getattr(self.models, "build_resolved_collection_payload", None)
        if callable(helper):
            try:
                return normalize_json_mapping(
                    helper(
                        collection=collection,
                        items=resolved_items,
                        overrides=overrides,
                        user_id=normalized_user_id,
                    )
                )
            except Exception:
                pass

        return {
            "schema_version": CREATIVE_LIBRARY_USER_REPOSITORY_VERSION,
            "user_id": normalized_user_id,
            "collection": to_dict_or_payload(collection),
            "items": resolved_items,
            "overrides": overrides,
            "item_count": len(resolved_items),
            "override_count": len(overrides),
            "resolved": True,
        }

    def get_resolved_user_library_payload(
        self,
        *,
        user_id: Any = DEFAULT_USER_ID,
        include_hidden: bool = False,
        include_deleted: bool = False,
        include_collections: bool = True,
    ) -> dict[str, Any]:
        """Builds resolved user Creative Library overlay payload."""
        normalized_user_id = normalize_user_id(user_id, default=DEFAULT_USER_ID) or DEFAULT_USER_ID

        collections = self.list_collection_payloads(
            query=CollectionQuery(
                user_id=normalized_user_id,
                include_system=True,
                include_user=True,
                active_only=not include_deleted,
                visible_only=False,
                include_deleted=include_deleted,
                limit=MAX_LIMIT,
            )
        )

        collection_payloads: list[dict[str, Any]] = []
        all_items: list[dict[str, Any]] = []

        if include_collections:
            for collection in collections:
                collection_uid = collection.get("collection_uid") or collection.get("id")
                try:
                    resolved = self.get_resolved_collection_payload(
                        collection_uid,
                        user_id=normalized_user_id,
                        include_hidden=include_hidden,
                        include_deleted=include_deleted,
                    )
                    collection_payloads.append(resolved)
                    all_items.extend(normalize_json_list(resolved.get("items")))
                except Exception:
                    continue

        return {
            "schema_version": CREATIVE_LIBRARY_USER_REPOSITORY_VERSION,
            "user_id": normalized_user_id,
            "resolved": True,
            "include_hidden": include_hidden,
            "include_deleted": include_deleted,
            "collections": collection_payloads if include_collections else collections,
            "collection_count": len(collection_payloads if include_collections else collections),
            "items": all_items,
            "item_count": len(all_items),
            "overrides": self.list_override_payloads(
                query=UserOverrideQuery(
                    user_id=normalized_user_id,
                    active_only=True,
                    include_deleted=include_deleted,
                    limit=MAX_LIMIT,
                )
            ),
        }

    def apply_overrides_to_items(
        self,
        items: Iterable[Mapping[str, Any]],
        overrides: Iterable[Mapping[str, Any]],
        *,
        include_hidden: bool = False,
        include_deleted: bool = False,
    ) -> list[dict[str, Any]]:
        """Applies user overrides to item payloads."""
        helper = getattr(self.models, "apply_user_override_to_item_payload", None)
        override_map = self._build_override_map(overrides)
        resolved: list[dict[str, Any]] = []

        for item in items:
            payload = normalize_json_mapping(item)
            key_candidates = self._item_override_keys(payload)
            override = None

            for key in key_candidates:
                override = override_map.get(key)
                if override:
                    break

            if override:
                if callable(helper):
                    try:
                        payload = normalize_json_mapping(helper(payload, override))
                    except Exception:
                        payload = self._fallback_apply_override(payload, override)
                else:
                    payload = self._fallback_apply_override(payload, override)

            if not include_hidden and not normalize_bool(payload.get("visible"), default=True):
                continue

            if not include_deleted and clean_string(payload.get("status")) == STATUS_DELETED:
                continue

            resolved.append(payload)

        resolved.sort(
            key=lambda item: (
                normalize_int(item.get("sort_order"), default=0) or 0,
                clean_string(item.get("custom_label") or item.get("label") or item.get("vplib_uid") or item.get("target_uid")),
            )
        )
        return resolved

    # ------------------------------------------------------------------
    # Audit
    # ------------------------------------------------------------------

    def create_audit_event(
        self,
        *,
        event_type: Any,
        user_id: Any = None,
        collection: Any = None,
        collection_item: Any = None,
        override: Any = None,
        before: Mapping[str, Any] | None = None,
        after: Mapping[str, Any] | None = None,
        diff: Mapping[str, Any] | None = None,
        payload: Mapping[str, Any] | None = None,
        metadata: Mapping[str, Any] | None = None,
        commit: bool = False,
    ) -> Any:
        """Creates audit event."""
        try:
            creator = getattr(self.models.CreativeLibraryUserAuditEvent, "create_event", None)

            if callable(creator):
                event = creator(
                    event_type=event_type,
                    user_id=user_id,
                    collection=collection,
                    collection_item=collection_item,
                    override=override,
                    before=before,
                    after=after,
                    diff=diff,
                    payload=payload,
                    metadata=metadata,
                )
            else:
                event = _new_model_with_attrs(
                    self.models.CreativeLibraryUserAuditEvent,
                    {
                        "event_type": clean_string(event_type, fallback="other"),
                        "user_id": normalize_user_id(user_id, default=None),
                        "collection_id": getattr(collection, "id", None),
                        "collection_item_id": getattr(collection_item, "id", None),
                        "override_id": getattr(override, "id", None),
                        "before_json": normalize_json_mapping(before),
                        "after_json": normalize_json_mapping(after),
                        "diff_json": normalize_json_mapping(diff),
                        "payload": normalize_json_mapping(payload),
                        "meta": normalize_json_mapping(metadata),
                        "metadata_json": normalize_json_mapping(metadata),
                    },
                )

            self.session.add(event)
            self._finish_write(commit=commit)
            return event

        except Exception:
            if commit:
                self.rollback()
            raise

    def list_audit_events(
        self,
        *,
        user_id: Any = DEFAULT_USER_ID,
        event_type: Any = None,
        target_type: Any = None,
        target_uid: Any = None,
        collection_uid: Any = None,
        vplib_uid: Any = None,
        limit: int = DEFAULT_LIMIT,
        offset: int = 0,
        as_dict: bool = True,
    ) -> list[Any]:
        """Lists audit events."""
        model = self.models.CreativeLibraryUserAuditEvent
        query = self.session.query(model)

        normalized_user_id = normalize_user_id(user_id, default=None)
        if normalized_user_id is not None and hasattr(model, "user_id"):
            query = query.filter(model.user_id == normalized_user_id)

        for field_name, value in (
            ("event_type", event_type),
            ("target_type", target_type),
            ("target_uid", target_uid),
            ("collection_uid", collection_uid),
            ("vplib_uid", vplib_uid),
        ):
            normalized = optional_string(value)
            if normalized is not None and hasattr(model, field_name):
                query = query.filter(getattr(model, field_name) == normalized)

        if hasattr(model, "created_at"):
            query = query.order_by(model.created_at.desc())
        else:
            query = query.order_by(model.id.desc())

        normalized_offset = normalize_int(offset, default=0, minimum=0) or 0
        normalized_limit = normalize_int(limit, default=DEFAULT_LIMIT, minimum=1, maximum=MAX_LIMIT) or DEFAULT_LIMIT

        if normalized_offset:
            query = query.offset(normalized_offset)

        query = query.limit(normalized_limit)

        values = query.all()

        if as_dict:
            return [event.to_dict() if hasattr(event, "to_dict") else to_dict_or_payload(event) for event in values]

        return values

    # ------------------------------------------------------------------
    # Health / diagnostics
    # ------------------------------------------------------------------

    def get_health(self) -> dict[str, Any]:
        """Returns repository health snapshot."""
        model_health = {}

        try:
            candidate = getattr(self.models, "get_creative_library_user_models_health", None)
            if callable(candidate):
                model_health = candidate()
        except Exception as exc:
            model_health = {"ok": False, "error": f"{type(exc).__name__}: {exc}"}

        return {
            "schema_version": CREATIVE_LIBRARY_USER_REPOSITORY_VERSION,
            "ok": True,
            "repository": type(self).__name__,
            "has_session": self._session is not None,
            "uses_default_db_session": self._session is None,
            "models_health": model_health,
            "supports_collections": True,
            "supports_collection_items": True,
            "supports_user_overrides": True,
            "supports_audit": True,
            "supports_resolved_user_library": True,
            "supports_default_system_collection": True,
            "supports_user_collection": True,
            "supports_soft_delete": True,
        }

    # ------------------------------------------------------------------
    # Internal query helpers
    # ------------------------------------------------------------------

    def _with_for_update(self, query: Any) -> Any:
        """Applies FOR UPDATE if supported."""
        try:
            return query.with_for_update()
        except Exception:
            return query

    def _apply_collection_sort(self, query: Any, model: type[Any]) -> Any:
        """Applies stable collection ordering."""
        order_fields = []

        for field_name in ("sort_order", "collection_kind", "label", "collection_key", "id"):
            column = getattr(model, field_name, None)
            if column is not None:
                try:
                    order_fields.append(column.asc())
                except Exception:
                    pass

        if order_fields:
            try:
                return query.order_by(*order_fields)
            except Exception:
                return query

        return query

    def _apply_collection_item_sort(self, query: Any, model: type[Any]) -> Any:
        """Applies stable item ordering."""
        order_fields = []

        for field_name in ("pinned", "sort_order", "custom_label", "vplib_uid", "id"):
            column = getattr(model, field_name, None)
            if column is not None:
                try:
                    if field_name == "pinned":
                        order_fields.append(column.desc())
                    else:
                        order_fields.append(column.asc())
                except Exception:
                    pass

        if order_fields:
            try:
                return query.order_by(*order_fields)
            except Exception:
                return query

        return query

    # ------------------------------------------------------------------
    # Internal fallback builders
    # ------------------------------------------------------------------

    def _fallback_collection_attrs(
        self,
        payload: Mapping[str, Any],
        *,
        owner_user_id: Any,
        source_scope: Any,
    ) -> dict[str, Any]:
        """Fallback attrs for collection model."""
        data = normalize_json_mapping(payload)
        normalized_source_scope = clean_string(source_scope, fallback=SOURCE_SCOPE_USER)
        normalized_owner_user_id = normalize_user_id(owner_user_id, default=None)

        if normalized_source_scope == SOURCE_SCOPE_SYSTEM:
            normalized_owner_user_id = None

        return {
            "collection_key": optional_string(data.get("collection_key")) or DEFAULT_USER_COLLECTION_KEY,
            "collection_kind": optional_string(data.get("collection_kind")) or COLLECTION_KIND_USER,
            "label": optional_string(data.get("label") or data.get("name")) or "Collection",
            "name": optional_string(data.get("name") or data.get("label")) or "Collection",
            "description": optional_string(data.get("description")),
            "source_scope": normalized_source_scope,
            "owner_user_id": normalized_owner_user_id,
            "owner_scope": owner_scope_for(source_scope=normalized_source_scope, owner_user_id=normalized_owner_user_id),
            "status": clean_string(data.get("status"), fallback=STATUS_ACTIVE),
            "active": normalize_bool(data.get("active"), default=True),
            "visible": normalize_bool(data.get("visible"), default=True),
            "sort_order": normalize_int(data.get("sort_order"), default=0, minimum=0) or 0,
            "payload": normalize_json_mapping(data.get("payload") or data),
            "meta": normalize_json_mapping(data.get("meta")),
            "metadata_json": normalize_json_mapping(data.get("metadata")),
        }

    def _fallback_collection_item_attrs(
        self,
        payload: Mapping[str, Any],
        *,
        collection: Any,
        user_id: Any,
        added_by_user_id: Any,
    ) -> dict[str, Any]:
        """Fallback attrs for collection item model."""
        data = normalize_json_mapping(payload)
        identity = extract_item_identity(data)

        return {
            "collection_id": getattr(collection, "id", None),
            "user_id": normalize_user_id(user_id, default=DEFAULT_USER_ID),
            "added_by_user_id": normalize_user_id(added_by_user_id, default=None),
            "source_scope": optional_string(data.get("source_scope")) or SOURCE_SCOPE_USER,
            "target_type": identity.get("target_type") or TARGET_TYPE_ITEM,
            "target_id": identity.get("target_id"),
            "target_uid": identity.get("target_uid") or identity.get("vplib_uid") or identity.get("variant_id"),
            "item_db_id": identity.get("item_db_id"),
            "variant_db_id": identity.get("variant_db_id"),
            "vplib_uid": identity.get("vplib_uid"),
            "family_id": identity.get("family_id"),
            "package_id": identity.get("package_id"),
            "variant_id": identity.get("variant_id"),
            "draft_id": identity.get("draft_id"),
            "draft_uid": identity.get("draft_uid"),
            "custom_label": optional_string(data.get("custom_label") or data.get("label")),
            "custom_icon": optional_string(data.get("custom_icon") or data.get("icon")),
            "custom_preview_url": optional_string(data.get("custom_preview_url") or data.get("preview_url")),
            "status": clean_string(data.get("status"), fallback=STATUS_ACTIVE),
            "active": normalize_bool(data.get("active"), default=True),
            "visible": normalize_bool(data.get("visible"), default=True),
            "pinned": normalize_bool(data.get("pinned"), default=False),
            "favorite": normalize_bool(data.get("favorite"), default=False),
            "sort_order": normalize_int(data.get("sort_order"), default=0, minimum=0) or 0,
            "payload": normalize_json_mapping(data.get("payload") or data),
            "meta": normalize_json_mapping(data.get("meta")),
            "metadata_json": normalize_json_mapping(data.get("metadata")),
        }

    def _fallback_override_attrs(self, payload: Mapping[str, Any]) -> dict[str, Any]:
        """Fallback attrs for override model."""
        data = normalize_json_mapping(payload)

        return {
            "user_id": normalize_user_id(data.get("user_id"), default=DEFAULT_USER_ID),
            "target_type": optional_string(data.get("target_type")) or TARGET_TYPE_ITEM,
            "target_id": normalize_int(data.get("target_id"), default=None, minimum=1),
            "target_uid": optional_string(data.get("target_uid")),
            "override_action": optional_string(data.get("override_action") or data.get("action")) or ACTION_PATCH,
            "status": clean_string(data.get("status"), fallback=STATUS_ACTIVE),
            "active": normalize_bool(data.get("active"), default=True),
            "visible_override": data.get("visible_override"),
            "active_override": data.get("active_override"),
            "favorite_override": data.get("favorite_override"),
            "pinned_override": data.get("pinned_override"),
            "label_override": optional_string(data.get("label_override") or data.get("label")),
            "description_override": optional_string(data.get("description_override") or data.get("description")),
            "sort_order_override": normalize_int(data.get("sort_order_override") or data.get("sort_order"), default=None, minimum=0),
            "payload_patch": normalize_json_mapping(data.get("payload_patch") or data.get("patch")),
            "before_json": normalize_json_mapping(data.get("before")),
            "after_json": normalize_json_mapping(data.get("after")),
            "meta": normalize_json_mapping(data.get("meta")),
            "metadata_json": normalize_json_mapping(data.get("metadata")),
        }

    def _fallback_update_collection(self, collection: Any, payload: Mapping[str, Any], *, user_id: Any = None) -> None:
        """Fallback collection update."""
        data = normalize_json_mapping(payload)

        for field_name in ("label", "name", "description", "collection_kind", "status"):
            if field_name in data and hasattr(collection, field_name):
                setattr(collection, field_name, optional_string(data.get(field_name)))

        for field_name in ("active", "visible", "locked"):
            if field_name in data and hasattr(collection, field_name):
                setattr(collection, field_name, normalize_bool(data.get(field_name), default=getattr(collection, field_name)))

        if "sort_order" in data and hasattr(collection, "sort_order"):
            collection.sort_order = normalize_int(data.get("sort_order"), default=getattr(collection, "sort_order", 0), minimum=0) or 0

        if "payload" in data and hasattr(collection, "payload"):
            collection.payload = normalize_json_mapping(data.get("payload"))

        if "meta" in data and hasattr(collection, "meta"):
            collection.meta = normalize_json_mapping(data.get("meta"))

        if ("metadata" in data or "metadata_json" in data) and hasattr(collection, "metadata_json"):
            collection.metadata_json = normalize_json_mapping(data.get("metadata") or data.get("metadata_json"))

        updater_id = normalize_user_id(user_id, default=None)
        if updater_id is not None and hasattr(collection, "updated_by_user_id"):
            collection.updated_by_user_id = updater_id

        if hasattr(collection, "touch") and callable(collection.touch):
            collection.touch()

    def _restore_or_update_collection_item(self, item: Any, payload: Mapping[str, Any], *, user_id: Any) -> None:
        """Restores existing item and applies incoming fields."""
        if hasattr(item, "restore") and callable(item.restore):
            item.restore(user_id=user_id)
        else:
            if hasattr(item, "status"):
                item.status = STATUS_ACTIVE
            if hasattr(item, "active"):
                item.active = True
            if hasattr(item, "visible"):
                item.visible = True

        self._fallback_update_collection_item_fields(item, payload, user_id=user_id)

    def _fallback_update_collection_item_fields(self, item: Any, payload: Mapping[str, Any], *, user_id: Any) -> None:
        """Updates item fields without audit."""
        data = normalize_json_mapping(payload)

        for field_name in ("custom_label", "custom_icon", "custom_preview_url", "status", "role", "note"):
            if field_name in data and hasattr(item, field_name):
                setattr(item, field_name, optional_string(data.get(field_name)))

        for field_name in ("active", "visible", "pinned", "favorite"):
            if field_name in data and hasattr(item, field_name):
                setattr(item, field_name, normalize_bool(data.get(field_name), default=getattr(item, field_name)))

        if "sort_order" in data and hasattr(item, "sort_order"):
            item.sort_order = normalize_int(data.get("sort_order"), default=getattr(item, "sort_order", 0), minimum=0) or 0

        if hasattr(item, "updated_by_user_id"):
            item.updated_by_user_id = normalize_user_id(user_id, default=None)

        if hasattr(item, "touch") and callable(item.touch):
            item.touch()

    def _fallback_update_override(self, override: Any, payload: Mapping[str, Any], *, user_id: Any) -> None:
        """Fallback override update."""
        data = normalize_json_mapping(payload)
        incoming = self._fallback_override_attrs(data)

        for key, value in incoming.items():
            if hasattr(override, key):
                setattr(override, key, value)

        if hasattr(override, "updated_by_user_id"):
            override.updated_by_user_id = normalize_user_id(user_id, default=None)

        if hasattr(override, "touch") and callable(override.touch):
            override.touch()

    def _build_override_map(self, overrides: Iterable[Mapping[str, Any]]) -> dict[str, dict[str, Any]]:
        """Builds override lookup map."""
        result: dict[str, dict[str, Any]] = {}

        for override in overrides:
            payload = normalize_json_mapping(override)

            for key in self._item_override_keys(payload):
                result[key] = payload

        return result

    def _item_override_keys(self, payload: Mapping[str, Any]) -> list[str]:
        """Builds possible override keys for item payload."""
        data = normalize_json_mapping(payload)
        keys: list[str] = []

        target_type = optional_string(data.get("target_type")) or TARGET_TYPE_ITEM

        for field_name in ("target_uid", "vplib_uid", "variant_id", "family_id", "package_id", "draft_uid"):
            value = optional_string(data.get(field_name))
            if value:
                keys.append(f"{target_type}:uid:{value}")
                keys.append(f"{field_name}:{value}")

        for field_name in ("target_id", "item_db_id", "variant_db_id", "draft_id"):
            value = normalize_int(data.get(field_name), default=None, minimum=1)
            if value is not None:
                keys.append(f"{target_type}:id:{value}")
                keys.append(f"{field_name}:{value}")

        return _dedupe_preserve_order(keys)  # type: ignore[return-value]

    def _fallback_apply_override(self, item_payload: Mapping[str, Any], override_payload: Mapping[str, Any]) -> dict[str, Any]:
        """Applies override without model helper."""
        result = normalize_json_mapping(item_payload)
        override = normalize_json_mapping(override_payload)
        action = clean_string(override.get("override_action") or override.get("action")).lower()

        if action in {ACTION_HIDE, ACTION_REMOVE, ACTION_REMOVE_FROM_USER_LIBRARY}:
            result["visible"] = False
            result["hidden_by_override"] = True

        if action == ACTION_RESTORE:
            result["visible"] = True
            result["active"] = True
            result["hidden_by_override"] = False

        if override.get("visible_override") is not None:
            result["visible"] = normalize_bool(override.get("visible_override"), default=result.get("visible", True))

        if override.get("active_override") is not None:
            result["active"] = normalize_bool(override.get("active_override"), default=result.get("active", True))

        if override.get("favorite_override") is not None:
            result["favorite"] = normalize_bool(override.get("favorite_override"), default=result.get("favorite", False))

        if override.get("pinned_override") is not None:
            result["pinned"] = normalize_bool(override.get("pinned_override"), default=result.get("pinned", False))

        for source_key, target_key in (
            ("label_override", "custom_label"),
            ("description_override", "description"),
            ("sort_order_override", "sort_order"),
        ):
            if override.get(source_key) is not None:
                result[target_key] = normalize_json_value(override.get(source_key))

        patch = normalize_json_mapping(override.get("payload_patch"))
        if patch:
            result["payload"] = {
                **normalize_json_mapping(result.get("payload")),
                **patch,
            }

        result["override"] = override
        return result


# ---------------------------------------------------------------------------
# Factory helpers
# ---------------------------------------------------------------------------

def create_creative_library_user_repository(session: Any | None = None) -> CreativeLibraryUserRepository:
    """Factory for dependency injection."""
    return CreativeLibraryUserRepository(session=session)


@lru_cache(maxsize=1)
def get_repository_version() -> str:
    """Cached repository version helper."""
    return CREATIVE_LIBRARY_USER_REPOSITORY_VERSION


def clear_creative_library_user_repository_caches() -> dict[str, Any]:
    """Clears import/static caches."""
    cleared: list[str] = []

    for cached_func in (
        _load_db,
        _load_user_models_module,
        get_repository_version,
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
    "CREATIVE_LIBRARY_USER_REPOSITORY_VERSION",
    "DEFAULT_USER_ID",
    "SOURCE_SCOPE_SYSTEM",
    "SOURCE_SCOPE_USER",
    "SOURCE_SCOPE_IMPORTED",
    "SOURCE_SCOPE_GENERATED",
    "STATUS_ACTIVE",
    "STATUS_INACTIVE",
    "STATUS_HIDDEN",
    "STATUS_DELETED",
    "STATUS_ARCHIVED",
    "COLLECTION_KIND_DEFAULT",
    "COLLECTION_KIND_USER",
    "COLLECTION_KIND_PROJECT",
    "COLLECTION_KIND_FAVORITES",
    "COLLECTION_KIND_RECENT",
    "COLLECTION_KIND_SYSTEM",
    "TARGET_TYPE_ITEM",
    "TARGET_TYPE_VARIANT",
    "TARGET_TYPE_COLLECTION",
    "TARGET_TYPE_COLLECTION_ITEM",
    "TARGET_TYPE_TAXONOMY_NODE",
    "TARGET_TYPE_DEFINITION",
    "TARGET_TYPE_DRAFT",
    "ACTION_ADD",
    "ACTION_REMOVE",
    "ACTION_HIDE",
    "ACTION_RESTORE",
    "ACTION_RENAME",
    "ACTION_REORDER",
    "ACTION_FAVORITE",
    "ACTION_UNFAVORITE",
    "ACTION_PIN",
    "ACTION_UNPIN",
    "ACTION_PATCH",
    "ACTION_REMOVE_FROM_USER_LIBRARY",
    "DEFAULT_SYSTEM_COLLECTION_KEY",
    "DEFAULT_USER_COLLECTION_KEY",
    "DEFAULT_FAVORITES_COLLECTION_KEY",

    # Exceptions
    "CreativeLibraryUserRepositoryError",
    "CreativeLibraryUserRepositoryImportError",
    "CreativeLibraryCollectionNotFoundError",
    "CreativeLibraryCollectionItemNotFoundError",
    "CreativeLibraryUserOverrideNotFoundError",
    "CreativeLibraryUserConflictError",

    # Dataclasses
    "CollectionQuery",
    "CollectionItemQuery",
    "UserOverrideQuery",
    "CreativeLibraryUserWriteResult",

    # Repository
    "CreativeLibraryUserRepository",
    "create_creative_library_user_repository",

    # Helpers
    "clean_string",
    "optional_string",
    "normalize_int",
    "normalize_user_id",
    "normalize_bool",
    "normalize_json_mapping",
    "normalize_json_list",
    "normalize_json_value",
    "enum_value",
    "owner_scope_for",
    "to_dict_or_payload",
    "extract_item_identity",
    "item_identity_key",
    "target_key_from_payload",
    "get_repository_version",
    "clear_creative_library_user_repository_caches",
]