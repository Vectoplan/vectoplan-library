# services/vectoplan-library/src/library/services/library_file_service.py
"""
Service for VECTOPLAN Library Files.

Diese Datei verarbeitet File-/Asset-Uploads fachlich und technisch:

- Upload-Eingaben normalisieren
- Dateiname bereinigen
- Extension / MIME / Size gegen document_type prüfen
- SHA-256 berechnen
- lokale Storage-Datei schreiben
- optional postgres_bytea vorbereiten
- LibraryFile / LibraryFileVersion erzeugen
- LibraryFileLink erzeugen
- single/multiple-Regeln aus document_type anwenden
- bestehende Versionen ersetzen
- Files / Links soft-deleten
- API-fähige Payloads zurückgeben

Ziel:

    Flask Route / Generator / Import
        -> LibraryFileService
        -> LibraryFileRepository
        -> models/library_files.py
        -> PostgreSQL + local storage

Architekturregeln:

- Service enthält keine Flask-Route.
- Service importiert Flask nicht hart.
- Service darf Datei-Storage schreiben.
- Service schreibt keine DB direkt, sondern über LibraryFileRepository.
- Service validiert Upload-Regeln über Definition Catalog.
- Service erzeugt keine Tabellen.
- Service führt keine Migration aus.
- Service führt kein db.create_all() aus.
- Service öffnet keine aktive DB-Verbindung beim Import.
- Technische Namen, JSON-Keys und Variablen bleiben Englisch.

Phase 1:

- user_id darf weiterhin 1 sein.
- Default storage_backend ist "local".
- postgres_bytea ist vorbereitet, aber nicht Default.
- object_storage ist vorbereitet, aber noch nicht implementiert.
"""

from __future__ import annotations

import hashlib
import importlib
import io
import mimetypes
import os
import re
import shutil
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone
from functools import lru_cache
from pathlib import Path
from types import ModuleType
from typing import Any, BinaryIO, Final, Iterable, Mapping, Protocol


# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

LIBRARY_FILE_SERVICE_VERSION: Final[str] = "vectoplan_library.service.library_file.v1"

DEFAULT_USER_ID: Final[int] = 1

STORAGE_BACKEND_LOCAL: Final[str] = "local"
STORAGE_BACKEND_POSTGRES_BYTEA: Final[str] = "postgres_bytea"
STORAGE_BACKEND_OBJECT_STORAGE: Final[str] = "object_storage"

DEFAULT_STORAGE_BACKEND: Final[str] = STORAGE_BACKEND_LOCAL

DEFAULT_ASSET_KIND_DOCUMENT: Final[str] = "document"
DEFAULT_ROLE_ATTACHMENT: Final[str] = "attachment"
DEFAULT_ROLE_PRIMARY: Final[str] = "primary"

DEFAULT_CHUNK_SIZE: Final[int] = 1024 * 1024
DEFAULT_MAX_UPLOAD_MB: Final[int] = 250
MAX_SAFE_FILENAME_LENGTH: Final[int] = 180
MAX_EXTENSION_LENGTH: Final[int] = 32

STATUS_OK: Final[str] = "ok"
STATUS_INVALID_REQUEST: Final[str] = "invalid_request"
STATUS_NOT_FOUND: Final[str] = "not_found"
STATUS_FAILED: Final[str] = "failed"

LOCAL_STORAGE_ENV_KEYS: Final[tuple[str, ...]] = (
    "VECTOPLAN_LIBRARY_FILE_STORAGE_ROOT",
    "VPLIB_LIBRARY_FILE_STORAGE_ROOT",
    "LIBRARY_FILE_STORAGE_ROOT",
    "LIBRARY_UPLOAD_ROOT",
)

CONFIG_STORAGE_KEYS: Final[tuple[str, ...]] = (
    "VECTOPLAN_LIBRARY_FILE_STORAGE_ROOT",
    "VPLIB_LIBRARY_FILE_STORAGE_ROOT",
    "LIBRARY_FILE_STORAGE_ROOT",
    "LIBRARY_UPLOAD_ROOT",
)


# ---------------------------------------------------------------------------
# Exceptions
# ---------------------------------------------------------------------------

class LibraryFileServiceError(RuntimeError):
    """Base error for LibraryFileService."""


class LibraryFileServiceImportError(LibraryFileServiceError):
    """Raised when service dependencies cannot be imported."""


class LibraryFileValidationError(LibraryFileServiceError):
    """Raised when upload validation fails."""

    def __init__(self, message: str, *, errors: Iterable[Any] | None = None) -> None:
        super().__init__(message)
        self.errors = [str(error) for error in (errors or [])]


class LibraryFileStorageError(LibraryFileServiceError):
    """Raised when file storage fails."""


class LibraryFileUnsupportedStorageError(LibraryFileStorageError):
    """Raised when requested storage backend is not implemented."""


# ---------------------------------------------------------------------------
# Protocols
# ---------------------------------------------------------------------------

class FileStorageLike(Protocol):
    filename: str

    @property
    def mimetype(self) -> str | None:
        ...

    @property
    def content_type(self) -> str | None:
        ...

    @property
    def stream(self) -> BinaryIO:
        ...


# ---------------------------------------------------------------------------
# Lazy imports
# ---------------------------------------------------------------------------

@lru_cache(maxsize=1)
def _load_repository_module() -> ModuleType:
    """Loads library_file_repository defensively."""
    errors: list[str] = []

    for module_name in (
        "library.repositories.library_file_repository",
        "src.library.repositories.library_file_repository",
        "vectoplan_library.library.repositories.library_file_repository",
        "vectoplan_library.src.library.repositories.library_file_repository",
    ):
        try:
            return importlib.import_module(module_name)
        except Exception as exc:
            errors.append(f"{module_name}: {type(exc).__name__}: {exc}")

    raise LibraryFileServiceImportError(
        "Could not import library_file_repository. "
        + " | ".join(errors)
    )


@lru_cache(maxsize=1)
def _load_definition_catalog_service_module() -> ModuleType:
    """Loads library_definition_catalog_service defensively."""
    errors: list[str] = []

    for module_name in (
        "library.services.library_definition_catalog_service",
        "src.library.services.library_definition_catalog_service",
        "vectoplan_library.library.services.library_definition_catalog_service",
        "vectoplan_library.src.library.services.library_definition_catalog_service",
    ):
        try:
            return importlib.import_module(module_name)
        except Exception as exc:
            errors.append(f"{module_name}: {type(exc).__name__}: {exc}")

    raise LibraryFileServiceImportError(
        "Could not import library_definition_catalog_service. "
        + " | ".join(errors)
    )


def _repo_module() -> ModuleType:
    """Short alias for repository module."""
    return _load_repository_module()


# ---------------------------------------------------------------------------
# Generic helpers
# ---------------------------------------------------------------------------

def utc_now() -> datetime:
    """Timezone-aware UTC timestamp."""
    return datetime.now(timezone.utc)


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

    if isinstance(value, Path):
        return str(value)

    if isinstance(value, datetime):
        return value.isoformat()

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


def bytes_to_mb(value: int | None) -> float | None:
    """Converts bytes to MB."""
    if value is None:
        return None
    return round(float(value) / (1024 * 1024), 4)


def mb_to_bytes(value: Any) -> int | None:
    """Converts MB to bytes."""
    number = normalize_int(value, default=None, minimum=0)
    if number is None:
        return None
    return int(number * 1024 * 1024)


def normalize_extension(value: Any) -> str | None:
    """Normalizes file extension with leading dot."""
    text = optional_string(value, max_length=MAX_EXTENSION_LENGTH)
    if not text:
        return None

    text = text.lower().strip()
    if not text.startswith("."):
        text = "." + text

    if text == ".":
        return None

    return text[:MAX_EXTENSION_LENGTH]


def extension_from_filename(filename: Any) -> str | None:
    """Extracts normalized extension from filename."""
    name = optional_string(filename)
    if not name:
        return None

    suffix = Path(name).suffix
    return normalize_extension(suffix)


def normalize_extension_set(values: Iterable[Any] | None) -> set[str]:
    """Normalizes extension list/set."""
    return {
        extension
        for extension in (normalize_extension(value) for value in normalize_json_list(values))
        if extension
    }


def normalize_mime_set(values: Iterable[Any] | None) -> set[str]:
    """Normalizes MIME list/set."""
    return {
        clean_string(value).lower()
        for value in normalize_json_list(values)
        if clean_string(value)
    }


def mime_matches(mime_type: str | None, allowed_mime: str) -> bool:
    """Checks exact or wildcard MIME match."""
    actual = clean_string(mime_type).lower()
    allowed = clean_string(allowed_mime).lower()

    if not actual or not allowed:
        return False

    if allowed == actual:
        return True

    if allowed.endswith("/*"):
        prefix = allowed[:-1]
        return actual.startswith(prefix)

    return False


def sanitize_filename(filename: Any, *, fallback: str = "upload.bin") -> str:
    """Creates a safe filename for storage/display."""
    raw = optional_string(filename, max_length=MAX_SAFE_FILENAME_LENGTH) or fallback
    raw = raw.replace("\\", "/").split("/")[-1].strip()
    raw = raw.replace("\x00", "")

    if not raw or raw in {".", ".."}:
        raw = fallback

    stem = Path(raw).stem
    suffix = Path(raw).suffix.lower()

    stem = re.sub(r"[^A-Za-z0-9._-]+", "_", stem).strip("._-")
    suffix = re.sub(r"[^A-Za-z0-9.]+", "", suffix).strip()

    if not stem:
        stem = "upload"

    if suffix and not suffix.startswith("."):
        suffix = "." + suffix

    result = f"{stem}{suffix}"[:MAX_SAFE_FILENAME_LENGTH]

    if not result:
        return fallback

    return result


def guess_mime_type(filename: Any, provided_mime_type: Any = None) -> str | None:
    """Guesses MIME type from provided value or filename."""
    provided = optional_string(provided_mime_type, max_length=160)
    if provided:
        return provided.lower()

    guessed, _encoding = mimetypes.guess_type(clean_string(filename))
    return guessed.lower() if guessed else None


def get_config_value(*keys: str) -> str | None:
    """Reads config from Flask current_app if available, then environment."""
    try:
        from flask import current_app

        if current_app:
            for key in keys:
                value = current_app.config.get(key)
                if value:
                    return str(value)
    except Exception:
        pass

    for key in keys:
        value = os.environ.get(key)
        if value:
            return str(value)

    return None


def default_storage_root() -> Path:
    """Returns default local storage root."""
    configured = get_config_value(*CONFIG_STORAGE_KEYS, *LOCAL_STORAGE_ENV_KEYS)

    if configured:
        return Path(configured).expanduser().resolve()

    return (Path.cwd() / "generated" / "uploads" / "library_files").resolve()


def ensure_directory(path: Path) -> None:
    """Ensures directory exists."""
    try:
        path.mkdir(parents=True, exist_ok=True)
    except Exception as exc:
        raise LibraryFileStorageError(f"Could not create directory {path}: {exc}") from exc


def now_path_part() -> str:
    """Builds date path part."""
    now = utc_now()
    return f"{now.year:04d}/{now.month:02d}/{now.day:02d}"


def remove_file_if_exists(path: Path | None) -> None:
    """Best-effort cleanup for failed uploads."""
    if path is None:
        return

    try:
        if path.exists() and path.is_file():
            path.unlink()
    except Exception:
        pass


def extract_file_storage_filename(value: Any) -> str | None:
    """Extracts filename from bytes/file/FileStorage-like input."""
    filename = getattr(value, "filename", None)
    if filename:
        return optional_string(filename)

    name = getattr(value, "name", None)
    if name:
        return optional_string(Path(str(name)).name)

    return None


def extract_file_storage_mime(value: Any) -> str | None:
    """Extracts MIME from FileStorage-like input."""
    for attr in ("mimetype", "content_type", "mime_type"):
        mime = getattr(value, attr, None)
        if mime:
            return optional_string(mime, max_length=160)
    return None


def open_binary_stream(value: Any) -> tuple[BinaryIO, bool]:
    """
    Converts supported input to binary stream.

    Returns:
        (stream, should_close)
    """
    if isinstance(value, bytes):
        return io.BytesIO(value), True

    if isinstance(value, bytearray):
        return io.BytesIO(bytes(value)), True

    stream = getattr(value, "stream", None)
    if stream is not None:
        try:
            if hasattr(stream, "seek"):
                stream.seek(0)
        except Exception:
            pass
        return stream, False

    if hasattr(value, "read") and callable(value.read):
        try:
            if hasattr(value, "seek"):
                value.seek(0)
        except Exception:
            pass
        return value, False

    raise ValueError("Unsupported upload content. Expected bytes, file-like object or Flask FileStorage-like object.")


# ---------------------------------------------------------------------------
# Dataclasses
# ---------------------------------------------------------------------------

@dataclass(slots=True)
class UploadValidationResult:
    """Result of upload validation."""

    ok: bool
    errors: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    constraints: dict[str, Any] = field(default_factory=dict)
    original_filename: str | None = None
    safe_filename: str | None = None
    extension: str | None = None
    mime_type: str | None = None
    size_bytes: int | None = None
    max_size_bytes: int | None = None

    def add_error(self, message: Any) -> None:
        self.ok = False
        self.errors.append(str(message))

    def add_warning(self, message: Any) -> None:
        self.warnings.append(str(message))

    def raise_if_invalid(self) -> None:
        if not self.ok:
            raise LibraryFileValidationError(
                "Upload validation failed.",
                errors=self.errors,
            )

    def to_dict(self) -> dict[str, Any]:
        return {
            "ok": self.ok,
            "errors": list(self.errors),
            "warnings": list(self.warnings),
            "constraints": normalize_json_mapping(self.constraints),
            "original_filename": self.original_filename,
            "safe_filename": self.safe_filename,
            "extension": self.extension,
            "mime_type": self.mime_type,
            "size_bytes": self.size_bytes,
            "size_mb": bytes_to_mb(self.size_bytes),
            "max_size_bytes": self.max_size_bytes,
            "max_size_mb": bytes_to_mb(self.max_size_bytes),
        }


@dataclass(slots=True)
class StoredUpload:
    """Stored upload result."""

    storage_backend: str
    storage_path: str | None
    external_uri: str | None
    binary_data: bytes | None
    size_bytes: int
    sha256: str
    safe_filename: str
    original_filename: str
    extension: str | None
    mime_type: str | None
    cleanup_path: Path | None = None

    def to_file_payload(self) -> dict[str, Any]:
        return {
            "storage_backend": self.storage_backend,
            "storage_path": self.storage_path,
            "external_uri": self.external_uri,
            "binary_data": self.binary_data,
            "size_bytes": self.size_bytes,
            "sha256": self.sha256,
            "safe_filename": self.safe_filename,
            "original_filename": self.original_filename,
            "extension": self.extension,
            "mime_type": self.mime_type,
        }

    def to_dict(self, *, include_binary: bool = False) -> dict[str, Any]:
        payload = {
            "storage_backend": self.storage_backend,
            "storage_path": self.storage_path,
            "external_uri": self.external_uri,
            "size_bytes": self.size_bytes,
            "size_mb": bytes_to_mb(self.size_bytes),
            "sha256": self.sha256,
            "safe_filename": self.safe_filename,
            "original_filename": self.original_filename,
            "extension": self.extension,
            "mime_type": self.mime_type,
        }

        if include_binary:
            payload["binary_data_size"] = len(self.binary_data or b"")

        return payload


@dataclass(slots=True)
class UploadRequest:
    """Normalized upload request."""

    content: Any
    original_filename: str | None = None
    mime_type: str | None = None
    document_type: str | None = None
    asset_kind: str | None = None
    field_key: str | None = None
    role: str | None = None
    is_primary: bool | None = None
    context_type: str | None = None
    context_db_id: int | None = None
    context_id: str | None = None
    context_uid: str | None = None
    vplib_uid: str | None = None
    family_id: str | None = None
    package_id: str | None = None
    variant_id: str | None = None
    revision_hash: str | None = None
    owner_user_id: int | None = DEFAULT_USER_ID
    user_id: int | None = DEFAULT_USER_ID
    source_scope: str = "user"
    storage_backend: str = DEFAULT_STORAGE_BACKEND
    metadata: dict[str, Any] = field(default_factory=dict)
    payload: dict[str, Any] = field(default_factory=dict)
    replace_single: bool | None = None

    @classmethod
    def from_payload(cls, payload: Mapping[str, Any], *, content: Any = None) -> "UploadRequest":
        data = normalize_json_mapping(payload)

        return cls(
            content=content if content is not None else data.get("content"),
            original_filename=optional_string(data.get("original_filename") or data.get("filename")),
            mime_type=optional_string(data.get("mime_type") or data.get("content_type"), max_length=160),
            document_type=optional_string(data.get("document_type") or data.get("documentType")),
            asset_kind=optional_string(data.get("asset_kind") or data.get("assetKind")),
            field_key=optional_string(data.get("field_key") or data.get("fieldKey")),
            role=optional_string(data.get("role")),
            is_primary=None if data.get("is_primary") is None and data.get("primary") is None else normalize_bool(data.get("is_primary") or data.get("primary")),
            context_type=optional_string(data.get("context_type") or data.get("contextType")),
            context_db_id=normalize_int(data.get("context_db_id") or data.get("contextDbId"), default=None, minimum=1),
            context_id=optional_string(data.get("context_id") or data.get("contextId")),
            context_uid=optional_string(data.get("context_uid") or data.get("contextUid")),
            vplib_uid=optional_string(data.get("vplib_uid") or data.get("vplibUid")),
            family_id=optional_string(data.get("family_id") or data.get("familyId")),
            package_id=optional_string(data.get("package_id") or data.get("packageId")),
            variant_id=optional_string(data.get("variant_id") or data.get("variantId")),
            revision_hash=optional_string(data.get("revision_hash") or data.get("revisionHash")),
            owner_user_id=normalize_user_id(data.get("owner_user_id") or data.get("user_id"), default=DEFAULT_USER_ID),
            user_id=normalize_user_id(data.get("user_id"), default=DEFAULT_USER_ID),
            source_scope=clean_string(data.get("source_scope"), fallback="user"),
            storage_backend=clean_string(data.get("storage_backend"), fallback=DEFAULT_STORAGE_BACKEND),
            metadata=normalize_json_mapping(data.get("metadata")),
            payload=normalize_json_mapping(data.get("payload")),
            replace_single=None if data.get("replace_single") is None else normalize_bool(data.get("replace_single")),
        )

    def resolved_original_filename(self) -> str:
        extracted = extract_file_storage_filename(self.content)
        return sanitize_filename(self.original_filename or extracted or "upload.bin")

    def resolved_mime_type(self) -> str | None:
        extracted = extract_file_storage_mime(self.content)
        return guess_mime_type(self.resolved_original_filename(), self.mime_type or extracted)

    def to_dict(self) -> dict[str, Any]:
        return {
            "original_filename": self.original_filename,
            "mime_type": self.mime_type,
            "document_type": self.document_type,
            "asset_kind": self.asset_kind,
            "field_key": self.field_key,
            "role": self.role,
            "is_primary": self.is_primary,
            "context_type": self.context_type,
            "context_db_id": self.context_db_id,
            "context_id": self.context_id,
            "context_uid": self.context_uid,
            "vplib_uid": self.vplib_uid,
            "family_id": self.family_id,
            "package_id": self.package_id,
            "variant_id": self.variant_id,
            "revision_hash": self.revision_hash,
            "owner_user_id": self.owner_user_id,
            "user_id": self.user_id,
            "source_scope": self.source_scope,
            "storage_backend": self.storage_backend,
            "metadata": normalize_json_mapping(self.metadata),
            "payload": normalize_json_mapping(self.payload),
            "replace_single": self.replace_single,
        }


@dataclass(slots=True)
class FileServiceResult:
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
            "schema_version": LIBRARY_FILE_SERVICE_VERSION,
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

class LibraryFileService:
    """
    High-level service for Library File uploads and links.

    Args:
        repository:
            Optional LibraryFileRepository instance.
        definition_service:
            Optional LibraryDefinitionCatalogService instance.
        storage_root:
            Optional local storage root.
        storage_backend:
            Default storage backend.
    """

    def __init__(
        self,
        repository: Any | None = None,
        definition_service: Any | None = None,
        storage_root: Path | str | None = None,
        storage_backend: str = DEFAULT_STORAGE_BACKEND,
    ) -> None:
        self.repository = repository or self._create_repository()
        self.definition_service = definition_service or self._create_definition_service()
        self.storage_root = Path(storage_root).expanduser().resolve() if storage_root is not None else default_storage_root()
        self.storage_backend = clean_string(storage_backend, fallback=DEFAULT_STORAGE_BACKEND)

    # ------------------------------------------------------------------
    # Construction
    # ------------------------------------------------------------------

    def _create_repository(self) -> Any:
        repo_module = _repo_module()
        factory = getattr(repo_module, "create_library_file_repository", None)

        if callable(factory):
            return factory()

        repo_class = getattr(repo_module, "LibraryFileRepository", None)
        if repo_class is None:
            raise LibraryFileServiceImportError("LibraryFileRepository class is not available.")

        return repo_class()

    def _create_definition_service(self) -> Any | None:
        try:
            module = _load_definition_catalog_service_module()
            factory = getattr(module, "create_library_definition_catalog_service", None)

            if callable(factory):
                return factory()

            service_class = getattr(module, "LibraryDefinitionCatalogService", None)
            if service_class is not None:
                return service_class()
        except Exception:
            return None

        return None

    # ------------------------------------------------------------------
    # Public upload methods
    # ------------------------------------------------------------------

    def upload(
        self,
        *,
        content: Any,
        original_filename: Any = None,
        mime_type: Any = None,
        document_type: Any = None,
        asset_kind: Any = None,
        field_key: Any = None,
        role: Any = None,
        is_primary: Any = None,
        context_type: Any = None,
        context_db_id: Any = None,
        context_id: Any = None,
        context_uid: Any = None,
        vplib_uid: Any = None,
        family_id: Any = None,
        package_id: Any = None,
        variant_id: Any = None,
        revision_hash: Any = None,
        user_id: Any = DEFAULT_USER_ID,
        owner_user_id: Any = DEFAULT_USER_ID,
        source_scope: Any = "user",
        storage_backend: Any = None,
        metadata: Mapping[str, Any] | None = None,
        payload: Mapping[str, Any] | None = None,
        replace_single: bool | None = None,
        commit: bool = True,
    ) -> dict[str, Any]:
        """Validates, stores and records a new file upload."""
        request_payload = UploadRequest(
            content=content,
            original_filename=optional_string(original_filename),
            mime_type=optional_string(mime_type, max_length=160),
            document_type=optional_string(document_type),
            asset_kind=optional_string(asset_kind),
            field_key=optional_string(field_key),
            role=optional_string(role),
            is_primary=None if is_primary is None else normalize_bool(is_primary),
            context_type=optional_string(context_type),
            context_db_id=normalize_int(context_db_id, default=None, minimum=1),
            context_id=optional_string(context_id),
            context_uid=optional_string(context_uid),
            vplib_uid=optional_string(vplib_uid),
            family_id=optional_string(family_id),
            package_id=optional_string(package_id),
            variant_id=optional_string(variant_id),
            revision_hash=optional_string(revision_hash),
            user_id=normalize_user_id(user_id, default=DEFAULT_USER_ID),
            owner_user_id=normalize_user_id(owner_user_id or user_id, default=DEFAULT_USER_ID),
            source_scope=clean_string(source_scope, fallback="user"),
            storage_backend=clean_string(storage_backend, fallback=self.storage_backend),
            metadata=normalize_json_mapping(metadata),
            payload=normalize_json_mapping(payload),
            replace_single=replace_single,
        )
        return self.upload_from_request(request_payload, commit=commit)

    def upload_from_request(
        self,
        request_payload: UploadRequest,
        *,
        commit: bool = True,
    ) -> dict[str, Any]:
        """Uploads using normalized UploadRequest."""
        stored: StoredUpload | None = None

        try:
            constraints = self.resolve_upload_constraints(
                user_id=request_payload.user_id,
                document_type=request_payload.document_type,
                field_key=request_payload.field_key,
            )

            pre_validation = self.validate_upload_metadata(
                original_filename=request_payload.resolved_original_filename(),
                mime_type=request_payload.resolved_mime_type(),
                document_type=request_payload.document_type,
                constraints=constraints,
                size_bytes=None,
            )
            pre_validation.raise_if_invalid()

            stored = self.store_upload_content(request_payload, constraints=constraints)

            post_validation = self.validate_upload_metadata(
                original_filename=stored.original_filename,
                mime_type=stored.mime_type,
                document_type=request_payload.document_type,
                constraints=constraints,
                size_bytes=stored.size_bytes,
            )
            post_validation.raise_if_invalid()

            file_payload = self.build_file_payload(
                request_payload,
                stored,
                constraints=constraints,
            )
            version_payload = self.build_version_payload(
                request_payload,
                stored,
                constraints=constraints,
            )

            file = self.repository.create_file(
                file_payload,
                owner_user_id=request_payload.owner_user_id,
                source_scope=request_payload.source_scope,
                created_by_user_id=request_payload.user_id,
                commit=False,
                audit=True,
            )

            version = self.repository.add_file_version(
                getattr(file, "id", None),
                version_payload,
                uploaded_by_user_id=request_payload.user_id,
                make_current=True,
                mark_previous_replaced=False,
                commit=False,
                audit=True,
            )

            link = None
            link_payload = self.build_link_payload(
                request_payload,
                file=file,
                version=version,
                constraints=constraints,
            )

            if link_payload is not None:
                replace_existing = self.should_replace_existing_link(
                    request_payload,
                    constraints=constraints,
                )

                if replace_existing:
                    link = self.repository.replace_single_link_for_context(
                        file_ref=getattr(file, "id", None),
                        payload=link_payload,
                        file_version_ref=getattr(version, "id", None),
                        user_id=request_payload.user_id,
                        commit=False,
                        audit=True,
                    )
                else:
                    link = self.repository.create_link(
                        file_ref=getattr(file, "id", None),
                        payload=link_payload,
                        file_version_ref=getattr(version, "id", None),
                        user_id=request_payload.user_id,
                        created_by_user_id=request_payload.user_id,
                        commit=False,
                        audit=True,
                    )

            if commit:
                self.repository.commit()
            else:
                self.repository.flush()

            return FileServiceResult(
                ok=True,
                status=STATUS_OK,
                action="upload",
                payload={
                    "file": self.repository.get_file_payload(
                        getattr(file, "id", None),
                        include_current_version=True,
                        include_versions=False,
                        include_links=True,
                    ),
                    "version": version.to_dict() if hasattr(version, "to_dict") else normalize_json_mapping(version_payload),
                    "link": link.to_dict(include_file=False, include_version=False) if link is not None and hasattr(link, "to_dict") else None,
                    "stored": stored.to_dict(),
                    "validation": post_validation.to_dict(),
                    "constraints": normalize_json_mapping(constraints),
                },
                warnings=post_validation.warnings,
            ).to_dict()

        except Exception as exc:
            remove_file_if_exists(stored.cleanup_path if stored else None)

            if commit:
                try:
                    self.repository.rollback()
                except Exception:
                    pass

            if isinstance(exc, LibraryFileValidationError):
                return FileServiceResult(
                    ok=False,
                    status=STATUS_INVALID_REQUEST,
                    action="upload",
                    errors=exc.errors or [str(exc)],
                ).to_dict()

            raise

    # ------------------------------------------------------------------
    # Existing file/version operations
    # ------------------------------------------------------------------

    def replace_version(
        self,
        file_ref: Any,
        *,
        content: Any,
        original_filename: Any = None,
        mime_type: Any = None,
        user_id: Any = DEFAULT_USER_ID,
        metadata: Mapping[str, Any] | None = None,
        payload: Mapping[str, Any] | None = None,
        storage_backend: Any = None,
        commit: bool = True,
    ) -> dict[str, Any]:
        """Stores a new current version for an existing file."""
        stored: StoredUpload | None = None

        try:
            file = self.repository.require_file(file_ref, include_deleted=False, for_update=True)
            document_type = getattr(file, "document_type", None)

            request_payload = UploadRequest(
                content=content,
                original_filename=optional_string(original_filename),
                mime_type=optional_string(mime_type, max_length=160),
                document_type=document_type,
                asset_kind=getattr(file, "asset_kind", None),
                owner_user_id=getattr(file, "owner_user_id", DEFAULT_USER_ID),
                user_id=normalize_user_id(user_id, default=DEFAULT_USER_ID),
                source_scope=getattr(file, "source_scope", "user"),
                storage_backend=clean_string(storage_backend, fallback=getattr(file, "storage_backend", self.storage_backend)),
                metadata=normalize_json_mapping(metadata),
                payload=normalize_json_mapping(payload),
            )

            constraints = self.resolve_upload_constraints(
                user_id=request_payload.user_id,
                document_type=request_payload.document_type,
                field_key=None,
            )

            pre_validation = self.validate_upload_metadata(
                original_filename=request_payload.resolved_original_filename(),
                mime_type=request_payload.resolved_mime_type(),
                document_type=request_payload.document_type,
                constraints=constraints,
                size_bytes=None,
            )
            pre_validation.raise_if_invalid()

            stored = self.store_upload_content(request_payload, constraints=constraints)

            post_validation = self.validate_upload_metadata(
                original_filename=stored.original_filename,
                mime_type=stored.mime_type,
                document_type=request_payload.document_type,
                constraints=constraints,
                size_bytes=stored.size_bytes,
            )
            post_validation.raise_if_invalid()

            version_payload = self.build_version_payload(
                request_payload,
                stored,
                constraints=constraints,
            )

            version = self.repository.replace_current_version(
                getattr(file, "id", None),
                version_payload,
                uploaded_by_user_id=request_payload.user_id,
                commit=commit,
                audit=True,
            )

            return FileServiceResult(
                ok=True,
                status=STATUS_OK,
                action="replace_version",
                payload={
                    "file": self.repository.get_file_payload(
                        getattr(file, "id", None),
                        include_current_version=True,
                        include_versions=False,
                        include_links=True,
                    ),
                    "version": version.to_dict() if hasattr(version, "to_dict") else normalize_json_mapping(version_payload),
                    "stored": stored.to_dict(),
                    "validation": post_validation.to_dict(),
                },
                warnings=post_validation.warnings,
            ).to_dict()

        except Exception as exc:
            remove_file_if_exists(stored.cleanup_path if stored else None)

            if commit:
                try:
                    self.repository.rollback()
                except Exception:
                    pass

            if isinstance(exc, LibraryFileValidationError):
                return FileServiceResult(
                    ok=False,
                    status=STATUS_INVALID_REQUEST,
                    action="replace_version",
                    errors=exc.errors or [str(exc)],
                ).to_dict()

            raise

    def link_existing_file(
        self,
        *,
        file_ref: Any,
        file_version_ref: Any = None,
        user_id: Any = DEFAULT_USER_ID,
        context_type: Any,
        context_db_id: Any = None,
        context_id: Any = None,
        context_uid: Any = None,
        field_key: Any = None,
        document_type: Any = None,
        role: Any = None,
        is_primary: Any = None,
        vplib_uid: Any = None,
        family_id: Any = None,
        package_id: Any = None,
        variant_id: Any = None,
        revision_hash: Any = None,
        replace_single: bool | None = None,
        metadata: Mapping[str, Any] | None = None,
        payload: Mapping[str, Any] | None = None,
        commit: bool = True,
    ) -> dict[str, Any]:
        """Links an existing file to a context."""
        try:
            file = self.repository.require_file(file_ref, include_deleted=False)
            version = self.repository.get_version(file_version_ref) if file_version_ref is not None else self.repository.get_current_version(getattr(file, "id", None))

            resolved_document_type = optional_string(document_type) or getattr(file, "document_type", None)
            constraints = self.resolve_upload_constraints(
                user_id=user_id,
                document_type=resolved_document_type,
                field_key=field_key,
            )

            request_payload = UploadRequest(
                content=b"",
                original_filename=getattr(file, "original_filename", None),
                mime_type=getattr(file, "mime_type", None),
                document_type=resolved_document_type,
                asset_kind=getattr(file, "asset_kind", None),
                field_key=optional_string(field_key),
                role=optional_string(role),
                is_primary=None if is_primary is None else normalize_bool(is_primary),
                context_type=optional_string(context_type),
                context_db_id=normalize_int(context_db_id, default=None, minimum=1),
                context_id=optional_string(context_id),
                context_uid=optional_string(context_uid),
                vplib_uid=optional_string(vplib_uid),
                family_id=optional_string(family_id),
                package_id=optional_string(package_id),
                variant_id=optional_string(variant_id),
                revision_hash=optional_string(revision_hash),
                user_id=normalize_user_id(user_id, default=DEFAULT_USER_ID),
                owner_user_id=getattr(file, "owner_user_id", DEFAULT_USER_ID),
                metadata=normalize_json_mapping(metadata),
                payload=normalize_json_mapping(payload),
                replace_single=replace_single,
            )

            link_payload = self.build_link_payload(
                request_payload,
                file=file,
                version=version,
                constraints=constraints,
            )

            if link_payload is None:
                raise ValueError("context_type is required to link an existing file.")

            if self.should_replace_existing_link(request_payload, constraints=constraints):
                link = self.repository.replace_single_link_for_context(
                    file_ref=getattr(file, "id", None),
                    payload=link_payload,
                    file_version_ref=getattr(version, "id", None) if version is not None else None,
                    user_id=request_payload.user_id,
                    commit=commit,
                    audit=True,
                )
            else:
                link = self.repository.create_link(
                    file_ref=getattr(file, "id", None),
                    payload=link_payload,
                    file_version_ref=getattr(version, "id", None) if version is not None else None,
                    user_id=request_payload.user_id,
                    created_by_user_id=request_payload.user_id,
                    commit=commit,
                    audit=True,
                )

            return FileServiceResult(
                ok=True,
                status=STATUS_OK,
                action="link_existing_file",
                payload={
                    "file": self.repository.get_file_payload(getattr(file, "id", None)),
                    "link": link.to_dict(include_file=False, include_version=True) if hasattr(link, "to_dict") else normalize_json_mapping(link_payload),
                    "constraints": normalize_json_mapping(constraints),
                },
            ).to_dict()

        except Exception:
            if commit:
                try:
                    self.repository.rollback()
                except Exception:
                    pass
            raise

    # ------------------------------------------------------------------
    # Reads / deletes
    # ------------------------------------------------------------------

    def get_file(self, file_ref: Any) -> dict[str, Any]:
        """Returns one file payload."""
        try:
            payload = self.repository.get_file_payload(
                file_ref,
                include_current_version=True,
                include_versions=True,
                include_links=True,
            )
            return FileServiceResult(
                ok=True,
                status=STATUS_OK,
                action="get_file",
                payload={"file": payload},
            ).to_dict()
        except Exception as exc:
            return self.exception_result(exc, action="get_file")

    def list_files(self, *, query: Mapping[str, Any] | None = None) -> dict[str, Any]:
        """Lists files."""
        try:
            files = self.repository.list_file_payloads(query=query)
            return FileServiceResult(
                ok=True,
                status=STATUS_OK,
                action="list_files",
                payload={
                    "items": files,
                    "count": len(files),
                    "query": normalize_json_mapping(query),
                },
            ).to_dict()
        except Exception as exc:
            return self.exception_result(exc, action="list_files")

    def list_links(self, *, query: Mapping[str, Any] | None = None) -> dict[str, Any]:
        """Lists file links."""
        try:
            links = self.repository.list_link_payloads(query=query, include_file=True, include_version=True)
            return FileServiceResult(
                ok=True,
                status=STATUS_OK,
                action="list_links",
                payload={
                    "items": links,
                    "count": len(links),
                    "query": normalize_json_mapping(query),
                },
            ).to_dict()
        except Exception as exc:
            return self.exception_result(exc, action="list_links")

    def delete_file(self, file_ref: Any, *, user_id: Any = DEFAULT_USER_ID, commit: bool = True) -> dict[str, Any]:
        """Soft-deletes file metadata and links."""
        try:
            deleted = self.repository.soft_delete_file(
                file_ref,
                user_id=user_id,
                commit=commit,
                audit=True,
            )
            return FileServiceResult(
                ok=True,
                status=STATUS_OK,
                action="delete_file",
                payload={
                    "file_ref": file_ref,
                    "deleted": deleted,
                },
            ).to_dict()
        except Exception as exc:
            return self.exception_result(exc, action="delete_file")

    def delete_link(self, link_ref: Any, *, user_id: Any = DEFAULT_USER_ID, commit: bool = True) -> dict[str, Any]:
        """Soft-deletes a file link."""
        try:
            deleted = self.repository.soft_delete_link(
                link_ref,
                user_id=user_id,
                commit=commit,
                audit=True,
            )
            return FileServiceResult(
                ok=True,
                status=STATUS_OK,
                action="delete_link",
                payload={
                    "link_ref": link_ref,
                    "deleted": deleted,
                },
            ).to_dict()
        except Exception as exc:
            return self.exception_result(exc, action="delete_link")

    # ------------------------------------------------------------------
    # Validation / constraints
    # ------------------------------------------------------------------

    def resolve_upload_constraints(
        self,
        *,
        user_id: Any = DEFAULT_USER_ID,
        document_type: Any = None,
        field_key: Any = None,
    ) -> dict[str, Any]:
        """Resolves upload constraints from Definition Catalog."""
        resolved_document_type = optional_string(document_type)
        resolved_field_key = optional_string(field_key)

        if self.definition_service is None:
            return {
                "enabled": True,
                "document_type": resolved_document_type,
                "field_key": resolved_field_key,
                "multiple": True,
                "max_size_mb": DEFAULT_MAX_UPLOAD_MB,
                "allowed_extensions": [],
                "allowed_mime_types": [],
                "source": "fallback",
            }

        try:
            response = self.definition_service.get_upload_constraints(
                user_id=user_id,
                document_type=resolved_document_type,
                field_key=resolved_field_key,
            )
            data = normalize_json_mapping(response)

            constraints = normalize_json_mapping(data.get("constraints"))
            if constraints:
                return constraints

            return data
        except Exception:
            return {
                "enabled": True,
                "document_type": resolved_document_type,
                "field_key": resolved_field_key,
                "multiple": True,
                "max_size_mb": DEFAULT_MAX_UPLOAD_MB,
                "allowed_extensions": [],
                "allowed_mime_types": [],
                "source": "fallback_after_definition_error",
            }

    def validate_upload_metadata(
        self,
        *,
        original_filename: Any,
        mime_type: Any = None,
        document_type: Any = None,
        constraints: Mapping[str, Any] | None = None,
        size_bytes: int | None = None,
    ) -> UploadValidationResult:
        """Validates upload metadata against constraints."""
        constraint_payload = normalize_json_mapping(constraints)
        filename = sanitize_filename(original_filename)
        extension = extension_from_filename(filename)
        resolved_mime = guess_mime_type(filename, mime_type)

        result = UploadValidationResult(
            ok=True,
            constraints=constraint_payload,
            original_filename=filename,
            safe_filename=sanitize_filename(filename),
            extension=extension,
            mime_type=resolved_mime,
            size_bytes=size_bytes,
        )

        if not filename:
            result.add_error("filename is required.")

        if not extension:
            result.add_error("file extension is required.")

        if not normalize_bool(constraint_payload.get("enabled"), default=True):
            result.add_error("upload is disabled for this field or document type.")

        expected_document_type = optional_string(constraint_payload.get("document_type"))
        provided_document_type = optional_string(document_type)

        if expected_document_type and provided_document_type and expected_document_type != provided_document_type:
            result.add_error(
                f"document_type mismatch: expected {expected_document_type!r}, got {provided_document_type!r}."
            )

        allowed_extensions = normalize_extension_set(constraint_payload.get("allowed_extensions"))
        if allowed_extensions and extension not in allowed_extensions:
            result.add_error(
                f"extension {extension!r} is not allowed. Allowed: {sorted(allowed_extensions)}."
            )

        allowed_mime_types = normalize_mime_set(constraint_payload.get("allowed_mime_types"))
        if allowed_mime_types:
            if not resolved_mime:
                result.add_error(
                    f"mime_type could not be determined. Allowed: {sorted(allowed_mime_types)}."
                )
            elif not any(mime_matches(resolved_mime, allowed) for allowed in allowed_mime_types):
                result.add_error(
                    f"mime_type {resolved_mime!r} is not allowed. Allowed: {sorted(allowed_mime_types)}."
                )

        max_size_bytes = mb_to_bytes(constraint_payload.get("max_size_mb") or DEFAULT_MAX_UPLOAD_MB)
        result.max_size_bytes = max_size_bytes

        if size_bytes is not None and max_size_bytes is not None and size_bytes > max_size_bytes:
            result.add_error(
                f"file is too large: {bytes_to_mb(size_bytes)} MB > {bytes_to_mb(max_size_bytes)} MB."
            )

        return result

    def should_replace_existing_link(
        self,
        request_payload: UploadRequest,
        *,
        constraints: Mapping[str, Any] | None = None,
    ) -> bool:
        """Determines single/multiple behavior."""
        if request_payload.replace_single is not None:
            return bool(request_payload.replace_single)

        constraint_payload = normalize_json_mapping(constraints)
        multiple = normalize_bool(constraint_payload.get("multiple"), default=True)

        return not multiple

    # ------------------------------------------------------------------
    # Storage
    # ------------------------------------------------------------------

    def store_upload_content(
        self,
        request_payload: UploadRequest,
        *,
        constraints: Mapping[str, Any] | None = None,
    ) -> StoredUpload:
        """Stores upload content according to requested backend."""
        backend = clean_string(request_payload.storage_backend, fallback=self.storage_backend)

        if backend == STORAGE_BACKEND_LOCAL:
            return self.store_local_upload(request_payload, constraints=constraints)

        if backend == STORAGE_BACKEND_POSTGRES_BYTEA:
            return self.store_postgres_bytea_upload(request_payload, constraints=constraints)

        if backend == STORAGE_BACKEND_OBJECT_STORAGE:
            raise LibraryFileUnsupportedStorageError("object_storage backend is not implemented yet.")

        raise LibraryFileUnsupportedStorageError(f"Unsupported storage_backend {backend!r}.")

    def store_local_upload(
        self,
        request_payload: UploadRequest,
        *,
        constraints: Mapping[str, Any] | None = None,
    ) -> StoredUpload:
        """Writes upload stream to local storage and computes SHA-256."""
        original_filename = request_payload.resolved_original_filename()
        safe_filename = sanitize_filename(original_filename)
        extension = extension_from_filename(safe_filename)
        mime_type = request_payload.resolved_mime_type()

        storage_token = str(uuid.uuid4()).lower()
        owner = f"user_{request_payload.owner_user_id or DEFAULT_USER_ID}"
        target_dir = self.storage_root / owner / now_path_part()
        ensure_directory(target_dir)

        storage_filename = f"{storage_token}{extension or ''}"
        target_path = (target_dir / storage_filename).resolve()

        try:
            target_path.relative_to(self.storage_root)
        except Exception as exc:
            raise LibraryFileStorageError("Resolved target path escaped storage root.") from exc

        stream, should_close = open_binary_stream(request_payload.content)
        sha256 = hashlib.sha256()
        size_bytes = 0

        try:
            with target_path.open("wb") as handle:
                while True:
                    chunk = stream.read(DEFAULT_CHUNK_SIZE)
                    if not chunk:
                        break

                    if isinstance(chunk, str):
                        chunk = chunk.encode("utf-8")

                    sha256.update(chunk)
                    size_bytes += len(chunk)
                    handle.write(chunk)
        except Exception as exc:
            remove_file_if_exists(target_path)
            raise LibraryFileStorageError(f"Could not write upload to local storage: {exc}") from exc
        finally:
            if should_close:
                try:
                    stream.close()
                except Exception:
                    pass

        return StoredUpload(
            storage_backend=STORAGE_BACKEND_LOCAL,
            storage_path=str(target_path),
            external_uri=None,
            binary_data=None,
            size_bytes=size_bytes,
            sha256=sha256.hexdigest(),
            safe_filename=safe_filename,
            original_filename=original_filename,
            extension=extension,
            mime_type=mime_type,
            cleanup_path=target_path,
        )

    def store_postgres_bytea_upload(
        self,
        request_payload: UploadRequest,
        *,
        constraints: Mapping[str, Any] | None = None,
    ) -> StoredUpload:
        """
        Reads upload into bytes for postgres_bytea storage.

        This backend is prepared for smaller files. For large GLB/GLTF files,
        prefer local/object storage.
        """
        original_filename = request_payload.resolved_original_filename()
        safe_filename = sanitize_filename(original_filename)
        extension = extension_from_filename(safe_filename)
        mime_type = request_payload.resolved_mime_type()

        stream, should_close = open_binary_stream(request_payload.content)

        try:
            data = stream.read()
            if isinstance(data, str):
                data = data.encode("utf-8")
        except Exception as exc:
            raise LibraryFileStorageError(f"Could not read upload for postgres_bytea storage: {exc}") from exc
        finally:
            if should_close:
                try:
                    stream.close()
                except Exception:
                    pass

        binary = bytes(data or b"")
        sha256 = hashlib.sha256(binary).hexdigest()

        return StoredUpload(
            storage_backend=STORAGE_BACKEND_POSTGRES_BYTEA,
            storage_path=None,
            external_uri=None,
            binary_data=binary,
            size_bytes=len(binary),
            sha256=sha256,
            safe_filename=safe_filename,
            original_filename=original_filename,
            extension=extension,
            mime_type=mime_type,
            cleanup_path=None,
        )

    # ------------------------------------------------------------------
    # Payload builders
    # ------------------------------------------------------------------

    def build_file_payload(
        self,
        request_payload: UploadRequest,
        stored: StoredUpload,
        *,
        constraints: Mapping[str, Any] | None = None,
    ) -> dict[str, Any]:
        """Builds LibraryFile payload."""
        constraint_payload = normalize_json_mapping(constraints)

        return {
            **stored.to_file_payload(),
            "document_type": request_payload.document_type or constraint_payload.get("document_type"),
            "asset_kind": request_payload.asset_kind or DEFAULT_ASSET_KIND_DOCUMENT,
            "owner_user_id": request_payload.owner_user_id,
            "source_scope": request_payload.source_scope,
            "status": "active",
            "active": True,
            "visible": True,
            "payload": {
                **normalize_json_mapping(request_payload.payload),
                "constraints": constraint_payload,
                "request": request_payload.to_dict(),
            },
            "meta": normalize_json_mapping(request_payload.metadata),
            "metadata": normalize_json_mapping(request_payload.metadata),
        }

    def build_version_payload(
        self,
        request_payload: UploadRequest,
        stored: StoredUpload,
        *,
        constraints: Mapping[str, Any] | None = None,
    ) -> dict[str, Any]:
        """Builds LibraryFileVersion payload."""
        payload = {
            **stored.to_file_payload(),
            "status": "active",
            "active": True,
            "payload": {
                **normalize_json_mapping(request_payload.payload),
                "constraints": normalize_json_mapping(constraints),
            },
            "meta": normalize_json_mapping(request_payload.metadata),
            "metadata": normalize_json_mapping(request_payload.metadata),
        }

        if stored.storage_backend != STORAGE_BACKEND_POSTGRES_BYTEA:
            payload.pop("binary_data", None)

        return payload

    def build_link_payload(
        self,
        request_payload: UploadRequest,
        *,
        file: Any = None,
        version: Any = None,
        constraints: Mapping[str, Any] | None = None,
    ) -> dict[str, Any] | None:
        """Builds LibraryFileLink payload if context_type is present."""
        if not request_payload.context_type:
            return None

        document_type = request_payload.document_type or normalize_json_mapping(constraints).get("document_type")
        role = request_payload.role or DEFAULT_ROLE_PRIMARY if request_payload.is_primary else request_payload.role or DEFAULT_ROLE_ATTACHMENT

        return {
            "user_id": request_payload.user_id,
            "context_type": request_payload.context_type,
            "context_db_id": request_payload.context_db_id,
            "context_id": request_payload.context_id,
            "context_uid": request_payload.context_uid,
            "vplib_uid": request_payload.vplib_uid,
            "family_id": request_payload.family_id,
            "package_id": request_payload.package_id,
            "variant_id": request_payload.variant_id,
            "revision_hash": request_payload.revision_hash,
            "field_key": request_payload.field_key,
            "document_type": document_type,
            "role": role,
            "is_primary": request_payload.is_primary if request_payload.is_primary is not None else role == DEFAULT_ROLE_PRIMARY,
            "active": True,
            "status": "active",
            "payload": {
                **normalize_json_mapping(request_payload.payload),
                "constraints": normalize_json_mapping(constraints),
                "file_uid": getattr(file, "file_uid", None),
                "version_uid": getattr(version, "version_uid", None),
            },
            "meta": normalize_json_mapping(request_payload.metadata),
            "metadata": normalize_json_mapping(request_payload.metadata),
        }

    # ------------------------------------------------------------------
    # Diagnostics
    # ------------------------------------------------------------------

    def get_health(self) -> dict[str, Any]:
        """Returns service health snapshot."""
        repository_health = {}
        definition_health = {}

        try:
            if hasattr(self.repository, "get_health"):
                repository_health = self.repository.get_health()
        except Exception as exc:
            repository_health = {"ok": False, "error": f"{type(exc).__name__}: {exc}"}

        try:
            if self.definition_service is not None and hasattr(self.definition_service, "get_health"):
                definition_health = self.definition_service.get_health()
        except Exception as exc:
            definition_health = {"ok": False, "error": f"{type(exc).__name__}: {exc}"}

        return {
            "schema_version": LIBRARY_FILE_SERVICE_VERSION,
            "ok": True,
            "healthy": True,
            "service": type(self).__name__,
            "storage_backend": self.storage_backend,
            "storage_root": str(self.storage_root),
            "storage_root_exists": self.storage_root.exists(),
            "repository_health": normalize_json_mapping(repository_health),
            "definition_service_health": normalize_json_mapping(definition_health),
            "supports_local_storage": True,
            "supports_postgres_bytea": True,
            "supports_object_storage": False,
            "supports_upload_validation": True,
            "supports_file_versions": True,
            "supports_context_links": True,
            "supports_single_multiple_rules": True,
        }

    def exception_result(self, exc: Exception, *, action: str) -> dict[str, Any]:
        """Maps exception to service result."""
        lowered = f"{type(exc).__name__} {exc}".lower()

        status = STATUS_FAILED
        if "notfound" in lowered or "not found" in lowered:
            status = STATUS_NOT_FOUND
        elif "invalid" in lowered or "validation" in lowered or "required" in lowered:
            status = STATUS_INVALID_REQUEST

        errors = getattr(exc, "errors", None)
        if errors:
            error_list = [str(error) for error in errors]
        else:
            error_list = [str(exc)]

        return FileServiceResult(
            ok=False,
            status=status,
            action=action,
            errors=error_list,
        ).to_dict()


# ---------------------------------------------------------------------------
# Factory helpers
# ---------------------------------------------------------------------------

def create_library_file_service(
    repository: Any | None = None,
    definition_service: Any | None = None,
    storage_root: Path | str | None = None,
    storage_backend: str = DEFAULT_STORAGE_BACKEND,
) -> LibraryFileService:
    """Factory for dependency injection."""
    return LibraryFileService(
        repository=repository,
        definition_service=definition_service,
        storage_root=storage_root,
        storage_backend=storage_backend,
    )


@lru_cache(maxsize=1)
def get_service_version() -> str:
    """Cached service version helper."""
    return LIBRARY_FILE_SERVICE_VERSION


def clear_library_file_service_caches() -> dict[str, Any]:
    """Clears service import/static caches."""
    cleared: list[str] = []

    for cached_func in (
        _load_repository_module,
        _load_definition_catalog_service_module,
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
    "LIBRARY_FILE_SERVICE_VERSION",
    "DEFAULT_USER_ID",
    "STORAGE_BACKEND_LOCAL",
    "STORAGE_BACKEND_POSTGRES_BYTEA",
    "STORAGE_BACKEND_OBJECT_STORAGE",
    "DEFAULT_STORAGE_BACKEND",
    "DEFAULT_CHUNK_SIZE",
    "DEFAULT_MAX_UPLOAD_MB",

    # Exceptions
    "LibraryFileServiceError",
    "LibraryFileServiceImportError",
    "LibraryFileValidationError",
    "LibraryFileStorageError",
    "LibraryFileUnsupportedStorageError",

    # Dataclasses
    "UploadValidationResult",
    "StoredUpload",
    "UploadRequest",
    "FileServiceResult",

    # Service
    "LibraryFileService",
    "create_library_file_service",

    # Helpers
    "utc_now",
    "clean_string",
    "optional_string",
    "normalize_int",
    "normalize_user_id",
    "normalize_bool",
    "normalize_json_mapping",
    "normalize_json_list",
    "normalize_json_value",
    "bytes_to_mb",
    "mb_to_bytes",
    "normalize_extension",
    "extension_from_filename",
    "normalize_extension_set",
    "normalize_mime_set",
    "mime_matches",
    "sanitize_filename",
    "guess_mime_type",
    "get_config_value",
    "default_storage_root",
    "ensure_directory",
    "remove_file_if_exists",
    "extract_file_storage_filename",
    "extract_file_storage_mime",
    "open_binary_stream",
    "get_service_version",
    "clear_library_file_service_caches",
]