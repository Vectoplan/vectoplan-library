# services/vectoplan-library/models/creative_library.py
"""
Creative Library database models for vectoplan-library.

Diese Datei enthält die PostgreSQL-/SQLAlchemy-Modelle für die veröffentlichte
Creative Library.

Zielpfad:

    Source VPLIB Packages
        -> Scanner
        -> Validation
        -> Fingerprint
        -> DB-Sync
        -> PostgreSQL
        -> Published Creative Library API
        -> Creative Inventory / Editor / Admin / Generator

Wichtige Architekturregeln:

- `vplib_uid` ist die stabile technische ID eines VPLIB-Packages.
- `vplib_uid` entsteht beim Erstellen der .vplib / des Source-Packages.
- `vplib_uid` wird in `vplib.manifest.json` gespeichert.
- Die Datenbank erzeugt `vplib_uid` NICHT selbst.
- Die Datenbank übernimmt, validiert, indiziert und versioniert diese ID nur.
- Interne DB-IDs sind nur technische Datenbankidentität.
- Fachlich relevant für Package-Updates ist `vplib_uid`.
- Inhaltsrevisionen werden über `revision_hash` erkannt.
- Published Creative Library bleibt die Wahrheit für veröffentlichte Items.
- Generator-/Bearbeitungsstände liegen in creative_library_drafts.py.
- User-spezifische Sicht liegt in creative_library_user.py.
- Generische Upload-/File-Metadaten liegen in library_files.py.
- Diese Datei bleibt für bestehende Repository-/Route-Namen rückwärtskompatibel.

Primäre Tabellen:

- creative_library_items
- creative_library_revisions
- creative_library_variants
- creative_library_assets
- creative_library_documents
- creative_library_scan_runs
- creative_library_scan_issues
- creative_library_inventory_slots

Kompatibilitätsnamen:

- CreativeLibraryItem bleibt erhalten.
- CreativeLibraryFamily ist Alias auf CreativeLibraryItem.
- CreativeLibraryRevision bleibt erhalten.
- CreativeLibraryFamilyRevision ist Alias auf CreativeLibraryRevision.

Wichtig für Flask-Migrate/Alembic:

- Diese Datei importiert nur `db` und deklariert Models.
- Keine Migrationen.
- Kein db.create_all().
- Keine aktive DB-Verbindung.
- Keine Scanner-Ausführung.
- Keine Seed-Logik.
- `models.import_all_models()` soll diese Datei importieren, damit Alembic
  die Tabellen in db.metadata sieht.

Technische Namen, JSON-Keys und Variablen bleiben Englisch.
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

CREATIVE_LIBRARY_MODELS_SCHEMA_VERSION: Final[str] = "vectoplan_library.creative_library.models.v4.1"
CREATIVE_LIBRARY_UID_FIELD: Final[str] = "vplib_uid"
DEFAULT_INVENTORY_KEY: Final[str] = "default"
DEFAULT_USER_ID: Final[int] = 1

MAX_VPLIB_UID_LENGTH = 128
MAX_UID_LENGTH: Final[int] = 80
MAX_STATUS_LENGTH: Final[int] = 40
MAX_SOURCE_SCOPE_LENGTH: Final[int] = 40
MAX_OWNER_SCOPE_LENGTH: Final[int] = 120
MAX_LABEL_LENGTH: Final[int] = 255
MAX_PACKAGE_ID_LENGTH: Final[int] = 255
MAX_FAMILY_ID_LENGTH: Final[int] = 255
MAX_FAMILY_SLUG_LENGTH: Final[int] = 160
MAX_VARIANT_ID_LENGTH: Final[int] = 160
MAX_OBJECT_KIND_LENGTH: Final[int] = 80
MAX_PROFILE_ID_LENGTH: Final[int] = 160
MAX_TAXONOMY_DOMAIN_LENGTH: Final[int] = 80
MAX_TAXONOMY_CATEGORY_LENGTH: Final[int] = 120
MAX_TAXONOMY_PATH_LENGTH: Final[int] = 512
MAX_HASH_LENGTH: Final[int] = 128
MAX_PATH_LENGTH: Final[int] = 1024
MAX_MIME_TYPE_LENGTH: Final[int] = 160
MAX_ROLE_LENGTH: Final[int] = 120
MAX_SCOPE_LENGTH: Final[int] = 120
MAX_FIELD_LENGTH: Final[int] = 255


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
# Enums
# ---------------------------------------------------------------------------

class CreativeLibrarySourceScope(str, enum.Enum):
    SYSTEM = "system"
    USER = "user"
    IMPORTED = "imported"
    GENERATED = "generated"

    @property
    def key(self) -> str:
        return str(self.value)


class CreativeLibraryStatus(str, enum.Enum):
    DRAFT = "draft"
    PENDING = "pending"
    ACTIVE = "active"
    PUBLISHED = "published"
    INVALID = "invalid"
    UNPUBLISHED = "unpublished"
    INACTIVE = "inactive"
    ARCHIVED = "archived"
    DEPRECATED = "deprecated"
    DELETED = "deleted"
    ERROR = "error"

    @property
    def key(self) -> str:
        return str(self.value)


class CreativeLibraryScanStatus(str, enum.Enum):
    RUNNING = "running"
    COMPLETED = "completed"
    FINISHED = "finished"
    PARTIAL = "partial"
    FAILED = "failed"
    EMPTY = "empty"
    ERROR = "error"

    @property
    def key(self) -> str:
        return str(self.value)


class CreativeLibraryIssueSeverity(str, enum.Enum):
    DEBUG = "debug"
    INFO = "info"
    WARNING = "warning"
    ERROR = "error"
    FATAL = "fatal"

    @property
    def key(self) -> str:
        return str(self.value)


class CreativeLibraryAssetKind(str, enum.Enum):
    ICON = "icon"
    PREVIEW = "preview"
    THUMBNAIL = "thumbnail"
    MESH = "mesh"
    MODEL = "model"
    MODEL_3D = "model_3d"
    RENDER_VARIANT = "render_variant"
    TEXTURE = "texture"
    MATERIAL = "material"
    DOCUMENT = "document"
    TECHNICAL_DRAWING = "technical_drawing"
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
    """Stable lowercase UUID string."""
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

    try:
        text = str(value).strip().lower()
    except Exception:
        return default

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
        return {"value": str(value)}

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

    if isinstance(value, (str, bytes, bytearray, Mapping)):
        return [normalize_json_value(value)]

    try:
        return [normalize_json_value(item) for item in value]
    except Exception:
        return [str(value)]


def normalize_json_value(value: Any) -> Any:
    """Normalisiert JSON-kompatible Werte."""
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


@lru_cache(maxsize=4096)
def _cached_vplib_uid_fallback(value: str) -> str | None:
    """Cached Fallback-Normalisierung für VPLIB UIDs."""
    text = normalize_optional_string(value, max_length=MAX_VPLIB_UID_LENGTH)
    if not text:
        return None

    lowered = text.lower()

    try:
        parsed = uuid.UUID(lowered)
        uuid_text = str(parsed).lower()
        if uuid_text == "00000000-0000-0000-0000-000000000000":
            return None
        return uuid_text
    except Exception:
        return lowered


def normalize_vplib_uid(value: Any) -> str | None:
    """
    Normalisiert eine VPLIB UID.

    Primär wird der zentrale VPLIB-ID-Service genutzt, falls vorhanden.

    Fallback:
    - akzeptiert nicht-leere String-IDs
    - normalisiert auf lowercase
    - lehnt die leere UUID ab

    Hintergrund:
    Die DB darf keine neue UID erzeugen. Sie soll aber während Migrationen nicht
    unnötig hart an einer einzelnen UID-Implementierung hängen.
    """

    if value is None:
        return None

    try:
        from vplib.vplib_id_service import normalize_vplib_uid as normalize

        result = normalize(value)
        if result:
            return str(result).strip().lower()
    except Exception:
        pass

    try:
        from src.vplib.vplib_id_service import normalize_vplib_uid as normalize  # type: ignore

        result = normalize(value)
        if result:
            return str(result).strip().lower()
    except Exception:
        pass

    try:
        return _cached_vplib_uid_fallback(str(value))
    except Exception:
        return None


def require_vplib_uid(value: Any) -> str:
    """Validiert und normalisiert eine verpflichtende VPLIB UID."""
    uid = normalize_vplib_uid(value)
    if not uid:
        raise ValueError("vplib_uid is required.")
    return uid


def normalize_source_scope(value: Any, *, default: str = CreativeLibrarySourceScope.SYSTEM.value) -> str:
    """Normalisiert source_scope."""
    text = enum_value(value, default=default).strip().lower()

    aliases = {
        "core": CreativeLibrarySourceScope.SYSTEM.value,
        "default": CreativeLibrarySourceScope.SYSTEM.value,
        "global": CreativeLibrarySourceScope.SYSTEM.value,
        "system": CreativeLibrarySourceScope.SYSTEM.value,
        "user": CreativeLibrarySourceScope.USER.value,
        "custom": CreativeLibrarySourceScope.USER.value,
        "import": CreativeLibrarySourceScope.IMPORTED.value,
        "imported": CreativeLibrarySourceScope.IMPORTED.value,
        "generated": CreativeLibrarySourceScope.GENERATED.value,
        "generator": CreativeLibrarySourceScope.GENERATED.value,
    }

    return aliases.get(text, text if text else default)[:MAX_SOURCE_SCOPE_LENGTH]


def owner_scope_for(
    *,
    source_scope: Any = CreativeLibrarySourceScope.SYSTEM.value,
    owner_user_id: Any = None,
) -> str:
    """
    Baut einen stabilen owner_scope.

    PostgreSQL behandelt NULL in UniqueConstraints nicht als gleich.
    Deshalb wird zusätzlich ein nicht-nullbarer owner_scope gespeichert.
    """

    scope = normalize_source_scope(source_scope)
    user_id = normalize_user_id(owner_user_id, default=None)

    if scope == CreativeLibrarySourceScope.SYSTEM.value and user_id is None:
        return CreativeLibrarySourceScope.SYSTEM.value

    if scope == CreativeLibrarySourceScope.USER.value:
        return f"user:{user_id or DEFAULT_USER_ID}"

    if user_id is not None:
        return f"{scope}:{user_id}"

    return scope or CreativeLibrarySourceScope.SYSTEM.value


def extract_manifest_classification(manifest: Mapping[str, Any]) -> dict[str, Any]:
    """Extrahiert Classification robust aus Manifest."""
    raw = manifest.get("classification")
    if isinstance(raw, Mapping):
        return normalize_json_mapping(raw)
    return {}


def identity_dict(value: Any) -> dict[str, Any] | None:
    """Gibt `to_dict()` zurück, falls vorhanden."""
    if value is None:
        return None

    if hasattr(value, "to_dict") and callable(value.to_dict):
        try:
            result = value.to_dict()
            return normalize_json_mapping(result if isinstance(result, Mapping) else {"value": result})
        except Exception:
            return {"value": str(value)}

    if isinstance(value, Mapping):
        return normalize_json_mapping(value)

    return {"value": str(value)}


def taxonomy_path_for(
    *,
    domain: Any = None,
    category: Any = None,
    subcategory: Any = None,
) -> str | None:
    """Baut Taxonomiepfad aus Domain/Kategorie/Subkategorie."""
    parts = [
        normalize_optional_string(domain, max_length=MAX_TAXONOMY_DOMAIN_LENGTH),
        normalize_optional_string(category, max_length=MAX_TAXONOMY_CATEGORY_LENGTH),
        normalize_optional_string(subcategory, max_length=MAX_TAXONOMY_CATEGORY_LENGTH),
    ]

    cleaned = [part for part in parts if part]
    return "/".join(cleaned) if cleaned else None


def normalize_status(value: Any, *, default: str = CreativeLibraryStatus.PUBLISHED.value) -> str:
    """Normalisiert Status."""
    return enum_value(value, default=default)[:MAX_STATUS_LENGTH]


def normalize_relative_path(value: Any, *, field_name: str = "relative_path") -> str:
    """Normalisiert package-relative Pfade defensiv."""
    path = normalize_required_string(value, field_name=field_name, max_length=MAX_PATH_LENGTH)
    cleaned = path.replace("\\", "/").strip()

    if cleaned.startswith("/"):
        raise ValueError(f"{field_name} must be package-relative.")

    parts = [part for part in cleaned.split("/") if part not in {"", "."}]

    if any(part == ".." for part in parts):
        raise ValueError(f"{field_name} must not contain parent traversal.")

    normalized = "/".join(parts)

    if not normalized:
        raise ValueError(f"{field_name} is required.")

    return normalized[:MAX_PATH_LENGTH]


def extract_variant_id(payload: Mapping[str, Any]) -> str:
    """Ermittelt Variant-ID tolerant aus Payload."""
    definition_values = normalize_json_mapping(
        payload.get("definition_values") or payload.get("definitionValues") or payload.get("values")
    )

    return normalize_required_string(
        first_non_empty(
            payload.get("variant_id"),
            payload.get("variantId"),
            payload.get("id"),
            payload.get("slug"),
            definition_values.get("variant.variant_id"),
        ),
        field_name="variant_id",
        max_length=MAX_VARIANT_ID_LENGTH,
    )


# ---------------------------------------------------------------------------
# Mixins
# ---------------------------------------------------------------------------

class TimestampMixin:
    """Created/updated timestamps."""

    created_at = db.Column(db.DateTime(timezone=True), nullable=False, default=utc_now)
    updated_at = db.Column(db.DateTime(timezone=True), nullable=False, default=utc_now, onupdate=utc_now)

    def touch(self) -> None:
        self.updated_at = utc_now()


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

class CreativeLibraryItem(TimestampMixin, JsonMixin, db.Model):
    """
    Aktives Creative-Library-Element.

    Ein Item entspricht fachlich einer Family. Der Name `CreativeLibraryItem`
    bleibt für Rückwärtskompatibilität erhalten.

    Repository-kompatibler Alias:

        CreativeLibraryFamily = CreativeLibraryItem
    """

    __tablename__ = "creative_library_items"

    id = db.Column(db.BigInteger, primary_key=True, autoincrement=True)

    # Stable external package identity from vplib.manifest.json.
    vplib_uid = db.Column(db.String(MAX_VPLIB_UID_LENGTH), nullable=False, unique=True, index=True)

    # Ownership / origin.
    owner_user_id = db.Column(db.BigInteger, nullable=True, index=True)
    source_scope = db.Column(
        db.String(MAX_SOURCE_SCOPE_LENGTH),
        nullable=False,
        default=CreativeLibrarySourceScope.SYSTEM.value,
        index=True,
    )
    owner_scope = db.Column(
        db.String(MAX_OWNER_SCOPE_LENGTH),
        nullable=False,
        default=CreativeLibrarySourceScope.SYSTEM.value,
        index=True,
    )
    created_by_user_id = db.Column(db.BigInteger, nullable=True, index=True)
    updated_by_user_id = db.Column(db.BigInteger, nullable=True, index=True)

    # Semantic/package identity.
    package_id = db.Column(db.String(MAX_PACKAGE_ID_LENGTH), nullable=True, index=True)
    family_id = db.Column(db.String(MAX_FAMILY_ID_LENGTH), nullable=True, index=True)
    family_slug = db.Column(db.String(MAX_FAMILY_SLUG_LENGTH), nullable=True, index=True)
    slug = db.Column(db.String(MAX_FAMILY_SLUG_LENGTH), nullable=True, index=True)
    label = db.Column(db.String(MAX_LABEL_LENGTH), nullable=True)
    name = db.Column(db.String(MAX_LABEL_LENGTH), nullable=True)
    description = db.Column(db.Text, nullable=True)

    # Taxonomy / classification.
    domain = db.Column(db.String(MAX_TAXONOMY_DOMAIN_LENGTH), nullable=True, index=True)
    category = db.Column(db.String(MAX_TAXONOMY_CATEGORY_LENGTH), nullable=True, index=True)
    subcategory = db.Column(db.String(MAX_TAXONOMY_CATEGORY_LENGTH), nullable=True, index=True)
    classification_path = db.Column(db.String(MAX_TAXONOMY_PATH_LENGTH), nullable=True, index=True)
    taxonomy_path = db.Column(db.String(MAX_TAXONOMY_PATH_LENGTH), nullable=True, index=True)
    object_kind = db.Column(db.String(MAX_OBJECT_KIND_LENGTH), nullable=True, index=True)

    # Profile/definition metadata.
    family_profile_id = db.Column(db.String(MAX_PROFILE_ID_LENGTH), nullable=True, index=True)
    variant_profile_id = db.Column(db.String(MAX_PROFILE_ID_LENGTH), nullable=True, index=True)
    definition_version = db.Column(db.String(80), nullable=True, index=True)

    # Source metadata.
    source_root = db.Column(db.Text, nullable=True)
    source_path = db.Column(db.Text, nullable=True, index=True)
    package_root = db.Column(db.Text, nullable=True)
    source_hash = db.Column(db.String(MAX_HASH_LENGTH), nullable=True, index=True)

    # Current publication pointer.
    current_revision_id = db.Column(
        db.BigInteger,
        db.ForeignKey(
            "creative_library_revisions.id",
            name="fk_creative_library_items_current_revision_id",
            use_alter=True,
            ondelete="SET NULL",
        ),
        nullable=True,
        index=True,
    )
    current_revision_hash = db.Column(db.String(MAX_HASH_LENGTH), nullable=True, index=True)
    latest_revision_hash = db.Column(db.String(MAX_HASH_LENGTH), nullable=True, index=True)
    published_revision_hash = db.Column(db.String(MAX_HASH_LENGTH), nullable=True, index=True)
    revision_hash = db.Column(db.String(MAX_HASH_LENGTH), nullable=True, index=True)

    default_variant_id = db.Column(db.String(MAX_VARIANT_ID_LENGTH), nullable=True, index=True)
    variant_count = db.Column(db.Integer, nullable=False, default=0)
    asset_count = db.Column(db.Integer, nullable=False, default=0)
    document_count = db.Column(db.Integer, nullable=False, default=0)
    revision_count = db.Column(db.Integer, nullable=False, default=0)

    # Lifecycle.
    status = db.Column(db.String(MAX_STATUS_LENGTH), nullable=False, default=CreativeLibraryStatus.PUBLISHED.value, index=True)
    publication_status = db.Column(db.String(MAX_STATUS_LENGTH), nullable=False, default=CreativeLibraryStatus.PUBLISHED.value, index=True)
    enabled = db.Column(db.Boolean, nullable=False, default=True, index=True)
    visible = db.Column(db.Boolean, nullable=False, default=True, index=True)
    is_deleted = db.Column(db.Boolean, nullable=False, default=False, index=True)

    editable = db.Column(db.Boolean, nullable=False, default=True)
    generator_editable = db.Column(db.Boolean, nullable=False, default=True)
    locked = db.Column(db.Boolean, nullable=False, default=False)
    system_required = db.Column(db.Boolean, nullable=False, default=False)

    first_seen_at = db.Column(db.DateTime(timezone=True), nullable=False, default=utc_now)
    last_seen_at = db.Column(db.DateTime(timezone=True), nullable=True)
    scanned_at = db.Column(db.DateTime(timezone=True), nullable=True)
    published_at = db.Column(db.DateTime(timezone=True), nullable=True)
    last_edited_at = db.Column(db.DateTime(timezone=True), nullable=True)
    last_generated_at = db.Column(db.DateTime(timezone=True), nullable=True)
    deleted_at = db.Column(db.DateTime(timezone=True), nullable=True)

    # JSON payloads.
    summary_payload = db.Column(db.JSON, nullable=False, default=dict)
    payload = db.Column(db.JSON, nullable=False, default=dict)
    generator_payload = db.Column(db.JSON, nullable=False, default=dict)
    definition_payload = db.Column(db.JSON, nullable=False, default=dict)
    file_refs_json = db.Column(db.JSON, nullable=False, default=list)
    meta = db.Column(db.JSON, nullable=False, default=dict)
    metadata_json = db.Column(db.JSON, nullable=False, default=dict)

    revisions = db.relationship(
        "CreativeLibraryRevision",
        back_populates="family",
        cascade="all, delete-orphan",
        foreign_keys="CreativeLibraryRevision.family_db_id",
        lazy="selectin",
    )
    current_revision = db.relationship(
        "CreativeLibraryRevision",
        foreign_keys=[current_revision_id],
        post_update=True,
        lazy="joined",
    )
    variants = db.relationship(
        "CreativeLibraryVariant",
        back_populates="family",
        cascade="all, delete-orphan",
        foreign_keys="CreativeLibraryVariant.family_db_id",
        lazy="selectin",
    )
    assets = db.relationship(
        "CreativeLibraryAsset",
        back_populates="family",
        cascade="all, delete-orphan",
        foreign_keys="CreativeLibraryAsset.family_db_id",
        lazy="selectin",
    )
    documents = db.relationship(
        "CreativeLibraryDocument",
        back_populates="family",
        cascade="all, delete-orphan",
        foreign_keys="CreativeLibraryDocument.family_db_id",
        lazy="selectin",
    )
    inventory_slots = db.relationship(
        "CreativeLibraryInventorySlot",
        back_populates="family",
        foreign_keys="CreativeLibraryInventorySlot.family_db_id",
        lazy="selectin",
    )

    __table_args__ = (
        db.Index("ix_creative_library_items_taxonomy", "domain", "category", "subcategory"),
        db.Index("ix_creative_library_items_active_lookup", "publication_status", "enabled", "visible", "is_deleted"),
        db.Index("ix_creative_library_items_family_lookup", "family_id", "family_slug"),
        db.Index("ix_creative_library_items_source_status", "source_path", "status"),
        db.Index("ix_creative_library_items_kind_taxonomy", "object_kind", "domain", "category"),
        db.Index("ix_creative_library_items_owner_status", "owner_scope", "publication_status", "enabled", "visible"),
        db.Index("ix_creative_library_items_profiles", "family_profile_id", "variant_profile_id"),
    )

    def __repr__(self) -> str:
        return f"<CreativeLibraryItem id={self.id!r} vplib_uid={self.vplib_uid!r} status={self.status!r}>"

    @classmethod
    def create_from_manifest(
        cls,
        *,
        manifest: Mapping[str, Any],
        source_root: str | None = None,
        source_path: str | None = None,
        metadata: Mapping[str, Any] | None = None,
        owner_user_id: Any = None,
        source_scope: Any = CreativeLibrarySourceScope.SYSTEM.value,
        created_by_user_id: Any = None,
    ) -> "CreativeLibraryItem":
        """Erzeugt ein Item aus `vplib.manifest.json`."""
        uid = require_vplib_uid(manifest.get(CREATIVE_LIBRARY_UID_FIELD))
        classification = extract_manifest_classification(manifest)

        family_slug = normalize_optional_string(
            manifest.get("family_slug") or manifest.get("slug"),
            max_length=MAX_FAMILY_SLUG_LENGTH,
        )
        label = normalize_optional_string(
            manifest.get("family_name") or manifest.get("label") or manifest.get("name"),
            max_length=MAX_LABEL_LENGTH,
        )

        domain = normalize_optional_string(
            manifest.get("domain") or classification.get("domain"),
            max_length=MAX_TAXONOMY_DOMAIN_LENGTH,
        )
        category = normalize_optional_string(
            manifest.get("category") or classification.get("category"),
            max_length=MAX_TAXONOMY_CATEGORY_LENGTH,
        )
        subcategory = normalize_optional_string(
            manifest.get("subcategory") or classification.get("subcategory"),
            max_length=MAX_TAXONOMY_CATEGORY_LENGTH,
        )
        taxonomy_path = taxonomy_path_for(domain=domain, category=category, subcategory=subcategory)

        normalized_source_scope = normalize_source_scope(source_scope)
        normalized_owner_user_id = normalize_user_id(owner_user_id, default=None)

        meta_payload = normalize_json_mapping(metadata)
        now = utc_now()

        return cls(
            vplib_uid=uid,
            owner_user_id=normalized_owner_user_id,
            source_scope=normalized_source_scope,
            owner_scope=owner_scope_for(source_scope=normalized_source_scope, owner_user_id=normalized_owner_user_id),
            created_by_user_id=normalize_user_id(created_by_user_id, default=None),
            updated_by_user_id=normalize_user_id(created_by_user_id, default=None),
            package_id=normalize_optional_string(manifest.get("package_id"), max_length=MAX_PACKAGE_ID_LENGTH),
            family_id=normalize_optional_string(manifest.get("family_id"), max_length=MAX_FAMILY_ID_LENGTH),
            family_slug=family_slug,
            slug=family_slug,
            label=label,
            name=label,
            description=normalize_optional_string(manifest.get("description")),
            domain=domain,
            category=category,
            subcategory=subcategory,
            classification_path=normalize_optional_string(
                manifest.get("classification_path") or classification.get("classification_path"),
                max_length=MAX_TAXONOMY_PATH_LENGTH,
            ),
            taxonomy_path=taxonomy_path,
            object_kind=normalize_optional_string(manifest.get("object_kind"), max_length=MAX_OBJECT_KIND_LENGTH),
            family_profile_id=normalize_optional_string(manifest.get("family_profile_id"), max_length=MAX_PROFILE_ID_LENGTH),
            variant_profile_id=normalize_optional_string(manifest.get("variant_profile_id"), max_length=MAX_PROFILE_ID_LENGTH),
            definition_version=normalize_optional_string(manifest.get("definitions_version") or manifest.get("definition_version"), max_length=80),
            source_root=source_root,
            source_path=source_path or normalize_optional_string(manifest.get("source_path")),
            package_root=normalize_optional_string(manifest.get("package_root")),
            source_hash=normalize_optional_string(manifest.get("source_hash"), max_length=MAX_HASH_LENGTH),
            status=CreativeLibraryStatus.PUBLISHED.value,
            publication_status=CreativeLibraryStatus.PUBLISHED.value,
            enabled=True,
            visible=True,
            is_deleted=False,
            editable=normalize_bool(meta_payload.get("editable"), default=True),
            generator_editable=normalize_bool(meta_payload.get("generator_editable"), default=True),
            locked=normalize_bool(meta_payload.get("locked"), default=False),
            system_required=normalize_bool(meta_payload.get("system_required"), default=normalized_source_scope == CreativeLibrarySourceScope.SYSTEM.value),
            summary_payload={},
            payload=normalize_json_mapping(manifest),
            generator_payload=normalize_json_mapping(manifest.get("generator")),
            definition_payload=normalize_json_mapping(manifest.get("definitions")),
            file_refs_json=normalize_json_list(manifest.get("file_refs") or manifest.get("files")),
            meta=meta_payload,
            metadata_json=meta_payload,
            first_seen_at=now,
            last_seen_at=now,
            scanned_at=now,
            published_at=now,
        )

    def update_from_manifest(
        self,
        *,
        manifest: Mapping[str, Any],
        source_root: str | None = None,
        source_path: str | None = None,
        metadata: Mapping[str, Any] | None = None,
        updated_by_user_id: Any = None,
    ) -> None:
        """Aktualisiert mutable Item-Felder aus dem aktuellen Manifest."""
        uid = require_vplib_uid(manifest.get(CREATIVE_LIBRARY_UID_FIELD))
        if self.vplib_uid != uid:
            raise ValueError(f"Cannot change vplib_uid from {self.vplib_uid!r} to {uid!r}.")

        classification = extract_manifest_classification(manifest)

        family_slug = normalize_optional_string(
            manifest.get("family_slug") or manifest.get("slug"),
            max_length=MAX_FAMILY_SLUG_LENGTH,
        )
        label = normalize_optional_string(
            manifest.get("family_name") or manifest.get("label") or manifest.get("name"),
            max_length=MAX_LABEL_LENGTH,
        )

        domain = normalize_optional_string(manifest.get("domain") or classification.get("domain"), max_length=MAX_TAXONOMY_DOMAIN_LENGTH)
        category = normalize_optional_string(manifest.get("category") or classification.get("category"), max_length=MAX_TAXONOMY_CATEGORY_LENGTH)
        subcategory = normalize_optional_string(manifest.get("subcategory") or classification.get("subcategory"), max_length=MAX_TAXONOMY_CATEGORY_LENGTH)
        taxonomy_path = taxonomy_path_for(domain=domain, category=category, subcategory=subcategory)

        now = utc_now()
        meta_payload = normalize_json_mapping(metadata)

        self.package_id = normalize_optional_string(manifest.get("package_id"), max_length=MAX_PACKAGE_ID_LENGTH)
        self.family_id = normalize_optional_string(manifest.get("family_id"), max_length=MAX_FAMILY_ID_LENGTH)
        self.family_slug = family_slug
        self.slug = family_slug
        self.label = label
        self.name = label
        self.description = normalize_optional_string(manifest.get("description"))
        self.domain = domain
        self.category = category
        self.subcategory = subcategory
        self.classification_path = normalize_optional_string(
            manifest.get("classification_path") or classification.get("classification_path"),
            max_length=MAX_TAXONOMY_PATH_LENGTH,
        )
        self.taxonomy_path = taxonomy_path
        self.object_kind = normalize_optional_string(manifest.get("object_kind"), max_length=MAX_OBJECT_KIND_LENGTH)
        self.family_profile_id = normalize_optional_string(manifest.get("family_profile_id"), max_length=MAX_PROFILE_ID_LENGTH)
        self.variant_profile_id = normalize_optional_string(manifest.get("variant_profile_id"), max_length=MAX_PROFILE_ID_LENGTH)
        self.definition_version = normalize_optional_string(manifest.get("definitions_version") or manifest.get("definition_version"), max_length=80)
        self.source_root = source_root if source_root is not None else self.source_root
        self.source_path = source_path or normalize_optional_string(manifest.get("source_path")) or self.source_path
        self.package_root = normalize_optional_string(manifest.get("package_root")) or self.package_root
        self.source_hash = normalize_optional_string(manifest.get("source_hash"), max_length=MAX_HASH_LENGTH) or self.source_hash
        self.payload = normalize_json_mapping(manifest)
        self.generator_payload = normalize_json_mapping(manifest.get("generator"))
        self.definition_payload = normalize_json_mapping(manifest.get("definitions"))
        self.file_refs_json = normalize_json_list(manifest.get("file_refs") or manifest.get("files"))
        self.meta = merge_json(self.meta, meta_payload)
        self.metadata_json = merge_json(self.metadata_json, meta_payload)
        self.status = CreativeLibraryStatus.PUBLISHED.value
        self.publication_status = CreativeLibraryStatus.PUBLISHED.value
        self.enabled = True
        self.visible = True
        self.is_deleted = False
        self.deleted_at = None
        self.last_seen_at = now
        self.scanned_at = now

        updater_id = normalize_user_id(updated_by_user_id, default=None)
        if updater_id is not None:
            self.updated_by_user_id = updater_id
            self.last_edited_at = now

        if self.published_at is None:
            self.published_at = now

        self.touch()

    def mark_seen(self) -> None:
        now = utc_now()
        self.last_seen_at = now
        self.scanned_at = now
        self.is_deleted = False
        self.deleted_at = None
        if self.status == CreativeLibraryStatus.DELETED.value:
            self.status = CreativeLibraryStatus.PUBLISHED.value
        if self.publication_status == CreativeLibraryStatus.DELETED.value:
            self.publication_status = CreativeLibraryStatus.PUBLISHED.value
        self.touch()

    def mark_invalid(self, *, metadata: Mapping[str, Any] | None = None) -> None:
        self.status = CreativeLibraryStatus.INVALID.value
        self.publication_status = CreativeLibraryStatus.INVALID.value
        self.meta = merge_json(self.meta, metadata)
        self.metadata_json = merge_json(self.metadata_json, metadata)
        self.last_seen_at = utc_now()
        self.touch()

    def mark_deleted(self) -> None:
        if self.locked or self.system_required:
            raise ValueError("Cannot delete a locked or system-required Creative Library item directly.")

        self.is_deleted = True
        self.status = CreativeLibraryStatus.DELETED.value
        self.publication_status = CreativeLibraryStatus.DELETED.value
        self.enabled = False
        self.visible = False
        self.deleted_at = utc_now()
        self.touch()

    def set_current_revision(self, revision: "CreativeLibraryRevision") -> None:
        self.current_revision_id = revision.id
        self.current_revision_hash = revision.revision_hash
        self.latest_revision_hash = revision.revision_hash
        self.published_revision_hash = revision.revision_hash
        self.revision_hash = revision.revision_hash
        self.status = CreativeLibraryStatus.PUBLISHED.value
        self.publication_status = CreativeLibraryStatus.PUBLISHED.value
        self.enabled = True
        self.visible = True
        self.is_deleted = False
        self.deleted_at = None
        self.last_seen_at = utc_now()
        self.published_at = self.published_at or utc_now()
        self.revision_count = max(normalize_int(self.revision_count, default=0, minimum=0) or 0, 1)
        self.touch()

    def mark_generator_updated(self, *, user_id: Any = None, payload: Mapping[str, Any] | None = None) -> None:
        self.last_generated_at = utc_now()
        self.generator_payload = merge_json(self.generator_payload, payload)
        updater_id = normalize_user_id(user_id, default=None)
        if updater_id is not None:
            self.updated_by_user_id = updater_id
        self.touch()

    def to_dict(self, *, include_current_revision: bool = False) -> dict[str, Any]:
        result = {
            "id": self.id,
            "family_db_id": self.id,
            "vplib_uid": self.vplib_uid,
            "owner_user_id": self.owner_user_id,
            "source_scope": self.source_scope,
            "owner_scope": self.owner_scope,
            "created_by_user_id": self.created_by_user_id,
            "updated_by_user_id": self.updated_by_user_id,
            "package_id": self.package_id,
            "family_id": self.family_id,
            "family_slug": self.family_slug,
            "slug": self.slug,
            "label": self.label,
            "name": self.name,
            "description": self.description,
            "domain": self.domain,
            "category": self.category,
            "subcategory": self.subcategory,
            "classification_path": self.classification_path,
            "taxonomy_path": self.taxonomy_path,
            "object_kind": self.object_kind,
            "family_profile_id": self.family_profile_id,
            "variant_profile_id": self.variant_profile_id,
            "definition_version": self.definition_version,
            "source_root": self.source_root,
            "source_path": self.source_path,
            "package_root": self.package_root,
            "source_hash": self.source_hash,
            "current_revision_id": self.current_revision_id,
            "current_revision_hash": self.current_revision_hash,
            "latest_revision_hash": self.latest_revision_hash,
            "published_revision_hash": self.published_revision_hash,
            "revision_hash": self.revision_hash,
            "default_variant_id": self.default_variant_id,
            "variant_count": self.variant_count,
            "asset_count": self.asset_count,
            "document_count": self.document_count,
            "revision_count": self.revision_count,
            "status": self.status,
            "publication_status": self.publication_status,
            "enabled": self.enabled,
            "visible": self.visible,
            "is_deleted": self.is_deleted,
            "editable": self.editable,
            "generator_editable": self.generator_editable,
            "locked": self.locked,
            "system_required": self.system_required,
            "first_seen_at": self.first_seen_at.isoformat() if self.first_seen_at else None,
            "last_seen_at": self.last_seen_at.isoformat() if self.last_seen_at else None,
            "scanned_at": self.scanned_at.isoformat() if self.scanned_at else None,
            "published_at": self.published_at.isoformat() if self.published_at else None,
            "last_edited_at": self.last_edited_at.isoformat() if self.last_edited_at else None,
            "last_generated_at": self.last_generated_at.isoformat() if self.last_generated_at else None,
            "deleted_at": self.deleted_at.isoformat() if self.deleted_at else None,
            "created_at": self.created_at.isoformat() if self.created_at else None,
            "updated_at": self.updated_at.isoformat() if self.updated_at else None,
            "summary_payload": normalize_json_mapping(self.summary_payload),
            "payload": normalize_json_mapping(self.payload),
            "generator_payload": normalize_json_mapping(self.generator_payload),
            "definition_payload": normalize_json_mapping(self.definition_payload),
            "file_refs": normalize_json_list(self.file_refs_json),
            "meta": normalize_json_mapping(self.meta),
            "metadata": normalize_json_mapping(self.metadata_json),
        }

        if include_current_revision:
            result["current_revision"] = (
                self.current_revision.to_dict(include_documents=False)
                if self.current_revision is not None
                else None
            )

        return result


class CreativeLibraryScanRun(TimestampMixin, JsonMixin, db.Model):
    """Ein vollständiger Scanner-/DB-Sync-/Publication-Lauf."""

    __tablename__ = "creative_library_scan_runs"

    id = db.Column(db.BigInteger, primary_key=True, autoincrement=True)

    scan_uid = db.Column(db.String(MAX_UID_LENGTH), nullable=False, unique=True, index=True, default=new_uid)

    owner_user_id = db.Column(db.BigInteger, nullable=True, index=True)
    source_scope = db.Column(
        db.String(MAX_SOURCE_SCOPE_LENGTH),
        nullable=False,
        default=CreativeLibrarySourceScope.SYSTEM.value,
        index=True,
    )
    owner_scope = db.Column(
        db.String(MAX_OWNER_SCOPE_LENGTH),
        nullable=False,
        default=CreativeLibrarySourceScope.SYSTEM.value,
        index=True,
    )

    source_root = db.Column(db.Text, nullable=True)
    mode = db.Column(db.String(80), nullable=True, index=True)
    triggered_by = db.Column(db.String(MAX_LABEL_LENGTH), nullable=True, index=True)

    started_at = db.Column(db.DateTime(timezone=True), nullable=False, default=utc_now)
    finished_at = db.Column(db.DateTime(timezone=True), nullable=True)
    duration_ms = db.Column(db.BigInteger, nullable=True)

    status = db.Column(db.String(MAX_STATUS_LENGTH), nullable=False, default=CreativeLibraryScanStatus.RUNNING.value, index=True)

    total_count = db.Column(db.Integer, nullable=False, default=0)
    scanned_count = db.Column(db.Integer, nullable=False, default=0)
    valid_count = db.Column(db.Integer, nullable=False, default=0)
    invalid_count = db.Column(db.Integer, nullable=False, default=0)
    created_count = db.Column(db.Integer, nullable=False, default=0)
    inserted_count = db.Column(db.Integer, nullable=False, default=0)
    updated_count = db.Column(db.Integer, nullable=False, default=0)
    unchanged_count = db.Column(db.Integer, nullable=False, default=0)
    published_count = db.Column(db.Integer, nullable=False, default=0)
    skipped_count = db.Column(db.Integer, nullable=False, default=0)
    deleted_count = db.Column(db.Integer, nullable=False, default=0)
    duplicate_count = db.Column(db.Integer, nullable=False, default=0)
    warning_count = db.Column(db.Integer, nullable=False, default=0)
    error_count = db.Column(db.Integer, nullable=False, default=0)

    summary_json = db.Column(db.JSON, nullable=False, default=dict)
    details = db.Column(db.JSON, nullable=False, default=dict)
    payload = db.Column(db.JSON, nullable=False, default=dict)
    meta = db.Column(db.JSON, nullable=False, default=dict)
    metadata_json = db.Column(db.JSON, nullable=False, default=dict)

    revisions = db.relationship("CreativeLibraryRevision", back_populates="scan_run", lazy="selectin")
    issues = db.relationship(
        "CreativeLibraryScanIssue",
        back_populates="scan_run",
        cascade="all, delete-orphan",
        lazy="selectin",
    )

    __table_args__ = (
        db.Index("ix_creative_library_scan_runs_status_started", "status", "started_at"),
        db.Index("ix_creative_library_scan_runs_mode_status", "mode", "status"),
        db.Index("ix_creative_library_scan_runs_owner", "owner_scope", "status"),
    )

    def __repr__(self) -> str:
        return f"<CreativeLibraryScanRun id={self.id!r} scan_uid={self.scan_uid!r} status={self.status!r}>"

    @classmethod
    def start(
        cls,
        *,
        source_root: str | None = None,
        mode: str | None = None,
        triggered_by: str | None = None,
        metadata: Mapping[str, Any] | None = None,
        owner_user_id: Any = None,
        source_scope: Any = CreativeLibrarySourceScope.SYSTEM.value,
    ) -> "CreativeLibraryScanRun":
        normalized_source_scope = normalize_source_scope(source_scope)
        normalized_owner_user_id = normalize_user_id(owner_user_id, default=None)

        return cls(
            scan_uid=new_uid(),
            owner_user_id=normalized_owner_user_id,
            source_scope=normalized_source_scope,
            owner_scope=owner_scope_for(source_scope=normalized_source_scope, owner_user_id=normalized_owner_user_id),
            source_root=source_root,
            mode=mode or "filesystem_sync",
            triggered_by=triggered_by,
            started_at=utc_now(),
            status=CreativeLibraryScanStatus.RUNNING.value,
            meta=normalize_json_mapping(metadata),
            metadata_json=normalize_json_mapping(metadata),
        )

    def finish(
        self,
        *,
        status: str = CreativeLibraryScanStatus.COMPLETED.value,
        summary: Mapping[str, Any] | None = None,
    ) -> None:
        self.finished_at = utc_now()
        self.status = enum_value(status, default=CreativeLibraryScanStatus.COMPLETED.value)
        self.summary_json = normalize_json_mapping(summary)

        if self.started_at and self.finished_at:
            delta = self.finished_at - self.started_at
            self.duration_ms = int(delta.total_seconds() * 1000)

        self.touch()

    def apply_counts(self, *, counts: Mapping[str, Any] | None = None) -> None:
        payload = normalize_json_mapping(counts)

        self.total_count = normalize_int(first_non_empty(payload.get("total_count"), payload.get("total")), default=self.total_count, minimum=0) or 0
        self.scanned_count = normalize_int(first_non_empty(payload.get("scanned_count"), payload.get("scanned")), default=self.scanned_count, minimum=0) or 0
        self.valid_count = normalize_int(first_non_empty(payload.get("valid_count"), payload.get("valid")), default=self.valid_count, minimum=0) or 0
        self.invalid_count = normalize_int(first_non_empty(payload.get("invalid_count"), payload.get("invalid")), default=self.invalid_count, minimum=0) or 0
        self.created_count = normalize_int(first_non_empty(payload.get("created_count"), payload.get("created")), default=self.created_count, minimum=0) or 0
        self.inserted_count = normalize_int(first_non_empty(payload.get("inserted_count"), payload.get("inserted")), default=self.inserted_count, minimum=0) or 0
        self.updated_count = normalize_int(first_non_empty(payload.get("updated_count"), payload.get("updated")), default=self.updated_count, minimum=0) or 0
        self.unchanged_count = normalize_int(first_non_empty(payload.get("unchanged_count"), payload.get("unchanged")), default=self.unchanged_count, minimum=0) or 0
        self.published_count = normalize_int(first_non_empty(payload.get("published_count"), payload.get("published")), default=self.published_count, minimum=0) or 0
        self.skipped_count = normalize_int(first_non_empty(payload.get("skipped_count"), payload.get("skipped")), default=self.skipped_count, minimum=0) or 0
        self.deleted_count = normalize_int(first_non_empty(payload.get("deleted_count"), payload.get("deleted")), default=self.deleted_count, minimum=0) or 0
        self.duplicate_count = normalize_int(first_non_empty(payload.get("duplicate_count"), payload.get("duplicates")), default=self.duplicate_count, minimum=0) or 0
        self.warning_count = normalize_int(first_non_empty(payload.get("warning_count"), payload.get("warnings")), default=self.warning_count, minimum=0) or 0
        self.error_count = normalize_int(first_non_empty(payload.get("error_count"), payload.get("errors")), default=self.error_count, minimum=0) or 0
        self.touch()

    def to_dict(self, *, include_issues: bool = False) -> dict[str, Any]:
        result = {
            "id": self.id,
            "scan_run_id": self.id,
            "scan_uid": self.scan_uid,
            "owner_user_id": self.owner_user_id,
            "source_scope": self.source_scope,
            "owner_scope": self.owner_scope,
            "source_root": self.source_root,
            "mode": self.mode,
            "triggered_by": self.triggered_by,
            "started_at": self.started_at.isoformat() if self.started_at else None,
            "finished_at": self.finished_at.isoformat() if self.finished_at else None,
            "duration_ms": self.duration_ms,
            "status": self.status,
            "total_count": self.total_count,
            "scanned_count": self.scanned_count,
            "valid_count": self.valid_count,
            "invalid_count": self.invalid_count,
            "created_count": self.created_count,
            "inserted_count": self.inserted_count,
            "updated_count": self.updated_count,
            "unchanged_count": self.unchanged_count,
            "published_count": self.published_count,
            "skipped_count": self.skipped_count,
            "deleted_count": self.deleted_count,
            "duplicate_count": self.duplicate_count,
            "warning_count": self.warning_count,
            "error_count": self.error_count,
            "summary": normalize_json_mapping(self.summary_json),
            "details": normalize_json_mapping(self.details),
            "payload": normalize_json_mapping(self.payload),
            "meta": normalize_json_mapping(self.meta),
            "metadata": normalize_json_mapping(self.metadata_json),
            "created_at": self.created_at.isoformat() if self.created_at else None,
            "updated_at": self.updated_at.isoformat() if self.updated_at else None,
        }

        if include_issues:
            result["issues"] = [issue.to_dict() for issue in self.issues]

        return result


class CreativeLibraryRevision(TimestampMixin, JsonMixin, db.Model):
    """Versionierter veröffentlichter Stand einer CreativeLibraryItem/Family."""

    __tablename__ = "creative_library_revisions"

    id = db.Column(db.BigInteger, primary_key=True, autoincrement=True)

    family_db_id = db.Column(
        db.BigInteger,
        db.ForeignKey("creative_library_items.id", ondelete="CASCADE"),
        nullable=True,
        index=True,
    )
    item_id = db.Column(
        db.BigInteger,
        db.ForeignKey("creative_library_items.id", ondelete="CASCADE"),
        nullable=True,
        index=True,
    )
    scan_run_id = db.Column(
        db.BigInteger,
        db.ForeignKey("creative_library_scan_runs.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )
    scan_run_db_id = db.Column(db.BigInteger, nullable=True, index=True)

    # Draft source pointer. String-only draft_uid remains useful even if the
    # draft row was discarded or archived.
    source_draft_id = db.Column(
        db.BigInteger,
        db.ForeignKey(
            "creative_library_drafts.id",
            name="fk_creative_library_revisions_source_draft_id",
            use_alter=True,
            ondelete="SET NULL",
        ),
        nullable=True,
        index=True,
    )
    source_draft_uid = db.Column(db.String(MAX_UID_LENGTH), nullable=True, index=True)

    owner_user_id = db.Column(db.BigInteger, nullable=True, index=True)
    source_scope = db.Column(
        db.String(MAX_SOURCE_SCOPE_LENGTH),
        nullable=False,
        default=CreativeLibrarySourceScope.SYSTEM.value,
        index=True,
    )
    owner_scope = db.Column(
        db.String(MAX_OWNER_SCOPE_LENGTH),
        nullable=False,
        default=CreativeLibrarySourceScope.SYSTEM.value,
        index=True,
    )

    vplib_uid = db.Column(db.String(MAX_VPLIB_UID_LENGTH), nullable=True, index=True)
    family_id = db.Column(db.String(MAX_FAMILY_ID_LENGTH), nullable=True, index=True)
    package_id = db.Column(db.String(MAX_PACKAGE_ID_LENGTH), nullable=True, index=True)

    revision_id = db.Column(db.String(MAX_VARIANT_ID_LENGTH), nullable=True, index=True)
    revision_hash = db.Column(db.String(MAX_HASH_LENGTH), nullable=False, index=True)
    previous_revision_hash = db.Column(db.String(MAX_HASH_LENGTH), nullable=True)

    package_version = db.Column(db.String(80), nullable=True)
    schema_version = db.Column(db.String(80), nullable=True)
    definitions_version = db.Column(db.String(80), nullable=True, index=True)

    source_root = db.Column(db.Text, nullable=True)
    source_path = db.Column(db.Text, nullable=True, index=True)
    source_mtime_ns = db.Column(db.BigInteger, nullable=True)
    source_size_bytes = db.Column(db.BigInteger, nullable=True)

    validation_status = db.Column(db.String(MAX_STATUS_LENGTH), nullable=True, index=True)
    status = db.Column(db.String(MAX_STATUS_LENGTH), nullable=False, default=CreativeLibraryStatus.PUBLISHED.value, index=True)
    publication_status = db.Column(db.String(MAX_STATUS_LENGTH), nullable=False, default=CreativeLibraryStatus.PUBLISHED.value, index=True)
    published_at = db.Column(db.DateTime(timezone=True), nullable=True)

    manifest_json = db.Column(db.JSON, nullable=False, default=dict)
    modules_json = db.Column(db.JSON, nullable=False, default=dict)
    identity_json = db.Column(db.JSON, nullable=False, default=dict)
    classification_json = db.Column(db.JSON, nullable=False, default=dict)
    resolved_package_json = db.Column(db.JSON, nullable=False, default=dict)
    document_paths_json = db.Column(db.JSON, nullable=False, default=list)

    summary_payload = db.Column(db.JSON, nullable=False, default=dict)
    detail_payload = db.Column(db.JSON, nullable=False, default=dict)
    raw_documents = db.Column(db.JSON, nullable=False, default=dict)
    documents = db.Column(db.JSON, nullable=False, default=dict)
    validation_payload = db.Column(db.JSON, nullable=False, default=dict)
    generator_payload = db.Column(db.JSON, nullable=False, default=dict)
    file_refs_json = db.Column(db.JSON, nullable=False, default=list)
    payload = db.Column(db.JSON, nullable=False, default=dict)
    meta = db.Column(db.JSON, nullable=False, default=dict)
    metadata_json = db.Column(db.JSON, nullable=False, default=dict)

    created_by_user_id = db.Column(db.BigInteger, nullable=True, index=True)
    published_by_user_id = db.Column(db.BigInteger, nullable=True, index=True)

    family = db.relationship(
        "CreativeLibraryItem",
        back_populates="revisions",
        foreign_keys=[family_db_id],
        lazy="joined",
    )
    item = db.relationship(
        "CreativeLibraryItem",
        foreign_keys=[item_id],
        lazy="joined",
    )
    scan_run = db.relationship(
        "CreativeLibraryScanRun",
        back_populates="revisions",
        lazy="joined",
    )
    variants = db.relationship(
        "CreativeLibraryVariant",
        back_populates="revision",
        cascade="all, delete-orphan",
        foreign_keys="CreativeLibraryVariant.revision_id",
        lazy="selectin",
    )
    assets = db.relationship(
        "CreativeLibraryAsset",
        back_populates="revision",
        cascade="all, delete-orphan",
        foreign_keys="CreativeLibraryAsset.revision_id",
        lazy="selectin",
    )
    document_rows = db.relationship(
        "CreativeLibraryDocument",
        back_populates="revision",
        cascade="all, delete-orphan",
        foreign_keys="CreativeLibraryDocument.revision_id",
        lazy="selectin",
    )

    __table_args__ = (
        db.UniqueConstraint("vplib_uid", "revision_hash", name="uq_creative_library_revision_uid_hash"),
        db.Index("ix_creative_library_revisions_family_status", "family_db_id", "publication_status"),
        db.Index("ix_creative_library_revisions_scan_status", "scan_run_id", "status"),
        db.Index("ix_creative_library_revisions_uid_created", "vplib_uid", "created_at"),
        db.Index("ix_creative_library_revisions_owner_status", "owner_scope", "publication_status"),
        db.Index("ix_creative_library_revisions_draft", "source_draft_uid", "source_draft_id"),
    )

    def __repr__(self) -> str:
        return f"<CreativeLibraryRevision id={self.id!r} vplib_uid={self.vplib_uid!r} hash={self.revision_hash!r}>"

    @classmethod
    def create_from_documents(
        cls,
        *,
        item: CreativeLibraryItem,
        revision_hash: str,
        manifest: Mapping[str, Any],
        modules: Mapping[str, Any] | None = None,
        identity: Mapping[str, Any] | None = None,
        classification: Mapping[str, Any] | None = None,
        resolved_package: Mapping[str, Any] | None = None,
        document_paths: Iterable[Any] | None = None,
        scan_run: CreativeLibraryScanRun | None = None,
        source_root: str | None = None,
        source_path: str | None = None,
        source_mtime_ns: int | None = None,
        source_size_bytes: int | None = None,
        metadata: Mapping[str, Any] | None = None,
        source_draft_id: Any = None,
        source_draft_uid: Any = None,
        created_by_user_id: Any = None,
        published_by_user_id: Any = None,
    ) -> "CreativeLibraryRevision":
        uid = require_vplib_uid(manifest.get(CREATIVE_LIBRARY_UID_FIELD))
        if item.vplib_uid != uid:
            raise ValueError(f"Manifest vplib_uid {uid!r} does not match item {item.vplib_uid!r}.")

        now = utc_now()
        metadata_payload = normalize_json_mapping(metadata)

        return cls(
            family=item,
            item=item,
            scan_run=scan_run,
            family_db_id=item.id,
            item_id=item.id,
            scan_run_id=scan_run.id if scan_run is not None else None,
            scan_run_db_id=scan_run.id if scan_run is not None else None,
            source_draft_id=normalize_int(source_draft_id, default=None, minimum=1),
            source_draft_uid=normalize_optional_string(source_draft_uid, max_length=MAX_UID_LENGTH),
            owner_user_id=item.owner_user_id,
            source_scope=item.source_scope,
            owner_scope=item.owner_scope,
            vplib_uid=uid,
            family_id=item.family_id,
            package_id=item.package_id,
            revision_hash=normalize_required_string(revision_hash, field_name="revision_hash", max_length=MAX_HASH_LENGTH),
            previous_revision_hash=item.current_revision_hash,
            schema_version=normalize_optional_string(manifest.get("schema_version"), max_length=80),
            definitions_version=normalize_optional_string(manifest.get("definitions_version") or manifest.get("definition_version"), max_length=80),
            source_root=source_root,
            source_path=source_path,
            source_mtime_ns=source_mtime_ns,
            source_size_bytes=source_size_bytes,
            manifest_json=normalize_json_mapping(manifest),
            modules_json=normalize_json_mapping(modules),
            identity_json=normalize_json_mapping(identity),
            classification_json=normalize_json_mapping(classification),
            resolved_package_json=normalize_json_mapping(resolved_package),
            document_paths_json=normalize_json_list(document_paths),
            raw_documents={},
            documents={},
            status=CreativeLibraryStatus.PUBLISHED.value,
            publication_status=CreativeLibraryStatus.PUBLISHED.value,
            published_at=now,
            generator_payload=normalize_json_mapping(manifest.get("generator")),
            file_refs_json=normalize_json_list(manifest.get("file_refs") or manifest.get("files")),
            meta=metadata_payload,
            metadata_json=metadata_payload,
            created_by_user_id=normalize_user_id(created_by_user_id, default=None),
            published_by_user_id=normalize_user_id(published_by_user_id, default=None),
        )

    def to_dict(self, *, include_documents: bool = True) -> dict[str, Any]:
        result = {
            "id": self.id,
            "revision_db_id": self.id,
            "family_db_id": self.family_db_id,
            "item_id": self.item_id,
            "scan_run_id": self.scan_run_id,
            "scan_run_db_id": self.scan_run_db_id,
            "source_draft_id": self.source_draft_id,
            "source_draft_uid": self.source_draft_uid,
            "owner_user_id": self.owner_user_id,
            "source_scope": self.source_scope,
            "owner_scope": self.owner_scope,
            "vplib_uid": self.vplib_uid,
            "family_id": self.family_id,
            "package_id": self.package_id,
            "revision_id": self.revision_id,
            "revision_hash": self.revision_hash,
            "previous_revision_hash": self.previous_revision_hash,
            "package_version": self.package_version,
            "schema_version": self.schema_version,
            "definitions_version": self.definitions_version,
            "source_root": self.source_root,
            "source_path": self.source_path,
            "source_mtime_ns": self.source_mtime_ns,
            "source_size_bytes": self.source_size_bytes,
            "validation_status": self.validation_status,
            "status": self.status,
            "publication_status": self.publication_status,
            "published_at": self.published_at.isoformat() if self.published_at else None,
            "created_by_user_id": self.created_by_user_id,
            "published_by_user_id": self.published_by_user_id,
            "created_at": self.created_at.isoformat() if self.created_at else None,
            "updated_at": self.updated_at.isoformat() if self.updated_at else None,
            "summary_payload": normalize_json_mapping(self.summary_payload),
            "detail_payload": normalize_json_mapping(self.detail_payload),
            "validation_payload": normalize_json_mapping(self.validation_payload),
            "generator_payload": normalize_json_mapping(self.generator_payload),
            "file_refs": normalize_json_list(self.file_refs_json),
            "payload": normalize_json_mapping(self.payload),
            "meta": normalize_json_mapping(self.meta),
            "metadata": normalize_json_mapping(self.metadata_json),
        }

        if include_documents:
            result.update(
                {
                    "manifest": normalize_json_mapping(self.manifest_json),
                    "modules": normalize_json_mapping(self.modules_json),
                    "identity": normalize_json_mapping(self.identity_json),
                    "classification": normalize_json_mapping(self.classification_json),
                    "resolved_package": normalize_json_mapping(self.resolved_package_json),
                    "document_paths": normalize_json_list(self.document_paths_json),
                    "raw_documents": normalize_json_mapping(self.raw_documents),
                    "documents": normalize_json_mapping(self.documents),
                }
            )

        return result


class CreativeLibraryVariant(TimestampMixin, JsonMixin, db.Model):
    """Eine konkrete Variant einer Revision."""

    __tablename__ = "creative_library_variants"

    id = db.Column(db.BigInteger, primary_key=True, autoincrement=True)

    family_db_id = db.Column(
        db.BigInteger,
        db.ForeignKey("creative_library_items.id", ondelete="CASCADE"),
        nullable=True,
        index=True,
    )
    item_id = db.Column(
        db.BigInteger,
        db.ForeignKey("creative_library_items.id", ondelete="CASCADE"),
        nullable=True,
        index=True,
    )
    revision_id = db.Column(
        db.BigInteger,
        db.ForeignKey("creative_library_revisions.id", ondelete="CASCADE"),
        nullable=True,
        index=True,
    )
    revision_db_id = db.Column(db.BigInteger, nullable=True, index=True)

    source_draft_variant_id = db.Column(
        db.BigInteger,
        db.ForeignKey(
            "creative_library_draft_variants.id",
            name="fk_creative_library_variants_source_draft_variant_id",
            use_alter=True,
            ondelete="SET NULL",
        ),
        nullable=True,
        index=True,
    )
    source_draft_variant_uid = db.Column(db.String(MAX_UID_LENGTH), nullable=True, index=True)

    vplib_uid = db.Column(db.String(MAX_VPLIB_UID_LENGTH), nullable=True, index=True)
    family_id = db.Column(db.String(MAX_FAMILY_ID_LENGTH), nullable=True, index=True)
    package_id = db.Column(db.String(MAX_PACKAGE_ID_LENGTH), nullable=True, index=True)
    revision_hash = db.Column(db.String(MAX_HASH_LENGTH), nullable=True, index=True)

    variant_id = db.Column(db.String(MAX_VARIANT_ID_LENGTH), nullable=False, index=True)
    id_in_family = db.Column(db.String(MAX_VARIANT_ID_LENGTH), nullable=True, index=True)
    slug = db.Column(db.String(MAX_VARIANT_ID_LENGTH), nullable=True, index=True)
    label = db.Column(db.String(MAX_LABEL_LENGTH), nullable=True)
    name = db.Column(db.String(MAX_LABEL_LENGTH), nullable=True)
    description = db.Column(db.Text, nullable=True)
    is_default = db.Column(db.Boolean, nullable=False, default=False, index=True)
    enabled = db.Column(db.Boolean, nullable=False, default=True, index=True)
    visible = db.Column(db.Boolean, nullable=False, default=True, index=True)

    family_profile_id = db.Column(db.String(MAX_PROFILE_ID_LENGTH), nullable=True, index=True)
    variant_profile_id = db.Column(db.String(MAX_PROFILE_ID_LENGTH), nullable=True, index=True)

    definition_values_json = db.Column(db.JSON, nullable=False, default=dict)
    additional_field_keys_json = db.Column(db.JSON, nullable=False, default=list)
    summary_json = db.Column(db.JSON, nullable=False, default=dict)
    resolved_payload = db.Column(db.JSON, nullable=False, default=dict)
    validation_payload = db.Column(db.JSON, nullable=False, default=dict)
    generator_payload = db.Column(db.JSON, nullable=False, default=dict)
    file_refs_json = db.Column(db.JSON, nullable=False, default=list)
    payload = db.Column(db.JSON, nullable=False, default=dict)
    meta = db.Column(db.JSON, nullable=False, default=dict)
    metadata_json = db.Column(db.JSON, nullable=False, default=dict)

    status = db.Column(db.String(MAX_STATUS_LENGTH), nullable=False, default=CreativeLibraryStatus.PUBLISHED.value, index=True)
    publication_status = db.Column(db.String(MAX_STATUS_LENGTH), nullable=True, index=True)
    sort_order = db.Column(db.Integer, nullable=False, default=0)

    created_by_user_id = db.Column(db.BigInteger, nullable=True, index=True)
    updated_by_user_id = db.Column(db.BigInteger, nullable=True, index=True)

    family = db.relationship("CreativeLibraryItem", back_populates="variants", foreign_keys=[family_db_id], lazy="joined")
    item = db.relationship("CreativeLibraryItem", foreign_keys=[item_id], lazy="joined")
    revision = db.relationship("CreativeLibraryRevision", back_populates="variants", foreign_keys=[revision_id], lazy="joined")

    assets = db.relationship(
        "CreativeLibraryAsset",
        back_populates="variant",
        foreign_keys="CreativeLibraryAsset.variant_db_id",
        lazy="selectin",
    )
    documents = db.relationship(
        "CreativeLibraryDocument",
        back_populates="variant",
        foreign_keys="CreativeLibraryDocument.variant_db_id",
        lazy="selectin",
    )

    __table_args__ = (
        db.UniqueConstraint("revision_id", "variant_id", name="uq_creative_library_variant_revision_variant"),
        db.Index("ix_creative_library_variants_family_default", "family_db_id", "is_default"),
        db.Index("ix_creative_library_variants_uid_variant", "vplib_uid", "variant_id"),
        db.Index("ix_creative_library_variants_profiles", "family_profile_id", "variant_profile_id"),
        db.Index("ix_creative_library_variants_draft", "source_draft_variant_uid", "source_draft_variant_id"),
    )

    def __repr__(self) -> str:
        return f"<CreativeLibraryVariant id={self.id!r} revision_id={self.revision_id!r} variant_id={self.variant_id!r}>"

    @classmethod
    def create_from_payload(
        cls,
        *,
        item: CreativeLibraryItem,
        revision: CreativeLibraryRevision,
        payload: Mapping[str, Any],
        sort_order: int = 0,
        source_draft_variant_id: Any = None,
        source_draft_variant_uid: Any = None,
    ) -> "CreativeLibraryVariant":
        variant_id = extract_variant_id(payload)

        definition_values = normalize_json_mapping(payload.get("definition_values") or payload.get("definitionValues") or payload.get("values"))

        return cls(
            family=item,
            item=item,
            revision=revision,
            family_db_id=item.id,
            item_id=item.id,
            revision_id=revision.id,
            revision_db_id=revision.id,
            source_draft_variant_id=normalize_int(source_draft_variant_id, default=None, minimum=1),
            source_draft_variant_uid=normalize_optional_string(source_draft_variant_uid, max_length=MAX_UID_LENGTH),
            vplib_uid=item.vplib_uid,
            family_id=item.family_id,
            package_id=item.package_id,
            revision_hash=revision.revision_hash,
            variant_id=variant_id,
            id_in_family=variant_id,
            slug=normalize_optional_string(payload.get("slug") or variant_id, max_length=MAX_VARIANT_ID_LENGTH),
            label=normalize_optional_string(payload.get("label") or payload.get("name") or definition_values.get("variant.label"), max_length=MAX_LABEL_LENGTH),
            name=normalize_optional_string(payload.get("name") or payload.get("label") or definition_values.get("variant.label"), max_length=MAX_LABEL_LENGTH),
            description=normalize_optional_string(payload.get("description") or definition_values.get("variant.description")),
            is_default=normalize_bool(payload.get("is_default") or payload.get("isDefault") or payload.get("default"), default=False),
            enabled=normalize_bool(payload.get("enabled"), default=True),
            visible=normalize_bool(payload.get("visible"), default=True),
            family_profile_id=normalize_optional_string(payload.get("family_profile_id") or payload.get("familyProfileId") or item.family_profile_id, max_length=MAX_PROFILE_ID_LENGTH),
            variant_profile_id=normalize_optional_string(payload.get("variant_profile_id") or payload.get("variantProfileId") or item.variant_profile_id, max_length=MAX_PROFILE_ID_LENGTH),
            definition_values_json=definition_values,
            additional_field_keys_json=normalize_json_list(payload.get("additional_field_keys") or payload.get("additionalFieldKeys")),
            summary_json=normalize_json_mapping(payload.get("summary")),
            resolved_payload=normalize_json_mapping(payload.get("resolved_payload") or payload.get("resolved")),
            validation_payload=normalize_json_mapping(payload.get("validation") or payload.get("validation_payload")),
            generator_payload=normalize_json_mapping(payload.get("generator") or payload.get("generator_payload")),
            file_refs_json=normalize_json_list(payload.get("file_refs") or payload.get("files")),
            payload=normalize_json_mapping(payload),
            meta=normalize_json_mapping(payload.get("metadata")),
            metadata_json=normalize_json_mapping(payload.get("metadata")),
            status=enum_value(payload.get("status"), default=CreativeLibraryStatus.PUBLISHED.value),
            publication_status=enum_value(payload.get("publication_status"), default=CreativeLibraryStatus.PUBLISHED.value),
            sort_order=normalize_int(sort_order, default=0, minimum=0) or 0,
            created_by_user_id=revision.created_by_user_id,
            updated_by_user_id=revision.created_by_user_id,
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "variant_db_id": self.id,
            "family_db_id": self.family_db_id,
            "item_id": self.item_id,
            "revision_id": self.revision_id,
            "revision_db_id": self.revision_db_id,
            "source_draft_variant_id": self.source_draft_variant_id,
            "source_draft_variant_uid": self.source_draft_variant_uid,
            "vplib_uid": self.vplib_uid,
            "family_id": self.family_id,
            "package_id": self.package_id,
            "revision_hash": self.revision_hash,
            "variant_id": self.variant_id,
            "id_in_family": self.id_in_family,
            "slug": self.slug,
            "label": self.label,
            "name": self.name,
            "description": self.description,
            "is_default": self.is_default,
            "enabled": self.enabled,
            "visible": self.visible,
            "family_profile_id": self.family_profile_id,
            "variant_profile_id": self.variant_profile_id,
            "definition_values": normalize_json_mapping(self.definition_values_json),
            "additional_field_keys": normalize_json_list(self.additional_field_keys_json),
            "summary": normalize_json_mapping(self.summary_json),
            "resolved_payload": normalize_json_mapping(self.resolved_payload),
            "validation_payload": normalize_json_mapping(self.validation_payload),
            "generator_payload": normalize_json_mapping(self.generator_payload),
            "file_refs": normalize_json_list(self.file_refs_json),
            "payload": normalize_json_mapping(self.payload),
            "status": self.status,
            "publication_status": self.publication_status,
            "sort_order": self.sort_order,
            "created_by_user_id": self.created_by_user_id,
            "updated_by_user_id": self.updated_by_user_id,
            "created_at": self.created_at.isoformat() if self.created_at else None,
            "updated_at": self.updated_at.isoformat() if self.updated_at else None,
            "meta": normalize_json_mapping(self.meta),
            "metadata": normalize_json_mapping(self.metadata_json),
        }


class CreativeLibraryAsset(TimestampMixin, JsonMixin, db.Model):
    """Asset-/Preview-/Mesh-/File-Verweis einer Revision."""

    __tablename__ = "creative_library_assets"

    id = db.Column(db.BigInteger, primary_key=True, autoincrement=True)

    family_db_id = db.Column(
        db.BigInteger,
        db.ForeignKey("creative_library_items.id", ondelete="CASCADE"),
        nullable=True,
        index=True,
    )
    item_id = db.Column(
        db.BigInteger,
        db.ForeignKey("creative_library_items.id", ondelete="CASCADE"),
        nullable=True,
        index=True,
    )
    revision_id = db.Column(
        db.BigInteger,
        db.ForeignKey("creative_library_revisions.id", ondelete="CASCADE"),
        nullable=True,
        index=True,
    )
    revision_db_id = db.Column(db.BigInteger, nullable=True, index=True)

    variant_db_id = db.Column(
        db.BigInteger,
        db.ForeignKey("creative_library_variants.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )
    variant_id = db.Column(db.String(MAX_VARIANT_ID_LENGTH), nullable=True, index=True)

    library_file_id = db.Column(
        db.BigInteger,
        db.ForeignKey("library_files.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )
    library_file_version_id = db.Column(
        db.BigInteger,
        db.ForeignKey("library_file_versions.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )

    vplib_uid = db.Column(db.String(MAX_VPLIB_UID_LENGTH), nullable=True, index=True)
    family_id = db.Column(db.String(MAX_FAMILY_ID_LENGTH), nullable=True, index=True)
    package_id = db.Column(db.String(MAX_PACKAGE_ID_LENGTH), nullable=True, index=True)
    revision_hash = db.Column(db.String(MAX_HASH_LENGTH), nullable=True, index=True)

    role = db.Column(db.String(MAX_ROLE_LENGTH), nullable=True, index=True)
    asset_kind = db.Column(db.String(MAX_ROLE_LENGTH), nullable=True, index=True)
    asset_type = db.Column(db.String(MAX_ROLE_LENGTH), nullable=True, index=True)
    document_type = db.Column(db.String(MAX_ROLE_LENGTH), nullable=True, index=True)
    field_key = db.Column(db.String(MAX_FIELD_LENGTH), nullable=True, index=True)

    asset_path = db.Column(db.Text, nullable=True)
    path = db.Column(db.Text, nullable=True)
    relative_path = db.Column(db.Text, nullable=True)
    uri = db.Column(db.Text, nullable=True)

    label = db.Column(db.String(MAX_LABEL_LENGTH), nullable=True)
    asset_hash = db.Column(db.String(MAX_HASH_LENGTH), nullable=True, index=True)
    checksum = db.Column(db.String(MAX_HASH_LENGTH), nullable=True, index=True)
    mime_type = db.Column(db.String(MAX_MIME_TYPE_LENGTH), nullable=True)
    size_bytes = db.Column(db.BigInteger, nullable=True)
    exists = db.Column(db.Boolean, nullable=False, default=True, index=True)
    is_primary = db.Column(db.Boolean, nullable=False, default=False, index=True)
    sort_order = db.Column(db.Integer, nullable=False, default=0)

    bounds_json = db.Column(db.JSON, nullable=False, default=dict)
    transform_json = db.Column(db.JSON, nullable=False, default=dict)

    payload = db.Column(db.JSON, nullable=False, default=dict)
    meta = db.Column(db.JSON, nullable=False, default=dict)
    metadata_json = db.Column(db.JSON, nullable=False, default=dict)

    family = db.relationship("CreativeLibraryItem", back_populates="assets", foreign_keys=[family_db_id], lazy="joined")
    item = db.relationship("CreativeLibraryItem", foreign_keys=[item_id], lazy="joined")
    revision = db.relationship("CreativeLibraryRevision", back_populates="assets", foreign_keys=[revision_id], lazy="joined")
    variant = db.relationship("CreativeLibraryVariant", back_populates="assets", foreign_keys=[variant_db_id], lazy="joined")
    library_file = db.relationship("LibraryFile", foreign_keys=[library_file_id], lazy="joined")
    library_file_version = db.relationship("LibraryFileVersion", foreign_keys=[library_file_version_id], lazy="joined")

    __table_args__ = (
        db.Index("ix_creative_library_assets_family_role", "family_db_id", "role"),
        db.Index("ix_creative_library_assets_revision_role", "revision_id", "role"),
        db.Index("ix_creative_library_assets_uid_role", "vplib_uid", "role"),
        db.Index("ix_creative_library_assets_file", "library_file_id", "library_file_version_id"),
        db.Index("ix_creative_library_assets_variant_field", "variant_db_id", "field_key"),
    )

    def __repr__(self) -> str:
        return f"<CreativeLibraryAsset id={self.id!r} role={self.role!r} path={self.path!r}>"

    @classmethod
    def create_from_payload(
        cls,
        *,
        item: CreativeLibraryItem,
        revision: CreativeLibraryRevision,
        payload: Mapping[str, Any],
    ) -> "CreativeLibraryAsset":
        path = first_non_empty(
            payload.get("asset_path"),
            payload.get("path"),
            payload.get("relative_path"),
            payload.get("uri"),
        )
        role = enum_value(payload.get("role") or payload.get("asset_kind") or payload.get("kind"), default=CreativeLibraryAssetKind.OTHER.value)

        return cls(
            family=item,
            item=item,
            revision=revision,
            family_db_id=item.id,
            item_id=item.id,
            revision_id=revision.id,
            revision_db_id=revision.id,
            variant_db_id=normalize_int(payload.get("variant_db_id"), default=None, minimum=1),
            variant_id=normalize_optional_string(payload.get("variant_id") or payload.get("variantId"), max_length=MAX_VARIANT_ID_LENGTH),
            library_file_id=normalize_int(payload.get("library_file_id") or payload.get("file_id"), default=None, minimum=1),
            library_file_version_id=normalize_int(payload.get("library_file_version_id") or payload.get("file_version_id"), default=None, minimum=1),
            vplib_uid=item.vplib_uid,
            family_id=item.family_id,
            package_id=item.package_id,
            revision_hash=revision.revision_hash,
            role=role,
            asset_kind=enum_value(payload.get("asset_kind") or payload.get("kind") or role, default=CreativeLibraryAssetKind.OTHER.value),
            asset_type=normalize_optional_string(payload.get("asset_type") or payload.get("type"), max_length=MAX_ROLE_LENGTH),
            document_type=normalize_optional_string(payload.get("document_type") or payload.get("documentType"), max_length=MAX_ROLE_LENGTH),
            field_key=normalize_optional_string(payload.get("field_key") or payload.get("fieldKey"), max_length=MAX_FIELD_LENGTH),
            asset_path=normalize_optional_string(path),
            path=normalize_optional_string(path),
            relative_path=normalize_optional_string(payload.get("relative_path") or payload.get("path")),
            uri=normalize_optional_string(payload.get("uri") or payload.get("url")),
            label=normalize_optional_string(payload.get("label") or role, max_length=MAX_LABEL_LENGTH),
            asset_hash=normalize_optional_string(payload.get("asset_hash") or payload.get("hash"), max_length=MAX_HASH_LENGTH),
            checksum=normalize_optional_string(payload.get("checksum") or payload.get("sha256"), max_length=MAX_HASH_LENGTH),
            mime_type=normalize_optional_string(payload.get("mime_type") or payload.get("mimeType"), max_length=MAX_MIME_TYPE_LENGTH),
            size_bytes=payload.get("size_bytes") if payload.get("size_bytes") is not None else payload.get("sizeBytes"),
            exists=normalize_bool(payload.get("exists"), default=True),
            is_primary=normalize_bool(payload.get("is_primary") or payload.get("primary"), default=False),
            sort_order=normalize_int(payload.get("sort_order"), default=0, minimum=0) or 0,
            bounds_json=normalize_json_mapping(payload.get("bounds")),
            transform_json=normalize_json_mapping(payload.get("transform")),
            payload=normalize_json_mapping(payload),
            meta=normalize_json_mapping(payload.get("metadata")),
            metadata_json=normalize_json_mapping(payload.get("metadata")),
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "asset_db_id": self.id,
            "family_db_id": self.family_db_id,
            "item_id": self.item_id,
            "revision_id": self.revision_id,
            "revision_db_id": self.revision_db_id,
            "variant_db_id": self.variant_db_id,
            "variant_id": self.variant_id,
            "library_file_id": self.library_file_id,
            "library_file_version_id": self.library_file_version_id,
            "vplib_uid": self.vplib_uid,
            "family_id": self.family_id,
            "package_id": self.package_id,
            "revision_hash": self.revision_hash,
            "role": self.role,
            "asset_kind": self.asset_kind,
            "asset_type": self.asset_type,
            "type": self.asset_type,
            "document_type": self.document_type,
            "field_key": self.field_key,
            "asset_path": self.asset_path,
            "path": self.path,
            "relative_path": self.relative_path,
            "uri": self.uri,
            "label": self.label,
            "asset_hash": self.asset_hash,
            "checksum": self.checksum,
            "mime_type": self.mime_type,
            "size_bytes": self.size_bytes,
            "exists": self.exists,
            "is_primary": self.is_primary,
            "sort_order": self.sort_order,
            "bounds": normalize_json_mapping(self.bounds_json),
            "transform": normalize_json_mapping(self.transform_json),
            "payload": normalize_json_mapping(self.payload),
            "created_at": self.created_at.isoformat() if self.created_at else None,
            "updated_at": self.updated_at.isoformat() if self.updated_at else None,
            "meta": normalize_json_mapping(self.meta),
            "metadata": normalize_json_mapping(self.metadata_json),
        }


class CreativeLibraryDocument(TimestampMixin, JsonMixin, db.Model):
    """Persistierte JSON-/Dokumentrepräsentation einer Revision."""

    __tablename__ = "creative_library_documents"

    id = db.Column(db.BigInteger, primary_key=True, autoincrement=True)

    family_db_id = db.Column(
        db.BigInteger,
        db.ForeignKey("creative_library_items.id", ondelete="CASCADE"),
        nullable=True,
        index=True,
    )
    item_id = db.Column(
        db.BigInteger,
        db.ForeignKey("creative_library_items.id", ondelete="CASCADE"),
        nullable=True,
        index=True,
    )
    revision_id = db.Column(
        db.BigInteger,
        db.ForeignKey("creative_library_revisions.id", ondelete="CASCADE"),
        nullable=True,
        index=True,
    )
    revision_db_id = db.Column(db.BigInteger, nullable=True, index=True)

    variant_db_id = db.Column(
        db.BigInteger,
        db.ForeignKey("creative_library_variants.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )
    variant_id = db.Column(db.String(MAX_VARIANT_ID_LENGTH), nullable=True, index=True)

    library_file_id = db.Column(
        db.BigInteger,
        db.ForeignKey("library_files.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )
    library_file_version_id = db.Column(
        db.BigInteger,
        db.ForeignKey("library_file_versions.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )

    vplib_uid = db.Column(db.String(MAX_VPLIB_UID_LENGTH), nullable=True, index=True)
    family_id = db.Column(db.String(MAX_FAMILY_ID_LENGTH), nullable=True, index=True)
    package_id = db.Column(db.String(MAX_PACKAGE_ID_LENGTH), nullable=True, index=True)
    revision_hash = db.Column(db.String(MAX_HASH_LENGTH), nullable=True, index=True)

    relative_path = db.Column(db.Text, nullable=False)
    path = db.Column(db.Text, nullable=True)
    document_type = db.Column(db.String(MAX_ROLE_LENGTH), nullable=True, index=True)
    module = db.Column(db.String(MAX_ROLE_LENGTH), nullable=True, index=True)
    field_key = db.Column(db.String(MAX_FIELD_LENGTH), nullable=True, index=True)
    checksum = db.Column(db.String(MAX_HASH_LENGTH), nullable=True, index=True)

    document = db.Column(db.JSON, nullable=False, default=dict)
    payload = db.Column(db.JSON, nullable=False, default=dict)
    meta = db.Column(db.JSON, nullable=False, default=dict)
    metadata_json = db.Column(db.JSON, nullable=False, default=dict)

    family = db.relationship("CreativeLibraryItem", back_populates="documents", foreign_keys=[family_db_id], lazy="joined")
    item = db.relationship("CreativeLibraryItem", foreign_keys=[item_id], lazy="joined")
    revision = db.relationship("CreativeLibraryRevision", back_populates="document_rows", foreign_keys=[revision_id], lazy="joined")
    variant = db.relationship("CreativeLibraryVariant", back_populates="documents", foreign_keys=[variant_db_id], lazy="joined")
    library_file = db.relationship("LibraryFile", foreign_keys=[library_file_id], lazy="joined")
    library_file_version = db.relationship("LibraryFileVersion", foreign_keys=[library_file_version_id], lazy="joined")

    __table_args__ = (
        db.UniqueConstraint("revision_id", "relative_path", name="uq_creative_library_document_revision_path"),
        db.Index("ix_creative_library_documents_uid_path", "vplib_uid", "relative_path"),
        db.Index("ix_creative_library_documents_revision_module", "revision_id", "module"),
        db.Index("ix_creative_library_documents_file", "library_file_id", "library_file_version_id"),
        db.Index("ix_creative_library_documents_variant_field", "variant_db_id", "field_key"),
    )

    def __repr__(self) -> str:
        return f"<CreativeLibraryDocument id={self.id!r} path={self.relative_path!r}>"

    @classmethod
    def create_from_payload(
        cls,
        *,
        item: CreativeLibraryItem,
        revision: CreativeLibraryRevision,
        payload: Mapping[str, Any],
    ) -> "CreativeLibraryDocument":
        relative_path = normalize_relative_path(
            payload.get("relative_path") or payload.get("path"),
            field_name="relative_path",
        )

        module = normalize_optional_string(payload.get("module"), max_length=MAX_ROLE_LENGTH)
        if not module and "/" in relative_path:
            module = relative_path.split("/", 1)[0]

        document_payload = first_non_empty(
            payload.get("document"),
            payload.get("payload"),
            {},
        )

        return cls(
            family=item,
            item=item,
            revision=revision,
            family_db_id=item.id,
            item_id=item.id,
            revision_id=revision.id,
            revision_db_id=revision.id,
            variant_db_id=normalize_int(payload.get("variant_db_id"), default=None, minimum=1),
            variant_id=normalize_optional_string(payload.get("variant_id") or payload.get("variantId"), max_length=MAX_VARIANT_ID_LENGTH),
            library_file_id=normalize_int(payload.get("library_file_id") or payload.get("file_id"), default=None, minimum=1),
            library_file_version_id=normalize_int(payload.get("library_file_version_id") or payload.get("file_version_id"), default=None, minimum=1),
            vplib_uid=item.vplib_uid,
            family_id=item.family_id,
            package_id=item.package_id,
            revision_hash=revision.revision_hash,
            relative_path=relative_path,
            path=relative_path,
            document_type=normalize_optional_string(payload.get("document_type") or payload.get("type"), max_length=MAX_ROLE_LENGTH),
            module=module,
            field_key=normalize_optional_string(payload.get("field_key") or payload.get("fieldKey"), max_length=MAX_FIELD_LENGTH),
            checksum=normalize_optional_string(payload.get("checksum"), max_length=MAX_HASH_LENGTH) or stable_json_hash(document_payload),
            document=normalize_json_mapping(document_payload if isinstance(document_payload, Mapping) else {"value": document_payload}),
            payload=normalize_json_mapping(document_payload if isinstance(document_payload, Mapping) else {"value": document_payload}),
            meta=normalize_json_mapping(payload.get("metadata")),
            metadata_json=normalize_json_mapping(payload.get("metadata")),
        )

    def to_dict(self, *, include_payload: bool = True) -> dict[str, Any]:
        result = {
            "id": self.id,
            "document_db_id": self.id,
            "family_db_id": self.family_db_id,
            "item_id": self.item_id,
            "revision_id": self.revision_id,
            "revision_db_id": self.revision_db_id,
            "variant_db_id": self.variant_db_id,
            "variant_id": self.variant_id,
            "library_file_id": self.library_file_id,
            "library_file_version_id": self.library_file_version_id,
            "vplib_uid": self.vplib_uid,
            "family_id": self.family_id,
            "package_id": self.package_id,
            "revision_hash": self.revision_hash,
            "relative_path": self.relative_path,
            "path": self.path or self.relative_path,
            "document_type": self.document_type,
            "type": self.document_type,
            "module": self.module,
            "field_key": self.field_key,
            "checksum": self.checksum,
            "created_at": self.created_at.isoformat() if self.created_at else None,
            "updated_at": self.updated_at.isoformat() if self.updated_at else None,
            "meta": normalize_json_mapping(self.meta),
            "metadata": normalize_json_mapping(self.metadata_json),
        }

        if include_payload:
            result["document"] = normalize_json_mapping(self.document)
            result["payload"] = normalize_json_mapping(self.payload)

        return result


class CreativeLibraryScanIssue(TimestampMixin, JsonMixin, db.Model):
    """Issue/Warning/Error aus einem ScanRun oder einem Kandidaten-Sync."""

    __tablename__ = "creative_library_scan_issues"

    id = db.Column(db.BigInteger, primary_key=True, autoincrement=True)

    scan_run_id = db.Column(
        db.BigInteger,
        db.ForeignKey("creative_library_scan_runs.id", ondelete="CASCADE"),
        nullable=True,
        index=True,
    )
    scan_run_db_id = db.Column(db.BigInteger, nullable=True, index=True)

    family_db_id = db.Column(
        db.BigInteger,
        db.ForeignKey("creative_library_items.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )
    revision_id = db.Column(
        db.BigInteger,
        db.ForeignKey("creative_library_revisions.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )
    revision_db_id = db.Column(db.BigInteger, nullable=True, index=True)

    severity = db.Column(db.String(MAX_SEVERITY_LENGTH if "MAX_SEVERITY_LENGTH" in globals() else 40), nullable=False, default=CreativeLibraryIssueSeverity.ERROR.value, index=True)
    level = db.Column(db.String(40), nullable=True, index=True)
    code = db.Column(db.String(160), nullable=True, index=True)
    message = db.Column(db.Text, nullable=True)

    path = db.Column(db.Text, nullable=True)
    field = db.Column(db.String(MAX_FIELD_LENGTH), nullable=True)
    scope = db.Column(db.String(MAX_SCOPE_LENGTH), nullable=True, index=True)
    source_path = db.Column(db.Text, nullable=True)
    relative_path = db.Column(db.Text, nullable=True)

    vplib_uid = db.Column(db.String(MAX_VPLIB_UID_LENGTH), nullable=True, index=True)
    package_id = db.Column(db.String(MAX_PACKAGE_ID_LENGTH), nullable=True, index=True)
    family_id = db.Column(db.String(MAX_FAMILY_ID_LENGTH), nullable=True, index=True)
    revision_hash = db.Column(db.String(MAX_HASH_LENGTH), nullable=True, index=True)

    active = db.Column(db.Boolean, nullable=False, default=True, index=True)
    resolved = db.Column(db.Boolean, nullable=False, default=False, index=True)

    context_json = db.Column(db.JSON, nullable=False, default=dict)
    payload = db.Column(db.JSON, nullable=False, default=dict)
    meta = db.Column(db.JSON, nullable=False, default=dict)
    metadata_json = db.Column(db.JSON, nullable=False, default=dict)

    scan_run = db.relationship("CreativeLibraryScanRun", back_populates="issues", lazy="joined")
    family = db.relationship("CreativeLibraryItem", foreign_keys=[family_db_id], lazy="joined")
    revision = db.relationship("CreativeLibraryRevision", foreign_keys=[revision_id], lazy="joined")

    __table_args__ = (
        db.Index("ix_creative_library_scan_issues_run_severity", "scan_run_id", "severity"),
        db.Index("ix_creative_library_scan_issues_uid_code", "vplib_uid", "code"),
        db.Index("ix_creative_library_scan_issues_scope_severity", "scope", "severity"),
    )

    def __repr__(self) -> str:
        return f"<CreativeLibraryScanIssue id={self.id!r} severity={self.severity!r} code={self.code!r}>"

    @classmethod
    def from_issue_payload(
        cls,
        *,
        scan_run: CreativeLibraryScanRun | None,
        payload: Mapping[str, Any],
    ) -> "CreativeLibraryScanIssue":
        return cls(
            scan_run=scan_run,
            scan_run_id=scan_run.id if scan_run is not None else None,
            scan_run_db_id=scan_run.id if scan_run is not None else None,
            severity=enum_value(payload.get("severity"), default=CreativeLibraryIssueSeverity.ERROR.value),
            level=enum_value(payload.get("level") or payload.get("severity"), default=CreativeLibraryIssueSeverity.ERROR.value),
            code=normalize_optional_string(payload.get("code"), max_length=160),
            message=normalize_optional_string(payload.get("message") or payload.get("detail") or payload.get("error")),
            path=normalize_optional_string(payload.get("path")),
            field=normalize_optional_string(payload.get("field"), max_length=MAX_FIELD_LENGTH),
            scope=normalize_optional_string(payload.get("scope"), max_length=MAX_SCOPE_LENGTH),
            source_path=normalize_optional_string(payload.get("source_path") or payload.get("sourcePath")),
            relative_path=normalize_optional_string(payload.get("relative_path") or payload.get("relativePath")),
            vplib_uid=normalize_vplib_uid(payload.get("vplib_uid") or payload.get("vplibUid")),
            package_id=normalize_optional_string(payload.get("package_id") or payload.get("packageId"), max_length=MAX_PACKAGE_ID_LENGTH),
            family_id=normalize_optional_string(payload.get("family_id") or payload.get("familyId"), max_length=MAX_FAMILY_ID_LENGTH),
            revision_hash=normalize_optional_string(payload.get("revision_hash"), max_length=MAX_HASH_LENGTH),
            active=normalize_bool(payload.get("active"), default=True),
            resolved=normalize_bool(payload.get("resolved"), default=False),
            context_json=normalize_json_mapping(payload.get("context") or payload.get("details")),
            payload=normalize_json_mapping(payload.get("payload") or payload),
            meta=normalize_json_mapping(payload.get("metadata")),
            metadata_json=normalize_json_mapping(payload.get("metadata")),
        )

    def mark_resolved(self) -> None:
        self.resolved = True
        self.active = False
        self.touch()

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "issue_db_id": self.id,
            "scan_run_id": self.scan_run_id,
            "scan_run_db_id": self.scan_run_db_id,
            "family_db_id": self.family_db_id,
            "revision_id": self.revision_id,
            "revision_db_id": self.revision_db_id,
            "severity": self.severity,
            "level": self.level,
            "code": self.code,
            "message": self.message,
            "path": self.path,
            "field": self.field,
            "scope": self.scope,
            "source_path": self.source_path,
            "relative_path": self.relative_path,
            "vplib_uid": self.vplib_uid,
            "package_id": self.package_id,
            "family_id": self.family_id,
            "revision_hash": self.revision_hash,
            "active": self.active,
            "resolved": self.resolved,
            "context": normalize_json_mapping(self.context_json),
            "payload": normalize_json_mapping(self.payload),
            "meta": normalize_json_mapping(self.meta),
            "metadata": normalize_json_mapping(self.metadata_json),
            "created_at": self.created_at.isoformat() if self.created_at else None,
            "updated_at": self.updated_at.isoformat() if self.updated_at else None,
        }


class CreativeLibraryInventorySlot(TimestampMixin, JsonMixin, db.Model):
    """
    Legacy/system Creative-Library-Inventar-Slot.

    Für user-spezifische Creative-Library-Sichten wird künftig
    models/creative_library_user.py verwendet. Diese Tabelle bleibt als
    rückwärtskompatible Default-/System-Inventar-Tabelle bestehen.
    """

    __tablename__ = "creative_library_inventory_slots"

    id = db.Column(db.BigInteger, primary_key=True, autoincrement=True)

    inventory_key = db.Column(db.String(120), nullable=False, default=DEFAULT_INVENTORY_KEY, index=True)
    slot_index = db.Column(db.Integer, nullable=False)
    slot_id = db.Column(db.String(120), nullable=True, index=True)

    owner_user_id = db.Column(db.BigInteger, nullable=True, index=True)
    source_scope = db.Column(
        db.String(MAX_SOURCE_SCOPE_LENGTH),
        nullable=False,
        default=CreativeLibrarySourceScope.SYSTEM.value,
        index=True,
    )
    owner_scope = db.Column(
        db.String(MAX_OWNER_SCOPE_LENGTH),
        nullable=False,
        default=CreativeLibrarySourceScope.SYSTEM.value,
        index=True,
    )

    family_db_id = db.Column(
        db.BigInteger,
        db.ForeignKey("creative_library_items.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )
    item_id = db.Column(
        db.BigInteger,
        db.ForeignKey("creative_library_items.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )

    vplib_uid = db.Column(db.String(MAX_VPLIB_UID_LENGTH), nullable=True, index=True)
    family_id = db.Column(db.String(MAX_FAMILY_ID_LENGTH), nullable=True, index=True)
    package_id = db.Column(db.String(MAX_PACKAGE_ID_LENGTH), nullable=True, index=True)
    variant_id = db.Column(db.String(MAX_VARIANT_ID_LENGTH), nullable=True, index=True)

    label = db.Column(db.String(MAX_LABEL_LENGTH), nullable=True)
    description = db.Column(db.Text, nullable=True)
    family_slug = db.Column(db.String(MAX_FAMILY_SLUG_LENGTH), nullable=True)
    object_kind = db.Column(db.String(MAX_OBJECT_KIND_LENGTH), nullable=True, index=True)

    domain = db.Column(db.String(MAX_TAXONOMY_DOMAIN_LENGTH), nullable=True, index=True)
    category = db.Column(db.String(MAX_TAXONOMY_CATEGORY_LENGTH), nullable=True, index=True)
    subcategory = db.Column(db.String(MAX_TAXONOMY_CATEGORY_LENGTH), nullable=True, index=True)
    taxonomy_path = db.Column(db.String(MAX_TAXONOMY_PATH_LENGTH), nullable=True)

    status = db.Column(db.String(MAX_STATUS_LENGTH), nullable=False, default=CreativeLibraryStatus.ACTIVE.value, index=True)
    source = db.Column(db.String(60), nullable=True, default="database")
    scope = db.Column(db.String(60), nullable=True, default="editor")
    mode = db.Column(db.String(60), nullable=True, default="creative")

    enabled = db.Column(db.Boolean, nullable=False, default=True, index=True)
    visible = db.Column(db.Boolean, nullable=False, default=True, index=True)
    active = db.Column(db.Boolean, nullable=False, default=True, index=True)
    locked = db.Column(db.Boolean, nullable=False, default=False)
    pinned = db.Column(db.Boolean, nullable=False, default=False)
    selected = db.Column(db.Boolean, nullable=False, default=False)

    sort_order = db.Column(db.Integer, nullable=False, default=0)

    icon = db.Column(db.JSON, nullable=False, default=dict)
    preview = db.Column(db.JSON, nullable=False, default=dict)
    assets = db.Column(db.JSON, nullable=False, default=list)
    variant = db.Column(db.JSON, nullable=False, default=dict)
    placement = db.Column(db.JSON, nullable=False, default=dict)

    revision_hash = db.Column(db.String(MAX_HASH_LENGTH), nullable=True, index=True)
    publication_status = db.Column(db.String(MAX_STATUS_LENGTH), nullable=True, index=True)
    validation_status = db.Column(db.String(MAX_STATUS_LENGTH), nullable=True, index=True)

    selected_at = db.Column(db.DateTime(timezone=True), nullable=True)
    published_at = db.Column(db.DateTime(timezone=True), nullable=True)

    payload = db.Column(db.JSON, nullable=False, default=dict)
    meta = db.Column(db.JSON, nullable=False, default=dict)
    metadata_json = db.Column(db.JSON, nullable=False, default=dict)

    family = db.relationship("CreativeLibraryItem", back_populates="inventory_slots", foreign_keys=[family_db_id], lazy="joined")
    item = db.relationship("CreativeLibraryItem", foreign_keys=[item_id], lazy="joined")

    __table_args__ = (
        db.UniqueConstraint("inventory_key", "slot_index", name="uq_creative_library_inventory_key_slot"),
        db.Index("ix_creative_library_inventory_lookup", "inventory_key", "enabled", "sort_order"),
        db.Index("ix_creative_library_inventory_uid_variant", "vplib_uid", "variant_id"),
        db.Index("ix_creative_library_inventory_taxonomy", "domain", "category", "subcategory"),
        db.Index("ix_creative_library_inventory_owner", "owner_scope", "inventory_key"),
    )

    def __repr__(self) -> str:
        return f"<CreativeLibraryInventorySlot inventory={self.inventory_key!r} slot={self.slot_index!r} uid={self.vplib_uid!r}>"

    @classmethod
    def create_for_item(
        cls,
        *,
        item: CreativeLibraryItem,
        slot_index: int,
        variant_id: str | None = None,
        inventory_key: str = DEFAULT_INVENTORY_KEY,
        label: str | None = None,
        metadata: Mapping[str, Any] | None = None,
    ) -> "CreativeLibraryInventorySlot":
        taxonomy_path = taxonomy_path_for(domain=item.domain, category=item.category, subcategory=item.subcategory)

        return cls(
            inventory_key=normalize_required_string(inventory_key, field_name="inventory_key", max_length=120),
            slot_index=normalize_int(slot_index, default=0, minimum=0) or 0,
            slot_id=f"slot_{normalize_int(slot_index, default=0, minimum=0) or 0}",
            owner_user_id=item.owner_user_id,
            source_scope=item.source_scope,
            owner_scope=item.owner_scope,
            family=item,
            item=item,
            family_db_id=item.id,
            item_id=item.id,
            vplib_uid=require_vplib_uid(item.vplib_uid),
            family_id=item.family_id,
            package_id=item.package_id,
            variant_id=normalize_optional_string(variant_id or item.default_variant_id, max_length=MAX_VARIANT_ID_LENGTH),
            label=normalize_optional_string(label or item.label or item.name, max_length=MAX_LABEL_LENGTH),
            description=item.description,
            family_slug=item.family_slug or item.slug,
            object_kind=item.object_kind,
            domain=item.domain,
            category=item.category,
            subcategory=item.subcategory,
            taxonomy_path=taxonomy_path,
            enabled=True,
            visible=True,
            active=True,
            sort_order=normalize_int(slot_index, default=0, minimum=0) or 0,
            revision_hash=item.revision_hash or item.current_revision_hash,
            publication_status=item.publication_status,
            published_at=item.published_at,
            meta=normalize_json_mapping(metadata),
            metadata_json=normalize_json_mapping(metadata),
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "slot_id": self.slot_id or f"slot_{self.slot_index}",
            "inventory_key": self.inventory_key,
            "slot_index": self.slot_index,
            "owner_user_id": self.owner_user_id,
            "source_scope": self.source_scope,
            "owner_scope": self.owner_scope,
            "family_db_id": self.family_db_id,
            "item_id": self.item_id,
            "vplib_uid": self.vplib_uid,
            "family_id": self.family_id,
            "package_id": self.package_id,
            "variant_id": self.variant_id,
            "label": self.label,
            "description": self.description,
            "family_slug": self.family_slug,
            "object_kind": self.object_kind,
            "domain": self.domain,
            "category": self.category,
            "subcategory": self.subcategory,
            "taxonomy_path": self.taxonomy_path,
            "status": self.status,
            "source": self.source,
            "scope": self.scope,
            "mode": self.mode,
            "enabled": self.enabled,
            "visible": self.visible,
            "active": self.active,
            "locked": self.locked,
            "pinned": self.pinned,
            "selected": self.selected,
            "sort_order": self.sort_order,
            "icon": normalize_json_mapping(self.icon),
            "preview": normalize_json_mapping(self.preview),
            "assets": normalize_json_list(self.assets),
            "variant": normalize_json_mapping(self.variant),
            "placement": normalize_json_mapping(self.placement),
            "revision_hash": self.revision_hash,
            "publication_status": self.publication_status,
            "validation_status": self.validation_status,
            "selected_at": self.selected_at.isoformat() if self.selected_at else None,
            "published_at": self.published_at.isoformat() if self.published_at else None,
            "payload": normalize_json_mapping(self.payload),
            "meta": normalize_json_mapping(self.meta),
            "metadata": normalize_json_mapping(self.metadata_json),
            "created_at": self.created_at.isoformat() if self.created_at else None,
            "updated_at": self.updated_at.isoformat() if self.updated_at else None,
        }


# ---------------------------------------------------------------------------
# Repository-compatible aliases
# ---------------------------------------------------------------------------

CreativeLibraryFamily = CreativeLibraryItem
CreativeLibraryFamilyRevision = CreativeLibraryRevision


# ---------------------------------------------------------------------------
# Public model helpers
# ---------------------------------------------------------------------------

def iter_creative_library_models() -> tuple[type[Any], ...]:
    """Gibt alle echten Modelklassen dieser Datei zurück."""
    return (
        CreativeLibraryItem,
        CreativeLibraryScanRun,
        CreativeLibraryRevision,
        CreativeLibraryVariant,
        CreativeLibraryAsset,
        CreativeLibraryDocument,
        CreativeLibraryScanIssue,
        CreativeLibraryInventorySlot,
    )


def iter_models() -> tuple[type[Any], ...]:
    """Kompatibler Alias für models.__init__.py."""
    return iter_creative_library_models()


def get_models() -> tuple[type[Any], ...]:
    """Kompatibler Alias für Modelle-Discovery."""
    return iter_creative_library_models()


def iter_creative_library_model_aliases() -> tuple[type[Any], ...]:
    """Gibt Alias-Klassen für Repository-Kompatibilität zurück."""
    return (
        CreativeLibraryFamily,
        CreativeLibraryFamilyRevision,
    )


def get_creative_library_model_names() -> tuple[str, ...]:
    """Gibt die Namen aller echten Creative-Library-Modelle zurück."""
    return tuple(model.__name__ for model in iter_creative_library_models())


def get_creative_library_alias_names() -> tuple[str, ...]:
    """Gibt die Namen der Repository-kompatiblen Aliase zurück."""
    return (
        "CreativeLibraryFamily",
        "CreativeLibraryFamilyRevision",
    )


def get_creative_library_table_names() -> tuple[str, ...]:
    """Gibt die Tabellennamen aller Creative-Library-Modelle zurück."""
    return tuple(
        str(getattr(model, "__tablename__", ""))
        for model in iter_creative_library_models()
    )


def get_creative_library_models_health() -> dict[str, Any]:
    """Gibt einen JSON-kompatiblen Health-Snapshot dieser Model-Datei zurück."""
    models = iter_creative_library_models()
    table_names = get_creative_library_table_names()

    try:
        metadata = getattr(db, "metadata", None)
        tables = getattr(metadata, "tables", None)

        if tables is None:
            metadata_table_names: tuple[str, ...] = tuple()
        else:
            metadata_table_names = tuple(sorted(str(name) for name in tables.keys()))

        missing_tables = [table_name for table_name in table_names if table_name not in metadata_table_names]
        healthy = len(models) > 0 and len(table_names) > 0 and not missing_tables

        return {
            "ok": healthy,
            "healthy": healthy,
            "schema_version": CREATIVE_LIBRARY_MODELS_SCHEMA_VERSION,
            "model_count": len(models),
            "model_names": [model.__name__ for model in models],
            "alias_names": list(get_creative_library_alias_names()),
            "table_count": len(table_names),
            "tables": list(table_names),
            "metadata_table_count": len(metadata_table_names),
            "metadata_table_names": list(metadata_table_names),
            "missing_tables": missing_tables,
            "vplib_uid_field": CREATIVE_LIBRARY_UID_FIELD,
            "database_creates_vplib_uid": False,
            "uses_sqlalchemy_extension": True,
            "supports_repository_family_alias": True,
            "supports_repository_revision_alias": True,
            "supports_document_table": True,
            "supports_inventory_slots": True,
            "supports_owner_scope": True,
            "supports_generator_metadata": True,
            "supports_library_file_links": True,
            "supports_draft_source_pointers": True,
        }
    except Exception as exc:
        return {
            "ok": False,
            "healthy": False,
            "schema_version": CREATIVE_LIBRARY_MODELS_SCHEMA_VERSION,
            "model_count": len(models),
            "model_names": [model.__name__ for model in models],
            "table_count": len(table_names),
            "tables": list(table_names),
            "error": f"{type(exc).__name__}: {exc}",
        }


def assert_creative_library_models_ready() -> None:
    """Wirft RuntimeError, wenn die Creative-Library-Models nicht bereit sind."""
    health = get_creative_library_models_health()

    if health.get("healthy"):
        return

    raise RuntimeError(f"Creative library models are not ready: {health}")


def clear_creative_library_models_cache() -> dict[str, Any]:
    """Leert lokale Caches dieser Datei."""
    cleared: list[str] = []

    for cached_func in (
        _load_db,
        _cached_vplib_uid_fallback,
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
    "CREATIVE_LIBRARY_MODELS_SCHEMA_VERSION",
    "CREATIVE_LIBRARY_UID_FIELD",
    "DEFAULT_INVENTORY_KEY",
    "DEFAULT_USER_ID",

    # Models
    "CreativeLibraryAsset",
    "CreativeLibraryDocument",
    "CreativeLibraryFamily",
    "CreativeLibraryFamilyRevision",
    "CreativeLibraryInventorySlot",
    "CreativeLibraryItem",
    "CreativeLibraryRevision",
    "CreativeLibraryScanIssue",
    "CreativeLibraryScanRun",
    "CreativeLibraryVariant",

    # Enums
    "CreativeLibraryAssetKind",
    "CreativeLibraryIssueSeverity",
    "CreativeLibraryScanStatus",
    "CreativeLibrarySourceScope",
    "CreativeLibraryStatus",

    # Mixins
    "JsonMixin",
    "TimestampMixin",

    # Helpers
    "assert_creative_library_models_ready",
    "clear_creative_library_models_cache",
    "enum_value",
    "extract_manifest_classification",
    "extract_variant_id",
    "first_non_empty",
    "get_creative_library_alias_names",
    "get_creative_library_model_names",
    "get_creative_library_models_health",
    "get_creative_library_table_names",
    "get_models",
    "identity_dict",
    "iter_creative_library_model_aliases",
    "iter_creative_library_models",
    "iter_models",
    "merge_json",
    "new_uid",
    "normalize_bool",
    "normalize_int",
    "normalize_json_list",
    "normalize_json_mapping",
    "normalize_json_value",
    "normalize_optional_string",
    "normalize_relative_path",
    "normalize_required_string",
    "normalize_source_scope",
    "normalize_status",
    "normalize_user_id",
    "normalize_vplib_uid",
    "owner_scope_for",
    "require_vplib_uid",
    "stable_json_hash",
    "taxonomy_path_for",
    "utc_now",
]