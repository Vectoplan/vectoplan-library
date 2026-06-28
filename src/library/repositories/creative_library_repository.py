# services/vectoplan-library/src/library/repositories/creative_library_repository.py
"""
Repository for VECTOPLAN Creative Library published state.

Diese Datei kapselt DB-Zugriffe auf die veröffentlichte Creative Library:

- creative_library_items
- creative_library_revisions
- creative_library_variants
- creative_library_assets
- creative_library_documents
- creative_library_scan_runs
- creative_library_scan_issues
- creative_library_inventory_slots

Ziel:

    src/library/source/*
        -> scan
        -> sync
        -> CreativeLibraryRepository
        -> PostgreSQL published state

Architekturregeln:

- Repository enthält keine Flask-Routes.
- Repository enthält keine UI-Logik.
- Repository enthält keine Source-Datei-Scanner-Logik.
- Repository enthält keine Draft-Generator-Logik.
- Repository erzeugt keine Tabellen.
- Repository führt keine Migration aus.
- Repository führt kein db.create_all() aus.
- Repository öffnet keine aktive DB-Verbindung beim Import.
- DB-Zugriffe laufen nur in expliziten Methoden.
- GET /scan darf dieses Repository nicht schreibend verwenden.
- POST /sync darf dieses Repository schreibend verwenden.
- `vplib_uid` kommt aus Package/Manifest, nicht aus der DB.
- Published Items/Revisions/Variants sind Quelle für die sichtbare System-Library.
- User Collections/Overrides liegen in creative_library_user_repository.py.
- Draft Working State liegt in creative_library_draft_repository.py.
- Technische Namen, JSON-Keys und Variablen bleiben Englisch.

Phase 1:

- user_id darf weiterhin 1 sein.
- Hotbar-Slots bleiben 9.
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

CREATIVE_LIBRARY_REPOSITORY_VERSION: Final[str] = "vectoplan_library.repository.creative_library.v1"

DEFAULT_USER_ID: Final[int] = 1
DEFAULT_HOTBAR_SLOT_COUNT: Final[int] = 9

STATUS_ACTIVE: Final[str] = "active"
STATUS_INACTIVE: Final[str] = "inactive"
STATUS_DELETED: Final[str] = "deleted"
STATUS_DRAFT: Final[str] = "draft"
STATUS_PUBLISHED: Final[str] = "published"
STATUS_REPLACED: Final[str] = "replaced"
STATUS_INVALID: Final[str] = "invalid"

REVISION_STATUS_CURRENT: Final[str] = "current"
REVISION_STATUS_ARCHIVED: Final[str] = "archived"
REVISION_STATUS_SUPERSEDED: Final[str] = "superseded"

SOURCE_SCOPE_SYSTEM: Final[str] = "system"
SOURCE_SCOPE_IMPORTED: Final[str] = "imported"
SOURCE_SCOPE_GENERATED: Final[str] = "generated"
SOURCE_SCOPE_USER: Final[str] = "user"

SCAN_STATUS_STARTED: Final[str] = "started"
SCAN_STATUS_COMPLETED: Final[str] = "completed"
SCAN_STATUS_FAILED: Final[str] = "failed"
SCAN_STATUS_PARTIAL: Final[str] = "partial"

ISSUE_SEVERITY_INFO: Final[str] = "info"
ISSUE_SEVERITY_WARNING: Final[str] = "warning"
ISSUE_SEVERITY_ERROR: Final[str] = "error"
ISSUE_SEVERITY_BLOCKING: Final[str] = "blocking"

ASSET_ROLE_PRIMARY: Final[str] = "primary"
ASSET_ROLE_PREVIEW: Final[str] = "preview"
ASSET_ROLE_RENDER_MODEL: Final[str] = "render_model"
ASSET_ROLE_ATTACHMENT: Final[str] = "attachment"

DOCUMENT_KIND_DOCUMENT: Final[str] = "document"
DOCUMENT_KIND_DATASHEET: Final[str] = "datasheet"
DOCUMENT_KIND_TECHNICAL_DRAWING: Final[str] = "technical_drawing"
DOCUMENT_KIND_MODEL_3D: Final[str] = "model_3d"

DEFAULT_LIMIT: Final[int] = 250
MAX_LIMIT: Final[int] = 5000


# ---------------------------------------------------------------------------
# Exceptions
# ---------------------------------------------------------------------------

class CreativeLibraryRepositoryError(RuntimeError):
    """Base error for CreativeLibraryRepository."""


class CreativeLibraryRepositoryImportError(CreativeLibraryRepositoryError):
    """Raised when db/model imports fail."""


class CreativeLibraryItemNotFoundError(CreativeLibraryRepositoryError):
    """Raised when a published item cannot be found."""


class CreativeLibraryRevisionNotFoundError(CreativeLibraryRepositoryError):
    """Raised when a revision cannot be found."""


class CreativeLibraryVariantNotFoundError(CreativeLibraryRepositoryError):
    """Raised when a variant cannot be found."""


class CreativeLibraryAssetNotFoundError(CreativeLibraryRepositoryError):
    """Raised when an asset cannot be found."""


class CreativeLibraryDocumentNotFoundError(CreativeLibraryRepositoryError):
    """Raised when a document cannot be found."""


class CreativeLibraryScanRunNotFoundError(CreativeLibraryRepositoryError):
    """Raised when a scan run cannot be found."""


class CreativeLibraryConflictError(CreativeLibraryRepositoryError):
    """Raised on conflicting published state operations."""


# ---------------------------------------------------------------------------
# Lazy imports
# ---------------------------------------------------------------------------

@lru_cache(maxsize=1)
def _load_db() -> Any:
    """Loads SQLAlchemy extension defensively."""
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

    raise CreativeLibraryRepositoryImportError(
        "Could not import SQLAlchemy extension `db`. "
        + " | ".join(errors)
    )


@lru_cache(maxsize=1)
def _load_models_module() -> ModuleType:
    """Loads models.creative_library defensively."""
    errors: list[str] = []

    for module_name in (
        "models.creative_library",
        "src.models.creative_library",
        "vectoplan_library.models.creative_library",
    ):
        try:
            return importlib.import_module(module_name)
        except Exception as exc:
            errors.append(f"{module_name}: {type(exc).__name__}: {exc}")

    raise CreativeLibraryRepositoryImportError(
        "Could not import creative_library models. "
        + " | ".join(errors)
    )


def _db() -> Any:
    return _load_db()


def _models() -> ModuleType:
    return _load_models_module()


# ---------------------------------------------------------------------------
# Generic helpers
# ---------------------------------------------------------------------------

def clean_string(value: Any, *, fallback: str = "") -> str:
    try:
        if value is None:
            return fallback
        text = str(value).replace("\x00", "").strip()
        return text if text else fallback
    except Exception:
        return fallback


def optional_string(value: Any, *, max_length: int | None = None) -> str | None:
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


def normalize_bool(value: Any, *, default: bool = False) -> bool:
    if isinstance(value, bool):
        return value

    if value is None:
        return default

    text = clean_string(value).lower()

    if text in {"1", "true", "yes", "y", "ja", "on", "enabled", "active", "published", "visible", "current"}:
        return True

    if text in {"0", "false", "no", "n", "nein", "off", "disabled", "inactive", "deleted", "hidden"}:
        return False

    return default


def normalize_json_mapping(value: Mapping[str, Any] | None) -> dict[str, Any]:
    if value is None:
        return {}

    if not isinstance(value, Mapping):
        return {"value": normalize_json_value(value)}

    return {str(key): normalize_json_value(child_value) for key, child_value in value.items()}


def normalize_json_list(value: Iterable[Any] | None) -> list[Any]:
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
    if value is None:
        return default

    if hasattr(value, "value"):
        try:
            text = str(value.value).strip()
            return text or default
        except Exception:
            return default

    return clean_string(value, fallback=default)


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
        "item_uid",
        "family_uid",
        "revision_uid",
        "variant_uid",
        "asset_uid",
        "document_uid",
        "scan_run_uid",
        "issue_uid",
        "inventory_slot_uid",
        "vplib_uid",
        "family_id",
        "package_id",
        "variant_id",
        "revision_number",
        "version",
        "status",
        "source_scope",
        "source_path",
        "classification_path",
        "domain",
        "category",
        "subcategory",
        "object_kind",
        "label",
        "name",
        "title",
        "description",
        "sort_order",
        "active",
        "visible",
        "created_at",
        "updated_at",
        "published_at",
    ):
        try:
            if hasattr(value, field_name):
                result[field_name] = normalize_json_value(getattr(value, field_name))
        except Exception:
            continue

    return result


def new_model_with_attrs(model_class: type[Any], attrs: Mapping[str, Any]) -> Any:
    obj = model_class()
    for key, value in attrs.items():
        try:
            if hasattr(obj, key):
                setattr(obj, key, value)
        except Exception:
            continue
    return obj


def ref_is_numeric(value: Any) -> bool:
    text = clean_string(value)
    return bool(text and text.isdigit())


def identity_from_payload(payload: Mapping[str, Any] | Any) -> dict[str, Any]:
    if isinstance(payload, Mapping):
        data = normalize_json_mapping(payload)
        getter = data.get
    else:
        getter = lambda key, default=None: getattr(payload, key, default)

    return {
        "id": normalize_int(getter("id"), default=None, minimum=1),
        "item_id": normalize_int(getter("item_id"), default=None, minimum=1),
        "item_uid": optional_string(getter("item_uid") or getter("family_uid")),
        "vplib_uid": optional_string(getter("vplib_uid")),
        "family_id": optional_string(getter("family_id")),
        "package_id": optional_string(getter("package_id")),
        "source_path": optional_string(getter("source_path")),
        "classification_path": optional_string(getter("classification_path")),
    }


def first_non_empty(*values: Any) -> Any:
    for value in values:
        if value is None:
            continue
        if isinstance(value, str) and not value.strip():
            continue
        return value
    return None


# ---------------------------------------------------------------------------
# Dataclasses
# ---------------------------------------------------------------------------

@dataclass(slots=True)
class ItemQuery:
    """Structured query for published creative-library items."""

    item_uid: str | None = None
    vplib_uid: str | None = None
    family_id: str | None = None
    package_id: str | None = None
    source_path: str | None = None
    classification_path: str | None = None
    domain: str | None = None
    category: str | None = None
    subcategory: str | None = None
    object_kind: str | None = None
    status: str | None = None
    source_scope: str | None = None
    active_only: bool = True
    visible_only: bool = False
    include_deleted: bool = False
    limit: int = DEFAULT_LIMIT
    offset: int = 0

    @classmethod
    def from_payload(cls, payload: Mapping[str, Any] | None = None, **kwargs: Any) -> "ItemQuery":
        data = normalize_json_mapping(payload)
        data.update({key: value for key, value in kwargs.items() if value is not None})

        return cls(
            item_uid=optional_string(data.get("item_uid") or data.get("family_uid")),
            vplib_uid=optional_string(data.get("vplib_uid")),
            family_id=optional_string(data.get("family_id")),
            package_id=optional_string(data.get("package_id")),
            source_path=optional_string(data.get("source_path")),
            classification_path=optional_string(data.get("classification_path")),
            domain=optional_string(data.get("domain")),
            category=optional_string(data.get("category")),
            subcategory=optional_string(data.get("subcategory")),
            object_kind=optional_string(data.get("object_kind")),
            status=optional_string(data.get("status")),
            source_scope=optional_string(data.get("source_scope")),
            active_only=normalize_bool(data.get("active_only"), default=True),
            visible_only=normalize_bool(data.get("visible_only"), default=False),
            include_deleted=normalize_bool(data.get("include_deleted"), default=False),
            limit=normalize_int(data.get("limit"), default=DEFAULT_LIMIT, minimum=1, maximum=MAX_LIMIT) or DEFAULT_LIMIT,
            offset=normalize_int(data.get("offset"), default=0, minimum=0) or 0,
        )


@dataclass(slots=True)
class RevisionQuery:
    """Structured query for revisions."""

    item_id: int | None = None
    item_uid: str | None = None
    revision_uid: str | None = None
    status: str | None = None
    version: str | None = None
    current_only: bool = False
    active_only: bool = True
    include_deleted: bool = False
    limit: int = DEFAULT_LIMIT
    offset: int = 0

    @classmethod
    def from_payload(cls, payload: Mapping[str, Any] | None = None, **kwargs: Any) -> "RevisionQuery":
        data = normalize_json_mapping(payload)
        data.update({key: value for key, value in kwargs.items() if value is not None})

        return cls(
            item_id=normalize_int(data.get("item_id"), default=None, minimum=1),
            item_uid=optional_string(data.get("item_uid") or data.get("family_uid")),
            revision_uid=optional_string(data.get("revision_uid")),
            status=optional_string(data.get("status")),
            version=optional_string(data.get("version") or data.get("package_version")),
            current_only=normalize_bool(data.get("current_only"), default=False),
            active_only=normalize_bool(data.get("active_only"), default=True),
            include_deleted=normalize_bool(data.get("include_deleted"), default=False),
            limit=normalize_int(data.get("limit"), default=DEFAULT_LIMIT, minimum=1, maximum=MAX_LIMIT) or DEFAULT_LIMIT,
            offset=normalize_int(data.get("offset"), default=0, minimum=0) or 0,
        )


@dataclass(slots=True)
class VariantQuery:
    """Structured query for variants."""

    item_id: int | None = None
    revision_id: int | None = None
    item_uid: str | None = None
    revision_uid: str | None = None
    variant_uid: str | None = None
    variant_id: str | None = None
    status: str | None = None
    active_only: bool = True
    include_deleted: bool = False
    limit: int = MAX_LIMIT
    offset: int = 0

    @classmethod
    def from_payload(cls, payload: Mapping[str, Any] | None = None, **kwargs: Any) -> "VariantQuery":
        data = normalize_json_mapping(payload)
        data.update({key: value for key, value in kwargs.items() if value is not None})

        return cls(
            item_id=normalize_int(data.get("item_id"), default=None, minimum=1),
            revision_id=normalize_int(data.get("revision_id"), default=None, minimum=1),
            item_uid=optional_string(data.get("item_uid")),
            revision_uid=optional_string(data.get("revision_uid")),
            variant_uid=optional_string(data.get("variant_uid")),
            variant_id=optional_string(data.get("variant_id")),
            status=optional_string(data.get("status")),
            active_only=normalize_bool(data.get("active_only"), default=True),
            include_deleted=normalize_bool(data.get("include_deleted"), default=False),
            limit=normalize_int(data.get("limit"), default=MAX_LIMIT, minimum=1, maximum=MAX_LIMIT) or MAX_LIMIT,
            offset=normalize_int(data.get("offset"), default=0, minimum=0) or 0,
        )


@dataclass(slots=True)
class ChildQuery:
    """Structured query for assets/documents."""

    item_id: int | None = None
    revision_id: int | None = None
    variant_id_db: int | None = None
    item_uid: str | None = None
    revision_uid: str | None = None
    variant_uid: str | None = None
    role: str | None = None
    document_type: str | None = None
    document_kind: str | None = None
    field_key: str | None = None
    status: str | None = None
    active_only: bool = True
    include_deleted: bool = False
    limit: int = MAX_LIMIT
    offset: int = 0

    @classmethod
    def from_payload(cls, payload: Mapping[str, Any] | None = None, **kwargs: Any) -> "ChildQuery":
        data = normalize_json_mapping(payload)
        data.update({key: value for key, value in kwargs.items() if value is not None})

        return cls(
            item_id=normalize_int(data.get("item_id"), default=None, minimum=1),
            revision_id=normalize_int(data.get("revision_id"), default=None, minimum=1),
            variant_id_db=normalize_int(data.get("variant_id_db") or data.get("variant_db_id"), default=None, minimum=1),
            item_uid=optional_string(data.get("item_uid")),
            revision_uid=optional_string(data.get("revision_uid")),
            variant_uid=optional_string(data.get("variant_uid")),
            role=optional_string(data.get("role")),
            document_type=optional_string(data.get("document_type")),
            document_kind=optional_string(data.get("document_kind")),
            field_key=optional_string(data.get("field_key")),
            status=optional_string(data.get("status")),
            active_only=normalize_bool(data.get("active_only"), default=True),
            include_deleted=normalize_bool(data.get("include_deleted"), default=False),
            limit=normalize_int(data.get("limit"), default=MAX_LIMIT, minimum=1, maximum=MAX_LIMIT) or MAX_LIMIT,
            offset=normalize_int(data.get("offset"), default=0, minimum=0) or 0,
        )


@dataclass(slots=True)
class ScanRunQuery:
    """Structured query for scan runs."""

    scan_run_uid: str | None = None
    status: str | None = None
    source_root: str | None = None
    limit: int = DEFAULT_LIMIT
    offset: int = 0

    @classmethod
    def from_payload(cls, payload: Mapping[str, Any] | None = None, **kwargs: Any) -> "ScanRunQuery":
        data = normalize_json_mapping(payload)
        data.update({key: value for key, value in kwargs.items() if value is not None})

        return cls(
            scan_run_uid=optional_string(data.get("scan_run_uid")),
            status=optional_string(data.get("status")),
            source_root=optional_string(data.get("source_root")),
            limit=normalize_int(data.get("limit"), default=DEFAULT_LIMIT, minimum=1, maximum=MAX_LIMIT) or DEFAULT_LIMIT,
            offset=normalize_int(data.get("offset"), default=0, minimum=0) or 0,
        )


@dataclass(slots=True)
class RepositoryWriteResult:
    """JSON-compatible write result."""

    ok: bool
    action: str
    item_id: int | None = None
    revision_id: int | None = None
    variant_id: int | None = None
    asset_id: int | None = None
    document_id: int | None = None
    scan_run_id: int | None = None
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
            "schema_version": CREATIVE_LIBRARY_REPOSITORY_VERSION,
            "ok": self.ok,
            "action": self.action,
            "item_id": self.item_id,
            "revision_id": self.revision_id,
            "variant_id": self.variant_id,
            "asset_id": self.asset_id,
            "document_id": self.document_id,
            "scan_run_id": self.scan_run_id,
            "created": self.created,
            "updated": self.updated,
            "deleted": self.deleted,
            "payload": normalize_json_mapping(self.payload),
            "errors": list(self.errors),
        }


# ---------------------------------------------------------------------------
# Repository
# ---------------------------------------------------------------------------

class CreativeLibraryRepository:
    """
    SQLAlchemy repository for published Creative Library state.

    Commit strategy:
        - Methods accept commit=False by default.
        - commit=False performs flush where IDs are required.
        - commit=True commits and rolls back on errors.
    """

    def __init__(self, session: Any | None = None) -> None:
        self._session = session

    # ------------------------------------------------------------------
    # Session / models
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
    # Item reads
    # ------------------------------------------------------------------

    def get_item_by_id(self, item_id: Any, *, include_deleted: bool = False, for_update: bool = False) -> Any | None:
        normalized_id = normalize_int(item_id, default=None, minimum=1)
        if normalized_id is None:
            return None

        model = self.models.CreativeLibraryItem
        query = self.session.query(model).filter(model.id == normalized_id)

        if not include_deleted and hasattr(model, "status"):
            query = query.filter(model.status != STATUS_DELETED)

        if for_update:
            query = self._with_for_update(query)

        return query.one_or_none()

    def get_item_by_uid(self, item_uid: Any, *, include_deleted: bool = False, for_update: bool = False) -> Any | None:
        uid = optional_string(item_uid)
        if not uid:
            return None

        model = self.models.CreativeLibraryItem
        query = self.session.query(model)

        for column_name in ("item_uid", "family_uid"):
            if hasattr(model, column_name):
                query = query.filter(getattr(model, column_name) == uid)
                break
        else:
            return None

        if not include_deleted and hasattr(model, "status"):
            query = query.filter(model.status != STATUS_DELETED)

        if for_update:
            query = self._with_for_update(query)

        return query.one_or_none()

    def get_item_by_vplib_uid(self, vplib_uid: Any, *, include_deleted: bool = False, for_update: bool = False) -> Any | None:
        uid = optional_string(vplib_uid)
        if not uid:
            return None

        model = self.models.CreativeLibraryItem
        if not hasattr(model, "vplib_uid"):
            return None

        query = self.session.query(model).filter(model.vplib_uid == uid)

        if not include_deleted and hasattr(model, "status"):
            query = query.filter(model.status != STATUS_DELETED)

        if for_update:
            query = self._with_for_update(query)

        return query.one_or_none()

    def get_item_by_family_id(self, family_id: Any, *, include_deleted: bool = False, for_update: bool = False) -> Any | None:
        value = optional_string(family_id)
        if not value:
            return None

        model = self.models.CreativeLibraryItem
        if not hasattr(model, "family_id"):
            return None

        query = self.session.query(model).filter(model.family_id == value)

        if not include_deleted and hasattr(model, "status"):
            query = query.filter(model.status != STATUS_DELETED)

        if for_update:
            query = self._with_for_update(query)

        return query.one_or_none()

    def get_item_by_source_path(self, source_path: Any, *, include_deleted: bool = False, for_update: bool = False) -> Any | None:
        value = optional_string(source_path)
        if not value:
            return None

        model = self.models.CreativeLibraryItem
        if not hasattr(model, "source_path"):
            return None

        query = self.session.query(model).filter(model.source_path == value)

        if not include_deleted and hasattr(model, "status"):
            query = query.filter(model.status != STATUS_DELETED)

        if for_update:
            query = self._with_for_update(query)

        return query.one_or_none()

    def get_item(self, item_ref: Any, *, include_deleted: bool = False, for_update: bool = False) -> Any | None:
        text = clean_string(item_ref)
        if not text:
            return None

        if ref_is_numeric(text):
            return self.get_item_by_id(text, include_deleted=include_deleted, for_update=for_update)

        for getter in (
            self.get_item_by_uid,
            self.get_item_by_vplib_uid,
            self.get_item_by_family_id,
            self.get_item_by_source_path,
        ):
            item = getter(text, include_deleted=include_deleted, for_update=for_update)
            if item is not None:
                return item

        return None

    def require_item(self, item_ref: Any, *, include_deleted: bool = False, for_update: bool = False) -> Any:
        item = self.get_item(item_ref, include_deleted=include_deleted, for_update=for_update)
        if item is None:
            raise CreativeLibraryItemNotFoundError(f"Creative Library item {item_ref!r} was not found.")
        return item

    def list_items(
        self,
        *,
        query: ItemQuery | Mapping[str, Any] | None = None,
        as_dict: bool = False,
        include_current_revision: bool = False,
    ) -> list[Any]:
        item_query = query if isinstance(query, ItemQuery) else ItemQuery.from_payload(query)
        model = self.models.CreativeLibraryItem
        db_query = self.session.query(model)

        for field_name in (
            "item_uid",
            "vplib_uid",
            "family_id",
            "package_id",
            "source_path",
            "classification_path",
            "domain",
            "category",
            "subcategory",
            "object_kind",
            "status",
            "source_scope",
        ):
            value = getattr(item_query, field_name)
            if value is not None and hasattr(model, field_name):
                db_query = db_query.filter(getattr(model, field_name) == value)

        if item_query.active_only and hasattr(model, "active"):
            db_query = db_query.filter(model.active.is_(True))

        if item_query.visible_only and hasattr(model, "visible"):
            db_query = db_query.filter(model.visible.is_(True))

        if not item_query.include_deleted and hasattr(model, "status"):
            db_query = db_query.filter(model.status != STATUS_DELETED)

        db_query = self._apply_item_sort(db_query, model)

        if item_query.offset:
            db_query = db_query.offset(item_query.offset)

        if item_query.limit:
            db_query = db_query.limit(item_query.limit)

        values = db_query.all()

        if as_dict:
            return [
                self.get_item_payload(value, include_current_revision=include_current_revision)
                for value in values
            ]

        return values

    def list_item_payloads(
        self,
        *,
        query: ItemQuery | Mapping[str, Any] | None = None,
        include_current_revision: bool = False,
    ) -> list[dict[str, Any]]:
        return self.list_items(query=query, as_dict=True, include_current_revision=include_current_revision)

    # ------------------------------------------------------------------
    # Item writes
    # ------------------------------------------------------------------

    def create_item(
        self,
        payload: Mapping[str, Any],
        *,
        commit: bool = False,
    ) -> Any:
        data = normalize_json_mapping(payload)

        try:
            creator = getattr(self.models.CreativeLibraryItem, "create_from_payload", None)

            if callable(creator):
                item = creator(data)
            else:
                item = new_model_with_attrs(
                    self.models.CreativeLibraryItem,
                    self._fallback_item_attrs(data),
                )

            self.session.add(item)
            self._finish_write(commit=commit)
            return item

        except Exception:
            if commit:
                self.rollback()
            raise

    def update_item(
        self,
        item_ref: Any,
        payload: Mapping[str, Any],
        *,
        commit: bool = False,
    ) -> Any:
        data = normalize_json_mapping(payload)

        try:
            item = self.require_item(item_ref, include_deleted=True, for_update=True)

            updater = getattr(item, "update_from_payload", None)
            if callable(updater):
                item = updater(data) or item
            else:
                self._fallback_update_item(item, data)

            self._finish_write(commit=commit)
            return item

        except Exception:
            if commit:
                self.rollback()
            raise

    def upsert_item(
        self,
        payload: Mapping[str, Any],
        *,
        commit: bool = False,
    ) -> tuple[Any, bool]:
        """Upserts published item by vplib_uid, family_id, item_uid or source_path."""
        data = normalize_json_mapping(payload)

        try:
            item = self.find_item_by_identity(data, include_deleted=True, for_update=True)
            created = item is None

            if created:
                item = self.create_item(data, commit=False)
            else:
                self._fallback_update_item(item, data)

            self._finish_write(commit=commit)
            return item, created

        except Exception:
            if commit:
                self.rollback()
            raise

    def soft_delete_item(self, item_ref: Any, *, commit: bool = False) -> bool:
        try:
            item = self.require_item(item_ref, include_deleted=True, for_update=True)

            if hasattr(item, "mark_deleted") and callable(item.mark_deleted):
                item.mark_deleted()
            else:
                if hasattr(item, "status"):
                    item.status = STATUS_DELETED
                if hasattr(item, "active"):
                    item.active = False
                if hasattr(item, "visible"):
                    item.visible = False
                if hasattr(item, "touch") and callable(item.touch):
                    item.touch()

            self._finish_write(commit=commit)
            return True

        except Exception:
            if commit:
                self.rollback()
            raise

    def find_item_by_identity(
        self,
        payload: Mapping[str, Any],
        *,
        include_deleted: bool = False,
        for_update: bool = False,
    ) -> Any | None:
        identity = identity_from_payload(payload)

        for key in ("id", "item_id"):
            value = identity.get(key)
            if value:
                item = self.get_item_by_id(value, include_deleted=include_deleted, for_update=for_update)
                if item is not None:
                    return item

        for key, getter in (
            ("item_uid", self.get_item_by_uid),
            ("vplib_uid", self.get_item_by_vplib_uid),
            ("family_id", self.get_item_by_family_id),
            ("source_path", self.get_item_by_source_path),
        ):
            value = identity.get(key)
            if value:
                item = getter(value, include_deleted=include_deleted, for_update=for_update)
                if item is not None:
                    return item

        package_id = identity.get("package_id")
        if package_id:
            model = self.models.CreativeLibraryItem
            if hasattr(model, "package_id"):
                query = self.session.query(model).filter(model.package_id == package_id)
                if not include_deleted and hasattr(model, "status"):
                    query = query.filter(model.status != STATUS_DELETED)
                if for_update:
                    query = self._with_for_update(query)
                return query.one_or_none()

        return None

    # ------------------------------------------------------------------
    # Revision reads / writes
    # ------------------------------------------------------------------

    def get_revision_by_id(self, revision_id: Any, *, include_deleted: bool = False, for_update: bool = False) -> Any | None:
        normalized_id = normalize_int(revision_id, default=None, minimum=1)
        if normalized_id is None:
            return None

        model = self.models.CreativeLibraryRevision
        query = self.session.query(model).filter(model.id == normalized_id)

        if not include_deleted and hasattr(model, "status"):
            query = query.filter(model.status != STATUS_DELETED)

        if for_update:
            query = self._with_for_update(query)

        return query.one_or_none()

    def get_revision_by_uid(self, revision_uid: Any, *, include_deleted: bool = False, for_update: bool = False) -> Any | None:
        uid = optional_string(revision_uid)
        if not uid:
            return None

        model = self.models.CreativeLibraryRevision
        query = self.session.query(model)

        for column_name in ("revision_uid",):
            if hasattr(model, column_name):
                query = query.filter(getattr(model, column_name) == uid)
                break
        else:
            return None

        if not include_deleted and hasattr(model, "status"):
            query = query.filter(model.status != STATUS_DELETED)

        if for_update:
            query = self._with_for_update(query)

        return query.one_or_none()

    def get_revision(self, revision_ref: Any, *, include_deleted: bool = False, for_update: bool = False) -> Any | None:
        if ref_is_numeric(revision_ref):
            return self.get_revision_by_id(revision_ref, include_deleted=include_deleted, for_update=for_update)
        return self.get_revision_by_uid(revision_ref, include_deleted=include_deleted, for_update=for_update)

    def require_revision(self, revision_ref: Any, *, include_deleted: bool = False, for_update: bool = False) -> Any:
        revision = self.get_revision(revision_ref, include_deleted=include_deleted, for_update=for_update)
        if revision is None:
            raise CreativeLibraryRevisionNotFoundError(f"Creative Library revision {revision_ref!r} was not found.")
        return revision

    def get_current_revision(self, item_ref: Any, *, include_deleted: bool = False) -> Any | None:
        item = self.get_item(item_ref, include_deleted=include_deleted)
        if item is None:
            return None

        model = self.models.CreativeLibraryRevision
        query = self.session.query(model)

        if hasattr(model, "item_id"):
            query = query.filter(model.item_id == item.id)
        else:
            return None

        if hasattr(model, "is_current"):
            query = query.filter(model.is_current.is_(True))
        elif hasattr(model, "status"):
            query = query.filter(model.status.in_((REVISION_STATUS_CURRENT, STATUS_PUBLISHED, STATUS_ACTIVE)))

        if not include_deleted and hasattr(model, "status"):
            query = query.filter(model.status != STATUS_DELETED)

        query = self._apply_revision_sort(query, model)
        return query.first()

    def list_revisions(
        self,
        *,
        query: RevisionQuery | Mapping[str, Any] | None = None,
        as_dict: bool = False,
    ) -> list[Any]:
        revision_query = query if isinstance(query, RevisionQuery) else RevisionQuery.from_payload(query)
        model = self.models.CreativeLibraryRevision
        db_query = self.session.query(model)

        item_id = revision_query.item_id
        if item_id is None and revision_query.item_uid:
            item = self.get_item_by_uid(revision_query.item_uid)
            item_id = getattr(item, "id", None) if item is not None else None
            if item_id is None:
                return []

        if item_id is not None and hasattr(model, "item_id"):
            db_query = db_query.filter(model.item_id == item_id)

        for field_name in ("revision_uid", "status", "version"):
            value = getattr(revision_query, field_name)
            if value is not None and hasattr(model, field_name):
                db_query = db_query.filter(getattr(model, field_name) == value)

        if revision_query.current_only and hasattr(model, "is_current"):
            db_query = db_query.filter(model.is_current.is_(True))

        if revision_query.active_only and hasattr(model, "active"):
            db_query = db_query.filter(model.active.is_(True))

        if not revision_query.include_deleted and hasattr(model, "status"):
            db_query = db_query.filter(model.status != STATUS_DELETED)

        db_query = self._apply_revision_sort(db_query, model)

        if revision_query.offset:
            db_query = db_query.offset(revision_query.offset)

        if revision_query.limit:
            db_query = db_query.limit(revision_query.limit)

        values = db_query.all()

        if as_dict:
            return [to_dict_or_payload(value) for value in values]

        return values

    def create_revision(
        self,
        item_ref: Any,
        payload: Mapping[str, Any],
        *,
        mark_current: bool = True,
        commit: bool = False,
    ) -> Any:
        data = normalize_json_mapping(payload)

        try:
            item = self.require_item(item_ref, include_deleted=True, for_update=True)

            if mark_current:
                self._unset_current_revisions(item.id)

            creator = getattr(self.models.CreativeLibraryRevision, "create_from_payload", None)
            if callable(creator):
                revision = creator(data, item=item)
            else:
                revision = new_model_with_attrs(
                    self.models.CreativeLibraryRevision,
                    self._fallback_revision_attrs(data, item=item, mark_current=mark_current),
                )

            self.session.add(revision)
            self.session.flush()

            if hasattr(item, "current_revision_id"):
                item.current_revision_id = getattr(revision, "id", None)

            if hasattr(item, "status") and getattr(item, "status", None) in {None, STATUS_DRAFT, STATUS_INVALID}:
                item.status = STATUS_PUBLISHED

            if hasattr(item, "touch") and callable(item.touch):
                item.touch()

            self._finish_write(commit=commit)
            return revision

        except Exception:
            if commit:
                self.rollback()
            raise

    def update_revision(self, revision_ref: Any, payload: Mapping[str, Any], *, commit: bool = False) -> Any:
        data = normalize_json_mapping(payload)

        try:
            revision = self.require_revision(revision_ref, include_deleted=True, for_update=True)
            self._fallback_update_child(revision, data)
            self._finish_write(commit=commit)
            return revision

        except Exception:
            if commit:
                self.rollback()
            raise

    def set_current_revision(self, revision_ref: Any, *, commit: bool = False) -> Any:
        try:
            revision = self.require_revision(revision_ref, include_deleted=True, for_update=True)
            item_id = getattr(revision, "item_id", None)

            if item_id is None:
                raise CreativeLibraryConflictError("Revision has no item_id.")

            self._unset_current_revisions(item_id)

            if hasattr(revision, "is_current"):
                revision.is_current = True
            if hasattr(revision, "status"):
                revision.status = REVISION_STATUS_CURRENT

            item = self.get_item_by_id(item_id, include_deleted=True, for_update=True)
            if item is not None and hasattr(item, "current_revision_id"):
                item.current_revision_id = getattr(revision, "id", None)

            self._finish_write(commit=commit)
            return revision

        except Exception:
            if commit:
                self.rollback()
            raise

    # ------------------------------------------------------------------
    # Variants
    # ------------------------------------------------------------------

    def get_variant_by_id(self, variant_db_id: Any, *, include_deleted: bool = False, for_update: bool = False) -> Any | None:
        return self._get_child_by_id(self.models.CreativeLibraryVariant, variant_db_id, include_deleted=include_deleted, for_update=for_update)

    def get_variant_by_uid(self, variant_uid: Any, *, include_deleted: bool = False, for_update: bool = False) -> Any | None:
        return self._get_child_by_uid(self.models.CreativeLibraryVariant, variant_uid, ("variant_uid",), include_deleted=include_deleted, for_update=for_update)

    def get_variant(self, variant_ref: Any, *, include_deleted: bool = False, for_update: bool = False) -> Any | None:
        if ref_is_numeric(variant_ref):
            return self.get_variant_by_id(variant_ref, include_deleted=include_deleted, for_update=for_update)
        return self.get_variant_by_uid(variant_ref, include_deleted=include_deleted, for_update=for_update)

    def require_variant(self, variant_ref: Any, *, include_deleted: bool = False, for_update: bool = False) -> Any:
        variant = self.get_variant(variant_ref, include_deleted=include_deleted, for_update=for_update)
        if variant is None:
            raise CreativeLibraryVariantNotFoundError(f"Creative Library variant {variant_ref!r} was not found.")
        return variant

    def list_variants(
        self,
        *,
        query: VariantQuery | Mapping[str, Any] | None = None,
        as_dict: bool = False,
    ) -> list[Any]:
        variant_query = query if isinstance(query, VariantQuery) else VariantQuery.from_payload(query)
        model = self.models.CreativeLibraryVariant
        db_query = self.session.query(model)

        item_id, revision_id = self._resolve_item_revision_ids(
            item_id=variant_query.item_id,
            revision_id=variant_query.revision_id,
            item_uid=variant_query.item_uid,
            revision_uid=variant_query.revision_uid,
        )

        if item_id is not None and hasattr(model, "item_id"):
            db_query = db_query.filter(model.item_id == item_id)

        if revision_id is not None and hasattr(model, "revision_id"):
            db_query = db_query.filter(model.revision_id == revision_id)

        for field_name in ("variant_uid", "variant_id", "status"):
            value = getattr(variant_query, field_name)
            if value is not None and hasattr(model, field_name):
                db_query = db_query.filter(getattr(model, field_name) == value)

        if variant_query.active_only and hasattr(model, "active"):
            db_query = db_query.filter(model.active.is_(True))

        if not variant_query.include_deleted and hasattr(model, "status"):
            db_query = db_query.filter(model.status != STATUS_DELETED)

        db_query = self._apply_child_sort(db_query, model)

        if variant_query.offset:
            db_query = db_query.offset(variant_query.offset)

        if variant_query.limit:
            db_query = db_query.limit(variant_query.limit)

        values = db_query.all()

        if as_dict:
            return [to_dict_or_payload(value) for value in values]

        return values

    def create_variant(self, payload: Mapping[str, Any], *, item_ref: Any = None, revision_ref: Any = None, commit: bool = False) -> Any:
        data = normalize_json_mapping(payload)

        try:
            item, revision = self._resolve_item_revision_for_write(data, item_ref=item_ref, revision_ref=revision_ref)

            creator = getattr(self.models.CreativeLibraryVariant, "create_from_payload", None)
            if callable(creator):
                variant = creator(data, item=item, revision=revision)
            else:
                variant = new_model_with_attrs(
                    self.models.CreativeLibraryVariant,
                    self._fallback_variant_attrs(data, item=item, revision=revision),
                )

            self.session.add(variant)
            self._finish_write(commit=commit)
            return variant

        except Exception:
            if commit:
                self.rollback()
            raise

    def upsert_variant(self, payload: Mapping[str, Any], *, item_ref: Any = None, revision_ref: Any = None, commit: bool = False) -> tuple[Any, bool]:
        data = normalize_json_mapping(payload)

        try:
            item, revision = self._resolve_item_revision_for_write(data, item_ref=item_ref, revision_ref=revision_ref)
            variant = self._find_variant_for_upsert(data, item=item, revision=revision, for_update=True)
            created = variant is None

            if created:
                variant = self.create_variant(data, item_ref=getattr(item, "id", None), revision_ref=getattr(revision, "id", None) if revision else None, commit=False)
            else:
                self._fallback_update_child(variant, data)

            self._finish_write(commit=commit)
            return variant, created

        except Exception:
            if commit:
                self.rollback()
            raise

    # ------------------------------------------------------------------
    # Assets / Documents
    # ------------------------------------------------------------------

    def get_asset(self, asset_ref: Any, *, include_deleted: bool = False, for_update: bool = False) -> Any | None:
        if ref_is_numeric(asset_ref):
            return self._get_child_by_id(self.models.CreativeLibraryAsset, asset_ref, include_deleted=include_deleted, for_update=for_update)
        return self._get_child_by_uid(self.models.CreativeLibraryAsset, asset_ref, ("asset_uid",), include_deleted=include_deleted, for_update=for_update)

    def require_asset(self, asset_ref: Any, *, include_deleted: bool = False, for_update: bool = False) -> Any:
        asset = self.get_asset(asset_ref, include_deleted=include_deleted, for_update=for_update)
        if asset is None:
            raise CreativeLibraryAssetNotFoundError(f"Creative Library asset {asset_ref!r} was not found.")
        return asset

    def get_document(self, document_ref: Any, *, include_deleted: bool = False, for_update: bool = False) -> Any | None:
        if ref_is_numeric(document_ref):
            return self._get_child_by_id(self.models.CreativeLibraryDocument, document_ref, include_deleted=include_deleted, for_update=for_update)
        return self._get_child_by_uid(self.models.CreativeLibraryDocument, document_ref, ("document_uid",), include_deleted=include_deleted, for_update=for_update)

    def require_document(self, document_ref: Any, *, include_deleted: bool = False, for_update: bool = False) -> Any:
        document = self.get_document(document_ref, include_deleted=include_deleted, for_update=for_update)
        if document is None:
            raise CreativeLibraryDocumentNotFoundError(f"Creative Library document {document_ref!r} was not found.")
        return document

    def list_assets(self, *, query: ChildQuery | Mapping[str, Any] | None = None, as_dict: bool = False) -> list[Any]:
        return self._list_children(self.models.CreativeLibraryAsset, query=query, as_dict=as_dict)

    def list_documents(self, *, query: ChildQuery | Mapping[str, Any] | None = None, as_dict: bool = False) -> list[Any]:
        return self._list_children(self.models.CreativeLibraryDocument, query=query, as_dict=as_dict)

    def create_asset(self, payload: Mapping[str, Any], *, item_ref: Any = None, revision_ref: Any = None, variant_ref: Any = None, commit: bool = False) -> Any:
        return self._create_child(
            model_class=self.models.CreativeLibraryAsset,
            child_kind="asset",
            payload=payload,
            item_ref=item_ref,
            revision_ref=revision_ref,
            variant_ref=variant_ref,
            commit=commit,
        )

    def create_document(self, payload: Mapping[str, Any], *, item_ref: Any = None, revision_ref: Any = None, variant_ref: Any = None, commit: bool = False) -> Any:
        return self._create_child(
            model_class=self.models.CreativeLibraryDocument,
            child_kind="document",
            payload=payload,
            item_ref=item_ref,
            revision_ref=revision_ref,
            variant_ref=variant_ref,
            commit=commit,
        )

    def update_asset(self, asset_ref: Any, payload: Mapping[str, Any], *, commit: bool = False) -> Any:
        return self._update_child_ref(self.require_asset, asset_ref, payload, commit=commit)

    def update_document(self, document_ref: Any, payload: Mapping[str, Any], *, commit: bool = False) -> Any:
        return self._update_child_ref(self.require_document, document_ref, payload, commit=commit)

    def soft_delete_asset(self, asset_ref: Any, *, commit: bool = False) -> bool:
        return self._soft_delete_child_ref(self.require_asset, asset_ref, commit=commit)

    def soft_delete_document(self, document_ref: Any, *, commit: bool = False) -> bool:
        return self._soft_delete_child_ref(self.require_document, document_ref, commit=commit)

    # ------------------------------------------------------------------
    # Scan runs / issues
    # ------------------------------------------------------------------

    def get_scan_run_by_id(self, scan_run_id: Any, *, for_update: bool = False) -> Any | None:
        normalized_id = normalize_int(scan_run_id, default=None, minimum=1)
        if normalized_id is None:
            return None

        model = self.models.CreativeLibraryScanRun
        query = self.session.query(model).filter(model.id == normalized_id)

        if for_update:
            query = self._with_for_update(query)

        return query.one_or_none()

    def get_scan_run_by_uid(self, scan_run_uid: Any, *, for_update: bool = False) -> Any | None:
        uid = optional_string(scan_run_uid)
        if not uid:
            return None

        model = self.models.CreativeLibraryScanRun
        if not hasattr(model, "scan_run_uid"):
            return None

        query = self.session.query(model).filter(model.scan_run_uid == uid)

        if for_update:
            query = self._with_for_update(query)

        return query.one_or_none()

    def get_scan_run(self, scan_run_ref: Any, *, for_update: bool = False) -> Any | None:
        if ref_is_numeric(scan_run_ref):
            return self.get_scan_run_by_id(scan_run_ref, for_update=for_update)
        return self.get_scan_run_by_uid(scan_run_ref, for_update=for_update)

    def require_scan_run(self, scan_run_ref: Any, *, for_update: bool = False) -> Any:
        scan_run = self.get_scan_run(scan_run_ref, for_update=for_update)
        if scan_run is None:
            raise CreativeLibraryScanRunNotFoundError(f"Creative Library scan run {scan_run_ref!r} was not found.")
        return scan_run

    def list_scan_runs(self, *, query: ScanRunQuery | Mapping[str, Any] | None = None, as_dict: bool = False) -> list[Any]:
        scan_query = query if isinstance(query, ScanRunQuery) else ScanRunQuery.from_payload(query)
        model = self.models.CreativeLibraryScanRun
        db_query = self.session.query(model)

        for field_name in ("scan_run_uid", "status", "source_root"):
            value = getattr(scan_query, field_name)
            if value is not None and hasattr(model, field_name):
                db_query = db_query.filter(getattr(model, field_name) == value)

        if hasattr(model, "started_at"):
            db_query = db_query.order_by(model.started_at.desc())
        elif hasattr(model, "created_at"):
            db_query = db_query.order_by(model.created_at.desc())
        else:
            db_query = db_query.order_by(model.id.desc())

        if scan_query.offset:
            db_query = db_query.offset(scan_query.offset)

        if scan_query.limit:
            db_query = db_query.limit(scan_query.limit)

        values = db_query.all()

        if as_dict:
            return [to_dict_or_payload(value) for value in values]

        return values

    def start_scan_run(self, payload: Mapping[str, Any] | None = None, *, commit: bool = False) -> Any:
        data = normalize_json_mapping(payload)

        try:
            creator = getattr(self.models.CreativeLibraryScanRun, "create_from_payload", None)
            if callable(creator):
                scan_run = creator({**data, "status": data.get("status") or SCAN_STATUS_STARTED})
            else:
                scan_run = new_model_with_attrs(
                    self.models.CreativeLibraryScanRun,
                    {
                        "status": data.get("status") or SCAN_STATUS_STARTED,
                        "source_root": optional_string(data.get("source_root")),
                        "started_at": data.get("started_at"),
                        "payload": data,
                        "meta": normalize_json_mapping(data.get("meta")),
                    },
                )

            self.session.add(scan_run)
            self._finish_write(commit=commit)
            return scan_run

        except Exception:
            if commit:
                self.rollback()
            raise

    def finish_scan_run(
        self,
        scan_run_ref: Any,
        *,
        status: Any = SCAN_STATUS_COMPLETED,
        counters: Mapping[str, Any] | None = None,
        errors: Iterable[Any] | None = None,
        commit: bool = False,
    ) -> Any:
        try:
            scan_run = self.require_scan_run(scan_run_ref, for_update=True)
            counter_payload = normalize_json_mapping(counters)
            errors_payload = normalize_json_list(errors)

            if hasattr(scan_run, "finish") and callable(scan_run.finish):
                try:
                    scan_run.finish(status=status, counters=counter_payload, errors=errors_payload)
                except TypeError:
                    scan_run.finish(status)
            else:
                if hasattr(scan_run, "status"):
                    scan_run.status = clean_string(status, fallback=SCAN_STATUS_COMPLETED)
                for key, value in counter_payload.items():
                    if hasattr(scan_run, key):
                        setattr(scan_run, key, normalize_int(value, default=0, minimum=0))
                if hasattr(scan_run, "error_payload"):
                    scan_run.error_payload = errors_payload
                if hasattr(scan_run, "payload"):
                    payload = normalize_json_mapping(getattr(scan_run, "payload", None))
                    payload["counters"] = counter_payload
                    payload["errors"] = errors_payload
                    scan_run.payload = payload
                if hasattr(scan_run, "touch") and callable(scan_run.touch):
                    scan_run.touch()

            self._finish_write(commit=commit)
            return scan_run

        except Exception:
            if commit:
                self.rollback()
            raise

    def record_scan_issue(self, scan_run_ref: Any, payload: Mapping[str, Any], *, commit: bool = False) -> Any:
        data = normalize_json_mapping(payload)

        try:
            scan_run = self.require_scan_run(scan_run_ref, for_update=False)
            model = self.models.CreativeLibraryScanIssue

            creator = getattr(model, "create_from_payload", None)
            if callable(creator):
                issue = creator(data, scan_run=scan_run)
            else:
                issue = new_model_with_attrs(
                    model,
                    {
                        "scan_run_id": getattr(scan_run, "id", None),
                        "severity": data.get("severity") or ISSUE_SEVERITY_ERROR,
                        "code": data.get("code"),
                        "message": data.get("message"),
                        "source_path": data.get("source_path"),
                        "field_path": data.get("field_path") or data.get("path"),
                        "payload": data,
                        "details_json": normalize_json_mapping(data.get("details")),
                    },
                )

            self.session.add(issue)
            self._finish_write(commit=commit)
            return issue

        except Exception:
            if commit:
                self.rollback()
            raise

    def list_scan_issues(self, scan_run_ref: Any | None = None, *, severity: Any = None, as_dict: bool = True, limit: int = DEFAULT_LIMIT) -> list[Any]:
        model = self.models.CreativeLibraryScanIssue
        query = self.session.query(model)

        if scan_run_ref is not None:
            scan_run = self.require_scan_run(scan_run_ref)
            if hasattr(model, "scan_run_id"):
                query = query.filter(model.scan_run_id == scan_run.id)

        normalized_severity = optional_string(severity)
        if normalized_severity and hasattr(model, "severity"):
            query = query.filter(model.severity == normalized_severity)

        if hasattr(model, "created_at"):
            query = query.order_by(model.created_at.desc())
        else:
            query = query.order_by(model.id.desc())

        query = query.limit(normalize_int(limit, default=DEFAULT_LIMIT, minimum=1, maximum=MAX_LIMIT) or DEFAULT_LIMIT)

        values = query.all()

        if as_dict:
            return [to_dict_or_payload(value) for value in values]

        return values

    # ------------------------------------------------------------------
    # Inventory slots
    # ------------------------------------------------------------------

    def list_inventory_slots(self, *, user_id: Any = DEFAULT_USER_ID, as_dict: bool = True) -> list[Any]:
        model = self.models.CreativeLibraryInventorySlot
        normalized_user_id = normalize_int(user_id, default=DEFAULT_USER_ID, minimum=1) or DEFAULT_USER_ID
        query = self.session.query(model)

        if hasattr(model, "user_id"):
            query = query.filter(model.user_id == normalized_user_id)

        if hasattr(model, "slot_index"):
            query = query.order_by(model.slot_index.asc())
        else:
            query = query.order_by(model.id.asc())

        values = query.all()

        if as_dict:
            return [to_dict_or_payload(value) for value in values]

        return values

    def get_inventory_slot(self, *, user_id: Any = DEFAULT_USER_ID, slot_index: Any) -> Any | None:
        model = self.models.CreativeLibraryInventorySlot
        normalized_user_id = normalize_int(user_id, default=DEFAULT_USER_ID, minimum=1) or DEFAULT_USER_ID
        normalized_slot = normalize_int(slot_index, default=None, minimum=0, maximum=DEFAULT_HOTBAR_SLOT_COUNT - 1)

        if normalized_slot is None:
            return None

        query = self.session.query(model)

        if hasattr(model, "user_id"):
            query = query.filter(model.user_id == normalized_user_id)

        if hasattr(model, "slot_index"):
            query = query.filter(model.slot_index == normalized_slot)
        else:
            return None

        return query.one_or_none()

    def set_inventory_slot(
        self,
        *,
        user_id: Any = DEFAULT_USER_ID,
        slot_index: Any,
        item_ref: Any = None,
        variant_ref: Any = None,
        payload: Mapping[str, Any] | None = None,
        commit: bool = False,
    ) -> Any:
        data = normalize_json_mapping(payload)
        normalized_user_id = normalize_int(user_id, default=DEFAULT_USER_ID, minimum=1) or DEFAULT_USER_ID
        normalized_slot = normalize_int(slot_index, default=None, minimum=0, maximum=DEFAULT_HOTBAR_SLOT_COUNT - 1)

        if normalized_slot is None:
            raise ValueError("slot_index must be between 0 and 8.")

        try:
            slot = self.get_inventory_slot(user_id=normalized_user_id, slot_index=normalized_slot)
            item = self.get_item(item_ref) if item_ref is not None else None
            variant = self.get_variant(variant_ref) if variant_ref is not None else None

            if slot is None:
                slot = new_model_with_attrs(
                    self.models.CreativeLibraryInventorySlot,
                    {
                        "user_id": normalized_user_id,
                        "slot_index": normalized_slot,
                    },
                )
                self.session.add(slot)

            attrs = {
                "item_id": getattr(item, "id", None),
                "variant_id": getattr(variant, "id", None),
                "vplib_uid": getattr(item, "vplib_uid", None) or data.get("vplib_uid"),
                "family_id": getattr(item, "family_id", None) or data.get("family_id"),
                "variant_key": getattr(variant, "variant_id", None) or data.get("variant_id"),
                "label": data.get("label"),
                "payload": data,
                "active": True,
                "visible": True,
                "status": STATUS_ACTIVE,
            }
            for key, value in attrs.items():
                if hasattr(slot, key):
                    setattr(slot, key, value)

            self._finish_write(commit=commit)
            return slot

        except Exception:
            if commit:
                self.rollback()
            raise

    def clear_inventory_slot(self, *, user_id: Any = DEFAULT_USER_ID, slot_index: Any, commit: bool = False) -> bool:
        try:
            slot = self.get_inventory_slot(user_id=user_id, slot_index=slot_index)
            if slot is None:
                return False

            for key, value in (
                ("item_id", None),
                ("variant_id", None),
                ("vplib_uid", None),
                ("family_id", None),
                ("variant_key", None),
                ("label", None),
                ("payload", {}),
                ("active", False),
                ("visible", False),
                ("status", STATUS_INACTIVE),
            ):
                if hasattr(slot, key):
                    setattr(slot, key, value)

            self._finish_write(commit=commit)
            return True

        except Exception:
            if commit:
                self.rollback()
            raise

    # ------------------------------------------------------------------
    # Aggregate payloads
    # ------------------------------------------------------------------

    def get_item_payload(
        self,
        item_ref: Any,
        *,
        include_current_revision: bool = False,
        include_revisions: bool = False,
        include_variants: bool = False,
        include_assets: bool = False,
        include_documents: bool = False,
    ) -> dict[str, Any]:
        item = item_ref if not isinstance(item_ref, (str, int)) else self.require_item(item_ref, include_deleted=True)
        payload = to_dict_or_payload(item)

        item_id = getattr(item, "id", None)

        if include_current_revision:
            payload["current_revision"] = to_dict_or_payload(self.get_current_revision(item_id, include_deleted=True))

        if include_revisions:
            payload["revisions"] = self.list_revisions(query={"item_id": item_id, "include_deleted": True}, as_dict=True)

        if include_variants:
            payload["variants"] = self.list_variants(query={"item_id": item_id, "include_deleted": True}, as_dict=True)

        if include_assets:
            payload["assets"] = self.list_assets(query={"item_id": item_id, "include_deleted": True}, as_dict=True)

        if include_documents:
            payload["documents"] = self.list_documents(query={"item_id": item_id, "include_deleted": True}, as_dict=True)

        return payload

    def get_library_payload(
        self,
        *,
        query: ItemQuery | Mapping[str, Any] | None = None,
        include_current_revision: bool = True,
        include_variants: bool = False,
        include_assets: bool = False,
        include_documents: bool = False,
    ) -> dict[str, Any]:
        items = self.list_items(query=query, as_dict=False)
        item_payloads = [
            self.get_item_payload(
                item,
                include_current_revision=include_current_revision,
                include_variants=include_variants,
                include_assets=include_assets,
                include_documents=include_documents,
            )
            for item in items
        ]

        return {
            "schema_version": CREATIVE_LIBRARY_REPOSITORY_VERSION,
            "published": True,
            "item_count": len(item_payloads),
            "items": item_payloads,
        }

    # ------------------------------------------------------------------
    # Health
    # ------------------------------------------------------------------

    def get_health(self) -> dict[str, Any]:
        model_health = {}

        try:
            candidate = getattr(self.models, "get_creative_library_models_health", None)
            if callable(candidate):
                model_health = candidate()
        except Exception as exc:
            model_health = {"ok": False, "error": f"{type(exc).__name__}: {exc}"}

        return {
            "schema_version": CREATIVE_LIBRARY_REPOSITORY_VERSION,
            "ok": True,
            "repository": type(self).__name__,
            "has_session": self._session is not None,
            "uses_default_db_session": self._session is None,
            "models_health": model_health,
            "supports_items": True,
            "supports_revisions": True,
            "supports_variants": True,
            "supports_assets": True,
            "supports_documents": True,
            "supports_scan_runs": True,
            "supports_scan_issues": True,
            "supports_inventory_slots": True,
            "supports_upsert": True,
            "supports_soft_delete": True,
            "vplib_uid_created_by_database": False,
        }

    # ------------------------------------------------------------------
    # Internal generic helpers
    # ------------------------------------------------------------------

    def _with_for_update(self, query: Any) -> Any:
        try:
            return query.with_for_update()
        except Exception:
            return query

    def _get_child_by_id(self, model: type[Any], child_id: Any, *, include_deleted: bool = False, for_update: bool = False) -> Any | None:
        normalized_id = normalize_int(child_id, default=None, minimum=1)
        if normalized_id is None:
            return None

        query = self.session.query(model).filter(model.id == normalized_id)

        if not include_deleted and hasattr(model, "status"):
            query = query.filter(model.status != STATUS_DELETED)

        if for_update:
            query = self._with_for_update(query)

        return query.one_or_none()

    def _get_child_by_uid(
        self,
        model: type[Any],
        uid: Any,
        uid_columns: Sequence[str],
        *,
        include_deleted: bool = False,
        for_update: bool = False,
    ) -> Any | None:
        normalized_uid = optional_string(uid)
        if not normalized_uid:
            return None

        query = self.session.query(model)

        for column_name in uid_columns:
            if hasattr(model, column_name):
                query = query.filter(getattr(model, column_name) == normalized_uid)
                break
        else:
            return None

        if not include_deleted and hasattr(model, "status"):
            query = query.filter(model.status != STATUS_DELETED)

        if for_update:
            query = self._with_for_update(query)

        return query.one_or_none()

    def _list_children(self, model: type[Any], *, query: ChildQuery | Mapping[str, Any] | None = None, as_dict: bool = False) -> list[Any]:
        child_query = query if isinstance(query, ChildQuery) else ChildQuery.from_payload(query)
        db_query = self.session.query(model)

        item_id, revision_id = self._resolve_item_revision_ids(
            item_id=child_query.item_id,
            revision_id=child_query.revision_id,
            item_uid=child_query.item_uid,
            revision_uid=child_query.revision_uid,
        )

        variant_id_db = child_query.variant_id_db
        if variant_id_db is None and child_query.variant_uid:
            variant = self.get_variant_by_uid(child_query.variant_uid)
            variant_id_db = getattr(variant, "id", None) if variant is not None else None
            if variant_id_db is None:
                return []

        for field_name, value in (
            ("item_id", item_id),
            ("revision_id", revision_id),
            ("variant_id", variant_id_db),
            ("role", child_query.role),
            ("document_type", child_query.document_type),
            ("document_kind", child_query.document_kind),
            ("field_key", child_query.field_key),
            ("status", child_query.status),
        ):
            if value is not None and hasattr(model, field_name):
                db_query = db_query.filter(getattr(model, field_name) == value)

        if child_query.active_only and hasattr(model, "active"):
            db_query = db_query.filter(model.active.is_(True))

        if not child_query.include_deleted and hasattr(model, "status"):
            db_query = db_query.filter(model.status != STATUS_DELETED)

        db_query = self._apply_child_sort(db_query, model)

        if child_query.offset:
            db_query = db_query.offset(child_query.offset)

        if child_query.limit:
            db_query = db_query.limit(child_query.limit)

        values = db_query.all()

        if as_dict:
            return [to_dict_or_payload(value) for value in values]

        return values

    def _create_child(
        self,
        *,
        model_class: type[Any],
        child_kind: str,
        payload: Mapping[str, Any],
        item_ref: Any = None,
        revision_ref: Any = None,
        variant_ref: Any = None,
        commit: bool = False,
    ) -> Any:
        data = normalize_json_mapping(payload)

        try:
            item, revision = self._resolve_item_revision_for_write(data, item_ref=item_ref, revision_ref=revision_ref)
            variant = self.get_variant(variant_ref) if variant_ref is not None else None

            creator = getattr(model_class, "create_from_payload", None)
            if callable(creator):
                child = creator(data, item=item, revision=revision, variant=variant)
            else:
                attrs = self._fallback_child_attrs(child_kind, data, item=item, revision=revision, variant=variant)
                child = new_model_with_attrs(model_class, attrs)

            self.session.add(child)
            self._finish_write(commit=commit)
            return child

        except Exception:
            if commit:
                self.rollback()
            raise

    def _update_child_ref(self, getter: Any, child_ref: Any, payload: Mapping[str, Any], *, commit: bool = False) -> Any:
        data = normalize_json_mapping(payload)

        try:
            child = getter(child_ref, include_deleted=True, for_update=True)
            self._fallback_update_child(child, data)
            self._finish_write(commit=commit)
            return child

        except Exception:
            if commit:
                self.rollback()
            raise

    def _soft_delete_child_ref(self, getter: Any, child_ref: Any, *, commit: bool = False) -> bool:
        try:
            child = getter(child_ref, include_deleted=True, for_update=True)
            self._mark_deleted(child)
            self._finish_write(commit=commit)
            return True

        except Exception:
            if commit:
                self.rollback()
            raise

    def _resolve_item_revision_ids(
        self,
        *,
        item_id: Any = None,
        revision_id: Any = None,
        item_uid: Any = None,
        revision_uid: Any = None,
    ) -> tuple[int | None, int | None]:
        resolved_item_id = normalize_int(item_id, default=None, minimum=1)
        resolved_revision_id = normalize_int(revision_id, default=None, minimum=1)

        if resolved_item_id is None and item_uid:
            item = self.get_item_by_uid(item_uid)
            resolved_item_id = getattr(item, "id", None) if item is not None else None
            if resolved_item_id is None:
                return None, None

        if resolved_revision_id is None and revision_uid:
            revision = self.get_revision_by_uid(revision_uid)
            resolved_revision_id = getattr(revision, "id", None) if revision is not None else None
            if resolved_revision_id is None:
                return resolved_item_id, None

        return resolved_item_id, resolved_revision_id

    def _resolve_item_revision_for_write(self, data: Mapping[str, Any], *, item_ref: Any = None, revision_ref: Any = None) -> tuple[Any, Any | None]:
        item_ref_value = first_non_empty(item_ref, data.get("item_id"), data.get("item_uid"), data.get("vplib_uid"), data.get("family_id"))
        item = self.require_item(item_ref_value, include_deleted=True)

        revision = None
        revision_ref_value = first_non_empty(revision_ref, data.get("revision_id"), data.get("revision_uid"))

        if revision_ref_value is not None:
            revision = self.require_revision(revision_ref_value, include_deleted=True)
        elif data.get("use_current_revision") or data.get("current_revision"):
            revision = self.get_current_revision(getattr(item, "id", None), include_deleted=True)

        return item, revision

    def _unset_current_revisions(self, item_id: int) -> None:
        model = self.models.CreativeLibraryRevision
        if not hasattr(model, "item_id"):
            return

        query = self.session.query(model).filter(model.item_id == item_id)

        if hasattr(model, "is_current"):
            query = query.filter(model.is_current.is_(True))

        for revision in query.all():
            if hasattr(revision, "is_current"):
                revision.is_current = False
            if hasattr(revision, "status") and getattr(revision, "status", None) == REVISION_STATUS_CURRENT:
                revision.status = REVISION_STATUS_ARCHIVED

    def _find_variant_for_upsert(self, data: Mapping[str, Any], *, item: Any, revision: Any | None = None, for_update: bool = False) -> Any | None:
        model = self.models.CreativeLibraryVariant
        query = self.session.query(model)

        if hasattr(model, "item_id"):
            query = query.filter(model.item_id == getattr(item, "id", None))

        if revision is not None and hasattr(model, "revision_id"):
            query = query.filter(model.revision_id == getattr(revision, "id", None))

        variant_uid = optional_string(data.get("variant_uid"))
        variant_id = optional_string(data.get("variant_id") or data.get("variant_key"))

        if variant_uid and hasattr(model, "variant_uid"):
            query = query.filter(model.variant_uid == variant_uid)
        elif variant_id and hasattr(model, "variant_id"):
            query = query.filter(model.variant_id == variant_id)
        else:
            return None

        if for_update:
            query = self._with_for_update(query)

        return query.one_or_none()

    def _mark_deleted(self, obj: Any) -> None:
        if hasattr(obj, "mark_deleted") and callable(obj.mark_deleted):
            try:
                obj.mark_deleted()
                return
            except Exception:
                pass

        if hasattr(obj, "status"):
            obj.status = STATUS_DELETED
        if hasattr(obj, "active"):
            obj.active = False
        if hasattr(obj, "visible"):
            obj.visible = False
        if hasattr(obj, "touch") and callable(obj.touch):
            obj.touch()

    # ------------------------------------------------------------------
    # Sorting
    # ------------------------------------------------------------------

    def _apply_item_sort(self, query: Any, model: type[Any]) -> Any:
        return self._apply_sort(query, model, ("sort_order", "label", "name", "family_id", "id"))

    def _apply_revision_sort(self, query: Any, model: type[Any]) -> Any:
        order_fields = []

        for field_name, descending in (
            ("is_current", True),
            ("revision_number", True),
            ("published_at", True),
            ("created_at", True),
            ("id", True),
        ):
            column = getattr(model, field_name, None)
            if column is not None:
                try:
                    order_fields.append(column.desc() if descending else column.asc())
                except Exception:
                    pass

        if order_fields:
            try:
                return query.order_by(*order_fields)
            except Exception:
                return query

        return query

    def _apply_child_sort(self, query: Any, model: type[Any]) -> Any:
        return self._apply_sort(query, model, ("sort_order", "variant_id", "role", "field_key", "id"))

    def _apply_sort(self, query: Any, model: type[Any], fields: Sequence[str]) -> Any:
        order_fields = []

        for field_name in fields:
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

    # ------------------------------------------------------------------
    # Fallback attrs
    # ------------------------------------------------------------------

    def _fallback_item_attrs(self, data: Mapping[str, Any]) -> dict[str, Any]:
        return {
            "vplib_uid": optional_string(data.get("vplib_uid")),
            "family_id": optional_string(data.get("family_id")),
            "package_id": optional_string(data.get("package_id")),
            "source_scope": optional_string(data.get("source_scope")) or SOURCE_SCOPE_SYSTEM,
            "source_path": optional_string(data.get("source_path")),
            "classification_path": optional_string(data.get("classification_path")),
            "domain": optional_string(data.get("domain")),
            "category": optional_string(data.get("category")),
            "subcategory": optional_string(data.get("subcategory")),
            "object_kind": optional_string(data.get("object_kind")),
            "label": optional_string(data.get("label") or data.get("name") or data.get("title")),
            "name": optional_string(data.get("name") or data.get("label") or data.get("title")),
            "title": optional_string(data.get("title") or data.get("label") or data.get("name")),
            "description": optional_string(data.get("description")),
            "status": optional_string(data.get("status")) or STATUS_ACTIVE,
            "active": normalize_bool(data.get("active"), default=True),
            "visible": normalize_bool(data.get("visible"), default=True),
            "sort_order": normalize_int(data.get("sort_order"), default=0, minimum=0) or 0,
            "manifest_payload": normalize_json_mapping(data.get("manifest_payload") or data.get("manifest")),
            "classification_payload": normalize_json_mapping(data.get("classification_payload") or data.get("classification")),
            "payload": normalize_json_mapping(data.get("payload") or data),
            "meta": normalize_json_mapping(data.get("meta")),
            "metadata_json": normalize_json_mapping(data.get("metadata")),
        }

    def _fallback_update_item(self, item: Any, data: Mapping[str, Any]) -> None:
        for field_name in (
            "vplib_uid",
            "family_id",
            "package_id",
            "source_scope",
            "source_path",
            "classification_path",
            "domain",
            "category",
            "subcategory",
            "object_kind",
            "label",
            "name",
            "title",
            "description",
            "status",
        ):
            if field_name in data and hasattr(item, field_name):
                setattr(item, field_name, optional_string(data.get(field_name)))

        for field_name in ("active", "visible"):
            if field_name in data and hasattr(item, field_name):
                setattr(item, field_name, normalize_bool(data.get(field_name), default=getattr(item, field_name)))

        if "sort_order" in data and hasattr(item, "sort_order"):
            item.sort_order = normalize_int(data.get("sort_order"), default=getattr(item, "sort_order", 0), minimum=0) or 0

        for field_name in ("manifest_payload", "classification_payload", "payload", "meta", "metadata_json"):
            source_names = {
                "manifest_payload": ("manifest_payload", "manifest"),
                "classification_payload": ("classification_payload", "classification"),
                "metadata_json": ("metadata_json", "metadata"),
            }.get(field_name, (field_name,))
            for source_name in source_names:
                if source_name in data and hasattr(item, field_name):
                    setattr(item, field_name, normalize_json_mapping(data.get(source_name)))
                    break

        if hasattr(item, "touch") and callable(item.touch):
            item.touch()

    def _fallback_revision_attrs(self, data: Mapping[str, Any], *, item: Any, mark_current: bool) -> dict[str, Any]:
        return {
            "item_id": getattr(item, "id", None),
            "revision_number": normalize_int(data.get("revision_number"), default=None, minimum=1),
            "version": optional_string(data.get("version") or data.get("package_version")),
            "status": REVISION_STATUS_CURRENT if mark_current else optional_string(data.get("status")) or STATUS_PUBLISHED,
            "is_current": mark_current,
            "source_path": optional_string(data.get("source_path") or getattr(item, "source_path", None)),
            "scan_run_id": normalize_int(data.get("scan_run_id"), default=None, minimum=1),
            "manifest_payload": normalize_json_mapping(data.get("manifest_payload") or data.get("manifest")),
            "modules_payload": normalize_json_mapping(data.get("modules_payload") or data.get("modules")),
            "family_payload": normalize_json_mapping(data.get("family_payload") or data.get("family")),
            "classification_payload": normalize_json_mapping(data.get("classification_payload") or data.get("classification")),
            "document_bundle": normalize_json_mapping(data.get("document_bundle")),
            "payload": normalize_json_mapping(data.get("payload") or data),
            "meta": normalize_json_mapping(data.get("meta")),
            "metadata_json": normalize_json_mapping(data.get("metadata")),
            "active": normalize_bool(data.get("active"), default=True),
        }

    def _fallback_variant_attrs(self, data: Mapping[str, Any], *, item: Any, revision: Any | None = None) -> dict[str, Any]:
        return {
            "item_id": getattr(item, "id", None),
            "revision_id": getattr(revision, "id", None),
            "variant_id": optional_string(data.get("variant_id") or data.get("variant_key")) or "default",
            "label": optional_string(data.get("label") or data.get("name")) or optional_string(data.get("variant_id")) or "Default",
            "description": optional_string(data.get("description")),
            "status": optional_string(data.get("status")) or STATUS_ACTIVE,
            "sort_order": normalize_int(data.get("sort_order"), default=0, minimum=0) or 0,
            "definition_values_json": normalize_json_mapping(data.get("definition_values") or data.get("definition_values_json")),
            "summary_json": normalize_json_mapping(data.get("summary") or data.get("summary_json")),
            "payload": normalize_json_mapping(data.get("payload") or data),
            "meta": normalize_json_mapping(data.get("meta")),
            "metadata_json": normalize_json_mapping(data.get("metadata")),
            "active": normalize_bool(data.get("active"), default=True),
            "visible": normalize_bool(data.get("visible"), default=True),
        }

    def _fallback_child_attrs(self, child_kind: str, data: Mapping[str, Any], *, item: Any, revision: Any | None, variant: Any | None) -> dict[str, Any]:
        attrs = {
            "item_id": getattr(item, "id", None),
            "revision_id": getattr(revision, "id", None),
            "variant_id": getattr(variant, "id", None),
            "status": optional_string(data.get("status")) or STATUS_ACTIVE,
            "role": optional_string(data.get("role")),
            "field_key": optional_string(data.get("field_key")),
            "sort_order": normalize_int(data.get("sort_order"), default=0, minimum=0) or 0,
            "library_file_id": normalize_int(data.get("library_file_id"), default=None, minimum=1),
            "file_version_id": normalize_int(data.get("file_version_id"), default=None, minimum=1),
            "file_uid": optional_string(data.get("file_uid")),
            "filename": optional_string(data.get("filename") or data.get("original_filename")),
            "mime_type": optional_string(data.get("mime_type") or data.get("content_type")),
            "size_bytes": normalize_int(data.get("size_bytes"), default=None, minimum=0),
            "sha256": optional_string(data.get("sha256")),
            "storage_path": optional_string(data.get("storage_path")),
            "source_path": optional_string(data.get("source_path")),
            "url": optional_string(data.get("url")),
            "payload": normalize_json_mapping(data.get("payload") or data),
            "meta": normalize_json_mapping(data.get("meta")),
            "metadata_json": normalize_json_mapping(data.get("metadata")),
            "active": normalize_bool(data.get("active"), default=True),
            "visible": normalize_bool(data.get("visible"), default=True),
        }

        if child_kind == "asset":
            attrs.update(
                {
                    "asset_kind": optional_string(data.get("asset_kind")),
                    "role": optional_string(data.get("role")) or ASSET_ROLE_ATTACHMENT,
                }
            )
        elif child_kind == "document":
            attrs.update(
                {
                    "document_kind": optional_string(data.get("document_kind")) or DOCUMENT_KIND_DOCUMENT,
                    "document_type": optional_string(data.get("document_type")),
                    "title": optional_string(data.get("title") or data.get("label")),
                }
            )

        return attrs

    def _fallback_update_child(self, child: Any, data: Mapping[str, Any]) -> None:
        for field_name in (
            "status",
            "role",
            "field_key",
            "variant_id",
            "variant_key",
            "label",
            "name",
            "title",
            "description",
            "asset_kind",
            "document_kind",
            "document_type",
            "file_uid",
            "filename",
            "mime_type",
            "sha256",
            "storage_path",
            "source_path",
            "url",
            "version",
        ):
            if field_name in data and hasattr(child, field_name):
                setattr(child, field_name, optional_string(data.get(field_name)))

        for field_name in ("sort_order", "library_file_id", "file_version_id", "size_bytes", "revision_number"):
            if field_name in data and hasattr(child, field_name):
                setattr(child, field_name, normalize_int(data.get(field_name), default=None, minimum=0))

        for field_name in ("active", "visible", "is_current"):
            if field_name in data and hasattr(child, field_name):
                setattr(child, field_name, normalize_bool(data.get(field_name), default=getattr(child, field_name)))

        for field_name in (
            "definition_values_json",
            "summary_json",
            "manifest_payload",
            "modules_payload",
            "family_payload",
            "classification_payload",
            "document_bundle",
            "payload",
            "meta",
            "metadata_json",
        ):
            source_names = {
                "definition_values_json": ("definition_values", "definition_values_json"),
                "summary_json": ("summary", "summary_json"),
                "manifest_payload": ("manifest", "manifest_payload"),
                "modules_payload": ("modules", "modules_payload"),
                "family_payload": ("family", "family_payload"),
                "classification_payload": ("classification", "classification_payload"),
                "metadata_json": ("metadata", "metadata_json"),
            }.get(field_name, (field_name,))

            for source_name in source_names:
                if source_name in data and hasattr(child, field_name):
                    setattr(child, field_name, normalize_json_mapping(data.get(source_name)))
                    break

        if hasattr(child, "touch") and callable(child.touch):
            child.touch()


# ---------------------------------------------------------------------------
# Factory helpers
# ---------------------------------------------------------------------------

def create_creative_library_repository(session: Any | None = None) -> CreativeLibraryRepository:
    """Factory for dependency injection."""
    return CreativeLibraryRepository(session=session)


@lru_cache(maxsize=1)
def get_repository_version() -> str:
    return CREATIVE_LIBRARY_REPOSITORY_VERSION


def clear_creative_library_repository_caches() -> dict[str, Any]:
    """Clears import/static caches."""
    cleared: list[str] = []

    for cached_func in (
        _load_db,
        _load_models_module,
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
    "CREATIVE_LIBRARY_REPOSITORY_VERSION",
    "DEFAULT_USER_ID",
    "DEFAULT_HOTBAR_SLOT_COUNT",
    "STATUS_ACTIVE",
    "STATUS_INACTIVE",
    "STATUS_DELETED",
    "STATUS_DRAFT",
    "STATUS_PUBLISHED",
    "STATUS_REPLACED",
    "STATUS_INVALID",
    "REVISION_STATUS_CURRENT",
    "REVISION_STATUS_ARCHIVED",
    "REVISION_STATUS_SUPERSEDED",
    "SOURCE_SCOPE_SYSTEM",
    "SOURCE_SCOPE_IMPORTED",
    "SOURCE_SCOPE_GENERATED",
    "SOURCE_SCOPE_USER",
    "SCAN_STATUS_STARTED",
    "SCAN_STATUS_COMPLETED",
    "SCAN_STATUS_FAILED",
    "SCAN_STATUS_PARTIAL",
    "ISSUE_SEVERITY_INFO",
    "ISSUE_SEVERITY_WARNING",
    "ISSUE_SEVERITY_ERROR",
    "ISSUE_SEVERITY_BLOCKING",
    "ASSET_ROLE_PRIMARY",
    "ASSET_ROLE_PREVIEW",
    "ASSET_ROLE_RENDER_MODEL",
    "ASSET_ROLE_ATTACHMENT",
    "DOCUMENT_KIND_DOCUMENT",
    "DOCUMENT_KIND_DATASHEET",
    "DOCUMENT_KIND_TECHNICAL_DRAWING",
    "DOCUMENT_KIND_MODEL_3D",

    # Exceptions
    "CreativeLibraryRepositoryError",
    "CreativeLibraryRepositoryImportError",
    "CreativeLibraryItemNotFoundError",
    "CreativeLibraryRevisionNotFoundError",
    "CreativeLibraryVariantNotFoundError",
    "CreativeLibraryAssetNotFoundError",
    "CreativeLibraryDocumentNotFoundError",
    "CreativeLibraryScanRunNotFoundError",
    "CreativeLibraryConflictError",

    # Dataclasses
    "ItemQuery",
    "RevisionQuery",
    "VariantQuery",
    "ChildQuery",
    "ScanRunQuery",
    "RepositoryWriteResult",

    # Repository
    "CreativeLibraryRepository",
    "create_creative_library_repository",

    # Helpers
    "clean_string",
    "optional_string",
    "normalize_int",
    "normalize_bool",
    "normalize_json_mapping",
    "normalize_json_list",
    "normalize_json_value",
    "enum_value",
    "to_dict_or_payload",
    "new_model_with_attrs",
    "identity_from_payload",
    "first_non_empty",
    "get_repository_version",
    "clear_creative_library_repository_caches",
]