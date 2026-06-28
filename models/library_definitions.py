# services/vectoplan-library/models/library_definitions.py
"""
Database models for VECTOPLAN Library Definitions.

Diese Datei modelliert den DB-seitigen Definitionskatalog für:

- variables
- units
- materials
- document_types
- object_kinds
- family_profiles
- variant_profiles
- profile_bindings
- user/system overrides

Ziel:

    definitions/data/*.json
        -> Seed / Fallback / Repo-Quelle
        -> LibraryDefinitionSeedRun
        -> PostgreSQL Definition Tables
        -> Definition Catalog Service
        -> /api/v1/vplib/definitions/*
        -> Create UI / Variant Drawer / Upload Rules / Generator

Wichtige Architekturregeln:

- Diese Datei erzeugt keine Tabellen.
- Diese Datei führt keine Migration aus.
- Diese Datei führt kein db.create_all() aus.
- Diese Datei führt keine Seed-Logik aus.
- Diese Datei spricht keine Datenbankverbindung aktiv an.
- Diese Datei deklariert nur SQLAlchemy Models und robuste Helfer.
- Systemdefinitionen werden nicht direkt überschrieben.
- User-Änderungen werden als eigene user-scoped Definitionen oder Overrides gespeichert.
- Technische Namen, JSON-Keys und Variablen bleiben Englisch.

Phase 1:

- user_id darf weiterhin 1 sein.
- owner_user_id=None bedeutet system-owned.
- owner_scope="system" bedeutet globale Standarddefinition.
- owner_scope="user:<id>" bedeutet User-Erweiterung.
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

LIBRARY_DEFINITIONS_MODELS_SCHEMA_VERSION: Final[str] = "vectoplan_library.library_definitions.models.v1"
DEFAULT_DEFINITIONS_VERSION: Final[str] = "v1"
DEFAULT_SCHEMA_VERSION: Final[str] = "1.0"
DEFAULT_USER_ID: Final[int] = 1

DATASET_VARIABLES: Final[str] = "variables"
DATASET_UNITS: Final[str] = "units"
DATASET_MATERIALS: Final[str] = "materials"
DATASET_DOCUMENT_TYPES: Final[str] = "document_types"
DATASET_OBJECT_KINDS: Final[str] = "object_kinds"
DATASET_FAMILY_PROFILES: Final[str] = "family_profiles"
DATASET_VARIANT_PROFILES: Final[str] = "variant_profiles"
DATASET_PROFILE_BINDINGS: Final[str] = "profile_bindings"

LIBRARY_DEFINITION_DATASET_KEYS: Final[tuple[str, ...]] = (
    DATASET_VARIABLES,
    DATASET_UNITS,
    DATASET_MATERIALS,
    DATASET_DOCUMENT_TYPES,
    DATASET_OBJECT_KINDS,
    DATASET_FAMILY_PROFILES,
    DATASET_VARIANT_PROFILES,
    DATASET_PROFILE_BINDINGS,
)

MAX_UID_LENGTH: Final[int] = 80
MAX_KEY_LENGTH: Final[int] = 255
MAX_SHORT_KEY_LENGTH: Final[int] = 160
MAX_LABEL_LENGTH: Final[int] = 255
MAX_DATASET_KEY_LENGTH: Final[int] = 120
MAX_STATUS_LENGTH: Final[int] = 40
MAX_SOURCE_SCOPE_LENGTH: Final[int] = 40
MAX_OWNER_SCOPE_LENGTH: Final[int] = 120


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

class LibraryDefinitionSourceScope(str, enum.Enum):
    SYSTEM = "system"
    USER = "user"
    IMPORTED = "imported"
    GENERATED = "generated"

    @property
    def key(self) -> str:
        return str(self.value)


class LibraryDefinitionStatus(str, enum.Enum):
    DRAFT = "draft"
    ACTIVE = "active"
    INACTIVE = "inactive"
    DEPRECATED = "deprecated"
    INVALID = "invalid"
    DELETED = "deleted"

    @property
    def key(self) -> str:
        return str(self.value)


class LibraryDefinitionSeedStatus(str, enum.Enum):
    RUNNING = "running"
    COMPLETED = "completed"
    PARTIAL = "partial"
    FAILED = "failed"
    SKIPPED = "skipped"

    @property
    def key(self) -> str:
        return str(self.value)


class LibraryDefinitionOverrideAction(str, enum.Enum):
    HIDE = "hide"
    RESTORE = "restore"
    RENAME = "rename"
    REORDER = "reorder"
    PATCH = "patch"
    REPLACE = "replace"
    DELETE = "delete"

    @property
    def key(self) -> str:
        return str(self.value)


class LibraryDefinitionValueType(str, enum.Enum):
    STRING = "string"
    TEXT = "text"
    NUMBER = "number"
    INTEGER = "integer"
    BOOLEAN = "boolean"
    ENUM = "enum"
    DATE = "date"
    DATETIME = "datetime"
    URL = "url"
    MONEY = "money"
    DOCUMENT_LIST = "document_list"
    FILE = "file"
    FILE_LIST = "file_list"
    JSON = "json"
    OBJECT = "object"
    LIST = "list"
    COLOR = "color"

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


def normalize_key(value: Any, *, field_name: str = "key", max_length: int = MAX_KEY_LENGTH) -> str:
    """
    Normalisiert stabile technische Definition-Keys.

    Wichtig:
    - Punkte bleiben erhalten: dimensions.width_mm
    - Slashes bleiben nicht erhalten.
    - Whitespace wird zu underscore.
    - Groß-/Kleinschreibung wird auf lowercase normalisiert.
    """

    raw = normalize_required_string(value, field_name=field_name, max_length=max_length)
    normalized = (
        raw.strip()
        .replace("\\", "/")
        .replace("/", ".")
        .replace(" ", "_")
        .replace("-", "_")
    )

    while ".." in normalized:
        normalized = normalized.replace("..", ".")

    normalized = normalized.strip("._").lower()

    if not normalized:
        raise ValueError(f"{field_name} is required.")

    return normalized[:max_length]


def normalize_slug(value: Any, *, fallback: str = "", max_length: int = MAX_SHORT_KEY_LENGTH) -> str | None:
    """Baut eine URL-/codefreundliche Slug-Form aus einem Key."""
    text = normalize_optional_string(value, max_length=max_length)
    if text is None:
        text = normalize_optional_string(fallback, max_length=max_length)

    if text is None:
        return None

    slug = (
        text.strip()
        .lower()
        .replace("\\", "/")
        .replace("/", "-")
        .replace(".", "-")
        .replace("_", "-")
        .replace(" ", "-")
    )

    cleaned = []
    previous_dash = False

    for char in slug:
        if char.isalnum():
            cleaned.append(char)
            previous_dash = False
            continue

        if char in {"-", "+"}:
            if not previous_dash:
                cleaned.append("-")
                previous_dash = True
            continue

        if not previous_dash:
            cleaned.append("-")
            previous_dash = True

    result = "".join(cleaned).strip("-")
    return result[:max_length] if result else None


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


def normalize_float(
    value: Any,
    *,
    default: float | None = None,
    minimum: float | None = None,
    maximum: float | None = None,
) -> float | None:
    """Robuste Float-Normalisierung."""
    if value is None and default is None:
        return None

    try:
        result = float(value)
    except Exception:
        if default is None:
            return None
        result = float(default)

    if minimum is not None:
        result = max(float(minimum), result)

    if maximum is not None:
        result = min(float(maximum), result)

    return result


def normalize_user_id(value: Any, *, default: int | None = DEFAULT_USER_ID) -> int | None:
    """Normalisiert User-ID. None bleibt None, wenn default=None."""
    return normalize_int(value, default=default, minimum=1)


def normalize_source_scope(value: Any, *, default: str = LibraryDefinitionSourceScope.SYSTEM.value) -> str:
    """Normalisiert source_scope."""
    text = enum_value(value, default=default).strip().lower()

    aliases = {
        "core": LibraryDefinitionSourceScope.SYSTEM.value,
        "default": LibraryDefinitionSourceScope.SYSTEM.value,
        "global": LibraryDefinitionSourceScope.SYSTEM.value,
        "system": LibraryDefinitionSourceScope.SYSTEM.value,
        "user": LibraryDefinitionSourceScope.USER.value,
        "custom": LibraryDefinitionSourceScope.USER.value,
        "import": LibraryDefinitionSourceScope.IMPORTED.value,
        "imported": LibraryDefinitionSourceScope.IMPORTED.value,
        "generated": LibraryDefinitionSourceScope.GENERATED.value,
        "generator": LibraryDefinitionSourceScope.GENERATED.value,
    }

    return aliases.get(text, text if text else default)[:MAX_SOURCE_SCOPE_LENGTH]


def owner_scope_for(
    *,
    source_scope: Any = LibraryDefinitionSourceScope.SYSTEM.value,
    owner_user_id: Any = None,
) -> str:
    """
    Baut einen stabilen owner_scope.

    Hintergrund:
    PostgreSQL behandelt NULL in UniqueConstraints nicht als gleich.
    Deshalb wird für eindeutige Definitionen zusätzlich ein nicht-nullbarer
    owner_scope gespeichert.
    """

    scope = normalize_source_scope(source_scope)
    user_id = normalize_user_id(owner_user_id, default=None)

    if scope == LibraryDefinitionSourceScope.SYSTEM.value and user_id is None:
        return LibraryDefinitionSourceScope.SYSTEM.value

    if scope == LibraryDefinitionSourceScope.USER.value:
        return f"user:{user_id or DEFAULT_USER_ID}"

    if user_id is not None:
        return f"{scope}:{user_id}"

    return scope or LibraryDefinitionSourceScope.SYSTEM.value


def normalize_status(
    value: Any,
    *,
    default: str = LibraryDefinitionStatus.ACTIVE.value,
    active: Any = None,
) -> str:
    """Normalisiert Status mit aktiv/inaktiv-Fallback."""
    if value is not None:
        text = enum_value(value, default=default).strip().lower()
        return text[:MAX_STATUS_LENGTH] if text else default

    if active is not None and not normalize_bool(active, default=True):
        return LibraryDefinitionStatus.INACTIVE.value

    return default


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


def item_list_from_payload(payload: Mapping[str, Any] | None) -> list[dict[str, Any]]:
    """Extrahiert items[] defensiv aus einem Dataset-Payload."""
    data = normalize_json_mapping(payload)
    items = data.get("items")

    if not isinstance(items, list):
        return []

    result: list[dict[str, Any]] = []

    for item in items:
        if isinstance(item, Mapping):
            result.append(normalize_json_mapping(item))

    return result


def definition_key_from_item(
    item: Mapping[str, Any],
    *,
    preferred_keys: tuple[str, ...] = ("key", "id"),
    field_name: str = "definition_key",
) -> str:
    """Ermittelt einen stabilen Definition-Key aus einem JSON-Item."""
    for key in preferred_keys:
        value = item.get(key)
        if value is not None and str(value).strip():
            return normalize_key(value, field_name=field_name)

    raise ValueError(f"{field_name} is required.")


def clean_dataset_key(value: Any) -> str:
    """Normalisiert Dataset-Key."""
    key = normalize_key(value, field_name="dataset_key", max_length=MAX_DATASET_KEY_LENGTH)
    aliases = {
        "documenttypes": DATASET_DOCUMENT_TYPES,
        "document_types": DATASET_DOCUMENT_TYPES,
        "documents": DATASET_DOCUMENT_TYPES,
        "objectkinds": DATASET_OBJECT_KINDS,
        "object_kinds": DATASET_OBJECT_KINDS,
        "familyprofiles": DATASET_FAMILY_PROFILES,
        "family_profiles": DATASET_FAMILY_PROFILES,
        "variantprofiles": DATASET_VARIANT_PROFILES,
        "variant_profiles": DATASET_VARIANT_PROFILES,
        "profilebindings": DATASET_PROFILE_BINDINGS,
        "profile_bindings": DATASET_PROFILE_BINDINGS,
    }

    return aliases.get(key, key)


def list_contains(value: Iterable[Any] | None, needle: Any) -> bool:
    """Prüft defensiv, ob eine JSON-Liste einen Wert enthält."""
    normalized_needle = clean_string(needle)
    if not normalized_needle:
        return False

    for item in normalize_json_list(value):
        if clean_string(item) == normalized_needle:
            return True

    return False


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


class DefinitionRecordMixin(TimestampMixin, JsonMixin):
    """
    Gemeinsame Spalten für konkrete Definitionstabellen.

    Jede konkrete Definitionstabelle bekommt zusätzlich dataset_id und
    tabellenspezifische Felder.
    """

    id = db.Column(db.BigInteger, primary_key=True, autoincrement=True)

    definition_uid = db.Column(db.String(MAX_UID_LENGTH), nullable=False, unique=True, index=True, default=new_uid)
    dataset_key = db.Column(db.String(MAX_DATASET_KEY_LENGTH), nullable=False, index=True)

    definition_key = db.Column(db.String(MAX_KEY_LENGTH), nullable=False, index=True)
    external_id = db.Column(db.String(MAX_KEY_LENGTH), nullable=True, index=True)
    slug = db.Column(db.String(MAX_SHORT_KEY_LENGTH), nullable=True, index=True)

    label = db.Column(db.String(MAX_LABEL_LENGTH), nullable=True)
    name = db.Column(db.String(MAX_LABEL_LENGTH), nullable=True)
    description = db.Column(db.Text, nullable=True)

    source_scope = db.Column(
        db.String(MAX_SOURCE_SCOPE_LENGTH),
        nullable=False,
        default=LibraryDefinitionSourceScope.SYSTEM.value,
        index=True,
    )
    owner_user_id = db.Column(db.BigInteger, nullable=True, index=True)
    owner_scope = db.Column(
        db.String(MAX_OWNER_SCOPE_LENGTH),
        nullable=False,
        default=LibraryDefinitionSourceScope.SYSTEM.value,
        index=True,
    )
    base_definition_uid = db.Column(db.String(MAX_UID_LENGTH), nullable=True, index=True)

    status = db.Column(
        db.String(MAX_STATUS_LENGTH),
        nullable=False,
        default=LibraryDefinitionStatus.ACTIVE.value,
        index=True,
    )
    active = db.Column(db.Boolean, nullable=False, default=True, index=True)
    visible = db.Column(db.Boolean, nullable=False, default=True, index=True)
    system_required = db.Column(db.Boolean, nullable=False, default=False)

    sort_order = db.Column(db.Integer, nullable=False, default=0)

    tags_json = db.Column(db.JSON, nullable=False, default=list)
    aliases_json = db.Column(db.JSON, nullable=False, default=list)
    i18n_json = db.Column(db.JSON, nullable=False, default=dict)
    ui_json = db.Column(db.JSON, nullable=False, default=dict)

    payload = db.Column(db.JSON, nullable=False, default=dict)
    meta = db.Column(db.JSON, nullable=False, default=dict)
    metadata_json = db.Column(db.JSON, nullable=False, default=dict)

    created_by_user_id = db.Column(db.BigInteger, nullable=True, index=True)
    updated_by_user_id = db.Column(db.BigInteger, nullable=True, index=True)
    deleted_at = db.Column(db.DateTime(timezone=True), nullable=True)

    def mark_deleted(self, *, user_id: Any = None) -> None:
        """Soft-delete für Definitionen."""
        self.active = False
        self.visible = False
        self.status = LibraryDefinitionStatus.DELETED.value
        self.deleted_at = utc_now()
        normalized_user_id = normalize_user_id(user_id, default=None)
        if normalized_user_id is not None:
            self.updated_by_user_id = normalized_user_id
        self.touch()

    def to_common_dict(self) -> dict[str, Any]:
        """Serialisiert gemeinsame Felder API-freundlich."""
        return {
            "id": self.id,
            "definition_uid": self.definition_uid,
            "dataset_key": self.dataset_key,
            "definition_key": self.definition_key,
            "external_id": self.external_id,
            "slug": self.slug,
            "label": self.label,
            "name": self.name,
            "description": self.description,
            "source_scope": self.source_scope,
            "owner_user_id": self.owner_user_id,
            "owner_scope": self.owner_scope,
            "base_definition_uid": self.base_definition_uid,
            "status": self.status,
            "active": self.active,
            "visible": self.visible,
            "system_required": self.system_required,
            "sort_order": self.sort_order,
            "tags": normalize_json_list(self.tags_json),
            "aliases": normalize_json_list(self.aliases_json),
            "i18n": normalize_json_mapping(self.i18n_json),
            "ui": normalize_json_mapping(self.ui_json),
            "payload": normalize_json_mapping(self.payload),
            "meta": normalize_json_mapping(self.meta),
            "metadata": normalize_json_mapping(self.metadata_json),
            "created_by_user_id": self.created_by_user_id,
            "updated_by_user_id": self.updated_by_user_id,
            "deleted_at": self.deleted_at.isoformat() if self.deleted_at else None,
            "created_at": self.created_at.isoformat() if self.created_at else None,
            "updated_at": self.updated_at.isoformat() if self.updated_at else None,
        }


def apply_common_definition_fields(
    instance: DefinitionRecordMixin,
    *,
    dataset_key: str,
    item: Mapping[str, Any],
    definition_key: str,
    source_scope: Any = LibraryDefinitionSourceScope.SYSTEM.value,
    owner_user_id: Any = None,
    dataset: Any = None,
    created_by_user_id: Any = None,
    updated_by_user_id: Any = None,
) -> None:
    """
    Füllt gemeinsame Felder auf einer Definition.

    Diese Funktion funktioniert für create und update. Wenn definition_uid bereits
    existiert, bleibt sie stabil.
    """

    normalized_dataset_key = clean_dataset_key(dataset_key)
    normalized_source_scope = normalize_source_scope(source_scope)
    normalized_owner_user_id = normalize_user_id(owner_user_id, default=None)
    normalized_owner_scope = owner_scope_for(
        source_scope=normalized_source_scope,
        owner_user_id=normalized_owner_user_id,
    )

    if not getattr(instance, "definition_uid", None):
        explicit_uid = normalize_optional_string(item.get("definition_uid") or item.get("uid"), max_length=MAX_UID_LENGTH)
        instance.definition_uid = explicit_uid or new_uid()

    if hasattr(instance, "dataset_id"):
        instance.dataset_id = getattr(dataset, "id", None)

    instance.dataset_key = normalized_dataset_key
    instance.definition_key = normalize_key(definition_key, field_name="definition_key")
    instance.external_id = normalize_optional_string(
        first_non_empty(item.get("id"), item.get("key"), instance.definition_key),
        max_length=MAX_KEY_LENGTH,
    )
    instance.slug = normalize_slug(first_non_empty(item.get("slug"), item.get("id"), item.get("key")), fallback=instance.definition_key)

    instance.label = normalize_optional_string(item.get("label"), max_length=MAX_LABEL_LENGTH)
    instance.name = normalize_optional_string(first_non_empty(item.get("name"), item.get("label")), max_length=MAX_LABEL_LENGTH)
    instance.description = normalize_optional_string(item.get("description"))

    instance.source_scope = normalized_source_scope
    instance.owner_user_id = normalized_owner_user_id
    instance.owner_scope = normalized_owner_scope
    instance.base_definition_uid = normalize_optional_string(
        first_non_empty(item.get("base_definition_uid"), item.get("baseDefinitionUid")),
        max_length=MAX_UID_LENGTH,
    )

    instance.active = normalize_bool(item.get("active"), default=True)
    instance.visible = normalize_bool(item.get("visible"), default=True)
    instance.system_required = normalize_bool(
        first_non_empty(
            item.get("system_required"),
            item.get("systemRequired"),
            normalize_json_mapping(item.get("metadata")).get("core_variable"),
            normalize_json_mapping(item.get("metadata")).get("core_unit"),
            normalize_json_mapping(item.get("metadata")).get("core_material"),
            normalize_json_mapping(item.get("metadata")).get("core_document_type"),
        ),
        default=False,
    )
    instance.status = normalize_status(item.get("status"), active=instance.active)

    instance.sort_order = normalize_int(item.get("sort_order"), default=0, minimum=0) or 0

    instance.tags_json = normalize_json_list(item.get("tags"))
    instance.aliases_json = normalize_json_list(item.get("aliases"))
    instance.i18n_json = normalize_json_mapping(item.get("i18n"))
    instance.ui_json = normalize_json_mapping(item.get("ui"))

    instance.payload = normalize_json_mapping(item)
    instance.meta = normalize_json_mapping(item.get("meta"))
    instance.metadata_json = normalize_json_mapping(item.get("metadata"))

    creator_id = normalize_user_id(created_by_user_id, default=None)
    updater_id = normalize_user_id(updated_by_user_id, default=None)

    if getattr(instance, "created_by_user_id", None) is None and creator_id is not None:
        instance.created_by_user_id = creator_id

    if updater_id is not None:
        instance.updated_by_user_id = updater_id

    instance.touch()


# ---------------------------------------------------------------------------
# Dataset / seed run models
# ---------------------------------------------------------------------------

class LibraryDefinitionDataset(TimestampMixin, JsonMixin, db.Model):
    """Ein Definitions-Dataset, z. B. variables, units oder variant_profiles."""

    __tablename__ = "library_definition_datasets"

    id = db.Column(db.BigInteger, primary_key=True, autoincrement=True)

    dataset_uid = db.Column(db.String(MAX_UID_LENGTH), nullable=False, unique=True, index=True, default=new_uid)
    dataset_key = db.Column(db.String(MAX_DATASET_KEY_LENGTH), nullable=False, unique=True, index=True)

    schema_version = db.Column(db.String(80), nullable=True)
    definitions_version = db.Column(db.String(80), nullable=True, index=True)

    label = db.Column(db.String(MAX_LABEL_LENGTH), nullable=True)
    description = db.Column(db.Text, nullable=True)

    source_file_path = db.Column(db.Text, nullable=True)
    checksum = db.Column(db.String(128), nullable=True, index=True)

    active = db.Column(db.Boolean, nullable=False, default=True, index=True)
    status = db.Column(db.String(MAX_STATUS_LENGTH), nullable=False, default=LibraryDefinitionStatus.ACTIVE.value, index=True)
    item_count = db.Column(db.Integer, nullable=False, default=0)

    seeded_at = db.Column(db.DateTime(timezone=True), nullable=True)
    last_synced_at = db.Column(db.DateTime(timezone=True), nullable=True)

    payload = db.Column(db.JSON, nullable=False, default=dict)
    meta = db.Column(db.JSON, nullable=False, default=dict)
    metadata_json = db.Column(db.JSON, nullable=False, default=dict)

    __table_args__ = (
        db.Index("ix_library_definition_datasets_key_status", "dataset_key", "status"),
        db.Index("ix_library_definition_datasets_version", "definitions_version", "active"),
    )

    def __repr__(self) -> str:
        return f"<LibraryDefinitionDataset id={self.id!r} key={self.dataset_key!r} version={self.definitions_version!r}>"

    @classmethod
    def create_from_payload(
        cls,
        payload: Mapping[str, Any],
        *,
        dataset_key: Any = None,
        source_file_path: Any = None,
        metadata: Mapping[str, Any] | None = None,
    ) -> "LibraryDefinitionDataset":
        """Erstellt ein Dataset-Objekt aus einem JSON-Dataset-Payload."""
        data = normalize_json_mapping(payload)
        key = clean_dataset_key(first_non_empty(dataset_key, data.get("dataset")))

        now = utc_now()

        return cls(
            dataset_uid=normalize_optional_string(data.get("dataset_uid"), max_length=MAX_UID_LENGTH) or new_uid(),
            dataset_key=key,
            schema_version=normalize_optional_string(data.get("schema_version"), max_length=80),
            definitions_version=normalize_optional_string(data.get("definitions_version"), max_length=80) or DEFAULT_DEFINITIONS_VERSION,
            label=normalize_optional_string(data.get("label"), max_length=MAX_LABEL_LENGTH),
            description=normalize_optional_string(data.get("description")),
            source_file_path=normalize_optional_string(source_file_path or data.get("_file")),
            checksum=stable_json_hash(data),
            active=True,
            status=LibraryDefinitionStatus.ACTIVE.value,
            item_count=len(item_list_from_payload(data)),
            seeded_at=now,
            last_synced_at=now,
            payload=data,
            meta=normalize_json_mapping(metadata),
            metadata_json=merge_json(data.get("metadata") if isinstance(data.get("metadata"), Mapping) else None, metadata),
        )

    def update_from_payload(
        self,
        payload: Mapping[str, Any],
        *,
        source_file_path: Any = None,
        metadata: Mapping[str, Any] | None = None,
    ) -> None:
        """Aktualisiert mutable Dataset-Felder."""
        data = normalize_json_mapping(payload)

        incoming_key = clean_dataset_key(first_non_empty(data.get("dataset"), self.dataset_key))
        if self.dataset_key and self.dataset_key != incoming_key:
            raise ValueError(f"Cannot change dataset_key from {self.dataset_key!r} to {incoming_key!r}.")

        self.schema_version = normalize_optional_string(data.get("schema_version"), max_length=80)
        self.definitions_version = normalize_optional_string(data.get("definitions_version"), max_length=80) or self.definitions_version
        self.label = normalize_optional_string(data.get("label"), max_length=MAX_LABEL_LENGTH)
        self.description = normalize_optional_string(data.get("description"))
        self.source_file_path = normalize_optional_string(source_file_path or data.get("_file")) or self.source_file_path
        self.checksum = stable_json_hash(data)
        self.active = True
        self.status = LibraryDefinitionStatus.ACTIVE.value
        self.item_count = len(item_list_from_payload(data))
        self.seeded_at = self.seeded_at or utc_now()
        self.last_synced_at = utc_now()
        self.payload = data
        self.meta = merge_json(self.meta, metadata)
        self.metadata_json = merge_json(self.metadata_json, data.get("metadata") if isinstance(data.get("metadata"), Mapping) else None, metadata)
        self.touch()

    def mark_deprecated(self) -> None:
        self.status = LibraryDefinitionStatus.DEPRECATED.value
        self.active = False
        self.touch()

    def to_dict(self, *, include_payload: bool = True) -> dict[str, Any]:
        result = {
            "id": self.id,
            "dataset_uid": self.dataset_uid,
            "dataset_key": self.dataset_key,
            "schema_version": self.schema_version,
            "definitions_version": self.definitions_version,
            "label": self.label,
            "description": self.description,
            "source_file_path": self.source_file_path,
            "checksum": self.checksum,
            "active": self.active,
            "status": self.status,
            "item_count": self.item_count,
            "seeded_at": self.seeded_at.isoformat() if self.seeded_at else None,
            "last_synced_at": self.last_synced_at.isoformat() if self.last_synced_at else None,
            "created_at": self.created_at.isoformat() if self.created_at else None,
            "updated_at": self.updated_at.isoformat() if self.updated_at else None,
            "meta": normalize_json_mapping(self.meta),
            "metadata": normalize_json_mapping(self.metadata_json),
        }

        if include_payload:
            result["payload"] = normalize_json_mapping(self.payload)

        return result


class LibraryDefinitionSeedRun(TimestampMixin, JsonMixin, db.Model):
    """Ein Seed-/Sync-Lauf für Definitionsdaten aus JSON oder anderer Quelle."""

    __tablename__ = "library_definition_seed_runs"

    id = db.Column(db.BigInteger, primary_key=True, autoincrement=True)

    run_uid = db.Column(db.String(MAX_UID_LENGTH), nullable=False, unique=True, index=True, default=new_uid)

    source_label = db.Column(db.String(MAX_LABEL_LENGTH), nullable=True)
    source_root = db.Column(db.Text, nullable=True)
    triggered_by = db.Column(db.String(MAX_LABEL_LENGTH), nullable=True, index=True)

    schema_version = db.Column(db.String(80), nullable=True)
    definitions_version = db.Column(db.String(80), nullable=True, index=True)

    status = db.Column(
        db.String(MAX_STATUS_LENGTH),
        nullable=False,
        default=LibraryDefinitionSeedStatus.RUNNING.value,
        index=True,
    )

    dataset_count = db.Column(db.Integer, nullable=False, default=0)
    item_count = db.Column(db.Integer, nullable=False, default=0)
    inserted_count = db.Column(db.Integer, nullable=False, default=0)
    updated_count = db.Column(db.Integer, nullable=False, default=0)
    unchanged_count = db.Column(db.Integer, nullable=False, default=0)
    deprecated_count = db.Column(db.Integer, nullable=False, default=0)
    skipped_count = db.Column(db.Integer, nullable=False, default=0)
    warning_count = db.Column(db.Integer, nullable=False, default=0)
    error_count = db.Column(db.Integer, nullable=False, default=0)

    started_at = db.Column(db.DateTime(timezone=True), nullable=False, default=utc_now)
    finished_at = db.Column(db.DateTime(timezone=True), nullable=True)
    duration_ms = db.Column(db.BigInteger, nullable=True)

    summary_json = db.Column(db.JSON, nullable=False, default=dict)
    errors_json = db.Column(db.JSON, nullable=False, default=list)
    payload = db.Column(db.JSON, nullable=False, default=dict)
    meta = db.Column(db.JSON, nullable=False, default=dict)
    metadata_json = db.Column(db.JSON, nullable=False, default=dict)

    __table_args__ = (
        db.Index("ix_library_definition_seed_runs_status_started", "status", "started_at"),
        db.Index("ix_library_definition_seed_runs_version", "definitions_version", "status"),
    )

    def __repr__(self) -> str:
        return f"<LibraryDefinitionSeedRun id={self.id!r} uid={self.run_uid!r} status={self.status!r}>"

    @classmethod
    def start(
        cls,
        *,
        source_label: Any = None,
        source_root: Any = None,
        triggered_by: Any = None,
        definitions_version: Any = DEFAULT_DEFINITIONS_VERSION,
        metadata: Mapping[str, Any] | None = None,
    ) -> "LibraryDefinitionSeedRun":
        return cls(
            run_uid=new_uid(),
            source_label=normalize_optional_string(source_label, max_length=MAX_LABEL_LENGTH),
            source_root=normalize_optional_string(source_root),
            triggered_by=normalize_optional_string(triggered_by, max_length=MAX_LABEL_LENGTH),
            definitions_version=normalize_optional_string(definitions_version, max_length=80) or DEFAULT_DEFINITIONS_VERSION,
            schema_version=DEFAULT_SCHEMA_VERSION,
            status=LibraryDefinitionSeedStatus.RUNNING.value,
            started_at=utc_now(),
            meta=normalize_json_mapping(metadata),
            metadata_json=normalize_json_mapping(metadata),
        )

    def apply_counts(self, counts: Mapping[str, Any] | None) -> None:
        payload = normalize_json_mapping(counts)

        self.dataset_count = normalize_int(payload.get("dataset_count"), default=self.dataset_count, minimum=0) or 0
        self.item_count = normalize_int(payload.get("item_count"), default=self.item_count, minimum=0) or 0
        self.inserted_count = normalize_int(payload.get("inserted_count"), default=self.inserted_count, minimum=0) or 0
        self.updated_count = normalize_int(payload.get("updated_count"), default=self.updated_count, minimum=0) or 0
        self.unchanged_count = normalize_int(payload.get("unchanged_count"), default=self.unchanged_count, minimum=0) or 0
        self.deprecated_count = normalize_int(payload.get("deprecated_count"), default=self.deprecated_count, minimum=0) or 0
        self.skipped_count = normalize_int(payload.get("skipped_count"), default=self.skipped_count, minimum=0) or 0
        self.warning_count = normalize_int(payload.get("warning_count"), default=self.warning_count, minimum=0) or 0
        self.error_count = normalize_int(payload.get("error_count"), default=self.error_count, minimum=0) or 0
        self.touch()

    def finish(
        self,
        *,
        status: Any = LibraryDefinitionSeedStatus.COMPLETED.value,
        summary: Mapping[str, Any] | None = None,
        errors: Iterable[Any] | None = None,
    ) -> None:
        self.finished_at = utc_now()
        self.status = enum_value(status, default=LibraryDefinitionSeedStatus.COMPLETED.value)
        self.summary_json = normalize_json_mapping(summary)
        self.errors_json = normalize_json_list(errors)

        if self.started_at and self.finished_at:
            delta = self.finished_at - self.started_at
            self.duration_ms = int(delta.total_seconds() * 1000)

        self.touch()

    def to_dict(self, *, include_payload: bool = False) -> dict[str, Any]:
        result = {
            "id": self.id,
            "run_uid": self.run_uid,
            "source_label": self.source_label,
            "source_root": self.source_root,
            "triggered_by": self.triggered_by,
            "schema_version": self.schema_version,
            "definitions_version": self.definitions_version,
            "status": self.status,
            "dataset_count": self.dataset_count,
            "item_count": self.item_count,
            "inserted_count": self.inserted_count,
            "updated_count": self.updated_count,
            "unchanged_count": self.unchanged_count,
            "deprecated_count": self.deprecated_count,
            "skipped_count": self.skipped_count,
            "warning_count": self.warning_count,
            "error_count": self.error_count,
            "started_at": self.started_at.isoformat() if self.started_at else None,
            "finished_at": self.finished_at.isoformat() if self.finished_at else None,
            "duration_ms": self.duration_ms,
            "summary": normalize_json_mapping(self.summary_json),
            "errors": normalize_json_list(self.errors_json),
            "meta": normalize_json_mapping(self.meta),
            "metadata": normalize_json_mapping(self.metadata_json),
            "created_at": self.created_at.isoformat() if self.created_at else None,
            "updated_at": self.updated_at.isoformat() if self.updated_at else None,
        }

        if include_payload:
            result["payload"] = normalize_json_mapping(self.payload)

        return result


# ---------------------------------------------------------------------------
# Concrete definition models
# ---------------------------------------------------------------------------

class LibraryDefinitionVariable(DefinitionRecordMixin, db.Model):
    """Variable/Felddefinition für Variant Drawer, Generator und Validierung."""

    __tablename__ = "library_definition_variables"

    dataset_id = db.Column(
        db.BigInteger,
        db.ForeignKey("library_definition_datasets.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )

    variable_key = db.Column(db.String(MAX_KEY_LENGTH), nullable=False, index=True)

    value_type = db.Column(db.String(80), nullable=False, default=LibraryDefinitionValueType.STRING.value, index=True)
    widget = db.Column(db.String(80), nullable=True, index=True)
    unit_id = db.Column(db.String(80), nullable=True, index=True)
    group_key = db.Column(db.String(120), nullable=True, index=True)

    required_default = db.Column(db.Boolean, nullable=False, default=False)
    default_value = db.Column(db.JSON, nullable=True)

    validation_json = db.Column(db.JSON, nullable=False, default=dict)
    options_json = db.Column(db.JSON, nullable=False, default=list)
    applies_to_json = db.Column(db.JSON, nullable=False, default=list)

    quantity_kind = db.Column(db.String(120), nullable=True, index=True)
    references_dataset = db.Column(db.String(120), nullable=True, index=True)
    document_type = db.Column(db.String(120), nullable=True, index=True)
    stored_in = db.Column(db.String(255), nullable=True)

    dataset = db.relationship("LibraryDefinitionDataset", lazy="joined")

    __table_args__ = (
        db.UniqueConstraint("owner_scope", "variable_key", name="uq_library_definition_variable_owner_key"),
        db.Index("ix_library_definition_variables_group_type", "group_key", "value_type"),
        db.Index("ix_library_definition_variables_unit", "unit_id", "quantity_kind"),
        db.Index("ix_library_definition_variables_status_active", "status", "active", "visible"),
    )

    def __repr__(self) -> str:
        return f"<LibraryDefinitionVariable key={self.variable_key!r} type={self.value_type!r}>"

    @classmethod
    def create_from_item(
        cls,
        item: Mapping[str, Any],
        *,
        dataset: LibraryDefinitionDataset | None = None,
        source_scope: Any = LibraryDefinitionSourceScope.SYSTEM.value,
        owner_user_id: Any = None,
        created_by_user_id: Any = None,
    ) -> "LibraryDefinitionVariable":
        obj = cls()
        obj.update_from_item(
            item,
            dataset=dataset,
            source_scope=source_scope,
            owner_user_id=owner_user_id,
            created_by_user_id=created_by_user_id,
        )
        return obj

    def update_from_item(
        self,
        item: Mapping[str, Any],
        *,
        dataset: LibraryDefinitionDataset | None = None,
        source_scope: Any = LibraryDefinitionSourceScope.SYSTEM.value,
        owner_user_id: Any = None,
        created_by_user_id: Any = None,
        updated_by_user_id: Any = None,
    ) -> None:
        data = normalize_json_mapping(item)
        key = definition_key_from_item(data, preferred_keys=("key", "id"), field_name="variable_key")

        apply_common_definition_fields(
            self,
            dataset_key=DATASET_VARIABLES,
            item=data,
            definition_key=key,
            source_scope=source_scope,
            owner_user_id=owner_user_id,
            dataset=dataset,
            created_by_user_id=created_by_user_id,
            updated_by_user_id=updated_by_user_id,
        )

        metadata = normalize_json_mapping(data.get("metadata"))

        self.variable_key = key
        self.value_type = enum_value(data.get("value_type"), default=LibraryDefinitionValueType.STRING.value)
        self.widget = normalize_optional_string(data.get("widget"), max_length=80)
        self.unit_id = normalize_optional_string(data.get("unit"), max_length=80)
        self.group_key = normalize_optional_string(data.get("group"), max_length=120)
        self.required_default = normalize_bool(data.get("required_default"), default=False)
        self.default_value = normalize_json_value(data.get("default_value"))
        self.validation_json = normalize_json_mapping(data.get("validation"))
        self.options_json = normalize_json_list(data.get("options"))
        self.applies_to_json = normalize_json_list(data.get("applies_to"))
        self.quantity_kind = normalize_optional_string(metadata.get("quantity_kind"), max_length=120)
        self.references_dataset = normalize_optional_string(metadata.get("references_dataset"), max_length=120)
        self.document_type = normalize_optional_string(metadata.get("document_type"), max_length=120)
        self.stored_in = normalize_optional_string(metadata.get("stored_in"), max_length=255)
        self.touch()

    def applies_to_profile(self, profile_id: Any) -> bool:
        return list_contains(self.applies_to_json, profile_id)

    def to_dict(self) -> dict[str, Any]:
        result = self.to_common_dict()
        result.update(
            {
                "variable_key": self.variable_key,
                "key": self.variable_key,
                "value_type": self.value_type,
                "widget": self.widget,
                "unit": self.unit_id,
                "unit_id": self.unit_id,
                "group": self.group_key,
                "group_key": self.group_key,
                "required_default": self.required_default,
                "default_value": normalize_json_value(self.default_value),
                "validation": normalize_json_mapping(self.validation_json),
                "options": normalize_json_list(self.options_json),
                "applies_to": normalize_json_list(self.applies_to_json),
                "quantity_kind": self.quantity_kind,
                "references_dataset": self.references_dataset,
                "document_type": self.document_type,
                "stored_in": self.stored_in,
            }
        )
        return result


class LibraryDefinitionUnit(DefinitionRecordMixin, db.Model):
    """Einheitendefinition."""

    __tablename__ = "library_definition_units"

    dataset_id = db.Column(
        db.BigInteger,
        db.ForeignKey("library_definition_datasets.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )

    unit_id = db.Column(db.String(80), nullable=False, index=True)
    symbol = db.Column(db.String(80), nullable=True)
    quantity_kind = db.Column(db.String(120), nullable=True, index=True)
    base_unit = db.Column(db.String(80), nullable=True, index=True)
    conversion_factor_to_base = db.Column(db.Float, nullable=True)
    precision = db.Column(db.Integer, nullable=True)

    dataset = db.relationship("LibraryDefinitionDataset", lazy="joined")

    __table_args__ = (
        db.UniqueConstraint("owner_scope", "unit_id", name="uq_library_definition_unit_owner_key"),
        db.Index("ix_library_definition_units_quantity", "quantity_kind", "base_unit"),
        db.Index("ix_library_definition_units_status_active", "status", "active", "visible"),
    )

    def __repr__(self) -> str:
        return f"<LibraryDefinitionUnit unit_id={self.unit_id!r} symbol={self.symbol!r}>"

    @classmethod
    def create_from_item(
        cls,
        item: Mapping[str, Any],
        *,
        dataset: LibraryDefinitionDataset | None = None,
        source_scope: Any = LibraryDefinitionSourceScope.SYSTEM.value,
        owner_user_id: Any = None,
        created_by_user_id: Any = None,
    ) -> "LibraryDefinitionUnit":
        obj = cls()
        obj.update_from_item(
            item,
            dataset=dataset,
            source_scope=source_scope,
            owner_user_id=owner_user_id,
            created_by_user_id=created_by_user_id,
        )
        return obj

    def update_from_item(
        self,
        item: Mapping[str, Any],
        *,
        dataset: LibraryDefinitionDataset | None = None,
        source_scope: Any = LibraryDefinitionSourceScope.SYSTEM.value,
        owner_user_id: Any = None,
        created_by_user_id: Any = None,
        updated_by_user_id: Any = None,
    ) -> None:
        data = normalize_json_mapping(item)
        key = definition_key_from_item(data, preferred_keys=("id", "key"), field_name="unit_id")

        apply_common_definition_fields(
            self,
            dataset_key=DATASET_UNITS,
            item=data,
            definition_key=key,
            source_scope=source_scope,
            owner_user_id=owner_user_id,
            dataset=dataset,
            created_by_user_id=created_by_user_id,
            updated_by_user_id=updated_by_user_id,
        )

        self.unit_id = key
        self.symbol = normalize_optional_string(data.get("symbol"), max_length=80)
        self.quantity_kind = normalize_optional_string(data.get("quantity_kind"), max_length=120)
        self.base_unit = normalize_optional_string(data.get("base_unit"), max_length=80)
        self.conversion_factor_to_base = normalize_float(data.get("conversion_factor_to_base"), default=None)
        self.precision = normalize_int(data.get("precision"), default=None, minimum=0)
        self.touch()

    def to_dict(self) -> dict[str, Any]:
        result = self.to_common_dict()
        result.update(
            {
                "unit_id": self.unit_id,
                "id": self.unit_id,
                "symbol": self.symbol,
                "quantity_kind": self.quantity_kind,
                "base_unit": self.base_unit,
                "conversion_factor_to_base": self.conversion_factor_to_base,
                "precision": self.precision,
            }
        )
        return result


class LibraryDefinitionMaterial(DefinitionRecordMixin, db.Model):
    """Materialdefinition."""

    __tablename__ = "library_definition_materials"

    dataset_id = db.Column(
        db.BigInteger,
        db.ForeignKey("library_definition_datasets.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )

    material_id = db.Column(db.String(120), nullable=False, index=True)
    parent_material_id = db.Column(db.String(120), nullable=True, index=True)

    compatible_family_profiles_json = db.Column(db.JSON, nullable=False, default=list)
    compatible_variant_profiles_json = db.Column(db.JSON, nullable=False, default=list)
    default_values_json = db.Column(db.JSON, nullable=False, default=dict)
    properties_json = db.Column(db.JSON, nullable=False, default=dict)

    technical_depth = db.Column(db.String(80), nullable=True, index=True)
    supports_product_overlay = db.Column(db.Boolean, nullable=False, default=False)

    dataset = db.relationship("LibraryDefinitionDataset", lazy="joined")

    __table_args__ = (
        db.UniqueConstraint("owner_scope", "material_id", name="uq_library_definition_material_owner_key"),
        db.Index("ix_library_definition_materials_parent", "parent_material_id"),
        db.Index("ix_library_definition_materials_depth", "technical_depth", "supports_product_overlay"),
        db.Index("ix_library_definition_materials_status_active", "status", "active", "visible"),
    )

    def __repr__(self) -> str:
        return f"<LibraryDefinitionMaterial material_id={self.material_id!r}>"

    @classmethod
    def create_from_item(
        cls,
        item: Mapping[str, Any],
        *,
        dataset: LibraryDefinitionDataset | None = None,
        source_scope: Any = LibraryDefinitionSourceScope.SYSTEM.value,
        owner_user_id: Any = None,
        created_by_user_id: Any = None,
    ) -> "LibraryDefinitionMaterial":
        obj = cls()
        obj.update_from_item(
            item,
            dataset=dataset,
            source_scope=source_scope,
            owner_user_id=owner_user_id,
            created_by_user_id=created_by_user_id,
        )
        return obj

    def update_from_item(
        self,
        item: Mapping[str, Any],
        *,
        dataset: LibraryDefinitionDataset | None = None,
        source_scope: Any = LibraryDefinitionSourceScope.SYSTEM.value,
        owner_user_id: Any = None,
        created_by_user_id: Any = None,
        updated_by_user_id: Any = None,
    ) -> None:
        data = normalize_json_mapping(item)
        key = definition_key_from_item(data, preferred_keys=("id", "key"), field_name="material_id")
        properties = normalize_json_mapping(data.get("properties"))

        apply_common_definition_fields(
            self,
            dataset_key=DATASET_MATERIALS,
            item=data,
            definition_key=key,
            source_scope=source_scope,
            owner_user_id=owner_user_id,
            dataset=dataset,
            created_by_user_id=created_by_user_id,
            updated_by_user_id=updated_by_user_id,
        )

        self.material_id = key
        self.parent_material_id = normalize_optional_string(data.get("parent_material_id"), max_length=120)
        self.compatible_family_profiles_json = normalize_json_list(data.get("compatible_family_profiles"))
        self.compatible_variant_profiles_json = normalize_json_list(data.get("compatible_variant_profiles"))
        self.default_values_json = normalize_json_mapping(data.get("default_values"))
        self.properties_json = properties
        self.technical_depth = normalize_optional_string(properties.get("technical_depth"), max_length=80)
        self.supports_product_overlay = normalize_bool(properties.get("supports_product_overlay"), default=False)
        self.touch()

    def compatible_with_variant_profile(self, profile_id: Any) -> bool:
        return list_contains(self.compatible_variant_profiles_json, profile_id)

    def to_dict(self) -> dict[str, Any]:
        result = self.to_common_dict()
        result.update(
            {
                "material_id": self.material_id,
                "id": self.material_id,
                "parent_material_id": self.parent_material_id,
                "compatible_family_profiles": normalize_json_list(self.compatible_family_profiles_json),
                "compatible_variant_profiles": normalize_json_list(self.compatible_variant_profiles_json),
                "default_values": normalize_json_mapping(self.default_values_json),
                "properties": normalize_json_mapping(self.properties_json),
                "technical_depth": self.technical_depth,
                "supports_product_overlay": self.supports_product_overlay,
            }
        )
        return result


class LibraryDefinitionDocumentType(DefinitionRecordMixin, db.Model):
    """Dokument-/Uploadtyp inklusive Dateiregeln."""

    __tablename__ = "library_definition_document_types"

    dataset_id = db.Column(
        db.BigInteger,
        db.ForeignKey("library_definition_datasets.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )

    document_type_id = db.Column(db.String(120), nullable=False, index=True)

    allowed_mime_types_json = db.Column(db.JSON, nullable=False, default=list)
    allowed_extensions_json = db.Column(db.JSON, nullable=False, default=list)
    required_for_profiles_json = db.Column(db.JSON, nullable=False, default=list)

    max_size_mb = db.Column(db.Float, nullable=True)
    multiple = db.Column(db.Boolean, nullable=False, default=True)
    upload_group = db.Column(db.String(120), nullable=True, index=True)

    can_be_preview_asset = db.Column(db.Boolean, nullable=False, default=False)
    can_be_render_asset = db.Column(db.Boolean, nullable=False, default=False)
    runtime_artifact = db.Column(db.Boolean, nullable=False, default=False)
    future_overlay_ready = db.Column(db.Boolean, nullable=False, default=False)

    dataset = db.relationship("LibraryDefinitionDataset", lazy="joined")

    __table_args__ = (
        db.UniqueConstraint("owner_scope", "document_type_id", name="uq_library_definition_document_type_owner_key"),
        db.Index("ix_library_definition_document_types_upload_group", "upload_group"),
        db.Index("ix_library_definition_document_types_asset_flags", "can_be_preview_asset", "can_be_render_asset"),
        db.Index("ix_library_definition_document_types_status_active", "status", "active", "visible"),
    )

    def __repr__(self) -> str:
        return f"<LibraryDefinitionDocumentType document_type_id={self.document_type_id!r}>"

    @classmethod
    def create_from_item(
        cls,
        item: Mapping[str, Any],
        *,
        dataset: LibraryDefinitionDataset | None = None,
        source_scope: Any = LibraryDefinitionSourceScope.SYSTEM.value,
        owner_user_id: Any = None,
        created_by_user_id: Any = None,
    ) -> "LibraryDefinitionDocumentType":
        obj = cls()
        obj.update_from_item(
            item,
            dataset=dataset,
            source_scope=source_scope,
            owner_user_id=owner_user_id,
            created_by_user_id=created_by_user_id,
        )
        return obj

    def update_from_item(
        self,
        item: Mapping[str, Any],
        *,
        dataset: LibraryDefinitionDataset | None = None,
        source_scope: Any = LibraryDefinitionSourceScope.SYSTEM.value,
        owner_user_id: Any = None,
        created_by_user_id: Any = None,
        updated_by_user_id: Any = None,
    ) -> None:
        data = normalize_json_mapping(item)
        key = definition_key_from_item(data, preferred_keys=("id", "key"), field_name="document_type_id")
        ui = normalize_json_mapping(data.get("ui"))
        metadata = normalize_json_mapping(data.get("metadata"))

        apply_common_definition_fields(
            self,
            dataset_key=DATASET_DOCUMENT_TYPES,
            item=data,
            definition_key=key,
            source_scope=source_scope,
            owner_user_id=owner_user_id,
            dataset=dataset,
            created_by_user_id=created_by_user_id,
            updated_by_user_id=updated_by_user_id,
        )

        self.document_type_id = key
        self.allowed_mime_types_json = normalize_json_list(data.get("allowed_mime_types"))
        self.allowed_extensions_json = normalize_json_list(data.get("allowed_extensions"))
        self.required_for_profiles_json = normalize_json_list(data.get("required_for_profiles"))
        self.max_size_mb = normalize_float(data.get("max_size_mb"), default=None, minimum=0)
        self.multiple = normalize_bool(data.get("multiple"), default=True)
        self.upload_group = normalize_optional_string(ui.get("group"), max_length=120)
        self.can_be_preview_asset = normalize_bool(metadata.get("can_be_preview_asset"), default=False)
        self.can_be_render_asset = normalize_bool(metadata.get("can_be_render_asset"), default=False)
        self.runtime_artifact = normalize_bool(metadata.get("runtime_artifact"), default=False)
        self.future_overlay_ready = normalize_bool(metadata.get("future_overlay_ready"), default=False)
        self.touch()

    def allows_extension(self, extension: Any) -> bool:
        ext = clean_string(extension).lower()
        if not ext:
            return False

        if not ext.startswith("."):
            ext = f".{ext}"

        return list_contains(self.allowed_extensions_json, ext)

    def allows_mime_type(self, mime_type: Any) -> bool:
        mime = clean_string(mime_type).lower()
        if not mime:
            return False

        return list_contains(self.allowed_mime_types_json, mime)

    def to_dict(self) -> dict[str, Any]:
        result = self.to_common_dict()
        result.update(
            {
                "document_type_id": self.document_type_id,
                "id": self.document_type_id,
                "allowed_mime_types": normalize_json_list(self.allowed_mime_types_json),
                "allowed_extensions": normalize_json_list(self.allowed_extensions_json),
                "required_for_profiles": normalize_json_list(self.required_for_profiles_json),
                "max_size_mb": self.max_size_mb,
                "multiple": self.multiple,
                "upload_group": self.upload_group,
                "can_be_preview_asset": self.can_be_preview_asset,
                "can_be_render_asset": self.can_be_render_asset,
                "runtime_artifact": self.runtime_artifact,
                "future_overlay_ready": self.future_overlay_ready,
            }
        )
        return result


class LibraryDefinitionObjectKind(DefinitionRecordMixin, db.Model):
    """UI-/Profile-Metadata für technische VPLIB object_kinds."""

    __tablename__ = "library_definition_object_kinds"

    dataset_id = db.Column(
        db.BigInteger,
        db.ForeignKey("library_definition_datasets.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )

    object_kind_id = db.Column(db.String(120), nullable=False, index=True)

    allowed_family_profiles_json = db.Column(db.JSON, nullable=False, default=list)
    default_family_profile_id = db.Column(db.String(160), nullable=True, index=True)
    default_variant_profile_id = db.Column(db.String(160), nullable=True, index=True)
    default_modules_json = db.Column(db.JSON, nullable=False, default=dict)
    geometry_rules_json = db.Column(db.JSON, nullable=False, default=dict)
    preview_behavior_json = db.Column(db.JSON, nullable=False, default=dict)
    technical_truth = db.Column(db.String(255), nullable=True)

    dataset = db.relationship("LibraryDefinitionDataset", lazy="joined")

    __table_args__ = (
        db.UniqueConstraint("owner_scope", "object_kind_id", name="uq_library_definition_object_kind_owner_key"),
        db.Index("ix_library_definition_object_kinds_defaults", "default_family_profile_id", "default_variant_profile_id"),
        db.Index("ix_library_definition_object_kinds_status_active", "status", "active", "visible"),
    )

    def __repr__(self) -> str:
        return f"<LibraryDefinitionObjectKind object_kind_id={self.object_kind_id!r}>"

    @classmethod
    def create_from_item(
        cls,
        item: Mapping[str, Any],
        *,
        dataset: LibraryDefinitionDataset | None = None,
        source_scope: Any = LibraryDefinitionSourceScope.SYSTEM.value,
        owner_user_id: Any = None,
        created_by_user_id: Any = None,
    ) -> "LibraryDefinitionObjectKind":
        obj = cls()
        obj.update_from_item(
            item,
            dataset=dataset,
            source_scope=source_scope,
            owner_user_id=owner_user_id,
            created_by_user_id=created_by_user_id,
        )
        return obj

    def update_from_item(
        self,
        item: Mapping[str, Any],
        *,
        dataset: LibraryDefinitionDataset | None = None,
        source_scope: Any = LibraryDefinitionSourceScope.SYSTEM.value,
        owner_user_id: Any = None,
        created_by_user_id: Any = None,
        updated_by_user_id: Any = None,
    ) -> None:
        data = normalize_json_mapping(item)
        key = definition_key_from_item(data, preferred_keys=("id", "key"), field_name="object_kind_id")
        metadata = normalize_json_mapping(data.get("metadata"))

        apply_common_definition_fields(
            self,
            dataset_key=DATASET_OBJECT_KINDS,
            item=data,
            definition_key=key,
            source_scope=source_scope,
            owner_user_id=owner_user_id,
            dataset=dataset,
            created_by_user_id=created_by_user_id,
            updated_by_user_id=updated_by_user_id,
        )

        self.object_kind_id = key
        self.allowed_family_profiles_json = normalize_json_list(data.get("allowed_family_profiles"))
        self.default_family_profile_id = normalize_optional_string(data.get("default_family_profile_id"), max_length=160)
        self.default_variant_profile_id = normalize_optional_string(data.get("default_variant_profile_id"), max_length=160)
        self.default_modules_json = normalize_json_mapping(data.get("default_modules"))
        self.geometry_rules_json = normalize_json_mapping(data.get("geometry_rules"))
        self.preview_behavior_json = normalize_json_mapping(data.get("preview_behavior"))
        self.technical_truth = normalize_optional_string(metadata.get("technical_truth"), max_length=255)
        self.touch()

    def to_dict(self) -> dict[str, Any]:
        result = self.to_common_dict()
        result.update(
            {
                "object_kind_id": self.object_kind_id,
                "id": self.object_kind_id,
                "allowed_family_profiles": normalize_json_list(self.allowed_family_profiles_json),
                "default_family_profile_id": self.default_family_profile_id,
                "default_variant_profile_id": self.default_variant_profile_id,
                "default_modules": normalize_json_mapping(self.default_modules_json),
                "geometry_rules": normalize_json_mapping(self.geometry_rules_json),
                "preview_behavior": normalize_json_mapping(self.preview_behavior_json),
                "technical_truth": self.technical_truth,
            }
        )
        return result


class LibraryDefinitionFamilyProfile(DefinitionRecordMixin, db.Model):
    """Fachliches Family-Profil."""

    __tablename__ = "library_definition_family_profiles"

    dataset_id = db.Column(
        db.BigInteger,
        db.ForeignKey("library_definition_datasets.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )

    family_profile_id = db.Column(db.String(160), nullable=False, index=True)

    object_kinds_json = db.Column(db.JSON, nullable=False, default=list)
    taxonomy_domains_json = db.Column(db.JSON, nullable=False, default=list)
    taxonomy_categories_json = db.Column(db.JSON, nullable=False, default=list)
    taxonomy_subcategories_json = db.Column(db.JSON, nullable=False, default=list)

    allowed_variant_profiles_json = db.Column(db.JSON, nullable=False, default=list)
    default_variant_profile_id = db.Column(db.String(160), nullable=True, index=True)

    required_modules_json = db.Column(db.JSON, nullable=False, default=list)
    optional_modules_json = db.Column(db.JSON, nullable=False, default=list)
    default_modules_json = db.Column(db.JSON, nullable=False, default=dict)

    supports_product_like_variants = db.Column(db.Boolean, nullable=False, default=False)
    future_overlay_ready = db.Column(db.Boolean, nullable=False, default=False)

    dataset = db.relationship("LibraryDefinitionDataset", lazy="joined")

    __table_args__ = (
        db.UniqueConstraint("owner_scope", "family_profile_id", name="uq_library_definition_family_profile_owner_key"),
        db.Index("ix_library_definition_family_profiles_default_variant", "default_variant_profile_id"),
        db.Index("ix_library_definition_family_profiles_status_active", "status", "active", "visible"),
    )

    def __repr__(self) -> str:
        return f"<LibraryDefinitionFamilyProfile family_profile_id={self.family_profile_id!r}>"

    @classmethod
    def create_from_item(
        cls,
        item: Mapping[str, Any],
        *,
        dataset: LibraryDefinitionDataset | None = None,
        source_scope: Any = LibraryDefinitionSourceScope.SYSTEM.value,
        owner_user_id: Any = None,
        created_by_user_id: Any = None,
    ) -> "LibraryDefinitionFamilyProfile":
        obj = cls()
        obj.update_from_item(
            item,
            dataset=dataset,
            source_scope=source_scope,
            owner_user_id=owner_user_id,
            created_by_user_id=created_by_user_id,
        )
        return obj

    def update_from_item(
        self,
        item: Mapping[str, Any],
        *,
        dataset: LibraryDefinitionDataset | None = None,
        source_scope: Any = LibraryDefinitionSourceScope.SYSTEM.value,
        owner_user_id: Any = None,
        created_by_user_id: Any = None,
        updated_by_user_id: Any = None,
    ) -> None:
        data = normalize_json_mapping(item)
        key = definition_key_from_item(data, preferred_keys=("id", "key"), field_name="family_profile_id")
        metadata = normalize_json_mapping(data.get("metadata"))

        apply_common_definition_fields(
            self,
            dataset_key=DATASET_FAMILY_PROFILES,
            item=data,
            definition_key=key,
            source_scope=source_scope,
            owner_user_id=owner_user_id,
            dataset=dataset,
            created_by_user_id=created_by_user_id,
            updated_by_user_id=updated_by_user_id,
        )

        self.family_profile_id = key
        self.object_kinds_json = normalize_json_list(data.get("object_kinds"))
        self.taxonomy_domains_json = normalize_json_list(data.get("taxonomy_domains"))
        self.taxonomy_categories_json = normalize_json_list(data.get("taxonomy_categories"))
        self.taxonomy_subcategories_json = normalize_json_list(data.get("taxonomy_subcategories"))
        self.allowed_variant_profiles_json = normalize_json_list(data.get("allowed_variant_profiles"))
        self.default_variant_profile_id = normalize_optional_string(data.get("default_variant_profile_id"), max_length=160)
        self.required_modules_json = normalize_json_list(data.get("required_modules"))
        self.optional_modules_json = normalize_json_list(data.get("optional_modules"))
        self.default_modules_json = normalize_json_mapping(data.get("default_modules"))
        self.supports_product_like_variants = normalize_bool(metadata.get("supports_product_like_variants"), default=False)
        self.future_overlay_ready = normalize_bool(metadata.get("future_overlay_ready"), default=False)
        self.touch()

    def allows_variant_profile(self, profile_id: Any) -> bool:
        return list_contains(self.allowed_variant_profiles_json, profile_id)

    def to_dict(self) -> dict[str, Any]:
        result = self.to_common_dict()
        result.update(
            {
                "family_profile_id": self.family_profile_id,
                "id": self.family_profile_id,
                "object_kinds": normalize_json_list(self.object_kinds_json),
                "taxonomy_domains": normalize_json_list(self.taxonomy_domains_json),
                "taxonomy_categories": normalize_json_list(self.taxonomy_categories_json),
                "taxonomy_subcategories": normalize_json_list(self.taxonomy_subcategories_json),
                "allowed_variant_profiles": normalize_json_list(self.allowed_variant_profiles_json),
                "default_variant_profile_id": self.default_variant_profile_id,
                "required_modules": normalize_json_list(self.required_modules_json),
                "optional_modules": normalize_json_list(self.optional_modules_json),
                "default_modules": normalize_json_mapping(self.default_modules_json),
                "supports_product_like_variants": self.supports_product_like_variants,
                "future_overlay_ready": self.future_overlay_ready,
            }
        )
        return result


class LibraryDefinitionVariantProfile(DefinitionRecordMixin, db.Model):
    """Variant-Drawer-/Variant-Feldprofil."""

    __tablename__ = "library_definition_variant_profiles"

    dataset_id = db.Column(
        db.BigInteger,
        db.ForeignKey("library_definition_datasets.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )

    variant_profile_id = db.Column(db.String(160), nullable=False, index=True)

    family_profiles_json = db.Column(db.JSON, nullable=False, default=list)
    object_kinds_json = db.Column(db.JSON, nullable=False, default=list)

    sections_json = db.Column(db.JSON, nullable=False, default=list)
    required_fields_json = db.Column(db.JSON, nullable=False, default=list)
    optional_fields_json = db.Column(db.JSON, nullable=False, default=list)
    summary_fields_json = db.Column(db.JSON, nullable=False, default=list)
    default_values_json = db.Column(db.JSON, nullable=False, default=dict)
    document_types_json = db.Column(db.JSON, nullable=False, default=list)

    manufacturer_mode = db.Column(db.String(80), nullable=True, index=True)
    drawer_size = db.Column(db.String(80), nullable=True)
    preview_mode = db.Column(db.String(120), nullable=True, index=True)

    supports_product_like_variants = db.Column(db.Boolean, nullable=False, default=False)
    future_overlay_ready = db.Column(db.Boolean, nullable=False, default=False)

    dataset = db.relationship("LibraryDefinitionDataset", lazy="joined")

    __table_args__ = (
        db.UniqueConstraint("owner_scope", "variant_profile_id", name="uq_library_definition_variant_profile_owner_key"),
        db.Index("ix_library_definition_variant_profiles_mode", "manufacturer_mode", "preview_mode"),
        db.Index("ix_library_definition_variant_profiles_status_active", "status", "active", "visible"),
    )

    def __repr__(self) -> str:
        return f"<LibraryDefinitionVariantProfile variant_profile_id={self.variant_profile_id!r}>"

    @classmethod
    def create_from_item(
        cls,
        item: Mapping[str, Any],
        *,
        dataset: LibraryDefinitionDataset | None = None,
        source_scope: Any = LibraryDefinitionSourceScope.SYSTEM.value,
        owner_user_id: Any = None,
        created_by_user_id: Any = None,
    ) -> "LibraryDefinitionVariantProfile":
        obj = cls()
        obj.update_from_item(
            item,
            dataset=dataset,
            source_scope=source_scope,
            owner_user_id=owner_user_id,
            created_by_user_id=created_by_user_id,
        )
        return obj

    def update_from_item(
        self,
        item: Mapping[str, Any],
        *,
        dataset: LibraryDefinitionDataset | None = None,
        source_scope: Any = LibraryDefinitionSourceScope.SYSTEM.value,
        owner_user_id: Any = None,
        created_by_user_id: Any = None,
        updated_by_user_id: Any = None,
    ) -> None:
        data = normalize_json_mapping(item)
        key = definition_key_from_item(data, preferred_keys=("id", "key"), field_name="variant_profile_id")
        ui = normalize_json_mapping(data.get("ui"))
        drawer = normalize_json_mapping(ui.get("drawer"))
        metadata = normalize_json_mapping(data.get("metadata"))

        apply_common_definition_fields(
            self,
            dataset_key=DATASET_VARIANT_PROFILES,
            item=data,
            definition_key=key,
            source_scope=source_scope,
            owner_user_id=owner_user_id,
            dataset=dataset,
            created_by_user_id=created_by_user_id,
            updated_by_user_id=updated_by_user_id,
        )

        self.variant_profile_id = key
        self.family_profiles_json = normalize_json_list(data.get("family_profiles"))
        self.object_kinds_json = normalize_json_list(data.get("object_kinds"))
        self.sections_json = normalize_json_list(data.get("sections"))
        self.required_fields_json = normalize_json_list(data.get("required_fields"))
        self.optional_fields_json = normalize_json_list(data.get("optional_fields"))
        self.summary_fields_json = normalize_json_list(data.get("summary_fields"))
        self.default_values_json = normalize_json_mapping(data.get("default_values"))
        self.document_types_json = normalize_json_list(data.get("document_types"))
        self.manufacturer_mode = normalize_optional_string(data.get("manufacturer_mode"), max_length=80)
        self.drawer_size = normalize_optional_string(drawer.get("size"), max_length=80)
        self.preview_mode = normalize_optional_string(drawer.get("preview_mode"), max_length=120)
        self.supports_product_like_variants = normalize_bool(metadata.get("supports_product_like_variants"), default=False)
        self.future_overlay_ready = normalize_bool(metadata.get("future_overlay_ready"), default=False)
        self.touch()

    def field_keys(self) -> tuple[str, ...]:
        keys: list[str] = []

        for section in normalize_json_list(self.sections_json):
            if not isinstance(section, Mapping):
                continue

            for field_key in normalize_json_list(section.get("fields")):
                text = normalize_optional_string(field_key, max_length=MAX_KEY_LENGTH)
                if text and text not in keys:
                    keys.append(text)

        for field_key in normalize_json_list(self.required_fields_json):
            text = normalize_optional_string(field_key, max_length=MAX_KEY_LENGTH)
            if text and text not in keys:
                keys.append(text)

        for field_key in normalize_json_list(self.optional_fields_json):
            text = normalize_optional_string(field_key, max_length=MAX_KEY_LENGTH)
            if text and text not in keys:
                keys.append(text)

        return tuple(keys)

    def has_field(self, field_key: Any) -> bool:
        text = normalize_optional_string(field_key, max_length=MAX_KEY_LENGTH)
        return bool(text and text in self.field_keys())

    def to_dict(self) -> dict[str, Any]:
        result = self.to_common_dict()
        result.update(
            {
                "variant_profile_id": self.variant_profile_id,
                "id": self.variant_profile_id,
                "family_profiles": normalize_json_list(self.family_profiles_json),
                "object_kinds": normalize_json_list(self.object_kinds_json),
                "sections": normalize_json_list(self.sections_json),
                "required_fields": normalize_json_list(self.required_fields_json),
                "optional_fields": normalize_json_list(self.optional_fields_json),
                "summary_fields": normalize_json_list(self.summary_fields_json),
                "default_values": normalize_json_mapping(self.default_values_json),
                "document_types": normalize_json_list(self.document_types_json),
                "manufacturer_mode": self.manufacturer_mode,
                "drawer_size": self.drawer_size,
                "preview_mode": self.preview_mode,
                "field_keys": list(self.field_keys()),
                "supports_product_like_variants": self.supports_product_like_variants,
                "future_overlay_ready": self.future_overlay_ready,
            }
        )
        return result


class LibraryDefinitionProfileBinding(DefinitionRecordMixin, db.Model):
    """Binding zwischen Taxonomie, object_kind, family_profile und variant_profile."""

    __tablename__ = "library_definition_profile_bindings"

    dataset_id = db.Column(
        db.BigInteger,
        db.ForeignKey("library_definition_datasets.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )

    binding_id = db.Column(db.String(MAX_KEY_LENGTH), nullable=False, index=True)

    priority = db.Column(db.Integer, nullable=False, default=1000, index=True)

    domain = db.Column(db.String(80), nullable=True, index=True)
    category = db.Column(db.String(120), nullable=True, index=True)
    subcategory = db.Column(db.String(120), nullable=True, index=True)
    taxonomy_path = db.Column(db.String(512), nullable=True, index=True)

    object_kind = db.Column(db.String(120), nullable=True, index=True)
    family_profile_id = db.Column(db.String(160), nullable=True, index=True)
    variant_profile_id = db.Column(db.String(160), nullable=True, index=True)

    match_json = db.Column(db.JSON, nullable=False, default=dict)

    supports_legacy_source_layout = db.Column(db.Boolean, nullable=False, default=False)
    supports_product_like_variants = db.Column(db.Boolean, nullable=False, default=False)
    fallback_binding = db.Column(db.Boolean, nullable=False, default=False)
    alias_binding = db.Column(db.Boolean, nullable=False, default=False)

    dataset = db.relationship("LibraryDefinitionDataset", lazy="joined")

    __table_args__ = (
        db.UniqueConstraint("owner_scope", "binding_id", name="uq_library_definition_profile_binding_owner_key"),
        db.Index("ix_library_definition_profile_bindings_taxonomy", "domain", "category", "subcategory"),
        db.Index("ix_library_definition_profile_bindings_lookup", "object_kind", "domain", "category", "subcategory"),
        db.Index("ix_library_definition_profile_bindings_profiles", "family_profile_id", "variant_profile_id"),
        db.Index("ix_library_definition_profile_bindings_priority", "priority", "active"),
    )

    def __repr__(self) -> str:
        return f"<LibraryDefinitionProfileBinding binding_id={self.binding_id!r} priority={self.priority!r}>"

    @classmethod
    def create_from_item(
        cls,
        item: Mapping[str, Any],
        *,
        dataset: LibraryDefinitionDataset | None = None,
        source_scope: Any = LibraryDefinitionSourceScope.SYSTEM.value,
        owner_user_id: Any = None,
        created_by_user_id: Any = None,
    ) -> "LibraryDefinitionProfileBinding":
        obj = cls()
        obj.update_from_item(
            item,
            dataset=dataset,
            source_scope=source_scope,
            owner_user_id=owner_user_id,
            created_by_user_id=created_by_user_id,
        )
        return obj

    def update_from_item(
        self,
        item: Mapping[str, Any],
        *,
        dataset: LibraryDefinitionDataset | None = None,
        source_scope: Any = LibraryDefinitionSourceScope.SYSTEM.value,
        owner_user_id: Any = None,
        created_by_user_id: Any = None,
        updated_by_user_id: Any = None,
    ) -> None:
        data = normalize_json_mapping(item)
        key = definition_key_from_item(data, preferred_keys=("id", "key"), field_name="binding_id")
        match = normalize_json_mapping(data.get("match"))
        metadata = normalize_json_mapping(data.get("metadata"))

        domain = normalize_optional_string(data.get("domain"), max_length=80)
        category = normalize_optional_string(data.get("category"), max_length=120)
        subcategory = normalize_optional_string(data.get("subcategory"), max_length=120)
        taxonomy_path = "/".join(part for part in (domain, category, subcategory) if part) or None

        apply_common_definition_fields(
            self,
            dataset_key=DATASET_PROFILE_BINDINGS,
            item=data,
            definition_key=key,
            source_scope=source_scope,
            owner_user_id=owner_user_id,
            dataset=dataset,
            created_by_user_id=created_by_user_id,
            updated_by_user_id=updated_by_user_id,
        )

        self.binding_id = key
        self.priority = normalize_int(data.get("priority"), default=1000, minimum=0) or 1000
        self.domain = domain
        self.category = category
        self.subcategory = subcategory
        self.taxonomy_path = taxonomy_path
        self.object_kind = normalize_optional_string(data.get("object_kind"), max_length=120)
        self.family_profile_id = normalize_optional_string(data.get("family_profile_id"), max_length=160)
        self.variant_profile_id = normalize_optional_string(data.get("variant_profile_id"), max_length=160)
        self.match_json = match
        self.supports_legacy_source_layout = normalize_bool(match.get("supports_legacy_source_layout"), default=False)
        self.supports_product_like_variants = normalize_bool(
            first_non_empty(match.get("supports_product_like_variants"), metadata.get("supports_product_like_variants")),
            default=False,
        )
        self.fallback_binding = normalize_bool(metadata.get("fallback"), default=False) or "fallback" in clean_string(match.get("strategy")).lower()
        self.alias_binding = normalize_bool(metadata.get("alias_binding"), default=False) or bool(match.get("alias_for"))
        self.touch()

    def matches_context(
        self,
        *,
        domain: Any = None,
        category: Any = None,
        subcategory: Any = None,
        object_kind: Any = None,
    ) -> bool:
        """
        Prüft, ob dieses Binding auf einen Kontext passt.

        None im Binding bedeutet Wildcard.
        """

        checks = (
            (self.domain, normalize_optional_string(domain, max_length=80)),
            (self.category, normalize_optional_string(category, max_length=120)),
            (self.subcategory, normalize_optional_string(subcategory, max_length=120)),
            (self.object_kind, normalize_optional_string(object_kind, max_length=120)),
        )

        for expected, actual in checks:
            if expected is None:
                continue
            if expected != actual:
                return False

        return True

    def to_dict(self) -> dict[str, Any]:
        result = self.to_common_dict()
        result.update(
            {
                "binding_id": self.binding_id,
                "id": self.binding_id,
                "priority": self.priority,
                "domain": self.domain,
                "category": self.category,
                "subcategory": self.subcategory,
                "taxonomy_path": self.taxonomy_path,
                "object_kind": self.object_kind,
                "family_profile_id": self.family_profile_id,
                "variant_profile_id": self.variant_profile_id,
                "match": normalize_json_mapping(self.match_json),
                "supports_legacy_source_layout": self.supports_legacy_source_layout,
                "supports_product_like_variants": self.supports_product_like_variants,
                "fallback_binding": self.fallback_binding,
                "alias_binding": self.alias_binding,
            }
        )
        return result


class LibraryDefinitionOverride(TimestampMixin, JsonMixin, db.Model):
    """
    User-/Scope-spezifischer Override auf eine Definition.

    Beispiele:

    - User blendet eine Systemvariable aus.
    - User benennt einen Dokumenttyp für seine UI um.
    - User überschreibt Sortierung eines Variant-Profile-Abschnitts.
    - User patched UI-Metadata, ohne die Systemdefinition zu verändern.
    """

    __tablename__ = "library_definition_overrides"

    id = db.Column(db.BigInteger, primary_key=True, autoincrement=True)

    override_uid = db.Column(db.String(MAX_UID_LENGTH), nullable=False, unique=True, index=True, default=new_uid)

    user_id = db.Column(db.BigInteger, nullable=False, default=DEFAULT_USER_ID, index=True)
    owner_scope = db.Column(db.String(MAX_OWNER_SCOPE_LENGTH), nullable=False, default=f"user:{DEFAULT_USER_ID}", index=True)

    dataset_key = db.Column(db.String(MAX_DATASET_KEY_LENGTH), nullable=False, index=True)
    target_definition_uid = db.Column(db.String(MAX_UID_LENGTH), nullable=True, index=True)
    target_key = db.Column(db.String(MAX_KEY_LENGTH), nullable=False, index=True)
    target_type = db.Column(db.String(120), nullable=True, index=True)

    override_action = db.Column(
        db.String(80),
        nullable=False,
        default=LibraryDefinitionOverrideAction.PATCH.value,
        index=True,
    )
    status = db.Column(
        db.String(MAX_STATUS_LENGTH),
        nullable=False,
        default=LibraryDefinitionStatus.ACTIVE.value,
        index=True,
    )

    active = db.Column(db.Boolean, nullable=False, default=True, index=True)
    visible_override = db.Column(db.Boolean, nullable=True)
    active_override = db.Column(db.Boolean, nullable=True)

    label_override = db.Column(db.String(MAX_LABEL_LENGTH), nullable=True)
    description_override = db.Column(db.Text, nullable=True)
    sort_order_override = db.Column(db.Integer, nullable=True)

    payload_patch = db.Column(db.JSON, nullable=False, default=dict)
    value_override_json = db.Column(db.JSON, nullable=False, default=dict)
    before_json = db.Column(db.JSON, nullable=False, default=dict)
    after_json = db.Column(db.JSON, nullable=False, default=dict)

    meta = db.Column(db.JSON, nullable=False, default=dict)
    metadata_json = db.Column(db.JSON, nullable=False, default=dict)

    created_by_user_id = db.Column(db.BigInteger, nullable=True, index=True)
    updated_by_user_id = db.Column(db.BigInteger, nullable=True, index=True)
    deleted_at = db.Column(db.DateTime(timezone=True), nullable=True)

    __table_args__ = (
        db.UniqueConstraint("user_id", "dataset_key", "target_key", name="uq_library_definition_override_user_dataset_target"),
        db.Index("ix_library_definition_overrides_lookup", "user_id", "dataset_key", "target_key", "active"),
        db.Index("ix_library_definition_overrides_action", "override_action", "status"),
    )

    def __repr__(self) -> str:
        return f"<LibraryDefinitionOverride user_id={self.user_id!r} dataset={self.dataset_key!r} target={self.target_key!r}>"

    @classmethod
    def create_from_payload(
        cls,
        payload: Mapping[str, Any],
        *,
        user_id: Any = DEFAULT_USER_ID,
        created_by_user_id: Any = None,
    ) -> "LibraryDefinitionOverride":
        data = normalize_json_mapping(payload)
        normalized_user_id = normalize_user_id(first_non_empty(user_id, data.get("user_id")), default=DEFAULT_USER_ID) or DEFAULT_USER_ID
        dataset_key = clean_dataset_key(data.get("dataset_key") or data.get("dataset"))
        target_key = normalize_key(first_non_empty(data.get("target_key"), data.get("definition_key"), data.get("key")), field_name="target_key")

        return cls(
            override_uid=normalize_optional_string(data.get("override_uid"), max_length=MAX_UID_LENGTH) or new_uid(),
            user_id=normalized_user_id,
            owner_scope=f"user:{normalized_user_id}",
            dataset_key=dataset_key,
            target_definition_uid=normalize_optional_string(data.get("target_definition_uid"), max_length=MAX_UID_LENGTH),
            target_key=target_key,
            target_type=normalize_optional_string(data.get("target_type"), max_length=120),
            override_action=enum_value(data.get("override_action") or data.get("action"), default=LibraryDefinitionOverrideAction.PATCH.value),
            status=normalize_status(data.get("status"), default=LibraryDefinitionStatus.ACTIVE.value),
            active=normalize_bool(data.get("active"), default=True),
            visible_override=data.get("visible_override") if isinstance(data.get("visible_override"), bool) else None,
            active_override=data.get("active_override") if isinstance(data.get("active_override"), bool) else None,
            label_override=normalize_optional_string(data.get("label_override") or data.get("label"), max_length=MAX_LABEL_LENGTH),
            description_override=normalize_optional_string(data.get("description_override") or data.get("description")),
            sort_order_override=normalize_int(data.get("sort_order_override") or data.get("sort_order"), default=None, minimum=0),
            payload_patch=normalize_json_mapping(data.get("payload_patch") or data.get("patch")),
            value_override_json=normalize_json_mapping(data.get("value_override") or data.get("value")),
            before_json=normalize_json_mapping(data.get("before")),
            after_json=normalize_json_mapping(data.get("after")),
            meta=normalize_json_mapping(data.get("meta")),
            metadata_json=normalize_json_mapping(data.get("metadata")),
            created_by_user_id=normalize_user_id(created_by_user_id, default=None),
            updated_by_user_id=normalize_user_id(created_by_user_id, default=None),
        )

    def mark_deleted(self, *, user_id: Any = None) -> None:
        self.active = False
        self.status = LibraryDefinitionStatus.DELETED.value
        self.deleted_at = utc_now()
        updater_id = normalize_user_id(user_id, default=None)
        if updater_id is not None:
            self.updated_by_user_id = updater_id
        self.touch()

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "override_uid": self.override_uid,
            "user_id": self.user_id,
            "owner_scope": self.owner_scope,
            "dataset_key": self.dataset_key,
            "target_definition_uid": self.target_definition_uid,
            "target_key": self.target_key,
            "target_type": self.target_type,
            "override_action": self.override_action,
            "status": self.status,
            "active": self.active,
            "visible_override": self.visible_override,
            "active_override": self.active_override,
            "label_override": self.label_override,
            "description_override": self.description_override,
            "sort_order_override": self.sort_order_override,
            "payload_patch": normalize_json_mapping(self.payload_patch),
            "value_override": normalize_json_mapping(self.value_override_json),
            "before": normalize_json_mapping(self.before_json),
            "after": normalize_json_mapping(self.after_json),
            "meta": normalize_json_mapping(self.meta),
            "metadata": normalize_json_mapping(self.metadata_json),
            "created_by_user_id": self.created_by_user_id,
            "updated_by_user_id": self.updated_by_user_id,
            "deleted_at": self.deleted_at.isoformat() if self.deleted_at else None,
            "created_at": self.created_at.isoformat() if self.created_at else None,
            "updated_at": self.updated_at.isoformat() if self.updated_at else None,
        }


# ---------------------------------------------------------------------------
# Factory helpers
# ---------------------------------------------------------------------------

MODEL_BY_DATASET_KEY: Final[dict[str, str]] = {
    DATASET_VARIABLES: "LibraryDefinitionVariable",
    DATASET_UNITS: "LibraryDefinitionUnit",
    DATASET_MATERIALS: "LibraryDefinitionMaterial",
    DATASET_DOCUMENT_TYPES: "LibraryDefinitionDocumentType",
    DATASET_OBJECT_KINDS: "LibraryDefinitionObjectKind",
    DATASET_FAMILY_PROFILES: "LibraryDefinitionFamilyProfile",
    DATASET_VARIANT_PROFILES: "LibraryDefinitionVariantProfile",
    DATASET_PROFILE_BINDINGS: "LibraryDefinitionProfileBinding",
}


def model_class_for_dataset(dataset_key: Any) -> type[Any]:
    """Gibt die Modelklasse für einen Dataset-Key zurück."""
    key = clean_dataset_key(dataset_key)
    name = MODEL_BY_DATASET_KEY.get(key)

    if not name:
        raise ValueError(f"Unknown library definition dataset: {dataset_key!r}")

    model = globals().get(name)
    if model is None:
        raise RuntimeError(f"Model class {name!r} is not loaded.")

    return model


def create_definition_model_from_item(
    dataset_key: Any,
    item: Mapping[str, Any],
    *,
    dataset: LibraryDefinitionDataset | None = None,
    source_scope: Any = LibraryDefinitionSourceScope.SYSTEM.value,
    owner_user_id: Any = None,
    created_by_user_id: Any = None,
) -> Any:
    """Erstellt ein konkretes Definition-Model aus dataset_key + item."""
    model = model_class_for_dataset(dataset_key)
    creator = getattr(model, "create_from_item", None)

    if not callable(creator):
        raise RuntimeError(f"Model for dataset {dataset_key!r} does not expose create_from_item().")

    return creator(
        item,
        dataset=dataset,
        source_scope=source_scope,
        owner_user_id=owner_user_id,
        created_by_user_id=created_by_user_id,
    )


# ---------------------------------------------------------------------------
# Public model helpers
# ---------------------------------------------------------------------------

def iter_library_definition_models() -> tuple[type[Any], ...]:
    """Gibt alle echten Modelklassen dieser Datei zurück."""
    return (
        LibraryDefinitionDataset,
        LibraryDefinitionSeedRun,
        LibraryDefinitionVariable,
        LibraryDefinitionUnit,
        LibraryDefinitionMaterial,
        LibraryDefinitionDocumentType,
        LibraryDefinitionObjectKind,
        LibraryDefinitionFamilyProfile,
        LibraryDefinitionVariantProfile,
        LibraryDefinitionProfileBinding,
        LibraryDefinitionOverride,
    )


def iter_models() -> tuple[type[Any], ...]:
    """Kompatibler Alias für models.__init__.py."""
    return iter_library_definition_models()


def get_models() -> tuple[type[Any], ...]:
    """Kompatibler Alias für Modelle-Discovery."""
    return iter_library_definition_models()


def get_library_definition_model_names() -> tuple[str, ...]:
    """Gibt alle Modelklassennamen zurück."""
    return tuple(model.__name__ for model in iter_library_definition_models())


def get_library_definition_table_names() -> tuple[str, ...]:
    """Gibt alle Tabellennamen zurück."""
    return tuple(str(getattr(model, "__tablename__", "")) for model in iter_library_definition_models())


def get_library_definition_models_health() -> dict[str, Any]:
    """JSON-kompatibler Health-Snapshot dieser Model-Datei."""
    model_names = get_library_definition_model_names()
    table_names = get_library_definition_table_names()

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
            "schema_version": LIBRARY_DEFINITIONS_MODELS_SCHEMA_VERSION,
            "healthy": healthy,
            "ok": healthy,
            "model_count": len(model_names),
            "table_count": len(table_names),
            "model_names": list(model_names),
            "table_names": list(table_names),
            "metadata_table_count": len(metadata_table_names),
            "metadata_table_names": list(metadata_table_names),
            "missing_tables": missing_tables,
            "dataset_keys": list(LIBRARY_DEFINITION_DATASET_KEYS),
            "supports_variables": True,
            "supports_units": True,
            "supports_materials": True,
            "supports_document_types": True,
            "supports_object_kinds": True,
            "supports_family_profiles": True,
            "supports_variant_profiles": True,
            "supports_profile_bindings": True,
            "supports_user_overrides": True,
        }
    except Exception as exc:
        return {
            "schema_version": LIBRARY_DEFINITIONS_MODELS_SCHEMA_VERSION,
            "healthy": False,
            "ok": False,
            "model_count": len(model_names),
            "table_count": len(table_names),
            "model_names": list(model_names),
            "table_names": list(table_names),
            "error": f"{type(exc).__name__}: {exc}",
        }


def assert_library_definition_models_ready() -> None:
    """Wirft RuntimeError, wenn die Definitions-Models nicht bereit sind."""
    health = get_library_definition_models_health()

    if health.get("healthy"):
        return

    raise RuntimeError(f"Library definition models are not ready: {health}")


def clear_library_definition_model_caches() -> dict[str, Any]:
    """Leert interne Caches dieser Datei."""
    try:
        _load_db.cache_clear()
    except Exception:
        pass

    return {
        "ok": True,
        "cleared": ["_load_db"],
    }


# ---------------------------------------------------------------------------
# Public exports
# ---------------------------------------------------------------------------

__all__ = [
    # Metadata / constants
    "LIBRARY_DEFINITIONS_MODELS_SCHEMA_VERSION",
    "DEFAULT_DEFINITIONS_VERSION",
    "DEFAULT_SCHEMA_VERSION",
    "DEFAULT_USER_ID",
    "DATASET_VARIABLES",
    "DATASET_UNITS",
    "DATASET_MATERIALS",
    "DATASET_DOCUMENT_TYPES",
    "DATASET_OBJECT_KINDS",
    "DATASET_FAMILY_PROFILES",
    "DATASET_VARIANT_PROFILES",
    "DATASET_PROFILE_BINDINGS",
    "LIBRARY_DEFINITION_DATASET_KEYS",
    "MODEL_BY_DATASET_KEY",

    # Enums
    "LibraryDefinitionSourceScope",
    "LibraryDefinitionStatus",
    "LibraryDefinitionSeedStatus",
    "LibraryDefinitionOverrideAction",
    "LibraryDefinitionValueType",

    # Models
    "LibraryDefinitionDataset",
    "LibraryDefinitionSeedRun",
    "LibraryDefinitionVariable",
    "LibraryDefinitionUnit",
    "LibraryDefinitionMaterial",
    "LibraryDefinitionDocumentType",
    "LibraryDefinitionObjectKind",
    "LibraryDefinitionFamilyProfile",
    "LibraryDefinitionVariantProfile",
    "LibraryDefinitionProfileBinding",
    "LibraryDefinitionOverride",

    # Helpers
    "utc_now",
    "new_uid",
    "enum_value",
    "first_non_empty",
    "clean_string",
    "normalize_optional_string",
    "normalize_required_string",
    "normalize_key",
    "normalize_slug",
    "normalize_bool",
    "normalize_int",
    "normalize_float",
    "normalize_user_id",
    "normalize_source_scope",
    "owner_scope_for",
    "normalize_status",
    "normalize_json_mapping",
    "normalize_json_list",
    "normalize_json_value",
    "merge_json",
    "stable_json_hash",
    "item_list_from_payload",
    "definition_key_from_item",
    "clean_dataset_key",
    "list_contains",
    "apply_common_definition_fields",
    "model_class_for_dataset",
    "create_definition_model_from_item",

    # Model discovery / health
    "iter_library_definition_models",
    "iter_models",
    "get_models",
    "get_library_definition_model_names",
    "get_library_definition_table_names",
    "get_library_definition_models_health",
    "assert_library_definition_models_ready",
    "clear_library_definition_model_caches",
]