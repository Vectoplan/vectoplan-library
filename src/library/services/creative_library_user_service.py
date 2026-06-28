# services/vectoplan-library/src/library/services/creative_library_user_service.py
"""
Service for VECTOPLAN Creative Library User Overlay.

Diese Datei bildet die fachliche Service-Schicht über:

- src/library/repositories/creative_library_user_repository.py
- models/creative_library_user.py

Ziel:

    Published/System Creative Library
        + System Default Collection
        + User Collections
        + User Added Items
        + User Hidden/Removed Items
        + User Overrides
        -> resolved Creative Library / Creative Inventory for user_id

Aufgaben:

- Creative Inventory für user_id auflösen
- Standardbibliothek + User-Änderungen mergen
- User Collections anlegen/ändern/löschen
- Items zu User Collections hinzufügen
- Items aus User Collections entfernen
- System-/Published-Items für User ausblenden
- Items wiederherstellen
- Items favorisieren/pinnen/umbenennen/sortieren
- Audit Events lesbar bereitstellen
- API-fähige Payloads für Routes liefern

Architekturregeln:

- Service enthält keine Flask-Route.
- Service enthält keine SQLAlchemy-Queries direkt.
- DB-Zugriffe laufen über CreativeLibraryUserRepository.
- Standardbibliothek wird nicht pro User kopiert.
- User-Erweiterungen sind Collections/CollectionItems/Overrides.
- Service erzeugt keine Tabellen.
- Service führt keine Migration aus.
- Service führt kein db.create_all() aus.
- Service öffnet keine aktive DB-Verbindung beim Import.
- Technische Namen, JSON-Keys und Variablen bleiben Englisch.

Phase 1:

- user_id darf weiterhin 1 sein.
- Default User Collection ist "user-default".
- Favorites Collection ist "favorites".
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

CREATIVE_LIBRARY_USER_SERVICE_VERSION: Final[str] = "vectoplan_library.service.creative_library_user.v1"

DEFAULT_USER_ID: Final[int] = 1

DEFAULT_USER_COLLECTION_KEY: Final[str] = "user-default"
DEFAULT_USER_COLLECTION_LABEL: Final[str] = "Meine Bibliothek"

DEFAULT_FAVORITES_COLLECTION_KEY: Final[str] = "favorites"
DEFAULT_FAVORITES_COLLECTION_LABEL: Final[str] = "Favoriten"

DEFAULT_SYSTEM_COLLECTION_KEY: Final[str] = "default"

SOURCE_SCOPE_SYSTEM: Final[str] = "system"
SOURCE_SCOPE_USER: Final[str] = "user"
SOURCE_SCOPE_IMPORTED: Final[str] = "imported"
SOURCE_SCOPE_GENERATED: Final[str] = "generated"

COLLECTION_KIND_DEFAULT: Final[str] = "default"
COLLECTION_KIND_USER: Final[str] = "user"
COLLECTION_KIND_PROJECT: Final[str] = "project"
COLLECTION_KIND_FAVORITES: Final[str] = "favorites"

TARGET_TYPE_ITEM: Final[str] = "item"
TARGET_TYPE_VARIANT: Final[str] = "variant"
TARGET_TYPE_COLLECTION_ITEM: Final[str] = "collection_item"
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

STATUS_OK: Final[str] = "ok"
STATUS_INVALID_REQUEST: Final[str] = "invalid_request"
STATUS_NOT_FOUND: Final[str] = "not_found"
STATUS_FAILED: Final[str] = "failed"

MAX_LIMIT: Final[int] = 5000


# ---------------------------------------------------------------------------
# Exceptions
# ---------------------------------------------------------------------------

class CreativeLibraryUserServiceError(RuntimeError):
    """Base error for CreativeLibraryUserService."""


class CreativeLibraryUserServiceImportError(CreativeLibraryUserServiceError):
    """Raised when repository import fails."""


class CreativeLibraryUserServiceValidationError(CreativeLibraryUserServiceError):
    """Raised when input payload is invalid."""

    def __init__(self, message: str, *, errors: Iterable[Any] | None = None) -> None:
        super().__init__(message)
        self.errors = [str(error) for error in (errors or [])]


class CreativeLibraryUserServiceNotFoundError(CreativeLibraryUserServiceError):
    """Raised when an entity cannot be found."""


class CreativeLibraryUserServiceConflictError(CreativeLibraryUserServiceError):
    """Raised when operation conflicts with state or ownership."""


# ---------------------------------------------------------------------------
# Lazy imports
# ---------------------------------------------------------------------------

@lru_cache(maxsize=1)
def _load_repository_module() -> ModuleType:
    """Loads creative_library_user_repository defensively."""
    errors: list[str] = []

    for module_name in (
        "library.repositories.creative_library_user_repository",
        "src.library.repositories.creative_library_user_repository",
        "vectoplan_library.library.repositories.creative_library_user_repository",
        "vectoplan_library.src.library.repositories.creative_library_user_repository",
    ):
        try:
            return importlib.import_module(module_name)
        except Exception as exc:
            errors.append(f"{module_name}: {type(exc).__name__}: {exc}")

    raise CreativeLibraryUserServiceImportError(
        "Could not import creative_library_user_repository. "
        + " | ".join(errors)
    )


def _repo_module() -> ModuleType:
    """Short alias for repository module."""
    return _load_repository_module()


# ---------------------------------------------------------------------------
# Generic helpers
# ---------------------------------------------------------------------------

def clean_string(value: Any, *, fallback: str = "") -> str:
    """Converts a value to a safe stripped string."""
    try:
        if value is None:
            return fallback

        text = str(value).replace("\x00", "").strip()
        return text if text else fallback
    except Exception:
        return fallback


def optional_string(value: Any, *, max_length: int | None = None) -> str | None:
    """Normalizes optional strings."""
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


def first_non_empty(*values: Any) -> Any:
    """Returns first non-empty value."""
    for value in values:
        if value is None:
            continue

        if isinstance(value, str) and not value.strip():
            continue

        return value

    return None


def to_dict_or_payload(value: Any, **kwargs: Any) -> dict[str, Any]:
    """Serializes model objects defensively."""
    helper = getattr(_repo_module(), "to_dict_or_payload", None)

    if callable(helper):
        try:
            return normalize_json_mapping(helper(value, **kwargs))
        except Exception:
            pass

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

    return {"value": str(value)}


def extract_item_identity(payload: Mapping[str, Any] | Any) -> dict[str, Any]:
    """Extracts item identity through repository helper when available."""
    helper = getattr(_repo_module(), "extract_item_identity", None)

    if callable(helper):
        try:
            return normalize_json_mapping(helper(payload))
        except Exception:
            pass

    if isinstance(payload, Mapping):
        data = normalize_json_mapping(payload)
        getter = data.get
    else:
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


def identity_has_reference(identity: Mapping[str, Any]) -> bool:
    """Checks whether item identity contains at least one usable reference."""
    data = normalize_json_mapping(identity)

    for key in ("target_uid", "vplib_uid", "family_id", "package_id", "variant_id", "draft_uid"):
        if optional_string(data.get(key)):
            return True

    for key in ("target_id", "item_db_id", "variant_db_id", "draft_id"):
        if normalize_int(data.get(key), default=None, minimum=1) is not None:
            return True

    return False


def collection_ref_from_payload(payload: Mapping[str, Any], *, default: str = DEFAULT_USER_COLLECTION_KEY) -> Any:
    """Extracts collection ref from payload."""
    return first_non_empty(
        payload.get("collection_ref"),
        payload.get("collection_uid"),
        payload.get("collection_id"),
        payload.get("collection_key"),
        default,
    )


def _dedupe_items(items: Iterable[Mapping[str, Any]]) -> list[dict[str, Any]]:
    """Dedupe item payloads by stable identity."""
    repo_helper = getattr(_repo_module(), "item_identity_key", None)

    result: list[dict[str, Any]] = []
    seen: set[str] = set()

    for item in items or ():
        payload = normalize_json_mapping(item)
        identity = extract_item_identity(payload)

        if callable(repo_helper):
            try:
                key = str(repo_helper(identity))
            except Exception:
                key = repr(sorted(identity.items()))
        else:
            key = repr(sorted(identity.items()))

        if key in seen:
            continue

        seen.add(key)
        result.append(payload)

    return result


# ---------------------------------------------------------------------------
# Dataclasses
# ---------------------------------------------------------------------------

@dataclass(slots=True)
class ResolvedCreativeLibraryQuery:
    """Query object for resolved user library."""

    user_id: int = DEFAULT_USER_ID
    include_hidden: bool = False
    include_deleted: bool = False
    include_collections: bool = True
    include_items: bool = True
    include_overrides: bool = True
    include_audit: bool = False
    ensure_defaults: bool = True

    @classmethod
    def from_payload(cls, payload: Mapping[str, Any] | None = None, **kwargs: Any) -> "ResolvedCreativeLibraryQuery":
        data = normalize_json_mapping(payload)
        data.update({key: value for key, value in kwargs.items() if value is not None})

        return cls(
            user_id=normalize_user_id(data.get("user_id"), default=DEFAULT_USER_ID) or DEFAULT_USER_ID,
            include_hidden=normalize_bool(data.get("include_hidden"), default=False),
            include_deleted=normalize_bool(data.get("include_deleted"), default=False),
            include_collections=normalize_bool(data.get("include_collections"), default=True),
            include_items=normalize_bool(data.get("include_items"), default=True),
            include_overrides=normalize_bool(data.get("include_overrides"), default=True),
            include_audit=normalize_bool(data.get("include_audit"), default=False),
            ensure_defaults=normalize_bool(data.get("ensure_defaults"), default=True),
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "user_id": self.user_id,
            "include_hidden": self.include_hidden,
            "include_deleted": self.include_deleted,
            "include_collections": self.include_collections,
            "include_items": self.include_items,
            "include_overrides": self.include_overrides,
            "include_audit": self.include_audit,
            "ensure_defaults": self.ensure_defaults,
        }


@dataclass(slots=True)
class CreativeLibraryCollectionInput:
    """Normalized collection input."""

    user_id: int = DEFAULT_USER_ID
    collection_key: str | None = None
    collection_kind: str = COLLECTION_KIND_USER
    label: str | None = None
    name: str | None = None
    description: str | None = None
    icon: str | None = None
    color: str | None = None
    sort_order: int = 0
    active: bool = True
    visible: bool = True
    payload: dict[str, Any] = field(default_factory=dict)
    metadata: dict[str, Any] = field(default_factory=dict)

    @classmethod
    def from_payload(cls, payload: Mapping[str, Any] | None = None, **kwargs: Any) -> "CreativeLibraryCollectionInput":
        data = normalize_json_mapping(payload)
        data.update({key: value for key, value in kwargs.items() if value is not None})

        label = optional_string(data.get("label") or data.get("name"))

        return cls(
            user_id=normalize_user_id(data.get("user_id"), default=DEFAULT_USER_ID) or DEFAULT_USER_ID,
            collection_key=optional_string(data.get("collection_key")),
            collection_kind=optional_string(data.get("collection_kind")) or COLLECTION_KIND_USER,
            label=label,
            name=optional_string(data.get("name") or label),
            description=optional_string(data.get("description")),
            icon=optional_string(data.get("icon")),
            color=optional_string(data.get("color")),
            sort_order=normalize_int(data.get("sort_order"), default=0, minimum=0) or 0,
            active=normalize_bool(data.get("active"), default=True),
            visible=normalize_bool(data.get("visible"), default=True),
            payload=normalize_json_mapping(data.get("payload") or data),
            metadata=normalize_json_mapping(data.get("metadata")),
        )

    def validate(self) -> None:
        errors: list[str] = []

        if not self.collection_key:
            errors.append("collection_key is required")

        if not self.label and not self.name:
            errors.append("label or name is required")

        if errors:
            raise CreativeLibraryUserServiceValidationError("Invalid collection input.", errors=errors)

    def to_payload(self) -> dict[str, Any]:
        return {
            "user_id": self.user_id,
            "collection_key": self.collection_key,
            "collection_kind": self.collection_kind,
            "label": self.label or self.name,
            "name": self.name or self.label,
            "description": self.description,
            "icon": self.icon,
            "color": self.color,
            "sort_order": self.sort_order,
            "active": self.active,
            "visible": self.visible,
            "payload": normalize_json_mapping(self.payload),
            "metadata": normalize_json_mapping(self.metadata),
        }


@dataclass(slots=True)
class CreativeLibraryItemInput:
    """Normalized item input."""

    user_id: int = DEFAULT_USER_ID
    collection_ref: Any = DEFAULT_USER_COLLECTION_KEY
    target_type: str = TARGET_TYPE_ITEM
    target_id: int | None = None
    target_uid: str | None = None
    item_db_id: int | None = None
    variant_db_id: int | None = None
    vplib_uid: str | None = None
    family_id: str | None = None
    package_id: str | None = None
    variant_id: str | None = None
    draft_id: int | None = None
    draft_uid: str | None = None
    custom_label: str | None = None
    custom_icon: str | None = None
    custom_preview_url: str | None = None
    role: str | None = None
    note: str | None = None
    sort_order: int = 0
    active: bool = True
    visible: bool = True
    pinned: bool = False
    favorite: bool = False
    payload: dict[str, Any] = field(default_factory=dict)
    metadata: dict[str, Any] = field(default_factory=dict)

    @classmethod
    def from_payload(cls, payload: Mapping[str, Any] | None = None, **kwargs: Any) -> "CreativeLibraryItemInput":
        data = normalize_json_mapping(payload)
        data.update({key: value for key, value in kwargs.items() if value is not None})
        identity = extract_item_identity(data)

        return cls(
            user_id=normalize_user_id(data.get("user_id"), default=DEFAULT_USER_ID) or DEFAULT_USER_ID,
            collection_ref=collection_ref_from_payload(data),
            target_type=optional_string(data.get("target_type")) or identity.get("target_type") or TARGET_TYPE_ITEM,
            target_id=normalize_int(data.get("target_id") or identity.get("target_id"), default=None, minimum=1),
            target_uid=optional_string(data.get("target_uid") or identity.get("target_uid")),
            item_db_id=normalize_int(data.get("item_db_id") or identity.get("item_db_id"), default=None, minimum=1),
            variant_db_id=normalize_int(data.get("variant_db_id") or identity.get("variant_db_id"), default=None, minimum=1),
            vplib_uid=optional_string(data.get("vplib_uid") or identity.get("vplib_uid")),
            family_id=optional_string(data.get("family_id") or identity.get("family_id")),
            package_id=optional_string(data.get("package_id") or identity.get("package_id")),
            variant_id=optional_string(data.get("variant_id") or identity.get("variant_id")),
            draft_id=normalize_int(data.get("draft_id") or identity.get("draft_id"), default=None, minimum=1),
            draft_uid=optional_string(data.get("draft_uid") or identity.get("draft_uid")),
            custom_label=optional_string(data.get("custom_label") or data.get("label")),
            custom_icon=optional_string(data.get("custom_icon") or data.get("icon")),
            custom_preview_url=optional_string(data.get("custom_preview_url") or data.get("preview_url")),
            role=optional_string(data.get("role")),
            note=optional_string(data.get("note")),
            sort_order=normalize_int(data.get("sort_order"), default=0, minimum=0) or 0,
            active=normalize_bool(data.get("active"), default=True),
            visible=normalize_bool(data.get("visible"), default=True),
            pinned=normalize_bool(data.get("pinned"), default=False),
            favorite=normalize_bool(data.get("favorite"), default=False),
            payload=normalize_json_mapping(data.get("payload") or data),
            metadata=normalize_json_mapping(data.get("metadata")),
        )

    def validate(self) -> None:
        identity = self.identity()
        if not identity_has_reference(identity):
            raise CreativeLibraryUserServiceValidationError(
                "Item input requires at least one reference: target_uid, target_id, item_db_id, vplib_uid, family_id, package_id, variant_id, draft_uid or draft_id."
            )

    def identity(self) -> dict[str, Any]:
        return {
            "target_type": self.target_type,
            "target_id": self.target_id,
            "target_uid": self.target_uid,
            "item_db_id": self.item_db_id,
            "variant_db_id": self.variant_db_id,
            "vplib_uid": self.vplib_uid,
            "family_id": self.family_id,
            "package_id": self.package_id,
            "variant_id": self.variant_id,
            "draft_id": self.draft_id,
            "draft_uid": self.draft_uid,
        }

    def to_payload(self) -> dict[str, Any]:
        return {
            **self.identity(),
            "user_id": self.user_id,
            "custom_label": self.custom_label,
            "custom_icon": self.custom_icon,
            "custom_preview_url": self.custom_preview_url,
            "role": self.role,
            "note": self.note,
            "sort_order": self.sort_order,
            "active": self.active,
            "visible": self.visible,
            "pinned": self.pinned,
            "favorite": self.favorite,
            "payload": normalize_json_mapping(self.payload),
            "metadata": normalize_json_mapping(self.metadata),
        }


@dataclass(slots=True)
class CreativeLibraryActionInput:
    """Normalized item/collection action input."""

    user_id: int = DEFAULT_USER_ID
    action: str = ACTION_PATCH
    collection_ref: Any = DEFAULT_USER_COLLECTION_KEY
    collection_item_ref: Any = None
    target_type: str = TARGET_TYPE_ITEM
    target_id: int | None = None
    target_uid: str | None = None
    item_db_id: int | None = None
    variant_db_id: int | None = None
    vplib_uid: str | None = None
    family_id: str | None = None
    package_id: str | None = None
    variant_id: str | None = None
    draft_id: int | None = None
    draft_uid: str | None = None
    label: str | None = None
    sort_order: int | None = None
    pinned: bool | None = None
    favorite: bool | None = None
    visible: bool | None = None
    payload_patch: dict[str, Any] = field(default_factory=dict)
    metadata: dict[str, Any] = field(default_factory=dict)

    @classmethod
    def from_payload(cls, payload: Mapping[str, Any] | None = None, **kwargs: Any) -> "CreativeLibraryActionInput":
        data = normalize_json_mapping(payload)
        data.update({key: value for key, value in kwargs.items() if value is not None})
        identity = extract_item_identity(data)

        return cls(
            user_id=normalize_user_id(data.get("user_id"), default=DEFAULT_USER_ID) or DEFAULT_USER_ID,
            action=clean_string(data.get("action") or data.get("override_action"), fallback=ACTION_PATCH).lower(),
            collection_ref=collection_ref_from_payload(data),
            collection_item_ref=first_non_empty(data.get("collection_item_ref"), data.get("collection_item_uid"), data.get("collection_item_id")),
            target_type=optional_string(data.get("target_type")) or identity.get("target_type") or TARGET_TYPE_ITEM,
            target_id=normalize_int(data.get("target_id") or identity.get("target_id"), default=None, minimum=1),
            target_uid=optional_string(data.get("target_uid") or identity.get("target_uid")),
            item_db_id=normalize_int(data.get("item_db_id") or identity.get("item_db_id"), default=None, minimum=1),
            variant_db_id=normalize_int(data.get("variant_db_id") or identity.get("variant_db_id"), default=None, minimum=1),
            vplib_uid=optional_string(data.get("vplib_uid") or identity.get("vplib_uid")),
            family_id=optional_string(data.get("family_id") or identity.get("family_id")),
            package_id=optional_string(data.get("package_id") or identity.get("package_id")),
            variant_id=optional_string(data.get("variant_id") or identity.get("variant_id")),
            draft_id=normalize_int(data.get("draft_id") or identity.get("draft_id"), default=None, minimum=1),
            draft_uid=optional_string(data.get("draft_uid") or identity.get("draft_uid")),
            label=optional_string(data.get("label") or data.get("custom_label") or data.get("label_override")),
            sort_order=normalize_int(data.get("sort_order") or data.get("sort_order_override"), default=None, minimum=0),
            pinned=None if data.get("pinned") is None else normalize_bool(data.get("pinned")),
            favorite=None if data.get("favorite") is None else normalize_bool(data.get("favorite")),
            visible=None if data.get("visible") is None else normalize_bool(data.get("visible")),
            payload_patch=normalize_json_mapping(data.get("payload_patch") or data.get("patch")),
            metadata=normalize_json_mapping(data.get("metadata")),
        )

    def identity(self) -> dict[str, Any]:
        return {
            "target_type": self.target_type,
            "target_id": self.target_id,
            "target_uid": self.target_uid,
            "item_db_id": self.item_db_id,
            "variant_db_id": self.variant_db_id,
            "vplib_uid": self.vplib_uid,
            "family_id": self.family_id,
            "package_id": self.package_id,
            "variant_id": self.variant_id,
            "draft_id": self.draft_id,
            "draft_uid": self.draft_uid,
        }

    def to_override_payload(self) -> dict[str, Any]:
        identity = self.identity()
        target_uid = first_non_empty(identity.get("target_uid"), identity.get("vplib_uid"), identity.get("variant_id"), identity.get("family_id"), identity.get("package_id"), identity.get("draft_uid"))
        target_id = first_non_empty(identity.get("target_id"), identity.get("item_db_id"), identity.get("variant_db_id"), identity.get("draft_id"))

        payload = {
            **identity,
            "user_id": self.user_id,
            "target_type": self.target_type,
            "target_uid": target_uid,
            "target_id": target_id,
            "override_action": self.action,
            "payload_patch": normalize_json_mapping(self.payload_patch),
            "metadata": normalize_json_mapping(self.metadata),
            "active": True,
        }

        if self.action in {ACTION_HIDE, ACTION_REMOVE, ACTION_REMOVE_FROM_USER_LIBRARY}:
            payload["visible_override"] = False

        if self.action == ACTION_RESTORE:
            payload["visible_override"] = True
            payload["active_override"] = True

        if self.action == ACTION_FAVORITE:
            payload["favorite_override"] = True

        if self.action == ACTION_UNFAVORITE:
            payload["favorite_override"] = False

        if self.action == ACTION_PIN:
            payload["pinned_override"] = True

        if self.action == ACTION_UNPIN:
            payload["pinned_override"] = False

        if self.label is not None:
            payload["label_override"] = self.label

        if self.sort_order is not None:
            payload["sort_order_override"] = self.sort_order

        return payload


@dataclass(slots=True)
class CreativeLibraryUserServiceResult:
    """API-compatible service result."""

    ok: bool
    status: str = STATUS_OK
    action: str = ""
    payload: dict[str, Any] = field(default_factory=dict)
    errors: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)

    def add_error(self, message: Any) -> None:
        self.ok = False
        self.status = STATUS_FAILED
        self.errors.append(str(message))

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema_version": CREATIVE_LIBRARY_USER_SERVICE_VERSION,
            "ok": self.ok,
            "healthy": self.ok,
            "status": self.status,
            "action": self.action,
            "payload": normalize_json_mapping(self.payload),
            "errors": list(self.errors),
            "warnings": list(self.warnings),
        }


# ---------------------------------------------------------------------------
# Service
# ---------------------------------------------------------------------------

class CreativeLibraryUserService:
    """
    High-level service for resolved Creative Library user overlays.

    Args:
        repository:
            Optional CreativeLibraryUserRepository instance.
    """

    def __init__(self, repository: Any | None = None) -> None:
        self.repository = repository or self._create_repository()

    # ------------------------------------------------------------------
    # Construction
    # ------------------------------------------------------------------

    def _create_repository(self) -> Any:
        repo_module = _repo_module()
        factory = getattr(repo_module, "create_creative_library_user_repository", None)

        if callable(factory):
            return factory()

        repo_class = getattr(repo_module, "CreativeLibraryUserRepository", None)
        if repo_class is None:
            raise CreativeLibraryUserServiceImportError("CreativeLibraryUserRepository class is not available.")

        return repo_class()

    # ------------------------------------------------------------------
    # Resolved read API
    # ------------------------------------------------------------------

    def get_resolved_library(
        self,
        *,
        user_id: Any = DEFAULT_USER_ID,
        include_hidden: bool = False,
        include_deleted: bool = False,
        include_collections: bool = True,
        include_items: bool = True,
        include_overrides: bool = True,
        include_audit: bool = False,
        ensure_defaults: bool = True,
    ) -> dict[str, Any]:
        """Returns resolved Creative Library for user."""
        query = ResolvedCreativeLibraryQuery.from_payload(
            {
                "user_id": user_id,
                "include_hidden": include_hidden,
                "include_deleted": include_deleted,
                "include_collections": include_collections,
                "include_items": include_items,
                "include_overrides": include_overrides,
                "include_audit": include_audit,
                "ensure_defaults": ensure_defaults,
            }
        )

        if query.ensure_defaults:
            self.ensure_default_user_collections(user_id=query.user_id, commit=True)

        payload = self.repository.get_resolved_user_library_payload(
            user_id=query.user_id,
            include_hidden=query.include_hidden,
            include_deleted=query.include_deleted,
            include_collections=query.include_collections,
        )

        collections = normalize_json_list(payload.get("collections"))
        items = _dedupe_items(normalize_json_list(payload.get("items")))

        result_payload = {
            "schema_version": CREATIVE_LIBRARY_USER_SERVICE_VERSION,
            "user_id": query.user_id,
            "resolved": True,
            "include_hidden": query.include_hidden,
            "include_deleted": query.include_deleted,
            "collection_count": len(collections),
            "item_count": len(items),
        }

        if query.include_collections:
            result_payload["collections"] = collections

        if query.include_items:
            result_payload["items"] = items

        if query.include_overrides:
            result_payload["overrides"] = normalize_json_list(payload.get("overrides"))

        if query.include_audit:
            result_payload["audit"] = self.repository.list_audit_events(
                user_id=query.user_id,
                limit=100,
                as_dict=True,
            )

        return CreativeLibraryUserServiceResult(
            ok=True,
            status=STATUS_OK,
            action="get_resolved_library",
            payload=result_payload,
        ).to_dict()

    def get_creative_inventory(
        self,
        *,
        user_id: Any = DEFAULT_USER_ID,
        include_hidden: bool = False,
        include_deleted: bool = False,
    ) -> dict[str, Any]:
        """Alias for inventory consumers."""
        result = self.get_resolved_library(
            user_id=user_id,
            include_hidden=include_hidden,
            include_deleted=include_deleted,
            include_collections=True,
            include_items=True,
            include_overrides=True,
            include_audit=False,
            ensure_defaults=True,
        )
        result["action"] = "get_creative_inventory"
        return result

    def get_collection(
        self,
        collection_ref: Any,
        *,
        user_id: Any = DEFAULT_USER_ID,
        include_hidden: bool = False,
        include_deleted: bool = False,
    ) -> dict[str, Any]:
        """Returns resolved collection payload."""
        try:
            payload = self.repository.get_resolved_collection_payload(
                collection_ref,
                user_id=user_id,
                include_hidden=include_hidden,
                include_deleted=include_deleted,
            )

            return CreativeLibraryUserServiceResult(
                ok=True,
                status=STATUS_OK,
                action="get_collection",
                payload=payload,
            ).to_dict()

        except Exception as exc:
            return self.exception_result(exc, action="get_collection")

    def list_collections(
        self,
        *,
        user_id: Any = DEFAULT_USER_ID,
        include_system: bool = True,
        include_user: bool = True,
        include_deleted: bool = False,
        visible_only: bool = False,
    ) -> dict[str, Any]:
        """Lists system/user collections."""
        try:
            items = self.repository.list_collection_payloads(
                query={
                    "user_id": normalize_user_id(user_id, default=DEFAULT_USER_ID),
                    "include_system": include_system,
                    "include_user": include_user,
                    "include_deleted": include_deleted,
                    "visible_only": visible_only,
                    "active_only": not include_deleted,
                    "limit": MAX_LIMIT,
                }
            )

            return CreativeLibraryUserServiceResult(
                ok=True,
                status=STATUS_OK,
                action="list_collections",
                payload={
                    "user_id": normalize_user_id(user_id, default=DEFAULT_USER_ID),
                    "count": len(items),
                    "items": items,
                },
            ).to_dict()

        except Exception as exc:
            return self.exception_result(exc, action="list_collections")

    # ------------------------------------------------------------------
    # Collection write API
    # ------------------------------------------------------------------

    def ensure_default_user_collections(
        self,
        *,
        user_id: Any = DEFAULT_USER_ID,
        commit: bool = True,
    ) -> dict[str, Any]:
        """Ensures default user collection and favorites collection exist."""
        normalized_user_id = normalize_user_id(user_id, default=DEFAULT_USER_ID) or DEFAULT_USER_ID

        try:
            user_collection, user_created = self.repository.get_or_create_user_collection(
                user_id=normalized_user_id,
                collection_key=DEFAULT_USER_COLLECTION_KEY,
                label=DEFAULT_USER_COLLECTION_LABEL,
                collection_kind=COLLECTION_KIND_USER,
                commit=False,
            )
            favorites_collection, favorites_created = self.repository.get_or_create_user_collection(
                user_id=normalized_user_id,
                collection_key=DEFAULT_FAVORITES_COLLECTION_KEY,
                label=DEFAULT_FAVORITES_COLLECTION_LABEL,
                collection_kind=COLLECTION_KIND_FAVORITES,
                commit=False,
            )

            if commit:
                self.repository.commit()
            else:
                self.repository.flush()

            return CreativeLibraryUserServiceResult(
                ok=True,
                status=STATUS_OK,
                action="ensure_default_user_collections",
                payload={
                    "user_id": normalized_user_id,
                    "collections": [
                        to_dict_or_payload(user_collection),
                        to_dict_or_payload(favorites_collection),
                    ],
                    "created": {
                        DEFAULT_USER_COLLECTION_KEY: user_created,
                        DEFAULT_FAVORITES_COLLECTION_KEY: favorites_created,
                    },
                },
            ).to_dict()

        except Exception as exc:
            if commit:
                try:
                    self.repository.rollback()
                except Exception:
                    pass
            return self.exception_result(exc, action="ensure_default_user_collections")

    def create_collection(
        self,
        payload: Mapping[str, Any],
        *,
        user_id: Any = DEFAULT_USER_ID,
        commit: bool = True,
    ) -> dict[str, Any]:
        """Creates a user-owned collection."""
        try:
            collection_input = CreativeLibraryCollectionInput.from_payload(payload, user_id=user_id)
            collection_input.validate()

            collection = self.repository.create_collection(
                collection_input.to_payload(),
                owner_user_id=collection_input.user_id,
                source_scope=SOURCE_SCOPE_USER,
                created_by_user_id=collection_input.user_id,
                commit=commit,
                audit=True,
            )

            return CreativeLibraryUserServiceResult(
                ok=True,
                status=STATUS_OK,
                action="create_collection",
                payload={
                    "created": True,
                    "item": to_dict_or_payload(collection),
                },
            ).to_dict()

        except Exception as exc:
            return self.exception_result(exc, action="create_collection")

    def update_collection(
        self,
        collection_ref: Any,
        payload: Mapping[str, Any],
        *,
        user_id: Any = DEFAULT_USER_ID,
        commit: bool = True,
    ) -> dict[str, Any]:
        """Updates a user-owned collection."""
        try:
            collection = self.repository.update_collection(
                collection_ref,
                payload,
                user_id=user_id,
                commit=commit,
                audit=True,
            )

            return CreativeLibraryUserServiceResult(
                ok=True,
                status=STATUS_OK,
                action="update_collection",
                payload={
                    "updated": True,
                    "item": to_dict_or_payload(collection),
                },
            ).to_dict()

        except Exception as exc:
            return self.exception_result(exc, action="update_collection")

    def delete_collection(
        self,
        collection_ref: Any,
        *,
        user_id: Any = DEFAULT_USER_ID,
        commit: bool = True,
    ) -> dict[str, Any]:
        """Soft-deletes a user collection."""
        try:
            deleted = self.repository.soft_delete_collection(
                collection_ref,
                user_id=user_id,
                commit=commit,
                audit=True,
            )

            return CreativeLibraryUserServiceResult(
                ok=True,
                status=STATUS_OK,
                action="delete_collection",
                payload={
                    "deleted": deleted,
                    "collection_ref": collection_ref,
                },
            ).to_dict()

        except Exception as exc:
            return self.exception_result(exc, action="delete_collection")

    def restore_collection(
        self,
        collection_ref: Any,
        *,
        user_id: Any = DEFAULT_USER_ID,
        commit: bool = True,
    ) -> dict[str, Any]:
        """Restores a user collection."""
        try:
            collection = self.repository.restore_collection(
                collection_ref,
                user_id=user_id,
                commit=commit,
                audit=True,
            )

            return CreativeLibraryUserServiceResult(
                ok=True,
                status=STATUS_OK,
                action="restore_collection",
                payload={
                    "restored": True,
                    "item": to_dict_or_payload(collection),
                },
            ).to_dict()

        except Exception as exc:
            return self.exception_result(exc, action="restore_collection")

    # ------------------------------------------------------------------
    # Collection item write API
    # ------------------------------------------------------------------

    def add_item(
        self,
        payload: Mapping[str, Any],
        *,
        user_id: Any = DEFAULT_USER_ID,
        collection_ref: Any = None,
        commit: bool = True,
    ) -> dict[str, Any]:
        """Adds item to a user collection."""
        try:
            item_input = CreativeLibraryItemInput.from_payload(
                payload,
                user_id=user_id,
                collection_ref=collection_ref or collection_ref_from_payload(payload),
            )
            item_input.validate()

            resolved_collection_ref = item_input.collection_ref or DEFAULT_USER_COLLECTION_KEY

            if resolved_collection_ref in {None, DEFAULT_USER_COLLECTION_KEY}:
                collection, _created = self.repository.get_or_create_user_collection(
                    user_id=item_input.user_id,
                    collection_key=DEFAULT_USER_COLLECTION_KEY,
                    label=DEFAULT_USER_COLLECTION_LABEL,
                    collection_kind=COLLECTION_KIND_USER,
                    commit=False,
                )
                resolved_collection_ref = getattr(collection, "id", None)

            item, created = self.repository.add_item_to_collection(
                resolved_collection_ref,
                item_input.to_payload(),
                user_id=item_input.user_id,
                added_by_user_id=item_input.user_id,
                commit=commit,
                audit=True,
            )

            return CreativeLibraryUserServiceResult(
                ok=True,
                status=STATUS_OK,
                action="add_item",
                payload={
                    "created": created,
                    "updated": not created,
                    "item": to_dict_or_payload(item),
                },
            ).to_dict()

        except Exception as exc:
            if commit:
                try:
                    self.repository.rollback()
                except Exception:
                    pass
            return self.exception_result(exc, action="add_item")

    def remove_item(
        self,
        payload: Mapping[str, Any],
        *,
        user_id: Any = DEFAULT_USER_ID,
        collection_item_ref: Any = None,
        collection_ref: Any = None,
        commit: bool = True,
    ) -> dict[str, Any]:
        """
        Removes item from user collection.

        If collection_item_ref is provided, removes direct collection item.
        Otherwise resolves by collection + item identity.
        """
        try:
            action_input = CreativeLibraryActionInput.from_payload(
                payload,
                user_id=user_id,
                collection_item_ref=collection_item_ref,
                collection_ref=collection_ref or collection_ref_from_payload(payload),
            )

            if action_input.collection_item_ref:
                deleted = self.repository.remove_item_from_collection(
                    action_input.collection_item_ref,
                    user_id=action_input.user_id,
                    commit=commit,
                    audit=True,
                )
            else:
                identity = action_input.identity()
                if not identity_has_reference(identity):
                    raise CreativeLibraryUserServiceValidationError(
                        "remove_item requires collection_item_ref or item identity."
                    )

                deleted = self.repository.remove_item_from_collection(
                    collection_ref=action_input.collection_ref,
                    identity=identity,
                    user_id=action_input.user_id,
                    commit=commit,
                    audit=True,
                )

            return CreativeLibraryUserServiceResult(
                ok=True,
                status=STATUS_OK,
                action="remove_item",
                payload={
                    "deleted": deleted,
                    "collection_item_ref": action_input.collection_item_ref,
                    "collection_ref": action_input.collection_ref,
                    "identity": action_input.identity(),
                },
            ).to_dict()

        except Exception as exc:
            return self.exception_result(exc, action="remove_item")

    def update_collection_item(
        self,
        collection_item_ref: Any,
        payload: Mapping[str, Any],
        *,
        user_id: Any = DEFAULT_USER_ID,
        commit: bool = True,
    ) -> dict[str, Any]:
        """Updates a collection item."""
        try:
            item = self.repository.update_collection_item(
                collection_item_ref,
                payload,
                user_id=user_id,
                commit=commit,
                audit=True,
            )

            return CreativeLibraryUserServiceResult(
                ok=True,
                status=STATUS_OK,
                action="update_collection_item",
                payload={
                    "updated": True,
                    "item": to_dict_or_payload(item),
                },
            ).to_dict()

        except Exception as exc:
            return self.exception_result(exc, action="update_collection_item")

    def pin_collection_item(
        self,
        collection_item_ref: Any,
        *,
        pinned: bool = True,
        user_id: Any = DEFAULT_USER_ID,
        commit: bool = True,
    ) -> dict[str, Any]:
        """Pins/unpins a collection item."""
        try:
            item = self.repository.set_collection_item_pinned(
                collection_item_ref,
                pinned=pinned,
                user_id=user_id,
                commit=commit,
            )

            return CreativeLibraryUserServiceResult(
                ok=True,
                status=STATUS_OK,
                action="pin_collection_item" if pinned else "unpin_collection_item",
                payload={
                    "pinned": pinned,
                    "item": to_dict_or_payload(item),
                },
            ).to_dict()

        except Exception as exc:
            return self.exception_result(exc, action="pin_collection_item")

    def favorite_collection_item(
        self,
        collection_item_ref: Any,
        *,
        favorite: bool = True,
        user_id: Any = DEFAULT_USER_ID,
        commit: bool = True,
    ) -> dict[str, Any]:
        """Favorites/unfavorites a collection item directly."""
        try:
            item = self.repository.update_collection_item(
                collection_item_ref,
                {"favorite": favorite},
                user_id=user_id,
                commit=commit,
                audit=True,
            )

            return CreativeLibraryUserServiceResult(
                ok=True,
                status=STATUS_OK,
                action="favorite_collection_item" if favorite else "unfavorite_collection_item",
                payload={
                    "favorite": favorite,
                    "item": to_dict_or_payload(item),
                },
            ).to_dict()

        except Exception as exc:
            return self.exception_result(exc, action="favorite_collection_item")

    def reorder_collection_item(
        self,
        collection_item_ref: Any,
        *,
        sort_order: Any,
        user_id: Any = DEFAULT_USER_ID,
        commit: bool = True,
    ) -> dict[str, Any]:
        """Reorders a collection item."""
        try:
            item = self.repository.reorder_collection_item(
                collection_item_ref,
                sort_order=sort_order,
                user_id=user_id,
                commit=commit,
            )

            return CreativeLibraryUserServiceResult(
                ok=True,
                status=STATUS_OK,
                action="reorder_collection_item",
                payload={
                    "sort_order": normalize_int(sort_order, default=0, minimum=0),
                    "item": to_dict_or_payload(item),
                },
            ).to_dict()

        except Exception as exc:
            return self.exception_result(exc, action="reorder_collection_item")

    # ------------------------------------------------------------------
    # User override action API
    # ------------------------------------------------------------------

    def hide_item(
        self,
        payload: Mapping[str, Any],
        *,
        user_id: Any = DEFAULT_USER_ID,
        commit: bool = True,
    ) -> dict[str, Any]:
        """Hides published/system item for current user via override."""
        try:
            action_input = CreativeLibraryActionInput.from_payload(payload, user_id=user_id, action=ACTION_HIDE)
            identity = action_input.identity()

            if not identity_has_reference(identity):
                raise CreativeLibraryUserServiceValidationError("hide_item requires item identity.")

            override = self.repository.hide_item_for_user(
                identity,
                user_id=action_input.user_id,
                commit=commit,
            )

            return CreativeLibraryUserServiceResult(
                ok=True,
                status=STATUS_OK,
                action="hide_item",
                payload={
                    "hidden": True,
                    "identity": identity,
                    "override": to_dict_or_payload(override),
                },
            ).to_dict()

        except Exception as exc:
            return self.exception_result(exc, action="hide_item")

    def restore_item(
        self,
        payload: Mapping[str, Any],
        *,
        user_id: Any = DEFAULT_USER_ID,
        commit: bool = True,
    ) -> dict[str, Any]:
        """Restores hidden item for current user via override."""
        try:
            action_input = CreativeLibraryActionInput.from_payload(payload, user_id=user_id, action=ACTION_RESTORE)
            identity = action_input.identity()

            if not identity_has_reference(identity):
                raise CreativeLibraryUserServiceValidationError("restore_item requires item identity.")

            override = self.repository.restore_item_for_user(
                identity,
                user_id=action_input.user_id,
                commit=commit,
            )

            return CreativeLibraryUserServiceResult(
                ok=True,
                status=STATUS_OK,
                action="restore_item",
                payload={
                    "restored": True,
                    "identity": identity,
                    "override": to_dict_or_payload(override),
                },
            ).to_dict()

        except Exception as exc:
            return self.exception_result(exc, action="restore_item")

    def favorite_item(
        self,
        payload: Mapping[str, Any],
        *,
        user_id: Any = DEFAULT_USER_ID,
        favorite: bool = True,
        commit: bool = True,
    ) -> dict[str, Any]:
        """Favorites/unfavorites item via override and optionally adds to favorites collection."""
        try:
            action_input = CreativeLibraryActionInput.from_payload(
                payload,
                user_id=user_id,
                action=ACTION_FAVORITE if favorite else ACTION_UNFAVORITE,
            )
            identity = action_input.identity()

            if not identity_has_reference(identity):
                raise CreativeLibraryUserServiceValidationError("favorite_item requires item identity.")

            override = self.repository.favorite_item_for_user(
                identity,
                favorite=favorite,
                user_id=action_input.user_id,
                commit=False,
            )

            favorite_collection_item = None

            if favorite:
                collection, _created_collection = self.repository.get_or_create_user_collection(
                    user_id=action_input.user_id,
                    collection_key=DEFAULT_FAVORITES_COLLECTION_KEY,
                    label=DEFAULT_FAVORITES_COLLECTION_LABEL,
                    collection_kind=COLLECTION_KIND_FAVORITES,
                    commit=False,
                )
                favorite_collection_item, _created_item = self.repository.add_item_to_collection(
                    getattr(collection, "id", None),
                    {
                        **identity,
                        "favorite": True,
                        "pinned": False,
                        "custom_label": action_input.label,
                        "payload": normalize_json_mapping(payload),
                    },
                    user_id=action_input.user_id,
                    added_by_user_id=action_input.user_id,
                    commit=False,
                    audit=True,
                )

            if commit:
                self.repository.commit()
            else:
                self.repository.flush()

            return CreativeLibraryUserServiceResult(
                ok=True,
                status=STATUS_OK,
                action="favorite_item" if favorite else "unfavorite_item",
                payload={
                    "favorite": favorite,
                    "identity": identity,
                    "override": to_dict_or_payload(override),
                    "favorite_collection_item": to_dict_or_payload(favorite_collection_item) if favorite_collection_item is not None else None,
                },
            ).to_dict()

        except Exception as exc:
            if commit:
                try:
                    self.repository.rollback()
                except Exception:
                    pass
            return self.exception_result(exc, action="favorite_item")

    def pin_item(
        self,
        payload: Mapping[str, Any],
        *,
        user_id: Any = DEFAULT_USER_ID,
        pinned: bool = True,
        commit: bool = True,
    ) -> dict[str, Any]:
        """Pins/unpins item via user override."""
        try:
            action_input = CreativeLibraryActionInput.from_payload(
                payload,
                user_id=user_id,
                action=ACTION_PIN if pinned else ACTION_UNPIN,
            )
            identity = action_input.identity()

            if not identity_has_reference(identity):
                raise CreativeLibraryUserServiceValidationError("pin_item requires item identity.")

            override, created = self.repository.upsert_override(
                {
                    **action_input.to_override_payload(),
                    "override_action": ACTION_PIN if pinned else ACTION_UNPIN,
                    "pinned_override": pinned,
                },
                user_id=action_input.user_id,
                created_by_user_id=action_input.user_id,
                updated_by_user_id=action_input.user_id,
                commit=commit,
                audit=True,
            )

            return CreativeLibraryUserServiceResult(
                ok=True,
                status=STATUS_OK,
                action="pin_item" if pinned else "unpin_item",
                payload={
                    "created": created,
                    "pinned": pinned,
                    "identity": identity,
                    "override": to_dict_or_payload(override),
                },
            ).to_dict()

        except Exception as exc:
            return self.exception_result(exc, action="pin_item")

    def rename_item(
        self,
        payload: Mapping[str, Any],
        *,
        user_id: Any = DEFAULT_USER_ID,
        label: Any = None,
        commit: bool = True,
    ) -> dict[str, Any]:
        """Renames item for current user via override."""
        try:
            action_input = CreativeLibraryActionInput.from_payload(
                payload,
                user_id=user_id,
                action=ACTION_RENAME,
                label=label or payload.get("label") or payload.get("custom_label"),
            )
            identity = action_input.identity()

            if not identity_has_reference(identity):
                raise CreativeLibraryUserServiceValidationError("rename_item requires item identity.")

            if not action_input.label:
                raise CreativeLibraryUserServiceValidationError("label is required.")

            override = self.repository.rename_item_for_user(
                identity,
                label=action_input.label,
                user_id=action_input.user_id,
                commit=commit,
            )

            return CreativeLibraryUserServiceResult(
                ok=True,
                status=STATUS_OK,
                action="rename_item",
                payload={
                    "label": action_input.label,
                    "identity": identity,
                    "override": to_dict_or_payload(override),
                },
            ).to_dict()

        except Exception as exc:
            return self.exception_result(exc, action="rename_item")

    def reorder_item(
        self,
        payload: Mapping[str, Any],
        *,
        user_id: Any = DEFAULT_USER_ID,
        sort_order: Any = None,
        commit: bool = True,
    ) -> dict[str, Any]:
        """Reorders item for current user via override."""
        try:
            action_input = CreativeLibraryActionInput.from_payload(
                payload,
                user_id=user_id,
                action=ACTION_REORDER,
                sort_order=sort_order if sort_order is not None else payload.get("sort_order"),
            )
            identity = action_input.identity()

            if not identity_has_reference(identity):
                raise CreativeLibraryUserServiceValidationError("reorder_item requires item identity.")

            if action_input.sort_order is None:
                raise CreativeLibraryUserServiceValidationError("sort_order is required.")

            override, created = self.repository.upsert_override(
                {
                    **action_input.to_override_payload(),
                    "override_action": ACTION_REORDER,
                    "sort_order_override": action_input.sort_order,
                },
                user_id=action_input.user_id,
                created_by_user_id=action_input.user_id,
                updated_by_user_id=action_input.user_id,
                commit=commit,
                audit=True,
            )

            return CreativeLibraryUserServiceResult(
                ok=True,
                status=STATUS_OK,
                action="reorder_item",
                payload={
                    "created": created,
                    "sort_order": action_input.sort_order,
                    "identity": identity,
                    "override": to_dict_or_payload(override),
                },
            ).to_dict()

        except Exception as exc:
            return self.exception_result(exc, action="reorder_item")

    def create_override(
        self,
        payload: Mapping[str, Any],
        *,
        user_id: Any = DEFAULT_USER_ID,
        commit: bool = True,
    ) -> dict[str, Any]:
        """Creates/updates a user override explicitly."""
        try:
            action_input = CreativeLibraryActionInput.from_payload(payload, user_id=user_id)
            identity = action_input.identity()

            if not identity_has_reference(identity):
                raise CreativeLibraryUserServiceValidationError("create_override requires item identity.")

            override, created = self.repository.upsert_override(
                action_input.to_override_payload(),
                user_id=action_input.user_id,
                created_by_user_id=action_input.user_id,
                updated_by_user_id=action_input.user_id,
                commit=commit,
                audit=True,
            )

            return CreativeLibraryUserServiceResult(
                ok=True,
                status=STATUS_OK,
                action="create_override",
                payload={
                    "created": created,
                    "updated": not created,
                    "identity": identity,
                    "override": to_dict_or_payload(override),
                },
            ).to_dict()

        except Exception as exc:
            return self.exception_result(exc, action="create_override")

    def delete_override(
        self,
        *,
        override_ref: Any = None,
        payload: Mapping[str, Any] | None = None,
        user_id: Any = DEFAULT_USER_ID,
        commit: bool = True,
    ) -> dict[str, Any]:
        """Soft-deletes a user override by ref or target identity."""
        try:
            data = normalize_json_mapping(payload)
            action_input = CreativeLibraryActionInput.from_payload(data, user_id=user_id)
            identity = action_input.identity()

            deleted = self.repository.soft_delete_override(
                override_ref=override_ref,
                user_id=action_input.user_id,
                target_type=identity.get("target_type"),
                target_uid=first_non_empty(identity.get("target_uid"), identity.get("vplib_uid"), identity.get("variant_id"), identity.get("family_id"), identity.get("package_id"), identity.get("draft_uid")),
                target_id=first_non_empty(identity.get("target_id"), identity.get("item_db_id"), identity.get("variant_db_id"), identity.get("draft_id")),
                commit=commit,
                audit=True,
            )

            return CreativeLibraryUserServiceResult(
                ok=True,
                status=STATUS_OK,
                action="delete_override",
                payload={
                    "deleted": deleted,
                    "override_ref": override_ref,
                    "identity": identity,
                },
            ).to_dict()

        except Exception as exc:
            return self.exception_result(exc, action="delete_override")

    def list_overrides(
        self,
        *,
        user_id: Any = DEFAULT_USER_ID,
        target_type: Any = None,
        target_uid: Any = None,
        target_id: Any = None,
        active_only: bool = True,
    ) -> dict[str, Any]:
        """Lists user overrides."""
        try:
            query = {
                "user_id": normalize_user_id(user_id, default=DEFAULT_USER_ID),
                "target_type": optional_string(target_type),
                "target_uid": optional_string(target_uid),
                "target_id": normalize_int(target_id, default=None, minimum=1),
                "active_only": active_only,
                "limit": MAX_LIMIT,
            }
            items = self.repository.list_override_payloads(query=query)

            return CreativeLibraryUserServiceResult(
                ok=True,
                status=STATUS_OK,
                action="list_overrides",
                payload={
                    "query": query,
                    "count": len(items),
                    "items": items,
                },
            ).to_dict()

        except Exception as exc:
            return self.exception_result(exc, action="list_overrides")

    # ------------------------------------------------------------------
    # Audit
    # ------------------------------------------------------------------

    def list_audit_events(
        self,
        *,
        user_id: Any = DEFAULT_USER_ID,
        event_type: Any = None,
        target_type: Any = None,
        target_uid: Any = None,
        collection_uid: Any = None,
        vplib_uid: Any = None,
        limit: int = 100,
        offset: int = 0,
    ) -> dict[str, Any]:
        """Lists user library audit events."""
        try:
            items = self.repository.list_audit_events(
                user_id=user_id,
                event_type=event_type,
                target_type=target_type,
                target_uid=target_uid,
                collection_uid=collection_uid,
                vplib_uid=vplib_uid,
                limit=limit,
                offset=offset,
                as_dict=True,
            )

            return CreativeLibraryUserServiceResult(
                ok=True,
                status=STATUS_OK,
                action="list_audit_events",
                payload={
                    "count": len(items),
                    "items": items,
                },
            ).to_dict()

        except Exception as exc:
            return self.exception_result(exc, action="list_audit_events")

    # ------------------------------------------------------------------
    # Health / diagnostics
    # ------------------------------------------------------------------

    def get_health(self) -> dict[str, Any]:
        """Returns service health snapshot."""
        repository_health = {}

        try:
            if hasattr(self.repository, "get_health") and callable(self.repository.get_health):
                repository_health = self.repository.get_health()
        except Exception as exc:
            repository_health = {
                "ok": False,
                "error": f"{type(exc).__name__}: {exc}",
            }

        return {
            "schema_version": CREATIVE_LIBRARY_USER_SERVICE_VERSION,
            "ok": True,
            "healthy": True,
            "service": type(self).__name__,
            "repository_health": normalize_json_mapping(repository_health),
            "supports_resolved_library": True,
            "supports_creative_inventory": True,
            "supports_default_collections": True,
            "supports_collection_crud": True,
            "supports_collection_items": True,
            "supports_user_overrides": True,
            "supports_hide_restore": True,
            "supports_favorite": True,
            "supports_pin": True,
            "supports_rename": True,
            "supports_reorder": True,
            "supports_audit": True,
        }

    def exception_result(self, exc: Exception, *, action: str) -> dict[str, Any]:
        """Maps exception to service result."""
        lowered = f"{type(exc).__name__} {exc}".lower()

        status = STATUS_FAILED

        if "notfound" in lowered or "not found" in lowered:
            status = STATUS_NOT_FOUND
        elif "invalid" in lowered or "required" in lowered or "validation" in lowered:
            status = STATUS_INVALID_REQUEST

        errors = getattr(exc, "errors", None)
        if errors:
            error_list = [str(error) for error in errors]
        else:
            error_list = [str(exc)]

        return CreativeLibraryUserServiceResult(
            ok=False,
            status=status,
            action=action,
            errors=error_list,
        ).to_dict()


# ---------------------------------------------------------------------------
# Factory helpers
# ---------------------------------------------------------------------------

def create_creative_library_user_service(repository: Any | None = None) -> CreativeLibraryUserService:
    """Factory for dependency injection."""
    return CreativeLibraryUserService(repository=repository)


@lru_cache(maxsize=1)
def get_service_version() -> str:
    """Cached service version helper."""
    return CREATIVE_LIBRARY_USER_SERVICE_VERSION


def clear_creative_library_user_service_caches() -> dict[str, Any]:
    """Clears service import/static caches."""
    cleared: list[str] = []

    for cached_func in (
        _load_repository_module,
        get_service_version,
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
    "CREATIVE_LIBRARY_USER_SERVICE_VERSION",
    "DEFAULT_USER_ID",
    "DEFAULT_USER_COLLECTION_KEY",
    "DEFAULT_USER_COLLECTION_LABEL",
    "DEFAULT_FAVORITES_COLLECTION_KEY",
    "DEFAULT_FAVORITES_COLLECTION_LABEL",
    "DEFAULT_SYSTEM_COLLECTION_KEY",
    "SOURCE_SCOPE_SYSTEM",
    "SOURCE_SCOPE_USER",
    "SOURCE_SCOPE_IMPORTED",
    "SOURCE_SCOPE_GENERATED",
    "COLLECTION_KIND_DEFAULT",
    "COLLECTION_KIND_USER",
    "COLLECTION_KIND_PROJECT",
    "COLLECTION_KIND_FAVORITES",
    "TARGET_TYPE_ITEM",
    "TARGET_TYPE_VARIANT",
    "TARGET_TYPE_COLLECTION_ITEM",
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
    "STATUS_OK",
    "STATUS_INVALID_REQUEST",
    "STATUS_NOT_FOUND",
    "STATUS_FAILED",

    # Exceptions
    "CreativeLibraryUserServiceError",
    "CreativeLibraryUserServiceImportError",
    "CreativeLibraryUserServiceValidationError",
    "CreativeLibraryUserServiceNotFoundError",
    "CreativeLibraryUserServiceConflictError",

    # Dataclasses
    "ResolvedCreativeLibraryQuery",
    "CreativeLibraryCollectionInput",
    "CreativeLibraryItemInput",
    "CreativeLibraryActionInput",
    "CreativeLibraryUserServiceResult",

    # Service
    "CreativeLibraryUserService",
    "create_creative_library_user_service",

    # Helpers
    "clean_string",
    "optional_string",
    "normalize_int",
    "normalize_user_id",
    "normalize_bool",
    "normalize_json_mapping",
    "normalize_json_list",
    "normalize_json_value",
    "first_non_empty",
    "to_dict_or_payload",
    "extract_item_identity",
    "identity_has_reference",
    "collection_ref_from_payload",
    "get_service_version",
    "clear_creative_library_user_service_caches",
]