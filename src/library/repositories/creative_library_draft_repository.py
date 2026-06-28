# services/vectoplan-library/src/library/repositories/creative_library_draft_repository.py
"""
Repository for VECTOPLAN Creative Library Drafts.

Diese Datei kapselt alle DB-Zugriffe auf:

- creative_library_drafts
- creative_library_draft_variants
- creative_library_draft_assets
- creative_library_draft_documents
- creative_library_draft_validation_issues
- creative_library_draft_audit_events

Ziel:

    Generator / Create Flow / Edit Flow
        -> CreativeLibraryDraftRepository
        -> Draft-Zwischenzustand
        -> Validate
        -> Publish Service
        -> CreativeLibraryRevision / Variant / Asset / Document

Architekturregeln:

- Repository enthält keine Flask-Routes.
- Repository enthält keine UI-Logik.
- Repository enthält keine eigentliche Publish-Businesslogik.
- Repository erzeugt keine Published-Revisions.
- Repository erzeugt keine Tabellen.
- Repository führt keine Migration aus.
- Repository führt kein db.create_all() aus.
- Repository öffnet keine aktive DB-Verbindung beim Import.
- DB-Zugriffe laufen nur in expliziten Methoden.
- Validation wird gespeichert, aber fachlich im Service berechnet.
- Publish wird vorbereitet, aber final im Draft-Service ausgeführt.
- Technische Namen, JSON-Keys und Variablen bleiben Englisch.

Phase 1:

- user_id darf weiterhin 1 sein.
- owner_user_id=1 bei User-Drafts.
- owner_scope="user:1".
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

CREATIVE_LIBRARY_DRAFT_REPOSITORY_VERSION: Final[str] = "vectoplan_library.repository.creative_library_draft.v1"

DEFAULT_USER_ID: Final[int] = 1

SOURCE_SCOPE_SYSTEM: Final[str] = "system"
SOURCE_SCOPE_USER: Final[str] = "user"
SOURCE_SCOPE_IMPORTED: Final[str] = "imported"
SOURCE_SCOPE_GENERATED: Final[str] = "generated"

DRAFT_MODE_CREATE: Final[str] = "create"
DRAFT_MODE_UPDATE: Final[str] = "update"
DRAFT_MODE_IMPORT: Final[str] = "import"
DRAFT_MODE_GENERATE: Final[str] = "generate"

DRAFT_STATUS_DRAFT: Final[str] = "draft"
DRAFT_STATUS_VALIDATING: Final[str] = "validating"
DRAFT_STATUS_VALID: Final[str] = "valid"
DRAFT_STATUS_INVALID: Final[str] = "invalid"
DRAFT_STATUS_PUBLISHED: Final[str] = "published"
DRAFT_STATUS_DISCARDED: Final[str] = "discarded"
DRAFT_STATUS_DELETED: Final[str] = "deleted"

DRAFT_STAGE_CREATED: Final[str] = "created"
DRAFT_STAGE_EDITING: Final[str] = "editing"
DRAFT_STAGE_VALIDATION: Final[str] = "validation"
DRAFT_STAGE_READY_TO_PUBLISH: Final[str] = "ready_to_publish"
DRAFT_STAGE_PUBLISHED: Final[str] = "published"
DRAFT_STAGE_DISCARDED: Final[str] = "discarded"

ITEM_STATUS_ACTIVE: Final[str] = "active"
ITEM_STATUS_INACTIVE: Final[str] = "inactive"
ITEM_STATUS_DELETED: Final[str] = "deleted"

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

class CreativeLibraryDraftRepositoryError(RuntimeError):
    """Base error for CreativeLibraryDraftRepository."""


class CreativeLibraryDraftRepositoryImportError(CreativeLibraryDraftRepositoryError):
    """Raised when db/model imports fail."""


class CreativeLibraryDraftNotFoundError(CreativeLibraryDraftRepositoryError):
    """Raised when a draft cannot be found."""


class CreativeLibraryDraftVariantNotFoundError(CreativeLibraryDraftRepositoryError):
    """Raised when a draft variant cannot be found."""


class CreativeLibraryDraftAssetNotFoundError(CreativeLibraryDraftRepositoryError):
    """Raised when a draft asset cannot be found."""


class CreativeLibraryDraftDocumentNotFoundError(CreativeLibraryDraftRepositoryError):
    """Raised when a draft document cannot be found."""


class CreativeLibraryDraftValidationIssueNotFoundError(CreativeLibraryDraftRepositoryError):
    """Raised when a draft validation issue cannot be found."""


class CreativeLibraryDraftConflictError(CreativeLibraryDraftRepositoryError):
    """Raised when draft operation conflicts with current state."""


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

    raise CreativeLibraryDraftRepositoryImportError(
        "Could not import SQLAlchemy extension `db`. "
        + " | ".join(errors)
    )


@lru_cache(maxsize=1)
def _load_draft_models_module() -> ModuleType:
    """Loads models.creative_library_drafts defensively."""
    errors: list[str] = []

    for module_name in (
        "models.creative_library_drafts",
        "src.models.creative_library_drafts",
        "vectoplan_library.models.creative_library_drafts",
    ):
        try:
            return importlib.import_module(module_name)
        except Exception as exc:
            errors.append(f"{module_name}: {type(exc).__name__}: {exc}")

    raise CreativeLibraryDraftRepositoryImportError(
        "Could not import creative_library_drafts models. "
        + " | ".join(errors)
    )


def _db() -> Any:
    """Short alias for lazy db access."""
    return _load_db()


def _models() -> ModuleType:
    """Short alias for lazy model access."""
    return _load_draft_models_module()


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

    if text in {"1", "true", "yes", "y", "ja", "on", "enabled", "active", "visible", "blocking", "resolved"}:
        return True

    if text in {"0", "false", "no", "n", "nein", "off", "disabled", "inactive", "hidden", "deleted", "unresolved"}:
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
        "draft_uid",
        "draft_variant_uid",
        "asset_uid",
        "document_uid",
        "issue_uid",
        "event_uid",
        "owner_user_id",
        "owner_scope",
        "source_scope",
        "mode",
        "status",
        "stage",
        "target_item_id",
        "target_vplib_uid",
        "base_revision_id",
        "published_revision_id",
        "family_id",
        "package_id",
        "vplib_uid",
        "variant_id",
        "title",
        "label",
        "name",
        "description",
        "sort_order",
        "active",
        "visible",
        "created_at",
        "updated_at",
        "published_at",
        "discarded_at",
    ):
        try:
            if hasattr(value, field_name):
                result[field_name] = normalize_json_value(getattr(value, field_name))
        except Exception:
            continue

    return result


def set_attrs_if_present(obj: Any, attrs: Mapping[str, Any]) -> Any:
    """Sets attributes only if object exposes them."""
    for key, value in attrs.items():
        try:
            if hasattr(obj, key):
                setattr(obj, key, value)
        except Exception:
            continue
    return obj


def new_model_with_attrs(model_class: type[Any], attrs: Mapping[str, Any]) -> Any:
    """Creates model instance and sets available attributes."""
    try:
        obj = model_class()
    except Exception:
        obj = model_class

    return set_attrs_if_present(obj, attrs)


def draft_ref_is_numeric(value: Any) -> bool:
    """Checks whether ref looks like DB id."""
    text = clean_string(value)
    return bool(text and text.isdigit())


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


def draft_is_locked_for_edit(draft: Any) -> bool:
    """Checks whether draft should not be edited."""
    status = enum_value(getattr(draft, "status", None)).lower()
    return status in {DRAFT_STATUS_PUBLISHED, DRAFT_STATUS_DISCARDED, DRAFT_STATUS_DELETED}


def issue_is_blocking(payload_or_issue: Mapping[str, Any] | Any) -> bool:
    """Checks whether validation issue is blocking."""
    helper = getattr(_models(), "issue_is_blocking", None)

    if callable(helper):
        try:
            return bool(helper(payload_or_issue))
        except Exception:
            pass

    if isinstance(payload_or_issue, Mapping):
        data = normalize_json_mapping(payload_or_issue)
        severity = clean_string(data.get("severity")).lower()
        return normalize_bool(data.get("blocking"), default=False) or severity in {
            ISSUE_SEVERITY_ERROR,
            ISSUE_SEVERITY_BLOCKING,
        }

    severity = enum_value(getattr(payload_or_issue, "severity", None)).lower()
    return normalize_bool(getattr(payload_or_issue, "blocking", None), default=False) or severity in {
        ISSUE_SEVERITY_ERROR,
        ISSUE_SEVERITY_BLOCKING,
    }


# ---------------------------------------------------------------------------
# Dataclasses
# ---------------------------------------------------------------------------

@dataclass(slots=True)
class DraftQuery:
    """Structured draft query."""

    user_id: int | None = None
    owner_user_id: int | None = None
    owner_scope: str | None = None
    source_scope: str | None = None
    mode: str | None = None
    status: str | None = None
    stage: str | None = None
    target_item_id: int | None = None
    target_vplib_uid: str | None = None
    base_revision_id: int | None = None
    family_id: str | None = None
    package_id: str | None = None
    vplib_uid: str | None = None
    created_by_user_id: int | None = None
    updated_by_user_id: int | None = None
    active_only: bool = False
    include_deleted: bool = False
    include_published: bool = True
    include_discarded: bool = False
    limit: int = DEFAULT_LIMIT
    offset: int = 0

    @classmethod
    def from_payload(cls, payload: Mapping[str, Any] | None = None, **kwargs: Any) -> "DraftQuery":
        data = normalize_json_mapping(payload)
        data.update({key: value for key, value in kwargs.items() if value is not None})

        return cls(
            user_id=normalize_user_id(data.get("user_id"), default=None),
            owner_user_id=normalize_user_id(data.get("owner_user_id"), default=None),
            owner_scope=optional_string(data.get("owner_scope")),
            source_scope=optional_string(data.get("source_scope")),
            mode=optional_string(data.get("mode")),
            status=optional_string(data.get("status")),
            stage=optional_string(data.get("stage")),
            target_item_id=normalize_int(data.get("target_item_id"), default=None, minimum=1),
            target_vplib_uid=optional_string(data.get("target_vplib_uid")),
            base_revision_id=normalize_int(data.get("base_revision_id"), default=None, minimum=1),
            family_id=optional_string(data.get("family_id")),
            package_id=optional_string(data.get("package_id")),
            vplib_uid=optional_string(data.get("vplib_uid")),
            created_by_user_id=normalize_user_id(data.get("created_by_user_id"), default=None),
            updated_by_user_id=normalize_user_id(data.get("updated_by_user_id"), default=None),
            active_only=normalize_bool(data.get("active_only"), default=False),
            include_deleted=normalize_bool(data.get("include_deleted"), default=False),
            include_published=normalize_bool(data.get("include_published"), default=True),
            include_discarded=normalize_bool(data.get("include_discarded"), default=False),
            limit=normalize_int(data.get("limit"), default=DEFAULT_LIMIT, minimum=1, maximum=MAX_LIMIT) or DEFAULT_LIMIT,
            offset=normalize_int(data.get("offset"), default=0, minimum=0) or 0,
        )

    def resolved_owner_scope(self) -> str | None:
        if self.owner_scope:
            return self.owner_scope

        user_id = self.owner_user_id or self.user_id
        if user_id is not None:
            return f"user:{user_id}"

        return None


@dataclass(slots=True)
class DraftChildQuery:
    """Query for variants/assets/documents/issues."""

    draft_id: int | None = None
    draft_uid: str | None = None
    draft_variant_id: int | None = None
    draft_variant_uid: str | None = None
    status: str | None = None
    active_only: bool = False
    include_deleted: bool = False
    limit: int = MAX_LIMIT
    offset: int = 0

    @classmethod
    def from_payload(cls, payload: Mapping[str, Any] | None = None, **kwargs: Any) -> "DraftChildQuery":
        data = normalize_json_mapping(payload)
        data.update({key: value for key, value in kwargs.items() if value is not None})

        return cls(
            draft_id=normalize_int(data.get("draft_id"), default=None, minimum=1),
            draft_uid=optional_string(data.get("draft_uid")),
            draft_variant_id=normalize_int(data.get("draft_variant_id"), default=None, minimum=1),
            draft_variant_uid=optional_string(data.get("draft_variant_uid")),
            status=optional_string(data.get("status")),
            active_only=normalize_bool(data.get("active_only"), default=False),
            include_deleted=normalize_bool(data.get("include_deleted"), default=False),
            limit=normalize_int(data.get("limit"), default=MAX_LIMIT, minimum=1, maximum=MAX_LIMIT) or MAX_LIMIT,
            offset=normalize_int(data.get("offset"), default=0, minimum=0) or 0,
        )


@dataclass(slots=True)
class DraftWriteResult:
    """JSON-compatible draft write result."""

    ok: bool
    action: str
    draft_uid: str | None = None
    draft_variant_uid: str | None = None
    asset_uid: str | None = None
    document_uid: str | None = None
    issue_uid: str | None = None
    event_uid: str | None = None
    draft_id: int | None = None
    draft_variant_id: int | None = None
    asset_id: int | None = None
    document_id: int | None = None
    issue_id: int | None = None
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
            "schema_version": CREATIVE_LIBRARY_DRAFT_REPOSITORY_VERSION,
            "ok": self.ok,
            "action": self.action,
            "draft_uid": self.draft_uid,
            "draft_variant_uid": self.draft_variant_uid,
            "asset_uid": self.asset_uid,
            "document_uid": self.document_uid,
            "issue_uid": self.issue_uid,
            "event_uid": self.event_uid,
            "draft_id": self.draft_id,
            "draft_variant_id": self.draft_variant_id,
            "asset_id": self.asset_id,
            "document_id": self.document_id,
            "issue_id": self.issue_id,
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

class CreativeLibraryDraftRepository:
    """
    SQLAlchemy repository for Creative Library Drafts.

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
    # Draft reads
    # ------------------------------------------------------------------

    def get_draft_by_id(
        self,
        draft_id: Any,
        *,
        include_deleted: bool = False,
        for_update: bool = False,
    ) -> Any | None:
        """Returns draft by DB id."""
        normalized_id = normalize_int(draft_id, default=None, minimum=1)
        if normalized_id is None:
            return None

        model = self.models.CreativeLibraryDraft
        query = self.session.query(model).filter(model.id == normalized_id)

        if not include_deleted and hasattr(model, "status"):
            query = query.filter(model.status != DRAFT_STATUS_DELETED)

        if for_update:
            query = self._with_for_update(query)

        return query.one_or_none()

    def get_draft_by_uid(
        self,
        draft_uid: Any,
        *,
        include_deleted: bool = False,
        for_update: bool = False,
    ) -> Any | None:
        """Returns draft by draft_uid."""
        uid = optional_string(draft_uid)
        if not uid:
            return None

        model = self.models.CreativeLibraryDraft
        query = self.session.query(model).filter(model.draft_uid == uid)

        if not include_deleted and hasattr(model, "status"):
            query = query.filter(model.status != DRAFT_STATUS_DELETED)

        if for_update:
            query = self._with_for_update(query)

        return query.one_or_none()

    def get_draft(
        self,
        draft_ref: Any,
        *,
        include_deleted: bool = False,
        for_update: bool = False,
    ) -> Any | None:
        """Returns draft by id or uid."""
        if draft_ref_is_numeric(draft_ref):
            return self.get_draft_by_id(draft_ref, include_deleted=include_deleted, for_update=for_update)

        return self.get_draft_by_uid(draft_ref, include_deleted=include_deleted, for_update=for_update)

    def require_draft(
        self,
        draft_ref: Any,
        *,
        include_deleted: bool = False,
        for_update: bool = False,
    ) -> Any:
        """Returns draft or raises."""
        draft = self.get_draft(draft_ref, include_deleted=include_deleted, for_update=for_update)

        if draft is None:
            raise CreativeLibraryDraftNotFoundError(f"Creative Library draft {draft_ref!r} was not found.")

        return draft

    def list_drafts(
        self,
        *,
        query: DraftQuery | Mapping[str, Any] | None = None,
        as_dict: bool = False,
        include_summary: bool = False,
    ) -> list[Any]:
        """Lists drafts."""
        draft_query = query if isinstance(query, DraftQuery) else DraftQuery.from_payload(query)
        model = self.models.CreativeLibraryDraft
        db_query = self.session.query(model)

        owner_scope = draft_query.resolved_owner_scope()
        if owner_scope and hasattr(model, "owner_scope"):
            db_query = db_query.filter(model.owner_scope == owner_scope)

        for field_name in (
            "source_scope",
            "mode",
            "status",
            "stage",
            "target_item_id",
            "target_vplib_uid",
            "base_revision_id",
            "family_id",
            "package_id",
            "vplib_uid",
            "created_by_user_id",
            "updated_by_user_id",
        ):
            value = getattr(draft_query, field_name)
            if value is not None and hasattr(model, field_name):
                db_query = db_query.filter(getattr(model, field_name) == value)

        if draft_query.owner_user_id is not None and hasattr(model, "owner_user_id"):
            db_query = db_query.filter(model.owner_user_id == draft_query.owner_user_id)

        if draft_query.active_only and hasattr(model, "active"):
            db_query = db_query.filter(model.active.is_(True))

        if not draft_query.include_deleted and hasattr(model, "status"):
            db_query = db_query.filter(model.status != DRAFT_STATUS_DELETED)

        if not draft_query.include_published and hasattr(model, "status"):
            db_query = db_query.filter(model.status != DRAFT_STATUS_PUBLISHED)

        if not draft_query.include_discarded and hasattr(model, "status"):
            db_query = db_query.filter(model.status != DRAFT_STATUS_DISCARDED)

        db_query = self._apply_default_sort(db_query, model)

        if draft_query.offset:
            db_query = db_query.offset(draft_query.offset)

        if draft_query.limit:
            db_query = db_query.limit(draft_query.limit)

        values = db_query.all()

        if as_dict:
            return [self.get_draft_payload(value, include_summary=include_summary) for value in values]

        return values

    def list_draft_payloads(
        self,
        *,
        query: DraftQuery | Mapping[str, Any] | None = None,
        include_summary: bool = False,
    ) -> list[dict[str, Any]]:
        """Lists drafts as dictionaries."""
        return self.list_drafts(query=query, as_dict=True, include_summary=include_summary)

    # ------------------------------------------------------------------
    # Draft writes
    # ------------------------------------------------------------------

    def create_draft(
        self,
        payload: Mapping[str, Any],
        *,
        owner_user_id: Any = DEFAULT_USER_ID,
        source_scope: Any = SOURCE_SCOPE_USER,
        created_by_user_id: Any = None,
        commit: bool = False,
        audit: bool = True,
    ) -> Any:
        """Creates a draft."""
        data = normalize_json_mapping(payload)

        try:
            creator = getattr(self.models.CreativeLibraryDraft, "create_from_payload", None)

            if callable(creator):
                draft = creator(
                    data,
                    owner_user_id=owner_user_id,
                    source_scope=source_scope,
                    created_by_user_id=created_by_user_id,
                )
            else:
                draft = new_model_with_attrs(
                    self.models.CreativeLibraryDraft,
                    self._fallback_draft_attrs(
                        data,
                        owner_user_id=owner_user_id,
                        source_scope=source_scope,
                        created_by_user_id=created_by_user_id,
                    ),
                )

            self.session.add(draft)
            self.session.flush()

            if audit:
                self.create_audit_event(
                    event_type="draft_created",
                    user_id=created_by_user_id or owner_user_id,
                    draft=draft,
                    after=to_dict_or_payload(draft),
                    commit=False,
                )

            self._finish_write(commit=commit)
            return draft

        except Exception:
            if commit:
                self.rollback()
            raise

    def update_draft(
        self,
        draft_ref: Any,
        payload: Mapping[str, Any],
        *,
        user_id: Any = None,
        allow_locked: bool = False,
        commit: bool = False,
        audit: bool = True,
    ) -> Any:
        """Updates mutable draft fields."""
        data = normalize_json_mapping(payload)

        try:
            draft = self.require_draft(draft_ref, include_deleted=True, for_update=True)

            if draft_is_locked_for_edit(draft) and not allow_locked:
                raise CreativeLibraryDraftConflictError(f"Draft {draft_ref!r} cannot be edited in status {getattr(draft, 'status', None)!r}.")

            before = self.get_draft_payload(draft, include_summary=True)

            updater = getattr(draft, "update_from_payload", None)
            if callable(updater):
                draft = updater(data, updated_by_user_id=user_id) or draft
            else:
                self._fallback_update_draft(draft, data, user_id=user_id)

            after = self.get_draft_payload(draft, include_summary=True)

            if audit:
                self.create_audit_event(
                    event_type="draft_updated",
                    user_id=user_id or getattr(draft, "owner_user_id", None),
                    draft=draft,
                    before=before,
                    after=after,
                    commit=False,
                )

            self._finish_write(commit=commit)
            return draft

        except Exception:
            if commit:
                self.rollback()
            raise

    def set_draft_status(
        self,
        draft_ref: Any,
        *,
        status: Any,
        stage: Any = None,
        user_id: Any = None,
        validation_payload: Mapping[str, Any] | None = None,
        published_revision_id: Any = None,
        commit: bool = False,
        audit: bool = True,
    ) -> Any:
        """Sets draft status/stage."""
        try:
            draft = self.require_draft(draft_ref, include_deleted=True, for_update=True)
            before = self.get_draft_payload(draft, include_summary=True)

            normalized_status = clean_string(status, fallback=DRAFT_STATUS_DRAFT)
            normalized_stage = optional_string(stage)

            if hasattr(draft, "set_status") and callable(draft.set_status):
                try:
                    draft.set_status(
                        normalized_status,
                        stage=normalized_stage,
                        user_id=user_id,
                        validation_payload=validation_payload,
                        published_revision_id=published_revision_id,
                    )
                except TypeError:
                    draft.set_status(normalized_status)
            else:
                if hasattr(draft, "status"):
                    draft.status = normalized_status
                if normalized_stage is not None and hasattr(draft, "stage"):
                    draft.stage = normalized_stage
                if validation_payload is not None and hasattr(draft, "validation_payload"):
                    draft.validation_payload = normalize_json_mapping(validation_payload)
                if published_revision_id is not None and hasattr(draft, "published_revision_id"):
                    draft.published_revision_id = normalize_int(published_revision_id, default=None, minimum=1)
                if hasattr(draft, "updated_by_user_id"):
                    draft.updated_by_user_id = normalize_user_id(user_id, default=None)
                if hasattr(draft, "touch") and callable(draft.touch):
                    draft.touch()

            after = self.get_draft_payload(draft, include_summary=True)

            if audit:
                self.create_audit_event(
                    event_type=f"draft_status_{normalized_status}",
                    user_id=user_id or getattr(draft, "owner_user_id", None),
                    draft=draft,
                    before=before,
                    after=after,
                    payload={
                        "status": normalized_status,
                        "stage": normalized_stage,
                        "published_revision_id": published_revision_id,
                    },
                    commit=False,
                )

            self._finish_write(commit=commit)
            return draft

        except Exception:
            if commit:
                self.rollback()
            raise

    def mark_validating(self, draft_ref: Any, *, user_id: Any = None, commit: bool = False) -> Any:
        """Marks draft as validating."""
        return self.set_draft_status(
            draft_ref,
            status=DRAFT_STATUS_VALIDATING,
            stage=DRAFT_STAGE_VALIDATION,
            user_id=user_id,
            commit=commit,
        )

    def mark_valid(self, draft_ref: Any, *, user_id: Any = None, validation_payload: Mapping[str, Any] | None = None, commit: bool = False) -> Any:
        """Marks draft as valid."""
        return self.set_draft_status(
            draft_ref,
            status=DRAFT_STATUS_VALID,
            stage=DRAFT_STAGE_READY_TO_PUBLISH,
            user_id=user_id,
            validation_payload=validation_payload,
            commit=commit,
        )

    def mark_invalid(self, draft_ref: Any, *, user_id: Any = None, validation_payload: Mapping[str, Any] | None = None, commit: bool = False) -> Any:
        """Marks draft as invalid."""
        return self.set_draft_status(
            draft_ref,
            status=DRAFT_STATUS_INVALID,
            stage=DRAFT_STAGE_VALIDATION,
            user_id=user_id,
            validation_payload=validation_payload,
            commit=commit,
        )

    def mark_published(
        self,
        draft_ref: Any,
        *,
        published_revision_id: Any = None,
        user_id: Any = None,
        commit: bool = False,
    ) -> Any:
        """Marks draft as published."""
        return self.set_draft_status(
            draft_ref,
            status=DRAFT_STATUS_PUBLISHED,
            stage=DRAFT_STAGE_PUBLISHED,
            user_id=user_id,
            published_revision_id=published_revision_id,
            commit=commit,
        )

    def discard_draft(
        self,
        draft_ref: Any,
        *,
        user_id: Any = None,
        commit: bool = False,
        audit: bool = True,
    ) -> bool:
        """Discards a draft."""
        try:
            draft = self.require_draft(draft_ref, include_deleted=True, for_update=True)
            before = self.get_draft_payload(draft, include_summary=True)

            if hasattr(draft, "discard") and callable(draft.discard):
                draft.discard(user_id=user_id)
            else:
                if hasattr(draft, "status"):
                    draft.status = DRAFT_STATUS_DISCARDED
                if hasattr(draft, "stage"):
                    draft.stage = DRAFT_STAGE_DISCARDED
                if hasattr(draft, "active"):
                    draft.active = False
                if hasattr(draft, "updated_by_user_id"):
                    draft.updated_by_user_id = normalize_user_id(user_id, default=None)
                if hasattr(draft, "touch") and callable(draft.touch):
                    draft.touch()

            after = self.get_draft_payload(draft, include_summary=True)

            if audit:
                self.create_audit_event(
                    event_type="draft_discarded",
                    user_id=user_id or getattr(draft, "owner_user_id", None),
                    draft=draft,
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

    def soft_delete_draft(
        self,
        draft_ref: Any,
        *,
        user_id: Any = None,
        commit: bool = False,
        audit: bool = True,
    ) -> bool:
        """Soft-deletes a draft."""
        try:
            draft = self.require_draft(draft_ref, include_deleted=True, for_update=True)
            before = self.get_draft_payload(draft, include_summary=True)

            if hasattr(draft, "mark_deleted") and callable(draft.mark_deleted):
                draft.mark_deleted(user_id=user_id)
            else:
                if hasattr(draft, "status"):
                    draft.status = DRAFT_STATUS_DELETED
                if hasattr(draft, "active"):
                    draft.active = False
                if hasattr(draft, "visible"):
                    draft.visible = False
                if hasattr(draft, "updated_by_user_id"):
                    draft.updated_by_user_id = normalize_user_id(user_id, default=None)
                if hasattr(draft, "touch") and callable(draft.touch):
                    draft.touch()

            after = self.get_draft_payload(draft, include_summary=True)

            if audit:
                self.create_audit_event(
                    event_type="draft_deleted",
                    user_id=user_id or getattr(draft, "owner_user_id", None),
                    draft=draft,
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
    # Draft variants
    # ------------------------------------------------------------------

    def get_variant_by_id(self, variant_id: Any, *, include_deleted: bool = False, for_update: bool = False) -> Any | None:
        """Returns draft variant by DB id."""
        normalized_id = normalize_int(variant_id, default=None, minimum=1)
        if normalized_id is None:
            return None

        model = self.models.CreativeLibraryDraftVariant
        query = self.session.query(model).filter(model.id == normalized_id)

        if not include_deleted and hasattr(model, "status"):
            query = query.filter(model.status != ITEM_STATUS_DELETED)

        if for_update:
            query = self._with_for_update(query)

        return query.one_or_none()

    def get_variant_by_uid(self, variant_uid: Any, *, include_deleted: bool = False, for_update: bool = False) -> Any | None:
        """Returns draft variant by uid."""
        uid = optional_string(variant_uid)
        if not uid:
            return None

        model = self.models.CreativeLibraryDraftVariant
        query = self.session.query(model)

        for column_name in ("draft_variant_uid", "variant_uid"):
            if hasattr(model, column_name):
                query = query.filter(getattr(model, column_name) == uid)
                break
        else:
            return None

        if not include_deleted and hasattr(model, "status"):
            query = query.filter(model.status != ITEM_STATUS_DELETED)

        if for_update:
            query = self._with_for_update(query)

        return query.one_or_none()

    def get_variant(self, variant_ref: Any, *, include_deleted: bool = False, for_update: bool = False) -> Any | None:
        """Returns draft variant by id or uid."""
        if draft_ref_is_numeric(variant_ref):
            return self.get_variant_by_id(variant_ref, include_deleted=include_deleted, for_update=for_update)
        return self.get_variant_by_uid(variant_ref, include_deleted=include_deleted, for_update=for_update)

    def require_variant(self, variant_ref: Any, *, include_deleted: bool = False, for_update: bool = False) -> Any:
        """Returns variant or raises."""
        variant = self.get_variant(variant_ref, include_deleted=include_deleted, for_update=for_update)
        if variant is None:
            raise CreativeLibraryDraftVariantNotFoundError(f"Draft variant {variant_ref!r} was not found.")
        return variant

    def list_variants(
        self,
        draft_ref: Any | None = None,
        *,
        query: DraftChildQuery | Mapping[str, Any] | None = None,
        as_dict: bool = False,
    ) -> list[Any]:
        """Lists draft variants."""
        child_query = query if isinstance(query, DraftChildQuery) else DraftChildQuery.from_payload(query)

        if draft_ref is not None:
            draft = self.require_draft(draft_ref)
            child_query.draft_id = getattr(draft, "id", None)

        model = self.models.CreativeLibraryDraftVariant
        db_query = self.session.query(model)

        db_query = self._apply_child_filters(db_query, model, child_query)

        db_query = self._apply_default_sort(db_query, model)

        if child_query.offset:
            db_query = db_query.offset(child_query.offset)

        if child_query.limit:
            db_query = db_query.limit(child_query.limit)

        values = db_query.all()

        if as_dict:
            return [to_dict_or_payload(value) for value in values]

        return values

    def add_variant(
        self,
        draft_ref: Any,
        payload: Mapping[str, Any],
        *,
        user_id: Any = None,
        commit: bool = False,
        audit: bool = True,
    ) -> Any:
        """Adds a draft variant."""
        data = normalize_json_mapping(payload)

        try:
            draft = self.require_draft(draft_ref, include_deleted=False, for_update=True)

            if draft_is_locked_for_edit(draft):
                raise CreativeLibraryDraftConflictError(f"Draft {draft_ref!r} cannot be edited.")

            creator = getattr(self.models.CreativeLibraryDraftVariant, "create_from_payload", None)

            if callable(creator):
                variant = creator(data, draft=draft, created_by_user_id=user_id)
            else:
                variant = new_model_with_attrs(
                    self.models.CreativeLibraryDraftVariant,
                    self._fallback_variant_attrs(data, draft=draft, user_id=user_id),
                )

            self.session.add(variant)
            self.session.flush()

            if audit:
                self.create_audit_event(
                    event_type="variant_added",
                    user_id=user_id or getattr(draft, "owner_user_id", None),
                    draft=draft,
                    draft_variant=variant,
                    after=to_dict_or_payload(variant),
                    commit=False,
                )

            self._finish_write(commit=commit)
            return variant

        except Exception:
            if commit:
                self.rollback()
            raise

    def update_variant(
        self,
        variant_ref: Any,
        payload: Mapping[str, Any],
        *,
        user_id: Any = None,
        commit: bool = False,
        audit: bool = True,
    ) -> Any:
        """Updates draft variant."""
        data = normalize_json_mapping(payload)

        try:
            variant = self.require_variant(variant_ref, include_deleted=True, for_update=True)
            draft = getattr(variant, "draft", None) or self.get_draft_by_id(getattr(variant, "draft_id", None), include_deleted=True)

            if draft is not None and draft_is_locked_for_edit(draft):
                raise CreativeLibraryDraftConflictError(f"Draft variant {variant_ref!r} cannot be edited because draft is locked.")

            before = to_dict_or_payload(variant)

            updater = getattr(variant, "update_from_payload", None)
            if callable(updater):
                variant = updater(data, updated_by_user_id=user_id) or variant
            else:
                self._fallback_update_child(variant, data, user_id=user_id)

            after = to_dict_or_payload(variant)

            if audit:
                self.create_audit_event(
                    event_type="variant_updated",
                    user_id=user_id or getattr(draft, "owner_user_id", None),
                    draft=draft,
                    draft_variant=variant,
                    before=before,
                    after=after,
                    commit=False,
                )

            self._finish_write(commit=commit)
            return variant

        except Exception:
            if commit:
                self.rollback()
            raise

    def soft_delete_variant(self, variant_ref: Any, *, user_id: Any = None, commit: bool = False, audit: bool = True) -> bool:
        """Soft-deletes draft variant."""
        try:
            variant = self.require_variant(variant_ref, include_deleted=True, for_update=True)
            draft = getattr(variant, "draft", None) or self.get_draft_by_id(getattr(variant, "draft_id", None), include_deleted=True)

            if draft is not None and draft_is_locked_for_edit(draft):
                raise CreativeLibraryDraftConflictError(f"Draft variant {variant_ref!r} cannot be deleted because draft is locked.")

            before = to_dict_or_payload(variant)
            self._mark_child_deleted(variant, user_id=user_id)
            after = to_dict_or_payload(variant)

            if audit:
                self.create_audit_event(
                    event_type="variant_deleted",
                    user_id=user_id or getattr(draft, "owner_user_id", None),
                    draft=draft,
                    draft_variant=variant,
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
    # Draft assets
    # ------------------------------------------------------------------

    def get_asset_by_id(self, asset_id: Any, *, include_deleted: bool = False, for_update: bool = False) -> Any | None:
        """Returns draft asset by DB id."""
        return self._get_child_by_id(self.models.CreativeLibraryDraftAsset, asset_id, include_deleted=include_deleted, for_update=for_update)

    def get_asset_by_uid(self, asset_uid: Any, *, include_deleted: bool = False, for_update: bool = False) -> Any | None:
        """Returns draft asset by uid."""
        return self._get_child_by_uid(self.models.CreativeLibraryDraftAsset, asset_uid, ("asset_uid",), include_deleted=include_deleted, for_update=for_update)

    def get_asset(self, asset_ref: Any, *, include_deleted: bool = False, for_update: bool = False) -> Any | None:
        """Returns asset by id or uid."""
        if draft_ref_is_numeric(asset_ref):
            return self.get_asset_by_id(asset_ref, include_deleted=include_deleted, for_update=for_update)
        return self.get_asset_by_uid(asset_ref, include_deleted=include_deleted, for_update=for_update)

    def require_asset(self, asset_ref: Any, *, include_deleted: bool = False, for_update: bool = False) -> Any:
        """Returns asset or raises."""
        asset = self.get_asset(asset_ref, include_deleted=include_deleted, for_update=for_update)
        if asset is None:
            raise CreativeLibraryDraftAssetNotFoundError(f"Draft asset {asset_ref!r} was not found.")
        return asset

    def list_assets(
        self,
        draft_ref: Any | None = None,
        *,
        query: DraftChildQuery | Mapping[str, Any] | None = None,
        as_dict: bool = False,
    ) -> list[Any]:
        """Lists draft assets."""
        return self._list_children(
            self.models.CreativeLibraryDraftAsset,
            draft_ref=draft_ref,
            query=query,
            as_dict=as_dict,
        )

    def add_asset(
        self,
        draft_ref: Any,
        payload: Mapping[str, Any],
        *,
        draft_variant_ref: Any = None,
        user_id: Any = None,
        commit: bool = False,
        audit: bool = True,
    ) -> Any:
        """Adds draft asset."""
        return self._add_child(
            child_kind="asset",
            model_class=self.models.CreativeLibraryDraftAsset,
            draft_ref=draft_ref,
            payload=payload,
            draft_variant_ref=draft_variant_ref,
            user_id=user_id,
            commit=commit,
            audit=audit,
        )

    def update_asset(self, asset_ref: Any, payload: Mapping[str, Any], *, user_id: Any = None, commit: bool = False, audit: bool = True) -> Any:
        """Updates draft asset."""
        return self._update_child(
            child_kind="asset",
            child_ref=asset_ref,
            getter=self.require_asset,
            payload=payload,
            user_id=user_id,
            commit=commit,
            audit=audit,
        )

    def soft_delete_asset(self, asset_ref: Any, *, user_id: Any = None, commit: bool = False, audit: bool = True) -> bool:
        """Soft-deletes draft asset."""
        return self._soft_delete_child(
            child_kind="asset",
            child_ref=asset_ref,
            getter=self.require_asset,
            user_id=user_id,
            commit=commit,
            audit=audit,
        )

    # ------------------------------------------------------------------
    # Draft documents
    # ------------------------------------------------------------------

    def get_document_by_id(self, document_id: Any, *, include_deleted: bool = False, for_update: bool = False) -> Any | None:
        """Returns draft document by DB id."""
        return self._get_child_by_id(self.models.CreativeLibraryDraftDocument, document_id, include_deleted=include_deleted, for_update=for_update)

    def get_document_by_uid(self, document_uid: Any, *, include_deleted: bool = False, for_update: bool = False) -> Any | None:
        """Returns draft document by uid."""
        return self._get_child_by_uid(self.models.CreativeLibraryDraftDocument, document_uid, ("document_uid",), include_deleted=include_deleted, for_update=for_update)

    def get_document(self, document_ref: Any, *, include_deleted: bool = False, for_update: bool = False) -> Any | None:
        """Returns document by id or uid."""
        if draft_ref_is_numeric(document_ref):
            return self.get_document_by_id(document_ref, include_deleted=include_deleted, for_update=for_update)
        return self.get_document_by_uid(document_ref, include_deleted=include_deleted, for_update=for_update)

    def require_document(self, document_ref: Any, *, include_deleted: bool = False, for_update: bool = False) -> Any:
        """Returns document or raises."""
        document = self.get_document(document_ref, include_deleted=include_deleted, for_update=for_update)
        if document is None:
            raise CreativeLibraryDraftDocumentNotFoundError(f"Draft document {document_ref!r} was not found.")
        return document

    def list_documents(
        self,
        draft_ref: Any | None = None,
        *,
        query: DraftChildQuery | Mapping[str, Any] | None = None,
        as_dict: bool = False,
    ) -> list[Any]:
        """Lists draft documents."""
        return self._list_children(
            self.models.CreativeLibraryDraftDocument,
            draft_ref=draft_ref,
            query=query,
            as_dict=as_dict,
        )

    def add_document(
        self,
        draft_ref: Any,
        payload: Mapping[str, Any],
        *,
        draft_variant_ref: Any = None,
        user_id: Any = None,
        commit: bool = False,
        audit: bool = True,
    ) -> Any:
        """Adds draft document."""
        return self._add_child(
            child_kind="document",
            model_class=self.models.CreativeLibraryDraftDocument,
            draft_ref=draft_ref,
            payload=payload,
            draft_variant_ref=draft_variant_ref,
            user_id=user_id,
            commit=commit,
            audit=audit,
        )

    def update_document(self, document_ref: Any, payload: Mapping[str, Any], *, user_id: Any = None, commit: bool = False, audit: bool = True) -> Any:
        """Updates draft document."""
        return self._update_child(
            child_kind="document",
            child_ref=document_ref,
            getter=self.require_document,
            payload=payload,
            user_id=user_id,
            commit=commit,
            audit=audit,
        )

    def soft_delete_document(self, document_ref: Any, *, user_id: Any = None, commit: bool = False, audit: bool = True) -> bool:
        """Soft-deletes draft document."""
        return self._soft_delete_child(
            child_kind="document",
            child_ref=document_ref,
            getter=self.require_document,
            user_id=user_id,
            commit=commit,
            audit=audit,
        )

    # ------------------------------------------------------------------
    # Validation issues
    # ------------------------------------------------------------------

    def get_issue_by_id(self, issue_id: Any, *, include_deleted: bool = False, for_update: bool = False) -> Any | None:
        """Returns validation issue by DB id."""
        return self._get_child_by_id(self.models.CreativeLibraryDraftValidationIssue, issue_id, include_deleted=include_deleted, for_update=for_update)

    def get_issue_by_uid(self, issue_uid: Any, *, include_deleted: bool = False, for_update: bool = False) -> Any | None:
        """Returns validation issue by uid."""
        return self._get_child_by_uid(self.models.CreativeLibraryDraftValidationIssue, issue_uid, ("issue_uid",), include_deleted=include_deleted, for_update=for_update)

    def get_issue(self, issue_ref: Any, *, include_deleted: bool = False, for_update: bool = False) -> Any | None:
        """Returns validation issue by id or uid."""
        if draft_ref_is_numeric(issue_ref):
            return self.get_issue_by_id(issue_ref, include_deleted=include_deleted, for_update=for_update)
        return self.get_issue_by_uid(issue_ref, include_deleted=include_deleted, for_update=for_update)

    def require_issue(self, issue_ref: Any, *, include_deleted: bool = False, for_update: bool = False) -> Any:
        """Returns issue or raises."""
        issue = self.get_issue(issue_ref, include_deleted=include_deleted, for_update=for_update)
        if issue is None:
            raise CreativeLibraryDraftValidationIssueNotFoundError(f"Draft validation issue {issue_ref!r} was not found.")
        return issue

    def list_validation_issues(
        self,
        draft_ref: Any | None = None,
        *,
        query: DraftChildQuery | Mapping[str, Any] | None = None,
        severity: Any = None,
        unresolved_only: bool = False,
        blocking_only: bool = False,
        as_dict: bool = False,
    ) -> list[Any]:
        """Lists validation issues."""
        child_query = query if isinstance(query, DraftChildQuery) else DraftChildQuery.from_payload(query)

        if draft_ref is not None:
            draft = self.require_draft(draft_ref)
            child_query.draft_id = getattr(draft, "id", None)

        model = self.models.CreativeLibraryDraftValidationIssue
        db_query = self.session.query(model)
        db_query = self._apply_child_filters(db_query, model, child_query)

        normalized_severity = optional_string(severity)
        if normalized_severity and hasattr(model, "severity"):
            db_query = db_query.filter(model.severity == normalized_severity)

        if unresolved_only and hasattr(model, "resolved"):
            db_query = db_query.filter(model.resolved.is_(False))

        if blocking_only and hasattr(model, "blocking"):
            db_query = db_query.filter(model.blocking.is_(True))

        db_query = self._apply_default_sort(db_query, model)

        if child_query.offset:
            db_query = db_query.offset(child_query.offset)

        if child_query.limit:
            db_query = db_query.limit(child_query.limit)

        values = db_query.all()

        if as_dict:
            return [to_dict_or_payload(value) for value in values]

        return values

    def clear_validation_issues(
        self,
        draft_ref: Any,
        *,
        user_id: Any = None,
        commit: bool = False,
        audit: bool = True,
    ) -> int:
        """Soft-deletes current validation issues for draft."""
        try:
            draft = self.require_draft(draft_ref, include_deleted=True, for_update=True)
            issues = self.list_validation_issues(draft.id, query={"include_deleted": False}, as_dict=False)
            count = 0

            for issue in issues:
                self._mark_child_deleted(issue, user_id=user_id)
                count += 1

            if audit:
                self.create_audit_event(
                    event_type="validation_issues_cleared",
                    user_id=user_id or getattr(draft, "owner_user_id", None),
                    draft=draft,
                    payload={"cleared_count": count},
                    commit=False,
                )

            self._finish_write(commit=commit)
            return count

        except Exception:
            if commit:
                self.rollback()
            raise

    def add_validation_issue(
        self,
        draft_ref: Any,
        payload: Mapping[str, Any],
        *,
        draft_variant_ref: Any = None,
        user_id: Any = None,
        commit: bool = False,
        audit: bool = False,
    ) -> Any:
        """Adds validation issue."""
        return self._add_child(
            child_kind="validation_issue",
            model_class=self.models.CreativeLibraryDraftValidationIssue,
            draft_ref=draft_ref,
            payload=payload,
            draft_variant_ref=draft_variant_ref,
            user_id=user_id,
            commit=commit,
            audit=audit,
        )

    def set_validation_results(
        self,
        draft_ref: Any,
        issues: Iterable[Mapping[str, Any]],
        *,
        user_id: Any = None,
        replace_existing: bool = True,
        commit: bool = False,
    ) -> dict[str, Any]:
        """Stores validation result issues and updates draft validity."""
        try:
            draft = self.require_draft(draft_ref, include_deleted=True, for_update=True)

            if replace_existing:
                self.clear_validation_issues(draft.id, user_id=user_id, commit=False, audit=False)

            created_issues: list[Any] = []
            blocking_count = 0

            for issue_payload in issues or ():
                issue = self.add_validation_issue(
                    draft.id,
                    issue_payload,
                    draft_variant_ref=issue_payload.get("draft_variant_id") or issue_payload.get("draft_variant_uid"),
                    user_id=user_id,
                    commit=False,
                    audit=False,
                )
                created_issues.append(issue)

                if issue_is_blocking(issue_payload) or issue_is_blocking(issue):
                    blocking_count += 1

            validation_payload = {
                "issue_count": len(created_issues),
                "blocking_count": blocking_count,
                "valid": blocking_count == 0,
            }

            if blocking_count:
                self.mark_invalid(
                    draft.id,
                    user_id=user_id,
                    validation_payload=validation_payload,
                    commit=False,
                )
            else:
                self.mark_valid(
                    draft.id,
                    user_id=user_id,
                    validation_payload=validation_payload,
                    commit=False,
                )

            self.create_audit_event(
                event_type="validation_results_set",
                user_id=user_id or getattr(draft, "owner_user_id", None),
                draft=draft,
                payload=validation_payload,
                commit=False,
            )

            self._finish_write(commit=commit)

            return {
                "schema_version": CREATIVE_LIBRARY_DRAFT_REPOSITORY_VERSION,
                "ok": True,
                "draft_uid": getattr(draft, "draft_uid", None),
                "draft_id": getattr(draft, "id", None),
                "issue_count": len(created_issues),
                "blocking_count": blocking_count,
                "valid": blocking_count == 0,
                "issues": [to_dict_or_payload(issue) for issue in created_issues],
            }

        except Exception:
            if commit:
                self.rollback()
            raise

    def has_blocking_issues(self, draft_ref: Any) -> bool:
        """Checks whether draft has unresolved blocking validation issues."""
        helper = getattr(self.models, "draft_has_blocking_issues", None)

        try:
            draft = self.require_draft(draft_ref)

            if callable(helper):
                return bool(helper(draft))

            issues = self.list_validation_issues(
                draft.id,
                unresolved_only=True,
                blocking_only=False,
                as_dict=False,
            )

            return any(issue_is_blocking(issue) for issue in issues)

        except Exception:
            return True

    # ------------------------------------------------------------------
    # Audit
    # ------------------------------------------------------------------

    def create_audit_event(
        self,
        *,
        event_type: Any,
        user_id: Any = None,
        draft: Any = None,
        draft_variant: Any = None,
        asset: Any = None,
        document: Any = None,
        issue: Any = None,
        before: Mapping[str, Any] | None = None,
        after: Mapping[str, Any] | None = None,
        diff: Mapping[str, Any] | None = None,
        payload: Mapping[str, Any] | None = None,
        metadata: Mapping[str, Any] | None = None,
        commit: bool = False,
    ) -> Any:
        """Creates a draft audit event."""
        try:
            creator = getattr(self.models.CreativeLibraryDraftAuditEvent, "create_event", None)

            if callable(creator):
                event = creator(
                    event_type=event_type,
                    user_id=user_id,
                    draft=draft,
                    draft_variant=draft_variant,
                    asset=asset,
                    document=document,
                    issue=issue,
                    before=before,
                    after=after,
                    diff=diff,
                    payload=payload,
                    metadata=metadata,
                )
            else:
                event = new_model_with_attrs(
                    self.models.CreativeLibraryDraftAuditEvent,
                    {
                        "event_type": clean_string(event_type, fallback="other"),
                        "user_id": normalize_user_id(user_id, default=None),
                        "draft_id": getattr(draft, "id", None),
                        "draft_uid": getattr(draft, "draft_uid", None),
                        "draft_variant_id": getattr(draft_variant, "id", None),
                        "asset_id": getattr(asset, "id", None),
                        "document_id": getattr(document, "id", None),
                        "issue_id": getattr(issue, "id", None),
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
        draft_ref: Any = None,
        user_id: Any = None,
        event_type: Any = None,
        limit: int = DEFAULT_LIMIT,
        offset: int = 0,
        as_dict: bool = True,
    ) -> list[Any]:
        """Lists draft audit events."""
        model = self.models.CreativeLibraryDraftAuditEvent
        query = self.session.query(model)

        if draft_ref is not None:
            draft = self.require_draft(draft_ref, include_deleted=True)
            if hasattr(model, "draft_id"):
                query = query.filter(model.draft_id == draft.id)

        normalized_user_id = normalize_user_id(user_id, default=None)
        if normalized_user_id is not None and hasattr(model, "user_id"):
            query = query.filter(model.user_id == normalized_user_id)

        normalized_event_type = optional_string(event_type)
        if normalized_event_type and hasattr(model, "event_type"):
            query = query.filter(model.event_type == normalized_event_type)

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
    # Aggregate payloads
    # ------------------------------------------------------------------

    def get_draft_payload(
        self,
        draft_ref: Any,
        *,
        include_variants: bool = False,
        include_assets: bool = False,
        include_documents: bool = False,
        include_issues: bool = False,
        include_audit: bool = False,
        include_summary: bool = False,
    ) -> dict[str, Any]:
        """Builds draft payload."""
        draft = draft_ref if not isinstance(draft_ref, (str, int)) else self.require_draft(draft_ref, include_deleted=True)

        if hasattr(draft, "to_dict"):
            try:
                payload = draft.to_dict(
                    include_variants=include_variants,
                    include_assets=include_assets,
                    include_documents=include_documents,
                    include_issues=include_issues,
                    include_audit=include_audit,
                    include_summary=include_summary,
                )
                return normalize_json_mapping(payload)
            except TypeError:
                pass
            except Exception:
                pass

        payload = to_dict_or_payload(draft)

        if include_summary:
            helper = getattr(self.models, "build_draft_payload_summary", None)
            if callable(helper):
                try:
                    payload["summary"] = normalize_json_mapping(helper(draft))
                except Exception:
                    payload["summary"] = self._fallback_draft_summary(draft)
            else:
                payload["summary"] = self._fallback_draft_summary(draft)

        draft_id = getattr(draft, "id", None)

        if include_variants:
            payload["variants"] = self.list_variants(draft_id, as_dict=True)

        if include_assets:
            payload["assets"] = self.list_assets(draft_id, as_dict=True)

        if include_documents:
            payload["documents"] = self.list_documents(draft_id, as_dict=True)

        if include_issues:
            payload["validation_issues"] = self.list_validation_issues(draft_id, as_dict=True)

        if include_audit:
            payload["audit_events"] = self.list_audit_events(draft_ref=draft_id, as_dict=True)

        return payload

    # ------------------------------------------------------------------
    # Health / diagnostics
    # ------------------------------------------------------------------

    def get_health(self) -> dict[str, Any]:
        """Returns repository health snapshot."""
        model_health = {}

        try:
            candidate = getattr(self.models, "get_creative_library_draft_models_health", None)
            if callable(candidate):
                model_health = candidate()
        except Exception as exc:
            model_health = {"ok": False, "error": f"{type(exc).__name__}: {exc}"}

        return {
            "schema_version": CREATIVE_LIBRARY_DRAFT_REPOSITORY_VERSION,
            "ok": True,
            "repository": type(self).__name__,
            "has_session": self._session is not None,
            "uses_default_db_session": self._session is None,
            "models_health": model_health,
            "supports_drafts": True,
            "supports_variants": True,
            "supports_assets": True,
            "supports_documents": True,
            "supports_validation_issues": True,
            "supports_audit": True,
            "supports_status_transitions": True,
            "supports_validation_results": True,
            "supports_publish_marker": True,
            "supports_soft_delete": True,
        }

    # ------------------------------------------------------------------
    # Internal generic helpers
    # ------------------------------------------------------------------

    def _with_for_update(self, query: Any) -> Any:
        """Applies FOR UPDATE if supported."""
        try:
            return query.with_for_update()
        except Exception:
            return query

    def _apply_default_sort(self, query: Any, model: type[Any]) -> Any:
        """Applies stable ordering."""
        order_fields = []

        for field_name in ("sort_order", "created_at", "id"):
            column = getattr(model, field_name, None)
            if column is not None:
                try:
                    if field_name == "created_at":
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

    def _apply_child_filters(self, query: Any, model: type[Any], child_query: DraftChildQuery) -> Any:
        """Applies common child filters."""
        draft_id = child_query.draft_id

        if draft_id is None and child_query.draft_uid:
            draft = self.get_draft_by_uid(child_query.draft_uid)
            draft_id = getattr(draft, "id", None) if draft is not None else None
            if draft_id is None:
                return query.filter(False)

        if draft_id is not None and hasattr(model, "draft_id"):
            query = query.filter(model.draft_id == draft_id)

        variant_id = child_query.draft_variant_id

        if variant_id is None and child_query.draft_variant_uid:
            variant = self.get_variant_by_uid(child_query.draft_variant_uid)
            variant_id = getattr(variant, "id", None) if variant is not None else None
            if variant_id is None:
                return query.filter(False)

        if variant_id is not None and hasattr(model, "draft_variant_id"):
            query = query.filter(model.draft_variant_id == variant_id)

        if child_query.status and hasattr(model, "status"):
            query = query.filter(model.status == child_query.status)

        if child_query.active_only and hasattr(model, "active"):
            query = query.filter(model.active.is_(True))

        if not child_query.include_deleted and hasattr(model, "status"):
            query = query.filter(model.status != ITEM_STATUS_DELETED)

        return query

    def _get_child_by_id(self, model: type[Any], child_id: Any, *, include_deleted: bool = False, for_update: bool = False) -> Any | None:
        """Generic child lookup by id."""
        normalized_id = normalize_int(child_id, default=None, minimum=1)
        if normalized_id is None:
            return None

        query = self.session.query(model).filter(model.id == normalized_id)

        if not include_deleted and hasattr(model, "status"):
            query = query.filter(model.status != ITEM_STATUS_DELETED)

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
        """Generic child lookup by uid."""
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
            query = query.filter(model.status != ITEM_STATUS_DELETED)

        if for_update:
            query = self._with_for_update(query)

        return query.one_or_none()

    def _list_children(
        self,
        model_class: type[Any],
        *,
        draft_ref: Any | None = None,
        query: DraftChildQuery | Mapping[str, Any] | None = None,
        as_dict: bool = False,
    ) -> list[Any]:
        """Generic child list."""
        child_query = query if isinstance(query, DraftChildQuery) else DraftChildQuery.from_payload(query)

        if draft_ref is not None:
            draft = self.require_draft(draft_ref)
            child_query.draft_id = getattr(draft, "id", None)

        db_query = self.session.query(model_class)
        db_query = self._apply_child_filters(db_query, model_class, child_query)
        db_query = self._apply_default_sort(db_query, model_class)

        if child_query.offset:
            db_query = db_query.offset(child_query.offset)

        if child_query.limit:
            db_query = db_query.limit(child_query.limit)

        values = db_query.all()

        if as_dict:
            return [to_dict_or_payload(value) for value in values]

        return values

    def _add_child(
        self,
        *,
        child_kind: str,
        model_class: type[Any],
        draft_ref: Any,
        payload: Mapping[str, Any],
        draft_variant_ref: Any = None,
        user_id: Any = None,
        commit: bool = False,
        audit: bool = True,
    ) -> Any:
        """Generic add for asset/document/issue."""
        data = normalize_json_mapping(payload)

        try:
            draft = self.require_draft(draft_ref, include_deleted=False, for_update=True)

            if draft_is_locked_for_edit(draft) and child_kind != "validation_issue":
                raise CreativeLibraryDraftConflictError(f"Draft {draft_ref!r} cannot be edited.")

            draft_variant = None
            if draft_variant_ref is not None:
                draft_variant = self.require_variant(draft_variant_ref)

            creator = getattr(model_class, "create_from_payload", None)

            if callable(creator):
                child = creator(data, draft=draft, draft_variant=draft_variant, created_by_user_id=user_id)
            else:
                child = new_model_with_attrs(
                    model_class,
                    self._fallback_child_attrs(child_kind, data, draft=draft, draft_variant=draft_variant, user_id=user_id),
                )

            self.session.add(child)
            self.session.flush()

            if audit:
                self.create_audit_event(
                    event_type=f"{child_kind}_added",
                    user_id=user_id or getattr(draft, "owner_user_id", None),
                    draft=draft,
                    draft_variant=draft_variant,
                    asset=child if child_kind == "asset" else None,
                    document=child if child_kind == "document" else None,
                    issue=child if child_kind == "validation_issue" else None,
                    after=to_dict_or_payload(child),
                    commit=False,
                )

            self._finish_write(commit=commit)
            return child

        except Exception:
            if commit:
                self.rollback()
            raise

    def _update_child(
        self,
        *,
        child_kind: str,
        child_ref: Any,
        getter: Any,
        payload: Mapping[str, Any],
        user_id: Any = None,
        commit: bool = False,
        audit: bool = True,
    ) -> Any:
        """Generic child update."""
        data = normalize_json_mapping(payload)

        try:
            child = getter(child_ref, include_deleted=True, for_update=True)
            draft = self.get_draft_by_id(getattr(child, "draft_id", None), include_deleted=True)

            if draft is not None and draft_is_locked_for_edit(draft) and child_kind != "validation_issue":
                raise CreativeLibraryDraftConflictError(f"Draft child {child_ref!r} cannot be edited because draft is locked.")

            before = to_dict_or_payload(child)
            self._fallback_update_child(child, data, user_id=user_id)
            after = to_dict_or_payload(child)

            if audit:
                self.create_audit_event(
                    event_type=f"{child_kind}_updated",
                    user_id=user_id or getattr(draft, "owner_user_id", None),
                    draft=draft,
                    draft_variant=self.get_variant_by_id(getattr(child, "draft_variant_id", None), include_deleted=True),
                    asset=child if child_kind == "asset" else None,
                    document=child if child_kind == "document" else None,
                    issue=child if child_kind == "validation_issue" else None,
                    before=before,
                    after=after,
                    commit=False,
                )

            self._finish_write(commit=commit)
            return child

        except Exception:
            if commit:
                self.rollback()
            raise

    def _soft_delete_child(
        self,
        *,
        child_kind: str,
        child_ref: Any,
        getter: Any,
        user_id: Any = None,
        commit: bool = False,
        audit: bool = True,
    ) -> bool:
        """Generic child soft delete."""
        try:
            child = getter(child_ref, include_deleted=True, for_update=True)
            draft = self.get_draft_by_id(getattr(child, "draft_id", None), include_deleted=True)

            if draft is not None and draft_is_locked_for_edit(draft) and child_kind != "validation_issue":
                raise CreativeLibraryDraftConflictError(f"Draft child {child_ref!r} cannot be deleted because draft is locked.")

            before = to_dict_or_payload(child)
            self._mark_child_deleted(child, user_id=user_id)
            after = to_dict_or_payload(child)

            if audit:
                self.create_audit_event(
                    event_type=f"{child_kind}_deleted",
                    user_id=user_id or getattr(draft, "owner_user_id", None),
                    draft=draft,
                    draft_variant=self.get_variant_by_id(getattr(child, "draft_variant_id", None), include_deleted=True),
                    asset=child if child_kind == "asset" else None,
                    document=child if child_kind == "document" else None,
                    issue=child if child_kind == "validation_issue" else None,
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

    def _mark_child_deleted(self, child: Any, *, user_id: Any = None) -> None:
        """Marks generic child deleted."""
        if hasattr(child, "mark_deleted") and callable(child.mark_deleted):
            try:
                child.mark_deleted(user_id=user_id)
                return
            except TypeError:
                child.mark_deleted()
                return
            except Exception:
                pass

        if hasattr(child, "status"):
            child.status = ITEM_STATUS_DELETED
        if hasattr(child, "active"):
            child.active = False
        if hasattr(child, "visible"):
            child.visible = False
        if hasattr(child, "updated_by_user_id"):
            child.updated_by_user_id = normalize_user_id(user_id, default=None)
        if hasattr(child, "touch") and callable(child.touch):
            child.touch()

    # ------------------------------------------------------------------
    # Fallback attrs/update helpers
    # ------------------------------------------------------------------

    def _fallback_draft_attrs(
        self,
        payload: Mapping[str, Any],
        *,
        owner_user_id: Any,
        source_scope: Any,
        created_by_user_id: Any = None,
    ) -> dict[str, Any]:
        """Fallback attrs for draft creation."""
        data = normalize_json_mapping(payload)
        normalized_owner_user_id = normalize_user_id(owner_user_id, default=DEFAULT_USER_ID)
        normalized_source_scope = clean_string(source_scope, fallback=SOURCE_SCOPE_USER)

        return {
            "owner_user_id": normalized_owner_user_id,
            "owner_scope": owner_scope_for(source_scope=normalized_source_scope, owner_user_id=normalized_owner_user_id),
            "source_scope": normalized_source_scope,
            "mode": optional_string(data.get("mode")) or DRAFT_MODE_CREATE,
            "status": optional_string(data.get("status")) or DRAFT_STATUS_DRAFT,
            "stage": optional_string(data.get("stage")) or DRAFT_STAGE_CREATED,
            "target_item_id": normalize_int(data.get("target_item_id"), default=None, minimum=1),
            "target_vplib_uid": optional_string(data.get("target_vplib_uid") or data.get("vplib_uid")),
            "base_revision_id": normalize_int(data.get("base_revision_id"), default=None, minimum=1),
            "published_revision_id": normalize_int(data.get("published_revision_id"), default=None, minimum=1),
            "family_id": optional_string(data.get("family_id")),
            "package_id": optional_string(data.get("package_id")),
            "vplib_uid": optional_string(data.get("vplib_uid") or data.get("target_vplib_uid")),
            "title": optional_string(data.get("title") or data.get("label") or data.get("name")),
            "label": optional_string(data.get("label") or data.get("title") or data.get("name")),
            "name": optional_string(data.get("name") or data.get("label") or data.get("title")),
            "description": optional_string(data.get("description")),
            "family_payload": normalize_json_mapping(data.get("family_payload")),
            "classification_payload": normalize_json_mapping(data.get("classification_payload")),
            "manifest_payload": normalize_json_mapping(data.get("manifest_payload")),
            "modules_payload": normalize_json_mapping(data.get("modules_payload")),
            "generator_payload": normalize_json_mapping(data.get("generator_payload")),
            "validation_payload": normalize_json_mapping(data.get("validation_payload")),
            "payload": normalize_json_mapping(data.get("payload") or data),
            "meta": normalize_json_mapping(data.get("meta")),
            "metadata_json": normalize_json_mapping(data.get("metadata")),
            "created_by_user_id": normalize_user_id(created_by_user_id, default=None),
            "updated_by_user_id": normalize_user_id(created_by_user_id, default=None),
            "active": normalize_bool(data.get("active"), default=True),
            "visible": normalize_bool(data.get("visible"), default=True),
        }

    def _fallback_update_draft(self, draft: Any, payload: Mapping[str, Any], *, user_id: Any = None) -> None:
        """Fallback draft update."""
        data = normalize_json_mapping(payload)

        for field_name in (
            "mode",
            "status",
            "stage",
            "target_vplib_uid",
            "family_id",
            "package_id",
            "vplib_uid",
            "title",
            "label",
            "name",
            "description",
        ):
            if field_name in data and hasattr(draft, field_name):
                setattr(draft, field_name, optional_string(data.get(field_name)))

        for field_name in ("target_item_id", "base_revision_id", "published_revision_id"):
            if field_name in data and hasattr(draft, field_name):
                setattr(draft, field_name, normalize_int(data.get(field_name), default=None, minimum=1))

        for field_name in ("active", "visible", "locked"):
            if field_name in data and hasattr(draft, field_name):
                setattr(draft, field_name, normalize_bool(data.get(field_name), default=getattr(draft, field_name)))

        for field_name in (
            "family_payload",
            "classification_payload",
            "manifest_payload",
            "modules_payload",
            "generator_payload",
            "validation_payload",
            "payload",
            "meta",
            "metadata_json",
        ):
            source_names = (field_name, "metadata") if field_name == "metadata_json" else (field_name,)
            for source_name in source_names:
                if source_name in data and hasattr(draft, field_name):
                    setattr(draft, field_name, normalize_json_mapping(data.get(source_name)))
                    break

        if hasattr(draft, "updated_by_user_id"):
            draft.updated_by_user_id = normalize_user_id(user_id, default=None)

        if hasattr(draft, "touch") and callable(draft.touch):
            draft.touch()

    def _fallback_variant_attrs(self, payload: Mapping[str, Any], *, draft: Any, user_id: Any = None) -> dict[str, Any]:
        """Fallback attrs for draft variant."""
        data = normalize_json_mapping(payload)
        return {
            "draft_id": getattr(draft, "id", None),
            "variant_id": optional_string(data.get("variant_id")),
            "variant_key": optional_string(data.get("variant_key") or data.get("key")),
            "status": optional_string(data.get("status")) or ITEM_STATUS_ACTIVE,
            "sort_order": normalize_int(data.get("sort_order"), default=0, minimum=0) or 0,
            "definition_values_json": normalize_json_mapping(data.get("definition_values") or data.get("definition_values_json")),
            "summary_json": normalize_json_mapping(data.get("summary") or data.get("summary_json")),
            "payload": normalize_json_mapping(data.get("payload") or data),
            "meta": normalize_json_mapping(data.get("meta")),
            "metadata_json": normalize_json_mapping(data.get("metadata")),
            "created_by_user_id": normalize_user_id(user_id, default=None),
            "updated_by_user_id": normalize_user_id(user_id, default=None),
            "active": normalize_bool(data.get("active"), default=True),
            "visible": normalize_bool(data.get("visible"), default=True),
        }

    def _fallback_child_attrs(self, child_kind: str, payload: Mapping[str, Any], *, draft: Any, draft_variant: Any = None, user_id: Any = None) -> dict[str, Any]:
        """Fallback attrs for generic child."""
        data = normalize_json_mapping(payload)
        attrs = {
            "draft_id": getattr(draft, "id", None),
            "draft_variant_id": getattr(draft_variant, "id", None),
            "status": optional_string(data.get("status")) or ITEM_STATUS_ACTIVE,
            "sort_order": normalize_int(data.get("sort_order"), default=0, minimum=0) or 0,
            "payload": normalize_json_mapping(data.get("payload") or data),
            "meta": normalize_json_mapping(data.get("meta")),
            "metadata_json": normalize_json_mapping(data.get("metadata")),
            "created_by_user_id": normalize_user_id(user_id, default=None),
            "updated_by_user_id": normalize_user_id(user_id, default=None),
            "active": normalize_bool(data.get("active"), default=True),
            "visible": normalize_bool(data.get("visible"), default=True),
        }

        if child_kind == "asset":
            attrs.update(
                {
                    "asset_kind": optional_string(data.get("asset_kind")),
                    "role": optional_string(data.get("role")) or ASSET_ROLE_ATTACHMENT,
                    "source_path": optional_string(data.get("source_path")),
                    "storage_path": optional_string(data.get("storage_path")),
                    "library_file_id": normalize_int(data.get("library_file_id"), default=None, minimum=1),
                    "file_version_id": normalize_int(data.get("file_version_id"), default=None, minimum=1),
                    "file_uid": optional_string(data.get("file_uid")),
                    "filename": optional_string(data.get("filename") or data.get("original_filename")),
                    "mime_type": optional_string(data.get("mime_type")),
                    "size_bytes": normalize_int(data.get("size_bytes"), default=None, minimum=0),
                    "sha256": optional_string(data.get("sha256")),
                }
            )

        elif child_kind == "document":
            attrs.update(
                {
                    "document_kind": optional_string(data.get("document_kind")) or DOCUMENT_KIND_DOCUMENT,
                    "document_type": optional_string(data.get("document_type")),
                    "field_key": optional_string(data.get("field_key")),
                    "title": optional_string(data.get("title") or data.get("label")),
                    "url": optional_string(data.get("url")),
                    "storage_path": optional_string(data.get("storage_path")),
                    "library_file_id": normalize_int(data.get("library_file_id"), default=None, minimum=1),
                    "file_version_id": normalize_int(data.get("file_version_id"), default=None, minimum=1),
                    "file_uid": optional_string(data.get("file_uid")),
                }
            )

        elif child_kind == "validation_issue":
            severity = optional_string(data.get("severity")) or ISSUE_SEVERITY_ERROR
            attrs.update(
                {
                    "severity": severity,
                    "code": optional_string(data.get("code")),
                    "message": optional_string(data.get("message")),
                    "field_key": optional_string(data.get("field_key")),
                    "path": optional_string(data.get("path")),
                    "blocking": normalize_bool(data.get("blocking"), default=severity in {ISSUE_SEVERITY_ERROR, ISSUE_SEVERITY_BLOCKING}),
                    "resolved": normalize_bool(data.get("resolved"), default=False),
                }
            )

        return attrs

    def _fallback_update_child(self, child: Any, payload: Mapping[str, Any], *, user_id: Any = None) -> None:
        """Fallback child update."""
        data = normalize_json_mapping(payload)

        for field_name in (
            "status",
            "variant_id",
            "variant_key",
            "asset_kind",
            "role",
            "source_path",
            "storage_path",
            "file_uid",
            "filename",
            "mime_type",
            "sha256",
            "document_kind",
            "document_type",
            "field_key",
            "title",
            "url",
            "severity",
            "code",
            "message",
            "path",
        ):
            if field_name in data and hasattr(child, field_name):
                setattr(child, field_name, optional_string(data.get(field_name)))

        for field_name in ("sort_order", "library_file_id", "file_version_id", "size_bytes"):
            if field_name in data and hasattr(child, field_name):
                setattr(child, field_name, normalize_int(data.get(field_name), default=None, minimum=0))

        for field_name in ("active", "visible", "blocking", "resolved"):
            if field_name in data and hasattr(child, field_name):
                setattr(child, field_name, normalize_bool(data.get(field_name), default=getattr(child, field_name)))

        for field_name in ("definition_values_json", "summary_json", "payload", "meta", "metadata_json"):
            source_names = {
                "definition_values_json": ("definition_values", "definition_values_json"),
                "summary_json": ("summary", "summary_json"),
                "metadata_json": ("metadata", "metadata_json"),
            }.get(field_name, (field_name,))

            for source_name in source_names:
                if source_name in data and hasattr(child, field_name):
                    setattr(child, field_name, normalize_json_mapping(data.get(source_name)))
                    break

        if hasattr(child, "updated_by_user_id"):
            child.updated_by_user_id = normalize_user_id(user_id, default=None)

        if hasattr(child, "touch") and callable(child.touch):
            child.touch()

    def _fallback_draft_summary(self, draft: Any) -> dict[str, Any]:
        """Fallback draft summary."""
        draft_id = getattr(draft, "id", None)

        try:
            variant_count = len(self.list_variants(draft_id, as_dict=False)) if draft_id is not None else 0
        except Exception:
            variant_count = 0

        try:
            asset_count = len(self.list_assets(draft_id, as_dict=False)) if draft_id is not None else 0
        except Exception:
            asset_count = 0

        try:
            document_count = len(self.list_documents(draft_id, as_dict=False)) if draft_id is not None else 0
        except Exception:
            document_count = 0

        try:
            issues = self.list_validation_issues(draft_id, as_dict=False) if draft_id is not None else []
            issue_count = len(issues)
            blocking_issue_count = len([issue for issue in issues if issue_is_blocking(issue)])
        except Exception:
            issue_count = 0
            blocking_issue_count = 0

        return {
            "draft_id": draft_id,
            "draft_uid": getattr(draft, "draft_uid", None),
            "status": enum_value(getattr(draft, "status", None)),
            "stage": enum_value(getattr(draft, "stage", None)),
            "variant_count": variant_count,
            "asset_count": asset_count,
            "document_count": document_count,
            "validation_issue_count": issue_count,
            "blocking_issue_count": blocking_issue_count,
            "valid": blocking_issue_count == 0,
        }


# ---------------------------------------------------------------------------
# Factory helpers
# ---------------------------------------------------------------------------

def create_creative_library_draft_repository(session: Any | None = None) -> CreativeLibraryDraftRepository:
    """Factory for dependency injection."""
    return CreativeLibraryDraftRepository(session=session)


@lru_cache(maxsize=1)
def get_repository_version() -> str:
    """Cached repository version helper."""
    return CREATIVE_LIBRARY_DRAFT_REPOSITORY_VERSION


def clear_creative_library_draft_repository_caches() -> dict[str, Any]:
    """Clears import/static caches."""
    cleared: list[str] = []

    for cached_func in (
        _load_db,
        _load_draft_models_module,
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
    "CREATIVE_LIBRARY_DRAFT_REPOSITORY_VERSION",
    "DEFAULT_USER_ID",
    "SOURCE_SCOPE_SYSTEM",
    "SOURCE_SCOPE_USER",
    "SOURCE_SCOPE_IMPORTED",
    "SOURCE_SCOPE_GENERATED",
    "DRAFT_MODE_CREATE",
    "DRAFT_MODE_UPDATE",
    "DRAFT_MODE_IMPORT",
    "DRAFT_MODE_GENERATE",
    "DRAFT_STATUS_DRAFT",
    "DRAFT_STATUS_VALIDATING",
    "DRAFT_STATUS_VALID",
    "DRAFT_STATUS_INVALID",
    "DRAFT_STATUS_PUBLISHED",
    "DRAFT_STATUS_DISCARDED",
    "DRAFT_STATUS_DELETED",
    "DRAFT_STAGE_CREATED",
    "DRAFT_STAGE_EDITING",
    "DRAFT_STAGE_VALIDATION",
    "DRAFT_STAGE_READY_TO_PUBLISH",
    "DRAFT_STAGE_PUBLISHED",
    "DRAFT_STAGE_DISCARDED",
    "ITEM_STATUS_ACTIVE",
    "ITEM_STATUS_INACTIVE",
    "ITEM_STATUS_DELETED",
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
    "CreativeLibraryDraftRepositoryError",
    "CreativeLibraryDraftRepositoryImportError",
    "CreativeLibraryDraftNotFoundError",
    "CreativeLibraryDraftVariantNotFoundError",
    "CreativeLibraryDraftAssetNotFoundError",
    "CreativeLibraryDraftDocumentNotFoundError",
    "CreativeLibraryDraftValidationIssueNotFoundError",
    "CreativeLibraryDraftConflictError",

    # Dataclasses
    "DraftQuery",
    "DraftChildQuery",
    "DraftWriteResult",

    # Repository
    "CreativeLibraryDraftRepository",
    "create_creative_library_draft_repository",

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
    "set_attrs_if_present",
    "new_model_with_attrs",
    "draft_ref_is_numeric",
    "draft_is_locked_for_edit",
    "issue_is_blocking",
    "get_repository_version",
    "clear_creative_library_draft_repository_caches",
]