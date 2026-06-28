# services/vectoplan-library/src/library/repositories/library_taxonomy_repository.py
"""
Repository for VECTOPLAN Library Taxonomy.

Diese Datei kapselt alle DB-Zugriffe auf:

- library_taxonomy_nodes
- library_taxonomy_overrides
- library_taxonomy_audit_events

Ziel:

    System Taxonomy
        + User Taxonomy Nodes
        + User Overrides
        -> resolved taxonomy for user_id
        -> Creative Inventory / Create Context / Taxonomy Routes

Architekturregeln:

- Repository enthält keine Flask-Routes.
- Repository enthält keine UI-Logik.
- Repository erzeugt keine Tabellen.
- Repository führt keine Migration aus.
- Repository führt kein db.create_all() aus.
- Repository öffnet keine aktive DB-Verbindung beim Import.
- DB-Zugriffe laufen nur in expliziten Methoden.
- Business-Regeln wie "darf User Systemnode löschen?" werden defensiv
  unterstützt, aber die finale Policy gehört in den Service.
- User-Erweiterungen sind eigene Nodes oder Overrides, keine Änderungen an
  Systemnodes.
- Technische Namen, JSON-Keys und Variablen bleiben Englisch.

Phase 1:

- user_id darf weiterhin 1 sein.
- Systemnodes: source_scope="system", owner_user_id=None, owner_scope="system".
- Usernodes: source_scope="user", owner_user_id=1, owner_scope="user:1".
- Systemnodes werden nicht kopiert, sondern über Overrides angepasst.
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

LIBRARY_TAXONOMY_REPOSITORY_VERSION: Final[str] = "vectoplan_library.repository.library_taxonomy.v1"

DEFAULT_USER_ID: Final[int] = 1

SOURCE_SCOPE_SYSTEM: Final[str] = "system"
SOURCE_SCOPE_USER: Final[str] = "user"
SOURCE_SCOPE_IMPORTED: Final[str] = "imported"
SOURCE_SCOPE_GENERATED: Final[str] = "generated"

NODE_TYPE_DOMAIN: Final[str] = "domain"
NODE_TYPE_CATEGORY: Final[str] = "category"
NODE_TYPE_SUBCATEGORY: Final[str] = "subcategory"

STATUS_ACTIVE: Final[str] = "active"
STATUS_INACTIVE: Final[str] = "inactive"
STATUS_HIDDEN: Final[str] = "hidden"
STATUS_DELETED: Final[str] = "deleted"

ACTION_HIDE: Final[str] = "hide"
ACTION_RESTORE: Final[str] = "restore"
ACTION_RENAME: Final[str] = "rename"
ACTION_REORDER: Final[str] = "reorder"
ACTION_MOVE: Final[str] = "move"
ACTION_PATCH: Final[str] = "patch"
ACTION_DELETE: Final[str] = "delete"

DEFAULT_LIMIT: Final[int] = 500
MAX_LIMIT: Final[int] = 2000


# ---------------------------------------------------------------------------
# Exceptions
# ---------------------------------------------------------------------------

class LibraryTaxonomyRepositoryError(RuntimeError):
    """Base error for LibraryTaxonomyRepository."""


class LibraryTaxonomyRepositoryImportError(LibraryTaxonomyRepositoryError):
    """Raised when db/model imports fail."""


class LibraryTaxonomyNodeNotFoundError(LibraryTaxonomyRepositoryError):
    """Raised when a taxonomy node cannot be found."""


class LibraryTaxonomyOverrideNotFoundError(LibraryTaxonomyRepositoryError):
    """Raised when a taxonomy override cannot be found."""


class LibraryTaxonomyConflictError(LibraryTaxonomyRepositoryError):
    """Raised when a write operation conflicts with current taxonomy state."""


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

    raise LibraryTaxonomyRepositoryImportError(
        "Could not import SQLAlchemy extension `db`. "
        + " | ".join(errors)
    )


@lru_cache(maxsize=1)
def _load_taxonomy_models_module() -> ModuleType:
    """Loads models.library_taxonomy defensively."""
    errors: list[str] = []

    for module_name in (
        "models.library_taxonomy",
        "src.models.library_taxonomy",
        "vectoplan_library.models.library_taxonomy",
    ):
        try:
            return importlib.import_module(module_name)
        except Exception as exc:
            errors.append(f"{module_name}: {type(exc).__name__}: {exc}")

    raise LibraryTaxonomyRepositoryImportError(
        "Could not import library taxonomy models. "
        + " | ".join(errors)
    )


def _db() -> Any:
    """Short alias for lazy db access."""
    return _load_db()


def _models() -> ModuleType:
    """Short alias for lazy model access."""
    return _load_taxonomy_models_module()


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

    if text in {"1", "true", "yes", "y", "ja", "on", "enabled", "active", "visible", "selectable"}:
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


def owner_scope_for(*, source_scope: Any = SOURCE_SCOPE_SYSTEM, owner_user_id: Any = None) -> str:
    """Builds stable owner_scope."""
    helper = getattr(_models(), "owner_scope_for", None)

    if callable(helper):
        return str(helper(source_scope=source_scope, owner_user_id=owner_user_id))

    scope = clean_string(source_scope, fallback=SOURCE_SCOPE_SYSTEM).lower()
    user_id = normalize_user_id(owner_user_id, default=None)

    if scope == SOURCE_SCOPE_SYSTEM and user_id is None:
        return SOURCE_SCOPE_SYSTEM

    if scope == SOURCE_SCOPE_USER:
        return f"user:{user_id or DEFAULT_USER_ID}"

    if user_id is not None:
        return f"{scope}:{user_id}"

    return scope


def taxonomy_path_for(
    *,
    domain: Any = None,
    category: Any = None,
    subcategory: Any = None,
) -> str | None:
    """Builds taxonomy_path."""
    helper = getattr(_models(), "taxonomy_path_for", None)

    if callable(helper):
        try:
            return helper(domain=domain, category=category, subcategory=subcategory)
        except Exception:
            pass

    parts = [
        optional_string(domain),
        optional_string(category),
        optional_string(subcategory),
    ]
    cleaned = [part for part in parts if part]
    return "/".join(cleaned) if cleaned else None


def infer_node_type(
    *,
    node_type: Any = None,
    domain: Any = None,
    category: Any = None,
    subcategory: Any = None,
    parent_node_id: Any = None,
) -> str:
    """Infers node type."""
    helper = getattr(_models(), "infer_node_type", None)

    if callable(helper):
        try:
            return str(
                helper(
                    node_type=node_type,
                    domain=domain,
                    category=category,
                    subcategory=subcategory,
                    parent_node_id=parent_node_id,
                )
            )
        except Exception:
            pass

    explicit = optional_string(node_type)
    if explicit:
        return explicit

    if subcategory:
        return NODE_TYPE_SUBCATEGORY

    if category:
        return NODE_TYPE_CATEGORY

    return NODE_TYPE_DOMAIN


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
        "node_uid",
        "parent_node_id",
        "parent_node_uid",
        "node_type",
        "node_key",
        "slug",
        "domain",
        "category",
        "subcategory",
        "taxonomy_path",
        "label",
        "name",
        "description",
        "source_scope",
        "owner_user_id",
        "owner_scope",
        "base_node_uid",
        "status",
        "active",
        "visible",
        "selectable",
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


def _payload_node_uid(payload: Mapping[str, Any]) -> str | None:
    """Gets node uid from payload."""
    return optional_string(payload.get("node_uid") or payload.get("uid") or payload.get("target_node_uid"))


def _payload_node_key(payload: Mapping[str, Any]) -> str | None:
    """Gets stable node key from payload."""
    return optional_string(
        payload.get("node_key")
        or payload.get("key")
        or payload.get("slug")
        or payload.get("taxonomy_path")
    )


# ---------------------------------------------------------------------------
# Dataclasses
# ---------------------------------------------------------------------------

@dataclass(slots=True)
class TaxonomyNodeQuery:
    """Structured taxonomy node query."""

    user_id: int | None = None
    owner_user_id: int | None = None
    owner_scope: str | None = None
    source_scope: str | None = None
    node_type: str | None = None
    parent_node_id: int | None = None
    parent_node_uid: str | None = None
    base_node_uid: str | None = None
    domain: str | None = None
    category: str | None = None
    subcategory: str | None = None
    taxonomy_path: str | None = None
    active_only: bool = True
    visible_only: bool = False
    selectable_only: bool = False
    include_deleted: bool = False
    include_system: bool = True
    include_user: bool = True
    limit: int = DEFAULT_LIMIT
    offset: int = 0

    @classmethod
    def from_payload(cls, payload: Mapping[str, Any] | None = None, **kwargs: Any) -> "TaxonomyNodeQuery":
        data = normalize_json_mapping(payload)
        data.update({key: value for key, value in kwargs.items() if value is not None})

        return cls(
            user_id=normalize_user_id(data.get("user_id"), default=None),
            owner_user_id=normalize_user_id(data.get("owner_user_id"), default=None),
            owner_scope=optional_string(data.get("owner_scope")),
            source_scope=optional_string(data.get("source_scope")),
            node_type=optional_string(data.get("node_type")),
            parent_node_id=normalize_int(data.get("parent_node_id"), default=None, minimum=1),
            parent_node_uid=optional_string(data.get("parent_node_uid")),
            base_node_uid=optional_string(data.get("base_node_uid")),
            domain=optional_string(data.get("domain")),
            category=optional_string(data.get("category")),
            subcategory=optional_string(data.get("subcategory")),
            taxonomy_path=optional_string(data.get("taxonomy_path")),
            active_only=normalize_bool(data.get("active_only"), default=True),
            visible_only=normalize_bool(data.get("visible_only"), default=False),
            selectable_only=normalize_bool(data.get("selectable_only"), default=False),
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

    def to_dict(self) -> dict[str, Any]:
        return {
            "user_id": self.user_id,
            "owner_user_id": self.owner_user_id,
            "owner_scope": self.owner_scope,
            "source_scope": self.source_scope,
            "node_type": self.node_type,
            "parent_node_id": self.parent_node_id,
            "parent_node_uid": self.parent_node_uid,
            "base_node_uid": self.base_node_uid,
            "domain": self.domain,
            "category": self.category,
            "subcategory": self.subcategory,
            "taxonomy_path": self.taxonomy_path,
            "active_only": self.active_only,
            "visible_only": self.visible_only,
            "selectable_only": self.selectable_only,
            "include_deleted": self.include_deleted,
            "include_system": self.include_system,
            "include_user": self.include_user,
            "limit": self.limit,
            "offset": self.offset,
        }


@dataclass(slots=True)
class TaxonomyOverrideQuery:
    """Structured taxonomy override query."""

    user_id: int = DEFAULT_USER_ID
    target_node_uid: str | None = None
    action: str | None = None
    active_only: bool = True
    include_deleted: bool = False
    limit: int = DEFAULT_LIMIT
    offset: int = 0

    @classmethod
    def from_payload(cls, payload: Mapping[str, Any] | None = None, **kwargs: Any) -> "TaxonomyOverrideQuery":
        data = normalize_json_mapping(payload)
        data.update({key: value for key, value in kwargs.items() if value is not None})

        return cls(
            user_id=normalize_user_id(data.get("user_id"), default=DEFAULT_USER_ID) or DEFAULT_USER_ID,
            target_node_uid=optional_string(data.get("target_node_uid")),
            action=optional_string(data.get("action") or data.get("override_action")),
            active_only=normalize_bool(data.get("active_only"), default=True),
            include_deleted=normalize_bool(data.get("include_deleted"), default=False),
            limit=normalize_int(data.get("limit"), default=DEFAULT_LIMIT, minimum=1, maximum=MAX_LIMIT) or DEFAULT_LIMIT,
            offset=normalize_int(data.get("offset"), default=0, minimum=0) or 0,
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "user_id": self.user_id,
            "target_node_uid": self.target_node_uid,
            "action": self.action,
            "active_only": self.active_only,
            "include_deleted": self.include_deleted,
            "limit": self.limit,
            "offset": self.offset,
        }


@dataclass(slots=True)
class TaxonomyWriteResult:
    """JSON-compatible taxonomy write result."""

    ok: bool
    action: str
    node_uid: str | None = None
    override_uid: str | None = None
    event_uid: str | None = None
    node_id: int | None = None
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
            "schema_version": LIBRARY_TAXONOMY_REPOSITORY_VERSION,
            "ok": self.ok,
            "action": self.action,
            "node_uid": self.node_uid,
            "override_uid": self.override_uid,
            "event_uid": self.event_uid,
            "node_id": self.node_id,
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

class LibraryTaxonomyRepository:
    """
    SQLAlchemy repository for Library Taxonomy.

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
    # Node reads
    # ------------------------------------------------------------------

    def get_node_by_id(
        self,
        node_id: Any,
        *,
        include_deleted: bool = False,
        for_update: bool = False,
    ) -> Any | None:
        """Returns node by DB id."""
        normalized_id = normalize_int(node_id, default=None, minimum=1)
        if normalized_id is None:
            return None

        model = self.models.LibraryTaxonomyNode
        query = self.session.query(model).filter(model.id == normalized_id)

        if not include_deleted and hasattr(model, "status"):
            query = query.filter(model.status != STATUS_DELETED)

        if for_update:
            query = self._with_for_update(query)

        return query.one_or_none()

    def get_node_by_uid(
        self,
        node_uid: Any,
        *,
        include_deleted: bool = False,
        for_update: bool = False,
    ) -> Any | None:
        """Returns node by node_uid."""
        uid = optional_string(node_uid)
        if not uid:
            return None

        model = self.models.LibraryTaxonomyNode
        query = self.session.query(model).filter(model.node_uid == uid)

        if not include_deleted and hasattr(model, "status"):
            query = query.filter(model.status != STATUS_DELETED)

        if for_update:
            query = self._with_for_update(query)

        return query.one_or_none()

    def get_node_by_path(
        self,
        taxonomy_path: Any,
        *,
        user_id: Any = None,
        prefer_user: bool = True,
        include_deleted: bool = False,
        for_update: bool = False,
    ) -> Any | None:
        """Returns node by taxonomy_path, preferring user node when requested."""
        path = optional_string(taxonomy_path)
        if not path:
            return None

        model = self.models.LibraryTaxonomyNode
        query = self.session.query(model).filter(model.taxonomy_path == path)

        owner_scopes = [SOURCE_SCOPE_SYSTEM]
        normalized_user_id = normalize_user_id(user_id, default=None)

        if normalized_user_id is not None:
            user_scope = f"user:{normalized_user_id}"
            owner_scopes = [user_scope, SOURCE_SCOPE_SYSTEM] if prefer_user else [SOURCE_SCOPE_SYSTEM, user_scope]

        if hasattr(model, "owner_scope"):
            query = query.filter(model.owner_scope.in_(tuple(_dedupe_preserve_order(owner_scopes))))

        if not include_deleted and hasattr(model, "status"):
            query = query.filter(model.status != STATUS_DELETED)

        if for_update:
            query = self._with_for_update(query)

        values = query.all()

        if not values:
            return None

        if normalized_user_id is not None and prefer_user:
            user_scope = f"user:{normalized_user_id}"
            for node in values:
                if getattr(node, "owner_scope", None) == user_scope:
                    return node

        for node in values:
            if getattr(node, "owner_scope", None) == SOURCE_SCOPE_SYSTEM:
                return node

        return values[0]

    def get_node(
        self,
        node_ref: Any,
        *,
        include_deleted: bool = False,
        for_update: bool = False,
    ) -> Any | None:
        """Returns node by id or uid."""
        text = clean_string(node_ref)

        if text.isdigit():
            return self.get_node_by_id(text, include_deleted=include_deleted, for_update=for_update)

        return self.get_node_by_uid(text, include_deleted=include_deleted, for_update=for_update)

    def require_node(
        self,
        node_ref: Any,
        *,
        include_deleted: bool = False,
        for_update: bool = False,
    ) -> Any:
        """Returns node or raises."""
        node = self.get_node(node_ref, include_deleted=include_deleted, for_update=for_update)

        if node is None:
            raise LibraryTaxonomyNodeNotFoundError(f"Taxonomy node {node_ref!r} was not found.")

        return node

    def list_nodes(
        self,
        *,
        query: TaxonomyNodeQuery | Mapping[str, Any] | None = None,
        as_dict: bool = False,
    ) -> list[Any]:
        """Lists taxonomy nodes."""
        node_query = query if isinstance(query, TaxonomyNodeQuery) else TaxonomyNodeQuery.from_payload(query)
        model = self.models.LibraryTaxonomyNode

        db_query = self.session.query(model)

        owner_scopes = node_query.resolved_owner_scopes()
        if owner_scopes and hasattr(model, "owner_scope"):
            db_query = db_query.filter(model.owner_scope.in_(owner_scopes))

        if node_query.source_scope:
            db_query = db_query.filter(model.source_scope == node_query.source_scope)

        if node_query.owner_user_id is not None:
            db_query = db_query.filter(model.owner_user_id == node_query.owner_user_id)

        if node_query.node_type:
            db_query = db_query.filter(model.node_type == node_query.node_type)

        if node_query.parent_node_id is not None:
            db_query = db_query.filter(model.parent_node_id == node_query.parent_node_id)

        if node_query.parent_node_uid:
            parent = self.get_node_by_uid(node_query.parent_node_uid)
            if parent is None:
                return []
            db_query = db_query.filter(model.parent_node_id == parent.id)

        if node_query.base_node_uid:
            db_query = db_query.filter(model.base_node_uid == node_query.base_node_uid)

        for field_name in ("domain", "category", "subcategory", "taxonomy_path"):
            value = getattr(node_query, field_name)
            if value is not None and hasattr(model, field_name):
                db_query = db_query.filter(getattr(model, field_name) == value)

        if node_query.active_only and hasattr(model, "active"):
            db_query = db_query.filter(model.active.is_(True))

        if node_query.visible_only and hasattr(model, "visible"):
            db_query = db_query.filter(model.visible.is_(True))

        if node_query.selectable_only and hasattr(model, "selectable"):
            db_query = db_query.filter(model.selectable.is_(True))

        if not node_query.include_deleted and hasattr(model, "status"):
            db_query = db_query.filter(model.status != STATUS_DELETED)

        db_query = self._apply_node_sort(db_query, model)

        if node_query.offset:
            db_query = db_query.offset(node_query.offset)

        if node_query.limit:
            db_query = db_query.limit(node_query.limit)

        values = db_query.all()

        if as_dict:
            return [to_dict_or_payload(value) for value in values]

        return values

    def list_node_payloads(self, *, query: TaxonomyNodeQuery | Mapping[str, Any] | None = None) -> list[dict[str, Any]]:
        """Lists taxonomy nodes as dicts."""
        return self.list_nodes(query=query, as_dict=True)

    def list_children(
        self,
        node_ref: Any,
        *,
        user_id: Any = None,
        include_deleted: bool = False,
        as_dict: bool = False,
    ) -> list[Any]:
        """Lists child nodes for one parent node."""
        parent = self.require_node(node_ref)
        query = TaxonomyNodeQuery(
            user_id=normalize_user_id(user_id, default=None),
            parent_node_id=getattr(parent, "id", None),
            include_deleted=include_deleted,
            limit=MAX_LIMIT,
        )
        return self.list_nodes(query=query, as_dict=as_dict)

    # ------------------------------------------------------------------
    # Node writes
    # ------------------------------------------------------------------

    def create_node(
        self,
        payload: Mapping[str, Any],
        *,
        source_scope: Any = SOURCE_SCOPE_USER,
        owner_user_id: Any = DEFAULT_USER_ID,
        created_by_user_id: Any = None,
        parent: Any = None,
        parent_ref: Any = None,
        commit: bool = False,
        audit: bool = True,
    ) -> Any:
        """Creates a taxonomy node."""
        data = normalize_json_mapping(payload)

        try:
            resolved_parent = parent
            if resolved_parent is None and parent_ref is not None:
                resolved_parent = self.require_node(parent_ref)

            if resolved_parent is not None:
                data.setdefault("parent_node_id", getattr(resolved_parent, "id", None))
                data.setdefault("parent_node_uid", getattr(resolved_parent, "node_uid", None))
                data.setdefault("parent_taxonomy_path", getattr(resolved_parent, "taxonomy_path", None))

            creator = getattr(self.models.LibraryTaxonomyNode, "create_from_payload", None)

            if callable(creator):
                node = creator(
                    data,
                    parent=resolved_parent,
                    source_scope=source_scope,
                    owner_user_id=owner_user_id,
                    created_by_user_id=created_by_user_id,
                )
            else:
                node = self.models.LibraryTaxonomyNode(**self._fallback_node_kwargs(data, source_scope=source_scope, owner_user_id=owner_user_id))

            self.session.add(node)
            self.session.flush()

            if audit:
                self.create_audit_event(
                    event_type="node_created",
                    user_id=created_by_user_id or owner_user_id,
                    node=node,
                    after=to_dict_or_payload(node),
                    commit=False,
                )

            self._finish_write(commit=commit)
            return node

        except Exception:
            if commit:
                self.rollback()
            raise

    def update_node(
        self,
        node_ref: Any,
        payload: Mapping[str, Any],
        *,
        user_id: Any = None,
        commit: bool = False,
        audit: bool = True,
    ) -> Any:
        """Updates a mutable taxonomy node."""
        data = normalize_json_mapping(payload)

        try:
            node = self.require_node(node_ref, include_deleted=True, for_update=True)
            before = to_dict_or_payload(node)

            updater = getattr(node, "update_from_payload", None)
            if callable(updater):
                updater(data, updated_by_user_id=user_id)
            else:
                self._fallback_update_node(node, data, user_id=user_id)

            after = to_dict_or_payload(node)

            if audit:
                self.create_audit_event(
                    event_type="node_updated",
                    user_id=user_id or getattr(node, "owner_user_id", None),
                    node=node,
                    before=before,
                    after=after,
                    commit=False,
                )

            self._finish_write(commit=commit)
            return node

        except Exception:
            if commit:
                self.rollback()
            raise

    def soft_delete_node(
        self,
        node_ref: Any,
        *,
        user_id: Any = None,
        commit: bool = False,
        audit: bool = True,
    ) -> bool:
        """Soft-deletes a node."""
        try:
            node = self.require_node(node_ref, include_deleted=True, for_update=True)

            if getattr(node, "owner_scope", None) == SOURCE_SCOPE_SYSTEM:
                raise LibraryTaxonomyConflictError(
                    "System taxonomy nodes should not be deleted directly. "
                    "Create a user override instead."
                )

            before = to_dict_or_payload(node)

            if hasattr(node, "mark_deleted") and callable(node.mark_deleted):
                node.mark_deleted(user_id=user_id)
            else:
                node.status = STATUS_DELETED
                node.active = False
                node.visible = False

            after = to_dict_or_payload(node)

            if audit:
                self.create_audit_event(
                    event_type="node_deleted",
                    user_id=user_id or getattr(node, "owner_user_id", None),
                    node=node,
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

    def restore_node(
        self,
        node_ref: Any,
        *,
        user_id: Any = None,
        commit: bool = False,
        audit: bool = True,
    ) -> Any:
        """Restores a deleted node."""
        try:
            node = self.require_node(node_ref, include_deleted=True, for_update=True)
            before = to_dict_or_payload(node)

            if hasattr(node, "restore") and callable(node.restore):
                node.restore(user_id=user_id)
            else:
                node.status = STATUS_ACTIVE
                node.active = True
                node.visible = True

            after = to_dict_or_payload(node)

            if audit:
                self.create_audit_event(
                    event_type="node_restored",
                    user_id=user_id or getattr(node, "owner_user_id", None),
                    node=node,
                    before=before,
                    after=after,
                    commit=False,
                )

            self._finish_write(commit=commit)
            return node

        except Exception:
            if commit:
                self.rollback()
            raise

    def get_or_create_node(
        self,
        payload: Mapping[str, Any],
        *,
        user_id: Any = DEFAULT_USER_ID,
        source_scope: Any = SOURCE_SCOPE_USER,
        commit: bool = False,
    ) -> tuple[Any, bool]:
        """
        Gets existing node by taxonomy_path or creates it.

        Returns:
            (node, created)
        """
        data = normalize_json_mapping(payload)
        path = optional_string(data.get("taxonomy_path")) or taxonomy_path_for(
            domain=data.get("domain"),
            category=data.get("category"),
            subcategory=data.get("subcategory"),
        )

        if path:
            existing = self.get_node_by_path(path, user_id=user_id, prefer_user=True)
            if existing is not None:
                return existing, False

        node = self.create_node(
            data,
            source_scope=source_scope,
            owner_user_id=user_id,
            created_by_user_id=user_id,
            commit=commit,
            audit=True,
        )
        return node, True

    # ------------------------------------------------------------------
    # Override reads
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

        model = self.models.LibraryTaxonomyOverride
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
        """Returns override by override_uid."""
        uid = optional_string(override_uid)
        if not uid:
            return None

        model = self.models.LibraryTaxonomyOverride
        query = self.session.query(model).filter(model.override_uid == uid)

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

    def get_override_for_node(
        self,
        *,
        user_id: Any,
        target_node_uid: Any,
        active_only: bool = True,
        include_deleted: bool = False,
        for_update: bool = False,
    ) -> Any | None:
        """Returns one override for user and target node."""
        model = self.models.LibraryTaxonomyOverride
        normalized_user_id = normalize_user_id(user_id, default=DEFAULT_USER_ID)
        target_uid = optional_string(target_node_uid)

        if not target_uid:
            return None

        query = (
            self.session.query(model)
            .filter(model.user_id == normalized_user_id)
            .filter(model.target_node_uid == target_uid)
        )

        if active_only and hasattr(model, "active"):
            query = query.filter(model.active.is_(True))

        if not include_deleted and hasattr(model, "status"):
            query = query.filter(model.status != STATUS_DELETED)

        if for_update:
            query = self._with_for_update(query)

        return query.one_or_none()

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
            raise LibraryTaxonomyOverrideNotFoundError(f"Taxonomy override {override_ref!r} was not found.")

        return override

    def list_overrides(
        self,
        *,
        query: TaxonomyOverrideQuery | Mapping[str, Any] | None = None,
        as_dict: bool = False,
    ) -> list[Any]:
        """Lists taxonomy overrides."""
        override_query = query if isinstance(query, TaxonomyOverrideQuery) else TaxonomyOverrideQuery.from_payload(query)
        model = self.models.LibraryTaxonomyOverride

        db_query = self.session.query(model).filter(model.user_id == override_query.user_id)

        if override_query.target_node_uid:
            db_query = db_query.filter(model.target_node_uid == override_query.target_node_uid)

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

    def list_override_payloads(self, *, query: TaxonomyOverrideQuery | Mapping[str, Any] | None = None) -> list[dict[str, Any]]:
        """Lists overrides as dicts."""
        return self.list_overrides(query=query, as_dict=True)

    # ------------------------------------------------------------------
    # Override writes
    # ------------------------------------------------------------------

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
        Creates or updates a taxonomy override.

        Returns:
            (override, created)
        """
        data = normalize_json_mapping(payload)
        normalized_user_id = normalize_user_id(user_id or data.get("user_id"), default=DEFAULT_USER_ID) or DEFAULT_USER_ID
        target_node_uid = optional_string(data.get("target_node_uid") or data.get("node_uid"))

        if not target_node_uid:
            target_node_ref = data.get("target_node_id") or data.get("node_id") or data.get("target")
            if target_node_ref:
                node = self.require_node(target_node_ref)
                target_node_uid = getattr(node, "node_uid", None)

        if not target_node_uid:
            raise ValueError("target_node_uid is required for taxonomy override.")

        try:
            override = self.get_override_for_node(
                user_id=normalized_user_id,
                target_node_uid=target_node_uid,
                active_only=False,
                include_deleted=True,
                for_update=True,
            )
            created = override is None

            if created:
                creator = getattr(self.models.LibraryTaxonomyOverride, "create_from_payload", None)

                if callable(creator):
                    override = creator(
                        {
                            **data,
                            "user_id": normalized_user_id,
                            "target_node_uid": target_node_uid,
                        },
                        user_id=normalized_user_id,
                        created_by_user_id=created_by_user_id,
                    )
                else:
                    override = self.models.LibraryTaxonomyOverride(
                        user_id=normalized_user_id,
                        target_node_uid=target_node_uid,
                        override_action=data.get("override_action") or data.get("action") or ACTION_PATCH,
                        active=True,
                    )

                self.session.add(override)
            else:
                before = to_dict_or_payload(override)
                incoming = self._build_override_for_update(
                    {
                        **data,
                        "user_id": normalized_user_id,
                        "target_node_uid": target_node_uid,
                    },
                    user_id=normalized_user_id,
                    created_by_user_id=created_by_user_id,
                )

                for field_name in (
                    "override_action",
                    "action",
                    "status",
                    "active",
                    "visible_override",
                    "active_override",
                    "selectable_override",
                    "label_override",
                    "description_override",
                    "icon_override",
                    "color_override",
                    "sort_order_override",
                    "parent_node_uid_override",
                    "payload_patch",
                    "before_json",
                    "after_json",
                    "meta",
                    "metadata_json",
                ):
                    if hasattr(override, field_name) and hasattr(incoming, field_name):
                        setattr(override, field_name, getattr(incoming, field_name))

                updater_id = normalize_user_id(updated_by_user_id, default=None)
                if updater_id is not None and hasattr(override, "updated_by_user_id"):
                    override.updated_by_user_id = updater_id

                if hasattr(override, "touch") and callable(override.touch):
                    override.touch()

            self.session.flush()

            if audit:
                self.create_audit_event(
                    event_type="override_created" if created else "override_updated",
                    user_id=normalized_user_id,
                    override=override,
                    node=self.get_node_by_uid(target_node_uid, include_deleted=True),
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
        target_node_uid: Any = None,
        commit: bool = False,
        audit: bool = True,
    ) -> bool:
        """Soft-deletes a taxonomy override."""
        try:
            if override_ref is not None:
                override = self.require_override(override_ref, include_deleted=True, for_update=True)
            else:
                override = self.get_override_for_node(
                    user_id=user_id,
                    target_node_uid=target_node_uid,
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
                override.status = STATUS_DELETED
                override.active = False

            after = to_dict_or_payload(override)

            if audit:
                self.create_audit_event(
                    event_type="override_deleted",
                    user_id=user_id,
                    override=override,
                    node=self.get_node_by_uid(getattr(override, "target_node_uid", None), include_deleted=True),
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
    # Resolved taxonomy
    # ------------------------------------------------------------------

    def get_resolved_nodes(
        self,
        *,
        user_id: Any = DEFAULT_USER_ID,
        include_hidden: bool = False,
        include_deleted: bool = False,
        as_tree: bool = False,
    ) -> list[dict[str, Any]] | dict[str, Any]:
        """
        Resolves system + user taxonomy + user overrides.

        Merge strategy:
        - load active system nodes
        - load active user nodes
        - apply active user overrides to system nodes
        - include user nodes directly
        - optionally build tree
        """
        normalized_user_id = normalize_user_id(user_id, default=DEFAULT_USER_ID) or DEFAULT_USER_ID

        system_nodes = self.list_node_payloads(
            query=TaxonomyNodeQuery(
                include_system=True,
                include_user=False,
                active_only=not include_deleted,
                visible_only=False,
                include_deleted=include_deleted,
                limit=MAX_LIMIT,
            )
        )
        user_nodes = self.list_node_payloads(
            query=TaxonomyNodeQuery(
                user_id=normalized_user_id,
                include_system=False,
                include_user=True,
                active_only=not include_deleted,
                visible_only=False,
                include_deleted=include_deleted,
                limit=MAX_LIMIT,
            )
        )
        overrides = self.list_override_payloads(
            query=TaxonomyOverrideQuery(
                user_id=normalized_user_id,
                active_only=True,
                include_deleted=include_deleted,
                limit=MAX_LIMIT,
            )
        )

        override_by_target_uid = {
            optional_string(override.get("target_node_uid")): override
            for override in overrides
            if optional_string(override.get("target_node_uid"))
        }

        resolved: list[dict[str, Any]] = []

        for node in system_nodes:
            node_uid = optional_string(node.get("node_uid"))
            override = override_by_target_uid.get(node_uid)

            if override:
                merged = self.apply_override_payload(node, override)
            else:
                merged = dict(node)

            if not include_hidden and not normalize_bool(merged.get("visible"), default=True):
                continue

            if not include_deleted and clean_string(merged.get("status")) == STATUS_DELETED:
                continue

            resolved.append(merged)

        for node in user_nodes:
            if not include_hidden and not normalize_bool(node.get("visible"), default=True):
                continue

            if not include_deleted and clean_string(node.get("status")) == STATUS_DELETED:
                continue

            resolved.append(dict(node))

        resolved.sort(
            key=lambda item: (
                normalize_int(item.get("depth"), default=0) or 0,
                normalize_int(item.get("sort_order"), default=0) or 0,
                clean_string(item.get("label") or item.get("node_key") or item.get("taxonomy_path")),
            )
        )

        if as_tree:
            return self.build_tree_payload(resolved)

        return resolved

    def get_resolved_taxonomy_payload(
        self,
        *,
        user_id: Any = DEFAULT_USER_ID,
        include_hidden: bool = False,
        include_deleted: bool = False,
    ) -> dict[str, Any]:
        """Returns full resolved taxonomy payload."""
        nodes = self.get_resolved_nodes(
            user_id=user_id,
            include_hidden=include_hidden,
            include_deleted=include_deleted,
            as_tree=False,
        )
        tree = self.build_tree_payload(nodes if isinstance(nodes, list) else [])

        return {
            "schema_version": LIBRARY_TAXONOMY_REPOSITORY_VERSION,
            "user_id": normalize_user_id(user_id, default=DEFAULT_USER_ID),
            "resolved": True,
            "include_hidden": include_hidden,
            "include_deleted": include_deleted,
            "node_count": len(nodes) if isinstance(nodes, list) else 0,
            "nodes": nodes,
            "tree": tree,
        }

    def apply_override_payload(
        self,
        node_payload: Mapping[str, Any],
        override_payload: Mapping[str, Any],
    ) -> dict[str, Any]:
        """Applies override to node payload."""
        helper = getattr(self.models, "apply_override_to_node_payload", None)

        if callable(helper):
            try:
                return normalize_json_mapping(helper(node_payload, override_payload))
            except Exception:
                pass

        result = normalize_json_mapping(node_payload)
        override = normalize_json_mapping(override_payload)

        action = clean_string(override.get("override_action") or override.get("action")).lower()

        if action == ACTION_HIDE:
            result["visible"] = False
            result["hidden_by_override"] = True

        if action == ACTION_RESTORE:
            result["visible"] = True
            result["hidden_by_override"] = False

        if action == ACTION_DELETE:
            result["status"] = STATUS_DELETED
            result["active"] = False
            result["visible"] = False
            result["deleted_by_override"] = True

        if override.get("visible_override") is not None:
            result["visible"] = normalize_bool(override.get("visible_override"), default=result.get("visible", True))

        if override.get("active_override") is not None:
            result["active"] = normalize_bool(override.get("active_override"), default=result.get("active", True))

        if override.get("selectable_override") is not None:
            result["selectable"] = normalize_bool(override.get("selectable_override"), default=result.get("selectable", True))

        for source_key, target_key in (
            ("label_override", "label"),
            ("description_override", "description"),
            ("icon_override", "icon"),
            ("color_override", "color"),
            ("sort_order_override", "sort_order"),
            ("parent_node_uid_override", "parent_node_uid"),
        ):
            if override.get(source_key) is not None:
                result[target_key] = normalize_json_value(override[source_key])

        patch = normalize_json_mapping(override.get("payload_patch"))
        if patch:
            result["payload"] = {
                **normalize_json_mapping(result.get("payload")),
                **patch,
            }

        result["override"] = override
        return result

    def build_tree_payload(self, nodes: Iterable[Mapping[str, Any]]) -> dict[str, Any]:
        """Builds a nested taxonomy tree payload."""
        helper = getattr(self.models, "build_taxonomy_tree_from_nodes", None)

        if callable(helper):
            try:
                return normalize_json_mapping(helper(nodes))
            except Exception:
                pass

        values = [normalize_json_mapping(node) for node in nodes]
        by_uid: dict[str, dict[str, Any]] = {}
        roots: list[dict[str, Any]] = []

        for node in values:
            node_uid = optional_string(node.get("node_uid"))
            if not node_uid:
                continue
            item = dict(node)
            item["children"] = []
            by_uid[node_uid] = item

        for item in by_uid.values():
            parent_uid = optional_string(item.get("parent_node_uid"))

            if parent_uid and parent_uid in by_uid:
                by_uid[parent_uid].setdefault("children", []).append(item)
            else:
                roots.append(item)

        def sort_children(node: dict[str, Any]) -> None:
            children = normalize_json_list(node.get("children"))
            children.sort(
                key=lambda child: (
                    normalize_int(child.get("sort_order"), default=0) or 0,
                    clean_string(child.get("label") or child.get("node_key") or child.get("taxonomy_path")),
                )
            )
            node["children"] = children

            for child in children:
                if isinstance(child, dict):
                    sort_children(child)

        roots.sort(
            key=lambda child: (
                normalize_int(child.get("sort_order"), default=0) or 0,
                clean_string(child.get("label") or child.get("node_key") or child.get("taxonomy_path")),
            )
        )

        for root in roots:
            sort_children(root)

        return {
            "roots": roots,
            "root_count": len(roots),
            "node_count": len(by_uid),
        }

    # ------------------------------------------------------------------
    # User action convenience
    # ------------------------------------------------------------------

    def hide_system_node_for_user(
        self,
        node_ref: Any,
        *,
        user_id: Any = DEFAULT_USER_ID,
        commit: bool = False,
    ) -> Any:
        """Creates/updates a hide override for a system node."""
        node = self.require_node(node_ref)

        if getattr(node, "owner_scope", None) != SOURCE_SCOPE_SYSTEM:
            raise LibraryTaxonomyConflictError("hide_system_node_for_user expects a system node.")

        override, _created = self.upsert_override(
            {
                "target_node_uid": getattr(node, "node_uid", None),
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

    def rename_system_node_for_user(
        self,
        node_ref: Any,
        *,
        label: Any,
        user_id: Any = DEFAULT_USER_ID,
        commit: bool = False,
    ) -> Any:
        """Creates/updates a rename override for a system node."""
        node = self.require_node(node_ref)

        if getattr(node, "owner_scope", None) != SOURCE_SCOPE_SYSTEM:
            raise LibraryTaxonomyConflictError("rename_system_node_for_user expects a system node.")

        override, _created = self.upsert_override(
            {
                "target_node_uid": getattr(node, "node_uid", None),
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
    # Audit
    # ------------------------------------------------------------------

    def create_audit_event(
        self,
        *,
        event_type: Any,
        user_id: Any = None,
        node: Any = None,
        override: Any = None,
        before: Mapping[str, Any] | None = None,
        after: Mapping[str, Any] | None = None,
        diff: Mapping[str, Any] | None = None,
        payload: Mapping[str, Any] | None = None,
        metadata: Mapping[str, Any] | None = None,
        commit: bool = False,
    ) -> Any:
        """Creates a taxonomy audit event."""
        try:
            creator = getattr(self.models.LibraryTaxonomyAuditEvent, "create_event", None)

            if callable(creator):
                event = creator(
                    event_type=event_type,
                    user_id=user_id,
                    node=node,
                    override=override,
                    before=before,
                    after=after,
                    diff=diff,
                    payload=payload,
                    metadata=metadata,
                )
            else:
                event = self.models.LibraryTaxonomyAuditEvent(
                    event_type=clean_string(event_type, fallback="other"),
                    user_id=normalize_user_id(user_id, default=None),
                    node_id=getattr(node, "id", None),
                    override_id=getattr(override, "id", None),
                    payload=normalize_json_mapping(payload),
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
        user_id: Any = None,
        event_type: Any = None,
        node_uid: Any = None,
        target_node_uid: Any = None,
        limit: int = DEFAULT_LIMIT,
        offset: int = 0,
        as_dict: bool = True,
    ) -> list[Any]:
        """Lists taxonomy audit events."""
        model = self.models.LibraryTaxonomyAuditEvent
        query = self.session.query(model)

        normalized_user_id = normalize_user_id(user_id, default=None)
        if normalized_user_id is not None and hasattr(model, "user_id"):
            query = query.filter(model.user_id == normalized_user_id)

        if event_type and hasattr(model, "event_type"):
            query = query.filter(model.event_type == clean_string(event_type))

        if node_uid and hasattr(model, "node_uid"):
            query = query.filter(model.node_uid == optional_string(node_uid))

        if target_node_uid and hasattr(model, "target_node_uid"):
            query = query.filter(model.target_node_uid == optional_string(target_node_uid))

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
            candidate = getattr(self.models, "get_library_taxonomy_models_health", None)
            if callable(candidate):
                model_health = candidate()
        except Exception as exc:
            model_health = {"ok": False, "error": f"{type(exc).__name__}: {exc}"}

        return {
            "schema_version": LIBRARY_TAXONOMY_REPOSITORY_VERSION,
            "ok": True,
            "repository": type(self).__name__,
            "has_session": self._session is not None,
            "uses_default_db_session": self._session is None,
            "models_health": model_health,
            "supports_nodes": True,
            "supports_overrides": True,
            "supports_audit": True,
            "supports_resolved_taxonomy": True,
            "supports_tree_payload": True,
            "supports_user_nodes": True,
            "supports_system_overrides": True,
            "supports_soft_delete": True,
        }

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _with_for_update(self, query: Any) -> Any:
        """Applies FOR UPDATE if supported."""
        try:
            return query.with_for_update()
        except Exception:
            return query

    def _apply_node_sort(self, query: Any, model: type[Any]) -> Any:
        """Applies stable node ordering."""
        order_fields = []

        for field_name in ("depth", "sort_order", "label", "node_key", "id"):
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

    def _fallback_node_kwargs(
        self,
        payload: Mapping[str, Any],
        *,
        source_scope: Any,
        owner_user_id: Any,
    ) -> dict[str, Any]:
        """Builds kwargs if model create_from_payload is unavailable."""
        data = normalize_json_mapping(payload)
        normalized_source_scope = clean_string(source_scope, fallback=SOURCE_SCOPE_USER)
        normalized_owner_user_id = normalize_user_id(owner_user_id, default=None)

        domain = optional_string(data.get("domain"))
        category = optional_string(data.get("category"))
        subcategory = optional_string(data.get("subcategory"))
        taxonomy_path = optional_string(data.get("taxonomy_path")) or taxonomy_path_for(
            domain=domain,
            category=category,
            subcategory=subcategory,
        )

        return {
            "source_scope": normalized_source_scope,
            "owner_user_id": normalized_owner_user_id,
            "owner_scope": owner_scope_for(source_scope=normalized_source_scope, owner_user_id=normalized_owner_user_id),
            "node_type": infer_node_type(
                node_type=data.get("node_type"),
                domain=domain,
                category=category,
                subcategory=subcategory,
                parent_node_id=data.get("parent_node_id"),
            ),
            "parent_node_id": normalize_int(data.get("parent_node_id"), default=None, minimum=1),
            "base_node_uid": optional_string(data.get("base_node_uid")),
            "domain": domain,
            "category": category,
            "subcategory": subcategory,
            "taxonomy_path": taxonomy_path,
            "node_key": optional_string(data.get("node_key") or taxonomy_path),
            "slug": optional_string(data.get("slug")),
            "label": optional_string(data.get("label") or data.get("name")),
            "name": optional_string(data.get("name") or data.get("label")),
            "description": optional_string(data.get("description")),
            "status": clean_string(data.get("status"), fallback=STATUS_ACTIVE),
            "active": normalize_bool(data.get("active"), default=True),
            "visible": normalize_bool(data.get("visible"), default=True),
            "selectable": normalize_bool(data.get("selectable"), default=True),
            "sort_order": normalize_int(data.get("sort_order"), default=0, minimum=0) or 0,
            "payload": data,
            "meta": normalize_json_mapping(data.get("meta")),
            "metadata_json": normalize_json_mapping(data.get("metadata")),
        }

    def _fallback_update_node(self, node: Any, payload: Mapping[str, Any], *, user_id: Any = None) -> None:
        """Updates node when model update_from_payload is unavailable."""
        data = normalize_json_mapping(payload)

        for field_name in (
            "label",
            "name",
            "description",
            "icon",
            "color",
            "sort_order",
            "active",
            "visible",
            "selectable",
            "status",
        ):
            if field_name not in data or not hasattr(node, field_name):
                continue

            if field_name in {"active", "visible", "selectable"}:
                setattr(node, field_name, normalize_bool(data.get(field_name), default=getattr(node, field_name)))
            elif field_name == "sort_order":
                setattr(node, field_name, normalize_int(data.get(field_name), default=getattr(node, field_name, 0), minimum=0) or 0)
            else:
                setattr(node, field_name, normalize_json_value(data.get(field_name)))

        if "payload" in data and hasattr(node, "payload"):
            node.payload = normalize_json_mapping(data.get("payload"))

        if "meta" in data and hasattr(node, "meta"):
            node.meta = normalize_json_mapping(data.get("meta"))

        if ("metadata" in data or "metadata_json" in data) and hasattr(node, "metadata_json"):
            node.metadata_json = normalize_json_mapping(data.get("metadata") or data.get("metadata_json"))

        updater_id = normalize_user_id(user_id, default=None)
        if updater_id is not None and hasattr(node, "updated_by_user_id"):
            node.updated_by_user_id = updater_id

        if hasattr(node, "touch") and callable(node.touch):
            node.touch()

    def _build_override_for_update(
        self,
        payload: Mapping[str, Any],
        *,
        user_id: Any,
        created_by_user_id: Any = None,
    ) -> Any:
        """Builds a temporary override object for update-copy."""
        creator = getattr(self.models.LibraryTaxonomyOverride, "create_from_payload", None)

        if callable(creator):
            return creator(
                payload,
                user_id=user_id,
                created_by_user_id=created_by_user_id,
            )

        return self.models.LibraryTaxonomyOverride(
            user_id=normalize_user_id(user_id, default=DEFAULT_USER_ID),
            target_node_uid=optional_string(payload.get("target_node_uid")),
            override_action=payload.get("override_action") or payload.get("action") or ACTION_PATCH,
            active=normalize_bool(payload.get("active"), default=True),
        )


# ---------------------------------------------------------------------------
# Factory helpers
# ---------------------------------------------------------------------------

def create_library_taxonomy_repository(session: Any | None = None) -> LibraryTaxonomyRepository:
    """Factory for dependency injection."""
    return LibraryTaxonomyRepository(session=session)


@lru_cache(maxsize=1)
def get_repository_version() -> str:
    """Cached repository version helper."""
    return LIBRARY_TAXONOMY_REPOSITORY_VERSION


def clear_library_taxonomy_repository_caches() -> dict[str, Any]:
    """Clears import/static caches."""
    cleared: list[str] = []

    for cached_func in (
        _load_db,
        _load_taxonomy_models_module,
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
    "LIBRARY_TAXONOMY_REPOSITORY_VERSION",
    "DEFAULT_USER_ID",
    "SOURCE_SCOPE_SYSTEM",
    "SOURCE_SCOPE_USER",
    "SOURCE_SCOPE_IMPORTED",
    "SOURCE_SCOPE_GENERATED",
    "NODE_TYPE_DOMAIN",
    "NODE_TYPE_CATEGORY",
    "NODE_TYPE_SUBCATEGORY",
    "STATUS_ACTIVE",
    "STATUS_INACTIVE",
    "STATUS_HIDDEN",
    "STATUS_DELETED",
    "ACTION_HIDE",
    "ACTION_RESTORE",
    "ACTION_RENAME",
    "ACTION_REORDER",
    "ACTION_MOVE",
    "ACTION_PATCH",
    "ACTION_DELETE",

    # Exceptions
    "LibraryTaxonomyRepositoryError",
    "LibraryTaxonomyRepositoryImportError",
    "LibraryTaxonomyNodeNotFoundError",
    "LibraryTaxonomyOverrideNotFoundError",
    "LibraryTaxonomyConflictError",

    # Dataclasses
    "TaxonomyNodeQuery",
    "TaxonomyOverrideQuery",
    "TaxonomyWriteResult",

    # Repository
    "LibraryTaxonomyRepository",
    "create_library_taxonomy_repository",

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
    "taxonomy_path_for",
    "infer_node_type",
    "to_dict_or_payload",
    "get_repository_version",
    "clear_library_taxonomy_repository_caches",
]