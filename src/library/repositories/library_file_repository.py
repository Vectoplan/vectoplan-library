# services/vectoplan-library/src/library/repositories/library_file_repository.py
"""
Repository for VECTOPLAN Library Files.

Diese Datei kapselt alle DB-Zugriffe auf:

- library_files
- library_file_versions
- library_file_links
- library_file_audit_events

Ziel:

    Upload / Generator / Import
        -> LibraryFileService
        -> LibraryFileRepository
        -> PostgreSQL File Tables
        -> File links to Creative Library / Draft / Definition / Taxonomy

Architekturregeln:

- Repository enthält keine Flask-Routes.
- Repository enthält keine Storage-Implementierung.
- Repository schreibt keine Dateien ins Dateisystem.
- Repository validiert keine MIME-/Extension-/Size-Regeln fachlich.
- Repository erzeugt keine Tabellen.
- Repository führt keine Migration aus.
- Repository führt kein db.create_all() aus.
- Repository öffnet keine aktive DB-Verbindung beim Import.
- DB-Zugriffe laufen nur in expliziten Methoden.
- Storage-Entscheidungen und Upload-Validierung liegen im library_file_service.py.
- Dieses Repository speichert Metadaten, Versionen, Links und Audit Events.

Phase 1:

- user_id darf weiterhin 1 sein.
- owner_user_id=1 bei User-Uploads.
- owner_scope="user:1" bei User-Uploads.
- Große Dateien sollten per storage_path/object storage referenziert werden.
- postgres_bytea ist vorbereitet, aber nicht Default.
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

LIBRARY_FILE_REPOSITORY_VERSION: Final[str] = "vectoplan_library.repository.library_file.v1"

DEFAULT_USER_ID: Final[int] = 1

STATUS_ACTIVE: Final[str] = "active"
STATUS_REPLACED: Final[str] = "replaced"
STATUS_DELETED: Final[str] = "deleted"
STATUS_QUARANTINED: Final[str] = "quarantined"

SOURCE_SCOPE_USER: Final[str] = "user"
SOURCE_SCOPE_SYSTEM: Final[str] = "system"
SOURCE_SCOPE_IMPORTED: Final[str] = "imported"
SOURCE_SCOPE_GENERATED: Final[str] = "generated"
SOURCE_SCOPE_EXTERNAL: Final[str] = "external"

CONTEXT_CREATIVE_ITEM: Final[str] = "creative_item"
CONTEXT_CREATIVE_VARIANT: Final[str] = "creative_variant"
CONTEXT_CREATIVE_REVISION: Final[str] = "creative_revision"
CONTEXT_CREATIVE_DRAFT: Final[str] = "creative_draft"
CONTEXT_DEFINITION: Final[str] = "definition"
CONTEXT_TAXONOMY_NODE: Final[str] = "taxonomy_node"
CONTEXT_USER_INVENTORY_SLOT: Final[str] = "user_inventory_slot"
CONTEXT_OTHER: Final[str] = "other"

ROLE_PRIMARY: Final[str] = "primary"
ROLE_ATTACHMENT: Final[str] = "attachment"
ROLE_PREVIEW: Final[str] = "preview"
ROLE_RENDER_MODEL: Final[str] = "render_model"
ROLE_DOCUMENT: Final[str] = "document"

MAX_DEFAULT_LIMIT: Final[int] = 500
DEFAULT_LIMIT: Final[int] = 100


# ---------------------------------------------------------------------------
# Exceptions
# ---------------------------------------------------------------------------

class LibraryFileRepositoryError(RuntimeError):
    """Base error for LibraryFileRepository."""


class LibraryFileRepositoryImportError(LibraryFileRepositoryError):
    """Raised when db/model imports fail."""


class LibraryFileNotFoundError(LibraryFileRepositoryError):
    """Raised when a file/version/link cannot be found."""


class LibraryFileConflictError(LibraryFileRepositoryError):
    """Raised when an operation conflicts with current state."""


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

    raise LibraryFileRepositoryImportError(
        "Could not import SQLAlchemy extension `db`. "
        + " | ".join(errors)
    )


@lru_cache(maxsize=1)
def _load_file_models_module() -> ModuleType:
    """Loads models.library_files defensively."""
    errors: list[str] = []

    for module_name in (
        "models.library_files",
        "src.models.library_files",
        "vectoplan_library.models.library_files",
    ):
        try:
            return importlib.import_module(module_name)
        except Exception as exc:
            errors.append(f"{module_name}: {type(exc).__name__}: {exc}")

    raise LibraryFileRepositoryImportError(
        "Could not import library file models. "
        + " | ".join(errors)
    )


def _db() -> Any:
    """Short alias for lazy db access."""
    return _load_db()


def _models() -> ModuleType:
    """Short alias for lazy model access."""
    return _load_file_models_module()


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

    if text in {"1", "true", "yes", "y", "ja", "on", "enabled", "active", "visible", "primary"}:
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
        return str(helper(source_scope=source_scope, owner_user_id=owner_user_id))

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
        "file_uid",
        "version_uid",
        "link_uid",
        "owner_user_id",
        "owner_scope",
        "document_type",
        "asset_kind",
        "original_filename",
        "safe_filename",
        "mime_type",
        "extension",
        "size_bytes",
        "sha256",
        "status",
        "active",
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


# ---------------------------------------------------------------------------
# Dataclasses
# ---------------------------------------------------------------------------

@dataclass(slots=True)
class FileQuery:
    """Structured file query options."""

    user_id: int | None = None
    owner_user_id: int | None = None
    owner_scope: str | None = None
    source_scope: str | None = None
    document_type: str | None = None
    asset_kind: str | None = None
    mime_type: str | None = None
    extension: str | None = None
    sha256: str | None = None
    status: str | None = None
    active_only: bool = True
    visible_only: bool = False
    include_deleted: bool = False
    limit: int = DEFAULT_LIMIT
    offset: int = 0

    @classmethod
    def from_payload(cls, payload: Mapping[str, Any] | None = None, **kwargs: Any) -> "FileQuery":
        data = normalize_json_mapping(payload)
        data.update({key: value for key, value in kwargs.items() if value is not None})

        return cls(
            user_id=normalize_user_id(data.get("user_id"), default=None),
            owner_user_id=normalize_user_id(data.get("owner_user_id"), default=None),
            owner_scope=optional_string(data.get("owner_scope")),
            source_scope=optional_string(data.get("source_scope")),
            document_type=optional_string(data.get("document_type")),
            asset_kind=optional_string(data.get("asset_kind")),
            mime_type=optional_string(data.get("mime_type")),
            extension=optional_string(data.get("extension")),
            sha256=optional_string(data.get("sha256")),
            status=optional_string(data.get("status")),
            active_only=normalize_bool(data.get("active_only"), default=True),
            visible_only=normalize_bool(data.get("visible_only"), default=False),
            include_deleted=normalize_bool(data.get("include_deleted"), default=False),
            limit=normalize_int(data.get("limit"), default=DEFAULT_LIMIT, minimum=1, maximum=MAX_DEFAULT_LIMIT) or DEFAULT_LIMIT,
            offset=normalize_int(data.get("offset"), default=0, minimum=0) or 0,
        )

    def resolved_owner_scope(self) -> str | None:
        if self.owner_scope:
            return self.owner_scope

        user_id = self.owner_user_id or self.user_id
        if user_id is not None:
            return f"user:{user_id}"

        return None

    def to_dict(self) -> dict[str, Any]:
        return {
            "user_id": self.user_id,
            "owner_user_id": self.owner_user_id,
            "owner_scope": self.owner_scope,
            "source_scope": self.source_scope,
            "document_type": self.document_type,
            "asset_kind": self.asset_kind,
            "mime_type": self.mime_type,
            "extension": self.extension,
            "sha256": self.sha256,
            "status": self.status,
            "active_only": self.active_only,
            "visible_only": self.visible_only,
            "include_deleted": self.include_deleted,
            "limit": self.limit,
            "offset": self.offset,
        }


@dataclass(slots=True)
class FileLinkQuery:
    """Structured file link query options."""

    user_id: int | None = None
    context_type: str | None = None
    context_db_id: int | None = None
    context_id: str | None = None
    context_uid: str | None = None
    vplib_uid: str | None = None
    family_id: str | None = None
    package_id: str | None = None
    variant_id: str | None = None
    revision_hash: str | None = None
    field_key: str | None = None
    document_type: str | None = None
    role: str | None = None
    primary_only: bool = False
    active_only: bool = True
    include_deleted: bool = False
    limit: int = DEFAULT_LIMIT
    offset: int = 0

    @classmethod
    def from_payload(cls, payload: Mapping[str, Any] | None = None, **kwargs: Any) -> "FileLinkQuery":
        data = normalize_json_mapping(payload)
        data.update({key: value for key, value in kwargs.items() if value is not None})

        return cls(
            user_id=normalize_user_id(data.get("user_id"), default=None),
            context_type=optional_string(data.get("context_type")),
            context_db_id=normalize_int(data.get("context_db_id"), default=None, minimum=1),
            context_id=optional_string(data.get("context_id")),
            context_uid=optional_string(data.get("context_uid")),
            vplib_uid=optional_string(data.get("vplib_uid")),
            family_id=optional_string(data.get("family_id")),
            package_id=optional_string(data.get("package_id")),
            variant_id=optional_string(data.get("variant_id")),
            revision_hash=optional_string(data.get("revision_hash")),
            field_key=optional_string(data.get("field_key")),
            document_type=optional_string(data.get("document_type")),
            role=optional_string(data.get("role")),
            primary_only=normalize_bool(data.get("primary_only"), default=False),
            active_only=normalize_bool(data.get("active_only"), default=True),
            include_deleted=normalize_bool(data.get("include_deleted"), default=False),
            limit=normalize_int(data.get("limit"), default=DEFAULT_LIMIT, minimum=1, maximum=MAX_DEFAULT_LIMIT) or DEFAULT_LIMIT,
            offset=normalize_int(data.get("offset"), default=0, minimum=0) or 0,
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "user_id": self.user_id,
            "context_type": self.context_type,
            "context_db_id": self.context_db_id,
            "context_id": self.context_id,
            "context_uid": self.context_uid,
            "vplib_uid": self.vplib_uid,
            "family_id": self.family_id,
            "package_id": self.package_id,
            "variant_id": self.variant_id,
            "revision_hash": self.revision_hash,
            "field_key": self.field_key,
            "document_type": self.document_type,
            "role": self.role,
            "primary_only": self.primary_only,
            "active_only": self.active_only,
            "include_deleted": self.include_deleted,
            "limit": self.limit,
            "offset": self.offset,
        }


@dataclass(slots=True)
class FileWriteResult:
    """JSON-compatible write result."""

    ok: bool
    action: str
    file_uid: str | None = None
    version_uid: str | None = None
    link_uid: str | None = None
    file_id: int | None = None
    version_id: int | None = None
    link_id: int | None = None
    created: bool = False
    updated: bool = False
    deleted: bool = False
    payload: dict[str, Any] = field(default_factory=dict)
    errors: list[str] = field(default_factory=list)

    def add_error(self, error: Any) -> None:
        self.ok = False
        self.errors.append(str(error))

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema_version": LIBRARY_FILE_REPOSITORY_VERSION,
            "ok": self.ok,
            "action": self.action,
            "file_uid": self.file_uid,
            "version_uid": self.version_uid,
            "link_uid": self.link_uid,
            "file_id": self.file_id,
            "version_id": self.version_id,
            "link_id": self.link_id,
            "created": self.created,
            "updated": self.updated,
            "deleted": self.deleted,
            "payload": normalize_json_mapping(self.payload),
            "errors": list(self.errors),
        }


# ---------------------------------------------------------------------------
# Repository
# ---------------------------------------------------------------------------

class LibraryFileRepository:
    """
    SQLAlchemy repository for Library Files.

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
    # File reads
    # ------------------------------------------------------------------

    def get_file_by_id(
        self,
        file_id: Any,
        *,
        include_deleted: bool = False,
        for_update: bool = False,
    ) -> Any | None:
        """Returns LibraryFile by DB id."""
        normalized_id = normalize_int(file_id, default=None, minimum=1)
        if normalized_id is None:
            return None

        model = self.models.LibraryFile
        query = self.session.query(model).filter(model.id == normalized_id)

        if not include_deleted:
            query = query.filter(model.status != STATUS_DELETED)

        if for_update:
            query = self._with_for_update(query)

        return query.one_or_none()

    def get_file_by_uid(
        self,
        file_uid: Any,
        *,
        include_deleted: bool = False,
        for_update: bool = False,
    ) -> Any | None:
        """Returns LibraryFile by file_uid."""
        uid = optional_string(file_uid)
        if not uid:
            return None

        model = self.models.LibraryFile
        query = self.session.query(model).filter(model.file_uid == uid)

        if not include_deleted:
            query = query.filter(model.status != STATUS_DELETED)

        if for_update:
            query = self._with_for_update(query)

        return query.one_or_none()

    def get_file(
        self,
        file_ref: Any,
        *,
        include_deleted: bool = False,
        for_update: bool = False,
    ) -> Any | None:
        """Returns file by id or file_uid."""
        if normalize_int(file_ref, default=None, minimum=1) is not None and str(file_ref).isdigit():
            return self.get_file_by_id(file_ref, include_deleted=include_deleted, for_update=for_update)

        return self.get_file_by_uid(file_ref, include_deleted=include_deleted, for_update=for_update)

    def require_file(
        self,
        file_ref: Any,
        *,
        include_deleted: bool = False,
        for_update: bool = False,
    ) -> Any:
        """Returns file or raises."""
        file = self.get_file(file_ref, include_deleted=include_deleted, for_update=for_update)
        if file is None:
            raise LibraryFileNotFoundError(f"Library file {file_ref!r} was not found.")
        return file

    def list_files(
        self,
        *,
        query: FileQuery | Mapping[str, Any] | None = None,
        as_dict: bool = False,
    ) -> list[Any]:
        """Lists LibraryFile rows."""
        file_query = query if isinstance(query, FileQuery) else FileQuery.from_payload(query)
        model = self.models.LibraryFile
        db_query = self.session.query(model)

        owner_scope = file_query.resolved_owner_scope()
        if owner_scope:
            db_query = db_query.filter(model.owner_scope == owner_scope)

        if file_query.source_scope:
            db_query = db_query.filter(model.source_scope == file_query.source_scope)

        if file_query.owner_user_id is not None:
            db_query = db_query.filter(model.owner_user_id == file_query.owner_user_id)

        if file_query.document_type:
            db_query = db_query.filter(model.document_type == file_query.document_type)

        if file_query.asset_kind:
            db_query = db_query.filter(model.asset_kind == file_query.asset_kind)

        if file_query.mime_type:
            db_query = db_query.filter(model.mime_type == file_query.mime_type)

        if file_query.extension:
            db_query = db_query.filter(model.extension == file_query.extension)

        if file_query.sha256:
            db_query = db_query.filter(model.sha256 == file_query.sha256)

        if file_query.status:
            db_query = db_query.filter(model.status == file_query.status)

        if file_query.active_only:
            db_query = db_query.filter(model.active.is_(True))

        if file_query.visible_only:
            db_query = db_query.filter(model.visible.is_(True))

        if not file_query.include_deleted:
            db_query = db_query.filter(model.status != STATUS_DELETED)

        db_query = db_query.order_by(model.created_at.desc(), model.id.desc())

        if file_query.offset:
            db_query = db_query.offset(file_query.offset)

        if file_query.limit:
            db_query = db_query.limit(file_query.limit)

        values = db_query.all()

        if as_dict:
            return [to_dict_or_payload(value) for value in values]

        return values

    def list_file_payloads(self, *, query: FileQuery | Mapping[str, Any] | None = None) -> list[dict[str, Any]]:
        """Lists LibraryFile rows as dicts."""
        return self.list_files(query=query, as_dict=True)

    # ------------------------------------------------------------------
    # Version reads
    # ------------------------------------------------------------------

    def get_version_by_id(
        self,
        version_id: Any,
        *,
        include_deleted: bool = False,
        for_update: bool = False,
    ) -> Any | None:
        """Returns LibraryFileVersion by DB id."""
        normalized_id = normalize_int(version_id, default=None, minimum=1)
        if normalized_id is None:
            return None

        model = self.models.LibraryFileVersion
        query = self.session.query(model).filter(model.id == normalized_id)

        if not include_deleted:
            query = query.filter(model.status != STATUS_DELETED)

        if for_update:
            query = self._with_for_update(query)

        return query.one_or_none()

    def get_version_by_uid(
        self,
        version_uid: Any,
        *,
        include_deleted: bool = False,
        for_update: bool = False,
    ) -> Any | None:
        """Returns LibraryFileVersion by version_uid."""
        uid = optional_string(version_uid)
        if not uid:
            return None

        model = self.models.LibraryFileVersion
        query = self.session.query(model).filter(model.version_uid == uid)

        if not include_deleted:
            query = query.filter(model.status != STATUS_DELETED)

        if for_update:
            query = self._with_for_update(query)

        return query.one_or_none()

    def get_version(
        self,
        version_ref: Any,
        *,
        include_deleted: bool = False,
        for_update: bool = False,
    ) -> Any | None:
        """Returns version by id or uid."""
        if normalize_int(version_ref, default=None, minimum=1) is not None and str(version_ref).isdigit():
            return self.get_version_by_id(version_ref, include_deleted=include_deleted, for_update=for_update)

        return self.get_version_by_uid(version_ref, include_deleted=include_deleted, for_update=for_update)

    def require_version(
        self,
        version_ref: Any,
        *,
        include_deleted: bool = False,
        for_update: bool = False,
    ) -> Any:
        """Returns version or raises."""
        version = self.get_version(version_ref, include_deleted=include_deleted, for_update=for_update)
        if version is None:
            raise LibraryFileNotFoundError(f"Library file version {version_ref!r} was not found.")
        return version

    def list_versions(
        self,
        file_ref: Any,
        *,
        active_only: bool = False,
        include_deleted: bool = False,
        as_dict: bool = False,
    ) -> list[Any]:
        """Lists versions for a file."""
        file = self.require_file(file_ref, include_deleted=include_deleted)
        model = self.models.LibraryFileVersion

        query = self.session.query(model).filter(model.file_id == file.id)

        if active_only:
            query = query.filter(model.active.is_(True))

        if not include_deleted:
            query = query.filter(model.status != STATUS_DELETED)

        query = query.order_by(model.version_index.asc(), model.id.asc())

        values = query.all()

        if as_dict:
            return [to_dict_or_payload(value) for value in values]

        return values

    def get_current_version(self, file_ref: Any) -> Any | None:
        """Returns current version for a file."""
        file = self.require_file(file_ref)

        if getattr(file, "current_version", None) is not None:
            return file.current_version

        if getattr(file, "current_version_id", None):
            return self.get_version_by_id(file.current_version_id)

        versions = self.list_versions(file.id, active_only=True, include_deleted=False)
        if not versions:
            return None

        versions.sort(key=lambda item: normalize_int(getattr(item, "version_index", 0), default=0) or 0, reverse=True)
        return versions[0]

    # ------------------------------------------------------------------
    # Link reads
    # ------------------------------------------------------------------

    def get_link_by_id(
        self,
        link_id: Any,
        *,
        include_deleted: bool = False,
        for_update: bool = False,
    ) -> Any | None:
        """Returns LibraryFileLink by DB id."""
        normalized_id = normalize_int(link_id, default=None, minimum=1)
        if normalized_id is None:
            return None

        model = self.models.LibraryFileLink
        query = self.session.query(model).filter(model.id == normalized_id)

        if not include_deleted:
            query = query.filter(model.status != STATUS_DELETED)

        if for_update:
            query = self._with_for_update(query)

        return query.one_or_none()

    def get_link_by_uid(
        self,
        link_uid: Any,
        *,
        include_deleted: bool = False,
        for_update: bool = False,
    ) -> Any | None:
        """Returns LibraryFileLink by link_uid."""
        uid = optional_string(link_uid)
        if not uid:
            return None

        model = self.models.LibraryFileLink
        query = self.session.query(model).filter(model.link_uid == uid)

        if not include_deleted:
            query = query.filter(model.status != STATUS_DELETED)

        if for_update:
            query = self._with_for_update(query)

        return query.one_or_none()

    def get_link(
        self,
        link_ref: Any,
        *,
        include_deleted: bool = False,
        for_update: bool = False,
    ) -> Any | None:
        """Returns link by id or uid."""
        if normalize_int(link_ref, default=None, minimum=1) is not None and str(link_ref).isdigit():
            return self.get_link_by_id(link_ref, include_deleted=include_deleted, for_update=for_update)

        return self.get_link_by_uid(link_ref, include_deleted=include_deleted, for_update=for_update)

    def require_link(
        self,
        link_ref: Any,
        *,
        include_deleted: bool = False,
        for_update: bool = False,
    ) -> Any:
        """Returns link or raises."""
        link = self.get_link(link_ref, include_deleted=include_deleted, for_update=for_update)
        if link is None:
            raise LibraryFileNotFoundError(f"Library file link {link_ref!r} was not found.")
        return link

    def list_links(
        self,
        *,
        query: FileLinkQuery | Mapping[str, Any] | None = None,
        as_dict: bool = False,
        include_file: bool = False,
        include_version: bool = False,
    ) -> list[Any]:
        """Lists LibraryFileLink rows."""
        link_query = query if isinstance(query, FileLinkQuery) else FileLinkQuery.from_payload(query)
        model = self.models.LibraryFileLink

        db_query = self.session.query(model)

        for field_name in (
            "user_id",
            "context_type",
            "context_db_id",
            "context_id",
            "context_uid",
            "vplib_uid",
            "family_id",
            "package_id",
            "variant_id",
            "revision_hash",
            "field_key",
            "document_type",
            "role",
        ):
            value = getattr(link_query, field_name)
            if value is not None:
                db_query = db_query.filter(getattr(model, field_name) == value)

        if link_query.primary_only:
            db_query = db_query.filter(model.is_primary.is_(True))

        if link_query.active_only:
            db_query = db_query.filter(model.active.is_(True))

        if not link_query.include_deleted:
            db_query = db_query.filter(model.status != STATUS_DELETED)

        db_query = db_query.order_by(model.sort_order.asc(), model.id.asc())

        if link_query.offset:
            db_query = db_query.offset(link_query.offset)

        if link_query.limit:
            db_query = db_query.limit(link_query.limit)

        values = db_query.all()

        if as_dict:
            return [
                value.to_dict(include_file=include_file, include_version=include_version)
                if hasattr(value, "to_dict")
                else to_dict_or_payload(value)
                for value in values
            ]

        return values

    def list_link_payloads(
        self,
        *,
        query: FileLinkQuery | Mapping[str, Any] | None = None,
        include_file: bool = True,
        include_version: bool = False,
    ) -> list[dict[str, Any]]:
        """Lists links as dicts."""
        return self.list_links(
            query=query,
            as_dict=True,
            include_file=include_file,
            include_version=include_version,
        )

    def list_context_files(
        self,
        *,
        context_type: Any,
        context_id: Any = None,
        context_db_id: Any = None,
        context_uid: Any = None,
        user_id: Any = None,
        field_key: Any = None,
        document_type: Any = None,
        active_only: bool = True,
    ) -> list[dict[str, Any]]:
        """Lists files linked to a specific context."""
        query = FileLinkQuery(
            user_id=normalize_user_id(user_id, default=None),
            context_type=optional_string(context_type),
            context_id=optional_string(context_id),
            context_db_id=normalize_int(context_db_id, default=None, minimum=1),
            context_uid=optional_string(context_uid),
            field_key=optional_string(field_key),
            document_type=optional_string(document_type),
            active_only=active_only,
            include_deleted=not active_only,
            limit=MAX_DEFAULT_LIMIT,
        )
        return self.list_link_payloads(query=query, include_file=True, include_version=True)

    # ------------------------------------------------------------------
    # File writes
    # ------------------------------------------------------------------

    def create_file(
        self,
        payload: Mapping[str, Any],
        *,
        owner_user_id: Any = DEFAULT_USER_ID,
        source_scope: Any = SOURCE_SCOPE_USER,
        created_by_user_id: Any = None,
        commit: bool = False,
        audit: bool = True,
    ) -> Any:
        """Creates a logical LibraryFile row."""
        data = normalize_json_mapping(payload)

        try:
            file = self.models.LibraryFile.create_from_payload(
                data,
                owner_user_id=owner_user_id,
                source_scope=source_scope,
                created_by_user_id=created_by_user_id,
            )
            self.session.add(file)
            self.session.flush()

            if audit:
                self.create_audit_event(
                    event_type="created",
                    user_id=created_by_user_id or owner_user_id,
                    file=file,
                    after=file.to_dict() if hasattr(file, "to_dict") else to_dict_or_payload(file),
                    commit=False,
                )

            self._finish_write(commit=commit)
            return file

        except Exception:
            if commit:
                self.rollback()
            raise

    def update_file_metadata(
        self,
        file_ref: Any,
        payload: Mapping[str, Any],
        *,
        user_id: Any = None,
        commit: bool = False,
        audit: bool = True,
    ) -> Any:
        """Updates mutable LibraryFile metadata, not file bytes."""
        data = normalize_json_mapping(payload)

        try:
            file = self.require_file(file_ref, include_deleted=True, for_update=True)
            before = file.to_dict() if hasattr(file, "to_dict") else to_dict_or_payload(file)

            for field_name, max_length in (
                ("document_type", 120),
                ("asset_kind", 80),
                ("original_filename", 512),
                ("safe_filename", 512),
                ("extension", 32),
                ("mime_type", 160),
                ("storage_backend", 80),
                ("status", 40),
            ):
                if field_name in data and hasattr(file, field_name):
                    setattr(file, field_name, optional_string(data.get(field_name), max_length=max_length))

            for field_name in ("storage_path", "external_uri", "quarantine_reason"):
                if field_name in data and hasattr(file, field_name):
                    setattr(file, field_name, optional_string(data.get(field_name)))

            for field_name in ("active", "visible", "locked"):
                if field_name in data and hasattr(file, field_name):
                    setattr(file, field_name, normalize_bool(data.get(field_name), default=getattr(file, field_name)))

            if "payload" in data:
                file.payload = normalize_json_mapping(data.get("payload"))

            if "meta" in data:
                file.meta = normalize_json_mapping(data.get("meta"))

            if "metadata" in data or "metadata_json" in data:
                file.metadata_json = normalize_json_mapping(data.get("metadata") or data.get("metadata_json"))

            if hasattr(file, "updated_by_user_id"):
                updater_id = normalize_user_id(user_id, default=None)
                if updater_id is not None:
                    file.updated_by_user_id = updater_id

            if hasattr(file, "touch") and callable(file.touch):
                file.touch()

            after = file.to_dict() if hasattr(file, "to_dict") else to_dict_or_payload(file)

            if audit:
                self.create_audit_event(
                    event_type="updated",
                    user_id=user_id,
                    file=file,
                    before=before,
                    after=after,
                    commit=False,
                )

            self._finish_write(commit=commit)
            return file

        except Exception:
            if commit:
                self.rollback()
            raise

    def soft_delete_file(
        self,
        file_ref: Any,
        *,
        user_id: Any = None,
        commit: bool = False,
        audit: bool = True,
    ) -> bool:
        """Soft-deletes file and its links."""
        try:
            file = self.require_file(file_ref, include_deleted=True, for_update=True)
            before = file.to_dict(include_links=True) if hasattr(file, "to_dict") else to_dict_or_payload(file)

            if getattr(file, "locked", False):
                raise LibraryFileConflictError(f"Library file {file_ref!r} is locked.")

            if hasattr(file, "mark_deleted") and callable(file.mark_deleted):
                file.mark_deleted(user_id=user_id)
            else:
                file.status = STATUS_DELETED
                file.active = False
                file.visible = False

            after = file.to_dict(include_links=True) if hasattr(file, "to_dict") else to_dict_or_payload(file)

            if audit:
                self.create_audit_event(
                    event_type="deleted",
                    user_id=user_id,
                    file=file,
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

    def quarantine_file(
        self,
        file_ref: Any,
        *,
        reason: Any = None,
        user_id: Any = None,
        commit: bool = False,
        audit: bool = True,
    ) -> Any:
        """Marks file as quarantined."""
        try:
            file = self.require_file(file_ref, include_deleted=True, for_update=True)
            before = file.to_dict() if hasattr(file, "to_dict") else to_dict_or_payload(file)

            if hasattr(file, "mark_quarantined") and callable(file.mark_quarantined):
                file.mark_quarantined(reason=reason, user_id=user_id)
            else:
                file.status = STATUS_QUARANTINED
                file.active = False
                file.visible = False
                file.quarantine_reason = optional_string(reason)

            after = file.to_dict() if hasattr(file, "to_dict") else to_dict_or_payload(file)

            if audit:
                self.create_audit_event(
                    event_type="quarantined",
                    user_id=user_id,
                    file=file,
                    before=before,
                    after=after,
                    payload={"reason": reason},
                    commit=False,
                )

            self._finish_write(commit=commit)
            return file

        except Exception:
            if commit:
                self.rollback()
            raise

    def restore_file(
        self,
        file_ref: Any,
        *,
        user_id: Any = None,
        commit: bool = False,
        audit: bool = True,
    ) -> Any:
        """Restores a deleted/quarantined file."""
        try:
            file = self.require_file(file_ref, include_deleted=True, for_update=True)
            before = file.to_dict() if hasattr(file, "to_dict") else to_dict_or_payload(file)

            if hasattr(file, "restore") and callable(file.restore):
                file.restore(user_id=user_id)
            else:
                file.status = STATUS_ACTIVE
                file.active = True
                file.visible = True

            after = file.to_dict() if hasattr(file, "to_dict") else to_dict_or_payload(file)

            if audit:
                self.create_audit_event(
                    event_type="restored",
                    user_id=user_id,
                    file=file,
                    before=before,
                    after=after,
                    commit=False,
                )

            self._finish_write(commit=commit)
            return file

        except Exception:
            if commit:
                self.rollback()
            raise

    # ------------------------------------------------------------------
    # Version writes
    # ------------------------------------------------------------------

    def add_file_version(
        self,
        file_ref: Any,
        payload: Mapping[str, Any],
        *,
        uploaded_by_user_id: Any = None,
        make_current: bool = True,
        mark_previous_replaced: bool = True,
        commit: bool = False,
        audit: bool = True,
    ) -> Any:
        """Adds a new version to an existing file."""
        data = normalize_json_mapping(payload)

        try:
            file = self.require_file(file_ref, include_deleted=True, for_update=True)

            if getattr(file, "locked", False):
                raise LibraryFileConflictError(f"Library file {file_ref!r} is locked.")

            before = file.to_dict(include_current_version=True) if hasattr(file, "to_dict") else to_dict_or_payload(file)

            previous_current = self.get_current_version(file.id)
            if previous_current is not None and mark_previous_replaced and hasattr(previous_current, "mark_replaced"):
                previous_current.mark_replaced()

            next_index = self.next_version_index(file)
            version = self.models.LibraryFileVersion.create_from_payload(
                data,
                file=file,
                version_index=next_index,
                uploaded_by_user_id=uploaded_by_user_id,
            )
            self.session.add(version)
            self.session.flush()

            if make_current:
                file.set_current_version(version)

            after = file.to_dict(include_current_version=True) if hasattr(file, "to_dict") else to_dict_or_payload(file)

            if audit:
                self.create_audit_event(
                    event_type="version_added",
                    user_id=uploaded_by_user_id,
                    file=file,
                    file_version=version,
                    before=before,
                    after=after,
                    commit=False,
                )

            self._finish_write(commit=commit)
            return version

        except Exception:
            if commit:
                self.rollback()
            raise

    def replace_current_version(
        self,
        file_ref: Any,
        payload: Mapping[str, Any],
        *,
        uploaded_by_user_id: Any = None,
        commit: bool = False,
        audit: bool = True,
    ) -> Any:
        """Adds a new current version and marks previous current version replaced."""
        return self.add_file_version(
            file_ref,
            payload,
            uploaded_by_user_id=uploaded_by_user_id,
            make_current=True,
            mark_previous_replaced=True,
            commit=commit,
            audit=audit,
        )

    def next_version_index(self, file: Any) -> int:
        """Returns next version index for a file."""
        current_count = normalize_int(getattr(file, "version_count", 0), default=0, minimum=0) or 0

        try:
            versions = self.list_versions(file.id, include_deleted=True)
            if versions:
                max_index = max(normalize_int(getattr(version, "version_index", 0), default=0) or 0 for version in versions)
                return max(max_index + 1, current_count + 1)
        except Exception:
            pass

        return current_count + 1

    def mark_version_deleted(
        self,
        version_ref: Any,
        *,
        user_id: Any = None,
        commit: bool = False,
        audit: bool = True,
    ) -> bool:
        """Soft-deletes a version."""
        try:
            version = self.require_version(version_ref, include_deleted=True, for_update=True)
            file = getattr(version, "file", None)

            if file is None and getattr(version, "file_id", None):
                file = self.get_file_by_id(version.file_id, include_deleted=True)

            before = version.to_dict() if hasattr(version, "to_dict") else to_dict_or_payload(version)

            if hasattr(version, "mark_deleted") and callable(version.mark_deleted):
                version.mark_deleted()
            else:
                version.status = STATUS_DELETED
                version.active = False

            if file is not None and getattr(file, "current_version_id", None) == getattr(version, "id", None):
                file.current_version_id = None
                if hasattr(file, "touch") and callable(file.touch):
                    file.touch()

            after = version.to_dict() if hasattr(version, "to_dict") else to_dict_or_payload(version)

            if audit:
                self.create_audit_event(
                    event_type="version_deleted",
                    user_id=user_id,
                    file=file,
                    file_version=version,
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
    # Combined create
    # ------------------------------------------------------------------

    def create_file_with_version(
        self,
        file_payload: Mapping[str, Any],
        *,
        version_payload: Mapping[str, Any] | None = None,
        link_payload: Mapping[str, Any] | None = None,
        owner_user_id: Any = DEFAULT_USER_ID,
        source_scope: Any = SOURCE_SCOPE_USER,
        created_by_user_id: Any = None,
        commit: bool = False,
        audit: bool = True,
    ) -> FileWriteResult:
        """Creates a file, initial version and optional link."""
        try:
            file = self.create_file(
                file_payload,
                owner_user_id=owner_user_id,
                source_scope=source_scope,
                created_by_user_id=created_by_user_id,
                commit=False,
                audit=audit,
            )

            version = self.add_file_version(
                file.id,
                version_payload or file_payload,
                uploaded_by_user_id=created_by_user_id or owner_user_id,
                make_current=True,
                mark_previous_replaced=False,
                commit=False,
                audit=audit,
            )

            link = None
            if link_payload is not None:
                link = self.create_link(
                    file_ref=file.id,
                    payload=link_payload,
                    file_version_ref=version.id,
                    user_id=created_by_user_id or owner_user_id,
                    commit=False,
                    audit=audit,
                )

            self._finish_write(commit=commit)

            return FileWriteResult(
                ok=True,
                action="create_file_with_version",
                file_uid=getattr(file, "file_uid", None),
                version_uid=getattr(version, "version_uid", None),
                link_uid=getattr(link, "link_uid", None) if link is not None else None,
                file_id=getattr(file, "id", None),
                version_id=getattr(version, "id", None),
                link_id=getattr(link, "id", None) if link is not None else None,
                created=True,
                payload={
                    "file": file.to_dict(include_current_version=True) if hasattr(file, "to_dict") else to_dict_or_payload(file),
                    "version": version.to_dict() if hasattr(version, "to_dict") else to_dict_or_payload(version),
                    "link": link.to_dict() if link is not None and hasattr(link, "to_dict") else None,
                },
            )

        except Exception as exc:
            if commit:
                self.rollback()
            raise

    # ------------------------------------------------------------------
    # Link writes
    # ------------------------------------------------------------------

    def create_link(
        self,
        *,
        file_ref: Any,
        payload: Mapping[str, Any],
        file_version_ref: Any = None,
        user_id: Any = DEFAULT_USER_ID,
        created_by_user_id: Any = None,
        commit: bool = False,
        audit: bool = True,
    ) -> Any:
        """Creates a LibraryFileLink."""
        data = normalize_json_mapping(payload)

        try:
            file = self.require_file(file_ref, include_deleted=False, for_update=True)
            version = None

            if file_version_ref is not None:
                version = self.require_version(file_version_ref, include_deleted=False)
            else:
                version = self.get_current_version(file.id)

            if getattr(file, "id", None) is None:
                self.session.flush()

            is_primary = normalize_bool(data.get("is_primary") or data.get("primary"), default=False)

            if is_primary:
                self.deactivate_primary_links_for_context(
                    context_type=data.get("context_type") or data.get("contextType") or CONTEXT_OTHER,
                    context_db_id=data.get("context_db_id") or data.get("contextDbId"),
                    context_id=data.get("context_id") or data.get("contextId"),
                    context_uid=data.get("context_uid") or data.get("contextUid"),
                    field_key=data.get("field_key") or data.get("fieldKey"),
                    document_type=data.get("document_type") or data.get("documentType") or getattr(file, "document_type", None),
                    user_id=user_id,
                    commit=False,
                )

            link = self.models.LibraryFileLink.create_from_payload(
                data,
                file=file,
                file_version=version,
                user_id=user_id,
                created_by_user_id=created_by_user_id or user_id,
            )
            self.session.add(link)
            self.session.flush()

            if audit:
                self.create_audit_event(
                    event_type="linked",
                    user_id=user_id,
                    file=file,
                    file_version=version,
                    link=link,
                    after=link.to_dict(include_file=False) if hasattr(link, "to_dict") else to_dict_or_payload(link),
                    commit=False,
                )

            self._finish_write(commit=commit)
            return link

        except Exception:
            if commit:
                self.rollback()
            raise

    def deactivate_primary_links_for_context(
        self,
        *,
        context_type: Any,
        context_db_id: Any = None,
        context_id: Any = None,
        context_uid: Any = None,
        field_key: Any = None,
        document_type: Any = None,
        user_id: Any = None,
        exclude_link_id: Any = None,
        commit: bool = False,
    ) -> int:
        """Sets is_primary=False for matching active links."""
        link_model = self.models.LibraryFileLink

        query = self.session.query(link_model).filter(
            link_model.context_type == clean_string(context_type, fallback=CONTEXT_OTHER),
            link_model.active.is_(True),
            link_model.status != STATUS_DELETED,
        )

        normalized_user_id = normalize_user_id(user_id, default=None)
        if normalized_user_id is not None:
            query = query.filter(link_model.user_id == normalized_user_id)

        normalized_context_db_id = normalize_int(context_db_id, default=None, minimum=1)
        if normalized_context_db_id is not None:
            query = query.filter(link_model.context_db_id == normalized_context_db_id)

        if context_id:
            query = query.filter(link_model.context_id == optional_string(context_id))

        if context_uid:
            query = query.filter(link_model.context_uid == optional_string(context_uid))

        if field_key:
            query = query.filter(link_model.field_key == optional_string(field_key))

        if document_type:
            query = query.filter(link_model.document_type == optional_string(document_type))

        excluded_id = normalize_int(exclude_link_id, default=None, minimum=1)
        if excluded_id is not None:
            query = query.filter(link_model.id != excluded_id)

        count = 0

        try:
            for link in query.all():
                if getattr(link, "is_primary", False):
                    link.is_primary = False
                    if hasattr(link, "touch") and callable(link.touch):
                        link.touch()
                    count += 1

            self._finish_write(commit=commit)
            return count

        except Exception:
            if commit:
                self.rollback()
            raise

    def set_link_primary(
        self,
        link_ref: Any,
        *,
        user_id: Any = None,
        commit: bool = False,
        audit: bool = True,
    ) -> Any:
        """Marks one link as primary and deactivates competing primary links."""
        try:
            link = self.require_link(link_ref, include_deleted=False, for_update=True)
            before = link.to_dict(include_file=False) if hasattr(link, "to_dict") else to_dict_or_payload(link)

            self.deactivate_primary_links_for_context(
                context_type=link.context_type,
                context_db_id=link.context_db_id,
                context_id=link.context_id,
                context_uid=link.context_uid,
                field_key=link.field_key,
                document_type=link.document_type,
                user_id=link.user_id or user_id,
                exclude_link_id=link.id,
                commit=False,
            )

            link.is_primary = True
            link.active = True
            link.status = STATUS_ACTIVE

            if hasattr(link, "touch") and callable(link.touch):
                link.touch()

            after = link.to_dict(include_file=False) if hasattr(link, "to_dict") else to_dict_or_payload(link)

            if audit:
                self.create_audit_event(
                    event_type="primary_changed",
                    user_id=user_id or link.user_id,
                    file=getattr(link, "file", None),
                    file_version=getattr(link, "file_version", None),
                    link=link,
                    before=before,
                    after=after,
                    commit=False,
                )

            self._finish_write(commit=commit)
            return link

        except Exception:
            if commit:
                self.rollback()
            raise

    def soft_delete_link(
        self,
        link_ref: Any,
        *,
        user_id: Any = None,
        commit: bool = False,
        audit: bool = True,
    ) -> bool:
        """Soft-deletes a file link."""
        try:
            link = self.require_link(link_ref, include_deleted=True, for_update=True)
            before = link.to_dict(include_file=False) if hasattr(link, "to_dict") else to_dict_or_payload(link)

            if hasattr(link, "mark_deleted") and callable(link.mark_deleted):
                link.mark_deleted(user_id=user_id)
            else:
                link.status = STATUS_DELETED
                link.active = False

            after = link.to_dict(include_file=False) if hasattr(link, "to_dict") else to_dict_or_payload(link)

            if audit:
                self.create_audit_event(
                    event_type="unlinked",
                    user_id=user_id or getattr(link, "user_id", None),
                    file=getattr(link, "file", None),
                    file_version=getattr(link, "file_version", None),
                    link=link,
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

    def restore_link(
        self,
        link_ref: Any,
        *,
        user_id: Any = None,
        commit: bool = False,
        audit: bool = True,
    ) -> Any:
        """Restores a deleted link."""
        try:
            link = self.require_link(link_ref, include_deleted=True, for_update=True)
            before = link.to_dict(include_file=False) if hasattr(link, "to_dict") else to_dict_or_payload(link)

            if hasattr(link, "restore") and callable(link.restore):
                link.restore(user_id=user_id)
            else:
                link.status = STATUS_ACTIVE
                link.active = True

            after = link.to_dict(include_file=False) if hasattr(link, "to_dict") else to_dict_or_payload(link)

            if audit:
                self.create_audit_event(
                    event_type="link_restored",
                    user_id=user_id or getattr(link, "user_id", None),
                    file=getattr(link, "file", None),
                    file_version=getattr(link, "file_version", None),
                    link=link,
                    before=before,
                    after=after,
                    commit=False,
                )

            self._finish_write(commit=commit)
            return link

        except Exception:
            if commit:
                self.rollback()
            raise

    # ------------------------------------------------------------------
    # Audit
    # ------------------------------------------------------------------

    def create_audit_event(
        self,
        *,
        event_type: Any,
        user_id: Any = None,
        file: Any = None,
        file_version: Any = None,
        link: Any = None,
        before: Mapping[str, Any] | None = None,
        after: Mapping[str, Any] | None = None,
        diff: Mapping[str, Any] | None = None,
        payload: Mapping[str, Any] | None = None,
        metadata: Mapping[str, Any] | None = None,
        commit: bool = False,
    ) -> Any:
        """Creates a LibraryFileAuditEvent row."""
        try:
            event = self.models.LibraryFileAuditEvent.create_event(
                event_type=event_type,
                user_id=user_id,
                file=file,
                file_version=file_version,
                link=link,
                before=before,
                after=after,
                diff=diff,
                payload=payload,
                metadata=metadata,
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
        file_uid: Any = None,
        user_id: Any = None,
        event_type: Any = None,
        context_type: Any = None,
        context_id: Any = None,
        limit: int = DEFAULT_LIMIT,
        offset: int = 0,
        as_dict: bool = True,
    ) -> list[Any]:
        """Lists file audit events."""
        model = self.models.LibraryFileAuditEvent
        query = self.session.query(model)

        if file_uid:
            query = query.filter(model.file_uid == optional_string(file_uid))

        normalized_user_id = normalize_user_id(user_id, default=None)
        if normalized_user_id is not None:
            query = query.filter(model.user_id == normalized_user_id)

        if event_type:
            query = query.filter(model.event_type == clean_string(event_type))

        if context_type:
            query = query.filter(model.context_type == optional_string(context_type))

        if context_id:
            query = query.filter(model.context_id == optional_string(context_id))

        query = query.order_by(model.created_at.desc(), model.id.desc())

        normalized_offset = normalize_int(offset, default=0, minimum=0) or 0
        normalized_limit = normalize_int(limit, default=DEFAULT_LIMIT, minimum=1, maximum=MAX_DEFAULT_LIMIT) or DEFAULT_LIMIT

        if normalized_offset:
            query = query.offset(normalized_offset)

        query = query.limit(normalized_limit)

        values = query.all()

        if as_dict:
            return [event.to_dict() if hasattr(event, "to_dict") else to_dict_or_payload(event) for event in values]

        return values

    # ------------------------------------------------------------------
    # Bulk helpers
    # ------------------------------------------------------------------

    def delete_links_for_context(
        self,
        *,
        context_type: Any,
        context_db_id: Any = None,
        context_id: Any = None,
        context_uid: Any = None,
        field_key: Any = None,
        document_type: Any = None,
        user_id: Any = None,
        commit: bool = False,
    ) -> int:
        """Soft-deletes all matching links for a context."""
        query = FileLinkQuery(
            user_id=normalize_user_id(user_id, default=None),
            context_type=optional_string(context_type),
            context_db_id=normalize_int(context_db_id, default=None, minimum=1),
            context_id=optional_string(context_id),
            context_uid=optional_string(context_uid),
            field_key=optional_string(field_key),
            document_type=optional_string(document_type),
            active_only=True,
            include_deleted=False,
            limit=MAX_DEFAULT_LIMIT,
        )
        links = self.list_links(query=query, as_dict=False)

        count = 0

        try:
            for link in links:
                if hasattr(link, "mark_deleted") and callable(link.mark_deleted):
                    link.mark_deleted(user_id=user_id)
                else:
                    link.status = STATUS_DELETED
                    link.active = False

                count += 1

            self._finish_write(commit=commit)
            return count

        except Exception:
            if commit:
                self.rollback()
            raise

    def replace_single_link_for_context(
        self,
        *,
        file_ref: Any,
        payload: Mapping[str, Any],
        file_version_ref: Any = None,
        user_id: Any = DEFAULT_USER_ID,
        commit: bool = False,
        audit: bool = True,
    ) -> Any:
        """
        Replaces existing active links for the same context/field/document_type.

        This supports document_type.multiple=False behavior in the service.
        """
        data = normalize_json_mapping(payload)

        try:
            self.delete_links_for_context(
                context_type=data.get("context_type") or data.get("contextType") or CONTEXT_OTHER,
                context_db_id=data.get("context_db_id") or data.get("contextDbId"),
                context_id=data.get("context_id") or data.get("contextId"),
                context_uid=data.get("context_uid") or data.get("contextUid"),
                field_key=data.get("field_key") or data.get("fieldKey"),
                document_type=data.get("document_type") or data.get("documentType"),
                user_id=user_id,
                commit=False,
            )

            data["is_primary"] = True

            link = self.create_link(
                file_ref=file_ref,
                payload=data,
                file_version_ref=file_version_ref,
                user_id=user_id,
                created_by_user_id=user_id,
                commit=False,
                audit=audit,
            )

            self._finish_write(commit=commit)
            return link

        except Exception:
            if commit:
                self.rollback()
            raise

    # ------------------------------------------------------------------
    # Payload helpers
    # ------------------------------------------------------------------

    def get_file_payload(
        self,
        file_ref: Any,
        *,
        include_current_version: bool = True,
        include_versions: bool = False,
        include_links: bool = False,
    ) -> dict[str, Any]:
        """Returns file payload."""
        file = self.require_file(file_ref)

        if hasattr(file, "to_dict"):
            return file.to_dict(
                include_current_version=include_current_version,
                include_versions=include_versions,
                include_links=include_links,
            )

        return to_dict_or_payload(file)

    def get_link_payload(
        self,
        link_ref: Any,
        *,
        include_file: bool = True,
        include_version: bool = True,
    ) -> dict[str, Any]:
        """Returns link payload."""
        link = self.require_link(link_ref)

        if hasattr(link, "to_dict"):
            return link.to_dict(include_file=include_file, include_version=include_version)

        return to_dict_or_payload(link)

    # ------------------------------------------------------------------
    # Health / diagnostics
    # ------------------------------------------------------------------

    def get_health(self) -> dict[str, Any]:
        """Returns repository health snapshot."""
        model_health = {}

        try:
            candidate = getattr(self.models, "get_library_file_models_health", None)
            if callable(candidate):
                model_health = candidate()
        except Exception as exc:
            model_health = {"ok": False, "error": f"{type(exc).__name__}: {exc}"}

        return {
            "schema_version": LIBRARY_FILE_REPOSITORY_VERSION,
            "ok": True,
            "repository": type(self).__name__,
            "has_session": self._session is not None,
            "uses_default_db_session": self._session is None,
            "models_health": model_health,
            "supports_files": True,
            "supports_versions": True,
            "supports_links": True,
            "supports_audit": True,
            "supports_primary_link": True,
            "supports_soft_delete": True,
            "supports_replace_single_link": True,
            "supports_context_queries": True,
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


# ---------------------------------------------------------------------------
# Factory helpers
# ---------------------------------------------------------------------------

def create_library_file_repository(session: Any | None = None) -> LibraryFileRepository:
    """Factory for dependency injection."""
    return LibraryFileRepository(session=session)


@lru_cache(maxsize=1)
def get_repository_version() -> str:
    """Cached repository version helper."""
    return LIBRARY_FILE_REPOSITORY_VERSION


def clear_library_file_repository_caches() -> dict[str, Any]:
    """Clears import/static caches."""
    cleared: list[str] = []

    for cached_func in (
        _load_db,
        _load_file_models_module,
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
    "LIBRARY_FILE_REPOSITORY_VERSION",
    "DEFAULT_USER_ID",
    "STATUS_ACTIVE",
    "STATUS_REPLACED",
    "STATUS_DELETED",
    "STATUS_QUARANTINED",
    "SOURCE_SCOPE_USER",
    "SOURCE_SCOPE_SYSTEM",
    "SOURCE_SCOPE_IMPORTED",
    "SOURCE_SCOPE_GENERATED",
    "SOURCE_SCOPE_EXTERNAL",
    "CONTEXT_CREATIVE_ITEM",
    "CONTEXT_CREATIVE_VARIANT",
    "CONTEXT_CREATIVE_REVISION",
    "CONTEXT_CREATIVE_DRAFT",
    "CONTEXT_DEFINITION",
    "CONTEXT_TAXONOMY_NODE",
    "CONTEXT_USER_INVENTORY_SLOT",
    "CONTEXT_OTHER",
    "ROLE_PRIMARY",
    "ROLE_ATTACHMENT",
    "ROLE_PREVIEW",
    "ROLE_RENDER_MODEL",
    "ROLE_DOCUMENT",

    # Exceptions
    "LibraryFileRepositoryError",
    "LibraryFileRepositoryImportError",
    "LibraryFileNotFoundError",
    "LibraryFileConflictError",

    # Dataclasses
    "FileQuery",
    "FileLinkQuery",
    "FileWriteResult",

    # Repository
    "LibraryFileRepository",
    "create_library_file_repository",

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
    "get_repository_version",
    "clear_library_file_repository_caches",
]