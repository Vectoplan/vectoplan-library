# services/vectoplan-library/models/library_files.py
"""
Database models for VECTOPLAN Library Files.

Diese Datei modelliert die generische Upload-/Datei-Schicht für:

- Dokumente
- Bilder
- technische Zeichnungen
- 3D-Modelle / GLB / GLTF
- Text-/JSON-Anhänge
- generierte Assets
- User-Dateien
- Links zwischen Dateien und VPLIB/Families/Variants/Drafts/Definitions

Ziel:

    Upload / Generator / Import
        -> LibraryFileService
        -> LibraryFile
        -> LibraryFileVersion
        -> LibraryFileLink
        -> PostgreSQL metadata
        -> storage_backend local | postgres_bytea | object_storage | external_uri

Wichtige Architekturregeln:

- Diese Datei erzeugt keine Tabellen.
- Diese Datei führt keine Migration aus.
- Diese Datei führt kein db.create_all() aus.
- Diese Datei spricht keine Datenbankverbindung aktiv an.
- Diese Datei schreibt keine Dateien ins Dateisystem.
- Diese Datei speichert nur Metadaten, optionale BYTEA-Daten und Beziehungen.
- Die eigentliche Dateiablage macht später der File-Service.
- Große Dateien, insbesondere GLB/GLTF, sollten standardmäßig nicht als BYTEA
  gespeichert werden, sondern über storage_path/object storage referenziert werden.
- Technische Namen, JSON-Keys und Variablen bleiben Englisch.

Phase 1:

- user_id darf weiterhin 1 sein.
- owner_user_id=None bedeutet system-owned.
- owner_scope="system" bedeutet globale Systemdatei.
- owner_scope="user:<id>" bedeutet User-Datei.
"""

from __future__ import annotations

import enum
import hashlib
import json
import mimetypes
import uuid
from datetime import datetime, timezone
from functools import lru_cache
from typing import Any, Final, Iterable, Mapping


# ---------------------------------------------------------------------------
# Metadata / constants
# ---------------------------------------------------------------------------

LIBRARY_FILES_MODELS_SCHEMA_VERSION: Final[str] = "vectoplan_library.library_files.models.v1"
DEFAULT_USER_ID: Final[int] = 1

MAX_UID_LENGTH: Final[int] = 80
MAX_FILENAME_LENGTH: Final[int] = 512
MAX_SAFE_FILENAME_LENGTH: Final[int] = 512
MAX_EXTENSION_LENGTH: Final[int] = 32
MAX_MIME_TYPE_LENGTH: Final[int] = 160
MAX_STATUS_LENGTH: Final[int] = 40
MAX_SOURCE_SCOPE_LENGTH: Final[int] = 40
MAX_OWNER_SCOPE_LENGTH: Final[int] = 120
MAX_DOCUMENT_TYPE_LENGTH: Final[int] = 120
MAX_ASSET_KIND_LENGTH: Final[int] = 80
MAX_STORAGE_BACKEND_LENGTH: Final[int] = 80
MAX_ROLE_LENGTH: Final[int] = 80
MAX_CONTEXT_TYPE_LENGTH: Final[int] = 120
MAX_CONTEXT_ID_LENGTH: Final[int] = 255
MAX_FIELD_KEY_LENGTH: Final[int] = 255
MAX_HASH_LENGTH: Final[int] = 128
MAX_LABEL_LENGTH: Final[int] = 255
MAX_VPLIB_UID_LENGTH: Final[int] = 80
MAX_FAMILY_ID_LENGTH: Final[int] = 255
MAX_PACKAGE_ID_LENGTH: Final[int] = 255
MAX_VARIANT_ID_LENGTH: Final[int] = 160

MODEL_3D_EXTENSIONS: Final[tuple[str, ...]] = (".glb", ".gltf")
IMAGE_EXTENSIONS: Final[tuple[str, ...]] = (".png", ".jpg", ".jpeg", ".webp", ".svg")
DRAWING_EXTENSIONS: Final[tuple[str, ...]] = (".dxf", ".dwg")
DOCUMENT_EXTENSIONS: Final[tuple[str, ...]] = (
    ".pdf",
    ".txt",
    ".md",
    ".json",
    ".csv",
    ".png",
    ".jpg",
    ".jpeg",
    ".webp",
)

FORBIDDEN_UPLOAD_EXTENSIONS: Final[tuple[str, ...]] = (
    ".py",
    ".pyc",
    ".pyo",
    ".sh",
    ".bash",
    ".zsh",
    ".bat",
    ".cmd",
    ".ps1",
    ".exe",
    ".dll",
    ".so",
    ".dylib",
    ".rb",
    ".php",
    ".pl",
    ".js",
    ".mjs",
    ".ts",
    ".jar",
)

MANUAL_MIME_TYPES: Final[dict[str, str]] = {
    ".glb": "model/gltf-binary",
    ".gltf": "model/gltf+json",
    ".dxf": "application/dxf",
    ".dwg": "application/octet-stream",
    ".webp": "image/webp",
    ".svg": "image/svg+xml",
    ".md": "text/markdown",
}


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

class LibraryFileSourceScope(str, enum.Enum):
    SYSTEM = "system"
    USER = "user"
    IMPORTED = "imported"
    GENERATED = "generated"
    EXTERNAL = "external"

    @property
    def key(self) -> str:
        return str(self.value)


class LibraryFileStatus(str, enum.Enum):
    PENDING = "pending"
    ACTIVE = "active"
    REPLACED = "replaced"
    QUARANTINED = "quarantined"
    INVALID = "invalid"
    FAILED = "failed"
    DELETED = "deleted"

    @property
    def key(self) -> str:
        return str(self.value)


class LibraryFileStorageBackend(str, enum.Enum):
    LOCAL = "local"
    POSTGRES_BYTEA = "postgres_bytea"
    OBJECT_STORAGE = "object_storage"
    EXTERNAL_URI = "external_uri"
    UNKNOWN = "unknown"

    @property
    def key(self) -> str:
        return str(self.value)


class LibraryFileAssetKind(str, enum.Enum):
    DOCUMENT = "document"
    IMAGE = "image"
    DRAWING = "drawing"
    MODEL_3D = "model_3d"
    TEXTURE = "texture"
    PREVIEW = "preview"
    ICON = "icon"
    MATERIAL = "material"
    RENDER_ASSET = "render_asset"
    GENERATED_PACKAGE = "generated_package"
    OTHER = "other"

    @property
    def key(self) -> str:
        return str(self.value)


class LibraryFileRole(str, enum.Enum):
    PRIMARY = "primary"
    SECONDARY = "secondary"
    ATTACHMENT = "attachment"
    DOCUMENT = "document"
    PREVIEW = "preview"
    ICON = "icon"
    TEXTURE = "texture"
    RENDER_MODEL = "render_model"
    TECHNICAL_DRAWING = "technical_drawing"
    DATASHEET = "datasheet"
    OTHER = "other"

    @property
    def key(self) -> str:
        return str(self.value)


class LibraryFileLinkContextType(str, enum.Enum):
    CREATIVE_ITEM = "creative_item"
    CREATIVE_VARIANT = "creative_variant"
    CREATIVE_REVISION = "creative_revision"
    CREATIVE_DRAFT = "creative_draft"
    DEFINITION = "definition"
    TAXONOMY_NODE = "taxonomy_node"
    USER_INVENTORY_SLOT = "user_inventory_slot"
    GENERATOR_RUN = "generator_run"
    IMPORT_RUN = "import_run"
    OTHER = "other"

    @property
    def key(self) -> str:
        return str(self.value)


class LibraryFileAuditEventType(str, enum.Enum):
    CREATED = "created"
    UPLOADED = "uploaded"
    VERSION_ADDED = "version_added"
    CURRENT_VERSION_CHANGED = "current_version_changed"
    LINKED = "linked"
    UNLINKED = "unlinked"
    REPLACED = "replaced"
    QUARANTINED = "quarantined"
    RESTORED = "restored"
    DELETED = "deleted"
    UPDATED = "updated"

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

    if text in {"1", "true", "yes", "y", "ja", "on", "enabled", "active", "visible", "published"}:
        return True

    if text in {"0", "false", "no", "n", "nein", "off", "disabled", "inactive", "hidden", "deleted"}:
        return False

    return default


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


def sha256_bytes(value: bytes | bytearray | memoryview | None) -> str | None:
    """Erzeugt SHA-256 für Binärdaten, falls vorhanden."""
    if value is None:
        return None

    try:
        return hashlib.sha256(bytes(value)).hexdigest()
    except Exception:
        return None


def normalize_source_scope(value: Any, *, default: str = LibraryFileSourceScope.USER.value) -> str:
    """Normalisiert source_scope."""
    text = enum_value(value, default=default).strip().lower()

    aliases = {
        "core": LibraryFileSourceScope.SYSTEM.value,
        "default": LibraryFileSourceScope.SYSTEM.value,
        "global": LibraryFileSourceScope.SYSTEM.value,
        "system": LibraryFileSourceScope.SYSTEM.value,
        "user": LibraryFileSourceScope.USER.value,
        "custom": LibraryFileSourceScope.USER.value,
        "import": LibraryFileSourceScope.IMPORTED.value,
        "imported": LibraryFileSourceScope.IMPORTED.value,
        "generated": LibraryFileSourceScope.GENERATED.value,
        "generator": LibraryFileSourceScope.GENERATED.value,
        "external": LibraryFileSourceScope.EXTERNAL.value,
        "url": LibraryFileSourceScope.EXTERNAL.value,
    }

    return aliases.get(text, text if text else default)[:MAX_SOURCE_SCOPE_LENGTH]


def owner_scope_for(
    *,
    source_scope: Any = LibraryFileSourceScope.USER.value,
    owner_user_id: Any = DEFAULT_USER_ID,
) -> str:
    """
    Baut einen stabilen owner_scope.

    PostgreSQL behandelt NULL in UniqueConstraints nicht als gleich.
    Deshalb wird zusätzlich ein nicht-nullbarer owner_scope gespeichert.
    """

    scope = normalize_source_scope(source_scope)
    user_id = normalize_user_id(owner_user_id, default=None)

    if scope == LibraryFileSourceScope.SYSTEM.value and user_id is None:
        return LibraryFileSourceScope.SYSTEM.value

    if scope == LibraryFileSourceScope.USER.value:
        return f"user:{user_id or DEFAULT_USER_ID}"

    if user_id is not None:
        return f"{scope}:{user_id}"

    return scope or LibraryFileSourceScope.USER.value


def normalize_status(value: Any, *, default: str = LibraryFileStatus.ACTIVE.value) -> str:
    """Normalisiert Status."""
    text = enum_value(value, default=default).strip().lower()
    return (text or default)[:MAX_STATUS_LENGTH]


def normalize_storage_backend(
    value: Any,
    *,
    storage_path: Any = None,
    external_uri: Any = None,
    binary_data: Any = None,
    default: str = LibraryFileStorageBackend.LOCAL.value,
) -> str:
    """Normalisiert Storage-Backend mit Fallback aus vorhandenen Feldern."""
    text = enum_value(value, default="").strip().lower()

    aliases = {
        "filesystem": LibraryFileStorageBackend.LOCAL.value,
        "file": LibraryFileStorageBackend.LOCAL.value,
        "local": LibraryFileStorageBackend.LOCAL.value,
        "disk": LibraryFileStorageBackend.LOCAL.value,
        "bytea": LibraryFileStorageBackend.POSTGRES_BYTEA.value,
        "db": LibraryFileStorageBackend.POSTGRES_BYTEA.value,
        "postgres": LibraryFileStorageBackend.POSTGRES_BYTEA.value,
        "postgres_bytea": LibraryFileStorageBackend.POSTGRES_BYTEA.value,
        "s3": LibraryFileStorageBackend.OBJECT_STORAGE.value,
        "object": LibraryFileStorageBackend.OBJECT_STORAGE.value,
        "object_storage": LibraryFileStorageBackend.OBJECT_STORAGE.value,
        "external": LibraryFileStorageBackend.EXTERNAL_URI.value,
        "url": LibraryFileStorageBackend.EXTERNAL_URI.value,
        "uri": LibraryFileStorageBackend.EXTERNAL_URI.value,
    }

    if text:
        return aliases.get(text, text)[:MAX_STORAGE_BACKEND_LENGTH]

    if binary_data is not None:
        return LibraryFileStorageBackend.POSTGRES_BYTEA.value

    if normalize_optional_string(external_uri):
        return LibraryFileStorageBackend.EXTERNAL_URI.value

    if normalize_optional_string(storage_path):
        return LibraryFileStorageBackend.LOCAL.value

    return default


@lru_cache(maxsize=2048)
def _cached_extension_from_filename(filename: str) -> str | None:
    """Cached extension extraction."""
    text = filename.strip().replace("\\", "/").rsplit("/", 1)[-1]

    if not text or "." not in text:
        return None

    extension = "." + text.rsplit(".", 1)[-1].lower().strip()
    if extension == ".":
        return None

    return extension[:MAX_EXTENSION_LENGTH]


def extension_from_filename(filename: Any) -> str | None:
    """Extrahiert Dateiendung aus einem Dateinamen."""
    text = normalize_optional_string(filename, max_length=MAX_FILENAME_LENGTH)
    if not text:
        return None

    return _cached_extension_from_filename(text)


def normalize_extension(value: Any, *, filename: Any = None) -> str | None:
    """Normalisiert Dateiendungen inklusive führendem Punkt."""
    text = normalize_optional_string(value, max_length=MAX_EXTENSION_LENGTH)

    if not text:
        text = extension_from_filename(filename)

    if not text:
        return None

    text = text.strip().lower()

    if not text.startswith("."):
        text = f".{text}"

    return text[:MAX_EXTENSION_LENGTH]


def extension_is_forbidden(extension: Any) -> bool:
    """Prüft, ob eine Dateiendung als Upload gefährlich ist."""
    ext = normalize_extension(extension)
    return bool(ext and ext in FORBIDDEN_UPLOAD_EXTENSIONS)


@lru_cache(maxsize=2048)
def _cached_mime_type_from_extension(extension: str) -> str | None:
    """Cached MIME-Ermittlung aus Extension."""
    ext = normalize_extension(extension)
    if not ext:
        return None

    if ext in MANUAL_MIME_TYPES:
        return MANUAL_MIME_TYPES[ext]

    try:
        guessed, _encoding = mimetypes.guess_type(f"file{ext}")
        if guessed:
            return str(guessed).lower()
    except Exception:
        return None

    return None


def infer_mime_type_from_filename(filename: Any, *, extension: Any = None) -> str | None:
    """Ermittelt MIME-Type aus Dateiname oder Extension."""
    ext = normalize_extension(extension, filename=filename)
    if not ext:
        return None

    return _cached_mime_type_from_extension(ext)


def normalize_mime_type(value: Any, *, filename: Any = None, extension: Any = None) -> str | None:
    """Normalisiert MIME-Type mit Fallback aus Dateiendung."""
    text = normalize_optional_string(value, max_length=MAX_MIME_TYPE_LENGTH)
    if text:
        return text.lower()

    inferred = infer_mime_type_from_filename(filename, extension=extension)
    return inferred[:MAX_MIME_TYPE_LENGTH] if inferred else None


def safe_filename_component(value: Any, *, fallback: str = "file", max_length: int = 180) -> str:
    """Normalisiert Dateinamenbestandteile ohne Pfadanteile."""
    text = normalize_optional_string(value, max_length=max_length)

    if not text:
        text = fallback

    text = text.replace("\\", "/").rsplit("/", 1)[-1]
    cleaned: list[str] = []
    previous_dash = False

    for char in text:
        if char.isalnum():
            cleaned.append(char)
            previous_dash = False
            continue

        if char in {"_", "-", "."}:
            cleaned.append(char)
            previous_dash = False
            continue

        if not previous_dash:
            cleaned.append("-")
            previous_dash = True

    result = "".join(cleaned).strip(" ._-")
    return result[:max_length] if result else fallback


def build_safe_filename(
    original_filename: Any,
    *,
    file_uid: Any = None,
    fallback: str = "file",
    max_length: int = MAX_SAFE_FILENAME_LENGTH,
) -> str:
    """Baut einen sicheren Dateinamen ohne Dateisystemzugriff."""
    original = normalize_optional_string(original_filename, max_length=MAX_FILENAME_LENGTH)
    uid = normalize_optional_string(file_uid, max_length=MAX_UID_LENGTH)

    if not original:
        original = uid or fallback

    extension = normalize_extension(None, filename=original)
    base = original

    if extension and base.lower().endswith(extension):
        base = base[: -len(extension)]

    safe_base = safe_filename_component(base, fallback=fallback, max_length=max_length)

    if uid and uid not in safe_base:
        safe_base = f"{safe_base}-{uid[:12]}"

    if extension:
        safe = f"{safe_base}{extension}"
    else:
        safe = safe_base

    return safe[:max_length]


def infer_asset_kind(
    *,
    document_type: Any = None,
    extension: Any = None,
    mime_type: Any = None,
    role: Any = None,
    default: str = LibraryFileAssetKind.OTHER.value,
) -> str:
    """Leitet asset_kind aus Dokumenttyp, Extension, MIME-Type oder Rolle ab."""
    doc_type = clean_string(document_type).lower()
    ext = normalize_extension(extension) or ""
    mime = clean_string(mime_type).lower()
    normalized_role = clean_string(role).lower()

    if doc_type in {"model_3d", "3d_model", "glb", "gltf"}:
        return LibraryFileAssetKind.MODEL_3D.value

    if ext in MODEL_3D_EXTENSIONS or mime in {"model/gltf-binary", "model/gltf+json"}:
        return LibraryFileAssetKind.MODEL_3D.value

    if normalized_role in {"render_model", "model", "mesh"}:
        return LibraryFileAssetKind.MODEL_3D.value

    if normalized_role == "icon":
        return LibraryFileAssetKind.ICON.value

    if normalized_role == "preview":
        return LibraryFileAssetKind.PREVIEW.value

    if normalized_role == "texture":
        return LibraryFileAssetKind.TEXTURE.value

    if doc_type in {"technical_drawing", "drawing"} or ext in DRAWING_EXTENSIONS:
        return LibraryFileAssetKind.DRAWING.value

    if ext in IMAGE_EXTENSIONS or mime.startswith("image/"):
        return LibraryFileAssetKind.IMAGE.value

    if doc_type:
        return LibraryFileAssetKind.DOCUMENT.value

    if ext in DOCUMENT_EXTENSIONS or mime.startswith("application/pdf") or mime.startswith("text/"):
        return LibraryFileAssetKind.DOCUMENT.value

    return default


def normalize_size_bytes(value: Any, *, binary_data: Any = None) -> int | None:
    """Normalisiert Dateigröße."""
    size = normalize_int(value, default=None, minimum=0)
    if size is not None:
        return size

    if binary_data is None:
        return None

    try:
        return len(bytes(binary_data))
    except Exception:
        return None


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

class LibraryFile(TimestampMixin, JsonMixin, db.Model):
    """
    Logische Datei.

    Eine LibraryFile ist der stabile Container für eine Datei über mehrere
    Versionen hinweg. Die aktuelle Version wird über current_version_id
    referenziert.
    """

    __tablename__ = "library_files"

    id = db.Column(db.BigInteger, primary_key=True, autoincrement=True)

    file_uid = db.Column(db.String(MAX_UID_LENGTH), nullable=False, unique=True, index=True, default=new_uid)

    owner_user_id = db.Column(db.BigInteger, nullable=True, index=True)
    source_scope = db.Column(
        db.String(MAX_SOURCE_SCOPE_LENGTH),
        nullable=False,
        default=LibraryFileSourceScope.USER.value,
        index=True,
    )
    owner_scope = db.Column(
        db.String(MAX_OWNER_SCOPE_LENGTH),
        nullable=False,
        default=f"user:{DEFAULT_USER_ID}",
        index=True,
    )

    document_type = db.Column(db.String(MAX_DOCUMENT_TYPE_LENGTH), nullable=True, index=True)
    asset_kind = db.Column(
        db.String(MAX_ASSET_KIND_LENGTH),
        nullable=False,
        default=LibraryFileAssetKind.OTHER.value,
        index=True,
    )

    original_filename = db.Column(db.String(MAX_FILENAME_LENGTH), nullable=True)
    safe_filename = db.Column(db.String(MAX_SAFE_FILENAME_LENGTH), nullable=True, index=True)
    extension = db.Column(db.String(MAX_EXTENSION_LENGTH), nullable=True, index=True)
    mime_type = db.Column(db.String(MAX_MIME_TYPE_LENGTH), nullable=True, index=True)

    size_bytes = db.Column(db.BigInteger, nullable=True)
    sha256 = db.Column(db.String(MAX_HASH_LENGTH), nullable=True, index=True)

    storage_backend = db.Column(
        db.String(MAX_STORAGE_BACKEND_LENGTH),
        nullable=False,
        default=LibraryFileStorageBackend.LOCAL.value,
        index=True,
    )
    storage_path = db.Column(db.Text, nullable=True)
    external_uri = db.Column(db.Text, nullable=True)

    current_version_id = db.Column(
        db.BigInteger,
        db.ForeignKey(
            "library_file_versions.id",
            name="fk_library_files_current_version_id",
            use_alter=True,
            ondelete="SET NULL",
        ),
        nullable=True,
        index=True,
    )
    version_count = db.Column(db.Integer, nullable=False, default=0)

    status = db.Column(
        db.String(MAX_STATUS_LENGTH),
        nullable=False,
        default=LibraryFileStatus.ACTIVE.value,
        index=True,
    )
    active = db.Column(db.Boolean, nullable=False, default=True, index=True)
    visible = db.Column(db.Boolean, nullable=False, default=True, index=True)
    locked = db.Column(db.Boolean, nullable=False, default=False)
    quarantine_reason = db.Column(db.Text, nullable=True)

    uploaded_at = db.Column(db.DateTime(timezone=True), nullable=True)
    replaced_at = db.Column(db.DateTime(timezone=True), nullable=True)
    deleted_at = db.Column(db.DateTime(timezone=True), nullable=True)
    last_accessed_at = db.Column(db.DateTime(timezone=True), nullable=True)

    payload = db.Column(db.JSON, nullable=False, default=dict)
    meta = db.Column(db.JSON, nullable=False, default=dict)
    metadata_json = db.Column(db.JSON, nullable=False, default=dict)

    created_by_user_id = db.Column(db.BigInteger, nullable=True, index=True)
    updated_by_user_id = db.Column(db.BigInteger, nullable=True, index=True)
    deleted_by_user_id = db.Column(db.BigInteger, nullable=True, index=True)

    versions = db.relationship(
        "LibraryFileVersion",
        back_populates="file",
        cascade="all, delete-orphan",
        foreign_keys="LibraryFileVersion.file_id",
        lazy="selectin",
    )
    current_version = db.relationship(
        "LibraryFileVersion",
        foreign_keys=[current_version_id],
        post_update=True,
        lazy="joined",
    )
    links = db.relationship(
        "LibraryFileLink",
        back_populates="file",
        cascade="all, delete-orphan",
        foreign_keys="LibraryFileLink.file_id",
        lazy="selectin",
    )

    __table_args__ = (
        db.Index("ix_library_files_owner_status", "owner_scope", "status", "active", "visible"),
        db.Index("ix_library_files_type_kind", "document_type", "asset_kind"),
        db.Index("ix_library_files_mime_extension", "mime_type", "extension"),
        db.Index("ix_library_files_storage", "storage_backend", "sha256"),
        db.Index("ix_library_files_created_owner", "owner_user_id", "created_at"),
    )

    def __repr__(self) -> str:
        return f"<LibraryFile id={self.id!r} uid={self.file_uid!r} filename={self.safe_filename!r}>"

    @classmethod
    def create_from_payload(
        cls,
        payload: Mapping[str, Any] | None,
        *,
        owner_user_id: Any = DEFAULT_USER_ID,
        source_scope: Any = LibraryFileSourceScope.USER.value,
        created_by_user_id: Any = None,
    ) -> "LibraryFile":
        """Erstellt ein logisches File-Objekt aus Upload-/Import-Metadaten."""
        data = normalize_json_mapping(payload)
        file_uid = normalize_optional_string(data.get("file_uid") or data.get("uid"), max_length=MAX_UID_LENGTH) or new_uid()

        original_filename = normalize_optional_string(
            first_non_empty(
                data.get("original_filename"),
                data.get("filename"),
                data.get("name"),
                data.get("safe_filename"),
                file_uid,
            ),
            max_length=MAX_FILENAME_LENGTH,
        )

        extension = normalize_extension(data.get("extension"), filename=original_filename)
        mime_type = normalize_mime_type(data.get("mime_type") or data.get("mimeType"), filename=original_filename, extension=extension)

        document_type = normalize_optional_string(
            first_non_empty(data.get("document_type"), data.get("documentType"), data.get("type")),
            max_length=MAX_DOCUMENT_TYPE_LENGTH,
        )

        role = first_non_empty(data.get("role"), data.get("file_role"), data.get("asset_role"))
        asset_kind = enum_value(
            data.get("asset_kind") or data.get("assetKind"),
            default=infer_asset_kind(
                document_type=document_type,
                extension=extension,
                mime_type=mime_type,
                role=role,
            ),
        )

        normalized_source_scope = normalize_source_scope(source_scope)
        normalized_owner_user_id = normalize_user_id(owner_user_id, default=None)

        storage_backend = normalize_storage_backend(
            data.get("storage_backend") or data.get("storageBackend"),
            storage_path=data.get("storage_path") or data.get("path"),
            external_uri=data.get("external_uri") or data.get("uri") or data.get("url"),
        )

        now = utc_now()

        return cls(
            file_uid=file_uid,
            owner_user_id=normalized_owner_user_id,
            source_scope=normalized_source_scope,
            owner_scope=owner_scope_for(
                source_scope=normalized_source_scope,
                owner_user_id=normalized_owner_user_id,
            ),
            document_type=document_type,
            asset_kind=asset_kind,
            original_filename=original_filename,
            safe_filename=build_safe_filename(original_filename, file_uid=file_uid),
            extension=extension,
            mime_type=mime_type,
            size_bytes=normalize_size_bytes(data.get("size_bytes") or data.get("sizeBytes")),
            sha256=normalize_optional_string(data.get("sha256") or data.get("checksum"), max_length=MAX_HASH_LENGTH),
            storage_backend=storage_backend,
            storage_path=normalize_optional_string(data.get("storage_path") or data.get("path")),
            external_uri=normalize_optional_string(data.get("external_uri") or data.get("uri") or data.get("url")),
            version_count=0,
            status=normalize_status(data.get("status"), default=LibraryFileStatus.ACTIVE.value),
            active=normalize_bool(data.get("active"), default=True),
            visible=normalize_bool(data.get("visible"), default=True),
            locked=normalize_bool(data.get("locked"), default=False),
            uploaded_at=now,
            payload=data,
            meta=normalize_json_mapping(data.get("meta")),
            metadata_json=normalize_json_mapping(data.get("metadata")),
            created_by_user_id=normalize_user_id(created_by_user_id, default=None),
            updated_by_user_id=normalize_user_id(created_by_user_id, default=None),
        )

    def set_current_version(self, version: "LibraryFileVersion") -> None:
        """Setzt die aktuelle Version und spiegelt wichtigste Metadaten."""
        self.current_version_id = version.id
        self.original_filename = version.original_filename or self.original_filename
        self.safe_filename = version.safe_filename or self.safe_filename
        self.extension = version.extension or self.extension
        self.mime_type = version.mime_type or self.mime_type
        self.size_bytes = version.size_bytes
        self.sha256 = version.sha256 or self.sha256
        self.storage_backend = version.storage_backend or self.storage_backend
        self.storage_path = version.storage_path or self.storage_path
        self.external_uri = version.external_uri or self.external_uri
        self.status = LibraryFileStatus.ACTIVE.value
        self.active = True
        self.visible = True
        self.deleted_at = None
        self.replaced_at = utc_now()
        self.version_count = max(normalize_int(self.version_count, default=0, minimum=0) or 0, version.version_index or 1)
        self.touch()

    def mark_deleted(self, *, user_id: Any = None) -> None:
        """Soft-delete für logische Datei und Links."""
        self.status = LibraryFileStatus.DELETED.value
        self.active = False
        self.visible = False
        self.deleted_at = utc_now()
        self.deleted_by_user_id = normalize_user_id(user_id, default=None)
        self.updated_by_user_id = normalize_user_id(user_id, default=self.updated_by_user_id)
        self.touch()

        for link in getattr(self, "links", []) or []:
            try:
                link.mark_deleted(user_id=user_id)
            except Exception:
                continue

    def mark_quarantined(self, *, reason: Any = None, user_id: Any = None) -> None:
        """Markiert Datei als quarantined, ohne sie zu löschen."""
        self.status = LibraryFileStatus.QUARANTINED.value
        self.active = False
        self.visible = False
        self.quarantine_reason = normalize_optional_string(reason)
        self.updated_by_user_id = normalize_user_id(user_id, default=self.updated_by_user_id)
        self.touch()

    def restore(self, *, user_id: Any = None) -> None:
        """Stellt eine gelöschte/quarantined Datei wieder aktiv."""
        self.status = LibraryFileStatus.ACTIVE.value
        self.active = True
        self.visible = True
        self.deleted_at = None
        self.deleted_by_user_id = None
        self.quarantine_reason = None
        self.updated_by_user_id = normalize_user_id(user_id, default=self.updated_by_user_id)
        self.touch()

    def touch_accessed(self) -> None:
        """Aktualisiert last_accessed_at defensiv."""
        self.last_accessed_at = utc_now()
        self.touch()

    def to_dict(
        self,
        *,
        include_current_version: bool = False,
        include_versions: bool = False,
        include_links: bool = False,
    ) -> dict[str, Any]:
        result = {
            "id": self.id,
            "file_db_id": self.id,
            "file_uid": self.file_uid,
            "owner_user_id": self.owner_user_id,
            "source_scope": self.source_scope,
            "owner_scope": self.owner_scope,
            "document_type": self.document_type,
            "asset_kind": self.asset_kind,
            "original_filename": self.original_filename,
            "safe_filename": self.safe_filename,
            "extension": self.extension,
            "mime_type": self.mime_type,
            "size_bytes": self.size_bytes,
            "sha256": self.sha256,
            "storage_backend": self.storage_backend,
            "storage_path": self.storage_path,
            "external_uri": self.external_uri,
            "current_version_id": self.current_version_id,
            "version_count": self.version_count,
            "status": self.status,
            "active": self.active,
            "visible": self.visible,
            "locked": self.locked,
            "quarantine_reason": self.quarantine_reason,
            "uploaded_at": self.uploaded_at.isoformat() if self.uploaded_at else None,
            "replaced_at": self.replaced_at.isoformat() if self.replaced_at else None,
            "deleted_at": self.deleted_at.isoformat() if self.deleted_at else None,
            "last_accessed_at": self.last_accessed_at.isoformat() if self.last_accessed_at else None,
            "payload": normalize_json_mapping(self.payload),
            "meta": normalize_json_mapping(self.meta),
            "metadata": normalize_json_mapping(self.metadata_json),
            "created_by_user_id": self.created_by_user_id,
            "updated_by_user_id": self.updated_by_user_id,
            "deleted_by_user_id": self.deleted_by_user_id,
            "created_at": self.created_at.isoformat() if self.created_at else None,
            "updated_at": self.updated_at.isoformat() if self.updated_at else None,
        }

        if include_current_version:
            result["current_version"] = (
                self.current_version.to_dict()
                if self.current_version is not None
                else None
            )

        if include_versions:
            versions = list(getattr(self, "versions", []) or [])
            versions.sort(key=lambda item: normalize_int(getattr(item, "version_index", 0), default=0) or 0)
            result["versions"] = [version.to_dict() for version in versions]

        if include_links:
            links = list(getattr(self, "links", []) or [])
            links.sort(key=lambda item: normalize_int(getattr(item, "sort_order", 0), default=0) or 0)
            result["links"] = [link.to_dict(include_file=False) for link in links]

        return result


class LibraryFileVersion(TimestampMixin, JsonMixin, db.Model):
    """Konkrete Version einer logischen Datei."""

    __tablename__ = "library_file_versions"

    id = db.Column(db.BigInteger, primary_key=True, autoincrement=True)

    version_uid = db.Column(db.String(MAX_UID_LENGTH), nullable=False, unique=True, index=True, default=new_uid)

    file_id = db.Column(
        db.BigInteger,
        db.ForeignKey("library_files.id", ondelete="CASCADE"),
        nullable=True,
        index=True,
    )

    version_index = db.Column(db.Integer, nullable=False, default=1)

    uploaded_by_user_id = db.Column(db.BigInteger, nullable=True, index=True)

    original_filename = db.Column(db.String(MAX_FILENAME_LENGTH), nullable=True)
    safe_filename = db.Column(db.String(MAX_SAFE_FILENAME_LENGTH), nullable=True, index=True)
    extension = db.Column(db.String(MAX_EXTENSION_LENGTH), nullable=True, index=True)
    mime_type = db.Column(db.String(MAX_MIME_TYPE_LENGTH), nullable=True, index=True)

    size_bytes = db.Column(db.BigInteger, nullable=True)
    sha256 = db.Column(db.String(MAX_HASH_LENGTH), nullable=True, index=True)

    storage_backend = db.Column(
        db.String(MAX_STORAGE_BACKEND_LENGTH),
        nullable=False,
        default=LibraryFileStorageBackend.LOCAL.value,
        index=True,
    )
    storage_path = db.Column(db.Text, nullable=True)
    external_uri = db.Column(db.Text, nullable=True)

    binary_data = db.Column(db.LargeBinary, nullable=True)
    content_encoding = db.Column(db.String(80), nullable=True)

    status = db.Column(
        db.String(MAX_STATUS_LENGTH),
        nullable=False,
        default=LibraryFileStatus.ACTIVE.value,
        index=True,
    )
    active = db.Column(db.Boolean, nullable=False, default=True, index=True)

    payload = db.Column(db.JSON, nullable=False, default=dict)
    meta = db.Column(db.JSON, nullable=False, default=dict)
    metadata_json = db.Column(db.JSON, nullable=False, default=dict)

    file = db.relationship(
        "LibraryFile",
        back_populates="versions",
        foreign_keys=[file_id],
        lazy="joined",
    )
    links = db.relationship(
        "LibraryFileLink",
        back_populates="file_version",
        foreign_keys="LibraryFileLink.file_version_id",
        lazy="selectin",
    )

    __table_args__ = (
        db.UniqueConstraint("file_id", "version_index", name="uq_library_file_version_file_index"),
        db.Index("ix_library_file_versions_file_active", "file_id", "active", "status"),
        db.Index("ix_library_file_versions_hash", "sha256", "size_bytes"),
        db.Index("ix_library_file_versions_storage", "storage_backend", "mime_type"),
    )

    def __repr__(self) -> str:
        return f"<LibraryFileVersion id={self.id!r} file_id={self.file_id!r} version={self.version_index!r}>"

    @classmethod
    def create_from_payload(
        cls,
        payload: Mapping[str, Any] | None,
        *,
        file: LibraryFile | None = None,
        version_index: Any = None,
        uploaded_by_user_id: Any = None,
    ) -> "LibraryFileVersion":
        """Erstellt eine Version aus Upload-/Storage-Metadaten."""
        raw_binary = None

        if isinstance(payload, Mapping):
            raw_binary = payload.get("binary_data") or payload.get("bytes")

        data = normalize_json_mapping(payload)

        if raw_binary is not None and not isinstance(raw_binary, (bytes, bytearray, memoryview)):
            raw_binary = None

        computed_hash = sha256_bytes(raw_binary)

        if version_index is None:
            if file is not None:
                version_index = (normalize_int(getattr(file, "version_count", 0), default=0, minimum=0) or 0) + 1
            else:
                version_index = data.get("version_index") or data.get("versionIndex") or 1

        original_filename = normalize_optional_string(
            first_non_empty(
                data.get("original_filename"),
                data.get("filename"),
                data.get("name"),
                getattr(file, "original_filename", None),
            ),
            max_length=MAX_FILENAME_LENGTH,
        )

        extension = normalize_extension(data.get("extension"), filename=original_filename)
        mime_type = normalize_mime_type(data.get("mime_type") or data.get("mimeType"), filename=original_filename, extension=extension)
        size_bytes = normalize_size_bytes(data.get("size_bytes") or data.get("sizeBytes"), binary_data=raw_binary)

        storage_backend = normalize_storage_backend(
            data.get("storage_backend") or data.get("storageBackend"),
            storage_path=data.get("storage_path") or data.get("path"),
            external_uri=data.get("external_uri") or data.get("uri") or data.get("url"),
            binary_data=raw_binary,
        )

        return cls(
            version_uid=normalize_optional_string(data.get("version_uid") or data.get("uid"), max_length=MAX_UID_LENGTH) or new_uid(),
            file=file,
            file_id=getattr(file, "id", None),
            version_index=normalize_int(version_index, default=1, minimum=1) or 1,
            uploaded_by_user_id=normalize_user_id(uploaded_by_user_id, default=None),
            original_filename=original_filename,
            safe_filename=build_safe_filename(
                first_non_empty(data.get("safe_filename"), original_filename),
                file_uid=getattr(file, "file_uid", None),
            ),
            extension=extension,
            mime_type=mime_type,
            size_bytes=size_bytes,
            sha256=normalize_optional_string(
                first_non_empty(data.get("sha256"), data.get("checksum"), computed_hash),
                max_length=MAX_HASH_LENGTH,
            ),
            storage_backend=storage_backend,
            storage_path=normalize_optional_string(data.get("storage_path") or data.get("path")),
            external_uri=normalize_optional_string(data.get("external_uri") or data.get("uri") or data.get("url")),
            binary_data=bytes(raw_binary) if raw_binary is not None else None,
            content_encoding=normalize_optional_string(data.get("content_encoding") or data.get("encoding"), max_length=80),
            status=normalize_status(data.get("status"), default=LibraryFileStatus.ACTIVE.value),
            active=normalize_bool(data.get("active"), default=True),
            payload=data,
            meta=normalize_json_mapping(data.get("meta")),
            metadata_json=normalize_json_mapping(data.get("metadata")),
        )

    def mark_replaced(self) -> None:
        """Markiert Version als ersetzt."""
        self.status = LibraryFileStatus.REPLACED.value
        self.active = False
        self.touch()

    def mark_deleted(self) -> None:
        """Markiert Version als gelöscht."""
        self.status = LibraryFileStatus.DELETED.value
        self.active = False
        self.touch()

    def to_dict(self, *, include_binary_info: bool = True) -> dict[str, Any]:
        result = {
            "id": self.id,
            "version_db_id": self.id,
            "version_uid": self.version_uid,
            "file_id": self.file_id,
            "version_index": self.version_index,
            "uploaded_by_user_id": self.uploaded_by_user_id,
            "original_filename": self.original_filename,
            "safe_filename": self.safe_filename,
            "extension": self.extension,
            "mime_type": self.mime_type,
            "size_bytes": self.size_bytes,
            "sha256": self.sha256,
            "storage_backend": self.storage_backend,
            "storage_path": self.storage_path,
            "external_uri": self.external_uri,
            "content_encoding": self.content_encoding,
            "status": self.status,
            "active": self.active,
            "payload": normalize_json_mapping(self.payload),
            "meta": normalize_json_mapping(self.meta),
            "metadata": normalize_json_mapping(self.metadata_json),
            "created_at": self.created_at.isoformat() if self.created_at else None,
            "updated_at": self.updated_at.isoformat() if self.updated_at else None,
        }

        if include_binary_info:
            result["has_binary_data"] = self.binary_data is not None
            result["binary_size_bytes"] = len(self.binary_data) if self.binary_data is not None else 0

        return result


class LibraryFileLink(TimestampMixin, JsonMixin, db.Model):
    """
    Link zwischen einer Datei und einem fachlichen Kontext.

    Beispiele:

    - field_key=documents.datasheets auf creative_variant
    - field_key=render.reference auf creative_variant
    - role=render_model für GLB
    - role=technical_drawing für DWG/DXF/PDF
    """

    __tablename__ = "library_file_links"

    id = db.Column(db.BigInteger, primary_key=True, autoincrement=True)

    link_uid = db.Column(db.String(MAX_UID_LENGTH), nullable=False, unique=True, index=True, default=new_uid)

    file_id = db.Column(
        db.BigInteger,
        db.ForeignKey("library_files.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    file_version_id = db.Column(
        db.BigInteger,
        db.ForeignKey("library_file_versions.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )

    user_id = db.Column(db.BigInteger, nullable=True, index=True)
    owner_scope = db.Column(db.String(MAX_OWNER_SCOPE_LENGTH), nullable=False, default=f"user:{DEFAULT_USER_ID}", index=True)

    context_type = db.Column(
        db.String(MAX_CONTEXT_TYPE_LENGTH),
        nullable=False,
        default=LibraryFileLinkContextType.OTHER.value,
        index=True,
    )
    context_db_id = db.Column(db.BigInteger, nullable=True, index=True)
    context_id = db.Column(db.String(MAX_CONTEXT_ID_LENGTH), nullable=True, index=True)
    context_uid = db.Column(db.String(MAX_UID_LENGTH), nullable=True, index=True)

    vplib_uid = db.Column(db.String(MAX_VPLIB_UID_LENGTH), nullable=True, index=True)
    family_id = db.Column(db.String(MAX_FAMILY_ID_LENGTH), nullable=True, index=True)
    package_id = db.Column(db.String(MAX_PACKAGE_ID_LENGTH), nullable=True, index=True)
    variant_id = db.Column(db.String(MAX_VARIANT_ID_LENGTH), nullable=True, index=True)
    revision_hash = db.Column(db.String(MAX_HASH_LENGTH), nullable=True, index=True)

    field_key = db.Column(db.String(MAX_FIELD_KEY_LENGTH), nullable=True, index=True)
    document_type = db.Column(db.String(MAX_DOCUMENT_TYPE_LENGTH), nullable=True, index=True)
    role = db.Column(db.String(MAX_ROLE_LENGTH), nullable=False, default=LibraryFileRole.ATTACHMENT.value, index=True)

    label = db.Column(db.String(MAX_LABEL_LENGTH), nullable=True)
    description = db.Column(db.Text, nullable=True)

    is_primary = db.Column(db.Boolean, nullable=False, default=False, index=True)
    sort_order = db.Column(db.Integer, nullable=False, default=0)

    status = db.Column(
        db.String(MAX_STATUS_LENGTH),
        nullable=False,
        default=LibraryFileStatus.ACTIVE.value,
        index=True,
    )
    active = db.Column(db.Boolean, nullable=False, default=True, index=True)

    assigned_at = db.Column(db.DateTime(timezone=True), nullable=False, default=utc_now)
    deleted_at = db.Column(db.DateTime(timezone=True), nullable=True)

    payload = db.Column(db.JSON, nullable=False, default=dict)
    meta = db.Column(db.JSON, nullable=False, default=dict)
    metadata_json = db.Column(db.JSON, nullable=False, default=dict)

    created_by_user_id = db.Column(db.BigInteger, nullable=True, index=True)
    updated_by_user_id = db.Column(db.BigInteger, nullable=True, index=True)
    deleted_by_user_id = db.Column(db.BigInteger, nullable=True, index=True)

    file = db.relationship(
        "LibraryFile",
        back_populates="links",
        foreign_keys=[file_id],
        lazy="joined",
    )
    file_version = db.relationship(
        "LibraryFileVersion",
        back_populates="links",
        foreign_keys=[file_version_id],
        lazy="joined",
    )

    __table_args__ = (
        db.Index("ix_library_file_links_context", "context_type", "context_db_id", "context_id"),
        db.Index("ix_library_file_links_vplib_variant", "vplib_uid", "variant_id", "field_key"),
        db.Index("ix_library_file_links_user_context", "user_id", "context_type", "active"),
        db.Index("ix_library_file_links_file_role", "file_id", "role", "active"),
        db.Index("ix_library_file_links_primary", "context_type", "context_id", "field_key", "is_primary"),
    )

    def __repr__(self) -> str:
        return f"<LibraryFileLink id={self.id!r} file_id={self.file_id!r} context={self.context_type!r}>"

    @classmethod
    def create_from_payload(
        cls,
        payload: Mapping[str, Any] | None,
        *,
        file: LibraryFile | None = None,
        file_version: LibraryFileVersion | None = None,
        user_id: Any = DEFAULT_USER_ID,
        created_by_user_id: Any = None,
    ) -> "LibraryFileLink":
        """Erstellt einen Link zwischen Datei und Kontext."""
        data = normalize_json_mapping(payload)

        normalized_user_id = normalize_user_id(first_non_empty(data.get("user_id"), user_id), default=DEFAULT_USER_ID)

        role = enum_value(
            first_non_empty(data.get("role"), data.get("file_role")),
            default=LibraryFileRole.ATTACHMENT.value,
        )

        context_type = enum_value(
            first_non_empty(data.get("context_type"), data.get("contextType")),
            default=LibraryFileLinkContextType.OTHER.value,
        )

        document_type = normalize_optional_string(
            first_non_empty(data.get("document_type"), data.get("documentType"), getattr(file, "document_type", None)),
            max_length=MAX_DOCUMENT_TYPE_LENGTH,
        )

        return cls(
            link_uid=normalize_optional_string(data.get("link_uid") or data.get("uid"), max_length=MAX_UID_LENGTH) or new_uid(),
            file=file,
            file_id=getattr(file, "id", None) or normalize_required_int(data.get("file_id"), field_name="file_id"),
            file_version=file_version,
            file_version_id=getattr(file_version, "id", None) or normalize_int(data.get("file_version_id"), default=None, minimum=1),
            user_id=normalized_user_id,
            owner_scope=f"user:{normalized_user_id or DEFAULT_USER_ID}",
            context_type=context_type,
            context_db_id=normalize_int(data.get("context_db_id") or data.get("contextDbId"), default=None, minimum=1),
            context_id=normalize_optional_string(data.get("context_id") or data.get("contextId"), max_length=MAX_CONTEXT_ID_LENGTH),
            context_uid=normalize_optional_string(data.get("context_uid") or data.get("contextUid"), max_length=MAX_UID_LENGTH),
            vplib_uid=normalize_optional_string(data.get("vplib_uid") or data.get("vplibUid"), max_length=MAX_VPLIB_UID_LENGTH),
            family_id=normalize_optional_string(data.get("family_id") or data.get("familyId"), max_length=MAX_FAMILY_ID_LENGTH),
            package_id=normalize_optional_string(data.get("package_id") or data.get("packageId"), max_length=MAX_PACKAGE_ID_LENGTH),
            variant_id=normalize_optional_string(data.get("variant_id") or data.get("variantId"), max_length=MAX_VARIANT_ID_LENGTH),
            revision_hash=normalize_optional_string(data.get("revision_hash") or data.get("revisionHash"), max_length=MAX_HASH_LENGTH),
            field_key=normalize_optional_string(data.get("field_key") or data.get("fieldKey"), max_length=MAX_FIELD_KEY_LENGTH),
            document_type=document_type,
            role=role,
            label=normalize_optional_string(data.get("label"), max_length=MAX_LABEL_LENGTH),
            description=normalize_optional_string(data.get("description")),
            is_primary=normalize_bool(data.get("is_primary") or data.get("primary"), default=False),
            sort_order=normalize_int(data.get("sort_order") or data.get("sortOrder"), default=0, minimum=0) or 0,
            status=normalize_status(data.get("status"), default=LibraryFileStatus.ACTIVE.value),
            active=normalize_bool(data.get("active"), default=True),
            assigned_at=utc_now(),
            payload=data,
            meta=normalize_json_mapping(data.get("meta")),
            metadata_json=normalize_json_mapping(data.get("metadata")),
            created_by_user_id=normalize_user_id(created_by_user_id, default=None),
            updated_by_user_id=normalize_user_id(created_by_user_id, default=None),
        )

    def mark_deleted(self, *, user_id: Any = None) -> None:
        """Soft-delete für Link."""
        self.status = LibraryFileStatus.DELETED.value
        self.active = False
        self.deleted_at = utc_now()
        self.deleted_by_user_id = normalize_user_id(user_id, default=None)
        self.updated_by_user_id = normalize_user_id(user_id, default=self.updated_by_user_id)
        self.touch()

    def restore(self, *, user_id: Any = None) -> None:
        """Stellt Link wieder her."""
        self.status = LibraryFileStatus.ACTIVE.value
        self.active = True
        self.deleted_at = None
        self.deleted_by_user_id = None
        self.updated_by_user_id = normalize_user_id(user_id, default=self.updated_by_user_id)
        self.touch()

    def to_dict(self, *, include_file: bool = True, include_version: bool = False) -> dict[str, Any]:
        result = {
            "id": self.id,
            "link_db_id": self.id,
            "link_uid": self.link_uid,
            "file_id": self.file_id,
            "file_version_id": self.file_version_id,
            "user_id": self.user_id,
            "owner_scope": self.owner_scope,
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
            "label": self.label,
            "description": self.description,
            "is_primary": self.is_primary,
            "sort_order": self.sort_order,
            "status": self.status,
            "active": self.active,
            "assigned_at": self.assigned_at.isoformat() if self.assigned_at else None,
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

        if include_file:
            result["file"] = self.file.to_dict(include_current_version=False) if self.file is not None else None

        if include_version:
            result["file_version"] = self.file_version.to_dict() if self.file_version is not None else None

        return result


class LibraryFileAuditEvent(TimestampMixin, JsonMixin, db.Model):
    """Audit-Event für Dateioperationen."""

    __tablename__ = "library_file_audit_events"

    id = db.Column(db.BigInteger, primary_key=True, autoincrement=True)

    event_uid = db.Column(db.String(MAX_UID_LENGTH), nullable=False, unique=True, index=True, default=new_uid)
    event_type = db.Column(db.String(120), nullable=False, index=True)

    user_id = db.Column(db.BigInteger, nullable=True, index=True)
    owner_scope = db.Column(db.String(MAX_OWNER_SCOPE_LENGTH), nullable=True, index=True)

    file_id = db.Column(
        db.BigInteger,
        db.ForeignKey("library_files.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )
    file_version_id = db.Column(
        db.BigInteger,
        db.ForeignKey("library_file_versions.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )
    link_id = db.Column(
        db.BigInteger,
        db.ForeignKey("library_file_links.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )

    file_uid = db.Column(db.String(MAX_UID_LENGTH), nullable=True, index=True)
    version_uid = db.Column(db.String(MAX_UID_LENGTH), nullable=True, index=True)
    link_uid = db.Column(db.String(MAX_UID_LENGTH), nullable=True, index=True)

    context_type = db.Column(db.String(MAX_CONTEXT_TYPE_LENGTH), nullable=True, index=True)
    context_id = db.Column(db.String(MAX_CONTEXT_ID_LENGTH), nullable=True, index=True)

    vplib_uid = db.Column(db.String(MAX_VPLIB_UID_LENGTH), nullable=True, index=True)
    family_id = db.Column(db.String(MAX_FAMILY_ID_LENGTH), nullable=True, index=True)
    variant_id = db.Column(db.String(MAX_VARIANT_ID_LENGTH), nullable=True, index=True)

    before_json = db.Column(db.JSON, nullable=False, default=dict)
    after_json = db.Column(db.JSON, nullable=False, default=dict)
    diff_json = db.Column(db.JSON, nullable=False, default=dict)

    payload = db.Column(db.JSON, nullable=False, default=dict)
    meta = db.Column(db.JSON, nullable=False, default=dict)
    metadata_json = db.Column(db.JSON, nullable=False, default=dict)

    file = db.relationship("LibraryFile", foreign_keys=[file_id], lazy="joined")
    file_version = db.relationship("LibraryFileVersion", foreign_keys=[file_version_id], lazy="joined")
    link = db.relationship("LibraryFileLink", foreign_keys=[link_id], lazy="joined")

    __table_args__ = (
        db.Index("ix_library_file_audit_user_event", "user_id", "event_type", "created_at"),
        db.Index("ix_library_file_audit_file_event", "file_uid", "event_type", "created_at"),
        db.Index("ix_library_file_audit_context", "context_type", "context_id", "created_at"),
    )

    def __repr__(self) -> str:
        return f"<LibraryFileAuditEvent id={self.id!r} event_type={self.event_type!r} file_uid={self.file_uid!r}>"

    @classmethod
    def create_event(
        cls,
        *,
        event_type: Any,
        user_id: Any = None,
        file: LibraryFile | None = None,
        file_version: LibraryFileVersion | None = None,
        link: LibraryFileLink | None = None,
        before: Mapping[str, Any] | None = None,
        after: Mapping[str, Any] | None = None,
        diff: Mapping[str, Any] | None = None,
        payload: Mapping[str, Any] | None = None,
        metadata: Mapping[str, Any] | None = None,
    ) -> "LibraryFileAuditEvent":
        data = normalize_json_mapping(payload)
        normalized_user_id = normalize_user_id(first_non_empty(user_id, data.get("user_id")), default=None)

        target_file = file or getattr(link, "file", None)
        target_version = file_version or getattr(link, "file_version", None)

        return cls(
            event_uid=new_uid(),
            event_type=enum_value(event_type, default=LibraryFileAuditEventType.UPDATED.value),
            user_id=normalized_user_id,
            owner_scope=f"user:{normalized_user_id}" if normalized_user_id else None,
            file=file,
            file_id=getattr(target_file, "id", None),
            file_version=file_version,
            file_version_id=getattr(target_version, "id", None),
            link=link,
            link_id=getattr(link, "id", None),
            file_uid=getattr(target_file, "file_uid", None),
            version_uid=getattr(target_version, "version_uid", None),
            link_uid=getattr(link, "link_uid", None),
            context_type=getattr(link, "context_type", None),
            context_id=getattr(link, "context_id", None),
            vplib_uid=first_non_empty(getattr(link, "vplib_uid", None), data.get("vplib_uid")),
            family_id=first_non_empty(getattr(link, "family_id", None), data.get("family_id")),
            variant_id=first_non_empty(getattr(link, "variant_id", None), data.get("variant_id")),
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
            "file_id": self.file_id,
            "file_version_id": self.file_version_id,
            "link_id": self.link_id,
            "file_uid": self.file_uid,
            "version_uid": self.version_uid,
            "link_uid": self.link_uid,
            "context_type": self.context_type,
            "context_id": self.context_id,
            "vplib_uid": self.vplib_uid,
            "family_id": self.family_id,
            "variant_id": self.variant_id,
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
# Additional helpers that require model-independent validation
# ---------------------------------------------------------------------------

def normalize_required_int(value: Any, *, field_name: str, minimum: int | None = 1) -> int:
    """Normalisiert Pflicht-Integer."""
    result = normalize_int(value, default=None, minimum=minimum)

    if result is None:
        raise ValueError(f"{field_name} is required.")

    return result


def build_file_payload_summary(file: LibraryFile | None) -> dict[str, Any]:
    """Kompakte File-Zusammenfassung für andere Services."""
    if file is None:
        return {}

    return {
        "file_uid": file.file_uid,
        "document_type": file.document_type,
        "asset_kind": file.asset_kind,
        "filename": file.safe_filename or file.original_filename,
        "mime_type": file.mime_type,
        "extension": file.extension,
        "size_bytes": file.size_bytes,
        "sha256": file.sha256,
        "storage_backend": file.storage_backend,
        "storage_path": file.storage_path,
        "external_uri": file.external_uri,
        "status": file.status,
        "active": file.active,
    }


def build_link_context_payload(link: LibraryFileLink | None) -> dict[str, Any]:
    """Kompakte Link-Kontext-Zusammenfassung."""
    if link is None:
        return {}

    return {
        "context_type": link.context_type,
        "context_db_id": link.context_db_id,
        "context_id": link.context_id,
        "context_uid": link.context_uid,
        "vplib_uid": link.vplib_uid,
        "family_id": link.family_id,
        "package_id": link.package_id,
        "variant_id": link.variant_id,
        "revision_hash": link.revision_hash,
        "field_key": link.field_key,
        "document_type": link.document_type,
        "role": link.role,
        "is_primary": link.is_primary,
    }


# ---------------------------------------------------------------------------
# Public model helpers
# ---------------------------------------------------------------------------

def iter_library_file_models() -> tuple[type[Any], ...]:
    """Gibt alle echten Modelklassen dieser Datei zurück."""
    return (
        LibraryFile,
        LibraryFileVersion,
        LibraryFileLink,
        LibraryFileAuditEvent,
    )


def iter_models() -> tuple[type[Any], ...]:
    """Kompatibler Alias für models.__init__.py."""
    return iter_library_file_models()


def get_models() -> tuple[type[Any], ...]:
    """Kompatibler Alias für Modelle-Discovery."""
    return iter_library_file_models()


def get_library_file_model_names() -> tuple[str, ...]:
    """Gibt alle Modelklassennamen zurück."""
    return tuple(model.__name__ for model in iter_library_file_models())


def get_library_file_table_names() -> tuple[str, ...]:
    """Gibt alle Tabellennamen zurück."""
    return tuple(str(getattr(model, "__tablename__", "")) for model in iter_library_file_models())


def get_library_file_models_health() -> dict[str, Any]:
    """JSON-kompatibler Health-Snapshot dieser Model-Datei."""
    model_names = get_library_file_model_names()
    table_names = get_library_file_table_names()

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
            "schema_version": LIBRARY_FILES_MODELS_SCHEMA_VERSION,
            "healthy": healthy,
            "ok": healthy,
            "model_count": len(model_names),
            "table_count": len(table_names),
            "model_names": list(model_names),
            "table_names": list(table_names),
            "metadata_table_count": len(metadata_table_names),
            "metadata_table_names": list(metadata_table_names),
            "missing_tables": missing_tables,
            "supports_files": True,
            "supports_file_versions": True,
            "supports_file_links": True,
            "supports_file_audit_events": True,
            "supports_postgres_bytea": True,
            "supports_local_storage_reference": True,
            "supports_object_storage_reference": True,
            "supports_external_uri_reference": True,
            "model_3d_extensions": list(MODEL_3D_EXTENSIONS),
            "forbidden_upload_extensions": list(FORBIDDEN_UPLOAD_EXTENSIONS),
        }
    except Exception as exc:
        return {
            "schema_version": LIBRARY_FILES_MODELS_SCHEMA_VERSION,
            "healthy": False,
            "ok": False,
            "model_count": len(model_names),
            "table_count": len(table_names),
            "model_names": list(model_names),
            "table_names": list(table_names),
            "error": f"{type(exc).__name__}: {exc}",
        }


def assert_library_file_models_ready() -> None:
    """Wirft RuntimeError, wenn die File-Models nicht bereit sind."""
    health = get_library_file_models_health()

    if health.get("healthy"):
        return

    raise RuntimeError(f"Library file models are not ready: {health}")


def clear_library_file_model_caches() -> dict[str, Any]:
    """Leert interne Caches dieser Datei."""
    cleared: list[str] = []

    for cached_func in (
        _load_db,
        _cached_extension_from_filename,
        _cached_mime_type_from_extension,
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
    "LIBRARY_FILES_MODELS_SCHEMA_VERSION",
    "DEFAULT_USER_ID",
    "MODEL_3D_EXTENSIONS",
    "IMAGE_EXTENSIONS",
    "DRAWING_EXTENSIONS",
    "DOCUMENT_EXTENSIONS",
    "FORBIDDEN_UPLOAD_EXTENSIONS",
    "MANUAL_MIME_TYPES",

    # Enums
    "LibraryFileSourceScope",
    "LibraryFileStatus",
    "LibraryFileStorageBackend",
    "LibraryFileAssetKind",
    "LibraryFileRole",
    "LibraryFileLinkContextType",
    "LibraryFileAuditEventType",

    # Models
    "LibraryFile",
    "LibraryFileVersion",
    "LibraryFileLink",
    "LibraryFileAuditEvent",

    # Helpers
    "utc_now",
    "new_uid",
    "enum_value",
    "first_non_empty",
    "clean_string",
    "normalize_optional_string",
    "normalize_required_string",
    "normalize_bool",
    "normalize_int",
    "normalize_required_int",
    "normalize_user_id",
    "normalize_json_mapping",
    "normalize_json_list",
    "normalize_json_value",
    "merge_json",
    "stable_json_hash",
    "sha256_bytes",
    "normalize_source_scope",
    "owner_scope_for",
    "normalize_status",
    "normalize_storage_backend",
    "extension_from_filename",
    "normalize_extension",
    "extension_is_forbidden",
    "infer_mime_type_from_filename",
    "normalize_mime_type",
    "safe_filename_component",
    "build_safe_filename",
    "infer_asset_kind",
    "normalize_size_bytes",
    "build_file_payload_summary",
    "build_link_context_payload",

    # Model discovery / health
    "iter_library_file_models",
    "iter_models",
    "get_models",
    "get_library_file_model_names",
    "get_library_file_table_names",
    "get_library_file_models_health",
    "assert_library_file_models_ready",
    "clear_library_file_model_caches",
]